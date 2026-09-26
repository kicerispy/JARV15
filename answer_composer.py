"""Evidence-grounded answer composition for JARVIS Autonomy Kernel v2.

The composer is intentionally deterministic for now. It never invents facts:
all substantive claims come from captured tool data or bounded execution
evidence. This makes it safe to use before introducing a model-backed
narration layer.
"""

from __future__ import annotations

import json
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from intent_resolver import resolve_intent, needs_evidence_answer


_GENERIC = {
    "",
    "done",
    "tool completed.",
    "browser action completed.",
    "google search complete.",
    "search complete.",
}


def _unwrap(value: Any) -> Any:
    if hasattr(value, "data") and hasattr(value, "success"):
        return getattr(value, "data", None)

    if isinstance(value, dict):
        marker_keys = {
            "success",
            "tool",
            "message",
            "error",
            "retryable",
            "observation",
        }
        if "data" in value and any(k in value for k in marker_keys):
            return value.get("data")

    return value


def _decode_json_text(value: Any) -> Any:
    if not isinstance(value, str):
        return value

    raw = value.strip()
    if not raw:
        return value

    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return value


def _mapping_payload(value: Any) -> Dict[str, Any]:
    """Return the most useful mapping from a direct or MCP content payload."""
    decoded = _decode_json_text(_unwrap(value))
    if isinstance(decoded, dict) and isinstance(decoded.get("content"), list):
        for item in decoded["content"]:
            if isinstance(item, dict) and "text" in item:
                nested = _decode_json_text(item.get("text"))
                if isinstance(nested, dict):
                    return nested
    return decoded if isinstance(decoded, dict) else {}

def _content_items(value: Any) -> List[Any]:
    value = _decode_json_text(_unwrap(value))

    if isinstance(value, dict) and isinstance(value.get("content"), list):
        items: List[Any] = []
        for item in value["content"]:
            if isinstance(item, dict) and "text" in item:
                decoded = _decode_json_text(item.get("text"))
                items.append(decoded)
            else:
                items.append(item)
        return items

    if isinstance(value, list):
        return list(value)

    return [value]


def _clip(text: Any, limit: int = 1200) -> str:
    value = " ".join(str(text or "").strip().split())
    if len(value) <= limit:
        return value
    return value[:limit].rstrip() + "…"


def _iter_dicts(value: Any) -> Iterable[Dict[str, Any]]:
    value = _decode_json_text(_unwrap(value))

    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _iter_dicts(child)
    elif isinstance(value, list):
        for item in value:
            yield from _iter_dicts(item)


def _names_from(value: Any) -> List[str]:
    names: List[str] = []
    for item in _iter_dicts(value):
        for key in (
            "fullName",
            "full_name",
            "path",
            "filePath",
            "file_path",
            "name",
            "displayName",
            "display_name",
        ):
            raw = item.get(key)
            if isinstance(raw, str) and raw.strip():
                name = raw.strip()
                if name not in names:
                    names.append(name)
                break
    return names


def _classes_from(value: Any) -> List[Tuple[str, str]]:
    pairs: List[Tuple[str, str]] = []
    for item in _iter_dicts(value):
        name = ""
        cls = ""
        for key in ("fullName", "full_name", "path", "name", "displayName"):
            raw = item.get(key)
            if raw and not name:
                name = str(raw).strip()
        for key in ("className", "class_name", "type", "instanceType"):
            raw = item.get(key)
            if raw and not cls:
                cls = str(raw).strip()

        if name and cls:
            pair = (name, cls)
            if pair not in pairs:
                pairs.append(pair)
    return pairs


def _script_like_names(value: Any) -> List[str]:
    """Extract actual Script/LocalScript/ModuleScript instances, not services."""
    names: List[str] = []
    exact_classes = {"Script", "LocalScript", "ModuleScript"}

    for item in _iter_dicts(value):
        name = ""
        for key in (
            "fullName",
            "full_name",
            "path",
            "filePath",
            "file_path",
            "name",
            "displayName",
            "display_name",
        ):
            raw = item.get(key)
            if isinstance(raw, str) and raw.strip():
                name = raw.strip()
                break

        cls = ""
        for key in ("className", "class_name", "type", "instanceType"):
            raw = item.get(key)
            if raw:
                cls = str(raw).strip()
                break

        lowered = name.lower()
        is_source_file = lowered.endswith((".lua", ".luau"))
        is_script_name = lowered.endswith((
            ".script",
            ".localscript",
            ".modulescript",
        ))

        if (
            name
            and (cls in exact_classes or is_source_file or is_script_name)
            and name not in names
        ):
            names.append(name)

    return names


def _meaningful_text(value: Any) -> List[str]:
    value = _decode_json_text(_unwrap(value))
    found: List[str] = []

    if isinstance(value, str):
        raw = value.strip()
        lowered = raw.lower()
        if raw and lowered not in _GENERIC:
            found.append(raw)
        return found

    if isinstance(value, dict):
        for key, child in value.items():
            if key in {
                "error",
                "retryable",
                "success",
                "verified",
            }:
                continue

            if isinstance(child, str):
                lowered = child.strip().lower()
                if child.strip() and lowered not in _GENERIC:
                    found.append(child.strip())
            elif isinstance(child, (dict, list)):
                found.extend(_meaningful_text(child))

    elif isinstance(value, list):
        for child in value:
            found.extend(_meaningful_text(child))

    return found


def _roblox_answer(task: Any, evidence: Sequence[Dict[str, Any]]) -> str:
    """Compose a compact Roblox answer from verified structured evidence."""
    place: Dict[str, Any] = {}
    structure: List[Any] = []
    scripts: List[Any] = []

    for item in evidence:
        tool = str(item.get("tool", "") or "").strip()
        data = _decode_json_text(item.get("data"))
        detail = str(item.get("detail", "") or "").strip()

        if tool == "roblox__get_place_info":
            place.update(_mapping_payload(data))
        elif tool == "roblox__get_project_structure":
            if data is not None:
                structure.extend(_content_items(data))
            if detail:
                structure.append(detail)
        elif tool in {
            "roblox__search_files",
            "roblox__grep_scripts",
            "roblox__get_script_source",
        }:
            if data is not None:
                scripts.extend(_content_items(data))
            if detail:
                scripts.append(detail)
        else:
            if detail:
                scripts.append(detail)
            if data is not None:
                scripts.extend(_content_items(data))

    lines: List[str] = []

    place_name = str(
        place.get("name")
        or place.get("placeName")
        or ""
    ).strip()
    place_id = str(
        place.get("placeId")
        or place.get("place_id")
        or ""
    ).strip()
    game_id = str(
        place.get("gameId")
        or place.get("game_id")
        or ""
    ).strip()

    request = str(getattr(task, "request", "") or "").strip().lower()
    identifiers_requested = any(
        phrase in request
        for phrase in (
            "place id",
            "game id",
            "place identifier",
            "game identifier",
            "place and game id",
            "place and game identifiers",
        )
    )

    if place_name:
        location = f"The active Roblox place is {place_name}."
        if identifiers_requested:
            if place_id:
                location += f" Its place ID is {place_id}."
            if game_id:
                location += f" The game ID is {game_id}."
        lines.append(location)

    exact_script_classes = {"Script", "LocalScript", "ModuleScript"}
    known_services = {
        "Workspace",
        "Players",
        "Lighting",
        "ReplicatedFirst",
        "ReplicatedStorage",
        "ServerScriptService",
        "ServerStorage",
        "StarterGui",
        "StarterPack",
        "StarterPlayer",
        "Teams",
        "SoundService",
        "TextChatService",
        "Chat",
        "MaterialService",
        "TestService",
    }

    service_names: List[str] = []
    script_names: List[str] = []

    for name, cls in _classes_from(structure):
        if cls in exact_script_classes:
            if name not in script_names:
                script_names.append(name)
        elif cls in known_services or name in known_services:
            if name not in service_names:
                service_names.append(name)

    if service_names:
        # Use service class names for speech instead of full game.X paths.
        # The full instance paths remain available in structured evidence.
        service_preview: List[str] = []
        for name, cls in _classes_from(structure):
            service = cls if cls in known_services else ""
            if not service:
                lowered_name = str(name).strip().lower()
                for candidate in known_services:
                    if lowered_name == candidate.lower() or lowered_name.endswith("." + candidate.lower()):
                        service = candidate
                        break
            if service and service not in service_preview:
                service_preview.append(service)

        if service_preview:
            # Keep the spoken structure summary intentionally small.
            preview = ", ".join(service_preview[:6])
            suffix = " and other standard services" if len(service_preview) > 6 else ""
            lines.append(
                f"The project is organized around {preview}{suffix}."
            )

    names: List[str] = list(script_names)
    for source in scripts:
        names.extend(_script_like_names(source))

    unique_names: List[str] = []
    for name in names:
        if name not in unique_names:
            unique_names.append(name)

    core_focus = any(
        phrase in request
        for phrase in (
            "core gameplay",
            "gameplay system",
            "gameplay systems",
            "gameplay scripts",
            "scripts that control gameplay",
            "scripts that control the gameplay",
        )
    )

    if core_focus:
        # Prefer server/client gameplay locations. Workspace scripts are often
        # attached to individual props/NPCs and are not enough evidence to call
        # them core gameplay systems.
        preferred = []
        preferred_markers = (
            "serverscriptservice",
            "starterplayer.starterplayerscripts",
            "replicatedstorage",
            "serverstorage",
        )
        for name in unique_names:
            lowered = name.lower()
            if any(marker in lowered for marker in preferred_markers):
                preferred.append(name)

        candidate_names = preferred
        if not candidate_names:
            candidate_names = [
                name for name in unique_names
                if "workspace." not in name.lower()
            ]

        candidate_names = candidate_names[:4]

        def _spoken_script_name(name: str) -> str:
            # Keep speech natural while retaining the exact path in evidence.
            return str(name).rsplit(".", 1)[-1].strip() or str(name).strip()

        spoken_names = []
        for name in candidate_names:
            short_name = _spoken_script_name(name)
            if short_name and short_name not in spoken_names:
                spoken_names.append(short_name)

        if spoken_names:
            count = len(spoken_names)
            noun = "script" if count == 1 else "scripts"
            lines.append(
                f"I found {count} likely core gameplay {noun}: "
                + ", ".join(spoken_names)
                + "."
            )
        elif scripts:
            lines.append(
                "I found script evidence, but none was clearly located in a "
                "core server or client gameplay area."
            )
    elif unique_names:
        preview = ", ".join(unique_names[:6])
        suffix = "…" if len(unique_names) > 6 else ""
        lines.append(
            f"I found {len(unique_names)} script-related item(s). "
            f"Examples: {preview}{suffix}."
        )

    if not lines:
        return (
            "I completed the Roblox inspection, but the returned evidence "
            "did not contain enough structured detail for a reliable summary."
        )

    # Evidence can remain richer than spoken output, but Roblox answers
    # should still be compact enough for natural TTS.
    return "\n".join(lines)[:650]

def _roblox_mcp_lifecycle_answer(
    task: Any,
    evidence: Sequence[Dict[str, Any]],
) -> str:
    """Summarize Roblox MCP setup/status evidence for the user."""
    request = str(getattr(task, "request", "") or "").strip().lower()
    item = next(
        (
            row for row in reversed(evidence)
            if str(row.get("tool", "") or "").strip()
            in {"roblox_mcp_status", "roblox_mcp_setup"}
        ),
        None,
    )
    if not item:
        return "The Roblox MCP check completed, but no structured status was returned."

    data = _mapping_payload(item.get("data"))
    if not data:
        detail = str(item.get("detail") or "").strip()
        return detail or "The Roblox MCP check completed, but no structured status was returned."

    server_url = str(data.get("server_url") or "").strip()
    health = data.get("health")
    status = data.get("status")

    plugin_connected = None
    candidates = []
    if isinstance(status, dict):
        candidates.append(status)
        for key in ("plugin", "studio", "connection", "connections"):
            value = status.get(key)
            if isinstance(value, dict):
                candidates.append(value)
    for candidate in candidates:
        for key in (
            "connected",
            "pluginConnected",
            "plugin_connected",
            "studioConnected",
            "studio_connected",
        ):
            value = candidate.get(key)
            if isinstance(value, bool):
                plugin_connected = value
                break
        if plugin_connected is not None:
            break

    healthy = isinstance(health, dict) and (
        health.get("healthy") is True
        or str(health.get("status") or "").lower() in {"ok", "healthy", "ready"}
    )

    if plugin_connected is True:
        answer = "Roblox MCP is running and the Roblox Studio plugin is connected."
    elif plugin_connected is False:
        answer = "Roblox MCP is running, but the Roblox Studio plugin is not connected."
    elif healthy:
        answer = "Roblox MCP is running. The health endpoint is responding, but Studio connection status was not exposed."
    else:
        answer = "Roblox MCP is reachable, but its detailed Studio connection state was not exposed."

    if "setup" in request:
        answer = "Roblox MCP setup completed. " + answer[0].lower() + answer[1:]

    return _clip(answer, 800)

def _integration_health_answer(task: Any, evidence: Sequence[Dict[str, Any]]) -> str:
    """Summarize the unified JARVIS tool/integration health sweep."""
    for item in reversed(evidence):
        if str(item.get("tool", "") or "").strip() != "integration_health":
            continue

        data = _decode_json_text(item.get("data"))
        if not isinstance(data, dict):
            continue

        components = data.get("components")
        if not isinstance(components, list):
            return str(data.get("message") or "").strip()

        groups: Dict[str, List[Dict[str, Any]]] = {}
        for component in components:
            if not isinstance(component, dict):
                continue
            groups.setdefault(str(component.get("status") or "UNKNOWN"), []).append(component)

        def names_for(status: str, limit: int = 8) -> str:
            names = [
                str(component.get("name"))
                for component in groups.get(status, [])
                if component.get("name")
            ]
            return ", ".join(names[:limit])

        lines = [str(data.get("message") or "").strip()]

        # Spoken health checks should identify problems, not recite every
        # healthy integration. The structured evidence still contains all
        # component states for UI/debugging.
        for status, label in (
            ("DEGRADED", "Degraded"),
            ("OFFLINE", "Offline"),
            ("DISABLED", "Disabled"),
            ("NOT_CONFIGURED", "Not configured"),
            ("NOT_INSTALLED", "Not installed"),
            ("NOT_READY", "Not ready"),
            ("ERROR", "Error"),
        ):
            names = names_for(status)
            if names:
                lines.append(f"{label}: {names}.")

        return "\n".join(line for line in lines if line)[:900]

    return "I completed the JARVIS integration health check, but there was not enough structured evidence to summarize it."

def _browser_answer(task: Any, evidence: Sequence[Dict[str, Any]]) -> str:
    """Summarize structured browser search evidence without reading raw metadata."""
    search_records: List[Dict[str, Any]] = []

    for item in evidence:
        tool = str(item.get("tool", "") or "").strip()
        if tool not in {
            "browser_search_google",
            "browser_search_bing",
            "search_website",
        }:
            continue

        data = _mapping_payload(item.get("data"))
        query = str(data.get("query") or "").strip()

        results = data.get("results")
        if isinstance(results, list):
            for result in results:
                if not isinstance(result, dict):
                    continue

                title = str(
                    result.get("title")
                    or result.get("name")
                    or ""
                ).strip()
                url = str(
                    result.get("url")
                    or result.get("href")
                    or ""
                ).strip()

                if not title:
                    continue

                record = {
                    "tool": tool,
                    "query": query,
                    "title": title,
                    "url": url,
                }

                if record not in search_records:
                    search_records.append(record)

        if not search_records:
            title = str(data.get("title") or "").strip()
            if title:
                record = {
                    "tool": tool,
                    "query": query,
                    "title": title,
                    "url": str(data.get("url") or "").strip(),
                }
                if record not in search_records:
                    search_records.append(record)

    request = str(getattr(task, "request", "") or "").strip()
    site = "Google"
    for item in evidence:
        tool = str(item.get("tool", "") or "").strip()
        if tool == "browser_search_bing":
            site = "Bing"
            break

    query = next(
        (
            record["query"]
            for record in search_records
            if record.get("query")
        ),
        "",
    )

    lines: List[str] = []
    if query:
        lines.append(f"I searched {site} for {query}.")
    else:
        lines.append("I checked the browser search results.")

    if search_records:
        lines.append(
            f"I found {len(search_records)} visible result"
            + ("s." if len(search_records) != 1 else ".")
        )
        lines.append(
            "The top results were: "
            + "; ".join(
                f"{index}. {record['title']}"
                for index, record in enumerate(search_records[:5], start=1)
            )
            + "."
        )
    elif request:
        lines.append(
            "The search completed, but the browser did not expose "
            "structured result titles for me to summarize."
        )

    return "\n".join(lines)


def _unreal_result_payload(data: Any) -> Dict[str, Any]:
    """Extract the useful upstream Unreal gateway payload from tool evidence."""
    decoded = _decode_json_text(_unwrap(data))
    if not isinstance(decoded, dict):
        return {}

    result = _decode_json_text(decoded.get("result", decoded))

    if isinstance(result, dict) and isinstance(result.get("structuredContent"), dict):
        result = result["structuredContent"]

    if isinstance(result, dict) and isinstance(result.get("content"), list):
        nested = _mapping_payload(result)
        if nested:
            result = nested

    return result if isinstance(result, dict) else {}


def _unreal_rows(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Return structured gateway rows from common search/describe result shapes."""
    rows: List[Dict[str, Any]] = []

    for key in (
        "results",
        "matches",
        "items",
        "capabilities",
        "tools",
        "actions",
        "candidates",
    ):
        value = payload.get(key)

        if isinstance(value, list):
            for item in value:
                if isinstance(item, dict) and item not in rows:
                    rows.append(item)
        elif isinstance(value, dict):
            for name, item in value.items():
                if isinstance(item, dict):
                    row = dict(item)
                    row.setdefault("name", name)
                    if row not in rows:
                        rows.append(row)

    return rows


def _unreal_row_name(row: Dict[str, Any]) -> str:
    tool = str(
        row.get("tool")
        or row.get("toolName")
        or row.get("tool_name")
        or ""
    ).strip()
    action = str(
        row.get("action")
        or row.get("actionName")
        or row.get("action_name")
        or ""
    ).strip()

    if tool and action:
        return f"{tool}.{action}"

    for key in (
        "capability",
        "capabilityId",
        "capability_id",
        "id",
        "name",
        "displayName",
        "display_name",
        "title",
        "label",
    ):
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()

    return ""


def _unreal_operation(item: Dict[str, Any], payload: Dict[str, Any]) -> str:
    operation = str(
        item.get("operation")
        or payload.get("operation")
        or ""
    ).strip().lower()

    if operation:
        return operation

    request = str(item.get("request") or "").lower()
    for candidate in ("search", "describe", "execute", "configure"):
        if candidate in request:
            return candidate

    return ""


def _unreal_answer(task: Any, evidence: Sequence[Dict[str, Any]]) -> str:
    """Compose concise, user-facing summaries for the upstream Unreal gateway."""
    status_items = [
        item for item in evidence
        if str(item.get("tool", "") or "").strip() == "unreal_mcp_status"
    ]

    if status_items:
        payload = _mapping_payload(status_items[-1].get("data"))
        connected = payload.get("connected") is True
        gateway_present = "unreal" in (
            payload.get("public_tools")
            if isinstance(payload.get("public_tools"), list)
            else []
        )

        if connected or gateway_present:
            return (
                "Unreal MCP is connected. The native server is authenticated "
                "and the Unreal gateway is ready."
            )

        return (
            "Unreal MCP responded, but the Unreal gateway was not advertised "
            "as available."
        )

    gateway_items = [
        item for item in evidence
        if str(item.get("tool", "") or "").strip() == "unreal_mcp"
    ]

    if not gateway_items:
        return "The Unreal MCP check completed successfully."

    item = gateway_items[-1]
    payload = _unreal_result_payload(item.get("data"))
    operation = _unreal_operation(item, payload)

    if operation == "search":
        rows = _unreal_rows(payload)
        names: List[str] = []

        for row in rows:
            name = _unreal_row_name(row)
            if name and name not in names:
                names.append(name)

        if names:
            preview = ", ".join(names[:6])
            suffix = " and more" if len(names) > 6 else ""
            noun = "capability" if len(names) == 1 else "capabilities"
            return (
                f"I found {len(names)} Unreal {noun}: "
                f"{preview}{suffix}."
            )

        text_values = _meaningful_text(payload)
        if text_values:
            return _clip(
                "The Unreal capability search completed. "
                + text_values[0].rstrip(".")
                + ".",
                650,
            )

        return (
            "The Unreal capability search completed, but it returned no "
            "capability names I could summarize."
        )

    if operation == "describe":
        rows = _unreal_rows(payload)
        names = [
            name
            for name in (_unreal_row_name(row) for row in rows)
            if name
        ]

        description = ""
        for key in ("description", "summary", "details", "help"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                description = _clip(value, 420)
                break

        if names and description:
            return f"I inspected {names[0]}. {description}"
        if names:
            return f"I inspected the Unreal capability {names[0]}."

        if description:
            return f"I inspected the requested Unreal capability. {description}"

        return (
            "The Unreal capability description was retrieved, but it did not "
            "include a concise description."
        )

    if operation == "execute":
        names = []
        tool = str(
            item.get("capability")
            or payload.get("capability")
            or payload.get("tool")
            or ""
        ).strip()
        action = str(
            item.get("action")
            or payload.get("action")
            or ""
        ).strip()

        if tool and action:
            names.append(f"{tool}.{action}")
        elif tool:
            names.append(tool)

        message = ""
        for key in ("message", "summary", "statusMessage", "result"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                message = _clip(value, 500)
                break

        if names and message:
            return f"I executed {names[0]}. {message}"
        if names:
            return f"I executed the Unreal action {names[0]} successfully."
        if message:
            return f"I executed the requested Unreal action. {message}"

        return "The requested Unreal action completed successfully."

    if operation == "configure":
        return "The Unreal MCP configuration change completed successfully."

    text_values = _meaningful_text(payload)
    if text_values:
        return _clip(text_values[0], 650)

    return "The Unreal MCP request completed successfully."


def _project_file_answer(evidence: Sequence[Dict[str, Any]]) -> str:
    """Summarize deterministic project-file lookup results."""
    values: List[str] = []

    for item in evidence:
        tool = str(item.get("tool", "") or "").strip()
        if tool not in {"find_file", "list_files"}:
            continue

        data = item.get("data")
        detail = str(item.get("detail", "") or "").strip()

        candidates: List[str] = []
        if isinstance(data, str):
            candidates.extend(
                line.strip()
                for line in data.splitlines()
                if line.strip()
            )
        elif isinstance(data, list):
            candidates.extend(
                str(value).strip()
                for value in data
                if str(value).strip()
            )
        elif isinstance(data, dict):
            for key in ("path", "paths", "files", "results", "matches"):
                value = data.get(key)
                if isinstance(value, str):
                    candidates.extend(
                        line.strip()
                        for line in value.splitlines()
                        if line.strip()
                    )
                elif isinstance(value, list):
                    candidates.extend(
                        str(entry).strip()
                        for entry in value
                        if str(entry).strip()
                    )

        if detail:
            for line in detail.splitlines():
                stripped = line.strip()
                if stripped and not stripped.lower().startswith("execution attempt"):
                    candidates.append(stripped)

        for candidate in candidates:
            candidate = candidate.removeprefix("Found:").strip()
            if candidate and candidate not in values:
                values.append(candidate)

    if not values:
        return "I checked the project, but I couldn't identify a matching file."

    preview = values[:8]
    lines = [f"I found {len(values)} matching project file" + ("s." if len(values) != 1 else ".")]
    lines.append("The matches are: " + "; ".join(preview) + ".")
    if len(values) > len(preview):
        lines.append(f"There are {len(values) - len(preview)} additional matches.")
    return " ".join(lines)


def _generic_answer(task: Any, evidence: Sequence[Dict[str, Any]]) -> str:
    lines: List[str] = []
    request = str(getattr(task, "request", "") or "").strip()

    for item in evidence:
        tool = str(item.get("tool", "") or "").strip()
        detail = str(item.get("detail", "") or "").strip()
        data = _decode_json_text(item.get("data"))

        useful = []
        if detail and detail.lower() not in _GENERIC:
            useful.append(detail)
        if data is not None:
            useful.extend(_meaningful_text(data))

        for text in useful:
            compact = _clip(text, 900)
            if compact and compact.lower() not in _GENERIC and compact not in lines:
                if tool:
                    lines.append(f"{tool}: {compact}")
                else:
                    lines.append(compact)

        if len(lines) >= 5:
            break

    if lines:
        header = (
            "I checked the requested information. Here’s what I found:"
            if request
            else "Here’s what I found:"
        )
        return header + "\n" + "\n".join(
            f"- {line.rstrip('.')}" + "."
            for line in lines[:5]
        )

    return (
        "I completed the requested checks, but the available evidence was "
        "not detailed enough for me to give you a reliable summary."
    )


def compose_task_answer(
    request: str,
    task: Any,
    active_context: Optional[Dict[str, Any]] = None,
) -> str:
    """Compose a user-facing answer using only verified captured evidence."""
    if not needs_evidence_answer(
        request,
        plan=getattr(task, "planner_result", None),
        active_context=active_context,
    ):
        return ""

    evidence = [
        item
        for item in (getattr(task, "evidence", []) or [])
        if isinstance(item, dict)
        and item.get("success") is True
        and item.get("verified") is True
    ]

    intent = resolve_intent(
        request,
        active_context=active_context,
        plan=getattr(task, "planner_result", None),
    )

    # Prefer the executed tool over keyword-based intent. Filenames such as
    # "browser_controller.py" contain browser vocabulary but are still project
    # filesystem lookups when find_file produced the evidence.
    executed_tools = {
        str(item.get("tool", "") or "").strip()
        for item in evidence
    }

    if "find_file" in executed_tools or "list_files" in executed_tools:
        return _project_file_answer(evidence)

    if "integration_health" in executed_tools:
        return _integration_health_answer(task, evidence)

    if "roblox_mcp_status" in executed_tools or "roblox_mcp_setup" in executed_tools:
        return _roblox_mcp_lifecycle_answer(task, evidence)

    if intent.get("domain") == "roblox":
        return _roblox_answer(task, evidence)

    if intent.get("domain") == "browser":
        return _browser_answer(task, evidence)

    if any(
        str(item.get("tool", "") or "").strip()
        in {"unreal_mcp", "unreal_mcp_status"}
        for item in evidence
    ):
        return _unreal_answer(task, evidence)

    return _generic_answer(task, evidence)
