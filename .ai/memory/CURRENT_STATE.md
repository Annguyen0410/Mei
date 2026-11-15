# Current state

As of 2026-11-14, working tree `main` at `a74ec98` plus the overhaul changes listed in
`CHANGELOG.md`. Nothing has been committed or pushed.

## Environment (verified)

| Item | Value |
|---|---|
| OS | Windows (win32), bash shell |
| Python | 3.11.9 |
| App engine | PyQt6 6.11.0 / Qt 6.11.0 / Chromium 140.0.7339.225 |
| Legacy engine | PyQt5 5.15.11 / Qt 5.15.2 — installed locally, **not shipped, not tested** (CI job removed) |
| Qt security stream | 146 (floor 146 — `tools/check_engine_security.py` passes) |
| cryptography | 50.0.2 (floor raised to 48.0.1) |
| Test tooling | pytest, hypothesis (property test added) |
| Disk | C: 30 GB free, D: 566 GB free |

## Test status

- Baseline before changes: **3356 passed, 56 skipped, 0 failed** (147 s).
- Targeted suites after changes: hardening/adblock/downloads/password/safety all green.
- Full-suite result after changes: see `../MEI_ENGINEERING_OVERHAUL_REPORT.md` §H.
- Known skipped tests are platform/engine dependent, unchanged by this work.

## What changed (code)

0. Page-context credential capture removed; save-on-login suspended (ADR-0006).
1. Private-tab downloads no longer persist (download list + activity history).
2. Cookie policy applied to every profile, including private ones.
3. Client Hints restricted to the exact sign-in origins.
4. Challenge whitelist narrowed off whole registrable domains.
5. EasyList `@@` exception rules implemented (blocked minus allowed).
6. Download records carry MIME, sizes, start/finish timestamps.
7. Download hibernation-pause counter decrements exactly once.
8. Dead "strict Referer" control removed; engine already enforces the behaviour.
9. `cryptography` floor raised to 48.0.1; CI installs `hypothesis`.
10. Test-order dependency fixed in `test_adblock_subscriptions.py`.

## Client bridges (reviewed 2026-11-14)

- Android bridge: strong input/network-scope validation; plaintext HTTP, single
  unrevocable bearer token, no replay protection (F-35, open, documented).
- Extension: local-only token, MV3 CSP, no ambient content scripts; broad host permissions
  (F-36) and no total-uncompressed ZIP cap (F-37) remain.

## What did not change

Engine pin, Qt façade, storage formats, backup allowlist, password vault format (v2), proxy
startup flags, AI behaviour, autofill. No data migration was required: every new JSON field is
additive and read with `.get`.
