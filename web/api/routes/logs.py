from __future__ import annotations

import asyncio
import json
from pathlib import Path

import structlog
from fastapi import APIRouter, Depends, Query

from config.settings import get_settings
from core.database import Database
from web.api.dependencies import get_db, verify_api_key

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["logs"])

# ---------------------------------------------------------------------------
# Tail-read: only read the last chunk of the log file instead of the whole
# thing.  The log file can be 200 MB+, so reading it entirely blocks the
# event loop and makes the whole dashboard unresponsive.
# ---------------------------------------------------------------------------

_TAIL_BYTES = 512 * 1024  # read last 512 KB – more than enough for 500 lines


def _tail_lines(path: Path, max_bytes: int = _TAIL_BYTES) -> list[str]:
    """Return the last *max_bytes* worth of lines from *path*."""
    size = path.stat().st_size
    offset = max(0, size - max_bytes)
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        if offset:
            fh.seek(offset)
            fh.readline()  # discard partial first line
        return fh.readlines()


@router.get("/logs", dependencies=[Depends(verify_api_key)])
async def get_logs(
    limit: int = Query(100, ge=1, le=500),
    level: str = Query("ALL"),
    db: Database = Depends(get_db),
) -> dict:
    settings = get_settings()
    log_path = Path(settings.log_file).resolve()

    entries: list[dict] = []

    if log_path.exists() and log_path.stat().st_size > 0:
        # Run blocking file I/O in a thread so we don't stall the event loop
        lines = await asyncio.to_thread(_tail_lines, log_path)

        raw_entries: list[dict] = []
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                entry = {
                    "event": line[:200],
                    "level": "info",
                    "timestamp": "",
                }
            if level != "ALL" and entry.get("level", "").lower() != level.lower():
                continue
            raw_entries.append(entry)

        entries = raw_entries[-limit:]
        entries.reverse()

    bot_events = await _get_bot_events(db, limit)

    return {
        "logs": entries,
        "bot_events": bot_events,
        "total_log_lines": len(entries),
        "log_file": str(log_path),
        "log_file_exists": log_path.exists(),
    }


async def _get_bot_events(db: Database, limit: int) -> list[dict]:
    cursor = await db.conn.execute(
        """
        SELECT id, timestamp, level, event, module, ticker, details
        FROM bot_logs
        ORDER BY id DESC
        LIMIT ?
        """,
        (limit,),
    )
    rows = await cursor.fetchall()
    return [
        {
            "id": r[0],
            "timestamp": r[1],
            "level": r[2],
            "event": r[3],
            "module": r[4],
            "ticker": r[5],
            "details": r[6],
        }
        for r in rows
    ]
