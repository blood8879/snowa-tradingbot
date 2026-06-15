"""
Daily CANSLIM Screening Pipeline.

KST 20:00에 실행되어 pre_market(22:00)보다 2시간 전에 완료한다.

Pipeline:
  1. 유니버스 로드 (6,690+ 종목)
  2. 전체 유니버스 가격 갱신 (yfinance bulk, period='5d', incremental)
  3. Earnings Calendar 조회 → 해당 종목만 재무 데이터 갱신
  4. WatchlistManager.run_full_screening() 실행
     - RS Rating → CANSLIM → Minervini → Composite → DB 저장

소요 시간 예상:
  - 가격 갱신: ~10분 (6,690종목 / 50배치 × 2초 딜레이)
  - Earnings 조회: ~2초
  - 재무 갱신: ~2분 (보통 50~150종목만 해당)
  - 스크리닝: ~5분
  - 총: ~20분 (pre_market 2시간 전 여유)
"""

from __future__ import annotations

import time

import structlog

from config.constants import (
    EARNINGS_CALENDAR_REFETCH_DAYS,
    YFINANCE_BATCH_DELAY,
    YFINANCE_BATCH_SIZE,
)
from config.settings import get_settings
from core.database import Database
from data.ai_stock_report import StockReportError, StockReportService
from data.ai_usage_status import AIUsageStatusService
from data.earnings_calendar import EarningsCalendar
from data.fundamental_data import FundamentalDataManager
from data.price_cache import PriceCache
from data.universe import UniverseManager
from data.universe_kr import KRUniverseManager
from screening.watchlist_manager import WatchlistManager

logger = structlog.get_logger(__name__)


class DailyScreeningPipeline:
    """매일 CANSLIM 스크리닝 파이프라인 오케스트레이터.

    TradingBot의 스케줄러에서 KST 20:00에 호출된다.
    각 단계는 독립적으로 에러를 처리하며,
    가격 갱신/재무 갱신 실패가 전체 스크리닝을 중단시키지 않는다.
    """

    def __init__(self, db: Database) -> None:
        self._db = db

    async def run(self, price_period: str = "5d", *, market: str = "US") -> dict:
        """전체 파이프라인 실행.

        Args:
            price_period: yfinance period for US market (ignored for KR).
            market: Market identifier ("US" or "KR").

        Returns:
            파이프라인 결과 요약 dict:
              - universe_count: 유니버스 종목 수
              - price_new_records: 새로 저장된 가격 레코드 수
              - earnings_targets: 재무 갱신 대상 종목 수
              - fundamental_new_records: 새로 저장된 재무 레코드 수
              - watchlist_count: 최종 워치리스트 종목 수
              - elapsed: 총 소요 시간 (초)
        """
        overall_start = time.monotonic()
        result: dict = {}

        logger.info("daily_screening_pipeline_start", market=market)

        try:
            # ── Step 1: 유니버스 로드 ────────────────────────
            if market == "KR":
                universe_mgr = KRUniverseManager()
                await universe_mgr.load_universe()
                tradeable = universe_mgr.filter_tradeable()
                tickers = sorted(s.ticker for s in tradeable)
            else:
                universe_mgr = UniverseManager()
                await universe_mgr.load_universe()
                tradeable = universe_mgr.filter_tradeable()
                tickers = sorted(s.ticker for s in tradeable)
            result["universe_count"] = len(tickers)

            logger.info("daily_screening_universe_loaded", count=len(tickers), market=market)

            # ── Step 2: 전체 유니버스 가격 갱신 ──────────────
            # US: period='5d'로 최근 5거래일만 가져와서 INSERT OR IGNORE
            # KR: pykrx로 최근 300일 가져오기
            price_start = time.monotonic()
            price_cache = PriceCache(self._db)

            if market == "KR":
                try:
                    price_new = await price_cache.bulk_load_from_pykrx(
                        tickers,
                        days=300,
                    )
                except Exception:
                    logger.exception("daily_screening_kr_price_refresh_error", market=market)
                    price_new = 0
            else:
                try:
                    price_new = await price_cache.bulk_load_from_yfinance(
                        tickers,
                        period=price_period,
                        batch_size=YFINANCE_BATCH_SIZE,
                        delay=YFINANCE_BATCH_DELAY,
                    )
                except Exception:
                    logger.exception("daily_screening_price_refresh_error", market=market)
                    price_new = 0

            result["price_new_records"] = price_new
            logger.info(
                "daily_screening_prices_refreshed",
                new_records=price_new,
                elapsed=f"{time.monotonic() - price_start:.1f}s",
                market=market,
            )

            # ── Step 3: 재무 갱신 대상 파악 ───────────────────
            # US: Earnings Calendar(최근 N일 실적 발표) + needs_update() 체크
            # KR: DART는 watchlist_manager Step 3.5에서 처리하므로 스킵
            fund_start = time.monotonic()
            fdm = FundamentalDataManager(self._db)

            if market == "KR":
                # KR: 기존 watchlist 종목의 DART 재무데이터 선제 갱신
                import os
                DART_API_KEY = os.environ.get("DART_API_KEY", "a9a83a37044c92dda80876d98c108d112c89136b")

                result["earnings_targets"] = 0
                stale_kr: list[str] = []

                if DART_API_KEY:
                    cursor = await self._db.conn.execute(
                        "SELECT ticker FROM watchlist WHERE status = 'ACTIVE' AND market = ?",
                        (market,),
                    )
                    wl_rows = await cursor.fetchall()
                    wl_tickers = [row[0] for row in wl_rows]

                    for ticker in wl_tickers:
                        try:
                            if await fdm.needs_update(ticker, market=market):
                                stale_kr.append(ticker)
                        except Exception:
                            stale_kr.append(ticker)

                    result["stale_targets"] = len(stale_kr)

                    if stale_kr:
                        from data.dart_financial import DartFinancialFetcher

                        dart = DartFinancialFetcher(
                            api_key=DART_API_KEY,
                            cache_dir=str(self._db.db_path.parent) if hasattr(self._db, "db_path") else "data",
                        )
                        await dart.load_corp_codes()
                        dart_new = await dart.bulk_fetch_and_store(stale_kr, self._db)
                        result["fundamental_new_records"] = dart_new
                    else:
                        result["fundamental_new_records"] = 0

                    logger.info(
                        "daily_screening_kr_fundamentals_refreshed",
                        market=market,
                        watchlist_count=len(wl_tickers),
                        stale=len(stale_kr),
                        new_records=result["fundamental_new_records"],
                        elapsed=f"{time.monotonic() - fund_start:.1f}s",
                    )
                else:
                    result["stale_targets"] = 0
                    result["fundamental_new_records"] = 0
                    logger.info(
                        "daily_screening_kr_fundamentals_skipped",
                        market=market,
                        reason="DART_API_KEY not configured",
                    )
            else:
                # 3a: Earnings Calendar — 최근 N일(REFETCH 윈도우) 실적 발표 종목.
                # yfinance 재무제표는 발표일보다 늦게 채워지므로 3일이 아니라
                # 더 넓은 윈도우로 잡아 직전 fetch가 놓친 신규 분기를 흡수한다.
                earnings_start = time.monotonic()
                earnings_cal = EarningsCalendar()

                try:
                    earnings_targets = await earnings_cal.get_update_targets(
                        tickers, days=EARNINGS_CALENDAR_REFETCH_DAYS
                    )
                except Exception:
                    logger.exception("daily_screening_earnings_calendar_error", market=market)
                    earnings_targets = []

                result["earnings_targets"] = len(earnings_targets)
                logger.info(
                    "daily_screening_earnings_targets",
                    targets=len(earnings_targets),
                    tickers_sample=earnings_targets[:10],
                    refetch_days=EARNINGS_CALENDAR_REFETCH_DAYS,
                    elapsed=f"{time.monotonic() - earnings_start:.1f}s",
                    market=market,
                )

                # 3b: 우선 갱신 대상 — ACTIVE 워치리스트 ∪ 보유 포지션.
                # 이 종목들은 스크리닝/매매가 의존하는 핵심이므로 stale cap에서
                # 면제(항상 갱신)한다. 유니버스에서 빠졌더라도 갱신한다.
                earnings_set = set(earnings_targets)
                priority_candidates = await self._get_priority_fundamental_tickers(market)

                priority_stale: list[str] = []
                for ticker in priority_candidates:
                    if ticker in earnings_set:
                        continue
                    try:
                        if await fdm.needs_update(ticker, market=market):
                            priority_stale.append(ticker)
                    except Exception:
                        pass
                priority_set = set(priority_stale)

                # 3c: 유니버스 일반 stale — needs_update() True인 나머지 종목.
                # cap은 이 일반 stale에만 적용한다(우선 대상은 면제).
                generic_stale: list[str] = []
                for ticker in tickers:
                    if ticker in earnings_set or ticker in priority_set:
                        continue
                    try:
                        if await fdm.needs_update(ticker, market=market):
                            generic_stale.append(ticker)
                    except Exception:
                        pass

                max_stale_targets = get_settings().screening_max_stale_fundamental_targets
                if max_stale_targets < 0:
                    max_stale_targets = 0

                if len(generic_stale) > max_stale_targets:
                    # Oldest-first rotation: cap을 알파벳 앞쪽에 고정 적용하면
                    # 뒤쪽 종목은 매일 잘려나가 영영 갱신되지 않는다.
                    # 가장 오래 방치된(또는 재무가 아예 없는) 종목을 우선해
                    # cap이 전체 유니버스를 시간에 걸쳐 순환하도록 한다.
                    last_upd = await self._fundamental_last_updated_map()
                    generic_stale.sort(key=lambda t: last_upd.get(t, ""))
                    logger.warning(
                        "daily_screening_stale_targets_capped",
                        original=len(generic_stale),
                        capped=max_stale_targets,
                        priority_exempt=len(priority_stale),
                        oldest_sample=generic_stale[:5],
                        market=market,
                    )
                    generic_stale = generic_stale[:max_stale_targets]

                stale_targets = priority_stale + generic_stale
                result["stale_targets"] = len(stale_targets)
                result["priority_stale_targets"] = len(priority_stale)
                logger.info(
                    "daily_screening_stale_targets",
                    stale=len(stale_targets),
                    priority=len(priority_stale),
                    generic=len(generic_stale),
                    sample=stale_targets[:10],
                    market=market,
                )

                # ── Step 4: 재무 데이터 갱신 (earnings + priority + generic) ────
                all_targets = earnings_targets + stale_targets

                if all_targets:
                    try:
                        fund_new = await fdm.bulk_fetch(
                            all_targets,
                            batch_size=YFINANCE_BATCH_SIZE,
                            delay=YFINANCE_BATCH_DELAY,
                            market=market,
                        )
                    except Exception:
                        logger.exception("daily_screening_fundamentals_refresh_error", market=market)
                        fund_new = 0

                    result["fundamental_new_records"] = fund_new
                    logger.info(
                        "daily_screening_fundamentals_refreshed",
                        tickers=len(all_targets),
                        new_records=fund_new,
                        elapsed=f"{time.monotonic() - fund_start:.1f}s",
                        market=market,
                    )
                else:
                    result["fundamental_new_records"] = 0
                    logger.info("daily_screening_no_fund_targets", market=market)

            # ── Step 5: CANSLIM 스크리닝 실행 ────────────────
            screening_start = time.monotonic()
            watchlist_mgr = WatchlistManager(self._db)

            try:
                entries = await watchlist_mgr.run_full_screening(tickers=tickers, market=market)
            except Exception:
                logger.exception("daily_screening_screening_error", market=market)
                entries = []

            result["watchlist_count"] = len(entries)
            logger.info(
                "daily_screening_screening_complete",
                watchlist=len(entries),
                elapsed=f"{time.monotonic() - screening_start:.1f}s",
                market=market,
            )

            # ── Step 6: LLM report pre-generation ─────────────
            # Cached by latest financial period/hash, so removed/re-added names
            # do not incur another API call unless financial data changed.
            llm_start = time.monotonic()
            settings = get_settings()
            llm_summary = await self._generate_ai_reports(entries, market=market)
            result.update(llm_summary)
            if settings.ai_report_filter_watchlist_to_pass:
                ai_filter_summary = await self._filter_watchlist_to_ai_pass(
                    entries,
                    pass_tickers=llm_summary["ai_report_pass_tickers"],
                    verdicts=llm_summary["ai_report_verdicts"],
                    market=market,
                )
                result.update(ai_filter_summary)
                result["watchlist_count_before_ai_filter"] = result["watchlist_count"]
                result["watchlist_count"] = ai_filter_summary["ai_report_pass_count"]
            logger.info(
                "daily_screening_ai_reports_complete",
                generated=llm_summary["ai_reports_generated"],
                cache_hits=llm_summary["ai_report_cache_hits"],
                skipped=llm_summary["ai_reports_skipped"],
                failed=llm_summary["ai_reports_failed"],
                pass_count=llm_summary["ai_report_pass_count"],
                filtered=(
                    result.get("ai_report_watchlist_removed", 0)
                    if settings.ai_report_filter_watchlist_to_pass
                    else 0
                ),
                elapsed=f"{time.monotonic() - llm_start:.1f}s",
                market=market,
            )

        except Exception:
            logger.exception("daily_screening_pipeline_error", market=market)
            raise

        elapsed = time.monotonic() - overall_start
        result["elapsed"] = round(elapsed, 1)

        logger.info(
            "daily_screening_pipeline_complete",
            universe=result.get("universe_count", 0),
            price_records=result.get("price_new_records", 0),
            earnings_targets=result.get("earnings_targets", 0),
            fundamental_records=result.get("fundamental_new_records", 0),
            watchlist=result.get("watchlist_count", 0),
            elapsed=f"{elapsed:.1f}s",
            market=market,
        )

        return result

    async def _get_priority_fundamental_tickers(self, market: str) -> list[str]:
        """재무 갱신에서 cap 면제로 항상 갱신해야 할 핵심 종목.

        ACTIVE 워치리스트 ∪ OPEN 포지션. 스크리닝과 매매가 이 종목들의
        최신 분기 재무에 직접 의존하므로, 유니버스 stale cap에 의해
        누락되면 옛 분기 데이터로 매매/리포트가 고착된다.
        """
        tickers: set[str] = set()
        try:
            cursor = await self._db.conn.execute(
                "SELECT ticker FROM watchlist WHERE status = 'ACTIVE' AND market = ?",
                (market,),
            )
            tickers.update(row[0] for row in await cursor.fetchall())
        except Exception:
            logger.exception("daily_screening_priority_watchlist_query_failed", market=market)

        try:
            cursor = await self._db.conn.execute(
                "SELECT ticker FROM positions WHERE status = 'OPEN' AND market = ?",
                (market,),
            )
            tickers.update(row[0] for row in await cursor.fetchall())
        except Exception:
            logger.exception("daily_screening_priority_positions_query_failed", market=market)

        return sorted(tickers)

    async def _fundamental_last_updated_map(self) -> dict[str, str]:
        """ticker → 재무 마지막 갱신 시각(없으면 빈 문자열). 단일 쿼리.

        generic stale 종목을 '오래 방치된 순'으로 정렬해 cap이 전체
        유니버스를 순환하도록 하는 데 쓴다.
        """
        result: dict[str, str] = {}
        try:
            cursor = await self._db.conn.execute(
                "SELECT ticker, MAX(updated_at) FROM fundamentals GROUP BY ticker"
            )
            for row in await cursor.fetchall():
                result[row[0]] = row[1] or ""
        except Exception:
            logger.exception("daily_screening_last_updated_map_failed")
        return result

    async def _generate_ai_reports(self, entries: list[dict], *, market: str) -> dict:
        settings = get_settings()
        summary = {
            "ai_reports_generated": 0,
            "ai_report_cache_hits": 0,
            "ai_reports_skipped": 0,
            "ai_reports_failed": 0,
            "ai_report_pass_count": 0,
            "ai_report_pass_tickers": [],
            "ai_report_verdicts": {},
        }
        if not settings.ai_report_auto_generate:
            summary["ai_reports_skipped"] = len(entries)
            return summary

        try:
            usage_status = await AIUsageStatusService(settings).get_status()
        except Exception as exc:
            summary["ai_reports_skipped"] = len(entries)
            logger.warning(
                "daily_screening_ai_reports_skipped_usage_status_failed",
                error=str(exc),
                market=market,
            )
            return summary
        if not usage_status.available:
            summary["ai_reports_skipped"] = len(entries)
            logger.warning(
                "daily_screening_ai_reports_skipped_provider_unavailable",
                status=usage_status.status,
                message=usage_status.message,
                market=market,
            )
            return summary

        service = StockReportService(self._db, settings)
        for entry in entries:
            ticker = entry["ticker"]
            try:
                report_result = await service.generate_report(ticker, market)
            except StockReportError as exc:
                summary["ai_reports_failed"] += 1
                logger.warning(
                    "daily_screening_ai_report_failed",
                    ticker=ticker,
                    market=market,
                    error=str(exc),
                )
                continue
            except Exception:
                summary["ai_reports_failed"] += 1
                logger.exception(
                    "daily_screening_ai_report_unexpected_error",
                    ticker=ticker,
                    market=market,
                )
                continue

            if report_result.get("cache_hit"):
                summary["ai_report_cache_hits"] += 1
            else:
                summary["ai_reports_generated"] += 1

            report = report_result.get("report") or {}
            verdict = report.get("verdict")
            if verdict:
                summary["ai_report_verdicts"][ticker] = verdict
            if verdict == "PASS":
                summary["ai_report_pass_tickers"].append(ticker)
                summary["ai_report_pass_count"] += 1

        return summary

    async def _filter_watchlist_to_ai_pass(
        self,
        entries: list[dict],
        *,
        pass_tickers: list[str],
        verdicts: dict[str, str],
        market: str,
    ) -> dict:
        """Keep only LLM PASS verdicts in the active watchlist."""
        if not entries:
            return {
                "ai_report_watchlist_removed": 0,
                "ai_report_pass_count": 0,
            }

        conn = self._db.conn
        now = time.strftime("%Y-%m-%dT%H:%M:%S")
        entry_tickers = {entry["ticker"] for entry in entries}
        pass_set = set(pass_tickers)
        remove_tickers = sorted(entry_tickers - pass_set)

        if not remove_tickers:
            return {
                "ai_report_watchlist_removed": 0,
                "ai_report_pass_count": len(pass_set),
            }

        placeholders = ",".join("?" for _ in remove_tickers)
        await conn.execute(
            f"""
            UPDATE watchlist
            SET status = 'REMOVED'
            WHERE status = 'ACTIVE'
              AND market = ?
              AND ticker IN ({placeholders})
            """,
            (market, *remove_tickers),
        )

        rows_cursor = await conn.execute(
            f"""
            SELECT ticker, name, quarterly_eps_growth, annual_eps_cagr,
                   rs_rating, custom_composite_score, minervini_pass
            FROM watchlist
            WHERE market = ? AND ticker IN ({placeholders})
            """,
            (market, *remove_tickers),
        )
        rows = await rows_cursor.fetchall()

        for row in rows:
            ticker = row[0]
            verdict = verdicts.get(ticker, "NO_CURRENT_PASS_REPORT")
            reason = f"LLM 리포트 PASS 미충족({verdict})"
            await conn.execute(
                """INSERT INTO watchlist_history
                   (ticker, name, market, action, reason, quarterly_eps_growth, annual_eps_cagr,
                    rs_rating, composite_score, minervini_pass, recorded_at)
                   VALUES (?, ?, ?, 'REMOVED', ?, ?, ?, ?, ?, ?, ?)""",
                (
                    ticker,
                    row[1],
                    market,
                    reason,
                    row[2],
                    row[3],
                    row[4],
                    row[5],
                    row[6],
                    now,
                ),
            )

        await conn.commit()
        logger.info(
            "daily_screening_ai_watchlist_filtered",
            market=market,
            pass_count=len(pass_set),
            removed=len(remove_tickers),
            removed_sample=remove_tickers[:10],
        )
        return {
            "ai_report_watchlist_removed": len(remove_tickers),
            "ai_report_pass_count": len(pass_set),
        }
