"""
NYSE + NASDAQ stock universe manager.

Downloads the full list of listed stocks from the NASDAQ Screener API,
and maintains a local CSV cache.
Used by screening and data-loading modules to enumerate tradeable tickers.

Symbol normalization: dots replaced with hyphens (BRK.B → BRK-B) for yfinance compatibility.

Data source:
  https://api.nasdaq.com/api/screener/stocks?tableonly=true&exchange=NASDAQ|NYSE|AMEX
  (the old FTP URLs at nasdaqtrader.com are no longer available as of 2025)
"""

from __future__ import annotations

import csv
import time
from dataclasses import dataclass
from pathlib import Path

import aiohttp
import structlog

logger = structlog.get_logger(__name__)

# ============================================================
# NASDAQ Screener API
# ============================================================

_SCREENER_BASE = "https://api.nasdaq.com/api/screener/stocks"
_EXCHANGES = ["NASDAQ", "NYSE", "AMEX"]

# Exchange code mapping: screener returns full names, we store short codes
_EXCHANGE_CODE_MAP: dict[str, str] = {
    "NASDAQ": "NASD",
    "NYSE": "NYSE",
    "AMEX": "AMEX",
}

# User-Agent header required by api.nasdaq.com
_HEADERS: dict[str, str] = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Accept": "application/json",
}

# Maximum stocks to fetch per exchange (API supports up to ~10000)
_FETCH_LIMIT = 10000

# Cache freshness threshold (7 days in seconds)
_CACHE_MAX_AGE_SECONDS = 7 * 24 * 60 * 60


# ============================================================
# Data Model
# ============================================================

@dataclass(frozen=True)
class UniverseStock:
    """A single stock in the NYSE/NASDAQ universe."""

    ticker: str
    name: str
    exchange: str       # "NASD", "NYSE", "AMEX"
    is_etf: bool = False


# ============================================================
# Universe Manager
# ============================================================

class UniverseManager:
    """NYSE + NASDAQ 전 종목 유니버스 관리."""

    def __init__(self, cache_dir: str = "data") -> None:
        self._cache_dir = Path(cache_dir)
        self._stocks: dict[str, UniverseStock] = {}
        self._loaded: bool = False

    # ── Public API ───────────────────────────────────────────

    async def load_universe(self, force_refresh: bool = False) -> int:
        """
        Load the full stock universe.

        Checks CSV cache first; downloads from NASDAQ FTP if stale or missing.

        Returns:
            Total number of loaded stocks.
        """
        # Try cache first (must be fresh AND non-empty)
        if not force_refresh and self._is_cache_fresh():
            if self._load_cache() and len(self._stocks) > 0:
                self._loaded = True
                logger.info(
                    "universe_loaded",
                    count=len(self._stocks),
                    source="cache",
                )
                return len(self._stocks)
            # Cache exists but is empty → force refresh from FTP
            logger.warning(
                "universe_cache_empty",
                msg="캐시 파일이 비어있어 NASDAQ FTP에서 다시 다운로드합니다.",
            )

        # Download fresh data from NASDAQ Screener API
        self._stocks.clear()

        try:
            await self._download_from_screener()
        except Exception as exc:
            logger.error(
                "universe_download_failed",
                error=str(exc),
                msg="NASDAQ Screener API 다운로드 실패. 네트워크 상태를 확인하세요.",
            )
            # 실패 시 기존 캐시라도 반환 (0건이어도 크래시보다 낫다)
            self._load_cache()
            self._loaded = True
            return len(self._stocks)

        if len(self._stocks) == 0:
            logger.error(
                "universe_parse_empty",
                msg="NASDAQ API 데이터를 파싱했지만 종목이 0건입니다. API 형식 변경 여부를 확인하세요.",
            )

        self._save_cache()
        self._loaded = True

        logger.info(
            "universe_loaded",
            count=len(self._stocks),
            source="api",
        )
        return len(self._stocks)

    async def get_all_tickers(self) -> list[str]:
        """Return sorted list of all ticker symbols."""
        if not self._loaded:
            await self.load_universe()
        return sorted(self._stocks.keys())

    def get_stock(self, ticker: str) -> UniverseStock | None:
        """Return UniverseStock for given ticker, or None if not found."""
        return self._stocks.get(ticker)

    def get_exchange(self, ticker: str) -> str:
        """Return exchange code for ticker. Defaults to 'NASD' if not found."""
        stock = self._stocks.get(ticker)
        return stock.exchange if stock else "NASD"

    def filter_tradeable(self) -> list[UniverseStock]:
        """Return non-ETF stocks only."""
        return [s for s in self._stocks.values() if not s.is_etf]

    # ── Download from NASDAQ Screener API ────────────────────

    async def _download_from_screener(self) -> None:
        """
        Fetch all stocks from NASDAQ Screener API for each exchange.

        API endpoint:
            GET https://api.nasdaq.com/api/screener/stocks
            ?tableonly=true&limit=10000&exchange=NASDAQ

        Response shape:
            {
                "data": {
                    "totalrecords": 4084,
                    "table": {
                        "rows": [
                            {"symbol": "AAPL", "name": "Apple Inc. ...", ...},
                            ...
                        ]
                    }
                }
            }
        """
        timeout = aiohttp.ClientTimeout(total=60)
        async with aiohttp.ClientSession(timeout=timeout, headers=_HEADERS) as session:
            for exchange in _EXCHANGES:
                url = (
                    f"{_SCREENER_BASE}"
                    f"?tableonly=true"
                    f"&limit={_FETCH_LIMIT}"
                    f"&exchange={exchange}"
                )
                try:
                    async with session.get(url) as resp:
                        resp.raise_for_status()
                        data = await resp.json()

                    rows = data.get("data", {}).get("table", {}).get("rows", [])
                    exchange_code = _EXCHANGE_CODE_MAP.get(exchange, exchange)
                    added = 0

                    for row in rows:
                        symbol = row.get("symbol", "").strip()
                        name = row.get("name", "").strip()

                        if not symbol:
                            continue

                        # Filter: skip symbols with special characters
                        # (warrants, units, preferred shares etc.)
                        if any(ch in symbol for ch in ("$", "^", "/")):
                            continue

                        # Normalize: BRK.B → BRK-B for yfinance compatibility
                        ticker = symbol.replace(".", "-")

                        # Detect ETF from name heuristic
                        name_lower = name.lower()
                        is_etf = any(
                            kw in name_lower
                            for kw in ("etf", "exchange traded", "exchange-traded")
                        )

                        self._stocks[ticker] = UniverseStock(
                            ticker=ticker,
                            name=name,
                            exchange=exchange_code,
                            is_etf=is_etf,
                        )
                        added += 1

                    logger.info(
                        "universe_exchange_loaded",
                        exchange=exchange,
                        fetched=len(rows),
                        added=added,
                    )

                except Exception as exc:
                    logger.error(
                        "universe_exchange_failed",
                        exchange=exchange,
                        error=str(exc),
                    )
                    # Continue with other exchanges even if one fails

    # ── Cache Management ─────────────────────────────────────

    @property
    def _cache_path(self) -> Path:
        """Path to the CSV cache file."""
        return self._cache_dir / "universe_cache.csv"

    def _save_cache(self) -> None:
        """Write all stocks to CSV: ticker,name,exchange,is_etf."""
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        with open(self._cache_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["ticker", "name", "exchange", "is_etf"])
            for stock in self._stocks.values():
                writer.writerow([
                    stock.ticker,
                    stock.name,
                    stock.exchange,
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
                    self._stocks[ticker] = UniverseStock(
                        ticker=ticker,
                        name=row["name"],
                        exchange=row["exchange"],
                        is_etf=row["is_etf"] == "Y",
                    )
            return True
        except (FileNotFoundError, KeyError, csv.Error):
            return False

    def _is_cache_fresh(self) -> bool:
        """Return True if cache file exists and mtime is within 7 days."""
        path = self._cache_path
        if not path.exists():
            return False
        age = time.time() - path.stat().st_mtime
        return age < _CACHE_MAX_AGE_SECONDS
