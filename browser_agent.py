"""Bridge from JARVIS to the isolated Browser Use worker."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from urllib.request import Request, urlopen

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_CDP_URL = os.getenv("JARVIS_CDP_URL", "http://127.0.0.1:9222")
DEFAULT_OLLAMA_HOST = os.getenv(
    "JARVIS_OLLAMA_HOST",
    "http://127.0.0.1:11434",
)
DEFAULT_BROWSER_MODEL = os.getenv("JARVIS_BROWSER_MODEL", "qwen3.5:9b")
DEFAULT_MAX_STEPS = 12
DEFAULT_TIMEOUT_SECONDS = 300


def _browser_agent_python() -> Path:
    override = str(os.getenv("JARVIS_BROWSER_AGENT_PYTHON", "")).strip()
    if override:
        return Path(override).expanduser().resolve()

    if os.name == "nt":
        return BASE_DIR / ".browser_agent_venv" / "Scripts" / "python.exe"
    return BASE_DIR / ".browser_agent_venv" / "bin" / "python"


def _probe_url(url: str, timeout: float = 2.0) -> bool:
    try:
        request = Request(url, method="GET")
        with urlopen(request, timeout=timeout):
            return True
    except Exception:
        return False


def _parse_argument(argument: str) -> tuple[str, dict]:
    raw = str(argument or "").strip()
    if not raw:
        return "", {}

    if raw.startswith("{") and raw.endswith("}"):
        try:
            payload = json.loads(raw)
            if isinstance(payload, dict):
                task = str(
                    payload.get("task")
                    or payload.get("request")
                    or ""
                ).strip()
                return task, payload
        except (json.JSONDecodeError, TypeError):
            pass

    return raw, {}


def _worker_import_ok(python_exe: Path) -> bool:
    if not python_exe.is_file():
        return False

    try:
        result = subprocess.run(
            [str(python_exe), "-c", "import browser_use; print('ok')"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False

    return result.returncode == 0 and result.stdout.strip().endswith("ok")


def browser_agent_status() -> dict:
    """Report whether the isolated Browser Use stack is usable."""
    python_exe = _browser_agent_python()
    worker_import_ok = _worker_import_ok(python_exe)
    python_ok = sys.version_info >= (3, 11)

    ollama_ok = _probe_url(DEFAULT_OLLAMA_HOST.rstrip("/") + "/api/tags")
    cdp_ok = _probe_url(DEFAULT_CDP_URL.rstrip("/") + "/json/version")

    available = bool(worker_import_ok and python_ok)
    verified = bool(available and ollama_ok and cdp_ok)

    details = [
        f"python={sys.version.split()[0]}",
        f"worker={'ready' if worker_import_ok else 'missing'}",
        f"ollama={'online' if ollama_ok else 'offline'}",
        f"cdp={'online' if cdp_ok else 'offline'}",
        f"model={DEFAULT_BROWSER_MODEL}",
    ]

    return {
        "success": available,
        "verified": verified,
        "available": available,
        "python_ok": python_ok,
        "worker_path": str(python_exe),
        "browser_use_installed": worker_import_ok,
        "ollama_ok": ollama_ok,
        "cdp_ok": cdp_ok,
        "cdp_url": DEFAULT_CDP_URL,
        "ollama_host": DEFAULT_OLLAMA_HOST,
        "model": DEFAULT_BROWSER_MODEL,
        "message": "Browser agent status: " + ", ".join(details),
    }


def browser_agent_run(argument: str = "") -> dict:
    """Run one autonomous browser task in JARVIS's existing Chromium session."""
    task, payload = _parse_argument(argument)
    if not task:
        return {
            "success": False,
            "verified": False,
            "error": "Browser agent task cannot be empty.",
            "message": "Provide a browser task.",
        }

    python_exe = _browser_agent_python()
    if not python_exe.is_file():
        return {
            "success": False,
            "verified": False,
            "error": f"Browser agent Python environment not found: {python_exe}",
            "message": "The isolated Browser Use environment is missing.",
        }

    try:
        max_steps = int(
            payload.get(
                "max_steps",
                os.getenv("JARVIS_BROWSER_MAX_STEPS", DEFAULT_MAX_STEPS),
            )
        )
    except (TypeError, ValueError):
        max_steps = DEFAULT_MAX_STEPS
    max_steps = max(1, min(max_steps, 30))

    try:
        timeout_seconds = int(
            payload.get(
                "timeout",
                os.getenv(
                    "JARVIS_BROWSER_AGENT_TIMEOUT",
                    DEFAULT_TIMEOUT_SECONDS,
                ),
            )
        )
    except (TypeError, ValueError):
        timeout_seconds = DEFAULT_TIMEOUT_SECONDS
    timeout_seconds = max(30, min(timeout_seconds, 1800))

    try:
        import browser_controller

        controller_status = browser_controller.ensure_browser()
        if not controller_status.get("success"):
            return {
                "success": False,
                "verified": False,
                "error": controller_status.get(
                    "message",
                    "Could not start JARVIS browser.",
                ),
                "message": "JARVIS browser could not be started.",
            }

        if not _probe_url(
            DEFAULT_CDP_URL.rstrip("/") + "/json/version",
            timeout=3.0,
        ):
            return {
                "success": False,
                "verified": False,
                "error": (
                    f"JARVIS Chromium CDP endpoint is not reachable at "
                    f"{DEFAULT_CDP_URL}."
                ),
                "message": "JARVIS browser is running but CDP is unavailable.",
            }

        worker_payload = json.dumps(
            {"task": task, "max_steps": max_steps},
            ensure_ascii=False,
        )

        env = os.environ.copy()
        env["JARVIS_CDP_URL"] = DEFAULT_CDP_URL
        env["JARVIS_OLLAMA_HOST"] = DEFAULT_OLLAMA_HOST
        env["JARVIS_BROWSER_MODEL"] = DEFAULT_BROWSER_MODEL

        process = subprocess.run(
            [
                str(python_exe),
                str(BASE_DIR / "browser_agent_worker.py"),
            ],
            input=worker_payload,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
            env=env,
        )

        stdout = (process.stdout or "").strip()
        stderr = (process.stderr or "").strip()

        try:
            parsed = json.loads(stdout) if stdout else None
        except json.JSONDecodeError:
            parsed = None

        if isinstance(parsed, dict):
            parsed.setdefault("worker_returncode", process.returncode)
            if stderr:
                parsed.setdefault("worker_stderr", stderr[-4000:])
            return parsed

        error_text = stderr or stdout or "Browser agent worker returned no output."
        return {
            "success": False,
            "verified": False,
            "error": error_text,
            "message": "Browser agent worker returned invalid JSON.",
            "worker_returncode": process.returncode,
        }

    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "verified": False,
            "error": (
                f"Browser agent timed out after {timeout_seconds} seconds."
            ),
            "message": "The autonomous browser task reached its safety timeout.",
        }
    except Exception as exc:
        return {
            "success": False,
            "verified": False,
            "error": str(exc),
            "message": f"Browser agent failed: {exc}",
        }


__all__ = ["browser_agent_run", "browser_agent_status"]
