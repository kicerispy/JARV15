"""Persistent, local recovery playbook for JARVIS.

The playbook turns repeated runtime failures into bounded, inspectable recovery
hints. It stores only sanitized metadata and never authorizes source mutation.
SQLite is used because it is part of Python's standard library and keeps the
feature dependency-free.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

import config
from healing_kernel import redact_sensitive


_DB_DIR = Path(getattr(config, "BASE_DIR", Path("."))) / ".jarvis_autonomy"
_DB_PATH = _DB_DIR / "healing_playbook.sqlite3"
_LOCK = threading.RLock()
_MAX_TEXT = 900


def _connect() -> sqlite3.Connection:
    _DB_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_DB_PATH), timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS failure_playbook (
            signature TEXT PRIMARY KEY,
            tool TEXT NOT NULL,
            category TEXT NOT NULL,
            error TEXT NOT NULL,
            argument TEXT NOT NULL,
            first_seen REAL NOT NULL,
            last_seen REAL NOT NULL,
            occurrences INTEGER NOT NULL DEFAULT 1,
            resolved_count INTEGER NOT NULL DEFAULT 0,
            last_action TEXT NOT NULL DEFAULT '',
            last_reason TEXT NOT NULL DEFAULT '',
            metadata TEXT NOT NULL DEFAULT '{}'
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_failure_playbook_tool_category
        ON failure_playbook(tool, category, last_seen DESC)
        """
    )
    conn.commit()
    return conn


def _clean(value: Any, limit: int = _MAX_TEXT) -> str:
    return redact_sensitive(value, limit)


def record_failure(
    *,
    signature: str,
    tool: str,
    category: str,
    error: Any,
    argument: Any = "",
    action: str = "",
    reason: str = "",
    metadata: dict[str, Any] | None = None,
) -> None:
    """Upsert one failure signature into the local recovery playbook."""
    if not bool(getattr(config, "SELF_HEALING_FAILURE_MEMORY_ENABLED", True)):
        return

    signature = str(signature or "").strip()[:64]
    tool = _clean(tool, 120)
    category = _clean(category, 80)
    if not signature or not tool:
        return

    now = time.time()
    error_text = _clean(error)
    argument_text = _clean(argument, 800)
    action_text = _clean(action, 120)
    reason_text = _clean(reason, 500)
    metadata_text = json.dumps(
        metadata if isinstance(metadata, dict) else {},
        ensure_ascii=True,
        sort_keys=True,
    )[:2000]

    with _LOCK:
        conn = _connect()
        try:
            conn.execute(
                """
                INSERT INTO failure_playbook (
                    signature, tool, category, error, argument,
                    first_seen, last_seen, occurrences, resolved_count,
                    last_action, last_reason, metadata
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, 1, 0, ?, ?, ?)
                ON CONFLICT(signature) DO UPDATE SET
                    tool=excluded.tool,
                    category=excluded.category,
                    error=excluded.error,
                    argument=excluded.argument,
                    last_seen=excluded.last_seen,
                    occurrences=failure_playbook.occurrences + 1,
                    last_action=excluded.last_action,
                    last_reason=excluded.last_reason,
                    metadata=excluded.metadata
                """,
                (
                    signature,
                    tool,
                    category,
                    error_text,
                    argument_text,
                    now,
                    now,
                    action_text,
                    reason_text,
                    metadata_text,
                ),
            )
            conn.commit()
        finally:
            conn.close()


def mark_recovered(
    *,
    tool: str,
    signature: str = "",
) -> None:
    """Record that a later successful execution followed a failure."""
    if not bool(getattr(config, "SELF_HEALING_FAILURE_MEMORY_ENABLED", True)):
        return

    tool = _clean(tool, 120)
    if not tool:
        return

    with _LOCK:
        conn = _connect()
        try:
            if signature:
                conn.execute(
                    """
                    UPDATE failure_playbook
                    SET resolved_count = resolved_count + 1,
                        last_seen = ?
                    WHERE signature = ? AND tool = ?
                    """,
                    (time.time(), str(signature)[:64], tool),
                )
            else:
                conn.execute(
                    """
                    UPDATE failure_playbook
                    SET resolved_count = resolved_count + 1,
                        last_seen = ?
                    WHERE tool = ?
                      AND rowid = (
                          SELECT rowid
                          FROM failure_playbook
                          WHERE tool = ?
                          ORDER BY last_seen DESC
                          LIMIT 1
                      )
                    """,
                    (time.time(), tool, tool),
                )
            conn.commit()
        finally:
            conn.close()


def failure_hints(
    *,
    tool: str = "",
    category: str = "",
    error: str = "",
    limit: int = 3,
) -> list[dict[str, Any]]:
    """Return the most useful prior failures for recovery planning."""
    if not bool(getattr(config, "SELF_HEALING_FAILURE_MEMORY_ENABLED", True)):
        return []

    limit = max(1, min(int(limit or 3), 8))
    tool = _clean(tool, 120)
    category = _clean(category, 80)
    error_tokens = {
        token.lower()
        for token in _clean(error, 600).split()
        if len(token) >= 4
    }

    with _LOCK:
        conn = _connect()
        try:
            clauses = []
            params: list[Any] = []

            if tool:
                clauses.append("tool = ?")
                params.append(tool)
            if category:
                clauses.append("category = ?")
                params.append(category)

            where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
            rows = conn.execute(
                f"""
                SELECT signature, tool, category, error, argument,
                       occurrences, resolved_count, last_action, last_reason,
                       last_seen
                FROM failure_playbook
                {where}
                ORDER BY occurrences DESC, last_seen DESC
                LIMIT 32
                """,
                params,
            ).fetchall()
        finally:
            conn.close()

    scored: list[tuple[float, sqlite3.Row]] = []
    for row in rows:
        prior_tokens = {
            token.lower()
            for token in f"{row['error']} {row['argument']}".split()
            if len(token) >= 4
        }
        overlap = len(error_tokens & prior_tokens)
        resolution_bonus = min(3.0, float(row["resolved_count"] or 0))
        repeat_penalty = min(4.0, float(row["occurrences"] or 0) / 5.0)
        score = overlap * 5.0 + resolution_bonus - repeat_penalty

        if error_tokens and overlap == 0 and category and row["category"] != category:
            continue

        scored.append((score, row))

    scored.sort(key=lambda pair: pair[0], reverse=True)

    return [
        {
            "signature": str(row["signature"]),
            "tool": str(row["tool"]),
            "category": str(row["category"]),
            "error": str(row["error"]),
            "argument": str(row["argument"]),
            "occurrences": int(row["occurrences"] or 0),
            "resolved_count": int(row["resolved_count"] or 0),
            "last_action": str(row["last_action"] or ""),
            "last_reason": str(row["last_reason"] or ""),
        }
        for _, row in scored[:limit]
    ]


def playbook_status() -> dict[str, Any]:
    """Return compact diagnostics for the persistent healing playbook."""
    if not bool(getattr(config, "SELF_HEALING_FAILURE_MEMORY_ENABLED", True)):
        return {
            "enabled": False,
            "path": str(_DB_PATH),
            "records": 0,
        }

    with _LOCK:
        conn = _connect()
        try:
            row = conn.execute(
                """
                SELECT COUNT(*) AS records,
                       COALESCE(SUM(occurrences), 0) AS observations,
                       COALESCE(SUM(resolved_count), 0) AS recoveries
                FROM failure_playbook
                """
            ).fetchone()
        finally:
            conn.close()

    return {
        "enabled": True,
        "path": str(_DB_PATH),
        "records": int(row["records"] or 0),
        "observations": int(row["observations"] or 0),
        "recoveries": int(row["recoveries"] or 0),
    }


__all__ = [
    "failure_hints",
    "mark_recovered",
    "playbook_status",
    "record_failure",
]
