"""
장중 모니터링 엔진 — WebSocket 틱마다 신호 판단.

우선순위:
1. 손절 체크 (가장 긴급)
2. 피라미딩 체크
3. 신규 진입 체크
4. Donchian 청산 체크 (매 틱마다 실시간)
"""

from __future__ import annotations

import asyncio
import csv
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from pathlib import Path
import structlog

from broker.kis_rest import KISRestClient
from broker.order_executor import OrderExecutor
from config.market_config import get_market_config
from core.database import Database
from core.events import EventBus
from core.models import (
    OrderStatus,
    OrderType,
    PrecomputedSignals,
    SignalType,
    TradeSignal,
)
from portfolio.correlation_groups import CorrelationGroupManager
from portfolio.position_manager import PositionManager
from portfolio.position_sizer import calculate_unit_shares
from portfolio.risk_manager import RiskManager
from strategy.breakout_tracker import BreakoutTracker
from strategy.entry_signals import check_entry_signals
from strategy.exit_signals import check_donchian_exit, should_check_donchian_exit
from strategy.pyramiding import check_pyramid_signal
from strategy.stop_loss import check_stop_hit, update_stop_on_pyramid
from bot.journal_context import (
    build_entry_context,
    build_exit_context,
    build_pyramid_context,
    build_stop_loss_context,
)

logger = structlog.get_logger(__name__)


# ════════════════════════════════════════════════════════════════
# Intraday Monitor
# ════════════════════════════════════════════════════════════════


class IntradayMonitor:
    """장중 실시간 가격 모니터링 엔진.

    KISWebSocket 으로부터 틱 데이터를 수신하고, 우선순위에 따라
    손절 → 피라미딩 → 신규 진입 → Donchian 청산을 판단한다.

    Attributes:
        precomputed_signals: 장전에 계산된 종목별 시그널 데이터.
        market_filter_pass: SPY 200MA 필터 통과 여부.
    """

    # 잔고 캐시 TTL (초) — KIS API 초당 1건 제한 회피
    _BALANCE_CACHE_TTL: float = 30.0
    # 주기적 상태 로그 간격 (초)
    _STATUS_LOG_INTERVAL: float = 300.0

    def __init__(
        self,
        db: Database,
        event_bus: EventBus,
        rest_client: KISRestClient,
        order_executor: OrderExecutor,
        position_mgr: PositionManager,
        risk_mgr: RiskManager,
        correlation_mgr: CorrelationGroupManager,
        breakout_tracker: BreakoutTracker | None = None,
    ) -> None:
        self._db = db
        self._event_bus = event_bus
        self._rest = rest_client
        self._order_executor = order_executor
        self._position_mgr = position_mgr
        self._risk_mgr = risk_mgr
        self._correlation_mgr = correlation_mgr
        self._breakout_tracker = breakout_tracker or BreakoutTracker(db)

        self.precomputed_signals: dict[str, PrecomputedSignals] = {}
        self.market_filter_pass: bool = False
        self.market_regime_scale: float = 1.0  # GREEN=1.0, YELLOW=0.5, RED=0.0
        self._running: bool = False
        self._market: str = "US"  # Default to US market
        self._stock_names: dict[str, str] = {}  # ticker → 종목명

        # 잔고 캐시: KIS REST API rate-limit (1 req/sec) 회피
        self._cached_cash: float | None = None
        self._balance_cache_time: float = 0.0

        # 주기적 상태 로그용 카운터
        self._tick_count: int = 0
        self._last_status_log_time: float = 0.0
        self._last_market_closed_log_time: float = 0.0
        self._last_prices: dict[str, float] = {}

        # 피라미딩/진입/손절 실패 시 쿨다운 (ticker → monotonic time)
        self._pyramid_cooldown: dict[str, float] = {}
        self._entry_cooldown: dict[str, float] = {}
        self._stop_loss_cooldown: dict[str, float] = {}
        self._SIGNAL_COOLDOWN: float = 60.0  # 실패 후 60초 대기
        self._RISK_BLOCK_COOLDOWN: float = 600.0  # 리스크 차단 후 10분 대기 (포지션 변동 없으면 동일 결과)
        self._STOP_LOSS_COOLDOWN: float = 120.0  # 손절 실패 후 120초 대기

        # 오늘 진입 3회 실패 → 하루 종일 차단 (매 틱 DB 쿼리/로그 방지)
        self._entry_blocked_today: set[str] = set()

        # 잔고 부족 시 모든 진입을 일괄 차단 (5분)
        self._global_entry_block_until: float = 0.0
        self._GLOBAL_ENTRY_BLOCK_SEC: float = 300.0

    def set_market(self, market: str) -> None:
        """Set the market for this monitor (US or KR)."""
        self._market = market

    # ────────────────────────────────────────────────────────
    # Lifecycle
    # ────────────────────────────────────────────────────────

    async def _get_cached_cash(self) -> float | None:
        """Return cached available cash, refreshing from KIS API only when TTL expires.

        Uses get_purchasable_amount() (매수가능금액조회) as primary source,
        which reliably returns ord_psbl_frcr_amt for both paper and live accounts.
        Falls back to get_balance() summary if purchasable amount fails.

        실패 시에도 캐시 시간을 업데이트하여 rate limit 폭풍 방지 (negative cache).
        """
        now = time.monotonic()
        if (now - self._balance_cache_time) < self._BALANCE_CACHE_TTL:
            # TTL 내: 캐시값 반환 (None 포함 — negative cache)
            return self._cached_cash

        cash: float | None = None

        # Primary: get_purchasable_amount (works reliably for paper & live)
        try:
            if self._market == "KR":
                # KR API는 종목/가격 필수 → 시그널 종목 또는 삼성전자 사용
                kr_ticker = next(iter(self.precomputed_signals), "005930")
                psamount = await self._rest.get_purchasable_amount(
                    ticker=kr_ticker, exchange="", price="10000", market="KR",
                )
                cash = float(psamount.get("ord_psbl_cash", 0))
                # KR: API 성공 시 값을 신뢰 (0이어도 유효 — 실제 주문가능금액)
                self._cached_cash = cash
                self._balance_cache_time = now
                logger.info("balance_cache_refreshed", cash=cash, source="purchasable_amount", market=self._market)
                return cash
            else:
                # US market: include reusable sell proceeds while preserving cash fallback.
                psamount = await self._rest.get_purchasable_amount(market=self._market)
                cash = float(psamount.get("ord_psbl_frcr_amt", 0))
                if cash <= 0:
                    cash = float(psamount.get("frcr_ord_psbl_amt1", 0))
                cash += float(psamount.get("sll_ruse_psbl_amt") or 0)
                # US: API 성공 시 값을 신뢰 (0이어도 유효 — 전액 투자 중일 수 있음)
                self._cached_cash = cash
                self._balance_cache_time = now
                logger.info("balance_cache_refreshed", cash=cash, source="purchasable_amount", market=self._market)
                return cash
        except Exception:
            logger.warning("purchasable_amount_fetch_failed", market=self._market, exc_info=True)

        # API 간 rate limit 회피 — 1초 대기
        await asyncio.sleep(1.0)

        # Fallback: get_balance summary (US only)
        # KR은 위 primary에서 확정 반환 — get_balance의 dnca_tot_amt/nass_amt는
        # 포지션 투입분을 반영 못해 부정확하므로 KR fallback으로 사용 불가
        if self._market != "KR":
            try:
                account_info = await self._rest.get_balance(market=self._market)
                summary = account_info.get("summary", {}) if isinstance(account_info, dict) else {}
                # US market: frcr_ord_psbl_amt1
                cash = float(summary.get("frcr_ord_psbl_amt1", 0))
                if cash > 0:
                    self._cached_cash = cash
                    self._balance_cache_time = now
                    logger.info("balance_cache_refreshed", cash=cash, source="balance_summary", market=self._market)
                    return cash
            except Exception:
                logger.warning("balance_fetch_failed", market=self._market, exc_info=True)

        # Last resort: use stale cache
        if self._cached_cash is not None:
            logger.info("balance_using_stale_cache", cash=self._cached_cash, market=self._market)
            self._balance_cache_time = now  # stale 캐시도 TTL 갱신
            return self._cached_cash

        # 모든 소스 실패 → negative cache (TTL 동안 재시도 방지)
        self._balance_cache_time = now
        logger.error("balance_all_sources_failed", market=self._market)
        return None

    def invalidate_balance_cache(self) -> None:
        """Force next balance call to hit the API (e.g., after order submission)."""
        self._cached_cash = None
        self._balance_cache_time = 0.0

    def _name(self, ticker: str) -> str:
        """종목명 조회 (없으면 빈 문자열)."""
        return self._stock_names.get(ticker, "")

    def _load_stock_names(self) -> None:
        """KR 종목명 CSV 로드."""
        if self._market != "KR":
            return
        cache_path = Path("data/universe_kr_cache.csv")
        if not cache_path.exists():
            return
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    self._stock_names[row["ticker"]] = row["name"]
        except Exception:
            pass

    def _is_regular_market_open(self) -> bool:
        """Return True only during the market's regular trading session."""
        if self._market == "KR":
            now_local = datetime.now(ZoneInfo("Asia/Seoul"))
            open_minutes = 9 * 60
            close_minutes = 15 * 60 + 30
        else:
            now_local = datetime.now(ZoneInfo("America/New_York"))
            open_minutes = 9 * 60 + 30
            close_minutes = 16 * 60

        if now_local.weekday() > 4:
            return False

        now_minutes = now_local.hour * 60 + now_local.minute
        return open_minutes <= now_minutes < close_minutes

    async def start(self) -> None:
        self._load_stock_names()
        self._running = True
        logger.info(
            "intraday_monitor_started",
            watchlist_count=len(self.precomputed_signals),
            market_filter=self.market_filter_pass,
        )

    async def stop(self) -> None:
        """모니터링 중지."""
        self._running = False
        logger.info("intraday_monitor_stopped")

    # ────────────────────────────────────────────────────────
    # Main Callback (for KISWebSocket)
    # ────────────────────────────────────────────────────────

    async def on_price_update(
        self,
        ticker: str,
        price: float,
        timestamp: float,
    ) -> None:
        """WebSocket 틱 수신 시 호출되는 메인 콜백.

        우선순위 기반으로 신호를 판단한다:
          1. 보유 종목 → 손절 체크 (가장 긴급)
          2. 보유 종목 → 피라미딩 체크
          3. 워치리스트 & 마켓필터 통과 & 미보유 → 신규 진입 체크
          4. 보유 종목 → Donchian 청산 체크 (매 틱마다 실시간)

        Args:
            ticker: 종목 코드.
            price: 현재 체결가.
            timestamp: 틱 수신 시각 (Unix timestamp).
        """
        if not self._running:
            return

        # 틱 카운터 & 주기적 상태 로그 (5분마다)
        self._tick_count += 1
        self._last_prices[ticker] = price
        now_mono = time.monotonic()
        if now_mono - self._last_status_log_time >= self._STATUS_LOG_INTERVAL:
            self._last_status_log_time = now_mono
            logger.info(
                "intraday_status_heartbeat",
                tick_count=self._tick_count,
                unique_tickers=len(self._last_prices),
                latest_prices=dict(sorted(self._last_prices.items())[:5]),
                signals_count=len(self.precomputed_signals),
            )

        if not self._is_regular_market_open():
            if now_mono - self._last_market_closed_log_time >= self._STATUS_LOG_INTERVAL:
                self._last_market_closed_log_time = now_mono
                logger.info("intraday_trading_skipped_market_closed", market=self._market)
            return

        # 사전 계산 데이터 & 포지션 조회
        signals = self.precomputed_signals.get(ticker)
        position = await self._position_mgr.get_position(ticker)

        # signals 없고 포지션도 없으면 무시 (워치리스트 외 종목)
        if signals is None and position is None:
            return

        # ── Priority 1: 손절 체크 (signals 불필요) ──
        if position is not None:
            stop_hit = check_stop_hit(price, position.current_stop_price)
            if stop_hit:
                # 쿨다운 체크: 이전 손절 실패 후 120초 대기 (API 폭풍 방지)
                cd = self._stop_loss_cooldown.get(ticker, 0.0)
                if now_mono - cd >= self._STOP_LOSS_COOLDOWN:
                    await self._execute_stop_loss(ticker, price, position, timestamp)
                    return
                # 쿨다운 중이면 손절 skip하되, Donchian 청산은 계속 체크
                # (아래 Priority 4로 fall-through)

        # signals 없으면 피라미딩/진입/Donchian 계산 불가 → 손절만 처리 후 종료
        if signals is None:
            return

        # ── Priority 2: 피라미딩 체크 ──
        if position is not None and position.can_add_unit:
            # 스크리닝 탈락 종목은 피라미딩 차단
            wl_cursor = await self._db.conn.execute(
                "SELECT status FROM watchlist WHERE ticker = ?", (ticker,)
            )
            wl_row = await wl_cursor.fetchone()
            if wl_row and wl_row[0] != "ACTIVE":
                pass  # 스크리닝 탈락 → 피라미딩 스킵, Priority 3/4로 진행
            else:
                # 쿨다운 체크: 이전 시도 실패 후 60초 대기
                cd = self._pyramid_cooldown.get(ticker, 0.0)
                if not (now_mono - cd < self._SIGNAL_COOLDOWN):
                    if not await self._db.has_submitted_order(ticker, "SELL"):
                        last_unit = position.units[-1] if position.units else None
                        if last_unit is not None:
                            pyramid_result = check_pyramid_signal(
                                current_price=price,
                                last_entry_price=last_unit.entry_price,
                                n_value=signals.n_value,
                                current_units=position.unit_count,
                            )
                            if pyramid_result["add"]:
                                await self._execute_pyramid(
                                    ticker, price, position, signals, pyramid_result, timestamp,
                                )
                                return

        # ── Priority 3: 신규 진입 체크 ──
        if position is None and self.market_filter_pass:
            # 쿨다운 체크: 이전 시도 실패 후 60초 대기
            cd = self._entry_cooldown.get(ticker, 0.0)
            if not (now_mono - cd < self._SIGNAL_COOLDOWN):
                # 이전 S1 돌파 결과 조회 (System 1 필터)
                last_s1_winner = await self._breakout_tracker.was_last_breakout_winner(ticker)

                donchian_levels: dict[str, float | None] = {
                    "upper_20": signals.donchian.upper_20,
                    "upper_55": signals.donchian.upper_55,
                }
                entry_signals = check_entry_signals(
                    current_price=price,
                    donchian_levels=donchian_levels,
                    last_s1_breakout_winner=last_s1_winner,
                    market_filter_pass=self.market_filter_pass,
                )
                if entry_signals:
                    await self._execute_entry(
                        ticker, price, signals, entry_signals[0], timestamp,
                    )
                    return

        # ── Priority 4: Donchian 청산 체크 (매 틱마다) ──
        if position is not None:
            await self._execute_donchian_exit(
                ticker, price, position, signals, timestamp,
            )

    # ────────────────────────────────────────────────────────
    # Execution: Stop-Loss
    # ────────────────────────────────────────────────────────

    def _is_close_imminent(self, buffer_minutes: int = 5) -> bool:
        """장 마감이 buffer_minutes 이내인지 확인.

        장 마감 직전(또는 이후)엔 주문이 거부될 가능성이 높으므로,
        stop-loss 주문 submit 대신 force_exit 플래그를 세워 다음 세션으로 연기한다.
        """
        mkt_cfg = get_market_config(self._market)
        if self._market == "KR":
            now_local = datetime.now(ZoneInfo("Asia/Seoul"))
        else:
            now_local = datetime.now(ZoneInfo("America/New_York"))
            # US config는 KST 기준이므로 ET로 환산
            # market_close_hour=6 (KST) → 16:00 ET (DST) / 17:00 ET (STD)
            # 간단히 ET 기준 16:00 - buffer 로 체크
            close_minutes = 16 * 60
            now_minutes = now_local.hour * 60 + now_local.minute
            return now_minutes >= (close_minutes - buffer_minutes)
        close_minutes = mkt_cfg.market_close_hour * 60 + mkt_cfg.market_close_minute
        now_minutes = now_local.hour * 60 + now_local.minute
        return now_minutes >= (close_minutes - buffer_minutes)

    async def _execute_stop_loss(
        self,
        ticker: str,
        price: float,
        position: object,
        timestamp: float,
    ) -> None:
        """손절 매도 실행.

        Args:
            ticker: 종목 코드.
            price: 현재가 (손절 트리거 가격).
            position: 현재 포지션 객체.
            timestamp: 이벤트 시각.
        """
        if await self._db.has_submitted_order(ticker, "SELL", "STOP_LOSS"):
            logger.debug("stop_loss_skipped_pending_order", ticker=ticker)
            return

        # Layer 1: 장 마감 임박 시 주문 submit 대신 force_exit 플래그로 다음 세션 강제 청산
        if self._is_close_imminent():
            await self._db.set_force_exit_flag(
                ticker=ticker,
                flag="MARKET_CLOSED",
                reason=f"stop triggered near close (price={price}, stop={getattr(position, 'current_stop_price', 0)})",
            )
            logger.warning(
                "stop_loss_deferred_near_close",
                ticker=ticker,
                price=price,
                market=self._market,
                msg="장 마감 임박 → 주문 skip, 다음 세션 강제 청산 예약",
            )
            return

        logger.warning(
            "stop_loss_triggered",
            ticker=ticker,
            name=self._name(ticker),
            price=price,
            stop_price=position.current_stop_price,  # type: ignore[attr-defined]
            total_shares=position.total_shares,  # type: ignore[attr-defined]
        )

        journal_notes = build_stop_loss_context(
            stop_price=position.current_stop_price,  # type: ignore[attr-defined]
            trigger_price=price,
            avg_entry_price=position.avg_entry_price,  # type: ignore[attr-defined]
            atr_at_entry=position.n_at_entry,  # type: ignore[attr-defined]
            units_held=len(position.units) if hasattr(position, 'units') and position.units else 0,  # type: ignore[attr-defined]
            total_shares=position.total_shares,  # type: ignore[attr-defined]
        )

        order = await self._order_executor.execute_stop_loss_sell(
            ticker=ticker,
            exchange=await self._resolve_exchange(ticker),
            current_price=price,
            shares=position.total_shares,  # type: ignore[attr-defined]
            notes=journal_notes,
            market=self._market,
        )
        self.invalidate_balance_cache()

        # 손절 주문 실패 시 처리
        if order.status.value == "FAILED":
            # NO_BROKER_BALANCE: 브로커에 잔고 없음 = 이전 주문이 이미 체결됨
            # 로컬 포지션을 강제 청산하여 무한 재시도 루프 방지
            if order.notes and "NO_BROKER_BALANCE" in order.notes:
                logger.warning(
                    "force_close_no_broker_balance",
                    ticker=ticker,
                    price=price,
                    msg="브로커 잔고 없음 → 이전 매도가 이미 체결된 것으로 간주, 로컬 포지션 강제 청산",
                )
                if hasattr(position, 'id') and position.id is not None:
                    await self._position_mgr.close_position(
                        position_id=position.id,
                        reason="STOP_LOSS_BROKER_CONFIRMED",
                        exit_price=price,
                    )
                return

            self._stop_loss_cooldown[ticker] = time.monotonic()
            logger.warning(
                "stop_loss_cooldown_set",
                ticker=ticker,
                cooldown_seconds=self._STOP_LOSS_COOLDOWN,
            )

        signal = TradeSignal(
            signal_type=SignalType.STOP_LOSS_HIT,
            ticker=ticker,
            price=price,
            timestamp=datetime.fromtimestamp(timestamp, tz=timezone.utc),
            stop_price=position.current_stop_price,  # type: ignore[attr-defined]
            shares=position.total_shares,  # type: ignore[attr-defined]
        )
        await self._event_bus.emit(signal)

    # ────────────────────────────────────────────────────────
    # Execution: Pyramiding
    # ────────────────────────────────────────────────────────

    async def _execute_pyramid(
        self,
        ticker: str,
        price: float,
        position: object,
        signals: PrecomputedSignals,
        pyramid_result: dict,
        timestamp: float,
    ) -> None:
        """피라미딩 추가 매수 실행.

        Args:
            ticker: 종목 코드.
            price: 현재가.
            position: 현재 포지션 객체.
            signals: 사전 계산 시그널.
            pyramid_result: check_pyramid_signal 결과.
            timestamp: 이벤트 시각.
        """
        if await self._db.has_submitted_order(ticker, "BUY", "PYRAMID"):
            logger.debug("pyramid_skipped_pending_order", ticker=ticker)
            return

        cash = await self._get_cached_cash()
        if cash is None:
            logger.error("pyramid_skipped_no_balance", ticker=ticker)
            self._pyramid_cooldown[ticker] = time.monotonic()
            return
        open_positions = await self._position_mgr.get_open_positions()
        # Bug #19 fix: 같은 시장의 포지션만 합산 (KRW/USD 혼합 방지)
        total_position_value = sum(p.total_cost for p in open_positions if p.market == self._market)
        account_equity = cash + total_position_value

        # 터틀 원칙: 모든 unit은 1차 진입 시 결정된 동일 shares를 사용한다.
        # 매번 재사이징하면 equity·가격·regime_scale 변동에 따라 unit별 수량이 달라진다.
        first_unit_shares = (
            position.units[0].shares  # type: ignore[attr-defined]
            if getattr(position, "units", None)
            else 0
        )
        if first_unit_shares < 1:
            logger.warning(
                "pyramid_skipped_no_first_unit_shares",
                ticker=ticker,
            )
            return
        shares = first_unit_shares

        # 현금 부족 사전 체크 — API 호출 낭비 방지
        required_cash = shares * price * 1.01  # 1% 버퍼
        if cash < required_cash:
            logger.info(
                "pyramid_skipped_insufficient_cash",
                ticker=ticker,
                cash=round(cash, 2),
                required=round(required_cash, 2),
            )
            self._pyramid_cooldown[ticker] = time.monotonic()
            return

        risk_check = await self._risk_mgr.can_add_unit(
            ticker=ticker,
            shares=shares,
            entry_price=price,
            account_equity=account_equity,
            market=self._market,
        )
        if not risk_check["allowed"]:
            logger.info(
                "pyramid_blocked_risk",
                ticker=ticker,
                violations=risk_check["violations"],
            )
            # 리스크 차단은 포지션 변동 전까지 동일 결과 → 10분 쿨다운
            self._pyramid_cooldown[ticker] = time.monotonic() + (self._RISK_BLOCK_COOLDOWN - self._SIGNAL_COOLDOWN)
            return

        # 스톱 갱신 계산
        new_stop = update_stop_on_pyramid(
            current_stop=position.current_stop_price,  # type: ignore[attr-defined]
            new_entry_price=price,
            n_value=signals.n_value,
        )

        # ── 매매일지 컨텍스트 ──
        _system = position.system.value if hasattr(position.system, "value") else str(position.system)  # type: ignore[attr-defined]
        _last_entry = position.units[-1].entry_price if position.units else price  # type: ignore[attr-defined]
        journal_notes = build_pyramid_context(
            system=_system,
            atr=signals.n_value,
            new_stop=new_stop,
            prev_stop=position.current_stop_price,  # type: ignore[attr-defined]
            unit_number=pyramid_result["next_unit_number"],
            account_equity=account_equity,
            shares=shares,
            entry_price=price,
            last_entry_price=_last_entry,
        )

        # 주문 실행
        order = await self._order_executor.execute_entry_buy(
            ticker=ticker,
            exchange=await self._resolve_exchange(ticker),
            current_price=price,
            shares=shares,
            order_type=OrderType.PYRAMID,
            notes=journal_notes,
            market=self._market,
        )
        self.invalidate_balance_cache()

        # 주문 실패 시 쿨다운 설정 후 중단
        if order.status == OrderStatus.FAILED:
            logger.warning(
                "pyramid_order_failed",
                ticker=ticker,
                name=self._name(ticker),
                shares=shares,
                price=price,
            )
            self._pyramid_cooldown[ticker] = time.monotonic()
            return

        logger.info(
            "pyramid_order_submitted",
            ticker=ticker,
            name=self._name(ticker),
            unit_number=pyramid_result["next_unit_number"],
            shares=shares,
            price=price,
            new_stop=new_stop,
        )

        # 이벤트 발행
        signal = TradeSignal(
            signal_type=SignalType.PYRAMID_ADD,
            ticker=ticker,
            price=price,
            timestamp=datetime.fromtimestamp(timestamp, tz=timezone.utc),
            shares=shares,
            unit_number=pyramid_result["next_unit_number"],
            n_value=signals.n_value,
            pyramid_entry_price=price,
            stop_price=new_stop,
        )
        await self._event_bus.emit(signal)

    # ────────────────────────────────────────────────────────
    # Execution: Entry
    # ────────────────────────────────────────────────────────

    async def _execute_entry(
        self,
        ticker: str,
        price: float,
        signals: PrecomputedSignals,
        entry_signal: dict,
        timestamp: float,
    ) -> None:
        """신규 진입 매수 실행.

        Args:
            ticker: 종목 코드.
            price: 현재가.
            signals: 사전 계산 시그널.
            entry_signal: check_entry_signals 에서 반환된 시그널 dict.
            timestamp: 이벤트 시각.
        """
        # 글로벌 진입 차단: 잔고 부족으로 모든 진입 일괄 차단 중
        if time.monotonic() < self._global_entry_block_until:
            return

        if await self._db.has_submitted_order(ticker, "BUY", "ENTRY"):
            logger.debug("entry_skipped_pending_order", ticker=ticker)
            return

        # 안전장치: 같은 종목에 오늘 FAILED 진입 주문이 3개 이상이면 차단
        # (fill check 실패로 반복 주문하는 루프 방지)
        if ticker in self._entry_blocked_today:
            return
        failed_count = await self._db.count_failed_entry_orders_today(ticker)
        if failed_count >= 3:
            self._entry_blocked_today.add(ticker)
            logger.warning(
                "entry_blocked_too_many_failures",
                ticker=ticker,
                name=self._name(ticker),
                failed_count=failed_count,
                msg="오늘 실패 주문 3회 초과 — 반복 진입 차단 (이후 로그 생략)",
            )
            return

        cash = await self._get_cached_cash()
        if cash is None:
            logger.error("entry_skipped_no_balance", ticker=ticker)
            self._entry_cooldown[ticker] = time.monotonic()
            return

        open_positions = await self._position_mgr.get_open_positions()
        # Bug #19 fix: 같은 시장의 포지션만 합산 (KRW/USD 혼합 방지)
        total_position_value = sum(p.total_cost for p in open_positions if p.market == self._market)
        account_equity = cash + total_position_value

        # 포지션 사이징 (YELLOW 레짐이면 account_equity 절반으로 축소 → 유닛 사이즈 절반)
        effective_equity = account_equity * self.market_regime_scale
        sizing = calculate_unit_shares(
            account_equity=effective_equity,
            entry_price=price,
            n_value=signals.n_value,
            market=self._market,
        )
        if sizing["skip"]:
            logger.info(
                "entry_skipped_sizing",
                ticker=ticker,
                reason=sizing.get("reason", "insufficient capital"),
                price=round(price, 4),
                n_value=round(signals.n_value, 4),
                cash=round(cash, 2),
                account_equity=round(account_equity, 2),
                effective_equity=round(effective_equity, 2),
                regime_scale=self.market_regime_scale,
            )
            self._entry_cooldown[ticker] = time.monotonic()
            return

        shares = sizing["shares"]

        # 현금 부족 사전 체크 — API 호출 낭비 방지
        required_cash = shares * price * 1.01  # 1% 버퍼
        if cash < required_cash:
            logger.info(
                "entry_skipped_insufficient_cash",
                ticker=ticker,
                name=self._name(ticker),
                cash=round(cash, 2),
                required=round(required_cash, 2),
            )
            self._entry_cooldown[ticker] = time.monotonic()
            return

        # 리스크 체크
        risk_check = await self._risk_mgr.can_enter_position(
            ticker=ticker,
            shares=shares,
            entry_price=price,
            account_equity=account_equity,
            market=self._market,
        )
        if not risk_check["allowed"]:
            logger.info(
                "entry_blocked_risk",
                ticker=ticker,
                violations=risk_check["violations"],
            )
            # 리스크 차단은 포지션 변동 전까지 동일 결과 → 10분 쿨다운
            self._entry_cooldown[ticker] = time.monotonic() + (self._RISK_BLOCK_COOLDOWN - self._SIGNAL_COOLDOWN)
            return

        # 포지션 정보 추출 (주문 및 매매일지에 공통 사용)
        stop_price = sizing["stop_price"]
        system = entry_signal.get("system", "S1")

        # ── 매매일지: RS Rating + 종합점수 DB 조회 ──
        rs_rating: float | None = None
        composite_score: float | None = None
        try:
            wl_cursor = await self._db.conn.execute(
                "SELECT rs_rating, custom_composite_score FROM watchlist WHERE ticker = ?",
                (ticker,),
            )
            wl_row = await wl_cursor.fetchone()
            if wl_row:
                rs_rating = wl_row[0]
                composite_score = wl_row[1]
        except Exception:
            pass  # 매매일지 컨텍스트는 best-effort

        journal_notes = build_entry_context(
            system=system,
            breakout_level=entry_signal.get("breakout_level"),
            atr=signals.n_value,
            stop_price=stop_price,
            market_filter=self.market_filter_pass,
            rs_rating=rs_rating,
            composite_score=composite_score,
            account_equity=account_equity,
            shares=shares,
            entry_price=price,
        )

        # 주문 실행
        exchange = await self._resolve_exchange(ticker)
        order = await self._order_executor.execute_entry_buy(
            ticker=ticker,
            exchange=exchange,
            current_price=price,
            shares=shares,
            order_type=OrderType.ENTRY,
            notes=journal_notes,
            market=self._market,
        )
        self.invalidate_balance_cache()

        # 주문 실패 시 쿨다운 설정 후 중단
        if order.status == OrderStatus.FAILED:
            logger.warning(
                "entry_order_failed",
                ticker=ticker,
                name=self._name(ticker),
                shares=shares,
                price=price,
            )
            self._entry_cooldown[ticker] = time.monotonic()
            # 잔고 부족 실패 → 모든 진입 5분간 일괄 차단 (API 낭비 방지)
            self._global_entry_block_until = (
                time.monotonic() + self._GLOBAL_ENTRY_BLOCK_SEC
            )
            logger.warning(
                "global_entry_blocked",
                ticker=ticker,
                block_seconds=self._GLOBAL_ENTRY_BLOCK_SEC,
                msg="주문 실패 → 모든 진입 5분간 차단",
            )
            return

        logger.info(
            "entry_order_submitted",
            ticker=ticker,
            name=self._name(ticker),
            system=system,
            shares=shares,
            price=price,
            stop_price=stop_price,
        )

        # 이벤트 발행
        signal = TradeSignal(
            signal_type=SignalType.ENTRY_LONG,
            ticker=ticker,
            price=price,
            timestamp=datetime.fromtimestamp(timestamp, tz=timezone.utc),
            system=system,
            shares=shares,
            stop_price=stop_price,
            breakout_level=entry_signal.get("breakout_level"),
            n_value=signals.n_value,
        )
        await self._event_bus.emit(signal)

    # ────────────────────────────────────────────────────────
    # Execution: Donchian Exit
    # ────────────────────────────────────────────────────────

    async def _execute_donchian_exit(
        self,
        ticker: str,
        price: float,
        position: object,
        signals: PrecomputedSignals,
        timestamp: float,
    ) -> None:
        """Donchian 채널 청산 실행.

        Args:
            ticker: 종목 코드.
            price: 현재가.
            position: 현재 포지션 객체.
            signals: 사전 계산 시그널.
            timestamp: 이벤트 시각.
        """
        if await self._db.has_submitted_order(ticker, "SELL", "EXIT"):
            logger.debug("donchian_exit_skipped_pending_order", ticker=ticker)
            return

        # Donchian 청산은 장 마감 15분 전부터만 체크 (장중 일시적 하락에 의한 조기 청산 방지)
        if self._market == "KR":
            kst = timezone(timedelta(hours=9))
            now_local = datetime.now(kst)
            mkt_cfg = get_market_config("KR")
            close_minutes = mkt_cfg.market_close_hour * 60 + mkt_cfg.market_close_minute
            now_minutes = now_local.hour * 60 + now_local.minute
            if now_minutes < close_minutes - mkt_cfg.donchian_exit_minutes_before_close:
                return
        else:
            # US market logic
            us_eastern = ZoneInfo("America/New_York")
            now_et = datetime.now(us_eastern)
            if not should_check_donchian_exit(now_et.hour, now_et.minute):
                return

        system = position.system.value if hasattr(position.system, "value") else str(position.system)  # type: ignore[attr-defined]

        exit_result = check_donchian_exit(
            current_price=price,
            system=system,
            donchian_lower_10=signals.donchian.lower_10,
            donchian_lower_20=signals.donchian.lower_20,
        )

        if not exit_result["exit"]:
            return

        logger.info(
            "donchian_exit_triggered",
            ticker=ticker,
            name=self._name(ticker),
            price=price,
            system=system,
            exit_level=exit_result["exit_level"],
            reason=exit_result["reason"],
        )

        # ── 매매일지 컨텍스트 ──
        journal_notes = build_exit_context(
            system=system,
            exit_level=exit_result.get("exit_level"),
            exit_reason=exit_result.get("reason", ""),
            avg_entry_price=position.avg_entry_price,  # type: ignore[attr-defined]
            atr=signals.n_value,
            units_held=len(position.units) if hasattr(position, 'units') and position.units else 0,  # type: ignore[attr-defined]
            total_shares=position.total_shares,  # type: ignore[attr-defined]
            current_price=price,
        )

        order = await self._order_executor.execute_exit_sell(
            ticker=ticker,
            exchange=await self._resolve_exchange(ticker),
            current_price=price,
            shares=position.total_shares,  # type: ignore[attr-defined]
            order_type=OrderType.EXIT,
            notes=journal_notes,
            market=self._market,
        )
        self.invalidate_balance_cache()

        # 이벤트 발행
        signal = TradeSignal(
            signal_type=SignalType.DONCHIAN_EXIT,
            ticker=ticker,
            price=price,
            timestamp=datetime.fromtimestamp(timestamp, tz=timezone.utc),
            system=system,
            shares=position.total_shares,  # type: ignore[attr-defined]
        )
        await self._event_bus.emit(signal)

    # ────────────────────────────────────────────────────────
    # Execution: Forced Market-Order Exit (next-session recovery)
    # ────────────────────────────────────────────────────────

    async def execute_forced_exit_market(self, position: object) -> None:
        """force_exit_flag가 세팅된 포지션을 시장가(또는 공격적 지정가)로 강제 청산.

        pre_market 직후 호출. 전 세션 마감 임박/이후 손절 거부 건 회수용.
        """
        ticker = position.ticker  # type: ignore[attr-defined]
        if await self._db.has_submitted_order(ticker, "SELL"):
            logger.debug("forced_exit_skipped_pending_order", ticker=ticker)
            return

        exchange = await self._resolve_exchange(ticker)
        # 현재가 조회 — 실패 시 avg_entry_price로 fallback
        current_price: float = 0.0
        try:
            price_data = await self._rest.get_current_price(ticker, exchange, market=self._market)
            if self._market == "KR":
                current_price = float(price_data.get("stck_prpr", 0)) or float(position.avg_entry_price)  # type: ignore[attr-defined]
            else:
                current_price = float(price_data.get("last", 0)) or float(position.avg_entry_price)  # type: ignore[attr-defined]
        except Exception as exc:
            logger.warning("forced_exit_price_fetch_failed", ticker=ticker, error=str(exc))
            current_price = float(position.avg_entry_price)  # type: ignore[attr-defined]

        logger.warning(
            "forced_exit_market_executing",
            ticker=ticker,
            flag=getattr(position, "force_exit_flag", None),
            reason=getattr(position, "force_exit_reason", None),
            current_price=current_price,
            shares=position.total_shares,  # type: ignore[attr-defined]
            market=self._market,
        )

        order = await self._order_executor.execute_exit_sell(
            ticker=ticker,
            exchange=exchange,
            current_price=current_price,
            shares=position.total_shares,  # type: ignore[attr-defined]
            order_type=OrderType.EXIT,
            notes=f"force_exit:{getattr(position, 'force_exit_flag', '')}:{getattr(position, 'force_exit_reason', '')}",
            market=self._market,
            aggressive=True,
        )
        self.invalidate_balance_cache()

        # 주문이 SUBMITTED 된 경우에만 플래그 제거 (체결은 fill_check 루프가 확인)
        if order.status.value == "SUBMITTED":
            await self._db.clear_force_exit_flag(ticker)
            logger.info("forced_exit_submitted_flag_cleared", ticker=ticker)
        else:
            logger.error(
                "forced_exit_failed",
                ticker=ticker,
                status=order.status.value,
                notes=order.notes,
            )

    # ────────────────────────────────────────────────────────
    # Helpers
    # ────────────────────────────────────────────────────────

    async def _resolve_exchange(self, ticker: str) -> str:
        try:
            cursor = await self._db.conn.execute(
                "SELECT exchange FROM watchlist WHERE ticker = ?",
                (ticker,),
            )
            row = await cursor.fetchone()
            if row and row[0]:
                return row[0]
        except Exception:
            pass
        return "KOSPI" if self._market == "KR" else "NASD"
