# Current state

As of 2026-11-14, branch `security/overhaul-autofill-bridge-hardening` (head `8af5d5b`, base
`main` at `a74ec98`) is **committed and pushed**: `a51ecc8` (hardening), `8af5d5b` (Qt 5.15
job removed). Ahead 2 / behind 0, CI run #115 green. **Not merged** — security sign-off still
pending one stabilization round (autofill GET + gesture, doc sync).

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
- Last full suite in this workspace (before push): **3395 passed, 56 skipped, 0 failed,
  1531 subtests** (189.96 s).
- CI run #115 on `8af5d5b`: **3400 passed, 51 skipped**, 1 DeprecationWarning.
- Targeted suites after the autofill round: password-manager + hardening green (see §H of the
  engineering report).
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

- Android bridge: strong input/network-scope validation; optional replay layer shipped
  (timestamp + nonce, 300 s window, single use, `X-Mei-Replay` response header). Plaintext LAN
  HTTP, one long-lived token, no per-device identity or revocation → **F-35 is accepted
  residual risk**, stated in the docs and the bridge UI. Enforcing the pair (and signing
  requests) waits for the MeiRemote client that sends the headers.
- Extension: local-only token, MV3 CSP, no ambient content scripts; **F-36 fixed**
  (`host_permissions: []`, `activeTab` + `scripting`, optional bridge origin requested only at
  pairing) and **F-37 fixed** (member/total/ratio caps, real decompressed bytes). Not
  runtime-tested in a real Chrome/Opera GX session — code review only.

## Stabilization round (2026-11-14, pending merge)

1. **Autofill GET (F-40)** — fixed: only a POST form on the exact matched origin is filled;
   `formmethod` overrides are refused. A GET submission would have put the password in the
   URL (history, Referer, server log).
2. **Autofill timing (F-40)** — fixed: `on_load_finished` no longer injects the script and no
   longer prompts for the master password. It only arms an offer and shows a toast; the fill
   happens on `Ctrl+Shift+L` (`fill_saved_login`), which re-checks the origin before filling.
3. **Docs** — this file, `../security/SECURITY_FINDINGS.md` and
   `../MEI_ENGINEERING_OVERHAUL_REPORT.md` now describe the pushed state, not the pre-push one.
4. **F-35** — recorded as intentional residual risk (loopback default) instead of "open".
5. Still missing: a pull request, and GUI/pairing smoke testing (no desktop GUI in Freebuff).

## What did not change

Engine pin, Qt façade, storage formats, backup allowlist, password vault format (v2), proxy
startup flags, AI behaviour, vault encryption and manual entries. No data migration was
required: every new JSON field is additive and read with `.get`.

Autofill behaviour *did* change (F-40): it is no longer automatic on page load, it refuses GET
forms, and it is triggered by `Ctrl+Shift+L`. The stored data is untouched.
