"""
주문 실행 엔진.

소프트웨어 스톱-로스 구현의 핵심 모듈.
한투 API에 스톱/시장가 주문이 없으므로, 봇이 직접:
1. 가격 감시 → 조건 발동 시 즉시 지정가 주문
2. 미체결 시 가격 갱신 후 재주문 (최대 3회)
3. 주문 상태 추적 및 DB 기록

참고: IMPLEMENTATION_PLAN.md §2.1 "스톱 주문 미지원 → 소프트웨어 스톱 구현"
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Any, TYPE_CHECKING

import structlog

from broker.kis_rest import KISRestClient, KISAPIError
from config.constants import (
    BUY_BUFFER_PCT,
    STOP_MAX_RETRIES,
    STOP_RETRY_DELAY_SECONDS,
    STOP_SELL_BUFFER_PCT,
)
from config.market_config import adjust_price_to_tick, KR_TICK_SIZE_TABLE
from core.database import Database
from core.models import CloseReason, Order, OrderSide, OrderStatus, OrderType

if TYPE_CHECKING:
    from portfolio.position_manager import PositionManager

logger = structlog.get_logger(__name__)


class OrderExecutor:
    """
    주문 실행 + 상태 관리.

    기능:
    - 돌파 진입 주문 (현재가 + 버퍼)
    - 손절 매도 주문 (현재가 - 버퍼, 미체결 시 재시도)
    - 피라미딩 추가 매수
    - Donchian 청산 매도
    - 주문 상태 추적 (DB에 기록)
    """

    def __init__(
        self,
        rest_client: KISRestClient,
        db: Database,
        position_mgr: PositionManager | None = None,
    ) -> None:
        self._rest = rest_client
        self._db = db
        self._position_mgr = position_mgr

    # ────────────────────────────────────────────────────────
    # 진입 주문
    # ────────────────────────────────────────────────────────

    async def execute_entry_buy(
        self,
        ticker: str,
        exchange: str,
        current_price: float,
        shares: int,
        order_type: OrderType = OrderType.ENTRY,
        notes: str | None = None,
        *,
        market: str = "US",
    ) -> Order:
        """
        돌파 진입 매수 주문.

        현재가가 이미 돌파가를 넘었으므로, 체결 확보를 위해
        현재가 + BUY_BUFFER_PCT(0.3%)로 지정가 매수.
        """
        if market == "KR":
            buy_price = int(adjust_price_to_tick(
                current_price * (1 + BUY_BUFFER_PCT), KR_TICK_SIZE_TABLE
            ))
        else:
            buy_price = round(current_price * (1 + BUY_BUFFER_PCT), 2)

        order = Order(
            ticker=ticker,
            side=OrderSide.BUY,
            order_type=order_type,
            requested_shares=shares,
            requested_price=buy_price,
            status=OrderStatus.PENDING,
            created_at=_now_iso(),
            updated_at=_now_iso(),
            notes=notes,
        )
        order._market = market

        try:
            result = await self._rest.place_order(
                ticker=ticker,
                exchange=exchange,
                side="BUY",
                quantity=shares,
                price=buy_price,
                market=market,
            )
            order.broker_order_id = result.get("ODNO", "")
            order.status = OrderStatus.SUBMITTED
            order.updated_at = _now_iso()

            logger.info(
                "order_entry_submitted",
                ticker=ticker,
                shares=shares,
                price=buy_price,
                order_no=order.broker_order_id,
                order_type=order_type.value,
            )

        except KISAPIError as e:
            order.status = OrderStatus.FAILED
            order.notes = _merge_error_note(order.notes, str(e))
            order.updated_at = _now_iso()
            logger.error("order_entry_failed", ticker=ticker, error=str(e))

        await self._save_order(order)
        return order

    # ────────────────────────────────────────────────────────
    # 손절 매도
    # ────────────────────────────────────────────────────────

    async def execute_stop_loss_sell(
        self,
        ticker: str,
        exchange: str,
        current_price: float,
        shares: int,
        notes: str | None = None,
        *,
        market: str = "US",
    ) -> Order:
        """
        손절 매도 주문.

        급락 중 체결을 확보하기 위해 현재가 - STOP_SELL_BUFFER_PCT(0.5%)
        로 aggressive limit order. 미체결 시 재시도.

        참고: IMPLEMENTATION_PLAN.md §2.1
        """
        order = Order(
            ticker=ticker,
            side=OrderSide.SELL,
            order_type=OrderType.STOP_LOSS,
            requested_shares=shares,
            requested_price=0.0,  # 아래에서 설정
            status=OrderStatus.PENDING,
            created_at=_now_iso(),
            updated_at=_now_iso(),
            notes=notes,
        )
        order._market = market

        for attempt in range(1, STOP_MAX_RETRIES + 1):
            if market == "KR":
                sell_price = int(adjust_price_to_tick(
                    current_price * (1 - STOP_SELL_BUFFER_PCT), KR_TICK_SIZE_TABLE
                ))
            else:
                sell_price = round(current_price * (1 - STOP_SELL_BUFFER_PCT), 2)
            order.requested_price = sell_price

            try:
                result = await self._rest.place_order(
                    ticker=ticker,
                    exchange=exchange,
                    side="SELL",
                    quantity=shares,
                    price=sell_price,
                    market=market,
                )
                order.broker_order_id = result.get("ODNO", "")
                order.updated_at = _now_iso()

                order.status = OrderStatus.SUBMITTED
                logger.warning(
                    "order_stop_loss_submitted",
                    ticker=ticker,
                    shares=shares,
                    price=sell_price,
                    attempt=attempt,
                    order_no=order.broker_order_id,
                )
                break

            except KISAPIError as e:
                logger.error(
                    "order_stop_loss_attempt_failed",
                    ticker=ticker,
                    attempt=attempt,
                    error=str(e),
                )
                # 40240000: 모의투자 잔고내역이 없습니다
                # → 브로커에 잔고 없음 = 이전 매도 주문이 이미 체결된 것
                # 재시도 무의미, 즉시 중단하고 포지션 강제 청산 필요
                if e.msg_cd == "40240000":
                    order.status = OrderStatus.FAILED
                    order.notes = _merge_error_note(order.notes, "NO_BROKER_BALANCE")
                    order.updated_at = _now_iso()
                    logger.warning(
                        "stop_loss_no_broker_balance",
                        ticker=ticker,
                        msg="브로커 잔고 없음 → 이전 주문이 이미 체결된 것으로 판단, 포지션 강제 청산 필요",
                    )
                    break
                if attempt < STOP_MAX_RETRIES:
                    await asyncio.sleep(STOP_RETRY_DELAY_SECONDS)
                    # 재시도 시 최신 가격으로 갱신
                    try:
                        price_data = await self._rest.get_current_price(ticker, exchange, market=market)
                        if market == "KR":
                            current_price = float(price_data.get("stck_prpr", current_price))
                        else:
                            current_price = float(price_data.get("last", current_price))
                    except Exception:
                        pass  # 가격 조회 실패 시 기존 가격 사용
                else:
                    order.status = OrderStatus.FAILED
                    order.notes = _merge_error_note(order.notes, f"손절 주문 {STOP_MAX_RETRIES}회 재시도 실패: {e}")
                    order.updated_at = _now_iso()

        await self._save_order(order)
        return order

    # ────────────────────────────────────────────────────────
    # 청산 매도
    # ────────────────────────────────────────────────────────

    async def execute_exit_sell(
        self,
        ticker: str,
        exchange: str,
        current_price: float,
        shares: int,
        order_type: OrderType = OrderType.EXIT,
        notes: str | None = None,
        *,
        market: str = "US",
    ) -> Order:
        """
        Donchian 청산 또는 일반 청산 매도.
        손절과 달리 급박하지 않으므로 버퍼를 작게.
        최대 2회 재시도 (장 마감 직전 API 과부하 대비).
        """
        order = Order(
            ticker=ticker,
            side=OrderSide.SELL,
            order_type=order_type,
            requested_shares=shares,
            requested_price=0.0,
            status=OrderStatus.PENDING,
            created_at=_now_iso(),
            updated_at=_now_iso(),
            notes=notes,
        )
        order._market = market

        max_retries = 2
        for attempt in range(1, max_retries + 1):
            if market == "KR":
                sell_price = int(adjust_price_to_tick(
                    current_price * (1 - STOP_SELL_BUFFER_PCT / 2), KR_TICK_SIZE_TABLE
                ))
            else:
                sell_price = round(current_price * (1 - STOP_SELL_BUFFER_PCT / 2), 2)
            order.requested_price = sell_price

            try:
                result = await self._rest.place_order(
                    ticker=ticker,
                    exchange=exchange,
                    side="SELL",
                    quantity=shares,
                    price=sell_price,
                    market=market,
                )
                order.broker_order_id = result.get("ODNO", "")
                order.updated_at = _now_iso()

                order.status = OrderStatus.SUBMITTED
                logger.info(
                    "order_exit_submitted",
                    ticker=ticker,
                    shares=shares,
                    price=sell_price,
                    order_type=order_type.value,
                    attempt=attempt,
                )
                break

            except KISAPIError as e:
                logger.error(
                    "order_exit_attempt_failed",
                    ticker=ticker,
                    attempt=attempt,
                    error=str(e),
                )
                # 40240000: 브로커 잔고 없음 = 이미 체결됨
                if e.msg_cd == "40240000":
                    order.status = OrderStatus.FAILED
                    order.notes = _merge_error_note(order.notes, "NO_BROKER_BALANCE")
                    order.updated_at = _now_iso()
                    logger.warning(
                        "exit_no_broker_balance",
                        ticker=ticker,
                        msg="브로커 잔고 없음 → 이전 주문이 이미 체결된 것으로 판단",
                    )
                    break
                if attempt < max_retries:
                    await asyncio.sleep(STOP_RETRY_DELAY_SECONDS)
                    try:
                        price_data = await self._rest.get_current_price(ticker, exchange, market=market)
                        if market == "KR":
                            current_price = float(price_data.get("stck_prpr", current_price))
                        else:
                            current_price = float(price_data.get("last", current_price))
                    except Exception:
                        pass
                else:
                    order.status = OrderStatus.FAILED
                    order.notes = _merge_error_note(order.notes, f"청산 주문 {max_retries}회 재시도 실패: {e}")
                    order.updated_at = _now_iso()

        await self._save_order(order)
        return order

    # ────────────────────────────────────────────────────────
    # 주문 취소
    # ────────────────────────────────────────────────────────

    async def cancel_order(self, order: Order, exchange: str) -> bool:
        """주문 취소. 성공하면 True."""
        if not order.broker_order_id:
            logger.warning("cancel_no_broker_id", ticker=order.ticker)
            return False

        try:
            await self._rest.cancel_order(
                order_no=order.broker_order_id,
                ticker=order.ticker,
                exchange=exchange,
                quantity=order.requested_shares,
            )
            order.status = OrderStatus.CANCELLED
            order.updated_at = _now_iso()
            await self._save_order(order)
            return True

        except KISAPIError as e:
            logger.error("cancel_failed", order_no=order.broker_order_id, error=str(e))
            return False

    # ────────────────────────────────────────────────────────
    # 주문 상태 확인
    # ────────────────────────────────────────────────────────

    async def check_order_fills(self) -> list[Order]:
        """
        미체결 주문의 체결 상태를 확인하고 DB 업데이트.

        1. DB에서 SUBMITTED/PARTIAL 상태의 주문을 조회
        2. KIS API에서 오늘 체결 내역을 조회
        3. broker_order_id(odno)로 매칭하여 체결 수량/가격을 업데이트
        4. 완전 체결 → FILLED, 부분 체결 → PARTIAL

        Returns:
            새로 FILLED 상태가 된 주문 목록.
        """
        filled_orders: list[Order] = []

        try:
            cursor = await self._db.conn.execute(
                """
                SELECT id, broker_order_id, ticker, side, order_type,
                       requested_shares, requested_price,
                       filled_shares, filled_price,
                       status, created_at, updated_at, filled_at, notes, market
                FROM orders
                WHERE status IN (?, ?)
                """,
                (OrderStatus.SUBMITTED.value, OrderStatus.PARTIAL.value),
            )
            rows = await cursor.fetchall()

            if not rows:
                return filled_orders

            pending_orders: dict[str, Order] = {}
            for row in rows:
                order = Order(
                    id=row[0],
                    broker_order_id=row[1],
                    ticker=row[2],
                    side=OrderSide(row[3]),
                    order_type=OrderType(row[4]),
                    requested_shares=row[5],
                    requested_price=row[6],
                    filled_shares=row[7] or 0,
                    filled_price=row[8],
                    status=OrderStatus(row[9]),
                    created_at=row[10],
                    updated_at=row[11],
                    filled_at=row[12],
                    notes=row[13],
                )
                order._market = row[14] if row[14] else "US"
                if order.broker_order_id:
                    # KIS API 체결조회는 odno 선행 0을 제거하여 반환 (예: "41291")
                    # 주문 제출 응답은 선행 0 포함 (예: "0000041291")
                    # 양쪽 모두 정규화하여 매칭
                    normalized_key = order.broker_order_id.lstrip("0") or "0"
                    pending_orders[normalized_key] = order

            if not pending_orders:
                return filled_orders

            # Determine which markets have pending orders
            markets_needed = set()
            for order in pending_orders.values():
                markets_needed.add(getattr(order, '_market', 'US'))

            # 주문 생성일 기준으로 조회 날짜 결정
            # 미국 장은 23:30~06:00 KST로 자정을 걸치므로, datetime.now()가 아닌
            # 실제 주문 생성일을 사용해야 체결 조회가 정확함
            order_dates: set[str] = set()
            for order in pending_orders.values():
                try:
                    created = datetime.fromisoformat(order.created_at)
                    order_dates.add(created.strftime("%Y%m%d"))
                except (ValueError, TypeError):
                    pass
            if not order_dates:
                order_dates.add(datetime.now().strftime("%Y%m%d"))
            start_date = min(order_dates)
            end_date = max(order_dates)
            # 오늘 날짜도 포함 (당일 주문이 있을 수 있으므로)
            today_str = datetime.now().strftime("%Y%m%d")
            if today_str > end_date:
                end_date = today_str

            # Fetch fills from each market
            all_fills = []
            for mkt in markets_needed:
                try:
                    fills = await self._rest.get_filled_orders(
                        start_date, end_date, market=mkt,
                    )
                    for f in fills:
                        f['_market'] = mkt
                    all_fills.extend(fills)
                except Exception:
                    logger.warning("filled_query_market_failed", market=mkt, exc_info=True)

            # ── KR Paper 모의투자 잔고 기반 체결 확인 fallback ──
            # VTTC8001R (KR 체결내역 조회)가 Paper에서 빈 결과 반환하므로,
            # get_balance()로 브로커 잔고를 조회하여 체결 여부를 추론.
            if "KR" in markets_needed and self._rest._settings.is_paper:
                kr_pending = {
                    k: v for k, v in pending_orders.items()
                    if getattr(v, '_market', 'US') == 'KR'
                    and v.status != OrderStatus.FILLED
                }
                if kr_pending:
                    try:
                        kr_balance = await self._rest.get_balance(market="KR")
                        broker_holdings: dict[str, int] = {}
                        for bp in kr_balance.get("positions", []):
                            pdno = bp.get("pdno", "")
                            qty = int(float(bp.get("hldg_qty", 0)))
                            if pdno and qty > 0:
                                broker_holdings[pdno] = qty

                        # DB 포지션 현재 수량 조회 (sync_positions 이중 반영 방지)
                        db_pos_shares: dict[str, int] = {}
                        if self._position_mgr:
                            for order_key, order in kr_pending.items():
                                pos = await self._position_mgr.get_position(order.ticker)
                                if pos:
                                    db_pos_shares[order.ticker] = pos.total_shares

                        for order_key, order in list(kr_pending.items()):
                            broker_qty = broker_holdings.get(order.ticker, 0)
                            if broker_qty <= 0:
                                if order.side == OrderSide.SELL:
                                    # 매도 후 잔고 0 = 체결
                                    pass
                                else:
                                    continue

                            if order.side == OrderSide.BUY:
                                fill_qty = order.requested_shares
                                fill_price = order.requested_price
                            else:
                                fill_qty = order.requested_shares
                                fill_price = order.requested_price

                            old_filled = order.filled_shares
                            order.filled_shares = fill_qty
                            order.filled_price = fill_price
                            order.status = OrderStatus.FILLED
                            order.filled_at = _now_iso()
                            order.updated_at = _now_iso()
                            filled_orders.append(order)
                            await self._save_order(order)

                            logger.info(
                                "order_filled_kr_paper_balance_fallback",
                                order_id=order.id,
                                broker_order_id=order_key,
                                ticker=order.ticker,
                                side=order.side.value,
                                filled_shares=fill_qty,
                                filled_price=fill_price,
                                broker_qty=broker_qty,
                            )

                            # 항상 _handle_fill_position 호출 — 유닛 기록에 필요
                            # BUY: sync_positions가 먼저 실행되어도 유닛 추적을 위해 호출 필수
                            # SELL: 포지션 청산/감소 처리 필수
                            if self._position_mgr:
                                await self._handle_fill_position(order, old_filled)
                    except Exception:
                        logger.warning("kr_paper_balance_fallback_failed", exc_info=True)

            if not all_fills:
                # KR paper fallback으로 이미 처리된 주문이 있을 수 있으므로
                # filled_orders가 비어있을 때만 early return
                if not filled_orders:
                    return filled_orders
                # fallback으로 체결된 것이 있으면 아래 만료 로직도 실행
                all_fills = []  # 빈 리스트로 두고 만료 로직으로 진행

            for fill in all_fills:
                raw_odno = fill.get("odno", "")
                if not raw_odno:
                    continue
                order_no = raw_odno.lstrip("0") or "0"
                if order_no not in pending_orders:
                    continue

                order = pending_orders[order_no]
                fill_market = fill.get('_market', 'US')

                # KR vs US have different field names for fill quantity/price
                if fill_market == "KR":
                    fill_qty = int(float(fill.get("tot_ccld_qty", 0)))
                    fill_price = float(fill.get("avg_prvs", 0))
                else:
                    fill_qty = int(float(fill.get("ft_ccld_qty", 0)))
                    fill_price = float(fill.get("ft_ccld_unpr3", 0))

                if fill_qty <= 0:
                    continue

                if order.status == OrderStatus.FILLED:
                    continue

                old_filled = order.filled_shares
                if fill_qty <= old_filled:
                    continue

                order.filled_shares = fill_qty
                if fill_price > 0:
                    order.filled_price = fill_price
                order.updated_at = _now_iso()

                if order.filled_shares >= order.requested_shares:
                    order.status = OrderStatus.FILLED
                    order.filled_at = _now_iso()
                    filled_orders.append(order)
                    logger.info(
                        "order_filled",
                        order_id=order.id,
                        broker_order_id=order_no,
                        ticker=order.ticker,
                        side=order.side.value,
                        filled_shares=order.filled_shares,
                        filled_price=order.filled_price,
                    )
                else:
                    order.status = OrderStatus.PARTIAL
                    logger.info(
                        "order_partial_fill",
                        order_id=order.id,
                        broker_order_id=order_no,
                        ticker=order.ticker,
                        filled=order.filled_shares,
                        requested=order.requested_shares,
                    )

                await self._save_order(order)

                if self._position_mgr:
                    await self._handle_fill_position(order, old_filled)

            # ── 오래된 미체결 주문 자동 정리 ──
            # get_filled_orders()는 오늘 날짜만 조회하므로, 전날 주문은 매칭 불가.
            # 2시간(7200초) 이상 된 SUBMITTED 주문은 자동 정리하여 무한 폴링 방지.
            # sync_positions가 다음 시작 시 포지션 수량을 보정해줌.
            now = datetime.now(timezone.utc)
            for order in pending_orders.values():
                if order.status == OrderStatus.FILLED:
                    continue  # 이미 위에서 체결 처리됨
                try:
                    created = datetime.fromisoformat(order.created_at)
                    age_s = (now - created).total_seconds()
                except (ValueError, TypeError):
                    age_s = 0

                # 매도 주문(STOP_LOSS/EXIT)은 30분, 매수 주문은 2시간 후 만료
                expire_seconds = 1800 if order.side == OrderSide.SELL else 7200
                if age_s > expire_seconds and (order.filled_shares or 0) == 0:
                    order.status = OrderStatus.FAILED
                    order.updated_at = _now_iso()
                    order.notes = json.dumps({
                        **(json.loads(order.notes) if order.notes else {}),
                        "resolved_by": "auto_expired_fill_check_timeout",
                        "age_hours": round(age_s / 3600, 1),
                    })
                    await self._save_order(order)
                    logger.warning(
                        "old_submitted_order_expired",
                        order_id=order.id,
                        ticker=order.ticker,
                        broker_order_id=order.broker_order_id,
                        age_hours=round(age_s / 3600, 1),
                    )

        except Exception as e:
            logger.error("check_fills_failed", error=str(e))

        return filled_orders

    # ────────────────────────────────────────────────────────
    # 체결 후 포지션 반영
    # ────────────────────────────────────────────────────────

    async def _handle_fill_position(self, order: Order, old_filled: int) -> None:
        """체결 확인 후 포지션 생성/업데이트/청산."""
        notes: dict = {}
        if order.notes:
            try:
                notes = json.loads(order.notes)
            except (json.JSONDecodeError, TypeError):
                pass

        fill_price = order.filled_price or order.requested_price
        fill_shares = order.filled_shares

        try:
            if order.order_type == OrderType.ENTRY and order.side == OrderSide.BUY:
                position = await self._position_mgr.get_position(order.ticker)
                if position is None:
                    n_value = notes.get("atr", 0.0)
                    stop_price = notes.get("stop_price", 0.0)

                    # 안전장치: notes 파싱 실패로 stop_price=0이면 재계산
                    if stop_price <= 0 and fill_price > 0:
                        from strategy.stop_loss import calculate_stop_price as calc_stop
                        if n_value > 0:
                            stop_price = calc_stop(fill_price, n_value)
                        else:
                            # n_value도 없으면 10% 고정 스톱
                            stop_price = fill_price * 0.90
                        logger.warning(
                            "fill_stop_price_recalculated",
                            ticker=order.ticker,
                            stop_price=stop_price,
                            n_value=n_value,
                        )

                    # 포지션이 이미 존재하는지 확인 (sync_positions가 먼저 생성했을 수 있음)
                    existing_pos = await self._position_mgr.get_position(order.ticker)
                    if existing_pos:
                        logger.info(
                            "fill_entry_position_already_exists",
                            ticker=order.ticker,
                            position_id=existing_pos.id,
                            msg="sync_positions가 이미 생성함 — 유닛 확인만 수행",
                        )
                    else:
                        order_market = getattr(order, '_market', 'US')
                        await self._position_mgr.open_position(
                            ticker=order.ticker,
                            system=notes.get("system", "S1"),
                            entry_price=fill_price,
                            shares=fill_shares,
                            n_value=n_value,
                            stop_price=stop_price,
                            market=order_market,
                        )
                        logger.info(
                            "fill_position_opened",
                            ticker=order.ticker,
                            price=fill_price,
                            shares=fill_shares,
                            market=order_market,
                        )
                else:
                    await self._position_mgr.update_entry_fill(
                        position_id=position.id,
                        filled_shares=fill_shares,
                        fill_price=fill_price,
                    )

            elif order.order_type == OrderType.PYRAMID and order.side == OrderSide.BUY:
                position = await self._position_mgr.get_position(order.ticker)
                if position is None:
                    logger.error("fill_pyramid_no_position", ticker=order.ticker)
                    return

                if old_filled == 0:
                    new_stop = notes.get("new_stop", position.current_stop_price)
                    await self._position_mgr.add_unit(
                        position_id=position.id,
                        entry_price=fill_price,
                        shares=fill_shares,
                        stop_price=new_stop,
                    )
                    logger.info(
                        "fill_pyramid_added",
                        ticker=order.ticker,
                        price=fill_price,
                        shares=fill_shares,
                    )
                else:
                    await self._position_mgr.update_pyramid_fill(
                        position_id=position.id,
                        filled_shares=fill_shares,
                        fill_price=fill_price,
                    )

            elif order.order_type == OrderType.STOP_LOSS and order.side == OrderSide.SELL:
                position = await self._position_mgr.get_position(order.ticker)
                if position and position.id is not None:
                    if order.status == OrderStatus.FILLED:
                        await self._position_mgr.close_position(
                            position_id=position.id,
                            reason=CloseReason.STOP_LOSS.value,
                            exit_price=fill_price,
                        )
                        logger.info("fill_stop_loss_closed", ticker=order.ticker, price=fill_price)
                    else:
                        await self._position_mgr.reduce_shares(
                            position_id=position.id,
                            filled_shares=fill_shares,
                        )
                        logger.info(
                            "stop_loss_partial_reduced",
                            ticker=order.ticker,
                            filled=fill_shares,
                            requested=order.requested_shares,
                        )
                else:
                    logger.warning("fill_stop_loss_no_position", ticker=order.ticker)

            elif order.order_type == OrderType.EXIT and order.side == OrderSide.SELL:
                position = await self._position_mgr.get_position(order.ticker)
                if position and position.id is not None:
                    system = notes.get("system", "S1")
                    if order.status == OrderStatus.FILLED:
                        reason = (
                            CloseReason.SYSTEM1_EXIT.value
                            if system == "S1"
                            else CloseReason.SYSTEM2_EXIT.value
                        )
                        await self._position_mgr.close_position(
                            position_id=position.id,
                            reason=reason,
                            exit_price=fill_price,
                        )
                        logger.info("fill_exit_closed", ticker=order.ticker, price=fill_price)
                    else:
                        await self._position_mgr.reduce_shares(
                            position_id=position.id,
                            filled_shares=fill_shares,
                        )
                        logger.info(
                            "exit_partial_reduced",
                            ticker=order.ticker,
                            filled=fill_shares,
                            requested=order.requested_shares,
                        )
                else:
                    logger.warning("fill_exit_no_position", ticker=order.ticker)

        except Exception:
            logger.exception(
                "fill_position_handling_failed",
                ticker=order.ticker,
                order_type=order.order_type.value,
            )

    # ────────────────────────────────────────────────────────
    # DB 저장
    # ────────────────────────────────────────────────────────

    async def _save_order(self, order: Order) -> None:
        """주문을 DB orders 테이블에 저장."""
        if order.id is None:
            # 신규 주문 INSERT
            cursor = await self._db.conn.execute(
                """
                INSERT INTO orders (
                    broker_order_id, ticker, side, order_type,
                    requested_shares, requested_price,
                    filled_shares, filled_price,
                    status, created_at, updated_at, filled_at, notes, market
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    order.broker_order_id,
                    order.ticker,
                    order.side.value,
                    order.order_type.value,
                    order.requested_shares,
                    order.requested_price,
                    order.filled_shares,
                    order.filled_price,
                    order.status.value,
                    order.created_at,
                    order.updated_at,
                    order.filled_at,
                    order.notes,
                    getattr(order, '_market', 'US'),
                ),
            )
            order.id = cursor.lastrowid
        else:
            # 기존 주문 UPDATE
            await self._db.conn.execute(
                """
                UPDATE orders SET
                    broker_order_id = ?, status = ?,
                    filled_shares = ?, filled_price = ?,
                    updated_at = ?, filled_at = ?, notes = ?
                WHERE id = ?
                """,
                (
                    order.broker_order_id,
                    order.status.value,
                    order.filled_shares,
                    order.filled_price,
                    order.updated_at,
                    order.filled_at,
                    order.notes,
                    order.id,
                ),
            )
        await self._db.conn.commit()


def _now_iso() -> str:
    """현재 시각 ISO 8601 문자열."""
    return datetime.now(timezone.utc).isoformat()


def _merge_error_note(context_notes: str | None, error: str) -> str:
    """에러 메시지를 기존 매매일지 JSON 컨텍스트에 병합.

    context_notes가 유효한 JSON이면 ``error`` 키를 추가하고,
    그렇지 않으면 텍스트로 연결한다.

    Args:
        context_notes: 기존 JSON 매매일지 (또는 None).
        error: 에러 메시지 문자열.

    Returns:
        병합된 notes 문자열.
    """
    if not context_notes:
        return error
    try:
        data = json.loads(context_notes)
        data["error"] = error
        return json.dumps(data, ensure_ascii=False)
    except (json.JSONDecodeError, TypeError):
        return f"{context_notes} | ERROR: {error}"
