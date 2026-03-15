"""
Position manager — CRUD operations for positions and units.

Handles opening/closing positions, adding pyramid units,
updating stops, and syncing with the SQLite database.
"""

from __future__ import annotations

from datetime import datetime, timezone

import structlog

from core.database import Database
from core.models import (
    CloseReason,
    Position,
    PositionStatus,
    TradingSystem,
    Unit,
)

logger = structlog.get_logger(__name__)


# ════════════════════════════════════════════════════════════════
# Position Manager
# ════════════════════════════════════════════════════════════════


class PositionManager:
    """
    Manages the lifecycle of trading positions and their pyramid units.

    All writes go through the SQLite database (raw SQL via aiosqlite).
    Position objects are plain dataclasses — no ORM magic.
    """

    def __init__(self, db: Database) -> None:
        self._db = db

    # ── Open / Close ─────────────────────────────────────────

    async def open_position(
        self,
        ticker: str,
        system: str,
        entry_price: float,
        shares: int,
        n_value: float,
        stop_price: float,
        sector: str | None = None,
        industry: str | None = None,
        market: str = "US",
    ) -> int:
        """Create a new position with its first entry unit.

        Inserts a row into ``positions`` and the initial unit into ``units``.

        Args:
            ticker: Stock symbol (e.g. "AAPL").
            system: Trading system ("S1" or "S2").
            entry_price: Price of the first unit entry.
            shares: Number of shares for the first unit.
            n_value: ATR(N) at the time of entry.
            stop_price: Initial stop-loss price.
            sector: GICS sector (for loosely-correlated limit).
            industry: IBD industry (for closely-correlated limit).
            market: Market identifier ("US" or "KR").

        Returns:
            The auto-generated position id.
        """
        now = datetime.now(timezone.utc).isoformat()
        total_cost = entry_price * shares

        conn = self._db.conn

        cursor = await conn.execute(
            """
            INSERT INTO positions
                (ticker, system, status,
                 total_shares, total_cost, avg_entry_price,
                 current_stop_price, n_at_entry,
                 sector, industry, opened_at, market)
            VALUES (?, ?, 'OPEN', ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                ticker, system,
                shares, total_cost, entry_price,
                stop_price, n_value,
                sector, industry, now, market,
            ),
        )
        position_id: int = cursor.lastrowid  # type: ignore[assignment]

        await conn.execute(
            """
            INSERT INTO units
                (position_id, unit_number,
                 entry_price, shares,
                 entry_stop_price, current_stop_price,
                 entered_at)
            VALUES (?, 1, ?, ?, ?, ?, ?)
            """,
            (position_id, entry_price, shares, stop_price, stop_price, now),
        )
        await conn.commit()

        logger.info(
            "position_opened",
            position_id=position_id,
            ticker=ticker,
            system=system,
            entry_price=entry_price,
            shares=shares,
            stop_price=stop_price,
        )
        return position_id

    async def close_position(
        self,
        position_id: int,
        reason: str,
        exit_price: float,
    ) -> float:
        """Close a position and record the realized P&L.

        Args:
            position_id: ID of the position to close.
            reason: Close reason string (e.g. "STOP_LOSS").
            exit_price: Exit (fill) price.

        Returns:
            Realized P&L for the position.
        """
        now = datetime.now(timezone.utc).isoformat()
        conn = self._db.conn

        cursor = await conn.execute(
            "SELECT total_shares, total_cost, ticker FROM positions WHERE id = ?",
            (position_id,),
        )
        row = await cursor.fetchone()
        if row is None:
            raise ValueError(f"Position {position_id} not found")

        total_shares, total_cost, ticker = row

        # 유닛 기반 total_cost 재검증 (sync_positions가 브로커 avg_price로
        # 덮어쓴 경우 positions.total_cost가 부정확할 수 있음)
        unit_cursor = await conn.execute(
            "SELECT SUM(shares * entry_price) FROM units WHERE position_id = ?",
            (position_id,),
        )
        unit_row = await unit_cursor.fetchone()
        unit_cost = unit_row[0] if unit_row and unit_row[0] else 0.0
        if unit_cost > 0 and abs(unit_cost - total_cost) > 1.0:
            logger.warning(
                "close_position_cost_mismatch_corrected",
                position_id=position_id,
                ticker=ticker,
                positions_total_cost=total_cost,
                units_total_cost=unit_cost,
            )
            total_cost = unit_cost

        realized_pnl = (exit_price * total_shares) - total_cost

        await conn.execute(
            """
            UPDATE positions
            SET status = 'CLOSED',
                close_reason = ?,
                closed_at = ?,
                realized_pnl = ?
            WHERE id = ?
            """,
            (reason, now, realized_pnl, position_id),
        )
        await conn.commit()

        logger.info(
            "position_closed",
            position_id=position_id,
            ticker=ticker,
            reason=reason,
            exit_price=exit_price,
            realized_pnl=realized_pnl,
        )
        return realized_pnl

    # ── Fill Updates ────────────────────────────────────────

    async def update_entry_fill(
        self,
        position_id: int,
        filled_shares: int,
        fill_price: float,
    ) -> None:
        """Update position's first unit with cumulative fill data from broker."""
        conn = self._db.conn

        await conn.execute(
            """
            UPDATE units
            SET shares = ?, entry_price = ?
            WHERE position_id = ? AND unit_number = 1
            """,
            (filled_shares, fill_price, position_id),
        )

        cursor = await conn.execute(
            """
            SELECT SUM(shares), SUM(shares * entry_price)
            FROM units WHERE position_id = ?
            """,
            (position_id,),
        )
        row = await cursor.fetchone()
        total_shares = row[0] or 0
        total_cost = row[1] or 0.0
        avg_entry = total_cost / total_shares if total_shares > 0 else 0.0

        await conn.execute(
            """
            UPDATE positions
            SET total_shares = ?, total_cost = ?, avg_entry_price = ?
            WHERE id = ?
            """,
            (total_shares, total_cost, avg_entry, position_id),
        )
        await conn.commit()

        logger.info(
            "entry_fill_updated",
            position_id=position_id,
            filled_shares=filled_shares,
            fill_price=fill_price,
            total_shares=total_shares,
        )

    async def update_pyramid_fill(
        self,
        position_id: int,
        filled_shares: int,
        fill_price: float,
    ) -> None:
        """Update latest pyramid unit with cumulative fill data from broker."""
        conn = self._db.conn

        cursor = await conn.execute(
            """
            SELECT unit_number FROM units
            WHERE position_id = ?
            ORDER BY unit_number DESC LIMIT 1
            """,
            (position_id,),
        )
        row = await cursor.fetchone()
        if row is None:
            raise ValueError(f"No units found for position {position_id}")
        unit_number = row[0]

        await conn.execute(
            """
            UPDATE units
            SET shares = ?, entry_price = ?
            WHERE position_id = ? AND unit_number = ?
            """,
            (filled_shares, fill_price, position_id, unit_number),
        )

        cursor = await conn.execute(
            """
            SELECT SUM(shares), SUM(shares * entry_price)
            FROM units WHERE position_id = ?
            """,
            (position_id,),
        )
        row = await cursor.fetchone()
        total_shares = row[0] or 0
        total_cost = row[1] or 0.0
        avg_entry = total_cost / total_shares if total_shares > 0 else 0.0

        await conn.execute(
            """
            UPDATE positions
            SET total_shares = ?, total_cost = ?, avg_entry_price = ?
            WHERE id = ?
            """,
            (total_shares, total_cost, avg_entry, position_id),
        )
        await conn.commit()

        logger.info(
            "pyramid_fill_updated",
            position_id=position_id,
            unit_number=unit_number,
            filled_shares=filled_shares,
            fill_price=fill_price,
            total_shares=total_shares,
        )

    async def reduce_shares(
        self,
        position_id: int,
        filled_shares: int,
    ) -> None:
        """Reduce position share count after partial sell fill."""
        conn = self._db.conn

        cursor = await conn.execute(
            "SELECT total_shares, total_cost, avg_entry_price FROM positions WHERE id = ?",
            (position_id,),
        )
        row = await cursor.fetchone()
        if row is None:
            return

        old_shares, old_cost, avg_price = row
        remaining = max(0, old_shares - filled_shares)
        remaining_cost = remaining * avg_price if remaining > 0 else 0.0

        await conn.execute(
            """
            UPDATE positions
            SET total_shares = ?, total_cost = ?
            WHERE id = ?
            """,
            (remaining, remaining_cost, position_id),
        )
        await conn.commit()

        logger.info(
            "position_shares_reduced",
            position_id=position_id,
            old_shares=old_shares,
            sold_shares=filled_shares,
            remaining=remaining,
        )

    # ── Pyramid Units ────────────────────────────────────────

    async def add_unit(
        self,
        position_id: int,
        entry_price: float,
        shares: int,
        stop_price: float,
    ) -> int:
        """Add a pyramid unit to an existing position.

        Updates position aggregates (total_shares, total_cost,
        avg_entry_price, current_stop_price) and inserts the new unit.

        Args:
            position_id: ID of the position to add to.
            entry_price: Price of the new unit entry.
            shares: Number of shares for this unit.
            stop_price: New stop-loss price (applies to all units).

        Returns:
            The auto-generated unit id.
        """
        now = datetime.now(timezone.utc).isoformat()
        conn = self._db.conn

        # Determine next unit number
        cursor = await conn.execute(
            "SELECT COUNT(*) FROM units WHERE position_id = ?",
            (position_id,),
        )
        row = await cursor.fetchone()
        unit_number = (row[0] if row else 0) + 1

        # Insert the new unit first, then recalculate aggregates from all units
        # (sync_positions가 먼저 position aggregates를 업데이트했을 수 있으므로
        #  incremental 방식 대신 units 테이블 기반 재계산으로 중복 방지)

        # Insert the new unit
        cursor = await conn.execute(
            """
            INSERT INTO units
                (position_id, unit_number,
                 entry_price, shares,
                 entry_stop_price, current_stop_price,
                 entered_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (position_id, unit_number, entry_price, shares, stop_price, stop_price, now),
        )
        unit_id: int = cursor.lastrowid  # type: ignore[assignment]

        # Recalculate position aggregates from all units
        cursor = await conn.execute(
            "SELECT SUM(shares), SUM(shares * entry_price) FROM units WHERE position_id = ?",
            (position_id,),
        )
        agg_row = await cursor.fetchone()
        new_total_shares = agg_row[0] or 0
        new_total_cost = agg_row[1] or 0.0
        new_avg_entry = new_total_cost / new_total_shares if new_total_shares > 0 else 0.0

        # Update position aggregates
        await conn.execute(
            """
            UPDATE positions
            SET total_shares = ?,
                total_cost = ?,
                avg_entry_price = ?,
                current_stop_price = ?
            WHERE id = ?
            """,
            (new_total_shares, new_total_cost, new_avg_entry, stop_price, position_id),
        )
        await conn.commit()

        logger.info(
            "unit_added",
            position_id=position_id,
            unit_number=unit_number,
            entry_price=entry_price,
            shares=shares,
            stop_price=stop_price,
        )
        return unit_id

    # ── Stop Updates ─────────────────────────────────────────

    async def update_stop(self, position_id: int, new_stop: float) -> None:
        """Update the stop-loss price for a position and all its units.

        Stops can only move UP (tighten). If ``new_stop`` is not higher
        than the current stop, the update is silently skipped.

        Args:
            position_id: ID of the position to update.
            new_stop: New stop-loss price.
        """
        conn = self._db.conn

        cursor = await conn.execute(
            "SELECT current_stop_price FROM positions WHERE id = ?",
            (position_id,),
        )
        row = await cursor.fetchone()
        if row is None:
            raise ValueError(f"Position {position_id} not found")

        current_stop = row[0]
        if new_stop <= current_stop:
            logger.debug(
                "stop_not_raised",
                position_id=position_id,
                current_stop=current_stop,
                requested_stop=new_stop,
            )
            return

        await conn.execute(
            "UPDATE positions SET current_stop_price = ? WHERE id = ?",
            (new_stop, position_id),
        )
        await conn.execute(
            "UPDATE units SET current_stop_price = ? WHERE position_id = ?",
            (new_stop, position_id),
        )
        await conn.commit()

        logger.info(
            "stop_updated",
            position_id=position_id,
            old_stop=current_stop,
            new_stop=new_stop,
        )

    # ── Queries ──────────────────────────────────────────────

    async def get_open_positions(self) -> list[Position]:
        """Return all open positions with their units loaded.

        Returns:
            List of ``Position`` dataclass instances (status=OPEN).
        """
        conn = self._db.conn

        cursor = await conn.execute(
            "SELECT * FROM positions WHERE status = 'OPEN'"
        )
        rows = await cursor.fetchall()

        positions: list[Position] = []
        for row in rows:
            position = self._row_to_position(row)
            position.units = await self.get_all_units(position.id)  # type: ignore[arg-type]
            positions.append(position)

        return positions

    async def get_position(self, ticker: str) -> Position | None:
        """Get the open position for a ticker, if one exists.

        Args:
            ticker: Stock symbol.

        Returns:
            ``Position`` with units loaded, or ``None``.
        """
        conn = self._db.conn

        cursor = await conn.execute(
            "SELECT * FROM positions WHERE ticker = ? AND status = 'OPEN'",
            (ticker,),
        )
        row = await cursor.fetchone()
        if row is None:
            return None

        position = self._row_to_position(row)
        position.units = await self.get_all_units(position.id)  # type: ignore[arg-type]
        return position

    async def get_position_by_id(self, position_id: int) -> Position | None:
        """Load a position (with units) by its database ID.

        Args:
            position_id: Position primary key.

        Returns:
            ``Position`` with units loaded, or ``None``.
        """
        conn = self._db.conn

        cursor = await conn.execute(
            "SELECT * FROM positions WHERE id = ?",
            (position_id,),
        )
        row = await cursor.fetchone()
        if row is None:
            return None

        position = self._row_to_position(row)
        position.units = await self.get_all_units(position_id)
        return position

    async def get_all_units(self, position_id: int) -> list[Unit]:
        """Return all units for a position, ordered by unit number.

        Args:
            position_id: Position primary key.

        Returns:
            List of ``Unit`` dataclass instances.
        """
        conn = self._db.conn

        cursor = await conn.execute(
            "SELECT * FROM units WHERE position_id = ? ORDER BY unit_number",
            (position_id,),
        )
        rows = await cursor.fetchall()
        return [self._row_to_unit(row) for row in rows]

    async def get_total_units_count(self) -> int:
        """Count all units across every open position.

        Returns:
            Total number of active units.
        """
        conn = self._db.conn

        cursor = await conn.execute(
            """
            SELECT COALESCE(SUM(unit_count), 0)
            FROM (
                SELECT COUNT(*) AS unit_count
                FROM units u
                JOIN positions p ON u.position_id = p.id
                WHERE p.status = 'OPEN'
                GROUP BY u.position_id
            )
            """,
        )
        row = await cursor.fetchone()
        return row[0] if row else 0

    # ── Row → Dataclass mappers ──────────────────────────────

    @staticmethod
    def _row_to_position(row: tuple) -> Position:
        """Convert a raw SQLite row to a Position dataclass.

        Column order must match ``SELECT * FROM positions``:
            id, ticker, system, status,
            total_shares, total_cost, avg_entry_price,
            current_stop_price, n_at_entry,
            sector, industry,
            opened_at, closed_at, close_reason, realized_pnl,
            market
        """
        return Position(
            id=row[0],
            ticker=row[1],
            system=TradingSystem(row[2]),
            status=PositionStatus(row[3]),
            total_shares=row[4],
            total_cost=row[5],
            avg_entry_price=row[6],
            current_stop_price=row[7],
            n_at_entry=row[8],
            sector=row[9],
            industry=row[10],
            opened_at=row[11],
            closed_at=row[12],
            close_reason=CloseReason(row[13]) if row[13] else None,
            realized_pnl=row[14],
            market=row[15] if len(row) > 15 else "US",
        )

    @staticmethod
    def _row_to_unit(row: tuple) -> Unit:
        """Convert a raw SQLite row to a Unit dataclass.

        Column order must match ``SELECT * FROM units``:
            id, position_id, unit_number,
            entry_price, shares,
            entry_stop_price, current_stop_price,
            entered_at
        """
        return Unit(
            id=row[0],
            position_id=row[1],
            unit_number=row[2],
            entry_price=row[3],
            shares=row[4],
            entry_stop_price=row[5],
            current_stop_price=row[6],
            entered_at=row[7],
        )
