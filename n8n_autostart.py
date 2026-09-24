"""Background n8n process supervisor for JARVIS on Windows.

JARVIS starts n8n automatically when enabled, but never blocks normal startup
waiting for n8n to become ready. The supervisor also refuses to launch a second
instance when port 5678 is already listening.
"""
from __future__ import annotations
import os
import shutil
import socket
import subprocess
import threading
from pathlib import Path
from typing import Optional

import config
from logger import logger

_n8n_process: Optional[subprocess.Popen] = None
_lock = threading.Lock()

def n8n_port_open(host: str = "127.0.0.1", port: int = 5678, timeout: float = 0.35) -> bool:
    try:
        with socket.create_connection((host, int(port)), timeout=max(0.05, float(timeout))):
            return True
    except (OSError, ValueError):
        return False

def n8n_start_script() -> Path:
    return Path(config.BASE_DIR) / "n8n" / "start-n8n.ps1"

def n8n_log_path() -> Path:
    """Return the ignored local log path for n8n startup diagnostics."""
    path = Path(config.BASE_DIR) / ".jarvis_runtime" / "n8n-autostart.log"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _powershell_path() -> str:
    windir = os.environ.get("WINDIR", r"C:\Windows")
    return str(Path(windir) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe")

def _is_windows() -> bool:
    return os.name == "nt"



def _npx_path() -> str | None:
    return shutil.which("npx.cmd") or shutil.which("npx")


def _launch_process() -> subprocess.Popen | None:
    npx = _npx_path()
    if not npx:
        logger.warning(
            "JARVIS: npx was not found in PATH; n8n autostart cannot start."
        )
        try:
            log_file = n8n_log_path().open("a", encoding="utf-8")
            log_file.write(
                "JARVIS n8n supervisor: npx was not found in PATH.\n"
            )
            log_file.close()
        except OSError:
            pass
        return None

    log_path = n8n_log_path()
    try:
        log_file = log_path.open("a", encoding="utf-8")
        log_file.write(
            "JARVIS n8n supervisor: launching npx directly.\n"
            f"npx={npx}\n"
        )
        log_file.flush()
    except OSError as exc:
        logger.warning(f"JARVIS: could not open n8n startup log: {exc}")
        return None

    env = os.environ.copy()
    env["N8N_HOST"] = "127.0.0.1"
    env["N8N_PORT"] = "5678"
    env["N8N_PROTOCOL"] = "http"

    cmd_exe = os.environ.get(
        "ComSpec",
        str(Path(os.environ.get("WINDIR", r"C:\Windows")) / "System32" / "cmd.exe"),
    )
    # npx.cmd is a batch file. Use CALL so cmd.exe handles it correctly even when
    # the Node.js installation path contains spaces (for example, Program Files).
    command_line = f'call "{npx}" --yes n8n@2.40.5'

    flags = int(getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
    flags |= int(getattr(subprocess, "CREATE_NO_WINDOW", 0))

    startupinfo = None
    if hasattr(subprocess, "STARTUPINFO"):
        startupinfo = subprocess.STARTUPINFO()
        if hasattr(subprocess, "STARTF_USESHOWWINDOW"):
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        if hasattr(subprocess, "SW_HIDE"):
            startupinfo.wShowWindow = subprocess.SW_HIDE

    try:
        process = subprocess.Popen(
            [cmd_exe, "/d", "/c", command_line],
            cwd=str(config.BASE_DIR),
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=log_file,
            stderr=log_file,
            startupinfo=startupinfo,
            creationflags=flags,
            close_fds=False,
        )
        log_file.write(
            f"JARVIS n8n supervisor: child PID={process.pid}.\n"
        )
        log_file.flush()
        return process
    except Exception as exc:
        log_file.write(
            f"JARVIS n8n supervisor: process launch failed: {exc}\n"
        )
        log_file.close()
        logger.warning(f"JARVIS: n8n autostart launch failed: {exc}")
        return None


def _monitor_startup(process: subprocess.Popen | None, timeout: float, poll_interval: float) -> None:
    elapsed = 0.0
    step = max(0.1, float(poll_interval))
    while elapsed < max(0.5, float(timeout)):
        if n8n_port_open():
            logger.info("JARVIS: n8n is listening on http://127.0.0.1:5678.")
            return
        if process is not None:
            try:
                if process.poll() is not None:
                    logger.warning(
                        "JARVIS: n8n autostart process exited before port 5678 became available."
                    )
                    return
            except Exception:
                pass
        threading.Event().wait(step)
        elapsed += step
    logger.warning(
        "JARVIS: n8n did not become ready during the autostart window. "
        "JARVIS will continue running normally."
    )

def ensure_n8n_started(*, timeout: float | None = None, poll_interval: float | None = None) -> dict[str, object]:
    if not bool(getattr(config, "N8N_ENABLED", False)):
        return {"success": False, "enabled": False, "started": False, "reachable": False, "message": "n8n autostart is disabled."}

    if not bool(getattr(config, "N8N_AUTOSTART", True)):
        return {"success": True, "enabled": True, "started": False, "reachable": False, "message": "n8n autostart is disabled by configuration."}

    if not _is_windows():
        return {"success": False, "enabled": True, "started": False, "reachable": False, "message": "n8n autostart is currently supported on Windows only."}

    if n8n_port_open():
        logger.info("JARVIS: n8n already listening on http://127.0.0.1:5678.")
        return {"success": True, "enabled": True, "started": False, "reachable": True, "already_running": True, "message": "n8n is already running."}

    with _lock:
        if n8n_port_open():
            return {"success": True, "enabled": True, "started": False, "reachable": True, "already_running": True, "message": "n8n is already running."}
        process = _launch_process()
        if process is None:
            return {"success": False, "enabled": True, "started": False, "reachable": False, "message": "JARVIS could not launch the n8n startup process."}
        global _n8n_process
        _n8n_process = process

    monitor_timeout = float(timeout) if timeout is not None else float(getattr(config, "N8N_AUTOSTART_TIMEOUT_SECONDS", 15.0))
    monitor_interval = float(poll_interval) if poll_interval is not None else float(getattr(config, "N8N_AUTOSTART_POLL_INTERVAL_SECONDS", 0.5))
    threading.Thread(
        target=_monitor_startup,
        args=(process, monitor_timeout, monitor_interval),
        name="JARVIS-n8n-autostart-monitor",
        daemon=True,
    ).start()
    logger.info(
        "JARVIS: n8n autostart launched in the background. "
        f"Startup log: {n8n_log_path()}"
    )
    return {
        "success": True,
        "enabled": True,
        "started": True,
        "reachable": False,
        "pid": getattr(process, "pid", None),
        "message": "n8n startup launched in the background; JARVIS will continue without waiting.",
    }
