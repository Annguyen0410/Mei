"""Dialog helpers for browser and shell."""
import os

from PyQt5.QtCore import Qt, QTimer, QUrl
from PyQt5.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QInputDialog,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from litebrowser.core import prefs
from litebrowser.ui.dialogs.common import _stylesheet


def show_workspace_dialog(parent):
    from litebrowser.services import workspace_manager
    base_dir = parent.base_dir
    dialog = QDialog(parent)
    dialog.setWindowTitle("Manage Workspaces")
    dialog.setStyleSheet(_stylesheet(parent))
    layout = QVBoxLayout(dialog)
    list_widget = QListWidget()
    for w in workspace_manager.get_workspaces_list(base_dir):
        list_widget.addItem("%s (%s)" % (w["name"], w["id"]))
    layout.addWidget(list_widget)
    btn_row = QHBoxLayout()
    def add_ws():
        name, ok = QInputDialog.getText(dialog, "New workspace", "Workspace name:")
        if ok and name.strip():
            workspace_manager.add_workspace(base_dir, name.strip())
            list_widget.clear()
            for w in workspace_manager.get_workspaces_list(base_dir):
                list_widget.addItem("%s (%s)" % (w["name"], w["id"]))
            if hasattr(parent, "_refresh_workspace_combo"):
                parent._refresh_workspace_combo()
    def remove_ws():
        row = list_widget.currentRow()
        if row < 0:
            return
        wlist = workspace_manager.get_workspaces_list(base_dir)
        if row >= len(wlist):
            return
        w = wlist[row]
        if w["id"] in (workspace_manager.PRIMARY_WORKSPACE_ID, workspace_manager.SECONDARY_WORKSPACE_ID, "default"):
            QMessageBox.information(dialog, "Workspace", "Cannot delete the Default workspace.")
            return
        if QMessageBox.Yes != QMessageBox.question(dialog, "Delete?", "Delete workspace \"%s\"?" % w["name"], QMessageBox.Yes | QMessageBox.No, QMessageBox.No):
            return
        workspace_manager.remove_workspace(base_dir, w["id"])
        list_widget.takeItem(row)
        parent.current_workspace_id = workspace_manager.get_current_id(base_dir)
        if hasattr(parent, "_refresh_workspace_combo"):
            parent._refresh_workspace_combo()
        if hasattr(parent, "_apply_workspace_filter"):
            parent._apply_workspace_filter()
    btn_add = QPushButton("Add workspace")
    btn_add.clicked.connect(add_ws)
    btn_remove = QPushButton("Remove selected")
    btn_remove.clicked.connect(remove_ws)
    btn_row.addWidget(btn_add)
    btn_row.addWidget(btn_remove)
    btn_row.addStretch()
    layout.addLayout(btn_row)
    dialog.exec_()


def show_quick_switcher(parent):
    from PyQt5.QtGui import QKeySequence
    from PyQt5.QtWidgets import QShortcut
    base_dir = parent.base_dir
    dialog = QDialog(parent)
    dialog.setWindowTitle("Command Palette & Quick Switcher — Ctrl+Shift+K")
    dialog.setMinimumSize(500, 400)
    dialog.setStyleSheet(_stylesheet(parent))
    layout = QVBoxLayout(dialog)
    search_edit = QLineEdit()
    search_edit.setPlaceholderText("Search commands (⚡), tabs, bookmarks, history...")
    search_edit.setMinimumHeight(36)
    layout.addWidget(search_edit)
    list_widget = QListWidget()
    layout.addWidget(list_widget)
    results = []

    # Slash-command registry: the switcher doubles as a command palette.
    COMMANDS = (
        ("/task ", "Create a task"),
        ("/note ", "Create a note"),
        ("/board ", "Create a board"),
        ("/focus 25", "Start a café pour"),
        ("/brief", "Morning brief"),
        ("/agent summary", "Digest open tabs"),
        ("/sync", "Push + pull snapshot"),
        ("/hub", "Project Hub"),
        ("/cql", "Cục Quản Lý"),
        ("/mas", "MAS"),
        ("/bimat", "Bí Mật"),
        ("/boitoan", "Bói Toán"),
        ("/leaderboard", "World Leaderboard"),
        ("/freeze", "Freeze background tabs"),
        ("/group-tabs", "Group tabs by domain"),
        ("/save-page", "Save page to Library"),
        ("/status", "Focus timer status"),
        ("/review", "Flashcard review queue"),
        ("/routines", "Schedule daily automations"),
        ("/export", "Export notes as MD zip or HTML site"),
        ("/template daily", "Daily plan note (tasks, events, focus)"),
        ("/template weekly", "Weekly review note"),
        ("/theme", "Switch theme (e.g. /theme matcha-day)"),
        ("/accent", "Switch accent color (e.g. /accent matcha)"),
    )

    def build_results():
        q = search_edit.text().strip().lower()
        results.clear()
        list_widget.clear()
        # Commands first: typing '/' or any query matches both names and
        # descriptions, so the palette doubles as a command launcher.
        if q:
            for cmd, desc in COMMANDS:
                if q in cmd.lower() or q in desc.lower():
                    results.append(("command", None, f"{cmd} — {desc}", cmd))
        if hasattr(parent, "tab_manager") and hasattr(parent, "browsers"):
            for i in range(len(parent.browsers)):
                item = parent.tab_list.item(i) if i < parent.tab_list.count() else None
                if item and item.isHidden():
                    continue
                b = parent.browsers[i]
                title = b.title() or "Tab"
                url = b.url().toString()
                if not q or q in title.lower() or q in url.lower():
                    results.append(("tab", i, title, url))
        for bm in prefs.load_bookmarks(base_dir):
            title = bm.get("title", "") or bm.get("url", "")
            url = bm.get("url", "")
            if not q or q in title.lower() or q in url.lower():
                results.append(("bookmark", None, title, url))
        entries = prefs.load_history_entries(base_dir)
        entries.sort(key=lambda x: -x[0])
        seen = set()
        for ts, url in entries[:80]:
            if url in seen or not url.startswith("http"):
                continue
            seen.add(url)
            short = url.replace("https://", "").replace("http://", "")[:50]
            if not q or q in url.lower() or q in short.lower():
                results.append(("history", None, short, url))
        for kind, idx, title, url in results[:50]:
            if kind == "command":
                list_widget.addItem("⚡ %s" % (title[:70],))
            elif kind == "tab":
                list_widget.addItem("📑 %s" % (title[:60] or url[:40]))
            elif kind == "bookmark":
                list_widget.addItem("⭐ %s" % (title[:60] or url[:40]))
            else:
                list_widget.addItem("🕐 %s" % (title[:60] or url[:40]))
        if results:
            list_widget.setCurrentRow(0)

    def on_accept():
        row = list_widget.currentRow()
        if row < 0 or row >= len(results):
            dialog.accept()
            return
        r = results[row]
        kind, idx, title, url = r[0], r[1], r[2], r[3]
        dialog.accept()
        if kind == "command":
            # Commands that take an argument prefill the omnibar and wait for
            # the user's input; self-contained commands run immediately.
            if url.endswith(" ") or url.startswith("/agent "):
                parent.omnibar.setText(url)
                parent.omnibar.setFocus()
                parent.omnibar.setCursorPosition(len(url))
                return
            parent.omnibar.setText(url)
            parent.handle_omnibar()
            return
        if kind == "tab" and idx is not None:
            parent.tab_list.setCurrentRow(idx)
            return
        if url:
            parent.tab_manager.add_tab(QUrl(url), (title or url)[:40], is_active=True)

    # Debounce the rebuild: build_results parses the entire history file;
    # v6.4 did that on every keystroke.
    debounce = QTimer(dialog)
    debounce.setSingleShot(True)
    debounce.setInterval(200)
    debounce.timeout.connect(build_results)
    search_edit.textChanged.connect(lambda _t: debounce.start())
    list_widget.itemDoubleClicked.connect(on_accept)
    QShortcut(QKeySequence(Qt.Key_Return), dialog).activated.connect(on_accept)
    QShortcut(QKeySequence(Qt.Key_Enter), dialog).activated.connect(on_accept)
    build_results()
    search_edit.setFocus()
    dialog.exec_()


def show_routines_dialog(parent):
    """Create/remove daily routines: time + weekdays + omnibar/URL actions."""
    from litebrowser.services import routines_service

    base_dir = parent.base_dir
    dialog = QDialog(parent)
    dialog.setWindowTitle("Routines — automate your café")
    dialog.resize(600, 480)
    dialog.setStyleSheet(_stylesheet(parent))
    layout = QVBoxLayout(dialog)
    layout.addWidget(QLabel(
        "Actions starting with / run as omnibar commands (e.g. /template daily); "
        "anything URL-like opens a background tab. Days: 0=Mon .. 6=Sun."
    ))
    list_widget = QListWidget()
    layout.addWidget(list_widget, 1)

    def refresh():
        list_widget.clear()
        routines = routines_service.load_routines(base_dir)
        if not routines:
            hint = QListWidgetItem("No routines yet — add one below (e.g. 07:30 · Mon-Fri · /template daily)")
            hint.setFlags(Qt.NoItemFlags)
            list_widget.addItem(hint)
            return
        for r in routines:
            days = ",".join(str(d) for d in r["days"]) or "every day"
            mark = "☑" if r["enabled"] else "☐"
            list_widget.addItem(f"{mark} {r['time']} · {r['name']} · [{days}] · {' | '.join(r['actions'])}")
            list_widget.item(list_widget.count() - 1).setData(Qt.UserRole, r["id"])

    def add_routine():
        name, ok = QInputDialog.getText(dialog, "New routine", "Name:")
        if not ok or not name.strip():
            return
        clock, ok = QInputDialog.getText(dialog, "Time", "Fire at (HH:MM):", text="07:30")
        if not ok:
            return
        days, ok = QInputDialog.getText(dialog, "Days", "Weekdays (0=Mon..6=Sun, comma-separated, empty = daily):", text="0,1,2,3,4")
        if not ok:
            return
        actions, ok = QInputDialog.getText(dialog, "Actions", "Actions separated by | (e.g. /template daily | school.edu):")
        if not ok:
            return
        day_list = [int(d) for d in days.replace(" ", "").split(",") if d.isdigit()]
        routines_service.add_routine(base_dir, name, clock, day_list, [a.strip() for a in actions.split("|")])
        refresh()

    def remove_routine():
        item = list_widget.currentItem()
        if not item or not item.data(Qt.UserRole):
            return
        routines_service.delete_routine(base_dir, item.data(Qt.UserRole))
        refresh()

    btn_row = QHBoxLayout()
    btn_add = QPushButton("Add routine")
    btn_add.clicked.connect(add_routine)
    btn_del = QPushButton("Remove selected")
    btn_del.clicked.connect(remove_routine)
    btn_close = QPushButton("Close")
    btn_close.clicked.connect(dialog.accept)
    btn_row.addWidget(btn_add)
    btn_row.addWidget(btn_del)
    btn_row.addStretch()
    btn_row.addWidget(btn_close)
    layout.addLayout(btn_row)
    refresh()
    dialog.exec_()


def show_export_dialog(parent):
    """Export center: notes -> Markdown zip or static HTML mini-site."""
    from litebrowser.services import export_service

    base_dir = parent.base_dir
    dialog = QDialog(parent)
    dialog.setWindowTitle("Export center")
    dialog.resize(480, 240)
    dialog.setStyleSheet(_stylesheet(parent))
    layout = QVBoxLayout(dialog)
    info = QLabel(
        "Bundle your SafeVault notes to share or archive.\n"
        "Both formats include every category; HTML is styled with your theme."
    )
    info.setObjectName("MutedLabel")
    info.setWordWrap(True)
    layout.addWidget(info)
    btn_md = QPushButton("Export Markdown bundle (.zip)")
    btn_html = QPushButton("Export HTML mini-site (.zip)")
    layout.addWidget(btn_md)
    layout.addWidget(btn_html)
    row = QHBoxLayout()
    row.addStretch()
    btn_close = QPushButton("Close")
    btn_close.clicked.connect(dialog.accept)
    row.addWidget(btn_close)
    layout.addLayout(row)

    def _do(kind: str):
        default = os.path.join(base_dir, f"mei-export-{kind}-{time.strftime('%Y%m%d')}.zip")
        path, _ = QFileDialog.getSaveFileName(dialog, "Export notes", default, "Zip (*.zip)")
        if not path:
            return
        try:
            if kind == "md":
                count = export_service.export_notes_md_zip(base_dir, path)
            else:
                count = export_service.export_notes_html(base_dir, path)
        except Exception as exc:
            QMessageBox.warning(dialog, "Export", f"Export failed: {exc}")
            return
        QMessageBox.information(dialog, "Export", f"Exported {count} notes to:\n{path}")

    btn_md.clicked.connect(lambda: _do("md"))
    btn_html.clicked.connect(lambda: _do("html"))
    dialog.exec_()


def show_downloads_dialog(parent):
    from litebrowser.services import download_mgr
    base_dir = parent.base_dir
    dialog = QDialog(parent)
    dialog.setWindowTitle("Downloads")
    dialog.resize(560, 400)
    dialog.setStyleSheet(_stylesheet(parent))
    layout = QVBoxLayout(dialog)
    list_widget = QListWidget()
    layout.addWidget(list_widget)

    def _selected_download():
        row = list_widget.currentRow()
        if row < 0:
            return None
        download_id = list_widget.item(row).data(Qt.UserRole)
        for item in download_mgr.load_list(base_dir):
            if isinstance(item, dict) and item.get("id") == download_id:
                return item
        return None

    def open_file():
        entry = _selected_download()
        if entry is None:
            return
        path = entry.get("path")
        if path and os.path.exists(path):
            try:
                os.startfile(path)
            except Exception:
                QMessageBox.warning(dialog, "Error", "Could not open the file.")
        else:
            QMessageBox.information(dialog, "Downloads", "The file does not exist or the path is invalid.")

    def open_folder():
        entry = _selected_download()
        if entry is None:
            return
        path = entry.get("path")
        if path:
            folder = os.path.dirname(path)
            if os.path.isdir(folder):
                try:
                    os.startfile(folder)
                except Exception:
                    QMessageBox.warning(dialog, "Error", "Could not open the folder.")
            else:
                try:
                    os.startfile(download_mgr.get_download_dir(base_dir))
                except Exception:
                    pass

    def remove_item():
        row = list_widget.currentRow()
        if row < 0:
            return
        download_id = list_widget.item(row).data(Qt.UserRole)
        download_mgr.remove_download(base_dir, download_id)
        refresh()

    def refresh():
        list_widget.clear()
        items = download_mgr.load_list(base_dir)
        if not items:
            list_widget.addItem("No downloads yet. Files you download will appear here.")
            list_widget.setEnabled(False)
            return
        list_widget.setEnabled(True)
        for d in items:
            fname = d.get("filename", d.get("path", ""))
            status = (d.get("status") or "?").lower()
            list_widget.addItem("%s — %s" % (status.title(), fname))
            list_widget.item(list_widget.count() - 1).setData(Qt.UserRole, d.get("id"))

    def open_selected():
        open_file()

    refresh()
    list_widget.itemDoubleClicked.connect(lambda _item: open_selected())
    btn_row = QHBoxLayout()
    btn_row.addStretch()
    btn_open_file = QPushButton("Open file")
    btn_open_file.clicked.connect(open_file)
    btn_open_folder = QPushButton("Open folder")
    btn_open_folder.clicked.connect(open_folder)
    btn_remove = QPushButton("Remove from list")
    btn_remove.clicked.connect(remove_item)
    btn_row.addWidget(btn_open_file)
    btn_row.addWidget(btn_open_folder)
    btn_row.addWidget(btn_remove)
    btn_row.addStretch()
    layout.addLayout(btn_row)
    dialog.exec_()

