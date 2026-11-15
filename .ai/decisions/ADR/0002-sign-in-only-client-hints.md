# ADR-0002 — Client Hints restricted to sign-in origins

- Status: Accepted (2026-11-14)
- Finding: F-21

## Context

`adblock._COMPAT_DOMAINS` listed whole registrable domains (`google.com`, `microsoft.com`,
`openai.com`, `anthropic.com`, `bing.com`, …). `interceptRequest` used that list to decide
whether to keep low-entropy Client Hints. The result: on ordinary pages of those domains the
CPU/GPU/arch hints leaked, contradicting the Privacy dialog ("Login sites … still receive
the full headers") and the setting's name ("Hide device info … from unfamiliar sites").

## Options

1. Keep the broad list for compatibility — silently false privacy claim.
2. Remove Client Hints entirely — breaks sign-in flows that require them.
3. Use the existing, narrow `engine_identity.SIGN_IN_COMPAT_HOSTS` list (exact host or
   subdomain of an exact host).

## Decision

Option 3. `is_compat = engine_identity.is_sign_in_host(host)`; headers are still applied only
when the separate sign-in compatibility preference is enabled. `_COMPAT_DOMAINS` and
`_is_compat_domain` were deleted so a second broad list cannot reappear.

## Consequences

- Ordinary Google/Microsoft/OpenAI pages now lose arch/bitness/full-version as promised.
- Sign-in pages keep their hints only when the user opts in.
- Any future compatibility need adds an **exact host** to `SIGN_IN_COMPAT_HOSTS` with a
  reason, not a registrable domain.

## Verification

`tests/test_hardening_2026.py::TestClientHintScope`; `tests/test_engine_identity.py`.
