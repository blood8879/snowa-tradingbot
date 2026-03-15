"""
IBD Market Direction — Standalone Logging Module.

Tracks IBD-style market status for SPY and QQQ:
  CONFIRMED_UPTREND → UPTREND_UNDER_PRESSURE → MARKET_IN_CORRECTION → RALLY_ATTEMPT

This module is LOGGING ONLY and does NOT affect trading decisions.
It runs daily in post_market (US only) and writes to:
  - ibd_market_direction   (one row per date × ticker)
  - ibd_distribution_days  (distribution / stalling / FTD days)

References:
  config/constants.py  — all IBD_* thresholds
  core/models.py       — IBDMarketState, IBDDistributionDay
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import structlog

from config.constants import (
    IBD_CORRECTION_THRESHOLD,
    IBD_DISTRIBUTION_MIN_DECLINE,
    IBD_DISTRIBUTION_RALLY_EXPIRE,
    IBD_DISTRIBUTION_WINDOW,
    IBD_FTD_EARLIEST_DAY,
    IBD_FTD_FRAGILE_DAYS,
    IBD_FTD_LATEST_DAY,
    IBD_FTD_MIN_GAIN,
    IBD_INDEXES_US,
    IBD_INDEXES_KR,
    IBD_LOOKBACK_DAYS,
    IBD_PRESSURE_THRESHOLD,
    IBD_STALL_CLOSE_RANGE_MAX,
    IBD_STALL_MAX_COUNT,
    IBD_STALL_MAX_GAIN,
    IBD_STALL_MIN_GAIN,
    IBD_STALL_VOLUME_RATIO,
)
from core.database import Database
from core.models import IBDDistributionDay, IBDMarketState, IBDMarketStatus
from data.price_cache import PriceCache

logger = structlog.get_logger(__name__)

# Status severity order (lower = better)
_STATUS_RANK: dict[str, int] = {
    IBDMarketStatus.CONFIRMED_UPTREND.value: 0,
    IBDMarketStatus.UPTREND_UNDER_PRESSURE.value: 1,
    IBDMarketStatus.RALLY_ATTEMPT.value: 2,
    IBDMarketStatus.MARKET_IN_CORRECTION.value: 3,
}


def _worse_status(a: str, b: str) -> str:
    """Return the worse (higher-severity) of two IBD status strings."""
    return a if _STATUS_RANK.get(a, 99) >= _STATUS_RANK.get(b, 99) else b


class IBDMarketDirection:
    """Compute and persist IBD Market Direction for US (SPY/QQQ) or KR (KODEX200/KOSDAQ150)."""

    def __init__(self, db: Database, price_cache: PriceCache, *, market: str = "US") -> None:
        self._db = db
        self._price_cache = price_cache
        self._market = market
        self._indexes = IBD_INDEXES_US if market == "US" else IBD_INDEXES_KR

    # ── Public ────────────────────────────────────────────────────

    async def update(self) -> dict[str, IBDMarketState]:
        """Run IBD update for all indexes and return per-ticker states.

        Returns:
            dict mapping ticker → IBDMarketState, plus "overall" key
            whose status is the worse of all tracked indexes.
        """
        results: dict[str, IBDMarketState] = {}

        for ticker in self._indexes:
            try:
                state = await self._update_ticker(ticker)
                if state is not None:
                    results[ticker] = state
            except Exception:
                logger.exception("ibd_ticker_update_error", ticker=ticker)

        if results:
            # Overall = worst status across all tickers
            worst_status = IBDMarketStatus.CONFIRMED_UPTREND.value
            for state in results.values():
                worst_status = _worse_status(worst_status, state.status)

            # Use the state with the worst status as "overall" template
            worst_state = max(
                results.values(),
                key=lambda s: _STATUS_RANK.get(s.status, 0),
            )
            overall = IBDMarketState(
                date=worst_state.date,
                index_ticker="overall",
                status=worst_status,
                prior_status=None,
                distribution_count=max(s.distribution_count for s in results.values()),
                rally_day_count=worst_state.rally_day_count,
                ftd_date=worst_state.ftd_date,
                ftd_low=worst_state.ftd_low,
            )
            results["overall"] = overall

        return results

    # ── Per-ticker update ─────────────────────────────────────────

    async def _update_ticker(self, ticker: str) -> IBDMarketState | None:
        """Full IBD update pipeline for a single index ticker."""
        # Load OHLCV history
        bars = await self._price_cache.get_ohlcv(ticker, days=IBD_LOOKBACK_DAYS + 5)
        if len(bars) < 2:
            logger.warning("ibd_insufficient_data", ticker=ticker, bars=len(bars))
            return None

        today_bar = bars[-1]
        prior_bar = bars[-2]
        today_str = today_bar.date

        # Load prior IBD state from DB
        prior_state = await self._load_prior_state(ticker)

        # Expire old distribution days (25-day window + 5% rally)
        await self._expire_distribution_days(ticker, bars)

        # Detect new special day types
        dist_day: IBDDistributionDay | None = None
        stall_day: IBDDistributionDay | None = None

        if self._is_distribution_day(today_bar, prior_bar):
            dist_day = IBDDistributionDay(
                index_ticker=ticker,
                date=today_str,
                day_type="DISTRIBUTION",
                close_price=today_bar.close,
                price_change_pct=(today_bar.close - prior_bar.close) / prior_bar.close,
                volume=today_bar.volume,
                prior_volume=prior_bar.volume,
            )
            await self._save_distribution_day(dist_day)
            logger.info("ibd_distribution_day", ticker=ticker, date=today_str,
                        close=today_bar.close,
                        pct=round((today_bar.close - prior_bar.close) / prior_bar.close, 4))

        elif self._is_stalling_day(today_bar, prior_bar):
            stall_day = IBDDistributionDay(
                index_ticker=ticker,
                date=today_str,
                day_type="STALLING",
                close_price=today_bar.close,
                price_change_pct=(today_bar.close - prior_bar.close) / prior_bar.close,
                volume=today_bar.volume,
                prior_volume=prior_bar.volume,
            )
            await self._save_distribution_day(stall_day)
            logger.info("ibd_stalling_day", ticker=ticker, date=today_str)

        # Count active distribution + stalling days (stalling capped at IBD_STALL_MAX_COUNT)
        active_dist_count = await self._count_active_distribution_days(ticker)

        # Determine rally_day_count and FTD info from prior state
        prior_status = prior_state.status if prior_state else IBDMarketStatus.MARKET_IN_CORRECTION.value
        prior_rally_day = prior_state.rally_day_count if prior_state else 0
        prior_ftd_date = prior_state.ftd_date if prior_state else None
        prior_ftd_low = prior_state.ftd_low if prior_state else None

        # Run state machine
        new_status, new_rally_day, new_ftd_date, new_ftd_low, notes = await self._run_state_machine(
            ticker=ticker,
            today_bar=today_bar,
            prior_bar=prior_bar,
            prior_status=prior_status,
            prior_rally_day=prior_rally_day,
            prior_ftd_date=prior_ftd_date,
            prior_ftd_low=prior_ftd_low,
            active_dist_count=active_dist_count,
            bars=bars,
        )

        # Detect FTD day record
        if (
            prior_status in (IBDMarketStatus.RALLY_ATTEMPT.value,)
            and new_status == IBDMarketStatus.CONFIRMED_UPTREND.value
        ):
            ftd_record = IBDDistributionDay(
                index_ticker=ticker,
                date=today_str,
                day_type="FOLLOW_THROUGH",
                close_price=today_bar.close,
                price_change_pct=(today_bar.close - prior_bar.close) / prior_bar.close,
                volume=today_bar.volume,
                prior_volume=prior_bar.volume,
            )
            await self._save_distribution_day(ftd_record)
            logger.info("ibd_follow_through_day", ticker=ticker, date=today_str,
                        rally_day=new_rally_day, close=today_bar.close)

        new_state = IBDMarketState(
            date=today_str,
            index_ticker=ticker,
            status=new_status,
            prior_status=prior_status,
            distribution_count=active_dist_count,
            rally_day_count=new_rally_day,
            ftd_date=new_ftd_date,
            ftd_low=new_ftd_low,
            notes=notes,
        )

        await self._save_state(new_state)

        logger.info(
            "ibd_state_updated",
            ticker=ticker,
            date=today_str,
            status=new_status,
            prior_status=prior_status,
            dist_count=active_dist_count,
            rally_day=new_rally_day,
        )

        return new_state

    # ── State Machine ─────────────────────────────────────────────

    async def _run_state_machine(
        self,
        ticker: str,
        today_bar,
        prior_bar,
        prior_status: str,
        prior_rally_day: int,
        prior_ftd_date: Optional[str],
        prior_ftd_low: Optional[float],
        active_dist_count: int,
        bars: list,
    ) -> tuple[str, int, Optional[str], Optional[float], Optional[str]]:
        """Apply IBD state-machine transitions.

        Returns:
            (new_status, new_rally_day, new_ftd_date, new_ftd_low, notes)
        """
        today_str = today_bar.date
        price_change_pct = (today_bar.close - prior_bar.close) / prior_bar.close
        notes: Optional[str] = None

        if prior_status == IBDMarketStatus.MARKET_IN_CORRECTION.value:
            # Up-close (any gain) starts a rally attempt
            if today_bar.close > prior_bar.close:
                # Store day1_low for later FTD validation
                await self._db.set_state(
                    f"ibd_rally_day1_low_{ticker}", str(today_bar.low)
                )
                return (
                    IBDMarketStatus.RALLY_ATTEMPT.value,
                    1,
                    None,
                    None,
                    "Rally attempt started",
                )
            return (prior_status, 0, None, None, None)

        elif prior_status == IBDMarketStatus.RALLY_ATTEMPT.value:
            new_rally_day = prior_rally_day + 1

            # Fetch day1_low from bot_state
            day1_low_str = await self._db.get_state(f"ibd_rally_day1_low_{ticker}")
            day1_low = float(day1_low_str) if day1_low_str else today_bar.low

            # Close below day1_low → back to correction
            if today_bar.close < day1_low:
                notes = f"Rally failed: close {today_bar.close} < day1_low {day1_low}"
                return (
                    IBDMarketStatus.MARKET_IN_CORRECTION.value,
                    0,
                    None,
                    None,
                    notes,
                )

            # FTD check: day 4-10, gain >= 1.25%, volume > prior
            if (
                IBD_FTD_EARLIEST_DAY <= new_rally_day <= IBD_FTD_LATEST_DAY
                and self._is_ftd(today_bar, prior_bar, new_rally_day)
            ):
                notes = f"Follow-through day {new_rally_day}"
                return (
                    IBDMarketStatus.CONFIRMED_UPTREND.value,
                    new_rally_day,
                    today_str,
                    today_bar.low,
                    notes,
                )

            # Beyond day 10 without FTD → correction
            if new_rally_day > IBD_FTD_LATEST_DAY:
                notes = f"Rally expired: day {new_rally_day} without FTD"
                return (
                    IBDMarketStatus.MARKET_IN_CORRECTION.value,
                    0,
                    None,
                    None,
                    notes,
                )

            return (prior_status, new_rally_day, None, None, None)

        elif prior_status == IBDMarketStatus.CONFIRMED_UPTREND.value:
            # FTD fragility check: within first IBD_FTD_FRAGILE_DAYS days of FTD
            if prior_ftd_date:
                trading_days_since_ftd = self._count_trading_days_between(
                    prior_ftd_date, today_str, bars
                )
                if trading_days_since_ftd <= IBD_FTD_FRAGILE_DAYS:
                    # Close below FTD low invalidates uptrend immediately
                    if prior_ftd_low and today_bar.close < prior_ftd_low:
                        notes = f"FTD invalidated: close below ftd_low {prior_ftd_low}"
                        return (
                            IBDMarketStatus.MARKET_IN_CORRECTION.value,
                            0,
                            None,
                            None,
                            notes,
                        )
                    # Distribution day within first IBD_FTD_FRAGILE_DAYS of FTD
                    is_dist = self._is_distribution_day(today_bar, prior_bar)
                    if is_dist:
                        notes = f"FTD fragile dist day within {IBD_FTD_FRAGILE_DAYS} days"
                        return (
                            IBDMarketStatus.MARKET_IN_CORRECTION.value,
                            0,
                            None,
                            None,
                            notes,
                        )

            # Distribution count thresholds
            if active_dist_count >= IBD_CORRECTION_THRESHOLD:
                notes = f"Distribution count {active_dist_count} >= correction threshold"
                return (
                    IBDMarketStatus.MARKET_IN_CORRECTION.value,
                    0,
                    None,
                    None,
                    notes,
                )
            if active_dist_count >= IBD_PRESSURE_THRESHOLD:
                notes = f"Distribution count {active_dist_count} >= pressure threshold"
                return (
                    IBDMarketStatus.UPTREND_UNDER_PRESSURE.value,
                    0,
                    prior_ftd_date,
                    prior_ftd_low,
                    notes,
                )

            return (prior_status, 0, prior_ftd_date, prior_ftd_low, None)

        elif prior_status == IBDMarketStatus.UPTREND_UNDER_PRESSURE.value:
            if active_dist_count >= IBD_CORRECTION_THRESHOLD:
                notes = f"Distribution count {active_dist_count} >= correction threshold"
                return (
                    IBDMarketStatus.MARKET_IN_CORRECTION.value,
                    0,
                    None,
                    None,
                    notes,
                )
            if active_dist_count < IBD_PRESSURE_THRESHOLD:
                notes = f"Distribution improved to {active_dist_count}"
                return (
                    IBDMarketStatus.CONFIRMED_UPTREND.value,
                    0,
                    prior_ftd_date,
                    prior_ftd_low,
                    notes,
                )
            return (prior_status, 0, prior_ftd_date, prior_ftd_low, None)

        # Fallback (should not happen)
        return (prior_status, prior_rally_day, prior_ftd_date, prior_ftd_low, None)

    # ── Detection helpers ─────────────────────────────────────────

    @staticmethod
    def _is_distribution_day(today_bar, prior_bar) -> bool:
        """Return True if today qualifies as a distribution day.

        Criteria:
          - Price change % < IBD_DISTRIBUTION_MIN_DECLINE (e.g. -0.2%)
          - Volume >= prior day's volume (higher volume sell-off)
        """
        price_change_pct = (today_bar.close - prior_bar.close) / prior_bar.close
        return (
            price_change_pct <= IBD_DISTRIBUTION_MIN_DECLINE
            and today_bar.volume >= prior_bar.volume
        )

    @staticmethod
    def _is_stalling_day(today_bar, prior_bar) -> bool:
        """Return True if today qualifies as a stalling day.

        Criteria (IBD stalling definition):
          - Gain is modest: IBD_STALL_MIN_GAIN <= pct <= IBD_STALL_MAX_GAIN
          - Close in lower half of day's range (close_range <= IBD_STALL_CLOSE_RANGE_MAX)
          - Volume is high: >= IBD_STALL_VOLUME_RATIO * prior volume
        """
        price_change_pct = (today_bar.close - prior_bar.close) / prior_bar.close
        day_range = today_bar.high - today_bar.low
        if day_range <= 0:
            return False
        close_range = (today_bar.close - today_bar.low) / day_range
        return (
            IBD_STALL_MIN_GAIN <= price_change_pct <= IBD_STALL_MAX_GAIN
            and close_range <= IBD_STALL_CLOSE_RANGE_MAX
            and today_bar.volume >= IBD_STALL_VOLUME_RATIO * prior_bar.volume
        )

    @staticmethod
    def _is_ftd(today_bar, prior_bar, rally_day_count: int) -> bool:
        """Return True if today qualifies as a Follow-Through Day.

        Criteria:
          - Rally day count in [IBD_FTD_EARLIEST_DAY, IBD_FTD_LATEST_DAY]  (checked by caller)
          - Price gain >= IBD_FTD_MIN_GAIN (e.g. 1.25%)
          - Volume >= prior day's volume
        """
        price_change_pct = (today_bar.close - prior_bar.close) / prior_bar.close
        return (
            price_change_pct >= IBD_FTD_MIN_GAIN
            and today_bar.volume >= prior_bar.volume
        )

    # ── Expiration helpers ────────────────────────────────────────

    async def _expire_distribution_days(self, ticker: str, bars: list) -> None:
        """Expire distribution days by two criteria:
          1. 25 trading days have elapsed since the dist day
          2. Latest close is >= dist_day_close * (1 + IBD_DISTRIBUTION_RALLY_EXPIRE)
        """
        if not bars:
            return

        latest_close = bars[-1].close
        today_str = bars[-1].date

        # Fetch all active dist days for this ticker
        cursor = await self._db.conn.execute(
            """
            SELECT id, date, close_price FROM ibd_distribution_days
            WHERE index_ticker = ? AND expired = 0
            """,
            (ticker,),
        )
        rows = await cursor.fetchall()
        if not rows:
            return

        # Build a date → index map from bars for efficient lookups
        date_index = {bar.date: i for i, bar in enumerate(bars)}
        today_idx = date_index.get(today_str, len(bars) - 1)

        for row_id, dist_date, dist_close in rows:
            # Criterion 1: 25 trading days elapsed
            dist_idx = date_index.get(dist_date)
            if dist_idx is not None:
                trading_days_elapsed = today_idx - dist_idx
            else:
                # dist_date older than bars window → definitely expired
                trading_days_elapsed = IBD_DISTRIBUTION_WINDOW + 1

            # Criterion 2: 5% rally above dist day close
            rally_expired = (
                dist_close is not None
                and latest_close >= dist_close * (1 + IBD_DISTRIBUTION_RALLY_EXPIRE)
            )

            if trading_days_elapsed >= IBD_DISTRIBUTION_WINDOW:
                await self._expire_one(row_id, "25_trading_days", today_str)
            elif rally_expired:
                await self._expire_one(row_id, "5pct_rally", today_str)

    async def _expire_one(self, row_id: int, reason: str, today_str: str) -> None:
        await self._db.conn.execute(
            """
            UPDATE ibd_distribution_days
            SET expired = 1, expiry_reason = ?, expiry_date = ?
            WHERE id = ?
            """,
            (reason, today_str, row_id),
        )
        await self._db.conn.commit()

    async def _count_active_distribution_days(self, ticker: str) -> int:
        """Count active (non-expired) distribution + stalling days.

        Stalling days are capped at IBD_STALL_MAX_COUNT total.
        """
        cursor = await self._db.conn.execute(
            """
            SELECT day_type, COUNT(*) FROM ibd_distribution_days
            WHERE index_ticker = ? AND expired = 0
            GROUP BY day_type
            """,
            (ticker,),
        )
        rows = await cursor.fetchall()
        dist_count = 0
        stall_count = 0
        for day_type, count in rows:
            if day_type == "DISTRIBUTION":
                dist_count += count
            elif day_type == "STALLING":
                stall_count += count
        # Cap stalling contribution
        effective_stall = min(stall_count, IBD_STALL_MAX_COUNT)
        return dist_count + effective_stall

    # ── DB helpers ────────────────────────────────────────────────

    async def _load_prior_state(self, ticker: str) -> IBDMarketState | None:
        """Load the most recent IBD state for this ticker from DB."""
        cursor = await self._db.conn.execute(
            """
            SELECT id, date, index_ticker, status, prior_status,
                   distribution_count, rally_day_count, ftd_date, ftd_low, notes
            FROM ibd_market_direction
            WHERE index_ticker = ?
            ORDER BY date DESC
            LIMIT 1
            """,
            (ticker,),
        )
        row = await cursor.fetchone()
        if not row:
            return None
        return IBDMarketState(
            id=row[0],
            date=row[1],
            index_ticker=row[2],
            status=row[3],
            prior_status=row[4],
            distribution_count=row[5] or 0,
            rally_day_count=row[6] or 0,
            ftd_date=row[7],
            ftd_low=row[8],
            notes=row[9],
        )

    async def _save_state(self, state: IBDMarketState) -> None:
        """Upsert IBDMarketState into ibd_market_direction."""
        await self._db.conn.execute(
            """
            INSERT INTO ibd_market_direction
                (date, index_ticker, status, prior_status,
                 distribution_count, rally_day_count, ftd_date, ftd_low, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(date, index_ticker) DO UPDATE SET
                status = excluded.status,
                prior_status = excluded.prior_status,
                distribution_count = excluded.distribution_count,
                rally_day_count = excluded.rally_day_count,
                ftd_date = excluded.ftd_date,
                ftd_low = excluded.ftd_low,
                notes = excluded.notes
            """,
            (
                state.date,
                state.index_ticker,
                state.status,
                state.prior_status,
                state.distribution_count,
                state.rally_day_count,
                state.ftd_date,
                state.ftd_low,
                state.notes,
            ),
        )
        await self._db.conn.commit()

    async def _save_distribution_day(self, day: IBDDistributionDay) -> None:
        """Insert a distribution/stalling/FTD day (ignore duplicates)."""
        await self._db.conn.execute(
            """
            INSERT OR IGNORE INTO ibd_distribution_days
                (index_ticker, date, day_type, close_price, price_change_pct,
                 volume, prior_volume, expired, expiry_reason, expiry_date)
            VALUES (?, ?, ?, ?, ?, ?, ?, 0, NULL, NULL)
            """,
            (
                day.index_ticker,
                day.date,
                day.day_type,
                day.close_price,
                day.price_change_pct,
                day.volume,
                day.prior_volume,
            ),
        )
        await self._db.conn.commit()

    # ── Utility ───────────────────────────────────────────────────

    @staticmethod
    def _count_trading_days_between(start_date: str, end_date: str, bars: list) -> int:
        """Count trading days between start_date (exclusive) and end_date (inclusive)."""
        count = 0
        counting = False
        for bar in bars:
            if bar.date == start_date:
                counting = True
                continue
            if counting:
                count += 1
            if bar.date == end_date:
                break
        return count
