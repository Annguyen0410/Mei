# Mei — User Guide

A day-to-day walkthrough of the app. For the full command and shortcut list see
[`COMMAND_REFERENCE.md`](COMMAND_REFERENCE.md); for running/building see
[`../RUN_AND_BUILD.md`](../RUN_AND_BUILD.md).

---

## 1. The shell (first thing you see)

- **Left rail** — switches workspaces: Home, Browser, History, AI, Personal, Library, Settings. Click the «/» button (or drag the divider, or press `Ctrl+1…7`) to switch; the rail itself can be collapsed/expanded and dragged wider.
- **Top bar** — brand, the **omnibar** (search box), Snapshot / Insights buttons.
- **Bottom status strip** — theme pill, sync state, status hints.

### The omnibar is the command center

| What you type | What happens |
|---|---|
| `python.org` | Navigates to the URL |
| `best coffee recipes` | Web search with the active engine |
| `b` | **Feature finder** — a live list of matching features (workspaces, Personal pages, sites, commands). Enter/click jumps there |
| `/task Buy milk` | Runs the command (creates a task) |
| `!` then a word | (if supported by the search engine) exact web search |

**Feature finder tips**

- Works for **any letter** — `s` → Settings, Sites, Sync…; if one letter matches nothing, the whole list is shown so you can browse.
- `↑`/`↓` move through results, `Esc` closes, Enter jumps.
- Password-protected areas (**AI**, **Personal**) ask for the passcode first and then open automatically.

## 2. The study loop — one process across the whole app

Mei has one work process, and every workspace is a station on it. Home shows where you
are and what is next; the other surfaces are where the step actually happens.

| Station | What lands there | Where it lives |
|---|---|---|
| **Capture** | A clipped page (`/save-page`, page menu → highlight clipping), a note (`/note`), a quick task (`/task`) | Library, Personal → Notes, Tasks |
| **Plan** | The dated commitment: an item with a course, a deadline, a focus block | Personal → **Weekly Plan** |
| **Study** | A Café Focus pour aimed at one item/block; elapsed minutes are credited back | **▶ Study**, `/focus`, `/status` |
| **Review** | The flashcard deck's due queue (SM-2) | Personal → **Review**, `/review` |
| **Reflect** | The Morning Brief, the saved brief note, the links between everything | Home card, `/brief` → **Save as note**, note **Related** panel |

**Home “Today” is the entrance.** Under the merged agenda (planner deadlines, planner time
blocks and quick inbox rows, overdue first) there is a loop line and two buttons:

- **▶ Continue** — runs the next step of the loop. It reads every store, so the button is
always the right one: *finish your pour → study the overdue item → today's block → review the
due cards → promote the inbox row → turn the clip into cards → plan the week*. The label
always says what will happen: if it offers a pour it starts one (with the duration shown), and
if it offers to plan a task it promotes that row into the Weekly Plan and opens the plan on it.
- **→ Planner** — promotes the selected inbox row into the Weekly Plan. The task is ticked off
and both sides stay linked, so nothing is lost and the row keeps a traceable history.

**`/flow` does the same thing from the keyboard**: it lists the five stations with their live
counts and then runs the next step. If a pour is already running, `/flow` reports it instead
of starting a second one.

The loop is closed at both ends: the **Morning Brief** ends with **▶ Next step** (the same
recommendation, in the daily note you can save with one click), the **planner** answers back
with `next: 🧠 Review 3 due card(s)` once a session is credited, and the **AI index** stores
the loop as a document, so `/ask what should I do next?` answers from your real state.

---

## 3. Browser workspace

The left desk holds your **workspace tabs** (groups with color dots, speaker chips for playing tabs, hibernation state). The divider between the desk and the page can be:

- **clicked once** → collapse/expand,
- **dragged** → resize,
- **double-clicked** → toggle.

Browser features worth knowing:

- **New tab** `Ctrl+T`, **incognito** `Ctrl+Shift+N`, **reopen closed** `Ctrl+Shift+T`, **duplicate** `Ctrl+Shift+D`.
- **Split view** — “Show beside” puts two live pages side by side.
- **Web panels** — ◫ docks Telegram/WhatsApp/Discord/Spotify/… beside the page (logins persist via the shared profile).
- **Tab groups** — color-coded, fold/unfold, session-persistent.
- **Zen mode** `Ctrl+Shift+Z` hides every chrome surface for pure reading; Esc exits.
- **Tab hibernation & memory saver** — idle background tabs freeze automatically; `Ctrl+Shift+M` optimizes memory now.
- **Address bar** — the connection chip in front of the address appears on web pages only
  (🔒 Secure / ⚠ HTTP). Internal pages (`about:`) and an empty field say nothing the address
  does not already show, so the chip stays out of the way.
- **Find bar** `Ctrl+F`, **PDF save** `Ctrl+Shift+S`, **screenshot** `Ctrl+S`, **print** `Ctrl+P`, **devtools** `F12`.
- **Help & Guide** `F1` — searchable list of every feature, shortcut and slash command;
  double-click a command to run it. It is generated from the same registries the app
  dispatches on, so it never documents something that does not exist.
- **Clipboard history** `Ctrl+Shift+V` — pick one of the last 20 copied items, restore or paste & go.

## 4. Personal Hub

The left rail inside Personal has its own collapse/expand (click the «/≫ button **or the divider** — the divider also drags to resize). Pages:

- **Overview** — today at a glance, a 12-week **focus streak heatmap** (each cell = one day, months + year on top, today ringed).
- **Weekly Plan** — courses (name, code, colour, schedule, credits) plus assignments, exams, projects and tasks on a weekly board. Pick the course when adding an item or a focus block, drag items between days to reschedule, double-click a block to edit it, and press **▶ Study** to pour a focus session for the selected item — its minutes are credited back to the item. *Planner first:* anything with a date or deadline belongs here; **Tasks** stays the quick inbox, and Home's *Today* card shows both side by side.
- **Notes** — SafeVault notes with Obsidian-style `[[wiki-links]]`, categories, a neural-graph view, find/replace, export. The **Related** panel under the editor links a note to a planner item (`🔗 Link…` / **Unlink**); cards made from the note appear there too, and deleting either side cleans the link up.
- **Tasks** — quick inbox with due dates; `⇄ Make flashcard` turns selected note text into a card. For study deadlines with a date, use the **Weekly Plan** instead.
- **Review** — SM-2 spaced-repetition flashcards. Browse with `←`/`→`, grade **Again/Hard/Good/Easy**, switch **Due / All cards**, delete cards, see the counter. `/review` opens it from anywhere, and the study label on the Weekly Plan hands you here (`next: 🧠 Review …`) once a pour is credited.
- **Calendar** — events, ICS import/export.
- **Boards** — sticky idea boards with links between cards.
- **Files** — your personal root directory.
- **Sites** — your own site list. **“Add site”** keeps private links separate from browser bookmarks; **“Include bundled sites”** toggles the seeded shortcut tiles (off = only sites you added; your data is never deleted either way).

## 5. AI workspace

- Providers: **RAG local only**, **OpenRouter**, **Ollama**, **llama.cpp**.
- `/ask your question` asks with the current workspace context; the Insights panel shows what the AI is reading.
- The workspace is passcode-gated: the first time you open it you set a passcode; later opens prompt for it.

## 6. Themes & focus

- `/theme <id>` — 16 café themes; `/accent <id>` — accent presets. **Auto day/night** flips to the sibling palette at 6:00/18:00.
- **One theme, everywhere.** The dashboard charts, the tab desk, the connection chip and the
  new-tab page repaint when the theme changes (including the automatic 6:00/18:00 flip), so
  nothing is left in yesterday's colours. The "Your Week" and "Where time goes" charts sit on
  their card's own surface, so no panel ever shows a second shade of the theme behind the bars.
- **Dark web pages follow the app.** Pages are darkened while the app is in a dark palette;
  flipping **Menu → Privacy → Dark Mode on Web** stores your own choice either way.
- `/focus 25` — start a café pour; the **distraction shield** blocks social/autoplay hosts while it runs.
- `/cafe` — focus journal/controls; `/status` — timer state; 20-20-20 eye-break nudges during long pours.

## 7. Privacy & security

- **VPN / proxy** — Settings → VPN (or the shield card): status, auto-connect, PAC URLs, leak test.
- **Adblock** — filter lists, subscriptions, https-only, third-party cookie blocking.
- **Password vault** — save passwords after logins; master-passcode protected.
- **Permissions manager** — per-origin camera/mic/notifications decisions.

## 8. Sync, export & automation

- **Snapshot** (top bar) — flush local state to disk.
- **Routines** — schedule daily automations (`/routines`), e.g. a 07:30 daily plan note.
- **Page monitor** — “Monitor this page” toasts when a watched page changes.
- **Export center** `/export` — notes → Markdown zip or a themed static HTML site.
- **The loop travels with your data** — planner items, courses, time blocks, flashcards and
  the link table ride backups (zip format v4) and self-hosted sync, so a restored profile
  resumes with the same next step. Old backups (v≤3) never wipe newer study data.
- **RSS** — mini-reader (RSS2 + Atom) under the web-panel menu.

---

*Mei is its own application; shortcut tiles in Personal → Sites may link out
to separate web apps that Mei neither contains nor depends on.*