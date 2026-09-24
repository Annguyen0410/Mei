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
| Themes / accents | `ui/theme.py` → `PALETTES` / `ACCENTS` |
| Morning-brief greetings | `core/greetings.py` (shared by `browser/new_tab_page.py` and `services/brief_service.py`) |
| Versioned profile stores | `core/store.py` + `core/migrations.py` → `personal_plan`, `tab_sets` |
| Sync entities | `services/sync_service.py` → `SYNC_ENTITIES` |
| Qt binding selection | `litebrowser/qt.py` over `qt_compat.py` |

## 2. Reserved API (reachable, no desktop caller yet)

These exist in the data/service layer, are reachable from the phone bridge, the sync
bundle, or a future UI, and are intentionally *not* dead:

| Capability | API | Reachable from | Why kept |
|---|---|---|---|
| Course lifecycle | `personal_plan.create_course` / `update_course` / `delete_course` | phone bridge, sync bundle | Planner schema is course-first; deleting a course detaches its items and time blocks instead of cascading |
| Time-block editing | `personal_plan.update_time_block` | phone bridge | Create/reschedule already used; only the edit path has no dialog yet |
| Whole-plan write | `personal_plan.save_plan` | sync import, tests | Bulk/normalising writer; the UI writes through the granular helpers |
| Planner settings | `personal_plan.update_plan_settings` | phone bridge | Semester/week settings persist with no Settings panel yet |
| Monitor removal | `page_monitor.remove_monitor` | phone bridge | Add/list are wired; removal arrived with the bridge contract |
| Tab-set rename | `tab_sets.rename_tab_set` | — | Sessions dialog saves and deletes sets; rename is the missing menu action |
| Workspace rename | `workspace_manager.rename_workspace` | — | Workspaces are created automatically; renaming is a future Settings affordance |
| Google token cache | `prefs.get_google_token_cache` / `set_google_token_cache` | `google_auth` | Written after sign-in, read by the refresh path |
| Google token refresh | `google_auth.ensure_valid_token` | `google_auth.sign_in_via_device_code` | Reuses a fresh token without network, refreshes or drops a stale one |
| Device-code sign-in | `google_auth.sign_in_via_device_code` | — | One-shot wrapper over `request_device_code` + `poll_device_token` for the upcoming "Sign in with Google" button |
| Passcode lock | `security.lock` | Settings | Unlock/verify are wired; re-locking without restart is the missing piece |
| Brief markdown | `brief_service.brief_markdown` | tests | Text and HTML briefs are rendered in the UI; markdown is the future export/share format |
| Cục Quản Lý support URL | `app_paths.cuc_quan_ly_support_url` | — | Resolves the bundled copy's `index.html`; wired when the packaged copy is missing |

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
