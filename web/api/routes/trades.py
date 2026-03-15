"""
Trades endpoint.

GET /api/trades — returns filled orders with pagination.

Merges:
  1. Bot-tracked orders from DB (status = FILLED)
  2. Broker filled orders from KIS API (for manual/external trades)
"""

from __future__ import annotations

from datetime import datetime

import structlog
from fastapi import APIRouter, Depends, Query

from broker.account import AccountManager
from core.database import Database
from web.api.dependencies import get_db, get_account_manager, verify_api_key

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["trades"])


async def _fetch_broker_trades(
    account_mgr: AccountManager | None,
    market: str = "US",
) -> list[dict]:
    """Fetch filled orders directly from the KIS broker API."""
    if account_mgr is None:
        return []
    try:
        # 최근 30일 체결 내역 조회
        today = datetime.now().strftime("%Y%m%d")
        from datetime import timedelta
        start = (datetime.now() - timedelta(days=30)).strftime("%Y%m%d")
        raw = await account_mgr._rest.get_filled_orders(
            start_date=start, end_date=today, market=market,
        )
    except Exception:
        logger.warning("broker_trades_fetch_failed", market=market, exc_info=True)
        return []

    result: list[dict] = []
    for r in raw:
        if market == "KR":
            side_code = r.get("sll_buy_dvsn_cd", "")
            side = "SELL" if side_code == "01" else "BUY"
            ticker = r.get("pdno", "")
            qty = int(float(r.get("ord_qty", 0)))
            filled_qty = int(float(r.get("tot_ccld_qty", 0)))
            price = float(r.get("ord_unpr", 0))
            filled_price = float(r.get("avg_prvs", 0))
            order_dt = r.get("ord_dt", "")
            order_time = r.get("ord_tmd", "")
            odno = r.get("odno", "")
        else:
            side_code = r.get("sll_buy_dvsn_cd", "")
            side = "SELL" if side_code == "01" else "BUY"
            ticker = r.get("pdno", r.get("ovrs_pdno", ""))
            qty = int(float(r.get("ft_ord_qty", 0)))
            filled_qty = int(float(r.get("ft_ccld_qty", 0)))
            price = float(r.get("ft_ord_unpr3", 0))
            filled_price = float(r.get("ft_ccld_unpr3", 0))
            order_dt = r.get("ord_dt", "")
            order_time = r.get("ord_tmd", "")
            odno = r.get("odno", "")

        if not ticker or filled_qty == 0:
            continue

        # 날짜 포맷팅
        created_at = ""
        if order_dt and len(order_dt) == 8:
            created_at = f"{order_dt[:4]}-{order_dt[4:6]}-{order_dt[6:]}"
            if order_time and len(order_time) >= 6:
                created_at += f"T{order_time[:2]}:{order_time[2:4]}:{order_time[4:6]}"

        result.append({
            "id": f"broker_{odno}",
            "broker_order_id": odno,
            "ticker": ticker,
            "side": side,
            "order_type": "BROKER",
            "requested_shares": qty,
            "requested_price": price,
            "filled_shares": filled_qty,
            "filled_price": filled_price,
            "status": "FILLED",
            "created_at": created_at,
            "updated_at": created_at,
            "filled_at": created_at,
            "notes": None,
            "source": "broker",
        })

    return result


@router.get("/trades", dependencies=[Depends(verify_api_key)])
async def get_trades(
    limit: int = Query(default=20, ge=1, le=100, description="Number of trades to return"),
    offset: int = Query(default=0, ge=0, description="Offset for pagination"),
    market: str = Query(default="US", description="Market filter"),
    db: Database = Depends(get_db),
    account_mgr: AccountManager | None = Depends(get_account_manager),
) -> dict:
    """Return filled orders with pagination.

    Merges bot-tracked orders from DB with broker filled orders from KIS API.
    """
    # Total count of filled orders from DB
    count_cursor = await db.conn.execute(
        "SELECT COUNT(*) FROM orders WHERE status = 'FILLED' AND market = ?",
        (market,),
    )
    count_row = await count_cursor.fetchone()
    total = count_row[0] if count_row else 0

    # Fetch paginated filled orders from DB (with stock name from watchlist)
    cursor = await db.conn.execute(
        """
        SELECT o.id, o.broker_order_id, o.ticker, o.side, o.order_type,
               o.requested_shares, o.requested_price,
               o.filled_shares, o.filled_price,
               o.status, o.created_at, o.updated_at, o.filled_at, o.notes,
               w.name
        FROM orders o
        LEFT JOIN watchlist w ON w.ticker = o.ticker
        WHERE o.status = 'FILLED' AND o.market = ?
        ORDER BY o.filled_at DESC
        LIMIT ? OFFSET ?
        """,
        (market, limit, offset),
    )
    rows = await cursor.fetchall()

    # KR 종목명 CSV fallback
    from web.api.routes.watchlist import _load_kr_stock_names
    kr_names = _load_kr_stock_names() if market == "KR" else {}

    trades = []
    for r in rows:
        notes_raw = r[13]
        trade_type = ""
        trade_system = ""
        if notes_raw:
            try:
                import json
                parsed = json.loads(notes_raw)
                t = parsed.get("type", "")
                s = parsed.get("system", "")
                if t == "ENTRY":
                    trade_type = f"{s} 진입"
                elif t == "PYRAMID":
                    unit = parsed.get("unit_number", "")
                    trade_type = f"{s} 피라미딩 #{unit}" if unit else f"{s} 피라미딩"
                elif t == "STOP_LOSS":
                    trade_type = "손절"
                elif t == "EXIT":
                    trade_type = parsed.get("exit_reason", "청산")
                else:
                    trade_type = t
                trade_system = s
            except (json.JSONDecodeError, TypeError):
                pass

        name = r[14] or kr_names.get(r[2])
        trades.append({
            "id": r[0],
            "broker_order_id": r[1],
            "ticker": r[2],
            "name": name,
            "side": r[3],
            "order_type": r[4],
            "trade_type": trade_type,
            "trade_system": trade_system,
            "requested_shares": r[5],
            "requested_price": r[6],
            "filled_shares": r[7],
            "filled_price": r[8],
            "status": r[9],
            "created_at": r[10],
            "updated_at": r[11],
            "filled_at": r[12],
            "notes": notes_raw,
            "source": "bot",
        })

    # Fetch broker filled orders (not in bot DB)
    broker_trades = await _fetch_broker_trades(account_mgr, market)

    # 봇 DB에 이미 있는 주문번호는 제외
    db_odno_set = {t["broker_order_id"] for t in trades if t["broker_order_id"]}
    broker_only = [bt for bt in broker_trades if bt["broker_order_id"] not in db_odno_set]

    return {
        "trades": trades,
        "broker_trades": broker_only,
        "total": total,
        "broker_total": len(broker_only),
        "limit": limit,
        "offset": offset,
        "market": market,
    }
