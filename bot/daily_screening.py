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

    async def run(self) -> dict:
        """전체 파이프라인 실행.

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

        logger.info("daily_screening_pipeline_start")

        try:
            # ── Step 1: 유니버스 로드 ────────────────────────
            universe_mgr = UniverseManager()
            await universe_mgr.load_universe()
            tradeable = universe_mgr.filter_tradeable()
            tickers = sorted(s.ticker for s in tradeable)
            result["universe_count"] = len(tickers)

            logger.info("daily_screening_universe_loaded", count=len(tickers))

            # ── Step 2: 전체 유니버스 가격 갱신 ──────────────
            # period='5d'로 최근 5거래일만 가져와서 INSERT OR IGNORE
            price_start = time.monotonic()
            price_cache = PriceCache(self._db)

            try:
                price_new = await price_cache.bulk_load_from_yfinance(
                    tickers,
                    period="5d",
                    batch_size=YFINANCE_BATCH_SIZE,
                    delay=YFINANCE_BATCH_DELAY,
                )
            except Exception:
                logger.exception("daily_screening_price_refresh_error")
                price_new = 0

            result["price_new_records"] = price_new
            logger.info(
                "daily_screening_prices_refreshed",
                new_records=price_new,
                elapsed=f"{time.monotonic() - price_start:.1f}s",
            )

            # ── Step 3: Earnings Calendar → 재무 갱신 대상 파악 ─
            earnings_start = time.monotonic()
            earnings_cal = EarningsCalendar()

            try:
                earnings_targets = await earnings_cal.get_update_targets(
                    tickers, days=EARNINGS_CALENDAR_LOOKBACK_DAYS
                )
            except Exception:
                logger.exception("daily_screening_earnings_calendar_error")
                earnings_targets = []

            result["earnings_targets"] = len(earnings_targets)
            logger.info(
                "daily_screening_earnings_targets",
                targets=len(earnings_targets),
                tickers_sample=earnings_targets[:10],
                elapsed=f"{time.monotonic() - earnings_start:.1f}s",
            )

            # ── Step 4: 해당 종목만 재무 데이터 갱신 ─────────
            if earnings_targets:
                fund_start = time.monotonic()
                fdm = FundamentalDataManager(self._db)

                try:
                    fund_new = await fdm.bulk_fetch(
                        earnings_targets,
                        batch_size=YFINANCE_BATCH_SIZE,
                        delay=YFINANCE_BATCH_DELAY,
                    )
                except Exception:
                    logger.exception("daily_screening_fundamentals_refresh_error")
                    fund_new = 0

                result["fundamental_new_records"] = fund_new
                logger.info(
                    "daily_screening_fundamentals_refreshed",
                    tickers=len(earnings_targets),
                    new_records=fund_new,
                    elapsed=f"{time.monotonic() - fund_start:.1f}s",
                )
            else:
                result["fundamental_new_records"] = 0
                logger.info("daily_screening_no_earnings_targets")

            # ── Step 5: CANSLIM 스크리닝 실행 ────────────────
            screening_start = time.monotonic()
            watchlist_mgr = WatchlistManager(self._db)

            try:
                entries = await watchlist_mgr.run_full_screening(tickers=tickers)
            except Exception:
                logger.exception("daily_screening_screening_error")
                entries = []

            result["watchlist_count"] = len(entries)
            logger.info(
                "daily_screening_screening_complete",
                watchlist=len(entries),
                elapsed=f"{time.monotonic() - screening_start:.1f}s",
            )

        except Exception:
            logger.exception("daily_screening_pipeline_error")
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
        )

        return result
