# Backup encryption and authenticity

## Status

**IMPLEMENTED, AUTOMATED-TESTED, MANUALLY UNVERIFIED ON A SECOND DEVICE.**

Mei still supports its original unencrypted `.mei-backup.zip` format. An
encrypted backup is a separate `.mei-backup.enc` artifact; it wraps an already
verified profile ZIP. No legacy archive is silently converted, and no plaintext
fallback is published when encryption fails.

The password is never stored in preferences, logs, the profile or the container.
There is intentionally **no recovery key and no password-reset path**. If the
password is lost, the encrypted backup cannot be decrypted.

## Container format

Byte layout:

```text
"MEIENC01" | 4-byte big-endian header length | UTF-8 JSON header
| AES-256-GCM ciphertext | 16-byte GCM tag
```

The header is authenticated as GCM associated data together with the magic and
length prefix. Header fields:

- `kind`: `mei.encrypted_backup`
- `format_version`: `1`
- `cipher`: `AES-256-GCM`
- `kdf`: `scrypt`
- `n`, `r`, `p`: scrypt parameters
- `salt`: 16 random bytes, hex encoded
- `nonce`: 12 random bytes, hex encoded
- `created_at`
- `inner_size`
- `inner_sha256`

Defaults: scrypt `n=32768`, `r=8`, `p=1`, 32-byte derived key. The reader
accepts only bounded, power-of-two `n`, bounded `r`/`p`, exact salt/nonce sizes,
and bounded header/payload sizes. Unsupported versions or algorithms are
refused.

The inner ZIP and its manifest are still verified by `backup_service` after
decryption. A modified ciphertext, modified tag, modified header, wrong password
or truncated file fails before the inner archive is accepted.

## Creation and restore flow

Creation:

1. Build the ordinary verified ZIP in a private temporary directory outside the
   profile.
2. Derive a fresh salt/key/nonce and stream-encrypt the archive.
3. Authenticate a test decryption and verify the inner manifest.
4. Atomically publish only the `.enc` file.
5. Remove the plaintext staging directory in `finally`.

Restore:

1. Read and validate the container header without touching live data.
2. Derive the key and stream-decrypt to a private temporary ZIP.
3. Verify the GCM tag before accepting the plaintext.
4. Verify the inner backup manifest/checksums.
5. Run the normal Restore Center preview, pre-restore backup and staged restore.
6. Delete the temporary plaintext after the operation.

A wrong password cannot modify live data because authentication fails before the
pre-restore or extraction stages.

## Threat model

Protected against:

- theft or copying of a backup file without the password;
- accidental archive modification;
- malicious modification of the header, ciphertext or authentication tag;
- a truncated archive;
- wrong-password attempts;
- traversal/symlink/extra-member attacks through the existing ZIP verifier.

Not protected against:

- malware running as the logged-in user while Mei is unlocked;
- an attacker who can read process memory during decryption;
- a compromised Mei binary;
- an attacker who already knows the password;
- a compromised device that can read the original plaintext profile;
- loss of the password (there is no recovery key);
- rollback to an older but validly authenticated backup, unless the user checks
  its timestamp/manifest.

## Operational limits

- Scheduled backups remain unencrypted because Mei does not persist the
  encryption password. The UI creates encrypted backups explicitly.
- Encrypted backups cannot be verified or decrypted without the password, so
  automatic retention never deletes an unverified encrypted archive.
- The encrypted backup is not a substitute for OS account protection or disk
  encryption.
- Cross-device encrypted restore is covered by service-level tests but was not
  performed with two physical devices in this batch.
- The GUI password prompts and failure dialogs were compiled and unit-wired but
  not exercised under a live display.

## Verification

`tests/test_data_integrity_closure.py` covers:

- round trip and absence of plaintext/password in the container;
- wrong password;
- modified ciphertext/tag;
- truncated and malformed headers;
- no live-store modification on wrong password;
- encrypted restore;
- legacy unencrypted import;
- encrypted listing without password;
- the absence of an automatic encrypted-verification claim.

Final full suite: **1205 passed, 1413 subtests passed in 136.58 s**. The focused
closure set is **75 passed, 88 subtests**.

## Cryptographic review status

The construction uses maintained `cryptography` primitives (AES-GCM and
scrypt), not a custom cipher. Independent cryptographic review and formal test
vectors are still recommended before treating this as a high-assurance archive
format. This implementation has automated tests, not an external audit.

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
