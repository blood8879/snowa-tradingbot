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
    market TEXT DEFAULT 'US',

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
    market TEXT DEFAULT 'US',

    opened_at TEXT NOT NULL,
    closed_at TEXT,
    close_reason TEXT,
    realized_pnl REAL,

    -- Force-exit flags: set when stop-loss rejected by market-close; cleared on next-session forced exit
    force_exit_flag TEXT,
    force_exit_reason TEXT,
    force_exit_set_at TEXT
);

-- 동일 종목 동시 OPEN 방지 (CLOSED는 복수 허용)
CREATE UNIQUE INDEX IF NOT EXISTS idx_positions_ticker_open
    ON positions(ticker) WHERE status = 'OPEN';

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

    notes TEXT,
    market TEXT DEFAULT 'US'
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
    date TEXT NOT NULL,
    market TEXT NOT NULL DEFAULT 'US',

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
    stop_losses_count INTEGER DEFAULT 0,

    PRIMARY KEY (date, market)
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
-- 11. Watchlist history (add/remove log with reasons)
-- ===================================================================
CREATE TABLE IF NOT EXISTS watchlist_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    name TEXT,
    market TEXT NOT NULL DEFAULT 'US',
    action TEXT NOT NULL,  -- 'ADDED' or 'REMOVED'
    reason TEXT,
    quarterly_eps_growth REAL,
    annual_eps_cagr REAL,
    rs_rating REAL,
    composite_score REAL,
    minervini_pass INTEGER,
    recorded_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_watchlist_history_market_date ON watchlist_history(market, recorded_at DESC);

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

    # ── Force-exit helpers ───────────────────────────────────

    async def set_force_exit_flag(
        self,
        ticker: str,
        flag: str,
        reason: str | None = None,
    ) -> None:
        """Mark an OPEN position for forced market-order exit at next session open.

        Args:
            ticker: Position ticker.
            flag: Short flag code (e.g., "MARKET_CLOSED", "STOP_DEFERRED_NEAR_CLOSE").
            reason: Human-readable reason (optional).
        """
        from datetime import datetime, timezone
        now_iso = datetime.now(timezone.utc).isoformat()
        await self.conn.execute(
            """
            UPDATE positions
            SET force_exit_flag = ?, force_exit_reason = ?, force_exit_set_at = ?
            WHERE ticker = ? AND status = 'OPEN'
            """,
            (flag, reason, now_iso, ticker),
        )
        await self.conn.commit()
        logger.warning(
            "position_force_exit_flag_set",
            ticker=ticker,
            flag=flag,
            reason=reason,
        )

    async def clear_force_exit_flag(self, ticker: str) -> None:
        """Clear force-exit flag after successful exit or manual intervention."""
        await self.conn.execute(
            """
            UPDATE positions
            SET force_exit_flag = NULL, force_exit_reason = NULL, force_exit_set_at = NULL
            WHERE ticker = ? AND status = 'OPEN'
            """,
            (ticker,),
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

        IMPORTANT: Orders with a valid broker_order_id are NOT auto-expired,
        because the broker confirmed receiving them. They may just need more
        time for fill confirmation (e.g., due to rate limits on fill-check API).
        Only orders without broker_order_id (failed submissions) are expired.
        """
        from datetime import datetime, timezone

        if order_type:
            cursor = await self.conn.execute(
                """
                SELECT id, created_at, filled_shares, broker_order_id FROM orders
                WHERE ticker = ? AND side = ? AND order_type = ?
                  AND status IN ('SUBMITTED', 'PARTIAL')
                """,
                (ticker, side, order_type),
            )
        else:
            cursor = await self.conn.execute(
                """
                SELECT id, created_at, filled_shares, broker_order_id FROM orders
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
            order_id, created_at_str, filled_shares, broker_order_id = row
            filled = filled_shares or 0
            try:
                created_at = datetime.fromisoformat(created_at_str)
                age = (now - created_at).total_seconds()
            except (ValueError, TypeError):
                age = 0

            if age > max_age_seconds and filled == 0:
                # 브로커가 확인한 주문(broker_order_id 있음)은 여기서 auto-expire하지 않음.
                # check_order_fills()가 체결 확인 + 만료를 담당 (매수 2시간, 매도 30분).
                # has_submitted_order()는 체크 함수이므로 side-effect 없이 대기만 함.
                if broker_order_id:
                    has_active = True
                    logger.debug(
                        "stale_order_waiting_broker_confirmed",
                        order_id=order_id,
                        ticker=ticker,
                        broker_order_id=broker_order_id,
                        age_seconds=int(age),
                    )
                else:
                    # broker_order_id 없음 → 제출 자체가 실패한 주문, 즉시 만료
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

    async def count_failed_entry_orders_today(self, ticker: str) -> int:
        """Count FAILED ENTRY orders for a ticker created today (UTC).

        Used as a safety guard to prevent repeated entry attempts when
        fill confirmation is broken.
        """
        from datetime import datetime, timezone

        today_start = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0,
        ).isoformat()
        cursor = await self.conn.execute(
            """
            SELECT COUNT(*) FROM orders
            WHERE ticker = ? AND side = 'BUY' AND order_type = 'ENTRY'
              AND status = 'FAILED' AND created_at >= ?
            """,
            (ticker, today_start),
        )
        row = await cursor.fetchone()
        return row[0] if row else 0

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

        if "name" not in columns:
            await self.conn.execute("ALTER TABLE watchlist ADD COLUMN name TEXT")
            await self.conn.commit()
            logger.info("migration_applied", migration="add_watchlist_name_column")

        # Migration: UNIQUE(ticker, status) → partial unique index (OPEN only)
        # 기존 테이블에 UNIQUE(ticker, status) 제약이 있으면 재생성
        cursor = await self.conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='positions'"
        )
        row = await cursor.fetchone()
        if row and row[0] and "UNIQUE(ticker, status)" in row[0]:
            await self.conn.executescript("""
                CREATE TABLE IF NOT EXISTS positions_new (
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
                    realized_pnl REAL
                );
                INSERT INTO positions_new SELECT * FROM positions;
                DROP TABLE positions;
                ALTER TABLE positions_new RENAME TO positions;
                CREATE UNIQUE INDEX IF NOT EXISTS idx_positions_ticker_open
                    ON positions(ticker) WHERE status = 'OPEN';
            """)
            await self.conn.commit()
            logger.info("migration_applied", migration="remove_unique_ticker_status")

        # Migration: Add 'market' column to support dual-market (US + KR)
        for table in ("watchlist", "positions", "orders", "daily_log"):
            cursor = await self.conn.execute(f"PRAGMA table_info({table})")
            columns = {row[1] for row in await cursor.fetchall()}
            if "market" not in columns:
                await self.conn.execute(
                    f"ALTER TABLE {table} ADD COLUMN market TEXT DEFAULT 'US'"
                )
                await self.conn.commit()
                logger.info("migration_applied", migration=f"add_{table}_market_column")

        # Migration: daily_log PK date → (date, market) composite key
        dl_cursor = await self.conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='daily_log'"
        )
        dl_row = await dl_cursor.fetchone()
        if dl_row and "PRIMARY KEY (date, market)" not in (dl_row[0] or ""):
            await self.conn.executescript("""
                CREATE TABLE IF NOT EXISTS daily_log_new (
                    date TEXT NOT NULL,
                    market TEXT NOT NULL DEFAULT 'US',
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
                    stop_losses_count INTEGER DEFAULT 0,
                    PRIMARY KEY (date, market)
                );
                INSERT OR IGNORE INTO daily_log_new
                    SELECT date, market, spy_close, spy_sma200, market_filter_pass,
                           account_equity, cash_balance, total_positions, total_units,
                           daily_pnl, daily_pnl_pct, cumulative_pnl, max_drawdown_pct,
                           entries_count, exits_count, stop_losses_count
                    FROM daily_log;
                DROP TABLE daily_log;
                ALTER TABLE daily_log_new RENAME TO daily_log;
            """)
            await self.conn.commit()
            logger.info("migration_applied", migration="daily_log_composite_pk")

        # Migration: Add regime/breadth/roc columns to daily_log
        dl_cols_cursor = await self.conn.execute("PRAGMA table_info(daily_log)")
        dl_cols = {row[1] for row in await dl_cols_cursor.fetchall()}
        for col, col_type in [("regime", "TEXT DEFAULT 'GREEN'"), ("breadth_pct", "REAL"), ("roc", "REAL")]:
            if col not in dl_cols:
                await self.conn.execute(f"ALTER TABLE daily_log ADD COLUMN {col} {col_type}")
                await self.conn.commit()
                logger.info("migration_applied", migration=f"add_daily_log_{col}")

        # Migration: positions force_exit flags (next-session forced market-order exit)
        pos_cols_cursor = await self.conn.execute("PRAGMA table_info(positions)")
        pos_cols = {row[1] for row in await pos_cols_cursor.fetchall()}
        for col, col_type in [
            ("force_exit_flag", "TEXT"),
            ("force_exit_reason", "TEXT"),
            ("force_exit_set_at", "TEXT"),
        ]:
            if col not in pos_cols:
                await self.conn.execute(f"ALTER TABLE positions ADD COLUMN {col} {col_type}")
                await self.conn.commit()
                logger.info("migration_applied", migration=f"add_positions_{col}")

        # Migration: IBD Market Direction tables
        cursor = await self.conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='ibd_market_direction'")
        if not await cursor.fetchone():
            await self.conn.executescript("""
                CREATE TABLE IF NOT EXISTS ibd_market_direction (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    date TEXT NOT NULL,
                    index_ticker TEXT NOT NULL,
                    status TEXT NOT NULL,
                    prior_status TEXT,
                    distribution_count INTEGER NOT NULL DEFAULT 0,
                    rally_day_count INTEGER NOT NULL DEFAULT 0,
                    ftd_date TEXT,
                    ftd_low REAL,
                    notes TEXT,
                    UNIQUE(date, index_ticker)
                );
                CREATE TABLE IF NOT EXISTS ibd_distribution_days (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    index_ticker TEXT NOT NULL,
                    date TEXT NOT NULL,
                    day_type TEXT NOT NULL,
                    close_price REAL NOT NULL,
                    price_change_pct REAL NOT NULL,
                    volume INTEGER NOT NULL,
                    prior_volume INTEGER NOT NULL,
                    expired INTEGER NOT NULL DEFAULT 0,
                    expiry_reason TEXT,
                    expiry_date TEXT,
                    UNIQUE(index_ticker, date)
                );
                CREATE INDEX IF NOT EXISTS idx_ibd_dist_active
                    ON ibd_distribution_days(index_ticker, expired) WHERE expired = 0;
            """)
            await self.conn.commit()
            logger.info("migration_applied", migration="add_ibd_market_direction_tables")
