# Release signing runbook

Mei's updater verifies an Ed25519 signature on `update.json` and fails closed:
a manifest that no pinned key signed is refused rather than trusted. The tree
currently pins one publisher key, in `litebrowser/core/update_keys.py`:

```python
TRUSTED_UPDATE_KEYS = {"mei-release-2026b": "<base64 raw Ed25519 public key>"}
CURRENT_UPDATE_KEY_ID = "mei-release-2026b"
```

An empty map remains a valid state for a fork — it means no remote update can be
accepted — but it is no longer this repository's state, and a build that cannot
verify its own releases cannot update at all. `tests/test_update_signature.py`
does **not** require the map to be empty: it requires every pinned value to be a
raw 32-byte **public** key (64 bytes would mean a private seed was committed) and
`CURRENT_UPDATE_KEY_ID` to name one of them. Nothing here creates a "fake" key:
the private half never enters the repository.

## 1. Generate a key pair (once per key id, offline)

```bash
python tools/generate_update_key.py --key-id mei-release-2027 --out ~/mei-update-key.txt
```

* Writes the private half to `--out` with mode 0600.
* Refuses to write inside the repository, refuses to overwrite an existing file,
  refuses to reuse a key id that is already pinned, and refuses a path whose
  shell variable was not expanded (a PowerShell `$env:` pasted into `cmd.exe`).
* Prints the `TRUSTED_UPDATE_KEYS` block only. The private half is **never
  printed**: a key in terminal scrollback, a screenshot or a pasted log is a
  leaked key. Read it from the file when you set the CI secret.
* `--from-private <file>` recovers the public half from an existing seed, for
  when the pair exists but the pin was never written.

> If a private key is ever printed or pasted anywhere, treat it as compromised:
> delete the file, generate a new key with a **new key id**, and pin that one.
> Do not "reuse but be careful" — the whole point of the pin is that only one
> key can sign an update.

## 2. Pin the public half

Add `--pin` to the command in step 1 and the tool writes both constants for you,
keeping any id that was already pinned (that is the rotation order). Without
`--pin`, edit `litebrowser/core/update_keys.py` by hand:

```python
TRUSTED_UPDATE_KEYS = {
    "mei-release-2026b": "<already pinned>",
    "mei-release-2027": "<base64 raw ed25519 public key>",
}
CURRENT_UPDATE_KEY_ID = "mei-release-2027"
```

Then run `python -m pytest tests/test_update_signature.py -q`. Do not weaken
`verify_manifest` to make an unpinned build pass.

## 3. Store the private half

| Where | What |
| --- | --- |
| GitHub → Settings → Secrets → Actions | `MEI_UPDATE_SIGNING_KEY` = base64 raw 32-byte seed |
| GitHub → Settings → Secrets → Actions | `MEI_UPDATE_KEY_ID` = the key id that seed belongs to |
| Maintainer password manager | the same values |
| Everywhere else | nothing |

Delete `~/mei-update-key.txt` after both copies exist. The publish step reads
`MEI_UPDATE_KEY_ID` + `MEI_UPDATE_SIGNING_KEY` together and refuses a
half-configured pair, so a missing secret is a failed release, not an unsigned
one. These values cannot be verified from the public repository — check them in
the Actions settings page, not by reading the workflow.

## 4. Authenticode

The updater checks the manifest signature; Windows checks the binary. Both are
required for a stable release.

Since the 2026 CA/B Forum baseline requirements a code-signing private key must
live in FIPS hardware and certificates last ~459 days, so CAs no longer issue
exportable `.pfx` files. The old `MEI_SIGNING_PFX_BASE64` /
`MEI_SIGNING_PFX_PASSWORD` / `MEI_TIMESTAMP_URL` secrets are gone and must not be
reintroduced. `release.yml` signs through a cloud HSM instead, configured with:

| Kind | Name |
| --- | --- |
| variable | `MEI_SIGNING_PROVIDER` = `azure-trusted-signing` |
| secret | `AZURE_TENANT_ID` |
| secret | `AZURE_CLIENT_ID` |
| secret | `AZURE_CLIENT_SECRET` |
| variable | `MEI_TS_ENDPOINT` |
| variable | `MEI_TS_ACCOUNT` |
| variable | `MEI_TS_PROFILE` |

With no provider configured the step records `unsigned build` in the job summary
and the stable-release gate refuses to publish. A pre-release may be unsigned so
the pipeline can be exercised without a certificate; an ordinary release may
not. `azure/trusted-signing-action` is pinned by commit SHA, not by a moving
major tag, because it holds the signing credentials.

## 5. Stable and pre-release

`releases/latest/download/update.json` is the channel every installed copy
polls, and GitHub's `latest` skips pre-releases. Therefore:

* an Alpha/Beta tag (`v1.0.1.0-alpha.2`) **must** be published with
  `--prerelease`; `publish_release.py` refuses a suffixed tag without it, and
  `release.yml` adds the flag automatically when the tag contains `-`;
* a release that already exists is re-`PATCH`ed with the same `prerelease` value,
  so a re-run cannot quietly promote an Alpha to stable;
* the tag's version must equal `litebrowser/core/product.py`'s `APP_VERSION`,
  and the manifest records the plain four-part version — never the suffix;
* one version per release: rebuild and republish rather than attaching a second
  `web_support` ZIP under a different version number.

## 6. Rotation

1. Generate a new key with a new id (`mei-release-2027`).
2. Add it to `TRUSTED_UPDATE_KEYS` **without** removing the old key.
3. Ship one release signed by the old key that carries both pins.
4. Switch `MEI_UPDATE_KEY_ID` to the new key and publish.
5. Remove the old pin only after every supported version can verify the new one.

A compromised key goes in `REVOKED_UPDATE_KEY_IDS` first — that refuses it even
while it is still pinned, which is why rotation publishes a new id rather than
reusing one.

## 7. Verification before publishing

```bash
python -m pytest tests/test_update_signature.py tests/test_update_identity.py tests/test_release_hardening.py -q
python tools/check_engine_security.py
```

`release.yml` runs both itself: the engine-security gate sits before the build,
because a release tag can point at a commit whose green CI ran on a different
engine. Then publish, and confirm the client side actually accepts the manifest
on a machine that holds the previous version — a signature nobody verified
end-to-end is a claim, not a check.
