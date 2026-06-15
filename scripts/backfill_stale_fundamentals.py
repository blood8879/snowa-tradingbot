"""One-off remediation: backfill fundamentals + regenerate LLM reports for
ACTIVE watchlist tickers that are stuck on an old financial quarter.

Background: SCREENING_MAX_STALE_FUNDAMENTAL_TARGETS=0 on the live server had
disabled the entire stale-refresh path, so any US ticker missed by the 3-day
earnings-calendar window stayed frozen on its prior quarter (e.g. MRX on
2025Q4 while yfinance already had 2026Q1). This script corrects the currently
frozen watchlist names immediately, rather than waiting for the next daily run.

Usage:
    python -m scripts.backfill_stale_fundamentals [US|KR]   (default: US)
"""

from __future__ import annotations

import asyncio
import sys

import structlog

structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.dev.ConsoleRenderer(),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(0),
)

logger = structlog.get_logger(__name__)


async def _latest_quarter(db, ticker: str) -> str | None:
    cur = await db.conn.execute(
        """
        SELECT period FROM fundamentals
        WHERE ticker = ? AND period_type = 'quarterly'
        ORDER BY period DESC LIMIT 1
        """,
        (ticker,),
    )
    row = await cur.fetchone()
    return row[0] if row else None


async def main() -> None:
    market = (sys.argv[1].upper() if len(sys.argv) > 1 else "US")

    from config.settings import get_settings
    from core.database import Database
    from data.fundamental_data import FundamentalDataManager
    from data.ai_stock_report import StockReportError, StockReportService

    settings = get_settings()
    db = Database(str(settings.db_full_path))
    await db.initialize()

    fdm = FundamentalDataManager(db)
    report_svc = StockReportService(db, settings)

    try:
        cur = await db.conn.execute(
            "SELECT ticker FROM watchlist WHERE status = 'ACTIVE' AND market = ? ORDER BY ticker",
            (market,),
        )
        active = [row[0] for row in await cur.fetchall()]

        stuck: list[str] = []
        for t in active:
            try:
                if await fdm.needs_update(t, market=market):
                    stuck.append(t)
            except Exception:
                stuck.append(t)

        logger.info("backfill_start", market=market, active=len(active), stuck=len(stuck), tickers=stuck)

        for t in stuck:
            before = await _latest_quarter(db, t)
            new_records = await fdm.fetch_and_store_fundamentals(t, market=market)
            after = await _latest_quarter(db, t)

            verdict = None
            regen = None
            try:
                res = await report_svc.generate_report(t, market)
                regen = "cache_hit" if res.get("cache_hit") else "regenerated"
                verdict = (res.get("report") or {}).get("verdict")
            except StockReportError as exc:
                regen = f"report_skip:{exc}"
            except Exception as exc:  # noqa: BLE001
                regen = f"report_error:{exc}"

            logger.info(
                "backfill_ticker",
                ticker=t,
                before=before,
                after=after,
                changed=(before != after),
                new_records=new_records,
                report=regen,
                verdict=verdict,
            )

        logger.info("backfill_complete", market=market, processed=len(stuck))
    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
