"""AI stock report endpoints."""
from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query

from config.settings import get_settings
from core.database import Database
from data.ai_stock_report import StockReportError, StockReportService
from data.ai_usage_status import CachedAIUsageStatusService
from web.api.dependencies import get_db, verify_api_key

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["stock-reports"])

_usage_status_service: CachedAIUsageStatusService | None = None


def _get_usage_status_service() -> CachedAIUsageStatusService:
    global _usage_status_service
    if _usage_status_service is None:
        _usage_status_service = CachedAIUsageStatusService(get_settings())
    return _usage_status_service


@router.get("/ai-reports/status", dependencies=[Depends(verify_api_key)])
async def get_ai_report_status() -> dict:
    """Return LLM report provider and configured budget status."""
    status = await _get_usage_status_service().get_status()
    return status.to_dict()


@router.get("/stock-reports/{ticker}", dependencies=[Depends(verify_api_key)])
async def get_stock_report(
    ticker: str,
    market: str = Query(default="US", description="Market filter"),
    db: Database = Depends(get_db),
) -> dict:
    """Return the cached AI report for a ticker, if one exists."""
    service = StockReportService(db, get_settings())
    return await service.get_cached_report(ticker, market)


@router.post("/stock-reports/{ticker}/generate", dependencies=[Depends(verify_api_key)])
async def generate_stock_report(
    ticker: str,
    market: str = Query(default="US", description="Market filter"),
    db: Database = Depends(get_db),
) -> dict:
    """Generate and cache an AI report unless an identical financial-data report exists."""
    service = StockReportService(db, get_settings())
    try:
        return await service.generate_report(ticker, market)
    except StockReportError as exc:
        logger.warning("stock_report_generation_rejected", ticker=ticker, market=market, error=str(exc))
        raise HTTPException(status_code=400, detail=str(exc)) from exc
