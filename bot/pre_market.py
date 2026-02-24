"""
장전 준비 모듈 — 매일 KST 22:00 (US 장 시작 전) 실행.

1. 토큰 갱신 (KIS OAuth)
2. 워치리스트 + 보유종목 가격 데이터 갱신
3. ATR(N) / Donchian Channel 계산
4. 진입/피라미드/손절 트리거 가격 사전 계산
5. 시장 필터 (SPY > 200 SMA) 판단
"""

from __future__ import annotations

from datetime import datetime, timezone

import structlog

from broker.account import AccountManager
from broker.kis_auth import KISAuth
from broker.kis_rest import KISRestClient
from config.constants import LOOKBACK_DATA_DAYS, MARKET_BENCHMARK
from core.database import Database
from core.models import DonchianLevels, PrecomputedSignals
from data.price_cache import PriceCache
from portfolio.position_manager import PositionManager
from strategy.atr import calculate_n_from_ohlcv
from strategy.donchian import build_donchian_levels_model
from strategy.market_filter import get_market_filter_status
from strategy.pyramiding import calculate_pyramid_price
from strategy.stop_loss import calculate_stop_price

logger = structlog.get_logger(__name__)


# ════════════════════════════════════════════════════════════════
# Pre-Market Preparer
# ════════════════════════════════════════════════════════════════


class PreMarketPreparer:
    """매일 장 시작 전 실행되는 사전 준비 루틴.

    의존성을 주입받아 다음 작업을 순차적으로 수행한다:
    1. KIS OAuth 토큰 갱신
    2. 워치리스트 + 보유종목의 일봉 OHLCV 데이터 갱신
    3. ATR(N) 및 Donchian Channel 계산
    4. 진입/피라미딩/손절 트리거 가격 사전 산출
    5. 시장 방향 필터 (SPY > 200 SMA) 판단
    6. 보유 종목의 갭다운 선점 체크
    """

    def __init__(
        self,
        db: Database,
        auth: KISAuth,
        rest_client: KISRestClient,
        account_mgr: AccountManager,
        position_mgr: PositionManager,
    ) -> None:
        self._db = db
        self._auth = auth
        self._rest = rest_client
        self._account_mgr = account_mgr
        self._position_mgr = position_mgr
        self._price_cache = PriceCache(db)

    # ── Public API ───────────────────────────────────────────

    async def run(self) -> dict:
        """전체 장전 준비 루틴을 실행하고 요약 결과를 반환한다.

        Returns:
            요약 dict::

                {
                    "market_filter_pass": bool,
                    "watchlist_count": int,
                    "position_count": int,
                    "signals": list[PrecomputedSignals],
                    "gap_down_tickers": list[str],
                }
        """
        started_at = datetime.now(timezone.utc)
        logger.info("pre_market_started")

        # Step 1: 토큰 갱신
        await self._refresh_token()

        # Step 2: 가격 데이터 갱신
        watchlist_tickers, position_tickers = await self._update_price_data()

        # Step 3: 시그널 계산 (ATR, Donchian, 트리거 가격)
        all_tickers = list(set(watchlist_tickers + position_tickers))
        signals = await self._calculate_signals(
            all_tickers, position_tickers,
        )

        # Step 4: 시장 필터 판단
        market_status = await self._check_market_filter()
        market_filter_pass: bool = market_status["filter_pass"]

        # Step 5: 갭다운 사전 체크
        gap_down_tickers = await self._check_gap_down()

        elapsed = (datetime.now(timezone.utc) - started_at).total_seconds()
        summary = {
            "market_filter_pass": market_filter_pass,
            "watchlist_count": len(watchlist_tickers),
            "position_count": len(position_tickers),
            "signals": signals,
            "gap_down_tickers": gap_down_tickers,
        }

        logger.info(
            "pre_market_completed",
            elapsed_s=round(elapsed, 2),
            market_filter=market_filter_pass,
            watchlist=len(watchlist_tickers),
            positions=len(position_tickers),
            signals_count=len(signals),
            gap_down_count=len(gap_down_tickers),
        )

        return summary

    # ── Step 1: Token ────────────────────────────────────────

    async def _refresh_token(self) -> None:
        """KIS OAuth 토큰이 만료되었거나 임박하면 갱신한다."""
        try:
            await self._auth.ensure_token_valid()
            logger.info("pre_market_token_ok")
        except Exception:
            logger.exception("pre_market_token_refresh_failed")
            raise

    # ── Step 2: Price Data ───────────────────────────────────

    async def _update_price_data(self) -> tuple[list[str], list[str]]:
        """워치리스트 + 보유종목의 OHLCV 데이터를 갱신한다.

        Returns:
            (watchlist_tickers, position_tickers) 튜플.
        """
        # 워치리스트에서 ACTIVE 종목 조회
        cursor = await self._db.conn.execute(
            "SELECT ticker FROM watchlist WHERE status = 'ACTIVE'"
        )
        watchlist_rows = await cursor.fetchall()
        watchlist_tickers = [row[0] for row in watchlist_rows]

        # 보유종목 조회
        open_positions = await self._position_mgr.get_open_positions()
        position_tickers = [pos.ticker for pos in open_positions]

        # 합집합으로 갱신 대상 결정 (+ SPY for market filter)
        all_tickers = list(set(watchlist_tickers + position_tickers + [MARKET_BENCHMARK]))

        if not all_tickers:
            logger.info("pre_market_no_tickers_to_update")
            return watchlist_tickers, position_tickers

        # yfinance 일괄 다운로드로 최신 가격 갱신
        new_records = await self._price_cache.bulk_load_from_yfinance(
            all_tickers, period="5d",
        )

        logger.info(
            "pre_market_price_update_done",
            total_tickers=len(all_tickers),
            new_records=new_records,
        )

        return watchlist_tickers, position_tickers

    # ── Step 3: Signals ──────────────────────────────────────

    async def _calculate_signals(
        self,
        all_tickers: list[str],
        position_tickers: list[str],
    ) -> list[PrecomputedSignals]:
        """각 종목에 대해 ATR(N), Donchian 레벨, 트리거 가격을 계산한다.

        Args:
            all_tickers: 워치리스트 + 보유종목의 합집합.
            position_tickers: 현재 보유 종목 리스트.

        Returns:
            종목별 ``PrecomputedSignals`` 리스트.
        """
        signals: list[PrecomputedSignals] = []

        for ticker in all_tickers:
            try:
                sig = await self._compute_ticker_signal(
                    ticker, ticker in position_tickers,
                )
                if sig is not None:
                    signals.append(sig)
            except Exception:
                logger.exception(
                    "pre_market_signal_error", ticker=ticker,
                )

        logger.info(
            "pre_market_signals_computed",
            total=len(all_tickers),
            success=len(signals),
        )
        return signals

    async def _compute_ticker_signal(
        self,
        ticker: str,
        has_position: bool,
    ) -> PrecomputedSignals | None:
        """단일 종목의 사전 계산 시그널을 생성한다.

        Args:
            ticker: 종목 코드.
            has_position: 현재 보유 중인지 여부.

        Returns:
            ``PrecomputedSignals`` 인스턴스, 데이터 부족 시 ``None``.
        """
        bars = await self._price_cache.get_ohlcv(ticker, LOOKBACK_DATA_DAYS)

        if len(bars) < 56:
            # 최소 55일(S2 entry) + 1일(ATR prev_close) 필요
            logger.debug(
                "pre_market_insufficient_data",
                ticker=ticker,
                bars=len(bars),
            )
            return None

        # ATR(N) 계산
        n_value = calculate_n_from_ohlcv(bars)
        if n_value is None:
            return None

        # Donchian 채널 계산
        highs = [bar.high for bar in bars]
        lows = [bar.low for bar in bars]

        try:
            donchian = build_donchian_levels_model(ticker, highs, lows)
        except ValueError:
            logger.debug("pre_market_donchian_insufficient", ticker=ticker)
            return None

        # 트리거 가격 계산
        stop_price: float | None = None
        pyramid_price: float | None = None

        if has_position:
            position = await self._position_mgr.get_position(ticker)
            if position is not None:
                # 현재 스톱 가격 유지
                stop_price = position.current_stop_price

                # 피라미딩 가격: 마지막 유닛의 진입가 기준
                if position.units:
                    last_unit = position.units[-1]
                    pyramid_price = calculate_pyramid_price(
                        last_unit.entry_price, n_value,
                    )

        signal = PrecomputedSignals(
            ticker=ticker,
            n_value=n_value,
            donchian=donchian,
            s1_entry_price=donchian.upper_20,
            s2_entry_price=donchian.upper_55,
            stop_price=stop_price,
            pyramid_price=pyramid_price,
        )

        return signal

    # ── Step 4: Market Filter ────────────────────────────────

    async def _check_market_filter(self) -> dict:
        """SPY 종가와 200일 SMA를 비교하여 시장 필터를 판단한다.

        Returns:
            ``get_market_filter_status`` 결과 dict.
        """
        from data.market_data import MarketDataProvider

        market_data = MarketDataProvider(self._price_cache)
        status = await get_market_filter_status(market_data)

        logger.info(
            "pre_market_filter_result",
            benchmark=status["benchmark"],
            close=status["close"],
            sma200=status["sma200"],
            filter_pass=status["filter_pass"],
        )

        return status

    # ── Step 5: Gap-Down Check ───────────────────────────────

    async def _check_gap_down(self) -> list[str]:
        """보유 종목 중 갭다운 청산이 필요할 수 있는 종목을 사전 확인한다.

        장 시작 시 전일 종가 대비 스톱 가격 이하로 시초가가 형성될 경우,
        시장가로 즉시 매도해야 한다. 여기서는 사전 경고 목적으로
        전일 종가가 이미 스톱 근처에 있는 종목을 식별한다.

        Returns:
            갭다운 위험이 있는 종목 리스트.
        """
        gap_down_tickers: list[str] = []

        open_positions = await self._position_mgr.get_open_positions()

        for pos in open_positions:
            latest_close = await self._price_cache.get_latest_close(pos.ticker)
            if latest_close is None:
                continue

            stop = pos.current_stop_price
            if stop <= 0:
                continue

            # 전일 종가가 스톱의 102% 이내이면 갭다운 위험 경고
            gap_threshold = stop * 1.02
            if latest_close <= gap_threshold:
                gap_down_tickers.append(pos.ticker)
                logger.warning(
                    "pre_market_gap_down_risk",
                    ticker=pos.ticker,
                    latest_close=latest_close,
                    stop_price=stop,
                    gap_threshold=gap_threshold,
                )

        return gap_down_tickers
