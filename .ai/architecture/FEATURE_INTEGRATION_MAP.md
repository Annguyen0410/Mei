# Feature integration map

Each entry lists what a change to that feature can affect. Use it to decide which tests
and documents a change needs.

```text
Tab management
 ├── QWebEngineProfile (normal or off-the-record)
 ├── BrowserPage (permissions, navigation policy, scripts)
 ├── History (browser-visit events)
 ├── Downloads (profile-bound signal)
 ├── Session state + tab sets + recently closed
 ├── Hibernation policy (count, audio, private, pinned)
 └── Workspace filter (tab metadata)
```

| Feature | Owns | Depends on | Breaks if changed carelessly |
|---|---|---|---|
| Tab create/close/duplicate | `TabManager` | profile, interceptor, page, workspace ID | history, session restore, hibernation counts |
| Incognito | per-tab OTR profile | OTR storage policy, permission policy, download privacy flag | session/tab-set leakage, cookie isolation, AI context |
| Split view | tab manager + docking | tab metadata, workspace filter | session restore, tab counts |
| Workspace switching | `workspace_manager` + tab metadata | `prefs.workspaces` | session restore, saved collections |
| Navigation policy | `BrowserPage.acceptNavigationRequest` | `local_content_policy`, scheme rules | local file access, chain apps |
| Request policy | `TrackingBlocker` | prefs, filter cache, subscriptions, engine identity | every site's behaviour, privacy headers |
| Downloads | `WindowToolsMixin` + `download_mgr` | profile, history, notifications, hibernation count | sidebar, AI index, backup |
| History | `history_service` | every domain service that logs events | History page, Home, AI index, privacy cleanup |
| Reading/progress + monitor | `page_monitor`, history | `safe_http`, activity log | toasts, duplicates |
| Favicons | engine `iconChanged` → `tab_manager` | `prefs.favicon_cache_dir` | tab rows, new tab page |
| Password vault | `password_manager` | `cryptography`, profile lock, capture script | autofill, login, backup exclusion |
| Permissions | `BrowserPage` | prefs, OTR state | site functionality, privacy |
| Proxy/VPN hub | `main._apply` flags + `vpn_hub` | Chromium startup flags | every request; requires restart |
| Android bridge | `android_bridge_service` + `open_request` | token, loopback, profile | mobile link, file ingest |
| Extension import | `extension_bridge` | tab manager, zip bounds | workspace creation |
| AI context | `ai_service`, `retriever` | history, downloads, notes, private exclusion | privacy, provider calls |
| Backup/restore | `backup_service`, `storage_catalog` | every owned store | data loss, secret leakage |
| Session restore | `window` + `prefs.session_state_*` | tabs, workspaces, privacy flags | startup crashes, private leakage |

## Cross-cutting rules

1. Every feature that persists something **must** define its behaviour for an OTR profile.
2. Every feature that logs activity goes through `history_service` with a typed `kind`.
3. Every feature that reads a user-editable file validates shape and bounds.
4. Every feature that talks to the network either uses Chromium (page traffic) or
   `safe_http` (app traffic). There is no third transport.
5. Every new persisted shape is additive or versioned; backups must still restore.
