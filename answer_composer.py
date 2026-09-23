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
    script_terms = (
        "script",
        "module",
        ".lua",
        ".luau",
    )
    names: List[str] = []

    for item in _names_from(value):
        lowered = item.lower()
        if any(term in lowered for term in script_terms):
            if item not in names:
                names.append(item)

    for name, cls in _classes_from(value):
        lowered_cls = cls.lower()
        if "script" in lowered_cls and name not in names:
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
    place = {}
    structure = []
    scripts = []

    for item in evidence:
        tool = str(item.get("tool", "") or "").strip()
        data = _decode_json_text(item.get("data"))
        detail = str(item.get("detail", "") or "").strip()

        if tool == "roblox__get_place_info":
            place.update(data if isinstance(data, dict) else {})
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

    if place_name:
        location = f"The active Roblox place is {place_name}"
        if place_id:
            location += f" (place ID {place_id})"
        if game_id:
            location += f", in game {game_id}"
        lines.append(location + ".")

    pair_data = []
    for source in structure:
        pair_data.extend(_classes_from(source))

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

    service_names = []
    script_names = []
    for name, cls in pair_data:
        lowered = cls.lower()
        if "script" in lowered:
            if name not in script_names:
                script_names.append(name)
        elif cls in known_services or name in known_services:
            if name not in service_names:
                service_names.append(name)

    if service_names:
        preview = ", ".join(service_names[:12])
        suffix = "…" if len(service_names) > 12 else ""
        lines.append(
            "The structure includes: "
            + preview
            + suffix
            + "."
        )

    names = []
    for source in scripts:
        names.extend(_script_like_names(source))

    if names:
        unique = []
        for name in names:
            if name not in unique:
                unique.append(name)

        preview = ", ".join(unique[:15])
        suffix = "…" if len(unique) > 15 else ""
        count_text = (
            f"{len(unique)} script-related items were found. "
            if len(unique) > 1
            else "One script-related item was found. "
        )
        lines.append(
            count_text
            + "Examples include: "
            + preview
            + suffix
            + "."
        )

    raw_text = []
    for source in structure + scripts:
        raw_text.extend(_meaningful_text(source))

    # Keep evidence-derived narrative useful without dumping raw MCP JSON.
    for chunk in raw_text[:4]:
        compact = _clip(chunk, 900)
        if compact and compact not in lines and compact not in _GENERIC:
            lines.append(compact.rstrip(".") + ".")

    if not lines:
        return (
            "I completed the Roblox inspection, but the returned evidence "
            "did not contain enough structured detail for me to summarize it safely."
        )

    return "\n".join(lines)


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

    if intent.get("domain") == "roblox":
        return _roblox_answer(task, evidence)

    return _generic_answer(task, evidence)
