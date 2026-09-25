"""Small harness-engineering checks derived from the configured JARVIS tool loop.

These are local invariants, not a reimplementation of the upstream awesome list.
They make the planner/executor expose the same guardrails consistently.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List


_MUTATING_HINTS = (
    "create",
    "delete",
    "edit",
    "write",
    "upload",
    "download",
    "install",
    "configure",
    "execute",
    "run",
    "send",
    "publish",
    "spawn",
    "import",
)


def review_plan(steps: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    steps = list(steps or [])
    issues: List[str] = []
    recommendations: List[str] = []
    seen_tools = set()

    for index, step in enumerate(steps, start=1):
        tool = str(step.get("tool") or "").strip()
        seen_tools.add(tool)
        if not tool:
            issues.append(f"Step {index} has no tool name.")
            continue
        argument = str(step.get("argument") or "").lower()
        tool_blob = f"{tool.lower()} {argument}"
        if any(hint in tool_blob for hint in _MUTATING_HINTS):
            if index == len(steps):
                recommendations.append("Mutation is last in the plan; verify the final state explicitly.")
            elif not any(
                token in str(steps[index].get("tool") or "").lower()
                for token in ("verify", "status", "test", "inspect", "extract")
            ):
                recommendations.append(
                    f"Step {index} ({tool}) mutates state; add a verification step when the tool supports one."
                )

    if len(steps) > 12:
        recommendations.append("Long-horizon plan exceeds 12 steps; prefer checkpoints or staged execution.")

    return {
        "success": not issues,
        "step_count": len(steps),
        "tools": sorted(seen_tools),
        "issues": issues,
        "recommendations": recommendations,
    }
