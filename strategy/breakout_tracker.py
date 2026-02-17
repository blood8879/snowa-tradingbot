"""
Breakout history tracker for System 1 filter.

System 1 entry filter: skip if the previous breakout was profitable.
This module tracks breakout events and determines hypothetical outcomes
(whether a skipped breakout "would have been" a winner).

Uses database for persistence — NOT a pure function module.
"""
from __future__ import annotations

from datetime import datetime

import structlog

from core.database import Database
from core.models import TradingSystem

logger = structlog.get_logger(__name__)


class BreakoutTracker:
    """System 1 돌파 이력 추적 및 필터 판단."""

    def __init__(self, db: Database) -> None:
        self._db = db

    # ────────────────────────────────────────────────────────────
    # Record a new breakout
    # ────────────────────────────────────────────────────────────

    async def record_breakout(
        self,
        ticker: str,
        system: str,
        breakout_price: float,
        was_entered: bool,
    ) -> int:
        """Record a new breakout event in the ``breakout_history`` table.

        Args:
            ticker: Stock ticker symbol.
            system: Trading system (``"S1"`` or ``"S2"``).
            breakout_price: Price at which the breakout occurred.
            was_entered: Whether the position was actually entered
                (False if the System 1 filter skipped it).

        Returns:
            The ``ROWID`` of the newly inserted record.
        """
        now = datetime.utcnow().isoformat()
        cursor = await self._db.conn.execute(
            """
            INSERT INTO breakout_history
                (ticker, system, breakout_date, breakout_price, was_actually_entered)
            VALUES (?, ?, ?, ?, ?)
            """,
            (ticker, system, now, breakout_price, int(was_entered)),
        )
        await self._db.conn.commit()

        row_id = cursor.lastrowid
        logger.info(
            "breakout_recorded",
            ticker=ticker,
            system=system,
            breakout_price=breakout_price,
            was_entered=was_entered,
            id=row_id,
        )
        return row_id  # type: ignore[return-value]

    # ────────────────────────────────────────────────────────────
    # Query last breakout outcome
    # ────────────────────────────────────────────────────────────

    async def was_last_breakout_winner(self, ticker: str) -> bool | None:
        """Check if the most recent S1 breakout for *ticker* was profitable.

        Used by the System 1 entry filter: when the previous breakout
        was a winner, the next S1 breakout is *skipped*.

        Args:
            ticker: Stock ticker symbol.

        Returns:
            True if the last S1 breakout was a winner, False if it was
            a loser, or None if there is no breakout history for this
            ticker.
        """
        cursor = await self._db.conn.execute(
            """
            SELECT would_have_been_winner
            FROM breakout_history
            WHERE ticker = ? AND system = 'S1'
            ORDER BY breakout_date DESC
            LIMIT 1
            """,
            (ticker,),
        )
        row = await cursor.fetchone()

        if row is None or row[0] is None:
            return None
        return bool(row[0])

    # ────────────────────────────────────────────────────────────
    # Update breakout outcome
    # ────────────────────────────────────────────────────────────

    async def update_breakout_outcome(
        self,
        breakout_id: int,
        was_winner: bool,
        exit_price: float,
        exit_date: str,
    ) -> None:
        """Update a breakout record with its hypothetical outcome.

        Called after a skipped breakout's hypothetical trade resolves
        (either the simulated position hits a stop or a Donchian exit).

        Args:
            breakout_id: Row ``id`` in the ``breakout_history`` table.
            was_winner: Whether the hypothetical trade was profitable.
            exit_price: The price at which the hypothetical exit occurred.
            exit_date: ISO-8601 date string of the hypothetical exit.
        """
        await self._db.conn.execute(
            """
            UPDATE breakout_history
            SET would_have_been_winner = ?,
                hypothetical_exit_price = ?,
                hypothetical_exit_date = ?
            WHERE id = ?
            """,
            (int(was_winner), exit_price, exit_date, breakout_id),
        )
        await self._db.conn.commit()

        logger.info(
            "breakout_outcome_updated",
            breakout_id=breakout_id,
            was_winner=was_winner,
            exit_price=exit_price,
            exit_date=exit_date,
        )

    # ────────────────────────────────────────────────────────────
    # Hypothetical evaluation
    # ────────────────────────────────────────────────────────────

    async def evaluate_hypothetical(
        self,
        ticker: str,
        breakout_price: float,
        current_price: float,
        donchian_lower_10: float,
    ) -> bool | None:
        """Determine if a hypothetical (skipped) breakout would have been a winner.

        Simulates entering at *breakout_price* and exiting at the
        current 10-day low (System 1 exit level).

        Args:
            ticker: Stock ticker symbol (for logging context).
            breakout_price: The price at which the skipped entry
                would have occurred.
            current_price: Current stock price (unused in the
                calculation but available for extended logic).
            donchian_lower_10: Current 10-day low — the hypothetical
                exit price.

        Returns:
            True if the hypothetical trade is a winner
            (``donchian_lower_10 > breakout_price``), False otherwise.
        """
        is_winner = donchian_lower_10 > breakout_price

        logger.debug(
            "hypothetical_evaluated",
            ticker=ticker,
            breakout_price=breakout_price,
            donchian_lower_10=donchian_lower_10,
            is_winner=is_winner,
        )
        return is_winner

    # ────────────────────────────────────────────────────────────
    # Recent breakout history
    # ────────────────────────────────────────────────────────────

    async def get_recent_breakouts(
        self,
        ticker: str,
        limit: int = 5,
    ) -> list[dict]:
        """Get recent breakout history for a ticker.

        Args:
            ticker: Stock ticker symbol.
            limit: Maximum number of records to return (default 5).

        Returns:
            A list of dicts, each representing a row from the
            ``breakout_history`` table (newest first).
        """
        cursor = await self._db.conn.execute(
            """
            SELECT *
            FROM breakout_history
            WHERE ticker = ?
            ORDER BY breakout_date DESC
            LIMIT ?
            """,
            (ticker, limit),
        )
        columns = [desc[0] for desc in cursor.description]
        rows = await cursor.fetchall()

        return [dict(zip(columns, row)) for row in rows]
