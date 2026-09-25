"""Bounded self-healing policy for JARVIS.

The Healing Kernel formalizes runtime failure detection, diagnosis, recovery
selection, and a local replay journal. It deliberately does not bypass the
existing checkpoint -> edit -> test -> diff-validation workflow for source
changes.
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping, Optional

import config
from logger import logger


_MEMORY_DIR = Path(getattr(config, "BASE_DIR", Path("."))) / ".jarvis_autonomy"
_JOURNAL_PATH = _MEMORY_DIR / "healing_events.jsonl"
_MAX_JOURNAL_EVENTS = 750
_MAX_TEXT = 1200
_MAX_ARGUMENT = 800
_LOCK = threading.RLock()

_SECRET_PATTERNS = (
    (
        re.compile(
            r"(?i)(authorization|api[_ -]?key|token|password|secret)"
            r"\s*[=:]\s*(?:bearer\s+)?[^\s,;]+"
        ),
        r"\1=<redacted>",
    ),
    (
        re.compile(r"(?i)bearer\s+[A-Za-z0-9._~+/=-]+"),
        "Bearer <redacted>",
    ),
)


@dataclass(frozen=True)
class FailureDiagnosis:
    """Deterministic classification of one failed execution."""

    category: str
    retryable: bool
    recoverable: bool
    escalate_to_agent: bool
    confidence: float
    reason: str
    signature: str


@dataclass(frozen=True)
class HealingDecision:
    """What the local recovery layer should do next."""

    action: str
    reason: str
    use_model: bool = False


def _clean(value: Any, limit: int = _MAX_TEXT) -> str:
    text = " ".join(str(value or "").strip().split())
    return text[:limit]


def redact_sensitive(value: Any, limit: int = _MAX_TEXT) -> str:
    """Return bounded failure text with common credential patterns redacted."""
    text = _clean(value, limit)
    for pattern, replacement in _SECRET_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def _signature(tool_name: str, error: str, category: str) -> str:
    payload = "|".join(
        (
            _clean(tool_name, 120).lower(),
            _clean(category, 80).lower(),
            redact_sensitive(error, 700).lower(),
        )
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def diagnose_failure(
    tool_name: str,
    error: Any,
    *,
    argument: Any = "",
    result: Any = None,
) -> FailureDiagnosis:
    """Classify a failure before invoking an LLM recovery strategy."""
    tool = _clean(tool_name, 120).lower()
    error_text = redact_sensitive(error, 1200)
    combined = f"{tool} {error_text} {_clean(argument, 700)}".lower()

    if any(
        marker in combined
        for marker in (
            "timed out",
            "timeout",
            "connection reset",
            "connection refused",
            "server disconnected",
            "temporarily unavailable",
            "502",
            "503",
            "504",
            "broken pipe",
        )
    ):
        category = "transient_transport"
        retryable = True
        recoverable = True
        escalate = False
        confidence = 0.97
        reason = "The failure looks transient and transport-related."

    elif any(
        marker in combined
        for marker in (
            "no such file",
            "file not found",
            "path does not exist",
            "module not found",
            "cannot import",
            "importerror",
            "filenotfounderror",
        )
    ):
        category = "missing_target"
        retryable = False
        recoverable = True
        escalate = True
        confidence = 0.94
        reason = "The requested runtime target is missing or moved."

    elif any(
        marker in combined
        for marker in (
            "no such element",
            "element not found",
            "locator",
            "selector",
            "target element",
            "stale element",
            "browser click",
        )
    ):
        category = "browser_drift"
        retryable = True
        recoverable = True
        escalate = True
        confidence = 0.91
        reason = "The browser target may have changed or drifted."

    elif tool in {"code_test", "code_diagnose", "dev_command"} and any(
        marker in combined
        for marker in (
            "assertionerror",
            "test failed",
            "failed: ",
            "syntaxerror",
            "traceback",
            "typeerror",
            "nameerror",
            "attributeerror",
            "importerror",
        )
    ):
        category = "code_regression"
        retryable = False
        recoverable = True
        escalate = True
        confidence = 0.96
        reason = "Validation exposed a likely software defect."

    elif any(
        marker in combined
        for marker in (
            "syntaxerror",
            "nameerror",
            "typeerror",
            "attributeerror",
            "invalid syntax",
            "indentationerror",
        )
    ):
        category = "runtime_code_defect"
        retryable = False
        recoverable = True
        escalate = True
        confidence = 0.93
        reason = "The runtime failure looks like a code defect."

    elif any(
        marker in combined
        for marker in (
            "permission denied",
            "access is denied",
            "operation not permitted",
            "readonly",
            "read-only",
        )
    ):
        category = "environment_permission"
        retryable = False
        recoverable = False
        escalate = True
        confidence = 0.95
        reason = "The failure is caused by an environment or permission boundary."

    elif any(
        marker in combined
        for marker in (
            "invalid argument",
            "bad argument",
            "required",
            "must be provided",
            "unsupported argument",
            "malformed",
        )
    ):
        category = "invalid_argument"
        retryable = False
        recoverable = True
        escalate = False
        confidence = 0.82
        reason = "The supplied tool argument may be malformed or incomplete."

    else:
        category = "unknown"
        retryable = False
        recoverable = True
        escalate = True
        confidence = 0.55
        reason = "The failure does not match a trusted deterministic category."

    return FailureDiagnosis(
        category=category,
        retryable=retryable,
        recoverable=recoverable,
        escalate_to_agent=escalate,
        confidence=confidence,
        reason=reason,
        signature=_signature(tool, error_text, category),
    )


def choose_recovery(
    diagnosis: FailureDiagnosis,
    *,
    attempt: int,
    max_attempts: int,
    model_available: bool = True,
) -> HealingDecision:
    """Select a bounded recovery action using diagnosis rather than guessing."""
    attempt = max(1, int(attempt))
    max_attempts = max(1, int(max_attempts))

    if attempt >= max_attempts:
        return HealingDecision(
            action="escalate" if diagnosis.escalate_to_agent else "stop",
            reason="The local recovery budget is exhausted.",
        )

    if diagnosis.category == "transient_transport":
        return HealingDecision(
            action="retry",
            reason="Retry the same operation before spending model time.",
        )

    if diagnosis.category in {"browser_drift", "missing_target"}:
        return HealingDecision(
            action="replan",
            reason=diagnosis.reason,
        )

    if diagnosis.category in {"code_regression", "runtime_code_defect"}:
        return HealingDecision(
            action="repair_code",
            reason=(
                "Escalate to the existing bounded source-repair workflow "
                "with checkpoint, focused test, and diff validation."
            ),
        )

    if diagnosis.category == "invalid_argument" and model_available:
        return HealingDecision(
            action="repair_argument",
            reason="Ask the recovery model for a corrected tool argument.",
            use_model=True,
        )

    if diagnosis.recoverable and model_available:
        return HealingDecision(
            action="replan",
            reason="Escalate the failure with structured evidence to Agent Core.",
        )

    return HealingDecision(
        action="stop",
        reason=diagnosis.reason,
    )


def build_healing_evidence(
    tool_name: str,
    argument: Any,
    error: Any,
    diagnosis: FailureDiagnosis,
    *,
    attempt: int,
    result: Any = None,
) -> dict[str, Any]:
    """Create a bounded, sanitized replay record for planners and diagnostics."""
    return {
        "timestamp": time.time(),
        "tool": _clean(tool_name, 120),
        "argument": redact_sensitive(argument, _MAX_ARGUMENT),
        "error": redact_sensitive(error, _MAX_TEXT),
        "attempt": max(1, int(attempt)),
        "diagnosis": asdict(diagnosis),
        "result_preview": redact_sensitive(result, 1000),
    }


def record_healing_event(event: Mapping[str, Any]) -> None:
    """Append one bounded healing event to local ignored runtime memory."""
    record = dict(event)
    record["timestamp"] = float(record.get("timestamp") or time.time())

    for key in ("tool", "argument", "error", "result_preview", "reason"):
        if key in record:
            record[key] = redact_sensitive(record[key])

    record["tool"] = _clean(record.get("tool", ""), 120)
    record["argument"] = _clean(record.get("argument", ""), _MAX_ARGUMENT)

    with _LOCK:
        try:
            _MEMORY_DIR.mkdir(parents=True, exist_ok=True)
            existing: list[dict[str, Any]] = []
            if _JOURNAL_PATH.exists():
                with _JOURNAL_PATH.open("r", encoding="utf-8") as handle:
                    for line in handle:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            item = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        if isinstance(item, dict):
                            existing.append(item)

            existing.append(record)
            existing = existing[-_MAX_JOURNAL_EVENTS:]

            temp_path = _JOURNAL_PATH.with_suffix(".tmp")
            with temp_path.open("w", encoding="utf-8") as handle:
                for item in existing:
                    handle.write(
                        json.dumps(
                            item,
                            ensure_ascii=True,
                            sort_keys=True,
                        )
                        + "\n"
                    )

            temp_path.replace(_JOURNAL_PATH)
        except OSError as exc:
            logger.debug(f"JARVIS HEALING: journal write skipped: {exc}")


def healing_status() -> dict[str, Any]:
    """Return compact diagnostics for the local self-healing subsystem."""
    with _LOCK:
        count = 0
        if _JOURNAL_PATH.exists():
            try:
                with _JOURNAL_PATH.open("r", encoding="utf-8") as handle:
                    count = sum(1 for line in handle if line.strip())
            except OSError:
                count = 0

    return {
        "enabled": bool(getattr(config, "SELF_HEALING_ENABLED", True)),
        "max_attempts": int(
            getattr(config, "SELF_HEALING_MAX_ATTEMPTS", 2)
        ),
        "journal": str(_JOURNAL_PATH),
        "events": min(count, _MAX_JOURNAL_EVENTS),
        "source_mutation_requires_bounded_agent_flow": True,
        "runtime_code_repair_bridge": bool(
            getattr(config, "SELF_HEALING_ENABLED", True)
        ),
    }


__all__ = [
    "FailureDiagnosis",
    "HealingDecision",
    "build_healing_evidence",
    "choose_recovery",
    "diagnose_failure",
    "healing_status",
    "record_healing_event",
    "redact_sensitive",
]
