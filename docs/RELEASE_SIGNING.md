# Release signing runbook

Mei's updater verifies an Ed25519 signature on `update.json` and fails closed:
`litebrowser/core/update_keys.py` ships `TRUSTED_UPDATE_KEYS = {}`, so until a
real public key is pinned, **no stable update can be published or accepted**.
That is intentional (see `docs/audit/MEI_CRITICAL_REMEDIATION_2026-11.md`), and
`tests/test_update_signature.py` asserts the trust store stays empty in git.

This page is the operational step that unblocks it. Nothing here creates a
"fake" key: the private half never enters the repository.

## 1. Generate the key pair (once, offline)

```bash
python tools/generate_update_key.py --key-id mei-release-2026 --out ~/mei-update-key.txt
```

* Writes the private half to `--out` with mode 0600.
* Refuses to write inside the repository, refuses to overwrite an existing file,
  refuses to reuse a key id that is already pinned, and refuses a path whose
  shell variable was not expanded (a PowerShell `$env:` pasted into `cmd.exe`).
* Prints the `TRUSTED_UPDATE_KEYS` block only. The private half is **never
  printed**: a key in terminal scrollback, a screenshot or a pasted log is a
  leaked key. Read it from the file when you set the CI secret.

> If a private key is ever printed or pasted anywhere, treat it as compromised:
> delete the file, generate a new key with a **new key id**, and pin that one.
> Do not "reuse but be careful" — the whole point of the pin is that only one
> key can sign an update.

## 2. Pin the public half

Add `--pin` to the command in step 1 and the tool writes both constants for you,
keeping any id that was already pinned (that is the rotation order). Without
`--pin`, edit `litebrowser/core/update_keys.py`:

```python
TRUSTED_UPDATE_KEYS = {
    "mei-release-2026": "<base64 raw ed25519 public key>",
}
CURRENT_UPDATE_KEY_ID = "mei-release-2026"
```

Then run the suite. `tests/test_update_signature.py::test_no_private_key_is_committed`
expects an empty trust store, so pinning is a deliberate two-step change:

1. add the public key and bump `CURRENT_UPDATE_KEY_ID`,
2. update that test to assert the *pinned* key id is present and no private key
   material is (base64 must decode to 32 bytes, never 64).

Do not weaken `verify_manifest` to make an unpinned build pass.

## 3. Store the private half

| Where | What |
| --- | --- |
| GitHub → Settings → Secrets → Actions | `MEI_UPDATE_SIGNING_KEY` = base64 raw 32-byte seed |
| Maintainer password manager | the same value, plus the key id |
| Everywhere else | nothing |

Delete `~/mei-update-key.txt` after both copies exist.

## 4. Authenticode

The updater checks the manifest signature; Windows checks the binary. Both are
required for a stable release. `release.yml` reads:

* `MEI_SIGNING_PFX_BASE64`
* `MEI_SIGNING_PFX_PASSWORD`
* `MEI_TIMESTAMP_URL`

Without them the workflow records `UNSIGNED` in the job summary and the artifact
must be labelled development-only. Signing checksum-only builds and calling them
stable is what this gate exists to prevent.

## 5. Rotation

1. Generate a new key with a new id (`mei-release-2027`).
2. Add it to `TRUSTED_UPDATE_KEYS` **without** removing the old key.
3. Ship one release signed by the old key that carries both pins.
4. Switch the publisher to the new key.
5. Remove the old pin only after every supported version can verify the new one.

A compromised key goes in `REVOKED_UPDATE_KEY_IDS` first — that refuses it even
while it is still pinned.

## 6. Verification before publishing

```bash
python -m pytest tests/test_update_signature.py tests/test_update_identity.py tests/test_release_hardening.py -q
python tools/check_engine_security.py
```

Then publish, and confirm the client side actually accepts the manifest on a
machine that holds the previous version — a signature nobody verified
end-to-end is a claim, not a check.
