"""
Positions endpoint.

GET /api/positions — returns open positions with their units.

Merges:
  1. DB positions (from bot's internal tracking)
  2. Broker positions (from KIS API live query)

Broker-only positions (not tracked by the bot) are shown with
source="broker" so the dashboard can display them separately.
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends

from broker.account import AccountManager
from core.database import Database
from web.api.dependencies import get_db, get_account_manager, verify_api_key

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["positions"])


async def _fetch_db_positions(db: Database) -> list[dict]:
    """Fetch open positions from the bot's internal DB."""
    cursor = await db.conn.execute(
        """
        SELECT id, ticker, system, status,
               total_shares, total_cost, avg_entry_price,
               current_stop_price, n_at_entry,
               sector, industry,
               opened_at, closed_at, close_reason, realized_pnl
        FROM positions
        WHERE status = 'OPEN'
        ORDER BY opened_at DESC
        """
    )
    position_rows = await cursor.fetchall()

    positions: list[dict] = []
    for p in position_rows:
        position_id = p[0]

        # Fetch units for this position
        unit_cursor = await db.conn.execute(
            """
            SELECT id, unit_number, entry_price, shares,
                   entry_stop_price, current_stop_price, entered_at
            FROM units
            WHERE position_id = ?
            ORDER BY unit_number ASC
            """,
            (position_id,),
        )
        unit_rows = await unit_cursor.fetchall()

        units = [
            {
                "id": u[0],
                "unit_number": u[1],
                "entry_price": u[2],
                "shares": u[3],
                "entry_stop_price": u[4],
                "current_stop_price": u[5],
                "entered_at": u[6],
            }
            for u in unit_rows
        ]

        positions.append({
            "id": position_id,
            "ticker": p[1],
            "system": p[2],
            "status": p[3],
            "total_shares": p[4],
            "total_cost": p[5],
            "avg_entry_price": p[6],
            "current_stop_price": p[7],
            "n_at_entry": p[8],
            "sector": p[9],
            "industry": p[10],
            "opened_at": p[11],
            "closed_at": p[12],
            "close_reason": p[13],
            "realized_pnl": p[14],
            "units": units,
            "source": "bot",
        })

    return positions


async def _fetch_broker_positions(
    account_mgr: AccountManager | None,
) -> list[dict]:
    """Fetch positions directly from the KIS broker API."""
    if account_mgr is None:
        return []
    try:
        broker_positions = await account_mgr.get_broker_positions()
    except Exception:
        logger.warning("broker_positions_fetch_failed", exc_info=True)
        return []

    result: list[dict] = []
    for bp in broker_positions:
        result.append({
            "ticker": bp["ticker"],
            "exchange": bp.get("exchange", ""),
            "quantity": bp["quantity"],
            "avg_price": bp["avg_price"],
            "current_price": bp["current_price"],
            "eval_amount": bp["eval_amount"],
            "pnl_amount": bp["pnl_amount"],
            "pnl_pct": bp["pnl_pct"],
            "currency": bp.get("currency", "USD"),
        })
    return result


@router.get("/positions", dependencies=[Depends(verify_api_key)])
async def get_positions(
    db: Database = Depends(get_db),
    account_mgr: AccountManager | None = Depends(get_account_manager),
) -> dict:
    """Return all open positions from bot DB and broker.

    Returns:
        Dict with:
        - positions: bot-tracked positions with nested units
        - broker_positions: live positions from the broker API
        - count: total bot-tracked positions
        - broker_count: total broker positions
    """
    db_positions = await _fetch_db_positions(db)

    # Tickers already tracked by the bot
    db_tickers = {p["ticker"] for p in db_positions}

    broker_positions = await _fetch_broker_positions(account_mgr)

    # 브로커 데이터를 ticker 기준으로 인덱싱
    broker_by_ticker = {bp["ticker"]: bp for bp in broker_positions}

    # Bot 포지션에 미실현 손익(현재가, 평가금액, P&L) 병합
    for pos in db_positions:
        bp = broker_by_ticker.get(pos["ticker"])
        if bp:
            pos["current_price"] = bp["current_price"]
            pos["eval_amount"] = bp["eval_amount"]
            pos["unrealized_pnl"] = bp["pnl_amount"]
            pos["unrealized_pnl_pct"] = bp["pnl_pct"]
        else:
            pos["current_price"] = None
            pos["eval_amount"] = None
            pos["unrealized_pnl"] = None
            pos["unrealized_pnl_pct"] = None

    # Mark broker positions that are NOT tracked by the bot
    broker_only = [
        bp for bp in broker_positions if bp["ticker"] not in db_tickers
    ]

    return {
        "positions": db_positions,
        "broker_positions": broker_only,
        "count": len(db_positions),
        "broker_count": len(broker_only),
    }
