# Run & Build MeiBrowser (Desktop App)This guide is specifically about **running** and **packaging** MeiBrowser
as a desktop app (.exe on Windows). For code / architecture content, see `README.md` and `ARCHITECTURE.md`.

---

## 1. Requirements

- **Python 3.11+** (Windows Store or python.org both work).
- The repo already ships a virtual environment: **`.venv`** (contains PyQt5, PyQt6, QtWebEngine,
  cryptography…). If you don't have `.venv` yet, recreate it:
  ```powershell
  python -m venv .venv
  .\.venv\Scripts\python.exe -m pip install -r requirements.txt
  ```
  > Note: prefer `python -m pip` over `pip.exe` — the venv's `pip.exe` sometimes has a broken
  > path (the `Fatal error in launcher` error). `python -m pip` always works.

- The app runs on both PyQt5 and PyQt6 (shim `litebrowser/qt_compat.py`). When PyQt6-WebEngine
  is installed (Qt 6.8 → Chromium 122) the app uses it; otherwise it falls back to PyQt5.

---

## 2. How to run the app

> **Important**: the project lives in the folder that contains `browser.py`, `run.bat`, `.venv`.
> If you are standing in the *parent* folder (e.g. `D:\Code folder\new browser\` while the project
> is at `D:\Code folder\new browser\new browser\`), `cd` into the actual project folder first.

### Way 1 — batch file (simplest)
```powershell
cd ".\new browser"        # enter the project folder
.\run.bat
```
`run.bat` prefers `.venv\Scripts\python.exe browser.py`; without a venv it falls back to `python`.

### Way 2 — run Python directly (PowerShell)
```powershell
cd ".\new browser"
.\.venv\Scripts\python.exe browser.py
```

### Way 3 — absolute paths (no cd needed)
```powershell
& "D:\Code folder\new browser\new browser\.venv\Scripts\python.exe" "D:\Code folder\new browser\new browser\browser.py"
```

### Way 4 — run as a module
```powershell
.\.venv\Scripts\python.exe -m litebrowser
```

---

## 3. Common run errors

| Symptom | Cause / fix |
|---|---|
| `Fatal error in launcher: Unable to create process using '...\pip.exe'` | The venv's `pip.exe` has a broken path. Use `python -m pip` instead. |
| `python.exe: can't open file '...browser.py': No such file or directory` | You are in the wrong folder. The project is in the folder containing `browser.py`. |
| `Set-Location: A positional parameter cannot be found...` | You are using **cmd** syntax (`cd /d`) in **PowerShell**. Use `cd "..."` (no `/d`). |
| `.venv\Scripts\python.exe : The term ... is not recognized` | Missing `.\` prefix in PowerShell. Type `.\ .venv\Scripts\python.exe` (no space). |
| App opens but the screen is white / renderer crashes | GPU driver issue. Run with `set LITEBROWSER_SOFTWARE_RENDERING=1` then rerun (software rendering). |
| Want to see JS logs from the web | `set LITEBROWSER_DEBUG_JS=1` before running. |

---

## 4. Post-launch testing checklist

The app opens **two windows** (primary + secondary), each with its own browser workspace. Quick checks:

1. **New-tab page** — Ctrl+T: café awning, CSS coffee cup + steam, menu cards, hint chips.
2. **Theme** — Settings → Interface → change Theme (Latte/Minimal/Café…) + Accent, press Apply.
3. **Tabs** — open several tabs, hover to see the MB bubble, `is:sleeping`/`site:`/`group:` filters work, `Ctrl+Tab` cycles.
4. **Morning Brief** — Home shows the digest card; `/brief` opens the popup.
5. **AI** — `/agent summary` (tabs → note), `/agent tasks a | b`, `/agent review`.
6. **Sync** — run the sample `sync_server.py` (see README → Self-hosted sync), Settings → Self-hosted sync → Sync now.
7. **Google sign-in** — visit `accounts.google.com`; the chrome-compat layer should avoid the block screen.

---

## 5. Build the desktop app (.exe) with PyInstaller

PyInstaller is already in `.venv` (check: `.\ .venv\Scripts\python.exe -m PyInstaller --version`).

### 5.1 One-file build (single .exe)
```powershell
.\.venv\Scripts\python.exe -m PyInstaller --onefile --windowed --icon=icon.ico --name="Mei" `
  --collect-all PyQt6.QtWebEngineCore `
  --collect-all PyQt6.QtWebEngineWidgets `
  --collect-all PyQt6.QtWebChannel `
  browser.py
```
- `--onefile`: bundle into a single exe file.
- `--windowed`: no console window.
- `--collect-all PyQt6.*`: pull in all QtWebEngine resources (bin, translations, icu…) —
  **mandatory**; without it the exe fails to initialize WebEngine.
- Result: `dist/Mei.exe`.

> If your machine only has PyQt5 (no PyQt6), replace the `--collect-all PyQt6.*` lines with
> `PyQt5.QtWebEngineCore`, `PyQt5.QtWebEngineWidgets`, `PyQt5.QtWebChannel`.

### 5.2 Folder build (faster, easier to debug)
```powershell
.\.venv\Scripts\python.exe -m PyInstaller --windowed --icon=icon.ico --name="Mei" `
  --collect-all PyQt6.QtWebEngineCore `
  --collect-all PyQt6.QtWebEngineWidgets `
  --collect-all PyQt6.QtWebChannel `
  browser.py
```
- Result: `dist/Mei/` (exe + DLLs + resources). Run `dist\Mei\Mei.exe`.
- You can zip this folder for distribution.

### 5.3 Put the app on the desktop (icon on screen) — like Electron

Electron's approach = 1 exe file + a **desktop shortcut with an icon**. PyInstaller handles the exe;
the shortcut script is included:

```powershell
powershell -ExecutionPolicy Bypass -File .\create_desktop_shortcut.ps1
```

The script creates `Mei.lnk` on the Desktop, pointing at `dist\Mei.exe`, with the
icon from `icon.ico`. To also pin it to the Taskbar: right-click the shortcut → **Pin to taskbar**.

### 5.4 A “real installer” (like an Electron app installer)

If you want a proper installation (Start Menu + desktop shortcut + uninstaller), use
**Inno Setup** (free: https://jrsoftware.org/isinfo.php). A script is already included:

```powershell
# after installing Inno Setup, open a Command Prompt in the project folder:
"C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer.iss
```

Result: **`dist\MeiSetup.exe`** — running it installs Mei into
`Program Files\Mei` (with the `web_support` folder), creates Start Menu + desktop
shortcuts automatically, and provides an uninstaller in Control Panel.

### 5.5 After building
- App data (profile, notes, BrowserData…) is created **outside the exe**:
  - running from source: `runtime_data/profiles/...`
  - running the exe: `%LOCALAPPDATA%\Mei\runtime_data/profiles/...`
- If the exe won't open the web: run it from a console (`dist\Mei\Mei.exe`) to see
  the error, and re-check the WebEngine `--collect-all` flags.
- To silence PyInstaller prompts during the build, add `--noconfirm`, and set `--version-file`
  (optional) to attach a version to the exe.

---

## 6. Related structure summary

```text
browser.py                  ← entry: calls litebrowser.main.main()
run.bat                     ← quick launcher (prefers .venv)
litebrowser/main.py         ← QApplication + 2 AppShell + proxy flag
litebrowser/qt_compat.py    ← PyQt5 → PyQt6 shim
litebrowser/core/app_paths.py ← runtime_data / profile locations
litebrowser/core/app_version.py ← APP_VERSION (currently: 6.4.0)
build_exe.bat                ← one-click PyInstaller exe build
create_desktop_shortcut.ps1 ← create an icon desktop shortcut
installer.iss               ← Inno Setup: real installer (MeiSetup.exe)
```

---

## 7. Quick “make a desktop app” summary

```text
1. .\build_exe.bat                        → dist\Mei.exe (+ dist\web_support)
2. powershell -ExecutionPolicy Bypass -File .\create_desktop_shortcut.ps1
                                          → Mei icon on the Desktop
3. (optional, for a “real install”) ISCC.exe installer.iss → dist\MeiSetup.exe
```
