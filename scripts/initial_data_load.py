"""
Initial bulk data loader.

Downloads and stores the full stock universe, fundamental data, and
historical price data into the SQLite database.

Usage:
    python -m scripts.initial_data_load --mode all
    python -m scripts.initial_data_load --mode fundamentals --limit 100
    python -m scripts.initial_data_load --mode prices --limit 500
"""

from __future__ import annotations

import argparse
import asyncio
import time

import structlog

from config.logging_config import setup_logging
from config.settings import get_settings
from core.database import Database
from data.earnings_calendar import EarningsCalendar
from data.fundamental_data import FundamentalDataManager
from data.price_cache import PriceCache
from data.universe import UniverseManager


logger = structlog.get_logger(__name__)


async def main(args: argparse.Namespace) -> None:
    """Orchestrate initial bulk data loading."""
    settings = get_settings()
    setup_logging(log_level=settings.log_level, log_file=settings.log_file)

    overall_start = time.monotonic()
    logger.info(
        "initial_data_load_start",
        mode=args.mode,
        limit=args.limit,
        batch_size=args.batch_size,
        delay=args.delay,
    )

    db = Database(settings.db_path)

    try:
        # ── Initialize database ──────────────────────────────
        await db.initialize()

        # ── Load universe ────────────────────────────────────
        phase_start = time.monotonic()
        um = UniverseManager()
        count = await um.load_universe()
        logger.info(
            "universe_phase_done",
            total_stocks=count,
            elapsed=f"{time.monotonic() - phase_start:.1f}s",
        )

        if args.mode == "universe":
            logger.info("universe_only_mode", total_stocks=count)
            return

        # ── Resolve tradeable tickers ────────────────────────
        tickers = [s.ticker for s in um.filter_tradeable()]
        tickers.sort()

        if args.limit > 0:
            tickers = tickers[: args.limit]

        logger.info("tickers_resolved", count=len(tickers))

        # ── Prices phase ─────────────────────────────────────
        if args.mode in ("all", "prices"):
            phase_start = time.monotonic()
            logger.info("prices_phase_start", tickers=len(tickers))

            try:
                pc = PriceCache(db)
                new_rows = await pc.bulk_load_from_yfinance(
                    tickers,
                    period="15mo",
                    batch_size=args.batch_size,
                    delay=args.delay,
                )
                logger.info(
                    "prices_phase_done",
                    new_records=new_rows,
                    elapsed=f"{time.monotonic() - phase_start:.1f}s",
                )
            except Exception:
                logger.exception("prices_phase_error")

        # ── Fundamentals phase ───────────────────────────────
        if args.mode in ("all", "fundamentals"):
            phase_start = time.monotonic()
            logger.info("fundamentals_phase_start", tickers=len(tickers))

            try:
                fdm = FundamentalDataManager(db)
                new_records = await fdm.bulk_fetch(
                    tickers,
                    batch_size=args.batch_size,
                    delay=args.delay,
                )
                logger.info(
                    "fundamentals_phase_done",
                    new_records=new_records,
                    elapsed=f"{time.monotonic() - phase_start:.1f}s",
                )
            except Exception:
                logger.exception("fundamentals_phase_error")

        # ── Earnings-update phase ────────────────────────────
        if args.mode == "earnings-update":
            phase_start = time.monotonic()
            logger.info(
                "earnings_update_phase_start",
                lookback_days=args.lookback_days,
            )

            try:
                cal = EarningsCalendar()
                targets = await cal.get_update_targets(
                    tickers, days=args.lookback_days
                )
                logger.info("earnings_update_targets", count=len(targets))

                if targets:
                    fdm = FundamentalDataManager(db)
                    new_records = await fdm.bulk_fetch(
                        targets,
                        batch_size=args.batch_size,
                        delay=args.delay,
                    )
                    logger.info(
                        "earnings_update_phase_done",
                        targets=len(targets),
                        new_records=new_records,
                        elapsed=f"{time.monotonic() - phase_start:.1f}s",
                    )
                else:
                    logger.info("earnings_update_no_targets")

            except Exception:
                logger.exception("earnings_update_phase_error")

    finally:
        await db.close()

    elapsed = time.monotonic() - overall_start
    logger.info(
        "initial_data_load_complete",
        mode=args.mode,
        total_elapsed=f"{elapsed:.1f}s",
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Initial bulk data loader for snowa_tradingbot",
    )
    parser.add_argument(
        "--mode",
        choices=["all", "fundamentals", "prices", "universe", "earnings-update"],
        default="all",
        help="Which data to load (default: all)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Max tickers to process; 0 = all (default: 0)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=100,
        help="Number of tickers per batch (default: 100)",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=1.0,
        help="Seconds to wait between batches (default: 1.0)",
    )
    parser.add_argument(
        "--lookback-days",
        type=int,
        default=3,
        help="Days to look back for earnings calendar (default: 3)",
    )

    args = parser.parse_args()
    asyncio.run(main(args))
