# Mei data-integrity closure — 2026-11

Status vocabulary: **IMPLEMENTED**, **TESTED**, **PARTIAL**, **BLOCKED**,
**NOT TESTED**. This document records the actual code and tests, not a design
claim.

## Scope delivered

### Authenticated encrypted backups

- New `litebrowser/services/encrypted_backup_service.py`.
- AES-256-GCM with fresh 16-byte salt and 12-byte nonce.
- scrypt `n=32768`, `r=8`, `p=1`, 32-byte key.
- Versioned binary header authenticated as associated data.
- Existing ZIP/manifest verification retained after decryption.
- Explicit UI creation, password verification and encrypted restore in
  Data Management.
- Legacy `.mei-backup.zip` remains importable and is never called encrypted.
- No recovery key; lost password is unrecoverable.

### HTTP sync conflict preservation

- Planner item/course/time-block divergences are archived before any winner.
- Planner conflict IDs use the folder-sync `item:`/`course:`/`block:` shape.
- Planner comparison uses the planner's own normalizer, preventing repeated
  sparse-vs-normalized conflicts.
- Bookmark URL divergences archive both versions and keep the local bookmark.
- A failed archive blocks the corresponding planner or note replacement.
- Notes no longer update an existing note when conflict archival fails.
- History remains append-only: it never replaces or deletes a local entry, so
  there is no destructive history divergence to archive.

### Record-level recovery

Added bookmark, tab-set/research and entity-link adapters. Bookmark identity is
its URL; restoring a bookmark as new is refused because it would duplicate an
external reference. Tab sets and links use their owning services, not raw JSON
replacement.

### Page-level unavailable states

`components.PageStoreNotice` is now embedded in Home, Library and Settings. It
names the unavailable stores relevant to that page and explicitly says an empty
list is not a real empty result. The global `StorageHealthBanner` remains above
the whole shell. Unaffected pages continue to work.

### Store inventory correction

`entity_links.json` is actually `{"version": ..., "links": [...]}`. The catalog
now records `dict`/`links` instead of the incorrect `list`, so backups no longer
refuse a healthy link store.

## Store coverage

The existing catalog has 25 JSON stores plus the notes file-store. Current
classification:

- **3/25** use journaled versioned transforms:
  `personal_plan.json`, `tab_sets.json`, `entity_links.json`.
- **22/25** are legacy/read-write-protected and have validation/quarantine,
  backups and recovery, but no new active schema transform in this batch.
- Notes remain per-file UTF-8 with atomic writes and record restore.
- External Chromium data, credentials, caches and proxy configuration remain
  excluded from backups.

This is **not** 100% migration coverage. The remaining 22 stores are explicitly
classified as legacy; no store is called migration-managed merely because it
appears in the catalog.

## Record restore support

Supported:

- tasks;
- calendar events;
- boards;
- saved pages;
- flashcards;
- planner items;
- notes;
- bookmarks (URL identity, replace only);
- tab sets/research collections;
- entity links.

Still unsupported: bookmark folders, workspaces, preferences, AI index, routines,
feeds, monitors, focus sessions, downloads and extension metadata.

## Verification

- Full suite: **1205 passed, 1413 subtests passed in 136.58 s**.
- Focused closure/UI/data/sync set: **75 passed, 88 subtests**.
- Encryption/wrong-password/tamper/truncation/legacy tests: 13 in
  `tests/test_data_integrity_closure.py`.
- Ruff `F401,F811,F841,F821`: clean.
- `py_compile`: clean.
- `git diff --check`: clean.

## Explicitly not tested

- Real GUI interaction under a display.
- Two physical devices doing encrypted backup restore.
- Real disk-full, forced power loss, removable-media removal.
- Packaged EXE/installer and Authenticode.
- Independent cryptographic review.
- Application proxy transport (still direct/refuse policy only).
- The 22 legacy stores were not given fabricated historical migrations.

## Remaining risks

| Severity | Risk | Consequence | Next step |
|---|---|---|---|
| High | Legacy migrations remain 3/25 | An old legacy schema may still require manual recovery | Add per-store transforms with fixtures, one store at a time |
| High | Backup password loss is permanent | Encrypted backup cannot be opened | Add a documented recovery-key design before claiming recoverability |
| Medium | Encrypted backups are opt-in only | Scheduled backups remain plaintext | Decide whether OS-backed key storage is acceptable |
| Medium | GUI was not exercised | Layout/prompt defects may remain unseen | Run the manual GUI checklist |
| Medium | HTTP bookmark conflicts keep local without a merge UI | User must inspect conflict archive | Add a bookmark-specific resolution view |
| Low | History has no conflict archive | Append-only history cannot overwrite; duplicate tuples are ignored | Document as non-destructive by design |
| Low | 22 stores are not record-restorable | Whole-category restore is still required | Add adapters only where IDs and references are stable |

## Reproduce

```powershell
.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider --no-header -q
.\.venv\Scripts\python.exe -m ruff check --select F401,F811,F841,F821 litebrowser tests
.\.venv\Scripts\python.exe -m py_compile litebrowser/services/encrypted_backup_service.py
git diff --check
```

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
