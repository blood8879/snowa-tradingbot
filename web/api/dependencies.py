"""
FastAPI dependency injection providers.

Provides:
- Database instance via get_db()
- Optional API key authentication via verify_api_key()
"""

from __future__ import annotations

import os

import structlog
from fastapi import Depends, HTTPException, Security
from fastapi.security import APIKeyHeader

from core.database import Database
from broker.account import AccountManager
from config.settings import get_settings

logger = structlog.get_logger(__name__)

# Module-level singletons, initialized in main.py lifespan
_db: Database | None = None
_account_mgr: AccountManager | None = None


def set_db(db: Database) -> None:
    global _db
    _db = db


def set_account_manager(mgr: AccountManager) -> None:
    global _account_mgr
    _account_mgr = mgr


async def get_account_manager() -> AccountManager | None:
    return _account_mgr


async def get_db() -> Database:
    """Return the active Database instance.

    In production the lifespan hook calls ``set_db()`` before any
    request is served.  As a safety net (e.g. when using httpx
    ASGITransport without lifespan), this will lazily create and
    initialize the database singleton on first access.

    Returns:
        The Database singleton.
    """
    global _db
    if _db is not None:
        return _db

    # Lazy init fallback — no asyncio.Lock needed because FastAPI
    # processes requests sequentially within a single event loop;
    # the first awaiting call to initialize() will complete before
    # the next request's get_db() is entered.
    settings = get_settings()
    db = Database(str(settings.db_full_path))
    await db.initialize()
    _db = db
    logger.info("db_lazy_initialized", db_path=str(settings.db_full_path))
    return _db


# ── Optional API Key Auth ────────────────────────────────────

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def verify_api_key(
    api_key: str | None = Security(_api_key_header),
) -> str | None:
    """Verify the optional API key from X-API-Key header.

    If DASHBOARD_API_KEY env var is not set, authentication is disabled
    and all requests are allowed through.

    Args:
        api_key: The API key from the request header.

    Returns:
        The validated API key, or None if auth is disabled.

    Raises:
        HTTPException: 403 if a key is required but missing/invalid.
    """
    expected_key = os.environ.get("DASHBOARD_API_KEY", "")

    # If no key is configured, skip authentication
    if not expected_key:
        return None

    if not api_key or api_key != expected_key:
        logger.warning("api_key_rejected", provided=bool(api_key))
        raise HTTPException(status_code=403, detail="Invalid or missing API key")

    return api_key
