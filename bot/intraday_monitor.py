"""
장중 모니터링 엔진 — WebSocket 틱마다 신호 판단.

우선순위:
1. 손절 체크 (가장 긴급)
2. 피라미딩 체크
3. 신규 진입 체크
4. Donchian 청산 체크 (장 마감 15분 전만)
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import structlog

from broker.kis_rest import KISRestClient
from broker.order_executor import OrderExecutor
from core.database import Database
from core.events import EventBus
from core.models import (
    CloseReason,
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
        self._running: bool = False

    # ────────────────────────────────────────────────────────
    # Lifecycle
    # ────────────────────────────────────────────────────────

    async def start(self) -> None:
        """모니터링 시작."""
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
          4. 장 마감 15분 전 & 보유 종목 → Donchian 청산 체크

        Args:
            ticker: 종목 코드.
            price: 현재 체결가.
            timestamp: 틱 수신 시각 (Unix timestamp).
        """
        if not self._running:
            return

        # 사전 계산 데이터가 없으면 무시
        signals = self.precomputed_signals.get(ticker)
        if signals is None:
            return

        # 현재 포지션 조회
        position = await self._position_mgr.get_position(ticker)

        # ── Priority 1: 손절 체크 ──
        if position is not None:
            stop_hit = check_stop_hit(price, position.current_stop_price)
            if stop_hit:
                await self._execute_stop_loss(ticker, price, position, timestamp)
                return

        # ── Priority 2: 피라미딩 체크 ──
        if position is not None and position.can_add_unit:
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

        # ── Priority 4: Donchian 청산 체크 (장 마감 15분 전만) ──
        if position is not None:
            now_utc = datetime.fromtimestamp(timestamp, tz=timezone.utc)
            # US Eastern: DST-aware 변환 (EDT/EST 자동 반영)
            now_et = now_utc.astimezone(ZoneInfo("America/New_York"))
            et_hour = now_et.hour
            et_minute = now_et.minute

            if should_check_donchian_exit(
                current_hour=et_hour,
                current_minute=et_minute,
                market_close_hour=16,
                market_close_minute=0,
            ):
                await self._execute_donchian_exit(
                    ticker, price, position, signals, timestamp,
                )

    # ────────────────────────────────────────────────────────
    # Execution: Stop-Loss
    # ────────────────────────────────────────────────────────

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
        logger.warning(
            "stop_loss_triggered",
            ticker=ticker,
            price=price,
            stop_price=position.current_stop_price,  # type: ignore[attr-defined]
            total_shares=position.total_shares,  # type: ignore[attr-defined]
        )

        # ── 매매일지 컨텍스트 ──
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
        )

        # 포지션 청산
        await self._position_mgr.close_position(
            position_id=position.id,  # type: ignore[attr-defined]
            reason=CloseReason.STOP_LOSS.value,
            exit_price=price,
        )

        # 이벤트 발행
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
        # 계좌 잔고 조회
        try:
            account_info = await self._rest.get_balance()
            summary = account_info.get("summary", {}) if isinstance(account_info, dict) else {}
            cash = float(summary.get("frcr_ord_psbl_amt1", 0))
        except Exception:
            logger.exception("pyramid_balance_fetch_failed", ticker=ticker)
            return
        account_equity = cash + position.total_cost  # type: ignore[attr-defined]

        # 리스크 체크
        sizing = calculate_unit_shares(
            account_equity=account_equity,
            entry_price=price,
            n_value=signals.n_value,
        )
        if sizing["skip"]:
            logger.info(
                "pyramid_skipped_sizing",
                ticker=ticker,
                reason=sizing.get("reason", "insufficient capital"),
            )
            return

        shares = sizing["shares"]

        risk_check = await self._risk_mgr.can_add_unit(
            ticker=ticker,
            shares=shares,
            entry_price=price,
            account_equity=account_equity,
        )
        if not risk_check["allowed"]:
            logger.info(
                "pyramid_blocked_risk",
                ticker=ticker,
                violations=risk_check["violations"],
            )
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
        )

        # 포지션에 유닛 추가 & 스톱 갱신
        await self._position_mgr.add_unit(
            position_id=position.id,  # type: ignore[attr-defined]
            entry_price=price,
            shares=shares,
            stop_price=new_stop,
        )

        logger.info(
            "pyramid_executed",
            ticker=ticker,
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
        # 계좌 잔고 조회
        try:
            account_info = await self._rest.get_balance()
            summary = account_info.get("summary", {}) if isinstance(account_info, dict) else {}
            cash = float(summary.get("frcr_ord_psbl_amt1", 0))
        except Exception:
            logger.exception("entry_balance_fetch_failed", ticker=ticker)
            return
        account_equity = cash  # 신규 진입 시 총 자산 기준

        # 포지션 사이징
        sizing = calculate_unit_shares(
            account_equity=account_equity,
            entry_price=price,
            n_value=signals.n_value,
        )
        if sizing["skip"]:
            logger.info(
                "entry_skipped_sizing",
                ticker=ticker,
                reason=sizing.get("reason", "insufficient capital"),
            )
            return

        shares = sizing["shares"]

        # 리스크 체크
        risk_check = await self._risk_mgr.can_enter_position(
            ticker=ticker,
            shares=shares,
            entry_price=price,
            account_equity=account_equity,
        )
        if not risk_check["allowed"]:
            logger.info(
                "entry_blocked_risk",
                ticker=ticker,
                violations=risk_check["violations"],
            )
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
        )

        # 포지션 오픈
        await self._position_mgr.open_position(
            ticker=ticker,
            system=system,
            entry_price=price,
            shares=shares,
            n_value=signals.n_value,
            stop_price=stop_price,
        )

        logger.info(
            "entry_executed",
            ticker=ticker,
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

        장 마감 15분 전에만 호출된다.

        Args:
            ticker: 종목 코드.
            price: 현재가.
            position: 현재 포지션 객체.
            signals: 사전 계산 시그널.
            timestamp: 이벤트 시각.
        """
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

        # 청산 주문
        order = await self._order_executor.execute_exit_sell(
            ticker=ticker,
            exchange=await self._resolve_exchange(ticker),
            current_price=price,
            shares=position.total_shares,  # type: ignore[attr-defined]
            order_type=OrderType.EXIT,
            notes=journal_notes,
        )

        # 포지션 청산
        close_reason = (
            CloseReason.SYSTEM1_EXIT.value
            if system == "S1"
            else CloseReason.SYSTEM2_EXIT.value
        )
        await self._position_mgr.close_position(
            position_id=position.id,  # type: ignore[attr-defined]
            reason=close_reason,
            exit_price=price,
        )

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
    # Helpers
    # ────────────────────────────────────────────────────────

    async def _resolve_exchange(self, ticker: str) -> str:
        """종목에 대한 거래소 코드를 반환.

        DB watchlist 에서 조회하거나, 기본값 NASD 사용.

        Args:
            ticker: 종목 코드.

        Returns:
            거래소 코드 문자열 (e.g. "NASD", "NYSE", "AMEX").
        """
        # watchlist 에서 거래소 정보가 있으면 사용
        # 현재 watchlist 테이블에는 exchange 컬럼이 없으므로 기본값 사용
        # TODO: watchlist 에 exchange 컬럼 추가 후 조회 로직 구현
        return "NASD"
