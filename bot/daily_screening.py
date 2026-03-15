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
    EARNINGS_CALENDAR_LOOKBACK_DAYS,
    YFINANCE_BATCH_DELAY,
    YFINANCE_BATCH_SIZE,
)
from core.database import Database
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
                result["earnings_targets"] = 0
                result["stale_targets"] = 0
                result["fundamental_new_records"] = 0
                logger.info(
                    "daily_screening_kr_fundamentals_skipped",
                    market=market,
                    reason="DART handles KR fundamentals in screening step",
                )
            else:
                # 3a: Earnings Calendar — 최근 실적 발표 종목
                earnings_start = time.monotonic()
                earnings_cal = EarningsCalendar()

                try:
                    earnings_targets = await earnings_cal.get_update_targets(
                        tickers, days=EARNINGS_CALENDAR_LOOKBACK_DAYS
                    )
                except Exception:
                    logger.exception("daily_screening_earnings_calendar_error", market=market)
                    earnings_targets = []

                result["earnings_targets"] = len(earnings_targets)
                logger.info(
                    "daily_screening_earnings_targets",
                    targets=len(earnings_targets),
                    tickers_sample=earnings_targets[:10],
                    elapsed=f"{time.monotonic() - earnings_start:.1f}s",
                    market=market,
                )

                # 3b: needs_update() — DB에 최신 분기 데이터가 없는 종목 추가
                earnings_set = set(earnings_targets)
                stale_targets: list[str] = []

                for ticker in tickers:
                    if ticker in earnings_set:
                        continue
                    try:
                        if await fdm.needs_update(ticker, market=market):
                            stale_targets.append(ticker)
                    except Exception:
                        pass

                result["stale_targets"] = len(stale_targets)
                logger.info(
                    "daily_screening_stale_targets",
                    stale=len(stale_targets),
                    sample=stale_targets[:10],
                    market=market,
                )

                # ── Step 4: 재무 데이터 갱신 (earnings + stale) ────
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
