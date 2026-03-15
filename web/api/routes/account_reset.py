"""
Account reset endpoint.

POST /api/account/reset — soft-delete trading data and re-fetch account info from broker.

Soft-delete strategy:
- positions: OPEN -> CLOSED (close_reason='ACCOUNT_RESET')
- orders: SUBMITTED/PENDING/PARTIAL -> CANCELLED (notes='account_reset')
- units: kept (belong to now-closed positions)
- daily_log, bot_logs, breakout_history: kept as historical
- watchlist, daily_prices, fundamentals: untouched (screening data)
- bot_state: trading-related keys cleared, last_reset_at recorded
"""

from __future__ import annotations

from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from broker.account import AccountManager
from core.database import Database
from config.settings import get_settings
from web.api.dependencies import get_db, get_account_manager, verify_api_key

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["account"])


class ResetRequest(BaseModel):
    confirm: bool = False


class ResetResponse(BaseModel):
    success: bool
    mode: str
    reset_at: str
    closed_positions: int
    cancelled_orders: int
    cleared_state_keys: int
    account_equity: float | None = None
    cash_balance: float | None = None
    currency: str = "USD"


# bot_state keys that should be cleared on reset (trading runtime state)
_TRADING_STATE_KEYS = [
    "last_screening_date",
    "last_pre_market",
    "last_post_market",
    "intraday_running",
    "ws_status",
    "ws_kr_status",
    "ws_reconnect_count",
    "global_entry_block_until",
    "last_heartbeat",
]


@router.post(
    "/account/reset",
    response_model=ResetResponse,
    dependencies=[Depends(verify_api_key)],
)
async def reset_account(
    body: ResetRequest,
    db: Database = Depends(get_db),
    account_mgr: AccountManager | None = Depends(get_account_manager),
) -> ResetResponse:
    """Reset trading data (soft-delete) and re-sync account from broker.

    - Paper mode: warning shown on frontend, proceeds after confirm
    - Live mode: same logic, clears DB trading state for fresh start
    """
    if not body.confirm:
        raise HTTPException(
            status_code=400,
            detail="confirm must be true to proceed with account reset",
        )

    settings = get_settings()
    mode = "paper" if settings.is_paper else "live"
    now = datetime.now(timezone.utc)
    now_str = now.isoformat()

    # ── 1. Close all OPEN positions (soft-delete) ────────────
    pos_cursor = await db.conn.execute(
        "SELECT COUNT(*) FROM positions WHERE status = 'OPEN'"
    )
    pos_count = (await pos_cursor.fetchone())[0]

    if pos_count > 0:
        await db.conn.execute(
            """UPDATE positions
               SET status = 'CLOSED',
                   closed_at = ?,
                   close_reason = 'ACCOUNT_RESET',
                   realized_pnl = 0
               WHERE status = 'OPEN'""",
            (now_str,),
        )
    logger.info("reset_positions_closed", count=pos_count)

    # ── 2. Cancel all active orders (soft-delete) ────────────
    ord_cursor = await db.conn.execute(
        "SELECT COUNT(*) FROM orders WHERE status IN ('PENDING', 'SUBMITTED', 'PARTIAL')"
    )
    ord_count = (await ord_cursor.fetchone())[0]

    if ord_count > 0:
        await db.conn.execute(
            """UPDATE orders
               SET status = 'CANCELLED',
                   notes = CASE
                       WHEN notes IS NULL OR notes = '' THEN 'account_reset'
                       ELSE notes || ' | account_reset'
                   END,
                   updated_at = ?
               WHERE status IN ('PENDING', 'SUBMITTED', 'PARTIAL')""",
            (now_str,),
        )
    logger.info("reset_orders_cancelled", count=ord_count)

    # ── 3. Clear trading-related bot_state keys ──────────────
    cleared = 0
    for key in _TRADING_STATE_KEYS:
        cursor = await db.conn.execute(
            "DELETE FROM bot_state WHERE key = ?", (key,)
        )
        if cursor.rowcount > 0:
            cleared += 1

    # Record reset timestamp
    await db.set_state("last_reset_at", now_str)
    await db.set_state("trading_mode", mode)
    logger.info("reset_state_cleared", cleared_keys=cleared)

    # ── 4. Commit all changes ────────────────────────────────
    await db.conn.commit()

    # ── 5. Fetch fresh account info from broker ──────────────
    account_equity = None
    cash_balance = None
    currency = "USD"

    if account_mgr is not None:
        for market in ("US", "KR"):
            try:
                info = await account_mgr.get_account_info(force=True, market=market)
                if market == "US":
                    account_equity = info.total_equity
                    cash_balance = info.cash_balance
                    currency = info.currency
                logger.info(
                    "reset_account_info_fetched",
                    market=market,
                    equity=info.total_equity,
                    cash=info.cash_balance,
                )
            except Exception as exc:
                logger.warning(
                    "reset_account_info_failed",
                    market=market,
                    error=str(exc),
                )
    else:
        logger.warning("reset_no_account_manager")

    logger.info(
        "account_reset_complete",
        mode=mode,
        closed_positions=pos_count,
        cancelled_orders=ord_count,
        cleared_state_keys=cleared,
    )

    return ResetResponse(
        success=True,
        mode=mode,
        reset_at=now_str,
        closed_positions=pos_count,
        cancelled_orders=ord_count,
        cleared_state_keys=cleared,
        account_equity=account_equity,
        cash_balance=cash_balance,
        currency=currency,
    )
