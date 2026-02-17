"""
Market direction filter — SPY above 200-day SMA.

When SPY closes below its 200-day SMA, new entries are blocked.
Existing positions continue to be managed by Turtle exit rules.

Reference: TURTLE_TRADING_STRATEGY.md §4, IMPLEMENTATION_PLAN.md Phase 5.1
"""

from __future__ import annotations

from typing import Any

import structlog

from config.constants import (
    MARKET_BENCHMARK,
    MARKET_FILTER_BUFFER_PCT,
    MARKET_MA_PERIOD,
)

logger = structlog.get_logger(__name__)


# ════════════════════════════════════════════════════════════════
# Pure Calculations
# ════════════════════════════════════════════════════════════════


def check_market_filter(
    spy_close: float,
    spy_sma200: float,
    buffer_pct: float = MARKET_FILTER_BUFFER_PCT,
) -> bool:
    """Return True if the market passes the trend filter.

    The market is considered in an uptrend when SPY's closing price
    is above its 200-day SMA (optionally adjusted by a buffer).

    Formula: ``spy_close > spy_sma200 × (1 − buffer_pct)``

    With the default ``buffer_pct = 0.0`` this simplifies to
    ``spy_close > spy_sma200``.

    Args:
        spy_close: SPY's most recent closing price.
        spy_sma200: SPY's 200-day Simple Moving Average.
        buffer_pct: Buffer percentage below the SMA that still counts
                    as "above" (default 0.0 — no buffer).

    Returns:
        True if the market filter passes (entries allowed).
    """
    return spy_close > spy_sma200 * (1 - buffer_pct)


def calculate_sma(closes: list[float], period: int) -> float | None:
    """Calculate the Simple Moving Average over *period* bars.

    Uses the last *period* values from *closes*.

    Args:
        closes: Closing prices (oldest first).
        period: Number of bars for the average window.

    Returns:
        The SMA value, or None if fewer than *period* data points
        are available.
    """
    if len(closes) < period:
        return None

    return sum(closes[-period:]) / period


# ════════════════════════════════════════════════════════════════
# Async Wrapper (uses MarketDataProvider)
# ════════════════════════════════════════════════════════════════


async def get_market_filter_status(market_data: Any) -> dict:
    """Fetch SPY data and evaluate the market direction filter.

    This is the only non-pure function in the module — it performs
    async I/O through *market_data* (a :class:`MarketDataProvider`).

    Args:
        market_data: A ``MarketDataProvider`` instance.  Typed as
                     ``Any`` to avoid a hard import dependency.

    Returns:
        A dict with the following shape::

            {
                "benchmark": "SPY",
                "close": float,
                "sma200": float,
                "filter_pass": bool,
            }

        On error the function *fails open* — ``filter_pass`` is ``True``
        so that trading is not blocked by a data gap.
    """
    try:
        spy_close = await market_data.get_latest_price(MARKET_BENCHMARK)
        spy_sma200 = await market_data.get_sma(
            MARKET_BENCHMARK, MARKET_MA_PERIOD
        )

        if spy_close is None or spy_sma200 is None:
            logger.warning(
                "market_filter_data_unavailable",
                benchmark=MARKET_BENCHMARK,
                close=spy_close,
                sma200=spy_sma200,
            )
            return {
                "benchmark": MARKET_BENCHMARK,
                "close": 0,
                "sma200": 0,
                "filter_pass": True,  # fail-open
            }

        filter_pass = check_market_filter(spy_close, spy_sma200)

        logger.debug(
            "market_filter_evaluated",
            benchmark=MARKET_BENCHMARK,
            close=spy_close,
            sma200=spy_sma200,
            filter_pass=filter_pass,
        )

        return {
            "benchmark": MARKET_BENCHMARK,
            "close": spy_close,
            "sma200": spy_sma200,
            "filter_pass": filter_pass,
        }

    except Exception:
        logger.exception(
            "market_filter_error",
            benchmark=MARKET_BENCHMARK,
        )
        return {
            "benchmark": MARKET_BENCHMARK,
            "close": 0,
            "sma200": 0,
            "filter_pass": True,  # fail-open
        }
