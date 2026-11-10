# Mei — Integrity Monitor

## 1. Contract

`services/integrity_service.py` is **read-only**. A scan does not repair,
rewrite, quarantine or delete. It reads stores through
`storage_health.read_json_checked`, records findings, and returns a redacted
report. The UI runs it on a QThread so the shell stays responsive.

Repair is a separate operation (`quarantine_store`) that requires explicit
confirmation, attempts a verified pre-repair backup first, and then copies the
damaged file to quarantine. It still does not delete the live store.

## 2. Checks

### Structural

* missing file (normal; not a finding for optional stores);
* empty file (HIGH);
* invalid UTF-8 (CRITICAL);
* malformed JSON (CRITICAL);
* oversized file (HIGH);
* wrong root type (HIGH);
* collection key missing/not a list (HIGH);
* rows that are not objects (MEDIUM);
* missing record id (LOW);
* duplicate record id (MEDIUM);
* invalid timestamp-shaped field (LOW);
* implausibly far-future timestamp (LOW).

### Schema

Expected versions are known for `tab_sets.json` (4), `personal_plan.json` (2),
`flashcards.json` (1), `prefs.json` and `profile_meta.json` (2). A newer version
is HIGH: this build must not edit it.

### Referential (bounded)

* planner `items[].course_id` and `time_blocks[].course_id` must exist in
  `courses`;
* research workspace `notes`, `tasks`, `saved_pages`, `flashcards` references
  must resolve to existing files/records.

These are LOW findings: an orphan may be intentional history, and the monitor
does not delete it.

### Migration / restore

* active or `RECOVERY_REQUIRED` journal entry → HIGH;
* non-terminal restore journal → HIGH;
* quarantine artifacts present → INFORMATIONAL.

### Notes

Notes are counted and checked for empty files, symlinks, invalid UTF-8 and read
errors. Note text is never included in a finding.

## 3. Severity model

| Severity | Meaning |
|---|---|
| CRITICAL | primary store unreadable/corrupt; no automatic repair |
| HIGH | unsupported schema, damaged structural shape, unfinished migration/restore |
| MEDIUM | duplicate ids, non-object rows, unreadable note, invalid encoding |
| LOW | orphan reference, missing id, invalid/implausible timestamp, symlink |
| INFORMATIONAL | quarantine artifacts / optional state |

The summary status is `critical`, `attention`, `warnings` or `healthy`.

## 4. Redaction and performance

* Record identifiers are SHA-256 truncated to 8 characters in findings.
* Note contents, passwords, tokens and browsing history are never included.
* A scan walks notes and known stores; it does not scan `BrowserData` or the
  entire profile tree.
* Cancellation is checked between stores and directories. The UI runs the scan
  off the GUI thread.
* A large note is read only up to 16 MiB for encoding validation; it is not
  parsed as Markdown.
* No caching of scan results yet. A repeated scan repeats the work; that is
  intentional until invalidation semantics are proven.

## 5. Repair workflow

1. Scan (read-only).
2. `repair_plan(report)` gives a non-destructive suggestion per finding.
3. For a damaged store, `quarantine_store(..., confirm=True)`:
   * creates a verified backup (`kind="pre-repair"`); aborts if it fails;
   * copies the damaged file to quarantine;
   * leaves the live file in place.
4. Restore from a verified backup through the Restore Center when the user
   chooses to replace the damaged store.
5. Re-scan to confirm the result.

There is no "auto-fix everything" action. In particular, duplicate ids and
orphan references are not silently merged or deleted.

## 6. Limitations

* Only known stores in `core/storage_catalog.py` get structural checks. A future
  store must be added to the catalog to be scanned/backed up.
* No full cross-store referential graph; only planner courses and research
  workspace references are checked.
* No content checksums for stores outside a backup manifest, so silent bit rot
  inside otherwise-valid JSON is not detected unless the value shape is invalid.
* No scheduler; the user runs the scan from Data Management. Startup does not
  scan every large store.
* The UI worker has not been exercised under a real display in this batch.

## 7. Tests

`tests/test_data_integrity_services.py` covers healthy read-only scanning
(mtime unchanged), corrupt-store CRITICAL preservation, duplicate ids, orphan
planner references and cancellation.
## Batch 4 — storage-health inventory and UI

`storage_health.store_health()` and `health_summary()` expose one outcome per
catalogued store.  The shell banner and Data Management → Storage Health use the
same inventory, so a corrupt store cannot be presented as a normal empty store
without a visible warning.  Missing optional stores are not warnings.

Limitations: legacy page lists still use their existing default-returning read
APIs internally; the banner is the cross-page warning, and the write guard is
the safety boundary.  Notes are individual UTF-8 files and are not included in
the JSON-health inventory; their recovery path is per-file record restore.

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
