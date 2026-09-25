"""Low-latency quality-of-life diagnostics for JARVIS.

These tools are read-only and intentionally dependency-light. They turn common
"what is my machine doing?" and "is JARVIS ready?" questions into deterministic
answers without spending an Ollama generation.
"""

from __future__ import annotations

import os
import platform
import subprocess
import sys
import time
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

import psutil

import config
import runtime_health
from healing_kernel import healing_status
from local_memory import memory_status
from resilience_kernel import tool_health_status


def _git_snapshot(base: Path) -> dict[str, Any]:
    try:
        branch = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=str(base),
            capture_output=True,
            text=True,
            timeout=3,
        )
        status = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=no"],
            cwd=str(base),
            capture_output=True,
            text=True,
            timeout=3,
        )
        return {
            "available": branch.returncode == 0 and status.returncode == 0,
            "branch": (branch.stdout or "").strip(),
            "clean": not bool((status.stdout or "").strip()),
        }
    except Exception as exc:
        return {"available": False, "error": str(exc)}


def _probe_http(url: str, timeout: float = 0.6) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        request = Request(
            url,
            headers={"User-Agent": "JARVIS/1.0"},
            method="GET",
        )
        with urlopen(request, timeout=timeout) as response:
            return {
                "ready": True,
                "status": int(getattr(response, "status", 200) or 200),
                "latency_ms": round((time.perf_counter() - started) * 1000, 1),
            }
    except Exception as exc:
        return {
            "ready": False,
            "latency_ms": round((time.perf_counter() - started) * 1000, 1),
            "error": str(exc)[:300],
        }


def resource_status() -> dict[str, Any]:
    """Return a compact CPU, memory, disk, and process summary."""
    disk = psutil.disk_usage(str(config.BASE_DIR))
    memory = psutil.virtual_memory()
    return {
        "success": True,
        "verified": True,
        "cpu_percent": round(psutil.cpu_percent(interval=None), 1),
        "memory_percent": round(memory.percent, 1),
        "memory_available_gb": round(memory.available / (1024**3), 2),
        "disk_percent": round(disk.percent, 1),
        "disk_free_gb": round(disk.free / (1024**3), 2),
        "cpu_count": psutil.cpu_count(logical=True) or 0,
    }


def process_snapshot(argument: str = "") -> dict[str, Any]:
    """Return the busiest local processes without exposing command-line secrets."""
    raw = str(argument or "").strip()
    try:
        limit = int(raw or 8)
    except ValueError:
        limit = 8
    limit = max(1, min(limit, 15))

    processes = []
    for proc in psutil.process_iter(["pid", "name", "cpu_percent", "memory_percent"]):
        try:
            info = proc.info
            processes.append(
                {
                    "pid": int(info.get("pid") or 0),
                    "name": str(info.get("name") or "unknown")[:120],
                    "cpu_percent": round(float(info.get("cpu_percent") or 0.0), 1),
                    "memory_percent": round(
                        float(info.get("memory_percent") or 0.0),
                        1,
                    ),
                }
            )
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    processes.sort(
        key=lambda item: (
            float(item["cpu_percent"]),
            float(item["memory_percent"]),
        ),
        reverse=True,
    )

    return {
        "success": True,
        "verified": True,
        "limit": limit,
        "processes": processes[:limit],
    }


def project_snapshot() -> dict[str, Any]:
    """Return project branch, source/test counts, and repository cleanliness."""
    base = Path(getattr(config, "BASE_DIR", Path.cwd())).resolve()
    python_files = 0
    test_files = 0

    try:
        for path in base.rglob("*.py"):
            if any(
                part in {".git", ".jarvis_autonomy", "jarvis_cuda", "__pycache__"}
                for part in path.parts
            ):
                continue
            python_files += 1
            if path.name.startswith("test_") or path.name.endswith("_test.py"):
                test_files += 1
    except OSError:
        pass

    git = _git_snapshot(base)
    return {
        "success": True,
        "verified": True,
        "project": str(base),
        "python_files": python_files,
        "test_files": test_files,
        "git": git,
        "python": sys.version.split()[0],
        "platform": platform.platform(),
    }


def service_status(argument: str = "") -> dict[str, Any]:
    """Probe local services JARVIS commonly depends on."""
    requested = str(argument or "").strip().lower()

    services: dict[str, dict[str, Any]] = {}
    if not requested or requested in {"ollama", "all"}:
        ollama = str(getattr(config, "OLLAMA_HOST", "")).rstrip("/")
        services["ollama"] = _probe_http(ollama + "/api/tags")

    if not requested or requested in {"n8n", "all"}:
        n8n = str(getattr(config, "N8N_BASE_URL", "")).rstrip("/")
        if n8n:
            services["n8n"] = _probe_http(n8n)

    if not services:
        return {
            "success": False,
            "verified": False,
            "message": "Unknown service. Use ollama, n8n, or all.",
        }

    return {
        "success": all(item.get("ready") for item in services.values()),
        "verified": True,
        "services": services,
    }


def jarvis_quickcheck() -> dict[str, Any]:
    """Fast deterministic readiness snapshot for voice/status commands."""
    started = time.perf_counter()
    health = runtime_health.collect_health()
    memory = memory_status()
    healing = healing_status()
    tools = tool_health_status(limit=8)
    resources = resource_status()

    degraded = [
        item
        for item in tools.get("degraded_tools", [])
        if isinstance(item, dict)
    ]

    overall = (
        "READY"
        if health.get("overall") == "READY"
        and not degraded
        else "DEGRADED"
    )

    return {
        "success": overall == "READY",
        "verified": True,
        "overall": overall,
        "health": health,
        "resources": resources,
        "tool_health": {
            "tracked": tools.get("tool_count", 0),
            "degraded": [item.get("tool", "?") for item in degraded[:8]],
        },
        "memory_records": memory.get("records", 0),
        "healing_events": healing.get("events", 0),
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 1),
    }


__all__ = [
    "jarvis_quickcheck",
    "process_snapshot",
    "project_snapshot",
    "resource_status",
    "service_status",
]
