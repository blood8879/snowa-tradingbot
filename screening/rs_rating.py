"""
Relative Strength (RS) Rating calculator.

Approximates IBD's RS Rating using a weighted return formula
across 3/6/9/12-month periods, then converts to a 1-99
percentile rank against the full stock universe.

Formula (from QUANTIFIED_STRATEGY.md §1.1):
    Raw_RS = 0.4 × (3-month return) + 0.2 × (6-month return)
           + 0.2 × (9-month return) + 0.2 × (12-month return)

Percentile rank: 1 (worst) to 99 (best).
"""

from __future__ import annotations

import time

import structlog

from config.constants import (
    RS_TRADING_DAYS_3M,
    RS_TRADING_DAYS_6M,
    RS_TRADING_DAYS_9M,
    RS_TRADING_DAYS_12M,
    RS_WEIGHT_3M,
    RS_WEIGHT_6M,
    RS_WEIGHT_9M,
    RS_WEIGHT_12M,
)
from data.price_cache import PriceCache

logger = structlog.get_logger(__name__)


class RSRatingCalculator:
    """전체 유니버스 대비 상대 강도(RS) Rating 계산."""

    def __init__(self, price_cache: PriceCache) -> None:
        self._cache = price_cache

    # ── Single Ticker ────────────────────────────────────────

    async def calculate_single(self, ticker: str, *, market: str = "US") -> float | None:
        """
        Calculate raw RS score for a single ticker.

        Returns the weighted return value (NOT a percentile rank).
        The percentile conversion requires the full universe — see
        :meth:`calculate_universe`.

        Args:
            ticker: Stock symbol.
            market: Market identifier ("US" or "KR") for logging context.

        Returns:
            Raw RS score as a float, or None if insufficient data.
        """
        bars = await self._cache.get_ohlcv(ticker, RS_TRADING_DAYS_12M + 10)
        closes = [bar.close for bar in bars]

        if len(closes) < RS_TRADING_DAYS_12M:
            return None

        ret_3m = (closes[-1] / closes[-RS_TRADING_DAYS_3M]) - 1
        ret_6m = (closes[-1] / closes[-RS_TRADING_DAYS_6M]) - 1
        ret_9m = (closes[-1] / closes[-RS_TRADING_DAYS_9M]) - 1
        ret_12m = (closes[-1] / closes[-RS_TRADING_DAYS_12M]) - 1

        raw_rs = (
            RS_WEIGHT_3M * ret_3m
            + RS_WEIGHT_6M * ret_6m
            + RS_WEIGHT_9M * ret_9m
            + RS_WEIGHT_12M * ret_12m
        )
        return raw_rs

    # ── Full Universe ────────────────────────────────────────

    async def calculate_universe(self, tickers: list[str], *, market: str = "US") -> dict[str, int]:
        """
        Calculate RS Rating (1-99) for every ticker in the universe.

        For KR market, RS ratings are calculated against KR universe only.
        For US market, RS ratings are calculated against US universe only.

        Steps:
            1. Compute raw RS for each ticker via :meth:`calculate_single`.
            2. Rank all raw scores to produce a 1-99 percentile.

        Args:
            tickers: Full list of ticker symbols in the stock universe.
            market: Market identifier ("US" or "KR") for separate universe calculation.

        Returns:
            Dict mapping ticker → RS Rating (1-99 int).
            Tickers with insufficient price data are omitted.
        """
        start = time.monotonic()

        # Step 1: compute raw RS scores
        raw_scores: dict[str, float] = {}
        for i, ticker in enumerate(tickers):
            score = await self.calculate_single(ticker, market=market)
            if score is not None:
                raw_scores[ticker] = score

            if (i + 1) % 500 == 0:
                logger.info(
                    "rs_rating_progress",
                    processed=i + 1,
                    total=len(tickers),
                    valid=len(raw_scores),
                    market=market,
                )

        if not raw_scores:
            return {}

        # Step 2: percentile rank each raw score
        sorted_tickers = sorted(raw_scores.keys(), key=lambda t: raw_scores[t])
        total = len(sorted_tickers)

        ratings: dict[str, int] = {}
        for rank, ticker in enumerate(sorted_tickers):
            # percentile: 1 to 99
            percentile = int(((rank + 1) / total) * 100)
            percentile = max(1, min(99, percentile))
            ratings[ticker] = percentile

        elapsed = time.monotonic() - start
        logger.info(
            "rs_rating_complete",
            total_tickers=len(tickers),
            rated=len(ratings),
            skipped=len(tickers) - len(ratings),
            elapsed_seconds=round(elapsed, 2),
            market=market,
        )

        return ratings

    # ── Lookup Helper ────────────────────────────────────────

    async def get_rs_rating(
        self, ticker: str, universe_ratings: dict[str, int]
    ) -> int | None:
        """
        Look up a pre-computed RS Rating for a single ticker.

        Args:
            ticker: Stock symbol.
            universe_ratings: Dict returned by :meth:`calculate_universe`.

        Returns:
            RS Rating (1-99) or None if the ticker was not rated.
        """
        return universe_ratings.get(ticker)
