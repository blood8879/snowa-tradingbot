"""
Main entry point for the SNOWA Trading Bot.

Usage:
    python -m scripts.run_bot
    # or via installed entry point:
    snowa-bot
"""

from __future__ import annotations

import asyncio
import sys

import structlog

from config.logging_config import setup_logging
from config.settings import get_settings


logger = structlog.get_logger(__name__)


async def startup() -> None:
    """Initialize and run the trading bot."""
    settings = get_settings()

    # 1. Setup logging
    setup_logging(log_level=settings.log_level, log_file=settings.log_file)
    logger.info("bot_starting", mode=settings.trading_mode.value)

    # 2. Import and run TradingBot
    from bot.trading_bot import TradingBot

    bot = TradingBot()

    try:
        await bot.run()
    except Exception:
        logger.exception("bot_fatal_error")
        raise
    finally:
        await bot.shutdown()


def main() -> None:
    """CLI entry point."""
    try:
        asyncio.run(startup())
    except KeyboardInterrupt:
        print("\nBot stopped by user.")
        sys.exit(0)
    except Exception as e:
        print(f"Fatal error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
