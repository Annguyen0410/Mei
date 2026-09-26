"""Help, control center, and modern guide dialogs.

One surface answers three questions: *what can this app do*, *where is it*, and
*what is the shortcut*. The reference half is generated from the registries the
app actually dispatches on — ``core/commands.py`` and this module's shortcut
table — so the guide cannot advertise a command that does not exist, and a new
command or shortcut shows up here for free.

F1 opens it; every shell also lists it in its menus.
"""
from typing import NamedTuple

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from litebrowser.core import commands as command_registry
from litebrowser.ui.dialogs.common import _stylesheet
from litebrowser.ui.dialogs.hotkeys import HOTKEYS
from litebrowser.ui.dialogs.navigation import (
    show_workspace_dialog,
)
from litebrowser.ui.dialogs.profiles_privacy import (
    show_privacy_dialog,
    show_profiles_dialog,
    show_save_password_dialog,
)
from litebrowser.ui.dialogs.sessions import (
    show_hibernate_pref_dialog,
    show_startup_dialog,
    show_vpn_dialog,
)
from litebrowser.ui.dialogs.vpn_hub import show_vpn_hub

# The marquee features, written the way a new user asks for them. Keep one line
# each: this is the part of the guide that is curated rather than generated.
GUIDE_FEATURES = (
    ("Two windows, seven workspaces", "Workspace 1 is browsing, Workspace 2 is your personal side. Ctrl+1..7 jumps between workspaces inside a window."),
    ("Command palette", "Ctrl+K searches tabs, bookmarks, history and every slash command. Fastest way to reach anything by name."),
    ("Omnibar commands", "Type / in the address bar: /task, /note, /focus 25, /brief, /theme matcha, /group-tabs, /help — hints appear as you type."),
    ("Web panels", "The ◫ button docks Telegram, WhatsApp, Discord or Spotify beside the page instead of in another window."),
    ("Zen mode", "Ctrl+Shift+Z hides every bar for reading; Esc brings them back."),
    ("Reading list & Library", "Page menu > Save to reading list keeps long articles; Library collects saved pages, notes and exports."),
    ("Personal Hub", "Notes, tasks, calendar, flashcards and the vault — one window, opened from the rail or /personal."),
    ("AI assistant", "The AI button asks about the current page or your notes; local Ollama and OpenRouter are both supported."),
    ("Capture", "Ctrl+S screenshots the visible page, Ctrl+Shift+S saves a PDF, Ctrl+Shift+E extracts the page text."),
    ("Privacy", "VPN hub, per-site permissions, cookie policy, profiles and the password vault all live under Control > Privacy."),
    ("Tab memory control", "Ctrl+Shift+M freezes background tabs (or open tabs) so a heavy session stays responsive."),
    ("Clipboard history", "Ctrl+Shift+V reopens the last 20 things you copied, in the browser window."),
    ("Cross-device sync", "/sync pushes and pulls a snapshot from your own server; nothing is sent anywhere else."),
    ("Auto theme", "Settings can follow the clock: the shell re-tints itself between day and night palettes."),
)

FEATURE_GROUP = "Feature"
SHORTCUT_GROUP = "Shortcut"
COMMAND_GROUP = "Command"


class GuideEntry(NamedTuple):
    """One searchable row of the guide."""

    group: str
    label: str
    detail: str
    command: str = ""

    def haystack(self) -> str:
        return f"{self.group} {self.label} {self.detail} {self.command}".lower()


def guide_entries() -> tuple[GuideEntry, ...]:
    """Every row the guide can show, in reading order.

    Generated from the same tables the app dispatches on, so the guide and the
    app cannot drift apart (the tool cards below are the curated part).
    """
    entries: list[GuideEntry] = []
    for title, detail in GUIDE_FEATURES:
        entries.append(GuideEntry(FEATURE_GROUP, title, detail))
    for shortcut, scope, description in HOTKEYS:
        entries.append(GuideEntry(SHORTCUT_GROUP, shortcut, f"{scope} — {description}"))
    for command in command_registry.COMMANDS:
        entries.append(
            GuideEntry(
                COMMAND_GROUP,
                command.completion().strip(),
                command.hint(),
                command=command.completion().strip(),
            )
        )
    return tuple(entries)


def filter_entries(entries, query: str):
    """Rows matching ``query`` (case-insensitive, all words must match)."""
    words = [word for word in (query or "").lower().split() if word]
    if not words:
        return tuple(entries)
    return tuple(entry for entry in entries if all(word in entry.haystack() for word in words))


def run_or_copy_command(parent, command: str, flash=None) -> str:
    """Run ``command`` through the shell when possible, else copy it.

    Returns ``"ran"`` or ``"copied"`` so callers (and tests) know what happened:
    a command needs the shell's dispatcher, and copying is the honest fallback
    when the guide was opened from a surface that has none.
    """
    handler = getattr(parent, "_handle_omnibar_text", None)
    if callable(handler) and command.startswith("/"):
        try:
            handler(command)
            return "ran"
        except Exception:
            # A dispatcher that refuses this command (needs an argument, gate
            # locked) is not a reason to lose it — fall through to the copy path.
            pass
    from PyQt5.QtWidgets import QApplication

    QApplication.clipboard().setText(command)
    if callable(flash):
        flash(f"Copied {command} — paste it in the omnibar (Ctrl+K)")
    return "copied"


def show_browser_control_center(parent):
    dialog = QDialog(parent)
    dialog.setWindowTitle("Help & Guide")
    dialog.resize(880, 620)
    dialog.setStyleSheet(_stylesheet(parent))
    layout = QVBoxLayout(dialog)
    layout.setContentsMargins(18, 18, 18, 18)
    layout.setSpacing(12)

    title = QLabel("Help & Guide")
    title.setStyleSheet("font-size: 20px; font-weight: 700;")
    title.setWordWrap(True)
    layout.addWidget(title)

    subtitle = QLabel(
        "Search a feature, a shortcut or a command — or jump straight into a tool below. "
        "Double-click a command to run it."
    )
    subtitle.setWordWrap(True)
    subtitle.setObjectName("MutedLabel")
    layout.addWidget(subtitle)

    search = QLineEdit()
    search.setPlaceholderText("Search: zen, screenshot, /task, Ctrl+K ...")
    search.setClearButtonEnabled(True)
    layout.addWidget(search)

    entries = guide_entries()

    reference = QListWidget()
    reference.setObjectName("TabList")
    reference.setAlternatingRowColors(False)
    layout.addWidget(reference, 1)

    grid_host = QWidget()
    grid = QGridLayout(grid_host)
    grid.setHorizontalSpacing(12)
    grid.setVerticalSpacing(12)

    cards = [
        ("Sessions & Spaces", "Workspace, startup, profiles, save current tab set", [
            ("Workspace", lambda: show_workspace_dialog(parent)),
            ("Startup", lambda: show_startup_dialog(parent)),
            ("Profiles", lambda: show_profiles_dialog(parent, getattr(parent, "app_dir", parent.base_dir))),
            ("Save current tabs", parent.save_current_tab_set),
        ]),
        ("Privacy & Performance", "Privacy, cookies, hibernate, proxy, passwords", [
            ("Privacy center", lambda: show_privacy_dialog(parent)),
            ("Hibernate timer", lambda: show_hibernate_pref_dialog(parent)),
            ("VPN hub (one-click)", lambda: show_vpn_hub(parent)),
            ("VPN / Proxy (form)", lambda: show_vpn_dialog(parent)),
            ("Save password", lambda: show_save_password_dialog(parent)),
        ]),
        ("Capture & Reading", "Screenshot, text extract, print, PDF, reader mode", [
            ("Screenshot", parent.capture_screenshot),
            ("Extract text", parent.extract_text),
            ("Print page", parent.print_page),
            ("Save PDF", parent.save_page_pdf),
            ("Save page to library", parent.save_current_page_to_library),
            ("Create note from page", parent.capture_page_as_note),
        ]),
        ("Library & Tools", "Bookmarks, history, downloads, extensions, vault", [
            ("Bookmarks", parent.show_bookmarks_dialog),
            ("History", parent.show_history_dialog),
            ("Downloads", parent.show_downloads_dialog),
            ("Extensions", parent.show_extensions_dialog),
            ("Safe vault", parent.show_vault),
            (
                "Management Center (web page)",
                lambda: getattr(parent, "open_cuc_quan_ly_support_page", lambda: None)(),
            ),
        ]),
    ]

    for index, (heading, desc, actions) in enumerate(cards):
        card = QFrame()
        card.setObjectName("SectionCard")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(14, 14, 14, 14)
        card_layout.setSpacing(8)
        lbl = QLabel(heading)
        lbl.setStyleSheet("font-size: 15px; font-weight: 700;")
        lbl.setWordWrap(True)
        card_layout.addWidget(lbl)
        body = QLabel(desc)
        body.setObjectName("MutedLabel")
        body.setWordWrap(True)
        card_layout.addWidget(body)
        for text, fn in actions:
            button = QPushButton(text)
            button.clicked.connect(lambda checked=False, cb=fn: [cb(), dialog.accept()])
            card_layout.addWidget(button)
        grid.addWidget(card, index // 2, index % 2)

    tools_header = QLabel("Tools")
    tools_header.setObjectName("SectionTitle")
    layout.addWidget(tools_header)
    layout.addWidget(grid_host, 1)

    def flash(message: str) -> None:
        # The status strip lives on the shell; a dialog without one still works.
        emit = getattr(parent, "_flash_status", None)
        if callable(emit):
            emit(message)

    def refill(query: str = "") -> None:
        reference.clear()
        matches = filter_entries(entries, query)
        if not matches:
            item = QListWidgetItem("Nothing matches that. Try “zen”, “/theme”, or clear the box.")
            item.setFlags(Qt.ItemIsEnabled)
            reference.addItem(item)
            return
        for entry in matches:
            row = QListWidgetItem(
                f"{entry.group}   ·   {entry.label}\n{entry.detail}" if entry.detail else entry.label
            )
            row.setData(Qt.UserRole, entry)
            if entry.command:
                row.setToolTip("Double-click to run this command")
            reference.addItem(row)

    def on_double_click(item) -> None:
        entry = item.data(Qt.UserRole)
        if isinstance(entry, GuideEntry) and entry.command:
            run_or_copy_command(parent, entry.command, flash)

    def on_search(text: str) -> None:
        searching = bool((text or "").strip())
        # While searching, the reference is the whole surface — two competing
        # lists on screen at once is what made the old help panel hard to read.
        grid_host.setVisible(not searching)
        tools_header.setVisible(not searching)
        refill(text)

    search.textChanged.connect(on_search)
    reference.itemDoubleClicked.connect(on_double_click)
    refill()

    footer = QHBoxLayout()
    hint = QLabel("Tip: F1 opens this guide from anywhere. Ctrl+K searches everything.")
    hint.setObjectName("MutedLabel")
    hint.setWordWrap(True)
    footer.addWidget(hint, 1)
    close_btn = QPushButton("Close")
    close_btn.clicked.connect(dialog.accept)
    footer.addWidget(close_btn)
    layout.addLayout(footer)

    search.setFocus()
    dialog.exec_()
