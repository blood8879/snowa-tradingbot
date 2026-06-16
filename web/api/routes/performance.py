"""
Performance / P&L endpoint.

GET /api/pnl — returns P&L data from daily_log for equity curve charting.
"""

from __future__ import annotations

from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, Depends, Query

from broker.account import AccountManager
from core.database import Database
from web.api.dependencies import get_db, get_account_manager, verify_api_key

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["performance"])


@router.get("/pnl", dependencies=[Depends(verify_api_key)])
async def get_pnl(
    period: str = Query(
        default="daily",
        description="Aggregation period: daily, weekly, or monthly",
    ),
    market: str = Query(default="US", description="Market filter"),
    db: Database = Depends(get_db),
    account_mgr: AccountManager | None = Depends(get_account_manager),
) -> dict:
    """Return P&L data from daily_log for equity curve visualization.

    Args:
        period: One of 'daily', 'weekly', or 'monthly'.
        db: Database dependency.

    Returns:
        Dict with equity curve data points and summary statistics.
    """
    if period == "weekly":
        # Group by ISO week — use strftime to get Monday of each week
        cursor = await db.conn.execute(
            """
            SELECT
                strftime('%Y-W%W', date) AS period_key,
                MIN(date) AS period_start,
                MAX(date) AS period_end,
                SUM(daily_pnl) AS period_pnl,
                MAX(account_equity) AS ending_equity,
                MAX(max_drawdown_pct) AS max_drawdown_pct,
                SUM(entries_count) AS entries,
                SUM(exits_count) AS exits,
                SUM(stop_losses_count) AS stop_losses
            FROM daily_log
            WHERE market = ?
            GROUP BY strftime('%Y-W%W', date)
            ORDER BY period_start ASC
            """,
            (market,)
        )
    elif period == "monthly":
        cursor = await db.conn.execute(
            """
            SELECT
                strftime('%Y-%m', date) AS period_key,
                MIN(date) AS period_start,
                MAX(date) AS period_end,
                SUM(daily_pnl) AS period_pnl,
                MAX(account_equity) AS ending_equity,
                MAX(max_drawdown_pct) AS max_drawdown_pct,
                SUM(entries_count) AS entries,
                SUM(exits_count) AS exits,
                SUM(stop_losses_count) AS stop_losses
            FROM daily_log
            WHERE market = ?
            GROUP BY strftime('%Y-%m', date)
            ORDER BY period_start ASC
            """,
            (market,)
        )
    else:
        # Daily (default)
        cursor = await db.conn.execute(
            """
            SELECT
                date AS period_key,
                date AS period_start,
                date AS period_end,
                daily_pnl AS period_pnl,
                account_equity AS ending_equity,
                max_drawdown_pct,
                entries_count AS entries,
                exits_count AS exits,
                stop_losses_count AS stop_losses,
                cash_balance AS cash
            FROM daily_log
            WHERE market = ?
            ORDER BY date ASC
            """,
            (market,)
        )

    rows = await cursor.fetchall()

    data_points = [
        {
            "period": r[0],
            "start": r[1],
            "end": r[2],
            "pnl": r[3],
            "equity": r[4],
            "max_drawdown_pct": r[5],
            "entries": r[6],
            "exits": r[7],
            "stop_losses": r[8],
            "cash": r[9] if len(r) > 9 else None,
        }
        for r in rows
    ]

    # ── 실시간 브로커 equity로 현재일/현재 기간 보정 ──
    if account_mgr is not None:
        try:
            info = await account_mgr.get_account_info(market=market)
            live_equity = info.total_equity
            if live_equity > 0:
                today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                if period == "daily":
                    _supplement_daily_equity(data_points, today, live_equity)
                else:
                    # weekly/monthly: daily_log의 마지막 기록 equity로 오늘 delta 계산
                    prev_cursor = await db.conn.execute(
                        "SELECT account_equity FROM daily_log WHERE market = ? ORDER BY date DESC LIMIT 1",
                        (market,),
                    )
                    prev_row = await prev_cursor.fetchone()
                    last_recorded = prev_row[0] if prev_row and prev_row[0] else 0.0
                    _supplement_period_equity(
                        data_points, today, live_equity, last_recorded,
                    )
        except Exception as exc:
            logger.warning("pnl_live_equity_failed", error=str(exc))

    # ── 실현/미실현 손익 시계열 (daily, 원금·입금 무관) ──
    # realized_cum: 청산일까지 누적 실현손익
    # unrealized: 그날 평가액(account_equity - cash) - 보유 units 매입원가
    if period == "daily" and data_points:
        ucur = await db.conn.execute(
            "SELECT u.shares, u.entry_price, u.entered_at, p.opened_at, p.closed_at "
            "FROM units u JOIN positions p ON p.id = u.position_id WHERE p.market = ?",
            (market,),
        )
        urows = await ucur.fetchall()
        ccur = await db.conn.execute(
            "SELECT realized_pnl, closed_at FROM positions "
            "WHERE status = 'CLOSED' AND market = ? AND realized_pnl IS NOT NULL",
            (market,),
        )
        crows = await ccur.fetchall()

        for dp in data_points:
            d = (dp.get("period") or "")[:10]
            cost_basis = sum(
                (u[0] or 0) * (u[1] or 0)
                for u in urows
                if (u[2] or "")[:10] <= d
                and (u[3] or "")[:10] <= d
                and (u[4] is None or (u[4] or "")[:10] > d)
            )
            dp["realized_cum"] = round(
                sum((c[0] or 0) for c in crows if (c[1] or "")[:10] <= d), 2
            )
            cash = dp.get("cash")
            if cash is not None and dp.get("equity") is not None:
                dp["unrealized"] = round((dp["equity"] - cash) - cost_basis, 2)
            else:
                dp["unrealized"] = None

        # 마지막(오늘) 점은 실시간 평가액/실현으로 보정
        if account_mgr is not None:
            try:
                info = await account_mgr.get_account_info(market=market)
                ocur = await db.conn.execute(
                    "SELECT COALESCE(SUM(total_cost), 0) FROM positions WHERE status='OPEN' AND market=?",
                    (market,),
                )
                open_cost = (await ocur.fetchone())[0] or 0.0
                data_points[-1]["unrealized"] = round((info.total_positions_value or 0.0) - open_cost, 2)
                data_points[-1]["realized_cum"] = round(sum((c[0] or 0) for c in crows), 2)
            except Exception:
                pass

    # Summary stats
    total_pnl = sum(d["pnl"] or 0.0 for d in data_points)
    max_equity = max((d["equity"] or 0.0 for d in data_points), default=0.0)
    max_drawdown = max((d["max_drawdown_pct"] or 0.0 for d in data_points), default=0.0)

    # 순수 실현 매매손익 — 청산된 포지션의 realized_pnl 합.
    # total_pnl(=일별 equity 변화 누적)은 입금/출금이 섞이지만, 이 값은
    # 매매로만 발생한 손익이라 입금과 무관하다.
    rcur = await db.conn.execute(
        "SELECT COALESCE(SUM(realized_pnl), 0) FROM positions WHERE status = 'CLOSED' AND market = ?",
        (market,),
    )
    realized_pnl_total = (await rcur.fetchone())[0] or 0.0

    last_unrealized = None
    if period == "daily" and data_points:
        last_unrealized = data_points[-1].get("unrealized")
    net_pnl = (realized_pnl_total + last_unrealized) if last_unrealized is not None else None

    return {
        "period": period,
        "market": market,
        "data": data_points,
        "summary": {
            "total_pnl": total_pnl,
            "realized_pnl": realized_pnl_total,
            "unrealized_pnl": last_unrealized,
            "net_pnl": net_pnl,
            "max_equity": max_equity,
            "max_drawdown_pct": max_drawdown,
            "data_points": len(data_points),
        },
    }


def _supplement_daily_equity(
    data_points: list[dict],
    today: str,
    live_equity: float,
) -> None:
    """daily period: 오늘 항목을 실시간 equity로 보정/추가한다."""
    if not data_points:
        return

    for i, dp in enumerate(data_points):
        if dp["period"] == today:
            prev_eq = data_points[i - 1]["equity"] if i > 0 else 0.0
            prev_eq = prev_eq or 0.0
            dp["equity"] = live_equity
            dp["pnl"] = live_equity - prev_eq if prev_eq > 0 else 0.0
            return
    # 오늘 항목이 없으면 추가
    prev_eq = data_points[-1]["equity"] or 0.0
    data_points.append({
        "period": today,
        "start": today,
        "end": today,
        "pnl": live_equity - prev_eq if prev_eq > 0 else 0.0,
        "equity": live_equity,
        "max_drawdown_pct": 0.0,
        "entries": 0,
        "exits": 0,
        "stop_losses": 0,
    })


def _supplement_period_equity(
    data_points: list[dict],
    today: str,
    live_equity: float,
    last_recorded_equity: float,
) -> None:
    """weekly/monthly period: 마지막 기간에 오늘의 실시간 delta를 반영한다."""
    if not data_points:
        return

    last = data_points[-1]
    start_date = last.get("start", "")
    # 마지막 기간이 오늘 이전에 종료되었으면 보정 불필요
    if start_date > today:
        return

    # 오늘의 daily_pnl = 실시간 equity - 마지막 기록된 equity
    today_pnl = 0.0
    if last_recorded_equity > 0:
        today_pnl = live_equity - last_recorded_equity

    last["pnl"] = (last["pnl"] or 0.0) + today_pnl
    last["equity"] = live_equity
