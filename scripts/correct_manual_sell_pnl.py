"""Correct realized_pnl for positions that sync closed with an estimated price.

When a position vanished from the broker (manual sell) before the actual-fill
lookup existed, sync_positions closed it using the stop price as an estimate.
This one-off reads the real sell fills from the broker and rewrites realized_pnl
with the actual exit price.

Idempotent: only touches positions still marked with an estimated close_reason
('sync_broker_missing' / 'sync_stop_estimated'); corrected rows are re-tagged
'sync_filled_actual_corrected' and skipped on re-run.

Run while the bot is stopped (self-authenticates REST only, no WS approval).

Usage:
    python -m scripts.correct_manual_sell_pnl [--days N] [--dry-run]
"""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timedelta

import structlog

structlog.configure(
    processors=[structlog.processors.TimeStamper(fmt="iso"), structlog.dev.ConsoleRenderer()],
    wrapper_class=structlog.make_filtering_bound_logger(0),
)
logger = structlog.get_logger(__name__)


async def main() -> None:
    dry_run = "--dry-run" in sys.argv
    days = 7
    if "--days" in sys.argv:
        try:
            days = int(sys.argv[sys.argv.index("--days") + 1])
        except (ValueError, IndexError):
            pass

    from config.settings import get_settings
    from core.database import Database
    from broker.kis_auth import KISAuth
    from broker.kis_rest import KISRestClient

    s = get_settings()
    db = Database(str(s.db_full_path))
    await db.initialize()

    auth = KISAuth()
    await auth.refresh_access_token()  # REST 토큰만 — WS approval 미발급(충돌 방지)
    rest = KISRestClient(auth)

    end = datetime.now().strftime("%Y%m%d")
    start = (datetime.now() - timedelta(days=days)).strftime("%Y%m%d")
    fills = await rest.get_filled_orders(start, end, market="US")

    sells: dict[str, dict[str, float]] = {}
    for f in fills:
        if str(f.get("sll_buy_dvsn_cd", "")) not in ("01", "1"):  # 01 = 매도
            continue
        tk = (f.get("pdno") or "").upper()
        qty = int(float(f.get("ft_ccld_qty") or f.get("tot_ccld_qty") or 0))
        price = float(f.get("ft_ccld_unpr3") or 0)
        if not tk or qty <= 0 or price <= 0:
            continue
        agg = sells.setdefault(tk, {"qty": 0.0, "amount": 0.0})
        agg["qty"] += qty
        agg["amount"] += price * qty

    logger.info("correct_pnl_fills_loaded", start=start, end=end, sell_tickers=sorted(sells.keys()))

    cur = await db.conn.execute(
        """SELECT id, ticker, total_shares, total_cost, realized_pnl, close_reason
           FROM positions
           WHERE status = 'CLOSED'
             AND close_reason IN ('sync_broker_missing', 'sync_stop_estimated')"""
    )
    rows = await cur.fetchall()

    corrected, skipped = 0, 0
    for pid, ticker, shares, cost, old_pnl, reason in rows:
        agg = sells.get((ticker or "").upper())
        if not agg or agg["qty"] <= 0:
            logger.warning("correct_pnl_skip_no_fill", ticker=ticker, position_id=pid)
            skipped += 1
            continue
        avg_exit = agg["amount"] / agg["qty"]
        new_pnl = avg_exit * (shares or 0) - (cost or 0)
        logger.info(
            "correct_pnl_apply",
            ticker=ticker,
            position_id=pid,
            exit_price=round(avg_exit, 4),
            old_realized_pnl=old_pnl,
            new_realized_pnl=round(new_pnl, 2),
            dry_run=dry_run,
        )
        if not dry_run:
            await db.conn.execute(
                "UPDATE positions SET realized_pnl = ?, close_reason = 'sync_filled_actual_corrected' WHERE id = ?",
                (new_pnl, pid),
            )
        corrected += 1

    if not dry_run:
        await db.conn.commit()
    logger.info("correct_pnl_complete", corrected=corrected, skipped=skipped, dry_run=dry_run)
    await db.close()


if __name__ == "__main__":
    asyncio.run(main())
