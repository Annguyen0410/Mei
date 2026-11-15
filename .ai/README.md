# `.ai/` — verified architecture, security and memory for Mei

This directory is the persistent knowledge base for humans and coding agents. It exists so
a future session does not have to rediscover the whole browser, and so a previous decision
is not silently reversed.

**The code is the source of truth.** Every statement here was checked against the working
tree on 2026-11-14, at baseline commit `a74ec98` plus the changes listed in
`memory/CHANGELOG.md`. If code and document disagree, investigate and update the document.

## Map

| Path | What it answers |
|---|---|
| `architecture/SYSTEM_OVERVIEW.md` | What Mei is, its layers, lifecycle, tech stack |
| `architecture/MODULE_REGISTRY.md` | Module → paths, responsibilities, interfaces, tests |
| `architecture/DEPENDENCY_GRAPH.md` | Allowed dependencies, coupling hotspots, duplicates |
| `architecture/DATA_FLOW.md` | Where each kind of data is written and read (incl. event flow) |
| `architecture/SECURITY_BOUNDARIES.md` | Trusted vs untrusted, origin/profile/file/network boundaries |
| `architecture/FEATURE_INTEGRATION_MAP.md` | What each feature touches when it changes |
| `security/THREAT_MODEL.md` | Assets, adversaries, threats, accepted risks (incl. attack surface) |
| `security/SECURITY_FINDINGS.md` | Every finding with evidence and final disposition |
| `security/SECURITY_REGRESSION_MATRIX.md` | Finding → regression test that pins it |
| `testing/TEST_STRATEGY.md` | How the suite is structured and run |
| `testing/REGRESSION_COVERAGE.md` | Which behaviours are covered, which are not |
| `memory/CURRENT_STATE.md` | Engine versions, suite status, what just changed |
| `memory/KNOWN_CONSTRAINTS.md` | Platform/API limits that shaped the design |
| `memory/TECHNICAL_DEBT.md` | Known, prioritised remaining work |
| `memory/CHANGELOG.md` | Knowledge-base and code changes from this overhaul |
| `decisions/ADR/` | Why each structural decision exists |

## Deliberate consolidations

`EVENT_FLOW.md`, `APPLICATION_LIFECYCLE.md` and `PROFILE_LIFECYCLE.md` are folded into
`DATA_FLOW.md` and `SYSTEM_OVERVIEW.md` rather than duplicated: Qt signal wiring and
lifecycle are one subject, and two copies would drift. `ATTACK_SURFACE.md` is the
"Entry points" section of `THREAT_MODEL.md`, and `INTEGRATION_MATRIX.md` is
`FEATURE_INTEGRATION_MAP.md` plus the tables in `testing/REGRESSION_COVERAGE.md`.

## For the next agent

1. Read `AGENTS.md`, then this map.
2. Load the feature document(s) for the subsystem you will touch.
3. Use symbol search (or Serena, if configured) to locate the exact definitions.
4. Confirm external API behaviour against current Qt/PyQt documentation; do not trust
   training data for Qt 6.11 behaviour.
5. Trace the whole feature before editing: callers, lifecycle owner, persistence, tests.
6. Add a regression test for every confirmed defect and update the affected document.
