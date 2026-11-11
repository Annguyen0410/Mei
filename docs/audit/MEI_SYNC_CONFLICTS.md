# Mei — Sync Conflicts

## 1. Merge policy today

Folder sync (`services/sync_folder.py`) is a three-way merge against a baseline
of content hashes. Per record:

| Local | Remote | Baseline | Verdict |
|---|---|---|---|
| same | same | any | nothing |
| absent | new | absent | take remote |
| present | absent | unchanged local | delete local (tombstone) |
| present | absent | local edited | keep local + conflict record |
| unchanged | changed | — | take remote |
| changed | unchanged | — | keep local |
| absent | edited | present | resurrect remote + conflict |
| changed | changed | — | conflict |

Text-like stores (tasks, events, boards, saved pages, planner rows, notes) keep
both versions where the adapter supports duplication. Flashcards deliberately do
not auto-duplicate: the same card would enter the scheduling deck twice. The
remote card still goes into the conflict archive, so the information is not
lost.

`flashcards` conflict policy is therefore: local stays active, remote preserved
for manual resolution. This is stated rather than hidden.

## 2. Conflict archive

`services/conflict_service.py` persists
`<profile>/Recovery/conflicts.json`:

| Field | Meaning |
|---|---|
| `id` | conflict id |
| `signature` | SHA-256 of store + record id + local canonical hash + remote canonical hash |
| `store` / `record_id` / `title` | where it came from |
| `conflict_type` | `both_edited`, `delete_edit`, … |
| `source_device` | device id from the sync payload when available |
| `local` / `remote` | full archived rows, copied before any merge write |
| `local_sha256` / `remote_sha256` | content hashes |
| `status` | `pending`, `deferred`, `resolved` |
| `resolution` | action, timestamp, result hash, previous hashes |

The archive is stored locally, not in logs. It can contain note text and task
titles; a diagnostics report must not include it verbatim.

### Deduplication

The signature is stable for a given pair of versions. Pulling the same unchanged
remote snapshot again returns the existing entry instead of creating a new one.
That prevents an endlessly growing conflict list during retries.

Unresolved entries are never pruned to make room. Only the oldest **resolved**
entries are dropped when the 500-entry cap is exceeded.

## 3. Resolution

`resolve_conflict(..., action, confirm=True)` supports:

* `keep_local` — no store change; the local active version remains.
* `keep_remote` — replace the active record with the archived remote row.
* `keep_both` — ask the store adapter to add the remote row as a new record;
  rejected when the adapter has no safe duplication rule.
* `defer` — leave both versions archived and mark deferred.

Every action appends a history row with action, timestamp, result hash, store
and source device. A failed resolution does not delete either archived version.
An already resolved conflict is not applied twice.

The Data Management dialog lists pending/deferred/resolved conflicts, shows the
two versions, and requires confirmation before resolving.

## 4. Baseline and repeated sync

* After `keep_remote`, the local store now equals the remote version; the next
  sync sees no difference.
* After `keep_local`, the remote may still differ. The merge may classify the
  same pair as a conflict again, but the archived signature already exists and
  is not duplicated.
* Deferred conflicts remain visible; they are not treated as consent to
  overwrite.
* `keep_both` creates a new id for the duplicate, so the original conflict pair
  is not replayed as the same record.
* Missing tombstones and clock skew remain limitations of the existing
  three-way merge; a stale baseline can still produce a conflict, which is
  archived rather than silently dropped.

## 5. Self-hosted HTTP sync

`sync_service` preserves divergent note text by creating a
`"<title> (other device)"` note, and is idempotent for repeated pulls. Those
copies are visible as notes but are **not** inserted into the Conflict Center,
because the HTTP snapshot does not carry the same baseline/change record as
folder sync. This is a PARTIAL coverage difference, stated explicitly.

## 6. Limitations

* No three-way text merge; conflicts are whole-record choices.
* No record-level conflict resolution from the HTTP sync path.
* Conflict archive entries contain user content and live in the profile; they
  are excluded from backups only because `Recovery/**` is excluded. A user who
  wants them preserved should resolve them or copy the profile while preserving
  Recovery.
* Flashcard conflicts cannot be auto-merged into two active cards; keeping both
  would corrupt the review schedule.
* No live two-device test was run in this batch; existing tests use fixture
  payloads and temporary folders.

## 7. Tests

`tests/test_data_integrity_services.py` covers archive dedupe, explicit
confirmation, keep-local, keep-remote and history. Existing
`tests/test_sync_folder.py` covers the merge verdicts and both-copy policy.
## Batch 4 — HTTP sync Conflict Center integration

HTTP sync previously applied a last-writer-wins merge and reported conflicts
only in a transient result.  The row-store and note paths now call
`conflict_service.record_conflict` before applying a winner:

* both local and remote full records are archived;
* the signature is derived from store, record id and both versions, so retries
  and repeated pulls do not create duplicates;
* if the archive cannot be written, the local row is preserved rather than
  overwritten;
* the existing Conflict Center lists the row, shows both versions and supports
  keep-local / keep-remote / keep-both / defer where the store adapter allows it;
* the remote timestamp still decides the active row for a row store, but the
  losing version is durable.

**Partial:** planner `_merge_plan` and bookmark/history merges still use their
older merge rules and do not archive every divergent version.  Flashcard
duplication remains deliberately disabled for semantic safety; both versions
are archived but keep-both is refused.

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

## 2026-11 follow-up — durable sync gate

The HTTP sync path now has an independent operation journal at
`Recovery/sync_operation_journal.json`. The remote snapshot is staged under
`Recovery/sync_staging/<operation>.json` before any entity merge. Archive and
write failures set `ARCHIVE_PENDING` or `RECOVERY_REQUIRED`, keep the local row,
keep the baseline unchanged, and block push. A successful retry carries the prior
operation in `previous`, commits `BASELINE_COMMITTED`, and only then clears the
state-level block. Push refuses on an unresolved or damaged journal, and on any
non-healthy `sync_state.json`.

Pull returns typed outcomes; only an explicit `NO_REMOTE_SNAPSHOT` status may lead
to an initial push. A generic error whose text happens to contain "No snapshot
yet" is `NETWORK_ERROR` and cannot authorise a push. `_apply_bundle()` now raises
`SyncMergeError` instead of returning partial counts after a failed archive.

Remaining limitation: multi-store merges are not one atomic transaction. Earlier
stores may already be merged when a later store fails; the journal records applied
counts and the failed store, the conflict archive preserves both versions, and
retry is idempotent. There is no deterministic per-store resume checkpoint yet.
