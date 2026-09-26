"""Regression detection for learned JARVIS strategies."""

from __future__ import annotations

from typing import Any

from plan_memory import find_strategies, recent_events
from resilience_kernel import tool_health_status


def detect_strategy_regression(
    strategy: dict[str, Any],
    *,
    recent_window: int = 6,
) -> dict[str, Any]:
    fingerprint = str(strategy.get("fingerprint", "") or "")
    events = recent_events(fingerprint, limit=max(3, recent_window))
    if len(events) < 4:
        return {
            "regressed": False,
            "reason": "Not enough history.",
            "fingerprint": fingerprint,
        }

    recent = events[:recent_window]
    recent_successes = sum(1 for item in recent if item.get("success"))
    recent_failures = len(recent) - recent_successes
    recent_success_rate = recent_successes / max(1, len(recent))

    baseline = float(strategy.get("success_rate", 0.0) or 0.0)
    regressed = (
        baseline >= 0.75
        and recent_success_rate < max(0.45, baseline * 0.60)
        and recent_failures >= 3
    )

    reason = (
        "Recent strategy success rate dropped materially below its historical baseline."
        if regressed
        else "No material strategy regression detected."
    )

    return {
        "regressed": regressed,
        "fingerprint": fingerprint,
        "baseline_success_rate": round(baseline, 4),
        "recent_success_rate": round(recent_success_rate, 4),
        "recent_failures": recent_failures,
        "recent_samples": len(recent),
        "reason": reason,
    }


def detect_tool_regressions(limit: int = 8) -> list[dict[str, Any]]:
    health = tool_health_status(limit=max(1, int(limit)))
    regressions = []
    for item in health.get("degraded_tools", []):
        if not isinstance(item, dict):
            continue
        regressed = (
            float(item.get("failures", 0) or 0) >= 3
            and float(item.get("success_rate", 1.0) or 1.0) < 0.75
        )
        if not regressed:
            continue
        regressions.append({
            **item,
            "regressed": True,
        })
    return regressions


def evaluate_request(
    request: str,
    *,
    domain: str = "",
    limit: int = 5,
) -> dict[str, Any]:
    strategies = find_strategies(
        request,
        domain=domain,
        limit=limit,
        include_quarantined=True,
    )
    evaluations = []
    for strategy in strategies:
        evaluation = detect_strategy_regression(strategy)
        evaluations.append(
            {
                "strategy": strategy,
                "regression": evaluation,
            }
        )

    return {
        "request": str(request or "")[:800],
        "strategies": evaluations,
        "tool_regressions": detect_tool_regressions(),
    }


__all__ = [
    "detect_strategy_regression",
    "detect_tool_regressions",
    "evaluate_request",
]