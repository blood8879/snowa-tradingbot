"""
Minervini SEPA Trend Template checker.

Implements Mark Minervini's 8-condition trend template to filter
stocks in a confirmed Stage 2 uptrend. Used as a quality filter
on top of CANSLIM screening.

Conditions (from QUANTIFIED_STRATEGY.md §5.4):
  1. Price > 50-day SMA
  2. Price > 150-day SMA
  3. Price > 200-day SMA
  4. 50-day SMA > 150-day SMA
  5. 150-day SMA > 200-day SMA
  6. 200-day SMA rising for ≥ 22 trading days (1 month)
  7. Price within 25% of 52-week high (≥ 75% of high)
  8. Price ≥ 130% of 52-week low (≥ 30% above low)

Optional: RS Rating ≥ 70
"""

from __future__ import annotations

from dataclasses import dataclass

import structlog

from config.constants import (
    MINERVINI_MAX_PRICE_VS_52W_HIGH,
    MINERVINI_MIN_PRICE_VS_52W_LOW,
    MINERVINI_200MA_UPTREND_DAYS,
    MINERVINI_MIN_RS_RATING_TREND,
    MINERVINI_HOLD_MIN_PASSED,
    MINERVINI_HOLD_MANDATORY_COND_IDX,
)
from data.market_data import MarketDataProvider

logger = structlog.get_logger(__name__)


# ── Data Structures ──────────────────────────────────────────


@dataclass
class TemplateCondition:
    """Single Minervini condition result."""

    name: str
    passed: bool
    value: float | None = None
    threshold: float | None = None


@dataclass
class TemplateResult:
    """Full Minervini Trend Template result for a ticker."""

    ticker: str
    conditions: list[TemplateCondition]
    rs_condition: TemplateCondition | None = None  # Optional RS check

    @property
    def passed_all(self) -> bool:
        """True if ALL 8 mandatory conditions pass (strict — for new entry)."""
        return all(c.passed for c in self.conditions)

    @property
    def passed_count(self) -> int:
        return sum(1 for c in self.conditions if c.passed)

    @property
    def passed_for_hold(self) -> bool:
        """Hysteresis variant: existing watchlist ticker stays if ≥ MINERVINI_HOLD_MIN_PASSED
        conditions pass AND the mandatory trend-anchor condition (price > 200MA) passes.

        Why: KR 변동성에서 8/8 매일 유지 어려움. 단 추세 앵커(200MA)가 깨지면
             보수적으로 탈락시킴.
        """
        if len(self.conditions) <= MINERVINI_HOLD_MANDATORY_COND_IDX:
            return False
        mandatory = self.conditions[MINERVINI_HOLD_MANDATORY_COND_IDX]
        if not mandatory.passed:
            return False
        return self.passed_count >= MINERVINI_HOLD_MIN_PASSED

    @property
    def passed_with_rs(self) -> bool:
        """True if all 8 conditions pass AND RS >= 70."""
        if not self.passed_all:
            return False
        if self.rs_condition is None:
            return True
        return self.rs_condition.passed


# ── Trend Template Checker ───────────────────────────────────


class MinerviniTemplate:
    """Minervini Trend Template 8-condition 체크."""

    def __init__(self, market_data: MarketDataProvider) -> None:
        self._market = market_data

    # ── Public API ───────────────────────────────────────────

    async def check(
        self, ticker: str, rs_rating: int | None = None, *, market: str = "US"
    ) -> TemplateResult:
        """Run all 8 Minervini conditions for a single ticker.

        Args:
            ticker: Stock ticker symbol.
            rs_rating: Pre-computed RS Rating (1-99). If provided,
                       an additional RS >= 70 check is appended.
            market: Market identifier ("US" or "KR"). Default: "US".

        Returns:
            TemplateResult with 8 mandatory conditions (+ optional RS).
        """
        # Gather market data
        latest = await self._market.get_latest_price(ticker)
        sma_50 = await self._market.get_sma(ticker, 50)
        sma_150 = await self._market.get_sma(ticker, 150)
        sma_200 = await self._market.get_sma(ticker, 200)
        high_52w = await self._market.get_52w_high(ticker)
        low_52w = await self._market.get_52w_low(ticker)

        # Helper: safely compare, returning False if either side is None
        def _gt(a: float | None, b: float | None) -> bool:
            if a is None or b is None:
                return False
            return a > b

        def _gte(a: float | None, b: float | None) -> bool:
            if a is None or b is None:
                return False
            return a >= b

        # ── Condition 1: Price > 50-day SMA ──────────────────
        cond1 = TemplateCondition(
            name="price_above_50sma",
            passed=_gt(latest, sma_50),
            value=latest,
            threshold=sma_50,
        )

        # ── Condition 2: Price > 150-day SMA ─────────────────
        cond2 = TemplateCondition(
            name="price_above_150sma",
            passed=_gt(latest, sma_150),
            value=latest,
            threshold=sma_150,
        )

        # ── Condition 3: Price > 200-day SMA ─────────────────
        cond3 = TemplateCondition(
            name="price_above_200sma",
            passed=_gt(latest, sma_200),
            value=latest,
            threshold=sma_200,
        )

        # ── Condition 4: 50-day SMA > 150-day SMA ───────────
        cond4 = TemplateCondition(
            name="50sma_above_150sma",
            passed=_gt(sma_50, sma_150),
            value=sma_50,
            threshold=sma_150,
        )

        # ── Condition 5: 150-day SMA > 200-day SMA ──────────
        cond5 = TemplateCondition(
            name="150sma_above_200sma",
            passed=_gt(sma_150, sma_200),
            value=sma_150,
            threshold=sma_200,
        )

        # ── Condition 6: 200-day SMA rising ≥ 22 days ───────
        sma_200_rising = await self._check_200sma_rising(ticker)
        cond6 = TemplateCondition(
            name="200sma_rising",
            passed=sma_200_rising,
        )

        # ── Condition 7: Price within 25% of 52-week high ───
        if latest is not None and high_52w is not None and high_52w > 0:
            pct_of_high = latest / high_52w
            cond7_passed = pct_of_high >= MINERVINI_MAX_PRICE_VS_52W_HIGH
        else:
            pct_of_high = None
            cond7_passed = False

        cond7 = TemplateCondition(
            name="within_25pct_of_52w_high",
            passed=cond7_passed,
            value=pct_of_high,
            threshold=MINERVINI_MAX_PRICE_VS_52W_HIGH,
        )

        # ── Condition 8: Price ≥ 130% of 52-week low ────────
        if latest is not None and low_52w is not None and low_52w > 0:
            pct_of_low = latest / low_52w
            cond8_passed = pct_of_low >= MINERVINI_MIN_PRICE_VS_52W_LOW
        else:
            pct_of_low = None
            cond8_passed = False

        cond8 = TemplateCondition(
            name="above_30pct_of_52w_low",
            passed=cond8_passed,
            value=pct_of_low,
            threshold=MINERVINI_MIN_PRICE_VS_52W_LOW,
        )

        conditions = [cond1, cond2, cond3, cond4, cond5, cond6, cond7, cond8]

        # ── Optional: RS Rating ≥ 70 ────────────────────────
        rs_condition: TemplateCondition | None = None
        if rs_rating is not None:
            rs_condition = TemplateCondition(
                name="rs_rating_above_threshold",
                passed=rs_rating >= MINERVINI_MIN_RS_RATING_TREND,
                value=float(rs_rating),
                threshold=float(MINERVINI_MIN_RS_RATING_TREND),
            )

        result = TemplateResult(
            ticker=ticker,
            conditions=conditions,
            rs_condition=rs_condition,
        )

        logger.debug(
            "minervini_check",
            ticker=ticker,
            passed=result.passed_count,
            total=len(conditions),
            all_passed=result.passed_all,
            market=market,
        )

        return result

    # ── Universe Scan ────────────────────────────────────────

    async def check_universe(
        self,
        tickers: list[str],
        rs_ratings: dict[str, int] | None = None,
        *,
        market: str = "US",
    ) -> list[TemplateResult]:
        """Check Minervini template for every ticker in the universe.

        Args:
            tickers: List of ticker symbols to check.
            rs_ratings: Optional dict mapping ticker → RS Rating (1-99).
            market: Market identifier ("US" or "KR"). Default: "US".

        Returns:
            List of TemplateResult for every ticker.
        """
        results: list[TemplateResult] = []

        for i, ticker in enumerate(tickers):
            rs = rs_ratings.get(ticker) if rs_ratings else None
            result = await self.check(ticker, rs_rating=rs, market=market)
            results.append(result)

            if (i + 1) % 500 == 0:
                passed = sum(1 for r in results if r.passed_all)
                logger.info(
                    "minervini_universe_progress",
                    processed=i + 1,
                    total=len(tickers),
                    passed=passed,
                    market=market,
                )

        passed_total = sum(1 for r in results if r.passed_all)
        logger.info(
            "minervini_universe_complete",
            total_tickers=len(tickers),
            passed=passed_total,
            failed=len(tickers) - passed_total,
            market=market,
        )

        return results

    # ── Internal Helpers ─────────────────────────────────────

    async def _check_200sma_rising(self, ticker: str) -> bool:
        """Check if the 200-day SMA has been rising for ≥ 22 trading days.

        Compares today's 200-day SMA against the 200-day SMA from
        MINERVINI_200MA_UPTREND_DAYS (22) days ago. If the current
        value is higher, the trend is considered rising.

        Returns:
            True if today's 200-SMA > 200-SMA from 22 days ago.
            False if insufficient data.
        """
        lookback = MINERVINI_200MA_UPTREND_DAYS
        # Need 200 days for the SMA window + lookback days of shift + buffer
        data_days = 200 + lookback + 10
        closes = await self._market.get_closes(ticker, data_days)

        # Minimum: enough closes to compute both SMA windows
        min_required = 200 + lookback
        if len(closes) < min_required:
            logger.debug(
                "200sma_rising_insufficient_data",
                ticker=ticker,
                required=min_required,
                available=len(closes),
            )
            return False

        # Current 200-day SMA (using the most recent 200 closes)
        sma_today = sum(closes[-200:]) / 200

        # 200-day SMA from `lookback` days ago
        end_idx = len(closes) - lookback
        start_idx = end_idx - 200
        sma_past = sum(closes[start_idx:end_idx]) / 200

        return sma_today > sma_past
