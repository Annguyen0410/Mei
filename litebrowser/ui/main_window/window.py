# Mei - Search window (main browser UI)
import json
import os
import re
import subprocess
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import parse_qs, quote_plus, unquote_plus, urlparse

from PyQt5.QtCore import (
    QAbstractAnimation,
    QEasingCurve,
    QObject,
    Qt,
    QTimer,
    QUrl,
    QVariantAnimation,
    pyqtSignal,
)
from PyQt5.QtGui import QDesktopServices, QFont, QIcon, QKeySequence
from PyQt5.QtNetwork import QNetworkProxy
from PyQt5.QtPrintSupport import QPrintDialog, QPrinter
from PyQt5.QtWebEngineWidgets import (
    QWebEngineProfile,
    QWebEngineSettings,
    QWebEngineView,
)
from PyQt5.QtWidgets import (
    QApplication,
    QButtonGroup,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QShortcut,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QStyle,
    QTextEdit,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from litebrowser.browser import adblock, extension_patterns, new_tab_page, tab_manager
from litebrowser.browser.browser_page import (
    build_text_highlight_js,
    ensure_text_highlight_script,
    ensure_webgl_disable_script,
)
from litebrowser.browser.tab_manager import TAB_META_ROLE, TAB_PINNED_ROLE
from litebrowser.core import app_paths, app_version, prefs
from litebrowser.services import (
    extension_bridge,
    google_auth,
    history_service,
    life_service,
    personal_service,
    tab_sets,
    workspace_manager,
)
from litebrowser.ui import dialogs, theme, vault_ui, win_titlebar

COMPATIBILITY_HOSTS = (
    "accounts.google.com",
    "claude.ai",
    "chatgpt.com",
    "copilot.microsoft.com",
    "gemini.google.com",
    "perplexity.ai",
)

# Chrome-style memory saver: when the process working set grows past this many
# MB, background tabs are frozen automatically until RAM settles down again.
MEMORY_SAVER_RSS_THRESHOLD_MB = 800


def _process_rss_mb():
    """Current process working-set size in MB (Windows), or None if unknown."""
    global _RSS_DLL_CACHE
    try:
        import ctypes
        from ctypes import wintypes

        if _RSS_DLL_CACHE is None:
            _RSS_DLL_CACHE = (ctypes.WinDLL("kernel32"), ctypes.WinDLL("psapi"))

        class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD),
                ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        kernel32, psapi = _RSS_DLL_CACHE
        counters = PROCESS_MEMORY_COUNTERS()
        counters.cb = ctypes.sizeof(PROCESS_MEMORY_COUNTERS)
        handle = kernel32.GetCurrentProcess()
        ok = psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb)
        if ok:
            return int(counters.WorkingSetSize // (1024 * 1024))
    except Exception:
        pass
    return None


_RSS_DLL_CACHE = None


class _FindBar(QWidget):
    """Chrome-style find bar: sticky row with next/prev, match count, Esc to
    close. Replaces the v6.4 modal QInputDialog that reopened on every Ctrl+F.
    Styling comes from the shell QSS (#FindBar) so it follows the theme."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("FindBar")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 4, 8, 4)
        lay.setSpacing(6)
        self.ed_query = QLineEdit()
        self.ed_query.setPlaceholderText("Find in page")
        self.ed_query.setClearButtonEnabled(True)
        self.ed_query.setFixedWidth(260)
        self.btn_prev = QToolButton()
        self.btn_prev.setText("▲")
        self.btn_prev.setToolTip("Previous match (Shift+F3)")
        self.btn_next = QToolButton()
        self.btn_next.setText("▼")
        self.btn_next.setToolTip("Next match (F3)")
        self.btn_close = QToolButton()
        self.btn_close.setText("✕")
        self.btn_close.setToolTip("Close (Esc)")
        for b in (self.btn_prev, self.btn_next, self.btn_close):
            b.setAutoRaise(True)
            b.setCursor(Qt.PointingHandCursor)
        self.lbl_count = QLabel("")
        self.lbl_count.setObjectName("MutedLabel")
        lay.addWidget(self.ed_query, 1)
        lay.addWidget(self.lbl_count)
        lay.addWidget(self.btn_prev)
        lay.addWidget(self.btn_next)
        lay.addWidget(self.btn_close)
        self.setFixedHeight(36)


class _WorkerRelay(QObject):
    """Queued-call bridge from executor threads to the GUI thread.

    QObjects/QTimers must not be created from worker threads (v6.4 used
    QTimer.singleShot inside future callbacks, which is unsafe); emit the
    callable instead and it runs on the GUI thread via a queued connection.
    """

    run_on_gui = pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.run_on_gui.connect(self._exec)

    def post(self, fn):
        self.run_on_gui.emit(fn)

    def _exec(self, fn):
        try:
            fn()
        except Exception:
            pass


class SearchWindow(QMainWindow):
    def __init__(self, base_dir=None, start_tabs=None, app_dir=None, embedded=False, window_slot=None):
        super().__init__()
        self._closing = False
        # Set BEFORE QWebEngineProfile is constructed so the two shell windows
        # get isolated disk caches/cookies instead of fighting over one dir.
        self._window_slot_hint = window_slot or "shared"
        self.embedded = embedded
        self.setWindowTitle("Mei - Browser")
        self.setGeometry(100, 100, 1300, 850)
        self.setMinimumSize(520 if embedded else 900, 420 if embedded else 600)
        self.base_dir = prefs.ensure_profile_layout(base_dir or app_paths.project_root())
        self.app_dir = app_dir or app_paths.project_root()
        self._executor = ThreadPoolExecutor(max_workers=2)
        self._worker_relay = _WorkerRelay(self)
        self._google_auth_running = False
        self.setWindowIcon(QIcon(os.path.join(self.app_dir, "icon.png")))

        # Native title bar color (Windows) - using shared helper.
        if not self.embedded:
            win_titlebar.apply_dark_titlebar(self, enabled=True)

        self.central_widget = QWidget()
        self.central_widget.setObjectName("MainWidget")
        self.setCentralWidget(self.central_widget)
        self.main_layout = QHBoxLayout(self.central_widget)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)

        QShortcut(QKeySequence("Ctrl+T"), self).activated.connect(lambda: self.add_new_tab())
        QShortcut(QKeySequence("Ctrl+Shift+N"), self).activated.connect(lambda: self.add_new_tab(is_incognito=True))
        QShortcut(QKeySequence("Ctrl+Shift+E"), self).activated.connect(self.extract_text)
        QShortcut(QKeySequence("Ctrl+S"), self).activated.connect(self.capture_screenshot)
        QShortcut(QKeySequence("Ctrl+W"), self).activated.connect(lambda: self.tab_manager.close_tab(self.tab_list.currentRow()))
        QShortcut(QKeySequence("F5"), self).activated.connect(lambda: self.current_browser().reload() if self.current_browser() else None)
        QShortcut(QKeySequence("Ctrl+R"), self).activated.connect(lambda: self.current_browser().reload() if self.current_browser() else None)
        QShortcut(QKeySequence("Ctrl+F"), self).activated.connect(self.find_text)
        QShortcut(QKeySequence("Ctrl+Shift+F"), self).activated.connect(self.focus_tab_filter)
        QShortcut(QKeySequence("Ctrl+H"), self).activated.connect(self.show_history_dialog)
        QShortcut(QKeySequence("Ctrl+J"), self).activated.connect(self.show_downloads_dialog)
        QShortcut(QKeySequence("Ctrl+L"), self).activated.connect(self.focus_url_bar)
        QShortcut(QKeySequence("Ctrl+Shift+B"), self).activated.connect(self._toggle_topbar)
        QShortcut(QKeySequence("Ctrl+D"), self).activated.connect(self.save_bookmark)
        QShortcut(QKeySequence("Alt+Left"), self).activated.connect(lambda: self.current_browser().back() if self.current_browser() else None)
        QShortcut(QKeySequence("Alt+Right"), self).activated.connect(lambda: self.current_browser().forward() if self.current_browser() else None)
        QShortcut(QKeySequence("F11"), self).activated.connect(self.toggle_fullscreen)
        QShortcut(QKeySequence("Ctrl+Shift+D"), self).activated.connect(lambda: self.tab_manager.duplicate_current_tab())
        QShortcut(QKeySequence("Ctrl+Shift+T"), self).activated.connect(self.reopen_closed_tab)
        QShortcut(QKeySequence("Ctrl+Tab"), self).activated.connect(self._cycle_tab_next)
        QShortcut(QKeySequence("Ctrl+PgDown"), self).activated.connect(self._cycle_tab_next)
        QShortcut(QKeySequence("Ctrl+Shift+Tab"), self).activated.connect(self._cycle_tab_prev)
        QShortcut(QKeySequence("Ctrl+PgUp"), self).activated.connect(self._cycle_tab_prev)
        QShortcut(QKeySequence("Ctrl+Shift+K"), self).activated.connect(lambda: dialogs.show_quick_switcher(self))
        QShortcut(QKeySequence("Ctrl+0"), self).activated.connect(self.zoom_reset)
        QShortcut(QKeySequence("Ctrl+="), self).activated.connect(self.zoom_in)
        QShortcut(QKeySequence("Ctrl+-"), self).activated.connect(self.zoom_out)
        QShortcut(QKeySequence("Ctrl+P"), self).activated.connect(self.print_page)
        QShortcut(QKeySequence("Ctrl+Shift+S"), self).activated.connect(self.save_page_pdf)
        QShortcut(QKeySequence("Ctrl+Shift+M"), self).activated.connect(
            lambda: getattr(self, "tab_manager", None) and self.tab_manager.optimize_memory()
        )
        QShortcut(QKeySequence("F12"), self).activated.connect(self.show_dev_tools)

        self.main_splitter = QSplitter(Qt.Horizontal)
        self.main_splitter.setChildrenCollapsible(False)
        self.main_splitter.setStretchFactor(0, 0)
        self.main_splitter.setStretchFactor(1, 1)
        self.main_layout.addWidget(self.main_splitter)

        self.sidebarWidget = QWidget()
        self.sidebarWidget.setObjectName("Sidebar")
        # Start with the useful, readable tab desk open.  The compact handler
        # still turns this into a slim rail on narrow embedded windows.
        self.sidebar_collapsed = False
        self._topbar_collapsed = False
        self.sidebarWidget.setMinimumWidth(190)
        self.sidebarWidget.setMaximumWidth(320)
        self.sidebar_layout = QVBoxLayout(self.sidebarWidget)
        self.sidebar_layout.setContentsMargins(8, 10, 8, 10)
        self.sidebar_layout.setSpacing(6)
        self.sidebar_layout.setAlignment(Qt.AlignTop)
        self._sidebar_anim = None
        sidebar_title_row = QHBoxLayout()
        sidebar_title_row.setAlignment(Qt.AlignCenter)
        self.btn_collapse_sidebar = QToolButton()
        self.btn_collapse_sidebar.setToolTip("Collapse / expand sidebar")
        self.btn_collapse_sidebar.setText("‹")
        self.btn_collapse_sidebar.clicked.connect(self._toggle_sidebar_collapse)
        sidebar_title_row.addWidget(self.btn_collapse_sidebar)
        self.brand_glyph = QLabel("🍵")
        self.brand_glyph.setObjectName("BrandGlyph")
        sidebar_title_row.addWidget(self.brand_glyph)
        self.title_label = QLabel("Mei")
        self.title_label.setObjectName("AppTitle")
        self.title_label.setFont(QFont("Segoe UI", 14, QFont.Bold))
        self.title_label.setAlignment(Qt.AlignCenter)
        sidebar_title_row.addWidget(self.title_label, 1)
        self.sidebar_layout.addLayout(sidebar_title_row)
        self.sidebar_layout.addSpacing(4)
        self.lbl_tab_count = QLabel("0 Live · 0 Sleeping")
        self.lbl_tab_count.setObjectName("TabCounter")
        self.lbl_tab_count.setToolTip("Live tabs use a browser renderer. Sleeping tabs reopen only when selected.")
        self.sidebar_layout.addWidget(self.lbl_tab_count)
        self.lbl_tab_count.setAlignment(Qt.AlignCenter)
        self.current_workspace_id = workspace_manager.get_current_id(self.base_dir)
        self.workspace_combo = QComboBox()
        self.workspace_combo.setObjectName("WorkspaceCombo")
        self.workspace_combo.setMinimumHeight(28)
        self._refresh_workspace_combo()
        self.workspace_combo.currentIndexChanged.connect(self._on_workspace_changed)
        self.sidebar_layout.addWidget(self.workspace_combo)
        self.sidebar_panel_buttons = QHBoxLayout()
        self.sidebar_panel_buttons.setSpacing(6)
        self.sidebar_panel_buttons.setAlignment(Qt.AlignCenter)
        self.btn_panel_tabs = QToolButton()
        self.btn_panel_tabs.setObjectName("SidebarPanelBtn")
        self.btn_panel_tabs.setText("◉")
        self.btn_panel_tabs.setToolTip("Tab list")
        self.btn_panel_tabs.setCheckable(True)
        self.btn_panel_tabs.setChecked(True)
        self.btn_panel_bookmarks = QToolButton()
        self.btn_panel_bookmarks.setObjectName("SidebarPanelBtn")
        self.btn_panel_bookmarks.setText("★")
        self.btn_panel_bookmarks.setToolTip("Bookmarks")
        self.btn_panel_bookmarks.setCheckable(True)
        self.btn_panel_history = QToolButton()
        self.btn_panel_history.setObjectName("SidebarPanelBtn")
        self.btn_panel_history.setText("◷")
        self.btn_panel_history.setToolTip("History")
        self.btn_panel_history.setCheckable(True)
        self.btn_panel_downloads = QToolButton()
        self.btn_panel_downloads.setObjectName("SidebarPanelBtn")
        self.btn_panel_downloads.setText("↓")
        self.btn_panel_downloads.setToolTip("Downloads")
        self.btn_panel_downloads.setCheckable(True)
        self.btn_panel_reading = QToolButton()
        self.btn_panel_reading.setObjectName("SidebarPanelBtn")
        self.btn_panel_reading.setText("☰")
        self.btn_panel_reading.setToolTip("Reading list")
        self.btn_panel_reading.setCheckable(True)
        self.sidebar_panel_group = QButtonGroup(self)
        self.sidebar_panel_group.setExclusive(True)
        self.sidebar_panel_group.addButton(self.btn_panel_tabs)
        self.sidebar_panel_group.addButton(self.btn_panel_bookmarks)
        self.sidebar_panel_group.addButton(self.btn_panel_history)
        self.sidebar_panel_group.addButton(self.btn_panel_downloads)
        self.sidebar_panel_group.addButton(self.btn_panel_reading)
        self.sidebar_panel_buttons.addStretch(1)
        self.sidebar_panel_buttons.addWidget(self.btn_panel_tabs)
        self.sidebar_panel_buttons.addWidget(self.btn_panel_bookmarks)
        self.sidebar_panel_buttons.addWidget(self.btn_panel_history)
        self.sidebar_panel_buttons.addWidget(self.btn_panel_downloads)
        self.sidebar_panel_buttons.addWidget(self.btn_panel_reading)
        self.sidebar_panel_buttons.addStretch(1)
        self.sidebar_layout.addLayout(self.sidebar_panel_buttons)
        self.sidebar_stack = QStackedWidget()
        self.sidebar_stack.setObjectName("SidebarStack")
        tab_page = QWidget()
        tab_page_layout = QVBoxLayout(tab_page)
        tab_page_layout.setContentsMargins(0, 0, 0, 0)
        tab_page_layout.setSpacing(0)
        self.tab_filter = QLineEdit()
        self.tab_filter.setObjectName("TabFilter")
        self.tab_filter.setPlaceholderText("Search tabs · is:sleeping · is:pinned · site:example.com · group:youtube.com")
        self.tab_filter.setClearButtonEnabled(True)
        self._tab_filter_timer = QTimer(self)
        self._tab_filter_timer.setSingleShot(True)
        self._tab_filter_timer.setInterval(65)
        self._tab_filter_timer.timeout.connect(self._filter_tab_list)
        self.tab_filter.textChanged.connect(self._queue_tab_filter)
        tab_page_layout.addWidget(self.tab_filter)
        self.tab_list = QListWidget()
        self.tab_list.setObjectName("TabList")
        self.tab_list.currentRowChanged.connect(self._on_change_tab)
        self.tab_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tab_list.customContextMenuRequested.connect(self.show_tab_context_menu)
        self.tab_list.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        self.tab_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.tab_list.setUniformItemSizes(True)
        tab_page_layout.addWidget(self.tab_list, 1)
        self.sidebar_stack.addWidget(tab_page)
        bookmarks_page = QWidget()
        bookmarks_page_layout = QVBoxLayout(bookmarks_page)
        bookmarks_page_layout.setContentsMargins(0, 0, 0, 0)
        bookmarks_page_layout.setSpacing(2)
        bm_toolbar = QHBoxLayout()
        bm_toolbar.setContentsMargins(4, 2, 4, 2)
        self.btn_add_bm_folder = QToolButton()
        self.btn_add_bm_folder.setText("+Folder")
        self.btn_add_bm_folder.setToolTip("Add bookmark folder")
        self.btn_add_bm_folder.clicked.connect(self._add_bookmark_folder)
        bm_toolbar.addWidget(self.btn_add_bm_folder)
        self.btn_add_bm = QToolButton()
        self.btn_add_bm.setText("+BM")
        self.btn_add_bm.setToolTip("Bookmark current page here")
        self.btn_add_bm.clicked.connect(lambda: self.save_bookmark(None))
        bm_toolbar.addWidget(self.btn_add_bm)
        bm_toolbar.addStretch()
        bookmarks_page_layout.addLayout(bm_toolbar)
        self.bookmarks_tree = QTreeWidget()
        self.bookmarks_tree.setObjectName("TabList")
        self.bookmarks_tree.setHeaderHidden(True)
        self.bookmarks_tree.setDragDropMode(self.bookmarks_tree.DragDropMode.InternalMove)
        self.bookmarks_tree.itemDoubleClicked.connect(lambda item, col: self._on_bookmark_clicked(item))
        self.bookmarks_tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.bookmarks_tree.customContextMenuRequested.connect(self._show_bookmark_context_menu)
        self.bookmarks_tree.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        bookmarks_page_layout.addWidget(self.bookmarks_tree, 1)
        self.sidebar_stack.addWidget(bookmarks_page)
        self.history_list = QListWidget()
        self.history_list.setObjectName("TabList")
        self.history_list.itemDoubleClicked.connect(self._on_history_clicked)
        self.history_list.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        self.history_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.sidebar_stack.addWidget(self.history_list)
        self.downloads_list = QListWidget()
        self.downloads_list.setObjectName("TabList")
        self.downloads_list.itemDoubleClicked.connect(self._on_download_clicked)
        self.downloads_list.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        self.downloads_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.sidebar_stack.addWidget(self.downloads_list)
        self.reading_list = QListWidget()
        self.reading_list.setObjectName("TabList")
        self.reading_list.itemDoubleClicked.connect(self._on_reading_clicked)
        self.reading_list.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        self.reading_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.sidebar_stack.addWidget(self.reading_list)
        self.sidebar_stack.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        self.sidebar_layout.addWidget(self.sidebar_stack, 1)
        self.btn_panel_tabs.clicked.connect(lambda: self._switch_sidebar_panel(0))
        self.btn_panel_bookmarks.clicked.connect(lambda: self._switch_sidebar_panel(1))
        self.btn_panel_history.clicked.connect(lambda: self._switch_sidebar_panel(2))
        self.btn_panel_downloads.clicked.connect(lambda: self._switch_sidebar_panel(3))
        self.btn_panel_reading.clicked.connect(lambda: self._switch_sidebar_panel(4))
        self.btn_new_tab = QPushButton("+  New Tab")
        self.btn_new_tab.setObjectName("NewTabBtn")
        self.btn_new_tab.setToolTip("Ctrl+T")
        self.btn_new_tab.clicked.connect(lambda: self.add_new_tab(None, "New Tab"))
        self.btn_options = QPushButton("⚙  Control")
        self.btn_options.setObjectName("OptionsBtn")
        self.options_menu = self._build_options_menu()
        self.btn_options.setMenu(self.options_menu)
        self._master_password = None
        self.sidebar_footer = QWidget()
        self.sidebar_footer.setObjectName("SidebarFooter")
        self.sidebar_footer.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        sidebar_footer_layout = QHBoxLayout(self.sidebar_footer)
        sidebar_footer_layout.setContentsMargins(0, 4, 0, 0)
        sidebar_footer_layout.setSpacing(6)
        sidebar_footer_layout.addStretch(1)
        sidebar_footer_layout.addWidget(self.btn_new_tab, 0, Qt.AlignHCenter)
        sidebar_footer_layout.addWidget(self.btn_options, 0, Qt.AlignHCenter)
        sidebar_footer_layout.addStretch(1)
        self.sidebar_layout.addWidget(self.sidebar_footer)
        self.main_splitter.addWidget(self.sidebarWidget)

        self.content_widget = QWidget()
        self.content_widget.setObjectName("ContentArea")
        self.content_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.content_layout = QVBoxLayout(self.content_widget)
        if self.embedded:
            self.content_layout.setContentsMargins(2, 2, 2, 2)
            self.content_layout.setSpacing(3)
        else:
            self.content_layout.setContentsMargins(2, 2, 2, 2)
            self.content_layout.setSpacing(2)
        self.topbar = QWidget()
        self.topbar.setObjectName("TopBar")
        self.topbar.setMinimumHeight(40 if self.embedded else 44)
        self.topbar_layout = QHBoxLayout(self.topbar)
        if self.embedded:
            self.topbar_layout.setContentsMargins(4, 3, 4, 3)
            self.topbar_layout.setSpacing(3)
        else:
            self.topbar_layout.setContentsMargins(4, 3, 4, 3)
            self.topbar_layout.setSpacing(2)
        style = self.style()
        self.btn_back = QToolButton()
        self.btn_back.setObjectName("TopIconButton")
        self.btn_back.setText("←")
        self.btn_back.setToolTip("Back (Alt+Left)")
        self.btn_back.clicked.connect(lambda: self.current_browser().back() if self.current_browser() else None)
        self.btn_forward = QToolButton()
        self.btn_forward.setObjectName("TopIconButton")
        self.btn_forward.setText("→")
        self.btn_forward.setToolTip("Forward (Alt+Right)")
        self.btn_forward.clicked.connect(lambda: self.current_browser().forward() if self.current_browser() else None)
        self.btn_reload = QToolButton()
        self.btn_reload.setObjectName("TopIconButton")
        self.btn_reload.setText("↻")
        self.btn_reload.setToolTip("Reload (F5)")
        self.btn_reload.clicked.connect(lambda: self.current_browser().reload() if self.current_browser() else None)
        self.topbar_layout.addWidget(self.btn_back)
        self.topbar_layout.addWidget(self.btn_forward)
        self.topbar_layout.addWidget(self.btn_reload)
        self.btn_vpn_hub = QPushButton()
        self.btn_vpn_hub.setObjectName("TopAccentButton")
        self.btn_vpn_hub.setText("VPN")
        self.btn_vpn_hub.setToolTip("Quick VPN / proxy presets")
        self.btn_vpn_hub.clicked.connect(lambda: dialogs.show_vpn_hub(self))
        self.topbar_layout.addWidget(self.btn_vpn_hub)
        self.topbar_layout.addSpacing(4)
        self.search_engine = QComboBox()
        self.search_engine.setObjectName("SearchEngine")
        self.search_engine.addItems(list(prefs.SEARCH_ENGINE_NAMES))
        self.search_engine.setEditable(False)
        saved_engine = prefs.get_search_engine(self.base_dir)
        saved_index = self.search_engine.findText(saved_engine)
        if saved_index >= 0:
            self.search_engine.setCurrentIndex(saved_index)
        self.search_engine.setMinimumWidth(78)
        self.search_engine.setMaximumWidth(118)
        self.search_engine.currentIndexChanged.connect(self._on_search_engine_changed)
        self.topbar_layout.addWidget(self.search_engine)
        self.lbl_site_state = QLabel("Search")
        self.lbl_site_state.setObjectName("AddressHint")
        self.lbl_site_state.setMinimumWidth(60)
        self.topbar_layout.addWidget(self.lbl_site_state)
        self.url_bar = QLineEdit()
        self.url_bar.setObjectName("UrlBar")
        self.url_bar.setPlaceholderText("URL, search, about:cuc-quan-ly, ...")
        self.url_bar.setFont(QFont("Segoe UI", 11))
        self.url_bar.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.url_bar.setMinimumWidth(120)
        self.url_bar.setClearButtonEnabled(False)
        self.url_bar.setToolTip("Type a URL or search and press Enter")
        self.url_bar.returnPressed.connect(self.navigate)
        self.url_clear_action = self.url_bar.addAction(
            self.style().standardIcon(QStyle.SP_DialogCloseButton),
            QLineEdit.TrailingPosition,
        )
        self.url_clear_action.triggered.connect(self.url_bar.clear)
        self.url_clear_action.setVisible(False)
        self.url_bar.textChanged.connect(lambda text: self.url_clear_action.setVisible(bool(text)))
        self.topbar_layout.addWidget(self.url_bar, 1)
        self.lbl_zoom = QLabel("100%")
        self.lbl_zoom.setObjectName("ZoomLabel")
        self.lbl_zoom.setMinimumWidth(42)
        self.lbl_zoom.setAlignment(Qt.AlignCenter)
        self.lbl_zoom.setToolTip("Zoom level")
        self.topbar_layout.addWidget(self.lbl_zoom)
        self.btn_ai = QToolButton()
        self.btn_ai.setObjectName("TopIconButton")
        self.btn_ai.setText("AI")
        self.btn_ai.setToolTip("Ask AI about this page")
        self.btn_ai.clicked.connect(self.ask_ai_about_current_page)
        self.topbar_layout.addWidget(self.btn_ai)
        self.btn_page_menu = QToolButton()
        self.btn_page_menu.setObjectName("TopIconButton")
        self.btn_page_menu.setText("\u2022\u2022\u2022")
        self.btn_page_menu.setToolTip("Page actions")
        self.page_menu = self._build_page_menu()
        self.btn_page_menu.setMenu(self.page_menu)
        self.btn_page_menu.setPopupMode(QToolButton.InstantPopup)
        self.topbar_layout.addWidget(self.btn_page_menu)
        self.btn_toggle_topbar = QToolButton()
        self.btn_toggle_topbar.setObjectName("TopIconButton")
        self.btn_toggle_topbar.setText("▾")
        self.btn_toggle_topbar.setToolTip("Collapse / expand the toolbar (Ctrl+Shift+B)")
        self.btn_toggle_topbar.clicked.connect(self._toggle_topbar)
        self.topbar_layout.addWidget(self.btn_toggle_topbar)
        self.topbar_layout.setStretchFactor(self.url_bar, 1)
        self.content_layout.addWidget(self.topbar, 0)
        self.inline_ai_panel = QFrame()
        self.inline_ai_panel.setObjectName("SectionCard")
        inline_ai_layout = QVBoxLayout(self.inline_ai_panel)
        inline_ai_layout.setContentsMargins(12, 12, 12, 12)
        inline_ai_layout.setSpacing(8)
        ai_row = QHBoxLayout()
        self.inline_ai_input = QLineEdit()
        self.inline_ai_input.setPlaceholderText("Ask AI about the page you are viewing...")
        self.inline_ai_ask = QPushButton("Ask page")
        self.inline_ai_close = QPushButton("Hide")
        ai_row.addWidget(self.inline_ai_input, 1)
        ai_row.addWidget(self.inline_ai_ask)
        ai_row.addWidget(self.inline_ai_close)
        inline_ai_layout.addLayout(ai_row)
        self.inline_ai_answer = QTextEdit()
        self.inline_ai_answer.setReadOnly(True)
        self.inline_ai_answer.setMaximumHeight(120)
        self.inline_ai_answer.setPlaceholderText("The page-aware assistant will answer here.")
        inline_ai_layout.addWidget(self.inline_ai_answer)
        self.inline_ai_panel.hide()
        self.inline_ai_input.returnPressed.connect(self._run_inline_ai)
        self.inline_ai_ask.clicked.connect(self._run_inline_ai)
        self.inline_ai_close.clicked.connect(self.inline_ai_panel.hide)
        self.content_layout.addWidget(self.inline_ai_panel, 0)
        self.ai_actions_available = embedded
        if not self.ai_actions_available:
            self.btn_ai.hide()
            self.inline_ai_panel.hide()
        self.web_container = QWidget()
        self.web_container.setObjectName("WebContainer")
        self.web_container.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.web_container_layout = QVBoxLayout(self.web_container)
        self.web_container_layout.setContentsMargins(0, 0, 0, 0)
        self.web_container_layout.setSpacing(0)
        self.stack = QStackedWidget()
        self.stack.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.web_container_layout.addWidget(self.stack, 1)
        self.content_layout.addWidget(self.web_container, 1)
        self.main_splitter.addWidget(self.content_widget)
        initial_sidebar = self._sidebar_expanded_nominal_width()
        self.main_splitter.setSizes([initial_sidebar, max(420, (1216 if self.embedded else 1228) - initial_sidebar)])
        self.title_label.setVisible(False)
        self.lbl_tab_count.setVisible(False)
        self.workspace_combo.setVisible(False)

        self.browsers = []
        self._incognito_profiles = []
        self._dev_windows = []
        self._cookie_filter = None
        self._trusted_site_profiles = {}
        self.ext_path = prefs.ext_path(self.base_dir)
        if not os.path.exists(self.ext_path):
            os.makedirs(self.ext_path)
        self._user_extension_scripts_cache = None
        data_path = app_paths.browser_data_path(self.base_dir)
        if not os.path.exists(data_path):
            os.makedirs(data_path)
        slot = self._shell_slot()
        profile_name = "MeiProfile-%s" % slot
        os.makedirs(os.path.join(data_path, slot), exist_ok=True)
        self.profile = QWebEngineProfile(profile_name, self)
        self._configure_web_profile(self.profile)
        # Highlight-selected-text + copy bubble: profile-level so it covers every
        # page of this browser AND embedded previews that share the profile.
        try:
            ensure_text_highlight_script(self.profile, prefs.get_text_highlight_enabled(self.base_dir), self.base_dir)
        except Exception:
            pass
        self.interceptor = adblock.TrackingBlocker(self, self.base_dir)
        self.interceptor.https_only = prefs.get_https_only(self.base_dir)
        self.interceptor.reload_filter_file()
        self.profile.setUrlRequestInterceptor(self.interceptor)
        # Auto-refresh subscribed filter lists in the background so the
        # blocklist keeps itself fresh without blocking startup.
        self._refresh_adblock_subscriptions_async()

        self.tab_manager = tab_manager.TabManager(self)
        self._apply_workspace_filter()
        self._apply_saved_proxy()
        self._load_block_third_party_cookies_pref()
        self._load_dark_web_pref()
        self._load_data_saver_pref()
        self._load_disable_webgl_pref()
        self._load_defer_background_pref()
        self._dynamic_bg_phase = 0
        self._dynamic_bg_timer = QTimer(self)
        self._dynamic_bg_timer.timeout.connect(self._tick_dynamic_background)
        self._load_ui_dynamic_background_pref()
        self.apply_styles()
        self._apply_responsive_layout()
        self._audio_indicator_timer = QTimer(self)
        self._audio_indicator_timer.timeout.connect(self._update_audio_indicators)
        self._audio_indicator_timer.start(5000)
        # Chrome-style auto memory saver: every 30s, freeze background tabs when
        # the process working set is above the threshold.
        self._memory_saver_timer = QTimer(self)
        self._memory_saver_timer.timeout.connect(self._auto_memory_saver_tick)
        self._memory_saver_timer.start(30_000)
        # Android bridge → real tabs: MeiRemote can ask the desktop to open a web
        # app (or any URL). The bridge thread writes a request file; drain it here.
        self._open_request_timer = QTimer(self)
        self._open_request_timer.timeout.connect(self._drain_open_requests)
        self._open_request_timer.start(2500)
        if start_tabs:
            # Start from saved tab set (listtab)
            self.tab_manager.begin_batch()
            try:
                active_index = next(
                    (idx for idx, tab in enumerate(start_tabs) if tab.get("active") and tab.get("url")),
                    next((idx for idx, tab in enumerate(start_tabs) if tab.get("url")), 0),
                )
                for idx, t in enumerate(start_tabs):
                    url = t.get("url") or ""
                    if not url:
                        continue
                    is_active = idx == active_index
                    self.tab_manager.add_tab(QUrl(url), t.get("title") or "Loading...", is_active=is_active, session_data=t)
            finally:
                self.tab_manager.end_batch()
        else:
            mode, home_url = prefs.get_startup_prefs(self.base_dir)
            session_path = prefs.session_path(self.base_dir)
            if mode == "restore" and os.path.exists(session_path):
                try:
                    session_state = prefs.session_state_load(self.base_dir)
                    tabs = session_state.get("tabs", [])
                    if not tabs:
                        # No saved tabs (mode still "restore"): fall back to the
                        # configured startup page. v6.4 tested mode == "newtab"
                        # here — always false inside a "restore" branch — so the
                        # new-tab path was dead code.
                        self.add_new_tab(None, "New Tab")
                    else:
                        active_index = next((idx for idx, tab in enumerate(tabs) if tab.get("active")), 0)
                        self.tab_manager.begin_batch()
                        try:
                            for idx, tab in enumerate(tabs):
                                url = tab.get("url") or home_url or "https://google.com"
                                self.tab_manager.add_tab(QUrl(url), tab.get("title") or "Loading...", is_active=(idx == active_index), session_data=tab)
                        finally:
                            self.tab_manager.end_batch()
                except Exception:
                    self.tab_manager.add_tab(QUrl(home_url or "https://google.com"), "Home")
            else:
                if mode == "newtab":
                    self.add_new_tab(None, "New Tab")
                else:
                    self.add_new_tab(QUrl(home_url or "https://google.com"), "Home")

        self._check_bootstrap_import_payload()

    def set_workspace_id(self, workspace_id, persist=False):
        if not workspace_id:
            return
        self.current_workspace_id = workspace_id
        self._refresh_workspace_combo()
        if persist:
            workspace_manager.set_current_id(self.base_dir, workspace_id)
        self._apply_workspace_filter()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._apply_responsive_layout()

    def _sidebar_expanded_nominal_width(self):
        """Preferred sidebar width when expanded (not collapsed rail)."""
        width = max(0, self.width())
        tiny = width < 900
        tight = width < 1120
        compact = width < 1400
        if tiny:
            return 200
        if tight:
            return 220
        if compact:
            return 240
        return 260

    def _apply_responsive_layout(self):
        width = max(0, self.width())
        compact = width < 1400
        tight = width < 1120
        tiny = width < 900
        xtiny = width < 640
        rail = 30 if not xtiny else 0

        _anim = getattr(self, "_sidebar_anim", None)
        _sidebar_anim_idle = _anim is None or _anim.state() != QAbstractAnimation.Running
        if hasattr(self, "sidebarWidget") and _sidebar_anim_idle:
            if self.sidebar_collapsed:
                self.sidebarWidget.setMinimumWidth(rail)
                self.sidebarWidget.setMaximumWidth(rail)
                self.sidebarWidget.setVisible(not xtiny)
            else:
                self.sidebarWidget.setMinimumWidth(120)
                self.sidebarWidget.setMaximumWidth(800)
        self._apply_sidebar_collapse_visibility()

        if hasattr(self, "topbar_layout"):
            self.topbar_layout.setSpacing(2 if xtiny else 3 if tight else 4)

        for button in (
            getattr(self, "btn_back", None),
            getattr(self, "btn_forward", None),
            getattr(self, "btn_reload", None),
            getattr(self, "btn_vpn_hub", None),
            getattr(self, "btn_ai", None),
            getattr(self, "btn_page_menu", None),
        ):
            if button:
                button.setMinimumWidth(24 if xtiny else 26 if tiny else 28)
                button.setMaximumWidth(34 if xtiny else 40 if tiny else 46 if tight else 52)
                button.setMinimumHeight(20 if xtiny else 24 if tiny else 26)
                button.setMaximumHeight(24 if xtiny else 28 if tiny else 30)

        if hasattr(self, "search_engine"):
            self.search_engine.setVisible(not tiny)
            self.search_engine.setMaximumWidth(90 if tight else 112)
        if hasattr(self, "lbl_site_state"):
            self.lbl_site_state.setVisible(not tight)
            self.lbl_site_state.setMinimumWidth(28)

        if hasattr(self, "url_bar"):
            self.url_bar.setMinimumWidth(100 if xtiny else 160 if tiny else 240 if tight else 320 if compact else 400)

        if hasattr(self, "btn_page_menu"):
            self.btn_page_menu.setVisible(not xtiny)

        if getattr(self, "_topbar_collapsed", False):
            self._apply_topbar_collapse()

    def _build_options_menu(self):
        menu = QMenu(self)
        hub_menu = menu.addMenu("Project Hub \u2014 App Chain")
        for site in app_paths.bundled_sites(getattr(self, "app_dir", None)):
            if not site.get("url") and not site.get("remote"):
                continue
            hub_menu.addAction(site["display"]).triggered.connect(
                lambda checked, site_key=site["key"]: self.open_bundled_site(site_key)
            )
        menu.addAction("Open Project Hub").triggered.connect(self.open_project_hub)
        menu.addAction("Help & Browser tools...").triggered.connect(lambda: dialogs.show_browser_control_center(self))
        menu.addAction(f"Check for updates ({app_version.APP_VERSION})...").triggered.connect(self._check_for_updates_from_browser)
        menu.addSeparator()

        sessions_menu = menu.addMenu("Sessions & Spaces")
        sessions_menu.addAction("New Incognito Tab (Ctrl+Shift+N)").triggered.connect(lambda: self.add_new_tab(is_incognito=True))
        sessions_menu.addAction("Workspaces...").triggered.connect(lambda: dialogs.show_workspace_dialog(self))
        sessions_menu.addAction("Profiles...").triggered.connect(lambda: dialogs.show_profiles_dialog(self, getattr(self, "app_dir", self.base_dir)))
        sessions_menu.addAction("On Startup...").triggered.connect(lambda: dialogs.show_startup_dialog(self))
        sessions_menu.addAction("Reopen Closed Tab (Ctrl+Shift+T)").triggered.connect(self.reopen_closed_tab)
        sessions_menu.addAction("Reopen Closed Window").triggered.connect(self.reopen_closed_window)
        sessions_menu.addAction("Quick Switcher (Ctrl+Shift+K)").triggered.connect(lambda: dialogs.show_quick_switcher(self))
        sessions_menu.addAction("Save Current Tab Set...").triggered.connect(self.save_current_tab_set)
        sessions_menu.addAction("Restore Tab Set...").triggered.connect(lambda: dialogs.show_tab_sets_dialog(self))

        tabs_menu = menu.addMenu("Tab Center")
        tabs_menu.addAction("Find tab (Ctrl+Shift+F)").triggered.connect(self.focus_tab_filter)
        tabs_menu.addAction("Suspend background tabs (Ctrl+Shift+M)").triggered.connect(
            lambda: self.tab_manager.optimize_memory()
        )
        tabs_menu.addAction("Close duplicate URLs in this workspace").triggered.connect(self.close_duplicate_tabs)
        tabs_menu.addAction("Copy visible workspace URLs").triggered.connect(self.copy_workspace_urls)
        tabs_menu.addAction("Group tabs by domain").triggered.connect(self.group_tabs_action)

        capture_menu = menu.addMenu("Read & Save")
        capture_menu.addAction("Capture Web Screenshot (Ctrl+S)").triggered.connect(self.capture_screenshot)
        capture_menu.addAction("Extract All Text (Ctrl+Shift+E)").triggered.connect(self.extract_text)
        capture_menu.addAction("Print Page").triggered.connect(self.print_page)
        capture_menu.addAction("Save PDF").triggered.connect(self.save_page_pdf)
        capture_menu.addAction("Save Page to Library").triggered.connect(self.save_current_page_to_library)
        capture_menu.addAction("Create Note from Current Page").triggered.connect(self.capture_page_as_note)

        privacy_menu = menu.addMenu("Privacy & Performance")
        privacy_menu.addAction("Security (HTTPS, Adblock, Passwords)...").triggered.connect(lambda: dialogs.show_privacy_dialog(self))
        privacy_menu.addAction("VPN / Proxy (Quick)...").triggered.connect(lambda: dialogs.show_vpn_hub(self))
        privacy_menu.addAction("VPN / Proxy (Detailed)...").triggered.connect(lambda: dialogs.show_vpn_dialog(self))
        privacy_menu.addAction("Tab Hibernation Timeout...").triggered.connect(lambda: dialogs.show_hibernate_pref_dialog(self))
        self.act_defer_background = privacy_menu.addAction("Background loading priority (lazy-load background tabs)")
        self.act_defer_background.setCheckable(True)
        self.act_defer_background.triggered.connect(self.toggle_defer_background)
        privacy_menu.addAction("Freeze All Background Tabs").triggered.connect(
            lambda: self.tab_manager.optimize_memory()
        )
        privacy_menu.addAction("Performance dashboard").triggered.connect(self.show_performance_dashboard)
        self.act_dark_mode = privacy_menu.addAction("Force Dark Mode on Web")
        self.act_dark_mode.setCheckable(True)
        self.act_dark_mode.triggered.connect(self.toggle_dark_web)
        self.act_dynamic_bg = privacy_menu.addAction("Animated Gradient Sidebar")
        self.act_dynamic_bg.setCheckable(True)
        self.act_dynamic_bg.triggered.connect(self.toggle_ui_dynamic_background)
        self.act_data_saver = privacy_menu.addAction("Data Saver (Skip Images on New Pages)")
        self.act_data_saver.setCheckable(True)
        self.act_data_saver.triggered.connect(self.toggle_data_saver)
        self.act_disable_webgl = privacy_menu.addAction("Lite Rendering (Disable WebGL)")
        self.act_disable_webgl.setCheckable(True)
        self.act_disable_webgl.triggered.connect(self.toggle_disable_webgl)
        self.act_block_3p_cookies = privacy_menu.addAction("Block Third-Party Cookies")
        self.act_block_3p_cookies.setCheckable(True)
        self.act_block_3p_cookies.triggered.connect(self.toggle_block_third_party_cookies)
        privacy_menu.addAction("Refresh adblock filters").triggered.connect(self._refresh_adblock_now)
        privacy_menu.addAction("Save Password for This Page").triggered.connect(lambda: dialogs.show_save_password_dialog(self))

        data_menu = menu.addMenu("Data & Tools")
        data_menu.addAction("History").triggered.connect(self.show_history_dialog)
        data_menu.addAction("Bookmarks").triggered.connect(self.show_bookmarks_dialog)
        data_menu.addAction("Downloads").triggered.connect(self.show_downloads_dialog)
        data_menu.addAction("Extensions").triggered.connect(self.show_extensions_dialog)
        data_menu.addAction("Safe Vault").triggered.connect(self.show_vault)
        data_menu.addAction("Open LinkLumina Backup Folder...").triggered.connect(self.open_linklumina_archive_folder)
        data_menu.addAction("Extension Import Center").triggered.connect(self.show_extension_import_center)
        account_menu = data_menu.addMenu("Google account")
        account_menu.addAction("Configure OAuth Client ID...").triggered.connect(self.configure_google_oauth_client_id)
        account_menu.addAction("Test OAuth configuration...").triggered.connect(self.test_google_oauth_configuration)
        account_menu.addAction("Sign in for Mei...").triggered.connect(self.start_google_oauth_sign_in)
        account_menu.addAction("Show signed-in account").triggered.connect(self.show_google_account_status)
        account_menu.addAction("Sign out").triggered.connect(self.sign_out_google_account)
        return menu

    def _check_for_updates_from_browser(self):
        shell = self.window()
        if hasattr(shell, "run_update_check"):
            shell.run_update_check(manual=True)

    def configure_google_oauth_client_id(self):
        current = prefs.get_google_oauth_client_id(self.base_dir) or os.environ.get("LITEBROWSER_GOOGLE_CLIENT_ID", "")
        text, ok = QInputDialog.getText(
            self,
            "Google OAuth Client ID",
            "Paste your Google OAuth Desktop Client ID "
            "(must be a 'Desktop app' type in Google Cloud Console, "
            "ends with .apps.googleusercontent.com):",
            text=current,
        )
        if not ok:
            return
        cid = (text or "").strip()
        prefs.set_google_oauth_client_id(self.base_dir, cid)

        bad_format_hint = ""
        if cid and not cid.endswith(".apps.googleusercontent.com"):
            bad_format_hint = (
                "\n\nNote: this Client ID does not end with '.apps.googleusercontent.com'  "
                "you may have pasted a client_secret by mistake or copied incompletely. Double-check it in Google Cloud Console."
            )

        QMessageBox.information(
            self,
            "Google OAuth",
            "Client ID saved."
            "\n\nMei uses the Device Code flow to sign in to Google  "
            "you only need a Client ID, no Redirect URI configuration."
            f"\n\n{bad_format_hint}",
        )

    def test_google_oauth_configuration(self):
        """Check if the Google OAuth client ID looks valid."""
        client_id = prefs.get_google_oauth_client_id(self.base_dir) or os.environ.get("LITEBROWSER_GOOGLE_CLIENT_ID", "")
        lines = []
        if not client_id:
            lines.append("No Client ID set. Use 'Configure OAuth Client ID' to add one.")
        elif not client_id.endswith(".apps.googleusercontent.com"):
            lines.append(
                f"Invalid Client ID: '{client_id[:30]}'"
                "\n   It must end with .apps.googleusercontent.com "
                "('Desktop app' type in Google Cloud Console)."
            )
        else:
            lines.append(f"Client ID looks valid: {client_id[:30]}")
            lines.append("\nMei uses Device Code flow (no Redirect URI needed).")
        QMessageBox.information(self, "Google OAuth check", "\n".join(lines))

    def start_google_oauth_sign_in(self):
        if self._google_auth_running:
            QMessageBox.information(self, "Google OAuth", "Sign-in already in progress.")
            return
        client_id = prefs.get_google_oauth_client_id(self.base_dir) or os.environ.get("LITEBROWSER_GOOGLE_CLIENT_ID", "")
        if not client_id:
            self.configure_google_oauth_client_id()
            client_id = prefs.get_google_oauth_client_id(self.base_dir) or os.environ.get("LITEBROWSER_GOOGLE_CLIENT_ID", "")
            if not client_id:
                return
        self._google_auth_running = True
        self._google_client_id = client_id
        future = self._executor.submit(google_auth.request_device_code, client_id)
        future.add_done_callback(lambda done: self._worker_relay.post(lambda: self._on_device_code_ready(done)))

    def _on_device_code_ready(self, future):
        try:
            device = future.result()
        except google_auth.GoogleAuthError as exc:
            self._google_auth_running = False
            QMessageBox.warning(self, "Google OAuth", str(exc))
            return
        except Exception as exc:
            self._google_auth_running = False
            QMessageBox.warning(self, "Google OAuth", f"Error:\n{exc}")
            return
        verification_url = device.get("verification_url", "https://www.google.com/device")
        user_code = device.get("user_code", "")
        minutes = int(device.get("expires_in", 1800) or 1800) // 60
        QMessageBox.information(
            self,
            "Google Sign-In — Device Code",
            "Step 1: Open this URL in any browser (Chrome, Edge, phone):\n"
            f"    {verification_url}\n\n"
            "Step 2: Enter this code when prompted:\n"
            f"    {user_code}\n\n"
            "Step 3: Sign in to your Google account.\n\n"
            "Mei will detect when you've completed sign-in.\n"
            f"Code expires in {minutes} minutes.",
        )
        future = self._executor.submit(google_auth.poll_device_token, self._google_client_id or "", device)
        future.add_done_callback(lambda done: self._worker_relay.post(lambda: self._finish_google_auth(done)))

    def _finish_google_auth(self, future):
        self._google_auth_running = False
        try:
            result = future.result()
        except google_auth.GoogleAuthError as exc:
            QMessageBox.warning(self, "Google OAuth", str(exc))
            return
        except Exception as exc:
            QMessageBox.warning(self, "Google OAuth", f"Error:\n{exc}")
            return
        if result:
            prefs.set_google_account(self.base_dir, result.get("account", {}))
            prefs.set_google_token_cache(self.base_dir, result.get("tokens", {}))
            account = result.get("account", {})
            label = account.get("email") or account.get("name") or "Google account"
            QMessageBox.information(self, "Google OAuth", f"Signed in as {label}.")

    def show_google_account_status(self):
        account = prefs.get_google_account(self.base_dir)
        if not account:
            QMessageBox.information(self, "Google account", "Mei is not signed in to a Google account.")
            return
        label = account.get("name") or "(no name)"
        email = account.get("email") or "(no email)"
        verified = "Yes" if account.get("email_verified") else "No"
        QMessageBox.information(
            self,
            "Google account",
            f"Name: {label}\nEmail: {email}\nEmail verified: {verified}",
        )

    def sign_out_google_account(self):
        prefs.clear_google_account(self.base_dir)
        QMessageBox.information(self, "Google account", "Cleared the saved Google account from this profile.")

    def _build_page_menu(self):
        menu = QMenu(self)
        menu.addAction("Home").triggered.connect(self._go_home)
        menu.addAction("Bookmark page").triggered.connect(lambda: self.save_bookmark(None))
        menu.addAction("Save to reading list").triggered.connect(self._add_to_reading_list)
        menu.addAction("Find in page").triggered.connect(self.find_text)
        menu.addAction("Reader mode").triggered.connect(self.toggle_reader_mode)
        menu.addSeparator()
        self.act_text_highlight = menu.addAction("✎ Highlight text to copy")
        self.act_text_highlight.setCheckable(True)
        self.act_text_highlight.setToolTip("Select any text to highlight it; a copy bubble appears next to the selection.")
        self.act_text_highlight.setChecked(prefs.get_text_highlight_enabled(self.base_dir))
        self.act_text_highlight.triggered.connect(self.toggle_text_highlight)
        menu.addSeparator()
        menu.addAction("Open externally").triggered.connect(self.open_current_in_external_browser)
        menu.addAction("Open accounts.google.com in Chrome / Edge").triggered.connect(
            lambda: self.open_url_in_external_browser("https://accounts.google.com/")
        )
        menu.addSeparator()
        menu.addAction("Zoom in").triggered.connect(self.zoom_in)
        menu.addAction("Zoom out").triggered.connect(self.zoom_out)
        menu.addAction("Reset zoom").triggered.connect(self.zoom_reset)
        menu.addSeparator()
        trans_menu = menu.addMenu("Translate")
        trans_menu.addAction("Translate this page (Google)").triggered.connect(lambda: self._translate_page("google"))
        trans_menu.addAction("Translate this page (Bing)").triggered.connect(lambda: self._translate_page("bing"))
        menu.addSeparator()
        self.act_page_disable_webgl = menu.addAction("Lite Rendering (Disable WebGL)")
        self.act_page_disable_webgl.setCheckable(True)
        self.act_page_disable_webgl.triggered.connect(self.toggle_disable_webgl)
        menu.addAction("Developer tools").triggered.connect(self.show_dev_tools)
        menu.addAction("More browser options").triggered.connect(lambda: self.btn_options.showMenu())
        return menu

    @staticmethod
    def _build_clean_ua(profile):
        raw_ua = profile.httpUserAgent() or ""
        m = re.search(r"Chrome/(\d+)", raw_ua)
        ver = m.group(1) if m else "122"
        return (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            f"Chrome/{ver}.0.0.0 Safari/537.36"
        )

    def _shell_slot(self):
        slot = (getattr(self, "_window_slot_hint", "") or "").strip()
        return slot if slot in ("primary", "secondary") else "shared"

    def _configure_web_profile(self, profile, off_the_record=False):
        data_path = app_paths.browser_data_path(self.base_dir)
        slot = self._shell_slot()
        slot_dir = os.path.join(data_path, slot)
        os.makedirs(slot_dir, exist_ok=True)
        chrome_ua = self._build_clean_ua(profile)
        profile.setHttpUserAgent(chrome_ua)
        if hasattr(profile, "setHttpAcceptLanguage"):
            profile.setHttpAcceptLanguage("en-US,en;q=0.9")
        if off_the_record:
            profile.setPersistentCookiesPolicy(QWebEngineProfile.NoPersistentCookies)
            if hasattr(profile, "setHttpCacheType"):
                profile.setHttpCacheType(QWebEngineProfile.MemoryHttpCache)
        else:
            profile.setPersistentStoragePath(slot_dir)
            cache_path = os.path.join(slot_dir, "Cache")
            try:
                os.makedirs(cache_path, exist_ok=True)
                profile.setCachePath(cache_path)
            except Exception as exc:
                print("Warning: failed to initialize disk cache, falling back to memory cache:", exc)
                if hasattr(profile, "setHttpCacheType"):
                    profile.setHttpCacheType(QWebEngineProfile.MemoryHttpCache)
            profile.setPersistentCookiesPolicy(QWebEngineProfile.ForcePersistentCookies)
        profile.downloadRequested.connect(self.handle_download_request)
        settings = profile.settings()
        settings.setAttribute(QWebEngineSettings.JavascriptEnabled, True)
        settings.setAttribute(QWebEngineSettings.JavascriptCanOpenWindows, True)
        settings.setAttribute(QWebEngineSettings.LocalContentCanAccessRemoteUrls, True)
        settings.setAttribute(QWebEngineSettings.LocalContentCanAccessFileUrls, False)
        settings.setAttribute(QWebEngineSettings.XSSAuditingEnabled, False)
        settings.setAttribute(QWebEngineSettings.AllowRunningInsecureContent, False)
        # NPAPI-style plug-ins are legacy and keep unnecessary helpers alive.
        settings.setAttribute(QWebEngineSettings.PluginsEnabled, False)
        settings.setAttribute(QWebEngineSettings.ScrollAnimatorEnabled, False)
        settings.setAttribute(QWebEngineSettings.AutoLoadImages, not prefs.get_browser_data_saver(self.base_dir))
        settings.setAttribute(QWebEngineSettings.LocalStorageEnabled, True)
        settings.setAttribute(QWebEngineSettings.ErrorPageEnabled, True)
        settings.setAttribute(QWebEngineSettings.FocusOnNavigationEnabled, True)
        settings.setAttribute(QWebEngineSettings.FullScreenSupportEnabled, True)
        settings.setAttribute(QWebEngineSettings.WebGLEnabled, not prefs.get_disable_webgl(self.base_dir))
        if hasattr(QWebEngineSettings, "Accelerated2dCanvasEnabled"):
            # Canvas-heavy local apps (LinkLumina) paint much smoother on the GPU.
            settings.setAttribute(QWebEngineSettings.Accelerated2dCanvasEnabled, True)
        if hasattr(QWebEngineSettings, "DnsPrefetchEnabled"):
            # Warm DNS lookups reduce the perceived lag when a site first opens.
            settings.setAttribute(QWebEngineSettings.DnsPrefetchEnabled, True)
        if hasattr(QWebEngineSettings, "PlaybackRequiresUserGesture"):
            # Background tabs should never wake a renderer simply to autoplay.
            settings.setAttribute(QWebEngineSettings.PlaybackRequiresUserGesture, True)
        if hasattr(QWebEngineSettings, "ServiceWorkersEnabled"):
            settings.setAttribute(QWebEngineSettings.ServiceWorkersEnabled, True)
        if hasattr(QWebEngineSettings, "NavigateOnDropEnabled"):
            settings.setAttribute(QWebEngineSettings.NavigateOnDropEnabled, True)
        if hasattr(profile, "setHttpCacheMaximumSize"):
            # Keep cache useful without allowing two shell windows to reserve a
            # large chunk of memory/disk for speculative page data.
            profile.setHttpCacheMaximumSize(64 * 1024 * 1024)
        if hasattr(QWebEngineSettings, "HyperlinkAuditingEnabled"):
            settings.setAttribute(QWebEngineSettings.HyperlinkAuditingEnabled, False)

    def get_profile_for_url(self, qurl=None, is_incognito=False):
        return self.profile

    def _host_from_url(self, value) -> str:
        try:
            if isinstance(value, QUrl):
                return (value.host() or "").lower()
            return (urlparse(value).netloc or "").lower()
        except Exception:
            return ""

    def is_compatibility_host(self, value) -> bool:
        host = self._host_from_url(value)
        return any(host == item or host.endswith("." + item) for item in COMPATIBILITY_HOSTS)

    def _should_preserve_site_native_ui(self, value) -> bool:
        host = self._host_from_url(value)
        if not host:
            return False
        native_ui_hosts = (
            "accounts.google.com",
            "gemini.google.com",
            "google.com",
            "www.google.com",
            "youtube.com",
            "www.youtube.com",
            "bing.com",
            "www.bing.com",
        )
        return any(host == item or host.endswith("." + item) for item in native_ui_hosts)

    def get_new_tab_html(self):
        engine = prefs.get_search_engine(self.base_dir)
        mode = prefs.get_shell_theme(self.base_dir)
        accent = prefs.get_accent(self.base_dir)
        # build_new_tab_html re-reads history + bookmarks and formats ~30 KB of
        # HTML per tab open; cache it briefly so rapid tab creation stays snappy.
        cache = getattr(self, "_new_tab_html_cache", None)
        key = (engine, mode, accent)
        now = time.time()
        if cache and cache[0] == key and (now - cache[1]) < 30.0:
            return cache[2]
        html = new_tab_page.build_new_tab_html(
            self.base_dir,
            getattr(self, "app_dir", None),
            engine,
            mode=mode,
            accent=accent,
        )
        self._new_tab_html_cache = (key, now, html)
        return html

    def add_new_tab(self, qurl=None, label="New Tab", is_active=True, is_incognito=False):
        self.tab_manager.add_tab(qurl, label, is_active, is_incognito)
        self._apply_workspace_filter()

    def current_browser(self):
        return self.tab_manager.current_browser()

    def _on_change_tab(self, i):
        self.tab_manager.change_tab(i)

    def _refresh_workspace_combo(self):
        self.workspace_combo.blockSignals(True)
        self.workspace_combo.clear()
        for w in workspace_manager.get_workspaces_list(self.base_dir):
            self.workspace_combo.addItem(w["name"], w["id"])
        idx = self.workspace_combo.findData(self.current_workspace_id)
        if idx >= 0:
            self.workspace_combo.setCurrentIndex(idx)
        self.workspace_combo.blockSignals(False)

    def _on_workspace_changed(self, index):
        if index < 0:
            return
        ws_id = self.workspace_combo.currentData()
        if ws_id is None:
            return
        self.current_workspace_id = ws_id
        workspace_manager.set_current_id(self.base_dir, ws_id)
        self._apply_workspace_filter()

    def focus_tab_filter(self):
        """Open the tab desk and put keyboard focus straight into its filter."""
        if self.sidebar_collapsed:
            self._toggle_sidebar_collapse()
        self._switch_sidebar_panel(0)
        self.tab_filter.setFocus()
        self.tab_filter.selectAll()

    def _tab_url_at(self, index):
        item = self.tab_list.item(index)
        metadata = dict(item.data(TAB_META_ROLE) or {}) if item else {}
        url = metadata.get("url", "")
        browser = self.browsers[index] if 0 <= index < len(self.browsers) else None
        if browser is not None:
            try:
                live_url = browser.url().toString()
                if live_url and live_url != "about:blank":
                    url = live_url
            except Exception:
                pass
        return (url or "").strip()

    def copy_workspace_urls(self):
        ws_role = Qt.UserRole + workspace_manager.WORKSPACE_ROLE
        urls = []
        for index in range(self.tab_list.count()):
            item = self.tab_list.item(index)
            if not item or item.data(ws_role) != self.current_workspace_id:
                continue
            url = self._tab_url_at(index)
            if url and url not in ("about:blank", "about:newtab"):
                urls.append(url)
        if not urls:
            QMessageBox.information(self, "Tab Center", "No page URLs in this workspace yet.")
            return
        QApplication.clipboard().setText("\n".join(urls))
        QMessageBox.information(self, "Tab Center", f"Copied {len(urls)} URLs.")

    def close_duplicate_tabs(self):
        """Close duplicate page URLs without touching the active or pinned tab."""
        ws_role = Qt.UserRole + workspace_manager.WORKSPACE_ROLE
        current_row = self.tab_list.currentRow()
        seen = set()
        if current_row >= 0:
            current_url = self._tab_url_at(current_row).split("#", 1)[0].rstrip("/").lower()
            if current_url:
                seen.add(current_url)
        duplicates = []
        for index in range(self.tab_list.count() - 1, -1, -1):
            if index == current_row:
                continue
            item = self.tab_list.item(index)
            if not item or item.data(ws_role) != self.current_workspace_id or item.data(TAB_PINNED_ROLE):
                continue
            normalized = self._tab_url_at(index).split("#", 1)[0].rstrip("/").lower()
            if not normalized or normalized in ("about:blank", "about:newtab"):
                continue
            if normalized in seen:
                duplicates.append(index)
            else:
                seen.add(normalized)
        for index in duplicates:
            self.tab_manager.close_tab(index)
        if duplicates:
            QMessageBox.information(self, "Tab Center", f"Closed {len(duplicates)} duplicate tabs.")
        else:
            QMessageBox.information(self, "Tab Center", "No duplicate URLs found in this workspace.")

    def _queue_tab_filter(self, _text=""):
        """Debounce filter work so a 400-tab workspace stays responsive while typing."""
        if hasattr(self, "_tab_filter_timer"):
            self._tab_filter_timer.start()

    def _tab_matches_filter(self, index, item, query):
        if not query:
            return True
        metadata = dict(item.data(TAB_META_ROLE) or {})
        browser = self.browsers[index] if 0 <= index < len(self.browsers) else None
        hibernated = bool(metadata.get("hibernated"))
        if browser is not None:
            try:
                hibernated = bool(browser.property("hibernated"))
            except Exception:
                pass
        title = (metadata.get("title") or "").lower()
        url = (metadata.get("url") or "").lower()
        widget = item.data(Qt.UserRole)
        if not title and widget:
            try:
                title = widget.text().lower()
            except Exception:
                pass
        host = self._host_from_url(url)
        haystack = " ".join((title, url, host))
        for term in (part.strip().lower() for part in query.split() if part.strip()):
            if term in ("is:sleeping", "is:hibernated", "sleeping", "hibernated"):
                if not hibernated:
                    return False
            elif term in ("is:active", "active"):
                if hibernated:
                    return False
            elif term in ("is:pinned", "pinned"):
                if not bool(item.data(TAB_PINNED_ROLE)):
                    return False
            elif term.startswith("site:"):
                if term[5:] not in host:
                    return False
            elif term.startswith("group:"):
                if term[6:] not in (metadata.get("group") or "").lower():
                    return False
            elif term not in haystack:
                return False
        return True

    def _apply_tab_list_visibility(self):
        """Apply the current workspace and filter together; never let one undo the other."""
        ws_role = Qt.UserRole + workspace_manager.WORKSPACE_ROLE
        query = self.tab_filter.text().strip().lower() if hasattr(self, "tab_filter") else ""
        current_ws = self.current_workspace_id
        visible_rows = []
        for i in range(self.tab_list.count()):
            item = self.tab_list.item(i)
            tab_ws = item.data(ws_role) if item else None
            if tab_ws is None:
                tab_ws = workspace_manager.PRIMARY_WORKSPACE_ID
            visible = bool(item and tab_ws == current_ws and self._tab_matches_filter(i, item, query))
            item.setHidden(not visible)
            if visible:
                visible_rows.append(i)
        current_row = self.tab_list.currentRow()
        if visible_rows and (current_row not in visible_rows):
            # Only auto-switch when the current tab was hidden by a *workspace*
            # change, not by typing in the filter: switching rows loads a whole
            # different page, which is jarring mid-search (v6.4 UX bug).
            if not query:
                self.tab_list.setCurrentRow(visible_rows[0])
        return visible_rows

    def _apply_workspace_filter(self):
        self._apply_tab_list_visibility()
        self.tab_manager.update_tab_count()

    def _switch_sidebar_panel(self, index):
        self.sidebar_stack.setCurrentIndex(index)
        self._lazy_panel_refresh(index)

    def _lazy_panel_refresh(self, panel_index, force=False):
        current = self.sidebar_stack.currentIndex()
        if current == 1 and (force or self.bookmarks_tree.topLevelItemCount() == 0):
            self._load_bookmarks_panel()
        elif current == 2 and (force or self.history_list.count() == 0):
            self._load_history_panel()
        elif current == 3 and (force or self.downloads_list.count() == 0):
            self._load_downloads_panel()
        elif current == 4:
            self._load_reading_list()

    def _load_reading_list(self):
        self.reading_list.clear()
        pages = life_service.load_saved_pages(self.base_dir)
        for p in pages:
            title = (p.get("title") or p.get("url", ""))[:50]
            self.reading_list.addItem(title)
            self.reading_list.item(self.reading_list.count() - 1).setData(Qt.UserRole, p.get("url", ""))

    def _on_reading_clicked(self, item):
        url = item.data(Qt.UserRole)
        if url:
            self.tab_manager.add_tab(QUrl(url), is_active=True)

    def _add_to_reading_list(self):
        browser = self.current_browser()
        if not browser:
            return
        url = browser.url().toString()
        title = browser.title() or url
        life_service.add_saved_page(self.base_dir, title, url)
        self._load_reading_list()
        QMessageBox.information(self, "Saved", "Page added to your reading list.")

    def _filter_tab_list(self, text=""):
        self._apply_tab_list_visibility()
        self.tab_manager.update_tab_count()

    def _load_bookmarks_panel(self):
        self.bookmarks_tree.clear()
        folders = prefs.load_bookmark_folders(self.base_dir)
        folder_map = {f["id"]: f for f in folders}
        tree_folders = {}
        for f in folders:
            item = QTreeWidgetItem([f.get("name", "Unnamed")])
            item.setData(0, Qt.UserRole, ("folder", f["id"]))
            item.setIcon(0, self.style().standardIcon(type(self.style()).StandardPixmap.SP_DirIcon))
            tree_folders[f["id"]] = item
        for fid, item in tree_folders.items():
            parent_id = folder_map[fid].get("parent_id", "")
            if parent_id and parent_id in tree_folders:
                tree_folders[parent_id].addChild(item)
            else:
                self.bookmarks_tree.addTopLevelItem(item)
        for b in prefs.load_bookmarks(self.base_dir):
            title = (b.get("title") or "")[:40]
            url = (b.get("url") or "")[:60]
            bm_item = QTreeWidgetItem([f"{title}  {url}"])
            bm_item.setData(0, Qt.UserRole, ("bookmark", b.get("url", "")))
            bm_item.setIcon(0, self.style().standardIcon(type(self.style()).StandardPixmap.SP_FileIcon))
            folder_id = b.get("folder_id", "")
            if folder_id and folder_id in tree_folders:
                tree_folders[folder_id].addChild(bm_item)
            else:
                self.bookmarks_tree.addTopLevelItem(bm_item)
        self.bookmarks_tree.expandAll()

    def _add_bookmark_folder(self):
        name, ok = QInputDialog.getText(self, "Bookmark folder", "Folder name:")
        if ok and name.strip():
            folders = prefs.load_bookmark_folders(self.base_dir)
            fid = "folder_" + uuid.uuid4().hex[:8]
            current_item = self.bookmarks_tree.currentItem()
            parent_id = ""
            if current_item:
                kind, data = current_item.data(0, Qt.UserRole) or ("", "")
                if kind == "folder":
                    parent_id = data
            folders.append({"id": fid, "name": name.strip(), "parent_id": parent_id})
            prefs.save_bookmark_folders(self.base_dir, folders)
            self._load_bookmarks_panel()

    def _show_bookmark_context_menu(self, pos):
        item = self.bookmarks_tree.itemAt(pos)
        menu = QMenu()
        add_folder_action = menu.addAction("+ Add subfolder" if item else "+ Add folder")
        add_bm_action = menu.addAction("+ Add bookmark here")
        menu.addSeparator()
        rename_action = None
        delete_action = None
        if item:
            kind, data = item.data(0, Qt.UserRole) or ("", "")
            if kind == "folder":
                rename_action = menu.addAction("Rename folder")
                delete_action = menu.addAction("Delete folder")
            else:
                delete_action = menu.addAction("Delete bookmark")
        action = menu.exec_(self.bookmarks_tree.viewport().mapToGlobal(pos))
        if action == add_folder_action:
            self._add_bookmark_folder()
        elif action == add_bm_action:
            self.save_bookmark()
        if delete_action and action == delete_action:
            kind, data = item.data(0, Qt.UserRole) or ("", "")
            if kind == "folder":
                folders = [f for f in prefs.load_bookmark_folders(self.base_dir) if f["id"] != data]
                bookmarks = [b for b in prefs.load_bookmarks(self.base_dir) if b.get("folder_id") != data]
                prefs.save_bookmark_folders(self.base_dir, folders)
                prefs.save_bookmarks(self.base_dir, bookmarks)
            else:
                bookmarks = [b for b in prefs.load_bookmarks(self.base_dir) if b.get("url") != data]
                prefs.save_bookmarks(self.base_dir, bookmarks)
            self._load_bookmarks_panel()
        if rename_action and action == rename_action:
            kind, data = item.data(0, Qt.UserRole) or ("", "")
            if kind == "folder":
                name, ok = QInputDialog.getText(self, "Rename", "New name:", text=item.text(0))
                if ok and name.strip():
                    folders = prefs.load_bookmark_folders(self.base_dir)
                    for f in folders:
                        if f["id"] == data:
                            f["name"] = name.strip()
                            break
                    prefs.save_bookmark_folders(self.base_dir, folders)
                    self._load_bookmarks_panel()

    def _load_history_panel(self):
        self.history_list.clear()
        session_state = prefs.session_state_load(self.base_dir)
        for item in session_state.get("recently_closed", [])[:12]:
            if item.get("kind") == "window":
                tabs = item.get("tabs", [])
                if not tabs:
                    continue
                title = item.get("title") or f"Window with {len(tabs)} tabs"
                self.history_list.addItem(f"[Recent] {title}")
                self.history_list.item(self.history_list.count() - 1).setData(Qt.UserRole, item)
                continue
            title = item.get("title") or item.get("url", "")
            url = item.get("url", "")
            if not url:
                continue
            self.history_list.addItem(f"[Recent] {title[:48]}")
            self.history_list.item(self.history_list.count() - 1).setData(Qt.UserRole, item)
        entries = prefs.load_history_entries(self.base_dir)
        entries.sort(key=lambda x: -x[0])
        seen = set()
        for ts, url in entries[:100]:
            if url in seen or not url.startswith("http"):
                continue
            seen.add(url)
            short = url.replace("https://", "").replace("http://", "")[:55]
            self.history_list.addItem(short)
            self.history_list.item(self.history_list.count() - 1).setData(Qt.UserRole, url)

    def _load_downloads_panel(self):
        from litebrowser.services import download_mgr
        self.downloads_list.clear()
        for i, d in enumerate(download_mgr.load_list(self.base_dir)):
            self.downloads_list.addItem(f"{d.get('status', '?')}  {d.get('filename', '')[:50]}")
            self.downloads_list.item(self.downloads_list.count() - 1).setData(Qt.UserRole, (i, d.get("path", "")))

    def _on_bookmark_clicked(self, item):
        kind, data = item.data(0, Qt.UserRole) or ("", "")
        if kind == "bookmark" and data:
            self.tab_manager.add_tab(QUrl(data), item.text(0)[:30], is_active=True)

    def _on_history_clicked(self, item):
        data = item.data(Qt.UserRole)
        if isinstance(data, dict) and data.get("kind") == "window":
            tabs = data.get("tabs", [])
            if not tabs:
                return
            for idx, tab in enumerate(tabs):
                url = tab.get("url", "")
                if not url:
                    continue
                self.tab_manager.add_tab(QUrl(url), tab.get("title") or "Loading...", is_active=(idx == 0), session_data=tab)
            return
        if isinstance(data, dict):
            url = data.get("url", "")
        else:
            url = data
        if url:
            self.tab_manager.add_tab(QUrl(url), item.text()[:30], is_active=True, session_data=(data if isinstance(data, dict) else None))

    def _on_download_clicked(self, item):
        data = item.data(Qt.UserRole)
        if data and isinstance(data, (list, tuple)) and len(data) >= 2:
            path = data[1]
            if path and os.path.exists(path):
                try:
                    os.startfile(path)
                except Exception:
                    pass

    def apply_styles(self):
        theme_name = prefs.get_shell_theme(self.base_dir)
        accent = prefs.get_accent(self.base_dir)
        qss = theme.main_qss(theme_name, accent)
        self.btn_collapse_sidebar.setStyleSheet(theme.collapse_btn_qss(theme_name, accent))
        self.setStyleSheet(qss)
        self._apply_dynamic_background_overlay()

    def _load_ui_dynamic_background_pref(self):
        self.act_dynamic_bg.blockSignals(True)
        self.act_dynamic_bg.setChecked(prefs.get_ui_dynamic_background(self.base_dir))
        self.act_dynamic_bg.blockSignals(False)
        if self.act_dynamic_bg.isChecked() and not self._dynamic_bg_timer.isActive():
            self._dynamic_bg_timer.start(7200)

    def _load_data_saver_pref(self):
        if not hasattr(self, "act_data_saver"):
            return
        self.act_data_saver.blockSignals(True)
        self.act_data_saver.setChecked(prefs.get_browser_data_saver(self.base_dir))
        self.act_data_saver.blockSignals(False)

    def toggle_data_saver(self):
        enabled = bool(self.act_data_saver.isChecked())
        prefs.set_browser_data_saver(self.base_dir, enabled)
        profiles = [self.profile] + list(getattr(self, "_incognito_profiles", [])) + list(
            getattr(self, "_trusted_site_profiles", {}).values()
        )
        seen = set()
        for profile in profiles:
            if profile is None or id(profile) in seen:
                continue
            seen.add(id(profile))
            try:
                profile.settings().setAttribute(QWebEngineSettings.AutoLoadImages, not enabled)
            except Exception:
                pass

    def _load_disable_webgl_pref(self):
        value = prefs.get_disable_webgl(self.base_dir)
        for act in (getattr(self, "act_disable_webgl", None), getattr(self, "act_page_disable_webgl", None)):
            if act is None:
                continue
            act.blockSignals(True)
            act.setChecked(value)
            act.blockSignals(False)

    def toggle_disable_webgl(self, checked=None):
        # Qt passes the new checked state of the triggering action; fall back to
        # the sidebar action's state when invoked programmatically.
        if checked is None:
            checked = bool(getattr(self, "act_disable_webgl", None) and self.act_disable_webgl.isChecked())
        enabled = bool(checked)
        prefs.set_disable_webgl(self.base_dir, enabled)
        # Keep both menu actions in sync.
        for act in (getattr(self, "act_disable_webgl", None), getattr(self, "act_page_disable_webgl", None)):
            if act is None:
                continue
            act.blockSignals(True)
            act.setChecked(enabled)
            act.blockSignals(False)
        profiles = [self.profile] + list(getattr(self, "_incognito_profiles", [])) + list(
            getattr(self, "_trusted_site_profiles", {}).values()
        )
        seen = set()
        for profile in profiles:
            if profile is None or id(profile) in seen:
                continue
            seen.add(id(profile))
            try:
                profile.settings().setAttribute(QWebEngineSettings.WebGLEnabled, not enabled)
                # Runtime toggling also needs the page-level shim: WebGLEnabled is
                # only read at renderer creation, but this script kills the WebGL
                # entry points on every page and works immediately after reload.
                ensure_webgl_disable_script(profile, enabled)
            except Exception:
                pass
        # Apply to every open tab too (profile defaults don't affect live views),
        # then reload the current page so the change is visible right away.
        for browser in list(getattr(self, "browsers", []) or []):
            if browser is None:
                continue
            try:
                browser.settings().setAttribute(QWebEngineSettings.WebGLEnabled, not enabled)
            except Exception:
                pass
        current = self.current_browser()
        if current is not None:
            try:
                current.reload()
            except Exception:
                pass

    def _load_defer_background_pref(self):
        if not hasattr(self, "act_defer_background"):
            return
        self.act_defer_background.blockSignals(True)
        self.act_defer_background.setChecked(prefs.get_defer_background_tabs(self.base_dir))
        self.act_defer_background.blockSignals(False)

    def toggle_defer_background(self):
        enabled = bool(self.act_defer_background.isChecked())
        prefs.set_defer_background_tabs(self.base_dir, enabled)
        # Existing open tabs are unaffected; the setting governs tabs opened from
        # now on. Freeze the current background tabs immediately if turned on so
        # the choice has an instant effect.
        if enabled:
            self.tab_manager.optimize_memory(notify=False)

    def _refresh_adblock_subscriptions_async(self):
        if not prefs.get_adblock_subscriptions(self.base_dir):
            return

        def _run():
            try:
                adblock.fetch_and_update_subscriptions(self.base_dir)
                return True
            except Exception:
                return False

        def _done(future):
            try:
                if future.result() and getattr(self, "interceptor", None) is not None:
                    self.interceptor.reload_filter_file()
            except Exception:
                pass

        future = self._executor.submit(_run)
        future.add_done_callback(lambda f: self._worker_relay.post(lambda: _done(f)))

    def _refresh_adblock_now(self):
        def _run():
            try:
                adblock.fetch_and_update_subscriptions(self.base_dir)
                return True
            except Exception:
                return False

        def _done(future):
            try:
                ok = bool(future.result())
            except Exception:
                ok = False
            if getattr(self, "interceptor", None) is not None:
                self.interceptor.reload_filter_file()
            QMessageBox.information(
                self,
                "Adblock",
                "Đã cập nhật bộ lọc quảng cáo." if ok else "Chưa có danh sách đăng ký hoặc cập nhật thất bại.",
            )

        future = self._executor.submit(_run)
        future.add_done_callback(lambda f: self._worker_relay.post(lambda: _done(f)))

    def _auto_memory_saver_tick(self):
        """Chrome-style memory saver: freeze background tabs when RAM runs hot."""
        rss = _process_rss_mb()
        if rss is None or rss < MEMORY_SAVER_RSS_THRESHOLD_MB:
            return
        self.tab_manager.optimize_memory(notify=False)

    def _drain_open_requests(self):
        """Open URLs requested by the Android bridge (MeiRemote "open app")."""
        try:
            from litebrowser.services import open_request

            requests = open_request.drain_open_requests(self.base_dir)
        except Exception:
            return
        for req in requests:
            url = str(req.get("url") or "").strip()
            if not url.startswith(("http://", "https://", "file://")):
                continue
            label = str(req.get("label") or "").strip() or url
            try:
                self.add_new_tab(QUrl(url), label, is_active=True)
            except Exception:
                pass

    def _live_sleeping_counts(self):
        live = 0
        sleeping = 0
        for browser in self.browsers:
            if browser is None:
                sleeping += 1
            elif browser.property("hibernated"):
                sleeping += 1
            else:
                live += 1
        return live, sleeping

    def show_performance_dashboard(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("Bảng đo hiệu năng — Mei")
        dlg.resize(440, 260)
        layout = QVBoxLayout(dlg)
        title = QLabel("Bảng đo hiệu năng")
        title.setObjectName("SectionTitle")
        layout.addWidget(title)
        lbl_ram = QLabel("")
        lbl_tabs = QLabel("")
        lbl_heap = QLabel("JS heap tab hiện tại: đang đo…")
        layout.addWidget(lbl_ram)
        layout.addWidget(lbl_tabs)
        layout.addWidget(lbl_heap)

        def _on_heap(value):
            try:
                val = float(value)
                if val >= 0:
                    lbl_heap.setText(f"JS heap tab hiện tại: {val:.1f} MB")
                else:
                    lbl_heap.setText("JS heap tab hiện tại: không khả dụng")
            except Exception:
                lbl_heap.setText("JS heap tab hiện tại: không khả dụng")

        def refresh():
            rss = _process_rss_mb()
            live, sleeping = self._live_sleeping_counts()
            lbl_ram.setText(
                f"RAM tiến trình: {rss} MB (Memory Saver kích hoạt > {MEMORY_SAVER_RSS_THRESHOLD_MB} MB)"
                if rss is not None
                else "RAM tiến trình: không đọc được trên hệ điều hành này"
            )
            lbl_tabs.setText(f"Tab: {live} live · {sleeping} sleeping")
            lbl_heap.setText("JS heap tab hiện tại: đang đo…")
            current = self.current_browser()
            if current is not None:
                current.page().runJavaScript(
                    "(function(){try{return (performance&&performance.memory)?(performance.memory.usedJSHeapSize/1048576):-1;}catch(e){return -1;}})();",
                    _on_heap,
                )

        refresh()
        row = QHBoxLayout()
        btn_refresh = QPushButton("Đo lại")
        btn_refresh.clicked.connect(refresh)
        btn_freeze = QPushButton("Freeze toàn bộ tab nền")
        btn_freeze.clicked.connect(lambda: (self.tab_manager.optimize_memory(notify=False), refresh()))
        row.addWidget(btn_refresh)
        row.addWidget(btn_freeze)
        layout.addLayout(row)
        dlg.exec_()

    def _tick_dynamic_background(self):
        self._dynamic_bg_phase += 1
        self._apply_dynamic_background_overlay()

    def _apply_dynamic_background_overlay(self):
        if not getattr(self, "act_dynamic_bg", None) or not self.act_dynamic_bg.isChecked():
            if hasattr(self, "central_widget"):
                self.central_widget.setStyleSheet("")
            return
        # A setStyleSheet with a new string re-polishes the whole widget tree
        # (sidebar + tabs + content). Skip the churn when the window is hidden
        # or minimized so background windows cost nothing.
        if not self.isVisible() or self.windowState() & (Qt.WindowMinimized | Qt.WindowMaximized) == Qt.WindowMinimized:
            return
        theme_name = prefs.get_shell_theme(self.base_dir)
        self.central_widget.setStyleSheet(
            theme.dynamic_main_widget_css(theme_name, self._dynamic_bg_phase, prefs.get_accent(self.base_dir))
        )

    def toggle_ui_dynamic_background(self):
        on = self.act_dynamic_bg.isChecked()
        prefs.set_ui_dynamic_background(self.base_dir, on)
        if on:
            if not self._dynamic_bg_timer.isActive():
                self._dynamic_bg_timer.start(7200)
        else:
            self._dynamic_bg_timer.stop()
            self.central_widget.setStyleSheet("")
        self.apply_styles()

    def open_linklumina_archive_folder(self):
        path = app_paths.linklumina_archive_dir(getattr(self, "app_dir", None))
        app_paths.ensure_linklumina_user_layout(getattr(self, "app_dir", None))
        QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def _maybe_local_workspace_perf_hints(self, browser):
        url = (browser.url().toString() or "").lower()
        if not url.startswith("file:"):
            return
        if "/link/" not in url and "cucquanly" not in url and "c%E1%BB%A5c" not in url:
            return
        browser.page().runJavaScript(
            "(function(){try{document.documentElement.style.textRendering='optimizeSpeed';}catch(e){}})();"
        )

    def _dialog_stylesheet(self):
        return theme.dialog_qss(prefs.get_shell_theme(self.base_dir), prefs.get_accent(self.base_dir))

    def _palette_lookup(self, key):
        from litebrowser.ui import theme as _th
        return _th._palette(prefs.get_shell_theme(self.base_dir), prefs.get_accent(self.base_dir))[key]


    def show_tab_context_menu(self, pos):
        item = self.tab_list.itemAt(pos)
        if not item:
            return
        row = self.tab_list.row(item)
        if row < 0 or row >= len(self.browsers):
            return
        browser = self.browsers[row]
        is_current = browser is not None and browser == self.current_browser()
        is_pinned = bool(item.data(TAB_PINNED_ROLE))
        menu = QMenu()
        copy_url_action = menu.addAction("Copy tab URL")
        suspend_action = menu.addAction("Suspend tab")
        suspend_action.setEnabled(browser is not None and not is_current and not is_pinned)
        mute_action = menu.addAction("Mute / Unmute")
        mute_action.setEnabled(browser is not None)
        reload_action = menu.addAction("Auto-Reload (10s)")
        reload_action.setEnabled(browser is not None)
        pin_action = menu.addAction("Pin / Unpin")
        dup_action = menu.addAction("Duplicate Tab")
        move_menu = menu.addMenu("Move to workspace")
        workspace_actions = {}
        for workspace in workspace_manager.get_workspaces_list(self.base_dir):
            move_action = move_menu.addAction(workspace.get("name") or "Workspace")
            workspace_actions[move_action] = workspace.get("id")
        menu.addSeparator()
        close_others_action = menu.addAction("Close other tabs in this workspace")
        close_action = menu.addAction("Close Tab")
        close_action.setEnabled(not is_pinned)
        action = menu.exec_(self.tab_list.mapToGlobal(pos))
        metadata = dict(item.data(TAB_META_ROLE) or {})
        if action == copy_url_action:
            url = metadata.get("url", "")
            if not url and browser is not None:
                try:
                    url = browser.url().toString()
                except Exception:
                    url = ""
            if url:
                QApplication.clipboard().setText(url)
        elif action == suspend_action:
            if browser is not None:
                self.tab_manager.hibernate_tab(browser, item)
        elif action in workspace_actions:
            target_workspace = workspace_actions.get(action)
            if target_workspace:
                item.setData(Qt.UserRole + workspace_manager.WORKSPACE_ROLE, target_workspace)
                self._apply_workspace_filter()
        elif action == close_others_action:
            ws_role = Qt.UserRole + workspace_manager.WORKSPACE_ROLE
            current_workspace = item.data(ws_role)
            rows_to_close = [
                idx
                for idx in range(self.tab_list.count())
                if idx != row
                and self.tab_list.item(idx).data(ws_role) == current_workspace
                and not bool(self.tab_list.item(idx).data(TAB_PINNED_ROLE))
            ]
            for idx in reversed(rows_to_close):
                self.tab_manager.close_tab(idx)
        elif action == mute_action:
            if browser is None:
                return
            browser.page().setAudioMuted(not browser.page().isAudioMuted())
            state = "Muted" if browser.page().isAudioMuted() else "Unmuted"
            self._flash_status(f"{state} for this tab")
        elif action == reload_action:
            if browser is None:
                return
            timer = browser.property("auto_reload_timer")
            if timer:
                timer.stop()
                browser.setProperty("auto_reload_timer", None)
                self._flash_status("Auto-reload turned OFF")
            else:
                timer = QTimer(browser)
                timer.timeout.connect(browser.reload)
                timer.start(10000)
                browser.setProperty("auto_reload_timer", timer)
                self._flash_status("This tab will auto-reload every 10 seconds")
        elif action == pin_action:
            is_pinned = bool(item.data(TAB_PINNED_ROLE))
            self.tab_manager.set_tab_pinned(row, not is_pinned)
        elif action == dup_action:
            self.tab_manager.duplicate_tab_at_row(row)
        elif action == close_action:
            self.tab_manager.close_tab(row)

    def toggle_fullscreen(self):
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()

    def _flash_status(self, message: str):
        """Non-modal toast: transient feedback without dialog spam (v6.4 used
        a modal QMessageBox for routine actions like mute/auto-reload).
        Styling comes from the shell QSS (#ToastLabel) so it follows the theme."""
        if getattr(self, "_toast_label", None) is None:
            self._toast_label = QLabel(self.central_widget)
            self._toast_label.setObjectName("ToastLabel")
            self._toast_label.hide()
            self._toast_timer = QTimer(self)
            self._toast_timer.setSingleShot(True)
            self._toast_timer.timeout.connect(self._toast_label.hide)
        toast = self._toast_label
        toast.setText(message)
        toast.adjustSize()
        margin = 24
        x = self.central_widget.width() - toast.width() - margin
        y = self.central_widget.height() - toast.height() - margin
        toast.move(max(margin, x), max(margin, y))
        toast.raise_()
        toast.show()
        self._toast_timer.start(2200)

    def update_urlbar(self, q, browser=None):
        if browser != self.current_browser():
            return
        url_str = q.toString()
        self.url_bar.setText(url_str)
        self.url_bar.setCursorPosition(0)
        if hasattr(self, "lbl_site_state"):
            if url_str.startswith("https://"):
                self.lbl_site_state.setText("Secure")
                self.lbl_site_state.setStyleSheet("color: %s;" % self._palette_lookup("SUCCESS"))
            elif url_str.startswith("http://"):
                self.lbl_site_state.setText("HTTP")
                self.lbl_site_state.setStyleSheet("color: %s;" % self._palette_lookup("DANGER"))
            elif url_str.startswith("about:"):
                self.lbl_site_state.setText("Local")
                self.lbl_site_state.setStyleSheet("")
            elif url_str.startswith("file:"):
                self.lbl_site_state.setText("File")
                self.lbl_site_state.setStyleSheet("")
            else:
                self.lbl_site_state.setText("Search")
                self.lbl_site_state.setStyleSheet("")
        tt = url_str if url_str else "URL or search..."
        if url_str.startswith("http://") and not url_str.startswith("https://"):
            tt += "\n\nWarning: unencrypted connection (HTTP)."
        self.url_bar.setToolTip(tt)

    def record_history(self, qurl, browser=None):
        url_str = qurl.toString()
        if url_str.startswith("http"):
            prefs.append_history_entry(self.base_dir, url_str)
            # Attribute the visit to the tab that actually navigated; v6.4 read
            # the *current* tab's title, so background-tab redirects were logged
            # under whatever page the user was viewing.
            title = ""
            if browser is not None:
                try:
                    title = browser.title()
                except Exception:
                    title = ""
            if not title:
                try:
                    current = self.current_browser()
                    title = current.title() if current is not None else ""
                except Exception:
                    title = ""
            history_service.log_event(self.base_dir, "browser-visit", title or url_str, url_str, {"url": url_str})

    def on_title_changed(self, title, browser):
        try:
            i = self.browsers.index(browser)
            if browser.property("pending_url"):
                return
            if title:
                item = self.tab_list.item(i)
                widget = item.data(TAB_WIDGET_ROLE) if item else None
                if widget is not None:
                    widget.setText(title)
            if browser == self.current_browser():
                self.setWindowTitle(f"{title} - Mei")
        except Exception:
            pass

    def _get_cached_user_extension_scripts(self):
        if self._user_extension_scripts_cache is not None:
            return self._user_extension_scripts_cache
        scripts = []
        try:
            ext_conf_file = os.path.join(self.ext_path, "extensions.json")
            ext_config = {}
            if os.path.exists(ext_conf_file):
                with open(ext_conf_file, "r", encoding="utf-8") as f:
                    ext_config = json.load(f)
            ext_dir = self.ext_path
            for file_name in sorted(os.listdir(ext_dir)):
                if file_name.endswith(".js") and ext_config.get(file_name, False):
                    fpath = os.path.join(ext_dir, file_name)
                    with open(fpath, "r", encoding="utf-8") as f:
                        source = f.read()
                    matches, excludes, name = extension_patterns.parse_user_script_metadata(source)
                    scripts.append({
                        "name": name or file_name,
                        "source": source,
                        "matches": matches,
                        "excludes": excludes,
                    })
        except Exception as e:
            print("Extension load error:", e)
        self._user_extension_scripts_cache = scripts
        return scripts

    def invalidate_extension_cache(self):
        self._user_extension_scripts_cache = None

    def on_load_finished(self, ok, browser):
        if not ok:
            return
        host = (browser.url().host() or "").lower()
        saved_zoom = prefs.get_site_zoom(self.base_dir, host)
        if saved_zoom:
            browser.setZoomFactor(float(saved_zoom))
        preserve_native_ui = self._should_preserve_site_native_ui(browser.url())
        js_queue = []
        if not preserve_native_ui:
            js_queue.append(self._browser_compat_patch_js())
        if self.act_dark_mode.isChecked():
            js_queue.append(self._dark_mode_js(True))
        if not preserve_native_ui:
            page_url = browser.url().toString()
            js_queue.extend(
                ext["source"]
                for ext in self._get_cached_user_extension_scripts()
                if extension_patterns.script_matches(page_url, ext["matches"], ext["excludes"])
            )
        for js in js_queue:
            browser.page().runJavaScript(js)
        if prefs.get_password_manager_enabled(self.base_dir) and prefs.get_autofill_passwords(self.base_dir):
            try:
                from litebrowser.services import password_manager
                if password_manager.HAS_CRYPTO:
                    url_str = browser.url().toString()
                    if url_str.startswith("http"):
                        master = getattr(self, "_master_password", None)
                        if master is None:
                            master = dialogs.ask_master_password(self)
                            if master is not None:
                                self._master_password = master
                        if master:
                            cred = password_manager.get_credentials_for(self.base_dir, url_str, master)
                            if cred:
                                browser.page().runJavaScript(password_manager.build_autofill_script(cred["username"], cred["password"]))
            except Exception:
                pass
        host_l = (browser.url().host() or "").lower()
        on_accounts_google = host_l == "accounts.google.com" or host_l.endswith(".accounts.google.com")
        if self.is_compatibility_host(browser.url()) or on_accounts_google:
            title_now = (browser.title() or "").lower()
            url_now = browser.url().toString().lower()
            hay = title_now + " " + url_now
            bot_tokens = ("security verification", "verify you are human", "captcha", "challenge")
            google_block_tokens = (
                "not be secure",
                "couldn't sign you",
                "couldnt sign you",
                "try using a different browser",
                "browser or app may not be secure",
            )
            # Once per host per session: repeated redirects/loads must not nag
            # the user with the same modal every time (v6.4 did).
            if not hasattr(self, "_compat_notified_hosts"):
                self._compat_notified_hosts = set()
            already_notified = host_l in self._compat_notified_hosts
            if any(token in hay for token in bot_tokens):
                if not already_notified:
                    self._compat_notified_hosts.add(host_l)
                    self._flash_status("Anti-bot verification: use Page menu > Open externally")
            elif on_accounts_google and any(token in hay for token in google_block_tokens):
                if not already_notified:
                    self._compat_notified_hosts.add(host_l)
                    QMessageBox.information(
                        self,
                        "Google sign-in",
                        "Google often blocks sign-in inside embedded browsers (Qt WebEngine).\n\n"
                        "Use the page menu (Page) > Open externally to sign in with Chrome or Edge, "
                        "then use Mei for everything else if you prefer.",
                    )

                    if QMessageBox.question(
                        self,
                        "Open externally",
                        "Mei cannot complete Google sign-in here.\n\nOpen this page in Chrome or Edge now?",
                        QMessageBox.Yes | QMessageBox.No,
                        QMessageBox.Yes,
                    ) == QMessageBox.Yes:
                        self.open_url_in_external_browser(browser.url().toString())
        self._maybe_local_workspace_perf_hints(browser)

    def _browser_compat_patch_js(self):
        return """
        (function() {
            var host = (location.hostname || '').toLowerCase();
            var href = (location.href || '').toLowerCase();
            if (
                host.indexOf('accounts.google.com') >= 0 ||
                host.indexOf('claude.ai') >= 0 ||
                host.indexOf('chatgpt.com') >= 0 ||
                host.indexOf('copilot.microsoft.com') >= 0 ||
                host.indexOf('gemini.google.com') >= 0 ||
                host.indexOf('perplexity.ai') >= 0 ||
                href.indexOf('security verification') >= 0 ||
                href.indexOf('captcha') >= 0 ||
                href.indexOf('challenge') >= 0
            ) {
                return;
            }
            function upgrade(value) {
                if (!value || typeof value !== 'string') return value;
                if (value.indexOf('http://img.youtube.com/') === 0) return value.replace('http://', 'https://');
                if (value.indexOf('http://www.youtube.com/') === 0) return value.replace('http://', 'https://');
                return value;
            }
            ['img', 'source', 'iframe'].forEach(function(tag) {
                document.querySelectorAll(tag).forEach(function(el) {
                    ['src', 'data-src', 'data-thumb'].forEach(function(attr) {
                        if (el.hasAttribute(attr)) {
                            var next = upgrade(el.getAttribute(attr));
                            if (next !== el.getAttribute(attr)) {
                                el.setAttribute(attr, next);
                                if (attr === 'src') el.src = next;
                            }
                        }
                    });
                });
            });
        })();
        """

    def _dark_mode_js(self, enabled):
        if enabled:
            return """
            (function() {
                var host = (location.hostname || '').toLowerCase();
                var href = (location.href || '').toLowerCase();
                if (
                    host.indexOf('claude.ai') >= 0 ||
                    host.indexOf('chatgpt.com') >= 0 ||
                    host.indexOf('copilot.microsoft.com') >= 0 ||
                    host.indexOf('gemini.google.com') >= 0 ||
                    host.indexOf('perplexity.ai') >= 0 ||
                    host.indexOf('google.') >= 0 ||
                    host.indexOf('youtube.') >= 0 ||
                    host.indexOf('bing.') >= 0 ||
                    href.indexOf('security verification') >= 0 ||
                    href.indexOf('captcha') >= 0 ||
                    href.indexOf('challenge') >= 0
                ) {
                    var old = document.getElementById('lite-dark-mode');
                    if (old) old.remove();
                    return;
                }
                if (!document.getElementById('lite-dark-mode')) {
                    var style = document.createElement('style');
                    style.id = 'lite-dark-mode';
                    style.type = 'text/css';
                    style.innerHTML = 'html, body { background: #16110d !important; color: #eadfcd !important; } body { filter: none !important; } img, video, iframe, canvas, svg, picture { filter: none !important; }';
                    document.head.appendChild(style);
                }
            })();
            """
        return "var el = document.getElementById('lite-dark-mode'); if (el) el.parentNode.removeChild(el);"

    def _update_audio_indicators(self):
        for i in range(len(self.browsers)):
            browser = self.browsers[i]
            if browser is None:
                continue
            item = self.tab_list.item(i)
            if not item:
                continue
            widget = item.data(Qt.UserRole)
            if not widget:
                continue
            try:
                page = browser.page()
                if not page or not hasattr(page, "recentlyAudible"):
                    continue
                text = widget.lbl_title.text()
                sound_prefix = "[Sound] "
                base = text.removeprefix(sound_prefix)
                if page.recentlyAudible():
                    if not text.startswith(sound_prefix):
                        widget.lbl_title.setText(sound_prefix + base)
                else:
                    if text.startswith(sound_prefix):
                        widget.lbl_title.setText(base)
            except Exception:
                pass

    def _go_home(self):
        _, home_url = prefs.get_startup_prefs(self.base_dir)
        url = home_url or "https://google.com"
        if self.current_browser():
            self.current_browser().setUrl(QUrl(url))

    def focus_url_bar(self):
        self.url_bar.setFocus()
        self.url_bar.selectAll()

    def _apply_sidebar_collapse_visibility(self):
        """Thorough collapse: hide the whole tab desk except the expand toggle
        so the web view gets every spare pixel (Opera-GX-style thin rail)."""
        collapsed = bool(getattr(self, "sidebar_collapsed", False))
        tiny = self.width() < 900
        if hasattr(self, "brand_glyph"):
            self.brand_glyph.setVisible(not collapsed)
        if hasattr(self, "title_label"):
            self.title_label.setVisible(not tiny and not collapsed)
        if hasattr(self, "lbl_tab_count"):
            self.lbl_tab_count.setVisible(not tiny and not collapsed)
        if hasattr(self, "workspace_combo"):
            self.workspace_combo.setVisible(not tiny and not collapsed)
        for attr in (
            "sidebar_stack",
            "sidebar_footer",
            "btn_panel_tabs",
            "btn_panel_bookmarks",
            "btn_panel_history",
            "btn_panel_downloads",
            "btn_panel_reading",
        ):
            widget = getattr(self, attr, None)
            if widget is not None:
                widget.setVisible(not collapsed)
        if hasattr(self, "btn_collapse_sidebar"):
            self.btn_collapse_sidebar.setVisible(True)

    def _toggle_sidebar_collapse(self):
        self.sidebar_collapsed = not self.sidebar_collapsed
        self.btn_collapse_sidebar.setText("›" if self.sidebar_collapsed else "‹")
        self._apply_sidebar_collapse_visibility()
        rail = 30
        end_open = self._sidebar_expanded_nominal_width()
        start_w = max(rail, self.sidebarWidget.width())
        end_w = rail if self.sidebar_collapsed else min(end_open, max(rail + 20, self.main_splitter.width() // 3))

        if self._sidebar_anim:
            self._sidebar_anim.stop()
        self._sidebar_anim = QVariantAnimation(self)
        self._sidebar_anim.setDuration(240)
        self._sidebar_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._sidebar_anim.setStartValue(float(start_w))
        self._sidebar_anim.setEndValue(float(end_w))

        def _on_sidebar_width(v):
            w = max(rail, int(round(v)))
            self.sidebarWidget.setMinimumWidth(w)
            self.sidebarWidget.setMaximumWidth(w)
            sw = max(0, self.main_splitter.width())
            if sw > 0:
                self.main_splitter.setSizes([w, max(280, sw - w)])

        def _on_sidebar_finished():
            if self.sidebar_collapsed:
                self.sidebarWidget.setMinimumWidth(rail)
                self.sidebarWidget.setMaximumWidth(rail)
            else:
                self.sidebarWidget.setMinimumWidth(120)
                self.sidebarWidget.setMaximumWidth(800)
            self._sidebar_anim = None
            self._apply_responsive_layout()

        self._sidebar_anim.valueChanged.connect(_on_sidebar_width)
        self._sidebar_anim.finished.connect(_on_sidebar_finished)
        self._sidebar_anim.start()

    def _toggle_topbar(self):
        self._topbar_collapsed = not getattr(self, "_topbar_collapsed", False)
        self._apply_topbar_collapse()

    def _apply_topbar_collapse(self):
        """Hide everything in the toolbar except its collapse toggle so the
        page gets the maximum vertical space, then restore it on re-expand."""
        collapsed = getattr(self, "_topbar_collapsed", False)
        if hasattr(self, "btn_toggle_topbar"):
            self.btn_toggle_topbar.setText("▴" if collapsed else "▾")
        if not hasattr(self, "topbar_layout"):
            return
        for index in range(self.topbar_layout.count()):
            item = self.topbar_layout.itemAt(index)
            widget = item.widget() if item else None
            if widget is not None and widget is not self.btn_toggle_topbar:
                widget.setVisible(not collapsed)
        self.topbar.setMaximumHeight(26 if collapsed else 16777215)
        self.topbar.setMinimumHeight(24 if collapsed else (40 if self.embedded else 44))

    def open_cuc_quan_ly_support_page(self):
        self.open_bundled_site("cucquanly")

    def open_bundled_site(self, key: str):
        """Open one of the six chained apps by stable key.

        Prefer the local bundled copy for offline apps, but use the deployed
        URL when a packaged build does not contain that app locally.
        """
        site = next((item for item in app_paths.bundled_sites(getattr(self, "app_dir", None)) if item["key"] == key), None)
        url = (site or {}).get("url") or (site or {}).get("remote")
        if not url:
            QMessageBox.warning(
                self,
                "Project Hub",
                "App '%s' not found locally or online.\n"
                "Place the app folder next to the exe or check its deployed URL." % key,
            )
            return
        self.url_bar.setText(url)
        browser = self.current_browser()
        if browser:
            browser.setUrl(QUrl(url))

    def open_project_hub(self):
        """Open the shared Project Hub landing page (fallback: the new-tab hub)."""
        url = app_paths.project_hub_url(getattr(self, "app_dir", None))
        if url:
            self.url_bar.setText(url)
            browser = self.current_browser()
            if browser:
                browser.setUrl(QUrl(url))
            return
        if self.current_browser():
            self.current_browser().page().setHtml(self.get_new_tab_html(), QUrl("about:newtab"))

    def navigate(self):
        raw = (self.url_bar.text() or "").strip()
        if not raw:
            return
        if raw.lower() in ("newtab", "about:newtab"):
            if self.current_browser():
                self.current_browser().page().setHtml(self.get_new_tab_html(), QUrl("about:newtab"))
            return
        if raw.lower() in ("about:hub", "hub", "about:chain", "chain"):
            self.open_project_hub()
            return
        low = raw.strip().lower()
        if low in ("about:cuc-quan-ly", "cuc-quan-ly", "cql", "cu:", "cu", "cuc", "quanly", "quan-ly"):
            self.open_bundled_site("cucquanly")
            return
        if low in ("about:linklumina", "linklumina", "lum:", "lumina"):
            self.open_bundled_site("linklumina")
            return
        if low in ("about:mas", "mas", "mahoraga", "mahoraga-adapt-system", "adapt-system"):
            self.open_bundled_site("mas")
            return
        if low in ("about:leaderboard", "about:world-leaderboard", "leaderboard", "world-leaderboard", "worldleaderboard"):
            self.open_bundled_site("worldleaderboard")
            return
        if low in ("about:bimat", "bimat", "personalfrequency", "personal-frequency"):
            self.open_bundled_site("bimat")
            return
        if low in ("about:boitoan", "boitoan", "boi-toan", "fortune"):
            self.open_bundled_site("boitoan")
            return
        engine = self.search_engine.currentText()
        url = raw
        if not (raw.startswith("http://") or raw.startswith("https://") or raw.startswith("file://")):
            if "." not in raw or " " in raw:
                url = self._engine_search_url(engine, raw)
            else:
                url = QUrl.fromUserInput(raw).toString()
        if self.current_browser():
            self.current_browser().setUrl(QUrl(url))
            self._maybe_import_from_url(url, show_feedback=True)

    def _check_bootstrap_import_payload(self):
        browser = self.current_browser()
        if not browser:
            return
        url = browser.url().toString()
        if not url:
            pending = browser.property("pending_url")
            if pending:
                url = pending.toString()
        self._maybe_import_from_url(url, show_feedback=False)

    def _maybe_import_from_url(self, value: str, show_feedback: bool = False):
        text = (value or "").strip()
        if not text or "importBatchData=" not in text:
            return False
        try:
            parsed = urlparse(text)
            params = parse_qs(parsed.query or "")
            encoded = (params.get("importBatchData") or [""])[0]
            if not encoded:
                return False
            batch = extension_bridge.import_from_encoded_query(self.base_dir, encoded)
        except Exception as exc:
            if show_feedback:
                QMessageBox.warning(self, "Extension import", f"Could not decode importBatchData.\n{exc}")
            return False
        if show_feedback:
            QMessageBox.information(
                self,
                "Extension import",
                f"Received {batch.get('tab_count', 0)} tabs from {batch.get('source_label', 'extension')}.",
            )
        return True

    def _format_extension_batch_label(self, batch):
        source = batch.get("source_browser") or "extension"
        label = batch.get("source_label") or f"Window {batch.get('window_id', '?')}"
        count = int(batch.get("tab_count") or len(batch.get("tabs") or []))
        imported = "Imported" if batch.get("imported_at") else "Stored"
        return f"[{source}] {label} | {count} tab | {imported}"

    def _refresh_extension_import_list(self, widget):
        widget.clear()
        for batch in extension_bridge.load_batches(self.base_dir):
            item = QListWidgetItem(self._format_extension_batch_label(batch))
            item.setData(Qt.UserRole, batch)
            widget.addItem(item)

    def _import_extension_batch_into_tabs(self, batch):
        tabs = batch.get("tabs") or []
        if not tabs:
            QMessageBox.information(self, "Extension import", "This batch has no tabs.")
            return 0
        imported = 0
        active_index = next((idx for idx, tab in enumerate(tabs) if tab.get("active")), 0)
        for idx, tab in enumerate(tabs):
            url = tab.get("url") or ""
            if not url:
                continue
            self.tab_manager.add_tab(
                QUrl(url),
                tab.get("title") or "Imported tab",
                is_active=(idx == active_index and imported == 0),
                session_data={
                    "url": url,
                    "title": tab.get("title") or url,
                    "pinned": bool(tab.get("pinned")),
                    "active": idx == active_index,
                    "workspace_id": self.current_workspace_id,
                },
            )
            imported += 1
        if imported:
            extension_bridge.mark_batch_imported(self.base_dir, batch.get("id", ""))
            self._apply_workspace_filter()
        return imported

    def _import_extension_batches_as_workspaces(self, batches):
        """Import a multi-screen extension export, one workspace per monitor.

        Screen 0 maps to Workspace 1, screen 1 to Workspace 2, and any further
        screens get a new workspace named after the batch label. Returns the
        total number of tabs imported.
        """
        ordered = sorted(
            batches,
            key=lambda b: (
                int(b.get("screen_index", -1)) if isinstance(b.get("screen_index"), int) else -1,
                b.get("window_id") or "",
            ),
        )
        # Fall back to import order for payloads without screen_index (old
        # single-window JSON or hand-written batches) so behavior is stable.
        if ordered and all(b.get("screen_index", -1) < 0 for b in ordered):
            ordered = list(batches)

        workspaces = workspace_manager.get_workspaces_list(self.base_dir)
        ws_ids = [w.get("id") for w in workspaces if isinstance(w, dict) and w.get("id")]
        used_ws = set()
        total = 0

        for idx, batch in enumerate(ordered):
            tabs = batch.get("tabs") or []
            if not tabs:
                continue
            if idx < len(ws_ids):
                ws_id = ws_ids[idx]
            else:
                label = (batch.get("source_label") or f"Window {batch.get('window_id', idx)}").strip()
                ws_id = workspace_manager.add_workspace(self.base_dir, label)
            used_ws.add(ws_id)
            active_index = next((i for i, tab in enumerate(tabs) if tab.get("active")), 0)
            imported = 0
            for tab_idx, tab in enumerate(tabs):
                url = tab.get("url") or ""
                if not url:
                    continue
                self.tab_manager.add_tab(
                    QUrl(url),
                    tab.get("title") or "Imported tab",
                    is_active=False,
                    session_data={
                        "url": url,
                        "title": tab.get("title") or url,
                        "pinned": bool(tab.get("pinned")),
                        "active": tab_idx == active_index,
                        "workspace_id": ws_id,
                    },
                )
                imported += 1
            if imported:
                extension_bridge.mark_batch_imported(self.base_dir, batch.get("id", ""))
            total += imported

        if used_ws:
            self._refresh_workspace_combo()
            self._apply_workspace_filter()
        return total

    def show_extension_import_center(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Extension Import Center")
        dialog.resize(820, 620)
        dialog.setStyleSheet(self._dialog_stylesheet())
        layout = QVBoxLayout(dialog)

        help_label = QLabel(
            "Paste a JSON payload from a Chrome/Opera GX extension (or open a .json/.zip export), "
            "then import all tabs into the current workspace — or use Import All as Workspaces "
            "to split a multi-screen export back into one Mei workspace per monitor."
        )
        help_label.setWordWrap(True)
        layout.addWidget(help_label)

        batch_list = QListWidget()
        layout.addWidget(batch_list, 1)

        payload_box = QTextEdit()
        payload_box.setPlaceholderText(
            '{\n'
            '  "batch_id": "chrome_123",\n'
            '  "window_id": 123,\n'
            '  "source_browser": "chrome",\n'
            '  "source_label": "Work Window",\n'
            '  "tabs": [{"url": "https://example.com", "title": "Example", "active": true}]\n'
            '}'
        )
        payload_box.setMaximumHeight(220)
        layout.addWidget(payload_box)

        button_row = QHBoxLayout()
        btn_refresh = QPushButton("Refresh")
        btn_import_file = QPushButton("Import File")
        btn_save_payload = QPushButton("Store Payload")
        btn_import_selected = QPushButton("Import Selected Batch")
        btn_import_all_ws = QPushButton("Import All as Workspaces")
        btn_close = QPushButton("Close")
        button_row.addWidget(btn_refresh)
        button_row.addWidget(btn_import_file)
        button_row.addWidget(btn_save_payload)
        button_row.addWidget(btn_import_selected)
        button_row.addWidget(btn_import_all_ws)
        button_row.addStretch(1)
        button_row.addWidget(btn_close)
        layout.addLayout(button_row)

        def refresh():
            self._refresh_extension_import_list(batch_list)

        def save_payload():
            text = payload_box.toPlainText().strip()
            if not text:
                QMessageBox.information(dialog, "Extension import", "Paste a JSON payload from the extension.")
                return
            try:
                batch = extension_bridge.import_from_json_text(self.base_dir, text)
            except Exception as exc:
                QMessageBox.warning(dialog, "Extension import", str(exc))
                return
            refresh()
            payload_box.clear()
            QMessageBox.information(
                dialog,
                "Extension import",
                f"Saved batch {batch.get('source_label', batch.get('id', ''))} with {batch.get('tab_count', 0)} tabs.",
            )

        def import_file():
            path, _ = QFileDialog.getOpenFileName(
                dialog,
                "Import extension payload",
                "",
                "JSON & ZIP (*.json *.zip);;JSON Files (*.json);;ZIP Archives (*.zip);;All Files (*.*)",
            )
            if not path:
                return
            try:
                batch = extension_bridge.import_from_file(self.base_dir, path)
            except Exception as exc:
                QMessageBox.warning(dialog, "Extension import", str(exc))
                return
            refresh()
            QMessageBox.information(
                dialog,
                "Extension import",
                f"Loaded file into batch {batch.get('source_label', batch.get('id', ''))} with {batch.get('tab_count', 0)} tabs.",
            )

        def import_selected():
            item = batch_list.currentItem()
            if not item:
                QMessageBox.information(dialog, "Extension import", "Please select a batch to import.")
                return
            batch = item.data(Qt.UserRole) or {}
            count = self._import_extension_batch_into_tabs(batch)
            refresh()
            if count:
                QMessageBox.information(dialog, "Extension import", f"Imported {count} tabs into the browser.")

        def import_all_as_workspaces():
            batches = extension_bridge.load_batches(self.base_dir)
            pending = [b for b in batches if not b.get("imported_at")]
            if not pending:
                QMessageBox.information(dialog, "Extension import", "No un-imported batches. Use Import Selected Batch to re-import one.")
                return
            count = self._import_extension_batches_as_workspaces(pending)
            refresh()
            if count:
                QMessageBox.information(
                    dialog,
                    "Extension import",
                    f"Imported {count} tabs across {len(pending)} window(s), one Mei workspace per screen.",
                )

        btn_refresh.clicked.connect(refresh)
        btn_import_file.clicked.connect(import_file)
        btn_save_payload.clicked.connect(save_payload)
        btn_import_selected.clicked.connect(import_selected)
        btn_import_all_ws.clicked.connect(import_all_as_workspaces)
        batch_list.itemDoubleClicked.connect(lambda _item: import_selected())
        btn_close.clicked.connect(dialog.accept)

        refresh()
        dialog.exec_()
        self._user_extension_scripts_cache = None

    def _engine_home_url(self, engine_name: str) -> str:
        return prefs.search_engine_home_url(engine_name)

    def _engine_search_url(self, engine_name: str, query: str) -> str:
        return prefs.search_engine_query_url(engine_name, query)

    def _looks_like_search_query(self, text: str) -> bool:
        value = (text or "").strip()
        if not value:
            return False
        lowered = value.lower()
        if lowered.startswith(("http://", "https://", "file://", "about:")):
            return False
        return "." not in value or " " in value

    def _extract_search_query(self, value: str) -> str:
        text = (value or "").strip()
        if not text:
            return ""
        if self._looks_like_search_query(text):
            return text
        try:
            parsed = urlparse(text)
        except Exception:
            return ""
        host = (parsed.netloc or "").lower()
        params = parse_qs(parsed.query or "")
        if "google." in host:
            return unquote_plus((params.get("q") or [""])[0])
        if "startpage.com" in host:
            return unquote_plus((params.get("q") or [""])[0])
        if "duckduckgo.com" in host:
            return unquote_plus((params.get("q") or [""])[0])
        if "bing.com" in host:
            return unquote_plus((params.get("q") or [""])[0])
        if "search.brave.com" in host:
            return unquote_plus((params.get("q") or [""])[0])
        if "ecosia.org" in host:
            return unquote_plus((params.get("q") or [""])[0])
        return ""

    def _on_search_engine_changed(self, index):
        if index < 0:
            return
        # Persist the user's choice so every window and future session uses it.
        try:
            prefs.set_search_engine(self.base_dir, self.search_engine.currentText())
        except Exception:
            pass
        # v6.5 UX: merely switching engines must not navigate the tab the user
        # is reading (v6.4 re-ran the last query and could yank them away).
        # The next new tab / search picks the new engine automatically.
        browser = self.current_browser()
        if browser is not None:
            current_url = browser.url().toString()
            if current_url in ("", "about:blank"):
                browser.setUrl(QUrl(self._engine_home_url(self.search_engine.currentText())))

    def save_bookmark(self, folder_id=None):
        browser = self.current_browser()
        if not browser:
            return
        url = browser.url().toString()
        title = browser.title()
        bookmarks = prefs.load_bookmarks(self.base_dir)
        # Guard against malformed entries (v6.4 raised KeyError on one).
        if any((b or {}).get("url") == url for b in bookmarks):
            self._flash_status("This page is already in your Bookmarks")
            return
        if folder_id is None:
            current_item = self.bookmarks_tree.currentItem()
            if current_item:
                data = current_item.data(0, Qt.UserRole)
                kind, data = data if isinstance(data, tuple) and len(data) == 2 else ("", data)
                if kind == "folder":
                    folder_id = data
        bookmarks.append({"title": title, "url": url, "folder_id": folder_id or ""})
        prefs.save_bookmarks(self.base_dir, bookmarks)
        history_service.log_event(self.base_dir, "bookmark", title or url, url, {"url": url})
        self._load_bookmarks_panel()
        self._flash_status("Page saved to Bookmarks")

    def open_current_in_external_browser(self):
        browser = self.current_browser()
        if not browser:
            return
        url = browser.url().toString()
        self.open_url_in_external_browser(url)

    def open_url_in_external_browser(self, url):
        if not url.startswith("http"):
            return
        browser_candidates = [
            os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"),
            os.path.expandvars(r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"),
            os.path.expandvars(r"%LocalAppData%\Microsoft\Edge\Application\msedge.exe"),
        ]
        for browser_path in browser_candidates:
            if os.path.exists(browser_path):
                try:
                    subprocess.Popen([browser_path, url])
                    return
                except Exception:
                    pass
        try:
            os.startfile(url)
        except Exception:
            QMessageBox.warning(self, "Open externally", "Could not launch Chrome, Edge, or the default browser.")

    def _apply_saved_proxy(self):
        path = prefs.proxy_config_path(self.base_dir)
        if not os.path.exists(path):
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            if cfg.get("enabled", False):
                self._set_proxy_from_config(cfg, prompt_restart=False)
        except Exception:
            pass

    def _set_proxy_from_config(self, cfg, prompt_restart: bool = True):
        """Apply a proxy to BOTH Qt's QNetworkAccessManager and (via env var) the
        next QtWebEngine launch. WebEngine reads --proxy-server only at startup,
        so live page loads keep the previous proxy until the user restarts."""
        host = (cfg.get("host") or "").strip()
        port = int(cfg.get("port") or 0)
        valid = bool(host) and 0 < port < 65536
        proxy_type = QNetworkProxy.HttpProxy if cfg.get("type", "http").lower() == "http" else QNetworkProxy.Socks5Proxy
        if valid:
            proxy = QNetworkProxy(proxy_type, host, port)
            if cfg.get("user"):
                proxy.setUser(cfg["user"])
            if cfg.get("password"):
                proxy.setPassword(cfg["password"])
            QNetworkProxy.setApplicationProxy(proxy)
        else:
            # Never install a half-configured proxy (empty host/port) — that
            # would silently break every QNetworkAccessManager request.
            QNetworkProxy.setApplicationProxy(QNetworkProxy(QNetworkProxy.NoProxy))

        scheme = "socks5" if (cfg.get("type") or "http").lower().startswith("socks") else "http"
        if valid:
            from urllib.parse import quote
            user = (cfg.get("user") or "").strip()
            password = (cfg.get("password") or "").strip()
            auth = ""
            if user:
                auth = quote(user, safe="") + (":" + quote(password, safe="") if password else "") + "@"
            flag = "--proxy-server=%s://%s%s:%d" % (scheme, auth, host, port)
            existing = os.environ.get("QTWEBENGINE_CHROMIUM_FLAGS", "").strip()
            existing = " ".join(tok for tok in existing.split() if not tok.startswith("--proxy-server="))
            os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = (existing + " " + flag).strip()
            if prompt_restart:
                QMessageBox.information(
                    self,
                    "VPN / Proxy",
                    "Proxy saved for Mei.\n\n"
                    "Important: QtWebEngine only reads proxy settings at startup.\n"
                    "Close and reopen Mei for all web tabs to go through the proxy.",
                )

    def _load_block_third_party_cookies_pref(self):
        self.act_block_3p_cookies.setChecked(prefs.get_block_third_party_cookies(self.base_dir))
        self._apply_cookie_policy(show_message=False)

    def _load_dark_web_pref(self):
        self.act_dark_mode.setChecked(prefs.get_force_dark_web(self.base_dir))

    def _apply_cookie_policy(self, show_message=True):
        checked = self.act_block_3p_cookies.isChecked()
        store = self.profile.cookieStore()
        if checked:
            def cookie_filter(req):
                first_party_url = ""
                try:
                    first_party = req.firstPartyUrl()
                    if first_party:
                        first_party_url = first_party.toString().lower()
                except Exception:
                    first_party_url = ""
                if self.is_compatibility_host(first_party_url):
                    return True
                third_party = getattr(req, "thirdParty", False)
                if callable(third_party):
                    try:
                        third_party = third_party()
                    except Exception:
                        third_party = False
                return not bool(third_party)

            self._cookie_filter = cookie_filter
            if hasattr(store, "setCookieFilter"):
                store.setCookieFilter(self._cookie_filter)
                if show_message:
                    self._flash_status("Third-party cookies blocked for this profile")
            elif show_message:
                self._flash_status("Preference saved — this Qt build cannot filter cookies")
        else:
            # Qt has no unsetCookieFilter: install a pass-through instead
            # (v6.4 approach, kept).
            if hasattr(store, "setCookieFilter"):
                self._cookie_filter = lambda _req: True
                store.setCookieFilter(self._cookie_filter)
            else:
                self._cookie_filter = None
            if show_message:
                self._flash_status("Third-party cookie blocking turned off")

    def toggle_block_third_party_cookies(self):
        checked = self.act_block_3p_cookies.isChecked()
        prefs.set_block_third_party_cookies(self.base_dir, checked)
        self._apply_cookie_policy(show_message=True)

    def update_zoom_label(self):
        browser = self.current_browser()
        if browser:
            pct = round(browser.zoomFactor() * 100)
            self.lbl_zoom.setText(f"{pct}%")

    def zoom_in(self):
        browser = self.current_browser()
        if browser:
            factor = round(min(browser.zoomFactor() + 0.1, 3.0), 2)
            browser.setZoomFactor(factor)
            self._remember_current_zoom(factor)
            self.update_zoom_label()

    def zoom_out(self):
        browser = self.current_browser()
        if browser:
            factor = round(max(browser.zoomFactor() - 0.1, 0.3), 2)
            browser.setZoomFactor(factor)
            self._remember_current_zoom(factor)
            self.update_zoom_label()

    def zoom_reset(self):
        browser = self.current_browser()
        if browser:
            host = (browser.url().host() or "").lower()
            browser.setZoomFactor(1.0)
            prefs.set_site_zoom(self.base_dir, host, None)
            self.update_zoom_label()

    def _remember_current_zoom(self, factor):
        browser = self.current_browser()
        if browser:
            host = (browser.url().host() or "").lower()
            if host:
                prefs.set_site_zoom(self.base_dir, host, factor)

    def find_text(self):
        if not self.current_browser():
            return
        bar = self._ensure_find_bar()
        bar.show()
        bar.raise_()
        bar.ed_query.setFocus()
        bar.ed_query.selectAll()
        self._find_browser = self.current_browser()

    def _ensure_find_bar(self):
        if getattr(self, "_find_bar", None) is None:
            self._find_bar = _FindBar(self)
            lay = self.central_widget.layout()
            lay.addWidget(self._find_bar)
            # Hidden until first use; sits above the web area like Chrome.
            self._find_bar.hide()
            self._find_bar.ed_query.textChanged.connect(self._on_find_text_changed)
            self._find_bar.ed_query.returnPressed.connect(self._find_next)
            self._find_bar.btn_next.clicked.connect(self._find_next)
            self._find_bar.btn_prev.clicked.connect(self._find_prev)
            self._find_bar.btn_close.clicked.connect(self._close_find_bar)
            QShortcut(QKeySequence(Qt.Key_Escape), self._find_bar).activated.connect(self._close_find_bar)
            QShortcut(QKeySequence("F3"), self._find_bar).activated.connect(self._find_next)
            QShortcut(QKeySequence("Shift+F3"), self._find_bar).activated.connect(self._find_prev)
        return self._find_bar

    def _find_next(self):
        bar = getattr(self, "_find_bar", None)
        if bar and bar.isVisible() and self.current_browser():
            self.current_browser().findText(bar.ed_query.text(), self._find_flags_forward())

    def _find_prev(self):
        bar = getattr(self, "_find_bar", None)
        if bar and bar.isVisible() and self.current_browser():
            self.current_browser().findText(bar.ed_query.text(), self._find_flags_backward())

    def _find_flags_forward(self):
        from PyQt5.QtWebEngineWidgets import QWebEnginePage
        return QWebEnginePage.FindFlags() if hasattr(QWebEnginePage, "FindFlags") else 0

    def _find_flags_backward(self):
        from PyQt5.QtWebEngineWidgets import QWebEnginePage
        try:
            return QWebEnginePage.FindFlag.FindBackward
        except AttributeError:
            return QWebEnginePage.FindBackward

    def _find_flags_count(self):
        from PyQt5.QtWebEngineWidgets import QWebEnginePage
        try:
            return QWebEnginePage.FindFlag.FindCaseSensitively
        except AttributeError:
            return 0

    def _on_find_text_changed(self, text):
        browser = self.current_browser()
        if not browser:
            return
        if not text:
            browser.findText("")
            bar = self._find_bar
            if bar:
                bar.lbl_count.setText("")
            return
        browser.findText(text, self._find_flags_forward(), self._on_find_result)

    def _on_find_result(self, result):
        bar = getattr(self, "_find_bar", None)
        if bar is None:
            return
        count, index = result.numberOfMatches(), result.activeMatch()
        bar.lbl_count.setText(f"{index}/{count}" if count else "0/0")

    def _close_find_bar(self):
        bar = getattr(self, "_find_bar", None)
        if bar is not None:
            bar.hide()
            browser = self.current_browser()
            if browser:
                browser.findText("")

    def _translate_page(self, service="google"):
        browser = self.current_browser()
        if not browser:
            return
        url = browser.url().toString()
        if not url or not url.startswith("http"):
            QMessageBox.information(self, "Translate", "Could not translate this page.")
            return
        if service == "google":
            self.tab_manager.add_tab(QUrl(f"https://translate.google.com/translate?sl=auto&tl=vi&u={quote_plus(url)}"), "Google Translate", is_active=True)
        elif service == "bing":
            self.tab_manager.add_tab(QUrl(f"https://www.bing.com/translator?ref=This&text=&from=auto&to=vi&url={quote_plus(url)}"), "Bing Translate", is_active=True)

    def toggle_reader_mode(self):
        browser = self.current_browser()
        if not browser:
            return
        # Reader palette follows the shell theme (v6.4 forced a dark scheme
        # even in light themes, then dark-forced sites double-inverted).
        p = theme.palette()
        bg, fg, muted = p["MAIN_BG"], p["TEXT"], p["TEXT_MUTED"]
        js = """
        var elements = document.querySelectorAll('header, footer, nav, aside, .sidebar, .ads, script, style, iframe');
        for (var i=0; i<elements.length; i++) elements[i].style.display = 'none';
        document.body.style.maxWidth = '800px';
        document.body.style.margin = '0 auto';
        document.body.style.padding = '20px';
        document.body.style.backgroundColor = '%s';
        document.body.style.color = '%s';
        document.body.style.fontSize = '18px';
        document.body.style.lineHeight = '1.6';
        """ % (bg, fg)
        browser.page().runJavaScript(js)
        self._flash_status("Reader mode — colors follow your theme")

    def toggle_text_highlight(self, checked=None):
        """Enable/disable the highlight-text-to-copy helper on every open page.

        The profile-level script covers all future loads (tabs + embedded
        previews); the per-page JS pass updates pages that are already open.
        """
        if checked is None:
            checked = bool(self.act_text_highlight.isChecked())
        checked = bool(checked)
        prefs.set_text_highlight_enabled(self.base_dir, checked)
        try:
            ensure_text_highlight_script(self.profile, checked, self.base_dir)
        except Exception:
            pass
        js = build_text_highlight_js(checked)
        for browser in self.browsers:
            if browser is not None and browser.page():
                try:
                    browser.page().runJavaScript(js)
                except Exception:
                    pass

    def show_dev_tools(self):
        if not self.current_browser():
            return
        # Reuse the existing devtools window: v6.4 stacked a fresh orphan
        # window (holding a whole renderer view) on every F12 press.
        existing = getattr(self, "_dev_windows", None)
        if existing:
            dev_window = existing[-1]
            if dev_window.isVisible():
                dev_window.raise_()
                dev_window.activateWindow()
                return
            dev_window.close()
            self._dev_windows.remove(dev_window)
        dev_view = QWebEngineView()
        self.current_browser().page().setDevToolsPage(dev_view.page())
        dev_window = QMainWindow(self)
        dev_window.setWindowTitle("Developer Tools - F12")
        dev_window.resize(800, 600)
        dev_window.setCentralWidget(dev_view)
        if not hasattr(self, "_dev_windows"):
            self._dev_windows = []
        self._dev_windows.append(dev_window)
        dev_window.destroyed.connect(lambda *_: self._dev_windows.remove(dev_window) if dev_window in self._dev_windows else None)
        dev_window.show()

    def toggle_dark_web(self):
        is_dark = self.act_dark_mode.isChecked()
        prefs.set_force_dark_web(self.base_dir, is_dark)
        try:
            from litebrowser.browser.browser_page import ensure_forced_dark_script
            ensure_forced_dark_script(self.profile, is_dark, self.base_dir)
        except Exception:
            pass
        js = self._dark_mode_js(is_dark)
        for browser in self.browsers:
            if browser is not None and browser.page():
                browser.page().runJavaScript(js)

    def show_history_dialog(self):
        dialogs.show_history_dialog(self)

    def remember_closed_tab(self, metadata):
        state = prefs.session_state_load(self.base_dir)
        recently_closed = state.get("recently_closed", [])
        entry = {
            "kind": metadata.get("kind", "tab"),
            "url": metadata.get("url", ""),
            "title": metadata.get("title", ""),
            "icon": metadata.get("icon", ""),
            "hibernated": bool(metadata.get("hibernated", True)),
            "pinned": bool(metadata.get("pinned")),
            "workspace_id": metadata.get("workspace_id") or metadata.get("workspace") or self.current_workspace_id,
        }
        if entry["url"]:
            recently_closed = [item for item in recently_closed if item.get("url") != entry["url"]]
            recently_closed.insert(0, entry)
            state["recently_closed"] = recently_closed[:50]
            prefs.session_state_save(self.base_dir, state)

    def reopen_closed_tab(self):
        """Reopen the most recently closed tab (or window) via Ctrl+Shift+T.

        Consumes the last ``kind == "tab"`` entry in the session's recently-closed
        list so an empty history produces a clear message instead of silently doing
        nothing. Windows (multi-tab) are surfaced through the History panel.
        """
        state = prefs.session_state_load(self.base_dir)
        recently_closed = state.get("recently_closed", [])
        tab_index = next((i for i, e in enumerate(recently_closed) if e.get("kind") == "tab" and e.get("url")), None)
        if tab_index is None:
            QMessageBox.information(self, "Reopen Closed Tab", "No recently closed tab to reopen.")
            return
        entry = recently_closed.pop(tab_index)
        state["recently_closed"] = recently_closed
        prefs.session_state_save(self.base_dir, state)
        url = entry.get("url", "")
        if not url:
            return
        self.tab_manager.add_tab(
            QUrl(url),
            entry.get("title") or "Reopened",
            is_active=True,
            session_data=entry,
        )
        # add_tab already inserts + selects the row; the panel switch re-applies
        # the workspace filter so the restored tab is visible. (There is no
        # ``SearchWindow.refresh`` — the old call here raised AttributeError.)
        self.switch_to_browser_panel()

    def switch_to_browser_panel(self):
        try:
            self._switch_sidebar_panel(0)
            self._apply_workspace_filter()
        except Exception:
            pass

    def reopen_closed_window(self):
        """Reopen the most recently closed multi-tab window (from session state)."""
        state = prefs.session_state_load(self.base_dir)
        recently_closed = state.get("recently_closed", [])
        window_index = next(
            (i for i, entry in enumerate(recently_closed) if entry.get("kind") == "window" and entry.get("tabs")),
            None,
        )
        if window_index is None:
            QMessageBox.information(self, "Reopen Closed Window", "No recently closed window to reopen.")
            return
        entry = recently_closed.pop(window_index)
        state["recently_closed"] = recently_closed
        prefs.session_state_save(self.base_dir, state)
        tabs = [tab for tab in entry.get("tabs", []) if tab.get("url")]
        if not tabs:
            return
        self.tab_manager.begin_batch()
        try:
            for tab in tabs:
                self.tab_manager.add_tab(
                    QUrl(tab.get("url")),
                    tab.get("title") or "Reopened",
                    is_active=bool(tab.get("active")),
                    session_data=tab,
                )
        finally:
            self.tab_manager.end_batch()
        self.switch_to_browser_panel()

    def _cycle_tab_next(self):
        self._cycle_tab(1)

    def _cycle_tab_prev(self):
        self._cycle_tab(-1)

    def _cycle_tab(self, direction):
        """Move keyboard focus to the next/previous visible tab in this workspace."""
        count = self.tab_list.count()
        if count == 0:
            return
        rows = [i for i in range(count) if not self.tab_list.item(i).isHidden()]
        if not rows:
            return
        current = self.tab_list.currentRow()
        try:
            position = rows.index(current)
        except ValueError:
            position = -1 if direction > 0 else 0
        target = rows[(position + direction) % len(rows)]
        self.tab_list.setCurrentRow(target)

    def remember_closed_window(self, tabs):
        tabs = [dict(tab) for tab in (tabs or []) if tab.get("url")]
        if len(tabs) < 2:
            return
        state = prefs.session_state_load(self.base_dir)
        recently_closed = state.get("recently_closed", [])
        entry = {
            "kind": "window",
            "title": f"Window with {len(tabs)} tabs",
            "tabs": tabs,
        }
        recently_closed.insert(0, entry)
        state["recently_closed"] = recently_closed[:30]
        prefs.session_state_save(self.base_dir, state)

    def refresh_insight_summary(self):
        host = self._host_shell()
        if host is None or not hasattr(host, "set_sleeping_tabs"):
            return
        sleeping = []
        for i, browser in enumerate(self.browsers):
            item = self.tab_list.item(i)
            meta = dict(item.data(TAB_META_ROLE) or {}) if item else {}
            hibernated = bool(meta.get("hibernated"))
            if browser is not None:
                try:
                    hibernated = bool(browser.property("hibernated"))
                except Exception:
                    pass
            if hibernated:
                sleeping.append(meta.get("title") or meta.get("url") or f"Tab {i+1}")
        host.set_sleeping_tabs(sleeping)

    def show_bookmarks_dialog(self):
        dialogs.show_bookmarks_dialog(self)

    def show_extensions_dialog(self):
        dialogs.show_extensions_dialog(self)

    def show_vault(self):
        vault_ui.show_vault_dialog(self, prefs.vault_path(self.base_dir), self._dialog_stylesheet)

    def show_downloads_dialog(self):
        dialogs.show_downloads_dialog(self)

    def handle_download_request(self, download):
        suggested = (download.suggestedFileName() or "").strip()
        suggested_lower = suggested.lower()
        dangerous = (".exe", ".bat", ".cmd", ".scr", ".msi", ".vbs", ".js", ".jar", ".pif", ".com")
        is_risky = suggested_lower.endswith(dangerous)
        msg = QMessageBox(self)
        msg.setWindowTitle("Download request")
        if is_risky:
            msg.setIcon(QMessageBox.Warning)
            msg.setText(f"This page is trying to download a file that can execute:\n{suggested or '(unnamed)'}\n\nOnly accept if you trust the source. Allow download?")
        else:
            msg.setText(f"This page is trying to download a file:\n{suggested or '(unnamed)'}\n\nAllow download?")
        msg.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        msg.setDefaultButton(QMessageBox.No)
        if msg.exec_() == QMessageBox.Yes:
            path, _ = QFileDialog.getSaveFileName(self, "Save file", suggested or "download")
            if path:
                download.setPath(path)
                download.accept()
                try:
                    from litebrowser.services import download_mgr
                    download_id = download_mgr.add_download(self.base_dir, download.url().toString(), path, download.suggestedFileName(), "downloading")
                    # Qt6 and Qt5 both expose stateChanged; use it as the primary signal so
                    # status always lands even when .finished / .isFinishedChanged are absent.
                    if hasattr(download, "stateChanged"):
                        download.stateChanged.connect(
                            lambda _state=None, did=download_id, item=download: self._finalize_download(did, item)
                        )
                    if hasattr(download, "finished"):
                        download.finished.connect(lambda did=download_id, item=download: self._finalize_download(did, item))
                    elif hasattr(download, "isFinishedChanged"):
                        download.isFinishedChanged.connect(
                            lambda done, did=download_id, item=download: self._finalize_download(did, item) if done else None
                        )
                except Exception:
                    pass
            else:
                download.cancel()
        else:
            download.cancel()

    def _finalize_download(self, download_id, download):
        # stateChanged and finished both fire per download; only the first
        # terminal event may be recorded or statuses get overwritten.
        if not hasattr(self, "_finalized_downloads"):
            self._finalized_downloads = set()
        if download_id in self._finalized_downloads:
            return
        try:
            from litebrowser.services import download_mgr
            state = download.state() if hasattr(download, "state") else None
            completed = getattr(download, "DownloadCompleted", None)
            cancelled = getattr(download, "DownloadCancelled", None)
            interrupted = getattr(download, "DownloadInterrupted", None)
            in_progress = getattr(download, "DownloadInProgress", None)
            requested = getattr(download, "DownloadRequested", None)
            terminal_states = [s for s in (completed, cancelled, interrupted) if s is not None]
            if state is None:
                return  # unknown state — do not mark anything yet
            if terminal_states and state not in terminal_states:
                return  # still requested/in-progress; keep "downloading" status
            status = "completed"
            if cancelled is not None and state == cancelled:
                status = "cancelled"
            elif interrupted is not None and state == interrupted:
                status = "interrupted"
            download_mgr.update_status(self.base_dir, download_id, status)
            self._finalized_downloads.add(download_id)
            self._load_downloads_panel()
        except Exception:
            pass

    def print_page(self):
        browser = self.current_browser()
        if not browser:
            return
        printer = QPrinter(QPrinter.HighResolution)
        dlg = QPrintDialog(printer, self)
        if dlg.exec_() == QDialog.Accepted:
            def on_print_finished(ok):
                # Qt5's QWebEnginePage.printFinished(bool) — the old handler
                # declared (path, ok) and would TypeError if it ever fired.
                self._flash_status("Sent to the printer" if ok else "Print failed")

            page = browser.page()
            if hasattr(page, "print"):
                try:
                    page.print(printer, on_print_finished)
                    return
                except TypeError:
                    pass
            # Qt 6.8+ removed QWebEnginePage.print(): fall back to PDF-then-print
            # so the feature never breaks under the PyQt6 shim.
            if hasattr(page, "printToPdf"):
                tmp_path = os.path.join(prefs.favicon_cache_dir(self.base_dir), "_print_preview.pdf")
                page.pdfPrintingFinished.connect(lambda _path, ok: self._flash_status("PDF saved — open it to print") if ok else None)
                page.printToPdf(tmp_path)
                self._flash_status("Printing to PDF fallback...")
                return
            self._flash_status("Printing is not available for this page")

    def save_page_pdf(self):
        browser = self.current_browser()
        if not browser:
            return
        file_path, _ = QFileDialog.getSaveFileName(self, "Save PDF", "", "PDF Files (*.pdf)")
        if not file_path:
            return
        if not file_path.endswith(".pdf"):
            file_path += ".pdf"
        page = browser.page()
        page.pdfPrintingFinished.connect(
            lambda path, ok: self._flash_status("PDF saved: " + os.path.basename(path or file_path)) if ok else self._flash_status("PDF export failed")
        )
        page.printToPdf(file_path)
        self._flash_status("Generating PDF...")

    def save_current_page_to_library(self):
        browser = self.current_browser()
        if not browser:
            return
        url = browser.url().toString()
        if not url or url in ("about:blank", "about:newtab"):
            return
        title = browser.title() or url
        life_service.add_saved_page(self.base_dir, title, url)
        shell = self._host_shell()
        if shell and hasattr(shell, "refresh_shell"):
            shell.refresh_shell()
        QMessageBox.information(self, "Library", "Current page saved to Library.")

    def ask_ai_about_current_page(self):
        browser = self.current_browser()
        if not browser:
            return
        self.inline_ai_panel.show()
        if not self.inline_ai_input.text().strip():
            self.inline_ai_input.setText("What can you see on this page?")
        self._run_inline_ai()

    def _run_inline_ai(self):
        browser = self.current_browser()
        if not browser:
            return
        shell = self._host_shell()
        if not shell or not hasattr(shell, "ask_ai_from_shell"):
            return
        question = (self.inline_ai_input.text() or "").strip() or "What can you see on this page?"
        self.inline_ai_answer.setPlainText("Reading the visible page and asking AI...")
        # Wire the answer back through the AIWorkspace signal so the inline panel
        # does not depend on a stale, synchronously-read ``_last_answer``.
        # Connect at most once: PyQt adds a new connection on every connect(),
        # so repeated asks would let an older answer overwrite the newest one.
        if not getattr(self, "_inline_ai_wired", False):
            shell.ai_page.query_finished.connect(self._on_inline_ai_answer)
            self._inline_ai_wired = True
        browser.page().runJavaScript(
            "(function(){var text=(document.body && document.body.innerText)||''; return text.slice(0,5000);})();",
            lambda text: self._handle_inline_ai_context(shell, browser, question, text or ""),
        )

    def _on_inline_ai_answer(self, future, _context_label, _provider_label=""):
        if self._closing:
            return
        try:
            result = future.result()
        except Exception as exc:
            self.inline_ai_answer.setPlainText("AI request failed: %s" % (exc,))
            return
        answer = (result or {}).get("answer") or "No answer returned."
        self.inline_ai_answer.setPlainText(answer)

    def _handle_inline_ai_context(self, shell, browser, question: str, page_text: str):
        if self._closing:
            return
        title = browser.title() or browser.url().toString() or "Current page"
        url = browser.url().toString()
        context = f"Title: {title}\nURL: {url}\n\nVisible page text:\n{page_text[:5000]}"
        shell.ed_ai_quick.setText(question)
        shell.ai_page.ask_with_context(question, "Current browser page", context)

    def capture_page_as_note(self):
        browser = self.current_browser()
        if not browser:
            return
        url = browser.url().toString()
        title = browser.title() or url or "Web note"
        note = personal_service.create_note(self.base_dir, title[:60], "# " + title + "\n\nURL: " + url + "\n\n")
        QMessageBox.information(self, "Personal", "Created new note: " + note["title"])

    def capture_screenshot(self):
        browser = self.current_browser()
        if not browser:
            return
        file_path, _ = QFileDialog.getSaveFileName(self, "Save Web Image", "", "PNG Files (*.png);;JPEG Files (*.jpg)")
        if file_path:
            browser.grab().save(file_path)
            QMessageBox.information(self, "Screenshot", f"Web page screenshot saved to:\n{file_path}")

    def _host_shell(self):
        current = self.parent()
        while current is not None:
            if hasattr(current, "switch_workspace") and hasattr(current, "ai_page"):
                return current
            current = current.parent()
        win = self.window()
        if hasattr(win, "switch_workspace") and hasattr(win, "ai_page"):
            return win
        return None

    def extract_text(self):
        browser = self.current_browser()
        if not browser:
            return
        def process_text(text):
            dialog = QDialog(self)
            dialog.setWindowTitle("Extract Text")
            dialog.resize(720, 520)
            dialog.setStyleSheet(self._dialog_stylesheet())
            layout = QVBoxLayout(dialog)
            text_edit = QTextEdit()
            text_edit.setPlainText(text)
            layout.addWidget(text_edit)
            btn_copy = QPushButton("Copy All")
            btn_copy.clicked.connect(lambda: [QApplication.clipboard().setText(text_edit.toPlainText()), QMessageBox.information(dialog, "Copy", "Copied to clipboard.")])
            layout.addWidget(btn_copy)
            dialog.exec_()
        browser.page().toPlainText(process_text)

    def _tab_state_payload(self, index, browser, active_browser):
        item = self.tab_list.item(index)
        meta = dict(item.data(TAB_META_ROLE) or {}) if item else {}
        url = meta.get("url", "")
        if browser is not None:
            try:
                live_url = browser.url().toString()
                if live_url and live_url != "about:blank":
                    url = live_url
                elif not url:
                    pending = browser.property("pending_url")
                    if pending:
                        url = pending.toString()
            except Exception:
                pass
        if not url or url in ("about:blank", "about:newtab"):
            return None
        workspace_id = item.data(Qt.UserRole + workspace_manager.WORKSPACE_ROLE) if item else self.current_workspace_id
        hibernated = bool(meta.get("hibernated"))
        if browser is not None:
            try:
                hibernated = bool(browser.property("hibernated"))
            except Exception:
                pass
        return {
            "kind": "tab",
            "url": url,
            "title": meta.get("title") or (browser.title() if browser is not None else "") or url,
            "icon": meta.get("icon", ""),
            "hibernated": hibernated,
            "active": (browser is active_browser),
            "pinned": bool(item.data(TAB_PINNED_ROLE)) if item else False,
            "workspace_id": workspace_id or self.current_workspace_id,
        }

    def closeEvent(self, event):
        if self._closing:
            event.accept()
            return
        self._closing = True
        try:
            tabs = []
            current = self.current_browser()
            for i, browser in enumerate(self.browsers):
                payload = self._tab_state_payload(i, browser, current)
                if payload:
                    tabs.append(payload)
            state = prefs.session_state_load(self.base_dir)
            state["tabs"] = tabs
            prefs.session_state_save(self.base_dir, state)
            # "Reopen Closed Window" must not offer the session that is live at
            # app exit (v6.4 recorded it on every quit). Only remember the
            # window when another shell window is still open, i.e. the user
            # closed one of the two browser windows.
            other_visible = 0
            for w in QApplication.topLevelWidgets():
                if w is not self and w.isVisible() and w.inherits("QMainWindow") and w.windowTitle():
                    other_visible += 1
            if other_visible > 0:
                self.remember_closed_window(tabs)
            # Auto snapshot tab set (listtab)
            self._auto_save_tab_set()
        except Exception:
            pass
        finally:
            event.accept()

    def get_current_tab_state(self):
        tabs = []
        current = self.current_browser()
        for i, b in enumerate(self.browsers):
            payload = self._tab_state_payload(i, b, current)
            if payload:
                tabs.append(payload)
        return tabs

    def _auto_save_tab_set(self):
        tabs = self.get_current_tab_state()
        if not tabs:
            return
        import time
        title = time.strftime("Search auto %Y-%m-%d %H:%M")
        try:
            tab_sets.add_tab_set(self.base_dir, "search", title, tabs)
        except Exception:
            pass

    def save_current_tab_set(self):
        from PyQt5.QtWidgets import QInputDialog
        tabs = self.get_current_tab_state()
        if not tabs:
            QMessageBox.information(self, "Tab set", "No tabs to save.")
            return
        import time
        default = time.strftime("Search manual %Y-%m-%d %H:%M")
        name, ok = QInputDialog.getText(self, "Save Current Tab Set", "Tab set name:", text=default)
        if not ok:
            return
        try:
            tab_sets.add_tab_set(self.base_dir, "search", name or default, tabs)
            QMessageBox.information(self, "Tab set", "Current tab set saved.")
        except Exception as e:
            QMessageBox.warning(self, "Tab set", "Could not save tab set:\n%s" % (str(e),))

    def save_tab_set_named(self, name=None):
        """Save the current workspace's tabs under a name without prompting.
        Used by the ``/save-tabs`` omnibar macro."""
        tabs = self.get_current_tab_state()
        if not tabs:
            QMessageBox.information(self, "Tab set", "No tabs to save.")
            return
        import time
        default = time.strftime("Search manual %Y-%m-%d %H:%M")
        title = (name or default).strip() or default
        try:
            tab_sets.add_tab_set(self.base_dir, "search", title, tabs)
            QMessageBox.information(self, "Tab set", f"Saved tab set \"{title}\" ({len(tabs)} tabs).")
        except Exception as e:
            QMessageBox.warning(self, "Tab set", "Could not save tab set:\n%s" % (str(e),))

    def restore_tab_set(self, set_id):
        """Open a saved tab collection. Tabs reopen in a hibernated state so
        restoring a large research session stays cheap until you select a tab."""
        data = tab_sets.get_tab_set(self.base_dir, set_id)
        if not data:
            QMessageBox.warning(self, "Tab set", "Tab set not found.")
            return
        tabs = [tab for tab in data.get("tabs", []) if tab.get("url")]
        if not tabs:
            QMessageBox.information(self, "Tab set", "This tab set is empty.")
            return
        self.tab_manager.begin_batch()
        try:
            for tab in tabs:
                self.tab_manager.add_tab(
                    QUrl(tab.get("url")),
                    tab.get("title") or "Tab",
                    is_active=bool(tab.get("active")),
                    session_data=tab,
                )
        finally:
            self.tab_manager.end_batch()
        self.switch_to_browser_panel()
        QMessageBox.information(
            self,
            "Tab set",
            "Opened %d tab(s) from \"%s\"." % (len(tabs), data.get("title", "")),
        )

    def group_tabs_by_domain(self):
        """Label every tab in this workspace with a domain-based group.

        The label is stored in tab metadata so it survives hibernation and can
        be filtered with ``group:domain`` in the tab search. Returns a
        ``{group: count}`` mapping.
        """
        from urllib.parse import urlparse
        ws_role = Qt.UserRole + workspace_manager.WORKSPACE_ROLE
        counts = {}
        for i in range(self.tab_list.count()):
            item = self.tab_list.item(i)
            if not item or item.data(ws_role) != self.current_workspace_id:
                continue
            metadata = dict(item.data(TAB_META_ROLE) or {})
            url = metadata.get("url") or ""
            host = ""
            if url.startswith("http"):
                host = (urlparse(url).netloc or "").lower()
                host = host.removeprefix("www.")
            group = host or "ungrouped"
            metadata["group"] = group
            item.setData(TAB_META_ROLE, metadata)
            counts[group] = counts.get(group, 0) + 1
        return counts

    def group_tabs_action(self):
        counts = self.group_tabs_by_domain()
        if not counts:
            QMessageBox.information(self, "Tab groups", "No tabs to group.")
            return
        lines = "\n".join(
            "%s: %d tab(s)" % (domain, count)
            for domain, count in sorted(counts.items(), key=lambda kv: -kv[1])
        )
        QMessageBox.information(
            self,
            "Tab groups",
            "Tabs grouped by domain:\n\n%s\n\nFilter with: group:domain (e.g. group:youtube.com)" % lines,
        )


# Backward-compatible alias (older imports expect Browser).
Browser = SearchWindow
