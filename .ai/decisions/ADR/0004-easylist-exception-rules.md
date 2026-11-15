# ADR-0004 — EasyList exception rules with allow-over-block precedence

- Status: Accepted (2026-11-14)
- Finding: F-26

## Context

The parser only understood `||domain^` and bare domains. EasyList's `@@` exception rules
failed the domain regex and were dropped, so a site explicitly whitelisted inside a blocked
CDN stayed blocked. That is over-blocking caused by partial syntax support.

## Options

1. Treat `@@` as a block rule — worse.
2. Skip the line (status quo) — silent over-blocking.
3. Parse exceptions into a separate allowlist and let them win.

## Decision

Option 3.

- `_filter_rule(line) -> (kind, domain)` with `kind ∈ {"block", "allow"}`; supported shapes
  are `||domain^`, bare `domain`, and their `@@` forms. Cosmetic/regex/path/`$` rules remain
  unsupported and are skipped.
- `load_filter_file(path) -> (blocked, allowed)`; `load_domains_from_filter_file` remains as
  a block-only wrapper for existing callers.
- Subscriptions keep `@@` lines in the merged cache.
- `_is_blocked_host` checks the allowlist first, so an exception overrides both the built-in
  list and subscription rules.

## Consequences

- Whitelisted sites work as the list author intended.
- An exception line can disable a built-in rule for its domain; that is EasyList semantics
  and is limited to domain-scoped rules (no path/option exceptions).
- Still not full EasyList compatibility; documented in the UI-adjacent audit matrix.

## Verification

`tests/test_hardening_2026.py::TestExceptionRules` (5 tests) plus the existing subscription
and performance tests.
