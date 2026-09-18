"""Small persistent memory for completed JARVIS tasks.

Only concise task metadata is stored; tool internals and raw logs are not.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List

from config import MAX_TASK_MEMORY, TASK_MEMORY_PATH


def _load() -> List[Dict[str, Any]]:
    try:
        if not TASK_MEMORY_PATH.exists():
            return []
        with open(TASK_MEMORY_PATH, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, list) else []
    except (OSError, json.JSONDecodeError):
        return []


def _save(items: List[Dict[str, Any]]) -> None:
    TASK_MEMORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = TASK_MEMORY_PATH.with_suffix(".tmp")
    with open(temporary, "w", encoding="utf-8") as handle:
        json.dump(items[-MAX_TASK_MEMORY:], handle, indent=2, ensure_ascii=False)
    os.replace(temporary, TASK_MEMORY_PATH)


def record_task(
    request: str,
    goal: str = "",
    status: str = "",
    result: Any = "",
    error: str = "",
    replans: int = 0,
) -> bool:
    entry = {
        "request": str(request or "").strip()[:800],
        "goal": str(goal or "").strip()[:800],
        "status": str(status or "").strip()[:80],
        "result": str(result or "").strip()[:1200],
        "error": str(error or "").strip()[:800],
        "replans": int(replans or 0),
    }

    try:
        items = _load()
        items.append(entry)
        _save(items)
        return True
    except OSError:
        return False


def get_recent(limit: int = 5) -> List[Dict[str, Any]]:
    limit = max(1, min(int(limit), MAX_TASK_MEMORY))
    return _load()[-limit:]


def format_recent(limit: int = 3) -> str:
    items = get_recent(limit)
    if not items:
        return "No recent completed tasks are recorded."

    lines = []
    for item in items:
        request = item.get("request", "")
        status = item.get("status", "unknown")
        result = item.get("result", "")
        if len(result) > 220:
            result = result[:220].rstrip() + "..."
        lines.append(f"- {status}: {request}" + (f" — {result}" if result else ""))

    return "\n".join(lines)
