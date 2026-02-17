"""
계좌 관리 모듈.

기능:
- 계좌 잔고/평가액 조회
- 보유 종목 → Position 동기화
- 브로커 잔고 vs 로컬 DB 불일치 감지
"""

from __future__ import annotations

from typing import Any

import structlog

from broker.kis_rest import KISRestClient
from core.database import Database
from core.models import AccountInfo

logger = structlog.get_logger(__name__)


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

    async def get_account_info(self) -> AccountInfo:
        """
        계좌 요약 정보 조회.

        inquire-psamount API로 현금 잔고를 조회하고,
        inquire-balance API로 보유 종목 평가액을 조회하여 합산.

        Returns:
            AccountInfo: 총 평가액, 현금 잔고, 포지션 가치
        """
        # 1) 현금 잔고: inquire-psamount (매수 가능 금액 조회)
        #    inquire-balance는 보유 종목이 없으면 현금 정보를 반환하지 않으므로
        #    반드시 inquire-psamount를 사용해야 함.
        cash = 0.0
        try:
            psamount = await self._rest.get_purchasable_amount()
            cash = float(psamount.get("ord_psbl_frcr_amt", 0))
        except Exception:
            logger.warning("get_purchasable_amount_failed", exc_info=True)

        # 2) 보유 종목 평가액: inquire-balance
        total_position_value = 0.0
        try:
            balance = await self._rest.get_balance()
            positions = balance.get("positions", [])
            for pos in positions:
                if not isinstance(pos, dict):
                    continue
                eval_amt = float(pos.get("ovrs_stck_evlu_amt", 0))
                total_position_value += eval_amt
        except Exception:
            logger.warning("get_balance_failed", exc_info=True)

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

        봇 재시작, 크래시 복구 시 호출.

        Returns:
            동기화 결과: {"matched": N, "broker_only": [...], "db_only": [...]}
        """
        broker_positions = await self.get_broker_positions()
        broker_tickers = {p["ticker"] for p in broker_positions}

        # DB에서 OPEN 포지션 조회
        cursor = await self._db.conn.execute(
            "SELECT ticker FROM positions WHERE status = 'OPEN'"
        )
        rows = await cursor.fetchall()
        db_tickers = {row[0] for row in rows}

        matched = broker_tickers & db_tickers
        broker_only = broker_tickers - db_tickers
        db_only = db_tickers - broker_tickers

        result = {
            "matched": len(matched),
            "broker_only": list(broker_only),
            "db_only": list(db_only),
        }

        if broker_only:
            logger.warning(
                "sync_broker_only",
                tickers=list(broker_only),
                msg="브로커에만 존재하는 포지션 (DB에 없음)",
            )
        if db_only:
            logger.warning(
                "sync_db_only",
                tickers=list(db_only),
                msg="DB에만 존재하는 포지션 (브로커에 없음)",
            )
        if not broker_only and not db_only:
            logger.info("sync_positions_ok", matched=len(matched))

        return result
