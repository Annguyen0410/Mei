"""Shell command palette: search every app feature and jump straight to it.

Typing filters workspaces, Personal sub-pages, the bundled/remote sites and
every slash command by name — ``b`` surfaces Browser, Bí Mật, Bói Toán,
Boards, ... Enter (or a click) executes the highlighted row through the
shell's own dispatch, so password-protected workspaces (AI / Personal)
prompt for the passcode first and then enter automatically.
"""
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QKeySequence
from PyQt5.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QShortcut,
    QVBoxLayout,
    QWidget,
)

from litebrowser.core import app_paths, prefs
from litebrowser.core.commands import COMMANDS
from litebrowser.ui.dialogs.common import _stylesheet

_WORKSPACES = (
    ("home", "Home", "🏠"),
    ("browser", "Browser", "🌐"),
    ("history", "History", "🕐"),
    ("ai", "AI Assistant", "✨"),
    ("personal", "Personal Hub", "◧"),
    ("library", "Library", "📚"),
    ("settings", "Settings", "⚙"),
)

_PERSONAL_PAGES = (
    ("overview", "Overview", "◧"),
    ("notes", "Notes", "✎"),
    ("tasks", "Tasks", "✓"),
    ("review", "Review", "⇄"),
    ("calendar", "Calendar", "◷"),
    ("boards", "Boards", "◌"),
    ("files", "Files", "▦"),
    ("sites", "Sites", "↗"),
)


def _build_entries(parent) -> list[dict]:
    """The single feature registry behind the palette AND the omnibar popup.

    Each entry is a dict the shell dispatches on:
      kind      -> workspace | personal_page | site | hub | command
      payload   -> workspace key, page key, site key, or slash command text
      title/…   -> what the user sees and searches
    Because both UIs read from here, the omnibar and the palette can never
    drift out of sync.
    """
    entries: list[dict] = []
    for key, label, glyph in _WORKSPACES:
        entries.append(
            {
                "title": label,
                "category": "Workspace",
                "keywords": label.lower(),
                "glyph": glyph,
                "kind": "workspace",
                "payload": key,
            }
        )
    for key, label, glyph in _PERSONAL_PAGES:
        entries.append(
            {
                "title": "Personal · %s" % label,
                "category": "Personal page",
                "keywords": "personal %s %s" % (label.lower(), key),
                "glyph": glyph,
                "kind": "personal_page",
                "payload": key,
            }
        )
    seen = set()
    for site in app_paths.bundled_sites(getattr(parent, "app_dir", None)) + app_paths.chain_remote_sites(
        getattr(parent, "app_dir", None)
    ):
        key = site.get("key") or ""
        if not key or key in seen:
            continue
        seen.add(key)
        entries.append(
            {
                "title": site.get("display") or key,
                "category": "Open site",
                "keywords": " ".join(
                    str(part).lower()
                    for part in (site.get("display"), site.get("subtitle"), key)
                    if part
                ),
                "glyph": site.get("glyph", "↗"),
                "kind": "site",
                "payload": key,
            }
        )
    entries.append(
        {
            "title": "Project Hub",
            "category": "Open site",
            "keywords": "project hub chain apps portal",
            "glyph": "☰",
            "kind": "hub",
            "payload": None,
        }
    )
    for cmd, takes_arg, desc in COMMANDS:
        entries.append(
            {
                "title": cmd,
                "category": desc,
                "keywords": "%s %s" % (cmd, desc),
                "glyph": "⚡",
                "kind": "command",
                "payload": cmd + (" " if takes_arg else ""),
            }
        )
    return entries


def _base_dir(parent) -> str:
    return getattr(parent, "profile_dir", None) or getattr(parent, "base_dir", None) or ""


def _entry_haystack(entry: dict) -> str:
    return "%s %s %s" % (
        entry["title"].lower(),
        entry.get("category", "").lower(),
        entry.get("keywords", ""),
    )


def filter_feature_entries(entries: list, q: str) -> list:
    """Feature rows matching ``q`` (case-insensitive substring over title +
    category + keywords). Any single letter must surface something: when a
    one-character query matches nothing, the whole registry is shown so the
    user can browse and keep typing to zoom in."""
    q = (q or "").strip().lower()
    rows = [e for e in entries if q in _entry_haystack(e)]
    if not rows and len(q) <= 1:
        rows = list(entries)
    return rows


def feature_row_widget(entry: dict, base: str) -> QWidget:
    """The glyph + title + category row used by the palette dialog AND the
    omnibar feature popup (kept in one place so both look identical)."""
    from litebrowser.ui import theme

    row = QWidget()
    row_layout = QHBoxLayout(row)
    row_layout.setContentsMargins(8, 3, 8, 3)
    row_layout.setSpacing(8)
    glyph = QLabel(entry.get("glyph", "◆"))
    glyph.setStyleSheet("font-size:15px;")
    row_layout.addWidget(glyph)
    title = QLabel(entry["title"])
    title.setStyleSheet("font-size:13px; font-weight:600;")
    row_layout.addWidget(title)
    row_layout.addStretch(1)
    category = QLabel(entry.get("category", ""))
    muted = theme.palette_tokens(prefs.get_shell_theme(base), prefs.get_accent(base))["TEXT_MUTED"]
    category.setStyleSheet("color:%s; font-size:11px;" % muted)
    row_layout.addWidget(category)
    return row


def add_feature_row(list_widget: QListWidget, entry: dict, base: str) -> QListWidgetItem:
    """Append one feature row to ``list_widget`` and return its item."""
    item = QListWidgetItem()
    row = feature_row_widget(entry, base)
    item.setSizeHint(row.sizeHint())
    list_widget.addItem(item)
    list_widget.setItemWidget(item, row)
    return item


def clear_feature_rows(list_widget: QListWidget) -> None:
    """Remove all rows, disposing their item widgets (safe to call repeatedly)."""
    while list_widget.count():
        item = list_widget.takeItem(0)
        widget = list_widget.itemWidget(item)
        if widget is not None:
            list_widget.removeItemWidget(item)
            widget.deleteLater()
        del item


def show_shell_palette(parent) -> None:
    """Open the modal feature-finder; ``parent`` must expose
    ``_dialog_stylesheet()`` and ``_execute_shell_palette(entry)``."""
    base = _base_dir(parent)
    entries = _build_entries(parent)
    dialog = QDialog(parent)
    dialog.setWindowTitle("Search features — Mei")
    dialog.setWindowModality(Qt.WindowModal)
    dialog.setMinimumSize(560, 460)
    dialog.setStyleSheet(_stylesheet(parent))

    layout = QVBoxLayout(dialog)
    layout.setContentsMargins(10, 10, 10, 10)
    layout.setSpacing(6)

    search = QLineEdit()
    search.setPlaceholderText("Search features — e.g.  b  → Browser, Bí Mật, Bói Toán, Boards …")
    search.setMinimumHeight(34)
    layout.addWidget(search)

    list_widget = QListWidget()
    list_widget.setObjectName("CafeList")
    list_widget.setUniformItemSizes(True)
    layout.addWidget(list_widget, 1)

    state = {"rows": []}  # [(entry, QListWidgetItem)]

    def _rebuild():
        q = search.text().strip().lower()
        clear_feature_rows(list_widget)
        state["rows"] = []
        for entry in filter_feature_entries(entries, q):
            state["rows"].append((entry, add_feature_row(list_widget, entry, base)))
        if state["rows"]:
            list_widget.setCurrentRow(0)

    def _execute():
        row = list_widget.currentRow()
        if row < 0 or row >= len(state["rows"]):
            dialog.accept()
            return
        entry = state["rows"][row][0]
        dialog.accept()
        parent._execute_shell_palette(entry)

    search.textChanged.connect(_rebuild)
    list_widget.itemDoubleClicked.connect(lambda _i: _execute())
    QShortcut(QKeySequence(Qt.Key_Return), dialog).activated.connect(_execute)
    QShortcut(QKeySequence(Qt.Key_Enter), dialog).activated.connect(_execute)
    QShortcut(QKeySequence(Qt.Key_Escape), dialog).activated.connect(dialog.reject)
    _rebuild()
    search.setFocus()
    dialog.exec_()