"""Unified JARVIS integration/tool health diagnostics.

The health layer is intentionally read-only. It reports local capability
availability plus bounded live probes for optional services. A failed optional
integration never makes the whole health check fail.
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import socket
from pathlib import Path
from typing import Any, Dict
from urllib.parse import urlparse
from urllib.request import Request, urlopen

import config
from tool_registry import (
    AGENT_SKILL_TOOLS,
    ANIPY_TOOLS,
    BROWSER_TOOLS,
    CONTEXT_MEMORY_TOOLS,
    GODS_EYE_TOOLS,
    N8N_TOOLS,
    SCREEN_MEMORY_TOOLS,
    SYSTEM_HEALTH_TOOLS,
    UNREAL_MCP_TOOLS,
)

DEFAULT_TIMEOUT = 1.5


def _probe_http(url: str, timeout: float = DEFAULT_TIMEOUT) -> tuple[bool, str]:
    """Probe an HTTP endpoint without mutating remote state."""
    try:
        request = Request(
            url,
            headers={
                "Accept": "application/json,text/plain,*/*",
                "User-Agent": "JARVIS-health/1.0",
            },
            method="GET",
        )
        with urlopen(request, timeout=timeout) as response:
            status = int(getattr(response, "status", 200) or 200)
        return 200 <= status < 500, f"HTTP {status}"
    except Exception as exc:
        return False, str(exc)[:180]


def _probe_socket(url: str, timeout: float = DEFAULT_TIMEOUT) -> tuple[bool, str]:
    """Check whether an endpoint's host/port accepts TCP connections."""
    try:
        parsed = urlparse(str(url or "").strip())
        host = parsed.hostname
        if not host:
            return False, "no host configured"
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        with socket.create_connection((host, port), timeout=timeout):
            return True, f"{host}:{port} reachable"
    except Exception as exc:
        return False, str(exc)[:180]


def _module_available(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ModuleNotFoundError, ValueError):
        return False


def _chrome_available() -> bool:
    direct = [
        shutil.which("chrome"),
        shutil.which("chrome.exe"),
        shutil.which("chromium"),
        shutil.which("chromium.exe"),
        shutil.which("msedge"),
        shutil.which("msedge.exe"),
    ]
    bases = [
        os.environ.get("LOCALAPPDATA", ""),
        os.environ.get("PROGRAMFILES", ""),
        os.environ.get("PROGRAMFILES(X86)", ""),
    ]
    for base in bases:
        if base:
            direct.extend(
                [
                    str(Path(base) / "Google" / "Chrome" / "Application" / "chrome.exe"),
                    str(Path(base) / "Chromium" / "Application" / "chrome.exe"),
                    str(Path(base) / "Microsoft" / "Edge" / "Application" / "msedge.exe"),
                ]
            )
    return any(bool(item) and Path(str(item)).exists() for item in direct)


def _component(
    name: str,
    status: str,
    message: str,
    *,
    tool_count: int = 0,
    optional: bool = True,
    live: bool = False,
) -> Dict[str, Any]:
    return {
        "name": name,
        "status": status,
        "message": message,
        "tool_count": tool_count,
        "optional": optional,
        "live": live,
    }


def _registry_counts() -> Dict[str, int]:
    return {
        "browser": len(BROWSER_TOOLS),
        "anipy": len(ANIPY_TOOLS),
        "unreal": len(UNREAL_MCP_TOOLS),
        "memory": len(CONTEXT_MEMORY_TOOLS),
        "skills": len(AGENT_SKILL_TOOLS),
        "gods_eye": len(GODS_EYE_TOOLS),
        "screen_memory": len(SCREEN_MEMORY_TOOLS),
        "n8n": len(N8N_TOOLS),
        "health": len(SYSTEM_HEALTH_TOOLS),
    }


def _ollama_component() -> Dict[str, Any]:
    host = str(
        getattr(config, "OLLAMA_HOST", "")
        or os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")
    ).rstrip("/")
    reachable, detail = _probe_http(f"{host}/api/tags") if host else (False, "no endpoint configured")
    return _component(
        "Ollama",
        "READY" if reachable else "OFFLINE",
        "Local Ollama API is reachable." if reachable else f"Ollama probe failed: {detail}",
        live=True,
        optional=False,
    )


def _browser_component() -> Dict[str, Any]:
    playwright = _module_available("playwright")
    chrome = _chrome_available()
    if playwright and chrome:
        status = "READY"
        message = "Playwright and a Chromium-family browser executable are available."
    elif playwright:
        status = "DEGRADED"
        message = "Playwright is installed, but no Chromium-family browser executable was detected."
    else:
        status = "NOT_INSTALLED"
        message = "Playwright is not installed in the active Python environment."
    return _component("Browser", status, message, tool_count=len(BROWSER_TOOLS), optional=False)


def _browser_agent_component() -> Dict[str, Any]:
    try:
        from browser_agent import browser_agent_status
        result = browser_agent_status()
        available = bool(result.get("available"))
        browser_use = bool(result.get("browser_use_installed"))
        cdp = bool(result.get("cdp_reachable"))
        status = "READY" if available else ("DEGRADED" if browser_use or cdp else "OFFLINE")
        return _component(
            "Browser Agent",
            status,
            str(result.get("message") or ("Browser agent worker is available." if available else "Browser agent worker is not currently available.")),
            tool_count=2,
            live=True,
        )
    except Exception as exc:
        return _component("Browser Agent", "ERROR", f"Browser agent diagnostic failed: {exc}", tool_count=2)


def _anipy_component() -> Dict[str, Any]:
    api_ready = _module_available("anipy_api")
    cli_ready = _module_available("anipy_cli")
    ffmpeg = shutil.which("ffmpeg") is not None
    if api_ready and cli_ready and ffmpeg:
        status = "READY"
        message = "anipy API/CLI packages and FFmpeg are available."
    elif api_ready and cli_ready:
        status = "DEGRADED"
        message = "anipy API/CLI are installed; FFmpeg was not detected."
    else:
        status = "NOT_INSTALLED"
        message = "anipy API/CLI packages are not both available."
    return _component("Anipy", status, message, tool_count=len(ANIPY_TOOLS))


def _screenpipe_component() -> Dict[str, Any]:
    try:
        from screen_memory import screen_memory_status

        result = screen_memory_status()
        data = result.get("data", {}) if isinstance(result, dict) else {}
        reachable = bool(data.get("reachable"))
        search_ready = bool(data.get("search_ready"))
        if search_ready:
            status = "READY"
        elif reachable:
            status = "DEGRADED"
        else:
            status = "OFFLINE"

        return _component(
            "Screenpipe Memory",
            status,
            str(result.get("message") or "Screenpipe status checked."),
            tool_count=len(SCREEN_MEMORY_TOOLS),
            live=True,
        )
    except Exception as exc:
        return _component(
            "Screenpipe Memory",
            "ERROR",
            f"Screenpipe diagnostic failed: {exc}",
            tool_count=len(SCREEN_MEMORY_TOOLS),
            live=True,
        )


def _gods_eye_component() -> Dict[str, Any]:
    try:
        from gods_eye import gods_eye_status
        result = gods_eye_status()
        data = result.get("data", {}) if isinstance(result, dict) else {}
        installed = bool(data.get("installed"))
        running = bool(data.get("running"))
        node_ok = bool(data.get("supported_node"))
        status = "RUNNING" if running else ("READY" if installed and node_ok else ("DEGRADED" if installed else "NOT_READY"))
        return _component(
            "God's Eye View",
            status,
            str(result.get("message") or "God's Eye View status checked."),
            tool_count=len(GODS_EYE_TOOLS),
            live=True,
        )
    except Exception as exc:
        return _component("God's Eye View", "ERROR", f"God's Eye diagnostic failed: {exc}", tool_count=len(GODS_EYE_TOOLS), live=True)


def _n8n_component() -> Dict[str, Any]:
    try:
        from n8n_bridge import n8n_status
        result = n8n_status()
        enabled = bool(result.get("enabled"))
        reachable = bool(result.get("reachable"))
        status = "DISABLED" if not enabled else ("READY" if reachable else "OFFLINE")
        return _component(
            "n8n",
            status,
            str(result.get("message") or "n8n status checked."),
            tool_count=len(N8N_TOOLS),
            live=True,
        )
    except Exception as exc:
        return _component("n8n", "ERROR", f"n8n diagnostic failed: {exc}", tool_count=len(N8N_TOOLS), live=True)


def _memory_component() -> Dict[str, Any]:
    try:
        from agent_context import backend_status

        result = backend_status(timeout=0.6)
        backends = result.get("backends", {}) if isinstance(result, dict) else {}
        selected = str(result.get("selected_backend") or "").strip()

        if selected in {"openviking", "agentmemory"}:
            status = "READY"
            message = f"External Memory is using the {selected} backend."
        elif selected == "local":
            status = "DEGRADED"
            message = (
                "External memory services are unavailable; JARVIS is using its "
                "local SQLite memory fallback."
            )
        else:
            status = "OFFLINE"
            message = "No usable context-memory backend is available."

        for backend_name in ("openviking", "agentmemory"):
            backend = backends.get(backend_name, {})
            if backend.get("reachable") and backend.get("healthy"):
                message += f" {backend_name} is reachable."

        return _component(
            "External Memory",
            status,
            message,
            tool_count=len(CONTEXT_MEMORY_TOOLS),
            live=True,
        )
    except Exception as exc:
        return _component(
            "External Memory",
            "ERROR",
            f"Memory backend diagnostic failed: {exc}",
            tool_count=len(CONTEXT_MEMORY_TOOLS),
            live=True,
        )


def _unreal_component() -> Dict[str, Any]:
    url = str(getattr(config, "UNREAL_MCP_URL", "") or "").strip()
    project = str(getattr(config, "UNREAL_MCP_PROJECT_PATH", "") or "").strip()
    token = str(getattr(config, "UNREAL_MCP_TOKEN", "") or "").strip()
    token_file = str(getattr(config, "UNREAL_MCP_TOKEN_FILE", "") or "").strip()
    if not url:
        return _component("Unreal MCP", "NOT_CONFIGURED", "Unreal MCP endpoint is not configured.", tool_count=len(UNREAL_MCP_TOOLS))
    reachable, detail = _probe_socket(url)
    credentials = bool(token or token_file or project)
    if reachable and credentials:
        status = "READY"
        message = f"Unreal MCP endpoint is reachable ({detail})."
    elif reachable:
        status = "DEGRADED"
        message = f"Unreal MCP endpoint is reachable ({detail}), but project/token configuration is incomplete."
    else:
        status = "OFFLINE"
        message = f"Unreal MCP endpoint is not reachable: {detail}"
    return _component("Unreal MCP", status, message, tool_count=len(UNREAL_MCP_TOOLS), live=True)


def _roblox_component() -> Dict[str, Any]:
    url = str(getattr(config, "ROBLOX_MCP_URL", "") or "").strip()
    if not url:
        return _component(
            "Roblox MCP",
            "NOT_CONFIGURED",
            "Roblox MCP endpoint is not configured.",
        )

    reachable, detail = _probe_socket(url)
    if not reachable:
        return _component(
            "Roblox MCP",
            "OFFLINE",
            f"Roblox MCP endpoint is not reachable: {detail}",
            live=True,
        )

    try:
        from roblox_mcp import roblox_mcp_status

        result = roblox_mcp_status('{"timeout":2}')
        if not getattr(result, "success", False):
            return _component(
                "Roblox MCP",
                "DEGRADED",
                "Roblox MCP server is reachable, but its detailed status check failed.",
                live=True,
            )

        data = result.data if isinstance(result.data, dict) else {}
        status_payload = data.get("status")
        plugin_connected = None
        if isinstance(status_payload, dict):
            for key in ("connected", "pluginConnected", "plugin_connected"):
                if isinstance(status_payload.get(key), bool):
                    plugin_connected = status_payload[key]
                    break
            plugin = status_payload.get("plugin")
            if plugin_connected is None and isinstance(plugin, dict):
                connected = plugin.get("connected")
                if isinstance(connected, bool):
                    plugin_connected = connected

        if plugin_connected is False:
            return _component(
                "Roblox MCP",
                "DEGRADED",
                "Roblox MCP server is running, but the Roblox Studio plugin is not connected.",
                live=True,
            )

        return _component(
            "Roblox MCP",
            "READY",
            f"Roblox MCP server is reachable ({detail})."
            + (
                " Roblox Studio plugin is connected."
                if plugin_connected is True
                else " Roblox Studio connection could not be confirmed."
            ),
            live=True,
        )
    except Exception:
        return _component(
            "Roblox MCP",
            "DEGRADED",
            f"Roblox MCP server is reachable ({detail}), but detailed plugin status could not be confirmed.",
            live=True,
        )


def _skills_component() -> Dict[str, Any]:
    try:
        from skill_catalog import run_skill_tool
        result = run_skill_tool("skills_status", "")
        if isinstance(result, dict) and result.get("success") is False:
            return _component("Agent Skills", "DEGRADED", str(result.get("message") or "Agent Skills reported a problem."), tool_count=len(AGENT_SKILL_TOOLS))
        return _component("Agent Skills", "READY", str(result.get("message") or "Agent Skills catalog is available."), tool_count=len(AGENT_SKILL_TOOLS))
    except Exception as exc:
        return _component("Agent Skills", "ERROR", f"Agent Skills diagnostic failed: {exc}", tool_count=len(AGENT_SKILL_TOOLS))


def _parse_argument(argument: str) -> Dict[str, Any]:
    raw = str(argument or "").strip()
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _static_components() -> list[Dict[str, Any]]:
    return [
        _component(
            "Ollama",
            "READY" if getattr(config, "OLLAMA_HOST", "") else "NOT_CONFIGURED",
            "Ollama endpoint is configured." if getattr(config, "OLLAMA_HOST", "") else "Ollama endpoint is not configured.",
            live=False,
            optional=False,
        ),
        _component(
            "Browser",
            "READY" if _module_available("playwright") else "NOT_INSTALLED",
            "Playwright is installed." if _module_available("playwright") else "Playwright is not installed.",
            tool_count=len(BROWSER_TOOLS),
            optional=False,
        ),
        _component(
            "Browser Agent",
            "READY" if _module_available("browser_agent") else "NOT_INSTALLED",
            "Browser agent integration is installed." if _module_available("browser_agent") else "Browser agent module is unavailable.",
            tool_count=2,
        ),
        _component(
            "Anipy",
            "READY" if (_module_available("anipy_api") and _module_available("anipy_cli")) else "NOT_INSTALLED",
            "anipy API/CLI modules are installed." if (_module_available("anipy_api") and _module_available("anipy_cli")) else "anipy modules are not both installed.",
            tool_count=len(ANIPY_TOOLS),
        ),
        _component("External Memory", "READY", "JARVIS context-memory integration is installed.", tool_count=len(CONTEXT_MEMORY_TOOLS)),
        _component("Agent Skills", "READY" if _module_available("skill_catalog") else "NOT_INSTALLED", "Agent Skills catalog is installed." if _module_available("skill_catalog") else "Agent Skills catalog is unavailable.", tool_count=len(AGENT_SKILL_TOOLS)),
        _component("Unreal MCP", "READY" if getattr(config, "UNREAL_MCP_URL", "") else "NOT_CONFIGURED", "Unreal MCP endpoint is configured." if getattr(config, "UNREAL_MCP_URL", "") else "Unreal MCP endpoint is not configured.", tool_count=len(UNREAL_MCP_TOOLS)),
        _component("Roblox MCP", "READY" if getattr(config, "ROBLOX_MCP_URL", "") else "NOT_CONFIGURED", "Roblox MCP endpoint is configured." if getattr(config, "ROBLOX_MCP_URL", "") else "Roblox MCP endpoint is not configured."),
        _component("n8n", "READY" if getattr(config, "N8N_ENABLED", False) else "DISABLED", "n8n delegation is configured." if getattr(config, "N8N_ENABLED", False) else "n8n delegation is disabled."),
    ]


def integration_health(argument: str = "") -> Dict[str, Any]:
    """Run a bounded, read-only health sweep across JARVIS integrations."""
    options = _parse_argument(argument)
    include_optional = options.get("include_optional", True) is not False
    probe = options.get("probe", True) is not False

    components = (
        _static_components()
        if not probe
        else [
        _ollama_component(),
        _browser_component(),
        _browser_agent_component(),
        _anipy_component(),
        _memory_component(),
        _skills_component(),
        _unreal_component(),
        _roblox_component(),
        _n8n_component(),
    ]
    )
    if include_optional and probe:
        components.extend([_screenpipe_component(), _gods_eye_component()])

    counts: Dict[str, int] = {}
    for item in components:
        status = str(item["status"])
        counts[status] = counts.get(status, 0) + 1

    ready = counts.get("READY", 0) + counts.get("RUNNING", 0)
    degraded = counts.get("DEGRADED", 0)
    unavailable = sum(
        counts.get(status, 0)
        for status in ("OFFLINE", "ERROR", "NOT_INSTALLED", "NOT_READY")
    )
    disabled = counts.get("DISABLED", 0)
    overall = "READY" if degraded == 0 and unavailable == 0 else "DEGRADED"
    parts = [
        f"{ready} ready/running",
        f"{degraded} degraded",
        f"{unavailable} unavailable",
    ]
    if disabled:
        parts.append(f"{disabled} disabled")

    return {
        "success": True,
        "verified": True,
        "tool": "integration_health",
        "status": overall,
        "message": f"Integration health is {overall.lower()}. " + ", ".join(parts) + ".",
        "counts": counts,
        "registry_counts": _registry_counts(),
        "components": components,
    }


def run_integration_health(argument: str = "") -> Dict[str, Any]:
    return integration_health(argument)
