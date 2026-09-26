# Capabilities & the reserved API

This file is the **ledger** for one rule: public API in `litebrowser/` either has a
caller somewhere in the repo, or it is listed here as *reserved* and covered by
`tests/test_reserved_api.py` — otherwise it gets deleted.

Two gates enforce it:

| Gate | Test | What it fails on |
|---|---|---|
| No dead public API | `tests/test_capability_ledger.py` | a public `def`/`class` in `litebrowser/` with no reference anywhere in the package or the tests |
| Reserved API stays honest | `tests/test_reserved_api.py` | a promoted/renamed/removed reserved function, or a behaviour regression in one |

The point of the pairing is that "we kept it for later" is a decision with a test
attached, not a comment nobody re-reads. Adding an entry below is the *only*
accepted alternative to deleting the code.

---

## 1. Live wiring (has a desktop caller)

| Capability | Single source of truth |
|---|---|
| Product identity, version, update channel, asset name | `core/product.py` (re-exported by `core/app_version.py`) |
| Update check / download / verify / install | `services/update_service.py` → `ui/app_shell.py` |
| Slash commands (completion, hints, help dialog) | `core/commands.py` → `app_shell.py`, `ui/dialogs/navigation.py`, `ui/dialogs/shell_palette.py` |
| Bridge action advertising | `services/android_bridge_service.py` (`API_VERSION`) |
| Workspace/chain apps (7 apps: LinkLumina, Cục Quản Lý, MAS, World Leaderboard, Bí Mật, Bói Toán, Hub) | `litebrowser/data/chain.json` → `core/app_paths.py` |
| Search engines | `core/prefs.py` → `SEARCH_ENGINES` |
| Themes / accents | `ui/theme.py` → `PALETTES` / `ACCENTS`; the *resolved* (auto day/night) mode comes from `core/prefs.py` (`resolved_auto_theme`, `theme_data.is_night_theme`) |
| Web pages following the shell's light/dark mode | `core/prefs.py` (`effective_force_dark_web`) → `browser/browser_page.py` (`ensure_forced_dark_script`), re-applied on a theme flip by `ui/main_window/window_topbar.py` (`refresh_chrome_theme`) |
| Morning-brief greetings | `core/greetings.py` (shared by `browser/new_tab_page.py` and `services/brief_service.py`) |
| Versioned profile stores | `core/store.py` + `core/migrations.py` → `personal_plan` (v2), `tab_sets`, `entity_links` |
| Sync entities | `services/sync_service.py` → `SYNC_ENTITIES` (incl. planner, flashcards, entity links) |
| Study data on every surface | planner + flashcards flow through backup (`history_service`), sync, the AI index (`ai_service.collect_docs`), library search (`life_service.search_everything`) and the Morning Brief (`brief_service`) |
| Course lifecycle + block editing | `personal_plan.create_course` / `update_course` / `delete_course` / `update_time_block` → Weekly Plan UI (`ui/personal_window.py`) |
| Study sessions | `services/study_session.py` → PersonalWindow “▶ Study”; minutes are credited to the item once |
| Entity links (two-way) | `services/link_service.py` (`entity_links.json`) → note “🔗 Link…/Unlink” panel; backlinks are the same rows read in reverse |
| Unified Home agenda | `life_service.today_agenda` → Home “Today” card (planner deadlines + quick-task inbox) |
| The study loop (one next step) | `services/study_flow.py` → Home “▶ Continue”, `/flow`, the brief's `next_step` line and the planner study hint |
| Inbox → planner promotion | `study_flow.promote_task` → Home “→ Planner” (task and item stay linked) |
| Proactive study reminders | `study_flow.reminder` → `AppShell._check_study_reminder` (60 s tick) → `system_notify` toast; gap from `prefs.get_study_reminder_minutes`, Settings combo |
| Weekly reflection | `study_flow.weekly_review` / `review_line` → Home “This Week” card (spark, streak, skipped rows) and the AI index (`study_week` doc) |
| Term settings | `personal_plan.update_plan_settings` → Weekly Plan “⚙ Semester” dialog |
| Google sign-in | `google_auth.sign_in_via_device_code` / `ensure_valid_token` + `prefs.get/set_google_token_cache` → Settings “Google account” card (background thread, `AppShell.run_in_background`) |
| Passcode re-lock | `security.lock` → Settings “Lock now” |
| Watched pages management | `page_monitor.remove_monitor` → Settings “Watched pages” card |
| Tab-set rename | `tab_sets.rename_tab_set` → Tab Sets dialog “⋯ More → Rename…” |
| Workspace rename | `workspace_manager.rename_workspace` → Manage Workspaces dialog “⋯ More → Rename the selected workspace…” (double-click also renames) |
| One action per dialog | `ui/dialogs/common.py::dialog_footer` + the Primary/Ghost/Quiet/Danger roles → every dialog footer, `theme.py` §6.7 |
| Background work relay | `AppShell.run_in_background` → `background_done` signal → page callbacks on the GUI thread |
| Loop memoization | `study_flow._memoized` (1 s TTL + store signature) → `reset_flow_cache` for callers that must see a write immediately |
| Brief markdown export | `brief_service.brief_markdown` → Home “📝 Save as note” |
| Qt binding selection | `litebrowser/qt.py` over `qt_compat.py` |

## 2. Reserved API (reachable, no desktop caller yet)

These exist in the data/service layer, are reachable from the phone bridge, the sync
bundle, or a future UI, and are intentionally *not* dead:

| Capability | API | Reachable from | Why kept |
|---|---|---|---|
| Cục Quản Lý support URL | `app_paths.cuc_quan_ly_support_url` | — | Resolves the bundled copy's `index.html`; wired when the packaged copy is missing |

The Google, planner-settings, rename, monitor-removal and passcode rows that used to
live here were promoted into §1 (Settings, the Weekly Plan header, the Tab Sets dialog
and the Manage Workspaces dialog) — the ledger only shrinks.

## 3. Promoting or dropping an entry

**Promote** (wire it into a dialog): keep the implementation, add the caller, then
remove the row from §2. `tests/test_reserved_api.py` still covers it, so both gates
keep passing — the ledger only shrinks.

**Drop** (no longer wanted): delete the function *and* its `test_reserved_api.py`
coverage in the same change. `tests/test_capability_ledger.py` fails the moment an
unreferenced public `def` survives without a ledger entry, so a half-finished
removal cannot land.

> Deleting `tests/test_reserved_api.py` coverage without deleting the code is the one
> mistake this file exists to prevent: the ledger test would then report the function
> as dead API.
