"""
System status endpoint.

GET /api/status — returns current bot mode, market filter state,
SPY data, position/unit counts, equity, and WebSocket status.
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, Query

from broker.account import AccountManager
from core.database import Database
from web.api.dependencies import get_db, get_account_manager, verify_api_key
from web.api.routes.market_filter_calc import compute_market_filter

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["status"])


async def _get_live_equity(
    account_mgr: AccountManager | None,
    db: Database,
    market: str = "US",
) -> tuple[float, float, float]:
    """Try live broker query first, fall back to daily_log."""
    if account_mgr is not None:
        try:
            info = await account_mgr.get_account_info(market=market)
            return info.total_equity, info.cash_balance, info.total_positions_value
        except Exception as exc:
            logger.warning("live_equity_fetch_failed", error=str(exc), exc_info=True)
    else:
        logger.warning("account_manager_not_available")

    cursor = await db.conn.execute(
        "SELECT account_equity FROM daily_log WHERE market = ? ORDER BY date DESC LIMIT 1",
        (market,),
    )
    row = await cursor.fetchone()
    equity = row[0] if row and row[0] is not None else 0.0
    if equity == 0.0:
        logger.warning("equity_fallback_zero", has_daily_log=row is not None)
    return equity, 0.0, 0.0


@router.get("/status", dependencies=[Depends(verify_api_key)])
async def get_status(
    db: Database = Depends(get_db),
    account_mgr: AccountManager | None = Depends(get_account_manager),
    market: str = Query(default="US", description="Market filter: US or KR"),
) -> dict:
    mode = await db.get_state("trading_mode") or "paper"
    ws_us = await db.get_state("ws_status") or "DISCONNECTED"
    ws_kr = await db.get_state("ws_kr_status") or "DISCONNECTED"
    ws_status = "CONNECTED" if ws_us == "CONNECTED" or ws_kr == "CONNECTED" else "DISCONNECTED"

    mf = await compute_market_filter(market)
    benchmark_name = mf.get("benchmark", "SPY")
    benchmark_close = mf["close"]
    benchmark_sma200 = mf["sma200"]
    market_filter_pass = mf["filter_pass"] or False
    market_filter = mf.get("label", "—")
    regime = mf.get("regime", "GREEN")
    regime_scale = mf.get("regime_scale", 1.0)
    breadth_pct = mf.get("breadth_pct")
    roc = mf.get("roc")

    account_equity, cash_balance, positions_value = await _get_live_equity(
        account_mgr, db, market=market,
    )

    pos_cursor = await db.conn.execute(
        "SELECT COUNT(*) FROM positions WHERE status = 'OPEN' AND market = ?",
        (market,)
    )
    pos_row = await pos_cursor.fetchone()
    open_positions = pos_row[0] if pos_row else 0

    unit_cursor = await db.conn.execute(
        """
        SELECT COUNT(*) FROM units u
        JOIN positions p ON u.position_id = p.id
        WHERE p.status = 'OPEN' AND p.market = ?
        """,
        (market,)
    )
    unit_row = await unit_cursor.fetchone()
    open_units = unit_row[0] if unit_row else 0

    return {
        "mode": mode,
        "market": market,
        "market_filter": market_filter,
        "market_filter_pass": market_filter_pass,
        "regime": regime,
        "regime_scale": regime_scale,
        "breadth_pct": breadth_pct,
        "roc": roc,
        "benchmark": {
            "name": benchmark_name,
            "close": benchmark_close,
            "sma200": benchmark_sma200,
        },
        "positions": open_positions,
        "units": open_units,
        "account_equity": account_equity,
        "cash_balance": cash_balance,
        "positions_value": positions_value,
        "ws_status": ws_status,
    }
