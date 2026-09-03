"""Hotkeys hub: a searchable reference of every shortcut Mei registers."""
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
)

from litebrowser.ui.dialogs.common import _stylesheet

# (shortcut, scope, description) — mirrors the QShortcut registrations.
HOTKEYS = (
    ("Ctrl+T", "Tabs", "Open a new tab"),
    ("Ctrl+Shift+N", "Tabs", "New incognito tab"),
    ("Ctrl+W", "Tabs", "Close current tab"),
    ("Ctrl+Shift+T", "Tabs", "Reopen last closed tab"),
    ("Ctrl+Shift+D", "Tabs", "Duplicate current tab"),
    ("Ctrl+Tab / Ctrl+PgDown", "Tabs", "Next tab"),
    ("Ctrl+Shift+Tab / Ctrl+PgUp", "Tabs", "Previous tab"),
    ("Ctrl+Shift+K", "Tabs", "Quick switcher (tabs, bookmarks, history)"),
    ("Ctrl+L", "Navigation", "Focus the address bar"),
    ("Alt+Left / Alt+Right", "Navigation", "Back / Forward"),
    ("F5 / Ctrl+R", "Navigation", "Reload page"),
    ("Ctrl+Shift+R", "Navigation", "Hard reload (bypass cache)"),
    ("Ctrl+F", "Navigation", "Find in page"),
    ("F3 / Shift+F3", "Navigation", "Find next / previous match"),
    ("F12", "Developer", "Toggle developer tools"),
    ("Ctrl+U", "Developer", "View page source"),
    ("Ctrl+Shift+E", "Capture", "Extract text from page"),
    ("Ctrl+S", "Capture", "Screenshot the visible page"),
    ("Ctrl+Shift+S", "Capture", "Save page as PDF"),
    ("Ctrl+P", "Capture", "Print page"),
    ("Ctrl+D", "Bookmark", "Bookmark current page"),
    ("Ctrl+H", "Panels", "Open history dialog"),
    ("Ctrl+J", "Panels", "Open downloads dialog"),
    ("Ctrl+Shift+B", "Shell", "Collapse / expand the toolbar"),
    ("Ctrl+Shift+F", "Shell", "Focus the tab filter"),
    ("Ctrl+Shift+M", "Shell", "Freeze background tabs now"),
    ("Ctrl+Shift+Z", "Shell", "Zen mode (hide chrome, Esc exits)"),
    ("Middle-click tab", "Mouse", "Close tab"),
    ("Double-click tab desk", "Mouse", "New tab"),
    ("Middle-click URL bar", "Mouse", "Paste & go"),
    ("Ctrl+0", "Zoom", "Reset page zoom"),
    ("Ctrl+= / Ctrl+-", "Zoom", "Zoom in / out"),
    ("Ctrl+K", "Shell", "Focus the omnibar"),
    ("Ctrl+1..7", "Shell", "Jump to workspace 1-7"),
)


def show_hotkeys_hub(parent):
    dialog = QDialog(parent)
    dialog.setWindowTitle("Hotkeys — Mei")
    dialog.resize(560, 520)
    dialog.setStyleSheet(_stylesheet(parent))
    layout = QVBoxLayout(dialog)

    search_edit = QLineEdit()
    search_edit.setPlaceholderText("Filter shortcuts...")
    layout.addWidget(search_edit)
    list_widget = QListWidget()
    layout.addWidget(list_widget, 1)

    def refresh(query=""):
        list_widget.clear()
        q = (query or "").strip().lower()
        for shortcut, scope, desc in HOTKEYS:
            hay = f"{shortcut} {scope} {desc}".lower()
            if q and q not in hay:
                continue
            row = QListWidgetItem(f"{shortcut}   ·   {desc}")
            row.setData(Qt.UserRole, scope)
            row.setToolTip(f"Scope: {scope}")
            list_widget.addItem(row)
        if list_widget.count() == 0:
            hint = QListWidgetItem("No shortcuts match.")
            hint.setFlags(Qt.NoItemFlags)
            list_widget.addItem(hint)

    search_edit.textChanged.connect(refresh)
    refresh()

    hint = QLabel("Tip: every shortcut works inside its workspace scope. Type to filter.")
    hint.setObjectName("MutedLabel")
    layout.addWidget(hint)
    row = QHBoxLayout()
    row.addStretch()
    btn_close = QPushButton("Close")
    btn_close.clicked.connect(dialog.accept)
    row.addWidget(btn_close)
    layout.addLayout(row)
    dialog.exec_()
