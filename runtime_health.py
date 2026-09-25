"""JARVIS runtime health and subsystem readiness checks.

The health layer is intentionally lightweight: it reports the state of
components that are already loaded and uses short-timeout probes for external
services. It never starts heavyweight subsystems just to answer a status query.
"""

from __future__ import annotations

import sys
import time
from typing import Any, Dict
from urllib.request import Request, urlopen

from config import (
    CHAT_MODEL,
    PLANNER_MODEL,
    CODING_MODEL,
    OLLAMA_HOST,
    VERIFY_MODEL,
    VISION_MODEL,
    WHISPER_MODEL,
)


def _ollama_ready(timeout: float = 0.75) -> bool:
    try:
        request = Request(
            OLLAMA_HOST.rstrip("/") + "/api/tags",
            headers={"User-Agent": "JARVIS/1.0"},
            method="GET",
        )
        with urlopen(request, timeout=timeout):
            return True
    except Exception:
        return False


def _loaded_module(name: str) -> bool:
    return name in sys.modules


def _speech_ready() -> bool:
    module = sys.modules.get("speech")
    return module is not None and getattr(module, "model", None) is not None


def _tts_ready() -> bool:
    module = sys.modules.get("voice")
    if module is None:
        return False
    try:
        status = module.tts_status()
        return bool(status.get("loaded"))
    except Exception:
        return False


def _resilience_summary() -> dict[str, Any]:
    try:
        from resilience_kernel import tool_health_status
        status = tool_health_status(limit=5)
        return {
            "degraded_tools": len(status.get("degraded_tools", [])),
            "circuit_breaker_enabled": bool(
                status.get("circuit_breaker_enabled", False)
            ),
        }
    except Exception:
        return {
            "degraded_tools": 0,
            "circuit_breaker_enabled": False,
        }


def _memory_summary() -> dict[str, Any]:
    try:
        from local_memory import memory_status
        from autonomy_memory import autonomy_memory_status

        semantic = memory_status()
        episodic = autonomy_memory_status()

        return {
            "semantic_records": int(semantic.get("records", 0) or 0),
            "experience_episodes": int(episodic.get("episodes", 0) or 0),
            "experience_failures": int(episodic.get("failures", 0) or 0),
        }
    except Exception:
        return {
            "semantic_records": 0,
            "experience_episodes": 0,
            "experience_failures": 0,
        }


def _browser_status() -> str:
    module = sys.modules.get("browser_controller")
    if module is None:
        return "STANDBY"
    try:
        context = getattr(module, "_context", None)
        page = getattr(module, "_page", None)
        if context is not None:
            return "CONNECTED"
        if page is not None:
            return "READY"
    except Exception:
        pass
    return "STANDBY"


def collect_health() -> Dict[str, Any]:
    started = time.perf_counter()

    ollama = _ollama_ready()

    status = {
        "ollama": ollama,
        "whisper": _speech_ready(),
        "piper": _tts_ready(),
        "wake_word": _loaded_module("wakeword"),
        "browser": _browser_status(),
        "barehands": _loaded_module("barehands_tools"),
        "resilience": _resilience_summary(),
        "memory": _memory_summary(),
        "models": {
            "chat": CHAT_MODEL,
            "planner": PLANNER_MODEL,
            "coding": CODING_MODEL,
            "vision": VISION_MODEL,
            "verify": VERIFY_MODEL,
            "whisper": WHISPER_MODEL,
        },
        "elapsed": round(time.perf_counter() - started, 3),
    }

    boolean_components = [
        bool(status["ollama"]),
        bool(status["whisper"]),
        bool(status["piper"]),
    ]
    status["overall"] = "READY" if all(boolean_components) else "DEGRADED"

    return status


def format_health(status: Dict[str, Any] | None = None) -> str:
    if status is None:
        status = collect_health()

    models = status.get("models", {})

    lines = [
        f"JARVIS system status: {status.get('overall', 'UNKNOWN')}",
        f"Ollama: {'READY' if status.get('ollama') else 'OFFLINE'}",
        f"Whisper: {'READY' if status.get('whisper') else 'NOT LOADED'}",
        f"Piper: {'READY' if status.get('piper') else 'NOT LOADED'}",
        f"Wake word: {'READY' if status.get('wake_word') else 'STANDBY'}",
        f"Browser: {status.get('browser', 'STANDBY')}",
        f"Barehands: {'READY' if status.get('barehands') else 'STANDBY'}",
        f"Degraded tools: {status.get('resilience', {}).get('degraded_tools', 0)}",
        f"Local memory: {status.get('memory', {}).get('semantic_records', 0)} records",
        "",
        f"Chat model: {models.get('chat', 'unknown')}",
        f"Planner model: {models.get('planner', 'unknown')}",
        f"Coding model: {models.get('coding', 'unknown')}",
        f"Vision model: {models.get('vision', 'unknown')}",
        f"Verify model: {models.get('verify', 'unknown')}",
        f"Health check: {status.get('elapsed', 0):.3f}s",
    ]

    return "\n".join(lines)


def get_status_text() -> str:
    return format_health(collect_health())
