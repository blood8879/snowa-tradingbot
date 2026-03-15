"""
SQLite-based daily OHLCV price cache.

Handles:
- Storage/retrieval of daily price bars from SQLite (daily_prices table)
- Bulk loading from yfinance for initial data population
- Gap-filling from KIS REST API for incremental updates

All data flows through the OHLCV dataclass defined in core/models.py.
The daily_prices table uses (ticker, date) as composite primary key,
so INSERT OR IGNORE naturally deduplicates.
"""

from __future__ import annotations

import asyncio
import math
import random
import time
from typing import Any

import structlog

from config.constants import (
    YFINANCE_BATCH_DELAY,
    YFINANCE_BATCH_SIZE,
    YFINANCE_RATE_LIMIT_BACKOFF_MULT,
    YFINANCE_RATE_LIMIT_BASE_DELAY,
    YFINANCE_RATE_LIMIT_MAX_DELAY,
    YFINANCE_RATE_LIMIT_MAX_RETRIES,
)
from core.database import Database
from core.models import OHLCV

logger = structlog.get_logger(__name__)

# ── YFRateLimitError lazy import ─────────────────────────────
# yfinance 0.2.31+ exposes this; older versions don't.
try:
    from yfinance.exceptions import YFRateLimitError
except (ImportError, ModuleNotFoundError):

    class YFRateLimitError(Exception):  # type: ignore[no-redef]
        """Fallback stub when yfinance doesn't expose the exception."""


class PriceCache:
    """SQLite 기반 일일 OHLCV 가격 캐시."""

    def __init__(self, db: Database) -> None:
        self._db = db

    # ── Query Methods ────────────────────────────────────────

    async def get_ohlcv(self, ticker: str, days: int = 300) -> list[OHLCV]:
        """
        Get recent OHLCV bars for a ticker.

        Returns bars in ascending date order (oldest first),
        limited to the most recent `days` records.
        """
        cursor = await self._db.conn.execute(
            """
            SELECT date, open, high, low, close, volume
            FROM daily_prices
            WHERE ticker = ?
            ORDER BY date DESC
            LIMIT ?
            """,
            (ticker, days),
        )
        rows = await cursor.fetchall()

        # Convert to OHLCV and reverse to ascending date order
        bars = [
            OHLCV(
                date=row[0],
                open=row[1],
                high=row[2],
                low=row[3],
                close=row[4],
                volume=row[5],
            )
            for row in rows
        ]
        bars.reverse()
        return bars

    async def get_latest_date(self, ticker: str) -> str | None:
        """Return the most recent date string for a ticker, or None if no data."""
        cursor = await self._db.conn.execute(
            "SELECT MAX(date) FROM daily_prices WHERE ticker = ?",
            (ticker,),
        )
        row = await cursor.fetchone()
        return row[0] if row and row[0] else None

    async def get_price_on_date(self, ticker: str, date: str) -> OHLCV | None:
        """Get OHLCV for a specific date."""
        cursor = await self._db.conn.execute(
            """
            SELECT date, open, high, low, close, volume
            FROM daily_prices
            WHERE ticker = ? AND date = ?
            """,
            (ticker, date),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        return OHLCV(
            date=row[0],
            open=row[1],
            high=row[2],
            low=row[3],
            close=row[4],
            volume=row[5],
        )

    async def get_latest_close(self, ticker: str) -> float | None:
        """Get the most recent closing price for a ticker."""
        cursor = await self._db.conn.execute(
            "SELECT close FROM daily_prices WHERE ticker = ? ORDER BY date DESC LIMIT 1",
            (ticker,),
        )
        row = await cursor.fetchone()
        return row[0] if row else None

    async def count_records(self, ticker: str) -> int:
        """Return total number of daily_prices records for a ticker."""
        cursor = await self._db.conn.execute(
            "SELECT COUNT(*) FROM daily_prices WHERE ticker = ?",
            (ticker,),
        )
        row = await cursor.fetchone()
        return row[0] if row else 0

    # ── Storage Methods ──────────────────────────────────────

    async def store_ohlcv(self, ticker: str, bars: list[OHLCV]) -> int:
        """
        Store OHLCV bars into daily_prices table.

        Uses INSERT OR IGNORE to skip duplicate (ticker, date) rows.

        Returns:
            Number of new rows inserted.
        """
        if not bars:
            return 0

        conn = self._db.conn

        # Get row count before insert
        cursor = await conn.execute(
            "SELECT COUNT(*) FROM daily_prices WHERE ticker = ?",
            (ticker,),
        )
        before_count = (await cursor.fetchone())[0]

        # Batch insert
        await conn.executemany(
            """
            INSERT OR REPLACE INTO daily_prices
                (ticker, date, open, high, low, close, volume)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (ticker, bar.date, bar.open, bar.high, bar.low, bar.close, bar.volume)
                for bar in bars
            ],
        )
        await conn.commit()

        # Count new rows
        cursor = await conn.execute(
            "SELECT COUNT(*) FROM daily_prices WHERE ticker = ?",
            (ticker,),
        )
        after_count = (await cursor.fetchone())[0]
        new_rows = after_count - before_count

        if new_rows > 0:
            logger.debug(
                "price_cache_stored",
                ticker=ticker,
                new_rows=new_rows,
                total_bars=len(bars),
            )

        return new_rows

    # ── Bulk Loading (yfinance) ──────────────────────────────

    async def bulk_load_from_yfinance(
        self,
        tickers: list[str],
        period: str = "15mo",
        batch_size: int = 100,
        delay: float = 2.0,
    ) -> int:
        """
        Bulk download OHLCV data using yfinance.

        Processes tickers in batches to avoid rate-limiting.
        Uses run_in_executor for the synchronous yfinance download.

        Returns:
            Total number of new records stored.
        """
        # Use constants as defaults if caller used original default args
        if batch_size == 100:
            batch_size = YFINANCE_BATCH_SIZE
        if delay == 2.0:
            delay = YFINANCE_BATCH_DELAY

        total_new = 0
        total_batches = math.ceil(len(tickers) / batch_size) if tickers else 0
        loop = asyncio.get_event_loop()

        for batch_num in range(total_batches):
            start = batch_num * batch_size
            end = start + batch_size
            batch_tickers = tickers[start:end]

            logger.info(
                "price_bulk_progress",
                batch=batch_num + 1,
                total=total_batches,
                tickers_in_batch=len(batch_tickers),
            )

            try:
                # Run synchronous yfinance download in executor
                result = await loop.run_in_executor(
                    None, self._yf_download_batch, batch_tickers, period
                )

                # Store results
                for ticker, bars in result.items():
                    new_rows = await self.store_ohlcv(ticker, bars)
                    total_new += new_rows

            except Exception:
                logger.exception(
                    "price_bulk_batch_error",
                    batch=batch_num + 1,
                    tickers=batch_tickers[:5],
                )

            # Rate-limit delay between batches (skip after last batch)
            if batch_num < total_batches - 1:
                await asyncio.sleep(delay)

        logger.info(
            "price_bulk_complete",
            total_tickers=len(tickers),
            total_new_records=total_new,
        )
        return total_new

    def _yf_download_batch(
        self, tickers: list[str], period: str
    ) -> dict[str, list[OHLCV]]:
        """
        Synchronous yfinance download for a batch of tickers.

        Runs inside executor — must not use any async calls.
        Retries on YFRateLimitError with exponential backoff.

        Returns:
            Dict mapping ticker → list of OHLCV bars.
        """
        import yfinance as yf

        result: dict[str, list[OHLCV]] = {}

        if not tickers:
            return result

        # ── Download with rate-limit retry ────────────────────
        data = None
        for attempt in range(1, YFINANCE_RATE_LIMIT_MAX_RETRIES + 1):
            try:
                data = yf.download(
                    tickers,
                    period=period,
                    group_by="ticker",
                    threads=True,
                    progress=False,
                )
                break

            except YFRateLimitError:
                if attempt >= YFINANCE_RATE_LIMIT_MAX_RETRIES:
                    logger.warning(
                        "yfinance_download_rate_limit_exhausted",
                        tickers=tickers[:5],
                        attempts=attempt,
                    )
                    return result
                delay = min(
                    YFINANCE_RATE_LIMIT_BASE_DELAY
                    * (YFINANCE_RATE_LIMIT_BACKOFF_MULT ** (attempt - 1)),
                    YFINANCE_RATE_LIMIT_MAX_DELAY,
                )
                jitter = random.uniform(0, 1.0)
                logger.info(
                    "yfinance_download_rate_limit_retry",
                    attempt=attempt,
                    delay=f"{delay + jitter:.1f}s",
                    tickers=tickers[:3],
                )
                time.sleep(delay + jitter)

            except Exception:
                logger.exception("yfinance_download_error", tickers=tickers[:5])
                return result

        if data is None or data.empty:
            return result

        single_ticker = len(tickers) == 1

        for ticker in tickers:
            try:
                if single_ticker:
                    # Single ticker: columns are OHLC/Volume directly
                    ticker_data = data
                else:
                    # Multiple tickers: first level is ticker
                    if ticker not in data.columns.get_level_values(0):
                        continue
                    ticker_data = data[ticker]

                bars: list[OHLCV] = []
                for idx, row in ticker_data.iterrows():
                    # Skip rows where all price values are NaN
                    if (
                        math.isnan(row.get("Open", float("nan")))
                        and math.isnan(row.get("High", float("nan")))
                        and math.isnan(row.get("Low", float("nan")))
                        and math.isnan(row.get("Close", float("nan")))
                    ):
                        continue

                    # Skip rows with any NaN in required fields
                    open_val = row.get("Open", float("nan"))
                    high_val = row.get("High", float("nan"))
                    low_val = row.get("Low", float("nan"))
                    close_val = row.get("Close", float("nan"))
                    volume_val = row.get("Volume", 0)

                    if any(
                        math.isnan(v) for v in [open_val, high_val, low_val, close_val]
                    ):
                        continue

                    bars.append(
                        OHLCV(
                            date=idx.strftime("%Y-%m-%d"),
                            open=float(open_val),
                            high=float(high_val),
                            low=float(low_val),
                            close=float(close_val),
                            volume=int(volume_val),
                        )
                    )

                if bars:
                    result[ticker] = bars

            except Exception:
                logger.exception("yfinance_parse_error", ticker=ticker)

        return result

    # ── Bulk Loading (pykrx) ─────────────────────────────────

    async def bulk_load_from_pykrx(
        self,
        tickers: list[str],
        days: int = 300,
        batch_size: int = 50,
        delay: float = 1.0,
    ) -> int:
        """
        Bulk download Korean stock OHLCV data using pykrx.

        pykrx is synchronous, so wraps in run_in_executor.
        Processes tickers in batches to avoid memory issues.

        Args:
            tickers: List of 6-digit Korean stock codes.
            days: Number of trading days to fetch.
            batch_size: Tickers per batch.
            delay: Delay between batches (seconds).

        Returns:
            Total number of new records stored.
        """
        total_new = 0
        total_batches = math.ceil(len(tickers) / batch_size) if tickers else 0
        loop = asyncio.get_event_loop()

        for batch_num in range(total_batches):
            start = batch_num * batch_size
            end = start + batch_size
            batch_tickers = tickers[start:end]

            logger.info(
                "pykrx_bulk_progress",
                batch=batch_num + 1,
                total=total_batches,
                tickers_in_batch=len(batch_tickers),
            )

            try:
                # Run synchronous pykrx download in executor
                result = await loop.run_in_executor(
                    None, self._pykrx_download_batch, batch_tickers, days
                )

                # Store results
                for ticker, bars in result.items():
                    new_rows = await self.store_ohlcv(ticker, bars)
                    total_new += new_rows

            except Exception:
                logger.exception(
                    "pykrx_bulk_batch_error",
                    batch=batch_num + 1,
                    tickers=batch_tickers[:5],
                )

            # Rate-limit delay between batches (skip after last batch)
            if batch_num < total_batches - 1:
                await asyncio.sleep(delay)

        logger.info(
            "pykrx_bulk_complete",
            total_tickers=len(tickers),
            total_new_records=total_new,
        )
        return total_new

    def _pykrx_download_batch(
        self, tickers: list[str], days: int
    ) -> dict[str, list[OHLCV]]:
        """
        Synchronous pykrx download for a batch of tickers.

        Uses pykrx.stock.get_market_ohlcv_by_date() for each ticker.
        Runs inside executor.

        Args:
            tickers: List of Korean stock codes.
            days: Number of trading days to fetch.

        Returns:
            Dict mapping ticker → list of OHLCV bars.
        """
        from datetime import datetime, timedelta

        try:
            from pykrx import stock as pykrx_stock
        except ImportError:
            logger.error("pykrx_import_error", msg="pykrx not installed")
            return {}

        end_date = datetime.now().strftime("%Y%m%d")
        # Use 1.5x factor to account for weekends/holidays
        start_date = (datetime.now() - timedelta(days=int(days * 1.5))).strftime(
            "%Y%m%d"
        )

        result: dict[str, list[OHLCV]] = {}

        for ticker in tickers:
            try:
                df = pykrx_stock.get_market_ohlcv_by_date(start_date, end_date, ticker)
                if df is None or df.empty:
                    continue

                bars: list[OHLCV] = []
                for idx, row in df.iterrows():
                    bars.append(
                        OHLCV(
                            date=idx.strftime("%Y-%m-%d"),
                            open=float(row["시가"]),
                            high=float(row["고가"]),
                            low=float(row["저가"]),
                            close=float(row["종가"]),
                            volume=int(row["거래량"]),
                        )
                    )

                if bars:
                    result[ticker] = bars

            except Exception:
                logger.warning("pykrx_ticker_error", ticker=ticker, exc_info=True)

        return result

    # ── KIS Gap Fill ─────────────────────────────────────────

    async def update_from_kis(
        self, ticker: str, exchange: str, kis_client: Any, *, market: str = "US"
    ) -> int:
        """
        Fill gaps in daily_prices using KIS REST API.

        Fetches recent daily prices from KIS and stores any
        dates not already in the database.

        Args:
            ticker: Stock ticker symbol.
            exchange: Exchange code (e.g. "NASD", "NYSE" for US, "KRX" for Korea).
            kis_client: KISRestClient instance (typed as Any to avoid circular imports).
            market: Market type ("US" or "KR").

        Returns:
            Number of new records stored.
        """
        latest_date = await self.get_latest_date(ticker)

        try:
            kis_bars: list[OHLCV] = await kis_client.get_daily_prices(
                ticker, exchange, market=market
            )
        except Exception:
            logger.exception(
                "kis_daily_price_error",
                ticker=ticker,
                exchange=exchange,
            )
            return 0

        if not kis_bars:
            return 0

        # Filter out dates already in DB
        if latest_date:
            new_bars = [bar for bar in kis_bars if bar.date > latest_date]
        else:
            new_bars = kis_bars

        if not new_bars:
            return 0

        new_count = await self.store_ohlcv(ticker, new_bars)

        if new_count > 0:
            logger.info(
                "kis_gap_fill_complete",
                ticker=ticker,
                new_records=new_count,
                latest_date=latest_date,
            )

        return new_count
