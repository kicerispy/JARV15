"""Thin JARVIS client for ChiR24/Unreal_mcp native MCP gateway."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

import requests

import config
from logger import logger

UNREAL_MCP_REPOSITORY = "https://github.com/ChiR24/Unreal_mcp.git"
UNREAL_MCP_BRANCH = "dev"
UNREAL_MCP_PROTOCOL_VERSION = "2025-11-25"
_SESSION = "Mcp-Session-Id"
_TOKEN = "X-MCP-Capability-Token"
_PROTOCOL = "MCP-Protocol-Version"


def _cfg(name: str, default: Any) -> Any:
    return getattr(config, name, default)


def endpoint() -> str:
    return str(
        _cfg("UNREAL_MCP_URL", os.environ.get("JARVIS_UNREAL_MCP_URL", "http://127.0.0.1:3000/mcp"))
        or ""
    ).strip().rstrip("/")


def timeout() -> float:
    try:
        return max(1.0, float(_cfg(
            "UNREAL_MCP_TIMEOUT_SECONDS",
            os.environ.get("JARVIS_UNREAL_MCP_TIMEOUT", "120"),
        )))
    except (TypeError, ValueError):
        return 120.0


def _project_path() -> Path | None:
    raw = str(
        _cfg("UNREAL_MCP_PROJECT_PATH", os.environ.get("JARVIS_UNREAL_MCP_PROJECT_PATH", ""))
        or ""
    ).strip()
    if not raw:
        return None

    path = Path(os.path.expandvars(os.path.expanduser(raw))).resolve()

    # Accept either the Unreal project directory or the .uproject file.
    # The token is always relative to the project directory.
    if path.is_file() and path.suffix.lower() == ".uproject":
        return path.parent

    return path


def capability_token() -> tuple[str | None, str]:
    explicit = str(
        _cfg("UNREAL_MCP_TOKEN", os.environ.get("JARVIS_UNREAL_MCP_TOKEN", "")) or ""
    ).strip()
    if explicit:
        return explicit, "environment"

    token_file = str(
        _cfg("UNREAL_MCP_TOKEN_FILE", os.environ.get("JARVIS_UNREAL_MCP_TOKEN_FILE", "")) or ""
    ).strip()
    candidates = []
    if token_file:
        candidates.append(Path(os.path.expandvars(os.path.expanduser(token_file))).resolve())
    project = _project_path()
    if project:
        candidates.append(project / "Saved" / "MCP" / "capability-token")

    for path in candidates:
        try:
            token = path.read_text(encoding="utf-8").strip()
        except (OSError, UnicodeError):
            continue
        if token:
            return token, f"file:{path}"
    return None, "none"


def _frames(response: requests.Response) -> list[Any]:
    content_type = str(response.headers.get("Content-Type", "")).lower()
    if "text/event-stream" not in content_type:
        if not response.text.strip():
            return []
        return [response.json()]

    frames: list[Any] = []
    data: list[str] = []

    def flush() -> None:
        if not data:
            return
        payload = "\n".join(data).strip()
        data.clear()
        if not payload or payload == "[DONE]":
            return
        try:
            frames.append(json.loads(payload))
        except json.JSONDecodeError:
            logger.debug("JARVIS: ignored non-JSON Unreal MCP SSE frame")

    for line in response.iter_lines(decode_unicode=True):
        value = "" if line is None else str(line)
        if not value.strip():
            flush()
        elif value.startswith("data:"):
            data.append(value[5:].lstrip())
    flush()
    return frames


def _matching_frame(frames: list[Any], request_id: int) -> dict[str, Any]:
    for frame in frames:
        if isinstance(frame, dict) and frame.get("id") == request_id:
            if "error" in frame or "result" in frame:
                return frame
    raise RuntimeError("Unreal MCP returned no matching JSON-RPC response.")


def _result(frame: dict[str, Any]) -> Any:
    if "error" in frame:
        error = frame["error"]
        if isinstance(error, dict):
            raise RuntimeError(
                str(error.get("message") or "Unknown Unreal MCP error.")
            )
        raise RuntimeError(str(error))
    return frame.get("result")


class UnrealMcpClient:
    def __init__(self) -> None:
        self.url = endpoint()
        self.timeout_seconds = timeout()
        self.token, self.token_source = capability_token()
        self.session_id: str | None = None
        self.protocol_version = UNREAL_MCP_PROTOCOL_VERSION
        self.next_id = 1000

    def headers(self, *, session: bool = True, protocol: bool = True) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if self.token:
            headers[_TOKEN] = self.token
        if session and self.session_id:
            headers[_SESSION] = self.session_id
        if protocol and self.session_id:
            headers[_PROTOCOL] = self.protocol_version
        return headers

    def post(self, payload: dict[str, Any], *, session: bool = True, protocol: bool = True, timeout_s: float | None = None) -> tuple[requests.Response, list[Any]]:
        if not self.url:
            raise RuntimeError("Unreal MCP URL is not configured.")
        response = requests.post(
            self.url,
            headers=self.headers(session=session, protocol=protocol),
            json=payload,
            timeout=timeout_s or self.timeout_seconds,
            stream=True,
        )
        try:
            frames = _frames(response)
        finally:
            response.close()
        return response, frames

    def initialize(self) -> None:
        response, frames = self.post(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": UNREAL_MCP_PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {"name": "JARVIS", "version": "1.0.0"},
                },
            },
            session=False,
            protocol=False,
            timeout_s=min(self.timeout_seconds, 30.0),
        )
        if response.status_code != 200:
            raise RuntimeError(f"Unreal MCP initialize returned HTTP {response.status_code}.")
        self.session_id = response.headers.get(_SESSION) or response.headers.get(_SESSION.lower())
        if not self.session_id:
            raise RuntimeError("Unreal MCP initialize returned no Mcp-Session-Id.")

        result = _result(_matching_frame(frames, 1))
        if isinstance(result, dict) and isinstance(result.get("protocolVersion"), str):
            self.protocol_version = result["protocolVersion"]

        self.post(
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            timeout_s=min(self.timeout_seconds, 15.0),
        )

    def request(self, method: str, params: dict[str, Any], timeout_s: float | None = None) -> Any:
        request_id = self.next_id
        self.next_id += 1
        response, frames = self.post(
            {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params},
            timeout_s=timeout_s,
        )
        if response.status_code != 200:
            raise RuntimeError(f"Unreal MCP {method} returned HTTP {response.status_code}.")
        return _result(_matching_frame(frames, request_id))

    def gateway(self, arguments: dict[str, Any]) -> Any:
        try:
            self.initialize()
            return self.request(
                "tools/call",
                {"name": "unreal", "arguments": arguments},
                timeout_s=self.timeout_seconds,
            )
        finally:
            self.close()

    def close(self) -> None:
        if not self.session_id or not self.url:
            return
        try:
            requests.delete(self.url, headers=self.headers(), timeout=min(self.timeout_seconds, 15.0))
        except requests.RequestException:
            pass
        finally:
            self.session_id = None


def _parse_gateway(argument: str) -> dict[str, Any]:
    try:
        payload = json.loads(str(argument or "").strip())
    except json.JSONDecodeError as exc:
        raise ValueError("unreal_mcp arguments must be valid JSON.") from exc
    if not isinstance(payload, dict):
        raise ValueError("unreal_mcp arguments must be a JSON object.")
    operation = str(payload.get("operation") or "").strip().lower()
    if operation not in {"search", "describe", "execute", "configure"}:
        raise ValueError("unreal_mcp operation must be search, describe, execute, or configure.")
    return payload


def _external_repo() -> Path:
    raw = str(
        _cfg("UNREAL_MCP_EXTERNAL_DIR", os.environ.get("JARVIS_UNREAL_MCP_EXTERNAL_DIR", ""))
        or ""
    ).strip()
    return (
        Path(os.path.expandvars(os.path.expanduser(raw))).resolve()
        if raw
        else Path.cwd().resolve() / ".jarvis_external" / "Unreal_mcp"
    )


def setup_unreal_mcp() -> dict[str, Any]:
    destination = _external_repo()
    destination.parent.mkdir(parents=True, exist_ok=True)

    if (destination / ".git").is_dir():
        commands = [
            ["git", "-C", str(destination), "fetch", "--depth", "1", "origin", UNREAL_MCP_BRANCH],
            ["git", "-C", str(destination), "reset", "--hard", f"origin/{UNREAL_MCP_BRANCH}"],
        ]
    elif destination.exists():
        return {
            "success": False,
            "verified": False,
            "retryable": False,
            "terminal": True,
            "tool": "unreal_mcp_setup",
            "error": f"Refusing to overwrite non-git directory: {destination}",
        }
    else:
        commands = [[
            "git", "clone", "--branch", UNREAL_MCP_BRANCH, "--depth", "1",
            UNREAL_MCP_REPOSITORY, str(destination),
        ]]

    for command in commands:
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=180,
        )
        if result.returncode != 0:
            return {
                "success": False,
                "verified": False,
                "retryable": True,
                "tool": "unreal_mcp_setup",
                "error": result.stderr.strip() or result.stdout.strip(),
            }

    plugin = destination / "plugins" / "McpAutomationBridge"
    return {
        "success": plugin.is_dir(),
        "verified": plugin.is_dir(),
        "tool": "unreal_mcp_setup",
        "repository": UNREAL_MCP_REPOSITORY,
        "branch": UNREAL_MCP_BRANCH,
        "path": str(destination),
        "plugin_path": str(plugin),
        "message": (
            "Unreal_mcp source is ready. Install plugins/McpAutomationBridge "
            "into the Unreal project, enable Native MCP on port 3000, then "
            "configure JARVIS_UNREAL_MCP_URL and the capability token/project path."
        ),
    }


def unreal_mcp_status() -> dict[str, Any]:
    client = UnrealMcpClient()
    try:
        client.initialize()
        listing = client.request("tools/list", {})
        names = [
            str(item.get("name"))
            for item in (listing.get("tools", []) if isinstance(listing, dict) else [])
            if isinstance(item, dict) and item.get("name")
        ]
        return {
            "success": True,
            "verified": "unreal" in names,
            "tool": "unreal_mcp_status",
            "endpoint": client.url,
            "protocol_version": client.protocol_version,
            "token_configured": bool(client.token),
            "token_source": client.token_source,
            "public_tools": names,
            "connected": "unreal" in names,
        }
    except requests.RequestException as exc:
        return {
            "success": False,
            "verified": False,
            "retryable": True,
            "tool": "unreal_mcp_status",
            "endpoint": client.url,
            "error": f"Unreal MCP connection failed: {exc}",
        }
    except Exception as exc:
        return {
            "success": False,
            "verified": False,
            "retryable": True,
            "tool": "unreal_mcp_status",
            "endpoint": client.url,
            "error": str(exc),
        }
    finally:
        client.close()


def run_unreal_mcp_tool(tool_name: str, argument: str = "") -> dict[str, Any]:
    try:
        if tool_name == "unreal_mcp_status":
            return unreal_mcp_status()
        if tool_name == "unreal_mcp_setup":
            return setup_unreal_mcp()
        if tool_name != "unreal_mcp":
            return {
                "success": False,
                "verified": False,
                "retryable": False,
                "terminal": True,
                "tool": tool_name,
                "error": f"Unknown Unreal MCP tool: {tool_name}",
            }

        payload = _parse_gateway(argument)
        result = UnrealMcpClient().gateway(payload)
        if isinstance(result, dict) and result.get("isError"):
            return {
                "success": False,
                "verified": False,
                "retryable": False,
                "terminal": True,
                "tool": "unreal_mcp",
                "result": result,
                "error": "Unreal MCP gateway reported an execution error.",
            }

        return {
            "success": True,
            "verified": True,
            "tool": "unreal_mcp",
            "operation": payload["operation"],
            "result": result,
        }
    except requests.RequestException as exc:
        return {
            "success": False,
            "verified": False,
            "retryable": True,
            "tool": tool_name,
            "error": f"Unreal MCP connection failed: {exc}",
        }
    except Exception as exc:
        return {
            "success": False,
            "verified": False,
            "retryable": True,
            "tool": tool_name,
            "error": str(exc),
        }
