@echo off
cd /d "%~dp0"
REM Prefer the project virtualenv so dependencies are found first.
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" browser.py
) else (
    python browser.py
)
pause