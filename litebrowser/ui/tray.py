"""System tray icon + native notifications (Windows toasts, free).

The tray lives on the primary shell: quick actions (new tab, quick note,
25-min pour, VPN status) plus native QSystemTrayIcon.showMessage toasts for
downloads, focus reminders and routines — visible even when Mei is in the
background. If the desktop has no tray, everything degrades gracefully.
"""
from PyQt5.QtGui import QIcon
from PyQt5.QtWidgets import QMenu, QSystemTrayIcon

from litebrowser.core import prefs


class MeiTray(QSystemTrayIcon):
    def __init__(self, shell):
        self.shell = shell
        icon = QIcon(shell.app_dir + "/icon.png")
        super().__init__(icon, shell)
        self.setToolTip("Mei — your café")

        menu = QMenu()
        act_note = menu.addAction("✎ Quick note")
        act_note.triggered.connect(self._quick_note)
        act_pour = menu.addAction("☕ Pour 25 min")
        act_pour.triggered.connect(self._quick_pour)
        act_vpn = menu.addAction("🛡 VPN status")
        act_vpn.triggered.connect(self._vpn_status)
        menu.addSeparator()
        act_quit = menu.addAction("✕ Quit Mei")
        act_quit.triggered.connect(lambda: self.shell.close())
        self.setContextMenu(menu)
        self.activated.connect(self._on_activated)
        # Many Linux setups still render showMessage fine; on systems without
        # a tray, isSystemTrayAvailable() guards construction in the caller.
        self.show()

    # -- actions -------------------------------------------------------
    def _quick_note(self):
        shell = self.shell
        shell.switch_workspace("personal")
        page = shell.personal_page
        if hasattr(page, "_switch_page"):
            page._switch_page("notes")
        if hasattr(page, "note_editor"):
            page.note_editor.setFocus()

    def _quick_pour(self):
        from litebrowser.services import focus_service

        focus_service.start_focus(self.shell.profile_dir, minutes=25, label="Tray pour")
        self.notify("Café Focus", "25-minute pour started — /status to check")

    def _vpn_status(self):
        cfg = prefs.get_proxy_config(self.shell.profile_dir)
        if cfg.get("enabled"):
            self.notify("Mei Shield", f"Protected via {cfg.get('host')}:{cfg.get('port')}")
        else:
            self.notify("Mei Shield", "Direct connection (no proxy)")

    def _on_activated(self, reason):
        if reason == QSystemTrayIcon.Trigger:  # single click → focus a window
            self.shell.showNormal()
            self.shell.raise_()

    # -- native toast --------------------------------------------------
    def notify(self, title: str, message: str, msecs: int = 4000):
        if self.isVisible():
            self.showMessage(title, message, QSystemTrayIcon.Information, msecs)
