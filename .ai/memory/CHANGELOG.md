# Knowledge-base and code changelog

## 2026-11-14 — engineering overhaul (uncommitted)

### Security / privacy

- **Private downloads no longer persist.** `handle_download_request` takes a per-profile
  `private` flag; `_record_download` skips the download list and activity history for OTR
  profiles; `_finalize_download(persisted=False)` still releases the hibernation pause.
  (`window_tools.py`, `window.py`, `tab_manager.py`)
- **Cookie policy applies to every profile**, including incognito and profiles created
  after startup. (`window.py`, `tab_manager.py`)
- **Client Hints are sign-in-only.** Removed the registrable-domain allowlist; the check is
  now `engine_identity.is_sign_in_host`. (`adblock.py`)
- **Challenge whitelist narrowed**: `challenges.cloudflare.com`,
  `client-api.arkoselabs.com`, explicit hCaptcha asset hosts. (`adblock.py`)
- **Dead "strict Referer" control removed** and replaced with a factual statement; the
  stored preference is still read for backward compatibility. (`profiles_privacy.py`,
  `prefs.py`, `adblock.py`)
- **Dependency floor raised** to `cryptography>=48.0.1` (pip-audit advisories);
  requirements, pyproject and CI updated.
- **EasyList `@@` exceptions implemented**: `load_filter_file` returns blocked+allowed;
  exceptions win over built-in and subscription rules. (`adblock.py`)

### Reliability

- **Download records now carry MIME, declared/received bytes and start/finish timestamps**;
  terminal time is stamped once; unknown/negative counters clamp to 0.
  (`download_mgr.py`, `window_tools.py`)
- **Download hibernation counter decrements exactly once**, in a `finally`, so a persistence
  error cannot leave hibernation disabled. (`window_tools.py`, `window.py`)
- **Order-dependent test fixed**: `test_adblock_subscriptions.py` imports
  `unittest.mock` explicitly.

### Testing

- New suite `tests/test_hardening_2026.py` (27 tests incl. a Hypothesis property test).
- CI installs `hypothesis`; dev extra updated.

### Documentation

- `AGENTS.md` and the full `.ai/` knowledge base (architecture, security, testing, memory,
  ADRs) added.
- `MEI_ENGINEERING_OVERHAUL_REPORT.md` records the audit, dispositions and evidence.

### Not changed

Engine pin, storage formats, backups, vault format, proxy startup behaviour, AI pipeline.
No commit, push or release was performed.

## 2026-11-14 — second pass: F-24 and client bridges

### Removed (security)

- **Page-context credential capture removed.** `CAPTURE_INSTALL_SCRIPT`,
  `READ_CAPTURED_SCRIPT`, the profile injection and the save-password bar are gone. The
  script ran in `MainWorld` and wrote plaintext credentials into `sessionStorage`, which
  any page script could read. Autofill, vault encryption, manual entries and the
  master-password flow are unchanged; automatic save-on-login is suspended until an
  isolated-world bridge exists (ADR-0006).

### Reviewed (no code change)

- **Android bridge**: bearer token via DPAPI, constant-time compare, loopback default,
  private/link-local-only in LAN mode, rate limits, body caps, content-type enforcement,
  traversal guards, generic errors, extension-only CORS. Open: plaintext HTTP, no device
  identity/revocation, no replay protection (F-35).
- **Extension import bridge**: MV3 CSP, local-only token storage, no ambient content
  scripts, pairing parser mirrored with the desktop, member size caps. Open: broad host
  permissions (F-36), no total-uncompressed cap in ZIP import (F-37).
- **Remaining MainWorld scripts** (dark mode, highlight, WebGL, userscripts): accepted by
  design; they hold no secrets (F-38).

### Tests

- `TestPasswordCaptureRemoved` (2 tests) pins the removal and autofill scope.

## ADR index

- ADR-0001 — Private downloads inherit the privacy context.
- ADR-0002 — Client Hints restricted to sign-in origins.
- ADR-0003 — Remove the unenforceable strict-referrer control.
- ADR-0004 — EasyList exception rules with allow-over-block precedence.
- ADR-0005 — Cookie policy installed per profile.
- ADR-0006 — Suspend credential capture until an isolated bridge exists.
