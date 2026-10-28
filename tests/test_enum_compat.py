"""Enum compat regression: every (class, member) the app dereferences must
resolve under the ACTIVE binding (PyQt6 shim or PyQt5). This is the net that
catches 'works on PyQt5, dies on PyQt6' startup crashes like the 0.6.8 one.

A missing member is not a cosmetic problem: PyQt6 turns an AttributeError
raised inside a reimplemented virtual into qFatal, so the whole application
aborts with no traceback. ``QGraphicsRectItem.ItemPositionHasChanged`` was
absent from the shim and killed Mei the first time a board with a sticky card
was opened; the last test here scans the source so the next one fails in CI
instead of on a user's desktop.
"""
import ast
import collections
import os
import sys
import unittest

os_setter = __import__("os").environ.setdefault
os_setter("QT_QPA_PLATFORM", "offscreen")

# The point of this file is to check the members the app dereferences under the
# ACTIVE binding, so the shim has to be active before these imports resolve - and
# importing PyQt5 first would load a second Qt runtime alongside it.
import litebrowser  # noqa: F401 - litebrowser/__init__ activates the Qt shim

from PyQt5 import QtCore, QtGui, QtWidgets
from PyQt5.QtCore import QEvent, QIODevice, Qt
from PyQt5.QtGui import QFont, QTextCursor
from PyQt5.QtNetwork import QNetworkProxy
from PyQt5.QtWebEngineWidgets import (
    QWebEnginePage,
    QWebEngineProfile,
    QWebEngineScript,
    QWebEngineSettings,
)
from PyQt5.QtWidgets import (
    QApplication,
    QCompleter,
    QDialog,
    QGraphicsRectItem,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QStyle,
    QSystemTrayIcon,
)

import litebrowser.qt_compat  # noqa: F401 - imported for its side effects


class TestEnumCompat(unittest.TestCase):
    def _assert_attr(self, cls, name):
        self.assertTrue(hasattr(cls, name), f"{cls.__name__}.{name} missing")

    def test_qevent_type_members(self):
        for name in ("MouseButtonDblClick", "MouseButtonRelease", "MouseButtonPress", "Resize", "Close"):
            self._assert_attr(QEvent, name)

    def test_qt_members(self):
        for name in ("MiddleButton", "LeftButton", "CustomContextMenu", "AlignCenter",
                      "ScrollBarAlwaysOff", "PointingHandCursor", "Key_Escape"):
            self._assert_attr(Qt, name)

    def test_webengine_profile(self):
        for name in ("NoPersistentCookies", "ForcePersistentCookies", "MemoryHttpCache"):
            self._assert_attr(QWebEngineProfile, name)

    def test_webengine_script(self):
        for name in ("DocumentCreation", "DocumentReady", "MainWorld", "ApplicationWorld"):
            self._assert_attr(QWebEngineScript, name)

    def test_webengine_page(self):
        for name in ("PermissionGrantedByUser", "PermissionDeniedByUser",
                      "ReloadAndBypassCache", "Reload", "Geolocation", "Notifications"):
            self._assert_attr(QWebEnginePage, name)

    def test_webengine_settings(self):
        for name in ("JavascriptEnabled", "JavascriptCanOpenWindows",
                      "LocalContentCanAccessRemoteUrls", "PluginsEnabled",
                      "ScrollAnimatorEnabled", "WebGLEnabled", "DnsPrefetchEnabled"):
            self._assert_attr(QWebEngineSettings, name)

    def test_widgets_and_tray(self):
        for name in ("Trigger", "DoubleClick", "Information"):
            self._assert_attr(QSystemTrayIcon, name)
        for name in ("Password", "Normal", "LeadingPosition", "TrailingPosition"):
            self._assert_attr(QLineEdit, name)
        for name in ("Yes", "No", "NoToAll", "Warning", "Information"):
            self._assert_attr(QMessageBox, name)
        for name in ("Accepted", "Rejected"):
            self._assert_attr(QDialog, name)
        self._assert_attr(QStyle, "SP_DialogCloseButton")
        for name in ("Socks5Proxy", "HttpProxy", "NoProxy"):
            self._assert_attr(QNetworkProxy, name)

    def test_graphics_item_flags_and_position_change(self):
        # Flags go to setFlags(); ItemPositionHasChanged arrives in itemChange().
        for name in ("ItemIsMovable", "ItemIsSelectable", "ItemSendsGeometryChanges"):
            self._assert_attr(QGraphicsRectItem, name)
        self._assert_attr(QGraphicsRectItem, "ItemPositionHasChanged")

    def test_text_cursor_move_modes(self):
        # The note find bar and wiki-link insertion both anchor a selection.
        for name in ("MoveAnchor", "KeepAnchor"):
            self._assert_attr(QTextCursor, name)

    def test_io_device_open_modes(self):
        self._assert_attr(QIODevice, "WriteOnly")

    def test_list_and_completer_aliases(self):
        self._assert_attr(QListWidget, "InternalMove")
        self._assert_attr(QListWidget, "SingleSelection")
        self._assert_attr(QCompleter, "PopupCompletion")
        self._assert_attr(QFont, "AbsoluteSpacing")

    def test_every_qt_member_dereferenced_by_the_source_exists(self):
        """Static net over ``QSomething.Member`` uses in app, tools and tests.

        Catches the whole class of PyQt5-only spellings rather than the handful
        that happen to be in the code today.
        """
        namespace = {}
        for module in (QtCore, QtGui, QtWidgets):
            for name in dir(module):
                if name.startswith("Q"):
                    namespace.setdefault(name, getattr(module, name))
        for module in (sys.modules.get("PyQt5.QtNetwork"), sys.modules.get("PyQt5.QtPrintSupport"),
                       sys.modules.get("PyQt5.QtWebEngineWidgets")):
            if module is None:
                continue
            for name in dir(module):
                if name.startswith("Q"):
                    namespace.setdefault(name, getattr(module, name))

        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        missing = collections.defaultdict(set)
        for folder in ("litebrowser", "tools", "tests"):
            for base, dirs, files in os.walk(os.path.join(root, folder)):
                dirs[:] = [d for d in dirs if d != "__pycache__"]
                for filename in files:
                    if not filename.endswith(".py"):
                        continue
                    path = os.path.join(base, filename)
                    try:
                        tree = ast.parse(open(path, encoding="utf-8").read(), path)
                    except SyntaxError:
                        continue
                    # A member that the same file feature-detects (hasattr /
                    # getattr default) or that sits in a try/except that names
                    # AttributeError is an intentional fallback, not a missing
                    # alias: those branches only run on a binding that has the
                    # old spelling.
                    guarded = set()
                    for node in ast.walk(tree):
                        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                                and node.func.id in ("hasattr", "getattr") and len(node.args) >= 2:
                            target_node, attr_node = node.args[0], node.args[1]
                            if isinstance(target_node, ast.Name) and isinstance(attr_node, ast.Constant) \
                                    and isinstance(attr_node.value, str):
                                guarded.add(f"{target_node.id}.{attr_node.value}")
                        if isinstance(node, ast.Try) and any(
                            (isinstance(handler.type, ast.Name) and handler.type.id == "AttributeError")
                            or (isinstance(handler.type, ast.Tuple) and any(
                                isinstance(item, ast.Name) and item.id == "AttributeError"
                                for item in handler.type.elts
                            ))
                            for handler in node.handlers
                        ):
                            for sub in ast.walk(node):
                                if isinstance(sub, ast.Attribute) and isinstance(sub.value, ast.Name):
                                    guarded.add(f"{sub.value.id}.{sub.attr}")
                    for node in ast.walk(tree):
                        if not isinstance(node, ast.Attribute) or not isinstance(node.value, ast.Name):
                            continue
                        target = namespace.get(node.value.id)
                        if target is None:
                            continue
                        qualified = f"{node.value.id}.{node.attr}"
                        if qualified in guarded:
                            continue
                        if not hasattr(target, node.attr):
                            missing[qualified].add(os.path.relpath(path, root))
        self.assertEqual(
            {},
            {name: sorted(files) for name, files in missing.items()},
            "Qt members dereferenced but missing under the active binding",
        )

    def test_exec_alias_on_all_used_classes(self):
        # PyQt6 removed exec_(); the shim must restore it on every class the
        # app calls exec_() on - QMenu especially (it is NOT a QDialog).
        from PyQt5.QtWidgets import QMenu
        for cls in (QApplication, QDialog, QMessageBox, QMenu):
            self.assertTrue(callable(getattr(cls, "exec_", None)), f"{cls.__name__}.exec_ missing")


if __name__ == "__main__":
    unittest.main()
