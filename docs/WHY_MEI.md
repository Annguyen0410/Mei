# Why Mei — structure, and what it does that browsers and planner apps don't

This is the honest version. Mei is not a bigger Chrome and not a prettier Todoist; it is a
different **unit of design**: instead of one feature per app window, Mei has one *process* —
capture → plan → study → review → reflect — and every workspace is a station on it.

Companion docs: [`../ARCHITECTURE.md`](../ARCHITECTURE.md) (layers and extension points),
[`CAPABILITIES.md`](CAPABILITIES.md) (what is wired vs. deliberately parked),
[`USER_GUIDE.md`](USER_GUIDE.md#2-the-study-loop--one-process-across-the-whole-app).

---

## 1. The structure, in one page

```text
                       ┌──────────── one process ────────────┐
   browser ──clip──▶ notes ──cards──▶ review ──grades──▶ deck stats
      │                │                 ▲                      │
      │                ├──link──▶ planner item ──▶ study session ──credited minutes──┘
      │                │                 │                │
      └──search/ask────┴── brief ──▶ Home "next step" ◀───┘  (study_flow)
```

- **One profile, one directory.** Tabs, history, cookies, notes, planner, cards, links and the
  pour journal all live under `runtime_data/profiles/<Name>/`. There is no account, no server
  round-trip, and no cross-app permission model to negotiate.
- **Layers, enforced.** `core/` → `services/` (pure data, never imports Qt widgets) →
  `browser/` → `ui/`. `tests/test_architecture_boundaries.py` fails the build on a back-edge,
  an orphan module or a stale allowlist entry.
- **Data layer is the product.** The interesting logic is in `services/`: `personal_plan`
  (weekly plan, store v2), `study_session` (pour from a planner row, credit minutes once),
  `flashcard_service` (compact SM-2), `link_service` (one typed edge table for every entity
  type), `life_service` (agenda + universal search), `brief_service`, `ai_service`/`retriever`
  (BM25 + optional embeddings), `sync_service` (self-hosted bundle), `history_service`
  (versioned backup, zip format v4).
- **`study_flow.py` is the glue added last.** It stores nothing. It reads the agenda, the deck,
  the captures, the pour journal and the link table, then answers one question — *what do I do
  next?* — with one action that Home, `/flow`, the Morning Brief and the planner all render.
  A recommendation that four surfaces share cannot drift the way four separate "suggestions"
  would.
- **Stores are versioned, migrations are registered.** `core/store.py` + `core/migrations.py`;
  a new field is a numbered step, not a best-effort `setdefault`.
- **Five cross-cutting planes.** Every study store travels through backup/import, self-hosted
  sync, the AI index, library search, and the Morning Brief. Adding a source is one
  `SYNC_ENTITIES` entry plus one row here — the planes are the contract.
- **Two gates keep it honest.** `test_capability_ledger.py` deletes-by-default: public API
  either has a caller or is listed in `CAPABILITIES.md` with a test. `test_command_registry.py`
  generates the omnibar autocomplete, the hint line, the palette, the in-app guide and the
  command docs from one tuple. Nothing is documented that is not dispatched.

## 2. Against browsers (Chrome, Edge, Firefox, Brave, Arc, Vivaldi, Opera GX)

| | Typical browser | Mei |
|---|---|---|
| What it organizes | Tabs, bookmarks, history | Tabs **plus** deadlines, courses, cards, links — the same profile |
| Clipping a page | Read-later list, maybe an account | Saved page → note → flashcard → linked to the planner item it belongs to |
| Time | "You spent 3h on youtube.com" | A pour per item, credited to that item, honest about elapsed-vs-planned minutes |
| Accounts | Required for sync/collections | None. Sync is *your* endpoint; backup is a file you own |
| Extension model | Store + broad permissions | Bundled workspace apps + user scripts with match patterns; narrower surface |
| Arc-style "spaces" | Group tabs | Pair the group with a commitment: today's blocks, what's due, what's overdue |

The claim is not that Mei is a better browser at browsing. Chromium renders the same. The claim
is that **the browser knows things no other browser can act on**: it knows you clipped a page
about BFS/DFS, that the exam is on Thursday, that the card is due, and that you already poured
25 minutes into that item — so it can hand you the next step instead of a fourth tab.

## 3. Against planner apps (Todoist, TickTick, Notion, Google Tasks/Calendar, Forest)

| | Typical planner | Mei |
|---|---|---|
| Source of material | You type it in | You type it **or** clip it while reading, with the URL preserved |
| Recall | A checkbox | The same item can carry cards, and its minutes are counted |
| Where the work happens | Somewhere else (an app you switch to) | The app you were reading in |
| Pricing / account | Subscription, account, servers | Local files, no account, MIT-style ownership of the data |
| Migration story | Export if the vendor allows | Versioned stores + registered migrations, readable JSON, zip v4 backup |
| Mixed inbox vs. plan | One flat list, guilt | Two honest systems: planner = anything with a date, Tasks = quick inbox, promoted with one click and linked both ways |

Most planners stop at "what should I do?" Mei adds "…and here is the material, the timer, the
recall queue and the reflection note for it", because all four are the same profile.

## 4. Against study apps (Anki, Quizlet, Notion templates, Forest)

| | Anki / Quizlet | Forest | Mei |
|---|---|---|---|
| Scheduling | Best-in-class (Anki) | n/a | Compact SM-2 with clamped ease, intervals floor at 1 day, 10-min retries |
| Source of cards | Hand-built decks | n/a | Clipped pages and notes become cards; the card links back to its note |
| Tie to the plan | None | A tree | The pour is *for* an item: the item's `studied_minutes` grows, the label points at the deck |
| Honesty rules | n/a | n/a | Whole elapsed minutes, capped by the planned duration, credited exactly once (`credited` flag + journal); abandoned pours credit nothing |
| Reflection | n/a | Streak | Morning Brief with a Next-step line, savable as a Markdown note |

Anki still wins on deck ecosystems and algorithm research, and Forest still wins on pure
gamification. Mei wins on **closure**: the same session that schedules the card also credits
the planner item and writes the line the brief reports tomorrow — no copy-paste, no plugin.

## 5. Against knowledge tools (Obsidian, Logseq, Notion)

- Notes are plain Markdown in a folder with `[[wiki-links]]`, autocomplete, backlinks and a
  graph — plus **typed entity links** (`entity_links.json`) that Obsidian only gets from
  plugins: note ↔ planner item ↔ card ↔ block ↔ course ↔ saved page ↔ board node, one edge
  table, cascade on delete, carried by backup and sync.
- Deleting a note removes its cards and its edges; deleting a card keeps the note. The graph
  cannot rot into dangling references.

## 6. Where Mei is genuinely weaker (so you can weigh it)

- **Engine lineage.** Chromium parity is whatever `PyQt5/PyQt6-WebEngine` ships
  (118–122 class), not current stable. New web platform features arrive late.
- **Ecosystem.** No Chrome Web Store, no mobile app, no team/collab features.
- **Single profile, single machine.** Self-hosted sync exists and merges sanely, but it is
  one-way-at-a-time snapshot sync, not real-time multi-device CRDT.
- **Distribution.** Built and shipped as a PyInstaller `--onefile` exe by hand; no signed
  auto-update channel beyond the local `update/` folder.
- **GUI test coverage.** Service-layer tests are extensive and headless; GUI tests are
  offscreen smoke tests on Windows. A real cross-platform UI regression suite is future work.

## 7. What this buys, in one sentence each

1. **One recommendation, four surfaces.** Home, `/flow`, the brief and the planner read the
   same function; they cannot disagree about what is next.
2. **The loop closes with real numbers.** A pour credits the item it was for, once, and that
   shows up in the brief, the AI index and every backup.
3. **Nothing is trapped.** Plain JSON + Markdown, versioned, self-hosted sync, no account.
4. **Zero cloud, zero subscription, zero telemetry** — and the app is still a full browser.
5. **The design is enforced, not aspirational.** Layer boundaries, the capability ledger, the
   command registry and the store-migration tests turn each promise into a failing build if it
   ever stops being true.

### Files that keep it true

| Promise | Gate |
|---|---|
| Layers stay clean, no orphan modules | `tests/test_architecture_boundaries.py` |
| No dead public API, reserved code is documented | `tests/test_capability_ledger.py`, `tests/test_reserved_api.py` |
| Commands are registered, dispatched and documented | `tests/test_command_registry.py`, `tests/test_help_guide.py` |
| Stores migrate instead of silently resetting | `tests/test_store_migrations.py`, `tests/test_profile_storage_safety.py` |
| The loop's ladder and counters | `tests/test_study_flow.py` |
| The loop across backup / sync / AI / brief / cascades | `tests/test_study_flow_surfaces.py` |
| The loop's desktop wiring | `tests/test_study_loop_ui.py` |
| Minutes are credited once, and only from a real pour | `tests/test_study_session_service.py`, `tests/test_study_session.py` |
