"""
Watchlist endpoint.

GET /api/watchlist — returns active watchlist stocks sorted by composite score.
"""

from __future__ import annotations

import csv
from pathlib import Path

import structlog
from fastapi import APIRouter, Depends, Query

from broker.account import AccountManager
from core.database import Database
from portfolio.position_sizer import calculate_unit_shares, calculate_max_position_value
from strategy.atr import calculate_n_single
from web.api.dependencies import get_db, get_account_manager, verify_api_key

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["watchlist"])


def _load_kr_stock_names() -> dict[str, str]:
    """Load KR stock names from universe cache CSV."""
    cache_path = Path("data/universe_kr_cache.csv")
    names: dict[str, str] = {}
    if not cache_path.exists():
        return names
    try:
        with open(cache_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                names[row["ticker"]] = row["name"]
    except Exception:
        pass
    return names


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


@router.get("/watchlist/history", dependencies=[Depends(verify_api_key)])
async def get_watchlist_history(
    market: str = Query(default="US", description="Market filter (US, KR, ALL)"),
    limit: int = Query(default=100, description="Max records to return"),
    db: Database = Depends(get_db),
) -> dict:
    """Return watchlist add/remove history."""
    params: list = []
    market_clause = ""
    if market and market != "ALL":
        market_clause = "AND market = ?"
        params.append(market)
    params.append(limit)

    cursor = await db.conn.execute(
        f"""
        SELECT id, ticker, name, market, action, reason,
               quarterly_eps_growth, annual_eps_cagr, rs_rating,
               composite_score, minervini_pass, recorded_at
        FROM watchlist_history
        WHERE 1=1 {market_clause}
        ORDER BY recorded_at DESC
        LIMIT ?
        """,
        params,
    )
    rows = await cursor.fetchall()

    # KR 종목명 CSV fallback
    kr_names = _load_kr_stock_names() if market in ("KR", "ALL") else {}

    history = []
    for r in rows:
        name = r[2] or kr_names.get(r[1])
        history.append({
            "id": r[0],
            "ticker": r[1],
            "name": name,
            "market": r[3],
            "action": r[4],
            "reason": r[5],
            "quarterly_eps_growth": r[6],
            "annual_eps_cagr": r[7],
            "rs_rating": r[8],
            "composite_score": r[9],
            "minervini_pass": bool(r[10]) if r[10] is not None else None,
            "recorded_at": r[11],
        })

    return {
        "history": history,
        "total": len(history),
        "market": market,
    }


@router.get("/watchlist", dependencies=[Depends(verify_api_key)])
async def get_watchlist(
    market: str = Query(default="US", description="Market filter"),
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
               w.latest_price,
               f.latest_report_date
        FROM watchlist w
        LEFT JOIN (
            SELECT ticker, MAX(report_date) AS latest_report_date
            FROM fundamentals
            GROUP BY ticker
        ) f ON f.ticker = w.ticker
        WHERE w.status = 'ACTIVE' AND w.market = ?
        ORDER BY w.custom_composite_score DESC NULLS LAST
        """,
        (market,),
    )
    rows = await cursor.fetchall()

    # 실시간 계좌 equity 조회 (유닛 사이징 계산용)
    # US → USD 잔고, KR → KRW 잔고 (각 시장별 별도 조회)
    account_equity = 0.0
    if account_mgr is not None:
        try:
            info = await account_mgr.get_account_info(market=market)
            account_equity = info.total_equity
        except Exception as exc:
            logger.warning("watchlist_equity_fetch_failed", error=str(exc), market=market)

    max_position_value = (
        round(calculate_max_position_value(account_equity), 2)
        if account_equity > 0
        else None
    )

    # KR 종목명 로드
    kr_names = _load_kr_stock_names() if market == "KR" else {}

    # ── Batch fetch last 50 bars for all tickers (single SQL) ──
    tickers = [r[0] for r in rows]
    n_values: dict[str, float | None] = {}
    avg_volumes: dict[str, float | None] = {}
    bars_by_ticker: dict[str, list] = {}
    if tickers:
        placeholders = ",".join("?" * len(tickers))
        bars_cursor = await db.conn.execute(
            f"""
            SELECT ticker, high, low, close, volume
            FROM (
                SELECT ticker, high, low, close, volume,
                       ROW_NUMBER() OVER (PARTITION BY ticker ORDER BY date DESC) AS rn
                FROM daily_prices
                WHERE ticker IN ({placeholders})
            )
            WHERE rn <= 50
            ORDER BY ticker, rn DESC
            """,
            tickers,
        )
        bars_rows = await bars_cursor.fetchall()
        for br in bars_rows:
            bars_by_ticker.setdefault(br[0], []).append(br)
        for ticker, bars in bars_by_ticker.items():
            if len(bars) >= 21:
                highs = [b[1] for b in bars]
                lows = [b[2] for b in bars]
                closes = [b[3] for b in bars]
                n = calculate_n_single(highs, lows, closes)
                n_values[ticker] = round(n, 4) if n is not None else None
            else:
                n_values[ticker] = None
            volumes = [b[4] for b in bars if b[4] is not None]
            avg_volumes[ticker] = round(sum(volumes) / len(volumes)) if volumes else None

    stocks = []
    for r in rows:
        ticker = r[0]
        latest_price = r[15]
        if latest_price is None:
            bars = bars_by_ticker.get(ticker)
            if bars:
                latest_price = bars[-1][3]
        n_value = n_values.get(ticker)
        avg_volume_50d = avg_volumes.get(ticker)

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
                market=market,
            )
            if not sizing.get("skip"):
                unit_shares = sizing["shares"]
                unit_value = round(sizing["position_value"], 2)
                unit_stop_price = round(sizing["stop_price"], 2)

        stock_name = kr_names.get(ticker) if market == "KR" else None

        stocks.append({
            "ticker": ticker,
            "name": stock_name,
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
            "market": market,
        })

    return {
        "watchlist": stocks,
        "count": len(stocks),
        "account_equity": round(account_equity, 2) if account_equity > 0 else None,
        "market": market,
    }
