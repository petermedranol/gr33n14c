@echo off
REM Greeniac live video gateway (GPU HLS). Auto-restarts; single-instance guarded in Python.
cd /d "%~dp0"
:loop
".venv\Scripts\pythonw.exe" -u gateway.py
ping -n 6 127.0.0.1 >nul
goto loop
