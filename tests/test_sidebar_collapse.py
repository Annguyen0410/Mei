"""Regression tests for the browser-window sidebar collapse/expand logic.

SearchWindow itself needs a live QWebEngine surface, so these tests drive the
*real* SearchWindow methods (SearchWindow._toggle_sidebar_collapse etc.) on a
minimal host window that mirrors the attributes the sidebar code touches.
The collapse animation is replaced with a synchronous fake so each scenario
runs deterministically offscreen.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# The shipped app imports this package before its Qt imports, which aliases
# the legacy PyQt5 imports below to PyQt6 when PyQt6 is installed.  Do the
# same in this test; otherwise it exercises a different splitter runtime than
# the actual Mei process.
import litebrowser  # noqa: F401

from PyQt5.QtCore import QAbstractAnimation, QObject, Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QApplication,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QSplitter,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

_app = QApplication.instance() or QApplication([])

import litebrowser.ui.main_window.window as _wm


class _FakeAnim(QObject):
    """Synchronous QVariantAnimation stand-in: jumps straight to its end."""

    valueChanged = pyqtSignal(float)
    finished = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._state = QAbstractAnimation.State.Stopped
        self._end = 0.0

    def stop(self):
        pass

    def setDuration(self, *_a):
        pass

    def setEasingCurve(self, *_a):
        pass

    def setStartValue(self, *_a):
        pass

    def setEndValue(self, v):
        self._end = float(v)

    def state(self):
        return self._state

    def start(self):
        self._state = QAbstractAnimation.State.Running
        self.valueChanged.emit(self._end)
        self.finished.emit()
        self._state = QAbstractAnimation.State.Stopped


_wm.QVariantAnimation = _FakeAnim


class _SidebarHost(QMainWindow):
    """Minimal host exposing exactly the attributes the sidebar methods use."""

    def _collapsed_rail_width(self):
        return _wm.SearchWindow._collapsed_rail_width(self)

    def _sidebar_expanded_nominal_width(self):
        return _wm.SearchWindow._sidebar_expanded_nominal_width(self)

    def _apply_sidebar_collapse_visibility(self):
        return _wm.SearchWindow._apply_sidebar_collapse_visibility(self)

    def _apply_responsive_layout(self):
        return _wm.SearchWindow._apply_responsive_layout(self)

    def _toggle_sidebar_collapse(self):
        return _wm.SearchWindow._toggle_sidebar_collapse(self)

    def _release_sidebar_width_lock(self, rail=None):
        return _wm.SearchWindow._release_sidebar_width_lock(self, rail)

    def _ensure_sidebar_splitter_healthy(self):
        return _wm.SearchWindow._ensure_sidebar_splitter_healthy(self)

    def _apply_collapse_btn_state(self):
        return _wm.SearchWindow._apply_collapse_btn_state(self)

    def _on_main_splitter_moved(self, pos, index):
        return _wm.SearchWindow._on_main_splitter_moved(self, pos, index)

    def _queue_expanded_sidebar_recovery(self):
        return _wm.SearchWindow._queue_expanded_sidebar_recovery(self)

    def eventFilter(self, obj, ev):
        return _wm.SearchWindow.eventFilter(self, obj, ev)

    def __init__(self, width, height=700):
        super().__init__()
        self.embedded = False
        self._topbar_collapsed = False
        self.sidebar_collapsed = False
        self._sidebar_anim = None
        self._sidebar_split_press = None
        root = QWidget()
        self.setCentralWidget(root)
        lay = QHBoxLayout(root)
        lay.setContentsMargins(0, 0, 0, 0)
        self.main_splitter = QSplitter(Qt.Horizontal)
        self.main_splitter.setChildrenCollapsible(False)
        lay.addWidget(self.main_splitter)
        self.sidebarWidget = QWidget()
        self.sidebarWidget.setObjectName("Sidebar")
        self.sidebarWidget.setMinimumWidth(190)
        self.sidebarWidget.setMaximumWidth(800)
        self.sidebar_layout = QVBoxLayout(self.sidebarWidget)
        self.sidebar_layout.setContentsMargins(8, 10, 8, 10)
        title_row = QHBoxLayout()
        self.btn_collapse_sidebar = QToolButton()
        self.btn_collapse_sidebar.setObjectName("SidebarCollapse")
        self.btn_collapse_sidebar.setText("<")
        title_row.addWidget(self.btn_collapse_sidebar)
        self.brand_glyph = QLabel("tea")
        title_row.addWidget(self.brand_glyph)
        self.title_label = QLabel("Mei")
        title_row.addWidget(self.title_label, 1)
        self.sidebar_layout.addLayout(title_row)
        self.lbl_tab_count = QLabel("1 Live")
        self.sidebar_layout.addWidget(self.lbl_tab_count)
        self.workspace_combo = QComboBox()
        self.workspace_combo.addItem("Workspace")
        self.sidebar_layout.addWidget(self.workspace_combo)
        row = QHBoxLayout()
        self.btn_panel_tabs = QToolButton()
        self.btn_panel_bookmarks = QToolButton()
        self.btn_panel_history = QToolButton()
        self.btn_panel_downloads = QToolButton()
        self.btn_panel_reading = QToolButton()
        for b in (self.btn_panel_tabs, self.btn_panel_bookmarks, self.btn_panel_history,
                  self.btn_panel_downloads, self.btn_panel_reading):
            b.setText("x")
            row.addWidget(b)
        self.sidebar_layout.addLayout(row)
        self.sidebar_stack = QStackedWidget()
        self.sidebar_stack.addWidget(QWidget())
        self.sidebar_layout.addWidget(self.sidebar_stack, 1)
        self.sidebar_footer = QWidget()
        self.sidebar_layout.addWidget(self.sidebar_footer)
        self.main_splitter.addWidget(self.sidebarWidget)
        content = QWidget()
        content.setMinimumWidth(200)
        self.main_splitter.addWidget(content)
        # Match the production order: explicitly lock each pane after both
        # have been added, which is the reliable form under the PyQt6 shim.
        self.main_splitter.setCollapsible(0, False)
        self.main_splitter.setCollapsible(1, False)
        self.main_splitter.setHandleWidth(8)
        handle = self.main_splitter.handle(1)
        if handle is not None:
            handle.installEventFilter(self)
        initial = self._sidebar_expanded_nominal_width()
        self.main_splitter.setSizes([initial, max(420, width - initial)])
        self.resize(width, height)
        self.show()
        _app.processEvents()
        self._apply_responsive_layout()


def _drag_splitter(host, sidebar_width):
    """Simulate a user dragging the divider so the sidebar is `sidebar_width`."""
    host.main_splitter.setSizes([sidebar_width, max(300, host.width() - sidebar_width)])
    _app.processEvents()
    host._on_main_splitter_moved(sidebar_width, 0)


def test_sidebar_collapse_never_reaches_zero_or_hides():
    for width in (560, 620, 700, 950, 1300):
        host = _SidebarHost(width)
        try:
            sw = host.sidebarWidget
            # Expanded default: readable width, visible.
            assert sw.isVisible()
            assert sw.width() >= 120
            assert sw.maximumWidth() > sw.minimumWidth()

            # Collapse via the real toggle handler.
            host._toggle_sidebar_collapse()
            assert host.sidebar_collapsed
            assert sw.isVisible(), f"collapsed sidebar hidden at width {width}"
            assert sw.width() >= 40, f"collapsed rail too small at width {width}: {sw.width()}"
            # Animation must NOT leave min==max (that is the stuck-desk bug).
            assert sw.maximumWidth() > sw.minimumWidth(), "collapse left min==max lock"
            assert host.btn_collapse_sidebar.isVisible()
            assert host.btn_collapse_sidebar.property("collapsed") is True
            assert host.btn_collapse_sidebar.width() >= 12

            # Drag the divider wider: the tab desk must come back.
            rail = host._collapsed_rail_width()
            _drag_splitter(host, rail + 80)
            assert not host.sidebar_collapsed
            assert sw.isVisible() and sw.width() >= 120
            assert sw.maximumWidth() > sw.minimumWidth()

            # Dragging it narrower only resizes it; it must never hide the
            # tab desk. The explicit arrow remains the collapse control.
            _drag_splitter(host, 140)
            assert not host.sidebar_collapsed
            assert sw.isVisible() and sw.width() >= 120

            # Toggle click: collapse, then expand again.
            host._toggle_sidebar_collapse()
            assert host.sidebar_collapsed and sw.isVisible() and sw.width() >= 26
            assert sw.maximumWidth() > sw.minimumWidth()
            host._toggle_sidebar_collapse()
            assert not host.sidebar_collapsed and sw.width() >= 120
            assert sw.maximumWidth() > sw.minimumWidth()

            # Simulate the historic stuck lock, then heal it.
            host.sidebarWidget.setMinimumWidth(80)
            host.sidebarWidget.setMaximumWidth(80)
            host._ensure_sidebar_splitter_healthy()
            assert host.sidebarWidget.maximumWidth() >= 800
            assert sw.isVisible() and sw.width() >= 120
        finally:
            host.close()


def test_divider_single_click_does_not_collapse():
    """Bare click on the resize handle must not hide or lock the tab desk."""
    from PyQt5.QtCore import QEvent, QPointF, Qt
    from PyQt5.QtGui import QMouseEvent

    host = _SidebarHost(950)
    try:
        handle = host.main_splitter.handle(1)
        assert handle is not None
        assert not host.main_splitter.isCollapsible(0)
        assert not host.main_splitter.isCollapsible(1)
        before = host.sidebar_collapsed
        before_sizes = list(host.main_splitter.sizes())
        mods = getattr(Qt, "NoModifier", None)
        if mods is None:
            mods = Qt.KeyboardModifier.NoModifier
        local = QPointF(2, 40)
        global_pos = QPointF(20, 80)
        press = QMouseEvent(
            QEvent.MouseButtonPress, local, global_pos, Qt.LeftButton, Qt.LeftButton, mods
        )
        release = QMouseEvent(
            QEvent.MouseButtonRelease, local, global_pos, Qt.LeftButton, Qt.LeftButton, mods
        )
        assert host.eventFilter(handle, press) is False
        # Mid-click: pretend layout tried to steal width.
        host.main_splitter.setSizes([0, 950])
        _app.processEvents()
        assert host.eventFilter(handle, release) is False
        assert host.sidebar_collapsed is before
        assert host.sidebarWidget.maximumWidth() > host.sidebarWidget.minimumWidth()
        assert host.sidebarWidget.width() >= 120
        # Sizes restored near the pre-click desk (not left at 0).
        assert host.main_splitter.sizes()[0] >= 120
        assert before_sizes[0] >= 120

        dbl = QMouseEvent(
            QEvent.MouseButtonDblClick, local, global_pos, Qt.LeftButton, Qt.LeftButton, mods
        )
        assert host.eventFilter(handle, dbl) is False
        assert host.sidebar_collapsed is before
    finally:
        host.close()


def test_narrow_expanded_sidebar_stays_open_while_resizing():
    """No divider interaction may hide a narrow, expanded tab desk."""
    host = _SidebarHost(560)
    try:
        _drag_splitter(host, 120)
        assert not host.sidebar_collapsed

        # A deliberate leftward resize from a normal desk width still leaves
        # the tab desk open; only the sidebar arrow can collapse it.
        host.main_splitter.setSizes([200, 360])
        _app.processEvents()
        host.main_splitter.setSizes([120, 440])
        _app.processEvents()
        assert not host.sidebar_collapsed
        assert host.sidebarWidget.maximumWidth() > host.sidebarWidget.minimumWidth()
    finally:
        host.close()


def test_layout_squeeze_recovers_an_expanded_sidebar():
    """A nested-layout squeeze must not leave the tab desk at zero width."""
    host = _SidebarHost(700)
    try:
        host.sidebarWidget.setMinimumWidth(0)
        host.main_splitter.setSizes([0, 700])
        _app.processEvents()
        host._on_main_splitter_moved(0, 1)
        _app.processEvents()

        assert not host.sidebar_collapsed
        assert host.sidebarWidget.isVisible()
        assert host.sidebarWidget.width() >= 120
        assert host.sidebarWidget.maximumWidth() > host.sidebarWidget.minimumWidth()
    finally:
        host.close()


def test_stuck_minmax_lock_is_healed_without_shell_rail():
    """Profile-rail toggle used to be the only unlock path — heal in-app."""
    host = _SidebarHost(900)
    try:
        host.sidebarWidget.setMinimumWidth(96)
        host.sidebarWidget.setMaximumWidth(96)
        host.main_splitter.setSizes([96, 804])
        _app.processEvents()
        # Drag/setSizes must fail while locked (documents the old bug).
        host.main_splitter.setSizes([240, 660])
        _app.processEvents()
        assert host.sidebarWidget.width() == 96

        host._ensure_sidebar_splitter_healthy()
        _app.processEvents()
        assert host.sidebarWidget.maximumWidth() >= 800
        assert host.sidebarWidget.width() >= 120
        host.main_splitter.setSizes([240, 660])
        _app.processEvents()
        assert host.sidebarWidget.width() >= 200
    finally:
        host.close()
