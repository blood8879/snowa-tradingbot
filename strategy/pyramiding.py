"""
Pyramiding (position add) calculator.

Implements Turtle Trading pyramid rules:
  - Max 4 units per stock (MAX_UNITS_PER_STOCK)
  - Add every 1/2 N (PYRAMID_INTERVAL_N = 0.5) above last entry
  - All stops tighten on each add

Pure functions — no side effects.
"""

from __future__ import annotations

from config.constants import MAX_CHASE_PCT, MAX_UNITS_PER_STOCK, PYRAMID_INTERVAL_N
from strategy.stop_loss import calculate_stop_price


# ════════════════════════════════════════════════════════════════
# Core Calculations
# ════════════════════════════════════════════════════════════════


def calculate_pyramid_price(
    last_entry_price: float,
    n_value: float,
    interval: float = PYRAMID_INTERVAL_N,
) -> float:
    """Calculate the next pyramid trigger price.

    Next add triggers when price reaches:
        last_entry_price + interval × N

    With default interval of 0.5, adds occur every half-N above
    the last entry.

    Args:
        last_entry_price: Entry price of the most recent unit.
        n_value: Current ATR (N) value.
        interval: Fraction of N for the add interval (default 0.5).

    Returns:
        Price at which the next pyramid unit should be added.
    """
    return last_entry_price + interval * n_value


def check_pyramid_signal(
    current_price: float,
    last_entry_price: float,
    n_value: float,
    current_units: int,
) -> dict:
    """Check whether a pyramid add should trigger.

    Conditions for an add:
        1. current_units < MAX_UNITS_PER_STOCK (4)
        2. current_price >= pyramid trigger price

    Args:
        current_price: Current market price.
        last_entry_price: Entry price of the most recent unit.
        n_value: Current ATR (N) value.
        current_units: Number of units currently held.

    Returns:
        Dict with keys:
            - ``"add"``: Whether to add a unit.
            - ``"next_unit_number"``: The unit number if added.
            - ``"trigger_price"``: Price that triggers the add.
            - ``"reason"``: Human-readable explanation.
    """
    trigger_price = calculate_pyramid_price(last_entry_price, n_value)
    can_add = current_units < MAX_UNITS_PER_STOCK
    price_met = current_price >= trigger_price

    if not can_add:
        return {
            "add": False,
            "next_unit_number": current_units + 1,
            "trigger_price": trigger_price,
            "reason": f"Max units reached ({MAX_UNITS_PER_STOCK})",
        }

    if not price_met:
        return {
            "add": False,
            "next_unit_number": current_units + 1,
            "trigger_price": trigger_price,
            "reason": (
                f"Price {current_price:.2f} below trigger {trigger_price:.2f}"
            ),
        }

    # Chase guard: skip if price ran too far above trigger (CANSLIM 5% rule)
    if trigger_price > 0:
        chase_pct = (current_price - trigger_price) / trigger_price
        if chase_pct > MAX_CHASE_PCT:
            return {
                "add": False,
                "next_unit_number": current_units + 1,
                "trigger_price": trigger_price,
                "reason": (
                    f"Pyramid chase guard: price {chase_pct:.1%} above trigger "
                    f"(max {MAX_CHASE_PCT:.0%})"
                ),
            }

    return {
        "add": True,
        "next_unit_number": current_units + 1,
        "trigger_price": trigger_price,
        "reason": (
            f"Price {current_price:.2f} >= trigger {trigger_price:.2f}, "
            f"adding unit {current_units + 1}"
        ),
    }


# ════════════════════════════════════════════════════════════════
# Planning & Display
# ════════════════════════════════════════════════════════════════


def calculate_pyramid_schedule(
    entry_price: float,
    n_value: float,
    max_units: int = MAX_UNITS_PER_STOCK,
) -> list[dict]:
    """Pre-calculate all pyramid levels for display and planning.

    Generates the full schedule of entry and stop prices:
        Unit 1: entry_price                → stop from that entry
        Unit 2: entry_price + 0.5 × N      → stop from that entry
        Unit 3: entry_price + 1.0 × N      → stop from that entry
        Unit 4: entry_price + 1.5 × N      → stop from that entry

    Stop prices tighten with each add — all units share the latest
    (highest) stop.

    Args:
        entry_price: Initial entry price (unit 1).
        n_value: Current ATR (N) value.
        max_units: Maximum number of units (default 4).

    Returns:
        List of dicts with ``"unit"``, ``"entry_price"``, and
        ``"stop_price"`` for each pyramid level.
    """
    schedule: list[dict] = []
    current_stop = 0.0

    for unit_num in range(1, max_units + 1):
        # Unit 1 enters at entry_price; subsequent units add 0.5N each
        unit_entry = entry_price + (unit_num - 1) * PYRAMID_INTERVAL_N * n_value
        unit_stop = calculate_stop_price(unit_entry, n_value)

        # Stop can only move up (tighten)
        current_stop = max(current_stop, unit_stop)

        schedule.append({
            "unit": unit_num,
            "entry_price": unit_entry,
            "stop_price": current_stop,
        })

    return schedule


# ════════════════════════════════════════════════════════════════
# Convenience Check
# ════════════════════════════════════════════════════════════════


def can_add_unit(
    current_units: int,
    max_units: int = MAX_UNITS_PER_STOCK,
) -> bool:
    """Check if another pyramid unit can be added.

    Args:
        current_units: Number of units currently held.
        max_units: Maximum allowed units (default 4).

    Returns:
        True if current_units < max_units.
    """
    return current_units < max_units
