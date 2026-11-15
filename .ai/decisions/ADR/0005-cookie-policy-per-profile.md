# ADR-0005 — Cookie policy installed per profile

- Status: Accepted (2026-11-14)
- Finding: F-22

## Context

`_apply_cookie_policy` called `self.profile.cookieStore().setCookieFilter(...)` once, at
startup. Incognito profiles created later by `TabManager._build_browser` never received the
filter, so "block third-party cookies" (default on) was silently ignored in private tabs.
Qt has no global cookie filter and no `unsetCookieFilter`.

## Options

1. Apply the filter lazily on first navigation — easy to miss, hard to test.
2. Apply it whenever a profile is created and whenever the setting changes, over the list of
   profiles the window owns.
3. Move the policy into `BrowserPage` — same per-profile problem, more places to get wrong.

## Decision

Option 2. `_apply_cookie_policy` iterates `[self.profile] + self._incognito_profiles`,
installing one shared callable. `_build_browser` calls it after creating an OTR profile.
Turning the policy off installs a pass-through (Qt cannot remove a filter). The sign-in
exemption remains the six exact hosts in `COMPATIBILITY_HOSTS`.

## Consequences

- Every profile, including private ones, follows the setting.
- Installing the filter is idempotent and cheap; it runs once per new private tab.
- A future third profile type must be added to the same iteration.

## Verification

`tests/test_hardening_2026.py::TestCookiePolicyScope` (3 tests); manual QA with a loopback
origin is still required to confirm engine behaviour.
