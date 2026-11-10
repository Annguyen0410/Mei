# Mei — Browser Compatibility Matrix

Engine of record: **PyQt6 6.11.0 / QtWebEngine 6.11.0 / Qt 6.11.2**, Chromium 140
line. The dev venv also contains PyQt5 5.15.11 (Chromium 87) as a legacy test
leg; it is not a production engine and must not be shipped.

## 1. What Mei used to change, and what it changes now

The former DocumentCreation script ran on every profile, in the main world, in
every subframe. It was removed in this batch. This table records what it did so
the change is auditable.

| API | Native engine value | Old Mei value | Old reason | Risk | Now |
|---|---|---|---|---|---|
| `navigator.webdriver` | `false` (Qt) / `undefined` (Chrome) | forced `undefined` + native-looking getter | pass Gaia check | active deception of automation detection | **native value, untouched** |
| `window.chrome` | partial object | filled `app`, `csi()`, `loadTimes()`, `runtime` enums, `webstore` | appear like desktop Chrome | fabricated API surface | **native value, untouched** |
| `navigator.plugins` | empty | 5 fake PDF plugins | avoid "headless" reads | fabricated fingerprint | **native** |
| `navigator.languages` | engine locale | forced `["en-US","en"]` | avoid empty array | contradicts user locale | **native** |
| `navigator.userAgentData` | Chromium brands | injected `"Google Chrome"` brand + fake `platformVersion`, `bitness`, `uaFullVersion` | pass Client Hints checks | false build/OS claims | **native**; real hints sent as HTTP headers on sign-in hosts only |
| `navigator.permissions.query` | native | notifications result forced to `Notification.permission` | avoid "embedded" read | breaks permission semantics | **native** |
| `navigator.deviceMemory` | present | `8` when missing | avoid bot tell | fabricated hardware | **native** |
| `navigator.hardwareConcurrency` | real cores | `8` when falsy | avoid bot tell | fabricated hardware | **native** |
| `navigator.vendor` | `"Google Inc."` | forced when empty | appear Chrome | claim of vendor | **native** |
| `navigator.maxTouchPoints`, `onLine` | native | `0`, `true` when missing | avoid bot tell | fabricated state | **native** |
| WebGL `UNMASKED_VENDOR_WEBGL` | real GPU string | `"Google Inc."` | hide SwiftShader/Qt | **fabricated GPU identity** | **native** |
| WebGL `UNMASKED_RENDERER_WEBGL` | real GPU string | `"ANGLE (Intel, Intel(R) UHD Graphics …)"` | hide software renderer | fabricated GPU identity | **native** |

The only compatibility mechanism left is `engine_identity.client_hint_headers`:
real `sec-ch-ua*` values derived from the running build, brand list
`Chromium` + `Mei`, sent **only** when all of these hold:

1. the user enabled sign-in compatibility (off by default),
2. the request host is in `SIGN_IN_COMPAT_HOSTS`
   (`accounts.google.com`, `accounts.youtube.com`, `gemini.google.com`,
   `chatgpt.com`, `auth.openai.com`, `claude.ai`, `login.microsoftonline.com`,
   `copilot.microsoft.com`, `perplexity.ai`),
3. the existing host classifier also accepts it.

No subframe injection, no page-script modification, no effect on ordinary
browsing.

## 2. Engine feature support (Qt 6.11 line)

| Capability | Status | Notes |
|---|---|---|
| HTML/CSS/ES2023 | supported | Chromium 140 |
| Service workers | enabled | `ServiceWorkersEnabled` set when available |
| WebGL / WebGL2 | supported unless user disables | GPU identity is real; do not expect spoofed values |
| WebGPU | unknown | not verified in this environment; Qt exposes no stable toggle |
| WebAuthn / passkeys | platform-dependent | no dedicated Mei UI; do not claim support until tested |
| WebRTC | supported | media devices require explicit permission |
| PDF viewing | engine-provided | no custom viewer claimed |
| DRM / Widevine | **not supported** | QtWebEngine build does not ship Widevine; sites must be told, not imitated |
| Media codecs | engine-dependent | H.264 support varies by Qt build |
| File upload/download | supported | download prompt has risky-extension warning |
| Clipboard read/write | page permission | not granted globally |
| Notifications | permission-gated | denied by default until asked |
| Geolocation | permission-gated | denied by default until asked |
| Camera / microphone | permission-gated | denied by default until asked |
| Screen capture | permission-gated | mapped to `desktop_capture` |
| OAuth popups | supported | `createWindow` routes to a new tab |
| Chrome Web Store extensions | **not supported** | QtWebEngine has no Chrome extension runtime; the separate bridge is not an extension host |

## 3. Compatibility policy

* A site that refuses an embedded engine is **not** a reason to fabricate an
  identity. Mei shows the refusal and offers "open in external browser".
* A per-site workaround must be: narrow (specific host), explainable, testable,
  reversible, and must not alter unrelated sites or private sessions.
* Adding a host to `SIGN_IN_COMPAT_HOSTS` requires a reproducible sign-in
  failure without it and a test that the change does not affect other hosts.

## 4. Verification status

| Check | Result |
|---|---|
| No spoofing primitives in `browser_page.py` | asserted by `tests/test_engine_identity.py` |
| UA names Mei, real Chromium major, no `Google Chrome`/`QtWebEngine` | asserted |
| Allowlist suffix matching (no `evilaccounts.google.com`) | asserted |
| Hints report Chromium/Mei and the real full version | asserted |
| Real-world site matrix (Google, Microsoft, ChatGPT, GitHub, Notion, banks, WebRTC/WebGL/PDF pages) | **NOT RUN** — no interactive desktop/session in this environment |
| Screenshot of Browser Diagnostics | **NOT TAKEN** — requires a running GUI |

No result in this document should be read as "all sites work". The matrix above
is capability knowledge, not a test log.

## 5. Known limitations to disclose in-product

1. Hibernation reloads a page; unsaved form/SPA state is lost. Only URL, title,
   icon, group, workspace and zoom are restored.
2. Widevine/DRM content is unavailable.
3. Chrome Web Store extensions cannot be installed.
4. Sign-in providers may still refuse an embedded browser; external-browser
   handoff is the supported path.
5. GPU backend, hardware-acceleration and sandbox state are reported as
   `Unknown` unless an environment opt-out proves otherwise.
