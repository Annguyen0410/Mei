# Mei — Remediation Plan

Status legend: DONE, PARTIAL, OPEN, BLOCKED, NOT STARTED.

## P0 — Trust, data and browser safety

| # | Item | Status | Evidence / next action |
|---|---|---|---|
| P0-1 | One production engine (Qt 6.11 / Chromium 140) | **DONE** | `pyproject.toml`, `requirements.txt`; `tests/test_engine_identity.py::TestSingleProductionEngine` |
| P0-2 | Remove global Chrome fingerprint spoofing | **DONE** | `browser_page.py` script deleted; uninstall hook only; `TestNoGlobalSpoofingScript` |
| P0-3 | Truthful UA + narrow, opt-in sign-in Client Hints | **DONE** | `browser/engine_identity.py`; `adblock._apply_compat_headers`; `TestClientHints` |
| P0-4 | Hibernation cannot discard working tabs | **DONE** (policy) | `browser/hibernation_policy.py`; `tab_manager` fire-time re-check; `tests/test_hibernation_policy.py` |
| P0-5 | Signed update manifest, fail closed | **DONE** (mechanism) / **BLOCKED** (key) | `services/update_signature.py`, `core/update_keys.py` empty; `tests/test_update_signature.py` |
| P0-6 | Authenticode signing workflow | **PARTIAL** / **BLOCKED** (cert) | `.github/workflows/release.yml` conditional signtool; no certificate available |
| P0-7 | Permission deny-by-default + incognito non-persistence | **DONE** | `browser_page._on_permission_requested` |
| P0-8 | Audit sensitive data paths | **PARTIAL** | diagnostics/update redaction verified; log-line secret hygiene not exhaustive |

## P1 — Data reliability and security

| # | Item | Status | Notes |
|---|---|---|---|
| P1-1 | Security & Privacy Center | **NOT STARTED** | Privacy dialog exists but is not a status center; must not show green for unenabled features |
| P1-2 | Credential audit (plaintext fallback, logs, backups) | **PARTIAL** | secret_store + diagnostics reviewed; no exhaustive log audit |
| P1-3 | Profile encryption architecture | **NOT STARTED** | passcode is a workspace lock, not profile encryption; must not be described as encryption |
| P1-4 | Scheduled/versioned backup, restore preview | **NOT STARTED** | export exists; retention/independence from sync missing |
| P1-5 | Sync coverage transparency | **PARTIAL** | table in `MEI_DATA_INTEGRITY_AUDIT.md`; no in-product view |
| P1-6 | Conflict Center | **NOT STARTED** | no compare/keep-both UI |
| P1-7 | Adblock subscription network safety | **DONE** (network) / **PARTIAL** (grammar) | HTTPS-only, pinned IP, caps, atomic cache, last-known-good; parser stays domain-only |
| P1-8 | Page Monitor DNS/IP validation (SSRF) | **DONE** | `safe_http` resolves once, validates every answer, connects to the validated IP, re-validates redirects |
| P1-9 | Incognito persistence audit | **DONE** (permissions/hibernation) / **PARTIAL** | broader metadata audit pending |
| P1-10 | Browser Diagnostics page | **DONE** | Settings → Diagnostics → Browser diagnostics; `services/engine_diagnostics.py` |

## P1 — Compatibility and performance

| # | Item | Status | Notes |
|---|---|---|---|
| P1-11 | Website compatibility suite | **NOT STARTED** | no interactive desktop/session; no test accounts |
| P1-12 | Adblock parser upgrade / engine decision | **NOT STARTED** | current grammar is domain-suffix, not EasyList |
| P1-13 | Adaptive hibernation thresholds | **NOT STARTED** | fixed `MEMORY_SAVER_RSS_THRESHOLD_MB = 800` |
| P1-14 | Performance benchmark suite | **NOT STARTED** | methodology in `MEI_PERFORMANCE_BASELINE.md`; zero measurements |
| P1-15 | Renderer recovery hardening | **PARTIAL** | one auto-reload then "[Crashed]" status exists; no crash-loop budget test |
| P1-16 | Long-duration stability | **BLOCKED** | no 8–72 h desktop run |

## P2 — Maintainability

| # | Item | Status | Notes |
|---|---|---|---|
| P2-1 | Split `personal_window.py` (5,352) | **NOT STARTED** | needs GUI regression harness first |
| P2-2 | Split `main_window/window.py` (4,067) | **NOT STARTED** | profile policy and window roles entangled |
| P2-3 | Split `shell/pages.py` (3,263) | **NOT STARTED** | settings/help/library mixed |
| P2-4 | Split `app_shell.py` (2,129) | **NOT STARTED** | global navigation state |
| P2-5 | Typed boundaries between UI and stores | **NOT STARTED** | UI writes stores directly |
| P2-6 | Migration journal + per-store schema version | **NOT STARTED** | single profile-wide stamp |
| P2-7 | Unified CI/release gate | **PARTIAL** | CI + release exist and run tests; no packaged behavior tests beyond smoke |
| P2-8 | Documentation consistency | **PARTIAL** | README/RUN_AND_BUILD engine claims corrected; broader sweep pending |

## P2 — Product maturity

| # | Item | Status |
|---|---|---|
| P2-9 | Goal-based onboarding | PARTIAL (onboarding exists; not goal-scoped) |
| P2-10 | Information architecture review | NOT STARTED |
| P2-11 | State visibility (sync/backup/AI permissions) | NOT STARTED |
| P2-12 | Installer/companion verification | PARTIAL (installer exists; no automatic missing-asset check) |
| P2-13 | Extension threat model/SDK | NOT STARTED (manifest-only plugins exist) |

## Batch 3 — Data integrity, backup and recovery

| Item | Status |
|---|---|
| Migration journal + pre-write snapshots + crash reconciliation | **DONE** for `StoreSpec` stores; legacy stores PARTIAL |
| Checked JSON reads + quarantine + overwrite guard | **DONE** (legacy reads return defaults but cannot overwrite preserved bytes) |
| Independent verified backup + manifest + retention | **DONE** (manual/executable policy; background timer PARTIAL) |
| Staged restore + preview + pre-restore snapshot + rollback | **DONE** for full/category restore; record-level PARTIAL |
| Sync conflict archive + dedupe + audited resolution | **DONE** for folder sync; HTTP note conflicts PARTIAL |
| Session marker + startup inspection + stale-temp quarantine | **DONE** |
| Read-only integrity scan + severity + redacted report | **DONE**; repair limited to explicit quarantine |
| Proxy policy | Environment proxies **DONE**; application proxy preference PARTIAL |

## Dependency order for the next batches

1. ~~P1-8 (Page Monitor SSRF)~~ — done in this batch; pinned-IP transport shared
   by subscriptions.
2. ~~P1-7 (subscription fetch)~~ — done for the network path; filter grammar is
   still domain-only by design.
3. **P0-5 provisioning** — needs the maintainer's key; blocks real remote
   updates. Then P0-6 certificate.
4. **P1-4 / P1-6** — backup and conflict UI depend on a stable store schema;
   P2-6 (migration journal) should land first.
5. **P1-14** — measure before P1-13 tuning, otherwise thresholds are guesses.
6. **P2-1…P2-4** — only after a GUI smoke harness exists; splitting blind is
   how behaviour regressions ship.

## Release blockers today

* No pinned update key → remote updates refused (secure, but users cannot
  update).
* No Authenticode certificate → SmartScreen warning and no publisher identity.
* Proxy-mediated Page Monitor/subscription fetches are unsupported (documented).
* Performance and long-duration gates unmeasured.
## Batch 4 — closure status

| Item | Status |
|---|---|
| Legacy corrupt-store warning + non-destructive write guard | **PARTIAL** (global banner; legacy reads still default) |
| All-store migration/recovery matrix | **DONE** (25 JSON stores + notes) |
| Journaled legacy migrations | **PARTIAL** (3/25 journaled; 22 byte-guarded, no active transform) |
| Automatic in-process backup scheduling | **DONE** |
| Conflict archive backup + merge restore | **DONE** |
| HTTP sync conflict persistence | **PARTIAL** (row stores + notes; planner still older merge path) |
| Record-level restore | **PARTIAL** (7 store types; not bookmarks/tab sets/links/prefs) |
| Recovery report UI | **DONE** |
| Application proxy policy for safe HTTP | **DONE** (refuse/direct only; no proxy transport) |
| Encrypted/authenticated backups | **BLOCKED** (design only) |
| Real Windows GUI/disk/power/live-sync tests | **NOT TESTED** |

The next safe increments are a legacy migration adapter for the remaining
versioned stores, planner/bookmark HTTP conflict archival, and record restore
for bookmarks/tab sets/links.  Encrypted backups require a reviewed
password/KDF/recovery-key design before implementation.

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
