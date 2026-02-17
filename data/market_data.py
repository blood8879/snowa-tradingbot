"""
Unified market data interface.

Single entry point for all price-related queries — abstracts away
the underlying data sources (SQLite cache, yfinance, KIS REST API).

Used by strategy, screening, and portfolio modules.
"""

from __future__ import annotations

import structlog

from core.models import OHLCV
from data.price_cache import PriceCache

logger = structlog.get_logger(__name__)


class MarketDataProvider:
    """통합 시세 인터페이스 — 가격 캐시 위에 편의 메서드를 제공."""

    def __init__(self, price_cache: PriceCache) -> None:
        self._cache = price_cache

    # ── Raw Data Access ──────────────────────────────────────

    async def get_ohlcv(self, ticker: str, days: int = 300) -> list[OHLCV]:
        """Return recent OHLCV bars (ascending date order, oldest first)."""
        return await self._cache.get_ohlcv(ticker, days)

    async def get_latest_price(self, ticker: str) -> float | None:
        """Return the most recent closing price for *ticker*."""
        return await self._cache.get_latest_close(ticker)

    async def get_closes(self, ticker: str, days: int = 300) -> list[float]:
        """Return closing prices as a flat list (oldest first)."""
        bars = await self._cache.get_ohlcv(ticker, days)
        return [bar.close for bar in bars]

    # ── Moving Averages ──────────────────────────────────────

    async def get_sma(
        self, ticker: str, period: int, data_days: int | None = None
    ) -> float | None:
        """Calculate Simple Moving Average over *period* days.

        Args:
            ticker: Stock ticker symbol.
            period: Number of days for the SMA window.
            data_days: How many days of price data to fetch.
                       Defaults to ``period + 50`` if not provided.

        Returns:
            The SMA value, or None if insufficient data.
        """
        if data_days is None:
            data_days = period + 50

        closes = await self.get_closes(ticker, data_days)

        if len(closes) < period:
            logger.debug(
                "sma_insufficient_data",
                ticker=ticker,
                period=period,
                available=len(closes),
            )
            return None

        return sum(closes[-period:]) / period

    async def get_ema(
        self, ticker: str, period: int, data_days: int | None = None
    ) -> float | None:
        """Calculate Exponential Moving Average over *period* days.

        Uses the standard EMA formula:
        - Seed with the SMA of the first *period* values.
        - ``multiplier = 2 / (period + 1)``
        - ``ema = close × multiplier + prev_ema × (1 − multiplier)``

        Args:
            ticker: Stock ticker symbol.
            period: Number of days for the EMA window.
            data_days: How many days of price data to fetch.
                       Defaults to ``period + 50`` if not provided.

        Returns:
            The latest EMA value, or None if insufficient data.
        """
        if data_days is None:
            data_days = period + 50

        closes = await self.get_closes(ticker, data_days)

        if len(closes) < period:
            logger.debug(
                "ema_insufficient_data",
                ticker=ticker,
                period=period,
                available=len(closes),
            )
            return None

        # Seed EMA with SMA of the first `period` values
        ema = sum(closes[:period]) / period
        multiplier = 2 / (period + 1)

        # Iterate through remaining closes
        for close in closes[period:]:
            ema = close * multiplier + ema * (1 - multiplier)

        return ema

    # ── Price Range ───────────────────────────────────────────

    async def get_52w_high(self, ticker: str) -> float | None:
        """Return the 52-week (252 trading days) high price.

        Returns None if insufficient data is available.
        """
        bars = await self._cache.get_ohlcv(ticker, 252)

        if not bars:
            logger.debug("52w_high_no_data", ticker=ticker)
            return None

        return max(bar.high for bar in bars)

    async def get_52w_low(self, ticker: str) -> float | None:
        """Return the 52-week (252 trading days) low price.

        Returns None if insufficient data is available.
        """
        bars = await self._cache.get_ohlcv(ticker, 252)

        if not bars:
            logger.debug("52w_low_no_data", ticker=ticker)
            return None

        return min(bar.low for bar in bars)

    # ── Volume ───────────────────────────────────────────────

    async def get_avg_volume(self, ticker: str, period: int = 50) -> int | None:
        """Return the average daily volume over *period* trading days.

        Returns None if insufficient data.
        """
        bars = await self._cache.get_ohlcv(ticker, period)

        if len(bars) < period:
            logger.debug(
                "avg_volume_insufficient_data",
                ticker=ticker,
                period=period,
                available=len(bars),
            )
            return None

        total_volume = sum(bar.volume for bar in bars[-period:])
        return int(total_volume / period)

    async def get_up_down_volume_ratio(
        self, ticker: str, period: int = 50
    ) -> float | None:
        """Calculate Up/Down Volume Ratio over *period* days.

        An up day is when ``close > previous close``; otherwise it is a down day.
        The ratio is ``sum(up-day volumes) / sum(down-day volumes)``.

        Returns None if insufficient data or if down-day volume is zero.
        """
        # Need period + 1 days: the extra day provides the prior close
        bars = await self._cache.get_ohlcv(ticker, period + 1)

        if len(bars) < period + 1:
            logger.debug(
                "up_down_ratio_insufficient_data",
                ticker=ticker,
                period=period,
                available=len(bars),
            )
            return None

        # Use the last (period + 1) bars for comparison
        recent_bars = bars[-(period + 1):]

        up_volume = 0
        down_volume = 0

        for i in range(1, len(recent_bars)):
            if recent_bars[i].close > recent_bars[i - 1].close:
                up_volume += recent_bars[i].volume
            else:
                down_volume += recent_bars[i].volume

        if down_volume == 0:
            return None

        return up_volume / down_volume

    # ── Price Change ─────────────────────────────────────────

    async def get_price_change_pct(self, ticker: str, days: int) -> float | None:
        """Calculate percentage price change over *days* trading days.

        Returns ``(latest_close / close_N_days_ago) − 1.0``,
        or None if insufficient data.
        """
        closes = await self.get_closes(ticker, days + 10)

        if len(closes) < days:
            logger.debug(
                "price_change_insufficient_data",
                ticker=ticker,
                days=days,
                available=len(closes),
            )
            return None

        return (closes[-1] / closes[-days]) - 1.0

    # ── Market Filter ────────────────────────────────────────

    async def get_market_filter(self) -> bool:
        """Check whether the broad market is in an uptrend.

        Uses the rule: ``SPY close > SPY 200-day SMA``.
        Returns True (fail-open) if data is unavailable,
        so that trading is not blocked by a data gap.
        """
        from config.constants import MARKET_BENCHMARK, MARKET_MA_PERIOD

        latest_close = await self.get_latest_price(MARKET_BENCHMARK)
        sma_200 = await self.get_sma(MARKET_BENCHMARK, MARKET_MA_PERIOD)

        if latest_close is None or sma_200 is None:
            logger.warning(
                "market_filter_data_unavailable",
                benchmark=MARKET_BENCHMARK,
                latest_close=latest_close,
                sma_200=sma_200,
            )
            return True  # fail-open: do not block trading

        result = latest_close > sma_200
        logger.debug(
            "market_filter_result",
            benchmark=MARKET_BENCHMARK,
            close=latest_close,
            sma=sma_200,
            above_ma=result,
        )
        return result
