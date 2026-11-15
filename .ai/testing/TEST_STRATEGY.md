# Test strategy

## Layers

| Layer | Where | What it proves |
|---|---|---|
| Unit | `tests/test_*.py` | Pure logic: URL policy, filter parsing, storage, vault, migrations |
| Structural gates | `test_architecture_boundaries`, `test_qt_facade`, `test_capability_ledger`, `test_command_registry`, `test_brand_consistency` | The codebase still has the intended shape |
| Integration | `test_session_state`, `test_profile_storage_safety`, `test_matrix_*`, `test_extension_bridge_*` | Features work together: profiles ↔ tabs ↔ stores |
| Security regression | `test_safe_http`, `test_critical_safety`, `test_password_manager`, `test_hardening_2026` | Adversarial inputs and privacy invariants |
| UI (offscreen) | `test_matrix_ui_dialogs`, `test_notes_page_ui`, `test_desktop_polish`, … | Widget wiring under `QT_QPA_PLATFORM=offscreen` |
| Property-based | `test_hardening_2026::TestUrlNormalisationInvariants` | Arbitrary text never escapes the URL contract |

## Running

```bash
./.venv/Scripts/python.exe -m pytest -q                 # full suite
./.venv/Scripts/python.exe -m pytest tests/test_hardening_2026.py -q
./.venv/Scripts/python.exe -m ruff check --select F401,F811,F841,F821 litebrowser tests tools
```

`tests/conftest.py` forces offscreen Qt and blanks the update channel so no test performs a
live HTTP request. Tests must not depend on wall-clock time (CI runs the suite at 10:00 and
22:00 via `tools/run_at_hour.py`).

## CI (`.github/workflows/ci.yml`)

- Windows runner, Python 3.11, matrix PyQt5 (legacy canary) + PyQt6 (shipped pin).
- Engine report + security-version gate; ruff subset; both halves of the day; full suite
  with `faulthandler_timeout` and failing-test annotations.
- Missing (documented debt): type checking, CodeQL/OpenGrep scanning, secret scanning,
  dependency audit, zizmor.

## Writing a test

1. Prefer the smallest unit that can fail for the right reason.
2. Assert the **intended behaviour**, not the implementation's assumptions (no mirror tests).
3. For a security fix, add a row to `security/SECURITY_REGRESSION_MATRIX.md`.
4. Do not weaken or delete an existing assertion to get green; fix the cause or document a
   real platform limitation.
5. Every persisted shape change needs a test that an older file still loads.
