"""Learned-strategy selection and bounded outcome recording for JARVIS."""

from __future__ import annotations

import time
from typing import Any

import config
from plan_memory import (
    detect_domain,
    find_strategies,
    quarantine_strategy,
    record_strategy,
    strategy_status,
)
from regression_detector import detect_strategy_regression
from task_trace import record_trace, trace_status


def _tool_penalty(plan: dict[str, Any], tool_health: dict[str, Any]) -> float:
    degraded = {
        str(item.get("tool", "")): item
        for item in tool_health.get("degraded_tools", [])
        if isinstance(item, dict)
    }
    penalty = 0.0
    for step in plan.get("steps", []) if isinstance(plan, dict) else []:
        if not isinstance(step, dict):
            continue
        item = degraded.get(str(step.get("tool", "") or "").strip())
        if not item:
            continue
        penalty += min(
            30.0,
            float(item.get("failures", 0) or 0) * 3.0
            + (20.0 if item.get("circuit_open") else 0.0),
        )
    return penalty


def rank_strategy(
    request: str,
    strategy: dict[str, Any],
    *,
    tool_health: dict[str, Any] | None = None,
) -> float:
    tool_health = tool_health if isinstance(tool_health, dict) else {}
    score = (
        float(strategy.get("similarity", 0.0) or 0.0) * 60.0
        + float(strategy.get("success_rate", 0.0) or 0.0) * 25.0
        + float(strategy.get("verified_rate", 0.0) or 0.0) * 15.0
    )
    score += 8.0 if strategy.get("trusted") else 0.0
    score -= min(12.0, float(strategy.get("avg_replans", 0.0) or 0.0) * 3.0)
    score -= _tool_penalty(
        {"steps": strategy.get("steps", [])},
        tool_health,
    )
    if float(strategy.get("quarantined_until", 0.0) or 0.0) > time.time():
        score -= 1000.0
    return round(score, 3)


def strategy_hints(
    request: str,
    context: dict[str, Any] | None = None,
    limit: int = 3,
) -> list[str]:
    context = context if isinstance(context, dict) else {}
    candidates = find_strategies(
        request,
        domain=detect_domain(request, context),
        limit=max(1, int(limit)),
    )
    try:
        from resilience_kernel import tool_health_status
        health = tool_health_status(limit=10)
    except Exception:
        health = {}

    ranked = sorted(
        candidates,
        key=lambda item: rank_strategy(request, item, tool_health=health),
        reverse=True,
    )

    hints = []
    for item in ranked[: max(1, int(limit))]:
        tools = " → ".join(
            str(step.get("tool", "") or "")
            for step in item.get("steps", [])
            if isinstance(step, dict) and step.get("tool")
        )
        if not tools:
            continue
        hints.append(
            f"Known strategy: {tools}; success={item.get('success_rate', 0):.2f}, "
            f"verified={item.get('verified_rate', 0):.2f}, "
            f"uses={item.get('total_attempts', 0)}, "
            "prefer only when current context still matches."
        )
    return hints


def select_learned_plan(
    request: str,
    *,
    context: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    if not getattr(config, "AUTONOMY_LEARNED_STRATEGY_ENABLED", True):
        return None

    context = context if isinstance(context, dict) else {}
    candidates = find_strategies(
        request,
        domain=detect_domain(request, context),
        limit=8,
    )
    if not candidates:
        return None

    try:
        from resilience_kernel import tool_health_status
        health = tool_health_status(limit=12)
    except Exception:
        health = {}

    candidates = [
        item
        for item in candidates
        if item.get("trusted")
        and float(item.get("similarity", 0.0) or 0.0) >= 0.55
    ]

    if not candidates:
        return None

    ranked = sorted(
        candidates,
        key=lambda item: rank_strategy(request, item, tool_health=health),
        reverse=True,
    )
    selected = ranked[0]

    return {
        "goal": f"reuse learned strategy for {request}",
        "learned_strategy": True,
        "strategy_fingerprint": selected["fingerprint"],
        "strategy_score": rank_strategy(request, selected, tool_health=health),
        "steps": [
            {
                "tool": str(step.get("tool", "") or "").strip(),
                "argument": str(step.get("argument", "") or ""),
            }
            for step in selected.get("steps", [])
            if isinstance(step, dict) and step.get("tool")
        ],
    }


def record_task_outcome(task: Any) -> dict[str, Any]:
    """Record one task trace and update the learned strategy aggregate."""
    if task is None:
        return {"recorded": False}

    started = float(getattr(task, "started_at", 0.0) or getattr(task, "created_at", time.time()))
    finished = float(getattr(task, "completed_at", 0.0) or time.time())
    plan = getattr(task, "planner_result", None)
    evidence = list(getattr(task, "evidence", []) or [])
    status = str(getattr(task, "status", "") or "").lower()
    success = status == "completed"
    verified = success and any(
        isinstance(item, dict) and item.get("success") and item.get("verified")
        for item in evidence
    )

    steps = []
    for step in getattr(task, "steps", []) or []:
        steps.append(
            {
                "tool": getattr(step, "tool", ""),
                "status": getattr(step, "status", ""),
                "attempts": getattr(step, "attempts", 0),
                "verified": getattr(step, "verified", False),
                "error": getattr(step, "error", ""),
            }
        )

    trace_result = record_trace(
        task_id=str(getattr(task, "task_id", "") or ""),
        request=str(getattr(task, "request", "") or ""),
        goal=str(getattr(task, "goal", "") or ""),
        status=status,
        verified=verified,
        duration_seconds=max(0.0, finished - started),
        replans=int(getattr(task, "replan_count", 0) or 0),
        error=str(getattr(task, "error", "") or ""),
        verification_reason=(
            "At least one step produced verified evidence."
            if verified
            else "No verified step evidence."
        ),
        plan=plan if isinstance(plan, dict) else {},
        steps=steps,
    )

    strategy_result = {}
    if isinstance(plan, dict) and plan.get("steps"):
        strategy_result = record_strategy(
            str(getattr(task, "request", "") or ""),
            plan,
            success=success,
            verified=verified,
            duration_seconds=max(0.0, finished - started),
            replans=int(getattr(task, "replan_count", 0) or 0),
            error=str(getattr(task, "error", "") or ""),
            context=(
                getattr(task, "active_context", {})
                if isinstance(getattr(task, "active_context", {}), dict)
                else {}
            ),
        )

    regression = None
    quarantine = False
    fingerprint = strategy_result.get("fingerprint")
    if fingerprint and not success:
        from plan_memory import get_strategy

        strategy = get_strategy(fingerprint)
        if strategy:
            regression = detect_strategy_regression(strategy)
            if regression.get("regressed"):
                quarantine = quarantine_strategy(
                    fingerprint,
                    seconds=3600,
                    reason=str(regression.get("reason", "")),
                )

    return {
        "recorded": bool(trace_result.get("recorded") or strategy_result.get("recorded")),
        "trace": trace_result,
        "strategy": strategy_result,
        "regression": regression,
        "quarantined": quarantine,
    }


def autonomy_status() -> dict[str, Any]:
    return {
        "enabled": bool(getattr(config, "AUTONOMY_LEARNED_STRATEGY_ENABLED", True)),
        "trace": trace_status(),
        "strategy": strategy_status(),
    }


__all__ = [
    "autonomy_status",
    "rank_strategy",
    "record_task_outcome",
    "select_learned_plan",
    "strategy_hints",
]