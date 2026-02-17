"""
Trading diary endpoint — per-stock trade history with journal notes.

GET /api/diary — returns orders enriched with parsed journal context,
optionally filtered by ticker. Joined with position data for P&L context.
"""

from __future__ import annotations

import json

import structlog
from fastapi import APIRouter, Depends, Query

from core.database import Database
from web.api.dependencies import get_db, verify_api_key

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["diary"])


@router.get("/diary", dependencies=[Depends(verify_api_key)])
async def get_diary(
    ticker: str = Query(
        default="",
        description="Filter by ticker symbol (uppercase). Empty = all tickers.",
    ),
    limit: int = Query(default=50, ge=1, le=200, description="Results per page"),
    offset: int = Query(default=0, ge=0, description="Pagination offset"),
    db: Database = Depends(get_db),
) -> dict:
    """종목별 매매 기록 + 전략 컨텍스트 조회.

    매매일지의 종목별 시간순 뷰를 제공한다.
    ``orders.notes`` JSON 컬럼에서 파싱된 전략 컨텍스트
    (ATR, 돌파 가격, RS Rating 등)와 포지션 정보를 함께 반환.

    Args:
        ticker: 선택적 종목 필터 (대소문자 무관, 대문자 변환됨).
        limit: 페이지 크기 (1-200).
        offset: 페이지네이션 오프셋.
        db: 데이터베이스 의존성.

    Returns:
        매매일지 항목, 총 건수, 페이지네이션 정보,
        필터 드롭다운용 종목 목록이 포함된 dict.
    """
    where_parts = ["o.notes IS NOT NULL", "o.notes != ''"]
    params: list = []

    if ticker:
        where_parts.append("o.ticker = ?")
        params.append(ticker.upper())

    where_sql = " AND ".join(where_parts)

    # ── 총 건수 ──
    count_cursor = await db.conn.execute(
        f"SELECT COUNT(*) FROM orders o WHERE {where_sql}",
        params,
    )
    count_row = await count_cursor.fetchone()
    total = count_row[0] if count_row else 0

    # ── 포지션 컨텍스트와 함께 항목 조회 ──
    query = f"""
        SELECT
            o.id, o.ticker, o.side, o.order_type,
            o.requested_shares, o.requested_price,
            o.filled_shares, o.filled_price,
            o.status, o.created_at, o.filled_at, o.notes,
            p.system, p.avg_entry_price, p.realized_pnl,
            p.close_reason, p.opened_at, p.closed_at
        FROM orders o
        LEFT JOIN positions p
            ON o.ticker = p.ticker
            AND o.created_at >= p.opened_at
            AND o.created_at <= COALESCE(p.closed_at, '9999-12-31')
        WHERE {where_sql}
        ORDER BY o.created_at DESC
        LIMIT ? OFFSET ?
    """
    query_params = params + [limit, offset]
    cursor = await db.conn.execute(query, query_params)
    rows = await cursor.fetchall()

    entries = []
    for r in rows:
        raw_notes = r[11]
        parsed_context: dict | None = None
        if raw_notes:
            try:
                parsed_context = json.loads(raw_notes)
            except (json.JSONDecodeError, TypeError):
                parsed_context = {"raw": raw_notes}

        entries.append({
            "order_id": r[0],
            "ticker": r[1],
            "side": r[2],
            "order_type": r[3],
            "requested_shares": r[4],
            "requested_price": r[5],
            "filled_shares": r[6],
            "filled_price": r[7],
            "status": r[8],
            "created_at": r[9],
            "filled_at": r[10],
            "context": parsed_context,
            "position_system": r[12],
            "position_avg_entry": r[13],
            "position_pnl": r[14],
            "close_reason": r[15],
            "position_opened": r[16],
            "position_closed": r[17],
        })

    # ── 필터 드롭다운용 종목 목록 ──
    ticker_cursor = await db.conn.execute(
        """
        SELECT DISTINCT ticker FROM orders
        WHERE notes IS NOT NULL AND notes != ''
        ORDER BY ticker
        """,
    )
    available_tickers = [row[0] for row in await ticker_cursor.fetchall()]

    return {
        "entries": entries,
        "total": total,
        "limit": limit,
        "offset": offset,
        "available_tickers": available_tickers,
    }
