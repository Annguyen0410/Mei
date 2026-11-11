# Mei — Backup and Restore

## 1. Backup format

A backup is a ZIP named `mei-<kind>-<UTC>-<id>.mei-backup.zip` containing:

* `mei-backup-manifest.json` — format version, backup id, timestamp, Mei version,
  profile id (hash of the normalized profile path), included categories,
  exclusions, per-store schema versions, file sizes, SHA-256 values and status;
* the allowlisted profile files;
* `SafeVault/notes/**` Markdown/text notes.

The manifest contains **no secret values** and no note contents.

## 2. Scope and exclusions

Included by allowlist (`core/storage_catalog.py`): preferences, profile metadata,
tasks, calendar, boards, saved pages, bookmarks/folders, flashcards, planner,
research/tab sets, workspace metadata, entity links, permissions, routines,
feeds, monitors, focus sessions, AI settings/index, extension settings, download
list, and notes.

Never included:

* `secrets.dat` (DPAPI-protected credentials);
* `proxy_config.json` (may contain a legacy plaintext password);
* `BrowserData/**` (cookies, cache, local storage, Chromium profile);
* `Recovery/**` (quarantine, migration snapshots, journals);
* downloads, favicon cache, logs, temporary files, Incognito data.

`prefs.json` is scrubbed before writing: keys whose lower-case name matches
`password`, `token`, `access_token`, `refresh_token`, `api_key`, `secret`,
`authorization`, `private_key`, etc. become `[redacted by Mei backup]`. The
exclusion is recorded in the manifest. This is defence in depth, not a promise
that arbitrary user text is free of secrets.

## 3. Atomic creation

1. Acquire the profile lock.
2. Read each allowlisted store with `storage_health.read_json_checked`; an
   unreadable store aborts the backup instead of producing a partial one.
3. Walk notes without following symlinks; skip/report symlinked notes.
4. Build the manifest and file list in memory, enforcing per-file and total
   limits.
5. Write a sibling `.<name>.part` ZIP with the manifest first.
6. fsync the archive.
7. Re-open and verify the **part** file: manifest kind/version/status, safe
   paths, no symlinks, exact sizes, SHA-256 of every member, no unlisted extras,
   total expansion limit.
8. Only then `os.replace(part, final)`. A failed verification is renamed
   `.failed` and never listed as a completed backup.

An incomplete or failing archive therefore cannot look successful.

## 4. Destination and retention

The default destination is a sibling of the profile:
`<profiles>/Mei Backups/<profile-name>`. A destination inside the active profile
is refused, so deleting/corrupting the profile does not automatically delete its
backups. The destination can be changed in Data Management; it must remain
outside the profile.

`apply_retention` keeps:

* the newest verified backup, unconditionally;
* up to `daily_keep` recent archives;
* one per ISO week for `weekly_keep` weeks;
* one per month for `monthly_keep` months.

Only **verified** archives are eligible for deletion. Unverified/corrupt
archives are left for inspection. The newest verified copy is never deleted.

Defaults: 7 daily, 4 weekly, 6 monthly. The policy lives in the `backup_policy`
preference and is editable in the UI.

Scheduling: `due_for_backup()` knows daily/weekly/manual cadence, and the UI
creates backups explicitly. **No OS timer daemon runs in this batch.**

## 5. Restore Center

### Preview

`restore_service.preview` verifies the archive first, then lists each selected
file with:

* current exists/absent;
* current vs backup SHA-256 and changed/unchanged;
* current and backup record counts where the store has a row collection;
* schema warnings for a backup newer than this build.

Unknown files in a manifest are ignored and warned about. Unsafe paths are
rejected.

### Restore

1. Require explicit confirmation and a selected category set.
2. Verify the backup and build the preview.
3. Create a **pre-restore backup**; abort if it cannot be verified.
4. Extract selected members into
   `<profile>/Recovery/restore_staging/<operation>/`, using
   `safe_child_path` against traversal/absolute paths and refusing oversized
   members.
5. Validate JSON root shape and schema version before touching the profile.
6. Copy the current bytes of every target into a rollback directory.
7. Write a restore journal in `Recovery/restore_journal.json`; mark `APPLYING`.
8. Replace targets with temp+fsync+replace.
9. Re-validate every restored JSON store.
10. Mark `COMMITTED` and remove staging.

If any step fails, every written target is restored from its rollback copy (or
removed if it did not exist). If rollback itself fails, the journal and result
say `RECOVERY_REQUIRED`; Mei does not claim the profile is intact.

Restore categories are file-level groups (`tasks`, `calendar`, `notes`,
`bookmarks`, …). It is **not** a record-level merge. The preview shows what will
be replaced before confirmation.

## 6. Compatibility

* A backup from a newer format version is rejected as `incompatible`.
* A store from a newer schema is rejected during restore validation.
* Older backups are accepted only when the on-disk shape still validates; no
  untested downgrade is performed.
* Credentials are absent, so restoring an old profile never restores an old
  password, token or proxy credential.

## 7. Security properties and limits

* ZIP traversal and absolute paths are rejected; symlink members are rejected.
* Per-member and total expansion limits bound memory/disk use.
* Destination is outside the profile; a malicious manifest cannot choose an
  arbitrary target path because every path is checked against the profile root.
* Backups are **not encrypted**. A backup destination is ordinary user data;
  protect it with OS permissions/disk encryption.
* There is no cloud upload. A cloud-synced destination is a user choice and is
  not treated as a transactional filesystem.
* A malicious process running as the same user can alter a backup and its
  manifest; checksums detect accidental corruption, not a keyed authenticity
  attack.
* No real disk-full, removable-disk removal or power-loss test was run.

## 8. Tests

`tests/test_data_integrity_services.py` covers verified creation, secret and
BrowserData exclusion, prefs redaction, inside-profile destination refusal,
tampered checksum rejection, traversal/incomplete rejection, retention keeping
the newest, confirmation requirement, pre-restore backup, selective restore,
rollback after a simulated commit failure, and future-schema refusal without
touching the current store.
## Batch 4 — automatic scheduling, conflict backup and record restore

### Scheduler

`services/backup_scheduler.py` adds an in-process scheduler used by `AppShell`:

* checks daily/weekly policy at startup (5 s defer) and every 30 minutes;
* refuses while a restore journal needs review or a migration is active or
  `RECOVERY_REQUIRED`;
* uses a non-blocking attempt lock and the backup service's creation lock, so
  manual/scheduled/pre-restore calls cannot write duplicate archives;
* records `last_attempt_at`, `last_status` and `last_error` under
  `Recovery/backup_scheduler_state.json`;
* a failed attempt never advances `last_success_at`;
* retention runs only after a verified archive is published.

This is **not** an OS scheduler.  Mei makes no claim that a backup happens while
the application is closed.  The scheduler is tested with a deterministic clock;
real timers and GUI progress were not exercised interactively.

### Conflict archive

`Recovery/conflicts.json` is an explicit backup allowlist entry, not a recursive
backup of `Recovery/**`.  It contains both full versions, signatures, source
type, status and resolution history.  Restore validates the archive and merges
by signature; it never activates a version.  A repeated restore is a no-op.

### Record restore

`services/record_restore_service.py` supports tasks, events, boards, saved pages,
flashcards, planner items and notes.  It validates the backup record, requires
explicit confirmation, creates a full `pre-record-restore` backup, writes
through the existing store writer, and records a redacted history row.  Existing
records require confirmation; `as_new` allocates a new id.  Bookmarks, tab sets,
entity links, preferences and other stores are **not** record-restorable yet.

### Encryption

No encrypted backup format is shipped.  SHA-256 remains a corruption checksum,
not a signature.  The threat model and proposed authenticated-encryption design
are in `MEI_BACKUP_ENCRYPTION.md`; status is **BLOCKED** rather than silently
shipping incomplete cryptography.

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

## 2026-11 follow-up — verified rollback classification

Restore recovery no longer treats "not original" as "safe to overwrite". The
journal target states are now explicit: `ORIGINAL`, `STAGED`, `MISSING`, `UNKNOWN`,
`UNREADABLE`. Rollback accepts only `STAGED` (or an explicitly policy-approved
missing original) and requires a readable rollback copy whose SHA-256 equals the
journal's original hash. It writes the journal state before and after each atomic
replacement and verifies the read-back. `UNKNOWN` and `UNREADABLE` targets are
preserved and the journal becomes `RECOVERY_REQUIRED`.

The critical regression constructs original A, stages B, crashes, writes an
independent C, then runs recovery: C remains byte-for-byte unchanged and A/B
artifacts are retained. See `tests/test_followup_safety.py::TestRestoreRollbackClassification`.

Remaining limitation: real process termination and disk-full/power-loss were not
available; interruption is injected deterministically in-process.
