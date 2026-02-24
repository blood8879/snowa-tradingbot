"""
계좌 관리 모듈.

기능:
- 계좌 잔고/평가액 조회
- 보유 종목 → Position 동기화
- 브로커 잔고 vs 로컬 DB 불일치 감지
"""

from __future__ import annotations

import time
from typing import Any

import structlog

from broker.kis_rest import KISRestClient
from core.database import Database
from core.models import AccountInfo

logger = structlog.get_logger(__name__)

ACCOUNT_INFO_CACHE_TTL = 60
ACCOUNT_INFO_FAIL_CACHE_TTL = 30


class AccountManager:
    """
    계좌 정보 관리.

    사용법:
        account = AccountManager(rest_client, db)
        info = await account.get_account_info()
        positions = await account.get_broker_positions()
    """

    def __init__(self, rest_client: KISRestClient, db: Database) -> None:
        self._rest = rest_client
        self._db = db
        self._account_info_cache: AccountInfo | None = None
        self._account_info_cache_ts: float = 0.0

    async def get_account_info(self, force: bool = False) -> AccountInfo:
        """
        계좌 요약 정보 조회.

        inquire-psamount API로 현금 잔고를 조회하고,
        inquire-balance API로 보유 종목 평가액을 조회하여 합산.

        Returns:
            AccountInfo: 총 평가액, 현금 잔고, 포지션 가치
        """
        now = time.monotonic()
        if not force and self._account_info_cache is not None:
            ttl = (
                ACCOUNT_INFO_CACHE_TTL
                if self._account_info_cache.total_equity > 0
                else ACCOUNT_INFO_FAIL_CACHE_TTL
            )
            if (now - self._account_info_cache_ts) < ttl:
                return self._account_info_cache

        cash = 0.0
        try:
            psamount = await self._rest.get_purchasable_amount()
            cash = float(psamount.get("ord_psbl_frcr_amt", 0))
        except Exception as exc:
            logger.warning("get_purchasable_amount_failed", error=str(exc), exc_info=True)

        total_position_value = 0.0
        try:
            balance = await self._rest.get_balance()
            positions = balance.get("positions", [])
            for pos in positions:
                if not isinstance(pos, dict):
                    continue
                eval_amt = float(pos.get("ovrs_stck_evlu_amt", 0))
                total_position_value += eval_amt
        except Exception as exc:
            logger.warning("get_balance_failed", error=str(exc), exc_info=True)

        info = AccountInfo(
            total_equity=cash + total_position_value,
            cash_balance=cash,
            total_positions_value=total_position_value,
            currency="USD",
        )

        logger.info(
            "account_info_fetched",
            equity=info.total_equity,
            cash=info.cash_balance,
            positions_value=info.total_positions_value,
        )

        self._account_info_cache = info
        self._account_info_cache_ts = now

        return info

    async def get_broker_positions(self) -> list[dict[str, Any]]:
        """
        브로커에서 보유 종목 리스트 조회.

        Returns:
            각 종목의 상세 정보 리스트:
            - ticker, exchange, quantity, avg_price, current_price, pnl, etc.
        """
        balance = await self._rest.get_balance()
        raw_positions = balance.get("positions", [])

        result: list[dict[str, Any]] = []
        for pos in raw_positions:
            if not isinstance(pos, dict):
                continue
            qty = int(float(pos.get("ovrs_cblc_qty", 0)))
            if qty <= 0:
                continue

            result.append({
                "ticker": pos.get("ovrs_pdno", ""),
                "exchange": pos.get("ovrs_excg_cd", ""),
                "quantity": qty,
                "avg_price": float(pos.get("pchs_avg_pric", 0)),
                "current_price": float(pos.get("now_pric2", 0)),
                "eval_amount": float(pos.get("ovrs_stck_evlu_amt", 0)),
                "pnl_amount": float(pos.get("frcr_evlu_pfls_amt", 0)),
                "pnl_pct": float(pos.get("evlu_pfls_rt", 0)),
                "currency": pos.get("tr_crcy_cd", "USD"),
            })

        logger.info("broker_positions_fetched", count=len(result))
        return result

    async def sync_positions(self) -> dict[str, Any]:
        """
        브로커 보유 종목과 로컬 DB 포지션을 비교/동기화.

        - db_only → CLOSED 처리 (브로커에 없으므로 이미 청산됨)
        - broker_only → OPEN 포지션 신규 생성 (크래시 복구)
        - matched → 수량 불일치 시 DB 업데이트

        Returns:
            동기화 결과 dict
        """
        from datetime import datetime, timezone

        broker_positions = await self.get_broker_positions()
        broker_map = {p["ticker"]: p for p in broker_positions}
        broker_tickers = set(broker_map.keys())

        cursor = await self._db.conn.execute(
            "SELECT id, ticker, total_shares FROM positions WHERE status = 'OPEN'"
        )
        rows = await cursor.fetchall()
        db_map = {row[1]: {"id": row[0], "shares": row[2]} for row in rows}
        db_tickers = set(db_map.keys())

        matched = broker_tickers & db_tickers
        broker_only = broker_tickers - db_tickers
        db_only = db_tickers - broker_tickers

        now_str = datetime.now(timezone.utc).isoformat()
        fixed_db_only = 0
        fixed_broker_only = 0
        fixed_qty_mismatch = 0

        # ── db_only: DB에만 있고 브로커에 없음 → CLOSED 처리 ──
        for ticker in db_only:
            pos_info = db_map[ticker]
            await self._db.conn.execute(
                """UPDATE positions
                   SET status = 'CLOSED', closed_at = ?, close_reason = 'sync_broker_missing'
                   WHERE id = ?""",
                (now_str, pos_info["id"]),
            )
            fixed_db_only += 1
            logger.warning(
                "sync_closed_db_only",
                ticker=ticker,
                position_id=pos_info["id"],
                msg="브로커에 없는 포지션 → CLOSED 처리",
            )

        # ── broker_only: 브로커에만 있고 DB에 없음 → OPEN 생성 ──
        for ticker in broker_only:
            bp = broker_map[ticker]
            qty = bp["quantity"]
            avg_price = bp["avg_price"]
            total_cost = avg_price * qty
            # 스톱 가격은 10% 고정 (정확한 ATR 없으므로)
            stop_price = avg_price * 0.90

            cursor_insert = await self._db.conn.execute(
                """INSERT INTO positions
                   (ticker, system, status, total_shares, total_cost,
                    avg_entry_price, current_stop_price, n_at_entry,
                    sector, industry, opened_at)
                   VALUES (?, 'S1', 'OPEN', ?, ?, ?, ?, 0, ?, ?, ?)""",
                (ticker, qty, total_cost, avg_price, stop_price,
                 bp.get("sector"), bp.get("industry"), now_str),
            )
            new_pos_id = cursor_insert.lastrowid

            # 유닛도 함께 생성 (1유닛으로 통합)
            await self._db.conn.execute(
                """INSERT INTO units
                   (position_id, unit_number, entry_price, shares,
                    entry_stop_price, current_stop_price, entered_at)
                   VALUES (?, 1, ?, ?, ?, ?, ?)""",
                (new_pos_id, avg_price, qty, stop_price, stop_price, now_str),
            )

            fixed_broker_only += 1
            logger.warning(
                "sync_created_broker_only",
                ticker=ticker,
                quantity=qty,
                avg_price=avg_price,
                msg="DB에 없는 브로커 포지션 → OPEN + 유닛 생성",
            )

        # ── matched: 수량 불일치 시 DB 업데이트 ──
        for ticker in matched:
            db_shares = db_map[ticker]["shares"]
            broker_shares = broker_map[ticker]["quantity"]
            if db_shares != broker_shares:
                bp = broker_map[ticker]
                new_cost = bp["avg_price"] * broker_shares
                await self._db.conn.execute(
                    """UPDATE positions
                       SET total_shares = ?, total_cost = ?, avg_entry_price = ?
                       WHERE id = ?""",
                    (broker_shares, new_cost, bp["avg_price"], db_map[ticker]["id"]),
                )
                fixed_qty_mismatch += 1
                logger.warning(
                    "sync_qty_mismatch_fixed",
                    ticker=ticker,
                    db_shares=db_shares,
                    broker_shares=broker_shares,
                )

        # ── 유닛 없는 OPEN 포지션 복구 ──
        fixed_missing_units = 0
        unit_check = await self._db.conn.execute(
            """SELECT p.id, p.ticker, p.total_shares, p.avg_entry_price,
                      p.current_stop_price, p.opened_at
               FROM positions p
               LEFT JOIN units u ON u.position_id = p.id
               WHERE p.status = 'OPEN'
               GROUP BY p.id
               HAVING COUNT(u.id) = 0"""
        )
        missing_unit_rows = await unit_check.fetchall()
        for row in missing_unit_rows:
            pos_id, ticker, shares, avg_price, stop_price, opened_at = row
            await self._db.conn.execute(
                """INSERT INTO units
                   (position_id, unit_number, entry_price, shares,
                    entry_stop_price, current_stop_price, entered_at)
                   VALUES (?, 1, ?, ?, ?, ?, ?)""",
                (pos_id, avg_price, shares, stop_price, stop_price,
                 opened_at or now_str),
            )
            fixed_missing_units += 1
            logger.warning(
                "sync_created_missing_unit",
                ticker=ticker,
                position_id=pos_id,
                shares=shares,
                msg="유닛 없는 포지션에 복구 유닛 생성",
            )

        if fixed_db_only or fixed_broker_only or fixed_qty_mismatch or fixed_missing_units:
            await self._db.conn.commit()

        result = {
            "matched": len(matched),
            "broker_only": list(broker_only),
            "db_only": list(db_only),
            "fixed_db_only": fixed_db_only,
            "fixed_broker_only": fixed_broker_only,
            "fixed_qty_mismatch": fixed_qty_mismatch,
            "fixed_missing_units": fixed_missing_units,
        }

        if not broker_only and not db_only and not fixed_qty_mismatch:
            logger.info("sync_positions_ok", matched=len(matched))
        else:
            logger.info("sync_positions_reconciled", **result)

        return result
