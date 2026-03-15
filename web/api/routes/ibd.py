"""IBD Market Direction API endpoint."""
from __future__ import annotations
import structlog
from fastapi import APIRouter, Depends, Query
from config.constants import IBD_INDEXES_US, IBD_INDEXES_KR
from core.database import Database
from web.api.dependencies import get_db, verify_api_key

logger = structlog.get_logger(__name__)
router = APIRouter(tags=["ibd"])

_KR_NAMES = {"069500": "KODEX200", "229200": "KOSDAQ150"}

STATUS_RANK = {
    "CONFIRMED_UPTREND": 0,
    "UPTREND_UNDER_PRESSURE": 1,
    "RALLY_ATTEMPT": 2,
    "MARKET_IN_CORRECTION": 3,
}


def _display_name(ticker: str) -> str:
    return _KR_NAMES.get(ticker, ticker)


@router.get("/ibd/status", dependencies=[Depends(verify_api_key)])
async def get_ibd_status(
    db: Database = Depends(get_db),
    market: str = Query(default="US"),
) -> dict:
    """Get latest IBD market direction status for the specified market."""
    indexes = IBD_INDEXES_US if market == "US" else IBD_INDEXES_KR
    placeholders = ",".join("?" for _ in indexes)

    cursor = await db.conn.execute(f"""
        SELECT index_ticker, date, status, distribution_count, rally_day_count,
               ftd_date, ftd_low, notes
        FROM ibd_market_direction
        WHERE index_ticker IN ({placeholders})
          AND date = (
            SELECT MAX(date) FROM ibd_market_direction
            WHERE index_ticker IN ({placeholders})
          )
        ORDER BY index_ticker
    """, (*indexes, *indexes))
    states = []
    for row in await cursor.fetchall():
        states.append({
            "index_ticker": row[0],
            "display_name": _display_name(row[0]),
            "date": row[1],
            "status": row[2],
            "distribution_count": row[3],
            "rally_day_count": row[4],
            "ftd_date": row[5],
            "ftd_low": row[6],
            "notes": row[7],
        })

    overall = "MARKET_IN_CORRECTION"
    if states:
        overall = max(states, key=lambda s: STATUS_RANK.get(s["status"], 0))["status"]

    return {"overall_status": overall, "indexes": states, "market": market}


@router.get("/ibd/distribution-days", dependencies=[Depends(verify_api_key)])
async def get_ibd_distribution_days(
    db: Database = Depends(get_db),
    market: str = Query(default="US"),
    active_only: bool = Query(default=True),
) -> dict:
    """Get distribution/stalling/FTD day records for the specified market."""
    indexes = IBD_INDEXES_US if market == "US" else IBD_INDEXES_KR
    placeholders = ",".join("?" for _ in indexes)
    expired_filter = "AND expired = 0" if active_only else ""

    cursor = await db.conn.execute(f"""
        SELECT index_ticker, date, day_type, close_price, price_change_pct,
               volume, prior_volume, expired, expiry_reason, expiry_date
        FROM ibd_distribution_days
        WHERE index_ticker IN ({placeholders}) {expired_filter}
        ORDER BY date DESC
        LIMIT 50
    """, indexes)
    days = []
    for row in await cursor.fetchall():
        days.append({
            "index_ticker": row[0],
            "display_name": _display_name(row[0]),
            "date": row[1],
            "day_type": row[2],
            "close_price": row[3],
            "price_change_pct": row[4],
            "volume": row[5],
            "prior_volume": row[6],
            "expired": bool(row[7]),
            "expiry_reason": row[8],
            "expiry_date": row[9],
        })
    return {"distribution_days": days, "market": market}


@router.get("/ibd/history", dependencies=[Depends(verify_api_key)])
async def get_ibd_history(
    db: Database = Depends(get_db),
    market: str = Query(default="US"),
    days: int = Query(default=30, le=90),
) -> dict:
    """Get IBD state history for charting."""
    indexes = IBD_INDEXES_US if market == "US" else IBD_INDEXES_KR
    placeholders = ",".join("?" for _ in indexes)

    cursor = await db.conn.execute(f"""
        SELECT date, index_ticker, status, distribution_count, rally_day_count
        FROM ibd_market_direction
        WHERE index_ticker IN ({placeholders})
        ORDER BY date DESC
        LIMIT ?
    """, (*indexes, days * len(indexes)))
    history = []
    for row in await cursor.fetchall():
        history.append({
            "date": row[0],
            "index_ticker": row[1],
            "display_name": _display_name(row[1]),
            "status": row[2],
            "distribution_count": row[3],
            "rally_day_count": row[4],
        })
    return {"history": history, "market": market}
