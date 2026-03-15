from __future__ import annotations

import asyncio
from time import time

import structlog

from config.constants import (
    MARKET_BREADTH_GREEN,
    MARKET_BREADTH_RED,
    MARKET_ROC_PERIOD,
    MARKET_ROC_WARNING,
    MARKET_REGIME_YELLOW_SCALE,
)

logger = structlog.get_logger(__name__)

_cache: dict[str, tuple[float, dict]] = {}
_CACHE_TTL = 300


def _determine_regime(sma_pass, breadth_pct, roc):
    """Determine regime from signals (same logic as strategy/market_filter.py)."""
    if not sma_pass:
        return "RED", 0.0
    breadth_ok = breadth_pct is None or breadth_pct >= MARKET_BREADTH_GREEN
    breadth_bad = breadth_pct is not None and breadth_pct < MARKET_BREADTH_RED
    roc_ok = roc is None or roc >= MARKET_ROC_WARNING
    roc_bad = roc is not None and roc < MARKET_ROC_WARNING
    if breadth_bad and roc_bad:
        return "RED", 0.0
    if breadth_ok and roc_ok:
        return "GREEN", 1.0
    return "YELLOW", MARKET_REGIME_YELLOW_SCALE


async def compute_market_filter(market: str = "US") -> dict:
    now = time()
    if market in _cache:
        cached_at, cached_result = _cache[market]
        if now - cached_at < _CACHE_TTL:
            return cached_result

    if market == "KR":
        result = await asyncio.to_thread(_fetch_kr_filter)
    else:
        result = await asyncio.to_thread(_fetch_spy_filter)

    # Add breadth from DB
    try:
        from core.database import Database
        db = Database("data/snowa.db")
        await db.initialize()
        from strategy.market_filter import calculate_breadth
        breadth_pct = await calculate_breadth(db, market=market)
        await db.close()
        result["breadth_pct"] = breadth_pct
    except Exception:
        result["breadth_pct"] = None

    # Determine regime
    regime, regime_scale = _determine_regime(
        result.get("filter_pass"),
        result.get("breadth_pct"),
        result.get("roc"),
    )
    result["regime"] = regime
    result["regime_scale"] = regime_scale

    # Update label to include regime
    regime_labels = {"GREEN": "GREEN", "YELLOW": "YELLOW", "RED": "RED"}
    result["label"] = regime_labels.get(regime, "—")

    _cache[market] = (now, result)
    return result


def _fetch_spy_filter() -> dict:
    try:
        import yfinance as yf

        spy = yf.Ticker("SPY")
        hist = spy.history(period="1y")
        if hist.empty or len(hist) < 200:
            return {"benchmark": "SPY", "close": None, "sma200": None, "filter_pass": None, "roc": None, "label": "데이터 부족"}

        closes = hist["Close"].tolist()
        spy_close = float(closes[-1])
        spy_sma200 = float(sum(closes[-200:]) / 200)
        filter_pass = spy_close > spy_sma200

        # ROC calculation
        roc = None
        if len(closes) > MARKET_ROC_PERIOD:
            old = closes[-(MARKET_ROC_PERIOD + 1)]
            if old > 0:
                roc = (closes[-1] / old) - 1.0

        return {
            "benchmark": "SPY",
            "close": round(spy_close, 2),
            "sma200": round(spy_sma200, 2),
            "filter_pass": filter_pass,
            "roc": roc,
        }
    except Exception as e:
        logger.warning("market_filter_calc_error", error=str(e))
        return {"benchmark": "SPY", "close": None, "sma200": None, "filter_pass": None, "roc": None, "label": "오류"}


def _fetch_kr_filter() -> dict:
    try:
        from datetime import datetime, timedelta
        from pykrx import stock as pykrx_stock

        end_date = datetime.now()
        start_date = end_date - timedelta(days=365)

        df = pykrx_stock.get_market_ohlcv_by_date(
            start_date.strftime("%Y%m%d"),
            end_date.strftime("%Y%m%d"),
            "069500"
        )

        if df is None or df.empty or len(df) < 200:
            return {"benchmark": "KODEX200", "close": None, "sma200": None, "filter_pass": None, "roc": None, "label": "데이터 부족"}

        closes = df["종가"].tolist()
        close_price = float(closes[-1])
        sma200 = float(sum(closes[-200:]) / 200)
        filter_pass = close_price > sma200

        roc = None
        if len(closes) > MARKET_ROC_PERIOD:
            old = closes[-(MARKET_ROC_PERIOD + 1)]
            if old > 0:
                roc = (closes[-1] / old) - 1.0

        return {
            "benchmark": "KODEX200",
            "close": round(close_price, 2),
            "sma200": round(sma200, 2),
            "filter_pass": filter_pass,
            "roc": roc,
        }
    except Exception as e:
        logger.warning("kr_market_filter_calc_error", error=str(e))
        return {"benchmark": "KODEX200", "close": None, "sma200": None, "filter_pass": None, "roc": None, "label": "오류"}
