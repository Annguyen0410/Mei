# Known constraints

## Engine / Qt

- **Chromium version is a Qt decision.** Qt 6.11 ships Chromium 140; updating PyQt6 alone
  does not move the patch stream. `core/engine_security.py` encodes the minimum security
  version and CI fails below it.
- **Proxy flags are read at startup.** `main.py` composes `QTWEBENGINE_CHROMIUM_FLAGS`
  (`--proxy-server=…`); changing the proxy requires a restart and the UI says so.
- **No `unsetCookieFilter`.** Turning third-party blocking off installs a pass-through
  filter instead of removing one.
- **`setCookieFilter` applies per store.** Every profile (including OTR) must be configured
  individually — this was the F-22 defect.
- **Qt has no per-request Referrer API.** The engine enforces
  strict-origin-when-cross-origin; a "send full URL" toggle cannot be implemented through
  the interceptor without breaking CORS. The control was removed (F-25).
- **Header control is limited.** `setHttpHeader` sets request headers; setting
  `Referrer-Policy` there triggers CORS preflights, which is why it is absent.
- **Scripts default to the main world.** `QWebEngineScript` runs in `MainWorld` for page
  globals; there is no isolated-world path in the current design (F-24).
- **Downloads use different accessors on Qt5/Qt6.** `totalBytes`/`receivedBytes`/`mimeType`
  are optional; `_download_attr` tolerates missing ones.

## Python

- **No memory zeroization.** Immutable `str` and Qt objects cannot be reliably wiped; the
  vault limits exposure rather than claiming secure erasure.
- **DPAPI is Windows-only.** Other platforms fall back to owner-only files and say so.
- **Threading.** Services are synchronous and lock-protected; long work runs on a shell
  executor, never on the UI thread. Signals may fire more than once — terminal handlers
  must be idempotent.

## Product

- **One profile per window.** `get_profile_for_url` returns the window's profile; private
  browsing is a separate OTR profile per tab, flagged explicitly.
- **Workspaces are UI groupings**, not profiles; their IDs are strings, not typed handles.
- **EasyList subset.** Domain rules and `@@` exceptions only; no cosmetic/regex/options.
- **App-level fetches are direct-only.** They refuse when a proxy is configured rather than
  bypassing the user's policy.

## Repository

- **One engine in CI.** PyQt6 6.11 / Chromium 140 only. The PyQt5 job was removed: it
  installed real Qt 5.15 (Chromium 87) — an engine nobody runs — and it died on a native
  access violation in the request interceptor, which no `try/except` can catch. The
  `from PyQt5 ...` imports in the source are rewritten onto PyQt6 by `qt_compat`.
- **Test isolation.** `conftest.py` blanks the update channel and forces offscreen Qt; tests
  must not require network, a display, or a specific wall-clock hour.
- **`uv.lock` is not regenerated** by the dependency-floor change; run `uv lock` when the
  next release is prepared.
