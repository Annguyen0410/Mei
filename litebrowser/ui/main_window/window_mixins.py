# Mei - window mixins: web panels, split view, and dock management.
#
# Split out of window.py (was 4600+ lines) so each feature area is a
# reviewable unit. SearchWindow inherits these; they only touch self.*
# attributes that SearchWindow owns (panel_dock, split_dock, tab_manager,
# profile, base_dir, ...) - no import cycles back into window.py.

from PyQt5.QtCore import QUrl
from PyQt5.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMenu,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from litebrowser.browser import browser_page
from litebrowser.core import prefs


class DockingMixin:
    """Web panels (GX-style right dock) + split view (left dock)."""

    # ------------------------------------------------------------------
    # Opera GX-style web panels: messenger/media apps docked beside the web.
    # The panel view shares the main QWebEngineProfile, so logging into
    # Telegram once keeps every later session signed in.

    WEB_PANEL_PRESETS = (
        ("Telegram", "✈", "https://web.telegram.org/k/"),
        ("WhatsApp", "◉", "https://web.whatsapp.com/"),
        ("Discord", "◕", "https://discord.com/channels/@me"),
        ("Messenger", "◈", "https://www.messenger.com/"),
        ("Spotify", "♫", "https://open.spotify.com/"),
        ("YouTube Music", "▶", "https://music.youtube.com/"),
        ("Instagram", "◍", "https://www.instagram.com/"),
        ("Gmail", "✉", "https://mail.google.com/"),
    )

    def _build_split_dock(self):
        """Left dock for split view (two pages side by side in one workspace)."""
        self.split_dock = QFrame()
        self.split_dock.setObjectName("SplitDock")
        dock_layout = QVBoxLayout(self.split_dock)
        dock_layout.setContentsMargins(0, 0, 0, 0)
        dock_layout.setSpacing(0)
        header = QFrame()
        header.setObjectName("WebPanelHeader")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(8, 3, 6, 3)
        header_layout.setSpacing(4)
        self.lbl_split_title = QLabel("Split")
        self.lbl_split_title.setObjectName("PageTitle")
        f = self.lbl_split_title.font()
        f.setPointSize(9)
        f.setBold(True)
        self.lbl_split_title.setFont(f)
        header_layout.addWidget(self.lbl_split_title, 1)
        self.btn_split_reload = QToolButton()
        self.btn_split_reload.setObjectName("TopIconButton")
        self.btn_split_reload.setText("⟳")
        self.btn_split_reload.setToolTip("Reload split pane")
        self.btn_split_reload.clicked.connect(lambda: self._ensure_split_view().reload())
        self.btn_split_open_tab = QToolButton()
        self.btn_split_open_tab.setObjectName("TopIconButton")
        self.btn_split_open_tab.setText("⇤")
        self.btn_split_open_tab.setToolTip("Move split page into a full tab")
        self.btn_split_open_tab.clicked.connect(self._split_to_tab)
        self.btn_split_close = QToolButton()
        self.btn_split_close.setObjectName("TopIconButton")
        self.btn_split_close.setText("✕")
        self.btn_split_close.setToolTip("Close split view")
        self.btn_split_close.clicked.connect(self.close_split_view)
        for b in (self.btn_split_reload, self.btn_split_open_tab, self.btn_split_close):
            header_layout.addWidget(b)
        dock_layout.addWidget(header, 0)
        self.split_view = None
        self._split_url = ""
        self.split_body = QWidget()
        self.split_body_layout = QVBoxLayout(self.split_body)
        self.split_body_layout.setContentsMargins(0, 0, 0, 0)
        dock_layout.addWidget(self.split_body, 1)
        self.split_dock.setMinimumWidth(300)
        self.split_dock.setMaximumWidth(900)
        self.split_dock.hide()

    def _ensure_split_view(self):
        if getattr(self, "split_view", None) is not None:
            return self.split_view
        self.split_view = QWebEngineView(self.split_dock)
        self.split_view.setObjectName("WebPanelView")
        try:
            self.split_view.setPage(browser_page.BrowserPage(self.profile, self.split_view, self.base_dir, host=self))
        except Exception:
            pass
        self.split_view.setZoomFactor(0.95)
        self.split_body_layout.addWidget(self.split_view)
        return self.split_view

    def open_split_view(self, url: str, title: str = "Split"):
        """Show a second live page beside the main one."""
        url = (url or "").strip()
        if not url or url in ("about:blank", "about:newtab"):
            self._flash_status("Split view needs a real page URL")
            return
        view = self._ensure_split_view()
        self.lbl_split_title.setText((title or "Split")[:40])
        self._split_url = url
        was_hidden = not self.split_dock.isVisible()
        self.split_dock.show()
        if was_hidden:
            total = max(700, self.panel_split.width())
            self.panel_split.setSizes([max(340, total // 3), total - max(340, total // 3)])
        view.setUrl(QUrl(url))
        self._flash_status("Split view — two pages side by side")

    def close_split_view(self):
        self.split_dock.hide()

    def _split_to_tab(self):
        if self._split_url:
            self.tab_manager.add_tab(QUrl(self._split_url), self.lbl_split_title.text() or "Split", is_active=True)
            self.close_split_view()

    def _build_web_panel_dock(self):
        self.panel_dock = QFrame()
        self.panel_dock.setObjectName("WebPanelDock")
        dock_layout = QVBoxLayout(self.panel_dock)
        dock_layout.setContentsMargins(0, 0, 0, 0)
        dock_layout.setSpacing(0)

        header = QFrame()
        header.setObjectName("WebPanelHeader")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(8, 3, 6, 3)
        header_layout.setSpacing(4)
        self.lbl_panel_title = QLabel("Panel")
        self.lbl_panel_title.setObjectName("PageTitle")
        f = self.lbl_panel_title.font()
        f.setPointSize(9)
        f.setBold(True)
        self.lbl_panel_title.setFont(f)
        header_layout.addWidget(self.lbl_panel_title, 1)
        self.btn_panel_pop = QToolButton()
        self.btn_panel_pop.setObjectName("TopIconButton")
        self.btn_panel_pop.setText("↗")
        self.btn_panel_pop.setToolTip("Open this panel as a full tab")
        self.btn_panel_pop.clicked.connect(self._open_panel_in_tab)
        self.btn_panel_reload = QToolButton()
        self.btn_panel_reload.setObjectName("TopIconButton")
        self.btn_panel_reload.setText("⟳")
        self.btn_panel_reload.setToolTip("Reload panel")
        self.btn_panel_reload.clicked.connect(lambda: self._ensure_panel_view().reload())
        self.btn_panel_close = QToolButton()
        self.btn_panel_close.setObjectName("TopIconButton")
        self.btn_panel_close.setText("✕")
        self.btn_panel_close.setToolTip("Close panel")
        self.btn_panel_close.clicked.connect(self.close_web_panel)
        header_layout.addWidget(self.btn_panel_pop)
        header_layout.addWidget(self.btn_panel_reload)
        header_layout.addWidget(self.btn_panel_close)
        dock_layout.addWidget(header, 0)

        # The WebEngine view is attached later by _ensure_panel_view(), after
        # the shared QWebEngineProfile exists.
        self.panel_view = None
        self._panel_last_url = prefs.get_last_web_panel(self.base_dir)[1] or ""
        self.panel_body = QWidget()
        self.panel_body_layout = QVBoxLayout(self.panel_body)
        self.panel_body_layout.setContentsMargins(0, 0, 0, 0)
        dock_layout.addWidget(self.panel_body, 1)
        self.panel_dock.setMinimumWidth(300)
        self.panel_dock.setMaximumWidth(620)

    def _ensure_panel_view(self):
        if getattr(self, "panel_view", None) is not None:
            return self.panel_view
        self.panel_view = QWebEngineView(self.panel_dock)
        self.panel_view.setObjectName("WebPanelView")
        try:
            self.panel_view.setPage(browser_page.BrowserPage(self.profile, self.panel_view, self.base_dir, host=self))
        except Exception:
            pass
        self.panel_view.setZoomFactor(0.9)
        self.panel_body_layout.addWidget(self.panel_view)
        return self.panel_view

    def toggle_web_panel(self, title="", url=""):
        """Show/hide the panel dock; a new preset replaces the current URL."""
        url = (url or "").strip()
        if self.panel_dock.isVisible() and not url:
            self.close_web_panel()
            return
        panel_view = self._ensure_panel_view()
        if url:
            self.lbl_panel_title.setText(title or "Panel")
            self._panel_last_url = url
            prefs.set_last_web_panel(self.base_dir, title, url)
            panel_view.setUrl(QUrl(url))
        if not self.panel_dock.isVisible():
            self.panel_dock.show()
            prefs.set_web_panel_visible(self.base_dir, True)
            total = max(600, self.panel_split.width())
            self.panel_split.setSizes([max(420, total - 380), 380])
        panel_view.setFocus()

    def close_web_panel(self):
        self.panel_dock.hide()
        self.btn_rail_panels.setChecked(False)
        prefs.set_web_panel_visible(self.base_dir, False)

    def toggle_ai_sidebar(self):
        """Edge-Copilot-style: dock the page-aware assistant beside the web."""
        if self.ai_dock.isVisible():
            self.ai_dock.hide()
            self.btn_rail_ai.setChecked(False)
            return
        self.ai_dock.show()
        self.btn_rail_ai.setChecked(True)
        total = max(600, self.panel_split.width())
        self.panel_split.setSizes([max(420, total - 360), 360])
        self.inline_ai_input.setFocus()
        if not self.inline_ai_answer.toPlainText().strip():
            self.inline_ai_answer.setPlainText(
                "Ask anything about the page you are viewing.\n\n"
                "The assistant reads the visible page text and answers with full context."
            )

    def close_ai_sidebar(self):
        self.ai_dock.hide()

    def _open_panel_in_tab(self):
        url = self._panel_last_url or ""
        if url:
            self.tab_manager.add_tab(QUrl(url), self.lbl_panel_title.text() or "Panel", is_active=True)

    def show_web_panel_menu(self):
        menu = QMenu(self)
        for name, glyph, url in self.WEB_PANEL_PRESETS:
            act = menu.addAction(f"{glyph}  {name}")
            act.triggered.connect(lambda _c=False, n=name, u=url: self.toggle_web_panel(n, u))
        menu.addSeparator()
        custom = menu.addAction("⌨  Custom URL...")
        custom.triggered.connect(self._open_custom_panel)
        menu.addSeparator()
        if self.panel_dock.isVisible():
            close_act = menu.addAction("✕  Close panel")
            close_act.triggered.connect(self.close_web_panel)
        menu.exec_(self.cursor().pos())

    def _open_custom_panel(self):
        text, ok = QInputDialog.getText(self, "Web panel", "Panel URL:")
        if ok and (text or "").strip():
            url = text.strip()
            if not url.startswith(("http://", "https://")):
                url = "https://" + url
            self.toggle_web_panel("Custom", url)
