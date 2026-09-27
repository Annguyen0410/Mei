"""The Settings card for plugins: the contract has to be reachable to matter.

``test_plugins.py`` covers the manifests and the runners. This file covers the
card: the shipped manifests are listed with what each one touches, running an
importer through the page really adds the rows and reports honestly, and a
manifest that is refused shows up as a sentence instead of breaking the page.
"""
import json
import os
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import litebrowser  # noqa: F401 - activates the Qt compatibility shim

from PyQt5.QtWidgets import QApplication, QWidget

from litebrowser.core import prefs
from litebrowser.services import life_service, plugins
from litebrowser.ui import personal_window as pw_module  # noqa: F401 - QtWebEngine first
from litebrowser.ui.shell import pages as pages_module

_app = QApplication.instance() or QApplication([])


class _StubShell(QWidget):
    def __init__(self, profile_dir, app_dir):
        super().__init__()
        self.profile_dir = profile_dir
        self.app_dir = app_dir
        self.update_status_text = ""
        self.refreshes = 0
        self.browser_page = QWidget()

    def refresh_shell(self, force_deep=False):
        self.refreshes += 1

    def __getattr__(self, name):
        return lambda *args, **kwargs: None


class TestPluginsCard(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name
        self.base = prefs.ensure_profile_layout(os.path.join(self.root, "profile"))
        self.shell = _StubShell(self.base, self.root)
        self.page = pages_module.SettingsPage(self.shell)

    def tearDown(self):
        self.page.deleteLater()
        self.shell.deleteLater()
        self._tmp.cleanup()

    def _csv(self, name: str, text: str) -> str:
        path = os.path.join(self.root, name)
        with open(path, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
        return path

    def _select(self, plugin_id: str):
        from PyQt5.QtCore import Qt

        for row in range(self.page.plugins_list.count()):
            item = self.page.plugins_list.item(row)
            plugin = item.data(Qt.UserRole)
            if isinstance(plugin, plugins.Plugin) and plugin.id == plugin_id:
                self.page.plugins_list.setCurrentItem(item)
                return plugin
        raise AssertionError(f"{plugin_id} is not in the plugin list")

    def test_the_shipped_manifests_are_listed_with_what_they_touch(self):
        listed = [self.page.plugins_list.item(row).text() for row in range(self.page.plugins_list.count())]
        self.assertTrue(any("Todoist" in text for text in listed), listed)
        self.assertTrue(any("Notes → CSV" in text for text in listed), listed)
        self.assertTrue(self.page.btn_run_plugin.isEnabled())
        self.assertIn("plugin(s) ready", self.page.lbl_plugin_problems.text())
        todos = self._select("todoist-csv")
        self.assertIn("Quick tasks", todos.touches())

    def test_running_an_importer_through_the_card_adds_the_rows(self):
        csv_path = self._csv("todoist.csv", "TYPE,DATE,CONTENT,PRIORITY,DESCRIPTION\ntask,,Buy ink,4,\n")
        self._select("todoist-csv")
        with mock.patch.object(pages_module.QFileDialog, "getOpenFileName", return_value=(csv_path, "")), \
                mock.patch.object(pages_module.QMessageBox, "information") as told:
            self.page.btn_run_plugin.click()
        self.assertEqual([task["title"] for task in life_service.load_tasks(self.base)], ["Buy ink"])
        self.assertIn("imported 1 of 1", told.call_args[0][2])
        self.assertIn("imported 1 of 1", self.page.lbl_plugin_problems.text())
        self.assertGreaterEqual(self.shell.refreshes, 1)

    def test_running_an_exporter_writes_the_file(self):
        target = os.path.join(self.root, "notes.csv")
        self._select("notes-to-csv")
        with mock.patch.object(pages_module.QFileDialog, "getSaveFileName", return_value=(target, "")), \
                mock.patch.object(pages_module.QMessageBox, "information") as told:
            self.page.btn_run_plugin.click()
        self.assertTrue(os.path.isfile(target))
        self.assertIn("wrote 0 row(s)", told.call_args[0][2])

    def test_a_refused_manifest_is_reported_on_the_card(self):
        folder = os.path.join(plugins.plugins_dir(self.base), "half-baked")
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, plugins.MANIFEST_NAME), "w", encoding="utf-8") as handle:
            json.dump({"id": "half", "name": "Half", "version": "1", "api": 1}, handle)
        self.page._refresh_plugins()
        text = self.page.lbl_plugin_problems.text()
        self.assertIn("refused", text)
        self.assertIn("half-baked", text)
        self.assertIn("missing field(s)", text)
        self.assertTrue(self.page.btn_run_plugin.isEnabled(), "one bad manifest must not hide the good ones")

    def test_a_cancelled_dialog_runs_nothing(self):
        self._select("todoist-csv")
        with mock.patch.object(pages_module.QFileDialog, "getOpenFileName", return_value=("", "")), \
                mock.patch.object(plugins, "run_plugin") as runner:
            self.page.btn_run_plugin.click()
        runner.assert_not_called()
        self.assertEqual(life_service.load_tasks(self.base), [])


if __name__ == "__main__":
    unittest.main()
