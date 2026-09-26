"""Optional adaptive runtime helpers for JARVIS.

This module deliberately avoids hard dependencies on third-party agent hosts.
It provides:
- Hindsight long-term memory over its local HTTP API.
- Magnitude installation/capability detection without making it a runtime dependency.
- A compact action-first response formatter inspired by concise agent UX practices.
- A conservative coding-plan review that favors reuse, minimal edits, and verification.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from typing import Any, Dict

import requests


def _bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


HINDSIGHT_URL = os.environ.get("JARVIS_HINDSIGHT_URL", "http://127.0.0.1:8888").strip().rstrip("/")
HINDSIGHT_BANK_ID = os.environ.get("JARVIS_HINDSIGHT_BANK_ID", "jarvis").strip() or "jarvis"
HINDSIGHT_API_KEY = os.environ.get("JARVIS_HINDSIGHT_API_KEY", "").strip()
HINDSIGHT_TIMEOUT = max(0.5, float(os.environ.get("JARVIS_HINDSIGHT_TIMEOUT", "8")))
ADAPTIVE_MEMORY_ENABLED = _bool(os.environ.get("JARVIS_ADAPTIVE_MEMORY_ENABLED", "0"))
ADAPTIVE_RESPONSE_STYLE = os.environ.get("JARVIS_RESPONSE_STYLE", "action_first").strip().lower()

_SECRET_RE = re.compile(
    r"(?i)(authorization|api[_ -]?key|token|password|secret)\s*[=:]\s*[^\s,;]+"
)


def _headers() -> Dict[str, str]:
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": "JARVIS-adaptive-runtime/1.0",
    }
    if HINDSIGHT_API_KEY:
        headers["Authorization"] = f"Bearer {HINDSIGHT_API_KEY}"
    return headers


def _hindsight_request(method: str, path: str, payload: Any = None, timeout: float | None = None) -> Any:
    response = requests.request(
        method,
        f"{HINDSIGHT_URL}/{path.lstrip('/')}",
        headers=_headers(),
        json=payload,
        timeout=timeout or HINDSIGHT_TIMEOUT,
    )
    response.raise_for_status()
    if not response.content:
        return {}
    return response.json()


def hindsight_status() -> Dict[str, Any]:
    started = time.perf_counter()
    if not ADAPTIVE_MEMORY_ENABLED:
        return {
            "success": True,
            "verified": True,
            "enabled": False,
            "configured": bool(HINDSIGHT_URL),
            "reachable": False,
            "message": "Hindsight adaptive memory is disabled.",
        }

    try:
        health = _hindsight_request("GET", "/health", timeout=min(HINDSIGHT_TIMEOUT, 2.0))
        version = _hindsight_request("GET", "/version", timeout=min(HINDSIGHT_TIMEOUT, 2.0))
        return {
            "success": True,
            "verified": True,
            "enabled": True,
            "reachable": True,
            "url": HINDSIGHT_URL,
            "bank_id": HINDSIGHT_BANK_ID,
            "health": health,
            "version": version,
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 1),
        }
    except Exception as exc:
        return {
            "success": False,
            "verified": True,
            "enabled": True,
            "reachable": False,
            "url": HINDSIGHT_URL,
            "bank_id": HINDSIGHT_BANK_ID,
            "message": f"Hindsight is unavailable: {exc}",
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 1),
        }


def hindsight_remember(
    content: str,
    *,
    document_id: str = "jarvis",
    context: str = "jarvis",
    tags: list[str] | None = None,
) -> Dict[str, Any]:
    text = str(content or "").strip()
    if not text:
        return {"success": False, "verified": False, "message": "Memory content is empty."}
    if not ADAPTIVE_MEMORY_ENABLED:
        return {"success": False, "verified": False, "message": "Hindsight adaptive memory is disabled."}

    item = {
        "content": text[:10000],
        "document_id": str(document_id or "jarvis")[:200],
        "metadata": {"source": "jarvis"},
    }
    if context:
        item["context"] = str(context)[:500]
    if tags:
        item["tags"] = [str(tag)[:100] for tag in tags[:16]]

    try:
        data = _hindsight_request(
            "POST",
            f"/v1/default/banks/{requests.utils.quote(HINDSIGHT_BANK_ID, safe='')}/memories",
            {"items": [item], "async": True},
        )
        return {
            "success": True,
            "verified": True,
            "backend": "hindsight",
            "bank_id": HINDSIGHT_BANK_ID,
            "result": data,
        }
    except Exception as exc:
        return {
            "success": False,
            "verified": True,
            "backend": "hindsight",
            "message": f"Hindsight retain failed: {exc}",
        }


def hindsight_recall(query: str, *, limit: int = 8, budget: str = "mid") -> Dict[str, Any]:
    text = str(query or "").strip()
    if not text:
        return {"success": False, "verified": False, "results": []}
    if not ADAPTIVE_MEMORY_ENABLED:
        return {"success": False, "verified": False, "results": [], "message": "Hindsight adaptive memory is disabled."}

    payload = {
        "query": text[:4000],
        "max_tokens": max(128, min(int(limit) * 256, 4096)),
        "budget": str(budget or "mid"),
    }

    try:
        data = _hindsight_request(
            "POST",
            f"/v1/default/banks/{requests.utils.quote(HINDSIGHT_BANK_ID, safe='')}/memories/recall",
            payload,
        )
        results = data.get("results", data) if isinstance(data, dict) else data
        return {
            "success": True,
            "verified": True,
            "backend": "hindsight",
            "bank_id": HINDSIGHT_BANK_ID,
            "query": text,
            "results": results,
        }
    except Exception as exc:
        return {
            "success": False,
            "verified": True,
            "backend": "hindsight",
            "results": [],
            "message": f"Hindsight recall failed: {exc}",
        }


def hindsight_reflect(query: str, *, budget: str = "mid", max_tokens: int = 1200) -> Dict[str, Any]:
    text = str(query or "").strip()
    if not text:
        return {"success": False, "verified": False, "answer": ""}
    if not ADAPTIVE_MEMORY_ENABLED:
        return {"success": False, "verified": False, "answer": "", "message": "Hindsight adaptive memory is disabled."}

    try:
        data = _hindsight_request(
            "POST",
            f"/v1/default/banks/{requests.utils.quote(HINDSIGHT_BANK_ID, safe='')}/reflect",
            {
                "query": text[:4000],
                "budget": str(budget or "mid"),
                "max_tokens": max(128, min(int(max_tokens), 4096)),
            },
            timeout=max(HINDSIGHT_TIMEOUT, 15.0),
        )
        answer = ""
        if isinstance(data, dict):
            answer = str(data.get("text") or data.get("answer") or "").strip()
        return {
            "success": True,
            "verified": True,
            "backend": "hindsight",
            "bank_id": HINDSIGHT_BANK_ID,
            "answer": answer,
            "result": data,
        }
    except Exception as exc:
        return {
            "success": False,
            "verified": True,
            "backend": "hindsight",
            "answer": "",
            "message": f"Hindsight reflect failed: {exc}",
        }


def adaptive_memory_tool(tool_name: str, argument: str = "") -> Dict[str, Any]:
    raw = str(argument or "").strip()
    payload: Dict[str, Any] = {}
    if raw:
        try:
            candidate = json.loads(raw)
            if isinstance(candidate, dict):
                payload = candidate
        except (json.JSONDecodeError, TypeError):
            payload = {"query": raw, "content": raw}

    if tool_name == "hindsight_status":
        return hindsight_status()
    if tool_name == "hindsight_remember":
        return hindsight_remember(
            str(payload.get("content") or ""),
            document_id=str(payload.get("document_id") or "jarvis"),
            context=str(payload.get("context") or "jarvis"),
            tags=payload.get("tags") if isinstance(payload.get("tags"), list) else [],
        )
    if tool_name == "hindsight_recall":
        return hindsight_recall(
            str(payload.get("query") or ""),
            limit=int(payload.get("limit") or 8),
            budget=str(payload.get("budget") or "mid"),
        )
    if tool_name == "hindsight_reflect":
        return hindsight_reflect(
            str(payload.get("query") or ""),
            budget=str(payload.get("budget") or "mid"),
            max_tokens=int(payload.get("max_tokens") or 1200),
        )
    return {"success": False, "verified": False, "message": f"Unknown adaptive memory tool: {tool_name}"}


def _redact(text: str) -> str:
    return _SECRET_RE.sub(r"\1=<redacted>", text)


def response_style(text: str, *, max_items: int = 5, max_chars: int = 900) -> str:
    """Apply action-first, state-aware response shaping without changing facts."""
    value = " ".join(_redact(str(text or "")).strip().split())
    if not value:
        return ""

    if len(value) <= max_chars and not ADAPTIVE_RESPONSE_STYLE:
        return value

    # Preserve explicit numbered items while removing common throat-clearing.
    value = re.sub(
        r"^(?:sure|absolutely|great question|no problem|of course)[,!.\s]+",
        "",
        value,
        flags=re.IGNORECASE,
    ).strip()

    sentences = [part.strip() for part in re.split(r"(?<=[.!?])\s+", value) if part.strip()]
    if len(sentences) > max_items:
        sentences = sentences[:max_items]

    return " ".join(sentences)[:max_chars].rstrip()


def coding_style_review(argument: str = "") -> Dict[str, Any]:
    """Review a proposed change for avoidable complexity before mutation."""
    raw = str(argument or "").strip()
    payload: Dict[str, Any] = {}
    if raw:
        try:
            candidate = json.loads(raw)
            if isinstance(candidate, dict):
                payload = candidate
        except (json.JSONDecodeError, TypeError):
            payload = {"request": raw}

    steps = payload.get("steps", [])
    files = payload.get("files", [])
    request = str(payload.get("request") or "").strip()

    steps = [step for step in steps if isinstance(step, dict)] if isinstance(steps, list) else []
    files = [str(item) for item in files if str(item).strip()] if isinstance(files, list) else []

    tool_names = [str(step.get("tool") or "").strip() for step in steps if step.get("tool")]
    mutation_tools = {
        "write_file", "edit_file", "delete_file", "dev_command",
        "code_test", "n8n_workflow_builder", "unreal_mcp",
    }

    concerns: list[str] = []
    suggestions: list[str] = []

    if len(steps) > 8:
        concerns.append("Plan has more than eight steps; look for a smaller deterministic path.")
    if len(files) > 6:
        concerns.append("Plan touches more than six files; confirm each file is necessary.")
    if sum(name in mutation_tools for name in tool_names) > 5:
        concerns.append("Plan contains many mutating actions; consolidate before editing.")
    if any("create" in str(step.get("description") or "").lower() for step in steps):
        suggestions.append("Prefer an existing module/tool before introducing another abstraction.")
    if not any(name in {"code_test", "code_diagnose"} for name in tool_names) and steps:
        suggestions.append("Keep a focused verification step after mutation.")
    if request and any(token in request.lower() for token in ("simple", "small", "quick", "fix")) and len(steps) > 5:
        concerns.append("Request sounds small but plan is large; require evidence before expanding scope.")

    return {
        "success": True,
        "verified": True,
        "lean": not concerns,
        "concerns": concerns[:8],
        "suggestions": suggestions[:8],
        "steps": len(steps),
        "files": files[:12],
        "tools": tool_names[:16],
        "policy": "reuse-first, smallest-change, verify-after-mutation",
    }


def agent_browser_status() -> Dict[str, Any]:
    """Detect optional Vercel agent-browser without making it a dependency."""
    executable = shutil.which("agent-browser") or shutil.which("agent-browser.cmd")
    if not executable:
        return {
            "success": True,
            "verified": True,
            "installed": False,
            "message": "agent-browser is not installed; JARVIS browser routing is unchanged.",
        }
    try:
        result = subprocess.run(
            [executable, "--version"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        return {
            "success": True,
            "verified": True,
            "installed": True,
            "executable": executable,
            "version": (result.stdout or result.stderr or "").strip()[:500],
        }
    except Exception as exc:
        return {
            "success": False,
            "verified": True,
            "installed": True,
            "executable": executable,
            "message": str(exc)[:500],
        }


_AGENT_BROWSER_ACTIONS = {
    "open": ("open", 2),
    "read": ("read", 3),
    "snapshot": ("snapshot", 1),
    "click": ("click", 2),
    "fill": ("fill", 3),
    "press": ("press", 2),
    "scroll": ("scroll", 2),
    "screenshot": ("screenshot", 2),
}


def agent_browser_action(argument: str = "") -> Dict[str, Any]:
    """Run one allowlisted agent-browser command as a bounded fallback."""
    status = agent_browser_status()
    if not status.get("installed"):
        return {
            "success": False,
            "verified": False,
            "retryable": False,
            "message": status.get("message", "agent-browser is not installed."),
        }

    raw = str(argument or "").strip()
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {
            "success": False,
            "verified": False,
            "message": "agent_browser_action expects JSON with action and optional target/text.",
        }

    if not isinstance(payload, dict):
        return {
            "success": False,
            "verified": False,
            "message": "agent_browser_action expects a JSON object.",
        }

    action = str(payload.get("action") or "").strip().lower()
    spec = _AGENT_BROWSER_ACTIONS.get(action)
    if spec is None:
        return {
            "success": False,
            "verified": False,
            "message": "Unsupported agent-browser action.",
            "allowed_actions": sorted(_AGENT_BROWSER_ACTIONS),
        }

    executable = str(status.get("executable") or "")
    args = [executable, spec[0]]

    target = str(payload.get("target") or payload.get("selector") or "").strip()
    text_value = str(payload.get("text") or "").strip()

    if action == "open":
        if not target:
            return {"success": False, "verified": False, "message": "open requires target URL."}
        args.append(target)
    elif action in {"read", "click", "fill", "press", "scroll", "screenshot"}:
        if target:
            args.append(target)
        if action == "fill":
            args.append(text_value)
        elif action == "press" and target:
            pass
    elif action == "snapshot":
        pass

    try:
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except Exception as exc:
        return {
            "success": False,
            "verified": False,
            "retryable": True,
            "message": f"agent-browser failed to start: {exc}",
        }

    output = (result.stdout or "").strip()
    error = (result.stderr or "").strip()
    success = result.returncode == 0

    return {
        "success": success,
        "verified": success,
        "retryable": not success,
        "action": action,
        "returncode": result.returncode,
        "output": output[:12000],
        "error": error[:2000] if error else "",
        "backend": "agent-browser",
    }


def magnitude_status() -> Dict[str, Any]:
    """Report optional Magnitude availability without making it a dependency."""
    executable = shutil.which("magnitude") or shutil.which("magnitude.exe")
    if not executable:
        return {
            "success": True,
            "verified": True,
            "installed": False,
            "message": "Magnitude is not installed; Ollama remains the active JARVIS model runtime.",
        }

    def run(*args: str) -> str:
        result = subprocess.run(
            [executable, *args],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        return (result.stdout or result.stderr or "").strip()[:4000]

    try:
        version = run("--version")
    except Exception as exc:
        version = f"version probe failed: {exc}"

    return {
        "success": True,
        "verified": True,
        "installed": True,
        "executable": executable,
        "version": version,
        "usage": "Magnitude can profile hardware and recommend/tune local models; it is optional and does not replace Ollama automatically.",
    }


def run_adaptive_tool(tool_name: str, argument: str = "") -> Dict[str, Any]:
    if tool_name.startswith("hindsight_"):
        return adaptive_memory_tool(tool_name, argument)
    if tool_name == "coding_style_review":
        return coding_style_review(argument)
    if tool_name == "magnitude_status":
        return magnitude_status()
    if tool_name == "agent_browser_status":
        return agent_browser_status()
    if tool_name == "agent_browser_action":
        return agent_browser_action(argument)
    if tool_name == "response_style":
        return {"success": True, "verified": True, "text": response_style(argument)}
    return {"success": False, "verified": False, "message": f"Unknown adaptive runtime tool: {tool_name}"}
