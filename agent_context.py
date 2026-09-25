"""Unified JARVIS context/memory facade.

Backends:
- OpenViking HTTP API (preferred when configured/reachable)
- agentmemory REST API
- JARVIS SQLite memory fallback

The facade deliberately uses HTTP instead of importing either upstream runtime.
This keeps JARVIS startup small and lets either service be upgraded independently.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from typing import Any, Dict, List, Optional

import requests

from config import (
    AGENT_MEMORY_URL,
    AGENT_MEMORY_SECRET,
    OPENVIKING_URL,
    OPENVIKING_API_KEY,
    OPENVIKING_USER,
    OPENVIKING_ACCOUNT,
    CONTEXT_MEMORY_BACKEND,
)

_SESSION_RE = re.compile(r"[^a-zA-Z0-9_-]+")
_STATUS_CACHE: Optional[Dict[str, Any]] = None
_STATUS_CACHE_AT = 0.0
_STATUS_CACHE_TTL = 30.0


def _clean(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def _bounded_text(value: Any, limit: int = 4000) -> str:
    return _clean(value)[:limit]


def _headers_json(extra: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": "JARVIS-context/1.0",
    }
    if extra:
        headers.update(extra)
    return headers


def _agentmemory_headers() -> Dict[str, str]:
    headers = _headers_json()
    if AGENT_MEMORY_SECRET:
        headers["Authorization"] = f"Bearer {AGENT_MEMORY_SECRET}"
    return headers


def _openviking_headers() -> Dict[str, str]:
    headers = _headers_json()
    if OPENVIKING_API_KEY:
        headers["X-API-Key"] = OPENVIKING_API_KEY
    if OPENVIKING_ACCOUNT:
        headers["X-OpenViking-Account"] = OPENVIKING_ACCOUNT
    if OPENVIKING_USER:
        headers["X-OpenViking-User"] = OPENVIKING_USER
    return headers


def _join_url(base: str, path: str) -> str:
    return f"{str(base or '').rstrip('/')}/{path.lstrip('/')}"


def _request_json(
    method: str,
    url: str,
    *,
    headers: Dict[str, str],
    timeout: float,
    **kwargs: Any,
) -> Any:
    response = requests.request(
        method,
        url,
        headers=headers,
        timeout=timeout,
        **kwargs,
    )
    response.raise_for_status()
    if not response.content:
        return {}
    return response.json()


def _extract_result(payload: Any) -> Any:
    if isinstance(payload, dict) and "result" in payload:
        return payload["result"]
    return payload


def _backend_order() -> List[str]:
    requested = str(CONTEXT_MEMORY_BACKEND or "auto").strip().lower()
    if requested in {"openviking", "agentmemory", "local"}:
        return [requested]
    return ["openviking", "agentmemory", "local"]


def _local_memory():
    # Import lazily so the external backends never make the legacy SQLite
    # module part of the import/startup critical path.
    from memory import memory
    return memory


def backend_status(timeout: float = 1.2, force: bool = False) -> Dict[str, Any]:
    """Return reachability for all configured context backends."""
    global _STATUS_CACHE, _STATUS_CACHE_AT

    now = time.monotonic()
    if not force and _STATUS_CACHE is not None and (now - _STATUS_CACHE_AT) < _STATUS_CACHE_TTL:
        return dict(_STATUS_CACHE)

    status: Dict[str, Any] = {
        "configured_backend": CONTEXT_MEMORY_BACKEND,
        "backends": {},
    }

    try:
        payload = _request_json(
            "GET",
            _join_url(OPENVIKING_URL, "/health"),
            headers=_openviking_headers(),
            timeout=timeout,
        )
        status["backends"]["openviking"] = {
            "reachable": True,
            "healthy": payload.get("status") == "ok" if isinstance(payload, dict) else True,
            "url": OPENVIKING_URL,
        }
    except Exception as exc:
        status["backends"]["openviking"] = {
            "reachable": False,
            "healthy": False,
            "url": OPENVIKING_URL,
            "error": str(exc),
        }

    try:
        response = requests.get(
            _join_url(AGENT_MEMORY_URL, "/agentmemory/livez"),
            headers=_agentmemory_headers(),
            timeout=timeout,
        )
        response.raise_for_status()
        status["backends"]["agentmemory"] = {
            "reachable": True,
            "healthy": True,
            "url": AGENT_MEMORY_URL,
        }
    except Exception as exc:
        status["backends"]["agentmemory"] = {
            "reachable": False,
            "healthy": False,
            "url": AGENT_MEMORY_URL,
            "error": str(exc),
        }

    try:
        local_count = int(_local_memory().count())
        status["backends"]["local"] = {
            "reachable": True,
            "healthy": True,
            "memory_count": local_count,
            "path": str(_local_memory().db_path),
        }
    except Exception as exc:
        status["backends"]["local"] = {
            "reachable": False,
            "healthy": False,
            "error": str(exc),
        }

    selected = None
    for backend in _backend_order():
        entry = status["backends"].get(backend, {})
        if entry.get("reachable") and entry.get("healthy"):
            selected = backend
            break
    status["selected_backend"] = selected
    _STATUS_CACHE = dict(status)
    _STATUS_CACHE_AT = now
    return status


def _choose_backend() -> str:
    requested = str(CONTEXT_MEMORY_BACKEND or "auto").strip().lower()
    if requested in {"openviking", "agentmemory", "local"}:
        return requested

    status = backend_status()
    return str(status.get("selected_backend") or "local")


def _agentmemory_post(path: str, payload: Dict[str, Any], timeout: float = 8.0) -> Any:
    return _extract_result(
        _request_json(
            "POST",
            _join_url(AGENT_MEMORY_URL, path),
            headers=_agentmemory_headers(),
            timeout=timeout,
            json=payload,
        )
    )


def _openviking_post(path: str, payload: Dict[str, Any], timeout: float = 8.0) -> Any:
    return _extract_result(
        _request_json(
            "POST",
            _join_url(OPENVIKING_URL, path),
            headers=_openviking_headers(),
            timeout=timeout,
            json=payload,
        )
    )


def remember(
    content: str,
    *,
    concepts: Optional[List[str]] = None,
    memory_type: str = "fact",
    files: Optional[List[str]] = None,
    project: str = "",
    ttl_days: Optional[int] = None,
) -> Dict[str, Any]:
    """Persist a durable fact/lesson with automatic backend selection."""
    text = _bounded_text(content)
    if not text:
        return {"success": False, "backend": "none", "message": "Memory content is empty."}

    concepts = [str(item).strip() for item in (concepts or []) if str(item).strip()][:32]
    files = [str(item).strip() for item in (files or []) if str(item).strip()][:32]

    for backend in _backend_order():
        try:
            if backend == "openviking":
                seed = hashlib.sha1(f"{time.time_ns()}:{text}".encode("utf-8")).hexdigest()[:12]
                session_id = _SESSION_RE.sub("-", f"jarvis-memory-{seed}").strip("-")
                _openviking_post(
                    "/api/v1/sessions",
                    {"session_id": session_id},
                )
                _openviking_post(
                    f"/api/v1/sessions/{session_id}/messages",
                    {
                        "role": "user",
                        "content": text,
                        "peer_id": "jarvis",
                    },
                )
                committed = _openviking_post(
                    f"/api/v1/sessions/{session_id}/commit",
                    {"keep_recent_count": 0},
                )
                return {
                    "success": True,
                    "backend": "openviking",
                    "session_id": session_id,
                    "result": committed,
                }

            if backend == "agentmemory":
                result = _agentmemory_post(
                    "/agentmemory/remember",
                    {
                        "content": text,
                        "concepts": concepts,
                        "files": files,
                        "type": memory_type,
                        "project": project or None,
                        **({"ttlDays": ttl_days} if ttl_days else {}),
                    },
                )
                return {"success": True, "backend": "agentmemory", "result": result}

            local = _local_memory()
            saved = local.save_memory(text)
            return {
                "success": bool(saved or local.memory_exists(text)),
                "backend": "local",
                "saved": bool(saved),
            }
        except Exception as exc:
            if backend == "local":
                return {
                    "success": False,
                    "backend": "local",
                    "message": f"Local memory failed: {exc}",
                }

    return {"success": False, "backend": "none", "message": "No context backend succeeded."}


def recall(query: str, limit: int = 8) -> Dict[str, Any]:
    """Retrieve semantically relevant context from the selected backend."""
    query = _bounded_text(query, 1200)
    limit = max(1, min(int(limit), 25))
    if not query:
        return {"success": False, "backend": "none", "results": []}

    for backend in _backend_order():
        try:
            if backend == "openviking":
                result = _openviking_post(
                    "/api/v1/search/find",
                    {"query": query, "limit": limit},
                )
                return {"success": True, "backend": "openviking", "results": result}

            if backend == "agentmemory":
                result = _agentmemory_post(
                    "/agentmemory/smart-search",
                    {"query": query, "limit": limit},
                )
                return {"success": True, "backend": "agentmemory", "results": result}

            memories = _local_memory().get_memories(limit=limit)
            lowered = query.lower()
            ranked = sorted(
                memories,
                key=lambda item: (
                    0 if lowered in str(item[0]).lower() else 1,
                    -len(str(item[0])),
                ),
            )
            return {
                "success": True,
                "backend": "local",
                "results": [{"memory": row[0]} for row in ranked[:limit]],
            }
        except Exception as exc:
            if backend == "local":
                return {"success": False, "backend": "local", "results": [], "message": str(exc)}

    return {"success": False, "backend": "none", "results": []}


def context(query: str, limit: int = 8) -> Dict[str, Any]:
    """Return a compact context block when a backend provides one."""
    query = _bounded_text(query, 1200)
    limit = max(1, min(int(limit), 25))
    for backend in _backend_order():
        try:
            if backend == "openviking":
                result = _openviking_post(
                    "/api/v1/search/search",
                    {
                        "query": query,
                        "limit": limit,
                        "mode": "context",
                    },
                )
                return {"success": True, "backend": "openviking", "context": result}

            if backend == "agentmemory":
                result = _agentmemory_post(
                    "/agentmemory/context",
                    {"query": query, "limit": limit},
                )
                return {"success": True, "backend": "agentmemory", "context": result}

            return recall(query, limit)
        except Exception as exc:
            if backend == "local":
                return {"success": False, "backend": "local", "context": "", "message": str(exc)}

    return {"success": False, "backend": "none", "context": ""}


def read(uri: str, limit: int = 12000) -> Dict[str, Any]:
    """Read an OpenViking URI when that backend is available."""
    uri = _bounded_text(uri, 2000)
    limit = max(1, min(int(limit), 50000))
    try:
        value = _request_json(
            "GET",
            _join_url(OPENVIKING_URL, "/api/v1/content/read"),
            headers=_openviking_headers(),
            timeout=10.0,
            params={"uri": uri, "offset": 0, "limit": limit},
        )
        return {"success": True, "backend": "openviking", "content": value}
    except Exception as exc:
        return {"success": False, "backend": "openviking", "content": "", "message": str(exc)}


def openviking_add_resource(
    path: str,
    *,
    to: str = "",
    parent: str = "",
    wait: bool = False,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "wait": bool(wait),
    }
    if to:
        payload["to"] = to
    if parent:
        payload["parent"] = parent
    if path:
        payload["path"] = path
    try:
        result = _openviking_post("/api/v1/resources", payload, timeout=30.0)
        return {"success": True, "backend": "openviking", "result": result}
    except Exception as exc:
        return {"success": False, "backend": "openviking", "message": str(exc)}


def openviking_add_skill(skill_data: Any, target_uri: str = "") -> Dict[str, Any]:
    payload: Dict[str, Any] = {"data": skill_data}
    if target_uri:
        payload["options"] = {"target_uri": target_uri}
    try:
        result = _openviking_post("/api/v1/skills", payload, timeout=30.0)
        return {"success": True, "backend": "openviking", "result": result}
    except Exception as exc:
        return {"success": False, "backend": "openviking", "message": str(exc)}


def run_context_tool(tool_name: str, argument: Any = "") -> Any:
    """Dispatcher used by tools.py."""
    name = str(tool_name or "").strip()
    if name == "context_backend_status":
        return backend_status()
    if name == "context_remember":
        try:
            payload = json.loads(str(argument or "{}"))
        except (json.JSONDecodeError, TypeError):
            return {"success": False, "message": "context_remember expects a JSON object."}
        if not isinstance(payload, dict):
            return {"success": False, "message": "context_remember expects a JSON object."}
        return remember(
            str(payload.get("content") or ""),
            concepts=payload.get("concepts") if isinstance(payload.get("concepts"), list) else [],
            memory_type=str(payload.get("type") or "fact"),
            files=payload.get("files") if isinstance(payload.get("files"), list) else [],
            project=str(payload.get("project") or ""),
            ttl_days=payload.get("ttlDays"),
        )
    if name == "context_recall":
        if isinstance(argument, dict):
            payload = argument
        else:
            try:
                payload = json.loads(str(argument or "{}"))
            except (json.JSONDecodeError, TypeError):
                payload = {"query": str(argument or "")}
        return recall(
            str(payload.get("query") or ""),
            int(payload.get("limit") or 8),
        )
    if name == "context_search":
        try:
            payload = json.loads(str(argument or "{}"))
        except (json.JSONDecodeError, TypeError):
            payload = {"query": str(argument or "")}
        return context(
            str(payload.get("query") or ""),
            int(payload.get("limit") or 8),
        )
    if name == "context_read":
        try:
            payload = json.loads(str(argument or "{}"))
        except (json.JSONDecodeError, TypeError):
            return {"success": False, "message": "context_read expects JSON {uri,limit}."}
        return read(str(payload.get("uri") or ""), int(payload.get("limit") or 12000))
    if name == "openviking_add_resource":
        try:
            payload = json.loads(str(argument or "{}"))
        except (json.JSONDecodeError, TypeError):
            return {"success": False, "message": "openviking_add_resource expects JSON."}
        return openviking_add_resource(
            str(payload.get("path") or ""),
            to=str(payload.get("to") or ""),
            parent=str(payload.get("parent") or ""),
            wait=bool(payload.get("wait", False)),
        )
    if name == "openviking_add_skill":
        try:
            payload = json.loads(str(argument or "{}"))
        except (json.JSONDecodeError, TypeError):
            return {"success": False, "message": "openviking_add_skill expects JSON."}
        return openviking_add_skill(payload.get("data"), str(payload.get("target_uri") or ""))
    return {"success": False, "message": f"Unknown context tool: {name}"}
