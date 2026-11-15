# AGENTS.md — working on Mei

Mei is a Qt WebEngine desktop browser. Production engine is **PyQt6 6.11.0 / Qt 6.11.0 /
Chromium 140.0.7339.225**, and the only one CI tests. PyQt5/Qt 5.15 is not supported: the
`from PyQt5 ...` imports throughout the source are rewritten onto PyQt6 by
`litebrowser/qt_compat.py`, so do not install real PyQt5 or "fix" a Qt5-only path.
Read `ARCHITECTURE.md` and `.ai/architecture/SYSTEM_OVERVIEW.md` before touching a major
subsystem, then the matching feature/boundary document under `.ai/`.

## Read before you edit

| You are changing | Read first |
|---|---|
| Tabs, profiles, incognito, hibernation | `.ai/architecture/SYSTEM_OVERVIEW.md`, `.ai/security/THREAT_MODEL.md` |
| Downloads, history, activity log | `.ai/architecture/DATA_FLOW.md`, `.ai/security/SECURITY_FINDINGS.md` |
| Adblock, Client Hints, cookies, HTTPS-only | `.ai/security/SECURITY_BOUNDARIES.md` |
| Storage, prefs, migrations, backups | `.ai/architecture/DATA_FLOW.md`, `.ai/memory/KNOWN_CONSTRAINTS.md` |
| Services layer | `.ai/architecture/DEPENDENCY_GRAPH.md` |

## Layer rules (enforced by `tests/test_architecture_boundaries.py` and `tests/test_qt_facade.py`)

1. `core/` and `services/` must not import `ui/`.
2. `services/` must not import `browser/`; `browser/` must not import `services/`.
   Shared helpers live in `core/`.
3. The layer graph stays acyclic. Orphan modules and stale allowlists fail the suite.
4. New code imports Qt through `litebrowser/qt.py`, not the binding directly.

## Non-negotiables

- **Private browsing writes nothing to the profile.** Any subsystem that persists
  navigation, downloads, permissions, session state or AI context must check the
  profile's off-the-record state first. `private_download` and session/tab-set code
  are the reference implementations.
- **One owner per data file.** `activity_history.json` is the only browser-history
  store; `downloads.json` only holds download records; prefs live in `prefs.json`.
  Do not add a second source of truth.
- **Origin checks parse URLs**; never compare string prefixes. `services/safe_http.py`
  is the reference (IDNA, ports, credentials, redirects, pinned IPs).
- **No security control is removed to make a test pass.** If an API cannot deliver a
  promised behaviour, remove the promise from the UI and document the decision.
- **Backward compatibility.** Additive JSON fields are read with `.get`; changing a
  shape requires a version bump and a `core/migrations.py` step.
- **Secrets never enter logs, diagnostics, backups or activity history.**
  Use `core/secret_store.py` and the redaction helpers.

## Verification (run from the repository root)

```bash
./.venv/Scripts/python.exe -m pytest -q                       # full suite (~150 s)
./.venv/Scripts/python.exe -m ruff check --select F401,F811,F841,F821 litebrowser tests tools
./.venv/Scripts/python.exe tools/engine_report.py             # engine actually installed
./.venv/Scripts/python.exe tools/check_engine_security.py     # fails below the patch floor
```

A change is done when the affected tests pass **and** the full suite still passes.
Never report a check you did not run; state skipped/platform-limited checks explicitly.

## After a structural change

Update the matching `.ai/` document and add an ADR for decisions that affect data
ownership, security boundaries, network behaviour or feature integration. The code is
the source of truth; these documents are its verified map.
