# Dependency graph and coupling

## Allowed directions

```text
ui ──────────────► browser ──────────► services ──────────► core
 │                    │                                        ▲
 └────────────────────┴────────────────────────────────────────┘
```

- `core` imports nothing from the project except `core`.
- `services` may import `core` only.
- `browser` may import `core` only (not `services`).
- `ui` may import all three.
- `tests/test_architecture_boundaries.py` fails on a violation, an orphan module, or a
  stale allowlist entry. Do not add an exemption to make an import compile.

Threading boundary: `services` never creates Qt widgets; background work is passed in as
callbacks (e.g. `download_mgr`, `history_service` are synchronous and lock-protected).

## High-coupling modules (change with care)

| Module | Why it is central | Consequence |
|---|---|---|
| `core/prefs.py` (1.5k lines) | ~200 getters/setters, every subsystem reads it | A new key needs a getter+setter pair and a default; never read `prefs.json` directly |
| `ui/main_window/window.py` (4.1k lines) | Owns QWebEngineProfile, interceptor, cookie policy, session | Touching profile config affects tabs, downloads, permissions, history |
| `ui/app_shell.py` (2.2k lines) | Composes browser + hubs, routes navigation | A service change can surface as a shell crash |
| `browser/tab_manager.py` (1.3k lines) | Tab lifecycle + incognito profiles + hibernation | Must know which profile a tab belongs to at every operation |
| `services/history_service.py` | Every domain service writes activity events through it | Its schema is effectively a cross-feature contract |
| `ui/shell/pages.py` (3.4k lines) | Home/library/settings/history surfaces | Reads most services directly |

## Shared mutable state

`SearchWindow` attributes that more than one subsystem writes:

- `browsers`, `tab_list`, `stack` — tab manager owns them; menus and tools read them.
- `_incognito_profiles` / `_incognito_interceptors` — tab manager creates/destroys;
  `_apply_cookie_policy` iterates them.
- `_active_download_count` / `_finalized_downloads` — download tools own;
  tab manager reads the count to pause hibernation.
- `_cookie_filter` — one callable installed on every profile's cookie store.
- `interceptor` — created by the window, configured by the privacy dialog and prefs.

## Known duplicate/legacy areas

| Area | State |
|---|---|
| Qt bindings | `litebrowser/qt.py` façade is the target; `PyQt5` direct imports remain in the `QT5_ALLOWLIST` (migration list, shrinks only) |
| Qt5 compatibility shims | `qt_compat.py` patches enums/signatures for PyQt5; production uses PyQt6 |
| `legacy/` and `docs/legacy/` | Historical code/docs, not imported by the app |
| Two shells in one process | `AppShell` embeds `SearchWindow`; `browser.py` is the standalone entry. Both end in the same window class |
| History | One store (`activity_history.json`); older audits mentioned a second, but no second writer/reader exists in the tree |

## Cascading-change map

- **Profile configuration** → tab creation, permissions, downloads, cookies, extensions,
  password capture, session restore.
- **`downloads.json` shape** → sidebar panel, Navigation dialog, AI RAG index, backup
  allowlist, Android bridge.
- **`activity_history.json` shape** → History page, Home digest, AI index, backup/export,
  privacy cleanup.
- **Interceptor policy** → every request: blocking, HTTPS upgrade, headers, challenge
  exemptions, shield.
- **Session payload** → restore, recently-closed, tab sets, crash autosave.
