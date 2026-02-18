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
from typing import Any

import structlog

from broker.kis_rest import KISRestClient, KISAPIError
from config.constants import (
    BUY_BUFFER_PCT,
    STOP_MAX_RETRIES,
    STOP_RETRY_DELAY_SECONDS,
    STOP_SELL_BUFFER_PCT,
)
from core.database import Database
from core.models import Order, OrderSide, OrderStatus, OrderType

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

    def __init__(self, rest_client: KISRestClient, db: Database) -> None:
        self._rest = rest_client
        self._db = db

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
    ) -> Order:
        """
        돌파 진입 매수 주문.

        현재가가 이미 돌파가를 넘었으므로, 체결 확보를 위해
        현재가 + BUY_BUFFER_PCT(0.3%)로 지정가 매수.
        """
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

        try:
            result = await self._rest.place_order(
                ticker=ticker,
                exchange=exchange,
                side="BUY",
                quantity=shares,
                price=buy_price,
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

        for attempt in range(1, STOP_MAX_RETRIES + 1):
            sell_price = round(current_price * (1 - STOP_SELL_BUFFER_PCT), 2)
            order.requested_price = sell_price

            try:
                result = await self._rest.place_order(
                    ticker=ticker,
                    exchange=exchange,
                    side="SELL",
                    quantity=shares,
                    price=sell_price,
                )
                order.broker_order_id = result.get("ODNO", "")
                order.status = OrderStatus.SUBMITTED
                order.updated_at = _now_iso()

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
                if attempt < STOP_MAX_RETRIES:
                    await asyncio.sleep(STOP_RETRY_DELAY_SECONDS)
                    # 재시도 시 최신 가격으로 갱신
                    try:
                        price_data = await self._rest.get_current_price(ticker, exchange)
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
    ) -> Order:
        """
        Donchian 청산 또는 일반 청산 매도.
        손절과 달리 급박하지 않으므로 버퍼를 작게.
        """
        sell_price = round(current_price * (1 - STOP_SELL_BUFFER_PCT / 2), 2)

        order = Order(
            ticker=ticker,
            side=OrderSide.SELL,
            order_type=order_type,
            requested_shares=shares,
            requested_price=sell_price,
            status=OrderStatus.PENDING,
            created_at=_now_iso(),
            updated_at=_now_iso(),
            notes=notes,
        )

        try:
            result = await self._rest.place_order(
                ticker=ticker,
                exchange=exchange,
                side="SELL",
                quantity=shares,
                price=sell_price,
            )
            order.broker_order_id = result.get("ODNO", "")
            order.status = OrderStatus.SUBMITTED
            order.updated_at = _now_iso()

            logger.info(
                "order_exit_submitted",
                ticker=ticker,
                shares=shares,
                price=sell_price,
                order_type=order_type.value,
            )

        except KISAPIError as e:
            order.status = OrderStatus.FAILED
            order.notes = _merge_error_note(order.notes, str(e))
            order.updated_at = _now_iso()
            logger.error("order_exit_failed", ticker=ticker, error=str(e))

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
                       status, created_at, updated_at, filled_at, notes
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
                if order.broker_order_id:
                    pending_orders[order.broker_order_id] = order

            if not pending_orders:
                return filled_orders

            fills = await self._rest.get_filled_orders()

            if not fills:
                return filled_orders

            for fill in fills:
                order_no = fill.get("odno", "")
                if not order_no or order_no not in pending_orders:
                    continue

                order = pending_orders[order_no]

                # KIS 해외주식 체결 필드: ft_ccld_qty(체결수량), ft_ccld_unpr3(체결단가)
                fill_qty = int(float(fill.get("ft_ccld_qty", 0)))
                fill_price = float(fill.get("ft_ccld_unpr3", 0))

                if fill_qty <= 0:
                    continue

                if order.status == OrderStatus.FILLED:
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

        except Exception as e:
            logger.error("check_fills_failed", error=str(e))

        return filled_orders

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
                    status, created_at, updated_at, filled_at, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
