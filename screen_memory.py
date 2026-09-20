"""Optional Screenpipe local-memory bridge for JARVIS."""

from __future__ import annotations

import json
import os
from urllib.parse import urlencode
from urllib.request import Request, urlopen


def _base_url() -> str:
    return os.environ.get("SCREENPIPE_LOCAL_API_URL", "http://127.0.0.1:3030").rstrip("/")


def _headers() -> dict[str, str]:
    key = os.environ.get("SCREENPIPE_LOCAL_API_KEY", "").strip()
    headers = {
        "Accept": "application/json",
        "X-Screenpipe-Client": "api",
        "X-Screenpipe-Agent": "JARVIS",
        "User-Agent": "JARVIS/1.0",
    }
    if key:
        headers["Authorization"] = f"Bearer {key}"
    return headers


def _get(path: str, params: dict | None = None, timeout: int = 8):
    url = f"{_base_url()}{path}"
    if params:
        url += "?" + urlencode(params)
    request = Request(url, headers=_headers(), method="GET")
    with urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8", errors="replace"))


def screen_memory_status(argument: str = "") -> dict:
    key_configured = bool(os.environ.get("SCREENPIPE_LOCAL_API_KEY", "").strip())
    if not key_configured:
        return {
            "success": True,
            "tool": "screen_memory_status",
            "data": {
                "configured": False,
                "url": _base_url(),
                "requires_api_key": True,
            },
            "message": "Screenpipe is not configured in JARVIS. Set SCREENPIPE_LOCAL_API_KEY to enable local screen memory.",
        }

    try:
        payload = _get("/search", {"limit": 1, "content_type": "all"})
        return {
            "success": True,
            "tool": "screen_memory_status",
            "data": {
                "configured": True,
                "reachable": True,
                "url": _base_url(),
                "result_count": len(payload.get("data") or []) if isinstance(payload, dict) else 0,
            },
            "message": "Screenpipe local memory is reachable.",
        }
    except Exception as exc:
        return {
            "success": False,
            "tool": "screen_memory_status",
            "message": f"Screenpipe local memory is not reachable: {exc}",
            "retryable": True,
        }


def screen_memory_search(argument: str = "") -> dict:
    raw = str(argument or "").strip()
    payload = {}
    if raw.startswith("{"):
        try:
            candidate = json.loads(raw)
            if isinstance(candidate, dict):
                payload = candidate
        except json.JSONDecodeError:
            payload = {}

    query = str(payload.get("q") or payload.get("query") or raw).strip()
    params = {
        "limit": int(payload.get("limit", 10) or 10),
        "content_type": str(payload.get("content_type", "all") or "all"),
    }
    if query:
        params["q"] = query
    for key in ("start_time", "end_time", "app_name"):
        if payload.get(key):
            params[key] = payload[key]

    if not os.environ.get("SCREENPIPE_LOCAL_API_KEY", "").strip():
        return {
            "success": False,
            "tool": "screen_memory_search",
            "message": "Set SCREENPIPE_LOCAL_API_KEY to use Screenpipe local search.",
            "retryable": False,
        }

    try:
        response = _get("/search", params)
        rows = response.get("data") if isinstance(response, dict) else []
        rows = rows if isinstance(rows, list) else []
        compact = []
        for row in rows[:10]:
            content = row.get("content") or {}
            compact.append({
                "type": row.get("type"),
                "app_name": content.get("app_name"),
                "text": content.get("text") or content.get("transcription"),
                "timestamp": content.get("timestamp"),
                "frame_id": content.get("frame_id"),
                "url": content.get("url"),
            })
        return {
            "success": True,
            "tool": "screen_memory_search",
            "data": {
                "query": query,
                "items": compact,
                "total": response.get("pagination", {}).get("total") if isinstance(response, dict) else len(compact),
                "source": "Screenpipe local REST API",
            },
            "message": f"Screen memory search returned {len(compact)} result(s).",
        }
    except Exception as exc:
        return {
            "success": False,
            "tool": "screen_memory_search",
            "message": f"Screenpipe search failed: {exc}",
            "retryable": True,
        }


def screen_memory_recent(argument: str = "") -> dict:
    payload = str(argument or "").strip()
    if payload:
        params = {"start_time": payload, "content_type": "all", "limit": 10}
    else:
        params = {"start_time": "1h ago", "content_type": "all", "limit": 10}
    return screen_memory_search(json.dumps(params))


DISPATCH = {
    "screen_memory_status": screen_memory_status,
    "screen_memory_search": screen_memory_search,
    "screen_memory_recent": screen_memory_recent,
}


def run_screen_memory_tool(tool_name: str, argument: str = ""):
    function = DISPATCH.get(str(tool_name or "").strip())
    if function is None:
        return {
            "success": False,
            "tool": tool_name,
            "message": f"Unknown screen-memory tool: {tool_name}",
            "retryable": False,
        }
    return function(argument)
