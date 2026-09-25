"""JARVIS runtime and computer status."""

from __future__ import annotations

import time
from typing import Any, Dict

import psutil

from logger import logger
import runtime_health
from healing_kernel import healing_status


_start_time = time.time()


def collect_status() -> Dict[str, Any]:
    """Collect fast system and subsystem status without blocking probes."""
    health = runtime_health.collect_health()
    return {
        "health": health,
        "cpu": psutil.cpu_percent(interval=None),
        "ram": psutil.virtual_memory().percent,
        "uptime": int(time.time() - _start_time),
    }


def get_status(model: str = "") -> str:
    try:
        status = collect_status()
        health = status["health"]
        healing = healing_status()

        model_text = model.strip() if model else "configured models"
        return (
            "JARVIS Status:\n"
            f"System: {health.get('overall', 'UNKNOWN')}\n"
            f"CPU: {status['cpu']}%\n"
            f"RAM: {status['ram']}%\n"
            f"Uptime: {status['uptime']} seconds\n\n"
            f"Ollama: {'READY' if health.get('ollama') else 'OFFLINE'}\n"
            f"Whisper: {'READY' if health.get('whisper') else 'NOT LOADED'}\n"
            f"Piper: {'READY' if health.get('piper') else 'NOT LOADED'}\n"
            f"Wake word: {'READY' if health.get('wake_word') else 'STANDBY'}\n"
            f"Browser: {health.get('browser', 'STANDBY')}\n"
            f"Barehands: {'READY' if health.get('barehands') else 'STANDBY'}\n"
            f"Self-healing: {'ENABLED' if healing.get('enabled') else 'DISABLED'}\n"
            f"Healing journal: {healing.get('events', 0)} events; "
            f"budget {healing.get('max_attempts', 0)} attempt(s)\n"
            f"Models: {model_text}"
        )
    except Exception as exc:
        logger.error(f"Failed to get JARVIS status: {exc}")
        return "I couldn't retrieve the JARVIS status."
