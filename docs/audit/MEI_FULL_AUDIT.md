# Mei — Full Repository Audit

Status: **living document**, reflecting the code on branch `new-main` after the
P0 remediation batch. Findings are classified, not asserted: a claim here is
either verified from source/tests or explicitly marked as unverified.

Scope: the whole repository at `new browser/` (44,615 lines under
`litebrowser/`, 96 test modules). Engine: PyQt6 6.11.0 / Qt 6.11.2 /
QtWebEngine 6.11.0 (Chromium 140 line) for production; PyQt5 5.15.11 is present
in the dev venv and in CI only as a legacy matrix leg.

## 1. Architecture as it actually is

```
browser.py / litebrowser/main.py        process entry, single-instance lock, smoke marker
  └─ litebrowser/qt_compat.py           import-time PyQt5→PyQt6 alias shim (sys.modules + enum flattening)
  └─ litebrowser/ui/main_window/        browser shell: window, topbar, menus, tools mixins
       └─ browser/tab_manager.py        tab desk, renderer lifecycle, hibernation, session metadata
            └─ browser/browser_page.py  QWebEnginePage: permissions, injection hooks
            └─ browser/adblock.py       request interceptor: blocking, HTTPS upgrade, Client Hints
  └─ litebrowser/ui/app_shell.py        workspace shell (Home, Browser, Library, Personal, AI, Settings)
       └─ ui/shell/pages.py             Settings/Help/Library surfaces (3,263 lines)
       └─ ui/personal_window.py         Personal hub (5,352 lines)
       └─ ui/ai_window.py               AI workspace (1,456 lines)
  └─ litebrowser/services/*             stores, sync, update, monitors, bridges, diagnostics
  └─ litebrowser/core/*                 paths, prefs, product identity, secret store, atomic JSON
```

Persistence is JSON-per-store under a profile directory, written through
`core/storage_utils.write_json` (atomic replace) and guarded by
`profile_locked()` for multi-process access. Chromium owns its own profile tree
under `BrowserData/<slot>/`.

## 2. Module inventory (highest-risk areas)

| Module | Lines | Responsibilities | Risk |
|---|---:|---|---|
| `ui/personal_window.py` | 5,352 | notes, tasks, calendar, boards, planner, flashcards, sites, AI dock | God object; UI→store direct writes |
| `ui/main_window/window.py` | 4,067 | window lifecycle, profile config, downloads, history, session | Many roles; profile policy inline |
| `ui/shell/pages.py` | 3,263 | settings, help, library, sync, diagnostics | Mixed presentation + persistence |
| `ui/app_shell.py` | 2,129 | workspace switching, navigation, global state | Implicit coupling to every page |
| `browser/tab_manager.py` | 1,237 | tab lifecycle, hibernation, groups, restore | Renderer ownership + UI state |
| `services/android_bridge_service.py` | 1,199 | LAN HTTP bridge, token auth | Network exposure |
| `core/prefs.py` | 1,456 | every preference + caching | Single mutable god-store |
| `services/sync_folder.py` | 966 | three-way folder sync | Conflict/data-loss surface |
| `services/update_service.py` | 718 | channel, download, swap, rollback | Supply chain |
| `browser/browser_page.py` | 860 | permissions, scripts | Security boundary |

## 3. Findings

Legend: CONFIRMED (read from source), REPRODUCED (test or run), HIGH CONFIDENCE,
POTENTIAL, NOT AN ISSUE, ALREADY FIXED, BLOCKED.

### F-01 — Two production browser engines (P0) — CONFIRMED, FIXED

* **Evidence**: `pyproject.toml` `[project].dependencies` listed
  `PyQt5>=5.15` / `PyQtWebEngine>=5.15`, while the release workflow and
  `Mei.spec` build with `PyQt6==6.11.0`. A plain `pip install .` therefore gave
  Qt 5.15 / Chromium 87; the shipped `.exe` was Chromium 140.
* **Impact**: source users got an engine that Google, Microsoft and most modern
  sites refuse; behaviour could not be reproduced from a bug report.
* **Fix**: default dependencies and `requirements.txt` now pin
  `PyQt6==6.11.0` + `PyQt6-WebEngine==6.11.0`. PyQt5 moved to a documented
  legacy `qt5` extra. `README.md` / `RUN_AND_BUILD.md` no longer advertise a
  silent fallback. Regression: `tests/test_engine_identity.py::TestSingleProductionEngine`.
* **Residual**: CI still runs a PyQt5 leg (intentional canary). It must never be
  the release engine; the release workflow installs PyQt6 only.

### F-02 — Global Chrome fingerprint spoofing (P0) — CONFIRMED, FIXED

* **Evidence**: `browser_page.py` contained a 15.5 KB `_CHROME_STUB_JS`
  installed on **every** profile, at `DocumentCreation`, `MainWorld`,
  `setRunsOnSubFrames(True)`. It deleted `navigator.webdriver`, replaced
  `navigator.plugins`, synthesized `navigator.userAgentData` including a
  `"Google Chrome"` brand, invented `deviceMemory`/`hardwareConcurrency`,
  rewrote WebGL `UNMASKED_VENDOR/RENDERER`, and patched
  `navigator.permissions.query`.
* **Impact**: every site Mei visited received a fabricated fingerprint, in
  every frame, including sites with no compatibility problem. It contradicted
  native values (itself detectable), and was explicitly designed to defeat
  embedded-browser detection and bot checks. This is not a compatibility fix;
  it is deception with a security and privacy cost.
* **Fix**: the script is deleted (`LEGACY_CHROME_SHIM_REMOVED = True`).
  `ensure_chrome_compat_script()` is now an uninstall hook that only removes a
  stale script object and never inserts one. Compatibility is reduced to real
  HTTP Client Hints on a narrow sign-in allowlist, opt-in, network-layer only
  (`browser/engine_identity.py`, `adblock._apply_compat_headers`). No
  `navigator.*`, WebGL or `window.chrome` patching remains.
* **Regression**: `tests/test_engine_identity.py::TestNoGlobalSpoofingScript`,
  `TestClientHints`, `TestSignInAllowlist`.

### F-03 — User-Agent claimed to be Google Chrome (P0) — CONFIRMED, FIXED

* **Evidence**: `window._build_clean_ua` stripped `QtWebEngine` and returned
  `... Chrome/<n>.0.0.0 Safari/537.36`, i.e. plain Chrome.
* **Fix**: `engine_identity.build_user_agent()` emits
  `Mei/<version> Chrome/<real major>.0.0.0`, omits the `Chrome/` token when the
  version cannot be read, and never emits `Google Chrome` or `QtWebEngine`.

### F-04 — Hibernation could discard tabs that were doing work (P0) — CONFIRMED, FIXED

* **Evidence**: `tab_manager.hibernate_tab()` guarded only active/pinned/
  already-hibernated. `_refresh_hibernate_timers()` armed a timer for any
  background tab. `recentlyAudible`, downloads and in-flight navigation were
  never consulted, so a playing video or an active download could be disposed.
  No "never hibernate" concept existed. Scroll/form/SPA state was never saved.
* **Fix**: new pure policy module `browser/hibernation_policy.py`. Hibernation
  now refuses: active, pinned, `never_hibernate`, incognito, audible,
  navigating, active download, recently used, unknown idleness, disabled pref.
  Fire-time re-check (`_hibernate_when_idle`) re-arms instead of forcing.
  Zoom factor is captured/restored; URL/title/icon/group/workspace already were.
  `set_tab_never_hibernate(row, enabled)` added.
* **Regression**: `tests/test_hibernation_policy.py` (16 cases).
* **Residual (documented, not fixed)**: unsaved form contents, SPA memory,
  WebSocket/WebRTC sessions, open dialogs and scroll position are **not**
  restorable from outside a renderer. The UI must state that a woken tab
  reloads. Scroll restoration is not implemented; it needs an async JS probe
  with a timeout before disposal.

### F-05 — Update manifest had no publisher authentication (P0) — CONFIRMED, FIXED (mechanism) / BLOCKED (key)

* **Evidence**: `update_service` verified product id, asset name, size, `MZ`
  and SHA-256 from the same manifest. Whoever could replace the manifest could
  replace its hash and the package together.
* **Fix**: `services/update_signature.py` — Ed25519 detached signature over a
  canonical JSON payload, `key_id`, pinned-key lookup, revocation set, no
  unsigned remote path. `check_for_updates` refuses a remote manifest that is
  unsigned/untrusted/tampered. Local `update/update.json` stays permitted as a
  deliberate manual channel and is labelled `channel_kind="local-manual"`.
  `tools/publish_release.py` signs when `MEI_UPDATE_SIGNING_KEY` +
  `MEI_UPDATE_KEY_ID` are present.
* **Tests**: `tests/test_update_signature.py` (valid, tampered version/URL,
  wrong key, unknown key, revoked key, malformed signature, empty trust store,
  rotation). `tests/test_update_identity.py` fixtures are now signed with an
  ephemeral key generated at test time.
* **BLOCKED**: `core/update_keys.py` is intentionally empty. No real publisher
  key exists, so every remote update is refused — fail closed. Provisioning
  steps are documented in that file. No placeholder/fake key was created.

### F-06 — No Authenticode / release signing path (P0) — CONFIRMED, PARTIAL

* **Evidence**: `release.yml` built and published `dist/Mei.exe` with no
  signing step; `Mei.spec` `codesign_identity=None`.
* **Fix**: release workflow now has a conditional `signtool sign` +
  `signtool verify /pa` step with RFC3161 timestamping, driven by
  `MEI_SIGNING_PFX_BASE64` / `MEI_SIGNING_PFX_PASSWORD` secrets and
  `MEI_TIMESTAMP_URL`; a following step records `signed`/`UNSIGNED` in the job
  summary.
* **BLOCKED**: no certificate exists in this environment, so no signed artifact
  was produced or verified. The step is a no-op until the secrets are set.

### F-07 — Permission prompts for unknown features; incognito persisted choices (P0) — CONFIRMED, FIXED

* **Evidence**: `_on_permission_requested` prompted for any feature, including
  `feature_9`, and `_decide(..., remember=True)` wrote to the persistent profile
  regardless of private browsing.
* **Fix**: unknown features are denied without a prompt; invalid origin and
  missing profile deny; `profile().isOffTheRecord()` forces "do not persist".

### F-08 — Browser diagnostics were invisible (P0) — CONFIRMED, FIXED

* **Evidence**: `services/diagnostics.engine_notice()` existed, but engine facts
  were only readable inside an exported zip.
* **Fix**: `services/engine_diagnostics.py` (pure) + Settings → Diagnostics →
  **Browser diagnostics** button showing Mei/Python/Qt/binding/QtWebEngine/
  Chromium/patch/GPU/hardware acceleration/sandbox/profile/UA/platform plus
  warnings. Undeterminable fields say `Unknown`; sandbox and GPU acceleration
  are only stated when an environment opt-out proves them.

### F-09 — Page Monitor validated the hostname, not the connected address (P1) — CONFIRMED, FIXED

* **Evidence**: `page_monitor._is_local_host()` parses a literal hostname/IP.
  `_open_url()` then lets `urllib` resolve and connect. A public hostname that
  resolves to `127.0.0.1` or `10.x` passes validation; a DNS answer can change
  between validation and connection (rebinding).
* **Impact**: SSRF from a user-added watch target to the local network.
* **Fix**: `services/safe_http.py` resolves once per hop, rejects the host if
  **any** answer is non-public (IPv4/IPv6, loopback, link-local, multicast,
  reserved, unspecified, CGNAT and IPv4-mapped IPv6 included), and connects the
  socket to that validated IP. The original hostname is kept for the HTTP
  `Host` header and for TLS SNI + certificate hostname checking. Every redirect
  is normalised, re-resolved, re-validated, loop-checked and limited; HTTPS to
  HTTP is refused. `page_monitor._open_url` uses this transport, so `urllib` no
  longer performs a second, unchecked resolution.
* **Regression**: `tests/test_safe_http.py` (31 cases), migrated redirect tests
  in `tests/test_page_monitor.py`, including a DNS-change-on-redirect case.
* **Residual**: proxy configurations are deliberately unsupported (the TCP peer
  would be the proxy, not the validated destination). Real-world DNS/TLS
  behaviour was not exercised; the guarantees are unit-tested with fakes.

### F-10 — Adblock subscription fetch (P1) — CONFIRMED, FIXED; parser scope — PARTIAL

* **Evidence**: the old updater accepted any URL scheme, used `urlopen` (second
  DNS resolution), wrote the cache with a plain `open(..., "w")`, derived the
  cache filename directly from the subscription name (path traversal), read the
  whole body without a cap, and swallowed every exception so a failed update was
  invisible. `load_domains_from_filter_file` read an unbounded file and logged
  nothing on failure.
* **Fix**: HTTPS-only subscription URLs validated before any request; the same
  pinned-IP transport (DNS answers validated, redirects re-validated); 8 MiB
  body cap; 200k line / 8 KiB line / 200k unique-rule caps; cache name = safe
  slug + SHA-256 of URL; temp-file + `os.replace` atomic writes; a failed, empty
  or malformed list keeps the last-known-good cache and reports `cached`; one
  subscription failing does not stop the others; per-subscription status is
  returned (`updated`/`unchanged`/`cached`/`failed`/`rejected`/`cancelled`/
  `busy`); a non-blocking lock prevents duplicate refreshes.
* **Regression**: `tests/test_adblock_subscriptions.py` (21 cases) and the
  existing `tests/test_adblock.py` hot-path test.
* **PARTIAL**: the parser still supports only `||domain^` / bare-domain lines.
  Cosmetic filters, regex rules, options and scriptlets are skipped, not
  emulated. This is documented in the compatibility matrix; full EasyList/uBlock
  compatibility is not claimed.

### F-11 — Giant UI modules (P2) — CONFIRMED, OPEN

`personal_window.py` (5,352), `window.py` (4,067), `pages.py` (3,263),
`app_shell.py` (2,129), `ai_window.py` (1,456) each hold several
responsibilities (presentation, navigation, persistence calls, business rules).
No refactor was attempted: a UI split without a GUI regression harness would
trade a maintainability problem for a functional one. See the remediation plan.

### F-12 — Long-duration / GPU / GUI verification (P1) — BLOCKED

No real desktop session, multi-monitor, high-DPI matrix, packaged `.exe`
startup, 8–72 h soak, or GPU backend inspection was performed in this
environment. `docs/audit/MEI_PERFORMANCE_BASELINE.md` records the harness and
the absence of results rather than inventing numbers.

## 4. Cross-module blind spots found while reading

1. **Two sources of truth for tab state**: the `QListWidgetItem` metadata dict
   and the live `QWebEngineView`. Hibernation mutates one and disposes the
   other; session restore reads the dict. The policy module now centralises the
   decision, but the duplication remains.
2. **Profile configuration is spread** across `window._configure_web_profile`,
   `tab_manager._build_browser` (incognito) and `BrowserPage.__init__` (scripts,
   permissions). A new setting can easily be applied to only one path; the
   incognito branch already needed a separate download wiring fix historically.
3. **`prefs` is a global mutable store** with a file-stat cache; several
   services write it through `profile_transaction`. Concurrent windows are
   protected by a file lock, but in-process cache invalidation depends on
   mtime/size, which is coarse.
4. **UI calls persistence directly** in the large pages, so a store schema
   change has no single adapter to update.
5. **Diagnostics duplicated knowledge** of the engine in `adblock`,
   `diagnostics`, and the UA builder; `engine_identity.py` is now the single
   source for version and identity.

## 5. Verification performed

| Check | Result |
|---|---|
| `py_compile` on every edited module | pass |
| `tests/test_engine_identity.py` | pass |
| `tests/test_hibernation_policy.py` | pass |
| `tests/test_update_signature.py` | pass |
| `tests/test_update_identity.py` (signed fixtures) | pass |
| `tests/test_engine_visibility.py` (updated for truthful hints) | pass |
| Targeted batch (5 modules) | 121 passed, 40 subtests |
| Full suite (project venv) | **1150 passed, 1413 subtests passed in 143.67s (0:02:23)** |
| `tests/test_safe_http.py` | pass (pinned IP, redirects, limits, TLS/timeout mapping) |
| `tests/test_adblock_subscriptions.py` | pass (cache survival, bounds, traversal, lock) |

## 6. Data integrity, backup and recovery (batch 3)

| ID | Finding | Severity | Status |
|---|---|---|---|
| F-13 | Malformed JSON was treated as an absent store; a later save replaced recoverable bytes. | HIGH | **CONFIRMED → FIXED (legacy UI partial)**. Versioned stores raise `StoreReadError` after quarantine; legacy reads preserve a hidden `.corrupt-*.bak` and block overwrite until a successful read. |
| F-14 | Store migrations had no durable journal or pre-write snapshot. | HIGH | **CONFIRMED → FIXED for `StoreSpec` stores; PARTIAL for legacy stores.** |
| F-15 | No independent, checksum-verified backup outside the profile. | HIGH | **CONFIRMED → FIXED** for manual creation/verification/retention. Automatic background scheduling remains **PARTIAL**. |
| F-16 | No staged, reversible restore. | HIGH | **CONFIRMED → FIXED** for full/category restore with pre-restore snapshot and rollback. Individual-record restore remains **PARTIAL**. |
| F-17 | Folder-sync conflicts were reported but not durably archived with both versions. | HIGH | **CONFIRMED → FIXED** for folder sync; HTTP note conflicts remain **PARTIAL**. |
| F-18 | No clean-shutdown marker or startup operation reconciliation. | MEDIUM | **CONFIRMED → FIXED** (session marker, journal reconciliation, stale-temp quarantine). |
| F-19 | No read-only integrity scan or severity model. | MEDIUM | **CONFIRMED → FIXED**; repair is limited to explicit quarantine with a pre-repair backup. |
| F-20 | Direct-only HTTP ignored proxy environment variables. | MEDIUM | **CONFIRMED → FIXED** for environment proxies (`FetchProxyUnsupported`); application proxy preference remains **PARTIAL**. |

Detailed service contracts and residual risks are in
`MEI_DATA_INTEGRITY_AUDIT.md`, `MEI_MIGRATION_RECOVERY.md`,
`MEI_BACKUP_RESTORE.md`, `MEI_SYNC_CONFLICTS.md`,
`MEI_PROFILE_RECOVERY.md`, and `MEI_INTEGRITY_MONITOR.md`.

### Verification for this batch

| Check | Result |
|---|---|
| New data-integrity suite | `tests/test_data_integrity_services.py` — 32 tests |
| Focused storage/sync/Qt façade run | 80 passed, 7 subtests passed |
| Full suite | **1192 passed, 1413 subtests passed in 126.16s (0:02:06)** |
| Ruff (`F401,F811,F841,F821`) | clean |
| `py_compile` | clean |
| Real disk-full / power loss / GUI interaction | **NOT TESTED** |

## 7. What this audit does **not** claim

Mei is not "secure", "bug-free" or "fully compatible". The items above are
fixed at the level described; F-10's parser remains domain-only, F-11 is
untouched, and F-12 is blocked by the environment. Proxy-mediated fetches are
unsupported by design, and the network tests use fakes rather than live hosts.
No fabricated certificate, key, GPU fact or performance number appears anywhere
in this repository.
## 8. Batch 4 — data-safety closure and integration

This batch closed the gaps between the recovery services and the running
application.  The important distinction is between a service existing and the
application actually using it.

| Area | Status | Evidence / limitation |
|---|---|---|
| Legacy corrupt-store visibility | **PARTIAL** | Global banner + Storage Health show unavailable stores and preserved artifacts; legacy pages still receive their old default arrays internally. |
| Write-time corrupt-store protection | **FIXED** | `write_json` now inspects the existing bytes, preserves a copy and refuses replacement even if no prior read occurred in this process. |
| Store inventory | **FIXED** | All 25 catalogued stores are classified; notes are documented as a file store. |
| Migration journal coverage | **PARTIAL** | 3/25 catalogued stores are journaled (`personal_plan`, `tab_sets`, `entity_links`); 22 legacy stores are byte-guarded and backup-protected but have no active versioned transform. |
| Automatic backup scheduling | **FIXED (in-process)** | Daily/weekly due checks run in the shell; no claim is made for backups while Mei is closed. |
| Conflict archive backup | **FIXED** | `Recovery/conflicts.json` is an explicit backup category; restore merges by signature and is idempotent. |
| HTTP sync conflicts | **PARTIAL** | ID-row stores and notes archive both versions; planner rows still use the older merge path. |
| Record-level restore | **PARTIAL** | Tasks, events, boards, saved pages, flashcards, planner items and notes; bookmarks/tab sets/links/prefs are not record-restorable yet. |
| Recovery report UI | **FIXED** | Read-only report, quarantine count, unresolved migrations/restores and incomplete backups appear in Data Management. |
| Application proxy policy | **FIXED for safe-HTTP callers** | Page Monitor and subscription refresh pass the app proxy preference and refuse rather than bypass; no proxy transport or SOCKS support is claimed. |
| Backup encryption/authenticity | **BLOCKED** | Design only in `MEI_BACKUP_ENCRYPTION.md`; no encrypted format shipped. |

### Verification

| Check | Result |
|---|---|
| Full suite | **1192 passed, 1413 subtests passed in 126.16 s** |
| Focused data/sync/proxy set | **150 passed, 133 subtests** |
| Ruff (`F401,F811,F841,F821`) | clean |
| `py_compile` touched modules | clean |
| `git diff --check` | clean |
| GUI interaction / real disk-full / power loss / two-device sync | **NOT TESTED** |
| Packaged build / Authenticode | **NOT TESTED** in this batch |

## 2026-11 data-integrity closure

This section supersedes earlier "blocked/design-only" statements where they
conflict. See `MEI_DATA_INTEGRITY_CLOSURE.md` for the full evidence.

- Authenticated encrypted backups are implemented as opt-in
  `.mei-backup.enc` files: AES-256-GCM, scrypt `n=32768/r=8/p=1`, fresh salt and
  nonce, authenticated header, verified inner ZIP. Legacy ZIPs remain readable.
- HTTP planner and bookmark divergences now archive both versions before a
  winner; a failed archive preserves local data. History is append-only.
- Record restore now also covers bookmarks (URL identity), tab sets and entity
  links, in addition to the seven earlier stores.
- Home, Library and Settings show a page-local unavailable-store notice.
- `entity_links.json` catalog shape was corrected from `list` to `dict/links`.
- Final suite: **1205 passed, 1413 subtests passed in 136.58 s**; focused
  closure/UI set: **75 passed, 88 subtests**.
- Migration coverage is still **3/25 journaled**. The remaining 22 legacy stores
  are byte-guarded and backup-protected, not described as migration-managed.
- Real GUI, two-device encrypted restore, disk-full/power-loss and packaged
  build remain **NOT TESTED**.

## 2026-11 critical remediation addendum

The critical data-safety pass is recorded in
`MEI_CRITICAL_REMEDIATION_2026-11.md` and `MEI_REMEDIATION_CHANGELOG.md`.
It changes corrupt-store writes to fail closed, adds typed HTTP sync merge
outcomes and a persisted push gate, rejects empty restore selections, replaces
the in-memory restore rollback with a version-2 per-file journal and startup
reconciliation, requires encrypted pre-restore backups for encrypted sources,
strictly validates the version-1 scrypt header before derivation, and blocks
stable publication without a trusted update signature and valid Authenticode.
The page guard now covers History in addition to Home, Library and Settings.
Remaining limitations are listed in the detailed record; no historical test
total is reused as a current result.

## 2026-11 follow-up status

Confirmed fixed in source and regression-covered:

- Restore rollback never overwrites an `UNKNOWN` or `UNREADABLE` live target.
- Restore interruption is recoverable from verified artifacts and is idempotent.
- Corrupt, empty, invalid-schema or unreadable `sync_state.json` blocks push.
- An unresolved or damaged sync journal blocks every push path.
- Archive and baseline failures keep push blocked; `NO_REMOTE_SNAPSHOT` is typed.
- Windows crash/temp tests use canonical path identity and assert the crash hook
  actually fired.
- Encrypted temp operations are owner-tracked and live-process protected.
- Scheduled backup protection is explicit; encryption is blocked, not faked.

Still blocked by external material: stable release publication (no pinned Ed25519
update public key, no Authenticode certificate), real second-device sync, real
power-loss/disk-full testing, ACL inspection with a non-admin Windows account, and
GUI verification on a real display session. PyQt5/PyQt6 CI jobs were not re-run
here; the local full suite was run under the installed binding.
