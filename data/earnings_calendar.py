"""
NASDAQ Earnings Calendar — 실적 발표 일정 조회.

NASDAQ 공개 API를 사용하여 특정 날짜에 실적을 발표한 종목을 조회한다.
이를 통해 재무 데이터를 incremental하게 갱신할 수 있다:
  - 매일 최근 N일간 실적 발표 종목만 파악
  - 해당 종목의 재무 데이터만 선택적으로 yfinance에서 다시 가져옴
  - 전체 유니버스(6,690+) 재무를 매일 갱신하는 비효율을 방지

API Endpoint:
    GET https://api.nasdaq.com/api/calendar/earnings?date=YYYY-MM-DD
    Headers: User-Agent: Mozilla/5.0 (필수 — 없으면 403)
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta

import structlog

from config.constants import EARNINGS_CALENDAR_LOOKBACK_DAYS

logger = structlog.get_logger(__name__)

# ── Constants ──────────────────────────────────────────────────
_BASE_URL = "https://api.nasdaq.com/api/calendar/earnings"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "Accept-Language": "en-US,en;q=0.9",
}
_REQUEST_TIMEOUT_SECONDS = 30


@dataclass(frozen=True)
class EarningsEntry:
    """단일 실적 발표 항목."""

    ticker: str
    name: str
    date: str  # YYYY-MM-DD
    eps_forecast: str | None
    eps_actual: str | None
    time: str | None  # "time-pre-market", "time-after-hours", "time-not-supplied"
    fiscal_quarter_ending: str | None  # e.g. "Dec/2025"
    market_cap: str | None


class EarningsCalendar:
    """NASDAQ Earnings Calendar API 래퍼.

    aiohttp를 사용하여 비동기로 실적 발표 일정을 조회한다.
    에러 발생 시 빈 리스트를 반환하며 절대 crash하지 않는다.
    """

    async def fetch_earnings_for_date(self, date: str) -> list[EarningsEntry]:
        """특정 날짜의 실적 발표 종목을 조회한다.

        Args:
            date: YYYY-MM-DD 형식의 날짜 문자열.

        Returns:
            EarningsEntry 리스트. API 실패 시 빈 리스트.
        """
        import aiohttp  # noqa: WPS433 — lazy import

        url = f"{_BASE_URL}?date={date}"
        entries: list[EarningsEntry] = []

        try:
            timeout = aiohttp.ClientTimeout(total=_REQUEST_TIMEOUT_SECONDS)
            async with aiohttp.ClientSession(
                headers=_HEADERS, timeout=timeout
            ) as session:
                async with session.get(url) as resp:
                    if resp.status != 200:
                        logger.warning(
                            "earnings_calendar_http_error",
                            date=date,
                            status=resp.status,
                        )
                        return entries

                    payload = await resp.json()

        except Exception:
            logger.warning(
                "earnings_calendar_request_failed",
                date=date,
                exc_info=True,
            )
            return entries

        # ── Parse response ───────────────────────────────────
        try:
            data = payload.get("data") or {}
            rows = data.get("rows") or []

            for row in rows:
                symbol = (row.get("symbol") or "").strip().upper()
                if not symbol:
                    continue

                # Symbol normalization: 일부 NASDAQ 심볼이 dot 표기 사용
                # (예: BRK.B) → 우리 시스템은 hyphen 표기 (BRK-B)
                symbol = symbol.replace(".", "-")

                entries.append(
                    EarningsEntry(
                        ticker=symbol,
                        name=(row.get("name") or "").strip(),
                        date=date,
                        eps_forecast=row.get("epsForecast"),
                        eps_actual=row.get("eps"),
                        time=row.get("time"),
                        fiscal_quarter_ending=row.get("fiscalQuarterEnding"),
                        market_cap=row.get("marketCap"),
                    )
                )

            logger.info(
                "earnings_calendar_fetched",
                date=date,
                count=len(entries),
            )

        except Exception:
            logger.warning(
                "earnings_calendar_parse_error",
                date=date,
                exc_info=True,
            )

        return entries

    async def fetch_recent_earnings(
        self, days: int = EARNINGS_CALENDAR_LOOKBACK_DAYS
    ) -> list[EarningsEntry]:
        """최근 N일간의 실적 발표 종목을 모두 조회한다.

        Args:
            days: 조회할 과거 일수 (기본값: EARNINGS_CALENDAR_LOOKBACK_DAYS).

        Returns:
            전체 기간의 EarningsEntry 리스트 (중복 없이).
        """
        today = datetime.now()
        all_entries: list[EarningsEntry] = []
        seen_tickers: set[str] = set()

        for offset in range(days):
            target_date = today - timedelta(days=offset)
            date_str = target_date.strftime("%Y-%m-%d")

            entries = await self.fetch_earnings_for_date(date_str)

            for entry in entries:
                if entry.ticker not in seen_tickers:
                    all_entries.append(entry)
                    seen_tickers.add(entry.ticker)

            # API rate limit 방지: 날짜 간 0.5초 대기
            if offset < days - 1:
                await asyncio.sleep(0.5)

        logger.info(
            "earnings_recent_fetched",
            days=days,
            unique_tickers=len(all_entries),
        )
        return all_entries

    async def get_update_targets(
        self,
        universe_tickers: list[str],
        days: int = EARNINGS_CALENDAR_LOOKBACK_DAYS,
    ) -> list[str]:
        """유니버스 중 최근 실적 발표한 종목만 필터링한다.

        재무 데이터 갱신이 필요한 종목만 반환한다:
          1. 최근 N일간 실적 발표한 전체 종목 조회
          2. 우리 유니버스에 포함된 종목만 필터
          3. 해당 종목의 ticker 리스트 반환

        Args:
            universe_tickers: 현재 유니버스 종목 리스트.
            days: 조회할 과거 일수.

        Returns:
            갱신이 필요한 종목의 ticker 리스트.
        """
        earnings = await self.fetch_recent_earnings(days=days)
        earnings_tickers = {e.ticker for e in earnings}

        universe_set = set(universe_tickers)
        targets = sorted(earnings_tickers & universe_set)

        logger.info(
            "earnings_update_targets",
            total_earnings=len(earnings_tickers),
            in_universe=len(targets),
            universe_size=len(universe_set),
        )
        return targets
