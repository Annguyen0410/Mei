# Mei critical data-safety remediation — 2026-11

Base review branch: `mei/data-integrity-closure-2026-11`
Reviewed commit: `43e805875d8298c810bdbac0be26bfd563caad08`
Implementation branch: `mei/critical-data-safety-fixes-2026-11`

This is an evidence record, not a claim of complete production assurance. The
branch was created from the reviewed HEAD; `new-main` and the original review
branch were not modified.

## Status

| Finding | Status | Evidence |
| --- | --- | --- |
| Corrupt-store quarantine failure could be followed by overwrite | **FIXED** | `storage_utils._preserve_corrupt_copy` verifies byte count, SHA-256, read-back and unchanged source metadata; `CorruptionWriteError` is fail-closed. Regression: `test_critical_safety.py::TestFailClosedQuarantine`. |
| Sync archive failure was swallowed by some merge paths | **FIXED** | All HTTP merge helpers now raise `SyncMergeError`; `_apply_bundle_result` exposes failure; pull blocks baseline/push; push gate is persisted. Regression: `TestSyncArchiveGate`. |
| Empty restore selection collapsed to “all” | **FIXED** | `_selected([]/()/set())` raises; `None` is the only explicit all value; UI disables empty submission. Regression: `TestRestoreSelectionAndJournal`. |
| Restore rollback depended on in-memory state | **FIXED (automated crash test; real power loss NOT TESTED)** | Version-2 journal records per-file original/staged hashes and rollback paths; `recover_interrupted` verifies live bytes before commit/rollback. Regression: crash-after-first-replacement test. |
| Encrypted restore silently created a plaintext pre-restore ZIP | **FIXED** | Encrypted restore now creates an encrypted pre-restore backup or blocks; UI asks for explicit acknowledgement. Regression: `test_encrypted_restore_uses_encrypted_pre_restore_backup`. |
| Version-1 KDF header accepted arbitrary expensive parameters | **FIXED** | Exact `n/r/p` configuration and strict JSON integer/hex checks before scrypt. Regression: `test_hostile_kdf_is_rejected_before_derivation`. |
| Plaintext encrypted-backup temp files could survive a kill | **PARTIAL** | Decryption/encryption temp files now live in a private Mei temp root with restrictive permissions and startup stale cleanup. Secure deletion from SSDs/filesystems is not claimed. Regression: `test_stale_private_temp_is_cleaned_without_touching_unrelated_files`. |
| Scheduled backups are plaintext | **PARTIAL / BLOCKED** | No silent plaintext fallback was added. An OS-protected key envelope/DPAPI design is not implemented in this branch; a policy must require an explicit lower-protection choice. |
| Page-local unavailable-state coverage | **PARTIAL** | Home, Library, Settings and History now have page-local guards; Library/History do not present an empty collection as a healthy empty result. Every legacy service read path and every writer was not converted to a typed read-result contract. |
| Stable publication could upload unsigned manifest | **FIXED** | `build_manifest(require_signature=True)` and `publish()` refuse before upload; generated signatures are verified against the pinned trust store. Stable releases require Authenticode and timestamping. |
| Authenticode workflow contained control characters | **FIXED** | Workflow uses `Join-Path ${env:ProgramFiles(x86)} "Windows Kits\10\bin"` and recursive `signtool.exe` discovery; regression scans for `0x08`. |
| CI PyQt6 failure | **PARTIAL / NOT REPRODUCED** | The base run failed at the offscreen `test_desktop_polish` menu timing assertion. It passes in isolation; the test window was made load-tolerant without changing its assertions. Job logs require repository admin rights (`HTTP 403`). |
| CI PyQt5 job timeout | **BLOCKED** | The reviewed run's PyQt5 job was cancelled after 30 minutes. No log access was available. The support policy was not changed silently. |

## Safety contracts

### Corrupt store writes

`storage_utils` keeps a process-wide write lock and a typed damage state. A
damaged path may only be replaced with an explicit `allow_replace_corrupt=True`
recovery action after preservation; an empty or missing artifact is never
treated as success. The profile process lock remains the cross-process boundary
for normal Mei profile access.

### HTTP sync

`pull()` no longer records `last_pull_at` or permits the following push when a
merge returns `ARCHIVE_FAILED`, `WRITE_FAILED`, or another non-applied result.
`sync_state.json` carries `push_blocked`, its reason and timestamp; `push()`
checks it centrally. A successful pull clears it only after the baseline write
succeeds. The remote snapshot is not re-pushed automatically after a blocked
merge.

### Restore

The journal version is 2. It stores the source backup hash, selected categories,
pre-restore path/protection, and for each target: original existence and hash,
staged hash, rollback relative path, and status. Startup accepts a commit only
when every target is the staged hash and the pre-restore snapshot exists; a
partially applied transaction rolls back from verified rollback copies. Unknown
target bytes are left untouched and become `RECOVERY_REQUIRED`.

### Encryption

Version 1 is AES-256-GCM with scrypt `N=32768, r=8, p=1`, a 16-byte salt, a
12-byte nonce and a 16-byte tag. Header integers must be JSON integers; salt and
nonce must be exact hex lengths; `inner_size` must equal ciphertext length; the
inner ZIP is verified only after GCM authentication. A lost password remains
unrecoverable; there is no recovery key in this branch.

### Release

No fake update key or certificate was added. `update_keys.TRUSTED_UPDATE_KEYS`
remains empty, so the updater still fails closed. Stable publication is blocked
until a genuine key is pinned and a genuine Authenticode certificate is
configured. Pre-release unsigned artifacts are labelled development-only and
cannot be accepted as stable update manifests.

## Verification actually run

- Focused critical/data-integrity/publish tests: **98 passed, 5 subtests**
  before the final page-local and timing edits.
- New critical regression file: **19 passed**.
- Ruff `F401,F811,F841,F821`: clean.
- `py_compile` on every changed Python module: clean.
- Full suite: see the final execution report in the chat; do not treat the base
  branch's historical totals as this branch's totals.

## Remaining limitations

- No real power-loss, disk-full, antivirus-lock, second-device or packaged-build
  test was performed.
- No genuine update signing key, Authenticode certificate or CI job log was
  available.
- Encrypted scheduled-backup key envelopes, recovery keys, encrypted retention,
  and every legacy store's typed read-result conversion remain unimplemented.
- The restore journal's rollback artifacts are removed after a successful commit
  (the journal still records their paths); an independent forensic rollback
  after commit is not retained.
- The page-level guard is not a substitute for a full read-result migration of
  every service used by every page.
