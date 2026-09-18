"""Model-free fast-path capability planning for simple online requests.

This module intentionally contains only deterministic routing. Complex or
computer-state-dependent requests return None so the normal planner/Agent Core
can handle them.
"""

from __future__ import annotations

import re
from typing import Any, Optional


_WEATHER_PREFIXES = (
    "what's the current weather in ",
    "what is the current weather in ",
    "current weather in ",
    "weather in ",
    "weather for ",
    "what's the weather in ",
    "what is the weather in ",
)


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "").strip()).lower()


def _looks_complex(text: str) -> bool:
    separators = (" and ", " then ", " after that ", " next ", ";")
    return any(separator in text for separator in separators)


def _weather_location(text: str) -> Optional[str]:
    original = str(text or "").strip()
    normalized = _normalize(original)

    for prefix in _WEATHER_PREFIXES:
        if normalized.startswith(prefix):
            location = original[len(prefix):].strip()
            location = re.sub(
                r"\s+(?:right now|today|tomorrow|now)\s*[?.!,]*$",
                "",
                location,
                flags=re.IGNORECASE,
            ).strip()
            location = location.rstrip("?.!,").strip()
            return location or None

    return None


def fast_plan_for_request(request: str) -> Optional[dict[str, Any]]:
    """Return a deterministic plan for requests safe to fast-path.

    Supported fast paths:
    - current/latest informational lookups -> web_search
    - current weather in a named location -> weather

    Return None for local computer actions or multi-step requests.
    """
    original = str(request or "").strip()
    normalized = _normalize(original)

    if not normalized or _looks_complex(normalized):
        return None

    # Latest/current release/version questions are online lookups, but
    # leave the exact user wording intact for the web-search tool.
    if (
        ("latest " in normalized or "current " in normalized)
        and any(
            noun in normalized
            for noun in (
                "release",
                "version",
                "news",
                "update",
            )
        )
        and (
            normalized.startswith("what ")
            or normalized.startswith("what's ")
            or normalized.startswith("what is ")
            or normalized.startswith("what are ")
        )
    ):
        return {
            "goal": "online informational lookup",
            "steps": [
                {
                    "tool": "web_search",
                    "argument": original,
                }
            ],
        }

    location = _weather_location(normalized)

    if location:
        return {
            "goal": "check weather",
            "steps": [
                {
                    "tool": "weather",
                    "argument": location,
                }
            ],
        }

    # Requests about the local project/computer must remain in Agent Core.
    local_markers = (
        "current project",
        "project folder",
        "my computer",
        "my pc",
        "my files",
        "this folder",
        "this project",
    )

    if any(marker in normalized for marker in local_markers):
        return None

    return None
