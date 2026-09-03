"""Dialog helpers for browser and shell."""
from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from litebrowser.core import prefs
from litebrowser.ui.dialogs.common import _stylesheet


def show_profiles_dialog(parent, app_dir):
    """Select / create / delete a profile. Called from browser.py before a window opens, or from the Options menu."""
    dialog = QDialog(parent)
    dialog.setWindowTitle("Profiles")
    dialog.setStyleSheet(_stylesheet(parent) if parent else "")
    layout = QVBoxLayout(dialog)
    layout.addWidget(QLabel("Select a profile to open (or create a new one). Restart with the selected profile."))
    list_widget = QListWidget()
    for name in prefs.list_profiles(app_dir):
        list_widget.addItem(name)
    layout.addWidget(list_widget)
    btn_row = QHBoxLayout()
    def add_profile():
        name, ok = QInputDialog.getText(dialog, "New profile", "Profile name:")
        if ok and name.strip():
            if prefs.create_profile(app_dir, name.strip()):
                list_widget.addItem(name.strip())
                QMessageBox.information(dialog, "OK", "Profile created. Select it and close, then restart.")
            else:
                QMessageBox.warning(dialog, "Error", "That name already exists or is invalid.")
    def delete_profile():
        row = list_widget.currentRow()
        if row < 0:
            return
        name = list_widget.item(row).text()
        if QMessageBox.Yes != QMessageBox.question(dialog, "Delete?", "Delete profile \"%s\"? (Data in the profile folder will be lost)" % name, QMessageBox.Yes | QMessageBox.No, QMessageBox.No):
            return
        prefs.delete_profile(app_dir, name)
        list_widget.takeItem(row)
    def use_selected():
        row = list_widget.currentRow()
        if row >= 0:
            name = list_widget.item(row).text()
            current = prefs.get_last_profile(app_dir)
            prefs.set_last_profile(app_dir, name)
            dialog.accept()
            if name == current:
                return  # already running it
            # Runtime switch: persist the session and smart-restart into the
            # chosen profile (tabs restore under the new profile on boot).
            relaunch = getattr(parent, "smart_restart", None) if parent is not None else None
            if relaunch is not None:
                relaunch(reason=f"Switched to profile: {name}")
            else:
                QMessageBox.information(dialog, "Selected", "Profile \"%s\" set. Restart Mei to use it." % name)
        else:
            dialog.accept()
    btn_add = QPushButton("Create profile")
    btn_add.clicked.connect(add_profile)
    btn_del = QPushButton("Delete selected")
    btn_del.clicked.connect(delete_profile)
    btn_use = QPushButton("Use this profile")
    btn_use.setObjectName("TopAccentButton")
    btn_use.clicked.connect(use_selected)
    btn_row.addWidget(btn_add)
    btn_row.addWidget(btn_del)
    btn_row.addWidget(btn_use)
    btn_row.addStretch()
    layout.addLayout(btn_row)
    dialog.exec_()


def ask_master_password(parent, title="Master password"):
    pw, ok = QInputDialog.getText(parent, title, "Enter master password (to unlock the password vault):", QLineEdit.Password)
    if ok and pw:
        return pw
    return None


def show_privacy_dialog(parent):
    base_dir = parent.base_dir
    dialog = QDialog(parent)
    dialog.setWindowTitle("Privacy & Security (2.0)")
    dialog.setMinimumWidth(480)
    dialog.resize(540, 420)
    dialog.setStyleSheet(_stylesheet(parent) + """
        QCheckBox { color: #e8e8ec; font-size: 13px; spacing: 8px; }
        QCheckBox::indicator { width: 18px; height: 18px; border-radius: 4px; border: 2px solid #4a4a52; background: #1e1e22; }
        QCheckBox::indicator:checked { background: #3b5bce; border-color: #4a6fa5; }
        QCheckBox::indicator:hover { border-color: #6b8ad4; }
    """)
    layout = QVBoxLayout(dialog)
    layout.setSpacing(14)
    layout.setContentsMargins(20, 20, 20, 20)

    chk_https = QCheckBox("Only load HTTPS (block http, except localhost)")
    chk_https.setChecked(prefs.get_https_only(base_dir))
    layout.addWidget(chk_https)

    chk_strict_ref = QCheckBox("Send shortened Referer to other sites (strict-origin)")
    chk_strict_ref.setChecked(prefs.get_strict_referrer(base_dir))
    chk_strict_ref.setToolTip(
        "Send only the origin (https://example.com) instead of the full URL when clicking to another site —\n"
        "reduces cross-site tracking without breaking on-site analytics."
    )
    layout.addWidget(chk_strict_ref)

    chk_strip_ch = QCheckBox("Hide device info (CPU, GPU, extra OS details) from unfamiliar sites")
    chk_strip_ch.setChecked(prefs.get_strip_client_hints(base_dir))
    chk_strip_ch.setToolTip(
        "Removes Sec-CH-UA-Arch / Bitness / Platform-Version / Model.\n"
        "Login sites (Google, Microsoft) in the allowlist still receive the full headers."
    )
    layout.addWidget(chk_strip_ch)

    chk_3p_cookie_priv = QCheckBox("Block third-party cookies (cross-site tracking)")
    chk_3p_cookie_priv.setChecked(prefs.get_block_third_party_cookies(base_dir))
    layout.addWidget(chk_3p_cookie_priv)

    chk_chrome_shim = QCheckBox("Chrome compatibility mode (hide automation detection)")
    chk_chrome_shim.setChecked(prefs.get_chrome_compat_shim(base_dir))
    chk_chrome_shim.setToolTip("Injects a script impersonating real Chrome — avoids being blocked by Google, OpenAI, Anthropic, etc.")
    layout.addWidget(chk_chrome_shim)

    layout.addSpacing(6)
    lbl_adblock = QLabel("Adblock filter file")
    lbl_adblock.setObjectName("SectionTitle")
    lbl_adblock.setToolTip("Format: one rule per line — ||domain^ or a domain name (e.g. ads.example.com)")
    layout.addWidget(lbl_adblock)
    row_file = QHBoxLayout()
    row_file.setSpacing(10)
    edit_filter = QLineEdit()
    edit_filter.setPlaceholderText("Path to a .txt file or leave blank")
    edit_filter.setText(prefs.get_adblock_filter_file(base_dir) or "")
    edit_filter.setMinimumHeight(32)
    row_file.addWidget(edit_filter, 1)
    btn_browse = QPushButton("Browse...")
    btn_browse.setMinimumWidth(80)
    btn_browse.setMinimumHeight(32)
    def browse_filter():
        path, _ = QFileDialog.getOpenFileName(dialog, "Choose filter file", "", "Text (*.txt);;All (*.*)")
        if path:
            edit_filter.setText(path)
    btn_browse.clicked.connect(browse_filter)
    row_file.addWidget(btn_browse)
    layout.addLayout(row_file)

    lbl_subs = QLabel("Subscribed filters (auto-updated)")
    lbl_subs.setObjectName("SectionTitle")
    layout.addWidget(lbl_subs)
    subs_list = QListWidget()
    subs_list.setMaximumHeight(80)
    _KNOWN_SUBS = {
        "EasyList": "https://easylist.to/easylist/easylist.txt",
        "EasyPrivacy": "https://easylist.to/easylist/easyprivacy.txt",
        "Vietnamese": "https://raw.githubusercontent.com/abpvn/abpvn/master/filter/abpvn.txt",
    }
    current_subs = prefs.get_adblock_subscriptions(base_dir)
    for sub in current_subs:
        subs_list.addItem(sub.get("name", sub.get("url", "?")))
    layout.addWidget(subs_list)
    subs_row = QHBoxLayout()
    sub_combo = QComboBox()
    sub_combo.addItems(list(_KNOWN_SUBS.keys()))
    subs_row.addWidget(sub_combo, 1)
    def add_subscription():
        name = sub_combo.currentText()
        url = _KNOWN_SUBS.get(name)
        if not url:
            return
        subs = prefs.get_adblock_subscriptions(base_dir)
        if any(s.get("url") == url for s in subs):
            QMessageBox.information(dialog, "Filter", f"\"{name}\" has already been added.")
            return
        subs.append({"name": name, "url": url})
        prefs.set_adblock_subscriptions(base_dir, subs)
        subs_list.addItem(name)
    btn_add_sub = QPushButton("+ Add")
    btn_add_sub.clicked.connect(add_subscription)
    subs_row.addWidget(btn_add_sub)
    def remove_subscription():
        row = subs_list.currentRow()
        if row < 0:
            return
        subs = prefs.get_adblock_subscriptions(base_dir)
        if row < len(subs):
            subs.pop(row)
            prefs.set_adblock_subscriptions(base_dir, subs)
            subs_list.takeItem(row)
    btn_remove_sub = QPushButton("Remove")
    btn_remove_sub.clicked.connect(remove_subscription)
    subs_row.addWidget(btn_remove_sub)
    layout.addLayout(subs_row)

    layout.addSpacing(14)
    chk_pw_mgr = QCheckBox("Enable password manager (save / autofill passwords)")
    chk_pw_mgr.setChecked(prefs.get_password_manager_enabled(base_dir))
    layout.addWidget(chk_pw_mgr)
    chk_autofill = QCheckBox("Autofill passwords once saved")
    chk_autofill.setChecked(prefs.get_autofill_passwords(base_dir))
    layout.addWidget(chk_autofill)
    note_crypto = QLabel("Note: The password manager requires a library — pip install cryptography")
    note_crypto.setObjectName("MutedLabel")
    note_crypto.setWordWrap(True)
    layout.addWidget(note_crypto)

    layout.addSpacing(18)
    btn_row = QHBoxLayout()
    btn_row.addStretch()
    btn = QPushButton("Save")
    btn.setMinimumWidth(120)
    btn.setMinimumHeight(36)
    def save_privacy():
        prefs.set_https_only(base_dir, chk_https.isChecked())
        prefs.set_strict_referrer(base_dir, chk_strict_ref.isChecked())
        prefs.set_strip_client_hints(base_dir, chk_strip_ch.isChecked())
        prefs.set_block_third_party_cookies(base_dir, chk_3p_cookie_priv.isChecked())
        prefs.set_chrome_compat_shim(base_dir, chk_chrome_shim.isChecked())
        prefs.set_adblock_filter_file(base_dir, edit_filter.text().strip())
        prefs.set_password_manager_enabled(base_dir, chk_pw_mgr.isChecked())
        prefs.set_autofill_passwords(base_dir, chk_autofill.isChecked())
        if hasattr(parent, "interceptor"):
            parent.interceptor.https_only = chk_https.isChecked()
            parent.interceptor.strict_referrer = chk_strict_ref.isChecked()
            parent.interceptor.strip_client_hints = chk_strip_ch.isChecked()
            try:
                from litebrowser.browser import adblock
                adblock.fetch_and_update_subscriptions(base_dir)
            except Exception:
                pass
            if hasattr(parent.interceptor, "reload_filter_file"):
                parent.interceptor.reload_filter_file()
        if hasattr(parent, "act_block_3p_cookies"):
            parent.act_block_3p_cookies.setChecked(chk_3p_cookie_priv.isChecked())
            if hasattr(parent, "_apply_cookie_policy"):
                parent._apply_cookie_policy(show_message=False)
        for browser in getattr(parent, "browsers", []):
            try:
                if browser.url().toString().startswith("http"):
                    browser.reload()
            except Exception:
                pass
        QMessageBox.information(dialog, "Saved", "Security preferences applied.")
        dialog.accept()
    btn.clicked.connect(save_privacy)
    btn_row.addWidget(btn)
    btn_row.addStretch()
    layout.addLayout(btn_row)
    dialog.exec_()


def show_save_password_dialog(parent):
    from litebrowser.services import password_manager
    if not password_manager.HAS_CRYPTO:
        QMessageBox.warning(parent, "Password", "Required: pip install cryptography")
        return
    browser = parent.current_browser() if hasattr(parent, "current_browser") and callable(parent.current_browser) else None
    url = browser.url().toString() if browser else ""
    dialog = QDialog(parent)
    dialog.setWindowTitle("Save password")
    dialog.setStyleSheet(_stylesheet(parent))
    layout = QVBoxLayout(dialog)
    layout.addWidget(QLabel("URL (page):"))
    url_edit = QLineEdit()
    url_edit.setText(url)
    layout.addWidget(url_edit)
    layout.addWidget(QLabel("Username:"))
    user_edit = QLineEdit()
    layout.addWidget(user_edit)
    layout.addWidget(QLabel("Password:"))
    pass_edit = QLineEdit()
    pass_edit.setEchoMode(QLineEdit.Password)
    layout.addWidget(pass_edit)
    layout.addWidget(QLabel("Master password (to encrypt the vault):"))
    master_edit = QLineEdit()
    master_edit.setEchoMode(QLineEdit.Password)
    layout.addWidget(master_edit)
    def do_save():
        u = url_edit.text().strip()
        usr = user_edit.text().strip()
        pw = pass_edit.text()
        master = master_edit.text()
        if not u or not usr or not master:
            QMessageBox.warning(dialog, "Save", "Fill in the URL, username, and master password.")
            return
        try:
            saved = password_manager.add_password(parent.base_dir, u, usr, pw, master)
        except password_manager.VaultUnlockError as exc:
            QMessageBox.warning(dialog, "Vault locked", str(exc))
            return
        if saved:
            QMessageBox.information(dialog, "OK", "Password saved.")
            dialog.accept()
        else:
            QMessageBox.warning(dialog, "Error", "Could not save (check the master password).")
    btn = QPushButton("Save")
    btn.clicked.connect(do_save)
    layout.addWidget(btn)
    dialog.exec_()


FEATURE_LABELS = {
    "geolocation": "Location",
    "microphone": "Microphone",
    "camera": "Camera",
    "microphone_camera": "Microphone + Camera",
    "desktop_capture": "Screen capture",
    "notifications": "Notifications",
}


def show_permissions_manager(parent):
    """Chrome-style site permissions manager: every origin × feature decision
    with allow/deny toggles, add new rule, and reset-all."""
    from PyQt5.QtCore import Qt

    base_dir = parent.base_dir
    dialog = QDialog(parent)
    dialog.setWindowTitle("Site Permissions")
    dialog.resize(620, 480)
    dialog.setStyleSheet(_stylesheet(parent))
    layout = QVBoxLayout(dialog)
    layout.addWidget(QLabel("Decisions you made for site features. Allow = grant, Deny = block permanently."))
    list_widget = QListWidget()
    layout.addWidget(list_widget, 1)
    btn_row = QHBoxLayout()

    def refresh():
        list_widget.clear()
        perms = prefs.load_permissions(base_dir)
        rows = []
        for origin, features in sorted(perms.items()):
            if not isinstance(features, dict):
                continue
            for feature, policy in sorted(features.items()):
                if policy not in ("allow", "deny"):
                    continue
                rows.append((origin, feature, policy))
        if not rows:
            list_widget.addItem("No saved site decisions yet. Mei asks the first time a site requests something.")
            list_widget.setEnabled(False)
            return
        list_widget.setEnabled(True)
        for origin, feature, policy in rows:
            label = FEATURE_LABELS.get(feature, feature)
            mark = "✅" if policy == "allow" else "⛔"
            item_text = f"{mark} {origin} — {label} ({policy})"
            list_widget.addItem(item_text)
            list_widget.item(list_widget.count() - 1).setData(Qt.UserRole, (origin, feature, policy))

    def flip():
        current = list_widget.currentItem()
        if not current:
            return
        payload = current.data(Qt.UserRole)
        if not payload:
            return
        origin, feature, policy = payload
        prefs.set_permission(base_dir, origin, feature, "deny" if policy == "allow" else "allow")
        refresh()

    def remove_rule():
        current = list_widget.currentItem()
        if not current:
            return
        payload = current.data(Qt.UserRole)
        if not payload:
            return
        origin, feature, _policy = payload
        perms = prefs.load_permissions(base_dir)
        if origin in perms:
            perms[origin].pop(feature, None)
            if not perms[origin]:
                perms.pop(origin, None)
            prefs.save_permissions(base_dir, perms)
        refresh()

    def add_rule():
        origin, ok = QInputDialog.getText(dialog, "Add rule", "Site origin (e.g. example.com):")
        if not ok or not origin.strip():
            return
        feature_names = list(FEATURE_LABELS.items())
        feature, ok = QInputDialog.getItem(dialog, "Feature", "Feature:", [label for _k, label in feature_names], 0, False)
        if not ok:
            return
        feature_key = next((k for k, label in feature_names if label == feature), "geolocation")
        policy, ok = QInputDialog.getItem(dialog, "Policy", "Policy:", ["allow", "deny"], 0, False)
        if not ok:
            return
        prefs.set_permission(base_dir, origin.strip(), feature_key, policy)
        refresh()

    btn_add = QPushButton("Add rule")
    btn_add.clicked.connect(add_rule)
    btn_flip = QPushButton("Allow ⇄ Deny")
    btn_flip.clicked.connect(flip)
    btn_remove = QPushButton("Remove rule")
    btn_remove.clicked.connect(remove_rule)
    btn_reset = QPushButton("Reset all")
    btn_reset.clicked.connect(lambda: (prefs.save_permissions(base_dir, {}), refresh()))
    for b in (btn_add, btn_flip, btn_remove, btn_reset):
        btn_row.addWidget(b)
    btn_row.addStretch()
    layout.addLayout(btn_row)
    close_row = QHBoxLayout()
    close_row.addStretch()
    btn_close = QPushButton("Close")
    btn_close.clicked.connect(dialog.accept)
    close_row.addWidget(btn_close)
    layout.addLayout(close_row)
    refresh()
    dialog.exec_()
