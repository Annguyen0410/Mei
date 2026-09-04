import os
import sys
import time
import webbrowser
from concurrent.futures import ThreadPoolExecutor

from PyQt5.QtCore import QUrl, QRect, Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QIcon, QKeySequence
from PyQt5.QtWidgets import (
    QApplication,
    QCompleter,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QShortcut,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from litebrowser.core import app_paths, app_version, prefs
from litebrowser.services import (
    history_service,
    life_service,
    personal_service,
    security,
    update_service,
    workspace_manager,
)
from litebrowser.ui import components, dialogs, theme, win_titlebar
from litebrowser.ui.ai_window import AIWindow
from litebrowser.ui.main_window import SearchWindow
from litebrowser.ui.personal_window import PersonalWindow
from litebrowser.ui.shell.pages import (
    HistoryPage,
    HomeDashboardPage,
    LibraryPage,
    SettingsPage,
    _format_ts,
)


class AppShell(QMainWindow):
    update_checked = pyqtSignal(object, bool)
    update_downloaded = pyqtSignal(object, object)
    sync_finished = pyqtSignal(bool, str)
    monitor_checked = pyqtSignal(object)

    def __init__(self, profile_dir: str, app_dir: str = None, window_slot: str = "primary", browser_workspace_id: str | None = None):
        super().__init__()
        self._closing = False
        self.profile_dir = prefs.ensure_profile_layout(profile_dir)
        self.app_dir = app_dir or app_paths.project_root()
        self.window_slot = window_slot
        self.browser_workspace_id = browser_workspace_id or workspace_manager.PRIMARY_WORKSPACE_ID
        self._unlocked_spaces = set()
        self._executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="shell")
        self._update_check_running = False
        self._update_install_running = False
        self._pending_update_info = None
        self.update_status_text = f"Installed version: {app_version.APP_VERSION}"
        self._insight_cache = None
        self._insight_cache_time = 0
        self._insights_user_toggled = False
        self.update_checked.connect(self._finish_update_check)
        self.update_downloaded.connect(self._finish_downloaded_update)
        self.sync_finished.connect(self._show_sync_result)
        self.monitor_checked.connect(self._on_monitor_checked)
        title_suffix = "Workspace 1" if self.window_slot == "primary" else "Workspace 2"
        self.setWindowTitle(f"Mei Tea Room Edition - {title_suffix}")
        self.setWindowIcon(QIcon(os.path.join(self.app_dir, "icon.png")))
        self.resize(1560, 940)
        self.setMinimumSize(760, 560)
        win_titlebar.apply_dark_titlebar(self, enabled=True)

        root = QWidget()
        root.setObjectName("ShellRoot")
        self.setCentralWidget(root)
        shell_layout = QVBoxLayout(root)
        shell_layout.setContentsMargins(0, 0, 0, 0)
        shell_layout.setSpacing(0)
        self._rail_collapsed = False
        self._topbar_collapsed = False

        # ---------- App top bar: brand + omnibar + actions ----------
        top_bar = QWidget()
        top_bar.setObjectName("ShellTopBar")
        top_layout = QHBoxLayout(top_bar)
        top_layout.setContentsMargins(14, 10, 14, 10)
        top_layout.setSpacing(10)

        brand_wrap = QWidget()
        brand_wrap.setObjectName("BrandWrap")
        brand_layout = QHBoxLayout(brand_wrap)
        brand_layout.setContentsMargins(0, 0, 0, 0)
        brand_layout.setSpacing(8)
        brand_glyph = QLabel("ðŸµ")
        brand_glyph.setObjectName("BrandGlyph")
        brand_layout.addWidget(brand_glyph)
        brand_text = QVBoxLayout()
        brand_text.setContentsMargins(0, 0, 0, 0)
        brand_text.setSpacing(0)
        brand_name = QLabel("Mei")
        brand_name.setObjectName("BrandName")
        brand_text.addWidget(brand_name)
        brand_sub = QLabel("YOUR DIGITAL TEA ROOM")
        brand_sub.setObjectName("BrandSub")
        brand_text.addWidget(brand_sub)
        brand_layout.addLayout(brand_text)
        top_layout.addWidget(brand_wrap)

        self.omnibar = QLineEdit()
        self.omnibar.setObjectName("ShellOmnibar")
        self.omnibar.setPlaceholderText("Search the web or run a command  ·  /task  /note  /ask")
        self._omnibar_completer = QCompleter([
            "/home", "/browser", "/history", "/ai", "/personal",
            "/library", "/settings", "/cql", "/guide", "/help",
            "/hub", "/linklumina", "/mas", "/leaderboard", "/bimat", "/boitoan",
            "/task ", "/note ", "/board ", "/save-page", "/ask ",
            "/read", "/reading-list",
            "/focus ", "/status", "/cafe",
            "/freeze", "/save-tabs ", "/summarize",
            "/brief", "/agent ", "/group-tabs", "/sync",
        ], self)
        self._omnibar_completer.setCaseSensitivity(Qt.CaseInsensitive)
        self._omnibar_completer.setFilterMode(Qt.MatchStartsWith)
        self.omnibar.setCompleter(self._omnibar_completer)
        self.omnibar.addAction(self.style().standardIcon(self.style().SP_FileDialogContentsView), QLineEdit.LeadingPosition)
        top_layout.addWidget(self.omnibar, 1)

        # Keyboard-first shell: Ctrl+K jumps to the omnibar, Ctrl+1..7 switch
        # straight to a workspace without touching the mouse.
        QShortcut(QKeySequence("Ctrl+K"), self).activated.connect(self._focus_omnibar)
        _workspace_order = ["home", "browser", "history", "ai", "personal", "library", "settings"]
        for _index, _name in enumerate(_workspace_order, start=1):
            _shortcut = QShortcut(QKeySequence("Ctrl+%d" % _index), self)
            _shortcut.activated.connect(lambda _n=_name: self.switch_workspace(_n))

        self.btn_sync = QPushButton("↻  Snapshot")
        self.btn_sync.setObjectName("CafeButton")
        self.btn_sync.setToolTip("Save a local snapshot of your profile state (tasks/notes/boards) to disk.")
        self.btn_insights = QPushButton("✦  Insights")
        self.btn_insights.setObjectName("CafeButton")
        top_layout.addWidget(self.btn_sync)
        top_layout.addWidget(self.btn_insights)
        self.btn_toggle_topbar = QPushButton("▾")
        self.btn_toggle_topbar.setObjectName("TopIconButton")
        self.btn_toggle_topbar.setToolTip("Collapse / expand the top bar")
        self.btn_toggle_topbar.clicked.connect(self._toggle_topbar)
        top_layout.addWidget(self.btn_toggle_topbar)
        self._top_bar = top_bar
        shell_layout.addWidget(top_bar)

        # Omnibar hints from the shared registry (core.commands): descriptions
        # stay in sync with the palette and docs automatically.
        _hint_examples = {
            "/task": "/task Prepare report",
            "/note": "/note Work/Brief | body",
            "/board": "/board Sprint map",
            "/ask": "/ask …",
            "/focus": "/focus 25 (minutes)",
            "/save-tabs": "/save-tabs Research",
            "/theme": "/theme matcha-day",
            "/accent": "/accent matcha",
            "/template": "/template daily",
            "/agent": "/agent summary",
        }
        self._command_hints = {}
        from litebrowser.core.commands import COMMANDS as _cmd_registry

        for _cmd, _takes_arg, _desc in _cmd_registry:
            _example = _hint_examples.get(_cmd, "")
            self._command_hints[_cmd] = f"{_desc} · {_example}" if _example else _desc

        self.split = QSplitter(Qt.Horizontal)
        shell_layout.addWidget(self.split, 1)

        rail = QWidget()
        rail.setObjectName("LeftRail")
        rail_layout = QVBoxLayout(rail)
        rail_layout.setContentsMargins(6, 10, 6, 10)
        rail_layout.setSpacing(4)
        self.btn_rail_toggle = QPushButton("«")
        self.btn_rail_toggle.setObjectName("NavToggle")
        self.btn_rail_toggle.setToolTip("Collapse / expand the navigation rail")
        rail_layout.addWidget(self.btn_rail_toggle, 0, Qt.AlignRight)
        profile_name = os.path.basename(self.profile_dir)
        self.rail_meta = QLabel(f"Profile: {profile_name}")
        self.rail_meta.setObjectName("RailMeta")
        self.rail_meta.setWordWrap(True)
        rail_layout.addWidget(self.rail_meta)
        self.nav_buttons = {}
        self.rail_section_labels = []
        nav_sections = (
            (
                "START",
                (
                    ("home", "Home", "◧"),
                    ("browser", "Browser", "↗"),
                    ("history", "History", "◷"),
                ),
            ),
            (
                "MAKE & KEEP",
                (
                    ("ai", "AI Workspace", "✦"),
                    ("personal", "Personal", "▲"),
                    ("library", "Library", "▤"),
                ),
            ),
            ("SETUP", (("settings", "Settings", "⚙"),)),
        )
        for section_name, section_items in nav_sections:
            section_label = QLabel(section_name)
            section_label.setObjectName("RailSectionLabel")
            self.rail_section_labels.append(section_label)
            rail_layout.addWidget(section_label)
            for key, label, glyph in section_items:
                button = components.nav_button(label, glyph)
                button.clicked.connect(lambda checked, item=key: self.switch_workspace(item))
                self.nav_buttons[key] = button
                rail_layout.addWidget(button)
        rail_layout.addStretch(1)
        self.lbl_sync_state = QLabel("")
        self.lbl_sync_state.setObjectName("RailMeta")
        self.lbl_sync_state.setWordWrap(True)
        rail_layout.addWidget(self.lbl_sync_state)
        self._rail = rail
        self._rail_children = [self.rail_meta] + list(self.rail_section_labels) + list(self.nav_buttons.values()) + [self.lbl_sync_state]
        self.split.addWidget(rail)

        center_wrap = QWidget()
        center_layout = QVBoxLayout(center_wrap)
        center_layout.setContentsMargins(4, 4, 4, 4)
        center_layout.setSpacing(4)
        self.stack = QStackedWidget()
        center_layout.addWidget(self.stack, 1)

        self.status_strip = QWidget()
        self.status_strip.setObjectName("StatusStrip")
        status_layout = QHBoxLayout(self.status_strip)
        status_layout.setContentsMargins(8, 3, 8, 3)
        status_layout.setSpacing(8)
        self.lbl_status = QLabel("")
        self.lbl_status.setObjectName("StatusPill")
        self.lbl_status_context = QLabel("")
        self.lbl_status_context.setObjectName("MutedLabel")
        status_layout.addWidget(self.lbl_status)
        status_layout.addWidget(self.lbl_status_context)
        status_layout.addStretch(1)
        status_theme = QLabel("")
        status_theme.setObjectName("MutedLabel")
        status_layout.addWidget(status_theme)
        self.lbl_theme_pill = status_theme
        center_layout.addWidget(self.status_strip)
        self.split.addWidget(center_wrap)

        self.insights = QFrame()
        self.insights.setObjectName("InsightPanel")
        insights_layout = QVBoxLayout(self.insights)
        insights_layout.setContentsMargins(8, 8, 8, 8)
        insights_layout.setSpacing(6)
        insights_title = QLabel("Ambient Insights")
        insights_title.setObjectName("SectionTitle")
        insights_layout.addWidget(insights_title)
        self.insight_list = QListWidget()
        self.insight_list.setObjectName("CafeList")
        insights_layout.addWidget(self.insight_list, 1)
        sleeping_card = QFrame()
        sleeping_card.setObjectName("SectionCard")
        sleeping_layout = QVBoxLayout(sleeping_card)
        sleeping_layout.setContentsMargins(8, 8, 8, 8)
        sleeping_layout.setSpacing(4)
        sleeping_title = QLabel("Sleeping Tabs")
        sleeping_title.setObjectName("SectionTitle")
        sleeping_layout.addWidget(sleeping_title)
        self.sleeping_tabs_list = QListWidget()
        self.sleeping_tabs_list.setObjectName("CafeList")
        sleeping_layout.addWidget(self.sleeping_tabs_list)
        insights_layout.addWidget(sleeping_card)
        assistant_card = QFrame()
        assistant_card.setObjectName("SectionCard")
        assistant_layout = QVBoxLayout(assistant_card)
        assistant_layout.setContentsMargins(8, 8, 8, 8)
        assistant_layout.setSpacing(5)
        assistant_layout.addWidget(QLabel("Assistant"))
        self.lbl_assistant_scope = QLabel("Context: current workspace")
        self.lbl_assistant_scope.setObjectName("MutedLabel")
        assistant_layout.addWidget(self.lbl_assistant_scope)
        self.ed_ai_quick = QLineEdit()
        self.ed_ai_quick.setPlaceholderText("Ask AI from anywhere...")
        assistant_layout.addWidget(self.ed_ai_quick)
        quick_row = QHBoxLayout()
        self.btn_ai_current = QPushButton("Ask here")
        self.btn_ai_global = QPushButton("Whole profile")
        quick_row.addWidget(self.btn_ai_current)
        quick_row.addWidget(self.btn_ai_global)
        assistant_layout.addLayout(quick_row)
        self.ai_preview = QLabel("Assistant replies will open in AI Workspace.")
        self.ai_preview.setWordWrap(True)
        self.ai_preview.setObjectName("MutedLabel")
        assistant_layout.addWidget(self.ai_preview)
        insights_layout.addWidget(assistant_card)
        self.split.addWidget(self.insights)
        # Collapsible(True) let a 0-width setSizes entry permanently collapse
        # the Insights pane - un-draggable afterwards (pre-1.0 layout bug).
        self.split.setChildrenCollapsible(False)
        self.split.setStretchFactor(0, 0)
        self.split.setStretchFactor(1, 1)
        self.split.setStretchFactor(2, 0)
        self.split.setSizes([165, 1160, 235])

        self.home_page = HomeDashboardPage(self)
        self.browser_page = SearchWindow(
            self.profile_dir, app_dir=self.app_dir, embedded=True, window_slot=self.window_slot
        )
        self.browser_page.set_workspace_id(self.browser_workspace_id, persist=False)
        self.history_page = HistoryPage(self)
        self.ai_page = AIWindow(self.profile_dir, app_dir=self.app_dir, embedded=True)
        self.personal_page = PersonalWindow(self.profile_dir, app_dir=self.app_dir, embedded=True)
        self.library_page = LibraryPage(self)
        self.settings_page = SettingsPage(self)
        self.settings_page.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        self.stack.addWidget(self.home_page)
        self.stack.addWidget(self.browser_page)
        self.stack.addWidget(self.history_page)
        self.stack.addWidget(self.ai_page)
        self.stack.addWidget(self.personal_page)
        self.stack.addWidget(self.library_page)
        self.stack.addWidget(self.settings_page)
        self.workspace_index = {
            "home": 0,
            "browser": 1,
            "history": 2,
            "ai": 3,
            "personal": 4,
            "library": 5,
            "settings": 6,
        }

        self.omnibar.returnPressed.connect(self.handle_omnibar)
        self.omnibar.textChanged.connect(self._update_omnibar_hint)
        self.btn_sync.clicked.connect(self._run_sync_now)
        self.btn_insights.clicked.connect(self.toggle_insights)
        self.btn_rail_toggle.clicked.connect(self._toggle_rail)
        self.btn_ai_current.clicked.connect(lambda: self.ask_ai_from_shell(scope="current"))
        self.btn_ai_global.clicked.connect(lambda: self.ask_ai_from_shell(scope="global"))
        self.ed_ai_quick.returnPressed.connect(lambda: self.ask_ai_from_shell(scope="current"))

        self._restore_window_state()
        # First-run experience: if there is no persisted session, land on the
        # Home dashboard so users see the hub. Restored sessions already open
        # tabs in the Browser workspace conceptually — keep them on Browser.
        has_persisted_tabs = bool(prefs.session_state_load(self.profile_dir).get("tabs"))
        self.switch_workspace("browser" if has_persisted_tabs else "home")
        # Both app windows need the shared stylesheet immediately.  Previously
        # only the primary workspace ran this deferred pass, leaving the second
        # window looking like an unstyled collection of default Qt controls.
        QTimer.singleShot(50, self._deferred_init)

    def _announce_focus(self, status: dict):
        """Show the running focus timer state in the status strip."""
        if status.get("running"):
            remaining = int(status.get("remaining", 0))
            mm, ss = divmod(remaining, 60)
            self.lbl_status.setText("ðŸµ Focus: %02d:%02d left — %s" % (mm, ss, status.get("session", {}).get("label", "")))
        else:
            self.lbl_status.setText("No café focus pour running. Try /focus 25")

    def _run_sync_now(self):
        """Flush the local change ledger: reset the pending counter and stamp the time.

        There is no remote backend in this build -- "sync" here means committing the
        profile's local state to disk and clearing the pending-changes counter that the
        rail displays, so the user gets honest feedback instead of a dead button.
        """
        try:
            state = life_service.load_sync_state(self.profile_dir)
            state["pending_changes"] = 0
            state["last_sync_at"] = int(time.time())
            life_service.save_sync_state(self.profile_dir, state)
            history_service.log_event(self.profile_dir, "account", "Local sync flush", "Pending changes cleared", {})
        except Exception:
            pass
        # A cheap read-back makes the rail reflect the flush immediately.
        self._insight_cache = None
        self.refresh_shell()

    def toggle_insights(self):
        self._insights_user_toggled = True
        self.insights.setVisible(not self.insights.isVisible())
        if self.insights.isVisible():
            theme.animate_entrance(self.insights)
        self._apply_compact_shell_layout()

    def _toggle_rail(self):
        self._rail_collapsed = not getattr(self, "_rail_collapsed", False)
        self._apply_compact_shell_layout()

    def _toggle_topbar(self):
        self._topbar_collapsed = not getattr(self, "_topbar_collapsed", False)
        self._apply_topbar_collapse()

    def _apply_topbar_collapse(self):
        """Hide every top-bar widget except the collapse toggle, then restore."""
        collapsed = getattr(self, "_topbar_collapsed", False)
        if hasattr(self, "btn_toggle_topbar"):
            self.btn_toggle_topbar.setText("▴" if collapsed else "▾")
        top_bar = getattr(self, "_top_bar", None)
        if top_bar is None:
            return
        layout = top_bar.layout()
        for index in range(layout.count()):
            item = layout.itemAt(index)
            widget = item.widget() if item else None
            if widget is not None and widget is not self.btn_toggle_topbar:
                widget.setVisible(not collapsed)
        top_bar.setMaximumHeight(26 if collapsed else 16777215)
        top_bar.setMinimumHeight(24 if collapsed else 0)

    def _update_omnibar_hint(self, text: str):
        parts = (text or "").strip().split(None, 1)
        command = parts[0].lower() if parts else ""
        hint = self._command_hints.get(command)
        if hint:
            self.lbl_status_context.setText(hint)
        elif parts:
            # Only clear when the user is typing a non-command query; keep the
            # last status line otherwise so it does not flicker on every edit.
            self.lbl_status_context.setText("Web search — press Enter")

    def refresh_shell(self, force_deep: bool = False):
        # Distraction Shield follows the focus session; refresh_shell runs on
        # every command + the auto-theme tick, so the shield flips within ~5 min.
        self._refresh_shield_state()
        # Auto theme: the café flips day/night palettes with the clock when on.
        theme_name = prefs.resolved_auto_theme(self.profile_dir)
        # Re-polishing 8 top-level widgets reparses a ~790-line QSS sheet and
        # repaints every child. Only do it when the theme/accent actually
        # changed (v6.4 did it for every omnibar command — visible lag).
        qss_key = (theme_name, prefs.get_accent(self.profile_dir))
        if force_deep or qss_key != getattr(self, "_qss_key", None):
            self._qss_key = qss_key
            qss = theme.main_qss(theme_name, prefs.get_accent(self.profile_dir))
            self.setStyleSheet(qss)
            for widget in (
                self.home_page,
                self.browser_page,
                self.history_page,
                self.ai_page,
                self.personal_page,
                self.library_page,
                self.settings_page,
            ):
                widget.setStyleSheet(qss)
            # Popups are separate top-levels: keep the tray menu on-theme.
            tray = getattr(self, "tray", None)
            if tray is not None and tray.contextMenu() is not None:
                tray.contextMenu().setStyleSheet(qss)
        self.home_page.refresh()
        self.history_page.refresh()
        self.library_page.refresh(self.library_page.ed_search.text().strip())
        self.settings_page.refresh()
        account = life_service.load_sync_account(self.profile_dir)
        sync_state = life_service.load_sync_state(self.profile_dir)
        status = account.get("display_name") or "Offline-ready"
        self.lbl_sync_state.setText(f"{status}\npending {int(sync_state.get('pending_changes', 0) or 0)}")
        self.lbl_status.setText(f"▲ Theme: {theme_name}")
        self.lbl_status_context.setText(f"Last sync: {_format_ts(int(sync_state.get('last_sync_at', 0) or 0))}")
        self.lbl_theme_pill.setText(f"{theme_name} · {prefs.get_accent(self.profile_dir)}")
        self._refresh_insights()
        self._apply_compact_shell_layout()
        if self.stack.currentIndex() == self.workspace_index["personal"]:
            self.personal_page.refresh_all()

    def _sync_auto_theme_timer(self):
        """Start/stop the auto-theme watcher to match the saved preference."""
        if prefs.get_auto_theme(self.profile_dir):
            if getattr(self, "_auto_theme_timer", None) is None or not self._auto_theme_timer.isActive():
                self._auto_theme_timer = QTimer(self)
                self._auto_theme_timer.setInterval(5 * 60 * 1000)
                self._auto_theme_timer.timeout.connect(self.refresh_shell)
                self._auto_theme_timer.start()
        elif getattr(self, "_auto_theme_timer", None) is not None:
            self._auto_theme_timer.stop()
        self.refresh_shell()

    def _deferred_init(self):
        self.refresh_shell()
        if self.window_slot == "primary":
            QTimer.singleShot(1500, self._startup_update_check)
            # First-run wizard: once per profile, skippable at every step.
            if not prefs.get_pref(self.profile_dir, "onboarding_done", False):
                QTimer.singleShot(900, lambda: self._safe_onboarding())
            self._init_tray()
            self._init_break_reminders()
            self._init_routines_timer()
            self._init_page_monitor()

    def _init_page_monitor(self):
        """Poll watched pages every 15 min on the executor (raw HTML hash)."""
        self._monitor_timer = QTimer(self)
        self._monitor_timer.setInterval(5 * 60 * 1000)
        self._monitor_timer.timeout.connect(self._check_page_monitors)
        self._monitor_timer.start()

    def _check_page_monitors(self):
        from litebrowser.services import page_monitor

        due = page_monitor.due_monitors(self.profile_dir)
        if not due:
            return

        def _run():
            outcomes = []
            for monitor in due:
                content_hash = page_monitor.fetch_and_hash(monitor["url"])
                if content_hash is None:
                    continue
                outcome = page_monitor.record_check(self.profile_dir, monitor["id"], content_hash)
                outcomes.append((monitor["title"], outcome))
            return outcomes

        # Marshal back to the GUI thread via a queued signal (same pattern as
        # update_checked); AppShell has no _worker_relay - that lives on the
        # browser window.
        future = self._executor.submit(_run)
        future.add_done_callback(lambda f: self.monitor_checked.emit(f))

    def _on_monitor_checked(self, future):
        if self._closing:
            return
        try:
            outcomes = future.result() or []
        except Exception:
            return
        for title, outcome in outcomes:
            if outcome == "changed":
                self.system_notify("Page changed 📄", title)

    def _init_routines_timer(self):
        """30s scheduler tick — fires due routines once per day each."""
        self._routines_timer = QTimer(self)
        self._routines_timer.setInterval(30 * 1000)
        self._routines_timer.timeout.connect(self._tick_routines)
        self._routines_timer.start()

    def _tick_routines(self):
        from litebrowser.services import routines_service

        for routine in routines_service.due_routines(self.profile_dir):
            routines_service.mark_fired(self.profile_dir, routine["id"], time.strftime("%Y-%m-%d"))
            self.system_notify("Routine: " + routine["name"], " · ".join(routine["actions"][:3]))
            for action in routine["actions"]:
                if action.startswith("/"):
                    self.omnibar.setText(action)
                    self.handle_omnibar()
                elif " " not in action and "." in action:
                    url = action if action.startswith("http") else "https://" + action
                    self.browser_page.add_new_tab(QUrl(url), routine["name"], is_active=False)

    def _init_tray(self):
        """System tray (primary shell only): quick actions + native toasts."""
        try:
            from PyQt5.QtWidgets import QSystemTrayIcon

            if not QSystemTrayIcon.isSystemTrayAvailable():
                return
            from litebrowser.ui.tray import MeiTray

            self.tray = MeiTray(self)
        except Exception:
            self.tray = None
        self._init_global_hotkey()

    def _init_global_hotkey(self):
        """Ctrl+Alt+M anywhere in Windows opens the quick-note overlay.

        Uses RegisterHotKey via ctypes; if the OS refuses (already taken,
        restricted session) we degrade to tray-only — no crash, no nag."""
        if not sys.platform.startswith("win"):
            return
        try:
            import ctypes
            import ctypes.wintypes  # noqa: F401  (submodule — NOT auto-imported)

            self._hotkey_msg_id = 0xB00B  # app-local WM_HOTKEY identifier
            MOD_CONTROL, MOD_ALT = 0x0002, 0x0001
            if not ctypes.windll.user32.RegisterHotKey(None, self._hotkey_msg_id, MOD_CONTROL | MOD_ALT, ord("M")):
                self._hotkey_msg_id = None
                return
            # Poll-based check is heavier than a nativeEventFilter, but ctypes
            # callbacks into a Qt app need a message window; a 1s PeekMessage
            # loop on a timer thread is the pragmatic free route.
            self._hotkey_timer = QTimer(self)
            self._hotkey_timer.setInterval(400)

            def _poll():
                # Guard every tick: an exception escaping a Qt slot can abort
                # the whole process (PyQt5 default excepthook policy).
                try:
                    msg = ctypes.wintypes.MSG()
                    while ctypes.windll.user32.PeekMessageW(
                        ctypes.byref(msg), None, 0x0312, 0x0312, 0x0001
                    ):  # PM_REMOVE, WM_HOTKEY range
                        if msg.message == 0x0312 and msg.wParam == self._hotkey_msg_id:
                            self._open_quick_note_overlay()
                except Exception:
                    self._hotkey_timer.stop()

            self._hotkey_timer.timeout.connect(_poll)
            self._hotkey_timer.start()
        except Exception:
            self._hotkey_msg_id = None

    def _open_quick_note_overlay(self):
        """Global quick capture: focus Mei, jump to a fresh note box."""
        self.showNormal()
        self.raise_()
        self.activateWindow()
        self.switch_workspace("personal")
        page = self.personal_page
        if hasattr(page, "_switch_page"):
            page._switch_page("notes")
        if hasattr(page, "note_editor"):
            page.note_editor.setFocus()

    def system_notify(self, title: str, message: str):
        """Native toast via the tray when available; in-app toast otherwise."""
        tray = getattr(self, "tray", None)
        if tray is not None and tray.isVisible():
            tray.notify(title, message)
        else:
            self._flash_status(f"{title} — {message}")

    def _init_break_reminders(self):
        """20-20-20 eye rest + a nudge when a focus pour ends (30s check)."""
        self._break_timer = QTimer(self)
        self._break_timer.setInterval(30 * 1000)
        self._break_timer.timeout.connect(self._check_breaks)
        self._break_timer.start()
        self._last_break_nudge = 0

    def _check_breaks(self):
        from litebrowser.services import focus_service

        now = time.time()
        session = focus_service.focus_status(self.profile_dir)
        if session.get("running"):
            remaining = int(session.get("remaining", 0) or 0)
            # A 20-20-20 nudge every 20 minutes inside a long pour.
            if 0 < remaining and (remaining % 1200) < 30 and now - self._last_break_nudge > 300:
                self._last_break_nudge = now
                self.system_notify("Eye break ☕", "Look 20 feet away for 20 seconds.")
        # Pour just finished → celebrate + suggest a stand-up break.
        if getattr(self, "_pour_was_running", False) and not session.get("running"):
            self.system_notify("Pour finished ☕", "Stand up, stretch, refill your cup.")
        self._pour_was_running = bool(session.get("running"))

    def _safe_onboarding(self):
        try:
            from litebrowser.ui.onboarding import show_onboarding

            show_onboarding(self)
        except Exception:
            pass
        # Auto theme watch: refresh_shell re-evaluates resolved_auto_theme; a
        # cheap no-op when the palette is unchanged (signature-keyed re-polish).
        self._sync_auto_theme_timer()

    def _startup_update_check(self):
        self.run_update_check(manual=False)

    def open_release_page(self, url: str | None = None):
        target = (url or app_version.RELEASES_PAGE_URL or "").strip()
        if not target:
            QMessageBox.information(
                self,
                "Updates",
                "No release page is configured in this build. "
                "Set LITEBROWSER_RELEASES_PAGE_URL when publishing a fork.",
            )
            return
        webbrowser.open(target)

    def run_update_check(self, manual: bool = False):
        if self._update_check_running:
            if manual:
                QMessageBox.information(self, "Update", "Mei is already checking for updates. Please wait a few seconds and try again.")
            return
        self._update_check_running = True
        self.update_status_text = "Checking for updates..."
        self.refresh_shell()
        future = self._executor.submit(update_service.check_for_updates)
        future.add_done_callback(lambda done: self.update_checked.emit(done, manual))

    def install_available_update(self):
        info = self._pending_update_info
        if not info or not info.has_update:
            QMessageBox.information(self, "Update", "There is no update package ready to install yet.")
            return
        if self._update_install_running:
            QMessageBox.information(self, "Update", "Mei is already downloading the update.")
            return
        if not getattr(sys, "frozen", False):
            QMessageBox.information(
                self,
                "Update",
                "Auto-update that replaces the executable only works in a built .exe. The Python version can only open the release page.",
            )
            self.open_release_page(info.download_url)
            return
        self._update_install_running = True
        self.update_status_text = f"Downloading {info.latest_version}..."
        self.refresh_shell()
        future = self._executor.submit(update_service.download_update_package, info.download_url, info.latest_version)
        future.add_done_callback(lambda done: self.update_downloaded.emit(done, info))

    def _finish_update_check(self, future, manual: bool):
        if self._closing:
            return
        self._update_check_running = False
        try:
            info = future.result() if future is not None else None
        except Exception as exc:
            self.update_status_text = update_service.format_error(exc)
            self.refresh_shell()
            if manual:
                QMessageBox.warning(self, "Update", self.update_status_text)
            return
        if info is None:
            return

        if info.has_update:
            self._pending_update_info = info
            published = f"\nPublished: {info.published_at}" if info.published_at else ""
            notes = f"\n\nNotes:\n{info.notes}" if info.notes else ""
            self.update_status_text = f"A new version {info.latest_version} is available. You are on {info.current_version}."
            self.refresh_shell()
            result = QMessageBox.question(
                self,
                "Update available",
                f"Mei {info.latest_version} is available.{published}\nDownload: {info.download_url}{notes}\n\nDownload and install now?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes,
            )
            if result == QMessageBox.Yes:
                self.install_available_update()
            return

        self._pending_update_info = info
        self.update_status_text = f"You are on the latest version ({info.current_version})."
        self.refresh_shell()
        if manual:
            QMessageBox.information(self, "Update", self.update_status_text)

    def _finish_downloaded_update(self, future, info):
        if self._closing:
            return
        self._update_install_running = False
        try:
            package_path = future.result() if future is not None else None
        except Exception as exc:
            self.update_status_text = update_service.format_error(exc)
            self.refresh_shell()
            QMessageBox.warning(self, "Update", self.update_status_text)
            return
        if package_path is None:
            return

        self.update_status_text = f"Downloaded {info.latest_version}. Applying update..."
        self.refresh_shell()
        try:
            update_service.install_downloaded_update(package_path)
        except Exception as exc:
            self.update_status_text = update_service.format_error(exc)
            self.refresh_shell()
            QMessageBox.warning(self, "Update", self.update_status_text)
            return

        QMessageBox.information(
            self,
            "Update",
            "Mei will close to replace the new .exe, then reopen automatically. Your current session will be saved before quitting.",
        )
        QApplication.instance().quit()

    def _refresh_insights(self):
        now = time.time()
        if self._insight_cache and (now - self._insight_cache_time) < 10:
            cached_snap, cached_texts = self._insight_cache
            self.insight_list.clear()
            for text in cached_texts:
                self.insight_list.addItem(text)
            self.sleeping_tabs_list.clear()
            self.lbl_assistant_scope.setText(f"Context: {self._current_ai_scope_label()}")
            return
        self.insight_list.clear()
        try:
            snapshot = life_service.get_dashboard_snapshot(self.profile_dir)
        except Exception:
            snapshot = {"tasks_pending": 0, "events_upcoming": [], "saved_pages_total": 0}
        suggestions = [
            f"{snapshot['tasks_pending']} pending tasks",
            f"{len(snapshot['events_upcoming'])} upcoming events",
            f"{snapshot['saved_pages_total']} saved pages",
            "/task <title> to create a task",
            "/note <cat>/<title> to create a note",
            "/ask <question> for AI help",
            "/guide for walkthrough",
        ]
        # Insight AI on: surface the page currently open in the browser so the
        # user sees the assistant can read it (its full text is attached to
        # every /ask while the insights panel is visible).
        if self.insights.isVisible():
            browser = self.browser_page.current_browser()
            if browser is not None:
                url = browser.url().toString()
                if url and url not in ("about:blank", "about:newtab"):
                    title = browser.title() or url
                    suggestions.insert(0, f"Reading browser: {title}")
                    suggestions.insert(1, f"Full page text ready for AI · {url[:56]}")
        for text in suggestions:
            self.insight_list.addItem(text)
        self._insight_cache = (snapshot, suggestions)
        self._insight_cache_time = now
        self.sleeping_tabs_list.clear()
        self.lbl_assistant_scope.setText(f"Context: {self._current_ai_scope_label()}")

    def _window_prefs_key(self):
        return "shell_window_primary" if self.window_slot == "primary" else "shell_window_secondary"

    def _restore_window_state(self):
        pref_key = self._window_prefs_key()
        prefs_data = prefs.load_prefs(self.profile_dir)
        state = prefs_data.get(pref_key, {})
        if isinstance(state, dict):
            x = state.get("x")
            y = state.get("y")
            w = state.get("width")
            h = state.get("height")
            if all(isinstance(v, int) for v in (x, y, w, h)):
                # Validate against current screens: after a monitor change the
                # saved geometry could be off-screen entirely (invisible window).
                visible = False
                for screen in QApplication.screens():
                    if screen.availableGeometry().intersects(QRect(x, y, max(w, 1), max(h, 1))):
                        visible = True
                        break
                if visible:
                    self.setGeometry(x, y, w, h)
                    return
        screen = self.screen()
        if not screen:
            return
        available = screen.availableGeometry()
        left_width = available.width() // 2
        right_width = available.width() - left_width
        if self.window_slot == "primary":
            self.setGeometry(available.x(), available.y(), left_width, available.height())
        else:
            self.setGeometry(available.x() + left_width, available.y(), right_width, available.height())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # Only re-run the full compact pass when a size class boundary is
        # crossed; v6.4 re-set the splitter and ~15 widget properties on every
        # pixel of a window drag, fighting any manual splitter adjustment.
        width = max(0, self.width())
        bucket = 680 if width < 680 else 900 if width < 900 else 1080 if width < 1080 else 1320 if width < 1320 else 1 << 30
        if bucket != getattr(self, "_compact_bucket", None):
            self._compact_bucket = bucket
            self._apply_compact_shell_layout()

    def _apply_compact_shell_layout(self):
        width = max(0, self.width())
        compact = width < 1320
        narrow = width < 1080
        tiny = width < 900
        xtiny = width < 680
        rail_collapsed = getattr(self, "_rail_collapsed", False)

        rail_width = 46 if rail_collapsed else (64 if xtiny else 96 if tiny else 112 if narrow else 126 if compact else 150)
        # A visible Insights panel keeps its width even in the Browser workspace
        # once the user toggled it on, so "bật insight AI" works while browsing.
        insight_visible = self.insights.isVisible()
        insight_width = 0 if not insight_visible else (120 if xtiny else 140 if tiny else 160 if narrow else 185 if compact else 205)
        middle_width = max(320, width - rail_width - insight_width - 18)
        # Only push sizes when the Insights panel just changed visibility; a
        # blind setSizes on every call fought the user's splitter drags and,
        # with setChildrenCollapsible(True), a 0-width entry could COLLAPSE a
        # pane entirely - dragging it afterwards was impossible (pre-1.0 bug).
        if insight_visible != getattr(self, "_last_insight_visible", None):
            self._last_insight_visible = insight_visible
            self.split.setSizes([rail_width, middle_width, insight_width])
        self.split.setChildrenCollapsible(False)

        if hasattr(self, "btn_rail_toggle"):
            self.btn_rail_toggle.setText("»" if rail_collapsed else "«")
        self.omnibar.setMinimumHeight(26 if xtiny else 30 if tiny else 34 if narrow else 36)
        self.btn_sync.setText("↻" if tiny else "↻  Snapshot")
        self.btn_insights.setText("✦" if tiny else "✦  Insights")
        self.lbl_status_context.setVisible(not tiny)
        self.lbl_sync_state.setVisible(not narrow and not rail_collapsed)
        self.lbl_status.setVisible(not xtiny)
        self.omnibar.setPlaceholderText("Search / command..." if not tiny else "Go...")
        self.rail_meta.setVisible(not rail_collapsed)
        for section_label in self.rail_section_labels:
            section_label.setVisible(not tiny and not rail_collapsed)

        for key, button in self.nav_buttons.items():
            labels = {"home": ("Home", "◧"), "browser": ("Browser", "↗"), "history": ("History", "◷"), "ai": ("AI", "◈"), "personal": ("Personal", "▲"), "library": ("Library", "▤"), "settings": ("Settings", "⚙")}
            name, glyph = labels.get(key, (key, "▲†"))
            button.setVisible(not rail_collapsed)
            if rail_collapsed or xtiny:
                button.setText(glyph)
            elif tiny:
                button.setText(glyph + "  " + name[:4])
            else:
                button.setText(glyph + "  " + name)
            button.setMinimumHeight(24 if xtiny else 28 if tiny else 30)
            button.setMaximumHeight(26 if xtiny else 30 if tiny else 34)

        self.btn_ai_global.setVisible(not tiny)
        self.ai_preview.setVisible(not narrow)
        self.insight_list.setSpacing(1)
        self.sleeping_tabs_list.setSpacing(1)

    def _save_window_state(self):
        geom = self.geometry()
        data = prefs.load_prefs(self.profile_dir)
        data[self._window_prefs_key()] = {
            "x": int(geom.x()),
            "y": int(geom.y()),
            "width": int(geom.width()),
            "height": int(geom.height()),
        }
        prefs.save_prefs(self.profile_dir, data)

    def set_sleeping_tabs(self, titles):
        self.sleeping_tabs_list.clear()
        titles = list(titles or [])
        if not titles:
            self.sleeping_tabs_list.addItem("No sleeping tabs")
            return
        for title in titles[:12]:
            self.sleeping_tabs_list.addItem(title)

    def switch_workspace(self, name: str) -> bool:
        if name not in self.workspace_index:
            # Unknown workspace names must not raise inside a UI slot.
            return False
        if name in ("ai", "personal") and name not in self._unlocked_spaces:
            if not security.ensure_unlocked(self, self.profile_dir, title=f"Open {name.title()}"):
                return False
            self._unlocked_spaces.add(name)
        previous = self.stack.currentIndex()
        self.stack.setCurrentIndex(self.workspace_index[name])
        for key, button in self.nav_buttons.items():
            button.setChecked(key == name)
        self.lbl_status.setText(f"Workspace: {name}")
        if name == "library":
            self.library_page.refresh(self.library_page.ed_search.text().strip())
        if name == "history":
            self.history_page.refresh()
        if name == "settings":
            self.settings_page.refresh()
        if name == "personal":
            self.personal_page.refresh_all()
        if name == "browser":
            # Keep browsing full-width on first launch, but respect the user's
            # explicit "✦ Insights" toggle (insight AI reads the browser page).
            if not getattr(self, "_insights_user_toggled", False):
                self.insights.hide()
        elif self.insights.isVisible():
            self.insights.show()
        # The insights list reflects the current workspace + browser page, so
        # drop the cache on every workspace switch and rebuild it when visible.
        self._insight_cache = None
        if self.insights.isVisible():
            self._refresh_insights()
        if previous != self.stack.currentIndex() and name != "browser":  # #[c] avoid compositing a QWebEngine surface.
            theme.animate_entrance(self.stack.currentWidget())
        self._apply_compact_shell_layout()
        return True

    def current_browser_widget(self):
        return self.browser_page

    def quick_task_dialog(self):
        title = self.omnibar.text().strip() or "Quick task"
        if title.startswith("/task"):
            title = title[5:].strip() or "Quick task"
        life_service.add_task(self.profile_dir, title)
        self.refresh_shell()
        self.switch_workspace("personal")
        QMessageBox.information(self, "Task", f"Created task: {title}")

    def _focus_omnibar(self):
        """Ctrl+K: focus AND select existing text so typing replaces it (the
        v6.4 binding left the caret mid-string with stale text selected)."""
        self.omnibar.setFocus()
        self.omnibar.selectAll()

    def _normalize_omnibar_cmd(self, text: str):
        return text.lower().strip()

    def _sync_now_worker(self, profile_dir, endpoint, token):
        from litebrowser.services import sync_service

        try:
            ok, msg = sync_service.sync_now(profile_dir, endpoint, token)
        except Exception as exc:
            ok, msg = False, f"Sync failed: {exc}"
        self.sync_finished.emit(bool(ok), str(msg))

    def _show_sync_result(self, ok: bool, msg: str):
        if self._closing:
            return
        self.lbl_status_context.setText(f"Last sync: {time.strftime('%H:%M:%S')}")
        QMessageBox.information(self, "Sync", msg)

    def _refresh_shield_state(self):
        """Push the current shield (focus running / always-on) into every
        TrackingBlocker instance in this shell."""
        for page in (self.browser_page,):
            for interceptor in [getattr(page, "interceptor", None)] + list(getattr(page, "_incognito_interceptors", []) or []):
                if interceptor is not None:
                    try:
                        interceptor._reload_shield_state()
                    except Exception:
                        pass

    def _flash_status(self, message: str):
        """Transient status-line feedback (mirrors SearchWindow's toast but
        lands in the shell's status strip instead)."""
        self.lbl_status.setText(f"● {message}")
        if getattr(self, "_status_restore_timer", None) is None:
            self._status_restore_timer = QTimer(self)
            self._status_restore_timer.setSingleShot(True)
            self._status_restore_timer.timeout.connect(lambda: self.lbl_status.setText(f"● Theme: {prefs.get_shell_theme(self.profile_dir)}"))
        self._status_restore_timer.start(3000)

    def _match_cmd(self, lowered: str, cmd: str) -> bool:
        """Exact command or command-with-argument; never a prefix of a longer
        command (v6.4: ``/brief`` also matched ``/briefcase``, ``/sync`` ate
        ``/syncfoo``)."""
        return lowered == cmd or lowered.startswith(cmd + " ")

    def handle_omnibar(self):
        try:
            text = (self.omnibar.text() or "").strip()
            if not text:
                return
            self._handle_omnibar_text(text)
        finally:
            # Always clear so the next Enter does not re-run the previous command —
            # otherwise typing ``/task buy milk /task ship report`` fires only once
            # and each following Return keeps re-submitting stale text.
            self.omnibar.clear()

    def _handle_omnibar_text(self, text: str):
        lowered = self._normalize_omnibar_cmd(text)
        if lowered in ("/home", "/browser", "/history", "/ai", "/personal", "/library", "/settings"):
            self.switch_workspace(lowered[1:])
            return
        if lowered in ("/cql", "/cuc-quan-ly", "/cu", "/cuc", "/quanly", "/quan-ly"):
            self.switch_workspace("browser")
            self.browser_page.open_bundled_site("cucquanly")
            return
        if lowered in ("/linklumina", "/link", "/lum"):
            self.switch_workspace("browser")
            self.browser_page.open_bundled_site("linklumina")
            return
        if lowered in ("/mas", "/mahoraga", "/adapt"):
            self.switch_workspace("browser")
            self.browser_page.open_bundled_site("mas")
            return
        if lowered in ("/leaderboard", "/rank", "/world"):
            self.switch_workspace("browser")
            self.browser_page.open_bundled_site("worldleaderboard")
            return
        if lowered in ("/bimat", "/personalfrequency", "/personal-frequency"):
            self.switch_workspace("browser")
            self.browser_page.open_bundled_site("bimat")
            return
        if lowered in ("/boitoan", "/boi-toan", "/fortune"):
            self.switch_workspace("browser")
            self.browser_page.open_bundled_site("boitoan")
            return
        if lowered in ("/hub", "/chain", "/projects"):
            self.switch_workspace("browser")
            self.browser_page.open_project_hub()
            return
        if lowered in ("/guide", "/help"):
            dialogs.show_browser_control_center(self.browser_page)
            return
        if lowered == "/ask" or lowered.startswith("/ask "):
            question = text[4:].strip() or "Summarize my current context"
            self.ask_ai_from_shell(scope="current", question=question)
            return
        if lowered == "/task" or lowered.startswith("/task "):
            title = text[5:].strip() or "Quick task"
            life_service.add_task(self.profile_dir, title)
            self._insight_cache = None
            self.refresh_shell()
            self.switch_workspace("personal")
            return
        if lowered == "/note" or lowered.startswith("/note "):
            raw_note = text[5:].strip()
            category = "General"
            title = raw_note or "Untitled note"
            body = ""
            if "|" in raw_note:
                parts = [part.strip() for part in raw_note.split("|")]
                if len(parts) >= 2:
                    category = parts[0] or "General"
                    title = parts[1] or "Untitled note"
                if len(parts) >= 3:
                    body = parts[2]
            elif "/" in raw_note:
                prefix, suffix = raw_note.split("/", 1)
                if prefix.strip() and suffix.strip():
                    category = prefix.strip()
                    title = suffix.strip()
            note = personal_service.create_note(
                self.profile_dir,
                title,
                body or f"# {title}\n\n",
                category=category,
            )
            self._insight_cache = None
            self.refresh_shell()
            self.switch_workspace("personal")
            self.personal_page.select_note(note["id"])
            return
        if lowered == "/board" or lowered.startswith("/board "):
            title = text[6:].strip() or "Idea board"
            life_service.add_board(self.profile_dir, title)
            self._insight_cache = None
            self.refresh_shell()
            self.switch_workspace("personal")
            return
        if self._match_cmd(lowered, "/brief"):
            from litebrowser.services import brief_service
            brief = brief_service.build_morning_brief(self.profile_dir)
            QMessageBox.information(self, "Morning Brief", brief_service.brief_text(brief))
            self.switch_workspace("home")
            return
        if lowered == "/agent" or lowered.startswith("/agent "):
            from litebrowser.services import agent_actions
            arg = text[len("/agent"):].strip()
            if arg == "summary" or arg.startswith("summary"):
                browser = self.current_browser_widget()
                tabs = browser.get_current_tab_state()
                note = agent_actions.summarize_tabs_to_note(self.profile_dir, tabs)
                self.switch_workspace("personal")
                self.personal_page.select_note(note["id"])
            elif arg == "tasks" or arg.startswith("tasks"):
                created = agent_actions.extract_tasks_from_text(self.profile_dir, arg[len("tasks"):].strip())
                self.switch_workspace("personal")
                QMessageBox.information(self, "Agent", "Created %d task(s)." % len(created))
            elif arg == "review" or arg.startswith("review"):
                content = agent_actions.weekly_review(self.profile_dir)
                note = personal_service.create_note(
                    self.profile_dir, "Weekly review %s" % time.strftime("%Y-%m-%d"), content, category="AI"
                )
                self.switch_workspace("personal")
                self.personal_page.select_note(note["id"])
            else:
                QMessageBox.information(
                    self, "Agent",
                    "Commands:\n/agent summary — digest open tabs into a note\n/agent tasks <a | b | c> — turn items into tasks\n/agent review — write a weekly review note",
                )
            return
        if self._match_cmd(lowered, "/sync"):
            endpoint = prefs.get_sync_endpoint(self.profile_dir)
            token = prefs.get_sync_token(self.profile_dir)
            # sync_now does two HTTP round-trips (up to ~30 s); never freeze
            # the GUI thread waiting on the network (v6.4 froze the shell).
            self.lbl_status_context.setText("Syncing...")
            self._executor.submit(self._sync_now_worker, self.profile_dir, endpoint, token)
            return
        if self._match_cmd(lowered, "/group-tabs"):
            self.switch_workspace("browser")
            self.browser_page.group_tabs_action()
            return
        if self._match_cmd(lowered, "/save-page"):
            browser = self.current_browser_widget().current_browser()
            if browser:
                life_service.add_saved_page(self.profile_dir, browser.title() or browser.url().toString(), browser.url().toString())
                self._insight_cache = None
                self.refresh_shell()
            return
        if self._match_cmd(lowered, "/freeze"):
            self.switch_workspace("browser")
            self.browser_page.tab_manager.optimize_memory()
            return
        if lowered == "/save-tabs" or lowered.startswith("/save-tabs "):
            name = text[len("/save-tabs"):].strip() or None
            self.switch_workspace("browser")
            self.browser_page.save_tab_set_named(name)
            return
        if lowered == "/summarize" or lowered.startswith("/summarize "):
            browser = self.current_browser_widget().current_browser()
            if not browser:
                return
            if self.insights.isVisible():
                # Insight AI is on: it already reads the whole browser page, so
                # asking for a summary needs no duplicate text grab.
                self.ask_ai_from_shell(scope="current", question="Briefly summarize this webpage.")
                return

            def _summarize_page(page_text):
                body = (page_text or "").strip()
                if not body:
                    QMessageBox.information(self, "Summarize", "No readable text on this page.")
                    return
                self.ask_ai_from_shell(
                    scope="current",
                    question="Briefly summarize this webpage:\n\n" + body[:6000],
                )

            browser.page().toPlainText(_summarize_page)
            return
        if lowered in ("/read", "/reading-list"):
            self.switch_workspace("browser")
            return
        if self._match_cmd(lowered, "/status"):
            from litebrowser.services import focus_service
            status = focus_service.focus_status(self.profile_dir)
            self._announce_focus(status)
            return
        if self._match_cmd(lowered, "/theme"):
            arg = text[len("/theme"):].strip().lower()
            if not arg:
                themes = ", ".join(sorted(theme.PALETTES.keys()))
                QMessageBox.information(self, "Themes", f"Available themes:\n{themes}\n\nUsage: /theme matcha-day")
                return
            if arg in theme.PALETTES:
                prefs.set_shell_theme(self.profile_dir, arg)
                self._qss_key = None  # force the QSS re-polish
                self.refresh_shell()
                self._flash_status(f"Theme: {theme.theme_display_name(arg)}")
            else:
                QMessageBox.warning(self, "Themes", f"Unknown theme '{arg}'.\n\nAvailable: {', '.join(sorted(theme.PALETTES.keys()))}")
            return
        if self._match_cmd(lowered, "/accent"):
            arg = text[len("/accent"):].strip().lower()
            if not arg:
                accents = ", ".join(sorted(theme.ACCENTS.keys()))
                QMessageBox.information(self, "Accents", f"Available accents:\n{accents}\n\nUsage: /accent matcha")
                return
            if arg in theme.ACCENTS:
                prefs.set_accent(self.profile_dir, arg)
                self._qss_key = None
                self.refresh_shell()
                self._flash_status(f"Accent: {theme.accent_display_name(arg)}")
            else:
                QMessageBox.warning(self, "Accents", f"Unknown accent '{arg}'.\n\nAvailable: {', '.join(sorted(theme.ACCENTS.keys()))}")
            return
        if self._match_cmd(lowered, "/cafe"):
            from litebrowser.services import focus_service
            self.switch_workspace("personal")
            session = focus_service.focus_status(self.profile_dir)
            if session.get("running"):
                QMessageBox.information(
                    self, "Café Focus",
                    "A pour is running (%d min left). Use /focus N to start fresh, /status to poll." % (session.get("remaining", 0) // 60),
                )
            else:
                QMessageBox.information(
                    self, "Café Focus",
                    "Welcome to the café.\n/focus 25 — start a 25 min pour\n/status — check the timer\nRecent pours: %d" % len(focus_service.focus_journal(self.profile_dir)),
                )
            return
        if self._match_cmd(lowered, "/review"):
            self.switch_workspace("personal")
            self.personal_page._switch_page("review")
            return
        if self._match_cmd(lowered, "/routines"):
            dialogs.show_routines_dialog(self)
            return
        if self._match_cmd(lowered, "/export"):
            dialogs.show_export_dialog(self)
            return
        if self._match_cmd(lowered, "/template"):
            from litebrowser.services import note_templates

            arg = text[len("/template"):].strip().lower()
            if arg in ("daily", "day"):
                note = note_templates.create_daily_note(self.profile_dir)
            elif arg in ("weekly", "review"):
                note = note_templates.create_weekly_review(self.profile_dir)
            else:
                QMessageBox.information(
                    self, "Templates",
                    "Usage: /template daily   — today's plan (tasks, events, top sites)\n"
                    "/template weekly   — last-7-days review",
                )
                return
            self._insight_cache = None
            self.refresh_shell()
            self.switch_workspace("personal")
            self.personal_page.select_note(note["id"])
            return
        if lowered == "/focus" or lowered.startswith("/focus "):
            from litebrowser.services import focus_service
            raw = text[len("/focus"):].strip()
            minutes = 25
            label = ""
            for token in raw.split():
                if token.isdigit():
                    minutes = int(token)
                else:
                    label = (label + " " + token).strip()
            session = focus_service.start_focus(self.profile_dir, minutes=minutes, label=label)
            self._refresh_shield_state()
            self._insight_cache = None
            self.refresh_shell()
            QMessageBox.information(
                self, "Café Focus",
                "Pour started — %d min «%s».\nUse /status to check remaining time." % (minutes, session.get("label", "")),
            )
            return
        if text.startswith("http://") or text.startswith("https://") or (" " not in text and "." in text):
            self.switch_workspace("browser")
            self.browser_page.url_bar.setText(text)
            self.browser_page.navigate()
            return
        self.library_page.refresh(text)
        self.switch_workspace("library")

    def open_library_item(self, data: dict):
        kind = data.get("kind", "")
        if kind in ("bookmark", "history", "download", "saved-page", "personal_site"):
            target = data.get("subtitle") or data.get("id") or data.get("target") or ""
            if target.startswith("http") or target.startswith("file://"):
                self.switch_workspace("browser")
                self.browser_page.url_bar.setText(target)
                self.browser_page.navigate()
                return
        if kind == "note":
            self.switch_workspace("personal")
            self.personal_page.select_note(data.get("id", ""))
            return
        if kind in ("task", "event", "board", "board-node"):
            self.switch_workspace("personal")
            self.personal_page.open_life_item(kind, data.get("id", ""))
            return
        subtitle = data.get("subtitle", "")
        if subtitle.startswith("http"):
            self.switch_workspace("browser")
            self.browser_page.url_bar.setText(subtitle)
            self.browser_page.navigate()

    def _current_ai_scope_label(self):
        names = {
            "home": "Home overview",
            "browser": "Current browser page",
            "history": "History archive",
            "ai": "AI workspace",
            "personal": "Current personal page",
            "library": "Library results",
            "settings": "Settings profile",
        }
        current = next((name for name, index in self.workspace_index.items() if index == self.stack.currentIndex()), "home")
        return names.get(current, "Current workspace")

    def _current_ai_context(self):
        current = next((name for name, index in self.workspace_index.items() if index == self.stack.currentIndex()), "home")
        if current == "browser":
            browser = self.browser_page.current_browser()
            if browser:
                return (
                    "Current browser page",
                    f"Title: {browser.title()}\nURL: {browser.url().toString()}\nWorkspace: Browser",
                )
        if current == "personal":
            note_title = self.personal_page.lbl_note_title.text() if hasattr(self.personal_page, "lbl_note_title") else ""
            note_body = self.personal_page.note_editor.toPlainText()[:2000] if getattr(self.personal_page, "current_note_id", None) else ""
            if note_body.strip():
                return ("Current note", f"Title: {note_title}\n\n{note_body}")
            return ("Personal Hub", "Use Personal Hub context: tasks, notes, boards, calendar, files, and sites.")
        if current == "history":
            return ("History archive", f"Recent activity records: {len(history_service.list_activity(self.profile_dir)[:30])}")
        if current == "library":
            query = self.library_page.ed_search.text().strip()
            return ("Library", f"Current library query: {query}")
        return ("Workspace", f"Current workspace: {current}")

    def ask_ai_from_shell(self, scope: str = "current", question: str | None = None):
        prompt = (question if question is not None else self.ed_ai_quick.text()).strip()
        if not prompt:
            return
        if scope == "global":
            self._submit_ai_ask(prompt, "Whole profile", "")
            return
        context_label, context_text = self._current_ai_context()
        if self.insights.isVisible():
            # Insight AI is on: attach the FULL text of the page currently open
            # in the browser so the assistant can actually read the webpage.
            browser = self.browser_page.current_browser()
            if browser is not None and browser.page() is not None:
                self.lbl_assistant_scope.setText("Context: insights reading the browser page")

                def _on_page_text(text):
                    if self._closing:
                        return
                    page_text = (text or "").strip()
                    label, combined = context_label, context_text
                    if page_text:
                        title = browser.title() or browser.url().toString() or "Current page"
                        combined = (
                            f"{context_text}\n\n"
                            f"[Page open in browser: {title} — {browser.url().toString()} (full text)]\n"
                            f"{page_text[:12000]}"
                        )
                        label = f"{context_label} + browser page"
                    self._submit_ai_ask(prompt, label, combined)

                browser.page().runJavaScript(
                    "(function(){try{return (document.body && document.body.innerText) || '';}catch(e){return '';}})();",
                    _on_page_text,
                )
                return
        self._submit_ai_ask(prompt, context_label, context_text)

    def _submit_ai_ask(self, prompt: str, context_label: str, context_text: str):
        # If the AI workspace is passcode-locked and the user cancels the
        # unlock, the prompt must not be submitted anyway (v6.4 did).
        if not self.switch_workspace("ai"):
            return
        self.ai_page.ask_with_context(prompt, context_label, context_text)
        # Wire the assistant's reply back to the floating preview through the
        # ``query_finished`` signal so we never display a stale ``_last_answer``.
        if not getattr(self, "_ai_preview_wired", False):
            self.ai_page.query_finished.connect(self._on_ai_answer_ready_for_preview)
            self._ai_preview_wired = True

    def _on_ai_answer_ready_for_preview(self, future, _context_label, _provider_label=""):
        if self._closing:
            return
        try:
            result = future.result()
        except Exception as exc:
            self.ai_preview.setText("AI request failed: %s" % (exc,))
            return
        answer = (result or {}).get("answer") or "No answer."
        self.ai_preview.setText(answer[:220])

    def closeEvent(self, event):
        if self._closing:
            event.accept()
            return
        self._closing = True
        # The window manager cascades close events to child widgets; we do not
        # need to call .close() on them manually, which would recursively fire
        # their own closeEvent handlers (double session saves, widget teardown).
        try:
            self._save_window_state()
        except Exception:
            pass
        try:
            self._executor.shutdown(wait=False, cancel_futures=True)
        except Exception:
            pass
        # Hide the tray icon promptly so quitting does not leave a ghost entry.
        tray = getattr(self, "tray", None)
        if tray is not None:
            try:
                tray.hide()
            except Exception:
                pass
        event.accept()
