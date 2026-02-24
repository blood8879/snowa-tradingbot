"""
Watchlist endpoint.

GET /api/watchlist — returns active watchlist stocks sorted by composite score.
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends

from broker.account import AccountManager
from core.database import Database
from portfolio.position_sizer import calculate_unit_shares, calculate_max_position_value
from strategy.atr import calculate_n_single
from web.api.dependencies import get_db, get_account_manager, verify_api_key

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
async def get_watchlist(
    db: Database = Depends(get_db),
    account_mgr: AccountManager | None = Depends(get_account_manager),
) -> dict:
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
               COALESCE(w.latest_price, dp.close) AS latest_price,
               f.latest_report_date
        FROM watchlist w
        LEFT JOIN (
            SELECT ticker, close,
                   ROW_NUMBER() OVER (PARTITION BY ticker ORDER BY date DESC) AS rn
            FROM daily_prices
        ) dp ON dp.ticker = w.ticker AND dp.rn = 1
        LEFT JOIN (
            SELECT ticker, MAX(report_date) AS latest_report_date
            FROM fundamentals
            GROUP BY ticker
        ) f ON f.ticker = w.ticker
        WHERE w.status = 'ACTIVE'
        ORDER BY w.custom_composite_score DESC NULLS LAST
        """
    )
    rows = await cursor.fetchall()

    # 실시간 계좌 equity 조회 (유닛 사이징 계산용)
    account_equity = 0.0
    if account_mgr is not None:
        try:
            info = await account_mgr.get_account_info()
            account_equity = info.total_equity
        except Exception as exc:
            logger.warning("watchlist_equity_fetch_failed", error=str(exc))

    max_position_value = (
        round(calculate_max_position_value(account_equity), 2)
        if account_equity > 0
        else None
    )

    stocks = []
    for r in rows:
        ticker = r[0]
        latest_price = r[15]
        n_value = await _calc_n_value(db, ticker)
        avg_volume_50d = await _calc_avg_volume_50d(db, ticker)

        # 1유닛 사이징 계산
        unit_shares = None
        unit_value = None
        unit_stop_price = None
        if account_equity > 0 and n_value and latest_price and latest_price > 0:
            sizing = calculate_unit_shares(
                account_equity=account_equity,
                entry_price=latest_price,
                n_value=n_value,
                avg_daily_volume=int(avg_volume_50d) if avg_volume_50d else None,
            )
            if not sizing.get("skip"):
                unit_shares = sizing["shares"]
                unit_value = round(sizing["position_value"], 2)
                unit_stop_price = round(sizing["stop_price"], 2)

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
            "latest_price": latest_price,
            "latest_financial_date": r[16],
            "n_value": n_value,
            "avg_volume_50d": avg_volume_50d,
            "unit_shares": unit_shares,
            "unit_value": unit_value,
            "unit_stop_price": unit_stop_price,
            "max_position_value": max_position_value,
        })

    return {
        "watchlist": stocks,
        "count": len(stocks),
        "account_equity": round(account_equity, 2) if account_equity > 0 else None,
    }
