# Mei — Data Management Guide

This is the ordinary-user guide for **Settings → Data Management**.

## 1. Where your data lives

Your profile is a folder. Mei stores preferences, notes, tasks, calendar,
boards, planner, flashcards and related indexes as files inside it. Chromium's
cookies/cache/local storage live in `BrowserData` inside the same profile.
Credentials use the OS-protected `secrets.dat`, not ordinary JSON.

The Data Management dialog shows the profile and runtime-data locations through
the Settings card.

## 2. Backups

### What is included

Notes, tasks, calendar, boards, saved pages, bookmarks, flashcards, planner,
research workspaces, routines, feeds, page monitors, focus sessions, permissions
and relevant settings.

### What is never included

* saved passwords and tokens (`secrets.dat`);
* proxy configuration;
* Chromium cookies, cache, local storage and `BrowserData`;
* downloads, favicon cache, logs, temporary files and Incognito data;
* Mei's own recovery/quarantine artifacts.

Preference keys that look like passwords/tokens are replaced with a redaction
marker. This is a safety net, not permission to store secrets in notes.

### Create and verify

1. Open **Settings → Data Management → Backups**.
2. Choose a destination outside the profile. The default is a sibling
   `Mei Backups` folder.
3. Click **Create backup now**. Mei writes a temporary archive, verifies its
   manifest and every checksum, then publishes it.
4. Select an archive and click **Verify selected** to re-check it later.

**Apply retention** removes only old *verified* backups and never the newest
one. Unverified/corrupt archives are left for inspection.

Backups are **not encrypted**. Protect the backup folder with your OS account
and disk encryption. Do not upload a backup to a service you do not trust.

## 3. Restore Center

1. Open **Restore Center**.
2. Select a verified backup.
3. Tick the categories to restore (tasks, notes, planner, etc.).
4. Click **Preview**. Check added/replaced counts and any schema warnings.
5. Click **Restore selected** and confirm.

Before replacing anything, Mei creates a pre-restore backup. It then stages the
selected files, validates them, records rollback copies and only then writes.
If something fails, it rolls the written files back. If rollback itself fails,
the result says **recovery required**; do not keep editing that profile until
the journal is reviewed.

Restore is file/category based. It does not merge individual records; a selected
store is replaced by the backup's version. Secrets are never restored.

## 4. Integrity Check

**Run integrity check** is read-only. It reports:

* unreadable/corrupt stores;
* unsupported newer schemas;
* duplicate record ids;
* broken planner course references and research workspace links;
* invalid timestamps;
* unfinished migrations/restores;
* quarantined artifacts.

Findings include hashed record references, not note text or secrets. A healthy
scan does not modify a single file.

If a store is damaged, first make a backup of the current profile if possible,
then restore the store from a verified backup. **Quarantine** copies the damaged
file for inspection and does not replace it automatically.

## 5. Sync Conflicts

Folder sync preserves both sides when it cannot merge. **Sync Conflicts** lists
archived conflicts with the local and remote versions.

Actions:

* **Keep local** — leave the active local record;
* **Keep remote** — apply the archived remote record;
* **Keep both** — add the remote version as a separate record where the store
  supports it;
* **Defer** — keep both archived and decide later.

Every resolution is recorded in history. A repeated sync does not create a new
entry for the same pair of versions.

Flashcards are special: keeping both would duplicate a scheduled card, so the
remote version stays in the archive for manual handling instead of being added
to the deck.

## 6. After an unexpected shutdown

Mei writes a session marker and recovery journals. On the next launch it:

* reconciles a migration that already reached its target version;
* quarantines old atomic-write temporary files;
* leaves an unfinished restore or ambiguous migration for review.

The report is stored at `Recovery/last_startup_report.json` inside the profile.
It contains paths, states and hashes, not note text.

## 7. If a file is corrupt

1. Do not repeatedly open/save the affected editor; writes are blocked while
   the damaged file is marked.
2. Open **Integrity Check** and note the finding.
3. Open **Backups**, create a backup if the profile is still readable, and
   verify it.
4. Restore the affected category from a verified backup.
5. Re-run the integrity check.

A hidden `.corrupt-*.bak` copy may sit next to a legacy damaged JSON file; it is
the byte-for-byte copy Mei preserved before blocking overwrite. Keep it until
you have restored or inspected the data.

## 8. Important limits

* Backups are local files; they do not protect against a deleted backup folder,
  ransomware or a compromised Windows account.
* There is no cloud backup or encryption in this batch.
* Automatic backup cadence is not a background timer; create backups explicitly
  (the due/retention policy is available to future scheduling).
* Restore is category-level, not individual-record recovery.
* Chromium profile recovery remains engine-owned.
## Batch 4 — Data Management surface

The dialog now contains:

* **Backups** — manual verified archive, destination, retention, scheduler
  status and last attempt/error.
* **Restore Center** — full/category staged restore with preview and rollback.
* **Record Restore** — one task/event/board/page/flashcard/planner item or note,
  with preview and as-new mode.
* **Storage Health** — 25-store inventory and migration coverage.
* **Integrity Check** — read-only scan.
* **Sync Conflicts** — folder and HTTP conflict archive/history.
* **Recovery** — last startup report and unresolved operations.
* **Proxy** — redacted app/environment policy and explicit direct opt-in.

The dialog remains modular and uses the existing Qt styling.  It was compiled and
unit-wired, but the visual layout was not exercised under a live display in this
batch.

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
