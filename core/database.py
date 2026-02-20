"""
SQLite database management.

Handles:
- Connection management (async via aiosqlite)
- Schema creation (all 9 tables from IMPLEMENTATION_PLAN.md §4)
- Schema migration (version-based)
- Common query helpers

Uses WAL mode for better concurrent read performance.
Single-writer model (asyncio event loop) avoids write contention.
"""

from __future__ import annotations

import aiosqlite
import structlog
from pathlib import Path

logger = structlog.get_logger(__name__)

# Current schema version — increment when schema changes
SCHEMA_VERSION = 1

# ============================================================
# Schema DDL
# ============================================================

SCHEMA_SQL = """
-- ===================================================================
-- 1. Watchlist (CANSLIM filtered stocks)
-- ===================================================================
CREATE TABLE IF NOT EXISTS watchlist (
    ticker TEXT PRIMARY KEY,
    added_date TEXT NOT NULL,
    last_screened TEXT NOT NULL,

    -- CANSLIM scores
    quarterly_eps_growth REAL,
    annual_eps_cagr REAL,
    rs_rating REAL,
    institutional_holders INTEGER,
    institutional_change_pct REAL,
    custom_composite_score REAL,

    -- Minervini Trend Template
    minervini_pass INTEGER DEFAULT 0,

    -- Meta
    sector TEXT,
    industry TEXT,
    avg_daily_volume INTEGER,
    market_cap REAL,
    latest_price REAL,
    exchange TEXT DEFAULT 'NASD',

    status TEXT DEFAULT 'ACTIVE'
);

-- ===================================================================
-- 2. Daily prices cache (OHLCV)
-- ===================================================================
CREATE TABLE IF NOT EXISTS daily_prices (
    ticker TEXT NOT NULL,
    date TEXT NOT NULL,
    open REAL NOT NULL,
    high REAL NOT NULL,
    low REAL NOT NULL,
    close REAL NOT NULL,
    volume INTEGER NOT NULL,

    PRIMARY KEY (ticker, date)
);

CREATE INDEX IF NOT EXISTS idx_daily_prices_date ON daily_prices(date);

-- ===================================================================
-- 3. Fundamentals cache
-- ===================================================================
CREATE TABLE IF NOT EXISTS fundamentals (
    ticker TEXT NOT NULL,
    report_date TEXT NOT NULL,
    period TEXT NOT NULL,
    period_type TEXT NOT NULL,

    eps REAL,
    revenue REAL,
    net_income REAL,
    shares_outstanding REAL,
    debt_to_equity REAL,

    updated_at TEXT NOT NULL,

    PRIMARY KEY (ticker, period)
);

-- ===================================================================
-- 4. Positions (currently held)
-- ===================================================================
CREATE TABLE IF NOT EXISTS positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    system TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'OPEN',

    total_shares INTEGER NOT NULL DEFAULT 0,
    total_cost REAL NOT NULL DEFAULT 0,
    avg_entry_price REAL NOT NULL DEFAULT 0,
    current_stop_price REAL NOT NULL,
    n_at_entry REAL NOT NULL,

    sector TEXT,
    industry TEXT,

    opened_at TEXT NOT NULL,
    closed_at TEXT,
    close_reason TEXT,
    realized_pnl REAL,

    UNIQUE(ticker, status)
);

-- ===================================================================
-- 5. Units (individual entry units within a position)
-- ===================================================================
CREATE TABLE IF NOT EXISTS units (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    position_id INTEGER NOT NULL REFERENCES positions(id),
    unit_number INTEGER NOT NULL,

    entry_price REAL NOT NULL,
    shares INTEGER NOT NULL,
    entry_stop_price REAL NOT NULL,
    current_stop_price REAL NOT NULL,

    entered_at TEXT NOT NULL,

    UNIQUE(position_id, unit_number)
);

-- ===================================================================
-- 6. Orders (order history)
-- ===================================================================
CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    broker_order_id TEXT,
    ticker TEXT NOT NULL,
    side TEXT NOT NULL,
    order_type TEXT NOT NULL,

    requested_shares INTEGER NOT NULL,
    requested_price REAL NOT NULL,

    filled_shares INTEGER DEFAULT 0,
    filled_price REAL,

    status TEXT NOT NULL DEFAULT 'PENDING',

    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    filled_at TEXT,

    notes TEXT
);

-- ===================================================================
-- 7. Breakout history (for System 1 filter)
-- ===================================================================
CREATE TABLE IF NOT EXISTS breakout_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    system TEXT NOT NULL,
    breakout_date TEXT NOT NULL,
    breakout_price REAL NOT NULL,

    would_have_been_winner INTEGER,
    hypothetical_exit_price REAL,
    hypothetical_exit_date TEXT,

    was_actually_entered INTEGER DEFAULT 0
);

-- ===================================================================
-- 8. Daily trading log
-- ===================================================================
CREATE TABLE IF NOT EXISTS daily_log (
    date TEXT PRIMARY KEY,

    spy_close REAL,
    spy_sma200 REAL,
    market_filter_pass INTEGER,

    account_equity REAL,
    cash_balance REAL,
    total_positions INTEGER,
    total_units INTEGER,

    daily_pnl REAL,
    daily_pnl_pct REAL,
    cumulative_pnl REAL,
    max_drawdown_pct REAL,

    entries_count INTEGER DEFAULT 0,
    exits_count INTEGER DEFAULT 0,
    stop_losses_count INTEGER DEFAULT 0
);

-- ===================================================================
-- 9. Bot state (runtime key-value store)
-- ===================================================================
CREATE TABLE IF NOT EXISTS bot_state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- ===================================================================
-- 10. Bot logs (important events for dashboard)
-- ===================================================================
CREATE TABLE IF NOT EXISTS bot_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    level TEXT NOT NULL,
    event TEXT NOT NULL,
    module TEXT,
    ticker TEXT,
    details TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_bot_logs_ts ON bot_logs(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_bot_logs_level ON bot_logs(level);

-- ===================================================================
-- Schema version tracking
-- ===================================================================
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);
"""


class Database:
    """
    Async SQLite database manager.

    Usage:
        db = Database("data/snowa.db")
        await db.initialize()
        async with db.connection() as conn:
            await conn.execute("SELECT ...")
        await db.close()
    """

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._connection: aiosqlite.Connection | None = None

    async def initialize(self) -> None:
        """Create database file, tables, and set pragmas."""
        # Ensure directory exists
        db_dir = Path(self._db_path).parent
        db_dir.mkdir(parents=True, exist_ok=True)

        self._connection = await aiosqlite.connect(self._db_path)

        # Performance pragmas
        await self._connection.execute("PRAGMA journal_mode=WAL")
        await self._connection.execute("PRAGMA synchronous=NORMAL")
        await self._connection.execute("PRAGMA foreign_keys=ON")
        await self._connection.execute("PRAGMA busy_timeout=5000")

        # Create all tables
        await self._connection.executescript(SCHEMA_SQL)

        await self._run_migrations()

        # Record schema version
        await self._connection.execute(
            """
            INSERT OR IGNORE INTO schema_version (version, applied_at)
            VALUES (?, datetime('now'))
            """,
            (SCHEMA_VERSION,),
        )
        await self._connection.commit()

        logger.info("database_initialized", path=self._db_path, schema_version=SCHEMA_VERSION)

    @property
    def conn(self) -> aiosqlite.Connection:
        """Get the active database connection. Raises if not initialized."""
        if self._connection is None:
            raise RuntimeError("Database not initialized. Call initialize() first.")
        return self._connection

    async def close(self) -> None:
        """Close the database connection."""
        if self._connection:
            await self._connection.close()
            self._connection = None
            logger.info("database_closed", path=self._db_path)

    # ── Bot State helpers ────────────────────────────────────

    async def get_state(self, key: str) -> str | None:
        """Get a value from the bot_state table."""
        cursor = await self.conn.execute(
            "SELECT value FROM bot_state WHERE key = ?", (key,)
        )
        row = await cursor.fetchone()
        return row[0] if row else None

    async def set_state(self, key: str, value: str) -> None:
        """Set a value in the bot_state table."""
        await self.conn.execute(
            """
            INSERT INTO bot_state (key, value, updated_at)
            VALUES (?, ?, datetime('now'))
            ON CONFLICT(key) DO UPDATE SET value = ?, updated_at = datetime('now')
            """,
            (key, value, value),
        )
        await self.conn.commit()

    # ── Schema info ──────────────────────────────────────────

    async def get_schema_version(self) -> int:
        """Get the current schema version."""
        cursor = await self.conn.execute(
            "SELECT MAX(version) FROM schema_version"
        )
        row = await cursor.fetchone()
        return row[0] if row and row[0] else 0

    async def has_submitted_order(
        self,
        ticker: str,
        side: str,
        order_type: str | None = None,
        max_age_seconds: int = 300,
    ) -> bool:
        """Check if a recent SUBMITTED/PARTIAL order exists for this ticker+side.

        Orders older than max_age_seconds with 0 fills are treated as stale
        and automatically marked FAILED to prevent blocking future orders.
        """
        from datetime import datetime, timezone

        if order_type:
            cursor = await self.conn.execute(
                """
                SELECT id, created_at, filled_shares FROM orders
                WHERE ticker = ? AND side = ? AND order_type = ?
                  AND status IN ('SUBMITTED', 'PARTIAL')
                """,
                (ticker, side, order_type),
            )
        else:
            cursor = await self.conn.execute(
                """
                SELECT id, created_at, filled_shares FROM orders
                WHERE ticker = ? AND side = ?
                  AND status IN ('SUBMITTED', 'PARTIAL')
                """,
                (ticker, side),
            )

        rows = await cursor.fetchall()
        if not rows:
            return False

        now = datetime.now(timezone.utc)
        has_active = False
        for row in rows:
            order_id, created_at_str, filled_shares = row
            filled = filled_shares or 0
            try:
                created_at = datetime.fromisoformat(created_at_str)
                age = (now - created_at).total_seconds()
            except (ValueError, TypeError):
                age = 0

            if age > max_age_seconds and filled == 0:
                await self.conn.execute(
                    "UPDATE orders SET status = 'FAILED', notes = 'auto_expired_stale' WHERE id = ?",
                    (order_id,),
                )
                await self.conn.commit()
                logger.info(
                    "stale_order_expired",
                    order_id=order_id,
                    ticker=ticker,
                    age_seconds=int(age),
                )
            else:
                has_active = True

        return has_active

    async def table_exists(self, table_name: str) -> bool:
        """Check if a table exists in the database."""
        cursor = await self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (table_name,),
        )
        return await cursor.fetchone() is not None

    async def _run_migrations(self) -> None:
        cursor = await self.conn.execute("PRAGMA table_info(watchlist)")
        columns = {row[1] for row in await cursor.fetchall()}
        if "exchange" not in columns:
            await self.conn.execute(
                "ALTER TABLE watchlist ADD COLUMN exchange TEXT DEFAULT 'NASD'"
            )
            await self.conn.commit()
            logger.info("migration_applied", migration="add_watchlist_exchange_column")
