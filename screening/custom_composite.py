"""
Custom Composite Score calculator.

Replaces IBD's proprietary Composite Rating with a weighted score (0-99)
built from publicly available data:

  EPS growth score:       30%  (quarterly + annual combined)
  RS Rating:              30%  (from rs_rating module)
  Institutional score:    15%  (holder count + accumulation)
  Supply/Demand score:    15%  (Up/Down volume ratio, ADV trend)
  Financial health:       10%  (D/E ratio, profit margin)

Weights from config/constants.py: COMPOSITE_WEIGHT_* constants.
"""

from __future__ import annotations

import time

import structlog

from config.constants import (
    COMPOSITE_WEIGHT_EPS,
    COMPOSITE_WEIGHT_RS,
    COMPOSITE_WEIGHT_INSTITUTIONAL,
    COMPOSITE_WEIGHT_SUPPLY_DEMAND,
    COMPOSITE_WEIGHT_FINANCIAL,
)
from data.fundamental_data import FundamentalDataManager
from data.market_data import MarketDataProvider

logger = structlog.get_logger(__name__)


# ── Helper ───────────────────────────────────────────────────


def _interpolate(value: float, breakpoints: list[tuple[float, float]]) -> float:
    """Linear interpolation between breakpoints [(threshold, score), ...].

    *breakpoints* must be sorted ascending by threshold.
    Values below the first threshold return the first score;
    values above the last threshold return the last score.
    """
    if not breakpoints:
        return 50.0

    # Below the lowest threshold
    if value <= breakpoints[0][0]:
        return breakpoints[0][1]

    # Above the highest threshold
    if value >= breakpoints[-1][0]:
        return breakpoints[-1][1]

    # Find surrounding breakpoints and interpolate
    for i in range(len(breakpoints) - 1):
        lo_thresh, lo_score = breakpoints[i]
        hi_thresh, hi_score = breakpoints[i + 1]

        if lo_thresh <= value <= hi_thresh:
            # Avoid division by zero (shouldn't happen with sorted unique thresholds)
            if hi_thresh == lo_thresh:
                return lo_score
            ratio = (value - lo_thresh) / (hi_thresh - lo_thresh)
            return lo_score + ratio * (hi_score - lo_score)

    # Fallback (should never reach here)
    return breakpoints[-1][1]


class CompositeScoreCalculator:
    """자체 Composite Score 계산 (IBD Composite Rating 대체)."""

    def __init__(
        self,
        fundamental_data: FundamentalDataManager,
        market_data: MarketDataProvider,
    ) -> None:
        self._fundamentals = fundamental_data
        self._market = market_data

    # ── Public API ───────────────────────────────────────────

    async def calculate(
        self, ticker: str, rs_rating: int | None = None
    ) -> float | None:
        """Calculate composite score for a single ticker.

        Computes five sub-scores on a 0-99 scale and returns the
        weighted average, clamped to 1-99.

        Args:
            ticker: Stock ticker symbol.
            rs_rating: Pre-computed RS Rating (1-99). If None, a neutral
                       default of 50 is used.

        Returns:
            Integer composite score (1-99), or None if a critical
            sub-score could not be computed.
        """
        eps_score = await self._calc_eps_score(ticker)
        rs_score = rs_rating if rs_rating is not None else 50
        inst_score = await self._calc_institutional_score(ticker)
        sd_score = await self._calc_supply_demand_score(ticker)
        fin_score = await self._calc_financial_score(ticker)

        # If any critical sub-score failed, bail out
        if any(s is None for s in (eps_score, inst_score, sd_score, fin_score)):
            logger.debug(
                "composite_score_incomplete",
                ticker=ticker,
                eps=eps_score,
                rs=rs_score,
                institutional=inst_score,
                supply_demand=sd_score,
                financial=fin_score,
            )
            return None

        composite = (
            COMPOSITE_WEIGHT_EPS * eps_score
            + COMPOSITE_WEIGHT_RS * rs_score
            + COMPOSITE_WEIGHT_INSTITUTIONAL * inst_score
            + COMPOSITE_WEIGHT_SUPPLY_DEMAND * sd_score
            + COMPOSITE_WEIGHT_FINANCIAL * fin_score
        )

        # Clamp to 1-99
        return max(1, min(99, round(composite)))

    async def calculate_universe(
        self,
        tickers: list[str],
        rs_ratings: dict[str, int] | None = None,
    ) -> dict[str, float]:
        """Calculate composite score for all tickers in the universe.

        Args:
            tickers: Full list of ticker symbols.
            rs_ratings: Optional pre-computed RS Ratings (ticker → 1-99).

        Returns:
            Dict mapping ticker → composite score (1-99).
            Tickers that fail computation are omitted.
        """
        start = time.monotonic()
        results: dict[str, float] = {}

        for i, ticker in enumerate(tickers):
            rs = rs_ratings.get(ticker) if rs_ratings else None
            score = await self.calculate(ticker, rs_rating=rs)
            if score is not None:
                results[ticker] = score

            if (i + 1) % 500 == 0:
                logger.info(
                    "composite_score_progress",
                    processed=i + 1,
                    total=len(tickers),
                    scored=len(results),
                )

        elapsed = time.monotonic() - start
        logger.info(
            "composite_score_complete",
            total_tickers=len(tickers),
            scored=len(results),
            skipped=len(tickers) - len(results),
            elapsed_seconds=round(elapsed, 2),
        )

        return results

    # ── Sub-score Calculators ────────────────────────────────

    async def _calc_eps_score(self, ticker: str) -> float:
        """Calculate EPS growth score (0-99).

        Combines quarterly YoY EPS growth (60%) with annual EPS CAGR (40%).
        Returns 50 (neutral) when data is unavailable.
        """
        quarterly_score = await self._quarterly_eps_score(ticker)
        annual_score = await self._annual_eps_score(ticker)

        return 0.6 * quarterly_score + 0.4 * annual_score

    async def _quarterly_eps_score(self, ticker: str) -> float:
        """Score quarterly EPS: most recent quarter vs. same quarter last year."""
        quarters = await self._fundamentals.get_quarterly_eps(ticker, limit=8)

        if len(quarters) < 2:
            return 50.0

        # quarters are descending by period: [newest, ..., oldest]
        current_period = quarters[0][0]  # e.g., "2025Q4"
        latest_eps = quarters[0][1]

        # Match by period name instead of index to handle NULL gaps
        try:
            year_str = current_period[:4]
            q_suffix = current_period[4:]  # "Q4", "Q3", etc.
            year_ago_period = f"{int(year_str) - 1}{q_suffix}"
        except (ValueError, IndexError):
            return 50.0

        yoy_eps = None
        for period, eps in quarters:
            if period == year_ago_period:
                yoy_eps = eps
                break

        if yoy_eps is None or yoy_eps == 0:
            return 50.0

        growth = (latest_eps - yoy_eps) / abs(yoy_eps)

        # Breakpoints: (growth_threshold, score)
        # Ascending by threshold for _interpolate
        breakpoints: list[tuple[float, float]] = [
            (-0.50, 1.0),
            (0.00, 20.0),
            (0.10, 40.0),
            (0.25, 60.0),
            (0.50, 80.0),
            (1.00, 99.0),
        ]
        return _interpolate(growth, breakpoints)

    async def _annual_eps_score(self, ticker: str) -> float:
        """Score annual EPS CAGR over available years."""
        annuals = await self._fundamentals.get_annual_eps(ticker, limit=5)

        if len(annuals) < 2:
            return 50.0

        # annuals are descending: [newest, ..., oldest]
        latest_eps = annuals[0][1]
        oldest_eps = annuals[-1][1]
        years = len(annuals) - 1

        if oldest_eps is None or oldest_eps <= 0 or latest_eps is None or latest_eps <= 0:
            # Cannot compute a meaningful CAGR with non-positive EPS
            if latest_eps is not None and oldest_eps is not None:
                # Both exist but one/both are negative — low score
                return 5.0 if latest_eps < oldest_eps else 15.0
            return 50.0

        cagr = (latest_eps / oldest_eps) ** (1.0 / years) - 1.0

        # Breakpoints: (cagr_threshold, score)
        breakpoints: list[tuple[float, float]] = [
            (-0.25, 1.0),
            (0.00, 15.0),
            (0.05, 35.0),
            (0.15, 55.0),
            (0.25, 75.0),
            (0.50, 99.0),
        ]
        return _interpolate(cagr, breakpoints)

    async def _calc_institutional_score(self, ticker: str) -> float:
        """Calculate institutional ownership score (0-99).

        Evaluates both the number of institutional holders and
        the percentage of shares they hold.  Returns 50 (neutral)
        when data is unavailable.
        """
        data = await self._fundamentals.get_institutional_data(ticker)
        holders_count = data.get("holders_count", 0)
        held_pct = data.get("held_pct", 0.0)

        if holders_count == 0 and held_pct == 0.0:
            return 50.0

        # ── Holders count score ──────────────────────────────
        holders_bp: list[tuple[float, float]] = [
            (1.0, 10.0),
            (5.0, 40.0),
            (10.0, 60.0),
            (20.0, 80.0),
            (50.0, 99.0),
        ]
        holders_score = _interpolate(float(holders_count), holders_bp)

        # ── Held percentage score ────────────────────────────
        # Sweet spot is 10-60%; too low = no interest, too high = over-owned
        if held_pct < 0.10:
            held_pct_score = _interpolate(
                held_pct,
                [(0.0, 10.0), (0.10, 20.0)],
            )
        elif held_pct <= 0.60:
            held_pct_score = _interpolate(
                held_pct,
                [(0.10, 40.0), (0.60, 90.0)],
            )
        elif held_pct <= 0.80:
            held_pct_score = _interpolate(
                held_pct,
                [(0.60, 90.0), (0.80, 30.0)],
            )
        else:
            held_pct_score = 30.0

        return 0.5 * holders_score + 0.5 * held_pct_score

    async def _calc_supply_demand_score(self, ticker: str) -> float:
        """Calculate supply/demand score (0-99).

        Evaluates the Up/Down volume ratio (60%) and average
        daily volume magnitude (40%).  Returns 50 (neutral)
        when data is unavailable.
        """
        ud_ratio = await self._market.get_up_down_volume_ratio(ticker, period=50)
        avg_vol = await self._market.get_avg_volume(ticker, period=50)

        if ud_ratio is None and avg_vol is None:
            return 50.0

        # ── Up/Down volume ratio score ───────────────────────
        if ud_ratio is not None:
            ud_bp: list[tuple[float, float]] = [
                (0.5, 5.0),
                (0.7, 30.0),
                (1.0, 50.0),
                (1.5, 80.0),
                (2.0, 99.0),
            ]
            ud_score = _interpolate(ud_ratio, ud_bp)
        else:
            ud_score = 50.0

        # ── Average volume magnitude score ───────────────────
        if avg_vol is not None:
            vol_bp: list[tuple[float, float]] = [
                (100_000.0, 10.0),
                (500_000.0, 50.0),
                (1_000_000.0, 70.0),
                (5_000_000.0, 90.0),
            ]
            vol_score = _interpolate(float(avg_vol), vol_bp)
        else:
            vol_score = 50.0

        return 0.6 * ud_score + 0.4 * vol_score

    async def _calc_financial_score(self, ticker: str) -> float:
        """Calculate financial health score (0-99).

        Currently based on debt-to-equity ratio.  Lower D/E is
        better.  Returns 50 (neutral) when data is unavailable.
        """
        de_ratio = await self._fundamentals.get_debt_to_equity(ticker)

        if de_ratio is None:
            return 50.0

        # Breakpoints: (D/E threshold, score) — lower is better
        de_bp: list[tuple[float, float]] = [
            (0.0, 99.0),
            (0.5, 95.0),
            (1.0, 75.0),
            (2.0, 50.0),
            (5.0, 25.0),
            (10.0, 5.0),
        ]
        return _interpolate(de_ratio, de_bp)
