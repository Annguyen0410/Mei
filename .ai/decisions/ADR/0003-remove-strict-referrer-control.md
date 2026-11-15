# ADR-0003 — Remove the unenforceable strict-referrer control

- Status: Accepted (2026-11-14)
- Finding: F-25 / F-29

## Context

Privacy & Security showed "Send shortened Referer to other sites (strict-origin)". The value
was written to `prefs.json`, copied onto `TrackingBlocker.strict_referrer`, and read by
nothing. Unchecking it promised the full URL would be sent; that never happened either.

Qt WebEngine does not expose a per-request referrer-policy hook. Chromium already applies
`strict-origin-when-cross-origin`, which is exactly the shipped behaviour. Setting
`Referrer-Policy` as a request header through the interceptor triggers CORS preflights
(the code comment in `interceptRequest` records the earlier attempt).

## Options

1. Implement it by setting the `Referer` header manually — brittle, breaks CORS, and
   Chromium may override it; cannot honestly promise the "off" state.
2. Leave the dead control — a false privacy control.
3. Remove the control, state the real behaviour, keep the stored pref for compatibility.

## Decision

Option 3. The checkbox is replaced by a factual sentence. `get_strict_referrer` /
`set_strict_referrer` remain so existing profiles keep loading and a future engine API can
re-use the key. The interceptor no longer carries the unused attribute.

## Consequences

- One fewer privacy control, but every remaining control does something.
- Users cannot request "send full referrer"; no supported API provides it.
- If Qt adds a referrer hook, re-introduce the control with an ADR superseding this one.

## Verification

`tests/test_hardening_2026.py::TestStrictReferrer`.
