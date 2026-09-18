"""Windows startup integration for JARVIS.

Uses the per-user Run key so no administrator privileges are required.
The functions fail safely on non-Windows systems.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "JARVIS"
_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def _command() -> str:
    if getattr(sys, "frozen", False):
        executable = Path(sys.executable).resolve()
        return f'"{executable}" --startup'

    executable = Path(sys.executable).resolve()
    if executable.name.lower() == "python.exe":
        pythonw = executable.with_name("pythonw.exe")
        if pythonw.exists():
            executable = pythonw

    script = Path(__file__).resolve().with_name("run_jarvis.py")
    return f'"{executable}" "{script}" --startup'


def is_supported() -> bool:
    return os.name == "nt"


def is_enabled() -> bool:
    if not is_supported():
        return False

    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            _RUN_KEY,
            0,
            winreg.KEY_READ,
        ) as key:
            value, _ = winreg.QueryValueEx(key, APP_NAME)
            return str(value).strip() == _command()
    except FileNotFoundError:
        return False
    except OSError:
        return False


def enable_startup() -> bool:
    if not is_supported():
        return False

    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            _RUN_KEY,
            0,
            winreg.KEY_SET_VALUE,
        ) as key:
            winreg.SetValueEx(
                key,
                APP_NAME,
                0,
                winreg.REG_SZ,
                _command(),
            )
        return True
    except OSError:
        return False


def disable_startup() -> bool:
    if not is_supported():
        return False

    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            _RUN_KEY,
            0,
            winreg.KEY_SET_VALUE,
        ) as key:
            winreg.DeleteValue(key, APP_NAME)
        return True
    except FileNotFoundError:
        return True
    except OSError:
        return False


def status_text() -> str:
    if not is_supported():
        return "Windows startup integration is unavailable on this system."

    return (
        "JARVIS is configured to start with Windows."
        if is_enabled()
        else "JARVIS is not configured to start with Windows."
    )
