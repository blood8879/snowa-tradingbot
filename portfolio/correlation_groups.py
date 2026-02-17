"""
Correlation group management for position limit enforcement.

Turtle Trading position limits:
  - Single stock: 4 units
  - Closely correlated (same IBD Industry): 6 units
  - Loosely correlated (same GICS Sector): 10 units
  - Total long: 12 units
  - Total short: 12 units
  - Total both: 24 units

Uses yfinance sector/industry data as proxy for IBD groups.
"""

from __future__ import annotations

import structlog

from config.constants import (
    MAX_UNITS_SINGLE,
    MAX_UNITS_CORRELATED,
    MAX_UNITS_LOOSELY_CORRELATED,
    MAX_UNITS_LONG,
    MAX_UNITS_SHORT,
    MAX_UNITS_TOTAL,
)

logger = structlog.get_logger(__name__)


# ════════════════════════════════════════════════════════════════
# Correlation Group Manager
# ════════════════════════════════════════════════════════════════


class CorrelationGroupManager:
    """Tracks sector/industry classifications and enforces position limits.

    Maintains a mapping from tickers to their sector and industry,
    then checks unit-count limits at every level: single stock,
    closely correlated (same industry), loosely correlated (same
    sector), and total portfolio.
    """

    def __init__(self) -> None:
        self._sector_map: dict[str, str] = {}    # ticker → sector
        self._industry_map: dict[str, str] = {}  # ticker → industry

    # ── Registration ─────────────────────────────────────────

    def set_stock_info(self, ticker: str, sector: str, industry: str) -> None:
        """Register sector and industry classification for a ticker.

        Args:
            ticker: Stock ticker symbol.
            sector: GICS sector name (e.g. "Technology").
            industry: IBD-proxy industry name (e.g. "Semiconductors").
        """
        self._sector_map[ticker] = sector
        self._industry_map[ticker] = industry

    # ── Lookups ──────────────────────────────────────────────

    def get_sector(self, ticker: str) -> str | None:
        """Return the sector for *ticker*, or None if unknown.

        Args:
            ticker: Stock ticker symbol.

        Returns:
            Sector name or None.
        """
        return self._sector_map.get(ticker)

    def get_industry(self, ticker: str) -> str | None:
        """Return the industry for *ticker*, or None if unknown.

        Args:
            ticker: Stock ticker symbol.

        Returns:
            Industry name or None.
        """
        return self._industry_map.get(ticker)

    def get_same_industry_tickers(self, ticker: str) -> list[str]:
        """Return all tickers sharing the same industry as *ticker*.

        The result includes *ticker* itself if it is registered.

        Args:
            ticker: Stock ticker symbol.

        Returns:
            List of ticker symbols in the same industry (may be empty).
        """
        industry = self._industry_map.get(ticker)
        if industry is None:
            return []

        return [t for t, ind in self._industry_map.items() if ind == industry]

    def get_same_sector_tickers(self, ticker: str) -> list[str]:
        """Return all tickers sharing the same sector as *ticker*.

        The result includes *ticker* itself if it is registered.

        Args:
            ticker: Stock ticker symbol.

        Returns:
            List of ticker symbols in the same sector (may be empty).
        """
        sector = self._sector_map.get(ticker)
        if sector is None:
            return []

        return [t for t, sec in self._sector_map.items() if sec == sector]

    # ── Limit Enforcement ────────────────────────────────────

    def check_correlation_limits(
        self,
        ticker: str,
        current_units: dict[str, int],
    ) -> dict:
        """Check all Turtle-style position limits for adding a unit.

        Evaluates four levels of limits:
            1. **Single**: units for *ticker* < MAX_UNITS_SINGLE (4).
            2. **Correlated**: total units in same industry < MAX_UNITS_CORRELATED (6).
            3. **Loosely correlated**: total units in same sector < MAX_UNITS_LOOSELY_CORRELATED (10).
            4. **Total long**: sum of ALL units < MAX_UNITS_LONG (12).

        Args:
            ticker: The stock to check before adding a new unit.
            current_units: Mapping of ticker → unit count for all
                currently open positions.

        Returns:
            Dict with keys:
                - ``allowed`` (bool): True if all limits permit a new unit.
                - ``violations`` (list[str]): Human-readable limit violations.
                - ``single_used`` (int): Units already held for *ticker*.
                - ``correlated_used`` (int): Total units in same industry.
                - ``sector_used`` (int): Total units in same sector.
                - ``total_used`` (int): Sum of all units across portfolio.
        """
        violations: list[str] = []

        # Single stock limit
        single_used = current_units.get(ticker, 0)
        if single_used >= MAX_UNITS_SINGLE:
            violations.append(
                f"Single stock limit: {single_used}/{MAX_UNITS_SINGLE} units"
            )

        # Closely correlated (same industry) limit
        same_industry = self.get_same_industry_tickers(ticker)
        correlated_used = sum(
            current_units.get(t, 0) for t in same_industry
        )
        if correlated_used >= MAX_UNITS_CORRELATED:
            industry = self._industry_map.get(ticker, "Unknown")
            violations.append(
                f"Correlated limit ({industry}): "
                f"{correlated_used}/{MAX_UNITS_CORRELATED} units"
            )

        # Loosely correlated (same sector) limit
        same_sector = self.get_same_sector_tickers(ticker)
        sector_used = sum(
            current_units.get(t, 0) for t in same_sector
        )
        if sector_used >= MAX_UNITS_LOOSELY_CORRELATED:
            sector = self._sector_map.get(ticker, "Unknown")
            violations.append(
                f"Sector limit ({sector}): "
                f"{sector_used}/{MAX_UNITS_LOOSELY_CORRELATED} units"
            )

        # Total long limit
        total_used = sum(current_units.values())
        if total_used >= MAX_UNITS_LONG:
            violations.append(
                f"Total long limit: {total_used}/{MAX_UNITS_LONG} units"
            )

        allowed = len(violations) == 0

        if not allowed:
            logger.debug(
                "correlation_limit_hit",
                ticker=ticker,
                violations=violations,
                single_used=single_used,
                correlated_used=correlated_used,
                sector_used=sector_used,
                total_used=total_used,
            )

        return {
            "allowed": allowed,
            "violations": violations,
            "single_used": single_used,
            "correlated_used": correlated_used,
            "sector_used": sector_used,
            "total_used": total_used,
        }
