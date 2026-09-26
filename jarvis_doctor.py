"""Deep, read-only JARVIS health diagnostics.

The doctor combines runtime health, Ollama model inventory, tool reliability,
self-healing memory, local semantic memory, Git state, and optional test probes.
It never mutates source code or installs packages.
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict

import config
from autonomy_memory import autonomy_memory_status
from healing_kernel import healing_status
from local_memory import memory_status
from model_manager import ModelManager
from resilience_kernel import tool_health_status
import runtime_health


def _git_snapshot(base: Path) -> Dict[str, Any]:
    try:
        branch = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=str(base),
            capture_output=True,
            text=True,
            timeout=5,
        )
        status = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=no"],
            cwd=str(base),
            capture_output=True,
            text=True,
            timeout=5,
        )
        return {
            "available": branch.returncode == 0 and status.returncode == 0,
            "branch": (branch.stdout or "").strip(),
            "tracked_worktree_clean": not bool((status.stdout or "").strip()),
        }
    except Exception as exc:
        return {
            "available": False,
            "error": str(exc),
        }


def _check_models() -> Dict[str, Any]:
    manager = ModelManager()
    try:
        models = manager.list_local_models()
        configured = {
            "chat": manager.chat_model,
            "planner": manager.planner_model,
            "change_planner": manager.change_planner_model,
            "coding": manager.coding_model,
            "coding_fallback": manager.coding_fallback_model,
        }
        available_names = {
            str(item.get("name") or item.get("model") or "")
            for item in models
            if isinstance(item, dict)
        }
        missing = {
            key: name
            for key, name in configured.items()
            if name and name not in available_names
        }
        return {
            "reachable": True,
            "configured": configured,
            "available_count": len(available_names),
            "available_models": sorted(available_names),
            "missing_configured_models": missing,
        }
    except Exception as exc:
        return {
            "reachable": False,
            "configured": {
                "chat": manager.chat_model,
                "planner": manager.planner_model,
                "change_planner": manager.change_planner_model,
                "coding": manager.coding_model,
                "coding_fallback": manager.coding_fallback_model,
            },
            "error": str(exc),
        }


def _compile_probe(base: Path) -> Dict[str, Any]:
    try:
        files = [
            path
            for path in base.rglob("*.py")
            if ".jarvis_autonomy" not in path.parts
            and ".git" not in path.parts
            and "jarvis_cuda" not in path.parts
            and "__pycache__" not in path.parts
        ]
        if not files:
            return {"status": "skipped", "reason": "no Python sources"}

        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "compileall",
                "-q",
                *[str(path.relative_to(base)) for path in files],
            ],
            cwd=str(base),
            capture_output=True,
            text=True,
            timeout=180,
        )
        return {
            "status": "passed" if completed.returncode == 0 else "failed",
            "files": len(files),
            "returncode": completed.returncode,
            "stderr": (completed.stderr or "")[-5000:],
        }
    except subprocess.TimeoutExpired:
        return {"status": "timeout", "files": 0}
    except Exception as exc:
        return {"status": "error", "error": str(exc)}


def run_doctor(
    *,
    deep: bool = False,
    run_tests: bool = False,
) -> Dict[str, Any]:
    started = time.perf_counter()
    base = Path(getattr(config, "BASE_DIR", Path.cwd())).resolve()

    health = runtime_health.collect_health()
    models = _check_models()
    healing = healing_status()
    experience = autonomy_memory_status()
    memory = memory_status()
    tools = tool_health_status(limit=12)
    git = _git_snapshot(base)

    probes: Dict[str, Any] = {}
    if deep:
        probes["compile"] = _compile_probe(base)

    if deep and run_tests:
        try:
            completed = subprocess.run(
                [sys.executable, "-m", "pytest", "tests", "-q"],
                cwd=str(base),
                capture_output=True,
                text=True,
                timeout=300,
            )
            probes["pytest"] = {
                "status": "passed" if completed.returncode == 0 else "failed",
                "returncode": completed.returncode,
                "stdout": (completed.stdout or "")[-10000:],
                "stderr": (completed.stderr or "")[-10000:],
            }
        except subprocess.TimeoutExpired:
            probes["pytest"] = {
                "status": "timeout",
                "returncode": None,
            }
        except Exception as exc:
            probes["pytest"] = {
                "status": "error",
                "error": str(exc),
            }

    failures = []
    if not health.get("ollama"):
        failures.append("Ollama is unreachable.")
    if health.get("overall") == "DEGRADED":
        failures.append("One or more core runtime components are not ready.")
    if not models.get("reachable"):
        failures.append("Ollama model inventory could not be read.")
    if models.get("missing_configured_models"):
        failures.append(
            "Configured model(s) are not installed: "
            + ", ".join(models["missing_configured_models"].values())
        )
    if deep and probes.get("compile", {}).get("status") not in {"passed", "skipped"}:
        failures.append("Python compilation probe failed.")
    if deep and run_tests and probes.get("pytest", {}).get("status") != "passed":
        failures.append("Project pytest suite did not pass.")

    summary = (
        "JARVIS doctor: healthy."
        if not failures
        else "JARVIS doctor: attention required."
    )

    healthy = not failures

    return {
        # Diagnostic execution succeeded even when the diagnosis is degraded.
        # Keep the health state explicit so the agent does not turn an
        # informational health finding into a failed task.
        "success": True,
        "healthy": healthy,
        "verified": True,
        "mode": "doctor",
        "summary": summary,
        "failures": failures,
        "health": health,
        "models": models,
        "healing": healing,
        "experience_memory": experience,
        "local_memory": memory,
        "tool_health": tools,
        "git": git,
        "probes": probes,
        "elapsed": round(time.perf_counter() - started, 3),
    }


def format_doctor_report(result: Dict[str, Any]) -> str:
    failures = result.get("failures", [])
    health = result.get("health", {})
    models = result.get("models", {})
    tools = result.get("tool_health", {})
    memory = result.get("local_memory", {})

    lines = [
        str(result.get("summary", "JARVIS doctor completed.")),
        f"Core runtime: {health.get('overall', 'UNKNOWN')}",
        f"Ollama: {'READY' if health.get('ollama') else 'OFFLINE'}",
        f"Models installed: {models.get('available_count', 0)}",
        f"Tool health records: {tools.get('tool_count', 0)}",
        f"Local memory records: {memory.get('records', 0)}",
    ]

    degraded = tools.get("degraded_tools") or []
    if degraded:
        lines.append(
            "Degraded tools: "
            + ", ".join(item.get("tool", "?") for item in degraded[:5])
        )

    if failures:
        lines.append("Issues:")
        lines.extend(f"- {item}" for item in failures[:8])

    lines.append(f"Doctor runtime: {result.get('elapsed', 0):.3f}s")
    return "\n".join(lines)


__all__ = ["run_doctor", "format_doctor_report"]
