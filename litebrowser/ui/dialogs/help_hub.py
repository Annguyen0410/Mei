"""Help, control center, and modern guide dialogs."""
from PyQt5.QtWidgets import (
    QDialog,
    QFrame,
    QGridLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from litebrowser.ui.dialogs.common import _stylesheet
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


def show_browser_control_center(parent):
    dialog = QDialog(parent)
    dialog.setWindowTitle("Help & Browser Tools")
    dialog.resize(760, 520)
    dialog.setStyleSheet(_stylesheet(parent))
    layout = QVBoxLayout(dialog)
    layout.setContentsMargins(18, 18, 18, 18)
    layout.setSpacing(14)

    title = QLabel("Help & Browser Tools")
    title.setStyleSheet("font-size: 20px; font-weight: 700;")
    title.setWordWrap(True)
    layout.addWidget(title)

    subtitle = QLabel("Groups powerful tools into a few main areas to keep the UI clean while staying fast to reach.")
    subtitle.setWordWrap(True)
    subtitle.setObjectName("MutedLabel")
    layout.addWidget(subtitle)

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

    layout.addWidget(grid_host, 1)
    close_btn = QPushButton("Close")
    close_btn.clicked.connect(dialog.accept)
    layout.addWidget(close_btn)
    dialog.exec_()
