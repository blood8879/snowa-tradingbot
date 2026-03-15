"""
Market control endpoints.

POST /api/market/{market_id}/toggle — enable/disable a market
GET /api/market/status — get all market statuses
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from core.database import Database
from web.api.dependencies import get_db, verify_api_key

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["market"])


class MarketToggleRequest(BaseModel):
    enabled: bool


@router.get("/market/status", dependencies=[Depends(verify_api_key)])
async def get_market_status(db: Database = Depends(get_db)) -> dict:
    """Get enabled/disabled status for all markets."""
    us_enabled = await db.get_state("market_us_enabled")
    kr_enabled = await db.get_state("market_kr_enabled")

    return {
        "markets": [
            {
                "market_id": "US",
                "display_name": "미국 주식",
                "enabled": us_enabled != "false",  # default enabled
                "currency": "USD",
                "exchanges": ["NASD", "NYSE", "AMEX"],
            },
            {
                "market_id": "KR",
                "display_name": "한국 주식",
                "enabled": kr_enabled == "true",  # default disabled
                "currency": "KRW",
                "exchanges": ["KOSPI", "KOSDAQ"],
            },
        ]
    }


@router.post("/market/{market_id}/toggle", dependencies=[Depends(verify_api_key)])
async def toggle_market(
    market_id: str,
    body: MarketToggleRequest,
    db: Database = Depends(get_db),
) -> dict:
    """Enable or disable a market."""
    market_id = market_id.upper()
    if market_id not in ("US", "KR"):
        return {"error": f"Unknown market: {market_id}", "success": False}

    key = f"market_{market_id.lower()}_enabled"
    await db.set_state(key, str(body.enabled).lower())

    logger.info("market_toggled", market=market_id, enabled=body.enabled)

    return {
        "market_id": market_id,
        "enabled": body.enabled,
        "success": True,
    }
