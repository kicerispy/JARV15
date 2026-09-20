"""Deterministic follow-up handling for structured JARVIS results.

This module deliberately avoids an LLM call for simple references to the
most recent structured result. It supports result lists, knowledge summaries,
selected-result follow-ups, and source requests.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Optional


_ORDINALS = {
    "first": 0,
    "1st": 0,
    "second": 1,
    "2nd": 1,
    "third": 2,
    "3rd": 2,
    "fourth": 3,
    "4th": 3,
    "fifth": 4,
    "5th": 4,
    "sixth": 5,
    "6th": 5,
    "seventh": 6,
    "7th": 6,
    "eighth": 7,
    "8th": 7,
    "ninth": 8,
    "9th": 8,
    "tenth": 9,
    "10th": 9,
    "last": -1,
    "final": -1,
}

_LIST_KEYS = (
    "books",
    "papers",
    "results",
    "holidays",
    "alerts",
    "earthquakes",
    "products",
    "items",
    "apis",
    "candidates",
)

_REFERENCE_WORDS = (
    "one",
    "item",
    "result",
    "book",
    "paper",
    "holiday",
    "alert",
    "earthquake",
    "product",
    "candidate",
    "entry",
)

_MORE_PATTERNS = (
    r"^tell me more(?: about (?:that|this|it))?$",
    r"^tell me more about (?:the )?(?:first|second|third|fourth|fifth|last|that|this|it)(?: one| result| item| book| paper| product)?$",
    r"^what else can you tell me(?: about (?:that|this|it))?$",
    r"^give me more (?:information|info|details)(?: about (?:that|this|it))?$",
    r"^explain (?:that|this|it) (?:more|further)$",
    r"^expand on (?:that|this|it)$",
)

_SOURCE_PATTERNS = (
    r"^(?:what(?:'s| is) the source|where did you get (?:that|this|it))$",
    r"^(?:where(?: did)? that come from|what is the source)$",
)


def _normalize(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _unwrap(data: Any) -> Any:
    if isinstance(data, dict) and "data" in data:
        marker_keys = {"success", "tool", "message", "retryable", "observation"}
        if any(key in data for key in marker_keys):
            return data.get("data")
    return data


def _result_data(context: Dict[str, Any]) -> Any:
    return _unwrap(context.get("last_result_data"))


def _items_for(context: Dict[str, Any]) -> list:
    data = _result_data(context)

    if isinstance(data, list):
        return [item for item in data if isinstance(item, (dict, str))]

    if not isinstance(data, dict):
        return []

    for key in _LIST_KEYS:
        value = data.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, (dict, str))]

    return []


def _display_name(item: Any, tool: str = "") -> str:
    if isinstance(item, str):
        return item.strip()

    if not isinstance(item, dict):
        return str(item).strip()

    for key in (
        "title",
        "name",
        "product_name",
        "display_name",
        "event",
        "word",
        "headline",
    ):
        value = item.get(key)
        if value:
            return str(value).strip()

    return ""


def _authors_text(item: Dict[str, Any]) -> str:
    authors = item.get("authors") or item.get("author") or []

    if isinstance(authors, str):
        return authors.strip()

    if isinstance(authors, list):
        names = []
        for author in authors[:4]:
            if isinstance(author, dict):
                name = " ".join(
                    str(author.get(key) or "").strip()
                    for key in ("given", "family")
                    if author.get(key)
                ).strip()
            else:
                name = str(author).strip()

            if name:
                names.append(name)

        return ", ".join(names)

    return ""


def _compact_item_details(item: Any, tool: str) -> str:
    if isinstance(item, str):
        return item.strip()

    if not isinstance(item, dict):
        return str(item).strip()

    title = _display_name(item, tool)

    if tool == "book_search":
        authors = _authors_text(item)
        year = item.get("first_publish_year")
        parts = []

        if title:
            parts.append(title)
        if authors:
            parts.append(f"by {authors}")
        if year:
            parts.append(f"first published {year}")

        return ", ".join(parts) or "That book result."

    if tool in {"research_arxiv", "research_crossref"}:
        authors = _authors_text(item)
        summary = (
            item.get("summary")
            or item.get("abstract")
            or item.get("description")
            or ""
        )
        parts = []

        if title:
            parts.append(title)
        if authors:
            parts.append(f"by {authors}")
        if summary:
            sentence = _first_sentences(summary, 2, 420)
            if sentence:
                parts.append(sentence)

        return ". ".join(parts).strip(". ") or "That research result."

    if tool == "holiday_lookup":
        date = item.get("date")
        local_name = item.get("local_name")
        name = item.get("name")
        label = local_name or name or "Holiday"
        return f"{label} on {date}." if date else label

    if tool == "weather_alerts":
        event = item.get("event") or item.get("headline") or "Weather alert"
        area = item.get("area_desc")
        severity = item.get("severity")
        parts = [str(event).strip()]
        if severity:
            parts.append(f"({severity})")
        if area:
            parts.append(f"for {area}")
        return " ".join(parts).strip()

    if tool == "earthquake_search":
        place = item.get("place") or item.get("title") or "Earthquake"
        magnitude = item.get("magnitude")
        if magnitude is not None:
            return f"{place}, magnitude {magnitude}."
        return str(place)

    # Generic product/result item.
    parts = []
    if title:
        parts.append(title)

    for key, label in (
        ("price", "price"),
        ("rating", "rating"),
        ("source", "source"),
        ("retailer", "retailer"),
    ):
        value = item.get(key)
        if value is not None and value != "":
            parts.append(f"{label}: {value}")

    summary = (
        item.get("summary")
        or item.get("description")
        or item.get("details")
        or item.get("reason")
        or ""
    )
    if summary:
        parts.append(_first_sentences(summary, 1, 320))

    return ". ".join(parts).strip(". ") or "That result."


def _first_sentences(value: Any, count: int = 2, limit: int = 600) -> str:
    text = " ".join(str(value or "").split())
    if not text:
        return ""

    sentences = re.split(r"(?<=[.!?])\s+", text)
    selected = []

    for sentence in sentences:
        if not sentence:
            continue
        selected.append(sentence)
        if len(selected) >= count:
            break

    result = " ".join(selected).strip()

    if len(result) <= limit:
        return result

    shortened = result[:limit].rsplit(" ", 1)[0]
    return shortened.rstrip(" ,;:") + "..."


def _ordinal_index(text: str) -> Optional[int]:
    match = re.search(
        r"\b(first|1st|second|2nd|third|3rd|fourth|4th|fifth|5th|"
        r"sixth|6th|seventh|7th|eighth|8th|ninth|9th|tenth|10th|last|final)\b",
        text,
        re.IGNORECASE,
    )

    if not match:
        return None

    token = match.group(1).lower()
    return _ORDINALS.get(token)


def _looks_like_result_reference(text: str) -> bool:
    if any(re.search(pattern, text, re.IGNORECASE) for pattern in _MORE_PATTERNS):
        return True

    if any(re.search(pattern, text, re.IGNORECASE) for pattern in _SOURCE_PATTERNS):
        return True

    index = _ordinal_index(text)
    if index is None:
        return False

    return (
        any(word in text for word in _REFERENCE_WORDS)
        or text.startswith(
            (
                "what was",
                "what is",
                "what about",
                "tell me about",
                "show me",
                "give me",
                "which one",
            )
        )
    )


def _source_for(item: Any, context: Dict[str, Any]) -> str:
    candidates = []

    if isinstance(item, dict):
        candidates.extend(
            item.get(key)
            for key in (
                "url",
                "link",
                "source_url",
                "result_url",
                "page_url",
            )
        )

    data = _result_data(context)
    if isinstance(data, dict):
        candidates.extend(
            data.get(key)
            for key in (
                "url",
                "source",
                "source_url",
            )
        )

    for value in candidates:
        if value:
            return str(value).strip()

    return ""


def _knowledge_more(context: Dict[str, Any]) -> Optional[str]:
    data = _result_data(context)

    if not isinstance(data, dict):
        return None

    summary = (
        data.get("summary")
        or data.get("extract")
        or data.get("description")
        or ""
    )

    if not summary:
        return None

    title = str(data.get("title") or "").strip()
    detail = _first_sentences(summary, 3, 650)

    if title:
        return f"{title}: {detail}"

    return detail


def _general_more(item: Any, context: Dict[str, Any]) -> Optional[str]:
    if isinstance(item, dict):
        title = _display_name(item, str(context.get("last_tool") or ""))

        text = (
            item.get("summary")
            or item.get("abstract")
            or item.get("description")
            or item.get("details")
            or item.get("reason")
            or item.get("review_summary")
            or ""
        )

        if text:
            prefix = f"{title}: " if title else ""
            return prefix + _first_sentences(text, 3, 650)

        if title:
            return _compact_item_details(
                item,
                str(context.get("last_tool") or ""),
            )

    return None


def compact_context_description(context: Dict[str, Any]) -> str:
    """Create a small planner-safe description of structured result context."""
    data = _result_data(context)
    tool = str(context.get("last_tool") or "").strip()

    if data is None:
        return ""

    lines = [
        f"Result tool: {tool or 'unknown'}"
    ]

    items = _items_for(context)

    if items:
        lines.append(f"Result count available: {len(items)}")
        for index, item in enumerate(items[:5], start=1):
            name = _display_name(item, tool)
            if name:
                lines.append(f"Result {index}: {name}")
        return "\n".join(lines)

    if isinstance(data, dict):
        title = data.get("title")
        if title:
            lines.append(f"Result title: {title}")

        summary = (
            data.get("summary")
            or data.get("description")
            or ""
        )
        if summary:
            lines.append(
                "Result summary: "
                + _first_sentences(summary, 2, 450)
            )

    return "\n".join(lines)


def resolve_result_followup(
    user_input: str,
    active_context: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """Resolve an unambiguous follow-up against the stored structured result."""
    text = _normalize(user_input)
    if not text:
        return None

    if not active_context or active_context.get("last_result_data") is None:
        return None

    # Browser/action commands must continue through the existing
    # browser context resolver instead of being answered as metadata.
    if text.startswith(
        (
            "open ",
            "click ",
            "play ",
            "select ",
            "choose ",
            "pick ",
        )
    ):
        return None

    data = _result_data(active_context)
    tool = str(active_context.get("last_tool") or "").strip()
    items = _items_for(active_context)

    if not data:
        return None

    # --------------------------------------------------------
    # Source requests
    # --------------------------------------------------------
    if any(
        re.match(pattern, text, re.IGNORECASE)
        for pattern in _SOURCE_PATTERNS
    ):
        selected = active_context.get("last_selected_result")
        source = _source_for(selected or data, active_context)

        if source:
            return {
                "reply": f"The source is {source}.",
                "index": active_context.get("last_result_index"),
                "selected": selected,
                "kind": "source",
            }

        return None

    # --------------------------------------------------------
    # Explicit result ordinal
    # --------------------------------------------------------
    index = _ordinal_index(text)

    if index is not None and _looks_like_result_reference(text):
        if items:
            if index == -1:
                actual_index = len(items) - 1
            else:
                actual_index = index

            if actual_index < 0 or actual_index >= len(items):
                return {
                    "reply": (
                        f"I only have {len(items)} results available."
                    ),
                    "index": None,
                    "selected": None,
                    "kind": "result_reference",
                }

            selected = items[actual_index]
            detail = _compact_item_details(selected, tool)

            return {
                "reply": detail + ("." if not detail.endswith((".", "!", "?")) else ""),
                "index": actual_index,
                "selected": selected,
                "kind": "result_reference",
            }

    # --------------------------------------------------------
    # "Tell me more" / expansion
    # --------------------------------------------------------
    if any(
        re.match(pattern, text, re.IGNORECASE)
        for pattern in _MORE_PATTERNS
    ):
        selected = active_context.get("last_selected_result")

        if selected is not None:
            detail = _general_more(selected, active_context)
            if detail:
                return {
                    "reply": detail,
                    "index": active_context.get("last_result_index"),
                    "selected": selected,
                    "kind": "selected_result",
                }

        if tool == "knowledge_lookup":
            detail = _knowledge_more(active_context)
            if detail:
                return {
                    "reply": detail,
                    "index": None,
                    "selected": data,
                    "kind": "knowledge_expansion",
                }

        if items:
            first = items[0]
            detail = _general_more(first, active_context)
            if detail:
                return {
                    "reply": detail,
                    "index": 0,
                    "selected": first,
                    "kind": "result_expansion",
                }

        return None

    return None
