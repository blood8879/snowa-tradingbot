"""
Donchian Channel calculator.

Computes the upper/lower channel levels used for
Turtle Trading System 1 (20-day) and System 2 (55-day) entry/exit signals.

Pure functions — no side effects.
"""
from __future__ import annotations

from config.constants import (
    SYSTEM1_ENTRY_DAYS,
    SYSTEM1_EXIT_DAYS,
    SYSTEM2_ENTRY_DAYS,
    SYSTEM2_EXIT_DAYS,
)


def donchian_high(highs: list[float], period: int) -> float | None:
    """Return the max of the last *period* values from *highs*.

    Returns ``None`` if there are fewer than *period* values.
    """
    if len(highs) < period:
        return None
    return max(highs[-period:])


def donchian_low(lows: list[float], period: int) -> float | None:
    """Return the min of the last *period* values from *lows*.

    Returns ``None`` if there are fewer than *period* values.
    """
    if len(lows) < period:
        return None
    return min(lows[-period:])


def calculate_donchian_levels(
    highs: list[float],
    lows: list[float],
) -> dict[str, float | None]:
    """Calculate all four Donchian channel levels.

    Returns a dict with keys:
      - ``upper_20``: max of last 20 highs  (System 1 entry)
      - ``upper_55``: max of last 55 highs  (System 2 entry)
      - ``lower_10``: min of last 10 lows   (System 1 exit)
      - ``lower_20``: min of last 20 lows   (System 2 exit)

    Any level whose period exceeds the available data is ``None``.
    """
    return {
        "upper_20": donchian_high(highs, SYSTEM1_ENTRY_DAYS),
        "upper_55": donchian_high(highs, SYSTEM2_ENTRY_DAYS),
        "lower_10": donchian_low(lows, SYSTEM1_EXIT_DAYS),
        "lower_20": donchian_low(lows, SYSTEM2_EXIT_DAYS),
    }


def calculate_donchian_levels_from_ohlcv(
    bars: list,
) -> dict[str, float | None]:
    """Calculate Donchian levels from a list of OHLCV-like objects.

    Each element in *bars* must have ``.high`` and ``.low`` attributes
    (e.g. an :class:`core.models.OHLCV` instance).
    """
    highs = [bar.high for bar in bars]
    lows = [bar.low for bar in bars]
    return calculate_donchian_levels(highs, lows)


def build_donchian_levels_model(
    ticker: str,
    highs: list[float],
    lows: list[float],
) -> DonchianLevels:
    """Build a :class:`core.models.DonchianLevels` dataclass instance.

    Calculates all four channel levels and stamps the current UTC time.

    Raises ``ValueError`` if any of the four levels is ``None``
    (insufficient data to construct a complete model).
    """
    from datetime import datetime

    from core.models import DonchianLevels

    levels = calculate_donchian_levels(highs, lows)

    missing = [k for k, v in levels.items() if v is None]
    if missing:
        raise ValueError(
            f"Insufficient data for {ticker}: "
            f"missing levels {missing}"
        )

    return DonchianLevels(
        ticker=ticker,
        upper_20=levels["upper_20"],  # type: ignore[arg-type]
        upper_55=levels["upper_55"],  # type: ignore[arg-type]
        lower_10=levels["lower_10"],  # type: ignore[arg-type]
        lower_20=levels["lower_20"],  # type: ignore[arg-type]
        calculated_at=datetime.utcnow().isoformat(),
    )
