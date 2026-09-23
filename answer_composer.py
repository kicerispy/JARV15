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

    if place_name:
        location = f"The active Roblox place is {place_name}"
        if place_id:
            location += f" (place ID {place_id})"
        if game_id:
            location += f", in game {game_id}"
        lines.append(location + ".")

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
        preview = ", ".join(service_names[:10])
        suffix = "…" if len(service_names) > 10 else ""
        lines.append(f"The project uses: {preview}{suffix}.")

    names: List[str] = list(script_names)
    for source in scripts:
        names.extend(_script_like_names(source))

    unique_names: List[str] = []
    for name in names:
        if name not in unique_names:
            unique_names.append(name)

    request = str(getattr(task, "request", "") or "").strip().lower()
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
        # Prefer server/client entry points that are structurally closer to
        # gameplay execution. This is a location-based shortlist, not a claim
        # that these scripts are definitely responsible for every game system.
        preferred = []
        for name in unique_names:
            lowered = name.lower()
            if any(
                marker in lowered
                for marker in (
                    "serverscriptservice",
                    "starterplayer.starterplayerscripts",
                )
            ):
                preferred.append(name)

        ordered = preferred + [
            name for name in unique_names if name not in preferred
        ]
        unique_names = ordered[:5]

        if unique_names:
            lines.append(
                f"I found {len(unique_names)} likely core gameplay entry point(s): "
                + ", ".join(unique_names)
                + "."
            )
        elif scripts:
            lines.append(
                "I found script evidence, but none was clearly located in a "
                "server/client gameplay entry point."
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

    return "\n".join(lines)[:900]

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

    if intent.get("domain") == "browser":
        return _browser_answer(task, evidence)

    return _generic_answer(task, evidence)
