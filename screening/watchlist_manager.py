"""
Watchlist manager — orchestrates the full CANSLIM screening pipeline.

Workflow:
  1. Load stock universe
  2. Calculate RS Ratings for entire universe
  3. Run CANSLIM screener on all tickers
  4. Apply Minervini Trend Template filter
  5. Calculate Custom Composite Score
  6. Build/update the watchlist in SQLite
  7. Log screening results
"""

from __future__ import annotations

from datetime import datetime

import structlog

from core.database import Database
from data.universe import UniverseManager
from data.price_cache import PriceCache
from data.market_data import MarketDataProvider
from data.fundamental_data import FundamentalDataManager
from screening.rs_rating import RSRatingCalculator
from screening.canslim_screener import CANSLIMResult, CANSLIMScreener
from screening.minervini_template import MinerviniTemplate
from screening.custom_composite import CompositeScoreCalculator

logger = structlog.get_logger(__name__)


class WatchlistManager:
    """워치리스트 관리 — 전체 스크리닝 파이프라인 오케스트레이션."""

    def __init__(self, db: Database) -> None:
        self._db = db

    # ── Full Screening Pipeline ──────────────────────────────

    async def run_full_screening(
        self, tickers: list[str] | None = None
    ) -> list[dict]:
        """Run the complete CANSLIM + Minervini screening pipeline.

        Steps:
            1. Load tradeable tickers from universe (if not provided).
            2. Initialize all screening components.
            3. Calculate RS Ratings for the entire universe.
            4. Run CANSLIM screening on all tickers.
            5. Filter to tickers that passed all CANSLIM filters.
            6. Run Minervini Trend Template on CANSLIM-passed tickers.
            7. Calculate composite score for Minervini-passed tickers.
            8. Save final watchlist to DB.

        Args:
            tickers: Optional explicit list of tickers. If None,
                     loads from UniverseManager (non-ETF only).

        Returns:
            List of dicts with ticker, scores, and pass/fail status.
        """
        now = datetime.now().isoformat(timespec="seconds")

        # ── Step 1: Load tickers ─────────────────────────────
        universe = UniverseManager()
        await universe.load_universe()
        if tickers is None:
            tradeable = universe.filter_tradeable()
            tickers = [s.ticker for s in tradeable]

        logger.info("screening_started", total_tickers=len(tickers))

        # ── Step 2: Initialize components ────────────────────
        price_cache = PriceCache(self._db)
        market_data = MarketDataProvider(price_cache)
        fundamental_data = FundamentalDataManager(self._db)
        rs_calc = RSRatingCalculator(price_cache)
        screener = CANSLIMScreener(fundamental_data, market_data, price_cache)
        template = MinerviniTemplate(market_data)
        composite_calc = CompositeScoreCalculator(fundamental_data, market_data)

        # ── Step 3: Calculate RS Ratings ─────────────────────
        rs_ratings = await rs_calc.calculate_universe(tickers)

        logger.info(
            "rs_ratings_calculated",
            total_tickers=len(tickers),
            rated=len(rs_ratings),
        )

        # ── Step 4: Run CANSLIM screening (core filters: C/A/S/L) ──
        canslim_results = await screener.screen_universe(
            tickers, rs_ratings, core_only=True,
        )

        # ── Step 5: Filter to passed tickers ─────────────────
        canslim_passed = [r for r in canslim_results if r.passed_all]
        canslim_passed_tickers = [r.ticker for r in canslim_passed]

        logger.info(
            "canslim_screening_complete",
            total_screened=len(canslim_results),
            passed=len(canslim_passed),
        )

        # ── Step 6: Run Minervini template ───────────────────
        minervini_passed_tickers: list[str] = []
        for ticker in canslim_passed_tickers:
            try:
                rs = rs_ratings.get(ticker)
                result = await template.check(ticker, rs_rating=rs)
                if result.passed_all:
                    minervini_passed_tickers.append(ticker)
            except Exception:
                logger.warning(
                    "minervini_check_failed",
                    ticker=ticker,
                    exc_info=True,
                )

        logger.info(
            "minervini_filtering_complete",
            canslim_passed=len(canslim_passed_tickers),
            minervini_passed=len(minervini_passed_tickers),
        )

        # ── Step 7: Calculate composite scores ───────────────
        composite_scores: dict[str, float] = {}
        for ticker in minervini_passed_tickers:
            try:
                rs = rs_ratings.get(ticker)
                score = await composite_calc.calculate(ticker, rs_rating=rs)
                if score is not None:
                    composite_scores[ticker] = score
            except Exception:
                logger.warning(
                    "composite_score_failed",
                    ticker=ticker,
                    exc_info=True,
                )

        # ── Step 8: Build watchlist entries and save ─────────
        # Build a lookup from CANSLIM results for quick access
        canslim_by_ticker: dict[str, CANSLIMResult] = {
            r.ticker: r for r in canslim_passed
        }

        entries: list[dict] = []
        for ticker in minervini_passed_tickers:
            canslim_result = canslim_by_ticker.get(ticker)
            if canslim_result is None:
                continue

            quarterly_eps_growth = canslim_result.c_filter.value
            annual_eps_cagr = canslim_result.a_filter.value
            rs_rating = rs_ratings.get(ticker)
            inst_holders = (
                int(canslim_result.i_filter.value)
                if canslim_result.i_filter.value is not None
                else None
            )
            institutional_change_pct = None
            composite_score = composite_scores.get(ticker)
            avg_volume = (
                int(canslim_result.s_filter.value)
                if canslim_result.s_filter.value is not None
                else None
            )

            latest_price: float | None = None
            try:
                latest_price = await market_data.get_latest_price(ticker)
            except Exception:
                pass

            sector = None
            industry = None
            market_cap = None
            exchange = universe.get_exchange(ticker) if universe else "NASD"

            entry = {
                "ticker": ticker,
                "added_date": now,
                "last_screened": now,
                "quarterly_eps_growth": quarterly_eps_growth,
                "annual_eps_cagr": annual_eps_cagr,
                "rs_rating": float(rs_rating) if rs_rating is not None else None,
                "institutional_holders": inst_holders,
                "institutional_change_pct": institutional_change_pct,
                "custom_composite_score": composite_score,
                "minervini_pass": 1,
                "sector": sector,
                "industry": industry,
                "avg_daily_volume": avg_volume,
                "market_cap": market_cap,
                "latest_price": latest_price,
                "exchange": exchange,
                "status": "ACTIVE",
            }
            entries.append(entry)

        # Sort by composite score descending (best first)
        entries.sort(
            key=lambda e: e.get("custom_composite_score") or 0,
            reverse=True,
        )

        saved_count = await self._save_watchlist(entries)

        logger.info(
            "screening_complete",
            total_screened=len(tickers),
            canslim_passed=len(canslim_passed),
            minervini_passed=len(minervini_passed_tickers),
            final_watchlist=saved_count,
        )

        return entries

    # ── Watchlist Persistence ────────────────────────────────

    async def _save_watchlist(self, entries: list[dict]) -> int:
        """Save/update watchlist entries in DB.

        For each entry, performs INSERT OR REPLACE. Then marks any
        previously ACTIVE tickers that are NOT in the new results
        as status='REMOVED'.

        Returns:
            Number of entries saved.
        """
        conn = self._db.conn
        now = datetime.now().isoformat(timespec="seconds")
        new_tickers: set[str] = set()

        for entry in entries:
            ticker = entry["ticker"]
            new_tickers.add(ticker)

            # Preserve original added_date if ticker already exists
            cursor = await conn.execute(
                "SELECT added_date FROM watchlist WHERE ticker = ?",
                (ticker,),
            )
            existing = await cursor.fetchone()
            added_date = existing[0] if existing else entry.get("added_date", now)

            await conn.execute(
                """
                INSERT OR REPLACE INTO watchlist (
                    ticker, added_date, last_screened,
                    quarterly_eps_growth, annual_eps_cagr, rs_rating,
                    institutional_holders, institutional_change_pct,
                    custom_composite_score, minervini_pass,
                    sector, industry, avg_daily_volume, market_cap,
                    status, latest_price, exchange
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    ticker,
                    added_date,
                    entry.get("last_screened", now),
                    entry.get("quarterly_eps_growth"),
                    entry.get("annual_eps_cagr"),
                    entry.get("rs_rating"),
                    entry.get("institutional_holders"),
                    entry.get("institutional_change_pct"),
                    entry.get("custom_composite_score"),
                    entry.get("minervini_pass", 0),
                    entry.get("sector"),
                    entry.get("industry"),
                    entry.get("avg_daily_volume"),
                    entry.get("market_cap"),
                    "ACTIVE",
                    entry.get("latest_price"),
                    entry.get("exchange", "NASD"),
                ),
            )

        # Mark tickers NOT in the new results as REMOVED
        if new_tickers:
            placeholders = ",".join("?" for _ in new_tickers)
            await conn.execute(
                f"""
                UPDATE watchlist
                SET status = 'REMOVED'
                WHERE status = 'ACTIVE' AND ticker NOT IN ({placeholders})
                """,
                tuple(new_tickers),
            )
        else:
            # No new entries — mark all previously active as REMOVED
            await conn.execute(
                "UPDATE watchlist SET status = 'REMOVED' WHERE status = 'ACTIVE'"
            )

        await conn.commit()

        logger.info("watchlist_saved", count=len(entries))
        return len(entries)

    # ── Watchlist Queries ────────────────────────────────────

    async def get_active_watchlist(self) -> list[dict]:
        """Query all ACTIVE watchlist entries, ordered by composite score.

        Returns:
            List of dicts, best composite score first.
        """
        cursor = await self._db.conn.execute(
            """
            SELECT ticker, added_date, last_screened,
                   quarterly_eps_growth, annual_eps_cagr, rs_rating,
                   institutional_holders, institutional_change_pct,
                   custom_composite_score, minervini_pass,
                   sector, industry, avg_daily_volume, market_cap,
                   status
            FROM watchlist
            WHERE status = 'ACTIVE'
            ORDER BY custom_composite_score DESC
            """
        )
        rows = await cursor.fetchall()
        columns = [
            "ticker", "added_date", "last_screened",
            "quarterly_eps_growth", "annual_eps_cagr", "rs_rating",
            "institutional_holders", "institutional_change_pct",
            "custom_composite_score", "minervini_pass",
            "sector", "industry", "avg_daily_volume", "market_cap",
            "status",
        ]
        return [dict(zip(columns, row)) for row in rows]

    async def get_watchlist_tickers(self) -> list[str]:
        """Return just the ticker symbols from the active watchlist."""
        cursor = await self._db.conn.execute(
            """
            SELECT ticker FROM watchlist
            WHERE status = 'ACTIVE'
            ORDER BY custom_composite_score DESC
            """
        )
        rows = await cursor.fetchall()
        return [row[0] for row in rows]

    # ── Watchlist Management ─────────────────────────────────

    async def remove_ticker(self, ticker: str) -> None:
        """Set status='REMOVED' for a ticker in the watchlist."""
        await self._db.conn.execute(
            "UPDATE watchlist SET status = 'REMOVED' WHERE ticker = ?",
            (ticker,),
        )
        await self._db.conn.commit()
        logger.info("watchlist_ticker_removed", ticker=ticker)

    async def suspend_ticker(self, ticker: str) -> None:
        """Set status='SUSPENDED' for a ticker in the watchlist."""
        await self._db.conn.execute(
            "UPDATE watchlist SET status = 'SUSPENDED' WHERE ticker = ?",
            (ticker,),
        )
        await self._db.conn.commit()
        logger.info("watchlist_ticker_suspended", ticker=ticker)
