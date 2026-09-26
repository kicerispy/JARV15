"""Persistent bounded execution traces for JARVIS autonomy learning.

The trace store keeps compact task metadata and sanitized step outcomes. It is
local-only runtime state and never mutates source code.
"""

from __future__ import annotations

import json
import re
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

import config

_TRACE_DIR = Path(getattr(config, "BASE_DIR", Path("."))) / ".jarvis_autonomy"
_TRACE_DB = _TRACE_DIR / "task_trace.sqlite3"
_MAX_TRACES = 1000
_MAX_TEXT = 1200
_LOCK = threading.RLock()
_SCHEMA_READY = False


def _clean(value: Any, limit: int = _MAX_TEXT) -> str:
    text = " ".join(str(value or "").strip().split())
    text = re.sub(
        r"(?i)(authorization|api[_ -]?key|token|password|secret)\s*[=:]\s*\S+",
        r"\1=<redacted>",
        text,
    )
    return text[:limit]


def trace_db_path() -> str:
    return str(_TRACE_DB)


def _connect() -> sqlite3.Connection:
    _TRACE_DIR.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(_TRACE_DB), timeout=5.0)
    connection.row_factory = sqlite3.Row
    connection.executescript(
        """
            CREATE TABLE IF NOT EXISTS traces (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT NOT NULL,
                timestamp REAL NOT NULL,
                request TEXT NOT NULL,
                goal TEXT,
                status TEXT,
                verified INTEGER NOT NULL DEFAULT 0,
                duration_seconds REAL NOT NULL DEFAULT 0,
                replans INTEGER NOT NULL DEFAULT 0,
                error TEXT,
                verification_reason TEXT,
                plan_json TEXT,
                steps_json TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_traces_timestamp
                ON traces(timestamp DESC);

            CREATE INDEX IF NOT EXISTS idx_traces_status
                ON traces(status);
        """
    )
    connection.commit()
    return connection


def _trim() -> None:
    with _connect() as connection:
        row = connection.execute(
            "SELECT COUNT(*) AS count FROM traces"
        ).fetchone()
        count = int(row["count"] or 0) if row else 0
        excess = count - _MAX_TRACES
        if excess > 0:
            connection.execute(
                """
                DELETE FROM traces
                WHERE id IN (
                    SELECT id FROM traces
                    ORDER BY timestamp ASC
                    LIMIT ?
                )
                """,
                (excess,),
            )
            connection.commit()


def record_trace(
    *,
    task_id: str,
    request: str,
    goal: str = "",
    status: str = "",
    verified: bool = False,
    duration_seconds: float = 0.0,
    replans: int = 0,
    error: str = "",
    verification_reason: str = "",
    plan: dict[str, Any] | None = None,
    steps: list[dict[str, Any]] | None = None,
) -> bool:
    """Persist one sanitized execution trace."""
    plan_payload = plan if isinstance(plan, dict) else {}
    step_payload = steps if isinstance(steps, list) else []

    compact_steps = []
    for item in step_payload[:64]:
        if not isinstance(item, dict):
            continue
        compact_steps.append(
            {
                "tool": _clean(item.get("tool"), 120),
                "status": _clean(item.get("status"), 32),
                "attempts": max(0, int(item.get("attempts", 0) or 0)),
                "verified": bool(item.get("verified", False)),
                "error": _clean(item.get("error"), 600),
            }
        )

    payload = {
        "goal": _clean(plan_payload.get("goal") or goal, 800),
        "tools": [
            _clean(item.get("tool"), 120)
            for item in compact_steps
            if item.get("tool")
        ],
    }

    try:
        with _LOCK:
            with _connect() as connection:
                connection.execute(
                    """
                    INSERT INTO traces(
                        task_id, timestamp, request, goal, status, verified,
                        duration_seconds, replans, error, verification_reason,
                        plan_json, steps_json
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        _clean(task_id, 120),
                        time.time(),
                        _clean(request, 1000),
                        _clean(payload["goal"], 800),
                        _clean(status, 32).lower(),
                        1 if verified else 0,
                        max(0.0, float(duration_seconds or 0.0)),
                        max(0, int(replans or 0)),
                        _clean(error, 900),
                        _clean(verification_reason, 500),
                        json.dumps(
                            {
                                "goal": payload["goal"],
                                "tools": payload["tools"],
                            },
                            ensure_ascii=False,
                            default=str,
                        )[:6000],
                        json.dumps(compact_steps, ensure_ascii=False, default=str)[:12000],
                    ),
                )
                connection.commit()
            _trim()
        return True
    except (OSError, sqlite3.Error, ValueError, TypeError):
        return False


def recent_traces(limit: int = 10) -> list[dict[str, Any]]:
    limit = max(1, min(int(limit), 50))
    try:
        with _LOCK:
            with _connect() as connection:
                rows = connection.execute(
                    """
                    SELECT *
                    FROM traces
                    ORDER BY timestamp DESC
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
        results = []
        for row in rows:
            results.append(
                {
                    "task_id": row["task_id"],
                    "timestamp": row["timestamp"],
                    "request": row["request"],
                    "goal": row["goal"],
                    "status": row["status"],
                    "verified": bool(row["verified"]),
                    "duration_seconds": row["duration_seconds"],
                    "replans": row["replans"],
                    "error": row["error"],
                    "verification_reason": row["verification_reason"],
                }
            )
        return results
    except (OSError, sqlite3.Error, ValueError):
        return []


def trace_status() -> dict[str, Any]:
    try:
        with _LOCK:
            with _connect() as connection:
                row = connection.execute(
                    """
                    SELECT
                        COUNT(*) AS traces,
                        SUM(CASE WHEN status='completed' THEN 1 ELSE 0 END) AS completed,
                        SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) AS failed,
                        SUM(CASE WHEN verified=1 THEN 1 ELSE 0 END) AS verified
                    FROM traces
                    """
                ).fetchone()
        return {
            "enabled": True,
            "path": str(_TRACE_DB),
            "max_traces": _MAX_TRACES,
            "traces": int(row["traces"] or 0) if row else 0,
            "completed": int(row["completed"] or 0) if row else 0,
            "failed": int(row["failed"] or 0) if row else 0,
            "verified": int(row["verified"] or 0) if row else 0,
        }
    except Exception as exc:
        return {
            "enabled": False,
            "path": str(_TRACE_DB),
            "error": _clean(exc, 300),
        }


__all__ = [
    "record_trace",
    "recent_traces",
    "trace_db_path",
    "trace_status",
]