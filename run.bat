@echo off
cd /d "%~dp0"
call jarvis_cuda\Scripts\activate.bat
python main.py
