@echo off
cd /d "%~dp0"
REM Build a single-file Windows .exe of Mei with PyInstaller.
REM Run this inside the project folder. PyInstaller is already installed in .venv.

set PY=.venv\Scripts\python.exe
if not exist .venv\Scripts\python.exe set PY=python

echo Building Mei.exe ...
"%PY%" -m PyInstaller ^
  --onefile ^
  --windowed ^
  --icon=icon.ico ^
  --name="Mei" ^
  --add-data "icon.png;." ^
  --add-data "web_support\boitoan;web_support\boitoan" ^
  --collect-all cryptography ^
  --collect-all segno ^
  --collect-all PyQt6.QtWebEngineCore ^
  --collect-all PyQt6.QtWebEngineWidgets ^
  --collect-all PyQt6.QtWebChannel ^
  --exclude-module PyQt5 ^
  browser.py ^
  --clean

echo.
echo Creating dist\web_support (large offline sites live here, next to the exe) ...
if not exist "dist\web_support" mkdir "dist\web_support"
xcopy /e /i /q /y "web_support" "dist\web_support" >nul

echo.
echo -----------------------------------------------------
echo  Done. Two things you must ship together:
echo    -  dist\Mei.exe
echo    -  dist\web_support  (folder, keep beside the .exe)
echo
echo  web_support is NOT bundled into the exe on purpose
echo  (it is ~600 MB; the app loads it from beside the exe).
echo -----------------------------------------------------
echo.
pause