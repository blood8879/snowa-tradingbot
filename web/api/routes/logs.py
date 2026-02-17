from __future__ import annotations

import json
from pathlib import Path

import structlog
from fastapi import APIRouter, Depends, Query

from config.settings import get_settings
from core.database import Database
from web.api.dependencies import get_db, verify_api_key

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["logs"])


@router.get("/logs", dependencies=[Depends(verify_api_key)])
async def get_logs(
    limit: int = Query(100, ge=1, le=500),
    level: str = Query("ALL"),
    db: Database = Depends(get_db),
) -> dict:
    settings = get_settings()
    log_path = Path(settings.log_file).resolve()

    entries: list[dict] = []

    if log_path.exists():
        lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
        raw_entries: list[dict] = []
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                raw_entries.append(entry)
            except json.JSONDecodeError:
                raw_entries.append({
                    "event": line[:200],
                    "level": "info",
                    "timestamp": "",
                })

        if level != "ALL":
            raw_entries = [
                e for e in raw_entries
                if e.get("level", "").lower() == level.lower()
            ]

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
