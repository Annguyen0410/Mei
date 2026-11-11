# Mei — Data Integrity, Disaster Recovery & Profile Resilience

Status of this document: implementation audit for branch `new-main`, batch
"Data integrity, disaster recovery and profile resilience" (November 2026).

Scope: every profile store Mei writes, migration handling, corruption detection,
quarantine, backups, restore, sync conflicts, crash recovery and the read-only
integrity monitor. Chromium's own `BrowserData` remains outside these
transactions; it is a separate engine-owned store and is deliberately excluded
from backup and restore.

## 1. Storage inventory

| Store / data | Format | Versioned? | Writer | Backup | Folder sync |
|---|---|---|---|---|---|
| `prefs.json` | JSON object | schema stamp (`schema_version`) | `core/prefs.py` | yes, secret-shaped keys redacted | no |
| `profile_meta.json` | JSON object | schema stamp | `core/prefs.py` | yes | no |
| `tasks.json` | JSON list | no per-store schema | `life_service` | yes | yes |
| `calendar.json` | JSON list | no | `life_service` | yes | yes (`events`) |
| `boards.json` | JSON list | no | `life_service` | yes | yes |
| `saved_pages.json` | JSON list | no | `life_service` | yes | yes |
| `bookmarks.json` / `bookmark_folders.json` | JSON list | no | `prefs` | yes | partial |
| `flashcards.json` | JSON object `{version,cards}` | v1 | `flashcard_service` | yes | yes |
| `personal_plan.json` | JSON object | v2 through `StoreSpec` | `personal_plan` | yes | yes |
| `tab_sets.json` | JSON object | v4 through `StoreSpec` | `tab_sets` | yes | yes |
| `entity_links.json` | JSON list | no | `link_service` | yes | yes |
| `permissions.json` | JSON object | no | `prefs` | yes | no |
| `routines.json`, `feeds.json`, `monitors.json` | JSON objects | no | services | yes | no |
| `focus_sessions.json`, `session.json`, `workspaces.json` | JSON | no | services | yes | no/partial |
| `ai_index.json`, `ai_settings.json` | JSON | no | AI service | yes (index rebuildable) | no |
| `extensions.json`, `extension_imports.json` | JSON | no | extension bridge | yes | no |
| `SafeVault/notes/**` | Markdown/text files | n/a | `personal_service` | yes | yes (note records) |
| `secrets.dat` | DPAPI-protected JSON | v1 | `secret_store` | **never** | **never** |
| `proxy_config.json` | JSON | no | `prefs` | **never** (may hold legacy plaintext) | no |
| `BrowserData/**` (cookies, cache, local storage) | Chromium files | engine-owned | QtWebEngine | **never** by default | no |
| `Recovery/**` (quarantine, snapshots, journals) | JSON + byte copies | internal | recovery services | **never** (avoid recursive copies) | no |

`core/store.py` owns versioned JSON stores; `core/storage_utils.py` owns atomic
replacement; `core/profile_lock.py` serialises in-process writers and claims a
profile across processes. Those were the prerequisites, not a backup system.

## 2. Confirmed risks and disposition

| ID | Finding | Severity | Disposition |
|---|---|---|---|
| D-01 | `read_json(path, default)` treated malformed JSON as an absent store; a later save replaced recoverable bytes. | HIGH | **FIXED (partial UI)** — legacy reads still return the caller's default so one optional store cannot crash the shell, but the bytes are copied to a hidden `.corrupt-*.bak`, the path is marked, and every later `write_json` refuses to overwrite it until a successful read proves repair. Versioned stores go further: they raise `StoreReadError` and quarantine the original. |
| D-02 | Store migrations ran in memory and were written without a durable journal; a crash between stores could not be diagnosed. | HIGH | **FIXED for `StoreSpec` stores** (planner, tab sets, links). **PARTIAL** for legacy ad-hoc stores, which have no registered migration path to journal. |
| D-03 | No independent, verified backup; note export was the only portable copy and sync could delete the only snapshot. | HIGH | **FIXED** — checksum-manifested zip backups outside the profile; incomplete archives never published. Scheduling is **PARTIAL** (due calculation + UI manual action; no OS timer daemon). |
| D-04 | Restore did not exist as a staged, reversible operation. | HIGH | **FIXED** for full/selective file categories. **PARTIAL**: no individual-record restore UI, and restore replaces a selected store rather than merging it. |
| D-05 | Folder-sync conflicts kept both copies in many cases but the losing version was not durable after the dialog closed. | HIGH | **FIXED** — every conflict pair is archived with hashes, deduplicated across repeated syncs, and resolutions are logged. `flashcards` cannot auto-keep-both (scheduling identity), but the remote version remains in the archive. |
| D-06 | No crash marker; a stale lock file was the only signal and OS locks are released automatically. | MEDIUM | **FIXED** — session marker with clean-exit flag; startup reconciles migration journal and quarantines stale atomic-write temp files. |
| D-07 | No read-only integrity scan across stores. | MEDIUM | **FIXED** — structural, schema, duplicate-ID, timestamp, planner/research reference and journal checks. Repair is limited to explicit quarantine with a pre-repair backup. |
| D-08 | No proxy policy for direct-only outbound fetches; env proxy variables were silently ignored. | MEDIUM | **FIXED for environment proxies** (`safe_http` now returns `FetchProxyUnsupported`). **PARTIAL**: the application proxy preference is not yet passed into `safe_http`; Page Monitor does not consult it. |
| D-09 | Disk-full and real OS shutdown were not fault-injected. | MEDIUM | **POTENTIAL** — atomic replacement preserves the old file on write failure (unit-tested with mocked `write_json` failure), but no real full-disk test was run. |
| D-10 | Cloud upload and directory-level fsync are not implemented. | LOW | **PARTIAL** — opt-in AES-256-GCM/scrypt `.mei-backup.enc` files are implemented and automated-tested; cloud upload and directory fsync are still not implemented. Scheduled backups remain unencrypted. |

## 3. Corruption handling contract

1. **Missing** file = legitimate first run; a store default is allowed.
2. **Empty** file = not the same as missing; it is reported/quarantined as damage.
3. **Malformed / invalid UTF-8 / wrong root** = preserve bytes, never invent an
   empty store.
4. **Future schema** = read-only; the existing writer already refuses to
   downgrade. Migration and restore reject newer versions.
5. **Quarantine** copies, never moves, the source; names include UTC time,
   store name, SHA-256 prefix and a collision suffix. The original remains in
   place for the owning process.
6. A **failed write** never replaces the previous valid file: `write_json`
   serialises first, writes a same-directory temp, fsyncs, then `os.replace`
   with bounded Windows lock retries.

## 4. Services added in this batch

| Module | Responsibility |
|---|---|
| `core/storage_health.py` | checked JSON read statuses, byte preservation, quarantine metadata, file hashing |
| `core/migration_journal.py` | durable states, snapshots, crash reconciliation |
| `core/storage_catalog.py` | one store inventory shared by backup/restore/integrity |
| `services/backup_service.py` | atomic verified backups, manifest/checksums, retention, exclusions |
| `services/restore_service.py` | verification, preview, staged restore, pre-restore snapshot, rollback |
| `services/integrity_service.py` | read-only scan, severity model, redacted findings, explicit quarantine |
| `services/conflict_service.py` | archived conflict pairs, dedupe, audited resolution |
| `services/recovery_service.py` | session marker, startup inspection, safe stale-temp recovery |
| `ui/dialogs/data_management.py` | Backups / Restore Center / Integrity / Conflicts |

`core/store.py` now journals every `StoreSpec` upgrade. `core/storage_utils.py`
now protects damaged legacy stores from being overwritten. `sync_folder.py`
archives conflicts in addition to its existing merge. `main.py` starts/ends the
session marker. The Settings page exposes Data Management.

## 5. Verification in this batch

| Check | Result |
|---|---|
| New data-integrity suite | `tests/test_data_integrity_services.py` — 32 tests |
| Existing storage/migration/sync tests | pass after the documented corrupt-store behaviour change |
| Full suite | see `MEI_REMEDIATION_CHANGELOG.md` (final run after all edits) |
| Ruff (`F401,F811,F841,F821`) | pass |
| `py_compile` (new/changed modules) | pass |
| Desktop GUI interaction | **NOT TESTED** — no display session was driven in this batch |
| Real disk-full / power loss | **NOT TESTED** |
| Live sync with two devices | **NOT TESTED** here; existing sync tests are offline |

## 6. What this audit does not claim

* It does **not** claim every legacy store has a schema migration. Only three
  stores use the versioned registry; the rest are covered by preservation,
  backup, integrity detection and restore, not by automatic upgrades.
* It does **not** claim a corrupt legacy store displays a recovery banner. Its
  read still returns the caller's default; the guarantee is that its bytes are
  preserved and a later write is blocked.
* It does **not** claim backup encryption, cloud backup, ransomware protection or
  protection against a malicious process running as the same Windows user.
* It does **not** claim directory-entry durability on every filesystem. File
  contents are fsynced before replacement; parent-directory fsync is not
  portable on Windows and is not performed.
* It does **not** claim individual-record restore or a merged restore. Restore
  replaces the selected store file after preview and confirmation.
* It does **not** claim automatic backups run on a timer. `due_for_backup` and
  retention exist; the current UI creates backups explicitly.
* It does **not** claim the app proxy preference is enforced by `safe_http` yet.
  Environment proxy variables are enforced; the application proxy remains a
  residual compatibility gap.
## Batch 4 — legacy visibility and write-time protection

### What changed

* `storage_utils.write_json` now examines the existing file before replacing it.
  A malformed or zero-byte JSON file is copied to an adjacent
  `.corrupt-<timestamp>-<nonce>.bak` and the replacement is refused.  This
  protects a background writer that runs before any UI read after a restart.
* `storage_health.health_summary` / `store_health` provide one explicit outcome
  per catalogued store: missing, empty, malformed, wrong root, oversized,
  unreadable or readable.
* `StorageHealthBanner` appears above the shell whenever a catalogued store is
  unavailable.  It names the affected stores, states that original bytes were
  preserved, and opens Data Management.
* Data Management now has **Storage Health**, **Recovery** and **Proxy** tabs.
* `write_json` serializes same-process writers, so the new pre-write inspection
  cannot misclassify a valid file being atomically replaced by another thread.

### Honest limitation

Legacy read APIs still return their caller default so an optional damaged store
cannot crash the whole shell.  The banner and write guard make that state
visible and non-destructive, but every individual task/notes/planner page does
not yet replace its empty-state copy with a store-specific recovery panel.
This is therefore **PARTIAL**, not a claim that corrupt data looks perfect.

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

## 2026-11 follow-up — honest storage lifecycle coverage

`storage_catalog.STORES` contains 26 persistent JSON entries plus the
`SafeVault/notes` file store. Coverage is classified, not inflated:

- **3 journaled versioned transforms:** `personal_plan.json`, `tab_sets.json`,
  `entity_links.json` (durable snapshot + migration journal).
- **22 legacy/stable JSON stores:** validated root shape, byte-quarantined on
  corruption, write-guarded after damage, included in verified backups and record
  restore where an adapter exists. They have no active versioned transform because
  their shape has not required one.
- **1 explicit conflict archive** (`Recovery/conflicts.json`): merge-only import,
  idempotent by conflict signature, never replaced by an older backup.
- **Notes:** markdown file store with atomic per-file writes, no JSON schema.

Unknown future versions are read-only: restore/import validation refuses a version
above the current schema. No historical schema was invented, and no store is called
migration-managed merely because it carries a version field. `migration_coverage()`
returns this classification so documentation and tests cannot drift.

Remaining limitation: coverage is an honest lifecycle contract, not 26 versioned
migrations. Real historical fixtures exist only for stores whose formats changed.
