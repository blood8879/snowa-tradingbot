"""
Market direction filter — 3-tier regime (GREEN / YELLOW / RED).

Signals:
  1. Benchmark > 200-day SMA (base filter, same as before)
  2. Market breadth: % of universe above their own 200 SMA
  3. Benchmark 125-day Rate of Change (momentum)

Regime determination:
  RED    — benchmark < 200 SMA (hard gate per TURTLE_TRADING_STRATEGY.md §2),
           OR breadth < 35% AND ROC < -5% (both bad)
  YELLOW — SMA pass but one of breadth/ROC is weak
  GREEN  — all signals healthy (SMA pass + breadth OK + ROC OK)

Data unavailable / errors → fail-closed (RED, entries blocked) per spec §2.3.
Existing positions continue to be managed by Turtle exit rules.
"""

from __future__ import annotations

from typing import Any

import structlog

from config.constants import (
    MARKET_BREADTH_GREEN,
    MARKET_BREADTH_RED,
    MARKET_FILTER_BUFFER_PCT,
    MARKET_MA_PERIOD,
    MARKET_REGIME_YELLOW_SCALE,
    MARKET_ROC_PERIOD,
    MARKET_ROC_WARNING,
)
from config.market_config import get_market_config

logger = structlog.get_logger(__name__)


# ════════════════════════════════════════════════════════════════
# Pure Calculations
# ════════════════════════════════════════════════════════════════


def check_market_filter(
    spy_close: float,
    spy_sma200: float,
    buffer_pct: float = MARKET_FILTER_BUFFER_PCT,
) -> bool:
    """Return True if the benchmark passes the 200 SMA trend filter."""
    return spy_close > spy_sma200 * (1 - buffer_pct)


def calculate_sma(closes: list[float], period: int) -> float | None:
    """Calculate the Simple Moving Average over *period* bars."""
    if len(closes) < period:
        return None
    return sum(closes[-period:]) / period


def calculate_roc(closes: list[float], period: int) -> float | None:
    """Calculate Rate of Change over *period* bars.

    Returns the fractional change (e.g., -0.05 for -5%).
    """
    if len(closes) < period + 1:
        return None
    old = closes[-(period + 1)]
    if old == 0:
        return None
    return (closes[-1] / old) - 1.0


def determine_regime(
    sma_pass: bool,
    breadth_pct: float | None,
    roc: float | None,
) -> tuple[str, float]:
    """Determine market regime from the three signals.

    Args:
        sma_pass: True if benchmark > 200 SMA.
        breadth_pct: Fraction of universe above 200 SMA (0.0-1.0), or None.
        roc: Benchmark ROC (fractional), or None.

    Returns:
        (regime, scale) — regime is "GREEN"/"YELLOW"/"RED",
        scale is 1.0 / 0.5 / 0.0.
    """
    # If breadth/ROC unavailable, fall back to SMA-only
    breadth_ok = breadth_pct is None or breadth_pct >= MARKET_BREADTH_GREEN
    breadth_bad = breadth_pct is not None and breadth_pct < MARKET_BREADTH_RED
    roc_ok = roc is None or roc >= MARKET_ROC_WARNING
    roc_bad = roc is not None and roc < MARKET_ROC_WARNING

    # SMA failure → RED. Spec §2.2: benchmark below 200 SMA blocks all
    # new entries — this is the hard gate, not a half-size warning.
    if not sma_pass:
        return "RED", 0.0

    # Both breadth AND ROC bad → RED (extra conservative layer)
    if breadth_bad and roc_bad:
        return "RED", 0.0

    # SMA pass + both good → GREEN
    if breadth_ok and roc_ok:
        return "GREEN", 1.0

    # One weak → YELLOW
    return "YELLOW", MARKET_REGIME_YELLOW_SCALE


# ════════════════════════════════════════════════════════════════
# Async Wrapper (uses MarketDataProvider + PriceCache)
# ════════════════════════════════════════════════════════════════


async def calculate_breadth(db: Any, *, market: str = "US") -> float | None:
    """Calculate % of universe stocks whose latest close > their 200 SMA.

    Uses the daily_prices table directly for efficiency.

    Args:
        db: Database instance with .conn attribute.
        market: "US" or "KR".

    Returns:
        Fraction (0.0–1.0), or None if insufficient data.
    """
    if market == "KR":
        # KR tickers are 6-digit numeric codes
        ticker_filter = "length(ticker) = 6 AND ticker GLOB '[0-9]*'"
    else:
        # US tickers are alphabetic
        ticker_filter = "NOT (length(ticker) = 6 AND ticker GLOB '[0-9]*')"

    try:
        cursor = await db.conn.execute(f"""
            WITH latest AS (
                SELECT ticker, close,
                       ROW_NUMBER() OVER (PARTITION BY ticker ORDER BY date DESC) as rn
                FROM daily_prices
                WHERE {ticker_filter}
            ),
            sma AS (
                SELECT ticker,
                       AVG(close) as sma200,
                       COUNT(*) as cnt
                FROM (
                    SELECT ticker, close,
                           ROW_NUMBER() OVER (PARTITION BY ticker ORDER BY date DESC) as rn
                    FROM daily_prices
                    WHERE {ticker_filter}
                )
                WHERE rn <= 200
                GROUP BY ticker
                HAVING cnt >= 200
            )
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN l.close > s.sma200 THEN 1 ELSE 0 END) as above
            FROM latest l
            JOIN sma s ON s.ticker = l.ticker
            WHERE l.rn = 1
        """)
        row = await cursor.fetchone()
        if row is None or row[0] == 0:
            return None
        total, above = row[0], row[1] or 0
        if total < 30:
            return None  # Too few stocks for meaningful breadth
        breadth = above / total
        logger.info(
            "market_breadth_calculated",
            market=market,
            above_200sma=above,
            total=total,
            breadth_pct=round(breadth * 100, 1),
        )
        return breadth
    except Exception:
        logger.exception("market_breadth_error", market=market)
        return None


async def get_market_filter_status(
    market_data: Any,
    *,
    market: str = "US",
    db: Any = None,
) -> dict:
    """Evaluate market direction with 3-tier regime.

    Returns:
        Dict with keys: benchmark, close, sma200, filter_pass,
        regime, regime_scale, breadth_pct, roc_125, market.
    """
    mkt_cfg = get_market_config(market)
    benchmark = mkt_cfg.benchmark_ticker

    # Spec §2.3: insufficient data → block new entries (fail-closed).
    fail_closed = {
        "benchmark": benchmark,
        "close": 0,
        "sma200": 0,
        "filter_pass": False,
        "regime": "RED",
        "regime_scale": 0.0,
        "breadth_pct": None,
        "roc_125": None,
        "market": market,
    }

    try:
        close = await market_data.get_latest_price(benchmark)
        sma200 = await market_data.get_sma(benchmark, MARKET_MA_PERIOD)

        if close is None or sma200 is None:
            logger.warning(
                "market_filter_data_unavailable",
                benchmark=benchmark,
                market=market,
            )
            return fail_closed

        sma_pass = check_market_filter(close, sma200)

        # ROC calculation
        closes = await market_data.get_closes(benchmark, MARKET_ROC_PERIOD + 10)
        roc = calculate_roc(closes, MARKET_ROC_PERIOD) if closes else None

        # Breadth calculation (requires db)
        breadth_pct = None
        if db is not None:
            breadth_pct = await calculate_breadth(db, market=market)

        # Determine regime
        regime, regime_scale = determine_regime(sma_pass, breadth_pct, roc)
        filter_pass = regime != "RED"

        logger.info(
            "market_filter_evaluated",
            benchmark=benchmark,
            market=market,
            close=close,
            sma200=round(sma200, 2),
            sma_pass=sma_pass,
            breadth_pct=round(breadth_pct * 100, 1) if breadth_pct else None,
            roc_125=round(roc * 100, 2) if roc else None,
            regime=regime,
            regime_scale=regime_scale,
            filter_pass=filter_pass,
        )

        return {
            "benchmark": benchmark,
            "close": close,
            "sma200": sma200,
            "filter_pass": filter_pass,
            "regime": regime,
            "regime_scale": regime_scale,
            "breadth_pct": breadth_pct,
            "roc_125": roc,
            "market": market,
        }

    except Exception:
        logger.exception("market_filter_error", benchmark=benchmark, market=market)
        return fail_closed
