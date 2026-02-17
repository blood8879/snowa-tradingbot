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


async def main() -> None:
    from config.settings import get_settings
    from core.database import Database
    from bot.daily_screening import DailyScreeningPipeline

    is_init = "--init" in sys.argv
    period = "1y" if is_init else "5d"

    settings = get_settings()
    db = Database(str(settings.db_full_path))
    await db.initialize()

    try:
        pipeline = DailyScreeningPipeline(db=db)
        logger.info("manual_screening_start", mode="init" if is_init else "daily", price_period=period)
        result = await pipeline.run(price_period=period)
        logger.info("manual_screening_complete", **result)
    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
