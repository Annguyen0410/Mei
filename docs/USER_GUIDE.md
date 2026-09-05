# MeiBrowser — User Guide

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

## 2. Browser workspace

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
- **Find bar** `Ctrl+F`, **PDF save** `Ctrl+Shift+S`, **screenshot** `Ctrl+S`, **print** `Ctrl+P`, **devtools** `F12`.
- **Clipboard history** `Ctrl+Shift+V` — pick one of the last 20 copied items, restore or paste & go.

## 3. Personal Hub

The left rail inside Personal has its own collapse/expand (click the «/≫ button **or the divider** — the divider also drags to resize). Pages:

- **Overview** — today at a glance, a 12-week **focus streak heatmap** (each cell = one day, months + year on top, today ringed).
- **Notes** — SafeVault notes with Obsidian-style `[[wiki-links]]`, categories, a neural-graph view, find/replace, export.
- **Tasks** — task list with due dates; `⇄ Make flashcard` turns selected note text into a card.
- **Review** — SM-2 spaced-repetition flashcards. Browse with `←`/`→`, grade **Again/Hard/Good/Easy**, switch **Due / All cards**, delete cards, see the counter. `/review` opens it from anywhere.
- **Calendar** — events, ICS import/export.
- **Boards** — sticky idea boards with links between cards.
- **Files** — your personal root directory.
- **Sites** — your own site list. **“Add site”** keeps private links separate from browser bookmarks; **“Include bundled sites”** toggles the seeded shortcut tiles (off = only sites you added; your data is never deleted either way).

## 4. AI workspace

- Providers: **RAG local only**, **OpenRouter**, **Ollama**, **llama.cpp**.
- `/ask your question` asks with the current workspace context; the Insights panel shows what the AI is reading.
- The workspace is passcode-gated: the first time you open it you set a passcode; later opens prompt for it.

## 5. Themes & focus

- `/theme <id>` — 16 café themes; `/accent <id>` — accent presets. **Auto day/night** flips to the sibling palette at 6:00/18:00.
- `/focus 25` — start a café pour; the **distraction shield** blocks social/autoplay hosts while it runs.
- `/cafe` — focus journal/controls; `/status` — timer state; 20-20-20 eye-break nudges during long pours.

## 6. Privacy & security

- **VPN / proxy** — Settings → VPN (or the shield card): status, auto-connect, PAC URLs, leak test.
- **Adblock** — filter lists, subscriptions, https-only, third-party cookie blocking.
- **Password vault** — save passwords after logins; master-passcode protected.
- **Permissions manager** — per-origin camera/mic/notifications decisions.

## 7. Sync, export & automation

- **Snapshot** (top bar) — flush local state to disk.
- **Routines** — schedule daily automations (`/routines`), e.g. a 07:30 daily plan note.
- **Page monitor** — “Monitor this page” toasts when a watched page changes.
- **Export center** `/export` — notes → Markdown zip or a themed static HTML site.
- **RSS** — mini-reader (RSS2 + Atom) under the web-panel menu.

---

*MeiBrowser is its own application; shortcut tiles in Personal → Sites may link out
to separate web apps that MeiBrowser neither contains nor depends on.*