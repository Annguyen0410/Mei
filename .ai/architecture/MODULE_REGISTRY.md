# Module registry

Verified against the working tree at `a74ec98+`. "Public interface" means the functions
other modules actually call, not every symbol.

## Core (`litebrowser/core/`)

| Module | Responsibility | Key interface | Notes / limits |
|---|---|---|---|
| `app_paths.py` | Profile + data paths, workspace chain manifest | `downloads_dir`, `browser_data_path`, `favicon_dir` | Chain manifest ships as package data |
| `prefs.py` | Every stored preference; one JSON file | `get_*`/`set_*` pairs, `load_prefs`, `save_prefs` | All writes go through `profile_transaction` |
| `store.py` + `migrations.py` | Versioned JSON stores with stepwise upgrades | `read_store`, `write_store`, `StoreSpec` | Newer-version files are never downgraded |
| `storage_utils.py` | Atomic JSON/text writes, checked reads | `read_json`, `write_json`, `write_text_atomic`, `read_json_checked` | Used by every store |
| `profile_lock.py` | Per-profile re-entrant lock | `profile_locked`, `profile_transaction` | Prevents cross-thread corruption |
| `secret_store.py` | OS-protected credentials | `get_secret`, `set_secret`, `adopt`, `status` | DPAPI on Windows; 0600 elsewhere; no silent plaintext fallback |
| `engine_security.py` | Minimum Qt security patch floor | `MIN_SECURITY_VERSION` | Consumed by `tools/check_engine_security.py` |
| `update_keys.py` / `app_version.py` / `product.py` | Update identity and signing pins | `pinned_keys`, `APP_VERSION`, `PRODUCT_ID` | Release signing is separate (`docs/RELEASE_SIGNING.md`) |
| `log.py` | Logging + secret redaction hooks | `get_logger`, redaction via `secret_store.known_secret_values` | Never log credentials |
| `time_utils.py`, `greetings.py`, `theme_data.py`, `storage_catalog.py`, `storage_health.py` | Shared helpers | — | `storage_catalog` is the backup allowlist |

## Browser (`litebrowser/browser/`)

| Module | Responsibility | Key interface | Notes / limits |
|---|---|---|---|
| `tab_manager.py` | Tab create/close/duplicate/split/hibernate, session restore | `add_tab`, `close_tab_item`, `_build_browser`, `_dispose_browser` | Owns incognito profile lifecycle |
| `browser_page.py` | Permission decisions, navigation policy, profile scripts, lifecycle | `BrowserPage(profile, view, base_dir, host)` | Deny-by-default; no persistence for OTR |
| `adblock.py` | Request interceptor: blocklist + `@@` exceptions, HTTPS upgrade, Client Hints, shield | `TrackingBlocker`, `load_filter_file`, `fetch_and_update_subscriptions` | EasyList subset (see compat matrix) |
| `engine_identity.py` | Truthful UA + sign-in-only Client Hints | `build_user_agent`, `is_sign_in_host`, `client_hint_headers` | No JS fingerprint spoofing |
| `local_content_policy.py` | Which `file://` documents may load | `is_trusted_local_document` | Used by `acceptNavigationRequest` |
| `extension_patterns.py` | Userscript match patterns | `match_pattern` | Pure functions |
| `new_tab_page.py` | Speed dial HTML | `build_new_tab_html` | Reads history/bookmarks |
| `hibernation_policy.py` | When a tab may be discarded | `hibernate_block_reason` | Refuses private/audio/downloading/recent |

## Services (`litebrowser/services/`)

| Module | Responsibility | Key interface | Notes / limits |
|---|---|---|---|
| `history_service.py` | **Single** activity/browser-history store + backup/export | `log_event`, `list_activity`, `clear_activity`, `export_profile_payload` | `activity_history.json`; bounded |
| `download_mgr.py` | Download records with full lifecycle metadata | `add_download`, `update_status`, `load_list` | `downloads.json`; additive fields |
| `safe_http.py` | Validated outbound HTTP | `fetch`, `normalize_http_url`, `resolve_public_addresses` | Direct-only; refuses configured proxy |
| `password_manager.py` | Encrypted vault + autofill/capture scripts | `save_passwords`, `load_passwords_status`, `add_password` | PBKDF2 390k + Fernet; legacy migration |
| `extension_bridge.py` | Import window/tab batches from the extension | `import_from_file`, `import_from_zip`, `upsert_batch` | JSON/zip bounds; no path extraction |
| `android_bridge_service.py` | Loopback HTTP bridge for MeiRemote | `AndroidBridgeService`, token auth | Loopback-only, token stored in `secret_store` |
| `open_request.py` | Desktop side of "open this URL from Android" | `read_requests`, `clear_requests` | Drained by a 2.5 s timer |
| `workspace_manager.py` | Workspace ID list + current ID | `load`, `add_workspace`, `set_current_id` | UI grouping inside one profile |
| `tab_sets.py` | Saved tab/research collections (v4) | `load_tab_sets`, `save_tab_sets` | Versioned store with migrations |
| `page_monitor.py` | Watch public pages for changes | `normalize_url`, `check_monitors` | `safe_http` only; no JS pages |
| `backup_service.py`, `encrypted_backup_service.py`, `restore_service.py`, `record_restore_service.py`, `integrity_service.py`, `recovery_service.py` | Backup/restore + conflict recovery | `create_backup`, `restore`, … | Explicit allowlist (`storage_catalog`); secrets excluded |
| `sync_service.py`, `sync_folder.py` | Self-hosted/folder sync bundles | `push`, `pull` | Credentials never sync |
| `diagnostics.py`, `engine_diagnostics.py` | Support reports | `collect`, `build_report` | Redacted; no secrets/paths of other profiles |
| `ai_service.py`, `retriever.py`, `agent_actions.py` | AI providers + local RAG | `answer`, `index`, `retrieve` | Context is opt-in; private pages excluded |
| Domain services | Notes, tasks, calendar, boards, flashcards, study plans, RSS, Anki | `life_service`, `personal_service`, … | All JSON, all locked/atomic |

## UI (`litebrowser/ui/`)

| Module | Responsibility | Notes |
|---|---|---|
| `app_shell.py` | Rail + omnibar + embedded windows, page routing, notifications | Composes `SearchWindow`, `PersonalWindow`, `AIWindow` |
| `main_window/window.py` | Browser window composition, profile config, cookie policy, session save/restore | 4.1k lines; mixins below hold concerns |
| `main_window/window_tools.py` | Find bar, downloads, password capture | Download lifecycle owner |
| `main_window/window_topbar.py` | Address bar, nav, engine pill | — |
| `main_window/window_menus.py` | Menus and session actions | — |
| `main_window/docking.py` | Panel/dock layout | — |
| `shell/pages.py` | Home / Library / Settings / History pages | 3.4k lines |
| `personal_window.py` | Personal hub UI | 5.4k lines |
| `ai_window.py` | AI workspace UI | — |
| `dialogs/*` | All dialogs | `profiles_privacy.py` owns privacy controls |
| `theme.py`, `components.py`, `icons.py` | Design system | — |

## Tests

121 test modules. Structural gates: `test_architecture_boundaries.py`,
`test_qt_facade.py`, `test_capability_ledger.py`, `test_command_registry.py`,
`test_brand_consistency.py`. Security-relevant suites: `test_safe_http.py`,
`test_critical_safety.py`, `test_password_manager.py`, `test_profile_storage_safety.py`,
`test_session_state.py`, `test_release_hardening.py`, `test_hardening_2026.py`.
