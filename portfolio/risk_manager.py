"""
Risk manager — enforces all Turtle Trading position limits.

Checks:
  - Single stock: 4 units max
  - Closely correlated (same industry): 6 units max
  - Loosely correlated (same sector): 10 units max
  - Total long: 12 units max
  - Account equity limits per position

Coordinates with CorrelationGroupManager and PositionManager.
"""

from __future__ import annotations

import structlog

from config.constants import (
    MAX_UNITS_SINGLE,
    MAX_UNITS_CORRELATED,
    MAX_UNITS_LOOSELY_CORRELATED,
    MAX_UNITS_LONG,
    MAX_UNITS_TOTAL,
    MAX_SINGLE_POSITION_PCT,
)
from portfolio.position_manager import PositionManager
from portfolio.correlation_groups import CorrelationGroupManager

logger = structlog.get_logger(__name__)


# ════════════════════════════════════════════════════════════════
# Risk Manager
# ════════════════════════════════════════════════════════════════


class RiskManager:
    """Enforces Turtle Trading position and portfolio risk limits.

    Every potential entry or pyramid add is evaluated against:
        1. Single stock unit limit (4 units).
        2. Closely correlated group limit (same industry, 6 units).
        3. Loosely correlated group limit (same sector, 10 units).
        4. Total long direction limit (12 units).
        5. Per-position equity concentration limit.

    The manager is stateless itself — it reads live data from
    ``PositionManager`` and ``CorrelationGroupManager`` on each call.
    """

    def __init__(
        self,
        position_manager: PositionManager,
        correlation_groups: CorrelationGroupManager,
    ) -> None:
        self._pm = position_manager
        self._cg = correlation_groups

    # ── Entry Checks ─────────────────────────────────────────

    async def can_enter_position(
        self,
        ticker: str,
        shares: int,
        entry_price: float,
        account_equity: float,
    ) -> dict:
        """Full risk check for a brand-new position entry.

        Validates that opening a new position (unit 1) would not
        breach any Turtle Trading limit or equity constraint.

        Args:
            ticker: Stock symbol to enter.
            shares: Number of shares for the first unit.
            entry_price: Planned entry price.
            account_equity: Current total account equity.

        Returns:
            Dict with keys:
                - ``allowed`` (bool): True if entry is permitted.
                - ``violations`` (list[str]): Human-readable violation messages.
                - ``details`` (dict): Breakdown of limit usage.
        """
        violations: list[str] = []
        current_units = await self._count_units_by_group()

        # Check if a position is already open for this ticker
        existing = await self._pm.get_position(ticker)
        if existing is not None:
            violations.append(
                f"Position already open for {ticker} "
                f"({existing.unit_count} units)"
            )

        # Correlation-based limits via CorrelationGroupManager
        corr_check = self._cg.check_correlation_limits(ticker, current_units)
        violations.extend(corr_check["violations"])

        # Per-position equity concentration
        position_value = shares * entry_price
        max_allowed_value = account_equity * MAX_SINGLE_POSITION_PCT
        if position_value > max_allowed_value:
            violations.append(
                f"Position value ${position_value:,.2f} exceeds "
                f"{MAX_SINGLE_POSITION_PCT:.0%} of equity "
                f"(${max_allowed_value:,.2f})"
            )

        allowed = len(violations) == 0

        details = {
            "ticker": ticker,
            "shares": shares,
            "entry_price": entry_price,
            "position_value": position_value,
            "max_position_value": max_allowed_value,
            "single_used": corr_check["single_used"],
            "correlated_used": corr_check["correlated_used"],
            "sector_used": corr_check["sector_used"],
            "total_used": corr_check["total_used"],
        }

        if not allowed:
            logger.warning(
                "entry_blocked",
                violations=violations,
                **details,
            )
        else:
            logger.debug(
                "entry_allowed",
                **details,
            )

        return {
            "allowed": allowed,
            "violations": violations,
            "details": details,
        }

    async def can_add_unit(
        self,
        ticker: str,
        shares: int,
        entry_price: float,
        account_equity: float,
    ) -> dict:
        """Check whether a pyramid unit addition is allowed.

        Validates adding a new unit to an existing position against
        all Turtle Trading limits and equity constraints.

        Args:
            ticker: Stock symbol of the existing position.
            shares: Number of shares for the new unit.
            entry_price: Planned entry price for the add.
            account_equity: Current total account equity.

        Returns:
            Dict with keys:
                - ``allowed`` (bool): True if the add is permitted.
                - ``violations`` (list[str]): Human-readable violation messages.
                - ``details`` (dict): Breakdown of limit usage.
        """
        violations: list[str] = []
        current_units = await self._count_units_by_group()

        # Verify the position actually exists
        existing = await self._pm.get_position(ticker)
        if existing is None:
            violations.append(f"No open position for {ticker}")
            return {
                "allowed": False,
                "violations": violations,
                "details": {"ticker": ticker},
            }

        # Single stock limit (check against MAX_UNITS_SINGLE for the add)
        ticker_units = current_units.get(ticker, 0)
        if ticker_units >= MAX_UNITS_SINGLE:
            violations.append(
                f"Single stock limit: {ticker_units}/{MAX_UNITS_SINGLE} units"
            )

        # Correlation-based limits via CorrelationGroupManager
        corr_check = self._cg.check_correlation_limits(ticker, current_units)
        # Only add violations not already caught by the single-stock check
        for v in corr_check["violations"]:
            if v not in violations:
                violations.append(v)

        # Per-position equity concentration (cumulative with existing cost)
        new_cost = shares * entry_price
        cumulative_value = existing.total_cost + new_cost
        max_allowed_value = account_equity * MAX_SINGLE_POSITION_PCT
        if cumulative_value > max_allowed_value:
            violations.append(
                f"Cumulative position value ${cumulative_value:,.2f} exceeds "
                f"{MAX_SINGLE_POSITION_PCT:.0%} of equity "
                f"(${max_allowed_value:,.2f})"
            )

        allowed = len(violations) == 0

        details = {
            "ticker": ticker,
            "shares": shares,
            "entry_price": entry_price,
            "existing_units": ticker_units,
            "existing_cost": existing.total_cost,
            "new_cost": new_cost,
            "cumulative_value": cumulative_value,
            "max_position_value": max_allowed_value,
            "single_used": corr_check["single_used"],
            "correlated_used": corr_check["correlated_used"],
            "sector_used": corr_check["sector_used"],
            "total_used": corr_check["total_used"],
        }

        if not allowed:
            logger.warning(
                "pyramid_blocked",
                violations=violations,
                **details,
            )
        else:
            logger.debug(
                "pyramid_allowed",
                **details,
            )

        return {
            "allowed": allowed,
            "violations": violations,
            "details": details,
        }

    # ── Portfolio Summary ────────────────────────────────────

    async def get_risk_summary(self, account_equity: float) -> dict:
        """Build a snapshot of current portfolio risk utilization.

        Args:
            account_equity: Current total account equity.

        Returns:
            Dict with keys:
                - ``total_units`` (int): Sum of units across all positions.
                - ``max_units`` (int): Maximum allowed total units.
                - ``positions_count`` (int): Number of open positions.
                - ``total_exposure`` (float): Sum of total_cost across open positions.
                - ``exposure_pct`` (float): total_exposure / account_equity.
                - ``by_sector`` (dict): sector → unit count.
                - ``by_industry`` (dict): industry → unit count.
        """
        positions = await self._pm.get_open_positions()
        current_units = await self._count_units_by_group()

        total_units = sum(current_units.values())
        total_exposure = sum(p.total_cost for p in positions)
        exposure_pct = (total_exposure / account_equity) if account_equity > 0 else 0.0

        # Build sector and industry unit aggregations
        by_sector: dict[str, int] = {}
        by_industry: dict[str, int] = {}

        for position in positions:
            unit_count = current_units.get(position.ticker, 0)

            sector = position.sector or "Unknown"
            by_sector[sector] = by_sector.get(sector, 0) + unit_count

            industry = position.industry or "Unknown"
            by_industry[industry] = by_industry.get(industry, 0) + unit_count

        return {
            "total_units": total_units,
            "max_units": MAX_UNITS_LONG,
            "positions_count": len(positions),
            "total_exposure": total_exposure,
            "exposure_pct": exposure_pct,
            "by_sector": by_sector,
            "by_industry": by_industry,
        }

    # ── Internal Helpers ─────────────────────────────────────

    async def _count_units_by_group(self) -> dict[str, int]:
        """Build a mapping of ticker → unit count from open positions.

        Queries all open positions via PositionManager and counts
        the number of units loaded for each.

        Returns:
            Dict mapping ticker symbol to its current unit count.
        """
        positions = await self._pm.get_open_positions()
        return {p.ticker: p.unit_count for p in positions}
