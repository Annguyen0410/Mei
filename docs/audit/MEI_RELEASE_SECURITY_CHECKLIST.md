# Mei — Release Security Checklist

Every release must pass this list. A box is checked only with evidence attached
to the release notes; "it usually works" is not evidence. Current status is the
state of branch `new-main` after the P0 batch, not a promise about future builds.

## 1. Engine

- [x] One production engine: PyQt6 6.11.0 / QtWebEngine 6.11.0, pinned.
- [x] `requirements.txt` and `pyproject.toml` agree; no default PyQt5 install.
- [x] Release workflow installs PyQt6 only (`--exclude-module PyQt5`).
- [x] No silent PyQt5 fallback in documentation.
- [x] Chromium major is readable at runtime (`qWebEngineChromiumVersion`).
- [ ] Chromium **security patch** verified against the upstream release notes
      for the shipping build. (Version string exists; patch-level audit not done.)
- [x] UA names Mei and the real Chromium major; no `Google Chrome` claim.
- [x] Global fingerprint-spoofing script removed; regression test present.
- [x] Compatibility limited to opt-in, sign-in-origin Client Hints.
- [ ] Real-website compatibility matrix executed (Google, Microsoft, ChatGPT,
      GitHub, Notion, WebRTC, WebGL, PDF). **Not run in this environment.**
- [ ] Hibernation behaviour checked on a real desktop with audio/download/forms.
- [x] Hibernation safety policy unit-tested.

## 2. Data

- [x] Atomic JSON writes for profile stores (`storage_utils.write_json`).
- [x] Multi-window writes serialised (`profile_locked`).
- [ ] Per-store schema versions + migration journal. **Missing.**
- [ ] Corrupt-store quarantine/recovery. **Missing** (silent default return).
- [ ] Scheduled, versioned, independent backups. **Missing.**
- [ ] Restore preview / selective restore. **Missing.**
- [ ] Conflict Center with local/remote/both. **Missing.**
- [x] Incognito does not persist permission decisions.
- [x] Incognito tabs are never auto-hibernated into persistent state.
- [ ] Full audit that incognito metadata never enters session/sync. **Partial.**
- [x] Diagnostics exclude note text, history, passwords, vault, secret store.

## 3. Security

- [x] No private signing key, token or certificate in the repository.
- [x] No silent plaintext credential fallback introduced.
- [x] No global TLS/certificate bypass.
- [x] No sandbox disable shipped (`QTWEBENGINE_DISABLE_SANDBOX` must be unset).
- [x] Update manifest signature verification implemented (Ed25519, pinned key,
      revocation, fail closed).
- [x] Tests: unsigned / tampered / wrong key / unknown key / revoked / rotation.
- [ ] **Pinned publisher key provisioned** (`core/update_keys.py` is empty).
      Until then remote updates are refused. Release blocker.
- [x] Package SHA-256 + size + MZ re-verified after download and before swap.
- [x] Local channel distinguished from remote and labelled.
- [ ] Authenticode signing executed and verified. **No certificate configured;**
      workflow step exists and records `UNSIGNED`.
- [x] Unknown web permissions denied by default.
- [x] Page Monitor SSRF fix: resolve once, validate every answer, connect to
      the validated IP, re-validate each redirect (`services/safe_http.py`).
- [x] Adblock subscription fetch: HTTPS-only, pinned IP, size/line/rule caps,
      atomic cache, last-known-good preservation, path-safe cache names.
- [ ] Proxy-mediated fetch path agreed and documented. Currently unsupported by
      design; fetches fail rather than bypass destination validation.
- [ ] Dependency vulnerability scan attached to the release.
- [ ] No-hardcoded-secret scan attached to the release.

## 4. Reliability

- [ ] Full test suite green on a clean machine with declared dependencies.
      (`segno` missing from the system Python is an environment fault; the
      project venv run is the authoritative one — record its result.)
- [ ] Source startup on a real desktop.
- [ ] Packaged `.exe` startup (release workflow smoke test only).
- [ ] Renderer crash recovery exercised (single retry, then "[Crashed]").
- [ ] Session restore exercised with 5/10/20/40 tabs.
- [ ] Disk-full behaviour exercised.
- [ ] Interrupted update recovery exercised on a real frozen build.
- [ ] Interrupted sync recovery exercised.
- [ ] No known critical data-loss bug. (Hibernation policy fixed; migration
      partiality remains a known gap.)

## 5. Performance

- [ ] Baseline recorded on the release machine (CPU/RAM/GPU/OS in the notes).
- [ ] Memory benchmark for 5/10/20/30/40/50 tabs.
- [ ] CPU idle/peak benchmark.
- [ ] Tab wake latency measured.
- [ ] Session restore measured.
- [ ] Large-profile (10k history/bookmarks) measured.
- [ ] Long-duration 8/24/48/72 h result, or a documented blocker.

## 6. Release artefact

- [ ] Version matches in `core/product.py`, `pyproject.toml`,
      `docs/CHANGELOG.md`, `installer.iss` (enforced by
      `tests/test_version_consistency.py`).
- [ ] `update.json` generated with `sha256`, `size`, `key_id`, `signature`.
- [ ] Signature verified by the app before publishing.
- [ ] EXE hash and size recorded in the job summary.
- [ ] `web_support` companion archive present and verified (`hub/index.html`).
- [ ] No source maps, secrets or private files in uploaded assets.
- [ ] Release notes state engine version, known limitations, and whether the
      build is signed.

## 7. Data integrity and recovery

- [ ] Backups are created only with a verified manifest/checksums; incomplete
      archives are not listed as successful.
- [ ] `secrets.dat`, `proxy_config.json` and `BrowserData` are absent from a
      produced backup.
- [ ] Restore preview, pre-restore backup and rollback were exercised on a
      synthetic profile.
- [ ] A corrupt versioned store raises `StoreReadError`; a legacy store's bytes
      are preserved and overwrite-blocked.
- [ ] Migration journal shows `COMMITTED` or an explicit `RECOVERY_REQUIRED`;
      no `APPLYING` entry survives a normal launch.
- [ ] Unfinished restore states are reviewed, never replayed automatically.
- [ ] Retention kept the newest verified backup in the test profile.
- [ ] Conflict archive deduplicated a repeated sync and history recorded the
      resolution.
- [ ] Real disk-full, power-loss and GUI interaction tests are explicitly
      marked NOT TESTED if not performed.

## 8. Sign-off

Release is **blocked** while any of these is true:

1. `core/update_keys.py` has no pinned key.
2. Page Monitor SSRF path is open.
3. The full suite is not green in the declared environment.
4. The packaged build is unsigned and the notes do not say so.
5. Performance/long-duration gates are claimed without recorded measurements.

Signed-off-by: ____________________  Date: __________
Build SHA: ____________________  Engine: Chromium __________
## 8. Batch 4 data-safety closure checks

- [ ] A malformed store produces a visible Storage Health warning and a
      preserved `.corrupt-*.bak`; a direct write is refused.
- [ ] The banner names the store and opens Data Management; healthy profiles hide
      it.
- [ ] Migration coverage reports 3/25 journaled and 22 legacy; no store is
      described as migration-managed without a journal.
- [ ] A scheduled backup runs while the shell is open, does not run twice, and
      does not advance the last success on failure.
- [ ] A restore/migration `RECOVERY_REQUIRED` state blocks scheduling.
- [ ] A backup contains `Recovery/conflicts.json`; restoring it merges and does
      not activate a version; a repeated restore is unchanged.
- [ ] Record restore requires confirmation and creates a full pre-restore
      backup; an existing record is not overwritten by `as_new`.
- [ ] HTTP sync archives both versions before applying a winner.
- [ ] Page Monitor refuses an app/environment proxy unless explicit direct mode
      is selected; diagnostics contain no credentials.
- [ ] Encrypted backup is absent/blocked, not represented as implemented.
- [ ] Real GUI, disk-full, power-loss, live two-device sync and packaged build
      were either performed or marked NOT TESTED.

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
