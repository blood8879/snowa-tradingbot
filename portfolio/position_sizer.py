"""
Position sizing calculator — Minervini risk-based unit sizing.

Unit size = (Account × RISK_PER_UNIT_PCT) / actual_stop_distance
where actual_stop = min(STOP_LOSS_N × N, entry_price × STOP_LOSS_MAX_PCT)

Constraints:
  - Single unit ≤ MAX_SINGLE_UNIT_PCT (30%) of account
  - Single position (4 units) ≤ MAX_SINGLE_POSITION_PCT (40%)
  - Unit ≤ MAX_POSITION_PCT_OF_ADV (5%) of ADV
  - shares must be int ≥ 1, else skip

Pure functions — no side effects.
"""

from __future__ import annotations

from config.constants import (
    RISK_PER_UNIT_PCT,
    STOP_LOSS_N,
    STOP_LOSS_MAX_PCT,
    MAX_SINGLE_UNIT_PCT,
    MAX_SINGLE_POSITION_PCT,
    MAX_POSITION_PCT_OF_ADV,
)


# ════════════════════════════════════════════════════════════════
# Unit Sizing
# ════════════════════════════════════════════════════════════════


def calculate_unit_shares(
    account_equity: float,
    entry_price: float,
    n_value: float,
    avg_daily_volume: int | None = None,
    *,
    market: str = "US",
) -> dict:
    """Calculate the number of shares for one unit.

    Uses Minervini risk-based sizing: each unit risks exactly
    RISK_PER_UNIT_PCT (1%) of account equity.  The stop distance is
    the hybrid min(2N, 10%) stop.

    Steps:
        1. Compute stop distance = min(STOP_LOSS_N × N, entry × STOP_LOSS_MAX_PCT).
        2. Dollar risk = account_equity × RISK_PER_UNIT_PCT.
        3. Raw shares = dollar_risk / stop_distance.
        4. Cap by max unit weight (30% of account).
        5. Cap by ADV limit (5% of average daily volume) when available.
        6. Floor to int; skip if < 1.

    Args:
        account_equity: Total account equity (cash + positions).
        entry_price: Planned entry price.
        n_value: Current ATR (N) value.
        avg_daily_volume: Average daily volume in shares. None to skip
            the ADV constraint.
        market: Market code ("US" or "KR"). KR applies tick adjustment
            to stop price.

    Returns:
        Dict with keys: ``shares``, ``skip``, and when skip is False:
        ``stop_distance``, ``stop_price``, ``position_value``,
        ``position_pct``, ``risk_amount``, ``risk_pct``.
        When skip is True, includes ``reason``.
    """
    # Step 0: input guards (spec §4.2)
    if n_value <= 0 or entry_price <= 0 or account_equity <= 0:
        return {"shares": 0, "skip": True, "reason": "Invalid inputs (n/price/equity <= 0)"}

    # Step 1: hybrid stop distance
    stop_distance = min(STOP_LOSS_N * n_value, entry_price * STOP_LOSS_MAX_PCT)

    # Step 2: dollar risk per unit
    dollar_risk = account_equity * RISK_PER_UNIT_PCT

    # Step 3: raw shares from risk budget
    raw_shares = dollar_risk / stop_distance

    # Step 4: max shares by unit weight cap
    max_shares_by_weight = int((account_equity * MAX_SINGLE_UNIT_PCT) / entry_price)

    # Step 5: max shares by ADV limit
    if avg_daily_volume is not None:
        max_shares_by_adv = int(avg_daily_volume * MAX_POSITION_PCT_OF_ADV)
    else:
        max_shares_by_adv = raw_shares

    # Step 6: take the most restrictive limit
    shares = int(min(raw_shares, max_shares_by_weight, max_shares_by_adv))

    # Step 7: skip if insufficient capital
    if shares < 1:
        return {"shares": 0, "skip": True, "reason": "Insufficient capital"}

    # KR market: adjust stop price to tick units
    if market == "KR":
        from config.market_config import adjust_price_to_tick, KR_TICK_SIZE_TABLE
        stop_price = adjust_price_to_tick(entry_price - stop_distance, KR_TICK_SIZE_TABLE)
        # Recalculate stop_distance based on tick-adjusted stop
        stop_distance = entry_price - stop_price
        if stop_distance <= 0:
            return {"shares": 0, "skip": True, "reason": "Stop distance zero after tick adjustment"}
    else:
        stop_price = entry_price - stop_distance

    position_value = shares * entry_price
    risk_amount = shares * stop_distance

    return {
        "shares": shares,
        "skip": False,
        "stop_distance": stop_distance,
        "stop_price": stop_price,
        "position_value": position_value,
        "position_pct": position_value / account_equity,
        "risk_amount": risk_amount,
        "risk_pct": risk_amount / account_equity,
        "market": market,
    }


# ════════════════════════════════════════════════════════════════
# Position Limits
# ════════════════════════════════════════════════════════════════


def calculate_max_position_value(account_equity: float) -> float:
    """Return the maximum value for a single position (all units combined).

    A single stock position (up to 4 units) must not exceed
    MAX_SINGLE_POSITION_PCT (40%) of account equity.

    Args:
        account_equity: Total account equity.

    Returns:
        Maximum dollar value for one position.
    """
    return account_equity * MAX_SINGLE_POSITION_PCT


def can_afford_position(
    account_equity: float,
    entry_price: float,
    shares: int,
    existing_position_value: float = 0.0,
    *,
    market: str = "US",
) -> bool:
    """Check whether adding a new unit would stay within position limits.

    The combined value of existing units plus the new unit must not
    exceed MAX_SINGLE_POSITION_PCT (40%) of account equity.

    Args:
        account_equity: Total account equity.
        entry_price: Entry price for the new unit.
        shares: Number of shares in the new unit.
        existing_position_value: Dollar value of units already held
            in this position.
        market: Market code ("US" or "KR"). Pass-through for consistency.

    Returns:
        True if the position would remain within limits.
    """
    total = existing_position_value + (shares * entry_price)
    return total <= account_equity * MAX_SINGLE_POSITION_PCT
