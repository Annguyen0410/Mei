# Mei — Architecture & Upgrade Guide

This document describes the current code structure and the **extension points** so future
features can be added without touching code all over the place. Read it alongside `README.md`.

---

## 1. Layers

```text
browser.py / litebrowser/main.py     Entry: profile + QApplication + 2 AppShell
        │
litebrowser/ui/                       UI layer (PyQt5 / PyQt6 via qt_compat shim)
   ├─ app_shell.py                    Master shell: rail + omnibar + insight panel
   ├─ main_window/window.py           SearchWindow (main browser)
   ├─ personal_window.py              Personal Hub (Notes/Tasks/Calendar/Boards/Files/Sites)
   ├─ ai_window.py                    AI Workspace
   ├─ shell/pages.py                  Home / Library / Settings / History
   ├─ components.py                   Shared design system
   ├─ theme.py                        Palette + QSS (theme + accent)
   └─ dialogs/                        All child dialogs
        │
litebrowser/browser/                  Browser core (independent of the shell)
   ├─ tab_manager.py                  Tab lifecycle + hibernation
   ├─ browser_page.py                 Permissions + Chrome-compat shim + profile scripts
   ├─ new_tab_page.py                 Speed dial (theme-aware)
   └─ adblock.py                      Interceptor: blocklist + HTTPS-only + client hints
        │
litebrowser/services/                 Data layer (never imports Qt widgets)
   ├─ prefs.py (core)                 All getters/setters + registry
   ├─ life_service.py                 Tasks / Events / Boards / Saved pages
   ├─ personal_service.py             Notes (SafeVault) + personal root
   ├─ ai_service.py / retriever.py    RAG index + BM25 (+ cosine embed when Ollama)
   ├─ history_service.py              Activity log + backup/import
   ├─ brief_service.py                Morning Brief (local-first digest)
   ├─ agent_actions.py                AI agent: /agent summary|tasks|review
   ├─ sync_service.py                 Self-hosted sync (push/pull JSON bundle)
   ├─ tab_sets.py                     Save/open tab sets (Search/Personal/AI)
   └─ ...                             download_mgr, password, security, ...
        │
litebrowser/core/                     Foundation: paths, storage, lock, version
```

**Important rule:** `services/` and `core/` must **not** import `ui/`. All data flows through
services; the UI only calls services and renders.

---

## 2. Storage & lock

- All data lives in the profile dir (`runtime_data/profiles/<Name>/`).
- File writes use **atomic writes** (`storage_utils.write_json` / `write_text_atomic`)
  → no risk of corrupting a file mid-write.
- `core/profile_lock.py` is a **per-profile RLock** → services can nest locks safely
  (e.g. `add_task` locks, then calls `history_service.log_event` which locks again).

---

## 3. Extension points

### Add a new search engine
Edit **exactly one place**: `litebrowser/core/prefs.py` → `SEARCH_ENGINES`.
The address bar, new-tab page, and validation update automatically.

### Add a new theme
Add an entry to `theme.PALETTES` (a color dict with all tokens). No QSS edits needed —
`theme.main_qss()` and `theme.palette_tokens()` both read from the palette.

### Add an accent color
Add a `(base, hover, soft, focus)` tuple to `theme.ACCENTS`.

### Add a slash command
In `app_shell.py`:
1. Add a suggestion to `_omnibar_completer` and `_command_hints`.
2. Handle it in `_handle_omnibar_text`.

Current slash commands: `/home /browser /history /ai /personal /library /settings`,
`/note /task /board /save-page /freeze /save-tabs /summarize /brief`,
`/agent summary|tasks|review /group-tabs /sync`.

### Add an extension user-script with match patterns
`litebrowser/browser/extension_patterns.py` parses the `==UserScript==` header (`@match` / `@exclude`)
of `.js` files in `Extensions/`. Adding a new pattern = edit this module + make sure the inject
loop (`window.py`) calls `should_inject_for_url`.

### Add a data source for self-hosted sync
`sync_service.py` — add the entity to the bundle builder + merge (last-writer-wins by `updated_at`).
Endpoints: `POST {base}/api/sync/push` + `GET {base}/api/sync/latest`. Sample server: README → Self-hosted sync.

### Add a workspace app / AI provider
- Workspace: `workspace_manager.py` + `app_shell.nav_sections`.
- AI provider: `ai_service.py` + `ai_window.cmb_provider` (data = key).

### Add a new indexed data type for AI
`ai_service.collect_docs()` — add the source and the retriever indexes it automatically.

---

## 4. Important flows

- **Startup**: `main.py` → select/ensure profile → `ensure_dual_workspaces` → 2 `AppShell`s.
- **New tab**: `SearchWindow.add_new_tab` → `tab_manager.add_tab` → `get_new_tab_html` (theme-aware).
- **App close**: `closeEvent` saves the session (tabs + recently_closed) → `_auto_save_tab_set`.
- **AI ask**: shell → `ai_window.ask_with_context` → `ai_service.answer_query` (thread pool).
- **Boards**: `PersonalWindow` → `QGraphicsScene` (StickyCardItem + InkStrokeItem + EdgeItem)
  → `life_service.update_board`.

---

## 5. Upgrade roadmap

| Item | Status | Notes |
|---|---|---|
| Search engine registry | ✅ Done (5.1) | single source of truth |
| `_format_ts` util | ✅ Done (5.1) | `core/time_utils.py` |
| Boards node-edge link | ✅ Added (5.1) | Link mode + EdgeItem |
| Rename "sync-ready" → local snapshot | ✅ Done (5.1) | honest UI |
| Merge Guide/Control Center | ✅ Ready | only one `show_browser_control_center` |
| Password manager export/import | ⏳ Not yet | depends on `cryptography` |
| Update service wired to a real URL | ⏳ Not yet | set env `LITEBROWSER_UPDATE_METADATA_URL` |
| Standardize 3 tab-set types | ⏳ Not yet | Search/Personal/AI differ slightly |
| Morning Brief (6.0) | ✅ Done | `brief_service.py` + Home card + `/brief` |
| AI Agent actions (6.0) | ✅ Done | `/agent summary/tasks`; `/agent review` (6.2) |
| Tab groups by domain (6.0) | ✅ Done | assign group + `group:` filter + `/group-tabs` |
| Semantic retrieval (5.5) | ✅ Done | cosine blend when Ollama, BM25 fallback |
| Extension match pattern (5.5) | ✅ Done | `extension_patterns.py` |
| Self-hosted sync (6.2) | ✅ Done | `sync_service.py` + Settings card + sample server |
| Tab Groups drag-drop + Split view | ⏳ Not yet | needs GUI testing (pure Qt UI) |
| Chromium engine upgrade (PyQt6-WebEngine 6.9/6.10) | ⏳ Not yet | big migration, needs GUI regression |

---

## 6. Quick checks

```bat
cd /d "D:\Code folder\new browser\new browser"
.venv\Scripts\python.exe -m py_compile litebrowser\core\*.py litebrowser\services\*.py litebrowser\browser\*.py litebrowser\ui\*.py litebrowser\ui\main_window\*.py litebrowser\ui\shell\*.py litebrowser\ui\dialogs\*.py
.venv\Scripts\python.exe browser.py
```
