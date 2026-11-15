# Regression coverage

## Covered by tests (verified paths)

| Behaviour | Suite |
|---|---|
| URL normalisation, DNS rebinding, redirect downgrade, proxy refusal | `test_safe_http` |
| Filter parsing bounds, subscription cache survival, `@@` exceptions | `test_adblock`, `test_adblock_subscriptions`, `test_hardening_2026` |
| Client-hint scope, challenge-host scope | `test_hardening_2026`, `test_engine_identity` |
| Cookie policy on all profiles | `test_hardening_2026` |
| Download metadata, terminal-state idempotence, pause counter, private exclusion | `test_hardening_2026`, `test_matrix_services_extra` |
| Password vault encryption, wrong-password lockout, legacy migration | `test_password_manager` |
| Private permissions / session / tab-set exclusion | `test_release_hardening`, `test_session_state` |
| Storage migrations and versioned stores | `test_store_migrations`, `test_matrix_storage` |
| Local-file navigation policy | `test_new_tab_security`, `test_critical_safety` |
| Architecture boundaries and Qt façade | `test_architecture_boundaries`, `test_qt_facade` |

## Not covered (honest gaps)

| Gap | Why it matters | Next step |
|---|---|---|
| Tab tear-off / duplicate across normal and private windows | Profile-context ambiguity (Issue 02) | Offscreen test constructing two windows and moving a tab |
| Split view with mixed privacy state | Same | Construct split with one OTR page and assert session exclusion |
| Favicon cache eviction | Unbounded disk growth | Add LRU or size cap + test |
| Proxy/DNS/WebRTC leak behaviour | Privacy claim (Issue 18) | Scriptable leak probe with a local proxy; currently manual only |
| Extension main-world isolation | Privilege boundary (F-24) | Design isolated world without breaking userscripts |
| Real Chromium behaviour (headers, cookie filter) | Unit fakes cannot prove engine behaviour | Manual QA with a loopback server; add to release checklist |
| Qt5 path | Production is Qt6 | CI canary only; do not fix Qt5-specific behaviour |
| Backup/restore of a real large profile | Data loss risk | Benchmark tool exists (`tools/benchmark_data_integrity.py`); add round-trip fixture |

## Baseline and current status

- Baseline (before any change): `3356 passed, 56 skipped, 1520 subtests`, 147 s.
- Post-change numbers are recorded in `MEI_ENGINEERING_OVERHAUL_REPORT.md`.
- Any failure that predates this work is listed there, never silently skipped.
