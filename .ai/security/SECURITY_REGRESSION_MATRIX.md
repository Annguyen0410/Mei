# Security regression matrix

Every fixed finding has a test that fails if the fix is reverted. Node IDs are stable.

| Finding | Behaviour pinned | Test node |
|---|---|---|
| F-20 | Private download writes no record and no activity event | `tests/test_hardening_2026.py::TestDownloadLifecycle::test_private_download_is_not_written_to_the_profile` |
| F-20 | Private terminal event still releases the hibernation pause | `…::test_private_terminal_event_releases_the_pause_without_writing` |
| F-20 | Regular download is still recorded | `…::test_regular_download_is_written_to_the_profile` |
| F-22 | Main and every incognito profile get the cookie filter | `…::TestCookiePolicyScope::test_every_profile_gets_the_filter` |
| F-22 | Filter refuses third-party but keeps first-party | `…::test_thirds_are_refused_but_first_party_is_kept` |
| F-22 | Turning the policy off installs a pass-through | `…::test_turning_the_policy_off_installs_a_pass_through` |
| F-21 | Ordinary Google pages lose device hints | `…::TestClientHintScope::test_device_hints_are_stripped_on_ordinary_google_pages` |
| F-21 | Sign-in host keeps truthful hints | `…::test_sign_in_host_keeps_its_hints` |
| F-28 | `blog.cloudflare.com` is not a challenge host | `…::test_cloudflare_registrable_domain_is_not_a_challenge_host` |
| F-26 | Exception rules parse into the allowlist | `…::TestExceptionRules::test_exception_rules_are_parsed_separately` |
| F-26 | Exception beats a blocking rule | `…::test_exception_wins_over_a_blocking_rule` |
| F-26 | Merged cache keeps `@@` lines | `…::test_merged_cache_keeps_exception_lines` |
| F-26 | Back-compat reader still returns blocks only | `…::test_back_compat_reader_returns_block_rules_only` |
| F-26 | Unsupported syntax stays skipped | `…::test_unsupported_syntax_is_still_skipped` |
| F-25 | Privacy dialog no longer offers the no-op toggle | `…::TestStrictReferrer::test_privacy_dialog_no_longer_offers_the_no_op_toggle` |
| F-25 | Old profiles still read the stored pref | `…::test_existing_preference_still_reads` |
| F-23 | MIME/sizes/timestamps are recorded | `…::TestDownloadLifecycle::test_records_mime_sizes_and_timestamps` |
| F-23 | Finish time is stamped once | `…::test_finish_time_is_stamped_once` |
| F-23 | Negative/unknown counters clamp to 0 | `…::test_missing_and_negative_sizes_are_normalised` |
| F-27 | Terminal event releases the pause exactly once | `…::test_terminal_event_releases_the_hibernation_pause` |
| F-27 | In-progress event keeps the pause | `…::test_a_download_that_is_still_running_keeps_the_pause` |
| URL policy | Normaliser accepts or refuses, never crashes | `…::TestUrlNormalisationInvariants::test_normalizer_accepts_or_refuses_but_never_crashes` |
| F-30 | Subscription bounds test no longer depends on import order | `tests/test_adblock_subscriptions.py::TestBounds` |
| F-34 | No page-context credential-capture script or storage key remains | `tests/test_hardening_2026.py::TestPasswordCaptureRemoved::test_no_page_context_capture_script_remains` |
| F-34 | Autofill keeps the secret out of `window` and `sessionStorage` | `…::test_autofill_keeps_credentials_out_of_page_scope` |

## Pre-existing coverage (not written by this overhaul)

| Area | Suite |
|---|---|
| DNS rebinding / redirect / proxy refusal | `tests/test_safe_http.py` |
| Password vault locking and legacy migration | `tests/test_password_manager.py` |
| Profile storage safety, locking, concurrency | `tests/test_profile_storage_safety.py`, `test_profile_concurrency.py` |
| Session/incognito payload exclusion | `tests/test_session_state.py` |
| Permission non-persistence in private mode | `tests/test_release_hardening.py` |
| Architecture/layer gates | `tests/test_architecture_boundaries.py`, `test_qt_facade.py` |

## Rule

A security fix without a node in this table is not finished. When a test here changes,
update the row in the same commit and explain why in `memory/CHANGELOG.md`.
