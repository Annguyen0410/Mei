# ADR-0001 — Private downloads inherit the privacy context

- Status: Accepted (2026-11-14)
- Finding: F-20

## Context

Every `QWebEngineProfile` connected `downloadRequested` to one handler that always wrote a
record through `download_mgr.add_download`, which also appends an activity-history event.
The off-the-record flag existed for storage/cache/permissions but was not passed to the
download path. A file downloaded in a private tab therefore left its URL and filename in
`downloads.json` and `activity_history.json`.

## Options

1. **Delete download history wholesale** — rejects a useful feature and loses data.
2. **Filter private records out at read time** — the data still persists; privacy claim
   remains false.
3. **Bind the privacy context at signal connection** and never write private records.

## Decision

Option 3. `_configure_web_profile` and `TabManager._build_browser` connect the signal with
`private=off_the_record` / `private=True`. `_record_download` returns `None` for private
transfers. `_finalize_download(..., persisted=False)` still releases the hibernation pause
and shows a completion toast without persisting anything. Private downloads use a unique
in-memory key so repeated terminal signals stay idempotent.

## Consequences

- Private downloads work and leave no profile trace; the sidebar/history do not list them.
- A private download cannot be resumed from history after the session.
- Any new persistent writer must accept the same privacy flag; the rule is now in
  `AGENTS.md` and the threat model.

## Verification

`tests/test_hardening_2026.py::TestDownloadLifecycle` (private, regular, terminal,
in-progress). No storage migration required.
