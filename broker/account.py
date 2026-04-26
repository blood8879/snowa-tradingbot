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
        self._account_info_cache_kr: AccountInfo | None = None
        self._account_info_cache_kr_ts: float = 0.0

    async def get_account_info(self, force: bool = False, *, market: str = "US") -> AccountInfo:
        """
        계좌 요약 정보 조회.

        US: inquire-psamount → 현금, inquire-balance → 포지션 평가 (USD)
        KR: domestic inquire-balance → summary의 예수금/평가금액 (KRW)

        Args:
            force: 캐시 무시 여부
            market: "US" 또는 "KR"

        Returns:
            AccountInfo: 총 평가액, 현금 잔고, 포지션 가치
        """
        if market == "KR":
            return await self._get_account_info_kr(force)
        return await self._get_account_info_us(force)

    async def _get_account_info_us(self, force: bool = False) -> AccountInfo:
        """US 계좌 정보 조회 (USD)."""
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
            cash = float(
                psamount.get("ord_psbl_frcr_amt")
                or psamount.get("frcr_ord_psbl_amt1")
                or 0
            )
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

        # 미체결 주문 예약금을 equity에 포함 (cash에서 차감되었으나 position에 미반영)
        pending_order_value = 0.0
        try:
            cursor = await self._db.conn.execute(
                "SELECT SUM(requested_shares * requested_price) FROM orders WHERE status = 'SUBMITTED' AND side = 'BUY' AND NOT (length(ticker) = 6 AND ticker GLOB '[0-9]*')"
            )
            row = await cursor.fetchone()
            if row and row[0]:
                pending_order_value = float(row[0])
        except Exception as exc:
            logger.warning("pending_order_value_failed", error=str(exc), exc_info=True)

        info = AccountInfo(
            total_equity=cash + total_position_value + pending_order_value,
            cash_balance=cash,
            total_positions_value=total_position_value,
            currency="USD",
        )

        logger.info(
            "account_info_fetched",
            market="US",
            equity=info.total_equity,
            cash=info.cash_balance,
            positions_value=info.total_positions_value,
        )

        self._account_info_cache = info
        self._account_info_cache_ts = now

        return info

    async def _get_account_info_kr(self, force: bool = False) -> AccountInfo:
        """KR 계좌 정보 조회 (KRW).

        국내주식 잔고 API (TTTC8434R) output2 summary:
        - dnca_tot_amt: 예수금총금액
        - scts_evlu_amt: 유가평가금액 (주식 평가)
        - tot_evlu_amt: 총평가금액
        - nass_amt: 순자산금액
        """
        now = time.monotonic()
        if not force and self._account_info_cache_kr is not None:
            ttl = (
                ACCOUNT_INFO_CACHE_TTL
                if self._account_info_cache_kr.total_equity > 0
                else ACCOUNT_INFO_FAIL_CACHE_TTL
            )
            if (now - self._account_info_cache_kr_ts) < ttl:
                return self._account_info_cache_kr

        cash = 0.0
        total_position_value = 0.0
        total_equity = 0.0

        try:
            balance = await self._rest.get_balance(market="KR")
            summary = balance.get("summary", {})

            # 예수금 (현금)
            cash = float(summary.get("dnca_tot_amt", 0))
            # 주식 평가금액
            total_position_value = float(summary.get("scts_evlu_amt", 0))
            # 총평가금액 (현금 + 주식)
            tot_evlu = float(summary.get("tot_evlu_amt", 0))
            total_equity = tot_evlu if tot_evlu > 0 else cash + total_position_value
        except Exception as exc:
            logger.warning("get_kr_balance_failed", error=str(exc), exc_info=True)

        # 미체결 주문 예약금을 equity에 포함
        pending_order_value = 0.0
        try:
            cursor = await self._db.conn.execute(
                "SELECT SUM(requested_shares * requested_price) FROM orders WHERE status = 'SUBMITTED' AND side = 'BUY' AND length(ticker) = 6 AND ticker GLOB '[0-9]*'"
            )
            row = await cursor.fetchone()
            if row and row[0]:
                pending_order_value = float(row[0])
        except Exception as exc:
            logger.warning("pending_order_value_kr_failed", error=str(exc), exc_info=True)

        total_equity += pending_order_value

        info = AccountInfo(
            total_equity=total_equity,
            cash_balance=cash,
            total_positions_value=total_position_value,
            currency="KRW",
        )

        logger.info(
            "account_info_fetched",
            market="KR",
            equity=info.total_equity,
            cash=info.cash_balance,
            positions_value=info.total_positions_value,
            currency="KRW",
        )

        self._account_info_cache_kr = info
        self._account_info_cache_kr_ts = now

        return info

    async def get_broker_positions(self, *, market: str = "US") -> list[dict[str, Any]]:
        """
        브로커에서 보유 종목 리스트 조회.

        Args:
            market: "US" (해외주식) 또는 "KR" (국내주식)

        Returns:
            각 종목의 상세 정보 리스트:
            - ticker, exchange, quantity, avg_price, current_price, pnl, etc.
        """
        if market == "KR":
            return await self._get_broker_positions_kr()
        return await self._get_broker_positions_us()

    async def _get_broker_positions_us(self) -> list[dict[str, Any]]:
        """US 해외주식 보유 종목 조회."""
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

        logger.info("broker_positions_fetched", market="US", count=len(result))
        return result

    async def _get_broker_positions_kr(self) -> list[dict[str, Any]]:
        """KR 국내주식 보유 종목 조회.

        TTTC8434R output1 필드:
        - pdno: 종목번호
        - prdt_name: 종목명
        - hldg_qty: 보유수량
        - pchs_avg_pric: 매입평균가격
        - prpr: 현재가
        - evlu_amt: 평가금액
        - evlu_pfls_amt: 평가손익금액
        - evlu_pfls_rt: 평가손익률
        """
        balance = await self._rest.get_balance(market="KR")
        raw_positions = balance.get("positions", [])

        result: list[dict[str, Any]] = []
        for pos in raw_positions:
            if not isinstance(pos, dict):
                continue
            qty = int(float(pos.get("hldg_qty", 0)))
            if qty <= 0:
                continue

            result.append({
                "ticker": pos.get("pdno", ""),
                "exchange": "KRX",
                "quantity": qty,
                "avg_price": float(pos.get("pchs_avg_pric", 0)),
                "current_price": float(pos.get("prpr", 0)),
                "eval_amount": float(pos.get("evlu_amt", 0)),
                "pnl_amount": float(pos.get("evlu_pfls_amt", 0)),
                "pnl_pct": float(pos.get("evlu_pfls_rt", 0)),
                "currency": "KRW",
            })

        logger.info("broker_positions_fetched", market="KR", count=len(result))
        return result

    async def sync_positions(self, *, market: str = "US") -> dict[str, Any]:
        """
        브로커 보유 종목과 로컬 DB 포지션을 비교/동기화.

        - db_only → CLOSED 처리 (브로커에 없으므로 이미 청산됨)
        - broker_only → OPEN 포지션 신규 생성 (크래시 복구)
        - matched → 수량 불일치 시 DB 업데이트

        Args:
            market: "US" 또는 "KR"

        Returns:
            동기화 결과 dict
        """
        from datetime import datetime, timezone

        broker_positions = await self.get_broker_positions(market=market)
        broker_map = {p["ticker"]: p for p in broker_positions}
        broker_tickers = set(broker_map.keys())

        cursor = await self._db.conn.execute(
            "SELECT id, ticker, total_shares, total_cost, avg_entry_price FROM positions WHERE status = 'OPEN' AND market = ?",
            (market,),
        )
        rows = await cursor.fetchall()
        db_map = {row[1]: {"id": row[0], "shares": row[2], "total_cost": row[3], "avg_entry_price": row[4]} for row in rows}
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
            total_cost = pos_info.get("total_cost", 0) or 0
            total_shares = pos_info.get("shares", 0) or 0

            # 체결가 추정: 마지막 SELL 주문의 체결가 → 없으면 손절가 → 없으면 None
            exit_price = None
            realized_pnl = None
            sell_cursor = await self._db.conn.execute(
                """SELECT filled_price FROM orders
                   WHERE ticker = ? AND side = 'SELL' AND status = 'FILLED'
                         AND filled_price > 0
                   ORDER BY filled_at DESC LIMIT 1""",
                (ticker,),
            )
            sell_row = await sell_cursor.fetchone()
            if sell_row and sell_row[0]:
                exit_price = sell_row[0]
            else:
                # 손절가를 exit_price 추정치로 사용
                stop_cursor = await self._db.conn.execute(
                    "SELECT current_stop_price FROM positions WHERE id = ?",
                    (pos_info["id"],),
                )
                stop_row = await stop_cursor.fetchone()
                if stop_row and stop_row[0]:
                    exit_price = stop_row[0]

            if exit_price and total_shares > 0 and total_cost > 0:
                realized_pnl = (exit_price * total_shares) - total_cost

            await self._db.conn.execute(
                """UPDATE positions
                   SET status = 'CLOSED', closed_at = ?, close_reason = 'sync_broker_missing',
                       realized_pnl = ?
                   WHERE id = ?""",
                (now_str, realized_pnl, pos_info["id"]),
            )
            fixed_db_only += 1
            logger.warning(
                "sync_closed_db_only",
                ticker=ticker,
                position_id=pos_info["id"],
                exit_price=exit_price,
                realized_pnl=realized_pnl,
                msg="브로커에 없는 포지션 → CLOSED 처리 (PnL 계산 포함)",
            )

        # ── broker_only: 브로커에만 있고 DB에 없음 → OPEN 생성 ──
        # ATR 기반 손절가 계산을 위한 import
        from data.price_cache import PriceCache
        from strategy.atr import calculate_n_from_ohlcv
        from strategy.stop_loss import calculate_stop_price

        price_cache = PriceCache(self._db)

        for ticker in broker_only:
            bp = broker_map[ticker]
            qty = bp["quantity"]
            avg_price = bp["avg_price"]
            total_cost = avg_price * qty

            # ATR(N) 조회 → 정확한 손절가 계산, 실패 시 10% fallback
            n_value = 0.0
            stop_price = avg_price * 0.90  # fallback
            try:
                exchange = bp.get("exchange", "NASD" if market == "US" else "KOSPI")
                bars = await price_cache.get_ohlcv(ticker, 60)
                if bars and len(bars) >= 20:
                    atr = calculate_n_from_ohlcv(bars)
                    if atr and atr > 0:
                        n_value = atr
                        stop_price = calculate_stop_price(avg_price, n_value)
                        logger.info(
                            "sync_stop_calculated_with_atr",
                            ticker=ticker,
                            avg_price=avg_price,
                            n_value=round(n_value, 4),
                            stop_price=round(stop_price, 4),
                        )
                import asyncio as _asyncio
                await _asyncio.sleep(1)  # KIS API rate limit
            except Exception:
                logger.warning(
                    "sync_atr_fetch_failed_using_fallback",
                    ticker=ticker,
                    stop_price=round(stop_price, 2),
                )

            cursor_insert = await self._db.conn.execute(
                """INSERT INTO positions
                   (ticker, system, status, total_shares, total_cost,
                    avg_entry_price, current_stop_price, n_at_entry,
                    sector, industry, opened_at, market)
                   VALUES (?, 'S1', 'OPEN', ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (ticker, qty, total_cost, avg_price, stop_price, n_value,
                 bp.get("sector"), bp.get("industry"), now_str, market),
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
                pos_id = db_map[ticker]["id"]

                # 수량 증가 시 누락된 피라미드 유닛 먼저 생성
                if broker_shares > db_shares:
                    unit_cursor = await self._db.conn.execute(
                        """SELECT SUM(shares), SUM(shares * entry_price),
                                  MAX(unit_number)
                           FROM units WHERE position_id = ?""",
                        (pos_id,),
                    )
                    unit_row = await unit_cursor.fetchone()
                    existing_unit_shares = unit_row[0] or 0
                    existing_unit_cost = unit_row[1] or 0.0
                    max_unit_number = unit_row[2] or 0

                    delta_shares = broker_shares - existing_unit_shares
                    if delta_shares > 0:
                        total_broker_cost = bp["avg_price"] * broker_shares
                        remainder = total_broker_cost - existing_unit_cost
                        delta_price = (
                            remainder / delta_shares
                            if remainder > 0
                            else bp["avg_price"]
                        )

                        stop_cursor = await self._db.conn.execute(
                            "SELECT current_stop_price FROM positions WHERE id = ?",
                            (pos_id,),
                        )
                        stop_row = await stop_cursor.fetchone()
                        stop_price = stop_row[0] if stop_row else bp["avg_price"] * 0.90

                        await self._db.conn.execute(
                            """INSERT INTO units
                               (position_id, unit_number, entry_price, shares,
                                entry_stop_price, current_stop_price, entered_at)
                               VALUES (?, ?, ?, ?, ?, ?, ?)""",
                            (pos_id, max_unit_number + 1,
                             round(delta_price, 4), delta_shares,
                             stop_price, stop_price, now_str),
                        )
                        logger.warning(
                            "sync_created_pyramid_unit",
                            ticker=ticker,
                            position_id=pos_id,
                            unit_number=max_unit_number + 1,
                            delta_shares=delta_shares,
                            inferred_price=round(delta_price, 4),
                            msg="수량 증가분에 대한 피라미드 유닛 생성",
                        )

                # 유닛 기반으로 total_cost 재계산 (브로커 avg_price는 수수료 포함
                # 등으로 실제 체결가와 다를 수 있으므로 유닛 데이터가 더 정확)
                recalc_cursor = await self._db.conn.execute(
                    "SELECT SUM(shares), SUM(shares * entry_price) FROM units WHERE position_id = ?",
                    (pos_id,),
                )
                recalc_row = await recalc_cursor.fetchone()
                unit_total_shares = recalc_row[0] or 0
                unit_total_cost = recalc_row[1] or 0.0

                # 유닛 데이터가 있으면 유닛 기반, 없으면 브로커 기반 fallback
                if unit_total_shares > 0:
                    new_shares = max(broker_shares, unit_total_shares)
                    new_cost = unit_total_cost
                    new_avg = new_cost / new_shares if new_shares > 0 else 0.0
                else:
                    new_shares = broker_shares
                    new_cost = bp["avg_price"] * broker_shares
                    new_avg = bp["avg_price"]

                await self._db.conn.execute(
                    """UPDATE positions
                       SET total_shares = ?, total_cost = ?, avg_entry_price = ?
                       WHERE id = ?""",
                    (new_shares, new_cost, new_avg, pos_id),
                )

                fixed_qty_mismatch += 1
                logger.warning(
                    "sync_qty_mismatch_fixed",
                    ticker=ticker,
                    db_shares=db_shares,
                    broker_shares=broker_shares,
                )

        # ── 유닛 수량 부족 복구 (유닛 없음 + 수량 불일치 모두 처리) ──
        fixed_missing_units = 0
        unit_check = await self._db.conn.execute(
            """SELECT p.id, p.ticker, p.total_shares, p.avg_entry_price,
                      p.current_stop_price, p.opened_at,
                      COALESCE(SUM(u.shares), 0) AS unit_shares,
                      COALESCE(SUM(u.shares * u.entry_price), 0) AS unit_cost,
                      COALESCE(MAX(u.unit_number), 0) AS max_unit
               FROM positions p
               LEFT JOIN units u ON u.position_id = p.id
               WHERE p.status = 'OPEN'
               GROUP BY p.id
               HAVING unit_shares < p.total_shares"""
        )
        missing_unit_rows = await unit_check.fetchall()
        for row in missing_unit_rows:
            pos_id = row[0]
            ticker = row[1]
            total_shares = row[2]
            avg_price = row[3]
            stop_price = row[4]
            opened_at = row[5]
            unit_shares = row[6]
            unit_cost = row[7]
            max_unit = row[8]

            delta_shares = total_shares - unit_shares

            if max_unit == 0:
                # 유닛이 하나도 없음 → unit_number=1로 전체 생성
                await self._db.conn.execute(
                    """INSERT INTO units
                       (position_id, unit_number, entry_price, shares,
                        entry_stop_price, current_stop_price, entered_at)
                       VALUES (?, 1, ?, ?, ?, ?, ?)""",
                    (pos_id, avg_price, total_shares, stop_price, stop_price,
                     opened_at or now_str),
                )
                fixed_missing_units += 1
                logger.warning(
                    "sync_created_missing_unit",
                    ticker=ticker,
                    position_id=pos_id,
                    shares=total_shares,
                    msg="유닛 없는 포지션에 복구 유닛 생성",
                )
            else:
                # 유닛 있지만 수량 부족 → 피라미드 유닛 추가
                total_position_cost = avg_price * total_shares
                remainder = total_position_cost - unit_cost
                delta_price = (
                    remainder / delta_shares
                    if remainder > 0
                    else avg_price
                )

                await self._db.conn.execute(
                    """INSERT INTO units
                       (position_id, unit_number, entry_price, shares,
                        entry_stop_price, current_stop_price, entered_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (pos_id, max_unit + 1, round(delta_price, 4),
                     delta_shares, stop_price, stop_price, now_str),
                )
                fixed_missing_units += 1
                logger.warning(
                    "sync_created_deficit_unit",
                    ticker=ticker,
                    position_id=pos_id,
                    unit_number=max_unit + 1,
                    delta_shares=delta_shares,
                    inferred_price=round(delta_price, 4),
                    msg="유닛 수량 부족분에 대한 피라미드 유닛 생성",
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
            logger.info("sync_positions_ok", market=market, matched=len(matched))
        else:
            logger.info("sync_positions_reconciled", market=market, **result)

        return result
