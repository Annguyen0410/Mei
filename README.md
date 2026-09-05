# Mei Tea Room Edition

Mei is a multi-workspace desktop shell built on **PyQt5/PyQt6 + QtWebEngine** (both runtimes work through the `litebrowser/qt_compat.py` shim). It is more than a browsing window: a café-themed workspace that wraps a full Chromium browser, a Personal Hub, an AI workspace, and a library — all under one roof.

> **Quick links**
> - 🚀 Run & package the app → [`RUN_AND_BUILD.md`](RUN_AND_BUILD.md)
> - 🧭 Use the app day-to-day → [`docs/USER_GUIDE.md`](docs/USER_GUIDE.md)
> - ⌨️ Every slash command & shortcut → [`docs/COMMAND_REFERENCE.md`](docs/COMMAND_REFERENCE.md)
> - 🏗️ Code architecture → [`ARCHITECTURE.md`](ARCHITECTURE.md)
> - 📜 Release history → [`docs/CHANGELOG.md`](docs/CHANGELOG.md)

---

## What's inside

**Seven workspaces**, switched from the left navigation rail (or `Ctrl+1` … `Ctrl+7`):

| Workspace | What it does |
|---|---|
| 🏠 **Home** | Dashboard: greeting, "Your Week" activity chart, quick launch tiles, recent notes/tasks |
| 🌐 **Browser** | Full Chromium engine — tab desk with workspace tabs, tab groups, split view, web panels, adblock, VPN/proxy, tab hibernation & memory saver |
| 🕐 **History** | Browsing history, searchable, open in new/background tabs |
| ✨ **AI** | RAG local assistant, OpenRouter, local LLMs (Ollama / llama.cpp); password-gated |
| ◧ **Personal** | Overview (focus streak heatmap), Notes (wiki-links, neural graph), Tasks, Review (SM-2 flashcards), Calendar, Boards, Files, Sites; password-gated |
| 📚 **Library** | Saved pages, bookmarks, downloads, reading list, RSS feeds |
| ⚙️ **Settings** | Theme/accent picker, VPN, privacy & permissions, profiles, routines, extensions |

### 🔍 The omnibar & feature finder

The search box at the top is the command center:

- Type a **URL or web query** → press Enter to search.
- Type **any letters** (e.g. `b`) → a live list drops down with every matching feature — workspaces, Personal pages, sites, slash commands (`B` → Browser, Bí Mật, Bói Toán, Boards…). Enter or click jumps straight there; `↑`/`↓` move, `Esc` closes. It works for every letter — a single letter with no match shows the whole list so you can browse.
- Protected workspaces (**AI / Personal**) prompt for the passcode first, then enter automatically.
- Type a **slash command** (e.g. `/task Buy milk`) → autocomplete + run.

### ✂️ Text is copyable everywhere

Every label in the app is selectable with the mouse (`Ctrl+C` to copy), and every button has a **right-click → “Copy text”** menu.

### 🌱 The café touch

- **16 café themes** with auto day/night pairing and rebalanced accents (`/theme`, `/accent`).
- **Focus pours** (`/focus 25`) with a distraction shield that blocks social/autoplay hosts while you work.
- **Tray & toasts** — quick note, focus timer, VPN status; native Windows notifications.

---

## Quickstart

```powershell
# From the project folder (the one containing browser.py / .venv)
.\run.bat
# or directly:
.\.venv\Scripts\python.exe browser.py
```

The repo ships a `.venv`. To recreate it: `python -m venv .venv`, then
`.\.venv\Scripts\python.exe -m pip install -r requirements.txt`.

> Full run/build instructions, PyInstaller packaging and troubleshooting live in
> [`RUN_AND_BUILD.md`](RUN_AND_BUILD.md).

---

## First steps

1. **Open a workspace** — click the rail icons or press `Ctrl+1…7`.
2. **Find any feature** — click into the search box, type `b`, pick “Browser”.
3. **Add your own sites** — Personal → Sites → “Add site”, or keep the bundled shortcut tiles via “Include bundled sites”.
4. **Study with flashcards** — Personal → Review (or `/review`): browse with `←`/`→`, grade with the SM-2 buttons.
5. **Set the mood** — `/theme espresso-house`, `/accent matcha`.

---

## Project layout

```
browser.py                     Entry point
litebrowser/
  core/        prefs, commands registry, app paths, storage, version
  services/    life service, AI, flashcards, focus, security, sync, …
  ui/          shell (AppShell + pages), browser window, Personal Hub, AI window,
               theme/QSS, dialogs (VPN, profiles, command palette, …)
  browser/     tab manager, new-tab page, page wrapper, adblock, downloads
tests/         pytest suite (run: .\.venv\Scripts\python.exe -m pytest tests/)
```

## Development

- **Run tests:** `.\.venv\Scripts\python.exe -m pytest tests/ -q`
- **Lint:** `.\.venv\Scripts\ruff.exe check litebrowser/ tests/ --select F,E9`
- **Architecture notes:** [`ARCHITECTURE.md`](ARCHITECTURE.md)
- **User guide:** [`docs/USER_GUIDE.md`](docs/USER_GUIDE.md)
- **Command & shortcut reference:** [`docs/COMMAND_REFERENCE.md`](docs/COMMAND_REFERENCE.md)

---

*Mei is its own application. Some shortcut tiles in Personal → Sites link out to
separate web apps that Mei does not contain or depend on.*