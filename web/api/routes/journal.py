"""
Trading journal endpoint.

GET /api/journal — returns trade statistics for a given month.
"""

from __future__ import annotations

import calendar
from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, Depends, Query

from broker.account import AccountManager
from core.database import Database
from web.api.dependencies import get_db, get_account_manager, verify_api_key

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["journal"])


@router.get("/journal", dependencies=[Depends(verify_api_key)])
async def get_journal(
    month: str = Query(
        default="",
        description="Month in YYYY-MM format (defaults to current month)",
    ),
    db: Database = Depends(get_db),
    account_mgr: AccountManager | None = Depends(get_account_manager),
) -> dict:
    """Return trade statistics for a specified month.

    Calculates win rate, risk-reward ratio, max drawdown,
    and other statistics from closed positions in the given month.

    Args:
        month: Target month in YYYY-MM format.
        db: Database dependency.

    Returns:
        Dict with monthly trade stats (win rate, R:R, MDD, etc.).
    """
    # Default to current month
    if not month:
        month = datetime.now().strftime("%Y-%m")

    # Validate format
    try:
        datetime.strptime(month, "%Y-%m")
    except ValueError:
        return {"error": "Invalid month format. Use YYYY-MM."}

    month_start = f"{month}-01"
    year, mon = month.split("-")
    last_day = calendar.monthrange(int(year), int(mon))[1]
    month_end = f"{month}-{last_day:02d}"

    # Closed positions in this month
    cursor = await db.conn.execute(
        """
        SELECT ticker, system, realized_pnl, opened_at, closed_at,
               close_reason, avg_entry_price, current_stop_price,
               total_shares, total_cost
        FROM positions
        WHERE status = 'CLOSED'
          AND closed_at BETWEEN ? AND ?
        ORDER BY closed_at ASC
        """,
        (month_start, month_end),
    )
    rows = await cursor.fetchall()

    trades = []
    winners = 0
    losers = 0
    total_win_pnl = 0.0
    total_loss_pnl = 0.0
    total_risk = 0.0
    total_reward = 0.0

    for r in rows:
        pnl = r[2] or 0.0
        avg_entry = r[6] or 0.0
        stop_price = r[7] or 0.0
        total_shares = r[8] or 0

        # Risk per share = entry - stop
        risk_per_share = abs(avg_entry - stop_price) if avg_entry and stop_price else 0.0
        risk_total = risk_per_share * total_shares

        if pnl > 0:
            winners += 1
            total_win_pnl += pnl
            total_reward += pnl
        elif pnl < 0:
            losers += 1
            total_loss_pnl += abs(pnl)

        total_risk += risk_total

        trades.append({
            "ticker": r[0],
            "system": r[1],
            "realized_pnl": pnl,
            "opened_at": r[3],
            "closed_at": r[4],
            "close_reason": r[5],
            "avg_entry_price": avg_entry,
            "stop_price": stop_price,
            "total_shares": total_shares,
            "risk_per_share": round(risk_per_share, 4),
        })

    total_trades = winners + losers
    win_rate = (winners / total_trades * 100) if total_trades > 0 else 0.0
    avg_win = (total_win_pnl / winners) if winners > 0 else 0.0
    avg_loss = (total_loss_pnl / losers) if losers > 0 else 0.0
    risk_reward_ratio = (avg_win / avg_loss) if avg_loss > 0 else 0.0

    # Max drawdown from daily_log for the month
    dd_cursor = await db.conn.execute(
        """
        SELECT MAX(max_drawdown_pct)
        FROM daily_log
        WHERE date BETWEEN ? AND ?
        """,
        (month_start, month_end),
    )
    dd_row = await dd_cursor.fetchone()
    max_drawdown_pct = dd_row[0] if dd_row and dd_row[0] else 0.0

    # Monthly P&L from daily_log
    pnl_cursor = await db.conn.execute(
        """
        SELECT SUM(daily_pnl), MIN(account_equity), MAX(account_equity)
        FROM daily_log
        WHERE date BETWEEN ? AND ?
        """,
        (month_start, month_end),
    )
    pnl_row = await pnl_cursor.fetchone()
    monthly_pnl = pnl_row[0] if pnl_row and pnl_row[0] else 0.0
    min_equity = pnl_row[1] if pnl_row and pnl_row[1] else 0.0
    max_equity = pnl_row[2] if pnl_row and pnl_row[2] else 0.0

    # ── 현재월이면 실시간 브로커 equity로 보정 ──
    current_month = datetime.now(timezone.utc).strftime("%Y-%m")
    if month == current_month and account_mgr is not None:
        try:
            info = await account_mgr.get_account_info()
            live_equity = info.total_equity
            if live_equity > 0:
                # 이전 월 마지막 equity 조회 (월초 기준점)
                prev_cursor = await db.conn.execute(
                    """
                    SELECT account_equity FROM daily_log
                    WHERE date < ?
                    ORDER BY date DESC LIMIT 1
                    """,
                    (month_start,),
                )
                prev_row = await prev_cursor.fetchone()
                prev_month_equity = prev_row[0] if prev_row and prev_row[0] else 0.0

                # 이전 월 equity가 없으면 starting_equity 사용
                if prev_month_equity <= 0:
                    starting = await db.get_state("starting_equity")
                    prev_month_equity = float(starting) if starting else 0.0

                if prev_month_equity > 0:
                    monthly_pnl = live_equity - prev_month_equity

                max_equity = max(max_equity, live_equity)
                if min_equity <= 0:
                    min_equity = live_equity
                else:
                    min_equity = min(min_equity, live_equity)
        except Exception as exc:
            logger.warning("journal_live_equity_failed", error=str(exc))

    return {
        "month": month,
        "stats": {
            "total_trades": total_trades,
            "winners": winners,
            "losers": losers,
            "win_rate_pct": round(win_rate, 2),
            "avg_win": round(avg_win, 2),
            "avg_loss": round(avg_loss, 2),
            "risk_reward_ratio": round(risk_reward_ratio, 2),
            "max_drawdown_pct": round(max_drawdown_pct, 4),
            "monthly_pnl": round(monthly_pnl, 2),
            "min_equity": round(min_equity, 2),
            "max_equity": round(max_equity, 2),
        },
        "trades": trades,
    }
