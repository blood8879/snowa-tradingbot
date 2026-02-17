"""
Trades endpoint.

GET /api/trades — returns filled orders with pagination.
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, Query

from core.database import Database
from web.api.dependencies import get_db, verify_api_key

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["trades"])


@router.get("/trades", dependencies=[Depends(verify_api_key)])
async def get_trades(
    limit: int = Query(default=20, ge=1, le=100, description="Number of trades to return"),
    offset: int = Query(default=0, ge=0, description="Offset for pagination"),
    db: Database = Depends(get_db),
) -> dict:
    """Return filled orders with pagination.

    Args:
        limit: Maximum number of results (1-100).
        offset: Pagination offset.
        db: Database dependency.

    Returns:
        Dict with paginated filled orders and total count.
    """
    # Total count of filled orders
    count_cursor = await db.conn.execute(
        "SELECT COUNT(*) FROM orders WHERE status = 'FILLED'"
    )
    count_row = await count_cursor.fetchone()
    total = count_row[0] if count_row else 0

    # Fetch paginated filled orders
    cursor = await db.conn.execute(
        """
        SELECT id, broker_order_id, ticker, side, order_type,
               requested_shares, requested_price,
               filled_shares, filled_price,
               status, created_at, updated_at, filled_at, notes
        FROM orders
        WHERE status = 'FILLED'
        ORDER BY filled_at DESC
        LIMIT ? OFFSET ?
        """,
        (limit, offset),
    )
    rows = await cursor.fetchall()

    trades = [
        {
            "id": r[0],
            "broker_order_id": r[1],
            "ticker": r[2],
            "side": r[3],
            "order_type": r[4],
            "requested_shares": r[5],
            "requested_price": r[6],
            "filled_shares": r[7],
            "filled_price": r[8],
            "status": r[9],
            "created_at": r[10],
            "updated_at": r[11],
            "filled_at": r[12],
            "notes": r[13],
        }
        for r in rows
    ]

    return {
        "trades": trades,
        "total": total,
        "limit": limit,
        "offset": offset,
    }
