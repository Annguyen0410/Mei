"""Dialog helpers for browser and shell."""
import json
import os
import re
import shutil
import time

from PyQt5.QtCore import Qt, QUrl
from PyQt5.QtGui import QDesktopServices
from PyQt5.QtNetwork import QNetworkProxy
from PyQt5.QtWidgets import (
    QComboBox,
    QDialog,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from litebrowser.core import prefs, time_utils
from litebrowser.services import tab_sets
from litebrowser.ui.dialogs.common import _stylesheet


def show_vpn_dialog(parent):
    base_dir = parent.base_dir
    dialog = QDialog(parent)
    dialog.setWindowTitle("VPN / Proxy")
    dialog.setGeometry(parent.x() + 200, parent.y() + 150, 420, 320)
    dialog.setStyleSheet(_stylesheet(parent))
    layout = QVBoxLayout(dialog)
    layout.setAlignment(Qt.AlignCenter)
    form = QWidget()
    form_layout = QGridLayout(form)
    form_layout.setSpacing(12)
    lbl_type = QLabel("Type:")
    type_combo = QComboBox()
    type_combo.addItems(["HTTP", "SOCKS5"])
    form_layout.addWidget(lbl_type, 0, 0)
    form_layout.addWidget(type_combo, 0, 1)
    lbl_host = QLabel("Host:")
    host_input = QLineEdit()
    host_input.setPlaceholderText("127.0.0.1")
    form_layout.addWidget(lbl_host, 1, 0)
    form_layout.addWidget(host_input, 1, 1)
    lbl_port = QLabel("Port:")
    port_input = QLineEdit()
    port_input.setPlaceholderText("1080")
    form_layout.addWidget(lbl_port, 2, 0)
    form_layout.addWidget(port_input, 2, 1)
    lbl_user = QLabel("User (optional):")
    user_input = QLineEdit()
    user_input.setPlaceholderText("Leave blank if not needed")
    form_layout.addWidget(lbl_user, 3, 0)
    form_layout.addWidget(user_input, 3, 1)
    lbl_pass = QLabel("Password (optional):")
    pass_input = QLineEdit()
    pass_input.setPlaceholderText("Leave blank if not needed")
    pass_input.setEchoMode(QLineEdit.Password)
    form_layout.addWidget(lbl_pass, 4, 0)
    form_layout.addWidget(pass_input, 4, 1)
    lbl_pac = QLabel("PAC URL (optional):")
    pac_input = QLineEdit()
    pac_input.setPlaceholderText("https://example.com/proxy.pac — overrides host/port")
    form_layout.addWidget(lbl_pac, 5, 0)
    form_layout.addWidget(pac_input, 5, 1)
    layout.addWidget(form, alignment=Qt.AlignCenter)
    _cfg = prefs.get_proxy_config(base_dir)
    if _cfg:
        type_combo.setCurrentIndex(1 if str(_cfg.get("type", "")).upper() == "SOCKS5" else 0)
        host_input.setText(str(_cfg.get("host", "")))
        port_input.setText(str(_cfg.get("port", "")))
        user_input.setText(str(_cfg.get("user") or ""))
        pass_input.setText(str(_cfg.get("password") or ""))
        pac_input.setText(str(_cfg.get("pac_url") or ""))
    btn_row = QHBoxLayout()
    btn_row.setSpacing(12)
    btn_apply = QPushButton("Enable Proxy")
    btn_off = QPushButton("Disable Proxy")
    btn_cancel = QPushButton("Cancel")
    btn_apply.clicked.connect(lambda: dialog.done(1))
    btn_off.clicked.connect(lambda: dialog.done(2))
    btn_cancel.clicked.connect(lambda: dialog.done(0))
    btn_row.addStretch()
    btn_row.addWidget(btn_apply)
    btn_row.addWidget(btn_off)
    btn_row.addWidget(btn_cancel)
    btn_row.addStretch()
    layout.addLayout(btn_row)
    result = dialog.exec_()
    host = host_input.text().strip()
    port = port_input.text().strip()
    if result == 1:
        if not host:
            QMessageBox.warning(parent, "VPN / Proxy", "Please enter a proxy host.")
            return
        if not port.isdigit():
            QMessageBox.warning(parent, "VPN / Proxy", "Port must be an integer (1–65535).")
            return
        port_n = int(port)
        if port_n < 1 or port_n > 65535:
            QMessageBox.warning(parent, "VPN / Proxy", "Invalid port.")
            return
        # Normalize: HttpProxy only accepts "http", not "HTTP" from the combo; after .lower() -> "http" is fine; SOCKS5 -> "socks5"
        raw_type = type_combo.currentText().strip().upper()
        norm_type = "socks5" if raw_type.startswith("SOCKS") else "http"
        cfg = {
            "enabled": True,
            "type": norm_type,
            "host": host,
            "port": port_n,
            "user": user_input.text().strip() or None,
            "password": pass_input.text().strip() or None,
            "pac_url": pac_input.text().strip() or None,
        }
        prefs.set_proxy_config(base_dir, cfg)
        prefs.set_last_vpn_proxy(base_dir, cfg)
        parent._set_proxy_from_config(cfg)
        relaunch = getattr(parent, "smart_restart", None)
        dialog.done(1)
        if relaunch is not None:
            relaunch(reason=f"VPN connected: {host}:{port_n}")
        else:
            QMessageBox.information(parent, "VPN", f"Proxy {type_combo.currentText()} enabled: {host}:{port_n}\n\nRestart Mei to route all tabs through it.")
    elif result == 2:
        prefs.set_proxy_config(base_dir, {"enabled": False})
        prefs.set_auto_connect_vpn(base_dir, False)
        QNetworkProxy.setApplicationProxy(QNetworkProxy(QNetworkProxy.NoProxy))
        existing = os.environ.get("QTWEBENGINE_CHROMIUM_FLAGS", "").strip()
        os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = " ".join(
            tok for tok in existing.split() if not tok.startswith("--proxy-server=")
        ).strip()
        relaunch = getattr(parent, "smart_restart", None)
        dialog.done(2)
        if relaunch is not None:
            relaunch(reason="VPN disconnected")
        else:
            QMessageBox.information(
                parent,
                "VPN",
                "Proxy disabled. Restart Mei so web tabs no longer route through the proxy.",
            )


def show_startup_dialog(parent):
    base_dir = parent.base_dir
    dialog = QDialog(parent)
    dialog.setWindowTitle("On Startup")
    dialog.setStyleSheet(_stylesheet(parent))
    layout = QVBoxLayout(dialog)
    layout.addWidget(QLabel("Behavior when Mei starts:"))
    combo = QComboBox()
    combo.addItem("Restore tabs (session)", "restore")
    combo.addItem("New Tab page", "newtab")
    combo.addItem("Home page (custom URL)", "home")
    mode, home_url = prefs.get_startup_prefs(base_dir)
    for i in range(combo.count()):
        if combo.itemData(i) == mode:
            combo.setCurrentIndex(i)
            break
    layout.addWidget(combo)
    layout.addWidget(QLabel("Home page URL (only when \"Home page\" is selected):"))
    home_edit = QLineEdit()
    home_edit.setPlaceholderText("https://google.com")
    home_edit.setText(home_url)
    layout.addWidget(home_edit)
    def save_startup():
        data = prefs.load_prefs(base_dir)
        data["startup_mode"] = combo.currentData()
        data["home_url"] = home_edit.text().strip() or "https://google.com"
        prefs.save_prefs(base_dir, data)
        QMessageBox.information(parent, "Saved", "Applied from the next time Mei opens.")
        dialog.accept()
    btn = QPushButton("Save")
    btn.clicked.connect(save_startup)
    layout.addWidget(btn)
    dialog.exec_()


def show_hibernate_pref_dialog(parent):
    base_dir = parent.base_dir
    dialog = QDialog(parent)
    dialog.setWindowTitle("Tab Hibernation Time")
    dialog.setStyleSheet(_stylesheet(parent))
    layout = QVBoxLayout(dialog)
    layout.addWidget(QLabel("Inactive tabs will hibernate after:"))
    combo = QComboBox()
    combo.addItem("Off", 0)
    combo.addItem("1 minute", 60)
    combo.addItem("5 minutes", 300)
    combo.addItem("15 minutes", 900)
    combo.addItem("30 minutes", 1800)
    current = prefs.get_hibernate_seconds(base_dir)
    for i in range(combo.count()):
        if combo.itemData(i) == current:
            combo.setCurrentIndex(i)
            break
    layout.addWidget(combo)
    btn = QPushButton("Save")
    btn.clicked.connect(dialog.accept)
    layout.addWidget(btn)
    if dialog.exec_() == QDialog.Accepted:
        val = combo.currentData() if hasattr(combo, "currentData") else combo.itemData(combo.currentIndex())
        prefs.save_hibernate_seconds(base_dir, val)
        QMessageBox.information(parent, "Saved", "Applied to new tabs and the next hibernation.")


def show_history_dialog(parent):
    base_dir = parent.base_dir
    dialog = QDialog(parent)
    dialog.setWindowTitle("Browsing History")
    dialog.resize(620, 480)
    dialog.setStyleSheet(_stylesheet(parent))
    layout = QVBoxLayout(dialog)
    search_edit = QLineEdit()
    search_edit.setPlaceholderText("Filter history by title or URL...")
    layout.addWidget(search_edit)
    list_widget = QListWidget()
    entries = prefs.load_history_entries(base_dir)
    entries.sort(key=lambda x: -x[0])
    history_data = list(entries)

    def refresh_list(query=""):
        list_widget.clear()
        ent = prefs.load_history_entries(base_dir)
        ent.sort(key=lambda x: -x[0])
        history_data.clear()
        history_data.extend(ent)
        q = (query or "").strip().lower()
        shown = 0
        for ts, url in ent:
            if q and q not in url.lower():
                continue
            list_widget.addItem(url)
            shown += 1
            if shown >= 500:
                break
        if not shown:
            list_widget.addItem("No history yet...")

    search_edit.textChanged.connect(refresh_list)

    # Initial fill (unfiltered)
    for ts, url in entries[:500]:
        list_widget.addItem(url)
    if not entries:
        list_widget.addItem("No history yet...")

    def clear_history(seconds_back):
        ent = prefs.load_history_entries(base_dir)
        now = int(time.time())
        if seconds_back is None:
            ent = []
        else:
            ent = [(t, u) for t, u in ent if now - t > seconds_back]
        prefs.save_history_entries(base_dir, ent)
        refresh_list()
        dialog.setWindowTitle("Browsing History (updated)")

    layout.addWidget(list_widget)
    btn_row = QHBoxLayout()
    btn_clear_1h = QPushButton("Delete 1 hour")
    btn_clear_1h.clicked.connect(lambda: clear_history(3600))
    btn_clear_24h = QPushButton("Delete 24 hours")
    btn_clear_24h.clicked.connect(lambda: clear_history(86400))
    btn_clear_7d = QPushButton("Delete 7 days")
    btn_clear_7d.clicked.connect(lambda: clear_history(7 * 86400))
    btn_clear_all = QPushButton("Delete all")
    btn_clear_all.clicked.connect(lambda: clear_history(None))
    btn_row.addStretch()
    btn_row.addWidget(btn_clear_1h)
    btn_row.addWidget(btn_clear_24h)
    btn_row.addWidget(btn_clear_7d)
    btn_row.addWidget(btn_clear_all)
    btn_row.addStretch()
    layout.addLayout(btn_row)
    row = QHBoxLayout()
    def open_selected():
        item = list_widget.currentItem()
        if item and item.text() and item.text() != "No history yet...":
            parent.tab_manager.add_tab(QUrl(item.text()))
            dialog.accept()
    btn_open = QPushButton("Open selected page")
    btn_open.clicked.connect(open_selected)
    row.addStretch()
    row.addWidget(btn_open)
    row.addStretch()
    layout.addLayout(row)
    dialog.exec_()


def show_bookmarks_dialog(parent):
    base_dir = parent.base_dir
    dialog = QDialog(parent)
    dialog.setWindowTitle("Bookmarks")
    dialog.resize(640, 480)
    dialog.setStyleSheet(_stylesheet(parent))
    layout = QVBoxLayout(dialog)
    list_widget = QListWidget()
    bookmarks = list(prefs.load_bookmarks(base_dir))

    def refresh_list():
        list_widget.clear()
        bookmarks.clear()
        bookmarks.extend(prefs.load_bookmarks(base_dir))
        for bm in bookmarks:
            # .get: a malformed entry must not crash the dialog (v6.4 KeyError).
            title = (bm.get("title") if isinstance(bm, dict) else "") or ""
            url = (bm.get("url") if isinstance(bm, dict) else "") or ""
            list_widget.addItem(f"{title} - {url}")
        if not bookmarks:
            list_widget.addItem("No bookmarks yet...")

    for bm in bookmarks:
        title = (bm.get("title") if isinstance(bm, dict) else "") or ""
        url = (bm.get("url") if isinstance(bm, dict) else "") or ""
        list_widget.addItem(f"{title} - {url}")
    if not bookmarks:
        list_widget.addItem("No bookmarks yet...")
    layout.addWidget(list_widget)

    def export_json():
        path, _ = QFileDialog.getSaveFileName(dialog, "Export bookmarks", "", "JSON (*.json)")
        if path:
            prefs.save_bookmarks(base_dir, bookmarks)
            shutil.copy(prefs.bookmarks_path(base_dir), path)
            QMessageBox.information(dialog, "Export", "JSON file saved.")

    def export_html():
        path, _ = QFileDialog.getSaveFileName(dialog, "Export bookmarks (Chrome)", "", "HTML (*.html)")
        if path:
            lines = ["<!DOCTYPE NETSCAPE-Bookmark-file-1>", "<META HTTP-EQUIV=\"Content-Type\" CONTENT=\"text/html; charset=UTF-8\">", "<TITLE>Bookmarks</TITLE>", "<H1>Bookmarks</H1>", "<DL><p>"]
            for b in bookmarks:
                title = b.get("title", "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                url = b.get("url", "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                lines.append('    <DT><A HREF="%s">%s</A>' % (url, title))
            lines.append("</DL><p>")
            with open(path, "w", encoding="utf-8") as f:
                f.write("\n".join(lines))
            QMessageBox.information(dialog, "Export", "HTML file saved.")

    def import_file():
        path, _ = QFileDialog.getOpenFileName(dialog, "Import bookmarks", "", "JSON (*.json);;HTML (*.html);;All (*.*)")
        if not path:
            return
        new_bms = []
        try:
            if path.lower().endswith(".json"):
                with open(path, "r", encoding="utf-8") as f:
                    new_bms = json.load(f)
                if not isinstance(new_bms, list):
                    new_bms = []
            else:
                with open(path, "r", encoding="utf-8", errors="ignore") as f:
                    html = f.read()
                for m in re.finditer(r'<A[^>]+HREF="([^"]+)"[^>]*>([^<]*)</A>', html, re.IGNORECASE):
                    new_bms.append({"url": m.group(1), "title": m.group(2).strip() or m.group(1)})
        except Exception as e:
            QMessageBox.warning(dialog, "Error", "Could not read file: " + str(e))
            return
        if not new_bms:
            QMessageBox.information(dialog, "Import", "No bookmarks found in the file.")
            return
        existing_urls = {b["url"] for b in bookmarks}
        added = 0
        for b in new_bms:
            if b.get("url") and b["url"] not in existing_urls:
                bookmarks.append({"title": b.get("title", b["url"]), "url": b["url"]})
                existing_urls.add(b["url"])
                added += 1
        prefs.save_bookmarks(base_dir, bookmarks)
        refresh_list()
        QMessageBox.information(dialog, "Import", "Added %d bookmark(s)." % added)

    btn_row = QHBoxLayout()
    btn_row.addStretch()
    btn_export_json = QPushButton("Export JSON")
    btn_export_json.clicked.connect(export_json)
    btn_export_html = QPushButton("Export HTML")
    btn_export_html.clicked.connect(export_html)
    btn_import = QPushButton("Import from file")
    btn_import.clicked.connect(import_file)
    btn_row.addWidget(btn_export_json)
    btn_row.addWidget(btn_export_html)
    btn_row.addWidget(btn_import)
    btn_row.addStretch()
    layout.addLayout(btn_row)
    row = QHBoxLayout()
    def open_selected():
        idx = list_widget.currentRow()
        if idx >= 0 and 0 <= idx < len(bookmarks):
            url = bookmarks[idx].get("url") if isinstance(bookmarks[idx], dict) else ""
            if url:
                parent.tab_manager.add_tab(QUrl(url))
                dialog.accept()
    btn_open = QPushButton("Open selected page")
    btn_open.clicked.connect(open_selected)
    row.addStretch()
    row.addWidget(btn_open)
    row.addStretch()
    layout.addLayout(row)
    dialog.exec_()


def show_extensions_dialog(parent):
    ext_path = parent.ext_path
    dialog = QDialog(parent)
    dialog.setWindowTitle("Extensions (.JS)")
    dialog.resize(560, 400)
    dialog.setStyleSheet(_stylesheet(parent))
    layout = QVBoxLayout(dialog)
    info = QLabel("Place .js files in the Extensions folder. Each file runs on every page unless it starts with a ==UserScript== header declaring @match / @exclude URL patterns.")
    info.setWordWrap(True)
    layout.addWidget(info)
    list_widget = QListWidget()
    layout.addWidget(list_widget)
    ext_conf_file = os.path.join(ext_path, "extensions.json")
    ext_config = {}
    if os.path.exists(ext_conf_file):
        try:
            with open(ext_conf_file, "r", encoding="utf-8") as f:
                ext_config = json.load(f)
        except Exception:
            pass
    for file_name in os.listdir(ext_path) if os.path.exists(ext_path) else []:
        if file_name.endswith(".js"):
            item = QListWidgetItem(file_name)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if ext_config.get(file_name, False) else Qt.Unchecked)
            list_widget.addItem(item)

    def save_extensions():
        new_config = {}
        for i in range(list_widget.count()):
            item = list_widget.item(i)
            new_config[item.text()] = (item.checkState() == Qt.Checked)
        with open(ext_conf_file, "w", encoding="utf-8") as f:
            json.dump(new_config, f, indent=4)
        if hasattr(parent, "_user_extension_scripts_cache"):
            parent._user_extension_scripts_cache = None
        if hasattr(parent, "browsers"):
            for browser in getattr(parent, "browsers", []):
                try:
                    if browser.url().toString().startswith("http"):
                        browser.reload()
                except Exception:
                    pass
        QMessageBox.information(dialog, "Saved", "Your extensions were saved and will apply to reloaded pages.")
        dialog.accept()

    def make_sample():
        sample_path = os.path.join(ext_path, "SimpleAdblock.js")
        with open(sample_path, "w", encoding="utf-8") as f:
            f.write("""// ==UserScript==
// @name        Simple Adblock
// @match       *://*/*
// ==/UserScript==
(function() {
    var badElems = document.querySelectorAll('iframe, .ads, [id*=\"ad-\"], [class*=\"banner\"]');
    badElems.forEach(e => e.style.display = \"none\");
})();""")
        list_widget.addItem(QListWidgetItem("SimpleAdblock.js"))
        item = list_widget.item(list_widget.count() - 1)
        item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
        item.setCheckState(Qt.Checked)

    btn_row = QHBoxLayout()
    btn_row.addStretch()
    btn_save = QPushButton("Save options")
    btn_save.clicked.connect(save_extensions)
    btn_row.addWidget(btn_save)
    btn_sample = QPushButton("Create Adblock sample (.js)")
    btn_sample.clicked.connect(make_sample)
    btn_row.addWidget(btn_sample)
    btn_gf = QPushButton("Browse GreasyFork…")
    btn_gf.clicked.connect(lambda: [dialog.accept(), parent.tab_manager.add_tab(QUrl("https://greasyfork.org/vi"), "GreasyFork", is_active=True)])
    btn_row.addWidget(btn_gf)
    btn_open = QPushButton("Open folder")
    btn_open.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(ext_path)))
    btn_row.addWidget(btn_open)
    btn_row.addStretch()
    layout.addLayout(btn_row)
    dialog.exec_()


def show_tab_sets_dialog(parent):
    """List saved tab collections; open or delete them."""
    base_dir = parent.base_dir
    dialog = QDialog(parent)
    dialog.setWindowTitle("Tab Sets")
    dialog.resize(560, 420)
    dialog.setStyleSheet(_stylesheet(parent))
    layout = QVBoxLayout(dialog)
    info = QLabel("Saved tab collections. Open one to restore all its tabs (inactive tabs start suspended).")
    info.setWordWrap(True)
    layout.addWidget(info)
    list_widget = QListWidget()
    layout.addWidget(list_widget)

    def refresh():
        list_widget.clear()
        for item in tab_sets.list_tab_sets(base_dir):
            count = len(item.get("tabs", []))
            updated = time_utils.format_ts(item.get("updated_at"))
            label = f"{item.get('title', 'Untitled')}  ·  {count} tab(s)  ·  {updated}"
            if item.get("kind"):
                label += f"  ·  {item.get('kind')}"
            list_item = QListWidgetItem(label)
            list_item.setData(Qt.UserRole, item.get("id"))
            list_widget.addItem(list_item)

    refresh()

    def open_selected():
        current = list_widget.currentItem()
        if not current:
            return
        set_id = current.data(Qt.UserRole)
        dialog.accept()
        if hasattr(parent, "restore_tab_set"):
            parent.restore_tab_set(set_id)

    def delete_selected():
        current = list_widget.currentItem()
        if not current:
            return
        set_id = current.data(Qt.UserRole)
        data = tab_sets.get_tab_set(base_dir, set_id)
        title = data.get("title", "") if data else "this tab set"
        if QMessageBox.question(dialog, "Delete", f"Delete \"{title}\"?", QMessageBox.Yes | QMessageBox.No) == QMessageBox.Yes:
            tab_sets.remove_tab_set(base_dir, set_id)
            refresh()

    list_widget.itemDoubleClicked.connect(lambda _item: open_selected())

    btn_row = QHBoxLayout()
    btn_open = QPushButton("Open")
    btn_open.clicked.connect(open_selected)
    btn_del = QPushButton("Delete")
    btn_del.clicked.connect(delete_selected)
    btn_refresh = QPushButton("Refresh")
    btn_refresh.clicked.connect(refresh)
    btn_close = QPushButton("Close")
    btn_close.clicked.connect(dialog.accept)
    btn_row.addWidget(btn_open)
    btn_row.addWidget(btn_del)
    btn_row.addWidget(btn_refresh)
    btn_row.addStretch()
    btn_row.addWidget(btn_close)
    layout.addLayout(btn_row)
    dialog.exec_()

