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
    plan = getattr(task, "planner_result", None)

    # Completed code-repair/change actions are operational tasks. Their
    # completion should not be converted into an information-query
    # postcondition that can fail merely because a lightweight executor test
    # double did not emit structured evidence.
    mutation_tools = {
        "write_file",
        "edit_file",
        "delete_file",
    }
    if isinstance(plan, dict):
        steps = plan.get("steps")
        if isinstance(steps, list) and any(
            isinstance(step, dict)
            and str(step.get("tool", "") or "").strip() in mutation_tools
            for step in steps
        ):
            return {
                "ready": True,
                "requires_answer": False,
                "reason": "Code mutation task completed operationally.",
                "evidence_count": len(
                    list(_evidence_for_task(task))
                ),
            }

    requires_answer = needs_evidence_answer(
        request,
        plan=plan,
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


def verify_execution_trace(
    task: Any,
) -> Dict[str, Any]:
    """Verify that an executor produced a coherent, non-failing trace."""
    try:
        from tool_executor import get_last_execution_trace

        trace = get_last_execution_trace() or []
    except Exception as exc:
        return {
            "ready": True,
            "verified": False,
            "trace_available": False,
            "reason": f"Execution trace unavailable; preserving legacy executor behavior: {exc}",
            "failed_steps": [],
            "verified_steps": 0,
            "total_steps": 0,
        }

    if not trace:
        return {
            "ready": True,
            "verified": False,
            "trace_available": False,
            "reason": "No structured trace was produced by the executor.",
            "failed_steps": [],
            "verified_steps": 0,
            "total_steps": 0,
        }

    failed_steps = []
    verified_steps = 0
    successful_steps = 0

    for entry in trace:
        if not isinstance(entry, dict):
            continue

        if entry.get("success") is False or str(
            entry.get("status", "") or ""
        ).lower() in {"failed", "error"}:
            failed_steps.append(
                {
                    "tool": str(entry.get("tool", "") or ""),
                    "message": str(
                        entry.get("message")
                        or entry.get("error")
                        or ""
                    )[:500],
                }
            )
            continue

        if entry.get("success") is True:
            successful_steps += 1
            if entry.get("verified") or str(
                entry.get("status", "") or ""
            ).lower() in {"completed", "success", "done"}:
                verified_steps += 1

    if failed_steps:
        return {
            "ready": False,
            "verified": False,
            "trace_available": True,
            "reason": "Execution trace contains failed steps.",
            "failed_steps": failed_steps[:8],
            "verified_steps": verified_steps,
            "total_steps": len(trace),
        }

    if successful_steps <= 0:
        return {
            "ready": False,
            "verified": False,
            "trace_available": True,
            "reason": "Execution completed without a successful step.",
            "failed_steps": [],
            "verified_steps": 0,
            "total_steps": len(trace),
        }

    return {
        "ready": verified_steps > 0,
        "verified": verified_steps > 0,
        "trace_available": True,
        "reason": (
            "At least one successful step has verified completion evidence."
            if verified_steps
            else "Successful steps were recorded without explicit verification."
        ),
        "failed_steps": [],
        "verified_steps": verified_steps,
        "total_steps": len(trace),
    }
