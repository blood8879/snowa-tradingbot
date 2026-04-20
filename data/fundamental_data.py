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

    async def fetch_and_store_fundamentals(self, ticker: str, *, market: str = "US") -> int:
        """Fetch quarterly + annual financial data for *ticker* and persist.

        Args:
            ticker: Stock ticker symbol
            market: "US" for US stocks (yfinance), "KR" for Korean stocks (pykrx)

        Returns the number of new records inserted (0 on error).
        """
        try:
            loop = asyncio.get_event_loop()
            if market == "KR":
                records = await loop.run_in_executor(
                    None, self._fetch_pykrx_data, ticker
                )
            else:
                records = await loop.run_in_executor(
                    None, self._fetch_yfinance_data, ticker
                )
            if not records:
                logger.debug(
                    "fetch_fundamentals_empty",
                    ticker=ticker,
                    market=market,
                )
                return 0
            return await self._store_records(records)
        except Exception:
            logger.warning("fetch_fundamentals_failed", ticker=ticker, market=market, exc_info=True)
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
        *,
        market: str = "US",
    ) -> int:
        """Fetch fundamentals for many tickers sequentially with rate-limiting.

        Args:
            tickers: List of ticker symbols
            batch_size: Number of tickers to process before logging progress
            delay: Delay between batches
            market: "US" for US stocks (yfinance), "KR" for Korean stocks (pykrx)

        Returns total number of new records inserted.
        """
        total = 0
        empty_tickers: list[str] = []
        per_request_delay = 0.5 if market == "US" else 0.1

        for idx, ticker in enumerate(tickers, start=1):
            count = await self.fetch_and_store_fundamentals(ticker, market=market)
            total += count
            if count == 0:
                empty_tickers.append(ticker)

            # Per-request delay to avoid yfinance rate limiting
            await asyncio.sleep(per_request_delay)

            if idx % batch_size == 0:
                logger.info(
                    "bulk_fetch_progress",
                    completed=idx,
                    total_tickers=len(tickers),
                    new_records_so_far=total,
                    empty_so_far=len(empty_tickers),
                    market=market,
                )
                await asyncio.sleep(delay)

        # Retry pass for tickers that returned empty data (capped to avoid long delays)
        MAX_RETRY = 30
        if empty_tickers and market == "US":
            retry_count = min(len(empty_tickers), MAX_RETRY)
            retry_targets = empty_tickers[:retry_count]
            logger.info(
                "bulk_fetch_retry_start",
                empty_count=len(empty_tickers),
                retry_count=retry_count,
                sample=retry_targets[:10],
                market=market,
            )
            retry_total = 0
            still_empty = 0
            for idx, ticker in enumerate(retry_targets, start=1):
                await asyncio.sleep(0.8)
                count = await self.fetch_and_store_fundamentals(ticker, market=market)
                retry_total += count
                if count == 0:
                    still_empty += 1

            total += retry_total
            logger.info(
                "bulk_fetch_retry_complete",
                retried=retry_count,
                new_records=retry_total,
                still_empty=still_empty,
                market=market,
            )

        logger.info(
            "bulk_fetch_complete",
            total_tickers=len(tickers),
            total_new_records=total,
            empty_count=len(empty_tickers),
            success_rate=f"{((len(tickers) - len(empty_tickers)) / len(tickers) * 100):.1f}%" if tickers else "N/A",
            market=market,
        )
        return total

    async def needs_update(
        self,
        ticker: str,
        earnings_tickers: set[str] | None = None,
        *,
        market: str = "US",
    ) -> bool:
        """Determine whether *ticker* needs a fundamental data refresh.

        Args:
            ticker: Stock ticker symbol
            earnings_tickers: Set of tickers that recently reported earnings
            market: "US" for US stocks, "KR" for Korean stocks

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

    # ── Internal: sync helpers (run in executor) ─────────────

    def _fetch_pykrx_data(self, ticker: str) -> list[dict]:
        """Synchronous helper for Korean fundamental data via pykrx.

        pykrx provides basic fundamental data:
        - PER, PBR, EPS, BPS, DIV via get_market_fundamental_by_date()

        Returns list of fundamental data records (quarterly sampling).
        """
        try:
            from pykrx import stock as pykrx_stock  # noqa: WPS433 — lazy import
        except ImportError:
            logger.warning("pykrx_import_failed", ticker=ticker)
            return []

        from datetime import timedelta  # noqa: WPS433

        records = []
        now = datetime.now()

        # Get quarterly-ish data by sampling every 3 months
        for months_ago in range(0, 24, 3):  # Last 2 years, quarterly
            sample_date = (now - timedelta(days=months_ago * 30)).strftime("%Y%m%d")
            try:
                # Get fundamental data for this ticker on this date
                df = pykrx_stock.get_market_fundamental_by_date(
                    sample_date, sample_date, ticker
                )
                if df is not None and not df.empty:
                    row = df.iloc[0]
                    eps = float(row.get("EPS", 0)) if row.get("EPS", 0) != 0 else None

                    sample_datetime = now - timedelta(days=months_ago * 30)
                    quarter = (sample_datetime.month - 1) // 3 + 1
                    year = sample_datetime.year
                    period = f"{year}Q{quarter}"

                    records.append(
                        {
                            "ticker": ticker,
                            "report_date": f"{sample_date[:4]}-{sample_date[4:6]}-{sample_date[6:8]}",
                            "period": period,
                            "period_type": "quarterly",
                            "eps": eps,
                            "revenue": None,  # pykrx doesn't provide revenue
                            "net_income": None,
                            "shares_outstanding": None,
                            "debt_to_equity": None,
                        }
                    )
            except Exception as exc:
                logger.debug(
                    "pykrx_sample_failed",
                    ticker=ticker,
                    sample_date=sample_date,
                    error=str(exc),
                )
                continue

        if records:
            logger.info(
                "pykrx_data_fetched",
                ticker=ticker,
                record_count=len(records),
            )

        return records

    def _fetch_yfinance_data(self, ticker: str) -> list[dict]:
        """Synchronous helper — called via ``run_in_executor``.

        Pulls quarterly & annual income-statement data plus balance-sheet
        debt/equity from yfinance and normalises into flat dicts.
        Retries on YFRateLimitError and empty responses with exponential backoff.
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

                # Retry if yfinance returned empty data (silent rate limit)
                if not records and attempt < YFINANCE_RATE_LIMIT_MAX_RETRIES:
                    delay = YFINANCE_RATE_LIMIT_BASE_DELAY * attempt + random.uniform(0, 1.0)
                    logger.debug(
                        "yfinance_empty_response_retry",
                        ticker=ticker,
                        attempt=attempt,
                        delay=f"{delay:.1f}s",
                    )
                    time.sleep(delay)
                    continue

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

            # Fallback: derive EPS from net_income / shares_outstanding
            if eps is None and net_income is not None and shares_outstanding:
                eps = net_income / shares_outstanding

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
        """INSERT OR REPLACE records into the fundamentals table.

        Returns the number of rows actually inserted or updated.
        """
        inserted = 0
        for rec in records:
            cursor = await self._db.conn.execute(
                """
                INSERT OR REPLACE INTO fundamentals
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
