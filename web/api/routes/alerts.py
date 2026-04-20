from __future__ import annotations

from datetime import datetime, timedelta, timezone

import structlog
from fastapi import APIRouter, Depends

from broker.account import AccountManager
from core.database import Database
from web.api.dependencies import get_db, get_account_manager, verify_api_key
from web.api.routes.market_filter_calc import compute_market_filter
from web.api.routes.watchlist import _load_kr_stock_names

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["alerts"])


@router.get("/alerts/near-entry", dependencies=[Depends(verify_api_key)])
async def get_near_entry_alerts(
    market: str = "US",
    db: Database = Depends(get_db),
    account_mgr: AccountManager | None = Depends(get_account_manager),
) -> dict:
    params: list = []
    market_clause = ""
    if market and market != "ALL":
        market_clause = "AND w.market = ?"
        params.append(market)

    watchlist_cursor = await db.conn.execute(
        f"""
        SELECT w.ticker, w.rs_rating, w.custom_composite_score, w.latest_price,
               f.latest_report_date, w.name, w.exchange
        FROM watchlist w
        LEFT JOIN (
            SELECT ticker, MAX(report_date) AS latest_report_date
            FROM fundamentals
            GROUP BY ticker
        ) f ON f.ticker = w.ticker
        WHERE w.status = 'ACTIVE'
        {market_clause}
        """,
        params,
    )
    watchlist_rows = await watchlist_cursor.fetchall()

    # KR 종목명 CSV fallback
    kr_names = _load_kr_stock_names() if market == "KR" else {}

    # 실시간 가격 조회 (KIS REST API) — 전체 5초 타임아웃, 실패 시 DB 캐시 사용
    realtime_prices: dict[str, float] = {}
    if account_mgr is not None:
        import asyncio

        async def _fetch_realtime() -> None:
            rest_client = account_mgr._rest
            for row in watchlist_rows:
                ticker = row[0]
                exchange = row[6] or ("J" if market == "KR" else "NASD")
                try:
                    if market == "KR":
                        price_data = await rest_client.get_current_price(ticker, exchange, market="KR")
                        raw = price_data.get("stck_prpr", "0")
                    else:
                        price_data = await rest_client.get_current_price(ticker, exchange, market="US")
                        raw = price_data.get("last", "0")
                    val = float(raw)
                    if val > 0:
                        realtime_prices[ticker] = val
                    await asyncio.sleep(0.35)  # KIS rate limit 방지
                except Exception:
                    logger.debug("alerts_realtime_price_failed", ticker=ticker, market=market)

        try:
            await asyncio.wait_for(_fetch_realtime(), timeout=5.0)
        except asyncio.TimeoutError:
            logger.warning("alerts_realtime_price_timeout", market=market, fetched=len(realtime_prices))

    alerts: list[dict] = []

    for row in watchlist_rows:
        ticker = row[0]
        rs_rating = row[1]
        composite_score = row[2]
        latest_price = row[3]
        latest_financial_date = row[4]
        name = row[5] or kr_names.get(ticker)

        prices_cursor = await db.conn.execute(
            """
            SELECT high, low, close
            FROM daily_prices
            WHERE ticker = ?
            ORDER BY date DESC
            LIMIT 55
            """,
            (ticker,),
        )
        price_rows = await prices_cursor.fetchall()

        # 실시간 가격 > daily_prices 종가 > watchlist.latest_price 순으로 우선
        if ticker in realtime_prices:
            latest_price = realtime_prices[ticker]
        elif price_rows and price_rows[0][2]:
            latest_price = price_rows[0][2]

        if latest_price is None:
            continue

        if len(price_rows) < 20:
            continue

        highs_20 = [r[0] for r in price_rows[:20]]
        lows_20 = [r[1] for r in price_rows[:20]]
        donchian_upper_20 = max(highs_20)
        donchian_lower_20 = min(lows_20)

        donchian_upper_55: float | None = None
        if len(price_rows) >= 55:
            highs_55 = [r[0] for r in price_rows[:55]]
            donchian_upper_55 = max(highs_55)

        proximity_20 = ((donchian_upper_20 - latest_price) / donchian_upper_20) * 100
        proximity_55: float | None = None
        if donchian_upper_55 is not None:
            proximity_55 = ((donchian_upper_55 - latest_price) / donchian_upper_55) * 100

        already_broken_20 = latest_price >= donchian_upper_20
        already_broken_55 = donchian_upper_55 is not None and latest_price >= donchian_upper_55

        signal_type: str = "none"
        if already_broken_20 and already_broken_55:
            signal_type = "S1+S2"
        elif already_broken_55:
            signal_type = "S2"
        elif already_broken_20:
            signal_type = "S1"
        elif proximity_20 <= 5.0:
            signal_type = "S1"
        elif proximity_55 is not None and proximity_55 <= 5.0:
            signal_type = "S2"

        alert_level = "normal"
        if already_broken_20 or already_broken_55:
            alert_level = "breakout"
        elif proximity_20 <= 2.0:
            alert_level = "imminent"
        elif proximity_20 <= 5.0:
            alert_level = "close"

        closes_20 = [r[2] for r in price_rows[:20]]
        sma_20 = sum(closes_20) / len(closes_20)

        alerts.append({
            "ticker": ticker,
            "name": name,
            "latest_price": latest_price,
            "donchian_upper_20": donchian_upper_20,
            "donchian_upper_55": donchian_upper_55,
            "donchian_lower_20": donchian_lower_20,
            "proximity_pct_20": round(proximity_20, 2),
            "proximity_pct_55": round(proximity_55, 2) if proximity_55 is not None else None,
            "already_broken_20": already_broken_20,
            "already_broken_55": already_broken_55,
            "signal_type": signal_type,
            "alert_level": alert_level,
            "rs_rating": rs_rating,
            "composite_score": composite_score,
            "sma_20": round(sma_20, 2),
            "latest_financial_date": latest_financial_date,
        })

    alerts.sort(key=lambda a: a["proximity_pct_20"])

    imminent_count = sum(1 for a in alerts if a["alert_level"] == "imminent")
    breakout_count = sum(1 for a in alerts if a["alert_level"] == "breakout")

    return {
        "alerts": alerts,
        "total": len(alerts),
        "imminent_count": imminent_count,
        "breakout_count": breakout_count,
    }


@router.get("/alerts/near-exit", dependencies=[Depends(verify_api_key)])
async def get_near_exit_alerts(
    market: str = "US",
    db: Database = Depends(get_db),
    account_mgr: AccountManager | None = Depends(get_account_manager),
) -> dict:
    # 브로커 실시간 데이터 조회 (해당 시장 기준)
    broker_by_ticker: dict[str, dict] = {}
    if account_mgr is not None:
        try:
            broker_positions = await account_mgr.get_broker_positions(market=market)
            broker_by_ticker = {bp["ticker"]: bp for bp in broker_positions}
        except Exception:
            logger.warning("exit_alerts_broker_fetch_failed", exc_info=True)

    pos_params: list = []
    pos_market_clause = ""
    if market and market != "ALL":
        pos_market_clause = "AND market = ?"
        pos_params.append(market)

    pos_cursor = await db.conn.execute(
        f"""
        SELECT p.id, p.ticker, p.system, p.avg_entry_price, w.name, p.current_stop_price
        FROM positions p
        LEFT JOIN watchlist w ON w.ticker = p.ticker
        WHERE p.status = 'OPEN'
        {pos_market_clause.replace("market", "p.market")}
        """,
        pos_params,
    )
    pos_rows = await pos_cursor.fetchall()

    # KR 종목명 CSV fallback
    kr_names_exit = _load_kr_stock_names() if market == "KR" else {}

    alerts: list[dict] = []

    for row in pos_rows:
        ticker = row[1]
        stock_name = row[4] or kr_names_exit.get(ticker)
        system = row[2] or "S1"
        entry_price = row[3]
        current_stop_price = row[5]

        prices_cursor = await db.conn.execute(
            """
            SELECT high, low, close
            FROM daily_prices
            WHERE ticker = ?
            ORDER BY date DESC
            LIMIT 20
            """,
            (ticker,),
        )
        price_rows = await prices_cursor.fetchall()

        if not price_rows:
            continue

        # 실시간 가격 우선, 없으면 daily_prices 종가 폴백
        bp = broker_by_ticker.get(ticker)
        current_price = bp["current_price"] if bp and bp["current_price"] > 0 else price_rows[0][2]
        if current_price is None:
            continue

        # 브로커 매입가 우선, 없으면 DB avg_entry_price 폴백
        if bp and bp.get("avg_price") and bp["avg_price"] > 0:
            entry_price = bp["avg_price"]

        lows_10 = [r[1] for r in price_rows[:10]] if len(price_rows) >= 10 else [r[1] for r in price_rows]
        lows_20 = [r[1] for r in price_rows[:20]] if len(price_rows) >= 20 else [r[1] for r in price_rows]

        donchian_lower_10 = min(lows_10)
        donchian_lower_20 = min(lows_20)

        relevant_exit = donchian_lower_10 if system == "S1" else donchian_lower_20
        exit_proximity_pct = ((current_price - relevant_exit) / current_price) * 100 if current_price else 0.0

        # 브로커 실시간 P&L 우선, 없으면 자체 계산 폴백
        if bp and bp.get("pnl_pct") is not None:
            unrealized_pnl_pct = bp["pnl_pct"]
        else:
            unrealized_pnl_pct = ((current_price - entry_price) / entry_price) * 100 if entry_price else 0.0

        if exit_proximity_pct <= 2.0:
            exit_level = "critical"
        elif exit_proximity_pct <= 5.0:
            exit_level = "warning"
        else:
            exit_level = "safe"

        alerts.append({
            "ticker": ticker,
            "name": stock_name,
            "position_side": "LONG",
            "entry_price": round(entry_price, 2),
            "current_price": round(current_price, 2),
            "unrealized_pnl_pct": round(unrealized_pnl_pct, 2),
            "system": system,
            "donchian_lower_10": round(donchian_lower_10, 2),
            "donchian_lower_20": round(donchian_lower_20, 2),
            "current_stop_price": round(current_stop_price, 2) if current_stop_price else None,
            "exit_proximity_pct": round(exit_proximity_pct, 2),
            "exit_level": exit_level,
        })

    alerts.sort(key=lambda a: a["exit_proximity_pct"])

    critical_count = sum(1 for a in alerts if a["exit_level"] == "critical")
    warning_count = sum(1 for a in alerts if a["exit_level"] == "warning")

    return {
        "alerts": alerts,
        "total": len(alerts),
        "critical_count": critical_count,
        "warning_count": warning_count,
    }


@router.get("/bot-health", dependencies=[Depends(verify_api_key)])
async def get_bot_health(
    db: Database = Depends(get_db),
    account_mgr: AccountManager | None = Depends(get_account_manager),
) -> dict:
    mode = await db.get_state("trading_mode") or "paper"
    ws_status = await db.get_state("ws_status") or "DISCONNECTED"
    mf = await compute_market_filter()
    market_filter = mf["label"]
    last_heartbeat = await db.get_state("last_heartbeat")
    last_screening = await db.get_state("last_screening")
    last_error = await db.get_state("last_error")
    bot_started_at = await db.get_state("bot_started_at")

    log_cursor = await db.conn.execute(
        """
        SELECT date, account_equity, daily_pnl, daily_pnl_pct,
               total_positions, total_units,
               entries_count, exits_count, stop_losses_count
        FROM daily_log
        ORDER BY date DESC
        LIMIT 1
        """
    )
    log_row = await log_cursor.fetchone()

    last_daily_log = None
    if log_row:
        last_daily_log = {
            "date": log_row[0],
            "account_equity": log_row[1],
            "daily_pnl": log_row[2],
            "daily_pnl_pct": log_row[3],
            "total_positions": log_row[4],
            "total_units": log_row[5],
            "entries_count": log_row[6],
            "exits_count": log_row[7],
            "stop_losses_count": log_row[8],
        }

    pos_cursor = await db.conn.execute(
        "SELECT COUNT(*) FROM positions WHERE status = 'OPEN'"
    )
    open_positions = (await pos_cursor.fetchone())[0]

    watchlist_cursor = await db.conn.execute(
        "SELECT COUNT(*) FROM watchlist WHERE status = 'ACTIVE'"
    )
    active_watchlist = (await watchlist_cursor.fetchone())[0]

    order_cursor = await db.conn.execute(
        """
        SELECT COUNT(*) FROM orders
        WHERE status IN ('PENDING', 'SUBMITTED')
        """
    )
    pending_orders = (await order_cursor.fetchone())[0]

    recent_errors_cursor = await db.conn.execute(
        """
        SELECT COUNT(*) FROM bot_logs
        WHERE level = 'error'
          AND timestamp >= datetime('now', '-24 hours')
        """
    )
    recent_errors_row = await recent_errors_cursor.fetchone()
    recent_error_count = recent_errors_row[0] if recent_errors_row else 0

    price_date_cursor = await db.conn.execute(
        "SELECT MAX(date) FROM daily_prices"
    )
    price_date_row = await price_date_cursor.fetchone()
    latest_price_date = price_date_row[0] if price_date_row else None

    fund_date_cursor = await db.conn.execute(
        "SELECT MAX(updated_at) FROM fundamentals"
    )
    fund_date_row = await fund_date_cursor.fetchone()
    latest_fundamental_date = fund_date_row[0] if fund_date_row else None

    screening_date_cursor = await db.conn.execute(
        "SELECT MAX(last_screened) FROM watchlist"
    )
    screening_date_row = await screening_date_cursor.fetchone()
    latest_screening_date = screening_date_row[0] if screening_date_row else None

    live_equity: float | None = None
    live_cash: float | None = None
    if account_mgr is not None:
        try:
            info = await account_mgr.get_account_info()
            live_equity = info.total_equity
            live_cash = info.cash_balance
        except Exception:
            logger.warning("bot_health_equity_fetch_failed", exc_info=True)

    is_running = False
    if last_heartbeat is not None:
        try:
            hb_time = datetime.fromisoformat(last_heartbeat)
            if hb_time.tzinfo is None:
                hb_time = hb_time.replace(tzinfo=timezone.utc)
            is_running = (datetime.now(timezone.utc) - hb_time) < timedelta(minutes=2)
        except (ValueError, TypeError):
            pass

    health_status = "running" if is_running else "stopped"
    if recent_error_count > 10:
        health_status = "degraded"

    return {
        "health_status": health_status,
        "mode": mode,
        "ws_status": ws_status,
        "market_filter": market_filter,
        "bot_started_at": bot_started_at,
        "last_heartbeat": last_heartbeat,
        "last_screening": last_screening,
        "last_error": last_error,
        "open_positions": open_positions,
        "active_watchlist": active_watchlist,
        "pending_orders": pending_orders,
        "recent_error_count": recent_error_count,
        "last_daily_log": last_daily_log,
        "latest_price_date": latest_price_date,
        "latest_fundamental_date": latest_fundamental_date,
        "latest_screening_date": latest_screening_date,
        "live_equity": live_equity,
        "live_cash": live_cash,
    }
