"""Local MCP client for n8n instance-level MCP.

JARVIS uses this module as a thin, dependency-free bridge to the
self-hosted n8n MCP server. It supports streamable HTTP JSON-RPC,
bearer-token authentication, bounded responses, tool discovery, and
high-level workflow execution without exposing credentials to the model.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from config import (
    N8N_MCP_DISCOVERY_TTL_SECONDS,
    N8N_MCP_ENABLED,
    N8N_MCP_EXECUTION_TIMEOUT_SECONDS,
    N8N_MCP_MAX_RESPONSE_BYTES,
    N8N_MCP_TIMEOUT_SECONDS,
    N8N_MCP_TOKEN,
    N8N_MCP_TOKEN_FILE,
    N8N_MCP_URL,
)

MODERN_MCP_PROTOCOL_VERSION = "2026-07-28"
LEGACY_MCP_PROTOCOL_VERSION = "2025-03-26"
MCP_PROTOCOL_VERSION = MODERN_MCP_PROTOCOL_VERSION
CLIENT_NAME = "JARVIS"
CLIENT_VERSION = "1.0"

MAX_TEXT_CHARS = 12000
MAX_DYNAMIC_TOOLS = 100

_TOOL_CACHE: Dict[str, Any] = {
    "expires_at": 0.0,
    "tools": [],
}
_SESSION_ID: Optional[str] = None
_PROTOCOL_MODE = "unknown"
_NEGOTIATED_PROTOCOL_VERSION = ""
_REQUEST_ID = 0


def _next_request_id() -> int:
    global _REQUEST_ID
    _REQUEST_ID += 1
    return _REQUEST_ID


def _bounded_text(value: Any, limit: int = MAX_TEXT_CHARS) -> str:
    text = str(value or "")
    if len(text) > limit:
        return text[:limit] + "...<truncated>"
    return text


def _token() -> str:
    if N8N_MCP_TOKEN.strip():
        return N8N_MCP_TOKEN.strip()

    path = Path(os.path.expandvars(os.path.expanduser(N8N_MCP_TOKEN_FILE)))
    try:
        value = path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""

    return value


def _request_headers(
    method: str = "",
    *,
    protocol_version: str = "",
    modern: bool = False,
    tool_name: str = "",
) -> Dict[str, str]:
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "Mcp-Method": method,
        "Mcp-Name": tool_name,
        "User-Agent": f"{CLIENT_NAME}/{CLIENT_VERSION}",
    }

    if protocol_version:
        headers["MCP-Protocol-Version"] = protocol_version

    token = _token()
    if token:
        headers["Authorization"] = f"Bearer {token}"

    if _SESSION_ID and not modern:
        headers["Mcp-Session-Id"] = _SESSION_ID

    return headers


def _parse_sse(raw: str) -> Any:
    """Parse the first JSON data event from an SSE response."""
    for block in raw.replace("\r\n", "\n").split("\n\n"):
        data_lines = []
        for line in block.split("\n"):
            if line.startswith("data:"):
                data_lines.append(line[5:].lstrip())
        if not data_lines:
            continue

        payload = "\n".join(data_lines).strip()
        if not payload or payload == "[DONE]":
            continue

        try:
            return json.loads(payload)
        except json.JSONDecodeError:
            continue

    raise ValueError("n8n MCP returned an SSE response without JSON data.")


def _decode_response(response) -> Any:
    global _SESSION_ID

    session_id = response.headers.get("Mcp-Session-Id")
    if session_id:
        _SESSION_ID = session_id

    raw = response.read(N8N_MCP_MAX_RESPONSE_BYTES + 1)
    if len(raw) > N8N_MCP_MAX_RESPONSE_BYTES:
        raise ValueError("n8n MCP response exceeded the configured size limit.")

    text = raw.decode("utf-8", errors="replace").strip()
    if not text:
        return {}

    content_type = str(
        response.headers.get("Content-Type", "")
    ).lower()

    if "text/event-stream" in content_type:
        return _parse_sse(text)

    return json.loads(text)


def _rpc(
    method: str,
    params: Optional[Dict[str, Any]] = None,
    *,
    notification: bool = False,
    protocol_version: str = "",
    modern: bool = False,
) -> Any:
    if not N8N_MCP_ENABLED:
        raise RuntimeError("n8n MCP is disabled.")

    if not N8N_MCP_URL:
        raise RuntimeError("n8n MCP URL is not configured.")

    request_id = _next_request_id()
    body: Dict[str, Any] = {
        "jsonrpc": "2.0",
        "method": method,
    }

    if not notification:
        body["id"] = request_id

    effective_params = dict(params or {})

    if modern:
        meta = effective_params.get("_meta")
        if not isinstance(meta, dict):
            meta = {}
        meta.setdefault(
            "io.modelcontextprotocol/protocolVersion",
            protocol_version or MODERN_MCP_PROTOCOL_VERSION,
        )
        meta.setdefault(
            "io.modelcontextprotocol/clientCapabilities",
            {},
        )
        meta.setdefault(
            "io.modelcontextprotocol/clientInfo",
            {
                "name": CLIENT_NAME,
                "version": CLIENT_VERSION,
            },
        )
        effective_params["_meta"] = meta

    if effective_params:
        body["params"] = effective_params

    headers = _request_headers(
        method,
        protocol_version=protocol_version,
        modern=modern,
        tool_name=str(effective_params.get("name") or "") if method == "tools/call" else "",
    )

    request = Request(
        N8N_MCP_URL,
        data=json.dumps(
            body,
            ensure_ascii=False,
            default=str,
        ).encode("utf-8"),
        headers=headers,
        method="POST",
    )

    try:
        with urlopen(
            request,
            timeout=N8N_MCP_TIMEOUT_SECONDS,
        ) as response:
            result = _decode_response(response)

        if notification:
            return result

        if not isinstance(result, dict):
            raise RuntimeError("n8n MCP returned an invalid JSON-RPC response.")

        if result.get("error"):
            error = result["error"]
            if isinstance(error, dict):
                message = error.get("message") or "n8n MCP request failed."
                code = error.get("code")
                detail = error.get("data")
                suffix = f" (code {code})" if code is not None else ""
                if detail and isinstance(detail, (dict, list, str)):
                    suffix += f" {str(detail)[:1000]}"
                raise RuntimeError(f"{message}{suffix}")
            raise RuntimeError(str(error))

        return result.get("result", result)

    except HTTPError as exc:
        detail = ""
        try:
            raw = exc.read(4096).decode("utf-8", errors="replace")
            detail = f": {raw[:1000]}"
        except Exception:
            pass
        raise RuntimeError(
            f"n8n MCP HTTP {exc.code}{detail}"
        ) from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise RuntimeError(
            f"n8n MCP connection failed: {exc}"
        ) from exc


def _legacy_initialize() -> Dict[str, Any]:
    global _SESSION_ID, _TOOL_CACHE

    _SESSION_ID = None
    _TOOL_CACHE = {"expires_at": 0.0, "tools": []}

    result = _rpc(
        "initialize",
        {
            "protocolVersion": LEGACY_MCP_PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {
                "name": CLIENT_NAME,
                "version": CLIENT_VERSION,
            },
        },
        protocol_version=LEGACY_MCP_PROTOCOL_VERSION,
        modern=False,
    )

    try:
        _rpc(
            "notifications/initialized",
            notification=True,
            protocol_version=LEGACY_MCP_PROTOCOL_VERSION,
            modern=False,
        )
    except Exception:
        pass

    return result if isinstance(result, dict) else {"result": result}


def discover_protocol() -> Dict[str, Any]:
    """Probe the modern MCP revision without creating a session."""
    global _PROTOCOL_MODE, _NEGOTIATED_PROTOCOL_VERSION, _SESSION_ID

    _SESSION_ID = None

    result = _rpc(
        "server/discover",
        {
            "_meta": {
                "io.modelcontextprotocol/protocolVersion": MODERN_MCP_PROTOCOL_VERSION,
                "io.modelcontextprotocol/clientCapabilities": {},
                "io.modelcontextprotocol/clientInfo": {
                    "name": CLIENT_NAME,
                    "version": CLIENT_VERSION,
                },
            }
        },
        protocol_version=MODERN_MCP_PROTOCOL_VERSION,
        modern=True,
    )

    _PROTOCOL_MODE = "modern"
    _NEGOTIATED_PROTOCOL_VERSION = MODERN_MCP_PROTOCOL_VERSION
    return result if isinstance(result, dict) else {"result": result}


def initialize() -> Dict[str, Any]:
    global _PROTOCOL_MODE, _NEGOTIATED_PROTOCOL_VERSION, _SESSION_ID, _TOOL_CACHE

    if _PROTOCOL_MODE == "modern":
        _SESSION_ID = None
        _TOOL_CACHE = {"expires_at": 0.0, "tools": []}
        return discover_protocol()

    if _PROTOCOL_MODE == "legacy":
        return _legacy_initialize()

    try:
        result = discover_protocol()
        return result
    except Exception as modern_exc:
        _PROTOCOL_MODE = "legacy"
        _NEGOTIATED_PROTOCOL_VERSION = LEGACY_MCP_PROTOCOL_VERSION
        try:
            return _legacy_initialize()
        except Exception as legacy_exc:
            raise RuntimeError(
                "n8n MCP protocol negotiation failed. "
                f"Modern: {modern_exc}; Legacy: {legacy_exc}"
            ) from legacy_exc


def list_tools(force: bool = False) -> List[Dict[str, Any]]:
    now = time.monotonic()

    if (
        not force
        and isinstance(_TOOL_CACHE.get("tools"), list)
        and _TOOL_CACHE.get("expires_at", 0.0) > now
    ):
        return list(_TOOL_CACHE["tools"])

    initialize()

    modern = _PROTOCOL_MODE == "modern"
    protocol_version = (
        _NEGOTIATED_PROTOCOL_VERSION
        or (MODERN_MCP_PROTOCOL_VERSION if modern else LEGACY_MCP_PROTOCOL_VERSION)
    )

    # MCP pagination params are optional. Do not send cursor: null on the
    # first page because some servers (including n8n) reject explicit null.
    result = _rpc(
        "tools/list",
        protocol_version=protocol_version,
        modern=modern,
    )
    sanitized: List[Dict[str, Any]] = []

    while True:
        tools = result.get("tools", []) if isinstance(result, dict) else []
        if not isinstance(tools, list):
            raise RuntimeError("n8n MCP tools/list returned an invalid tool list.")

        for item in tools:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name", "") or "").strip()
            if not name:
                continue

            sanitized.append(
                {
                    "name": name,
                    "description": _bounded_text(item.get("description", "")),
                    "inputSchema": (
                        item.get("inputSchema")
                        if isinstance(item.get("inputSchema"), dict)
                        else {}
                    ),
                }
            )

            if len(sanitized) >= MAX_DYNAMIC_TOOLS:
                break

        if len(sanitized) >= MAX_DYNAMIC_TOOLS:
            break

        next_cursor = (
            result.get("nextCursor")
            if isinstance(result, dict)
            else None
        )
        if not isinstance(next_cursor, str) or not next_cursor:
            break

        result = _rpc(
            "tools/list",
            {"cursor": next_cursor},
            protocol_version=protocol_version,
            modern=modern,
        )

    _TOOL_CACHE["tools"] = sanitized[:MAX_DYNAMIC_TOOLS]
    _TOOL_CACHE["expires_at"] = now + max(
        0.0,
        float(N8N_MCP_DISCOVERY_TTL_SECONDS),
    )
    return list(sanitized)


def tool_descriptions() -> Dict[str, str]:
    descriptions: Dict[str, str] = {}
    for item in list_tools():
        schema = item.get("inputSchema")
        schema_text = ""
        if isinstance(schema, dict):
            try:
                schema_text = _bounded_text(
                    json.dumps(schema, ensure_ascii=False, separators=(",", ":")),
                    3500,
                )
            except (TypeError, ValueError):
                schema_text = ""

        descriptions[f"n8n_mcp__{item['name']}"] = (
            f"n8n MCP tool: {item.get('description') or item['name']}. "
            "Argument must be a JSON object."
            + (f" Input schema: {schema_text}" if schema_text else "")
        )
    return descriptions


def is_known_tool(name: str) -> bool:
    remote_name = str(name or "")
    if remote_name.startswith("n8n_mcp__"):
        remote_name = remote_name[len("n8n_mcp__"):]

    try:
        return any(
            item.get("name") == remote_name
            for item in list_tools()
        )
    except Exception:
        return False


def call_tool(
    name: str,
    arguments: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    remote_name = str(name or "")
    if remote_name.startswith("n8n_mcp__"):
        remote_name = remote_name[len("n8n_mcp__"):]

    if not remote_name:
        return {
            "success": False,
            "retryable": False,
            "terminal": True,
            "execution_owner": "n8n",
            "message": "n8n MCP tool name is empty.",
        }

    try:
        if not is_known_tool(remote_name):
            return {
                "success": False,
                "retryable": False,
                "terminal": True,
                "execution_owner": "n8n",
                "message": f"Unknown n8n MCP tool: {remote_name}",
            }

        result = _rpc(
            "tools/call",
            {
                "name": remote_name,
                "arguments": arguments if isinstance(arguments, dict) else {},
            },
        )

        is_error = bool(
            result.get("isError")
            if isinstance(result, dict)
            else False
        )
        parsed: Any = result

        if isinstance(result, dict):
            structured = result.get("structuredContent")
            if structured is not None:
                parsed = structured
            else:
                content = result.get("content")
                if isinstance(content, list):
                    text_parts = [
                        item.get("text", "")
                        for item in content
                        if isinstance(item, dict)
                        and item.get("type") == "text"
                    ]
                    if text_parts:
                        combined = "\n".join(text_parts).strip()
                        try:
                            parsed = json.loads(combined)
                        except json.JSONDecodeError:
                            parsed = {"text": _bounded_text(combined)}

        payload = parsed if isinstance(parsed, dict) else {"result": parsed}

        return {
            "success": not is_error,
            "verified": not is_error,
            "retryable": False,
            "terminal": True,
            "execution_owner": "n8n",
            "mcp_tool": remote_name,
            "data": payload,
            "message": (
                f"n8n MCP tool {remote_name} completed."
                if not is_error
                else f"n8n MCP tool {remote_name} reported an error."
            ),
        }

    except Exception as exc:
        return {
            "success": False,
            "verified": False,
            "retryable": False,
            "terminal": True,
            "execution_owner": "n8n",
            "mcp_tool": remote_name,
            "message": str(exc),
        }


def status() -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "success": False,
        "verified": False,
        "enabled": bool(N8N_MCP_ENABLED),
        "configured": bool(N8N_MCP_URL and _token()),
        "reachable": False,
        "url": N8N_MCP_URL,
        "execution_owner": "n8n",
        "transport": "streamable_http",
    }

    if not N8N_MCP_ENABLED:
        result["message"] = "n8n MCP is disabled."
        return result

    if not N8N_MCP_URL:
        result["message"] = "n8n MCP URL is not configured."
        return result

    if not _token():
        result["message"] = "n8n MCP token is not configured."
        return result

    try:
        initialized = initialize()
        result.update(
            {
                "success": True,
                "verified": True,
                "reachable": True,
                "protocol_version": (
                    initialized.get("protocolVersion")
                    if isinstance(initialized, dict)
                    else None
                ),
                "message": "n8n MCP is reachable and authenticated.",
            }
        )
        return result
    except Exception as exc:
        result["message"] = str(exc)
        return result


def _score_workflow(request: str, workflow: Dict[str, Any]) -> float:
    text = " ".join(
        str(request or "").lower().split()
    )
    haystack = " ".join(
        [
            str(workflow.get("name") or ""),
            str(workflow.get("description") or ""),
            " ".join(
                str(tag.get("name", ""))
                for tag in workflow.get("tags", [])
                if isinstance(tag, dict)
            ),
        ]
    ).lower()

    tokens = {
        token.strip(".,!?;:()[]{}\"'")
        for token in text.split()
        if len(token) >= 3
    }

    score = float(sum(1 for token in tokens if token in haystack))

    request_phrase = text.strip()
    if request_phrase and request_phrase in haystack:
        score += 8.0

    for strong in (
        "weather",
        "email",
        "calendar",
        "github",
        "discord",
        "slack",
        "spotify",
        "monitor",
        "schedule",
        "automation",
        "workflow",
        "research",
    ):
        if strong in text and strong in haystack:
            score += 2.0

    return score


def _workflow_search_queries(
    request: str,
    workflow_class: str,
) -> List[str]:
    """Build progressively broader queries for n8n's name/description search."""
    request_text = " ".join(str(request or "").split()).strip()
    class_text = " ".join(str(workflow_class or "").split()).strip()

    queries: List[str] = []
    if request_text:
        queries.append(request_text)

    stopwords = {
        "a", "an", "and", "for", "from", "in", "into", "me", "my",
        "of", "on", "please", "run", "the", "to", "use", "with",
    }
    keywords = [
        token.strip(".,!?;:()[]{}\"'")
        for token in request_text.split()
        if token.strip(".,!?;:()[]{}\"'").lower() not in stopwords
        and len(token.strip(".,!?;:()[]{}\"'")) >= 3
    ]
    if keywords:
        keyword_query = " ".join(keywords)
        if keyword_query not in queries:
            queries.append(keyword_query)

    if class_text and class_text not in queries:
        queries.append(class_text)

    return queries


def _select_workflow(
    request: str,
    workflow_class: str,
) -> Optional[Dict[str, Any]]:
    candidates: List[Dict[str, Any]] = []

    for query in _workflow_search_queries(request, workflow_class):
        result = call_tool(
            "search_workflows",
            {
                "query": query,
                "limit": 50,
                "sortBy": "updatedAt:desc",
            },
        )

        if result.get("success") is not True:
            continue

        payload = result.get("data")
        if isinstance(payload, dict):
            values = payload.get("data", [])
        else:
            values = []

        if isinstance(values, list):
            candidates.extend(
                item
                for item in values
                if isinstance(item, dict)
                and item.get("availableInMCP") is True
            )

        if candidates:
            break

    deduped: Dict[str, Dict[str, Any]] = {}
    for workflow in candidates:
        workflow_id = str(workflow.get("id") or "").strip()
        if workflow_id:
            deduped[workflow_id] = workflow

    ranked = sorted(
        deduped.values(),
        key=lambda item: (
            _score_workflow(request, item),
            str(item.get("updatedAt") or ""),
        ),
        reverse=True,
    )

    if not ranked:
        return None

    return ranked[0]


def _trigger_candidates(workflow: Dict[str, Any]) -> List[Dict[str, Any]]:
    nodes = workflow.get("nodes", [])
    if not isinstance(nodes, list):
        return []

    candidates: List[Dict[str, Any]] = []

    for node in nodes:
        if not isinstance(node, dict):
            continue

        node_type = str(node.get("type") or "").lower()
        name = str(node.get("name") or "").strip()

        kind = None
        if "chattrigger" in node_type or "chat trigger" in node_type:
            kind = "chat"
        elif node_type.endswith(".webhook") or node_type.endswith("/webhook") or "webhook" in node_type:
            kind = "webhook"
        elif "formtrigger" in node_type or "form trigger" in node_type:
            kind = "form"
        elif "scheduletrigger" in node_type or "schedule trigger" in node_type or node_type.endswith(".cron"):
            kind = "schedule"
        elif "manualtrigger" in node_type or "manual trigger" in node_type:
            kind = "manual"

        if kind:
            candidates.append(
                {
                    "name": name,
                    "kind": kind,
                }
            )

    return candidates


def _build_execution_inputs(
    trigger: Dict[str, Any],
    request: str,
    context: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    kind = trigger.get("kind")

    if kind == "chat":
        return {
            "chatInput": request,
        }

    if kind == "webhook":
        body = dict(context)
        body["request"] = request
        body["workflow_class"] = str(
            context.get("workflow_class") or ""
        )
        return {
            "webhookData": {
                "method": "POST",
                "body": body,
            }
        }

    if kind == "form":
        body = dict(context)
        body["request"] = request
        return {
            "formData": body,
        }

    return None


def run_workflow_request(
    request: str,
    workflow_class: str,
    context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Find and execute an MCP-enabled n8n workflow for a JARVIS request."""
    context = dict(context or {})
    context["workflow_class"] = workflow_class

    workflow = _select_workflow(request, workflow_class)

    if workflow is None:
        return {
            "success": False,
            "verified": False,
            "retryable": False,
            "terminal": True,
            "execution_owner": "n8n",
            "message": (
                "No MCP-enabled n8n workflow matched the request. "
                "Enable the intended workflow under Settings > Instance-level MCP."
            ),
        }

    workflow_id = str(workflow.get("id") or "").strip()
    details = call_tool(
        "get_workflow_details",
        {
            "workflowId": workflow_id,
            "detailLevel": "full",
        },
    )

    if details.get("success") is not True:
        return details

    payload = details.get("data")
    if not isinstance(payload, dict):
        return {
            "success": False,
            "verified": False,
            "retryable": False,
            "terminal": True,
            "execution_owner": "n8n",
            "message": "n8n returned invalid workflow details.",
        }

    workflow_data = payload.get("workflow")
    if not isinstance(workflow_data, dict):
        return {
            "success": False,
            "verified": False,
            "retryable": False,
            "terminal": True,
            "execution_owner": "n8n",
            "message": "n8n workflow details were missing workflow metadata.",
        }

    can_execute = workflow_data.get("canExecute")
    if can_execute is False:
        return {
            "success": False,
            "verified": False,
            "retryable": False,
            "terminal": True,
            "execution_owner": "n8n",
            "message": f"You don't have permission to execute workflow {workflow_data.get('name') or workflow_id}.",
        }

    trigger_candidates = _trigger_candidates(workflow_data)
    if not trigger_candidates:
        return {
            "success": False,
            "verified": False,
            "retryable": False,
            "terminal": True,
            "execution_owner": "n8n",
            "message": (
                f"Workflow {workflow_data.get('name') or workflow_id} has no supported MCP trigger."
            ),
        }

    if len(trigger_candidates) > 1:
        input_candidates = [
            item for item in trigger_candidates
            if item["kind"] in {"chat", "webhook", "form"}
        ]
        if len(input_candidates) == 1:
            trigger = input_candidates[0]
        else:
            return {
                "success": False,
                "verified": False,
                "retryable": False,
                "terminal": True,
                "execution_owner": "n8n",
                "workflow_id": workflow_id,
                "workflow_name": workflow_data.get("name"),
                "message": (
                    "Multiple eligible n8n triggers exist. "
                    "Choose one explicitly: "
                    + ", ".join(item["name"] for item in trigger_candidates)
                ),
            }
    else:
        trigger = trigger_candidates[0]

    active = bool(workflow_data.get("active"))
    mode = "production" if active else "manual"

    inputs = _build_execution_inputs(
        trigger,
        request,
        context,
    )

    params: Dict[str, Any] = {
        "workflowId": workflow_id,
        "executionMode": mode,
        "triggerNodeName": trigger.get("name"),
    }

    if inputs is not None:
        params["inputs"] = inputs

    execution = call_tool(
        "execute_workflow",
        params,
    )

    if execution.get("success") is not True:
        return execution

    execution_payload = execution.get("data")
    if not isinstance(execution_payload, dict):
        return execution

    execution_id = execution_payload.get("executionId")
    if not execution_id:
        return {
            "success": False,
            "verified": False,
            "retryable": False,
            "terminal": True,
            "execution_owner": "n8n",
            "workflow_id": workflow_id,
            "workflow_name": workflow_data.get("name"),
            "message": "n8n accepted the workflow call without an execution ID.",
        }

    deadline = time.monotonic() + max(
        1.0,
        float(N8N_MCP_EXECUTION_TIMEOUT_SECONDS),
    )
    terminal_statuses = {
        "success",
        "error",
        "canceled",
        "crashed",
        "unknown",
    }
    execution_state = {}

    while time.monotonic() < deadline:
        check = call_tool(
            "get_workflow_execution",
            {
                "workflowId": workflow_id,
                "executionId": execution_id,
                "includeData": True,
                "truncateData": 50,
            },
        )

        if check.get("success") is True:
            check_payload = check.get("data")
            if isinstance(check_payload, dict):
                execution_state = check_payload.get("execution") or {}
                status = str(
                    execution_state.get("status") or ""
                ).lower()

                if status in terminal_statuses:
                    return {
                        "success": status == "success",
                        "verified": status == "success",
                        "retryable": False,
                        "terminal": True,
                        "execution_owner": "n8n",
                        "workflow_id": workflow_id,
                        "workflow_name": workflow_data.get("name"),
                        "execution_id": execution_id,
                        "execution_status": status,
                        "data": check_payload.get("data"),
                        "message": (
                            f"n8n workflow {workflow_data.get('name') or workflow_id} "
                            f"finished with status {status}."
                        ),
                    }

        time.sleep(1.0)

    return {
        "success": True,
        "verified": False,
        "retryable": False,
        "terminal": True,
        "execution_owner": "n8n",
        "workflow_id": workflow_id,
        "workflow_name": workflow_data.get("name"),
        "execution_id": execution_id,
        "execution_status": str(
            execution_state.get("status") or "running"
        ),
        "message": (
            f"n8n started {workflow_data.get('name') or workflow_id}; "
            "the execution did not finish before the bounded wait expired."
        ),
    }
