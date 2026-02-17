"""
Performance / P&L endpoint.

GET /api/pnl — returns P&L data from daily_log for equity curve charting.
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, Query

from core.database import Database
from web.api.dependencies import get_db, verify_api_key

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["performance"])


@router.get("/pnl", dependencies=[Depends(verify_api_key)])
async def get_pnl(
    period: str = Query(
        default="daily",
        description="Aggregation period: daily, weekly, or monthly",
    ),
    db: Database = Depends(get_db),
) -> dict:
    """Return P&L data from daily_log for equity curve visualization.

    Args:
        period: One of 'daily', 'weekly', or 'monthly'.
        db: Database dependency.

    Returns:
        Dict with equity curve data points and summary statistics.
    """
    if period == "weekly":
        # Group by ISO week — use strftime to get Monday of each week
        cursor = await db.conn.execute(
            """
            SELECT
                strftime('%Y-W%W', date) AS period_key,
                MIN(date) AS period_start,
                MAX(date) AS period_end,
                SUM(daily_pnl) AS period_pnl,
                MAX(account_equity) AS ending_equity,
                MAX(max_drawdown_pct) AS max_drawdown_pct,
                SUM(entries_count) AS entries,
                SUM(exits_count) AS exits,
                SUM(stop_losses_count) AS stop_losses
            FROM daily_log
            GROUP BY strftime('%Y-W%W', date)
            ORDER BY period_start ASC
            """
        )
    elif period == "monthly":
        cursor = await db.conn.execute(
            """
            SELECT
                strftime('%Y-%m', date) AS period_key,
                MIN(date) AS period_start,
                MAX(date) AS period_end,
                SUM(daily_pnl) AS period_pnl,
                MAX(account_equity) AS ending_equity,
                MAX(max_drawdown_pct) AS max_drawdown_pct,
                SUM(entries_count) AS entries,
                SUM(exits_count) AS exits,
                SUM(stop_losses_count) AS stop_losses
            FROM daily_log
            GROUP BY strftime('%Y-%m', date)
            ORDER BY period_start ASC
            """
        )
    else:
        # Daily (default)
        cursor = await db.conn.execute(
            """
            SELECT
                date AS period_key,
                date AS period_start,
                date AS period_end,
                daily_pnl AS period_pnl,
                account_equity AS ending_equity,
                max_drawdown_pct,
                entries_count AS entries,
                exits_count AS exits,
                stop_losses_count AS stop_losses
            FROM daily_log
            ORDER BY date ASC
            """
        )

    rows = await cursor.fetchall()

    data_points = [
        {
            "period": r[0],
            "start": r[1],
            "end": r[2],
            "pnl": r[3],
            "equity": r[4],
            "max_drawdown_pct": r[5],
            "entries": r[6],
            "exits": r[7],
            "stop_losses": r[8],
        }
        for r in rows
    ]

    # Summary stats
    total_pnl = sum(d["pnl"] or 0.0 for d in data_points)
    max_equity = max((d["equity"] or 0.0 for d in data_points), default=0.0)
    max_drawdown = max((d["max_drawdown_pct"] or 0.0 for d in data_points), default=0.0)

    return {
        "period": period,
        "data": data_points,
        "summary": {
            "total_pnl": total_pnl,
            "max_equity": max_equity,
            "max_drawdown_pct": max_drawdown,
            "data_points": len(data_points),
        },
    }
