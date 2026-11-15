# Data flow (storage, events, lifecycle)

All stores are per-profile JSON under the profile directory, written atomically while
holding the profile lock. There is no central database by design; `startup` reads are
bounded and every reader treats a malformed file as "skip this row", not "crash".

## Store ownership

| Data | File | Owner (only writer) | Readers |
|---|---|---|---|
| Preferences | `prefs.json` | `core/prefs.py` | everything |
| Browser/activity history | `activity_history.json` | `services/history_service.py` | History page, Home, AI index, backup, cleanup |
| Download records | `downloads.json` | `services/download_mgr.py` | sidebar, Navigation dialog, AI index, backup |
| Permissions | `permissions.json` | `core/prefs.py` (via `browser_page`) | permission prompts |
| Session state | `session.json` | `core/prefs.session_state_save` | restore/autosave |
| Workspaces | `workspaces.json` | `services/workspace_manager.py` | tab desk filter |
| Tab sets / research collections | `tab_sets.json` (v4 store) | `services/tab_sets.py` | Sessions & Spaces |
| Notes / tasks / calendar / boards | `personal_service`, `life_service` files | respective services | hubs, AI, backup |
| Flashcards, study plan, sessions | per-service JSON | respective services | study surfaces |
| Vault | `SafeVault/passwords.enc` | `services/password_manager.py` | vault UI, autofill |
| Secrets | `secrets.dat` | `core/secret_store.py` | AI key, sync token, bridge token, proxy password |
| Filters cache | `adblock_cache/*.txt` | `browser/adblock.py` | interceptor |
| Watch list | `monitors.json` | `services/page_monitor.py` | page monitor |
| Extension imports | `extension_imports.json` | `services/extension_bridge.py` | tab import UI |
| Favicons | `favicons/*.png` | engine (`iconChanged` → file) | tab rows, new tab |
| Logs | `logs/` | `core/log.py` | diagnostics |

Secrets are **excluded** from backups, sync, and AI indexing (see `storage_catalog.py`).

## Flow: navigation → history

```text
user types/loads URL
  → BrowserPage.acceptNavigationRequest (local-file + scheme policy)
  → engine navigates
  → SearchWindow.on_url_changed / loadFinished
  → history_service.log_event(base_dir, "browser-visit", title, url, {...})
  → activity_history.json (bounded, atomic, locked)
  → Home speed dial / History page / AI index read the same file
```

Private tabs: `BrowserPage` refuses to persist permissions for an OTR profile, and
session/tab-set payloads skip tabs whose privacy state cannot be verified. Downloads
were the exception; see F-20 in `../security/SECURITY_FINDINGS.md` (fixed).

## Flow: download

```text
engine downloadRequested
  → profile-bound handler (SearchWindow.handle_download_request, private flag bound per profile)
  → user confirms → setPath/accept
  → _record_download: skip for OTR, else download_mgr.add_download(...)
      → downloads.json row (id, url, path, filename, status, mime_type,
        total_bytes, received_bytes, started_at, finished_at=0)
      → history_service.log_event("download", ...)
  → stateChanged/finished → _finalize_download (once per download)
      → update_status(status, bytes) → finished_at stamped once
      → counter decrement (hibernation resumes)
      → toast + system notification on completion
```

## Flow: cookie policy

```text
Privacy toggle / startup (_load_block_third_party_cookies_pref)
  → _apply_cookie_policy
      → one filter callable (allow sign-in hosts, else !thirdParty)
      → installed on the main profile AND every incognito profile
      → new incognito profile gets it at creation (TabManager._build_browser)
```

## Flow: request policy

```text
every request → TrackingBlocker.interceptRequest
  1. sign-in host?  (engine_identity.is_sign_in_host) → compat headers only if opt-in
  2. challenge host? → skip DNT/GPC/upgrade/blocklist
  3. else → DNT/Sec-GPC, strip low-entropy Client Hints (unless sign-in host)
  4. https-only upgrade (not for challenge/localhost)
  5. distraction shield → block
  6. blocklist ∪ subscription rules, minus @@ exceptions → block
```

## Flow: app-level outbound fetch (monitor, filters)

`safe_http.fetch` normalizes the URL, resolves every address and refuses any non-public
answer, connects to the pinned IP with the hostname kept for `Host`/SNI, re-validates
each redirect, caps bytes/time/redirects, and refuses to run when a proxy is configured
unless the caller explicitly chose direct.

## Lifecycle notes

- Timers are parented to the window; autosave reuses the close-event payload.
- Incognito profiles are deleted with their tab; their interceptor is removed from the
  window list.
- Closing a window persists session state, stops workers, and releases profiles.
- A crash still leaves the last 5-minute autosave and the atomic store write.
