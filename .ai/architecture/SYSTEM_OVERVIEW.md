# System overview

## What Mei is

A desktop web browser built on **Qt WebEngine** (Chromium), plus two product surfaces that
share the same profile storage: a Personal hub (notes, tasks, calendar, boards, study
planning, flashcards) and an AI workspace. An Android app (**MeiRemote**) and a browser
extension (**`Extensions/`**) drive the browser through narrow bridges; both are clients,
not alternate engines.

## Runtime stack (verified on this machine)

| Component | Version |
|---|---|
| Python | 3.11.9 |
| PyQt6 / Qt | 6.11.0 / 6.11.0 |
| Chromium (engine) | 140.0.7339.225 |
| Qt security patch stream | 146 (floor 146, gated by `tools/check_engine_security.py`) |
| Legacy canary | PyQt5 5.15.11 / Qt 5.15.2 (CI only, never shipped) |
| Packaging | PyInstaller 6.19.0 (`Mei.spec`, `installer.iss`) |

## Layers

```text
browser.py / litebrowser/main.py   process entry: QApplication, profile, AppShell window(s)
        │
litebrowser/qt.py                  Qt façade (PyQt5/PyQt6 selected by qt_compat.py)
        │
litebrowser/ui/                    shell, main window, hubs, dialogs, theme
        │
litebrowser/browser/               tabs, pages, permissions, interceptor, new-tab page
        │
litebrowser/services/              persistence + business logic (no Qt widgets)
        │
litebrowser/core/                  paths, atomic JSON storage, lock, prefs, migrations, secrets
```

Import direction is enforced: `core` ← `services` ← `browser`/`ui`; `ui` may import
`browser`; `services` may not import `browser`; nothing below `ui` imports `ui`.

## Profile model

- Every window belongs to a **profile directory** (`base_dir`), and to a shell **slot**
  (`primary`, `secondary`, or `shared`) via `SearchWindow._shell_slot`.
- The main window creates one `QWebEngineProfile` named `MeiProfile-<slot>`, configured by
  `SearchWindow._configure_web_profile` (storage paths, cache, UA, settings, password
  capture script, download wiring, cookie policy).
- **Incognito is a real off-the-record profile**, created per private tab by
  `TabManager._build_browser`: `NoPersistentCookies` + `MemoryHttpCache`, its own
  interceptor, no password-capture script, no permission persistence, and no hibernation.
  It is destroyed with the tab (`TabManager._dispose_browser`).
- Workspaces are **UI groupings inside one profile** (tab metadata + `prefs.workspaces`),
  not profiles. Do not treat the identifiers as interchangeable (see ADR-0005 note in
  `memory/TECHNICAL_DEBT.md`; the mapping is string IDs, not typed handles).

## Major subsystems

| Subsystem | Owner |
|---|---|
| Window lifecycle, menus, topbar | `ui/main_window/*` mixins + `window.py` |
| Shell/rail/home/library/settings | `ui/app_shell.py`, `ui/shell/pages.py` |
| Tab create/close/reorder/hibernate | `browser/tab_manager.py` |
| Page policy (permissions, navigation, local files) | `browser/browser_page.py`, `browser/local_content_policy.py` |
| Network policy (blocklist, HTTPS-only, hints, cookies) | `browser/adblock.py`, `window._apply_cookie_policy` |
| Downloads | `ui/main_window/window_tools.py`, `services/download_mgr.py` |
| Activity history / browser history | `services/history_service.py` |
| Storage + migrations | `core/store.py`, `core/migrations.py`, `core/storage_utils.py` |
| Secrets | `core/secret_store.py` (DPAPI/file) |
| Password vault | `services/password_manager.py` (PBKDF2 + Fernet) |
| Outbound fetch policy | `services/safe_http.py` |
| Android bridge | `services/android_bridge_service.py`, `services/open_request.py` |
| Extension import bridge | `services/extension_bridge.py`, `browser/extension_patterns.py` |

## Application lifecycle (verified flow)

1. `litebrowser/main.py` sets Chromium flags (including the proxy flag when configured),
   creates `QApplication`, resolves/creates the profile, applies the single-instance lock.
2. `AppShell` builds the rail and embeds `SearchWindow`; `SearchWindow.__init__` builds
   menus, the main profile, the interceptor, the tab manager and timers.
3. Timers: audio indicator (5 s), memory saver (30 s), Android open-request drain (2.5 s),
   session autosave (5 min), adblock subscription refresh (background).
4. Navigation creates `BrowserPage`, which applies permission policy and scripts.
5. Shutdown: `closeEvent` saves session state, stops threads, releases profiles.

## Security boundaries in one sentence each

- Page JavaScript is untrusted; app logic never evaluates page-provided strings.
- Profile storage is the isolation unit; private profiles must leave no trace.
- `file://` content is third-class: only trusted folders may load, and only
  `LocalContentCanAccessRemoteUrls` is enabled (never `FileUrls`).
- Outbound app fetches (`safe_http`) connect to an already-validated public IP and refuse
  to bypass a configured proxy.
- Credentials are protected by the OS (DPAPI on Windows) or owner-only permissions; the
  password vault is encrypted at rest with PBKDF2-SHA256 (390k) + Fernet.
