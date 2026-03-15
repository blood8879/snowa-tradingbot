"""
Trading journal endpoint.

GET /api/journal — returns trade statistics for a given month.
"""

from __future__ import annotations

import calendar
from datetime import datetime, timezone

import csv
from pathlib import Path

import structlog
from fastapi import APIRouter, Depends, Query

from broker.account import AccountManager
from core.database import Database
from web.api.dependencies import get_db, get_account_manager, verify_api_key

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["journal"])


def _load_kr_stock_names() -> dict[str, str]:
    cache_path = Path("data/universe_kr_cache.csv")
    names: dict[str, str] = {}
    if not cache_path.exists():
        return names
    try:
        with open(cache_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                names[row["ticker"]] = row["name"]
    except Exception:
        pass
    return names


@router.get("/journal", dependencies=[Depends(verify_api_key)])
async def get_journal(
    month: str = Query(
        default="",
        description="Month in YYYY-MM format (defaults to current month)",
    ),
    market: str = Query(default="US", description="Market filter (US, KR, ALL)"),
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
    journal_params: list = [month_start, month_end]
    journal_market_clause = ""
    if market and market != "ALL":
        journal_market_clause = "AND market = ?"
        journal_params.append(market)

    cursor = await db.conn.execute(
        f"""
        SELECT ticker, system, realized_pnl, opened_at, closed_at,
               close_reason, avg_entry_price, current_stop_price,
               total_shares, total_cost
        FROM positions
        WHERE status = 'CLOSED'
          AND closed_at BETWEEN ? AND ?
          {journal_market_clause}
        ORDER BY closed_at ASC
        """,
        journal_params,
    )
    rows = await cursor.fetchall()

    kr_names = _load_kr_stock_names() if market == "KR" else {}

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

        ticker = r[0]
        total_cost = r[9] or 0.0
        exit_price = (total_cost + pnl) / total_shares if total_shares > 0 else 0.0

        trades.append({
            "ticker": ticker,
            "name": kr_names.get(ticker) if market == "KR" else None,
            "system": r[1],
            "realized_pnl": pnl,
            "opened_at": r[3],
            "closed_at": r[4],
            "close_reason": r[5],
            "avg_entry_price": avg_entry,
            "stop_price": stop_price,
            "exit_price": round(exit_price, 4),
            "total_shares": total_shares,
            "risk_per_share": round(risk_per_share, 4),
        })

    total_trades = winners + losers
    win_rate = (winners / total_trades * 100) if total_trades > 0 else 0.0
    avg_win = (total_win_pnl / winners) if winners > 0 else 0.0
    avg_loss = (total_loss_pnl / losers) if losers > 0 else 0.0
    risk_reward_ratio = (avg_win / avg_loss) if avg_loss > 0 else 0.0

    # Max drawdown from daily_log for the month
    dd_params: list = [month_start, month_end]
    dd_market_clause = ""
    if market and market != "ALL":
        dd_market_clause = "AND market = ?"
        dd_params.append(market)

    dd_cursor = await db.conn.execute(
        f"""
        SELECT MAX(max_drawdown_pct)
        FROM daily_log
        WHERE date BETWEEN ? AND ?
        {dd_market_clause}
        """,
        dd_params,
    )
    dd_row = await dd_cursor.fetchone()
    max_drawdown_pct = dd_row[0] if dd_row and dd_row[0] else 0.0

    # Monthly P&L from daily_log
    pnl_params: list = [month_start, month_end]
    pnl_market_clause = ""
    if market and market != "ALL":
        pnl_market_clause = "AND market = ?"
        pnl_params.append(market)

    # starting_equity 조회 (인플레이션 감지용)
    _se_key = f"starting_equity_{market}" if market and market != "ALL" else "starting_equity"
    _se_val = await db.get_state(_se_key)
    if not _se_val:
        _se_val = await db.get_state("starting_equity")
    _starting_equity = float(_se_val) if _se_val else 0.0
    _equity_cap = _starting_equity * 2 if _starting_equity > 0 else 0

    # equity_cap이 설정되면 인플레이션된 레코드 제외
    if _equity_cap > 0:
        pnl_market_clause_ext = pnl_market_clause + f" AND account_equity <= {_equity_cap}"
    else:
        pnl_market_clause_ext = pnl_market_clause

    pnl_cursor = await db.conn.execute(
        f"""
        SELECT SUM(daily_pnl), MIN(account_equity), MAX(account_equity)
        FROM daily_log
        WHERE date BETWEEN ? AND ?
        {pnl_market_clause_ext}
        """,
        pnl_params,
    )
    pnl_row = await pnl_cursor.fetchone()
    monthly_pnl = pnl_row[0] if pnl_row and pnl_row[0] else 0.0
    min_equity = pnl_row[1] if pnl_row and pnl_row[1] else 0.0
    max_equity = pnl_row[2] if pnl_row and pnl_row[2] else 0.0

    # ── 현재월이면 실시간 브로커 equity로 보정 ──
    current_month = datetime.now(timezone.utc).strftime("%Y-%m")
    if month == current_month and account_mgr is not None:
        try:
            info = await account_mgr.get_account_info(market=market)
            live_equity = info.total_equity
            if live_equity > 0:
                # 이전 월 마지막 equity 조회 (월초 기준점)
                prev_params: list = [month_start]
                prev_market_clause = ""
                if market and market != "ALL":
                    prev_market_clause = "AND market = ?"
                    prev_params.append(market)
                prev_cursor = await db.conn.execute(
                    f"""
                    SELECT account_equity FROM daily_log
                    WHERE date < ?
                    {prev_market_clause}
                    ORDER BY date DESC LIMIT 1
                    """,
                    prev_params,
                )
                prev_row = await prev_cursor.fetchone()
                prev_month_equity = prev_row[0] if prev_row and prev_row[0] else 0.0

                # 이전 월 equity가 없으면 당월 첫 daily_log equity 사용
                if prev_month_equity <= 0:
                    first_params: list = [month_start, month_end]
                    first_market_clause = ""
                    if market and market != "ALL":
                        first_market_clause = "AND market = ?"
                        first_params.append(market)
                    first_cursor = await db.conn.execute(
                        f"""
                        SELECT account_equity FROM daily_log
                        WHERE date BETWEEN ? AND ?
                        {first_market_clause}
                        ORDER BY date ASC LIMIT 1
                        """,
                        first_params,
                    )
                    first_row = await first_cursor.fetchone()
                    prev_month_equity = first_row[0] if first_row and first_row[0] else 0.0

                # 최종 fallback: 마켓별 starting_equity
                key = f"starting_equity_{market}" if market and market != "ALL" else "starting_equity"
                starting = await db.get_state(key)
                if not starting:
                    starting = await db.get_state("starting_equity")
                starting_equity = float(starting) if starting else 0.0

                if prev_month_equity <= 0:
                    prev_month_equity = starting_equity

                # prev_month_equity가 starting_equity 대비 비정상적으로 높으면
                # (Bug #25: paper 모드 잔고 인플레이션) starting_equity로 대체
                if starting_equity > 0 and prev_month_equity > starting_equity * 2:
                    logger.warning(
                        "journal_prev_equity_inflated",
                        prev_month_equity=prev_month_equity,
                        starting_equity=starting_equity,
                        market=market,
                    )
                    prev_month_equity = starting_equity

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
