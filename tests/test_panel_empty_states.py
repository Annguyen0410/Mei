"""Sidebar panels explain themselves when they have nothing to show.

Bookmarks, history and downloads used to render as blank boxes on a fresh
profile while the reading list already had a hint row — so the panel looked
broken rather than empty. The hint rows must also stay inert: no URL, no data
role, so the existing click and context-menu handlers ignore them.
"""
import os
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import litebrowser  # noqa: F401  activates the Qt compatibility shim
from litebrowser.core import prefs
from litebrowser.qt import QtCore, QtWidgets
from litebrowser.ui.main_window.window import SearchWindow

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


class _PanelHost(QtWidgets.QWidget):
    """Only the widgets the three panel loaders touch.

    A real SearchWindow needs a live QWebEngine surface, so these tests drive the
    real loader methods on a host that mirrors the attributes they read.
    """

    def __init__(self, base_dir):
        super().__init__()
        self.base_dir = base_dir
        self.bookmarks_tree = QtWidgets.QTreeWidget()
        self.history_list = QtWidgets.QListWidget()
        self.downloads_list = QtWidgets.QListWidget()


class TestSidebarEmptyStates(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base = prefs.ensure_profile_layout(os.path.join(self._tmp.name, "profile"))
        self.host = _PanelHost(self.base)

    def tearDown(self):
        self.host.deleteLater()
        self._tmp.cleanup()

    def test_empty_history_explains_itself(self):
        SearchWindow._load_history_panel(self.host)
        self.assertEqual(self.host.history_list.count(), 1)
        item = self.host.history_list.item(0)
        self.assertIn("No history yet", item.text())
        self.assertIsNone(item.data(QtCore.Qt.UserRole), "the hint must not be openable")

    def test_empty_downloads_explains_itself(self):
        SearchWindow._load_downloads_panel(self.host)
        self.assertEqual(self.host.downloads_list.count(), 1)
        item = self.host.downloads_list.item(0)
        self.assertIn("No downloads yet", item.text())
        self.assertIsNone(item.data(QtCore.Qt.UserRole))

    def test_empty_bookmarks_explains_itself(self):
        SearchWindow._load_bookmarks_panel(self.host)
        self.assertEqual(self.host.bookmarks_tree.topLevelItemCount(), 1)
        item = self.host.bookmarks_tree.topLevelItem(0)
        self.assertIn("No bookmarks yet", item.text(0))
        self.assertIsNone(item.data(0, QtCore.Qt.UserRole))
        self.assertFalse(item.flags() & QtCore.Qt.ItemIsDragEnabled, "the hint is not a bookmark")
        self.assertFalse(item.flags() & QtCore.Qt.ItemIsSelectable)

    def test_hint_rows_are_inert_for_the_click_handlers(self):
        SearchWindow._load_history_panel(self.host)
        SearchWindow._load_downloads_panel(self.host)
        SearchWindow._load_bookmarks_panel(self.host)
        # Would raise or start a bogus navigation if the hints carried data.
        SearchWindow._on_history_clicked(self.host, self.host.history_list.item(0))
        SearchWindow._on_download_clicked(self.host, self.host.downloads_list.item(0))
        SearchWindow._on_bookmark_clicked(self.host, self.host.bookmarks_tree.topLevelItem(0))

    def test_a_real_history_entry_replaces_the_hint(self):
        prefs.save_history_entries(self.base, [(1, "https://example.org/")])
        SearchWindow._load_history_panel(self.host)
        titles = [self.host.history_list.item(i).text() for i in range(self.host.history_list.count())]
        self.assertTrue(any("example.org" in text for text in titles))
        self.assertFalse(any("No history yet" in text for text in titles))


if __name__ == "__main__":
    unittest.main()
