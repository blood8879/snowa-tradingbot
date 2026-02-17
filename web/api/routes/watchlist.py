"""
Watchlist endpoint.

GET /api/watchlist — returns active watchlist stocks sorted by composite score.
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends

from core.database import Database
from strategy.atr import calculate_n_single
from web.api.dependencies import get_db, verify_api_key

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["watchlist"])


async def _calc_n_value(db: Database, ticker: str) -> float | None:
    """Calculate latest N (ATR-20) for a ticker from daily_prices."""
    cursor = await db.conn.execute(
        """
        SELECT high, low, close
        FROM daily_prices
        WHERE ticker = ?
        ORDER BY date ASC
        """,
        (ticker,),
    )
    rows = await cursor.fetchall()

    if len(rows) < 21:
        return None

    # Use last 50 bars for EMA convergence (or all if fewer)
    bars = rows[-50:] if len(rows) >= 50 else rows
    highs = [r[0] for r in bars]
    lows = [r[1] for r in bars]
    closes = [r[2] for r in bars]

    n = calculate_n_single(highs, lows, closes)
    return round(n, 4) if n is not None else None


async def _calc_avg_volume_50d(db: Database, ticker: str) -> float | None:
    """Calculate 50-day average volume for a ticker."""
    cursor = await db.conn.execute(
        """
        SELECT AVG(volume) FROM (
            SELECT volume FROM daily_prices
            WHERE ticker = ? AND volume IS NOT NULL
            ORDER BY date DESC
            LIMIT 50
        )
        """,
        (ticker,),
    )
    row = await cursor.fetchone()
    return round(row[0]) if row and row[0] is not None else None


@router.get("/watchlist", dependencies=[Depends(verify_api_key)])
async def get_watchlist(db: Database = Depends(get_db)) -> dict:
    """Return active watchlist stocks sorted by composite score (descending).

    Returns:
        Dict with list of watchlist stocks and count.
    """
    cursor = await db.conn.execute(
        """
        SELECT w.ticker, w.added_date, w.last_screened,
               w.quarterly_eps_growth, w.annual_eps_cagr,
               w.rs_rating, w.institutional_holders,
               w.institutional_change_pct, w.custom_composite_score,
               w.minervini_pass,
               w.sector, w.industry, w.avg_daily_volume, w.market_cap,
               w.status,
               COALESCE(w.latest_price, dp.close) AS latest_price
        FROM watchlist w
        LEFT JOIN (
            SELECT ticker, close,
                   ROW_NUMBER() OVER (PARTITION BY ticker ORDER BY date DESC) AS rn
            FROM daily_prices
        ) dp ON dp.ticker = w.ticker AND dp.rn = 1
        WHERE w.status = 'ACTIVE'
        ORDER BY w.custom_composite_score DESC NULLS LAST
        """
    )
    rows = await cursor.fetchall()

    stocks = []
    for r in rows:
        ticker = r[0]
        n_value = await _calc_n_value(db, ticker)
        avg_volume_50d = await _calc_avg_volume_50d(db, ticker)

        stocks.append({
            "ticker": ticker,
            "added_date": r[1],
            "last_screened": r[2],
            "quarterly_eps_growth": r[3],
            "annual_eps_cagr": r[4],
            "rs_rating": r[5],
            "institutional_holders": r[6],
            "institutional_change_pct": r[7],
            "custom_composite_score": r[8],
            "minervini_pass": bool(r[9]),
            "sector": r[10],
            "industry": r[11],
            "avg_daily_volume": r[12],
            "market_cap": r[13],
            "status": r[14],
            "latest_price": r[15],
            "n_value": n_value,
            "avg_volume_50d": avg_volume_50d,
        })

    return {"watchlist": stocks, "count": len(stocks)}
