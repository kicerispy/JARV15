"""
JARVIS - Windows Entry Point
This is the main entry point that can be compiled to a .exe with PyInstaller.
"""
import os
import sys
from pathlib import Path

# Always anchor JARVIS to its own project directory. This matters for
# Windows startup because the process working directory is not guaranteed.
PROJECT_DIR = Path(__file__).resolve().parent
os.chdir(PROJECT_DIR)

# When running as a frozen executable, also add the executable directory
# to the Python path for bundled imports.
if getattr(sys, 'frozen', False):
    sys.path.insert(0, str(Path(sys.executable).resolve().parent))

# Add project root to path.
sys.path.insert(0, str(PROJECT_DIR))

def main():
    """Main entry point."""
    # Import here so PyInstaller can bundle everything
    from main import main as jarvis_main
    jarvis_main()


if __name__ == "__main__":
    main()