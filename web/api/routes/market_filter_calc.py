from __future__ import annotations

import asyncio
from functools import lru_cache
from time import time

import structlog

logger = structlog.get_logger(__name__)

_cache: dict[str, tuple[float, dict]] = {}
_CACHE_TTL = 300


async def compute_market_filter() -> dict:
    now = time()
    if "spy" in _cache:
        cached_at, cached_result = _cache["spy"]
        if now - cached_at < _CACHE_TTL:
            return cached_result

    result = await asyncio.to_thread(_fetch_spy_filter)
    _cache["spy"] = (now, result)
    return result


def _fetch_spy_filter() -> dict:
    try:
        import yfinance as yf

        spy = yf.Ticker("SPY")
        hist = spy.history(period="1y")
        if hist.empty or len(hist) < 200:
            return {"spy_close": None, "spy_sma200": None, "filter_pass": None, "label": "데이터 부족"}

        spy_close = float(hist["Close"].iloc[-1])
        spy_sma200 = float(hist["Close"].rolling(200).mean().iloc[-1])
        filter_pass = spy_close > spy_sma200

        return {
            "spy_close": round(spy_close, 2),
            "spy_sma200": round(spy_sma200, 2),
            "filter_pass": filter_pass,
            "label": "PASS" if filter_pass else "FAIL",
        }
    except Exception as e:
        logger.warning("market_filter_calc_error", error=str(e))
        return {"spy_close": None, "spy_sma200": None, "filter_pass": None, "label": "오류"}
