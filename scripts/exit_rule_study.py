"""Exit-rule comparison study (daily-bar level).

For each CLOSED position, replays alternative exit rules over the daily bars
*after entry* and compares the hypothetical result to what actually happened.
Uses entry price/shares/date from positions + daily_prices OHLC.

CAVEATS (read before trusting):
  - Small sample → exploratory only, not statistically conclusive.
  - Ignores pyramiding (uses avg_entry_price × total_shares).
  - Daily-bar fills: stop/Donchian exits assume fill at the trigger level
    (gaps approximated by that day's open when worse). No slippage.
  - "hold/untriggered" rules mark to the latest close (unrealized) — so they
    include open-trade marks, not realized cash. Compare with that in mind.

Usage:
    python -m scripts.exit_rule_study [--market US]
"""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime

RULES = ["actual", "donchian10", "donchian20", "trail_2n", "trail_3n", "time20", "hold"]


def _simulate(entry_price: float, bars: list, rule: str, n: float | None):
    """Return (exit_date, exit_price, triggered: bool) for a rule over post-entry bars.

    bars: list of (date, open, high, low, close), oldest first.
    """
    highest = entry_price
    for i, (date, o, h, low, c) in enumerate(bars):
        highest = max(highest, h)
        if rule == "trail_2n" and n:
            stop = highest - 2 * n
            if low <= stop:
                return date, min(stop, o), True
        elif rule == "trail_3n" and n:
            stop = highest - 3 * n
            if low <= stop:
                return date, min(stop, o), True
        elif rule == "donchian10" and i >= 10:
            low10 = min(b[3] for b in bars[i - 10:i])
            if low <= low10:
                return date, min(low10, o), True
        elif rule == "donchian20" and i >= 20:
            low20 = min(b[3] for b in bars[i - 20:i])
            if low <= low20:
                return date, min(low20, o), True
        elif rule == "time20" and i >= 19:
            return date, c, True
    # untriggered → mark to last close (open-trade mark)
    return bars[-1][0], bars[-1][4], False


def _days(d1: str, d2: str) -> int:
    try:
        return (datetime.fromisoformat(d2[:10]) - datetime.fromisoformat(d1[:10])).days
    except Exception:
        return 0


async def main() -> None:
    market = "US"
    if "--market" in sys.argv:
        market = sys.argv[sys.argv.index("--market") + 1]

    from config.settings import get_settings
    from core.database import Database
    from strategy.atr import calculate_n_single

    s = get_settings()
    db = Database(str(s.db_full_path))
    await db.initialize()

    cur = await db.conn.execute(
        "SELECT ticker, avg_entry_price, total_shares, opened_at, closed_at, realized_pnl "
        "FROM positions WHERE status='CLOSED' AND market=? AND realized_pnl IS NOT NULL "
        "ORDER BY opened_at",
        (market,),
    )
    positions = await cur.fetchall()

    agg = {r: {"pnl": 0.0, "wins": 0, "n": 0, "days": 0, "untrig": 0} for r in RULES}

    for ticker, entry, shares, opened, closed, real_pnl in positions:
        ed = (opened or "")[:10]
        # N from up-to-entry bars
        ncur = await db.conn.execute(
            "SELECT high, low, close FROM daily_prices WHERE ticker=? AND date<=? ORDER BY date DESC LIMIT 25",
            (ticker, ed),
        )
        pre = list(reversed(await ncur.fetchall()))
        nval = (
            calculate_n_single([b[0] for b in pre], [b[1] for b in pre], [b[2] for b in pre])
            if len(pre) >= 20
            else None
        )
        bcur = await db.conn.execute(
            "SELECT date, open, high, low, close FROM daily_prices WHERE ticker=? AND date>? ORDER BY date",
            (ticker, ed),
        )
        bars = await bcur.fetchall()
        if not bars or not entry or not shares:
            continue

        for rule in RULES:
            if rule == "actual":
                pnl = real_pnl
                exit_date, trig = (closed or "")[:10], True
            else:
                exit_date, exit_price, trig = _simulate(entry, bars, rule, nval)
                pnl = (exit_price - entry) * shares
            agg[rule]["pnl"] += pnl
            agg[rule]["n"] += 1
            agg[rule]["days"] += _days(ed, exit_date)
            if pnl > 0:
                agg[rule]["wins"] += 1
            if not trig:
                agg[rule]["untrig"] += 1

    print(f"\nExit-rule study — market={market}, sample={len(positions)} closed positions")
    print(f"{'rule':12} {'total_pnl':>10} {'avg_pnl':>9} {'win%':>6} {'avg_days':>9} {'open_marks':>11}")
    for r in RULES:
        a = agg[r]
        if a["n"] == 0:
            continue
        print(
            f"{r:12} {a['pnl']:>10.1f} {a['pnl']/a['n']:>9.1f} "
            f"{100*a['wins']/a['n']:>5.0f}% {a['days']/a['n']:>8.1f} {a['untrig']:>11}"
        )
    print("\n(open_marks = trades the rule never exited → marked to latest close, unrealized)")
    await db.close()


if __name__ == "__main__":
    asyncio.run(main())
