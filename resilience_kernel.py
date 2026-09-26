"""Runtime resilience, tool health, and bounded circuit breaking for JARVIS.

This layer is intentionally dependency-free and sits below Agent Core. It tracks
tool reliability, prevents pathological retry storms, preserves sanitized
failure signatures, and exposes compact health data for planning and diagnostics.
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict

import config
from healing_kernel import diagnose_failure, redact_sensitive


_MEMORY_DIR = Path(getattr(config, "BASE_DIR", Path("."))) / ".jarvis_autonomy"
_HEALTH_PATH = _MEMORY_DIR / "tool_health.json"
_MAX_TOOLS = 128
_MAX_ERROR_CHARS = 500


@dataclass
class ToolHealth:
    tool: str
    calls: int = 0
    successes: int = 0
    failures: int = 0
    consecutive_failures: int = 0
    retryable_failures: int = 0
    last_error: str = ""
    last_category: str = ""
    last_duration_ms: float = 0.0
    last_success_at: float = 0.0
    last_failure_at: float = 0.0
    circuit_open_until: float = 0.0

    @property
    def success_rate(self) -> float:
        if self.calls <= 0:
            return 1.0
        return round(self.successes / self.calls, 4)


class RuntimeResilience:
    """Bounded per-tool reliability state with optional circuit breaking."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._tools: Dict[str, ToolHealth] = {}
        self._load()

    @property
    def enabled(self) -> bool:
        return bool(getattr(config, "TOOL_RESILIENCE_ENABLED", True))

    @property
    def circuit_breaker_enabled(self) -> bool:
        return bool(getattr(config, "TOOL_CIRCUIT_BREAKER_ENABLED", True))

    @property
    def failure_threshold(self) -> int:
        return max(2, int(getattr(config, "TOOL_CIRCUIT_FAILURE_THRESHOLD", 4)))

    @property
    def cooldown_seconds(self) -> float:
        return max(5.0, float(getattr(config, "TOOL_CIRCUIT_COOLDOWN_SECONDS", 20.0)))

    def _load(self) -> None:
        try:
            if not _HEALTH_PATH.exists():
                return
            payload = json.loads(_HEALTH_PATH.read_text(encoding="utf-8"))
            tools = payload.get("tools", {}) if isinstance(payload, dict) else {}
            if not isinstance(tools, dict):
                return
            for tool, raw in list(tools.items())[:_MAX_TOOLS]:
                if not isinstance(raw, dict):
                    continue
                self._tools[str(tool)] = ToolHealth(
                    tool=str(tool),
                    calls=int(raw.get("calls", 0) or 0),
                    successes=int(raw.get("successes", 0) or 0),
                    failures=int(raw.get("failures", 0) or 0),
                    consecutive_failures=int(raw.get("consecutive_failures", 0) or 0),
                    retryable_failures=int(raw.get("retryable_failures", 0) or 0),
                    last_error=redact_sensitive(raw.get("last_error", ""), _MAX_ERROR_CHARS),
                    last_category=str(raw.get("last_category", "") or ""),
                    last_duration_ms=float(raw.get("last_duration_ms", 0.0) or 0.0),
                    last_success_at=float(raw.get("last_success_at", 0.0) or 0.0),
                    last_failure_at=float(raw.get("last_failure_at", 0.0) or 0.0),
                    circuit_open_until=float(raw.get("circuit_open_until", 0.0) or 0.0),
                )
        except Exception:
            self._tools = {}

    def _persist(self) -> None:
        try:
            _MEMORY_DIR.mkdir(parents=True, exist_ok=True)
            payload = {
                "updated_at": time.time(),
                "tools": {
                    key: asdict(value)
                    for key, value in list(self._tools.items())[:_MAX_TOOLS]
                },
            }
            temp = _HEALTH_PATH.with_suffix(".tmp")
            temp.write_text(
                json.dumps(payload, ensure_ascii=True, sort_keys=True),
                encoding="utf-8",
            )
            temp.replace(_HEALTH_PATH)
        except OSError:
            pass

    def before(self, tool: str) -> Dict[str, Any]:
        """Return whether a tool is currently permitted to run."""
        name = str(tool or "").strip()
        if not name or not self.enabled or not self.circuit_breaker_enabled:
            return {"allowed": True, "tool": name}

        now = time.time()
        with self._lock:
            state = self._tools.get(name)
            if state is None or state.circuit_open_until <= now:
                if state is not None and state.circuit_open_until:
                    state.circuit_open_until = 0.0
                return {"allowed": True, "tool": name}

            remaining = round(state.circuit_open_until - now, 1)
            return {
                "allowed": False,
                "tool": name,
                "retry_after": remaining,
                "reason": (
                    f"Tool circuit is open after repeated failures; "
                    f"retry after approximately {remaining:.1f}s."
                ),
            }

    def record(
        self,
        tool: str,
        *,
        success: bool,
        retryable: bool = False,
        error: Any = "",
        duration_ms: float = 0.0,
        argument: Any = "",
    ) -> Dict[str, Any]:
        """Record one normalized tool outcome and return its diagnosis metadata."""
        name = str(tool or "").strip() or "unknown"
        error_text = redact_sensitive(error, _MAX_ERROR_CHARS)

        diagnosis = None
        if not success:
            try:
                diagnosis = diagnose_failure(
                    name,
                    error_text,
                    argument=argument,
                )
            except Exception:
                diagnosis = None

        with self._lock:
            state = self._tools.setdefault(name, ToolHealth(tool=name))
            state.calls += 1
            state.last_duration_ms = round(max(0.0, float(duration_ms)), 2)

            if success:
                state.successes += 1
                state.consecutive_failures = 0
                state.last_success_at = time.time()
                state.circuit_open_until = 0.0
            else:
                state.failures += 1
                state.consecutive_failures += 1
                state.last_failure_at = time.time()
                state.last_error = error_text
                state.last_category = (
                    diagnosis.category if diagnosis is not None else ""
                )
                if retryable:
                    state.retryable_failures += 1

                if (
                    self.enabled
                    and self.circuit_breaker_enabled
                    and state.consecutive_failures >= self.failure_threshold
                ):
                    state.circuit_open_until = (
                        time.time() + self.cooldown_seconds
                    )

            self._persist()

            return {
                "tool": name,
                "success": bool(success),
                "retryable": bool(retryable),
                "category": (
                    diagnosis.category if diagnosis is not None else ""
                ),
                "signature": (
                    diagnosis.signature if diagnosis is not None else ""
                ),
                "consecutive_failures": state.consecutive_failures,
                "circuit_open": bool(
                    state.circuit_open_until > time.time()
                ),
            }

    def snapshot(self, *, limit: int = 20) -> Dict[str, Any]:
        """Return compact tool reliability statistics."""
        now = time.time()
        with self._lock:
            states = list(self._tools.values())

        states.sort(
            key=lambda item: (
                item.failures,
                item.calls,
                item.last_failure_at,
            ),
            reverse=True,
        )

        degraded = []
        historical = []
        for state in states[: max(1, int(limit))]:
            currently_degraded = (
                state.consecutive_failures > 0
                or state.circuit_open_until > now
            )
            record = {
                "tool": state.tool,
                "calls": state.calls,
                "successes": state.successes,
                "failures": state.failures,
                "success_rate": state.success_rate,
                "consecutive_failures": state.consecutive_failures,
                "retryable_failures": state.retryable_failures,
                "last_category": state.last_category,
                "last_error": state.last_error,
                "last_duration_ms": state.last_duration_ms,
                "circuit_open": state.circuit_open_until > now,
                "retry_after": (
                    round(state.circuit_open_until - now, 1)
                    if state.circuit_open_until > now
                    else 0.0
                ),
            }

            if state.failures > 0:
                historical.append(record)

            if not currently_degraded:
                continue
            degraded.append(record)

        return {
            "enabled": self.enabled,
            "circuit_breaker_enabled": self.circuit_breaker_enabled,
            "failure_threshold": self.failure_threshold,
            "cooldown_seconds": self.cooldown_seconds,
            "tool_count": len(states),
            "degraded_tools": degraded,
            "historical_failures": historical,
        }

    def reset_tool(self, tool: str) -> bool:
        name = str(tool or "").strip()
        if not name:
            return False
        with self._lock:
            if name not in self._tools:
                return False
            self._tools[name] = ToolHealth(tool=name)
            self._persist()
            return True


_RESILIENCE = RuntimeResilience()


def get_resilience() -> RuntimeResilience:
    return _RESILIENCE


def resilient_backoff(attempt: int, *, base: float = 0.20, cap: float = 3.0) -> float:
    """Return bounded exponential backoff for retry callers."""
    attempt = max(1, int(attempt))
    return min(float(cap), max(0.0, float(base)) * (2 ** (attempt - 1)))


def tool_health_status(limit: int = 20) -> Dict[str, Any]:
    return _RESILIENCE.snapshot(limit=limit)


__all__ = [
    "RuntimeResilience",
    "ToolHealth",
    "get_resilience",
    "resilient_backoff",
    "tool_health_status",
]
