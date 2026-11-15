# Security boundaries

## Trust table

| Component / input | Trust | Rule |
|---|---|---|
| Page JavaScript, page HTML, page titles | **Untrusted** | Never `eval`; never interpolate into `runJavaScript` without `json.dumps`; AI treats page text as data |
| Extension payloads (`extension_imports.json`, zip) | **Untrusted** | Schema-validated, size-bounded, no path extraction |
| Android bridge requests | **Semi-trusted** | Loopback only + bearer token from `secret_store` |
| `file://` documents | **Untrusted** | Only trusted folders load (`local_content_policy`) |
| Profile JSON files | **Untrusted on read** | Bounded reads, malformed rows skipped, never crash the app |
| Update artifacts | **Untrusted** | Signature checked against pinned keys (`update_keys`, `update_signature`) |
| `safe_http` responses | **Untrusted** | Byte/time caps, redirect revalidation, no proxy bypass |
| App code, `core/` | Trusted | Holds the privilege; must validate everything above |

## Origin boundary

Origin identity is computed from parsed URLs, never string prefixes:

- `services/safe_http.normalize_http_url` — scheme allowlist, IDNA host, default-port
  removal, credentials rejected, control characters rejected, IPv4/IPv6 handling.
- `services/page_monitor.normalize_url` — same shape plus local-host refusal.
- `services/password_manager._normalize_origin` — exact `scheme://host[:port]` matching;
  host-only legacy entries are interpreted as HTTPS, never released on a downgrade.
- `browser/engine_identity.is_sign_in_host` — exact host or subdomain of an exact host.

A suffix/substring comparison over raw URL text is a defect. `tests/test_safe_http.py`
and `tests/test_password_manager.py` hold the adversarial cases.

## Profile boundary

- A profile directory is the isolation unit for cookies, cache, localStorage, IndexedDB,
  service workers, permissions, history, downloads and the vault.
- Each window creates `MeiProfile-<slot>` with its own persistent storage and cache paths.
- **Off-the-record profiles** (`TabManager._build_browser`) force
  `NoPersistentCookies` + `MemoryHttpCache`, skip the password-capture script, refuse to
  persist permission decisions, are never hibernated, and are excluded from session,
  tab-set and AI context payloads.
- Anything that writes to `base_dir` on behalf of a page must know whether the page's
  profile is off-the-record. Downloads now do (`_record_download(private=...)`).

## Private browsing: what it does and does not promise

Promised and enforced: no persistent cookies/cache for the private profile, no saved
permissions, no session/tab-set entries, no AI page context, no download record.

Not promised: anonymity from the network, protection from extension-level activity,
or resistance to OS-level tracing (files still land on disk when the user saves them).
The Privacy dialog and User Guide must not claim more than this.

## File-system boundary

- Downloads: user-chosen path, engine writes, app records metadata only.
- Backups/restores: explicit allowlist (`core/storage_catalog.py`); `secrets.dat`,
  credentials, logs, caches and profile-internal temp files are excluded.
- Filter cache: sanitized label + URL hash (`_cache_filename`) and atomic replace.
- Extension zip import: reads members in memory, refuses members over 32 MB; no
  extraction, so archive paths cannot traverse.
- Local documents: `LocalContentCanAccessRemoteUrls` on, `LocalContentCanAccessFileUrls`
  **off**; arbitrary `file://` navigation is blocked with an explicit user prompt.

## Network boundary

| Path | Control |
|---|---|
| Page traffic | Chromium through the configured proxy flag; interceptor applies blocklist/HTTPS-only |
| App `safe_http` fetches | Public IP pinning, TLS verification with SNI, redirects revalidated, proxy refused unless explicit |
| Android bridge | Loopback bind, token auth, no remote addresses |
| AI providers | Opt-in; loopback for local models; no page/private context by default |
| Update check | Product-tagged channel, signature verification before install |
| WebRTC/DNS | **No leak test**; only the VPN hub compares visible IP vs direct IP |

## Extension boundary

- Extensions are not a full WebExtension runtime: the shipped `Extensions/` folder and
  the import bridge move window/tab metadata, not code.
- Userscripts and profile scripts are injected into the **main world** of the page
  (`browser/browser_page.py`, `window.py` password capture). They therefore run with page
  privileges and must never receive secrets. This is a known, open design risk
  (F-24 in `../security/SECURITY_FINDINGS.md`), not an isolated-world implementation.

## Authentication / secrets boundary

- `secret_store`: DPAPI (current user) on Windows; 0600 JSON elsewhere with an explicit
  "not encrypted at rest" warning; no silent plaintext migration path.
- Password vault: PBKDF2-SHA256 (390,000 iterations, 16-byte salt) + Fernet; a vault that
  cannot be decrypted is **locked**, never overwritten.
- Secrets never enter logs, diagnostics, backups, sync bundles, AI prompts or history.
