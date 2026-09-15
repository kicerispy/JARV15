"""
JARVIS launcher - creates a proper Windows executable entry point.
Run this to create a desktop shortcut or start JARVIS directly.
"""
import os
import sys
import subprocess
from pathlib import Path


def find_python():
    """Find the Python executable to use."""
    # Check for virtual environment first
    venv_paths = [
        Path(__file__).parent / "jarvis_cuda" / "Scripts" / "python.exe",
        Path(__file__).parent / "jarvis_cuda" / "Scripts" / "pythonw.exe",
    ]
    
    for path in venv_paths:
        if path.exists():
            return str(path)
    
    # Fall back to system Python
    return sys.executable


def run_jarvis():
    """Start JARVIS."""
    python = find_python()
    main_script = Path(__file__).parent / "main.py"
    
    print(f"Starting JARVIS with: {python}")
    print(f"Script: {main_script}")
    print("-" * 50)
    
    subprocess.call([python, str(main_script)])


def create_shortcut():
    """Create a Windows desktop shortcut for JARVIS."""
    try:
        import win32com.client
    except ImportError:
        print("pywin32 not installed - cannot create shortcut")
        return False
    
    python = find_python()
    main_script = Path(__file__).parent / "main.py"
    
    shell = win32com.client.Dispatch("WScript.Shell")
    shortcut = shell.CreateShortchut(
        str(Path.home() / "Desktop" / "JARVIS.lnk"),
        python,
        f'"{main_script}"',
        description="JARVIS AI Assistant",
    )
    shortcut.save()
    
    print(f"Shortcut created on desktop: {Path.home() / 'Desktop' / 'JARVIS.lnk'}")
    return True


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--shortcut":
        create_shortcut()
    else:
        run_jarvis()