"""
Entry signal detection for Turtle Trading Systems 1 and 2.

System 1: 20-day Donchian breakout (with last-breakout filter)
System 2: 55-day Donchian breakout (no filter — always enter)

Pure functions — determine IF a signal exists, not execute trades.
"""
from __future__ import annotations

from config.constants import (
    SYSTEM1_ENTRY_DAYS,
    SYSTEM2_ENTRY_DAYS,
    SYSTEM1_FILTER_ENABLED,
    SYSTEM2_FILTER_ENABLED,
    BUY_BUFFER_PCT,
)
from core.models import TradingSystem


# ------------------------------------------------------------------
# System 1 entry
# ------------------------------------------------------------------

def check_s1_entry(
    current_price: float,
    donchian_upper_20: float,
    last_breakout_was_winner: bool | None = None,
) -> dict:
    """Check System 1 (20-day) entry signal.

    A signal fires when *current_price* exceeds the 20-day Donchian
    high (*donchian_upper_20*).

    **System 1 filter** (``SYSTEM1_FILTER_ENABLED = True``):
      * If the most recent breakout was a winner → **skip** this entry.
      * If the most recent breakout was a loser or there is no prior
        breakout history (``None``) → **enter**.

    Returns a dict describing the signal and any filter outcome.
    """
    breakout = current_price > donchian_upper_20

    filtered_out = False
    reason = ""

    if breakout and SYSTEM1_FILTER_ENABLED:
        if last_breakout_was_winner is True:
            filtered_out = True
            reason = "S1 filter: prior breakout was a winner — skipped"
        elif last_breakout_was_winner is False:
            reason = "S1 filter: prior breakout was a loser — entering"
        else:
            reason = "S1 filter: no prior breakout history — entering"
    elif breakout:
        reason = "S1 breakout detected (filter disabled)"
    else:
        reason = "No S1 breakout"

    signal = breakout and not filtered_out

    return {
        "signal": signal,
        "system": TradingSystem.S1.value,
        "breakout_level": donchian_upper_20,
        "entry_price": current_price,
        "filtered_out": filtered_out,
        "reason": reason,
    }


# ------------------------------------------------------------------
# System 2 entry
# ------------------------------------------------------------------

def check_s2_entry(
    current_price: float,
    donchian_upper_55: float,
) -> dict:
    """Check System 2 (55-day) entry signal.

    A signal fires when *current_price* exceeds the 55-day Donchian
    high (*donchian_upper_55*).  No filter is applied — every
    breakout is entered.

    Returns a dict describing the signal.
    """
    breakout = current_price > donchian_upper_55

    return {
        "signal": breakout,
        "system": TradingSystem.S2.value,
        "breakout_level": donchian_upper_55,
        "entry_price": current_price,
    }


# ------------------------------------------------------------------
# Combined entry check
# ------------------------------------------------------------------

def check_entry_signals(
    current_price: float,
    donchian_levels: dict[str, float | None],
    last_s1_breakout_winner: bool | None = None,
    market_filter_pass: bool = True,
) -> list[dict]:
    """Check both System 1 and System 2 entry signals.

    Parameters
    ----------
    current_price:
        Latest traded / closing price.
    donchian_levels:
        Dict with at least ``upper_20`` and ``upper_55`` keys
        (as returned by :func:`strategy.donchian.calculate_donchian_levels`).
    last_s1_breakout_winner:
        Whether the most recent S1 breakout was profitable.
        Passed through to :func:`check_s1_entry`.
    market_filter_pass:
        ``False`` when the broad-market filter (e.g. SPY < 200 MA)
        forbids new entries.  Returns an empty list immediately.

    Returns
    -------
    list[dict]
        Zero, one, or two signal dicts — System 1 checked first,
        then System 2.
    """
    if not market_filter_pass:
        return []

    signals: list[dict] = []

    # --- System 1 ---
    upper_20 = donchian_levels.get("upper_20")
    if upper_20 is not None:
        s1 = check_s1_entry(current_price, upper_20, last_s1_breakout_winner)
        if s1["signal"]:
            signals.append(s1)

    # --- System 2 ---
    upper_55 = donchian_levels.get("upper_55")
    if upper_55 is not None:
        s2 = check_s2_entry(current_price, upper_55)
        if s2["signal"]:
            signals.append(s2)

    return signals


# ------------------------------------------------------------------
# Entry-price helper
# ------------------------------------------------------------------

def calculate_entry_price(
    breakout_level: float,
    buffer_pct: float = BUY_BUFFER_PCT,
) -> float:
    """Calculate the limit-order entry price.

    ``entry_price = breakout_level × (1 + buffer_pct)``

    With the default ``BUY_BUFFER_PCT = 0.003`` this places the order
    0.3 % above the breakout level.
    """
    return breakout_level * (1.0 + buffer_pct)
