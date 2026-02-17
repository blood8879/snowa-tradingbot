"""
ATR (Average True Range) calculator — "N" in Turtle terminology.

Implements the 20-day EMA-based ATR per TURTLE_TRADING_STRATEGY.md §3.3.
Pure functions — no side effects, no database access.
"""

from __future__ import annotations

from config.constants import ATR_PERIOD, ATR_SMOOTHING_FACTOR


# ════════════════════════════════════════════════════════════════
# Core Calculations
# ════════════════════════════════════════════════════════════════


def true_range(high: float, low: float, prev_close: float) -> float:
    """Calculate True Range for a single bar.

    TR = max(high − low, |high − prev_close|, |low − prev_close|)

    Args:
        high: Current bar's high price.
        low: Current bar's low price.
        prev_close: Previous bar's closing price.

    Returns:
        The True Range value.
    """
    return max(high - low, abs(high - prev_close), abs(low - prev_close))


def calculate_n(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    period: int = ATR_PERIOD,
) -> list[float]:
    """Calculate N (ATR) array using the EMA method.

    Requires at least ``period + 1`` data points (one extra for prev_close).

    Steps:
        1. Build TR series (skip index 0 — no prev_close available).
        2. Seed the first N value as the simple average of the first
           *period* TRs.
        3. Subsequent values use the EMA formula:
           ``N_new = N_prev + smoothing × (TR − N_prev)``
           where ``smoothing = ATR_SMOOTHING_FACTOR`` (1/20).

    Args:
        highs: High prices (oldest first).
        lows: Low prices (oldest first).
        closes: Closing prices (oldest first).
        period: Lookback window for the initial SMA seed (default 20).

    Returns:
        List of N values, one per bar starting from the bar where
        the first full-period SMA can be computed.
        Length = ``len(highs) - 1 - period + 1`` = ``len(highs) - period``.

    Raises:
        ValueError: If fewer than ``period + 1`` data points are supplied.
    """
    n_bars = len(highs)

    if n_bars < period + 1:
        raise ValueError(
            f"Need at least {period + 1} bars, got {n_bars}"
        )

    # Step 1: TR series — starts from index 1 (prev_close = closes[i-1])
    tr_series: list[float] = [
        true_range(highs[i], lows[i], closes[i - 1])
        for i in range(1, n_bars)
    ]

    # Step 2: Seed N with simple average of first `period` TRs
    first_n = sum(tr_series[:period]) / period

    # Step 3: EMA-based N values
    n_values: list[float] = [first_n]
    smoothing = ATR_SMOOTHING_FACTOR

    for tr in tr_series[period:]:
        prev_n = n_values[-1]
        new_n = prev_n + smoothing * (tr - prev_n)
        n_values.append(new_n)

    return n_values


# ════════════════════════════════════════════════════════════════
# Convenience Wrappers
# ════════════════════════════════════════════════════════════════


def calculate_n_single(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    period: int = ATR_PERIOD,
) -> float | None:
    """Return the latest N (ATR) value, or None if insufficient data.

    Convenience wrapper around :func:`calculate_n` that returns only
    the most recent value.

    Args:
        highs: High prices (oldest first).
        lows: Low prices (oldest first).
        closes: Closing prices (oldest first).
        period: Lookback window (default 20).

    Returns:
        Latest N value, or None when data is too short.
    """
    if len(highs) < period + 1:
        return None

    n_values = calculate_n(highs, lows, closes, period)
    return n_values[-1]


def calculate_n_from_ohlcv(bars: list) -> float | None:
    """Calculate the latest N from a list of OHLCV objects.

    Accepts ``list`` (not ``list[OHLCV]``) to avoid an import cycle —
    the caller is responsible for passing proper OHLCV instances with
    ``.high``, ``.low``, and ``.close`` attributes.

    Args:
        bars: OHLCV bar objects (oldest first).

    Returns:
        Latest N value, or None when data is insufficient.
    """
    if not bars:
        return None

    highs = [bar.high for bar in bars]
    lows = [bar.low for bar in bars]
    closes = [bar.close for bar in bars]

    return calculate_n_single(highs, lows, closes)
