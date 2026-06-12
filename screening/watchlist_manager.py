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

import csv
from datetime import datetime
from pathlib import Path

import structlog

from config.settings import get_settings
from core.database import Database
from data.universe import UniverseManager
from data.universe_kr import KRUniverseManager
from config.market_config import get_market_config
from data.price_cache import PriceCache
from data.market_data import MarketDataProvider
from data.fundamental_data import FundamentalDataManager
from screening.rs_rating import RSRatingCalculator
from screening.canslim_screener import CANSLIMResult, CANSLIMScreener
from screening.minervini_template import MinerviniTemplate
from screening.custom_composite import CompositeScoreCalculator

# DART API key for Korean financial data
import os

DART_API_KEY = os.environ.get("DART_API_KEY", "a9a83a37044c92dda80876d98c108d112c89136b")

logger = structlog.get_logger(__name__)


class WatchlistManager:
    """워치리스트 관리 — 전체 스크리닝 파이프라인 오케스트레이션."""

    def __init__(self, db: Database) -> None:
        self._db = db

    # ── Full Screening Pipeline ──────────────────────────────

    async def run_full_screening(
        self, tickers: list[str] | None = None, *, market: str = "US"
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
            market: Market identifier ("US" or "KR"). Default: "US".

        Returns:
            List of dicts with ticker, scores, and pass/fail status.
        """
        now = datetime.now().isoformat(timespec="seconds")

        # ── Step 1: Load tickers ─────────────────────────────
        if market == "KR":
            kr_universe = KRUniverseManager()
            await kr_universe.load_universe()
            if tickers is None:
                tradeable = kr_universe.filter_tradeable()
                tickers = [s.ticker for s in tradeable]
            universe = kr_universe  # Use KR universe for exchange lookup
        else:
            universe = UniverseManager()
            await universe.load_universe()
            if tickers is None:
                tradeable = universe.filter_tradeable()
                tickers = [s.ticker for s in tradeable]

        logger.info("screening_started", total_tickers=len(tickers), market=market)

        # ── Step 2: Initialize components ────────────────────
        price_cache = PriceCache(self._db)
        market_data = MarketDataProvider(price_cache)
        fundamental_data = FundamentalDataManager(self._db)
        rs_calc = RSRatingCalculator(price_cache)
        screener = CANSLIMScreener(fundamental_data, market_data, price_cache)
        template = MinerviniTemplate(market_data)
        composite_calc = CompositeScoreCalculator(fundamental_data, market_data)

        # ── Step 2.5: Load existing watchlist for hysteresis ─────
        # Why: 기존 watchlist 종목은 HOLD 임계치(관대)로 평가해서 경계값 토글 방지.
        #      또한 데이터 결손 시 이전 값으로 fallback.
        existing_tickers, previous_values_map = await self._load_existing_watchlist(
            market=market,
        )
        logger.info(
            "existing_watchlist_loaded",
            count=len(existing_tickers),
            with_previous_values=len(previous_values_map),
            market=market,
        )

        # ── Step 3: Calculate RS Ratings ─────────────────────
        rs_ratings = await rs_calc.calculate_universe(tickers, market=market)

        logger.info(
            "rs_ratings_calculated",
            total_tickers=len(tickers),
            rated=len(rs_ratings),
            market=market,
        )

        # ── Step 3.5: For KR market, pre-fetch DART financials ──
        if market == "KR" and DART_API_KEY:
            try:
                from data.dart_financial import DartFinancialFetcher
                from config.constants import CANSLIM_MIN_RS_RATING

                # Pre-filter: RS >= 80 candidates + existing watchlist tickers
                # (watchlist tickers need fresh data for re-screening)
                dart_candidates = [
                    t for t in tickers
                    if rs_ratings.get(t, 0) >= CANSLIM_MIN_RS_RATING
                ]
                # Always include existing watchlist tickers regardless of RS
                cursor = await self._db.conn.execute(
                    "SELECT ticker FROM watchlist WHERE status = 'ACTIVE' AND market = ?",
                    (market,),
                )
                existing_rows = await cursor.fetchall()
                existing_tickers = {row[0] for row in existing_rows}
                dart_candidate_set = set(dart_candidates)
                for t in existing_tickers:
                    if t not in dart_candidate_set and t in set(tickers):
                        dart_candidates.append(t)

                max_dart_prefetch = get_settings().screening_max_kr_dart_prefetch_targets
                if max_dart_prefetch < 0:
                    max_dart_prefetch = 0

                if len(dart_candidates) > max_dart_prefetch:
                    logger.warning(
                        "dart_prefetch_candidates_capped",
                        original=len(dart_candidates),
                        capped=max_dart_prefetch,
                        market=market,
                    )
                    dart_candidates = dart_candidates[:max_dart_prefetch]

                logger.info(
                    "dart_prefetch_start",
                    candidates=len(dart_candidates),
                    total_tickers=len(tickers),
                    market=market,
                )

                dart = DartFinancialFetcher(
                    api_key=DART_API_KEY,
                    cache_dir=str(self._db.db_path.parent) if hasattr(self._db, 'db_path') else "data",
                )
                await dart.load_corp_codes()
                dart_records = await dart.bulk_fetch_and_store(
                    dart_candidates, self._db,
                )

                logger.info(
                    "dart_prefetch_complete",
                    candidates=len(dart_candidates),
                    records=dart_records,
                    market=market,
                )
            except Exception:
                logger.warning(
                    "dart_prefetch_failed",
                    market=market,
                    exc_info=True,
                )

        # ── Step 4: Run CANSLIM screening (core filters: C/A/S/L) ──
        # 기존 watchlist 종목은 hold_mode=True로 HOLD 임계치 적용 (hysteresis)
        canslim_results = await screener.screen_universe(
            tickers, rs_ratings, core_only=True, market=market,
            existing_tickers=existing_tickers,
            previous_values_map=previous_values_map,
        )

        # ── Step 5: Filter to passed tickers ─────────────────
        canslim_passed = [r for r in canslim_results if r.passed_all]
        canslim_passed_tickers = [r.ticker for r in canslim_passed]

        logger.info(
            "canslim_screening_complete",
            total_screened=len(canslim_results),
            passed=len(canslim_passed),
            market=market,
        )

        # ── Step 6: Run Minervini template ───────────────────
        # 기존 watchlist 종목은 passed_for_hold (8개 중 6개 + 200MA 필수)로 평가
        minervini_passed_tickers: list[str] = []
        for ticker in canslim_passed_tickers:
            try:
                rs = rs_ratings.get(ticker)
                result = await template.check(ticker, rs_rating=rs, market=market)
                is_existing = ticker in existing_tickers
                check_pass = result.passed_for_hold if is_existing else result.passed_all
                if check_pass:
                    minervini_passed_tickers.append(ticker)
            except Exception:
                logger.warning(
                    "minervini_check_failed",
                    ticker=ticker,
                    market=market,
                    exc_info=True,
                )

        logger.info(
            "minervini_filtering_complete",
            canslim_passed=len(canslim_passed_tickers),
            minervini_passed=len(minervini_passed_tickers),
            market=market,
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
                    market=market,
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

            # 섹터/업종 분류 — 상관 한도(업종 6유닛/섹터 10유닛) 체크에 필수.
            # DB 기존값 재사용으로 yfinance 반복 조회를 방지하고,
            # US 신규 종목만 yfinance info에서 1회 조회해 채운다.
            sector = None
            industry = None
            try:
                cursor = await self._db.conn.execute(
                    "SELECT sector, industry FROM watchlist WHERE ticker = ?",
                    (ticker,),
                )
                row = await cursor.fetchone()
                if row:
                    sector, industry = row[0], row[1]
            except Exception:
                pass
            if market == "US" and (not sector or not industry):
                try:
                    import asyncio as _asyncio
                    import yfinance as _yf
                    info = await _asyncio.to_thread(lambda: _yf.Ticker(ticker).info)
                    sector = sector or info.get("sector")
                    industry = industry or info.get("industry")
                except Exception:
                    logger.debug("watchlist_sector_fetch_failed", ticker=ticker)
            market_cap = None
            # Exchange 폴백: universe → DB 기존값 → market 기반 기본값
            exchange = None
            if universe and universe.get_stock(ticker):
                exchange = universe.get_exchange(ticker)
            if exchange is None:
                try:
                    cursor = await self._db.conn.execute(
                        "SELECT exchange FROM watchlist WHERE ticker = ?",
                        (ticker,),
                    )
                    row = await cursor.fetchone()
                    if row and row[0]:
                        exchange = row[0]
                except Exception:
                    pass
            if exchange is None:
                exchange = "KOSPI" if market == "KR" else "NASD"

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
                "market": market,
                "status": "ACTIVE",
            }
            entries.append(entry)

        # Sort by composite score descending (best first)
        entries.sort(
            key=lambda e: e.get("custom_composite_score") or 0,
            reverse=True,
        )

        # Build removal reason lookup from screening results
        canslim_all: dict[str, "CANSLIMResult"] = {r.ticker: r for r in canslim_results}
        minervini_set = set(minervini_passed_tickers)

        saved_count = await self._save_watchlist(
            entries,
            market=market,
            canslim_all=canslim_all,
            minervini_set=minervini_set,
        )

        logger.info(
            "screening_complete",
            total_screened=len(tickers),
            canslim_passed=len(canslim_passed),
            minervini_passed=len(minervini_passed_tickers),
            final_watchlist=saved_count,
            market=market,
        )

        return entries

    # ── Hysteresis Support ───────────────────────────────────

    async def _load_existing_watchlist(
        self, *, market: str,
    ) -> tuple[set[str], dict[str, dict]]:
        """Load current ACTIVE watchlist tickers and their last screening values.

        Used to apply hysteresis (HOLD thresholds) and data-gap fallback
        during the next screening run.

        Args:
            market: Market filter ('US' or 'KR').

        Returns:
            (existing_tickers, previous_values_map)
            previous_values_map: ticker → {quarterly_eps_growth, annual_eps_cagr,
                                           rs_rating, last_screened}
            Only includes tickers whose last_screened is within
            SCREENING_FALLBACK_MAX_DAYS.
        """
        from config.constants import SCREENING_FALLBACK_MAX_DAYS
        from datetime import datetime, timedelta

        cursor = await self._db.conn.execute(
            """SELECT ticker, quarterly_eps_growth, annual_eps_cagr,
                      rs_rating, last_screened
               FROM watchlist
               WHERE status = 'ACTIVE' AND market = ?""",
            (market,),
        )
        rows = await cursor.fetchall()

        cutoff = datetime.now() - timedelta(days=SCREENING_FALLBACK_MAX_DAYS)
        existing: set[str] = set()
        prev_map: dict[str, dict] = {}

        for row in rows:
            ticker, qeg, acagr, rs, last_screened = row
            existing.add(ticker)

            # Only include values if last_screened is recent enough
            if last_screened:
                try:
                    ts = datetime.fromisoformat(last_screened)
                    if ts < cutoff:
                        continue
                except (ValueError, TypeError):
                    continue

            values: dict = {}
            if qeg is not None:
                values["quarterly_eps_growth"] = qeg
            if acagr is not None:
                values["annual_eps_cagr"] = acagr
            if rs is not None:
                values["rs_rating"] = rs
            if values:
                prev_map[ticker] = values

        return existing, prev_map

    # ── Watchlist Persistence ────────────────────────────────

    async def _save_watchlist(
        self,
        entries: list[dict],
        *,
        market: str = "US",
        canslim_all: dict | None = None,
        minervini_set: set | None = None,
    ) -> int:
        """Save/update watchlist entries in DB.

        For each entry, performs INSERT OR REPLACE. Then marks any
        previously ACTIVE tickers that are NOT in the new results
        as status='REMOVED'.

        Args:
            entries: List of watchlist entry dicts.
            market: Market identifier ("US" or "KR"). Default: "US".
            canslim_all: All CANSLIM results keyed by ticker (for removal reasons).
            minervini_set: Set of tickers that passed Minervini template.

        Returns:
            Number of entries saved.
        """
        conn = self._db.conn
        now = datetime.now().isoformat(timespec="seconds")
        new_tickers: set[str] = set()

        # Get currently active tickers before update
        active_cursor = await conn.execute(
            "SELECT ticker FROM watchlist WHERE status = 'ACTIVE' AND market = ?",
            (market,),
        )
        prev_active = {row[0] for row in await active_cursor.fetchall()}

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
                    status, latest_price, exchange, market
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    entry.get("market", "US"),
                ),
            )

        # Mark tickers NOT in the new results as REMOVED (filtered by market)
        if new_tickers:
            placeholders = ",".join("?" for _ in new_tickers)
            await conn.execute(
                f"""
                UPDATE watchlist
                SET status = 'REMOVED'
                WHERE status = 'ACTIVE' AND market = ? AND ticker NOT IN ({placeholders})
                """,
                (market, *tuple(new_tickers)),
            )
        else:
            # No new entries — mark all previously active as REMOVED for this market
            await conn.execute(
                "UPDATE watchlist SET status = 'REMOVED' WHERE status = 'ACTIVE' AND market = ?",
                (market,),
            )

        await conn.commit()

        # Log watchlist changes to history
        added_tickers = new_tickers - prev_active
        removed_tickers = prev_active - new_tickers

        # Load KR stock names for history records
        kr_names: dict[str, str] = {}
        if market == "KR" and (added_tickers or removed_tickers):
            cache_path = Path("data/universe_kr_cache.csv")
            if cache_path.exists():
                try:
                    with open(cache_path, "r", encoding="utf-8") as f:
                        reader = csv.DictReader(f)
                        for row in reader:
                            kr_names[row["ticker"]] = row["name"]
                except Exception:
                    pass

        for ticker in added_tickers:
            entry_data = next((e for e in entries if e["ticker"] == ticker), None)
            eps_g = entry_data.get("quarterly_eps_growth") if entry_data else None
            cagr = entry_data.get("annual_eps_cagr") if entry_data else None
            rs = entry_data.get("rs_rating") if entry_data else None
            cs = entry_data.get("custom_composite_score") if entry_data else None
            stock_name = (entry_data.get("name") if entry_data else None) or kr_names.get(ticker)
            reason_parts = ["CANSLIM+Minervini 통과"]
            if eps_g is not None:
                reason_parts.append(f"EPS성장 {eps_g * 100:.0f}%")
            if rs is not None:
                reason_parts.append(f"RS {rs:.0f}")
            if cs is not None:
                reason_parts.append(f"종합 {cs:.0f}")
            await conn.execute(
                """INSERT INTO watchlist_history
                   (ticker, name, market, action, reason, quarterly_eps_growth, annual_eps_cagr,
                    rs_rating, composite_score, minervini_pass, recorded_at)
                   VALUES (?, ?, ?, 'ADDED', ?, ?, ?, ?, ?, ?, ?)""",
                (
                    ticker,
                    stock_name,
                    market,
                    ", ".join(reason_parts),
                    eps_g, cagr, rs, cs,
                    entry_data.get("minervini_pass", 0) if entry_data else 0,
                    now,
                ),
            )

        for ticker in removed_tickers:
            score_cursor = await conn.execute(
                """SELECT quarterly_eps_growth, annual_eps_cagr, rs_rating,
                          custom_composite_score, minervini_pass, name
                   FROM watchlist WHERE ticker = ?""",
                (ticker,),
            )
            score_row = await score_cursor.fetchone()

            # Use latest screening values where available, fallback to DB
            prev_eps_g = score_row[0] if score_row else None
            prev_cagr = score_row[1] if score_row else None
            canslim_r = canslim_all.get(ticker) if canslim_all else None
            new_eps_g = canslim_r.c_filter.value if canslim_r and canslim_r.c_filter.value is not None else prev_eps_g
            new_cagr = canslim_r.a_filter.value if canslim_r and canslim_r.a_filter.value is not None else prev_cagr

            # Build specific removal reason (with prev values for comparison)
            reason = self._build_removal_reason(ticker, canslim_all, minervini_set, prev_eps_g=prev_eps_g, prev_cagr=prev_cagr)

            removed_name = (score_row[5] if score_row else None) or kr_names.get(ticker)
            await conn.execute(
                """INSERT INTO watchlist_history
                   (ticker, name, market, action, reason, quarterly_eps_growth, annual_eps_cagr,
                    rs_rating, composite_score, minervini_pass, recorded_at)
                   VALUES (?, ?, ?, 'REMOVED', ?, ?, ?, ?, ?, ?, ?)""",
                (
                    ticker,
                    removed_name,
                    market,
                    reason,
                    new_eps_g,
                    new_cagr,
                    score_row[2] if score_row else None,
                    score_row[3] if score_row else None,
                    score_row[4] if score_row else 0,
                    now,
                ),
            )

        if added_tickers or removed_tickers:
            await conn.commit()
            logger.info(
                "watchlist_history_logged",
                added=len(added_tickers),
                removed=len(removed_tickers),
                market=market,
            )

        logger.info("watchlist_saved", count=len(entries), market=market)
        return len(entries)

    @staticmethod
    def _build_removal_reason(
        ticker: str,
        canslim_all: dict | None,
        minervini_set: set | None,
        *,
        prev_eps_g: float | None = None,
        prev_cagr: float | None = None,
    ) -> str:
        """Build a human-readable removal reason from screening results."""
        if canslim_all is None:
            return "스크리닝 탈락"

        result = canslim_all.get(ticker)
        if result is None:
            return "유니버스 제외 (상장폐지/거래량 부족)"

        # Check which CANSLIM filters failed
        failed: list[str] = []
        if not result.c_filter.passed:
            val = result.c_filter.value
            if val is not None:
                prev_str = f"{prev_eps_g * 100:.0f}%→" if prev_eps_g is not None else ""
                failed.append(f"분기EPS성장 미달({prev_str}{val * 100:.0f}%<25%)")
            else:
                failed.append("분기EPS 데이터 없음")
        if not result.a_filter.passed:
            val = result.a_filter.value
            if val is not None:
                prev_str = f"{prev_cagr * 100:.0f}%→" if prev_cagr is not None else ""
                failed.append(f"연간EPS성장 미달({prev_str}{val * 100:.0f}%<25%)")
            else:
                failed.append("연간EPS 데이터 없음")
        if not result.s_filter.passed:
            failed.append("거래량 부족")
        if not result.l_filter.passed:
            val = result.l_filter.value
            if val is not None:
                failed.append(f"RS등급 미달({val:.0f}<80)")
            else:
                failed.append("RS등급 데이터 없음")

        if failed:
            return "CANSLIM 탈락: " + ", ".join(failed)

        # Passed CANSLIM but failed Minervini
        if minervini_set is not None and ticker not in minervini_set:
            return "Minervini 추세 템플릿 미통과"

        return "스크리닝 탈락"

    # ── Watchlist Queries ────────────────────────────────────

    async def get_active_watchlist(self, *, market: str | None = None) -> list[dict]:
        """Query all ACTIVE watchlist entries, ordered by composite score.

        Args:
            market: Optional market filter ("US" or "KR"). If None, returns all markets.

        Returns:
            List of dicts, best composite score first.
        """
        query = """
            SELECT ticker, added_date, last_screened,
                   quarterly_eps_growth, annual_eps_cagr, rs_rating,
                   institutional_holders, institutional_change_pct,
                   custom_composite_score, minervini_pass,
                   sector, industry, avg_daily_volume, market_cap,
                   status
            FROM watchlist
            WHERE status = 'ACTIVE'
        """
        if market:
            query += " AND market = ?"
            cursor = await self._db.conn.execute(query + " ORDER BY custom_composite_score DESC", (market,))
        else:
            cursor = await self._db.conn.execute(query + " ORDER BY custom_composite_score DESC")
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

    async def get_watchlist_tickers(self, *, market: str | None = None) -> list[str]:
        """Return just the ticker symbols from the active watchlist.

        Args:
            market: Optional market filter ("US" or "KR"). If None, returns all markets.

        Returns:
            List of ticker symbols.
        """
        query = """
            SELECT ticker FROM watchlist
            WHERE status = 'ACTIVE'
        """
        if market:
            query += " AND market = ?"
            cursor = await self._db.conn.execute(query + " ORDER BY custom_composite_score DESC", (market,))
        else:
            cursor = await self._db.conn.execute(query + " ORDER BY custom_composite_score DESC")
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
