"""
KOSPI + KOSDAQ stock universe manager.

Downloads the full list of listed stocks from Naver Finance API (primary)
or pykrx (fallback), and maintains a local CSV cache.
Used by screening and data-loading modules to enumerate tradeable Korean tickers.

Data source (priority order):
  1. Naver Finance mobile API - https://m.stock.naver.com/api/stocks/
  2. pykrx.stock (fallback) - https://github.com/sharebook-kr/pykrx
"""

from __future__ import annotations

import asyncio
import csv
import math
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

import requests
import structlog

logger = structlog.get_logger(__name__)

# ============================================================
# Cache Configuration
# ============================================================

# Cache freshness threshold (7 days in seconds)
_CACHE_MAX_AGE_SECONDS = 7 * 24 * 60 * 60

# Minimum market cap (100B KRW = 1000억원)
_MIN_MARKET_CAP = 100_000_000_000


# ============================================================
# Data Model
# ============================================================

@dataclass(frozen=True)
class KRUniverseStock:
    """A single stock in the KOSPI/KOSDAQ universe."""

    ticker: str         # 6-digit code (e.g., "005930")
    name: str           # Korean name (e.g., "삼성전자")
    exchange: str       # "KOSPI" or "KOSDAQ"
    market_cap: float = 0.0  # 시가총액 (원)
    is_etf: bool = False


# ============================================================
# Universe Manager
# ============================================================

class KRUniverseManager:
    """KOSPI + KOSDAQ 전 종목 유니버스 관리."""

    def __init__(self, cache_dir: str = "data") -> None:
        self._cache_dir = Path(cache_dir)
        self._stocks: dict[str, KRUniverseStock] = {}
        self._loaded: bool = False

    # ── Public API ───────────────────────────────────────────

    async def load_universe(self, force_refresh: bool = False) -> int:
        """
        Load the full stock universe.

        Checks CSV cache first; downloads from pykrx if stale or missing.

        Returns:
            Total number of loaded stocks.
        """
        # Try cache first (must be fresh AND non-empty)
        if not force_refresh and self._is_cache_fresh():
            if self._load_cache() and len(self._stocks) > 0:
                self._loaded = True
                logger.info(
                    "kr_universe_loaded",
                    count=len(self._stocks),
                    source="cache",
                )
                return len(self._stocks)
            # Cache exists but is empty → force refresh from pykrx
            logger.warning(
                "kr_universe_cache_empty",
                msg="캐시 파일이 비어있어 pykrx에서 다시 다운로드합니다.",
            )

        # Download fresh data (Naver first, pykrx fallback)
        self._stocks.clear()

        try:
            await self._download_from_naver()
        except Exception as exc:
            logger.warning(
                "kr_universe_naver_failed",
                error=str(exc),
                msg="네이버 금융 API 실패. pykrx로 폴백합니다.",
            )
            try:
                await self._download_from_pykrx()
            except Exception as exc2:
                logger.error(
                    "kr_universe_download_failed",
                    error=str(exc2),
                    msg="pykrx도 실패. 캐시를 사용합니다.",
                )
                self._load_cache()
                self._loaded = True
                return len(self._stocks)

        if len(self._stocks) == 0:
            logger.error(
                "kr_universe_all_sources_empty",
                msg="모든 소스에서 종목이 0건입니다.",
            )

        self._save_cache()
        self._loaded = True

        logger.info(
            "kr_universe_loaded",
            count=len(self._stocks),
            source="pykrx",
        )
        return len(self._stocks)

    async def get_all_tickers(self) -> list[str]:
        """Return sorted list of all ticker symbols."""
        if not self._loaded:
            await self.load_universe()
        return sorted(self._stocks.keys())

    def get_stock(self, ticker: str) -> KRUniverseStock | None:
        """Return KRUniverseStock for given ticker, or None if not found."""
        return self._stocks.get(ticker)

    def get_exchange(self, ticker: str) -> str:
        """Return exchange code for ticker. Defaults to 'KOSPI' if not found."""
        stock = self._stocks.get(ticker)
        return stock.exchange if stock else "KOSPI"

    def filter_tradeable(self) -> list[KRUniverseStock]:
        """Return non-ETF stocks only."""
        return [s for s in self._stocks.values() if not s.is_etf]

    # ── Download from Naver Finance ──────────────────────────

    _NAVER_API_URL = "https://m.stock.naver.com/api/stocks/marketValue/{market}?page={page}&pageSize={page_size}"
    _NAVER_PAGE_SIZE = 100
    _NAVER_HEADERS = {"User-Agent": "Mozilla/5.0"}

    async def _download_from_naver(self) -> None:
        """
        Fetch all stocks from Naver Finance mobile API for KOSPI and KOSDAQ.

        Uses run_in_executor to avoid blocking on synchronous HTTP calls.
        """
        loop = asyncio.get_event_loop()

        for market in ["KOSPI", "KOSDAQ"]:
            try:
                stocks = await loop.run_in_executor(
                    None, self._fetch_naver_market, market
                )
                added = 0
                for s in stocks:
                    if self._should_exclude(s["ticker"], s["name"]):
                        continue
                    is_etf = self._is_etf(s["name"])
                    self._stocks[s["ticker"]] = KRUniverseStock(
                        ticker=s["ticker"],
                        name=s["name"],
                        exchange=market,
                        market_cap=s.get("market_cap", 0.0),
                        is_etf=is_etf,
                    )
                    added += 1

                logger.info(
                    "kr_universe_naver_loaded",
                    market=market,
                    fetched=len(stocks),
                    added=added,
                )
            except Exception as exc:
                logger.error(
                    "kr_universe_naver_market_failed",
                    market=market,
                    error=str(exc),
                )
                raise

    def _fetch_naver_market(self, market: str) -> list[dict]:
        """Synchronous: paginate through Naver Finance API for one market."""
        all_stocks: list[dict] = []

        # First request to get totalCount
        url = self._NAVER_API_URL.format(
            market=market, page=1, page_size=self._NAVER_PAGE_SIZE
        )
        resp = requests.get(url, headers=self._NAVER_HEADERS, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        total = data.get("totalCount", 0)
        if total == 0:
            return []

        total_pages = math.ceil(total / self._NAVER_PAGE_SIZE)

        # Parse first page
        all_stocks.extend(self._parse_naver_stocks(data.get("stocks", [])))

        # Fetch remaining pages
        for page in range(2, total_pages + 1):
            url = self._NAVER_API_URL.format(
                market=market, page=page, page_size=self._NAVER_PAGE_SIZE
            )
            resp = requests.get(url, headers=self._NAVER_HEADERS, timeout=15)
            resp.raise_for_status()
            page_data = resp.json()
            all_stocks.extend(self._parse_naver_stocks(page_data.get("stocks", [])))

        return all_stocks

    @staticmethod
    def _parse_naver_stocks(stocks: list[dict]) -> list[dict]:
        """Parse Naver Finance API stock entries."""
        result: list[dict] = []
        for s in stocks:
            ticker = s.get("itemCode", "")
            name = s.get("stockName", "")
            if not ticker or not name:
                continue

            # Parse market_cap (e.g., "12,816,016" in 억원 units)
            market_cap_str = s.get("marketValue", "0")
            try:
                market_cap = float(market_cap_str.replace(",", "")) * 1_0000_0000  # 억원 → 원
            except (ValueError, AttributeError):
                market_cap = 0.0

            result.append({
                "ticker": ticker,
                "name": name,
                "market_cap": market_cap,
            })
        return result

    # ── Download from pykrx (fallback) ───────────────────────

    async def _download_from_pykrx(self) -> None:
        """
        Fetch all stocks from pykrx for KOSPI and KOSDAQ.

        Uses run_in_executor to avoid blocking on synchronous pykrx calls.
        """
        loop = asyncio.get_event_loop()

        # Get valid trading date (today, or previous business day if market is closed)
        date_str = await loop.run_in_executor(None, self._get_valid_date)

        for market in ["KOSPI", "KOSDAQ"]:
            try:
                tickers = await loop.run_in_executor(
                    None, self._get_ticker_list, date_str, market
                )

                added = 0
                for ticker in tickers:
                    try:
                        # Get stock name
                        name = await loop.run_in_executor(
                            None, self._get_ticker_name, ticker
                        )

                        # Filter out unwanted stocks
                        if self._should_exclude(ticker, name):
                            continue

                        # Detect ETF
                        is_etf = self._is_etf(name)

                        self._stocks[ticker] = KRUniverseStock(
                            ticker=ticker,
                            name=name,
                            exchange=market,
                            market_cap=0.0,  # Can add market cap fetching later if needed
                            is_etf=is_etf,
                        )
                        added += 1

                    except Exception as exc:
                        logger.debug(
                            "kr_universe_ticker_failed",
                            ticker=ticker,
                            error=str(exc),
                        )
                        continue

                logger.info(
                    "kr_universe_market_loaded",
                    market=market,
                    fetched=len(tickers),
                    added=added,
                )

            except Exception as exc:
                logger.error(
                    "kr_universe_market_failed",
                    market=market,
                    error=str(exc),
                )
                # Continue with other market even if one fails

    def _get_valid_date(self) -> str:
        """
        Get a valid trading date string (YYYYMMDD).

        Tries today, then walks back up to 7 days to find a non-holiday.
        """
        try:
            from pykrx import stock as pykrx_stock
        except ImportError:
            logger.error("pykrx_not_installed", msg="pykrx 라이브러리가 설치되지 않았습니다.")
            raise

        # Try today and previous 7 days
        for i in range(8):
            date = datetime.now() - timedelta(days=i)
            date_str = date.strftime("%Y%m%d")

            try:
                # Test if this date has data by trying to fetch KOSPI tickers
                tickers = pykrx_stock.get_market_ticker_list(date_str, market="KOSPI")
                if tickers and len(tickers) > 0:
                    logger.debug("kr_universe_valid_date", date=date_str)
                    return date_str
            except Exception:
                continue

        # Fallback to today if no valid date found
        fallback = datetime.now().strftime("%Y%m%d")
        logger.warning(
            "kr_universe_date_fallback",
            date=fallback,
            msg="유효한 거래일을 찾지 못해 오늘 날짜를 사용합니다.",
        )
        return fallback

    def _get_ticker_list(self, date_str: str, market: str) -> list[str]:
        """Synchronous wrapper for pykrx.stock.get_market_ticker_list()."""
        try:
            from pykrx import stock as pykrx_stock
        except ImportError:
            logger.error("pykrx_not_installed", msg="pykrx 라이브러리가 설치되지 않았습니다.")
            return []

        return pykrx_stock.get_market_ticker_list(date_str, market=market)

    def _get_ticker_name(self, ticker: str) -> str:
        """Synchronous wrapper for pykrx.stock.get_market_ticker_name()."""
        try:
            from pykrx import stock as pykrx_stock
        except ImportError:
            return ""

        return pykrx_stock.get_market_ticker_name(ticker)

    # ── Filtering Logic ──────────────────────────────────────

    def _should_exclude(self, ticker: str, name: str) -> bool:
        """
        Return True if stock should be excluded from universe.

        Exclusion rules:
        - ETN (name contains "ETN")
        - SPAC (name contains "스팩" or "SPAC")
        - Preferred shares (name ends with "우", "2우", "3우" etc.)
        """
        if not name:
            return True

        name_lower = name.lower()

        # Exclude ETN
        if "etn" in name_lower:
            return True

        # Exclude SPAC
        if "스팩" in name or "spac" in name_lower:
            return True

        # Exclude preferred shares (우선주)
        # Common patterns: "삼성전자우", "현대차2우", "SK텔레콤3우"
        if name.endswith("우") or any(name.endswith(f"{i}우") for i in range(1, 10)):
            return True

        return False

    def _is_etf(self, name: str) -> bool:
        """Return True if stock is an ETF based on name."""
        if not name:
            return False

        name_lower = name.lower()
        return "etf" in name_lower or "상장지수" in name

    # ── Cache Management ─────────────────────────────────────

    @property
    def _cache_path(self) -> Path:
        """Path to the CSV cache file."""
        return self._cache_dir / "universe_kr_cache.csv"

    def _save_cache(self) -> None:
        """Write all stocks to CSV: ticker,name,exchange,market_cap,is_etf."""
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        with open(self._cache_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["ticker", "name", "exchange", "market_cap", "is_etf"])
            for stock in self._stocks.values():
                writer.writerow([
                    stock.ticker,
                    stock.name,
                    stock.exchange,
                    str(stock.market_cap),
                    "Y" if stock.is_etf else "N",
                ])

    def _load_cache(self) -> bool:
        """
        Read CSV cache and populate _stocks.

        Returns:
            True if cache was successfully loaded.
        """
        try:
            with open(self._cache_path, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                self._stocks.clear()
                for row in reader:
                    ticker = row["ticker"]
                    self._stocks[ticker] = KRUniverseStock(
                        ticker=ticker,
                        name=row["name"],
                        exchange=row["exchange"],
                        market_cap=float(row.get("market_cap", 0)),
                        is_etf=row["is_etf"] == "Y",
                    )
            return True
        except (FileNotFoundError, KeyError, ValueError, csv.Error):
            return False

    def _is_cache_fresh(self) -> bool:
        """Return True if cache file exists and mtime is within 7 days."""
        path = self._cache_path
        if not path.exists():
            return False
        age = time.time() - path.stat().st_mtime
        return age < _CACHE_MAX_AGE_SECONDS
