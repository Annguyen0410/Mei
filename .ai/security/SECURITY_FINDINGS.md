# Security findings register

Audit date: 2026-11-14. Baseline: `a74ec98`, suite **3356 passed / 56 skipped**.
Evidence standard: a finding is "confirmed" only with a file+line execution path and either
a reproduction or a regression test. Scanner output alone is not proof.

Severity scale: Critical / High / Medium / Low / Informational.
Status values: Fixed and verified · Partially fixed · Already fixed · Not reproducible ·
False positive · Needs investigation · Open (accepted, documented).

## Summary

| ID | Finding | Sev | Confidence | Status |
|---|---|---|---|---|
| F-20 | Private-tab downloads written to the profile's download list and activity history | High | Confirmed | Fixed and verified |
| F-24 | User scripts / password capture execute in the page's main world (no isolated world) | High | Confirmed | **Open** (design, documented) |
| F-21 | Client Hints exempted whole registrable domains (google.com, microsoft.com, …) | Medium | Confirmed | Fixed and verified |
| F-22 | Third-party cookie policy installed on the main profile only | Medium | Confirmed | Fixed and verified |
| F-26 | EasyList `@@` exception rules silently ignored (over-blocking) | Medium | Confirmed | Fixed (partial: cosmetic/options still unsupported) |
| F-27 | Download pause counter incremented but never decremented | Medium | Confirmed | Fixed and verified |
| F-32 | Broad `except Exception: pass` in UI paths hides real failures | Medium | Confirmed | Open (debt; download path hardened) |
| F-23 | Download record lacked MIME, sizes, timestamps | Low | Confirmed | Fixed and verified |
| F-25 | "Strict Referer" privacy toggle was a no-op | Low | Confirmed | Fixed (control removed) |
| F-28 | Challenge whitelist included all of `cloudflare.com` | Low | Confirmed | Fixed and verified |
| F-29 | Privacy wording promised what the implementation did not do | Low | Confirmed | Fixed (wording + code) |
| F-31 | Favicon cache is unbounded and keyed by full URL | Low | High | Open |
| F-30 | Order-dependent test relied on another test importing `unittest.mock` | Info | Confirmed | Fixed and verified |
| F-33 | `cryptography>=41` allowed vulnerable installs (pip-audit) | Medium | Confirmed | Fixed (floor raised to 48.0.1) |

## Original 19 issues — disposition

| # | Issue | Result |
|---|---|---|
| 01 | Incognito data leakage | **Partially fixed.** OTR storage/cache/permissions/session/AI already correct; downloads were persisted (F-20, fixed). No cache/indexedDB residue found. |
| 02 | Profile context across tabs/split view | **Needs investigation.** `get_profile_for_url` returns the window's single profile by design; incognito is passed explicitly. Tab tear-off/duplication across windows was not exercised at runtime. |
| 03 | Cookie policy vs behaviour | **Fixed** (F-22). Incognito profiles now receive the filter; sign-in exemption is narrow (6 exact hosts). |
| 04 | Extension script isolation | **Confirmed open** (F-24). Scripts run in `MainWorld`; changing this breaks userscripts that need page globals, so it is documented, not silently changed. |
| 05 | Download metadata | **Fixed** (F-23). |
| 06 | Monitoring/history/reading-progress inconsistency | **Not reproduced.** Single `activity_history.json`; no duplicate listener found. Runtime duplication was not exercised. |
| 07 | Favicon caching | **Not reproducible as a security bug**: the app never fetches favicons; the engine supplies `iconChanged`. Cache growth keyed by URL remains open (F-31). |
| 08 | Duplicate history storage | **Not reproducible.** One store, one writer (`history_service`). |
| 09 | Privacy claims vs runtime | **Fixed where false** (F-20, F-25/F-29); remaining claims match the threat model's stated limits. |
| 10 | Strict Referer control | **Fixed** (F-25). Removed the control; engine already enforces strict-origin-when-cross-origin. |
| 11 | Overly broad challenge whitelist | **Fixed** (F-21, F-28). |
| 12 | EasyList compatibility | **Partially fixed** (F-26). `@@` exceptions now work; cosmetic filters, regex, path rules and `$` options remain unsupported by design. |
| 13 | Download counter/lifecycle | **Fixed** (F-27). |
| 14 | SafeHTTP origin validation | **No defect found.** Parsed URL equality, IDNA, ports, credentials, redirect revalidation, pinned IP; no prefix comparison. |
| 15 | Workspace vs profile confusion | **Needs investigation.** Workspaces are string IDs inside one profile; no typed separation. No concrete cross-profile exposure found. |
| 16 | Password manager | **Reviewed, no change.** PBKDF2 390k + Fernet, locked-vault protection, legacy migration. Memory zeroization is not claimed. |
| 17 | Qt/QtWebEngine patch gap | **No defect today.** 6.11.0 / Chromium 140 / security version 146 = floor; CI gate exists. |
| 18 | Proxy/DNS/WebRTC leak test | **Limitation documented.** Leak test compares visible vs direct IP only; no DNS/WebRTC coverage. |
| 19 | Other architecture/lifecycle issues | **Mixed.** Fixed download counter and test isolation; silent exception suppression remains (F-32). |

## Details — fixed findings

### F-20 — Private-tab downloads persisted (High)

- Files: `litebrowser/ui/main_window/window_tools.py`, `window.py`, `browser/tab_manager.py`.
- Root cause: every profile connected `downloadRequested` to the same handler, which always
  called `download_mgr.add_download(self.base_dir, …)`; that function also writes an activity
  event. The OTR flag was never passed.
- Impact: URL + filename of a private download stayed in `downloads.json` and
  `activity_history.json` after the private tab closed.
- Reproduction: open an incognito tab, download a file, close the tab, inspect the profile.
- Fix: the signal is bound with `private=off_the_record`; `_record_download` returns `None`
  for private transfers; `_finalize_download(..., persisted=False)` decrements the pause
  without writing. Private downloads still work.
- Test: `tests/test_hardening_2026.py::TestDownloadLifecycle` (3 tests).

### F-22 — Cookie policy skipped private profiles (Medium)

- Files: `window.py::_apply_cookie_policy`, `tab_manager.py`.
- Root cause: `store = self.profile.cookieStore()` — one profile, at startup only.
- Impact: with "block third-party cookies" on (the default), private tabs and later-created
  profiles still accepted third-party cookies.
- Fix: `_apply_cookie_policy` installs the same filter on the main profile and every
  incognito profile; `TabManager._build_browser` applies it when a new OTR profile exists.
- Test: `TestCookiePolicyScope` (3 tests).

### F-21 — Client Hints exempted whole registrable domains (Medium)

- Files: `browser/adblock.py`.
- Root cause: `_COMPAT_DOMAINS` held `google.com`, `microsoft.com`, `openai.com`, `bing.com`,
  `anthropic.com`, … and `is_compat` skipped hint stripping for any subdomain.
- Impact: the "hide device info" setting leaked arch/bitness/full-version on ordinary pages
  of those domains, contradicting the UI tooltip.
- Fix: `is_compat = engine_identity.is_sign_in_host(host)` (9 exact hosts/subdomains).
- Test: `TestClientHintScope`.

### F-26 — EasyList `@@` exceptions ignored (Medium)

- Files: `browser/adblock.py`.
- Root cause: the parser accepted only `||domain^` / bare domains; `@@` lines failed the
  domain regex and were dropped, so a whitelisted site inside a blocked CDN stayed blocked.
- Fix: `_filter_rule` returns `(kind, domain)`; `load_filter_file` returns
  `(blocked, allowed)`; merged cache keeps exception lines; `_is_blocked_host` lets an
  exception win over built-in and subscription rules.
- Test: `TestExceptionRules` (5 tests).
- Remaining: cosmetic filters, regex, path rules and `$` options are still unsupported and
  documented in `docs/audit/MEI_BROWSER_COMPATIBILITY_MATRIX.md`.

### F-27 — Download pause counter never decremented (Medium)

- Files: `window_tools.py`.
- Root cause: `_active_download_count += 1` on accept; no decrement anywhere; hibernation
  reads `> 0`.
- Impact: after one download, automatic tab hibernation was disabled for the session;
  memory grew with every new tab.
- Fix: decrement exactly once per terminal event in `_finalize_download`'s `finally`,
  keyed by `_finalized_downloads`; counter starts in `__init__`.
- Test: `TestDownloadLifecycle::test_terminal_event_releases_the_hibernation_pause`,
  `…keeps_the_pause`, `…private_terminal_event…`.

### F-23 — Incomplete download metadata (Low)

- Files: `services/download_mgr.py`, `window_tools.py`.
- Fix: records now carry `mime_type`, `total_bytes`, `received_bytes`, `started_at`,
  `finished_at`; terminal status stamps `finished_at` once; negative/unknown counters clamp
  to 0; older records keep working (additive keys).

### F-25 / F-29 — Dead "strict Referer" control (Low)

- Files: `ui/dialogs/profiles_privacy.py`, `core/prefs.py`, `browser/adblock.py`.
- Root cause: `strict_referrer` was stored and copied onto the interceptor but never read by
  any request path. Unchecking it promised the full Referer and changed nothing.
- Fix: control removed and replaced with a factual statement; interceptor no longer carries
  the dead attribute; the pref getter/setter remain so old profiles load.
- Test: `TestStrictReferrer`.

### F-28 — Challenge whitelist too broad (Low)

- Fix: `cloudflare.com` → `challenges.cloudflare.com`; `arkoselabs.com` →
  `client-api.arkoselabs.com`; hCaptcha asset hosts made explicit.
- Test: `TestClientHintScope::test_cloudflare_registrable_domain_is_not_a_challenge_host`.

### F-33 — Vulnerable dependency floor (Medium)

- `pip-audit --local` reported `cryptography 46.0.5` against PYSEC-2026-3552/3553/3554 and
  GHSA-537c-gmf6-5ccf (fixed in 48.0.1+). The declared floor was `>=41`.
- Fix: floor raised to `>=48.0.1` in `pyproject.toml`, `requirements.txt`, CI; local venv
  upgraded to 50.0.2; vault + safety tests pass.
- Remaining audit output is `pip`/`setuptools` in the developer venv (not shipped).

## Open items (not hidden)

- **F-24** main-world script execution — architectural; requires an isolated-world design
  that keeps userscripts working.
- **F-32** silent exception suppression — many UI paths swallow errors; the download path was
  hardened, the rest is debt.
- **F-31** favicon cache growth — no eviction.
- Issues 02, 06, 15 need runtime reproduction with disposable profiles.

---

# Second pass — F-24 and client-bridge review (2026-11-14)

Scope: the JavaScript execution boundary and the two independent trust boundaries that
feed Mei Browser (MeiRemote/Android bridge, Mei extension import bridge).

## Summary

| ID | Finding | Sev | Confidence | Status |
|---|---|---|---|---|
| F-34 | Save-password wrote **plaintext credentials into page-readable `sessionStorage`** from a MainWorld script | Critical | Confirmed | Fixed by removal (feature suspended, ADR-0006) |
| F-24 | Secret-bearing script executed in the page's main world | High | Confirmed | Resolved with F-34 (no secret-bearing script remains) |
| F-35 | Android bridge uses plain HTTP with a long-lived bearer token; no device identity, revocation or replay protection | Medium | Confirmed | Partially fixed — **residual risk accepted** (optional replay layer shipped; TLS/device identity deferred to the client) |
| F-36 | Extension requests `http://*/*` + `https://*/*` host permissions although it only reads the active tab on demand | Low | Confirmed | Fixed (`activeTab`, no standing host access) |
| F-37 | Extension ZIP import bounds each member (32 MB) but not the total uncompressed size | Low | Confirmed | Fixed (members, total, ratio, traversal, real bytes) |
| F-39 | Autofill filled a form without re-checking the document, the frame or the form's target origin | High | Confirmed | Fixed (top-frame + origin + form-action checks, no cleartext HTTP) |
| F-40 | Autofill ran automatically on page load and would fill a **GET** form, putting the password in the URL | High | Confirmed | Fixed (POST only, `formmethod` overrides refused, fill requires `Ctrl+Shift+L`) |
| F-38 | App UI scripts (dark mode, highlight, WebGL off, userscripts) run in MainWorld | Info | Confirmed | Accepted by design (no secrets; DOM mutation is the feature) |

## F-34 — plaintext credentials in page storage (Critical)

- Files: `litebrowser/services/password_manager.py` (`CAPTURE_INSTALL_SCRIPT`,
  `READ_CAPTURED_SCRIPT`), `window.py` (injection), `window_tools.py` (save bar).
- Path: profile `DocumentCreation` script in `MainWorld` → form `submit` listener →
  `sessionStorage.setItem('__mei_pending_creds', JSON.stringify({user, pass}))` → next
  `loadFinished` reads it in the same world.
- Impact: any page script can read the submitted password before the app does and can
  exfiltrate it; the value survives same-origin navigation.
- Fix: the script, read path and save bar were removed. Capture is suspended until an
  isolated-world bridge exists (ADR-0006). Autofill, vault encryption, manual entries
  and the master-password flow are unchanged.
- Test: `TestPasswordCaptureRemoved` (source has no capture script/storage key; autofill
  keeps the secret out of `window` and `sessionStorage`).
- Note: moving the same script to `ApplicationWorld` would **not** have fixed it —
  isolated worlds share web storage with the page.

## F-35 — Android bridge transport and identity (Medium, open)

Verified controls (no defect):

- Bearer token from `secret_store` (DPAPI on Windows), compared with
  `hmac.compare_digest`; 8 failed attempts/minute/IP.
- Scope: loopback by default; LAN mode accepts loopback/private/link-local only.
- Limits: 120 requests/min, 10 MB JSON, 25 MB upload, 16 connection slots, 30 s socket
  timeout, chunked bodies refused, content type enforced.
- Path safety: `safe_child_path`, `..` rejection, Windows-forbidden characters, reserved
  device names, unique-name dedupe.
- Error hygiene: generic `service_failure`, no exception text or local paths returned.
- CORS answered only for extension origins; `OPTIONS` refused for web origins; security
  headers on every response (nosniff, DENY, no-referrer, no-store, CSP).

Gaps (accepted for a loopback-first feature, must be stated):

1. No TLS. In LAN mode the pairing token and payloads cross Wi-Fi in cleartext; anyone
   who captures the token can call the bridge until it is rotated.
2. One long-lived token per profile; no per-device identity, listing or revocation;
   rotation is manual.
3. ~~No request signing/nonce/timestamp~~ — **fixed for clients that send it; residual risk
   for the 1.x client**: a request that carries
   `X-Mei-Timestamp` + `X-Mei-Nonce` is checked (300 s window, single use, bounded cache)
   and answered with `X-Mei-Replay: on`; a stale or replayed pair is refused with 409.
   Clients that send neither are still accepted and answered `X-Mei-Replay: optional`,
   because the 1.x Android app predates the headers. Until that client ships, a captured
   request is still replayable; enforcement (making the pair mandatory) is the next step.
4. LAN mode trusts any device on the same private network to *attempt* authentication.

Recommendation: default stays loopback; require an explicit warning for LAN mode; add
"rotate token / forget device" and HMAC-signed requests (`timestamp + nonce + body hash`)
before advertising LAN use as secure. Do not claim VPN-grade privacy for this bridge.

## F-39 — Autofill as its own credential boundary (High, fixed)

Removing password capture did **not** make autofill safe by itself: filling a form is
handing a vault secret to a document, and every script on that document can read it.

- Files: `litebrowser/services/password_manager.py` (`AUTOFILL_SCRIPT`,
  `build_autofill_script`, `autofill_allowed`, `credentials_for_autofill`),
  `litebrowser/ui/main_window/window.py` (call site).
- Before: the script took the **first** `<form>` on the page, filled any password input
  in it, and never re-checked which document it was running in. `loadFinished` →
  `runJavaScript` is asynchronous, so a navigation that started in between could have
  received the value on a different page.
- After, four checks, all required:
  1. exact-origin match between the stored entry and the page (unchanged, `_origin_match`);
  2. `autofill_allowed`: `https`, or `http` **only** on loopback (a cleartext page or
     cleartext form target is refused regardless of the origin match);
  3. in-script `window.top === window.self` and `location.origin === expected origin`,
     so a subframe or a post-navigation document gets nothing;
  4. a form whose resolved `action` points at another origin is skipped — the filled
     password would otherwise be posted to a third party;
  5. only a form whose resolved `method` is **POST** is filled (F-40). `form.method`
     already resolves to the spec default `get`, so an unlabelled form is refused, and any
     `formmethod` override on a submit control must also be POST.
- The username/password are JSON-escaped into local closure variables; the script keeps
  them out of `window`, `sessionStorage`, `localStorage` and the network (asserted).
- Test: `TestAutofillBoundary` (7 cases) plus the existing capture-removal checks.
- Residual: a same-origin script still reads what was filled — that is inherent to any
  autofill, and is the reason the origin match must be exact. Cross-origin iframe logins
  are **not** filled (they are skipped, not silently attempted).

## F-40 — Autofill timing and GET forms (High, fixed)

Two defects in the same function, both found in review after F-39:

- **Automatic fill.** `on_load_finished` called `build_autofill_script` on every successful
  load and, if the master password was not cached, opened the master-password dialog by
  itself. The user never asked for the secret; the page did. Any navigation that completed
  between `loadFinished` and the JS call made the fill a side effect of visiting a page.
- **GET forms.** `AUTOFILL_SCRIPT` checked the form's `action` origin but not its `method`.
  A `<form method="get">` (or a form with **no** method attribute, which defaults to GET)
  serialises all fields into the query string on submit, so the filled password would be
  written into browser history, the `Referer` of every subresource on the next page, and the
  server's access log — a leak that survives far longer than the session.

Fix, in `password_manager.AUTOFILL_SCRIPT` and `window.py`:

1. The script returns early unless the form's resolved method is `post`, and unless every
   `formmethod` override on a submit control is also `post`.
2. The load path no longer injects anything and no longer prompts. It only records an offer
   (`mei_autofill_url` on the view) and shows a toast: *Saved login available · Ctrl+Shift+L
   to fill*. `_saved_login_offer` performs the boundary checks without decrypting anything.
3. `fill_saved_login` (new `Ctrl+Shift+L`, listed in the hotkeys hub) is the only caller of
   `build_autofill_script`. It re-checks `same_origin(offer, current URL)` before touching the
   vault, so a redirect between load and keypress fills nothing, and it only asks for the
   master password at that moment.

- Test: `TestAutofillRefusesFormsThatLeakTheUrl` (2 cases), `TestAutofillNeedsAUserGesture`
  (2 source-level cases: the load path contains neither `build_autofill_script` nor
  `ask_master_password`, and the shortcut exists), plus the 7 F-39 cases.
- Residual: a same-origin script can still read a filled value, and a POST form on a
  compromised origin can still ship it anywhere the page wants. Autofill is a convenience for
  origins the user chose to save credentials for, not a confidentiality boundary.

## F-36 — Extension capability scope (Low, fixed)

- `manifest.json` requests `tabs`, `storage`, `downloads`, `scripting` and host
  permissions for every http(s) site. The extension only reads the **active tab** when the
  user clicks Send/Selection (`chrome.scripting.executeScript` on `tabId`).
- Good: token lives in `chrome.storage.local` (not `sync`, so it does not travel to other
  profiles), MV3 CSP `script-src 'self'; object-src 'none'`, no auto-injected content
  scripts, pairing parser mirrors the desktop's rules, loopback host default.
- Fixed in v1.3: `host_permissions` is now empty, `activeTab` replaces the standing
  access, and `optional_host_permissions: ["http://*/*"]` is requested for the **bridge
  origin only** on the click that saved the pairing code. `tabs` stays for the popup's
  window enumeration; `scripting` stays for the selection read.
- Not verified here: a real Chrome/Opera GX run. Opening the popup is the user gesture
  that grants `activeTab`, which is the documented behaviour, but this environment has no
  browser automation for extensions — treat as code-reviewed, not runtime-tested.

## F-37 — ZIP import total size (Low, fixed)

- `extension_bridge.import_from_zip` refuses members over 32 MB but read each `.json`
  member whole; an archive with many members just under the cap could allocate far more
  than intended.
- Fixed: `ZIP_MAX_MEMBERS` (256), `ZIP_MAX_MEMBER_BYTES` (32 MB), `ZIP_MAX_TOTAL_BYTES`
  (64 MB) and `ZIP_MAX_RATIO` (200:1) are checked before reading; member names are
  rejected when absolute, drive-qualified or containing `..`; and each member is read
  through `_read_member_limited`, which caps the bytes **actually decompressed** rather
  than trusting the size in the header. `import_from_file` got the same total cap.
- Test: `TestZipImportLimits` (7 cases, including a real compression bomb).

## F-38 — Remaining MainWorld scripts (Info, accepted)

Forced-dark, text-highlight, WebGL-disable and user-authored userscripts run in
`MainWorld`. They manipulate the DOM — that is the feature — and hold no credentials or
native handles. Userscripts are user-supplied code by definition; treat them as trusted
user input and never feed them vault values. This is documented in
`architecture/SECURITY_BOUNDARIES.md`.

## Bridge conclusion

Both bridges were reviewed as independent trust boundaries, not as "does it connect".
The extension side is meaningfully tighter (local token, MV3 CSP, no ambient content
scripts, pure-protocol module with Node tests). The Android side has strong input and
network-scope validation, an optional nonce/timestamp replay layer (enforced when the client
sends it, `X-Mei-Replay: on|optional|rejected`), and a loopback default; what remains is a
plaintext LAN transport and one unrevocable long-lived token. That remainder is **accepted
residual risk, not a passed control**: it is documented here, in the bridge UI and in
`memory/CURRENT_STATE.md`, and it must not be described as "LAN mode is secure". Neither
bridge can reach the encrypted vault or the password manager; the Android bridge writes
notes/tasks/pages/files, and the extension bridge writes tab/workspace metadata.

