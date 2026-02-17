"""
FastAPI application for the SNOWA Trading Bot Dashboard.

Provides REST API endpoints for:
- Bot status monitoring
- Open positions with units
- CANSLIM watchlist
- Trade history (filled orders)
- P&L / equity curve data
- Monthly trade journal statistics

Serves the frontend SPA from web/frontend/dist/ if it exists.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from collections.abc import AsyncIterator

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from config.settings import get_settings
from core.database import Database
from broker.kis_auth import KISAuth
from broker.kis_rest import KISRestClient
from broker.account import AccountManager
from web.api.dependencies import set_db, set_account_manager
from web.api.routes import status, positions, watchlist, trades, performance, journal, diary, logs, alerts, realtime_prices

logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Application lifespan: initialize and close the database.

    Args:
        app: The FastAPI application instance.
    """
    settings = get_settings()
    db = Database(str(settings.db_full_path))
    await db.initialize()
    set_db(db)
    logger.info("api_startup", db_path=str(settings.db_full_path))

    kis_rest: KISRestClient | None = None
    try:
        kis_auth = KISAuth()
        await kis_auth.refresh_access_token()
        kis_rest = KISRestClient(kis_auth)
        account_mgr = AccountManager(kis_rest, db)
        set_account_manager(account_mgr)
        logger.info("kis_broker_initialized", mode=settings.trading_mode.value)
    except Exception:
        logger.warning("kis_broker_init_failed", exc_info=True)

    yield

    if kis_rest is not None:
        await kis_rest.close()
    await db.close()
    logger.info("api_shutdown")


app = FastAPI(
    title="SNOWA Trading Bot Dashboard",
    version="1.0.0",
    description="REST API for monitoring the SNOWA turtle trading bot.",
    lifespan=lifespan,
)

# ── CORS Middleware ───────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Include Routers ──────────────────────────────────────────
app.include_router(status.router, prefix="/api")
app.include_router(positions.router, prefix="/api")
app.include_router(watchlist.router, prefix="/api")
app.include_router(trades.router, prefix="/api")
app.include_router(performance.router, prefix="/api")
app.include_router(journal.router, prefix="/api")
app.include_router(diary.router, prefix="/api")
app.include_router(logs.router, prefix="/api")
app.include_router(alerts.router, prefix="/api")
app.include_router(realtime_prices.router, prefix="/api")


# ── Health Check ─────────────────────────────────────────────

@app.get("/api/health", tags=["health"])
async def health_check() -> dict:
    return {"status": "ok", "version": "1.0.0"}


# ── Static Files (SPA) ──────────────────────────────────────

_frontend_dist = Path(__file__).resolve().parent.parent / "frontend" / "dist"
if _frontend_dist.is_dir():
    _index_html = _frontend_dist / "index.html"

    app.mount("/assets", StaticFiles(directory=str(_frontend_dist / "assets")), name="assets")

    @app.get("/{full_path:path}")
    async def spa_fallback(request: Request, full_path: str) -> FileResponse:
        file_path = _frontend_dist / full_path
        if full_path and file_path.is_file():
            return FileResponse(file_path)
        return FileResponse(_index_html)

    logger.info("frontend_mounted", path=str(_frontend_dist))
