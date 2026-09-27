# Engine spike — PyQt6 6.11 / Chromium 140

**Status: landed.** The engine is pinned (PyQt6 / PyQt6-WebEngine 6.11.0 in
`pyproject.toml` and in the CI matrix), the one app-side assumption it broke is
fixed with tests, the engine is visible in Settings, and the packaged `.exe` was
rebuilt on it. This file is the evidence, the two things that still need a human,
and what was *not* tested.

Measured on 2026-09-26/27, Windows, x64, 3.11 interpreter.

| | before | after |
|---|---|---|
| PyQt6 / PyQt6-WebEngine | 6.8.0 | **6.11.0** |
| Qt | 6.8.2 | 6.11.2 |
| Chromium (`qWebEngineChromiumVersion`) | 122.0.6261.171 | **140.0.7339.225** |

## What was run

| Check | On 122 | On 140 | Result |
|---|---|---|---|
| Full suite | 785 passed / 739 subtests | 798 passed / 739 subtests | green both sides; 13 of the new tests are this work's |
| Ruff (`F401,F811,F841,F821`) | clean | clean | — |
| CI (Qt6 job) | — | green, twice | the job is now **pinned** to 6.11.0; before that it installed `PyQt6>=6.6` and had already been testing 140 by accident |
| App-level smoke, 24 facts (`tools/engine_smoke.py`) | 24/24 | 24/24 | two facts failed on 140 before the fix below |
| Packaged exe (`--onefile --windowed`) | 3 engine processes, 43 threads, 439 MB | 3 engine processes, 44 threads, 477 MB | same shape |
| `Mei 1.0.0.0 ready in …` from source | 11.71s | 10.55s | one sample each; no regression |

The suite was run in an isolated venv (`build/spike-qt611/.venv`, gitignored) so
the working `.venv` kept running the shipped engine until the switch was decided.
The CI job matters more than it looks: it runs the same command as the local
runs, on a Windows runner with `QT_QPA_PLATFORM=offscreen`, and its install was
unpinned — so a green run was already a green run on Chromium 140. Pinning it
means the green run now says *which* engine it tested, and a Qt bump cannot reach
users through CI again.

### The smoke, and why it exists

The suite is service-heavy and its GUI half is offscreen smoke, so a Qt jump can
pass every test and still break the *app*: an interceptor whose signature
changed, a profile path that never gets created, a download that never fires,
force-dark that silently stops applying, a UA spoof that keeps claiming an engine
we no longer ship.

`tools/engine_smoke.py` drives the app's own code for exactly those paths and
prints one PASS/FAIL line per fact; it is hermetic (pages come from a loopback
HTTP server, so it needs no network) and exits non-zero if anything failed. Facts
it pins: the shim resolving WebEngine onto PyQt6; the engine's own version; the
UA spoof following the live engine; the client hints carrying a *real* build;
the interceptor being called by the engine, blocking a blocked host for real and
leaving the control host alone; profile scripts still running at
`DocumentReady` (proven with a probe script, so "stood down on purpose" can be
told apart from "never ran"); force-dark either repainting a light page or
standing down on a dark one; a download reaching `downloadRequested`; the
persistent storage and cache paths being created; and **two pages at once on one
profile** — the shape split view and web panel actually create
(`window_mixins.open_split_view` / `toggle_web_panel`, both `BrowserPage` on the
same profile), which also proves the compatibility shim is installed once rather
than once per page.

An earlier revision of this report claimed those two features do not exist. That
was a truncated `grep` on my side: they do, and nothing in the suite drives them
— the smoke now covers their engine shape, the docks themselves stay uncovered
(see *not tested*, below).

## Findings

### F1 — the client hints carried an invented build (fixed)

The Chrome-shaped client hints sent to sign-in hosts carry a full build number,
and they were read out of the engine's user agent. Qt 6.8's UA says
`Chrome/122.0.6261.171` — a real build. Qt 6.11's says only `Chrome/140.0.0.0`;
the 4-part regex still matched, so `sec-ch-ua-full-version` would have gone out
as a build that never existed, on the header the fragile Google compatibility
path lives on. (On 0.7.1.0 the value was correct: this was an assumption waiting
for a Qt release.)

Fixed by asking the binding first — `qWebEngineChromiumVersion()` needs no
application object and answers on both engines — with the UA path kept as the
fallback only, which is what the PyQt5 branch has left (`tests/test_engine_visibility.py`
pins the precedence, the reduced-UA case, and the fallback's shape).

### F2 — `prefers-color-scheme` is host-dependent again (needs a human, 15 minutes)

With `QT_QPA_PLATFORM=offscreen`, 6.8 hands the page `prefers-color-scheme:
light` and 6.11 hands it `dark` (the host desktop is in dark mode). force-dark
does exactly what it documents — it stands down and leaves the page alone — so
this is not a bug; it is a rendering difference a headless run cannot settle. It
also means `QStyleHints.setColorScheme()` does not stick under the offscreen
platform on 6.11, which is why the smoke reports the scheme it *observed* instead
of the one it asked for.

Before promoting the Alpha: open a few light-only sites with force-dark off and
on, on a real display, in both Windows light and dark mode.

### F3 — the pre-existing "unstable on Windows" note, located (fixed in the suite)

Writing the F1 test hard-crashed the suite: touching
`QWebEngineProfile.defaultProfile()` late in a run that has already built and
torn down GUI tests takes Qt 6.11 down with it, and the old docstring's caveat
("when called before a QApplication exists") was only half the story. PyQt6 never
reaches that path now, and rather than keep a test that reproduces a crash, the
UA parsing became a pure function (`adblock._ua_chrome_versions`, string in,
version out) whose rules are covered without asking Qt anything.

### F4 — packaging is a second variable (process note)

The frozen build is healthy on the new engine — onefile + windowed starts, spawns
**3** `QtWebEngineProcess` children, reaches 44 threads and ~477 MB, and the
rebuilt `dist/Mei.exe` is 208 MB (the 0.7.1.0 exe was 168 MB; Qt 6.11's WebEngine
ships more data). It was verified with both `PyInstaller 6.19.0` (what the
working venv has, and now what `pyproject.toml` pins) and `6.22.3`, which is why
the report pins them separately: two moving parts in one commit means a broken
exe with two possible causes. `tools/engine_exe_smoke.ps1` re-runs that check
(engine processes up, and the thread/memory shape) and kills by PID, so a running
Mei of yours is never touched.

`--onedir --console` builds are the useful diagnostic form: they print
`Mei 1.0.0.0 ready in 2.56s` and every Chromium error to a real console, where a
`--windowed` onefile build prints nothing at all. Worth remembering for the next
frozen-build hunt.

## What the upgrade buys

- 18 Chromium majors of security and web-platform fixes: this is a browser, so
  the engine *is* the product surface.
- Fewer sites classifying a 2024-era UA as unsupported.
- The checks are now tools rather than a one-off: the next jump is
  `tools/engine_report.py` before, `tools/engine_smoke.py` during, and
  `tools/engine_exe_smoke.ps1` after — which is what made this one cost an
  afternoon instead of a release.

## What was **not** tested

Only offscreen rendering and loopback traffic were exercised. Untested: Google
sign-in end to end, Cloudflare/hCaptcha challenges, hardware GPU paths and video
decode, DRM (Widevine/Netflix), the built-in PDF viewer, printing, downloads from
real hosts, and interactive desktop behaviour generally. Also uncovered by any
test, engine-independent: the split-view and web-panel **docks** themselves (the
missing `MainWindow`-level test is a gap this spike did not close). A 30-minute
manual checklist on a real display, plus the Alpha/beta channel, is the mitigation
— not more headless runs.

## Reproducing this

```bash
# isolated venv, if you want to test an engine before adopting it
python -m venv build/spike/.venv
build/spike/.venv/Scripts/python.exe -m pip install PyQt6==6.11.0 PyQt6-WebEngine==6.11.0 pytest ruff
# which engine would this interpreter run?
build/spike/.venv/Scripts/python.exe tools/engine_report.py
# the suite (keep temp off a full system drive)
TEMP=<repo>/build/spike/tmp build/spike/.venv/Scripts/python.exe -m pytest -p no:cacheprovider --no-header -q
# app-level engine smoke — no network needed, non-zero exit on any failed fact
build/spike/.venv/Scripts/python.exe tools/engine_smoke.py
# packaged app: is the engine actually up, and in what shape
powershell -NoProfile -ExecutionPolicy Bypass -File tools/engine_exe_smoke.ps1 -ExePaths dist/Mei.exe
```
