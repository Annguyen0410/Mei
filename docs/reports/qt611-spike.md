# Engine spike — PyQt6 6.11 / Chromium 140

**Verdict: land it.** The jump from Chromium 122 to 140 passes the whole suite on
the new engine, drives every engine-level path the app has, and packages into a
working `Mei.exe`. Two app-side assumptions break on the way (both fixable with
small, testable changes) and one packaging variable should be pinned in the same
commit so the two are never bumped together again.

Measured on 2026-09-26/27, Windows, x64, 3.11 interpreter.

| | today (shipped) | spike |
|---|---|---|
| PyQt6 / PyQt6-WebEngine | 6.8.0 | 6.11.0 |
| Qt | 6.8.2 | 6.11.2 |
| Chromium (`qWebEngineChromiumVersion`) | 122.0.6261.171 | **140.0.7339.225** |

## What was run

| Check | Today | Spike | Result |
|---|---|---|---|
| Full suite, isolated venv | 785 passed / 739 subtests | 785 passed / 739 subtests | identical, no skips either side |
| Ruff (`F401,F811,F841,F821`) | clean | clean | — |
| CI `tests · PyQt6` job | green | green on the pushed commit | see below |
| App-level smoke, 20 facts (`build/spike-qt611/smoke_engine.py`) | 20/20 | 18/20 | both failures are app assumptions, not engine breakage |
| Packaged `--onefile --windowed` exe | starts, 3 engine processes | starts, 3 engine processes | same shape, see packaging |
| `Mei 1.0.0.0 ready in …` from source | 11.71s | 10.55s | one sample each; no regression |

The CI job matters more than it looks: `.github/workflows/ci.yml` installs
`PyQt6>=6.6` **unpinned** and runs the exact command the local runs use, on a
Windows runner with `QT_QPA_PLATFORM=offscreen`. So the green Qt6 job on the
pushed commit (`e045a1b`) is the same suite on 6.11 in a second environment — the
suite already passes on Chromium 140 twice, in two places, without the venv being
hand-built.

### The smoke, and why it exists

The suite is service-heavy and its GUI half is offscreen smoke, so a Qt jump can
pass all 785 tests and still break the app: an interceptor whose signature
changed, a profile path that never gets created, a download that never fires,
force-dark that silently stops applying, a UA spoof that keeps claiming an engine
we no longer ship.

`build/spike-qt611/smoke_engine.py` drives the app's own code for exactly those
paths and prints one PASS/FAIL line per fact. It is hermetic: pages are served
from a loopback HTTP server, so it needs no network and gives the same answers on
a machine that has none. Facts it pins, all green on both engines unless noted:

- the shim resolves `PyQt5.QtWebEngineCore`/`QtWidgets` onto PyQt6;
- the engine's own version, from the binding;
- the adblock UA spoof follows the live engine and the spoofed UA carries the
  real major version;
- client hints are Chrome-shaped (`Chromium`, `Google Chrome`, `Not(A:Brand`);
- the app's `TrackingBlocker.interceptRequest` is called by the engine, the
  blocked host (`doubleclick.net`) is blocked for real (image never loads) and
  the control host is not;
- profile scripts still run at `DocumentReady` (proven with a probe script of our
  own, so "stood down on purpose" can be told apart from "never ran");
- force-dark repaints a light page, or deliberately stands down when the page
  already asks for dark;
- a download reaches `downloadRequested`; the persistent storage and cache paths
  get created.

There is no split view or web panel in this app (grepped: neither exists), so the
plan's smoke list was replaced by the surfaces that do exist — interceptor,
ad-block, force-dark, script injection, downloads, profile paths, UA and client
hints.

## Findings

### F1 — the client-hint full version goes stale on 6.11 (medium, app-side)

On Qt 6.8 the engine's default UA carries the full 4-part Chromium version
(`Chrome/122.0.6261.171`), so `adblock._detect_chrome_versions()` matches its
4-part regex and reports a real build. On Qt 6.11 the same UA reports only
`Chrome/140.0.0.0`, the regex falls through to the major-only branch, and
`sec-ch-ua-full-version` goes out as `"140.0.0.0"` — a build that has never
existed — while `qWebEngineChromiumVersion()` knows the real one
(`140.0.7339.225`).

This is the app's most fragile integration (the Chrome-shaped hints exist to stop
Google rejecting the built-in browser), and the fix is small and engine-agnostic:

```python
def _detect_chrome_versions():
    ...
    try:
        from PyQt5.QtWebEngineCore import qWebEngineChromiumVersion
        full = qWebEngineChromiumVersion() or ""
        if re.match(r"^\d+\.\d+\.\d+\.\d+$", full):
            return full.split(".")[0], full      # authoritative, both engines
    except Exception:
        pass
    ...  # existing UA regex stays as the fallback
```

Also update the two stale constants that still say `122` (the `major`/`full`
fallback in the same function, and the `Chromium ~122` comment on
`interceptRequest`), and add a test that asserts the hints match
`qWebEngineChromiumVersion()` rather than a literal.

Cheap insurance either way: the hints only differ from the truth in a field a bot
check could read.

### F2 — `prefers-color-scheme` is host-dependent again (low, needs a human eye)

With `QT_QPA_PLATFORM=offscreen`, 6.8 hands the page `prefers-color-scheme:
light` and 6.11 hands it `dark` (the host desktop is in dark mode). force-dark
does exactly what it documents — it stands down and leaves the page alone — so
this is not a bug; it is a rendering difference that a headless run cannot settle.
It also means `QStyleHints.setColorScheme()` does not stick under the offscreen
platform on 6.11, which is why the smoke reports the scheme it *observed* instead
of the one it asked for.

Before shipping: open a few light-only sites with force-dark off and on, on a
real display, in both Windows light and dark mode. Fifteen minutes, no code.

### F3 — packaging is a second variable (process note)

The frozen build is healthy on the new engine: onefile + windowed starts, spawns
**3** `QtWebEngineProcess` children, reaches 43 threads and ~487 MB — the shipped
0.7.1.0 exe measures 3 / 43 / 439 MB. Same for a build with `PyInstaller 6.19.0`
(the version in the working venv) and with `6.22.3` (ships with newer pip
resolution), which is why the report pins both: if Qt and PyInstaller move in the
same commit and the exe misbehaves, there is no way to tell which one did it.

`--onedir --console` builds are the useful diagnostic form: they print
`Mei 1.0.0.0 ready in 2.56s` and every Chromium error to a real console, where
`--windowed` onefile builds print nothing at all. Keep that trick in mind for the
next frozen-build hunt.

## What the upgrade buys

- 18 Chromium majors of security and web-platform fixes: this is a browser, so
  the engine *is* the product surface.
- Fewer sites classifying a 2024-era UA as unsupported. Qt's own release notes
  and the Chromium version table make the ordering explicit; `122` is old enough
  that some sign-in and challenge flows already treat it as suspicious.
- It is the last cheap jump: the venv is one `pip install` away and the suite
  gives a clean signal. Each further jump is the same spike again, so pinning
  what we land on is what makes the next one cheaper.

## What this spike did **not** cover

Only offscreen rendering and loopback traffic were exercised. Untested: Google
sign-in end to end, Cloudflare/hCaptcha challenges, hardware GPU paths and video
decode, DRM (Widevine/Netflix), the built-in PDF viewer, printing, downloads from
real hosts, and interactive desktop behaviour generally. A 30-minute manual
checklist on a real display, plus the beta/Alpha channel, is the mitigation — not
more headless runs.

## Steps to land (next commit, after a read)

1. Pin in the same commit: `PyQt6==6.11.0`, `PyQt6-WebEngine==6.11.0`,
   `PyInstaller==6.19.0`; update `[project.optional-dependencies] qt6` and the CI
   matrix so the Qt6 job stops being an accidental beta channel.
2. Apply F1 with its test; refresh the stale `122` constants.
3. Make the engine visible: print `qWebEngineChromiumVersion()` in Diagnostics /
   Settings, and warn when the PyQt5 branch is in use (Qt 5.15.2 ships Chromium
   87 — a fact worth showing, not hiding).
4. Add one CI step that prints the engine version, so every future run records
   which Chromium it tested.
5. Rebuild `Mei.exe`, run the F2 eye check, then cut the Alpha pre-release.

## Reproducing this spike

```bash
# isolated venv (never touch the working one)
build/spike-qt611/.venv/Scripts/python.exe -m pip install PyQt6==6.11.0 PyQt6-WebEngine==6.11.0 pytest
# suite on the new engine
TEMP=<repo>/build/spike-qt611/tmp build/spike-qt611/.venv/Scripts/python.exe -m pytest -p no:cacheprovider --no-header -q
# app-level smoke (no network needed)
build/spike-qt611/.venv/Scripts/python.exe build/spike-qt611/smoke_engine.py
# packaging, with all temp/work output kept off the system drive
build/spike-qt611/.venv/Scripts/python.exe -m PyInstaller --onefile --windowed ... browser.py
# packaged-app check: engine processes + thread/handle shape
powershell -NoProfile -ExecutionPolicy Bypass -File build/spike-qt611/run_exe_smoke.ps1
```

Everything lives under `build/spike-qt611/` (gitignored, ~700 MB with both venv
and build output) and can be deleted whole; the two scripts are worth keeping
because they are what make the next engine jump cheap.
