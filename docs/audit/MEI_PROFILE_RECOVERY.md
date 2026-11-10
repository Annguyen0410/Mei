# Mei — Profile Crash Recovery

## 1. Why a lock file is not enough

Windows releases an OS file lock when the owning process exits, cleanly or not.
The presence of `.mei-profile-lock` therefore cannot distinguish a crash from a
normal previous run. Mei now writes an explicit session marker at startup:

`<profile>/Recovery/session_state.json`

```json
{
  "kind": "mei.session",
  "version": 1,
  "session_id": "...",
  "pid": 1234,
  "started_at": 0,
  "last_update": 0,
  "clean_exit": false,
  "ended_at": 0
}
```

`main.py` calls `begin_session` only after the process has claimed the profile,
then `recover_startup`, and `finish_application` flips `clean_exit` on
`QApplication.aboutToQuit`.

The marker is a hint, not proof. OS shutdown, process kill, debugger stop and a
Windows crash can all leave `clean_exit: false`.

## 2. Startup inspection

`recovery_service.inspect_startup` reports:

* previous session clean/unclean;
* pending or `RECOVERY_REQUIRED` migration journal entries;
* restore journal state;
* incomplete `.part` / `.failed` backups in the configured destination;
* stale hidden atomic-write temp files older than 24 hours;
* number of quarantine artifacts.

It writes nothing. `recover_startup` then performs only safe actions:

1. Reconcile migration entries against the current store version.
2. Quarantine stale temp files, remove the temp only if its hash still matches
   the preserved copy.
3. Leave unfinished restores and incomplete backups for explicit review.
4. Write `Recovery/last_startup_report.json`.

The Data Management dialog does not currently render the startup report; the
file is available for support and a future UI. An unclean shutdown does not
raise a modal warning by itself, because a forced OS restart is common and a
warning without a concrete finding would train users to dismiss it.

## 3. Atomic-write behavior

`storage_utils.write_json` and `write_text_atomic`:

* serialise/encode before creating a temp file;
* create the temp in the destination directory (same filesystem);
* write, flush, `fsync` file contents;
* replace the target with `os.replace`;
* retry a transient Windows `PermissionError` up to five times;
* remove the temp on failure.

The previous file remains untouched until replacement succeeds. A crash during
write can leave a hidden temp file, which startup quarantines after it is old
enough.

Known limit: parent-directory `fsync` is not portable on Windows and is not
performed. File contents are fsynced; the directory entry durability is left to
the OS/filesystem.

## 4. Disk exhaustion

A full disk causes `write_json` to raise. Because serialization happens before
the temp is created and replacement happens last, the previous valid store
survives. Migration catches the write failure, marks `RECOVERY_REQUIRED`, keeps
the source snapshot and returns the old payload. Restore catches the failure and
rolls back already-written targets from the rollback copies.

This is exercised with mocked write failures, **not** by filling a real disk.
No claim is made about Chromium's own disk-full behavior.

## 5. Quarantine

`storage_health.quarantine_file` copies, never moves, a damaged file to
`Recovery/quarantine/<UTC>-<store>-<sha12>.<ext>` plus a `.json` sidecar:

* original relative path;
* category, reason and detail;
* size and SHA-256;
* source preserved flag;
* artifact name.

Collisions get a random suffix; no earlier artifact is overwritten. Permissions
are tightened to owner-only where the platform supports it. Quarantine is
excluded from backups to avoid recursively copying damaged data.

Normal reads never automatically delete a quarantine artifact. The user can
inspect it, restore from a verified backup, or ask support to examine it.

## 6. Interrupted restore

`restore_service` writes `Recovery/restore_journal.json` with `PREPARING`,
`APPLYING`, `COMMITTED` or `FAILED`/`RECOVERY_REQUIRED`. If startup sees a
non-terminal restore state, it reports it but does not replay or discard it: a
partially applied multi-file restore needs the rollback evidence in
`Recovery/restore_staging`.

## 7. Limitations and manual tests still required

* **NOT TESTED** on a real forced power loss or Windows bugcheck.
* **NOT TESTED** on a real full disk or removable drive disappearing mid-write.
* No GUI test of startup after a crash; the service path is unit-tested.
* A user who deletes `Recovery/**` removes the snapshots/journals and loses the
  automatic diagnosis, though the stores themselves are unaffected.
* A malicious same-user process can forge a clean marker; this is crash
  recovery, not tamper detection.
* Chromium's own profile recovery is engine-owned and outside this design.

## 8. Tests

`tests/test_data_integrity_services.py` covers clean/unclean markers, stale-temp
quarantine + hash-checked removal, recovery-report writing and migration
reconciliation. `tests/test_profile_storage_safety.py` covers atomic writes,
transient replace retries and invalid payloads not touching the existing store.
## Batch 4 — startup recovery report UI

Data Management → **Recovery** is now a read-only view of
`Recovery/last_startup_report.json` plus live inspection:

* clean vs unclean previous session;
* pending migration entries and their state;
* interrupted restore state;
* incomplete `.part`/`.failed` backups;
* stale temporary files and quarantine artifact count.

Unresolved migration and restore states are shown as actions requiring review;
resolved or absent states are not presented as active emergencies.  The view
uses store names, journal states and counts, never note bodies or secrets.  It
does not auto-restore or replay anything.

The last report is the only historical report retained; a report history browser
is not implemented.

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
