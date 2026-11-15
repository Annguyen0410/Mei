# Technical debt (prioritised)

## Priority 1 — security architecture

1. **F-24 / F-34 credential capture.** The plaintext `sessionStorage` handoff is removed and
   save-on-login is suspended (ADR-0006). Re-enabling needs an isolated-world bridge with a
   nonce/Origin-validated native channel; userscripts stay in the page world by design
   (documented, no secrets).
2. **F-32 silent exception suppression.** Many UI/service paths use `except Exception: pass`.
   Each one hides a real failure mode. Replace with logged, typed handling; start with
   download/session/cookie paths.
3. **Proxy/leak verification (Issue 18).** Leak test compares visible vs direct IP only.
   Add DNS and WebRTC checks or restate the guarantee in the UI.

## Priority 2 — correctness and lifecycle

4. **Issue 02/15 verification.** Add runtime tests for tab tear-off/duplication and split
   view across normal/private windows; consider typed IDs for profile vs workspace.
5. **F-31 favicon cache.** No eviction; key includes the full URL (per-path duplicates).
   Add a size cap/LRU and invalidate on origin change.
6. **F-30 class of bugs.** The suite had an order dependency; add a CI job that runs test
   files in isolation or randomized order to catch the next one.
7. **EasyList completeness.** Cosmetic filters and `$` options are unsupported; document in
   the UI, not only in audit docs.

## Priority 3 — engineering quality

8. **`window.py` / `personal_window.py` / `shell/pages.py` size** (4.1k / 5.4k / 3.4k lines).
   Extract concerns along the existing mixin pattern; do not rewrite behaviour.
9. **Type checking.** Pyright is not configured or in CI. Introduce gradually on `core/` and
   `services/` where annotations already exist.
10. **CI security scanning.** No CodeQL, OpenGrep, Gitleaks, pip-audit or zizmor. Add
    pip-audit at minimum; it caught a real advisory during this audit.
11. **Qt5 façade migration.** The `QT5_ALLOWLIST` is a shrinking migration list; keep it
    shrinking and never add entries.
12. **`uv.lock` drift.** Dependency floors changed without regenerating the lock.
