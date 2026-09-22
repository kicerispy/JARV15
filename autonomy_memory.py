"""Lightweight local experience memory for the active JARVIS Agent Core.

This module records bounded task outcomes outside Git so JARVIS can learn from
repeated failures without mutating source code automatically. The existing
checkpoint -> edit -> test workflow remains the only path for source changes.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from pathlib import Path
from typing import Any

_MEMORY_DIR = Path(".jarvis_autonomy")
_EPISODE_PATH = _MEMORY_DIR / "episodes.jsonl"
_MAX_EPISODES = 500
_MAX_REQUEST_CHARS = 320
_MAX_ERROR_CHARS = 900

_lock = threading.RLock()


def _clean(value: Any, limit: int) -> str:
    return " ".join(str(value or "").strip().split())[:limit]


def _fingerprint(request: str, error: str, tools: list[str]) -> str:
    payload = "|".join([
        _clean(request, 500).lower(),
        _clean(error, 500).lower(),
        ",".join(tools).lower(),
    ])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _load() -> list[dict[str, Any]]:
    if not _EPISODE_PATH.exists():
        return []

    records: list[dict[str, Any]] = []

    try:
        with _EPISODE_PATH.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    item = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(item, dict):
                    records.append(item)
    except OSError:
        return []

    return records[-_MAX_EPISODES:]


def _save(records: list[dict[str, Any]]) -> None:
    _MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    trimmed = records[-_MAX_EPISODES:]

    temp_path = _EPISODE_PATH.with_suffix(".tmp")

    with temp_path.open("w", encoding="utf-8") as handle:
        for item in trimmed:
            handle.write(json.dumps(item, ensure_ascii=True) + "\n")

    temp_path.replace(_EPISODE_PATH)


def record_episode(
    request: str,
    status: str,
    tools: list[str] | tuple[str, ...] | None = None,
    *,
    replans: int = 0,
    duration_seconds: float = 0.0,
    error: str = "",
    domain: str = "",
) -> None:
    """Persist one bounded task outcome for future planning."""
    request_text = _clean(request, _MAX_REQUEST_CHARS)
    error_text = _clean(error, _MAX_ERROR_CHARS)
    tool_names = [
        _clean(tool, 120)
        for tool in (tools or [])
        if _clean(tool, 120)
    ]

    record = {
        "timestamp": time.time(),
        "request": request_text,
        "status": _clean(status, 32).lower(),
        "tools": tool_names[:32],
        "replans": max(0, int(replans or 0)),
        "duration_seconds": max(0.0, float(duration_seconds or 0.0)),
        "error": error_text,
        "domain": _clean(domain, 64).lower(),
    }

    if record["status"] == "failed":
        record["fingerprint"] = _fingerprint(
            request_text,
            error_text,
            tool_names,
        )

    with _lock:
        records = _load()
        records.append(record)
        _save(records)


def get_failure_hints(request: str, limit: int = 3) -> list[str]:
    """Return repeated, relevant failure lessons for a future planner call."""
    if limit <= 0:
        return []

    query_tokens = {
        token.lower()
        for token in _clean(request, 500).split()
        if len(token) >= 4
    }

    if not query_tokens:
        return []

    with _lock:
        records = _load()

    failures = [
        record
        for record in reversed(records)
        if str(record.get("status", "")).lower() == "failed"
        and str(record.get("error", "")).strip()
    ]

    hints: list[str] = []
    seen_fingerprints: set[str] = set()

    for record in failures:
        prior_text = " ".join([
            str(record.get("request", "")),
            str(record.get("error", "")),
            " ".join(str(tool) for tool in record.get("tools", [])),
        ]).lower()

        overlap = sum(
            1
            for token in query_tokens
            if token in prior_text
        )

        if overlap < 2 and not any(
            token in prior_text
            for token in ("roblox", "browser", "code", "python", "git")
            if token in query_tokens
        ):
            continue

        fingerprint = str(record.get("fingerprint", "") or "")
        if fingerprint and fingerprint in seen_fingerprints:
            continue

        if fingerprint:
            seen_fingerprints.add(fingerprint)

        tools = ", ".join(
            str(tool)
            for tool in record.get("tools", [])[:4]
            if tool
        )

        lesson = (
            "Previous failed attempt: "
            + str(record.get("error", "")).strip()
        )

        if tools:
            lesson += f" Tools involved: {tools}."

        lesson += " Do not repeat the same failed strategy blindly."

        hints.append(lesson)

        if len(hints) >= limit:
            break

    return hints


def autonomy_memory_status() -> dict[str, Any]:
    """Return compact local experience-memory statistics."""
    with _lock:
        records = _load()

    failures = sum(
        1
        for record in records
        if str(record.get("status", "")).lower() == "failed"
    )

    return {
        "enabled": True,
        "path": str(_EPISODE_PATH),
        "episodes": len(records),
        "failures": failures,
        "max_episodes": _MAX_EPISODES,
    }
