# ADR-0006 — Suspend credential capture until an isolated bridge exists

- Status: Accepted (2026-11-14)
- Findings: F-24 (main-world scripts), F-34 (plaintext credentials in page storage)

## Context

Save-password worked like this:

1. A `DocumentCreation` script was injected into the page's **MainWorld** for every
   non-private profile when the password manager was enabled.
2. On `submit` (and Enter in a password field) it read the login form and wrote
   `{user, pass}` as **plaintext** into `sessionStorage` under `__mei_pending_creds`.
3. On the next `loadFinished`, the app ran a read script in the same world, took the
   value, removed the key, and offered to save it in the vault.

Step 2 is a credential exposure, not just a main-world hygiene issue. `sessionStorage`
belongs to the origin's document, so **any script on the page** — an ad, an analytics
bundle, a supply-chain compromise — can call
`sessionStorage.getItem('__mei_pending_creds')` in the same tick and exfiltrate the
password before the app reads it. The value also survives same-origin navigations.

Qt WebEngine has no browser-internal password manager (Chromium's is not exposed), and
there is no page→native channel that both survives navigation and is hidden from the
page. `runJavaScript` callbacks are pull-based and asynchronous, isolated-world globals
die with the document, and QWebChannel lives in the main world where the page can hook
its transport.

## Options considered

1. **Keep the script, move it to `ApplicationWorld`.** Rejected as a fix: an isolated
   world still shares web storage with the page, so plaintext in `sessionStorage`
   remains readable. It would look safer without being safer.
2. **Encrypt the stored value with a native key.** Rejected for now: the read side needs
   `crypto.subtle.decrypt`, which is async, and `runJavaScript` returns the synchronous
   value only. Without a native callback channel this cannot complete.
3. **Console-message or custom-scheme channel.** Rejected as unverifiable in this
   environment and too invasive to ship without GUI testing.
4. **Suspend automatic capture; keep autofill and manual vault entries.**

## Decision

Option 4. The capture script, its read script and the save-password bar are removed.
Autofill, the encrypted vault, master-password flow and manual add/edit still work. The
Privacy dialog says that saving is done in the Vault until the bridge ships.

## Requirements for the bridge that re-enables this

- Capture runs in an isolated world (`ApplicationWorld`), never in `MainWorld`.
- The page must never be able to read, forge or replay a captured credential.
- Native transfer uses a minimal protocol with a per-document nonce, origin validation,
  frame validation (`top` frame only), size limits and strict input validation.
- Nothing is written to page storage, logs, diagnostics, activity history or any file
  outside the encrypted vault.
- The native side must treat every captured value as untrusted input, re-check that the
  page origin at save time matches the origin at capture time, and never auto-submit.
- Account for page manipulation: fake forms, hidden fields, DOM rewrites before submit,
  and pages that listen for `submit` to harvest values. Capture is advisory; the user
  confirms every save.
- Failure mode is "no prompt", never "crash" or "silent save".

## Consequences

- No automatic save-on-login until the bridge lands; users add logins in the Vault.
- The most dangerous credential path in the browser is gone.
- No storage migration: the keys were transient.
- Re-enabling requires a new ADR superseding this one and an end-to-end test with a
  loopback login page that proves page scripts cannot observe the credential.

## Verification

`tests/test_hardening_2026.py::TestPasswordCaptureRemoved` pins the removal and asserts
autofill keeps credentials out of page scope.
