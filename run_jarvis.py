"""
JARVIS - Windows Entry Point
This is the main entry point that can be compiled to a .exe with PyInstaller.
"""
import os
import sys
from pathlib import Path

# When running as a frozen executable, set the working directory
if getattr(sys, 'frozen', False):
    # Get the directory where the executable is
    exe_dir = Path(sys.executable).parent
    os.chdir(exe_dir)
    
    # Also add the executable directory to the Python path
    sys.path.insert(0, str(exe_dir))

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

def main():
    """Main entry point."""
    # Import here so PyInstaller can bundle everything
    from main import main as jarvis_main
    jarvis_main()


if __name__ == "__main__":
    main()