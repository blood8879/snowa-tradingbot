"""
CANSLIM stock screener.

Implements the six CANSLIM criteria plus additional quality filters:
  C — Current quarterly EPS growth ≥ 25% YoY
  A — Annual EPS CAGR ≥ 25% over 5 years
  N — New high (52-week high proximity)
  S — Supply/demand (volume analysis, ADV, Up/Down ratio)
  L — Leader (RS Rating ≥ 80) — delegated to rs_rating module
  I — Institutional sponsorship (min holders, QoQ growth)
  Additional — min price, max D/E, ADV floor

Each filter returns a ScreenResult dataclass with pass/fail and detail values.
"""

from __future__ import annotations

from dataclasses import dataclass

import structlog

from config.constants import (
    CANSLIM_MIN_QUARTERLY_EPS_GROWTH,
    CANSLIM_MIN_ANNUAL_EPS_CAGR,
    CANSLIM_MIN_RS_RATING,
    CANSLIM_HOLD_QUARTERLY_EPS_GROWTH,
    CANSLIM_HOLD_ANNUAL_EPS_CAGR,
    CANSLIM_HOLD_RS_RATING,
    CANSLIM_MIN_INSTITUTIONAL_HOLDERS,
    CANSLIM_MIN_ADV,
    CANSLIM_MIN_UP_DOWN_RATIO,
    CANSLIM_MAX_DEBT_TO_EQUITY,
    CANSLIM_MIN_PRICE,
)
from data.fundamental_data import FundamentalDataManager
from data.market_data import MarketDataProvider
from data.price_cache import PriceCache

logger = structlog.get_logger(__name__)


# ════════════════════════════════════════════════════════════════
# Data Structures
# ════════════════════════════════════════════════════════════════


@dataclass
class ScreenResult:
    """Result of a single CANSLIM filter."""

    passed: bool
    value: float | None = None      # The actual measured value
    threshold: float | None = None   # The threshold it was compared against
    detail: str = ""                 # Human-readable explanation


@dataclass
class CANSLIMResult:
    """Full CANSLIM screening result for a single ticker."""

    ticker: str
    c_filter: ScreenResult   # Current quarterly EPS
    a_filter: ScreenResult   # Annual EPS CAGR
    n_filter: ScreenResult   # New high
    s_filter: ScreenResult   # Supply/Demand
    l_filter: ScreenResult   # Leader (RS Rating)
    i_filter: ScreenResult   # Institutional
    additional: ScreenResult  # Min price, D/E, ADV

    @property
    def passed_all(self) -> bool:
        """Core quantifiable CANSLIM filters only: C, A, S, L.

        Excluded from gating:
        - N (New High): Redundant — Turtle Donchian breakout covers this.
        - I (Institutional): Unreliable from public data (yfinance).
        - Additional (Price, D/E): Informational, not gating.
        """
        return all([
            self.c_filter.passed,
            self.a_filter.passed,
            self.s_filter.passed,
            self.l_filter.passed,
        ])

    @property
    def passed_count(self) -> int:
        """Count of passed core filters (C, A, S, L)."""
        filters = [
            self.c_filter, self.a_filter,
            self.s_filter, self.l_filter,
        ]
        return sum(1 for f in filters if f.passed)


# ════════════════════════════════════════════════════════════════
# CANSLIM Screener
# ════════════════════════════════════════════════════════════════


class CANSLIMScreener:
    """CANSLIM 기반 종목 스크리닝."""

    def __init__(
        self,
        fundamental_data: FundamentalDataManager,
        market_data: MarketDataProvider,
        price_cache: PriceCache,
    ) -> None:
        self._fundamentals = fundamental_data
        self._market = market_data
        self._cache = price_cache

    # ── Main Entry Points ────────────────────────────────────

    async def screen_ticker(
        self,
        ticker: str,
        rs_rating: int | None = None,
        core_only: bool = False,
        *,
        market: str = "US",
        hold_mode: bool = False,
        previous_values: dict | None = None,
    ) -> CANSLIMResult:
        """Run CANSLIM filters for a single ticker.

        Args:
            ticker: Stock ticker symbol.
            rs_rating: Pre-computed RS Rating (1–99). If None the L filter fails.
            core_only: When True, skip non-gating filters (N, I, Additional)
                       to avoid slow yfinance API calls during bulk screening.
            market: Market identifier ("US" or "KR") for threshold adjustments.
            hold_mode: True if this ticker is already in the watchlist. Applies
                       relaxed HOLD thresholds (hysteresis) to prevent daily toggling.
            previous_values: Last known screening values (fallback for data gaps).
                             Keys: quarterly_eps_growth, annual_eps_cagr, rs_rating.

        Returns:
            A ``CANSLIMResult`` containing every filter's outcome.
        """
        s = await self.check_s_filter(ticker, market=market)
        l = await self.check_l_filter(
            ticker, rs_rating, market=market,
            hold_mode=hold_mode, previous_values=previous_values,
        )

        # Short-circuit: for KR, skip expensive DART API lookups if S or L already failed
        if market == "KR" and not (s.passed and l.passed):
            c = ScreenResult(passed=False, detail="Skipped (S or L failed)")
            a = ScreenResult(passed=False, detail="Skipped (S or L failed)")
        else:
            c = await self.check_c_filter(
                ticker, market=market,
                hold_mode=hold_mode, previous_values=previous_values,
            )
            a = await self.check_a_filter(
                ticker, market=market,
                hold_mode=hold_mode, previous_values=previous_values,
            )

        if core_only:
            n = ScreenResult(passed=False, detail="Skipped (core_only)")
            i = ScreenResult(passed=False, detail="Skipped (core_only)")
            additional = ScreenResult(passed=True, detail="Skipped (core_only)")
        else:
            n = await self.check_n_filter(ticker, market=market)
            i = await self.check_i_filter(ticker, market=market)
            additional = await self.check_additional(ticker, market=market)

        result = CANSLIMResult(
            ticker=ticker,
            c_filter=c,
            a_filter=a,
            n_filter=n,
            s_filter=s,
            l_filter=l,
            i_filter=i,
            additional=additional,
        )

        logger.debug(
            "canslim_screen_complete",
            ticker=ticker,
            market=market,
            passed_count=result.passed_count,
            passed_all=result.passed_all,
        )
        return result

    async def screen_universe(
        self,
        tickers: list[str],
        rs_ratings: dict[str, int] | None = None,
        core_only: bool = False,
        *,
        market: str = "US",
        existing_tickers: set[str] | None = None,
        previous_values_map: dict[str, dict] | None = None,
    ) -> list[CANSLIMResult]:
        """Screen all tickers and return results sorted by *passed_count* descending.

        Args:
            tickers: List of ticker symbols to screen.
            rs_ratings: Optional mapping of ticker → RS Rating.
            core_only: Skip non-gating filters for performance.
            market: Market identifier ("US" or "KR") for threshold adjustments.
            existing_tickers: Tickers already in watchlist. Receive hold_mode=True
                              for hysteresis-based evaluation.
            previous_values_map: ticker → last screening values dict (fallback for gaps).

        Returns:
            List of ``CANSLIMResult``, best candidates first.
        """
        if rs_ratings is None:
            rs_ratings = {}
        existing_tickers = existing_tickers or set()
        previous_values_map = previous_values_map or {}

        results: list[CANSLIMResult] = []
        total = len(tickers)

        for idx, ticker in enumerate(tickers, start=1):
            try:
                rs = rs_ratings.get(ticker)
                result = await self.screen_ticker(
                    ticker, rs_rating=rs, core_only=core_only, market=market,
                    hold_mode=(ticker in existing_tickers),
                    previous_values=previous_values_map.get(ticker),
                )
                results.append(result)
            except Exception:
                logger.warning("screen_ticker_failed", ticker=ticker, exc_info=True)

            if idx % 200 == 0:
                logger.info(
                    "screen_universe_progress",
                    market=market,
                    completed=idx,
                    total=total,
                    passed_so_far=sum(1 for r in results if r.passed_all),
                )

        # Sort by passed_count descending (best candidates first)
        results.sort(key=lambda r: r.passed_count, reverse=True)

        logger.info(
            "screen_universe_complete",
            market=market,
            total_screened=len(results),
            passed_all=sum(1 for r in results if r.passed_all),
        )
        return results

    # ── Individual Filters ───────────────────────────────────

    async def check_c_filter(
        self, ticker: str, *, market: str = "US",
        hold_mode: bool = False, previous_values: dict | None = None,
    ) -> ScreenResult:
        """**C = Current Quarterly EPS** — YoY growth ≥ 25% (진입) / ≥ 15% (유지).

        Compares the most recent quarter's EPS against the same quarter
        one year prior.  Requires at least 5 quarters of data.

        Uses DART OpenAPI data for KR market (net income as EPS proxy).
        If data is missing but ticker has a recent previous value (hold_mode),
        falls back to that value to avoid daily toggling.
        """
        threshold = (
            CANSLIM_HOLD_QUARTERLY_EPS_GROWTH if hold_mode
            else CANSLIM_MIN_QUARTERLY_EPS_GROWTH
        )

        def _fallback_if_missing(reason: str) -> ScreenResult | None:
            # Hold mode only: reuse the last known value when fresh data is unavailable.
            if not hold_mode or not previous_values:
                return None
            prev = previous_values.get("quarterly_eps_growth")
            if prev is None:
                return None
            passed = prev >= threshold
            return ScreenResult(
                passed=passed,
                value=prev,
                threshold=threshold,
                detail=f"[fallback] {reason}; using previous {prev * 100:.1f}%",
            )

        try:
            eps_data = await self._fundamentals.get_quarterly_eps(ticker, 8)
        except Exception:
            logger.warning("c_filter_data_error", ticker=ticker, exc_info=True)
            fb = _fallback_if_missing("fetch error")
            if fb:
                return fb
            return ScreenResult(
                passed=False,
                detail="Failed to fetch quarterly EPS data",
            )

        # For KR with DART data, we only get 2 quarters (current + YoY).
        # Use those 2 for direct YoY comparison instead of requiring 5.
        if market == "KR" and len(eps_data) == 2:
            current_eps = eps_data[0][1]
            year_ago_eps = eps_data[1][1]

            if year_ago_eps <= 0:
                return ScreenResult(
                    passed=False,
                    value=current_eps,
                    threshold=threshold,
                    detail=f"Prior-year net income ≤ 0 ({year_ago_eps:.0f}억), cannot compute growth",
                )

            growth = (current_eps / year_ago_eps) - 1.0
            passed = growth >= threshold

            return ScreenResult(
                passed=passed,
                value=growth,
                threshold=threshold,
                detail=(
                    f"Quarterly NI growth: {growth * 100:.1f}% "
                    f"(current={current_eps:.0f}억, year-ago={year_ago_eps:.0f}억)"
                    f"{' [HOLD]' if hold_mode else ''}"
                ),
            )

        if len(eps_data) < 2:
            fb = _fallback_if_missing(
                "no DART data" if market == "KR" and len(eps_data) == 0
                else f"insufficient data ({len(eps_data)}q)"
            )
            if fb:
                return fb
            if market == "KR" and len(eps_data) == 0:
                return ScreenResult(
                    passed=False,
                    detail="No DART financial data available",
                )
            return ScreenResult(
                passed=False,
                detail=f"Insufficient quarterly EPS data ({len(eps_data)} quarters, need at least 2)",
            )

        # eps_data is ordered DESC: index 0 = most recent quarter
        # Match by quarter number (e.g., 2025Q4 → find 2024Q4) instead of
        # assuming index [4] is the same quarter last year.
        # This handles gaps in quarterly data correctly.
        current_period = eps_data[0][0]  # e.g., "2025Q4"
        current_eps = eps_data[0][1]

        # Extract quarter number and compute year-ago period
        # Period format: "2025Q4" or "2025Q3" etc.
        try:
            year_str = current_period[:4]
            q_suffix = current_period[4:]  # "Q4", "Q3", etc.
            year_ago_period = f"{int(year_str) - 1}{q_suffix}"  # "2024Q4"
        except (ValueError, IndexError):
            return ScreenResult(
                passed=False,
                detail=f"Cannot parse quarter from period '{current_period}'",
            )

        # Find the matching year-ago quarter in eps_data
        year_ago_eps = None
        for period, eps in eps_data:
            if period == year_ago_period:
                year_ago_eps = eps
                break

        if year_ago_eps is None:
            fb = _fallback_if_missing(f"year-ago {year_ago_period} missing")
            if fb:
                return fb
            return ScreenResult(
                passed=False,
                value=current_eps,
                threshold=threshold,
                detail=f"Year-ago quarter {year_ago_period} not found in data",
            )

        if year_ago_eps <= 0:
            return ScreenResult(
                passed=False,
                value=current_eps,
                threshold=threshold,
                detail=f"Prior-year EPS ≤ 0 ({year_ago_eps:.2f}), cannot compute meaningful growth",
            )

        growth = (current_eps / year_ago_eps) - 1.0
        passed = growth >= threshold

        return ScreenResult(
            passed=passed,
            value=growth,
            threshold=threshold,
            detail=(
                f"Quarterly EPS growth: {growth * 100:.1f}% "
                f"(current={current_eps:.2f} [{current_period}], "
                f"year-ago={year_ago_eps:.2f} [{year_ago_period}])"
                f"{' [HOLD]' if hold_mode else ''}"
            ),
        )

    async def check_a_filter(
        self, ticker: str, *, market: str = "US",
        hold_mode: bool = False, previous_values: dict | None = None,
    ) -> ScreenResult:
        """**A = Annual EPS CAGR** — 5-year compound annual growth ≥ 25% (진입) / ≥ 15% (유지).

        Falls back gracefully when fewer than 5 years are available,
        as long as at least 2 years of data exist.

        Uses DART OpenAPI data for KR market (net income as EPS proxy).
        """
        threshold = (
            CANSLIM_HOLD_ANNUAL_EPS_CAGR if hold_mode
            else CANSLIM_MIN_ANNUAL_EPS_CAGR
        )

        def _fallback_if_missing(reason: str) -> ScreenResult | None:
            if not hold_mode or not previous_values:
                return None
            prev = previous_values.get("annual_eps_cagr")
            if prev is None:
                return None
            passed = prev >= threshold
            return ScreenResult(
                passed=passed,
                value=prev,
                threshold=threshold,
                detail=f"[fallback] {reason}; using previous {prev * 100:.1f}%",
            )

        try:
            eps_data = await self._fundamentals.get_annual_eps(ticker, 5)
        except Exception:
            logger.warning("a_filter_data_error", ticker=ticker, exc_info=True)
            fb = _fallback_if_missing("fetch error")
            if fb:
                return fb
            return ScreenResult(
                passed=False,
                detail="Failed to fetch annual EPS data",
            )

        if len(eps_data) < 2:
            fb = _fallback_if_missing(
                "no DART data" if market == "KR" and len(eps_data) == 0
                else f"insufficient data ({len(eps_data)}y)"
            )
            if fb:
                return fb
            if market == "KR" and len(eps_data) == 0:
                return ScreenResult(
                    passed=False,
                    detail="No DART annual financial data available",
                )
            return ScreenResult(
                passed=False,
                detail=f"Insufficient annual EPS data ({len(eps_data)} years, need ≥ 2)",
            )

        # eps_data is ordered DESC: index 0 = most recent year
        latest_eps = eps_data[0][1]
        oldest_eps = eps_data[-1][1]
        years = len(eps_data) - 1

        if oldest_eps <= 0:
            return ScreenResult(
                passed=False,
                value=latest_eps,
                threshold=threshold,
                detail=f"Base-year EPS ≤ 0 ({oldest_eps:.2f}), cannot compute CAGR",
            )

        if latest_eps <= 0:
            return ScreenResult(
                passed=False,
                value=0.0,
                threshold=threshold,
                detail=f"Latest EPS ≤ 0 ({latest_eps:.2f}), CAGR not meaningful",
            )

        cagr = (latest_eps / oldest_eps) ** (1.0 / years) - 1.0
        passed = cagr >= threshold

        return ScreenResult(
            passed=passed,
            value=cagr,
            threshold=threshold,
            detail=(
                f"Annual EPS CAGR: {cagr * 100:.1f}% over {years}y "
                f"(latest={latest_eps:.2f}, oldest={oldest_eps:.2f})"
                f"{' [HOLD]' if hold_mode else ''}"
            ),
        )

    async def check_n_filter(self, ticker: str, *, market: str = "US") -> ScreenResult:
        """**N = New High** — price within 25% of 52-week high.

        Uses the Minervini trend-template threshold of 75%.
        """
        try:
            high_52w = await self._market.get_52w_high(ticker)
            latest_close = await self._market.get_latest_price(ticker)
        except Exception:
            logger.warning("n_filter_data_error", ticker=ticker, exc_info=True)
            return ScreenResult(
                passed=False,
                detail="Failed to fetch price data for N filter",
            )

        if high_52w is None or latest_close is None:
            return ScreenResult(
                passed=False,
                detail="52-week high or latest close not available",
            )

        if high_52w <= 0:
            return ScreenResult(
                passed=False,
                detail=f"Invalid 52-week high ({high_52w})",
            )

        ratio = latest_close / high_52w
        min_ratio = 0.75
        passed = ratio >= min_ratio

        return ScreenResult(
            passed=passed,
            value=ratio,
            threshold=min_ratio,
            detail=f"Price at {ratio * 100:.1f}% of 52W high",
        )

    async def check_s_filter(self, ticker: str, *, market: str = "US") -> ScreenResult:
        """**S = Supply/Demand** — average daily volume ≥ 500K (US) or ≥ 50K (KR).

        Additionally reports the Up/Down volume ratio as a supplementary
        signal when available.
        """
        # KR market: lower ADV threshold (50K vs 500K for US)
        min_adv = 50_000 if market == "KR" else CANSLIM_MIN_ADV

        try:
            avg_volume = await self._market.get_avg_volume(ticker, 50)
        except Exception:
            logger.warning("s_filter_data_error", ticker=ticker, exc_info=True)
            return ScreenResult(
                passed=False,
                detail="Failed to fetch volume data",
            )

        if avg_volume is None:
            return ScreenResult(
                passed=False,
                detail="Average daily volume data not available",
            )

        passed = avg_volume >= min_adv

        # Supplementary Up/Down volume ratio check
        ud_detail = ""
        try:
            ud_ratio = await self._market.get_up_down_volume_ratio(ticker, 50)
            if ud_ratio is not None:
                ud_signal = "positive" if ud_ratio >= CANSLIM_MIN_UP_DOWN_RATIO else "neutral"
                ud_detail = f", U/D ratio={ud_ratio:.2f} ({ud_signal})"
        except Exception:
            pass  # U/D ratio is supplementary — do not fail the filter

        return ScreenResult(
            passed=passed,
            value=float(avg_volume),
            threshold=float(min_adv),
            detail=f"ADV={avg_volume:,.0f}{ud_detail}",
        )

    async def check_l_filter(
        self, ticker: str, rs_rating: int | None = None, *, market: str = "US",
        hold_mode: bool = False, previous_values: dict | None = None,
    ) -> ScreenResult:
        """**L = Leader** — RS Rating ≥ 80 (진입) / ≥ 75 (유지).

        The RS Rating must be pre-computed and passed in; this filter
        does not calculate it. Hysteresis applied for existing watchlist tickers.
        """
        threshold = CANSLIM_HOLD_RS_RATING if hold_mode else CANSLIM_MIN_RS_RATING

        # Fallback: RS rating missing but we have a previous value (hold_mode only)
        if rs_rating is None:
            if hold_mode and previous_values:
                prev = previous_values.get("rs_rating")
                if prev is not None:
                    passed = prev >= threshold
                    return ScreenResult(
                        passed=passed,
                        value=float(prev),
                        threshold=float(threshold),
                        detail=f"[fallback] RS missing; using previous {prev:.0f}",
                    )
            return ScreenResult(
                passed=False,
                detail="RS rating not available",
            )

        passed = rs_rating >= threshold

        return ScreenResult(
            passed=passed,
            value=float(rs_rating),
            threshold=float(threshold),
            detail=f"RS Rating={rs_rating}{' [HOLD]' if hold_mode else ''}",
        )

    async def check_i_filter(self, ticker: str, *, market: str = "US") -> ScreenResult:
        """**I = Institutional Sponsorship** — ≥ 5 institutional holders."""
        try:
            inst_data = await self._fundamentals.get_institutional_data(ticker)
        except Exception:
            logger.warning("i_filter_data_error", ticker=ticker, exc_info=True)
            return ScreenResult(
                passed=False,
                detail="Failed to fetch institutional data",
            )

        holders_count = inst_data.get("holders_count", 0)
        held_pct = inst_data.get("held_pct", 0.0)

        passed = holders_count >= CANSLIM_MIN_INSTITUTIONAL_HOLDERS

        return ScreenResult(
            passed=passed,
            value=float(holders_count),
            threshold=float(CANSLIM_MIN_INSTITUTIONAL_HOLDERS),
            detail=f"Holders: {holders_count}, Held: {held_pct * 100:.1f}%",
        )

    async def check_additional(self, ticker: str, *, market: str = "US") -> ScreenResult:
        """**Additional filters** — minimum price and max debt-to-equity.

        All sub-checks must pass:
        - Price ≥ $10 (US) or ≥ ₩5,000 (KR)
        - D/E ≤ 2.0  (benefit of the doubt when D/E is unavailable)
        """
        # KR market: min price ₩5,000 vs $10 for US
        min_price = 5_000.0 if market == "KR" else CANSLIM_MIN_PRICE
        currency = "₩" if market == "KR" else "$"

        # ── Price check ──────────────────────────────────────
        try:
            price = await self._market.get_latest_price(ticker)
        except Exception:
            logger.warning("additional_price_error", ticker=ticker, exc_info=True)
            return ScreenResult(
                passed=False,
                detail="Failed to fetch latest price",
            )

        if price is None:
            return ScreenResult(
                passed=False,
                detail="Latest price not available",
            )

        if price < min_price:
            return ScreenResult(
                passed=False,
                value=price,
                threshold=min_price,
                detail=f"Price {currency}{price:,.0f} below minimum {currency}{min_price:,.0f}",
            )

        # ── Debt-to-Equity check ─────────────────────────────
        try:
            de_ratio = await self._fundamentals.get_debt_to_equity(ticker)
        except Exception:
            logger.warning("additional_de_error", ticker=ticker, exc_info=True)
            de_ratio = None

        if de_ratio is not None and de_ratio > CANSLIM_MAX_DEBT_TO_EQUITY:
            return ScreenResult(
                passed=False,
                value=de_ratio,
                threshold=CANSLIM_MAX_DEBT_TO_EQUITY,
                detail=f"D/E ratio {de_ratio:.2f} exceeds max {CANSLIM_MAX_DEBT_TO_EQUITY:.2f}",
            )

        # ── All sub-checks passed ────────────────────────────
        de_detail = f", D/E={de_ratio:.2f}" if de_ratio is not None else ", D/E=N/A"

        return ScreenResult(
            passed=True,
            value=price,
            threshold=min_price,
            detail=f"Price={currency}{price:,.0f}{de_detail}",
        )
