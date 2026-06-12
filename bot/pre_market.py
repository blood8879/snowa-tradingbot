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
from zoneinfo import ZoneInfo

import structlog

from broker.account import AccountManager
from broker.kis_auth import KISAuth
from broker.kis_rest import KISRestClient
from config.constants import LOOKBACK_DATA_DAYS, MARKET_BENCHMARK, MARKET_MA_PERIOD
from config.market_config import get_market_config
from core.database import Database
from core.models import DonchianLevels, PrecomputedSignals
from data.price_cache import PriceCache
from portfolio.correlation_groups import CorrelationGroupManager
from portfolio.position_manager import PositionManager
from strategy.atr import calculate_n_from_ohlcv
from strategy.breakout_tracker import BreakoutTracker
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
        correlation_mgr: CorrelationGroupManager | None = None,
    ) -> None:
        self._db = db
        self._auth = auth
        self._rest = rest_client
        self._account_mgr = account_mgr
        self._position_mgr = position_mgr
        self._correlation_mgr = correlation_mgr
        self._price_cache = PriceCache(db)
        self._breakout_tracker = BreakoutTracker(db)

    # ── Public API ───────────────────────────────────────────

    async def run(self, market: str = "US") -> dict:
        """전체 장전 준비 루틴을 실행하고 요약 결과를 반환한다.

        Args:
            market: 시장 ID ("US" or "KR"). 기본값은 "US".

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
        logger.info("pre_market_started", market=market)

        # Step 1: 토큰 갱신
        await self._refresh_token()

        # Step 2: 가격 데이터 갱신
        watchlist_tickers, position_tickers = await self._update_price_data(market)

        # Step 2.5: 상관 그룹(섹터/업종) 등록 — 6/10유닛 한도 데이터 공급
        await self._register_correlation_groups(market)

        # Step 3: 시그널 계산 (ATR, Donchian, 트리거 가격)
        all_tickers = list(set(watchlist_tickers + position_tickers))
        signals = await self._calculate_signals(
            all_tickers, position_tickers, market,
        )

        # Step 4: 시장 필터 판단 (3-tier regime)
        market_status = await self._check_market_filter(market)
        market_filter_pass: bool = market_status["filter_pass"]
        market_regime: str = market_status.get("regime", "GREEN")
        market_regime_scale: float = market_status.get("regime_scale", 1.0)

        # Step 5: 갭다운 사전 체크
        gap_down_tickers = await self._check_gap_down(market)

        elapsed = (datetime.now(timezone.utc) - started_at).total_seconds()
        summary = {
            "market_filter_pass": market_filter_pass,
            "market_regime": market_regime,
            "market_regime_scale": market_regime_scale,
            "watchlist_count": len(watchlist_tickers),
            "position_count": len(position_tickers),
            "signals": signals,
            "gap_down_tickers": gap_down_tickers,
        }

        logger.info(
            "pre_market_completed",
            market=market,
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

    async def _update_price_data(self, market: str) -> tuple[list[str], list[str]]:
        """워치리스트 + 보유종목의 OHLCV 데이터를 갱신한다.

        Args:
            market: 시장 ID ("US" or "KR").

        Returns:
            (watchlist_tickers, position_tickers) 튜플.
        """
        # 워치리스트에서 ACTIVE 종목 조회 (market 필터 적용)
        cursor = await self._db.conn.execute(
            "SELECT ticker FROM watchlist WHERE status = 'ACTIVE' AND market = ?",
            (market,),
        )
        watchlist_rows = await cursor.fetchall()
        watchlist_tickers = [row[0] for row in watchlist_rows]

        # 보유종목 조회 (해당 시장만)
        open_positions = await self._position_mgr.get_open_positions()
        position_tickers = [pos.ticker for pos in open_positions if pos.market == market]

        # 시장별 벤치마크 티커 가져오기
        market_cfg = get_market_config(market)
        benchmark_ticker = market_cfg.benchmark_ticker

        # 합집합으로 갱신 대상 결정 (+ benchmark for market filter)
        all_tickers = list(set(watchlist_tickers + position_tickers + [benchmark_ticker]))

        if not all_tickers:
            logger.info("pre_market_no_tickers_to_update", market=market)
            return watchlist_tickers, position_tickers

        # 벤치마크 히스토리 부족 시 자동 채움 (SMA200 계산에 200일 필요)
        await self._ensure_benchmark_history(benchmark_ticker, market)

        # KR 시장: pykrx로 최근 가격 갱신
        if market == "KR":
            try:
                new_records = await self._price_cache.bulk_load_from_pykrx(
                    all_tickers, days=10,
                )
                logger.info(
                    "pre_market_price_update_done",
                    market=market,
                    total_tickers=len(all_tickers),
                    new_records=new_records,
                )
            except Exception:
                logger.exception("pre_market_kr_price_update_error", market=market)
            return watchlist_tickers, position_tickers

        # yfinance 일괄 다운로드로 최신 가격 갱신 (US 시장)
        new_records = await self._price_cache.bulk_load_from_yfinance(
            all_tickers, period="5d",
        )

        logger.info(
            "pre_market_price_update_done",
            market=market,
            total_tickers=len(all_tickers),
            new_records=new_records,
        )

        return watchlist_tickers, position_tickers

    async def _ensure_benchmark_history(
        self, benchmark: str, market: str,
    ) -> None:
        """벤치마크 가격 히스토리가 SMA200 계산에 충분한지 확인하고, 부족하면 채운다."""
        count = await self._price_cache.count_records(benchmark)
        if count >= MARKET_MA_PERIOD:
            return

        logger.warning(
            "pre_market_benchmark_history_insufficient",
            benchmark=benchmark,
            market=market,
            current_count=count,
            required=MARKET_MA_PERIOD,
        )

        try:
            if market == "KR":
                new = await self._price_cache.bulk_load_from_pykrx(
                    [benchmark], days=MARKET_MA_PERIOD + 50,
                )
            else:
                new = await self._price_cache.bulk_load_from_yfinance(
                    [benchmark], period="15mo",
                )
            logger.info(
                "pre_market_benchmark_history_filled",
                benchmark=benchmark,
                market=market,
                new_records=new,
            )
        except Exception:
            logger.exception(
                "pre_market_benchmark_history_fill_error",
                benchmark=benchmark,
                market=market,
            )

    # ── Step 2.5: Correlation Groups ─────────────────────────

    async def _register_correlation_groups(self, market: str) -> None:
        """워치리스트/보유종목의 섹터·업종을 CorrelationGroupManager에 등록한다.

        등록이 없으면 상관 한도(업종 6유닛 / 섹터 10유닛) 체크가
        항상 0으로 계산되어 무력화되므로, 매 장전마다 갱신한다.
        분류가 없는 종목은 종목별 고유 placeholder를 부여해
        '미분류' 그룹으로 잘못 묶이는 것을 방지한다.
        """
        if self._correlation_mgr is None:
            return

        registered = 0
        try:
            for query in (
                "SELECT ticker, sector, industry FROM watchlist",
                "SELECT ticker, sector, industry FROM positions WHERE status = 'OPEN'",
            ):
                cursor = await self._db.conn.execute(query)
                rows = await cursor.fetchall()
                for ticker, sector, industry in rows:
                    self._correlation_mgr.set_stock_info(
                        ticker,
                        sector or f"_unknown_sector_{ticker}",
                        industry or f"_unknown_industry_{ticker}",
                    )
                    registered += 1
            logger.info(
                "pre_market_correlation_registered",
                market=market,
                count=registered,
            )
        except Exception:
            logger.exception("pre_market_correlation_register_error", market=market)

    # ── Breakout History (System 1 Filter) ───────────────────

    async def _update_breakout_history(self, ticker: str, bars: list) -> None:
        """S1 돌파 이력 갱신 — System 1 필터 데이터 공급 (명세 §5.1).

        실제 진입 여부와 무관하게 완성 일봉 종가 기준으로 20일 돌파를
        기록하고, 가상 포지션의 10일 저가 청산을 일봉 단위로 추적하여
        수익/손실(would_have_been_winner)을 판정한다.
        """
        if len(bars) < 22:
            return

        open_bo = await self._breakout_tracker.get_open_breakout(ticker)

        if open_bo is not None:
            # 미해결 돌파: 돌파일 이후 일봉을 순회하며 10일 저가 이탈(가상 청산) 확인
            bo_date = (open_bo.get("breakout_date") or "")[:10]
            for i in range(11, len(bars)):
                bar = bars[i]
                if bar.date <= bo_date:
                    continue
                lower_10 = min(b.low for b in bars[i - 10:i])
                if bar.close < lower_10:
                    winner = await self._breakout_tracker.evaluate_hypothetical(
                        ticker,
                        open_bo["breakout_price"],
                        bar.close,
                        lower_10,
                    )
                    await self._breakout_tracker.update_breakout_outcome(
                        open_bo["id"],
                        bool(winner),
                        lower_10,
                        bar.date,
                    )
                    break
            # 미해결 돌파가 있는 동안에는 새 돌파를 기록하지 않는다
            return

        # 새 S1 돌파 탐지: 마지막 완성 일봉 종가 > 직전 20일 최고가
        last = bars[-1]
        prior_upper_20 = max(b.high for b in bars[-21:-1])
        if last.close > prior_upper_20:
            await self._breakout_tracker.record_breakout(
                ticker,
                "S1",
                breakout_price=prior_upper_20,
                was_entered=False,
                breakout_date=last.date,
            )

    # ── Step 3: Signals ──────────────────────────────────────

    async def _calculate_signals(
        self,
        all_tickers: list[str],
        position_tickers: list[str],
        market: str,
    ) -> list[PrecomputedSignals]:
        """각 종목에 대해 ATR(N), Donchian 레벨, 트리거 가격을 계산한다.

        Args:
            all_tickers: 워치리스트 + 보유종목의 합집합.
            position_tickers: 현재 보유 종목 리스트.
            market: 시장 ID ("US" or "KR").

        Returns:
            종목별 ``PrecomputedSignals`` 리스트.
        """
        signals: list[PrecomputedSignals] = []

        for ticker in all_tickers:
            try:
                sig = await self._compute_ticker_signal(
                    ticker, ticker in position_tickers, market,
                )
                if sig is not None:
                    signals.append(sig)
            except Exception:
                logger.exception(
                    "pre_market_signal_error", ticker=ticker, market=market,
                )

        logger.info(
            "pre_market_signals_computed",
            market=market,
            total=len(all_tickers),
            success=len(signals),
        )
        return signals

    def _exclude_incomplete_current_bar(self, bars: list, market: str, ticker: str) -> list:
        """Remove the current market day's unfinished daily bar before signal math."""
        if not bars:
            return bars

        if market == "US":
            now_local = datetime.now(ZoneInfo("America/New_York"))
            close_minutes = 16 * 60
        else:
            now_local = datetime.now(ZoneInfo("Asia/Seoul"))
            mkt_cfg = get_market_config("KR")
            close_minutes = mkt_cfg.market_close_hour * 60 + mkt_cfg.market_close_minute

        latest_date = getattr(bars[-1], "date", None)
        current_date = now_local.date().isoformat()
        now_minutes = now_local.hour * 60 + now_local.minute

        if latest_date == current_date and now_minutes <= close_minutes:
            logger.info(
                "pre_market_excluding_incomplete_bar",
                ticker=ticker,
                market=market,
                date=latest_date,
            )
            return bars[:-1]

        return bars

    async def _compute_ticker_signal(
        self,
        ticker: str,
        has_position: bool,
        market: str,
    ) -> PrecomputedSignals | None:
        """단일 종목의 사전 계산 시그널을 생성한다.

        Args:
            ticker: 종목 코드.
            has_position: 현재 보유 중인지 여부.
            market: 시장 ID ("US" or "KR").

        Returns:
            ``PrecomputedSignals`` 인스턴스, 데이터 부족 시 ``None``.
        """
        bars = await self._price_cache.get_ohlcv(ticker, LOOKBACK_DATA_DAYS)
        bars = self._exclude_incomplete_current_bar(bars, market, ticker)

        if len(bars) < 56:
            # 최소 55일(S2 entry) + 1일(ATR prev_close) 필요
            logger.debug(
                "pre_market_insufficient_data",
                ticker=ticker,
                market=market,
                bars=len(bars),
            )
            return None

        # S1 돌파 이력 갱신 (System 1 필터 — 실패해도 시그널 계산은 계속)
        try:
            await self._update_breakout_history(ticker, bars)
        except Exception:
            logger.exception("pre_market_breakout_history_error", ticker=ticker)

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
            logger.debug("pre_market_donchian_insufficient", ticker=ticker, market=market)
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

    async def _check_market_filter(self, market: str) -> dict:
        """벤치마크 종가와 200일 SMA를 비교하여 시장 필터를 판단한다.

        Args:
            market: 시장 ID ("US" or "KR").

        Returns:
            ``get_market_filter_status`` 결과 dict.
        """
        from data.market_data import MarketDataProvider

        market_data = MarketDataProvider(self._price_cache)
        status = await get_market_filter_status(market_data, market=market, db=self._db)

        logger.info(
            "pre_market_filter_result",
            market=market,
            benchmark=status["benchmark"],
            close=status["close"],
            sma200=status["sma200"],
            filter_pass=status["filter_pass"],
            regime=status.get("regime"),
            regime_scale=status.get("regime_scale"),
            breadth_pct=status.get("breadth_pct"),
            roc_125=status.get("roc_125"),
        )

        return status

    # ── Step 5: Gap-Down Check ───────────────────────────────

    async def _check_gap_down(self, market: str) -> list[str]:
        """보유 종목 중 갭다운 청산이 필요할 수 있는 종목을 사전 확인한다.

        장 시작 시 전일 종가 대비 스톱 가격 이하로 시초가가 형성될 경우,
        시장가로 즉시 매도해야 한다. 여기서는 사전 경고 목적으로
        전일 종가가 이미 스톱 근처에 있는 종목을 식별한다.

        Args:
            market: 시장 ID ("US" or "KR").

        Returns:
            갭다운 위험이 있는 종목 리스트.
        """
        gap_down_tickers: list[str] = []

        open_positions = await self._position_mgr.get_open_positions()

        for pos in open_positions:
            if pos.market != market:
                continue
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
                    market=market,
                    ticker=pos.ticker,
                    latest_close=latest_close,
                    stop_price=stop,
                    gap_threshold=gap_threshold,
                )

        return gap_down_tickers
