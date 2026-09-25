"""Tiny dependency-free persistent memory layer for local JARVIS.

The store keeps semantic facts, preferences, procedures, and lessons in a
bounded JSONL journal. Retrieval is deterministic keyword scoring so memory
remains useful even when Ollama is unavailable.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Dict, List

import config
from healing_kernel import redact_sensitive


_MEMORY_DIR = Path(getattr(config, "BASE_DIR", Path("."))) / ".jarvis_autonomy"
_MEMORY_PATH = _MEMORY_DIR / "memory.jsonl"
_MAX_RECORDS = 1000
_MAX_TEXT = 700
_LOCK = threading.RLock()


def _index_path() -> Path:
    """Return the optional SQLite FTS5 shadow index beside the JSONL journal."""
    return _MEMORY_DIR / "memory_fts.sqlite3"


def _fts_available() -> bool:
    try:
        conn = sqlite3.connect(":memory:")
        try:
            conn.execute(
                "CREATE VIRTUAL TABLE fts_probe USING fts5(text)"
            )
            return True
        finally:
            conn.close()
    except sqlite3.Error:
        return False


def _rebuild_fts(records: List[Dict[str, Any]]) -> bool:
    """Rebuild the bounded FTS5 cache from the durable JSONL records."""
    if not _fts_available():
        return False

    try:
        _MEMORY_DIR.mkdir(parents=True, exist_ok=True)
        path = _index_path()
        temp = path.with_suffix(".tmp")
        conn = sqlite3.connect(str(temp), timeout=5.0)
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("DROP TABLE IF EXISTS memories")
            conn.execute(
                """
                CREATE VIRTUAL TABLE memories USING fts5(
                    fingerprint UNINDEXED,
                    text,
                    tags,
                    kind UNINDEXED,
                    timestamp UNINDEXED,
                    tokenize='porter unicode61'
                )
                """
            )
            for item in records[-_MAX_RECORDS:]:
                conn.execute(
                    """
                    INSERT INTO memories(
                        fingerprint, text, tags, kind, timestamp
                    )
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        str(item.get("fingerprint", "")),
                        str(item.get("text", "")),
                        " ".join(str(tag) for tag in item.get("tags", [])),
                        str(item.get("kind", "fact")),
                        float(item.get("timestamp", 0.0) or 0.0),
                    ),
                )
            conn.commit()
        finally:
            conn.close()

        temp.replace(path)
        return True
    except (OSError, sqlite3.Error):
        return False


def _fts_search(query: str, limit: int) -> list[tuple[str, float]]:
    """Return fingerprint/rank pairs from the FTS5 cache, or [] on failure."""
    if not _fts_available():
        return []

    tokens = sorted(_tokens(query))
    if not tokens:
        return []

    match_query = " OR ".join(
        '"' + token.replace('"', '""') + '"'
        for token in tokens
    )

    try:
        conn = sqlite3.connect(str(_index_path()), timeout=2.0)
        try:
            rows = conn.execute(
                """
                SELECT fingerprint, bm25(memories) AS rank
                FROM memories
                WHERE memories MATCH ?
                ORDER BY bm25(memories)
                LIMIT ?
                """,
                (match_query, max(1, int(limit))),
            ).fetchall()
        finally:
            conn.close()

        return [
            (str(row[0]), float(row[1]))
            for row in rows
            if str(row[0] or "")
        ]
    except (OSError, sqlite3.Error):
        return []


def _tokens(value: Any) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9_'-]+", str(value or "").lower())
        if len(token) >= 3
    }


def _fingerprint(kind: str, text: str) -> str:
    return hashlib.sha256(
        f"{kind}|{str(text).strip().lower()}".encode("utf-8")
    ).hexdigest()[:16]


def _load() -> List[Dict[str, Any]]:
    if not _MEMORY_PATH.exists():
        return []
    records: List[Dict[str, Any]] = []
    try:
        with _MEMORY_PATH.open("r", encoding="utf-8") as handle:
            for line in handle:
                try:
                    item = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(item, dict):
                    records.append(item)
    except OSError:
        return []
    return records[-_MAX_RECORDS:]


def _save(records: List[Dict[str, Any]]) -> None:
    _MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    temp = _MEMORY_PATH.with_suffix(".tmp")
    with temp.open("w", encoding="utf-8") as handle:
        for item in records[-_MAX_RECORDS:]:
            handle.write(
                json.dumps(item, ensure_ascii=True, sort_keys=True)
                + "\n"
            )
    temp.replace(_MEMORY_PATH)


def remember(
    text: str,
    *,
    kind: str = "fact",
    tags: List[str] | None = None,
) -> Dict[str, Any]:
    value = redact_sensitive(str(text or "").strip(), _MAX_TEXT)
    if not value:
        return {
            "success": False,
            "verified": False,
            "message": "Memory text cannot be empty.",
        }

    normalized_kind = str(kind or "fact").strip().lower()
    if normalized_kind not in {"fact", "preference", "procedure", "lesson"}:
        normalized_kind = "fact"

    tag_values = [
        redact_sensitive(str(tag), 80)
        for tag in (tags or [])
        if str(tag or "").strip()
    ][:12]

    fingerprint = _fingerprint(normalized_kind, value)

    with _LOCK:
        records = _load()
        records = [
            item
            for item in records
            if str(item.get("fingerprint", "")) != fingerprint
        ]
        record = {
            "timestamp": time.time(),
            "kind": normalized_kind,
            "text": value,
            "tags": tag_values,
            "fingerprint": fingerprint,
        }
        records.append(record)
        _save(records)
        _rebuild_fts(records)

    return {
        "success": True,
        "verified": True,
        "kind": normalized_kind,
        "text": value,
        "tags": tag_values,
        "message": "Memory stored locally.",
    }


def recall(query: str, *, limit: int = 5, kind: str = "") -> List[Dict[str, Any]]:
    query_tokens = _tokens(query)

    with _LOCK:
        records = _load()

    wanted_kind = str(kind or "").strip().lower()

    if not query_tokens:
        recent = [
            item
            for item in records
            if not wanted_kind
            or str(item.get("kind", "")).lower() == wanted_kind
        ]
        recent.sort(
            key=lambda item: float(item.get("timestamp", 0.0) or 0.0),
            reverse=True,
        )
        return [
            {
                "kind": str(item.get("kind", "fact")),
                "text": str(item.get("text", "")),
                "tags": list(item.get("tags", [])),
                "score": 0.0,
            }
            for item in recent[: max(1, int(limit))]
        ]

    fts_rows = _fts_search(query, max(10, int(limit) * 5))
    fts_scores = {
        fingerprint: abs(rank)
        for fingerprint, rank in fts_rows
    }

    scored = []

    for item in records:
        if wanted_kind and str(item.get("kind", "")).lower() != wanted_kind:
            continue

        text = str(item.get("text", ""))
        haystack = _tokens(text) | _tokens(" ".join(item.get("tags", [])))
        overlap = len(query_tokens & haystack)
        fts_rank = fts_scores.get(
            str(item.get("fingerprint", "")),
            0.0,
        )
        if overlap <= 0 and not fts_rank:
            continue

        age_days = max(0.0, (time.time() - float(item.get("timestamp", time.time()))) / 86400)
        recency = min(3.0, 1.0 / max(0.25, age_days + 0.25))
        score = overlap * 10.0 + min(8.0, fts_rank) + recency
        scored.append((score, item))

    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [
        {
            "kind": str(item.get("kind", "fact")),
            "text": str(item.get("text", "")),
            "tags": list(item.get("tags", [])),
            "score": round(score, 3),
        }
        for score, item in scored[: max(1, int(limit))]
    ]


def forget(query: str) -> Dict[str, Any]:
    text = str(query or "").strip()
    if not text:
        return {
            "success": False,
            "verified": False,
            "message": "Memory query cannot be empty.",
        }

    query_tokens = _tokens(text)
    with _LOCK:
        records = _load()
        kept = []
        removed = 0
        for item in records:
            haystack = _tokens(item.get("text", "")) | _tokens(
                " ".join(item.get("tags", []))
            )
            exact = text.lower() in str(item.get("text", "")).lower()
            if exact or query_tokens and query_tokens.issubset(haystack):
                removed += 1
                continue
            kept.append(item)

        _save(kept)
        _rebuild_fts(kept)

    return {
        "success": True,
        "verified": True,
        "removed": removed,
        "message": f"Forgot {removed} matching memory item(s).",
    }


def memory_status() -> Dict[str, Any]:
    with _LOCK:
        records = _load()

    counts: Dict[str, int] = {}
    for item in records:
        kind = str(item.get("kind", "fact"))
        counts[kind] = counts.get(kind, 0) + 1

    return {
        "enabled": True,
        "path": str(_MEMORY_PATH),
        "records": len(records),
        "by_kind": counts,
        "max_records": _MAX_RECORDS,
        "fts5_enabled": _fts_available(),
        "fts5_index": str(_index_path()),
    }


__all__ = ["remember", "recall", "forget", "memory_status"]
