"""Local controller and data bridge for Bilawal Sidhu's God's Eye View."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path
from typing import Any

GEV_REPO = "https://github.com/bilawalsidhu/gods-eye-view.git"
GEV_DIR = Path.cwd() / ".jarvis_external" / "gods-eye-view"
GEV_URL = "http://127.0.0.1:4173"
PID_PATH = Path.cwd() / ".jarvis_gods_eye.pid"


def _clean(value: Any, limit: int = 500) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else text[:limit].rsplit(" ", 1)[0] + "..."


def _run(argv: list[str], *, cwd: Path | None = None, timeout: int = 30):
    return subprocess.run(
        argv,
        cwd=str(cwd or GEV_DIR.parent),
        capture_output=True,
        text=True,
        timeout=timeout,
        shell=False,
    )


def _node_version() -> tuple[int, int] | None:
    try:
        completed = _run(["node", "--version"], cwd=Path.cwd(), timeout=10)
    except Exception:
        return None
    if completed.returncode != 0:
        return None
    match = __import__("re").search(r"v?(\d+)\.(\d+)", completed.stdout or "")
    return (int(match.group(1)), int(match.group(2))) if match else None


def _http_json(path: str, *, timeout: int = 8):
    request = urllib.request.Request(
        f"{GEV_URL}{path}",
        headers={"User-Agent": "JARVIS/1.0", "Accept": "application/json"},
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8", errors="replace"))


def gods_eye_status(argument: str = "") -> dict[str, Any]:
    version = _node_version()
    installed = GEV_DIR.exists() and (GEV_DIR / "package.json").exists()
    running = False
    http_ok = False
    payload = None

    try:
        payload = _http_json("/api/opensky", timeout=3)
        http_ok = True
        running = True
    except Exception:
        running = False

    return {
        "success": True,
        "tool": "gods_eye_status",
        "data": {
            "installed": installed,
            "running": running,
            "url": GEV_URL,
            "node": f"{version[0]}.{version[1]}" if version else None,
            "supported_node": bool(version and ((version[0] == 24 and version[1] >= 14) or version[0] == 26)),
            "api_ok": http_ok,
        },
        "message": (
            f"God's Eye View is {'running' if running else 'not running'}"
            + (f" at {GEV_URL}." if running else ".")
        ),
    }


def gods_eye_setup(argument: str = "") -> dict[str, Any]:
    version = _node_version()
    if not version:
        return {
            "success": False,
            "tool": "gods_eye_setup",
            "message": "Node.js 24.14+ or 26.x is required for God's Eye View.",
            "retryable": False,
        }
    if not ((version[0] == 24 and version[1] >= 14) or version[0] == 26):
        return {
            "success": False,
            "tool": "gods_eye_setup",
            "message": f"Detected Node.js {version[0]}.{version[1]}; God's Eye View supports Node 24.14+ in 24.x or Node 26.x.",
            "retryable": False,
        }

    GEV_DIR.parent.mkdir(parents=True, exist_ok=True)

    try:
        if not (GEV_DIR / ".git").exists():
            completed = _run(["git", "clone", GEV_REPO, str(GEV_DIR)], cwd=GEV_DIR.parent, timeout=180)
        else:
            completed = _run(["git", "pull", "--ff-only", "origin", "main"], cwd=GEV_DIR, timeout=120)

        if completed.returncode != 0:
            return {
                "success": False,
                "tool": "gods_eye_setup",
                "message": "God's Eye View Git setup failed.",
                "error": (completed.stderr or completed.stdout or "").strip()[:2000],
                "retryable": True,
            }

        npm_cmd = shutil.which("npm.cmd") or shutil.which("npm")
        if not npm_cmd:
            return {
                "success": False,
                "tool": "gods_eye_setup",
                "message": "npm was not found after the Node.js check.",
                "retryable": False,
            }

        installed = _run([npm_cmd, "ci"], cwd=GEV_DIR, timeout=600)
        if installed.returncode != 0:
            return {
                "success": False,
                "tool": "gods_eye_setup",
                "message": "God's Eye View dependency installation failed.",
                "error": (installed.stderr or installed.stdout or "").strip()[:3000],
                "retryable": True,
            }

        doctor = _run([npm_cmd, "run", "doctor"], cwd=GEV_DIR, timeout=180)
        return {
            "success": doctor.returncode == 0,
            "tool": "gods_eye_setup",
            "data": {
                "path": str(GEV_DIR),
                "node": f"{version[0]}.{version[1]}",
                "doctor_output": (doctor.stdout or doctor.stderr or "").strip()[-4000:],
            },
            "message": (
                "God's Eye View is installed and passed its setup doctor."
                if doctor.returncode == 0
                else "God's Eye View was installed, but its setup doctor reported issues."
            ),
            "retryable": doctor.returncode != 0,
        }
    except Exception as exc:
        return {
            "success": False,
            "tool": "gods_eye_setup",
            "message": f"God's Eye View setup failed: {exc}",
            "retryable": True,
        }


def gods_eye_start(argument: str = "") -> dict[str, Any]:
    if not (GEV_DIR / "package.json").exists():
        return {
            "success": False,
            "tool": "gods_eye_start",
            "message": "God's Eye View is not installed. Run the setup command first.",
            "retryable": False,
        }

    if gods_eye_status()["data"]["running"]:
        webbrowser.open(GEV_URL)
        return {
            "success": True,
            "tool": "gods_eye_start",
            "data": {"url": GEV_URL, "already_running": True},
            "message": "God's Eye View is already running.",
        }

    npm_cmd = shutil.which("npm.cmd") or shutil.which("npm")
    if not npm_cmd:
        return {
            "success": False,
            "tool": "gods_eye_start",
            "message": "npm was not found.",
            "retryable": False,
        }

    try:
        process = subprocess.Popen(
            [npm_cmd, "run", "dev", "--", "--host", "127.0.0.1", "--port", "4173"],
            cwd=str(GEV_DIR),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            shell=False,
        )
        PID_PATH.write_text(str(process.pid), encoding="utf-8")

        deadline = time.monotonic() + 12
        while time.monotonic() < deadline:
            try:
                _http_json("/api/opensky", timeout=1)
                webbrowser.open(GEV_URL)
                return {
                    "success": True,
                    "tool": "gods_eye_start",
                    "data": {"url": GEV_URL, "pid": process.pid},
                    "message": "God's Eye View is running.",
                }
            except Exception:
                time.sleep(0.4)

        return {
            "success": False,
            "tool": "gods_eye_start",
            "message": "God's Eye View did not become reachable on port 4173.",
            "retryable": True,
        }
    except Exception as exc:
        return {
            "success": False,
            "tool": "gods_eye_start",
            "message": f"Could not start God's Eye View: {exc}",
            "retryable": True,
        }


def gods_eye_open(argument: str = "") -> dict[str, Any]:
    try:
        webbrowser.open(GEV_URL)
        return {
            "success": True,
            "tool": "gods_eye_open",
            "data": {"url": GEV_URL},
            "message": "Opened God's Eye View in the browser.",
        }
    except Exception as exc:
        return {"success": False, "tool": "gods_eye_open", "message": str(exc), "retryable": False}


def gods_eye_stop(argument: str = "") -> dict[str, Any]:
    if not PID_PATH.exists():
        return {"success": True, "tool": "gods_eye_stop", "message": "God's Eye View is not tracked as running."}

    try:
        pid = int(PID_PATH.read_text(encoding="utf-8").strip())
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, text=True, shell=False, timeout=15)
        PID_PATH.unlink(missing_ok=True)
        return {"success": True, "tool": "gods_eye_stop", "data": {"pid": pid}, "message": "God's Eye View was stopped."}
    except Exception as exc:
        return {"success": False, "tool": "gods_eye_stop", "message": f"Could not stop God's Eye View: {exc}", "retryable": False}


def _gev_list(endpoint: str, key: str, label: str) -> dict[str, Any]:
    try:
        payload = _http_json(endpoint, timeout=10)
        if isinstance(payload, list):
            rows = payload
        elif isinstance(payload, dict):
            rows = payload.get(key)
            if not isinstance(rows, list):
                rows = payload.get("results")
            if not isinstance(rows, list):
                rows = payload.get("items")
            if not isinstance(rows, list):
                rows = payload.get("sources")
            if not isinstance(rows, list):
                rows = payload.get("stations")
            if not isinstance(rows, list):
                rows = payload.get("feeds")
        else:
            rows = []
        rows = rows if isinstance(rows, list) else []
        return {
            "success": True,
            "tool": f"gods_eye_{label}",
            "data": {key: rows[:20], "source": "God's Eye View local API"},
            "message": f"God's Eye View returned {len(rows)} {label.replace('_', ' ')}.",
        }
    except Exception as exc:
        return {
            "success": False,
            "tool": f"gods_eye_{label}",
            "message": f"God's Eye View data request failed: {exc}",
            "retryable": True,
        }


def gods_eye_contacts(argument: str = "") -> dict[str, Any]:
    try:
        payload = _http_json("/api/opensky", timeout=12)
        states = payload.get("states") or []
        contacts = []
        for row in states[:50]:
            contacts.append({
                "icao24": row[0] if len(row) > 0 else None,
                "callsign": _clean(row[1], 40) if len(row) > 1 else None,
                "country": row[2] if len(row) > 2 else None,
                "longitude": row[5] if len(row) > 5 else None,
                "latitude": row[6] if len(row) > 6 else None,
                "altitude_m": row[7] if len(row) > 7 else None,
                "velocity_mps": row[9] if len(row) > 9 else None,
            })
        return {
            "success": True,
            "tool": "gods_eye_contacts",
            "data": {"contacts": contacts, "count": len(contacts), "source": "God's Eye View / OpenSky"},
            "message": f"God's Eye View reports {len(contacts)} aircraft contacts.",
        }
    except Exception as exc:
        return {"success": False, "tool": "gods_eye_contacts", "message": f"Could not read live aircraft contacts: {exc}", "retryable": True}


def gods_eye_launches(argument: str = "") -> dict[str, Any]:
    return _gev_list("/api/launches", "launches", "launches")


def gods_eye_cameras(argument: str = "") -> dict[str, Any]:
    return _gev_list("/api/cctv/sources", "sources", "cameras")


def gods_eye_radio(argument: str = "") -> dict[str, Any]:
    return _gev_list("/api/radio/stations", "stations", "radio")


def gods_eye_transit(argument: str = "") -> dict[str, Any]:
    return _gev_list("/api/transit/feeds", "feeds", "transit")


DISPATCH = {
    "gods_eye_status": gods_eye_status,
    "gods_eye_setup": gods_eye_setup,
    "gods_eye_start": gods_eye_start,
    "gods_eye_open": gods_eye_open,
    "gods_eye_stop": gods_eye_stop,
    "gods_eye_contacts": gods_eye_contacts,
    "gods_eye_launches": gods_eye_launches,
    "gods_eye_cameras": gods_eye_cameras,
    "gods_eye_radio": gods_eye_radio,
    "gods_eye_transit": gods_eye_transit,
}


def run_gods_eye_tool(tool_name: str, argument: str = "") -> Any:
    function = DISPATCH.get(str(tool_name or "").strip())
    if function is None:
        return {
            "success": False,
            "tool": tool_name,
            "message": f"Unknown God's Eye View tool: {tool_name}",
            "retryable": False,
        }
    return function(argument)
