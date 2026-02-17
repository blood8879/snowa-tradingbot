from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from time import time

import structlog
from fastapi import APIRouter, Depends, Query

from web.api.dependencies import verify_api_key

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["prices"])

_cache: dict[str, tuple[float, dict]] = {}
_CACHE_TTL = 60


def _fetch_prices(tickers: list[str]) -> dict[str, dict]:
    import yfinance as yf

    result: dict[str, dict] = {}
    ticker_str = " ".join(tickers)

    try:
        data = yf.download(ticker_str, period="1d", interval="1m", progress=False)
        if data.empty:
            raise ValueError("empty intraday data")

        for t in tickers:
            try:
                if len(tickers) == 1:
                    close_col = data["Close"]
                    vol_col = data["Volume"] if "Volume" in data.columns else None
                else:
                    close_col = data["Close"][t]
                    vol_col = data["Volume"][t] if "Volume" in data.columns else None

                close_series = close_col.dropna()
                if close_series.empty:
                    continue

                current = float(close_series.iloc[-1])
                prev_close = float(close_series.iloc[0])
                change_pct = ((current - prev_close) / prev_close) * 100 if prev_close else 0.0

                volume: int | None = None
                if vol_col is not None:
                    vol_series = vol_col.dropna()
                    if not vol_series.empty:
                        volume = int(vol_series.sum())

                result[t] = {
                    "price": round(current, 2),
                    "change_pct": round(change_pct, 2),
                    "volume": volume,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }
            except Exception:
                continue

    except Exception as e:
        logger.warning("intraday_fetch_failed", error=str(e))

    missing = [t for t in tickers if t not in result]
    if missing:
        try:
            data_daily = yf.download(" ".join(missing), period="5d", interval="1d", progress=False)
            if not data_daily.empty:
                for t in missing:
                    try:
                        if len(missing) == 1:
                            close_col = data_daily["Close"]
                            vol_col = data_daily["Volume"] if "Volume" in data_daily.columns else None
                        else:
                            close_col = data_daily["Close"][t]
                            vol_col = data_daily["Volume"][t] if "Volume" in data_daily.columns else None

                        close_series = close_col.dropna()
                        if len(close_series) < 2:
                            continue

                        current = float(close_series.iloc[-1])
                        prev = float(close_series.iloc[-2])
                        change_pct = ((current - prev) / prev) * 100 if prev else 0.0

                        volume = None
                        if vol_col is not None:
                            vol_series = vol_col.dropna()
                            if not vol_series.empty:
                                volume = int(vol_series.iloc[-1])

                        result[t] = {
                            "price": round(current, 2),
                            "change_pct": round(change_pct, 2),
                            "volume": volume,
                            "updated_at": datetime.now(timezone.utc).isoformat(),
                        }
                    except Exception:
                        continue
        except Exception as e:
            logger.warning("daily_fallback_failed", error=str(e))

    return result


@router.get("/prices/realtime", dependencies=[Depends(verify_api_key)])
async def get_realtime_prices(
    tickers: str = Query(..., description="Comma-separated ticker symbols"),
) -> dict:
    ticker_list = [t.strip().upper() for t in tickers.split(",") if t.strip()]
    if not ticker_list:
        return {"prices": {}, "cached": False}

    cache_key = ",".join(sorted(ticker_list))
    now = time()

    if cache_key in _cache:
        cached_at, cached_result = _cache[cache_key]
        if now - cached_at < _CACHE_TTL:
            return {"prices": cached_result, "cached": True}

    prices = await asyncio.to_thread(_fetch_prices, ticker_list)
    _cache[cache_key] = (now, prices)

    return {"prices": prices, "cached": False}
