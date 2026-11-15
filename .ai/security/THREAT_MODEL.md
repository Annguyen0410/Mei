# Threat model

## Assets

1. Saved passwords and vault master password.
2. API keys, sync token, Android bridge token, proxy password (`secrets.dat`).
3. Browsing history, downloads, notes/tasks and AI conversations.
4. Profile isolation: one profile's data must not appear in another, and private sessions
   must leave no persistent trace.
5. Integrity of the binary and updates (signed releases, pinned keys).
6. User trust in privacy claims (cookies, referrer, IP, adblock).

## Adversaries

| Adversary | Capability |
|---|---|
| Hostile website | Arbitrary JS/HTML, redirects, malformed URLs, downloads, permission prompts |
| Malicious filter list / subscription | Large or crafted text, redirects, attempt to exfiltrate |
| Malicious extension payload | Crafted JSON/zip with oversized or deceptive tab data |
| Network attacker | DNS rebinding, TLS interception, redirect manipulation |
| Local attacker (same machine, other user) | Reads profile files, copies them to another machine |
| Accidental self-harm | User pastes malformed data; app overwrites a vault on a typo |

Out of scope: a compromised OS/kernel, a malicious Qt/Chromium build, physical access to
an unlocked session, and anonymity against a global network observer.

## Threat → control map

| Threat | Control | Where |
|---|---|---|
| DNS rebinding to localhost/private IP | Resolve once, reject any non-public answer, pin the socket to that IP | `services/safe_http.py` |
| Redirect to a private host or HTTPS→HTTP downgrade | Re-validate each hop; refuse downgrade | `safe_http.redirect_target` |
| Proxy silently bypassed | Refuse to fetch when a proxy is configured unless caller chose direct | `safe_http.fetch` |
| Origin confusion (`evil-example.com` vs `example.com`) | Parsed origin equality, exact host/subdomain checks | `safe_http`, `password_manager`, `engine_identity` |
| Private session persisted | OTR profile policy + explicit private flags on writers | `tab_manager`, `browser_page`, `window_tools` |
| Malicious filter list exhausts memory / traverses paths | Size/line/rule caps, hash cache names, atomic write, last-known-good | `browser/adblock.py` |
| Zip bomb / deceptive extension payload | Member size cap, in-memory read, schema validation, no extraction | `services/extension_bridge.py` |
| Credentials in logs/reports | Redaction registry, diagnostics excludes secrets | `core/log.py`, `core/secret_store.py`, `services/diagnostics.py` |
| Vault wiped by wrong master password | `locked` status refuses writes; legacy migration is additive | `services/password_manager.py` |
| Update tampering | Signature against pinned keys | `services/update_signature.py`, `update_keys.py` |
| Local file exfiltration via `file://` | Trusted-folder policy + explicit prompt | `browser/local_content_policy.py` |
| Fingerprinting | Low-entropy Client Hints stripped outside sign-in origins; no JS spoofing | `browser/adblock.py`, `engine_identity.py` |

## Entry points (attack surface)

- **URL bar / omnibar** → navigation, search, local-file detection.
- **Every page request** → interceptor.
- **Permission prompts** → `BrowserPage._on_permission_requested`.
- **Download requests** → profile signal → `handle_download_request`.
- **Extension import** → file/zip/encoded query.
- **Android bridge HTTP server** → loopback endpoints with token.
- **Clipboard / drag-drop** → URL and file drops.
- **Profile files on disk** → parsed on startup and by backup/restore.
- **AI provider responses** → treated as untrusted text, rendered not executed.
- **Update metadata** → parsed, signature-checked.

## Accepted risks / limitations (documented, not hidden)

1. **Proxy covers page traffic only after restart.** Chromium reads `--proxy-server` at
   startup; the VPN hub says so. The leak test compares the browser's visible IP with the
   direct path — it does not test DNS resolution or WebRTC candidates (F-18).
2. **App-level `safe_http` features do not use the proxy**; they refuse rather than bypass.
3. **Userscripts/extensions run in the page's main world** (F-24). There is no isolated
   world; do not hand them secrets.
4. **Python/Qt cannot guarantee memory zeroization.** The vault limits exposure (Fernet
   objects, no logging, no clipboard auto-copy) but does not claim secure erasure.
5. **Qt patch stream** is pinned to a floor (currently 146 for Qt 6.11.0) and gated in CI;
   the bundled Chromium is whatever Qt ships.
6. **Non-Windows secret storage is owner-only files**, stated in the UI/status.
