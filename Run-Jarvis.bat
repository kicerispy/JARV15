@echo off
setlocal

cd /d "%~dp0"

REM Activate the jarvis_cuda virtual environment if it exists
if exist "jarvis_cuda\Scripts\activate.bat" (
    call "jarvis_cuda\Scripts\activate.bat"
)

REM Run JARVIS
python main.py

endlocal