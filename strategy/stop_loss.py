"""
Stop-loss calculator — hybrid min(2N, 10%) stop.

Implements the Turtle Trading stop-loss with Minervini 10% cap:
  actual_stop_distance = min(STOP_LOSS_N × N, entry_price × STOP_LOSS_MAX_PCT)
  stop_price = entry_price - actual_stop_distance

On pyramid: all stops tighten to min(2N, 10%) from LATEST entry.
Stops can only move UP, never down (STOP_LOSS_MOVE_DIRECTION = "UP_ONLY").

Pure functions — no side effects.
"""

from __future__ import annotations

from config.constants import STOP_LOSS_N, STOP_LOSS_MAX_PCT, STOP_SELL_BUFFER_PCT


# ════════════════════════════════════════════════════════════════
# Core Calculations
# ════════════════════════════════════════════════════════════════


def calculate_stop_distance(n_value: float, entry_price: float) -> float:
    """Calculate the hybrid stop distance: min(2N, 10% of entry).

    Uses the smaller of the Turtle 2N stop and the Minervini 10% cap
    to ensure the stop is never wider than 10% from entry.

    - When N/P ≤ 5%: 2N applies (10% cap inactive).
    - When N/P > 5%: 10% cap activates (tighter than 2N).

    Args:
        n_value: Current ATR (N) value.
        entry_price: Entry price for the position.

    Returns:
        Stop distance as a positive number.
    """
    turtle_stop = STOP_LOSS_N * n_value
    max_stop = entry_price * STOP_LOSS_MAX_PCT
    return min(turtle_stop, max_stop)


def calculate_stop_price(entry_price: float, n_value: float) -> float:
    """Calculate stop price from entry.

    stop_price = entry_price - min(2N, entry_price × 10%)

    Args:
        entry_price: Entry price for the position.
        n_value: Current ATR (N) value.

    Returns:
        The stop price.
    """
    return entry_price - calculate_stop_distance(n_value, entry_price)


# ════════════════════════════════════════════════════════════════
# Pyramid Stop Tightening
# ════════════════════════════════════════════════════════════════


def update_stop_on_pyramid(
    current_stop: float,
    new_entry_price: float,
    n_value: float,
) -> float:
    """Recalculate stop when a new pyramid unit is added.

    On each pyramid add, the stop is recalculated from the latest entry.
    The stop can only move UP (tighten), never down.

    Args:
        current_stop: Existing stop price before this pyramid add.
        new_entry_price: Entry price of the newly added unit.
        n_value: Current ATR (N) value.

    Returns:
        Updated stop price — the higher of old stop and new stop.
    """
    new_stop = new_entry_price - calculate_stop_distance(n_value, new_entry_price)
    return max(current_stop, new_stop)


def check_stop_hit(current_price: float, stop_price: float) -> bool:
    """Check whether the stop-loss has been triggered.

    Args:
        current_price: Current market price.
        stop_price: Active stop price.

    Returns:
        True if current_price <= stop_price (stop hit).
    """
    return current_price <= stop_price


# ════════════════════════════════════════════════════════════════
# Multi-Unit Stop Schedule
# ════════════════════════════════════════════════════════════════


def calculate_all_unit_stops(
    units: list[dict],
    n_value: float,
) -> list[dict]:
    """Calculate stops for all pyramid units with tightening.

    After each pyramid add, ALL unit stops tighten to the latest
    entry's stop (if it is higher).  Units are processed in order.

    Example with entry $100, N=$5:
        Unit 1 @ $100.0 → stop = $100.0  - min(10, 10) = $90.0
        Unit 2 @ $102.5 → stop = $102.5  - 10 = $92.5  → ALL get $92.5
        Unit 3 @ $105.0 → stop = $105.0  - 10 = $95.0  → ALL get $95.0
        Unit 4 @ $107.5 → stop = $107.5  - 10 = $97.5  → ALL get $97.5

    Args:
        units: List of dicts, each with ``"entry_price"`` and
            ``"unit_number"`` keys.  Must be ordered by unit_number.
        n_value: Current ATR (N) value.

    Returns:
        Copy of units list with ``"stop_price"`` added to each dict.
    """
    result: list[dict] = []
    current_stop = 0.0

    for unit in units:
        entry = unit["entry_price"]
        unit_stop = calculate_stop_price(entry, n_value)

        # Stop can only move up (tighten)
        current_stop = max(current_stop, unit_stop)

        result.append({
            **unit,
            "stop_price": current_stop,
        })

    return result


# ════════════════════════════════════════════════════════════════
# Order Execution Helper
# ════════════════════════════════════════════════════════════════


def calculate_stop_sell_price(current_price: float) -> float:
    """Calculate limit price for executing a stop sell order.

    Places the limit slightly below the current price to increase
    fill probability during stop execution.

    Args:
        current_price: Current market price at stop trigger time.

    Returns:
        Limit sell price (current_price × (1 − STOP_SELL_BUFFER_PCT)).
    """
    return current_price * (1 - STOP_SELL_BUFFER_PCT)
