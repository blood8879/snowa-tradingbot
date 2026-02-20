"""
Exit signal detection for Turtle Trading.

Two exit mechanisms:
  1. Donchian channel exit: close below N-day low
     - System 1: 10-day low exit
     - System 2: 20-day low exit
  2. Stop-loss exit: price hits stop (handled in stop_loss.py)

Plus gap-down handling at market open.

Pure functions — no side effects.
"""
from __future__ import annotations

from config.constants import (
    SYSTEM1_EXIT_DAYS,
    SYSTEM2_EXIT_DAYS,
    DONCHIAN_EXIT_MINUTES_BEFORE_CLOSE,
)
from core.models import TradingSystem


# ════════════════════════════════════════════════════════════════
# Donchian Channel Exit
# ════════════════════════════════════════════════════════════════


def check_donchian_exit(
    current_price: float,
    system: str,
    donchian_lower_10: float | None,
    donchian_lower_20: float | None,
) -> dict:
    """Check whether the current price triggers a Donchian channel exit.

    System 1 exits when ``current_price < donchian_lower_10`` (10-day low).
    System 2 exits when ``current_price < donchian_lower_20`` (20-day low).

    Args:
        current_price: Latest price of the stock.
        system: Trading system identifier (``"S1"`` or ``"S2"``).
        donchian_lower_10: 10-day low (System 1 exit level).
        donchian_lower_20: 20-day low (System 2 exit level).

    Returns:
        A dict with keys:
          - ``exit``: True if exit triggered.
          - ``system``: The system checked.
          - ``exit_level``: The Donchian level that was breached (0.0 if N/A).
          - ``reason``: Human-readable explanation.
    """
    if system == TradingSystem.S1.value:
        if donchian_lower_10 is None:
            return {
                "exit": False,
                "system": system,
                "exit_level": 0.0,
                "reason": f"S1 Donchian {SYSTEM1_EXIT_DAYS}-day low not available",
            }
        triggered = current_price <= donchian_lower_10
        return {
            "exit": triggered,
            "system": system,
            "exit_level": donchian_lower_10,
            "reason": (
                f"S1 exit: price {current_price:.2f} <= "
                f"{SYSTEM1_EXIT_DAYS}-day low {donchian_lower_10:.2f}"
                if triggered
                else f"S1 hold: price {current_price:.2f} > "
                f"{SYSTEM1_EXIT_DAYS}-day low {donchian_lower_10:.2f}"
            ),
        }

    if system == TradingSystem.S2.value:
        if donchian_lower_20 is None:
            return {
                "exit": False,
                "system": system,
                "exit_level": 0.0,
                "reason": f"S2 Donchian {SYSTEM2_EXIT_DAYS}-day low not available",
            }
        triggered = current_price <= donchian_lower_20
        return {
            "exit": triggered,
            "system": system,
            "exit_level": donchian_lower_20,
            "reason": (
                f"S2 exit: price {current_price:.2f} <= "
                f"{SYSTEM2_EXIT_DAYS}-day low {donchian_lower_20:.2f}"
                if triggered
                else f"S2 hold: price {current_price:.2f} > "
                f"{SYSTEM2_EXIT_DAYS}-day low {donchian_lower_20:.2f}"
            ),
        }

    # Unknown system — no exit
    return {
        "exit": False,
        "system": system,
        "exit_level": 0.0,
        "reason": f"Unknown system '{system}' — no Donchian exit check",
    }


# ════════════════════════════════════════════════════════════════
# Gap-Down Exit
# ════════════════════════════════════════════════════════════════


def check_gap_down_exit(
    open_price: float,
    stop_price: float,
) -> dict:
    """Check if the market opens below the stop price (gap down).

    When a stock gaps below the stop on open, the position should
    be liquidated at the market open price rather than waiting for
    the intraday stop mechanism.

    Args:
        open_price: The stock's opening price for the day.
        stop_price: The current stop-loss price for the position.

    Returns:
        A dict with keys:
          - ``exit``: True if the open price is at or below the stop.
          - ``gap_size_pct``: Gap size as a percentage of the stop price
            (negative means open is below stop).
          - ``reason``: Human-readable explanation.
    """
    triggered = open_price <= stop_price
    gap_size_pct = (open_price - stop_price) / stop_price if stop_price != 0 else 0.0

    return {
        "exit": triggered,
        "gap_size_pct": gap_size_pct,
        "reason": (
            f"Gap-down exit: open {open_price:.2f} <= "
            f"stop {stop_price:.2f} (gap {gap_size_pct:+.2%})"
            if triggered
            else f"No gap-down: open {open_price:.2f} > "
            f"stop {stop_price:.2f}"
        ),
    }


# ════════════════════════════════════════════════════════════════
# Exit Timing
# ════════════════════════════════════════════════════════════════


def should_check_donchian_exit(
    current_hour: int,
    current_minute: int,
    market_close_hour: int = 16,
    market_close_minute: int = 0,
) -> bool:
    """Determine whether we are within the Donchian exit check window.

    Donchian channel exits are only evaluated in the final
    ``DONCHIAN_EXIT_MINUTES_BEFORE_CLOSE`` minutes (default 15)
    before market close.  This prevents premature exits on intraday
    dips earlier in the session.

    Args:
        current_hour: Current hour (24-hour format).
        current_minute: Current minute.
        market_close_hour: Market close hour (default 16 for 4:00 PM).
        market_close_minute: Market close minute (default 0).

    Returns:
        True if current time is within the exit check window
        (i.e., 0 < remaining_minutes <= DONCHIAN_EXIT_MINUTES_BEFORE_CLOSE).
    """
    close_in_minutes = market_close_hour * 60 + market_close_minute
    now_in_minutes = current_hour * 60 + current_minute
    remaining_minutes = close_in_minutes - now_in_minutes

    return 0 < remaining_minutes <= DONCHIAN_EXIT_MINUTES_BEFORE_CLOSE


# ════════════════════════════════════════════════════════════════
# Exit Price Calculation
# ════════════════════════════════════════════════════════════════


def calculate_exit_price(
    current_price: float,
    exit_type: str,
) -> float:
    """Determine the execution price for an exit.

    - **Donchian exit**: uses the closing price (``EXECUTION_PRICE_BASIS="CLOSE"``).
    - **Gap-down**: uses the market-open price.
    - **Stop-loss**: the stop sell price is computed in the stop_loss module;
      here we return *current_price* as a passthrough.

    Args:
        current_price: The price to base the exit on
            (closing price for Donchian, open price for gap-down).
        exit_type: One of ``"donchian"``, ``"gap_down"``, or ``"stop_loss"``.

    Returns:
        The execution price for the exit order.
    """
    # All three types currently pass through current_price.
    # Donchian → closing price (caller provides close).
    # Gap-down → open price (caller provides open).
    # Stop-loss → stop sell price (caller provides stop from stop_loss module).
    return current_price
