"""Autonomy Kernel v3: evidence, scope, recovery, regression and repair ledgers.

This module sits beside the existing Healing Kernel and Resilience Kernel. It
does not mutate source code itself. It makes repair decisions safer by
requiring bounded evidence, explicit mutation scope, targeted verification,
and durable outcome records.
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping


_LOCK = threading.RLock()
_MAX_TEXT = 1200
_MAX_PATHS = 24
_MUTATION_TOOLS = {"edit_file", "write_file", "delete_file", "rename_file", "move_file"}
_VERIFY_TOOLS = {"code_test", "code_diagnose", "verify_screen", "tool_health", "integration_health"}
_CHECKPOINT_TOOLS = {"code_checkpoint", "code_restore_checkpoint"}

_TEST_MAP = {
    "commands.py": ("tests/test_commands.py", "tests/test_natural_action_routing.py"),
    "planner.py": ("tests/test_agent_planning.py", "tests/test_planner_fast_path.py"),
    "smart_router.py": ("tests/test_smart_router.py",),
    "browser_controller.py": (
        "tests/test_browser_agent.py",
        "tests/test_browser_fast_routes.py",
        "tests/test_browser_dom_integration.py",
    ),
    "browser_agent.py": ("tests/test_browser_agent.py", "tests/test_agent_browser_setup.py"),
    "browser_agent_worker.py": ("tests/test_browser_agent.py", "tests/test_agent_browser_setup.py"),
    "tool_registry.py": ("tests/test_tool_contract.py",),
    "tool_executor.py": ("tests/test_tool_executor.py", "tests/test_agent_core.py"),
    "agent_core.py": (
        "tests/test_agent_core.py",
        "tests/test_autonomy_hardening.py",
        "tests/test_self_repair_entry.py",
    ),
    "healing_kernel.py": ("tests/test_autonomy_hardening.py",),
    "resilience_kernel.py": ("tests/test_autonomy_hardening.py",),
    "integration_health.py": ("tests/test_integration_health.py",),
}


@dataclass(frozen=True)
class AutonomyFailure:
    category: str
    retryable: bool
    recoverable: bool
    confidence: float
    signature: str
    reason: str
    evidence: dict[str, Any]


@dataclass(frozen=True)
class RecoveryPlan:
    action: str
    reason: str
    retry_same_step: bool = False
    restore_checkpoint: bool = False
    replan: bool = False
    targeted_tests: tuple[str, ...] = ()


def _clean(value: Any, limit: int = _MAX_TEXT) -> str:
    try:
        from healing_kernel import redact_sensitive

        return redact_sensitive(value, limit)
    except Exception:
        text = " ".join(str(value or "").strip().split())
        return text[:limit]


def _signature(tool: str, category: str, error: Any) -> str:
    raw = "|".join((_clean(tool, 120).lower(), category.lower(), _clean(error, 700).lower()))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def classify_failure(tool: str, error: Any, *, argument: Any = "", result: Any = None) -> AutonomyFailure:
    """Classify failures with more operational categories than the base kernel."""
    text = f"{tool} {error} {argument} {result}".lower()

    patterns = [
        ("tool_contract", ("unknown tool", "tool contract", "not registered", "unsupported tool", "invalid tool"), False, True, 0.98),
        ("dependency_missing", ("module not found", "cannot import", "npm is not installed", "executable not found", "ffmpeg was not detected"), False, True, 0.96),
        ("integration_offline", ("connection refused", "offline", "unreachable", "server disconnected", "plugin not connected"), True, True, 0.93),
        ("permission_boundary", ("permission denied", "access is denied", "operation not permitted", "read-only"), False, False, 0.97),
        ("scope_mismatch", ("wrong file", "unexpected file", "target mismatch", "outside project", "path traversal"), False, True, 0.99),
        ("validation_failure", ("assertionerror", "test failed", "pytest", "syntaxerror", "typeerror", "nameerror", "attributeerror"), False, True, 0.98),
        ("browser_drift", ("locator", "selector", "no such element", "stale element", "browser click"), True, True, 0.92),
        ("transient_transport", ("timeout", "timed out", "502", "503", "504", "connection reset", "broken pipe"), True, True, 0.97),
    ]

    category = "unknown"
    retryable = False
    recoverable = True
    confidence = 0.55
    reason = "Failure did not match a trusted autonomy category."

    for candidate, markers, can_retry, can_recover, score in patterns:
        if any(marker in text for marker in markers):
            category = candidate
            retryable = can_retry
            recoverable = can_recover
            confidence = score
            reason = {
                "tool_contract": "Tool registration or contract drift was detected.",
                "dependency_missing": "A runtime dependency or executable is missing.",
                "integration_offline": "An integration appears offline or unreachable.",
                "permission_boundary": "The environment denied the requested operation.",
                "scope_mismatch": "The attempted mutation does not match the verified task scope.",
                "validation_failure": "Validation or tests exposed a likely regression.",
                "browser_drift": "The browser target may have changed.",
                "transient_transport": "The failure looks transient and transport-related.",
            }[candidate]
            break

    return AutonomyFailure(
        category=category,
        retryable=retryable,
        recoverable=recoverable,
        confidence=confidence,
        signature=_signature(tool, category, error),
        reason=reason,
        evidence={
            "tool": _clean(tool, 120),
            "error": _clean(error),
            "argument": _clean(argument, 800),
            "result_preview": _clean(result, 700),
        },
    )


def extract_paths(value: Any) -> list[str]:
    """Extract likely repository-relative file paths from a request/plan."""
    text = _clean(value, 5000)
    candidates = re.findall(
        r"(?<![A-Za-z0-9_])(?:[A-Za-z0-9_.-]+/)*[A-Za-z0-9_.-]+\.(?:py|toml|yaml|yml|json|md|txt|ps1|bat)(?![A-Za-z0-9_])",
        text,
        re.IGNORECASE,
    )
    unique = []
    seen = set()
    for item in candidates:
        normalized = item.replace("\\", "/").lstrip("./")
        if normalized and normalized not in seen:
            seen.add(normalized)
            unique.append(normalized)
    return unique[:_MAX_PATHS]


def _plan_steps(plan: Mapping[str, Any] | None) -> list[Mapping[str, Any]]:
    steps = plan.get("steps", []) if isinstance(plan, Mapping) else []
    return [step for step in steps if isinstance(step, Mapping)]


def mutation_paths(plan: Mapping[str, Any] | None) -> list[str]:
    paths = []
    for step in _plan_steps(plan):
        tool = str(step.get("tool", "") or "").strip()
        if tool not in _MUTATION_TOOLS:
            continue
        paths.extend(extract_paths(step.get("argument", "")))
    unique = []
    seen = set()
    for path in paths:
        if path not in seen:
            seen.add(path)
            unique.append(path)
    return unique[:_MAX_PATHS]


def assess_scope(request: str, plan: Mapping[str, Any] | None) -> dict[str, Any]:
    """Check mutation scope without silently rewriting a model plan."""
    requested = set(extract_paths(request))
    mutated = set(mutation_paths(plan))
    violations: list[str] = []

    if requested and mutated:
        unexpected = sorted(mutated - requested)
        multi_file_language = any(
            phrase in request.lower()
            for phrase in ("multiple files", "across the project", "update the tests", "update tests", "refactor")
        )
        if unexpected and not multi_file_language:
            violations.extend(unexpected)

    absolute_or_escape = [
        path
        for path in mutated
        if path.startswith(("/", "\\"))
        or re.match(r"^[A-Za-z]:", path)
        or ".." in Path(path).parts
    ]
    violations.extend(absolute_or_escape)

    return {
        "allowed": not violations,
        "requested_targets": sorted(requested),
        "mutation_targets": sorted(mutated),
        "unexpected_targets": sorted(set(violations)),
        "confidence": 0.99 if not violations else 0.12,
        "reason": (
            "Mutation targets are consistent with the requested scope."
            if not violations
            else "Mutation plan contains targets outside the verified request scope."
        ),
    }


def plan_confidence(request: str, plan: Mapping[str, Any] | None, evidence: Iterable[Mapping[str, Any]] = ()) -> dict[str, Any]:
    """Score whether a mutation plan has enough evidence to execute."""
    steps = _plan_steps(plan)
    tools = [str(step.get("tool", "") or "") for step in steps]
    score = 0.40
    reasons = []

    if any(tool in _CHECKPOINT_TOOLS for tool in tools):
        score += 0.10
        reasons.append("checkpoint")
    if any(tool == "read_file" for tool in tools):
        score += 0.15
        reasons.append("source-read")
    if any(tool in _VERIFY_TOOLS for tool in tools):
        score += 0.15
        reasons.append("verification")
    if any(tool in _MUTATION_TOOLS for tool in tools):
        score += 0.05
    if not tools:
        score -= 0.20
        reasons.append("empty-plan")

    scope = assess_scope(request, plan)
    if not scope["allowed"]:
        score = min(score, 0.20)
        reasons.append("scope-mismatch")

    verified_evidence = sum(1 for item in evidence if isinstance(item, Mapping) and item.get("success") and item.get("verified"))
    if verified_evidence:
        score += min(0.10, 0.02 * verified_evidence)
        reasons.append("prior-evidence")

    score = round(max(0.0, min(1.0, score)), 3)
    return {
        "confidence": score,
        "minimum": 0.62,
        "allowed": score >= 0.62 and bool(scope["allowed"]),
        "reasons": reasons,
        "scope": scope,
    }


def targeted_test_paths(changed_paths: Iterable[str], request: str = "") -> list[str]:
    """Select a small deterministic pytest set from changed files."""
    paths = [str(item).replace("\\", "/").lstrip("./") for item in changed_paths if str(item).strip()]
    selected: list[str] = []

    for path in paths:
        key = Path(path).name.lower()
        for test in _TEST_MAP.get(key, ()):
            if test not in selected:
                selected.append(test)

    request_lower = request.lower()
    if "browser agent" in request_lower or "browser use" in request_lower:
        selected.extend(["tests/test_smart_router.py", "tests/test_agent_browser_setup.py"])
    if "self-heal" in request_lower or "self healing" in request_lower or "repair" in request_lower:
        selected.extend(["tests/test_autonomy_hardening.py", "tests/test_self_repair_entry.py"])

    return list(dict.fromkeys(selected))[:12]


def select_recovery(
    failure: AutonomyFailure,
    *,
    attempt: int,
    max_attempts: int,
    changed_paths: Iterable[str] = (),
    request: str = "",
) -> RecoveryPlan:
    """Convert diagnosis into a bounded recovery plan."""
    attempt = max(1, int(attempt))
    max_attempts = max(1, int(max_attempts))
    tests = tuple(targeted_test_paths(changed_paths, request))

    if attempt >= max_attempts:
        return RecoveryPlan(
            action="escalate",
            reason="Autonomy recovery budget exhausted.",
            restore_checkpoint=failure.category in {"validation_failure", "scope_mismatch"},
            replan=failure.recoverable,
            targeted_tests=tests,
        )

    if failure.category == "transient_transport":
        return RecoveryPlan("retry", failure.reason, retry_same_step=True, targeted_tests=tests)
    if failure.category == "browser_drift":
        return RecoveryPlan("reobserve", failure.reason, retry_same_step=True, replan=True, targeted_tests=tests)
    if failure.category in {"validation_failure", "scope_mismatch"}:
        return RecoveryPlan("rollback_repair", failure.reason, restore_checkpoint=True, replan=True, targeted_tests=tests)
    if failure.category in {"tool_contract", "dependency_missing", "integration_offline"}:
        return RecoveryPlan("repair_dependency", failure.reason, replan=True, targeted_tests=tests)
    if failure.category == "permission_boundary":
        return RecoveryPlan("escalate", failure.reason, replan=False, targeted_tests=tests)

    return RecoveryPlan("replan", failure.reason, replan=True, targeted_tests=tests)


def stale_tool_report(snapshot: Mapping[str, Any] | None) -> dict[str, Any]:
    """Identify tools that are repeatedly failing or have become one-sided."""
    suspect = []
    for item in (snapshot or {}).get("historical_failures", []) if isinstance(snapshot, Mapping) else []:
        calls = int(item.get("calls", 0) or 0)
        failures = int(item.get("failures", 0) or 0)
        consecutive = int(item.get("consecutive_failures", 0) or 0)
        rate = float(item.get("success_rate", 1.0) or 0.0)
        if consecutive >= 3 or (calls >= 4 and rate < 0.50) or failures >= 5:
            suspect.append({
                "tool": item.get("tool"),
                "reason": "Repeated runtime failures indicate stale, unavailable, or drifting tool state.",
                "category": item.get("last_category", ""),
                "consecutive_failures": consecutive,
                "success_rate": rate,
            })
    return {"suspect_tools": suspect[:16], "count": len(suspect)}


def record_repair_event(
    event: Mapping[str, Any],
    *,
    kind: str = "recovery",
) -> None:
    """Persist a sanitized repair/recovery outcome for future diagnosis."""
    try:
        import config

        base = Path(getattr(config, "BASE_DIR", Path("."))) / ".jarvis_autonomy"
        base.mkdir(parents=True, exist_ok=True)
        path = base / "repair_ledger.jsonl"
    except Exception:
        return

    record = dict(event)
    record["kind"] = kind
    record["timestamp"] = time.time()
    if "signature" not in record:
        record["signature"] = _signature(
            str(record.get("tool", "")),
            str(record.get("category", "unknown")),
            record.get("error", ""),
        )

    for key in ("tool", "error", "argument", "reason", "message"):
        if key in record:
            record[key] = _clean(record[key])

    line = json.dumps(record, ensure_ascii=True, sort_keys=True)
    with _LOCK:
        try:
            existing = []
            if path.exists():
                with path.open("r", encoding="utf-8") as handle:
                    existing = [item.strip() for item in handle if item.strip()][-499:]
            existing.append(line)
            temp = path.with_suffix(".tmp")
            temp.write_text("\n".join(existing) + "\n", encoding="utf-8")
            temp.replace(path)
        except OSError:
            return


def autonomy_status(snapshot: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Compact public diagnostic for Autonomy Kernel v3."""
    stale = stale_tool_report(snapshot)
    return {
        "version": 3,
        "features": {
            "failure_classification": True,
            "persistent_repair_ledger": True,
            "scope_gate": True,
            "targeted_test_selection": True,
            "planner_confidence_gate": True,
            "stale_tool_detection": True,
        },
        "suspect_tools": stale["count"],
        "targeted_test_catalog": len(_TEST_MAP),
    }


__all__ = [
    "AutonomyFailure",
    "RecoveryPlan",
    "assess_scope",
    "autonomy_status",
    "classify_failure",
    "extract_paths",
    "mutation_paths",
    "plan_confidence",
    "record_repair_event",
    "select_recovery",
    "stale_tool_report",
    "targeted_test_paths",
]
