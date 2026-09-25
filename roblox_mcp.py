
"""JARVIS <-> Roblox Studio MCP integration.

The BoshyDX robloxstudio-mcp server exposes two useful surfaces:

* /mcp                Streamable HTTP MCP transport for discovery/session work.
* /mcp/<tool_name>    Direct JSON tool routes for execution.

JARVIS uses the MCP client only to discover the live tool catalog. Tool
execution uses the direct JSON route so large Roblox responses do not have to
travel through the Streamable HTTP/SSE response path that can close early.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import threading
import time
from typing import Any, Callable, Dict, Optional
from urllib.parse import quote

import requests

import config
from tool_result import ToolResult


ROBLOX_MCP_URL = str(
    getattr(
        config,
        "ROBLOX_MCP_URL",
        "http://127.0.0.1:58741",
    )
).rstrip("/")

ROBLOX_MCP_ENDPOINT = f"{ROBLOX_MCP_URL}/mcp"

_DISCOVERY_TTL = float(
    getattr(config, "ROBLOX_MCP_DISCOVERY_TTL", 60.0)
)

_REQUEST_TIMEOUT = float(
    getattr(config, "ROBLOX_MCP_TIMEOUT", 60.0)
)

_MAX_DESCRIPTION_CHARS = 1200
_MAX_SCHEMA_CHARS = 2400
_MAX_OBSERVATION_CHARS = 12000

_DISCOVERY_LOCK = threading.RLock()
_DISCOVERY_CACHE: Dict[str, Dict[str, Any]] = {}
_DISCOVERY_EXPIRES_AT = 0.0
_DISCOVERY_ERROR = ""
_SERVER_PROCESS: subprocess.Popen | None = None
_SERVER_LOCK = threading.RLock()


def _run_async(factory: Callable[[], Any]) -> Any:
    """Run one async MCP operation from JARVIS's synchronous tool layer."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(factory())

    result: Dict[str, Any] = {}
    error: Dict[str, BaseException] = {}

    def runner() -> None:
        try:
            result["value"] = asyncio.run(factory())
        except BaseException as exc:
            error["value"] = exc

    thread = threading.Thread(
        target=runner,
        name="jarvis-roblox-mcp",
        daemon=True,
    )
    thread.start()
    thread.join()

    if "value" in error:
        raise error["value"]

    return result.get("value")


async def _discover_async() -> Dict[str, Dict[str, Any]]:
    """Discover Roblox MCP tools through the official Python MCP client."""
    from mcp import Client

    async with Client(ROBLOX_MCP_ENDPOINT) as client:
        result = await client.list_tools()

    discovered: Dict[str, Dict[str, Any]] = {}

    for tool in getattr(result, "tools", []) or []:
        name = str(
            getattr(tool, "name", "") or ""
        ).strip()

        if not name:
            continue

        description = str(
            getattr(tool, "description", "") or ""
        ).strip()

        input_schema = getattr(
            tool,
            "inputSchema",
            {},
        )

        if not isinstance(input_schema, dict):
            input_schema = {}

        discovered[name] = {
            "name": name,
            "description": description,
            "input_schema": input_schema,
        }

    return discovered


def discover_roblox_tools(
    force: bool = False,
) -> Dict[str, Dict[str, Any]]:
    """Return a cached live Roblox MCP tool catalog."""
    global _DISCOVERY_CACHE
    global _DISCOVERY_EXPIRES_AT
    global _DISCOVERY_ERROR

    now = time.monotonic()

    with _DISCOVERY_LOCK:
        if (
            not force
            and _DISCOVERY_CACHE
            and now < _DISCOVERY_EXPIRES_AT
        ):
            return dict(_DISCOVERY_CACHE)

    try:
        discovered = _run_async(_discover_async)

        with _DISCOVERY_LOCK:
            _DISCOVERY_CACHE = dict(discovered)
            _DISCOVERY_EXPIRES_AT = (
                time.monotonic() + _DISCOVERY_TTL
            )
            _DISCOVERY_ERROR = ""

        return dict(discovered)

    except Exception as exc:
        with _DISCOVERY_LOCK:
            _DISCOVERY_ERROR = str(exc)

            # Keep a still-valid stale catalog available during transient
            # MCP restarts so the planner does not suddenly lose all Roblox
            # capabilities.
            if _DISCOVERY_CACHE:
                return dict(_DISCOVERY_CACHE)

        return {}


def refresh_roblox_tools() -> Dict[str, Dict[str, Any]]:
    """Force a fresh MCP tool discovery."""
    return discover_roblox_tools(force=True)


def get_roblox_discovery_error() -> str:
    """Return the latest discovery error, if any."""
    with _DISCOVERY_LOCK:
        return _DISCOVERY_ERROR


def is_known_roblox_tool(tool_name: str) -> bool:
    """Return True when the live/stale MCP catalog contains tool_name."""
    normalized = str(tool_name or "").strip()

    if not normalized:
        return False

    return normalized in discover_roblox_tools()


def _compact_json(value: Any, limit: int) -> str:
    try:
        rendered = json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
        )
    except (TypeError, ValueError):
        rendered = str(value)

    if len(rendered) <= limit:
        return rendered

    return (
        rendered[:limit]
        + "... [schema truncated]"
    )


def get_roblox_planner_tool_descriptions() -> Dict[str, str]:
    """Return planner-ready names/descriptions for the live MCP catalog."""
    catalog = discover_roblox_tools()

    descriptions: Dict[str, str] = {}

    for name, metadata in catalog.items():
        description = str(
            metadata.get("description", "")
            or "Roblox Studio MCP tool."
        ).strip()

        if len(description) > _MAX_DESCRIPTION_CHARS:
            description = (
                description[:_MAX_DESCRIPTION_CHARS]
                + "..."
            )

        schema = metadata.get(
            "input_schema",
            {},
        )

        schema_text = _compact_json(
            schema,
            _MAX_SCHEMA_CHARS,
        )

        descriptions[
            f"roblox__{name}"
        ] = (
            f"{description} "
            f"Argument must be a JSON object matching this MCP schema: "
            f"{schema_text}"
        )

    return descriptions


def _parse_tool_argument(
    argument: str,
) -> tuple[Optional[Dict[str, Any]], Optional[str]]:
    raw = str(argument or "").strip()

    if not raw:
        return {}, None

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        return None, (
            "Roblox MCP tool arguments must be valid JSON. "
            f"Parser error: {exc}"
        )

    if not isinstance(payload, dict):
        return None, (
            "Roblox MCP tool arguments must be a JSON object."
        )

    return payload, None


def _extract_observation(
    payload: Any,
) -> Dict[str, Any]:
    """Create bounded execution evidence without truncating result data."""
    observation: Dict[str, Any] = {}

    if isinstance(payload, dict):
        content = payload.get("content")

        if isinstance(content, list):
            text_parts = []

            for item in content:
                if not isinstance(item, dict):
                    continue

                text_value = item.get("text")

                if text_value:
                    text_parts.append(str(text_value))

            if text_parts:
                text_value = "\n".join(text_parts)

                observation["text"] = (
                    text_value
                    if len(text_value) <= _MAX_OBSERVATION_CHARS
                    else (
                        text_value[:_MAX_OBSERVATION_CHARS]
                        + "\n... [observation truncated by JARVIS] ..."
                    )
                )

        if payload.get("isError") is True:
            observation["is_error"] = True

    if not observation:
        observation["summary"] = (
            _compact_json(
                payload,
                _MAX_OBSERVATION_CHARS,
            )
        )

    return observation


def run_roblox_tool(
    tool_name: str,
    argument: str = "",
) -> ToolResult:
    """Execute one validated Roblox MCP tool through the direct JSON route."""
    raw_name = str(tool_name or "").strip()
    qualified_name = f"roblox__{raw_name}"

    if not raw_name:
        return ToolResult(
            success=False,
            tool=qualified_name,
            error="Roblox MCP tool name cannot be empty.",
        )

    catalog = discover_roblox_tools()

    if raw_name not in catalog:
        discovery_error = get_roblox_discovery_error()

        detail = (
            f"Unknown Roblox MCP tool: {raw_name}."
        )

        if discovery_error:
            detail += (
                " Tool discovery is currently unavailable: "
                + discovery_error
            )

        return ToolResult(
            success=False,
            tool=qualified_name,
            error=detail,
            retryable=True,
        )

    payload, parse_error = _parse_tool_argument(
        argument
    )

    if parse_error:
        return ToolResult(
            success=False,
            tool=qualified_name,
            error=parse_error,
            retryable=False,
        )

    url = (
        f"{ROBLOX_MCP_URL}/mcp/"
        f"{quote(raw_name, safe='')}"
    )

    try:
        response = requests.post(
            url,
            json=payload,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            timeout=_REQUEST_TIMEOUT,
        )

        try:
            data = response.json()
        except ValueError:
            data = {
                "raw": response.text,
            }

        if not response.ok:
            message = ""

            if isinstance(data, dict):
                message = str(
                    data.get("error")
                    or data.get("message")
                    or ""
                ).strip()

            if not message:
                message = response.text.strip()

            full_error = (
                f"Roblox MCP HTTP {response.status_code}"
                + (f": {message}" if message else "")
            )

            # A Studio plugin connection timeout is an infrastructure
            # precondition failure, not a planner strategy failure. Retrying
            # or asking the LLM to replan only repeats the same unavailable
            # dependency and wastes the recovery budget.
            plugin_connection_failure = (
                "studio plugin connection timeout" in full_error.lower()
                or "plugin connection timeout" in full_error.lower()
                or "studio plugin" in full_error.lower()
                and "not connected" in full_error.lower()
            )

            return ToolResult(
                success=False,
                tool=qualified_name,
                data=data,
                error=full_error,
                retryable=(
                    not plugin_connection_failure
                    and (
                        response.status_code in {
                            408,
                            429,
                        }
                        or response.status_code >= 500
                    )
                ),
                observation=_extract_observation(data),
            )

        if (
            isinstance(data, dict)
            and data.get("isError") is True
        ):
            return ToolResult(
                success=False,
                tool=qualified_name,
                data=data,
                error=(
                    f"Roblox MCP tool {raw_name} returned an error."
                ),
                retryable=False,
                observation=_extract_observation(data),
            )

        return ToolResult(
            success=True,
            tool=qualified_name,
            data=data,
            observation=_extract_observation(data),
        )

    except requests.RequestException as exc:
        return ToolResult(
            success=False,
            tool=qualified_name,
            error=(
                "Could not reach Roblox MCP at "
                f"{ROBLOX_MCP_URL}: {exc}"
            ),
            retryable=True,
        )


def roblox_mcp_status(
    argument: str = "",
) -> ToolResult:
    """Return concise Roblox MCP server and Studio plugin status."""
    timeout_value = min(_REQUEST_TIMEOUT, 10.0)
    raw_argument = str(argument or "").strip()
    if raw_argument:
        try:
            payload = json.loads(raw_argument)
            if isinstance(payload, dict) and payload.get("timeout") is not None:
                timeout_value = max(0.5, min(float(payload["timeout"]), 10.0))
        except (json.JSONDecodeError, TypeError, ValueError):
            pass

    try:
        health_response = requests.get(
            f"{ROBLOX_MCP_URL}/health",
            timeout=timeout_value,
        )
        health_response.raise_for_status()
        health = health_response.json()

        status_response = requests.get(
            f"{ROBLOX_MCP_URL}/status",
            timeout=timeout_value,
        )
        status_response.raise_for_status()
        status = status_response.json()

        result = {
            "success": True,
            "verified": True,
            "server_url": ROBLOX_MCP_URL,
            "health": health,
            "status": status,
        }

        return ToolResult(
            success=True,
            tool="roblox_mcp_status",
            data=result,
            observation=result,
        )

    except (requests.RequestException, ValueError) as exc:
        return ToolResult(
            success=False,
            tool="roblox_mcp_status",
            error=(
                f"Roblox MCP status unavailable: {exc}"
            ),
            retryable=True,
        )


def roblox_mcp_setup(argument: str = "") -> ToolResult:
    """Ensure the local Roblox MCP server is available.

    The server is started through npx when it is not already reachable. Studio
    plugin activation remains an explicit Roblox Studio step because JARVIS
    cannot activate a Studio plugin inside the editor process itself.
    """
    global _SERVER_PROCESS

    del argument

    try:
        existing = roblox_mcp_status('{"timeout":1.5}')
        if existing.success:
            return ToolResult(
                success=True,
                tool="roblox_mcp_setup",
                data=existing.data,
                observation=existing.observation,
            )

        npx_cmd = (
            shutil.which("npx.cmd")
            or shutil.which("npx")
        )
        if not npx_cmd:
            return ToolResult(
                success=False,
                tool="roblox_mcp_setup",
                error="npx was not found. Install Node.js and ensure npx is on PATH.",
                retryable=False,
            )

        with _SERVER_LOCK:
            if _SERVER_PROCESS is None or _SERVER_PROCESS.poll() is not None:
                package = os.environ.get(
                    "JARVIS_ROBLOX_MCP_PACKAGE",
                    "robloxstudio-mcp@latest",
                ).strip() or "robloxstudio-mcp@latest"

                kwargs = {
                    "cwd": os.getcwd(),
                    "stdout": subprocess.DEVNULL,
                    "stderr": subprocess.DEVNULL,
                }
                if os.name == "nt":
                    kwargs["creationflags"] = (
                        getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
                        | getattr(subprocess, "CREATE_NO_WINDOW", 0)
                    )

                _SERVER_PROCESS = subprocess.Popen(
                    [
                        npx_cmd,
                        "-y",
                        package,
                    ],
                    **kwargs,
                )

        deadline = time.monotonic() + max(30.0, min(_REQUEST_TIMEOUT, 60.0))
        last_error = ""
        while time.monotonic() < deadline:
            checked = roblox_mcp_status('{"timeout":1.5}')
            if checked.success:
                return ToolResult(
                    success=True,
                    tool="roblox_mcp_setup",
                    data=checked.data,
                    observation=checked.observation,
                )
            last_error = str(checked.error or "")
            time.sleep(0.4)

        return ToolResult(
            success=False,
            tool="roblox_mcp_setup",
            error=(
                "Roblox MCP server did not become reachable. "
                "Start Roblox Studio with the MCP plugin activated. "
                + (last_error if last_error else "")
            ).strip(),
            retryable=True,
        )
    except Exception as exc:
        return ToolResult(
            success=False,
            tool="roblox_mcp_setup",
            error=f"Roblox MCP setup failed: {exc}",
            retryable=True,
        )
