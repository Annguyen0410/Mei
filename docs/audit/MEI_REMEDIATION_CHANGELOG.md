# Mei — Remediation Changelog

Branch: `new-main`. Scope: P0 trust/safety batch plus the Browser Diagnostics
surface. No user data, profile, browser store or credential was touched; all
tests used temporary directories and throwaway keys.

## 1. Verification results

| Command | Result |
|---|---|
| `py_compile` on every edited module | pass |
| `python -m pytest tests/test_engine_identity.py tests/test_hibernation_policy.py tests/test_update_signature.py tests/test_update_identity.py tests/test_engine_visibility.py` | 128 passed, 47 subtests |
| Full suite, project venv (`.venv`, PyQt5+PyQt6, `segno`, pytest 9.1.1) | **1107 passed, 1385 subtests, 0 failed** (132.66 s) |
| Full suite, system Python 3.11 | fails at `test_android_bridge` with `ModuleNotFoundError: segno` — environment is missing a declared dependency; not a code failure |
| `ruff check --select F401,F811,F841,F821` | see §6 |

Not run (blocked by this environment): packaged `.exe` startup, real desktop
GUI, multi-monitor/high-DPI, renderer-crash drill, 8–72 h soak, performance
benchmarks, real-site compatibility matrix, Authenticode verification.

## 2. Code changes

### 2.1 Engine identity and spoofing removal

* **`litebrowser/browser/browser_page.py`**
  * Deleted `_CHROME_STUB_JS` (15,564 characters) — a DocumentCreation,
    MainWorld, subframe-enabled script that fabricated `navigator.webdriver`,
    `navigator.plugins`, `navigator.userAgentData`, `deviceMemory`,
    `hardwareConcurrency`, `vendor`, WebGL unmasked vendor/renderer and
    `permissions.query`.
  * `ensure_chrome_compat_script()` is now an uninstall hook: it removes a
    legacy script object and never inserts one.
  * Added `LEGACY_CHROME_SHIM_REMOVED = True` as a permanent marker with the
    reason.
  * `_on_permission_requested`: deny-by-default for unknown features, invalid
    origin or missing profile; incognito decisions are never persisted;
    `_known_feature()` added, `_feature_name()` kept compatible.
* **`litebrowser/browser/engine_identity.py`** (new)
  * `chromium_version()` asks `qWebEngineChromiumVersion` through the project
    Qt facade, UA only as fallback, `("", "")` when unknown.
  * `build_user_agent()` → `Mei/<version> Chrome/<real major>`; omits the
    `Chrome/` token when unknown; never emits `Google Chrome`/`QtWebEngine`.
  * `SIGN_IN_COMPAT_HOSTS` (9 sign-in origins), `is_sign_in_host()` with exact
    suffix matching, `client_hint_headers()` with Chromium+Mei brands.
* **`litebrowser/browser/adblock.py`**
  * `_apply_compat_headers()` now emits real engine hints and no `Google
    Chrome` brand; platform-version is blanked instead of asserting `15.0.0`.
  * `sign_in_compat` pref wired in `_reload_privacy_prefs`; hints apply only
    when the pref is on **and** the host is a sign-in origin.
* **`litebrowser/ui/main_window/window.py`**
  * `_build_clean_ua()` delegates to `engine_identity.build_user_agent()`.
* **`litebrowser/core/prefs.py`**
  * `get_chrome_compat_shim()` now defaults to **False** and documents that it
    gates headers only; `set_chrome_compat_shim()` drops the obsolete
    `chrome_compat_script` key.
* **`litebrowser/ui/dialogs/profiles_privacy.py`**
  * Label/tooltip no longer claim "hide automation detection" or script
    injection.

### 2.2 Engine standardization

* **`pyproject.toml`**: default dependencies are
  `PyQt6==6.11.0` + `PyQt6-WebEngine==6.11.0`; added `qt5` legacy extra with an
  explicit LEGACY warning; kept `qt6` alias.
* **`requirements.txt`**: same two pins.
* **`README.md`**, **`RUN_AND_BUILD.md`**: removed the "supports PyQt5 and
  PyQt6" / silent-fallback claims; documented Qt 6.11 as production and PyQt5
  as legacy test-only.

### 2.3 Tab hibernation safety

* **`litebrowser/browser/hibernation_policy.py`** (new): `TabState`,
  `hibernate_block_reason()`, `describe_reason()`. Refuses active, pinned,
  never-hibernate, incognito, audible, navigating, downloading, recently used,
  unknown idleness and disabled pref.
* **`litebrowser/browser/tab_manager.py`**
  * `hibernate_tab(..., force=False)` consults the policy and returns bool.
  * `_hibernate_state()` collects audible/navigation/download/idleness facts.
  * `_hibernate_when_idle()` re-checks at timer fire and re-arms on a blocker.
  * `_has_active_download()` checks per-view and window-wide counters.
  * `set_tab_never_hibernate(row, enabled)`.
  * Zoom captured before disposal and restored on materialization; title
    preserved in metadata.
* **`litebrowser/ui/main_window/window_tools.py`**: accepted downloads
  increment `_active_download_count` (conservative pause of hibernation).

### 2.4 Update authenticity

* **`litebrowser/services/update_signature.py`** (new): canonical JSON payload,
  Ed25519 verify/sign, `key_id`, revoked ids, strict base64/length checks,
  `UpdateSignatureError` with actionable messages; no private key stored.
* **`litebrowser/core/update_keys.py`** (new): empty pinned-key map, revoked
  set, `signing_configured()`; provisioning and rotation documented. Intentionally
  empty → fail closed.
* **`litebrowser/services/update_service.py`**: remote manifests with an update
  or a download URL must verify against a pinned key; local manual channel
  exempt and labelled. `UpdateInfo` gained `key_id`, `signature_verified`,
  `channel_kind`.
* **`tools/publish_release.py`**: signs the manifest when
  `MEI_UPDATE_SIGNING_KEY` + `MEI_UPDATE_KEY_ID` are set; otherwise writes an
  empty signature so the build is visibly unauthenticated rather than silently
  trusted.
* **`.github/workflows/release.yml`**: conditional Authenticode
  `signtool sign`/`verify /pa` with RFC3161 timestamping, plus a signing-status
  summary line. No-op until secrets exist.

### 2.5 Diagnostics

* **`litebrowser/services/engine_diagnostics.py`** (new): `collect()` and
  `format_report()`; reports Mei/Python/Qt/binding/QtWebEngine/Chromium/patch/
  GPU/hardware acceleration/sandbox/profile/UA/platform and warnings.
  Undeterminable values are `Unknown`; sandbox is only "disabled" when the
  environment proves it.
* **`litebrowser/ui/shell/pages.py`**: Settings → Diagnostics gained a
  **Browser diagnostics** button showing the report; engine module imported;
  profile label computed without an invalid escape.

## 3. Tests added

* `tests/test_engine_identity.py` — truthfulness, allowlist, hints, absence of
  spoofing code, uninstall-only hook, single pinned engine.
* `tests/test_hibernation_policy.py` — 16 blocker/allow cases.
* `tests/test_update_signature.py` — valid, tampered, wrong/unknown/revoked key,
  malformed signature/key, rotation, empty trust store.
* `tests/test_update_identity.py` — fixtures now signed with a runtime-generated
  Ed25519 key (`setUpModule`/`tearDownModule`); size-limit test signed so it
  still tests size rather than signature.
* `tests/test_engine_visibility.py` — expects Chromium/Mei brands, asserts
  `Google Chrome` is absent.

## 4. Bugs fixed (summary)

1. Source installs could receive Chromium 87 while releases shipped 140.
2. Every site received a fabricated Chrome fingerprint, in every subframe.
3. The UA claimed to be Google Chrome.
4. A background tab playing audio or downloading could be hibernated.
5. Hibernation did not preserve zoom; no never-hibernate option; timer could
   not re-arm after a temporary blocker.
6. An update manifest could be replaced together with its package and still
   pass SHA-256.
7. Unknown web permissions prompted the user; incognito persisted grants.
8. Engine facts were only visible inside an exported zip.

## 5. Remaining risks and blocked items

| Item | Status | Why |
|---|---|---|
| Page Monitor SSRF (F-09) | OPEN | needs resolve→validate→connect-to-IP; not attempted |
| Adblock subscription fetch | UNVERIFIED | scheme/redirect/private-IP/size audit pending |
| Update publisher key | BLOCKED | no real key; map empty by design |
| Authenticode certificate | BLOCKED | no certificate; workflow ready |
| Real-site compatibility matrix | BLOCKED | no interactive desktop/test accounts |
| GUI/multi-monitor/DPI | BLOCKED | headless session |
| Performance + soak | BLOCKED | no desktop; no numbers invented |
| UI monolith refactors | NOT STARTED | needs GUI regression harness first |
| Migration journal / corrupt-store recovery | NOT STARTED | documented gap |
| Backup scheduling / Conflict Center | NOT STARTED | documented gap |
| System-Python suite | ENVIRONMENT | `segno` absent; project venv is green |

## 6. Lint

`ruff check --select F401,F811,F841,F821 litebrowser tests tools` — **clean**
(5 unused-import/redefinition findings from the edit itself were removed, not
suppressed; the gate passes with no `noqa` additions).

## 7. Compatibility notes for reviewers

* Behaviour change: sign-in compatibility is now **off by default**. Existing
  profiles that stored `chrome_compat_shim = true` keep header compatibility
  (scoped, truthful); no profile can restore the script.
* Behaviour change: a remote update now fails closed without a pinned key. This
  is intentional; provisioning is a one-time maintainer step.
* Behaviour change: hibernation can keep more renderers alive (audio, download,
  incognito, recent). That is the correct trade; memory tuning must not be done
  by weakening the policy.
* No database schema, file format or internal API was removed. `UpdateInfo`
  only gained fields; `hibernate_tab` only gained a keyword and a return value;
  `_feature_name` remains.

## 8. Batch 2 — network security (Page Monitor + subscriptions)

### 8.1 Confirmed vulnerabilities

1. **Page Monitor SSRF / DNS rebinding**: `_is_local_host` validated the
   hostname string, then `urllib` resolved it again and connected wherever DNS
   pointed. A public name resolving to `127.0.0.1` or `10.x` passed; a redirect
   was validated only by string, never by resolved address.
2. **Subscription updater**: accepted `file:`/`ftp:`/`javascript:` URLs, used
   `urlopen` (second resolution), had no body/line caps, wrote the cache
   non-atomically, derived the filename from the raw subscription name (path
   traversal), and swallowed every failure so a broken list was invisible.
3. **Unbounded filter reads**: `load_domains_from_filter_file` read a file of
   any size and logged nothing when it failed.

### 8.2 Implemented

* **`litebrowser/services/safe_http.py`** (new): `is_public_address` (unwraps
  IPv4-mapped IPv6; rejects loopback/private/link-local/multicast/reserved/
  unspecified/CGNAT/documentation), `resolve_public_addresses` (refuses a host
  if any answer is non-public), `normalize_http_url`, `redirect_target`
  (HTTPS→HTTP refused), pinned `HTTPConnection`/`HTTPSConnection` subclasses
  (socket to validated IP; Host/SNI keep the real hostname; default TLS context,
  no bypass), `fetch` (per-hop re-resolution, 5-redirect limit, loop detection,
  cross-origin header stripping, byte cap, timeout/cancel, TLS/timeout mapping).
  No proxy support, by design.
* **`litebrowser/services/page_monitor.py`**: removed `_HttpOnlyRedirect` and the
  urllib opener; `_open_url` delegates to `safe_http.fetch`; `_fetch_page` maps
  transport failures to `MonitorFetchError`; public IPv6 literals are accepted
  and canonicalised with brackets; `urllib.request` import removed.
* **`litebrowser/browser/adblock.py`**: rewritten subscription refresh (HTTPS
  only, pinned IP, 8 MiB/200k line/8 KiB line/200k rule caps, sanitized
  slug+hash cache names, atomic `os.replace`, last-known-good on failure, per-sub
  status, non-blocking refresh lock, cancellation, dedupe); bounded
  `load_domains_from_filter_file` with logging instead of silent swallow.

### 8.3 Tests

* `tests/test_safe_http.py` — public/private IPv4+IPv6, mapped IPv6, multicast,
  reserved, CGNAT, multi-answer refusal, pinned connection IP, ports, declared
  and streamed oversize, empty body, HTTP error, timeout, TLS failure,
  cancellation, redirect to localhost, DNS change on redirect, downgrade, loop,
  limit, cross-origin header stripping, URL normalisation.
* `tests/test_adblock_subscriptions.py` — HTTP and bad schemes rejected without
  a request, duplicate URLs, path traversal, atomic cache, unchanged refresh,
  failed/empty/malformed update preserving cache, HTTP error, per-sub isolation,
  line/line-count/byte caps, unsupported syntax skipped, bounded file read,
  busy lock, cancellation.
* `tests/test_page_monitor.py` — redirect tests migrated from the deleted
  `_HttpOnlyRedirect` to the real `_fetch_page` path (private resolution and
  private redirect destination), plus public IPv6 canonicalisation.

### 8.4 Verification

* Focused (safe_http + page_monitor + adblock + subscriptions): **73 passed,
  45 subtests**.
* `ruff check --select F401,F811,F841,F821` on changed modules/tests: clean.
* `py_compile`: clean.
* Full suite after the batch: **1150 passed, 1413 subtests passed in 143.67s (0:02:23)**.

### 8.5 Residual risks / unsupported

* Proxy-mediated fetches are unsupported; a proxy requirement makes Page Monitor
  and subscription refresh fail rather than bypass the destination check.
* No live-network DNS/TLS test was run; the guarantees are unit-tested with
  faked resolvers and sockets. A manual check against a public host and a
  deliberately rebinding test domain is still required before release.
* Filter grammar remains domain-only; EasyList cosmetic/regex/option rules are
  skipped, not emulated.
* DNS pinning does not defend against a malicious resolver returning a public
  address that later forwards traffic internally (e.g. a public reverse proxy);
  that is outside a client-side SSRF boundary.
## 9. Batch 3 — data integrity, backup and recovery

### 9.1 Behaviour changes

* Versioned stores no longer return their default payload on malformed JSON.
  `read_store` now raises `StoreReadError`, keeps the source and records a
  quarantine copy. The old test was updated with that rationale.
* `write_json` refuses to overwrite a legacy store marked damaged until a
  successful read proves it was repaired.
* `safe_http.fetch` defaults to refusing when a proxy environment variable is
  set; direct access now requires `proxy_mode="direct"` explicitly. The prior
  test was updated because silently ignoring a proxy was the bug.

### 9.2 Added modules

`core/storage_health.py`, `core/migration_journal.py`,
`core/storage_catalog.py`, `services/backup_service.py`,
`services/restore_service.py`, `services/integrity_service.py`,
`services/conflict_service.py`, `services/recovery_service.py`,
`ui/dialogs/data_management.py`.

### 9.3 Integration

`core/store.py` journals migrations; `core/storage_utils.py` preserves and
write-protects damaged legacy stores; `sync_folder.py` archives conflicts;
`main.py` marks session start/end and runs safe startup reconciliation; Settings
exposes **Data Management** (Backups, Restore Center, Integrity Check, Sync
Conflicts).

### 9.4 Tests and verification

* New suite: `tests/test_data_integrity_services.py` — 32 tests.
* Focused storage/sync/Qt run: **80 passed, 7 subtests passed**.
* Full suite: **1192 passed, 1413 subtests passed in 126.16s (0:02:06)**.
* Ruff (`F401,F811,F841,F821`): clean.
* `py_compile`: clean.
* Not tested: real disk-full, forced power loss, live two-device sync, and GUI
  interaction under a display session.
## 10. Batch 4 — data-safety closure and integration

### Added

* `services/backup_scheduler.py` — in-process due-backup scheduler with
  collision, restore/migration and last-known-good guards.
* `services/record_restore_service.py` — record-level restore for tasks,
  events, boards, saved pages, flashcards, planner items and notes.
* `ui/components.py::StorageHealthBanner` — one global unavailable-store
  warning.
* Data Management tabs for Storage Health, Record Restore, Recovery and Proxy.
* `storage_catalog.migration_coverage()` — explicit 25-store matrix.
* `MEI_BACKUP_ENCRYPTION.md` — threat model and blocked design.

### Changed behaviour

* `write_json` inspects existing bytes before replacement and refuses to erase a
  malformed store, even when no read occurred in the current process.  It also
  serializes same-process JSON writers.
* HTTP sync archives differing task/event/board/page/note rows before applying
  a winner; archive failure leaves the local row intact.
* Conflict archive restore merges by signature and is idempotent; it never
  activates a version.
* Page Monitor and adblock refresh pass Mei's proxy preference and refuse to
  connect directly unless the user opted in.  `proxy_mode="proxy"` never falls
  back to direct because no proxy transport exists.
* Data Management exposes recovery reports and migration coverage.

### Verification

* Full suite: **1192 passed, 1413 subtests passed in 126.16 s**.
* Focused data/sync/proxy suite: **150 passed, 133 subtests**.
* Ruff and `py_compile`: clean.
* Not tested: real GUI interaction, disk-full, power loss, live two-device
  sync, packaged build.

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

## 2026-11 critical data-safety hardening

Detailed evidence and remaining limitations are in
`MEI_CRITICAL_REMEDIATION_2026-11.md`.

- Quarantine failure is now fail-closed: a corrupt store cannot be overwritten
  unless a byte- and SHA-256-verified preservation copy exists.  Regression tests
  cover permission failure, read-before-write failure and source mutation.
- HTTP merge results are typed; archive/write failures abort the pull, preserve
  the baseline, and leave a durable push-block reason.  Tests cover tasks,
  planner/bookmarks/notes paths and retry clearing.
- Empty restore categories are rejected; `None` is the only all-categories
  value.  Restore now uses a version-2 journal with per-file original/staged
  hashes, verified rollback copies, locks around the pre-restore snapshot and
  deterministic startup reconciliation.
- Encrypted restores create an encrypted pre-restore backup or block; the
  version-1 scrypt parameters are exact and parsed with strict types before KDF
  work.  Decryption/encryption temporary files use a private Mei temp root and
  startup stale cleanup.
- Stable release publication requires a signed manifest verifiable by the
  pinned trust store, and stable Authenticode requires a valid signer and
  timestamp.  The workflow's control-character signtool path is fixed.
- History now has a page-local store guard; Library and History do not render an
  unavailable store as a normal empty collection.  Data Management preview,
  verification and retention run through the existing Qt worker.
- New focused verification: **123 passed, 5 subtests**.  Full-suite and CI
  limitations are reported in `MEI_CRITICAL_REMEDIATION_2026-11.md`; no
  historical test total is reused as a current result.
