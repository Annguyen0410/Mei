"""First-run onboarding: three quick steps, shown once, always skippable.

1. Pick a theme + accent (live swatches) — plus optional auto day/night.
2. Import from Chrome/Edge (bookmarks + passwords via the existing bridge) — optional.
3. Pair the Android bridge (QR) — optional.

Completion is recorded in prefs ('onboarding_done'), so it never nags again.
"""
from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor, QPainter, QPen, QPixmap
from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from litebrowser.core import prefs
from litebrowser.ui import theme
from litebrowser.ui.dialogs.common import _stylesheet

STEPS = ("Welcome to your café ☕", "Bring your stuff", "Pair your phone (optional)")


def _swatch_icon(mode_id: str, accent_id: str) -> QPixmap:
    pal = theme._palette(mode_id, accent_id)
    pixmap = QPixmap(64, 34)
    pixmap.fill(QColor(pal["MAIN_BG"]))
    painter = QPainter(pixmap)
    painter.setPen(QPen(QColor(pal["BORDER_SOFT"]), 1))
    painter.setBrush(QColor(pal["SIDEBAR_BG"]))
    painter.drawRect(0, 0, 63, 33)
    painter.setBrush(QColor(pal["ACCENT"]))
    painter.setPen(Qt.NoPen)
    painter.drawRoundedRect(6, 8, 20, 18, 4, 4)
    painter.setBrush(QColor(pal["ACCENT_SOFT"]))
    painter.drawRoundedRect(32, 8, 26, 8, 3, 3)
    painter.drawRoundedRect(32, 20, 26, 6, 3, 3)
    painter.end()
    return pixmap


def show_onboarding(shell) -> None:
    if prefs.get_pref(shell.profile_dir, "onboarding_done", False):
        return
    dlg = QDialog(shell)
    dlg.setWindowTitle("Welcome to Mei — setup")
    dlg.resize(620, 480)
    dlg.setStyleSheet(_stylesheet(shell))
    layout = QVBoxLayout(dlg)

    title = QLabel(STEPS[0])
    title.setObjectName("HeroTitle")
    layout.addWidget(title)
    step_lbl = QLabel("Step 1 of 3")
    step_lbl.setObjectName("MutedLabel")
    layout.addWidget(step_lbl)

    body = QWidget()
    body_layout = QVBoxLayout(body)
    body_layout.setContentsMargins(0, 0, 0, 0)
    layout.addWidget(body, 1)

    # --- Step 1: theme ---
    theme_page = QWidget()
    tp_layout = QVBoxLayout(theme_page)
    tp_layout.addWidget(QLabel("Pick the look of your café — you can change it anytime with /theme and /accent."))
    combo_theme = QComboBox()
    combo_accent = QComboBox()
    preview = QLabel()
    preview.setMinimumHeight(60)
    for mode_id in sorted(theme.PALETTES.keys()):
        combo_theme.addItem(theme.theme_display_name(mode_id), mode_id)
    for accent_id in sorted(theme.ACCENTS.keys()):
        combo_accent.addItem(theme.accent_display_name(accent_id), accent_id)

    def _current_ids():
        return combo_theme.currentData() or theme.DEFAULT_THEME, combo_accent.currentData() or "brass"

    def _update_preview():
        mode_id, accent_id = _current_ids()
        preview.setPixmap(_swatch_icon(mode_id, accent_id).scaled(128, 68))

    combo_theme.currentIndexChanged.connect(lambda _i: _update_preview())
    combo_accent.currentIndexChanged.connect(lambda _i: _update_preview())
    combo_theme.setCurrentIndex(max(0, list(sorted(theme.PALETTES.keys())).index(theme.DEFAULT_THEME)))
    _update_preview()
    tp_layout.addWidget(QLabel("Theme:"))
    tp_layout.addWidget(combo_theme)
    tp_layout.addWidget(QLabel("Accent:"))
    tp_layout.addWidget(combo_accent)
    tp_layout.addWidget(preview)
    chk_auto = QCheckBox("Auto day / night — day palette by day, night palette after 18:00")
    tp_layout.addWidget(chk_auto)
    body_layout.addWidget(theme_page)

    # --- Step 2: import ---
    import_page = QWidget()
    imp_layout = QVBoxLayout(import_page)
    imp_layout.addWidget(QLabel(
        "Mei can pull tabs from your current browser through the Mei bridge extension "
        "(Chrome / Opera GX / Edge). You can also skip and use File → Import later."
    ))
    chk_skip_import = QCheckBox("Skip for now")
    chk_skip_import.setChecked(True)
    imp_layout.addWidget(chk_skip_import)
    imp_layout.addStretch(1)
    body_layout.addWidget(import_page)
    import_page.hide()

    # --- Step 3: phone ---
    phone_page = QWidget()
    phone_layout = QVBoxLayout(phone_page)
    phone_layout.addWidget(QLabel(
        "The Android bridge lets your phone push links, files and notes into Mei over Wi-Fi. "
        "Enable it later from Settings, or run the VPN / Bridge hub anytime."
    ))
    chk_skip_phone = QCheckBox("Skip for now")
    chk_skip_phone.setChecked(True)
    phone_layout.addWidget(chk_skip_phone)
    chk_bridge = QCheckBox("Enable the Android bridge now (localhost only)")
    phone_layout.addWidget(chk_bridge)
    phone_layout.addStretch(1)
    body_layout.addWidget(phone_page)
    phone_page.hide()

    state = {"step": 1}

    nav_row = QHBoxLayout()
    btn_back = QPushButton("Back")
    btn_back.setEnabled(False)
    btn_next = QPushButton("Next")
    btn_next.setObjectName("TopAccentButton")
    nav_row.addStretch(1)
    nav_row.addWidget(btn_back)
    nav_row.addWidget(btn_next)
    layout.addLayout(nav_row)

    pages = {1: theme_page, 2: import_page, 3: phone_page}

    def _show_step(n: int):
        state["step"] = n
        for key, page in pages.items():
            page.setVisible(key == n)
        step_lbl.setText(f"Step {n} of 3 — {STEPS[n - 1]}")
        btn_back.setEnabled(n > 1)
        btn_next.setText("Finish ✨" if n == 3 else "Next")

    def _on_next():
        step = state["step"]
        if step == 1:
            theme_id, accent_id = _current_ids()
            prefs.set_shell_theme(shell.profile_dir, theme_id)
            prefs.set_accent(shell.profile_dir, accent_id)
            prefs.set_auto_theme(shell.profile_dir, chk_auto.isChecked())
            shell._qss_key = None
            shell.refresh_shell()
            _show_step(2)
            return
        if step == 2:
            if not chk_skip_import.isChecked():
                dlg.accept()
                from litebrowser.ui.dialogs import sessions as _sessions

                _sessions.show_extensions_dialog(shell.browser_page)
            else:
                _show_step(3)
            return
        if chk_bridge.isChecked():
            prefs.set_mobile_bridge_enabled(shell.profile_dir, True)
        prefs.save_pref(shell.profile_dir, "onboarding_done", True)
        dlg.accept()

    def _on_back():
        _show_step(max(1, state["step"] - 1))

    btn_next.clicked.connect(_on_next)
    btn_back.clicked.connect(_on_back)
    _show_step(1)
    dlg.exec_()
