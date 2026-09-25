"""Optional Screenpipe local-memory bridge for JARVIS.

Screenpipe exposes a local REST API on localhost:3030. Health is intentionally
checked without credentials; authenticated search uses SCREENPIPE_LOCAL_API_KEY
(or the compatibility SCREENPIPE_API_KEY name).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError

_SERVER_PROCESS: subprocess.Popen | None = None


def _base_url() -> str:
    return os.environ.get(
        "SCREENPIPE_LOCAL_API_URL",
        "http://127.0.0.1:3030",
    ).rstrip("/")


def _api_key() -> str:
    return (
        os.environ.get("SCREENPIPE_LOCAL_API_KEY", "").strip()
        or os.environ.get("SCREENPIPE_API_KEY", "").strip()
    )


def _headers(*, authenticated: bool = True) -> dict[str, str]:
    headers = {
        "Accept": "application/json",
        "X-Screenpipe-Client": "api",
        "X-Screenpipe-Agent": "JARVIS",
        "User-Agent": "JARVIS/1.0",
    }
    if authenticated and _api_key():
        headers["Authorization"] = f"Bearer {_api_key()}"
    return headers


def _get(
    path: str,
    params: dict | None = None,
    timeout: int = 8,
    *,
    authenticated: bool = True,
):
    url = f"{_base_url()}{path}"
    if params:
        url += "?" + urlencode(params)
    request = Request(
        url,
        headers=_headers(authenticated=authenticated),
        method="GET",
    )
    with urlopen(request, timeout=timeout) as response:
        raw = response.read().decode("utf-8", errors="replace")
        return json.loads(raw) if raw else {}


def _health_probe() -> tuple[bool, str]:
    try:
        payload = _get("/health", timeout=2, authenticated=False)
        if isinstance(payload, dict):
            status = str(payload.get("status") or "").strip().lower()
            if status in {"ok", "healthy", "ready"} or payload.get("healthy") is True:
                return True, "Screenpipe health endpoint is ready."
        return True, "Screenpipe health endpoint is reachable."
    except HTTPError as exc:
        return False, f"Screenpipe health returned HTTP {exc.code}."
    except Exception as exc:
        return False, f"Screenpipe health probe failed: {exc}"


def screen_memory_setup(argument: str = "") -> dict:
    """Ensure Screenpipe is running and attempt to configure its local API key."""
    del argument

    global _SERVER_PROCESS

    reachable, _ = _health_probe()
    if not reachable:
        executable = (
            shutil.which("screenpipe.exe")
            or shutil.which("screenpipe")
        )
        if not executable:
            return {
                "success": False,
                "tool": "screen_memory_setup",
                "message": (
                    "Screenpipe is not installed or not on PATH. "
                    "Install the Screenpipe desktop/CLI runtime first."
                ),
                "retryable": False,
            }

        if _SERVER_PROCESS is None or _SERVER_PROCESS.poll() is not None:
            kwargs = {
                "stdout": subprocess.DEVNULL,
                "stderr": subprocess.DEVNULL,
            }
            if os.name == "nt":
                kwargs["creationflags"] = (
                    getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
                    | getattr(subprocess, "CREATE_NO_WINDOW", 0)
                )
            _SERVER_PROCESS = subprocess.Popen(
                [executable],
                **kwargs,
            )

        deadline = time.monotonic() + 15.0
        while time.monotonic() < deadline:
            reachable, _ = _health_probe()
            if reachable:
                break
            time.sleep(0.5)

    if not reachable:
        return {
            "success": False,
            "tool": "screen_memory_setup",
            "message": (
                "Screenpipe was started, but its local API did not become "
                "reachable on the configured endpoint."
            ),
            "retryable": True,
        }

    if not _api_key():
        cli = (
            shutil.which("screenpipe.exe")
            or shutil.which("screenpipe")
            or shutil.which("screenpipe.cmd")
        )
        if cli:
            try:
                token_result = subprocess.run(
                    [cli, "auth", "token"],
                    capture_output=True,
                    text=True,
                    timeout=20,
                    check=False,
                )
                if token_result.returncode == 0:
                    candidates = [
                        line.strip().strip('"').strip("'")
                        for line in token_result.stdout.splitlines()
                        if line.strip()
                    ]
                    if candidates:
                        token = candidates[-1]
                        token = re.sub(r"^(?:token|api[-_ ]?key)\s*[:=]\s*", "", token, flags=re.IGNORECASE).strip()
                        if len(token) >= 12 and " " not in token:
                            os.environ["SCREENPIPE_LOCAL_API_KEY"] = token
            except Exception:
                pass

    status = screen_memory_status()
    return {
        "success": bool(status.get("data", {}).get("reachable")),
        "verified": bool(status.get("data", {}).get("reachable")),
        "tool": "screen_memory_setup",
        "data": status.get("data", {}),
        "message": str(status.get("message") or "Screenpipe setup completed."),
        "retryable": not bool(status.get("data", {}).get("reachable")),
    }


def screen_memory_status(argument: str = "") -> dict:
    del argument

    reachable, detail = _health_probe()
    key_configured = bool(_api_key())

    if reachable and key_configured:
        search_ready = True
        status_message = (
            "Screenpipe local memory is running and authenticated search is configured."
        )
    elif reachable:
        search_ready = False
        status_message = (
            "Screenpipe is running locally, but authenticated search is not configured. "
            "Set SCREENPIPE_LOCAL_API_KEY or SCREENPIPE_API_KEY."
        )
    else:
        search_ready = False
        status_message = (
            detail
            + (" Set SCREENPIPE_LOCAL_API_KEY or SCREENPIPE_API_KEY." if not key_configured else "")
        )

    return {
        "success": True,
        "verified": reachable,
        "tool": "screen_memory_status",
        "data": {
            "configured": key_configured,
            "key_configured": key_configured,
            "reachable": reachable,
            "search_ready": search_ready,
            "url": _base_url(),
            "auth_required_for_search": True,
        },
        "message": status_message,
        "retryable": not reachable,
    }


def _parse_payload(argument: str) -> dict:
    raw = str(argument or "").strip()
    if not raw:
        return {}
    if not raw.startswith("{"):
        return {"query": raw}
    try:
        candidate = json.loads(raw)
    except json.JSONDecodeError:
        return {"query": raw}
    return candidate if isinstance(candidate, dict) else {}


def screen_memory_search(argument: str = "") -> dict:
    payload = _parse_payload(argument)

    query_value = payload.get("q") or payload.get("query")
    query = str(query_value or "").strip()
    try:
        limit = max(1, min(int(payload.get("limit", 10) or 10), 20))
    except (TypeError, ValueError):
        limit = 10

    params = {
        "limit": limit,
        "content_type": str(payload.get("content_type", "all") or "all"),
    }
    if query:
        params["q"] = query
    for key in ("start_time", "end_time", "app_name"):
        if payload.get(key):
            params[key] = payload[key]

    if not _api_key():
        return {
            "success": False,
            "tool": "screen_memory_search",
            "message": (
                "Screenpipe search requires an API key. Set "
                "SCREENPIPE_LOCAL_API_KEY or SCREENPIPE_API_KEY."
            ),
            "retryable": False,
        }

    try:
        response = _get("/search", params)
        rows = response.get("data") if isinstance(response, dict) else []
        rows = rows if isinstance(rows, list) else []
        compact = []
        for row in rows[:limit]:
            content = row.get("content") or {}
            compact.append({
                "type": row.get("type"),
                "app_name": content.get("app_name"),
                "window_name": content.get("window_name"),
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
                "total": (
                    response.get("pagination", {}).get("total")
                    if isinstance(response, dict)
                    else len(compact)
                ),
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
    params = {
        "start_time": payload or "1h ago",
        "content_type": "all",
        "limit": 10,
    }
    return screen_memory_search(json.dumps(params))


DISPATCH = {
    "screen_memory_setup": screen_memory_setup,
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
