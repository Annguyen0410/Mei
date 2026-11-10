# Mei — Migration Journal and Recovery

## 1. What changed

Before this batch, a versioned store upgrade was:

```
read old payload → transform in memory → write_json(new payload)
```

The transform was deterministic, but there was no durable record of the attempt.
A crash during or after the replacement could leave a store at one version, its
profile stamp at another, and no explanation. Multi-store upgrades were worse:
filesystem writes are not one transaction.

`core/migration_journal.py` adds a local journal per profile:
`<profile>/Recovery/migration_journal.json`. It is deliberately small — one
JSON file, one entry per attempt, a byte snapshot of the source, explicit states.
It is not a distributed transaction manager and does not claim atomicity across
different stores.

## 2. Entry schema

| Field | Meaning |
|---|---|
| `id` | random operation id |
| `kind` | `mei.store_migration` |
| `store` | store filename, e.g. `personal_plan.json` |
| `source_schema_version` / `target_schema_version` | versions being bridged |
| `migration_implementation_version` | schema of the migration code itself |
| `started_at` / `last_update` / `completed_at` | Unix timestamps |
| `state` | see below |
| `snapshot` | relative path under `Recovery/migration_snapshots` |
| `input_sha256` / `output_sha256` | source bytes / committed result |
| `error` | failure text (paths and parse messages, no user content) |
| `recovery_action` | what a person should do when review is required |

States:

`PENDING → PREPARING → BACKUP_CREATED → APPLYING → VALIDATING → COMMITTED`

Failure states: `FAILED`, `RECOVERY_REQUIRED`, `ROLLED_BACK`.
`RECOVERY_REQUIRED` means "do not replay automatically"; it is not a synonym for
"corrupt" and it is not silently cleared.

## 3. Migration sequence

Implemented in `core/store.py::read_store` and
`core/migration_journal.py`:

1. Read the existing store through `storage_health.read_json_checked`.
2. If the file is missing, return the store default. If it is unreadable, raise
   `StoreReadError` after quarantine — never substitute the default.
3. Compute the stepwise migration through `core/migrations.py`.
4. Open a journal entry.
5. Copy the source bytes to `migration_snapshots/` and record input SHA-256.
6. Mark `APPLYING`.
7. Validate the transformed payload: object root, expected version, JSON
   serialisable with `allow_nan=False`.
8. Mark `VALIDATING`.
9. Write through the existing atomic temp+fsync+replace helper.
10. Record output SHA-256 and mark `COMMITTED`.

If any step raises, the code marks `RECOVERY_REQUIRED`, keeps the snapshot, and
returns the **original in-memory payload**. The original file is only replaced
once validation has passed; a failed `write_json` leaves it untouched.

If the journal itself cannot be opened, the migration is not attempted. A store
is never rewritten without a recoverable record.

## 4. Crash reconciliation

`migration_journal.reconcile(base_dir)` runs at startup through
`recovery_service.recover_startup`. It includes `RECOVERY_REQUIRED` entries, not
only active ones:

* store's current version ≥ target → replacement landed; mark `COMMITTED`;
* store version < target → mark `RECOVERY_REQUIRED` and keep the snapshot;
* store unreadable → `RECOVERY_REQUIRED`, no guess.

A crash after replacement but before the journal's final write is therefore
recognised as committed on the next launch. A crash before replacement is never
replayed silently; the user gets the snapshot and the integrity finding.

## 5. Idempotency and repeated reads

* Once the store on disk carries the target version, the normal path does not
  migrate again.
* A committed journal entry is historical; reconciliation is a no-op.
* A failed migration that left the source at the old version will be attempted
  again on the next read only when the ordinary migration path runs. The
  failure marker remains for audit; the code does not claim the earlier attempt
  succeeded.
* Migration steps are pure `dict → dict` functions. They must not perform I/O.

## 6. Future schema protection

`read_store` already returns a newer store untouched. `write_store` refuses to
overwrite it with `StoreWriteError`. Restore and integrity scanning also reject
a newer schema instead of downgrading it. A newer profile is readable where the
shape permits, but this build does not rewrite it.

## 7. Multi-store upgrades

Each store has its own journal entry and snapshot. There is **no** atomic
multi-store commit. If an upgrade changes several stores:

* one store may be committed while another remains at its old version;
* integrity scanning reports unfinished entries as HIGH;
* references between stores are not automatically repaired;
* the safe recovery is to restore the affected stores from the pre-upgrade
  backup, or complete the remaining migration explicitly.

The backup service creates a pre-migration snapshot only when a caller asks for
one; the migration journal snapshots each source store independently.

## 8. Limitations

* Only the three stores registered through `StoreSpec` (planner, tab sets,
  entity links) use this journal. Legacy ad-hoc stores have no schema registry
  to journal. Their corruption is preserved/blocked by `storage_utils`, and
  their backup/restore is covered.
* The journal is not encrypted. It contains paths, versions, hashes and error
  text, not store contents.
* A malicious process with the same Windows user can modify both store and
  journal. The journal detects accidental/crash states, not an attacker.
* Directory-entry durability is not guaranteed; file bytes are fsynced before
  replace, but Windows has no portable parent-directory fsync.
* Journal snapshots are not automatically pruned. They remain part of recovery
  evidence and are excluded from backups to avoid recursive copies.

## 9. Tests

`tests/test_data_integrity_services.py` covers:

* normal migration writes a `COMMITTED` entry with a byte-identical snapshot;
* crash-after-replacement is reconciled from `RECOVERY_REQUIRED` to
  `COMMITTED`;
* failed replacement leaves the source at the old version, keeps the snapshot
  and marks `RECOVERY_REQUIRED`;
* corrupt stores quarantine and refuse overwrite;
* legacy `read_json` damage is preserved and blocked from overwrite.
## Batch 4 — migration coverage matrix

`storage_catalog.migration_coverage()` is now the executable inventory.  It
contains 25 catalogued JSON stores plus a separate `SafeVault/notes` file-store
entry.  The matrix records manager, migration strategy, journal strategy,
backup eligibility, future-schema behavior and recovery path for every row.

| Manager | Count | Meaning |
|---|---:|---|
| `storespec` | 3 | `personal_plan.json`, `tab_sets.json`, `entity_links.json`; versioned, snapshot + migration journal, crash reconciliation. |
| `legacy` | 22 | Byte-preserving read/write guard and verified backup; no active versioned transform. |
| File store | 1 (notes) | Per-file atomic writes, backup and record restore; no JSON schema. |

Journal coverage is **3/25 = 12.0%**.  This number is deliberately reported
instead of describing every versioned store as migration-managed.  The legacy
stores do not have a journaled transform because no active schema transform was
introduced for them in this batch; adding one without a real conversion would
be worse than documenting the gap.

Cross-store ordering remains a design requirement for future migrations:
notes/tasks/planner are read by entity links and research workspaces, so a
future transform must commit dependencies first.  No migration is replayed
automatically from `RECOVERY_REQUIRED`.

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
