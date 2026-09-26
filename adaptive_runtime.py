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
from urllib.parse import quote

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
            f"/v1/default/banks/{quote(HINDSIGHT_BANK_ID, safe='')}/memories",
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
            f"/v1/default/banks/{quote(HINDSIGHT_BANK_ID, safe='')}/memories/recall",
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
            f"/v1/default/banks/{quote(HINDSIGHT_BANK_ID, safe='')}/reflect",
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


AGENT_BROWSER_EXECUTABLE = os.environ.get(
    "JARVIS_AGENT_BROWSER_EXECUTABLE",
    "",
).strip()
AGENT_BROWSER_MAX_OUTPUT = max(
    1000,
    int(os.environ.get("JARVIS_AGENT_BROWSER_MAX_OUTPUT", "12000")),
)
AGENT_BROWSER_TIMEOUT_SECONDS = max(
    5,
    min(int(os.environ.get("JARVIS_AGENT_BROWSER_TIMEOUT", "20")), 180),
)
AGENT_BROWSER_ALLOW_WEBMCP = _bool(
    os.environ.get("JARVIS_AGENT_BROWSER_ALLOW_WEBMCP", "0"),
)


def _agent_browser_executable() -> str:
    explicit = AGENT_BROWSER_EXECUTABLE
    if explicit and shutil.which(explicit):
        return explicit
    if explicit and os.path.isfile(explicit):
        return explicit
    return shutil.which("agent-browser") or shutil.which("agent-browser.cmd") or ""


def _agent_browser_json(value: str) -> Any:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None


def _run_agent_browser_command(
    args: list[str],
    *,
    timeout: int | None = None,
) -> Dict[str, Any]:
    executable = _agent_browser_executable()
    if not executable:
        return {
            "success": False,
            "verified": False,
            "retryable": False,
            "message": "agent-browser is not installed or could not be located.",
        }

    env = os.environ.copy()
    env["AGENT_BROWSER_MAX_OUTPUT"] = str(AGENT_BROWSER_MAX_OUTPUT)

    try:
        result = subprocess.run(
            [executable, *args],
            capture_output=True,
            text=True,
            timeout=timeout or AGENT_BROWSER_TIMEOUT_SECONDS,
            check=False,
            env=env,
        )
    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "verified": False,
            "retryable": True,
            "message": "agent-browser command timed out.",
            "backend": "agent-browser",
        }
    except Exception as exc:
        return {
            "success": False,
            "verified": False,
            "retryable": True,
            "message": f"agent-browser failed to start: {exc}",
            "backend": "agent-browser",
        }

    output = (result.stdout or "").strip()
    error = (result.stderr or "").strip()
    success = result.returncode == 0
    return {
        "success": success,
        "verified": success,
        "retryable": not success,
        "returncode": result.returncode,
        "output": output[:AGENT_BROWSER_MAX_OUTPUT],
        "json": _agent_browser_json(output),
        "error": error[:3000] if error else "",
        "backend": "agent-browser",
    }


def agent_browser_setup(argument: str = "") -> Dict[str, Any]:
    """Install or upgrade the optional agent-browser CLI explicitly."""
    raw = str(argument or "").strip()
    try:
        payload = json.loads(raw) if raw else {}
    except (json.JSONDecodeError, TypeError):
        payload = {"action": raw}

    if not isinstance(payload, dict):
        payload = {}

    action = str(payload.get("action") or "install").strip().lower()
    if action not in {"install", "upgrade", "status"}:
        return {
            "success": False,
            "verified": False,
            "message": "agent_browser_setup supports install, upgrade, or status.",
        }

    if action == "status":
        return agent_browser_status()

    executable = _agent_browser_executable()
    if action == "upgrade" and executable:
        command = [executable, "upgrade"]
    else:
        npm = shutil.which("npm") or shutil.which("npm.cmd")
        node = shutil.which("node") or shutil.which("node.exe")
        if not npm or not node:
            return {
                "success": False,
                "verified": False,
                "retryable": False,
                "message": "Node.js/npm was not found. agent-browser 0.38.x requires Node.js 24+.",
            }

        try:
            node_result = subprocess.run(
                [node, "--version"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            node_version = (node_result.stdout or node_result.stderr or "").strip()
            match = re.search(r"(\d+)(?:\.\d+)?", node_version)
            major = int(match.group(1)) if match else 0
        except Exception:
            major = 0
            node_version = ""

        if major < 24:
            return {
                "success": False,
                "verified": False,
                "retryable": False,
                "message": (
                    "agent-browser 0.38.x requires Node.js 24+. "
                    f"Detected {node_version or 'an unknown Node.js version'}."
                ),
            }

        npm = npm
                        "success": False,
                "verified": False,
                "retryable": False,
                "message": "npm was not found. Install Node.js/npm first, then retry agent-browser setup.",
            }
        command = [npm, "install", "-g", "agent-browser"]

    env = os.environ.copy()
    try:
        install = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
            env=env,
        )
    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "verified": False,
            "retryable": True,
            "message": "agent-browser package setup timed out.",
        }
    except Exception as exc:
        return {
            "success": False,
            "verified": False,
            "retryable": True,
            "message": f"agent-browser setup failed to start: {exc}",
        }

    install_output = (install.stdout or install.stderr or "").strip()
    if install.returncode != 0:
        return {
            "success": False,
            "verified": False,
            "retryable": True,
            "returncode": install.returncode,
            "output": install_output[:AGENT_BROWSER_MAX_OUTPUT],
            "message": "agent-browser package installation/upgrade failed.",
        }

    executable = _agent_browser_executable()
    if not executable:
        return {
            "success": False,
            "verified": False,
            "retryable": False,
            "output": install_output[:AGENT_BROWSER_MAX_OUTPUT],
            "message": "agent-browser was installed, but the executable is not discoverable on PATH yet.",
        }

    chrome_setup = _run_agent_browser_command(
        ["install"],
        timeout=300,
    )
    status = agent_browser_status()
    return {
        "success": bool(status.get("installed") and status.get("ready")),
        "verified": bool(status.get("ready")),
        "action": action,
        "install_returncode": install.returncode,
        "install_output": install_output[:AGENT_BROWSER_MAX_OUTPUT],
        "chrome_setup": {
            "success": chrome_setup.get("success"),
            "returncode": chrome_setup.get("returncode"),
            "output": chrome_setup.get("output", ""),
            "error": chrome_setup.get("error", ""),
        },
        "status": status,
        "message": (
            "agent-browser setup completed and the runtime doctor is healthy."
            if status.get("ready")
            else "agent-browser package setup completed, but the browser runtime still needs attention."
        ),
    }


def agent_browser_status() -> Dict[str, Any]:
    """Probe the current Vercel agent-browser CLI and its browser runtime."""
    executable = _agent_browser_executable()
    if not executable:
        return {
            "success": True,
            "verified": True,
            "installed": False,
            "ready": False,
            "message": "agent-browser is not installed; JARVIS browser routing is unchanged.",
        }

    try:
        version_result = subprocess.run(
            [executable, "--version"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        version = (version_result.stdout or version_result.stderr or "").strip()[:500]
    except Exception as exc:
        return {
            "success": False,
            "verified": True,
            "installed": True,
            "ready": False,
            "executable": executable,
            "message": str(exc)[:500],
        }

    doctor = _run_agent_browser_command(
        ["doctor", "--offline", "--quick", "--json"],
        timeout=15,
    )
    return {
        "success": True,
        "verified": True,
        "installed": True,
        "ready": bool(doctor.get("success")),
        "executable": executable,
        "version": version,
        "doctor": doctor.get("json") or doctor.get("output") or "",
        "doctor_error": doctor.get("error", ""),
        "webmcp_enabled": AGENT_BROWSER_ALLOW_WEBMCP,
        "max_output": AGENT_BROWSER_MAX_OUTPUT,
    }


_AGENT_BROWSER_ACTIONS = frozenset(
    {
        "open",
        "read",
        "snapshot",
        "click",
        "dblclick",
        "fill",
        "type",
        "focus",
        "hover",
        "press",
        "scroll",
        "screenshot",
        "get_text",
        "get_title",
        "get_url",
        "get_value",
        "get_html",
        "find",
        "connect",
        "back",
        "forward",
        "refresh",
        "close",
        "doctor",
        "webmcp_list",
        "webmcp_invoke",
        "webmcp_result",
        "webmcp_cancel",
    }
)


def agent_browser_action(argument: str = "") -> Dict[str, Any]:
    """Run a bounded, allowlisted agent-browser command as a browser fallback."""
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
    if action not in _AGENT_BROWSER_ACTIONS:
        return {
            "success": False,
            "verified": False,
            "message": "Unsupported agent-browser action.",
            "allowed_actions": sorted(_AGENT_BROWSER_ACTIONS),
        }

    target = str(
        payload.get("target")
        or payload.get("selector")
        or ""
    ).strip()
    text_value = str(payload.get("text") or "").strip()
    args: list[str] = []

    if action == "open":
        if not target:
            return {"success": False, "verified": False, "message": "open requires a URL."}
        args = ["open", target]

    elif action == "read":
        args = ["read", target] if target else ["read"]

    elif action == "snapshot":
        args = ["snapshot"]
        if bool(payload.get("interactive")):
            args.append("-i")

    elif action in {"click", "dblclick", "focus", "hover"}:
        if not target:
            return {"success": False, "verified": False, "message": f"{action} requires a selector or @ref."}
        args = [action, target]

    elif action in {"fill", "type"}:
        if not target or not text_value:
            return {
                "success": False,
                "verified": False,
                "message": f"{action} requires target and text.",
            }
        args = [action, target, text_value]

    elif action == "press":
        key = str(payload.get("key") or target or "").strip()
        if not key:
            return {"success": False, "verified": False, "message": "press requires a key."}
        args = ["press", key]

    elif action == "scroll":
        direction = str(payload.get("direction") or target or "down").strip().lower()
        if direction not in {"up", "down", "left", "right"}:
            return {"success": False, "verified": False, "message": "scroll direction must be up, down, left, or right."}
        amount = payload.get("amount", payload.get("pixels", 300))
        try:
            amount = max(1, min(int(amount), 5000))
        except (TypeError, ValueError):
            amount = 300
        args = ["scroll", direction, str(amount)]

    elif action == "screenshot":
        args = ["screenshot"]
        if target:
            args.append(target)

    elif action == "get_text":
        if not target:
            return {"success": False, "verified": False, "message": "get_text requires a selector or @ref."}
        args = ["get", "text", target]

    elif action in {"get_title", "get_url"}:
        args = ["get", "title" if action == "get_title" else "url"]

    elif action in {"get_value", "get_html"}:
        if not target:
            return {"success": False, "verified": False, "message": f"{action} requires a selector or @ref."}
        args = ["get", "value" if action == "get_value" else "html", target]

    elif action == "find":
        strategy = str(payload.get("strategy") or "text").strip().lower()
        query = str(payload.get("query") or target).strip()
        find_action = str(payload.get("find_action") or payload.get("action_name") or "click").strip().lower()
        if strategy not in {"role", "text", "label", "placeholder", "alt", "title", "testid", "first", "last"}:
            return {"success": False, "verified": False, "message": "Unsupported find strategy."}
        if not query:
            return {"success": False, "verified": False, "message": "find requires a query."}
        if find_action not in {"click", "dblclick", "fill", "type", "focus", "hover", "text", "press"}:
            return {"success": False, "verified": False, "message": "Unsupported find action."}

        args = ["find", strategy, query, find_action]
        name = str(payload.get("name") or "").strip()
        if strategy == "role" and name:
            args.extend(["--name", name])
        if find_action in {"fill", "type", "press"}:
            value = str(payload.get("value") or text_value or payload.get("key") or "").strip()
            if not value:
                return {"success": False, "verified": False, "message": f"find {find_action} requires a value."}
            args.append(value)

    elif action == "connect":
        port = str(payload.get("port") or target or "9222").strip()
        args = ["connect", port]

    elif action in {"back", "forward", "refresh", "close"}:
        args = [action]

    elif action == "doctor":
        args = ["doctor", "--offline", "--quick"]

    elif action == "webmcp_list":
        args = ["webmcp", "list"]
        if target:
            args.append(target)
        frame_id = str(payload.get("frame") or payload.get("frame_id") or "").strip()
        if frame_id:
            args.extend(["--frame", frame_id])
        if bool(payload.get("json", True)):
            args.append("--json")

    elif action == "webmcp_invoke":
        if not AGENT_BROWSER_ALLOW_WEBMCP:
            return {
                "success": False,
                "verified": False,
                "retryable": False,
                "message": "WebMCP invocation is disabled. Set JARVIS_AGENT_BROWSER_ALLOW_WEBMCP=1 explicitly.",
            }
        if payload.get("confirmed") is not True:
            return {
                "success": False,
                "verified": False,
                "retryable": False,
                "message": "WebMCP invocation requires confirmed=true because page-provided tools are untrusted.",
            }
        tool_name = str(payload.get("tool") or target).strip()
        if not tool_name:
            return {"success": False, "verified": False, "message": "webmcp_invoke requires a page tool name."}
        params = payload.get("params", {})
        if not isinstance(params, dict):
            return {"success": False, "verified": False, "message": "webmcp_invoke params must be a JSON object."}
        args = ["webmcp", "invoke", tool_name]
        frame_id = str(payload.get("frame") or payload.get("frame_id") or "").strip()
        if frame_id:
            args.extend(["--frame", frame_id])
        args.extend(["--params", json.dumps(params, ensure_ascii=False)])

    elif action in {"webmcp_result", "webmcp_cancel"}:
        invocation_id = str(payload.get("id") or target).strip()
        if not invocation_id:
            return {"success": False, "verified": False, "message": f"{action} requires an invocation id."}
        args = ["webmcp", "result" if action == "webmcp_result" else "cancel", invocation_id]

    result = _run_agent_browser_command(args)
    result["action"] = action
    return result
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
    if tool_name == "agent_browser_setup":
        return agent_browser_setup(argument)
    if tool_name == "agent_browser_action":
        return agent_browser_action(argument)
    if tool_name == "response_style":
        return {"success": True, "verified": True, "text": response_style(argument)}
    return {"success": False, "verified": False, "message": f"Unknown adaptive runtime tool: {tool_name}"}
