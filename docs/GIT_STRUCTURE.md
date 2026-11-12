# Repository structure and branch policy

One trunk, one remote that owns the product, and short-lived branches that die on
merge. This page is the contract; the tables at the bottom record the
consolidation that brought the repository to it.

## At a glance

| Thing | Value |
| --- | --- |
| Trunk | `main` |
| Product remote | `origin` → `github.com/Annguyen0410/Mei.git` |
| Legacy remote | `mahoraga` → `MAHORAGA-ADAPT-SYSTEM-MAS-v9.0` (**not** this product) |
| Release tags | `v<version>` (stable), `v<version>-alpha.N` (pre-release) |
| Retired lines | `archive/<name>` tags |

`main` is the only long-lived branch. Everything else exists to carry one change
into it and is deleted when that change lands.

## Branch names

| Kind | Pattern | Example | Lifespan |
| --- | --- | --- | --- |
| Feature | `feat/<slug>` | `feat/reading-progress` | days |
| Bug fix | `fix/<slug>` | `fix/focus-streak-off-by-one` | days |
| Hardening | `fix/<area>-<date>` | `fix/local-file-policy-2026-11` | days |
| Chore / infra | `chore/<slug>` | `chore/pin-signing-action` | days |
| Tests only | `test/<slug>` | `test/engine-matrix` | days |
| Docs only | `docs/<slug>` | `docs/branch-policy` | days |
| Release prep | `release/<version>` | `release/1.0.1.0` | until the tag |
| Dependency bot | `dependabot/*` | managed by GitHub | until the PR closes |

Rules that keep it readable:

1. **A branch name never repeats the remote name.** `mei/mei/critical-…` and
   `new-main` were both symptoms of pushing a branch called `mei/...` *to* the
   remote called `mei`; the far side grew a second prefix. Use the table above.
2. **No aliases for `main`.** `new-main` was a second trunk that drifted 21
   commits behind and had to be checked by hand before every release.
3. **Lowercase, hyphenated, no dates in the slug** — the date lives in the commit
   or the PR, not in a name people have to remember.
4. **One change per branch**, squashed on merge, so `git log main` reads as a
   list of decisions rather than a list of attempts.
5. **Delete on merge.** A merged branch is noise; its commits are already in
   `main`, and anything that must survive is a tag.

## Remotes

```
origin     https://github.com/Annguyen0410/Mei.git                      (fetch/push)
mahoraga   https://github.com/Annguyen0410/MAHORAGA-ADAPT-SYSTEM-MAS-v9.0.git
```

Before the 2026-11 consolidation the names were inverted: `origin` pointed at
the unrelated MAHORAGA repository and `mei` pointed at Mei. A bare `git push`
from a checkout of this product therefore pushed to the wrong project, and the
local `main` tracked a MAHORAGA branch — which is how the checkout ended up with
a v6.4-era `main` that was 265 commits behind the real line while every release
came from a branch called `mei/main`. `origin` now means Mei, which is what every
tool, script and habit expects.

## Tags

| Tag | Meaning |
| --- | --- |
| `v1.0.1.0` | stable; this is what `releases/latest/download/update.json` may serve |
| `v1.0.1.0-alpha.2` | pre-release; must be published with `--prerelease` (see `docs/RELEASE_SIGNING.md`) |
| `archive/<name>` | a retired line kept for history — not a release, never deployed |

`publish_release.py` refuses a suffixed tag unless `--prerelease` is passed,
because a suffixed tag published as an ordinary release takes over
`releases/latest` and every installed copy is offered a test build.

## Consolidation of 2026-11-12

Every branch below was verified to be **fully contained in `main`**
(`git rev-list --count main..<ref>` → `0`), so removing it loses no commit. Each
one is also captured by an `archive/*` tag before deletion.

| Branch | Tip | State | Action |
| --- | --- | --- | --- |
| `main` | `a2a5c3d` | trunk | keep |
| `mei/critical-data-safety-fixes-2026-11` | `398e07d` | merged, 11 behind | remove (`archive/critical-data-safety-fixes-2026-11`) |
| `mei/critical-data-safety-followup-2026-11` | `1ac1082` | merged, 12 behind | remove (`archive/critical-data-safety-followup-2026-11`) |
| `mei/data-integrity-closure-2026-11` | `43e8058` | merged, 15 behind | remove (`archive/data-integrity-closure-2026-11`) |
| `new-main` | `6a86eee` | merged, 21 behind; alias of `main` | remove (`archive/new-main`) |
| `dependabot/github_actions/actions-1a08786932` | `b7dd474` | bot branch, 2026-10 | close the PR, then remove |
| `dependabot/pip/pyinstaller-6.22.3` | `426c0af` | bot branch, 2026-10 | close the PR, then remove |
| `dependabot/pip/pytest-gte-9.2.0` | `c9bc783` | bot branch, 2026-10 | close the PR, then remove |
| `dependabot/pip/python-runtime-afd19d4160` | `e46d576` | bot branch, 2026-10 | close the PR, then remove |
| `dependabot/pip/setuptools-gte-84.2.1` | `46baab3` | bot branch, 2026-10 | close the PR, then remove |

Local checkout after the consolidation: one branch (`main`, tracking
`origin/main`), five archive tags, and both remotes under their correct names.
The legacy `main` line (`a412a69`, an unrelated v6.4 history with its own
`Initial commit`) is preserved as `archive/legacy-main-v6.4.0`.

### Finishing the cleanup on GitHub

The archive tags exist locally so nothing can be lost; pushing them is what makes
the removal durable on the server:

```bash
git push origin --tags                       # makes archive/* permanent
git push origin --delete \
  mei/critical-data-safety-fixes-2026-11 \
  mei/critical-data-safety-followup-2026-11 \
  mei/data-integrity-closure-2026-11 \
  new-main
```

For the five `dependabot/*` branches, close the pull request in the UI instead of
deleting the branch: Dependabot removes its own branch when the PR closes, and a
hand-deleted branch comes straight back on the next scan.

Verify afterwards:

```bash
git ls-remote --heads origin          # one line: refs/heads/main
git branch -r                         # origin/main only, plus the bots until closed
```

## Keeping it that way

* **Protect `main`**: require a pull request, require the `tests · PyQt6` check
  (the shipped engine) and the release security gate, and disallow direct pushes.
  A green `main` is what every release tag is cut from.
* **Squash-merge**, so `main` stays a list of decisions.
* **One dependency bump per month**, grouped in a single PR: the five stale
  Dependabot branches above are what ungrouped, unattended bumps look like after
  a few weeks.
* **Cut releases only from `main`**, never from a feature branch — a tag on a
  side branch is how `v1.0.1.0-alpha.2` ended up pointing at a commit whose test
  suite failed.
