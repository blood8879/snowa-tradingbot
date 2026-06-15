"""Re-apply the AI PASS gate to the current ACTIVE watchlist.

Mirrors DailyScreeningPipeline._filter_watchlist_to_ai_pass, but runs on demand
outside the daily pipeline. For each ACTIVE watchlist ticker it (re)generates
the LLM report under the configured prompt_version (cache hit if unchanged),
then REMOVEs any entry whose verdict is not PASS.

Use after a prompt_version change or an ad-hoc fundamentals backfill, when the
watchlist may contain non-PASS names that the pipeline filter has not yet pruned.

Usage:
    python -m scripts.reapply_ai_pass_filter [--dry-run]
"""

from __future__ import annotations

import asyncio
import sys
import time

import structlog

structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.dev.ConsoleRenderer(),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(0),
)

logger = structlog.get_logger(__name__)


async def main() -> None:
    dry_run = "--dry-run" in sys.argv

    from config.settings import get_settings
    from core.database import Database
    from data.ai_stock_report import StockReportError, StockReportService

    settings = get_settings()
    db = Database(str(settings.db_full_path))
    await db.initialize()

    svc = StockReportService(db, settings)
    logger.info("reapply_start", prompt_version=settings.ai_report_prompt_version, dry_run=dry_run)

    try:
        cur = await db.conn.execute(
            """
            SELECT ticker, name, market, quarterly_eps_growth, annual_eps_cagr,
                   rs_rating, custom_composite_score, minervini_pass
            FROM watchlist WHERE status = 'ACTIVE' ORDER BY market, ticker
            """
        )
        rows = await cur.fetchall()

        kept: list[str] = []
        removed: list[tuple] = []  # (ticker, market, verdict)
        now = time.strftime("%Y-%m-%dT%H:%M:%S")

        for row in rows:
            ticker, name, market = row[0], row[1], row[2]
            verdict = None
            try:
                res = await svc.generate_report(ticker, market)
                verdict = (res.get("report") or {}).get("verdict")
            except StockReportError as exc:
                logger.warning("reapply_report_skip", ticker=ticker, market=market, error=str(exc))
            except Exception:
                logger.exception("reapply_report_error", ticker=ticker, market=market)

            if verdict == "PASS":
                kept.append(f"{market}:{ticker}")
                continue

            removed.append((ticker, market, verdict))
            if dry_run:
                continue

            await db.conn.execute(
                "UPDATE watchlist SET status = 'REMOVED' WHERE ticker = ? AND market = ? AND status = 'ACTIVE'",
                (ticker, market),
            )
            await db.conn.execute(
                """INSERT INTO watchlist_history
                   (ticker, name, market, action, reason, quarterly_eps_growth, annual_eps_cagr,
                    rs_rating, composite_score, minervini_pass, recorded_at)
                   VALUES (?, ?, ?, 'REMOVED', ?, ?, ?, ?, ?, ?, ?)""",
                (
                    ticker, name, market,
                    f"LLM 리포트 PASS 미충족({verdict or 'NO_REPORT'})",
                    row[3], row[4], row[5], row[6], row[7], now,
                ),
            )

        if not dry_run:
            await db.conn.commit()

        logger.info(
            "reapply_complete",
            dry_run=dry_run,
            kept=len(kept),
            removed=len(removed),
            removed_detail=[f"{m}:{t}({v})" for t, m, v in removed],
        )
    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
