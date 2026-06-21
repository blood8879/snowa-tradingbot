"""Diagnostic: compare DB latest quarter vs yfinance latest quarter per ticker.

Detects the old freshness bug (yfinance has a newer quarter than the DB).
Read-only; safe to run while the bot is live (yfinance needs no broker auth).

Usage:
    python -m scripts.check_fundamental_freshness
"""

from __future__ import annotations

import asyncio

import yfinance as yf


def to_period(ts) -> str:
    q = (ts.month - 1) // 3 + 1
    return f"{ts.year}Q{q}"


async def main() -> None:
    from config.settings import get_settings
    from core.database import Database

    s = get_settings()
    db = Database(str(s.db_full_path))
    await db.initialize()

    cur = await db.conn.execute(
        "SELECT ticker FROM watchlist WHERE status='ACTIVE' AND market='US' "
        "UNION SELECT ticker FROM positions WHERE status='OPEN' AND market='US'"
    )
    tickers = sorted(r[0] for r in await cur.fetchall())

    stale = []
    print(f"{'ticker':8} {'DB':9} {'yfinance':9} status")
    for t in tickers:
        dbcur = await db.conn.execute(
            "SELECT MAX(period) FROM fundamentals WHERE ticker=? AND period_type='quarterly'",
            (t,),
        )
        db_q = (await dbcur.fetchone())[0]
        try:
            q = yf.Ticker(t).quarterly_income_stmt
            yf_q = to_period(max(q.columns)) if q is not None and not q.empty else None
        except Exception:
            yf_q = "ERR"

        status = "ok"
        if yf_q and yf_q != "ERR" and db_q and yf_q > db_q:
            status = "STALE  <-- yfinance has newer quarter"
            stale.append(t)
        print(f"{t:8} {str(db_q):9} {str(yf_q):9} {status}")

    print(f"\nSTALE tickers: {len(stale)} {stale}")
    await db.close()


if __name__ == "__main__":
    asyncio.run(main())
