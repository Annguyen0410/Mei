"""Enum compat regression: every (class, member) the app dereferences must
resolve under the ACTIVE binding (PyQt6 shim or PyQt5). This is the net that
catches 'works on PyQt5, dies on PyQt6' startup crashes like the 0.6.8 one."""
import unittest

os_setter = __import__("os").environ.setdefault
os_setter("QT_QPA_PLATFORM", "offscreen")

import litebrowser.qt_compat  # noqa: F402  (activates the shim)

from PyQt5.QtCore import QEvent, Qt
from PyQt5.QtWidgets import QApplication, QSystemTrayIcon, QLineEdit, QMessageBox, QDialog
from PyQt5.QtGui import QFont, QPainter
from PyQt5.QtWidgets import QStyle, QLineEdit as _LE
from PyQt5.QtWebEngineWidgets import (
    QWebEnginePage,
    QWebEngineProfile,
    QWebEngineScript,
    QWebEngineSettings,
)
from PyQt5.QtNetwork import QNetworkProxy


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

    def test_exec_alias_on_all_used_classes(self):
        # PyQt6 removed exec_(); the shim must restore it on every class the
        # app calls exec_() on - QMenu especially (it is NOT a QDialog).
        from PyQt5.QtWidgets import QMenu
        for cls in (QApplication, QDialog, QMessageBox, QMenu):
            self.assertTrue(callable(getattr(cls, "exec_", None)), f"{cls.__name__}.exec_ missing")


if __name__ == "__main__":
    unittest.main()
