@echo off
REM Greeniac Telegram bot (auto-restarts; single-instance guarded in Python).
cd /d "%~dp0"
:loop
".venv\Scripts\python.exe" -u bot.py
ping -n 11 127.0.0.1 >nul
goto loop
