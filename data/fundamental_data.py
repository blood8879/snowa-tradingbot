"""
Fundamental financial data manager.

Fetches EPS, revenue, balance sheet data via yfinance
and stores results in the SQLite fundamentals table.

Uses run_in_executor() to wrap synchronous yfinance calls
so they don't block the asyncio event loop.
"""

from __future__ import annotations

import asyncio
import random
import time
from datetime import datetime
from typing import Any

import structlog

from config.constants import (
    FUNDAMENTAL_UPDATE_MONTHS,
    YFINANCE_BATCH_DELAY,
    YFINANCE_BATCH_SIZE,
    YFINANCE_RATE_LIMIT_BACKOFF_MULT,
    YFINANCE_RATE_LIMIT_BASE_DELAY,
    YFINANCE_RATE_LIMIT_MAX_DELAY,
    YFINANCE_RATE_LIMIT_MAX_RETRIES,
)
from core.database import Database

logger = structlog.get_logger(__name__)

# ── YFRateLimitError lazy import ─────────────────────────────
# yfinance 0.2.31+ exposes this; older versions don't.
try:
    from yfinance.exceptions import YFRateLimitError
except (ImportError, ModuleNotFoundError):

    class YFRateLimitError(Exception):  # type: ignore[no-redef]
        """Fallback stub when yfinance doesn't expose the exception."""


class FundamentalDataManager:
    """yfinance를 통한 재무 데이터 수집 및 SQLite 저장."""

    def __init__(self, db: Database) -> None:
        self._db = db

    # ── Public API ───────────────────────────────────────────

    async def fetch_and_store_fundamentals(self, ticker: str) -> int:
        """Fetch quarterly + annual financial data for *ticker* and persist.

        Returns the number of new records inserted (0 on error).
        """
        try:
            loop = asyncio.get_event_loop()
            records = await loop.run_in_executor(
                None, self._fetch_yfinance_data, ticker
            )
            if not records:
                return 0
            return await self._store_records(records)
        except Exception:
            logger.warning("fetch_fundamentals_failed", ticker=ticker, exc_info=True)
            return 0

    async def get_quarterly_eps(
        self, ticker: str, limit: int = 8
    ) -> list[tuple[str, float]]:
        """Return most recent *limit* quarterly (period, eps) pairs."""
        cursor = await self._db.conn.execute(
            """
            SELECT period, eps
            FROM fundamentals
            WHERE ticker = ? AND period_type = 'quarterly' AND eps IS NOT NULL
            ORDER BY period DESC
            LIMIT ?
            """,
            (ticker, limit),
        )
        rows = await cursor.fetchall()
        return [(row[0], row[1]) for row in rows]

    async def get_annual_eps(
        self, ticker: str, limit: int = 5
    ) -> list[tuple[str, float]]:
        """Return most recent *limit* annual (period, eps) pairs."""
        cursor = await self._db.conn.execute(
            """
            SELECT period, eps
            FROM fundamentals
            WHERE ticker = ? AND period_type = 'annual' AND eps IS NOT NULL
            ORDER BY period DESC
            LIMIT ?
            """,
            (ticker, limit),
        )
        rows = await cursor.fetchall()
        return [(row[0], row[1]) for row in rows]

    async def get_debt_to_equity(self, ticker: str) -> float | None:
        """Return the most recent debt-to-equity ratio, or None."""
        cursor = await self._db.conn.execute(
            """
            SELECT debt_to_equity
            FROM fundamentals
            WHERE ticker = ? AND debt_to_equity IS NOT NULL
            ORDER BY report_date DESC
            LIMIT 1
            """,
            (ticker,),
        )
        row = await cursor.fetchone()
        return row[0] if row else None

    async def get_institutional_data(self, ticker: str) -> dict:
        """Fetch institutional ownership stats from yfinance.

        Returns ``{"holders_count": int, "held_pct": float}``.
        """
        try:
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(
                None, self._fetch_institutional_data, ticker
            )
        except Exception:
            logger.warning("institutional_data_failed", ticker=ticker, exc_info=True)
            return {"holders_count": 0, "held_pct": 0.0}

    async def bulk_fetch(
        self,
        tickers: list[str],
        batch_size: int = YFINANCE_BATCH_SIZE,
        delay: float = YFINANCE_BATCH_DELAY,
    ) -> int:
        """Fetch fundamentals for many tickers sequentially with rate-limiting.

        Returns total number of new records inserted.
        """
        total = 0
        for idx, ticker in enumerate(tickers, start=1):
            count = await self.fetch_and_store_fundamentals(ticker)
            total += count

            if idx % batch_size == 0:
                logger.info(
                    "bulk_fetch_progress",
                    completed=idx,
                    total_tickers=len(tickers),
                    new_records_so_far=total,
                )
                await asyncio.sleep(delay)

        logger.info(
            "bulk_fetch_complete",
            total_tickers=len(tickers),
            total_new_records=total,
        )
        return total

    async def needs_update(
        self,
        ticker: str,
        earnings_tickers: set[str] | None = None,
    ) -> bool:
        """Determine whether *ticker* needs a fundamental data refresh.

        Returns True when:
        - The ticker is in *earnings_tickers* (recently reported earnings)
        - No records exist at all
        - The most recent quarterly period is older than (current quarter − 1)
        - The current month is an earnings-season month (fallback)
        """
        # Earnings calendar override: if this ticker just reported, force update
        if earnings_tickers is not None and ticker in earnings_tickers:
            return True

        now = datetime.now()

        # Fallback: force update during earnings-season months
        if now.month in FUNDAMENTAL_UPDATE_MONTHS:
            return True

        cursor = await self._db.conn.execute(
            """
            SELECT period
            FROM fundamentals
            WHERE ticker = ? AND period_type = 'quarterly'
            ORDER BY period DESC
            LIMIT 1
            """,
            (ticker,),
        )
        row = await cursor.fetchone()
        if row is None:
            return True

        # Compare latest period to the threshold quarter (current − 1)
        current_quarter = (now.month - 1) // 3 + 1
        current_year = now.year
        threshold_quarter = current_quarter - 1
        threshold_year = current_year
        if threshold_quarter < 1:
            threshold_quarter = 4
            threshold_year -= 1
        threshold_period = f"{threshold_year}Q{threshold_quarter}"

        latest_period: str = row[0]
        return latest_period < threshold_period

    # ── Internal: sync yfinance helpers (run in executor) ────

    def _fetch_yfinance_data(self, ticker: str) -> list[dict]:
        """Synchronous helper — called via ``run_in_executor``.

        Pulls quarterly & annual income-statement data plus balance-sheet
        debt/equity from yfinance and normalises into flat dicts.
        Retries on YFRateLimitError with exponential backoff.
        """
        import yfinance as yf  # noqa: WPS433 — intentional lazy import

        for attempt in range(1, YFINANCE_RATE_LIMIT_MAX_RETRIES + 1):
            try:
                ticker_obj = yf.Ticker(ticker)
                records: list[dict] = []

                shares_outstanding = ticker_obj.info.get("sharesOutstanding")

                # ── Quarterly income statement ───────────────────────
                quarterly_inc = ticker_obj.quarterly_income_stmt
                if quarterly_inc is not None and not quarterly_inc.empty:
                    self._extract_income_records(
                        records,
                        quarterly_inc,
                        ticker,
                        period_type="quarterly",
                        shares_outstanding=shares_outstanding,
                    )

                # ── Annual income statement ──────────────────────────
                annual_inc = ticker_obj.income_stmt
                if annual_inc is not None and not annual_inc.empty:
                    self._extract_income_records(
                        records,
                        annual_inc,
                        ticker,
                        period_type="annual",
                        shares_outstanding=shares_outstanding,
                    )

                # ── Quarterly balance sheet (debt-to-equity) ─────────
                quarterly_bs = ticker_obj.quarterly_balance_sheet
                if quarterly_bs is not None and not quarterly_bs.empty:
                    self._merge_balance_sheet(records, quarterly_bs, ticker)

                return records

            except YFRateLimitError:
                if attempt >= YFINANCE_RATE_LIMIT_MAX_RETRIES:
                    logger.warning(
                        "yfinance_rate_limit_exhausted",
                        ticker=ticker,
                        attempts=attempt,
                    )
                    return []
                delay = min(
                    YFINANCE_RATE_LIMIT_BASE_DELAY
                    * (YFINANCE_RATE_LIMIT_BACKOFF_MULT ** (attempt - 1)),
                    YFINANCE_RATE_LIMIT_MAX_DELAY,
                )
                jitter = random.uniform(0, 1.0)
                logger.info(
                    "yfinance_rate_limit_retry",
                    ticker=ticker,
                    attempt=attempt,
                    delay=f"{delay + jitter:.1f}s",
                )
                time.sleep(delay + jitter)

        return []  # unreachable, but satisfies type checker

    @staticmethod
    def _fetch_institutional_data(ticker: str) -> dict:
        """Synchronous helper for institutional ownership stats.

        Retries on YFRateLimitError with exponential backoff.
        """
        import yfinance as yf  # noqa: WPS433

        for attempt in range(1, YFINANCE_RATE_LIMIT_MAX_RETRIES + 1):
            try:
                ticker_obj = yf.Ticker(ticker)
                info = ticker_obj.info
                held_pct = info.get("heldPercentInstitutions", 0.0) or 0.0

                holders_count = 0
                try:
                    inst_holders = ticker_obj.institutional_holders
                    if inst_holders is not None and not inst_holders.empty:
                        holders_count = len(inst_holders)
                except Exception:
                    pass  # some tickers don't have institutional_holders

                return {"holders_count": holders_count, "held_pct": float(held_pct)}

            except YFRateLimitError:
                if attempt >= YFINANCE_RATE_LIMIT_MAX_RETRIES:
                    logger.warning(
                        "institutional_rate_limit_exhausted",
                        ticker=ticker,
                        attempts=attempt,
                    )
                    return {"holders_count": 0, "held_pct": 0.0}
                delay = min(
                    YFINANCE_RATE_LIMIT_BASE_DELAY
                    * (YFINANCE_RATE_LIMIT_BACKOFF_MULT ** (attempt - 1)),
                    YFINANCE_RATE_LIMIT_MAX_DELAY,
                )
                jitter = random.uniform(0, 1.0)
                logger.info(
                    "institutional_rate_limit_retry",
                    ticker=ticker,
                    attempt=attempt,
                    delay=f"{delay + jitter:.1f}s",
                )
                time.sleep(delay + jitter)

        return {"holders_count": 0, "held_pct": 0.0}

    # ── Internal: extraction helpers ─────────────────────────

    def _extract_income_records(
        self,
        records: list[dict],
        df: Any,
        ticker: str,
        period_type: str,
        shares_outstanding: float | None,
    ) -> None:
        """Pull EPS / revenue / net-income rows from an income-statement DataFrame."""
        for col_ts in df.columns:
            period = self._timestamp_to_period(col_ts, period_type)
            report_date = col_ts.strftime("%Y-%m-%d")

            eps = self._safe_get_value(df, col_ts, "Basic EPS")
            if eps is None:
                eps = self._safe_get_value(df, col_ts, "Diluted EPS")

            revenue = self._safe_get_value(df, col_ts, "Total Revenue")
            net_income = self._safe_get_value(df, col_ts, "Net Income")

            records.append(
                {
                    "ticker": ticker,
                    "report_date": report_date,
                    "period": period,
                    "period_type": period_type,
                    "eps": eps,
                    "revenue": revenue,
                    "net_income": net_income,
                    "shares_outstanding": shares_outstanding,
                    "debt_to_equity": None,  # filled later from balance sheet
                }
            )

    def _merge_balance_sheet(
        self,
        records: list[dict],
        bs_df: Any,
        ticker: str,
    ) -> None:
        """Compute debt-to-equity from quarterly balance sheet and merge into *records*."""
        for col_ts in bs_df.columns:
            period = self._timestamp_to_period(col_ts, "quarterly")

            total_debt = self._safe_get_value(bs_df, col_ts, "Total Debt")
            equity = self._safe_get_value(bs_df, col_ts, "Stockholders Equity")

            if total_debt is not None and equity is not None and equity != 0:
                d2e = total_debt / equity
            else:
                d2e = None

            # Try to match an existing record for the same period
            matched = False
            for rec in records:
                if rec["ticker"] == ticker and rec["period"] == period:
                    rec["debt_to_equity"] = d2e
                    matched = True
                    break

            # If no matching income-statement record exists, create a
            # standalone record so the debt-to-equity data is not lost.
            if not matched:
                records.append(
                    {
                        "ticker": ticker,
                        "report_date": col_ts.strftime("%Y-%m-%d"),
                        "period": period,
                        "period_type": "quarterly",
                        "eps": None,
                        "revenue": None,
                        "net_income": None,
                        "shares_outstanding": None,
                        "debt_to_equity": d2e,
                    }
                )

    def _timestamp_to_period(self, ts: Any, period_type: str) -> str:
        """Convert a pandas Timestamp to a period string.

        Examples:
            Timestamp("2024-09-30"), "quarterly" → "2024Q3"
            Timestamp("2024-12-31"), "annual"    → "FY2024"
        """
        if period_type == "quarterly":
            quarter = (ts.month - 1) // 3 + 1
            return f"{ts.year}Q{quarter}"
        # annual
        return f"FY{ts.year}"

    @staticmethod
    def _safe_get_value(df: Any, col: Any, row_label: str) -> float | None:
        """Safely extract a single cell from a DataFrame, returning None on miss."""
        try:
            if row_label in df.index:
                val = df.loc[row_label, col]
                import math

                if val is None or (isinstance(val, float) and math.isnan(val)):
                    return None
                return float(val)
        except (KeyError, TypeError, ValueError):
            pass
        return None

    # ── Internal: database persistence ───────────────────────

    async def _store_records(self, records: list[dict]) -> int:
        """INSERT OR IGNORE records into the fundamentals table.

        Returns the number of rows actually inserted (ignores duplicates).
        """
        inserted = 0
        for rec in records:
            cursor = await self._db.conn.execute(
                """
                INSERT OR IGNORE INTO fundamentals
                    (ticker, report_date, period, period_type,
                     eps, revenue, net_income, shares_outstanding,
                     debt_to_equity, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
                """,
                (
                    rec["ticker"],
                    rec["report_date"],
                    rec["period"],
                    rec["period_type"],
                    rec["eps"],
                    rec["revenue"],
                    rec["net_income"],
                    rec["shares_outstanding"],
                    rec["debt_to_equity"],
                ),
            )
            inserted += cursor.rowcount

        await self._db.conn.commit()

        if inserted:
            logger.info(
                "fundamentals_stored",
                ticker=records[0]["ticker"],
                new_records=inserted,
                total_attempted=len(records),
            )
        return inserted
