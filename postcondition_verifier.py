"""Postcondition checks for JARVIS Autonomy Kernel v2."""

from __future__ import annotations

from typing import Any, Dict, Iterable, Optional

from intent_resolver import needs_evidence_answer


_GENERIC_COMPLETION_TEXT = {
    "",
    "done",
    "tool completed.",
    "browser action completed.",
    "google search complete.",
    "search complete.",
}


def _is_truthy_success(evidence: Dict[str, Any]) -> bool:
    return (
        bool(evidence.get("success"))
        and bool(evidence.get("verified"))
    )


def _meaningful(value: Any) -> bool:
    if value is None:
        return False

    if isinstance(value, str):
        text = value.strip().lower()
        return bool(text) and text not in _GENERIC_COMPLETION_TEXT

    if isinstance(value, dict):
        if not value:
            return False
        ignored = {
            "success",
            "verified",
            "retryable",
            "tool",
            "message",
            "error",
        }
        return any(
            _meaningful(v)
            for key, v in value.items()
            if key not in ignored
        )

    if isinstance(value, (list, tuple, set)):
        return any(_meaningful(v) for v in value)

    return True


def _evidence_for_task(task: Any) -> Iterable[Dict[str, Any]]:
    for item in getattr(task, "evidence", []) or []:
        if isinstance(item, dict) and _is_truthy_success(item):
            yield item


def verify_postcondition(
    request: str,
    task: Any,
    active_context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Check whether the completed task has enough real evidence for its user-facing goal."""
    requires_answer = needs_evidence_answer(
        request,
        plan=getattr(task, "planner_result", None),
        active_context=active_context,
    )

    if not requires_answer:
        return {
            "ready": True,
            "requires_answer": False,
            "reason": "Action task does not require an evidence-based narrative.",
            "evidence_count": 0,
        }

    evidence = list(_evidence_for_task(task))

    if not evidence:
        return {
            "ready": False,
            "requires_answer": True,
            "reason": "No verified evidence was captured for an information request.",
            "evidence_count": 0,
        }

    useful = 0
    for item in evidence:
        detail = item.get("detail")
        data = item.get("data")

        if _meaningful(detail) or _meaningful(data):
            useful += 1

    if useful == 0:
        return {
            "ready": False,
            "requires_answer": True,
            "reason": "Tools succeeded, but no meaningful evidence is available to explain the result.",
            "evidence_count": len(evidence),
        }

    return {
        "ready": True,
        "requires_answer": True,
        "reason": "Verified evidence is available for an answer.",
        "evidence_count": len(evidence),
    }
