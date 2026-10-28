"""Idea Boards refinement: shelf rows, empty stage, modes, cards, ink.

Exercised on a real offscreen PersonalWindow, like the notes tests, so the
assertions cover the widget tree the app builds rather than a parallel mock.

The sticky-card scene is exercised for real now: constructing a card used to
abort the process (a Qt member missing from the shim, see test_enum_compat), and
the crash guard at the bottom of this file runs that path in a subprocess so a
regression fails a test instead of killing the whole run.
"""
import gc
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import litebrowser  # noqa: F401 - activates the Qt shim

from PyQt5.QtCore import QEvent, QPoint, QPointF, Qt
from PyQt5.QtGui import QMouseEvent
from PyQt5.QtWidgets import QApplication, QInputDialog, QWidget

from litebrowser.core import prefs
from litebrowser.services import life_service
from litebrowser.ui import personal_window as pw


@unittest.skipUnless(sys.platform.startswith("win"), "offscreen smoke on dev machine")
class TestBoardsPageUI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base = prefs.ensure_profile_layout(os.path.join(self._tmp.name, "profile"))
        self._patched = []
        self.window = None

    def tearDown(self):
        for attr, value in self._patched:
            setattr(pw, attr, value)
        if self.window is not None:
            self.window.close()
            self.window.setParent(None)
            self.window = None
            gc.collect()
            QApplication.processEvents()
        self._tmp.cleanup()

    def _window(self, width=1440, height=900, show=True):
        class _FakeSiteView(QWidget):
            def __getattr__(self, name):
                return lambda *a, **k: None

        # Sites builds a real WebEngine view offscreen, which hangs; not under test.
        self._patched.append(("_build_site_view", pw.PersonalWindow._build_site_view))
        pw.PersonalWindow._build_site_view = lambda self: _FakeSiteView()
        self.window = pw.PersonalWindow(self.base, embedded=True)
        self.window.resize(width, height)
        self.window._switch_page("boards")
        if show:
            self.window.show()
            QApplication.processEvents()
        return self.window

    def _board(self, title, strokes=0, cards=0, background=None):
        board = life_service.add_board(self.base, title)
        if strokes:
            board["strokes"] = [
                {
                    "id": f"{title}-s{index}",
                    "tool": "pen",
                    "color": "#292d32",
                    "width": 3,
                    "opacity": 1,
                    "points": [{"x": 10, "y": 10}, {"x": 80 + index, "y": 40}],
                }
                for index in range(strokes)
            ]
        if cards:
            board["nodes"] = [
                {"id": f"{title}-n{index}", "title": f"Card {index}", "kind": "sticky",
                 "payload": "", "x": 20, "y": 20, "color": "#f5e4ad"}
                for index in range(cards)
            ]
        if background:
            board["background"] = background
        life_service.update_board(self.base, board)
        return board

    # ---------------------------------------------------------------- cards

    def test_a_board_with_cards_and_links_opens_its_scene(self):
        window = self._window(show=False)
        board = self._board("Cards", cards=2)
        board["edges"] = [{"id": "e1", "from": "Cards-n0", "to": "Cards-n1"}]
        life_service.update_board(self.base, board)

        window.open_life_item("board", board["id"])
        QApplication.processEvents()

        items = window.board_scene.items()
        cards = [item for item in items if isinstance(item, pw.StickyCardItem)]
        edges = [item for item in items if isinstance(item, pw.EdgeItem)]
        self.assertEqual(2, len(cards))
        self.assertEqual(1, len(edges))
        self.assertEqual(2, len([i for i in items if isinstance(i, pw.StickyCardItem)]))

    def test_a_link_follows_the_card_it_connects(self):
        window = self._window(show=False)
        board = self._board("Links", cards=2)
        board["edges"] = [{"id": "e1", "from": "Links-n0", "to": "Links-n1"}]
        life_service.update_board(self.base, board)
        window.open_life_item("board", board["id"])
        QApplication.processEvents()

        edge = next(item for item in window.board_scene.items() if isinstance(item, pw.EdgeItem))
        before = edge.path().pointAtPercent(0.0)
        card = edge.from_item
        card.setPos(card.pos() + QPointF(90, 40))
        after = edge.path().pointAtPercent(0.0)
        self.assertNotEqual(before, after)
        self.assertAlmostEqual(card.pos().x() + card.rect().width() / 2, after.x(), places=3)

    def test_adding_a_card_persists_it(self):
        window = self._window(show=False)
        board = self._board("Notes board")
        window.open_life_item("board", board["id"])
        QApplication.processEvents()

        with mock.patch.object(QInputDialog, "getText", staticmethod(lambda *a, **k: ("Next step", True))):
            window._add_board_card()
        QApplication.processEvents()

        saved = next(b for b in life_service.load_boards(self.base) if b["id"] == board["id"])
        self.assertEqual(["Next step"], [node["title"] for node in saved["nodes"]])
        self.assertEqual(1, len([i for i in window.board_scene.items() if isinstance(i, pw.StickyCardItem)]))

    def test_a_swept_stroke_is_saved_and_can_be_undone(self):
        window = self._window(show=False)
        board = self._board("Sketch")
        window.open_life_item("board", board["id"])
        QApplication.processEvents()
        view = window.board_view
        view.set_mode("draw")
        view.set_tool("pen")
        viewport = view.viewport()

        def send(kind, pos, buttons):
            event = QMouseEvent(
                kind,
                QPointF(pos),
                QPointF(viewport.mapToGlobal(pos)),
                Qt.MouseButton.LeftButton,
                buttons,
                Qt.KeyboardModifier.NoModifier,
            )
            if kind == QEvent.Type.MouseButtonPress:
                view.mousePressEvent(event)
            elif kind == QEvent.Type.MouseMove:
                view.mouseMoveEvent(event)
            else:
                view.mouseReleaseEvent(event)

        send(QEvent.Type.MouseButtonPress, QPoint(120, 120), Qt.MouseButton.LeftButton)
        for step in range(1, 8):
            send(QEvent.Type.MouseMove, QPoint(120 + step * 8, 120 + step * 6), Qt.MouseButton.LeftButton)
        send(QEvent.Type.MouseButtonRelease, QPoint(180, 160), Qt.MouseButton.NoButton)
        QApplication.processEvents()

        strokes = window._board_snapshot()["strokes"]
        self.assertEqual(1, len(strokes))
        self.assertGreaterEqual(len(strokes[0]["points"]), 2)
        self.assertTrue(window.btn_board_undo.isEnabled())

        window._save_current_board_positions(notify=False)
        saved = next(b for b in life_service.load_boards(self.base) if b["id"] == board["id"])
        self.assertEqual(1, len(saved["strokes"]))

        view.undo()
        QApplication.processEvents()
        self.assertEqual([], window._board_snapshot()["strokes"])
        view.redo()
        QApplication.processEvents()
        self.assertEqual(1, len(window._board_snapshot()["strokes"]))

    def test_creating_a_sticky_card_does_not_abort_the_process(self):
        """Regression guard for the qFatal in QGraphicsItem.itemChange()."""
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        probe = (
            "import os, sys\n"
            "os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')\n"
            f"sys.path.insert(0, {root!r})\n"
            "import litebrowser\n"
            "from PyQt5.QtWidgets import QApplication, QGraphicsScene\n"
            "from litebrowser.ui import personal_window as pw\n"
            "app = QApplication([])\n"
            "scene = QGraphicsScene()\n"
            "item = pw.StickyCardItem({'id': 'n1', 'title': 'Card', 'payload': 'body',\n"
            "                          'x': 20, 'y': 20, 'color': '#f5e4ad'})\n"
            "scene.addItem(item)\n"
            "item.setPos(120.0, 80.0)\n"
            "item.setPos(200.0, 140.0)\n"
            "print('CARD_OK', len(scene.items()))\n"
        )
        env = dict(os.environ, QT_QPA_PLATFORM="offscreen", LITEBROWSER_UPDATE_METADATA_URL="")
        completed = subprocess.run(
            [sys.executable, "-c", probe],
            capture_output=True,
            text=True,
            timeout=120,
            env=env,
        )
        self.assertEqual(0, completed.returncode, completed.stderr[-2000:])
        self.assertIn("CARD_OK", completed.stdout)

    # ---------------------------------------------------------------- shelf

    def test_shelf_rows_carry_counts_and_readable_titles(self):
        self._board("Research wall", strokes=2)
        # Parked: selected boards with cards abort this Qt build, so its counts
        # are asserted on the row payload only.
        self._board("Node wall", cards=1)
        win = self._window()

        self.assertIsInstance(win.boards_list.itemDelegate(), pw.BoardRowDelegate)
        first, second = win.boards_list.item(0), win.boards_list.item(1)
        self.assertEqual(first.text(), "Research wall")
        self.assertEqual(first.data(Qt.UserRole), life_service.load_boards(self.base)[0]["id"])
        self.assertIn("2 strokes", first.data(pw.BOARD_ROW_ROLE)["meta"])
        self.assertEqual(first.toolTip().splitlines()[0], "Research wall")
        self.assertIn("2 strokes", first.toolTip())
        self.assertEqual(second.data(pw.BOARD_ROW_ROLE)["meta"], "1 card")
        self.assertEqual(win._boards_header_subtitle.text(), "2 boards")

        # Saving a fresh stroke updates the row's counts without a list rebuild.
        before = win._board_snapshot()
        from litebrowser.ui.board_canvas import InkStrokeItem

        win.board_scene.addItem(InkStrokeItem({"id": "new", "points": [{"x": 1, "y": 1}, {"x": 4, "y": 4}]}))
        win.board_view.record_change(before)
        self.assertTrue(win._save_current_board_positions(notify=False))
        self.assertIn("3 strokes", win.boards_list.item(0).data(pw.BOARD_ROW_ROLE)["meta"])

    def test_empty_stage_offers_the_one_next_step(self):
        win = self._window()
        self.assertEqual(win._board_stack.currentIndex(), 1)
        self.assertEqual(win.lbl_board_title.text(), "No board open")
        self.assertFalse(win.btn_add_card.isEnabled())
        self.assertFalse(win.btn_canvas_color.isEnabled())
        self.assertEqual(win._board_empty_title.text(), "No boards yet")
        self.assertIn("Create one", win._board_empty_hint.text())
        self.assertTrue(win.btn_empty_new_board.isVisible())
        self.assertEqual(win._boards_header_subtitle.text(), "No boards yet")

        with mock.patch.object(pw.QInputDialog, "getText", return_value=("First wall", True)):
            win.btn_empty_new_board.click()
        QApplication.processEvents()
        self.assertEqual(win.boards_list.count(), 1)
        self.assertEqual(win._board_stack.currentIndex(), 0)
        self.assertEqual(win.lbl_board_title.text(), "First wall")
        self.assertTrue(win.btn_add_card.isEnabled())
        self.assertTrue(win.lbl_board_hint.isVisible())

    def test_shelf_stays_resizable_and_never_collapses(self):
        self._board("One", strokes=1)
        win = self._window()
        self.assertFalse(win._boards_splitter.childrenCollapsible())
        win._boards_splitter.setSizes([240, 700])
        QApplication.processEvents()
        self.assertEqual(win._boards_splitter.sizes()[0], 240)
        self.assertGreaterEqual(win.boards_list.minimumWidth(), 148)

    # -------------------------------------------------------------- toolbar

    def test_mode_chips_name_their_mode_and_stay_exclusive(self):
        self._board("One", strokes=1)
        win = self._window()
        self.assertTrue(win.btn_mode_pan.isChecked())
        self.assertEqual(win.board_view.mode, "pan")
        self.assertEqual(win.btn_mode_draw.accessibleName(), "Draw mode")
        self.assertIn("sketch", win.btn_mode_draw.toolTip())

        win.btn_mode_draw.click()
        self.assertEqual(win.board_view.mode, "draw")
        self.assertTrue(win.btn_mode_draw.isChecked())
        self.assertFalse(win.btn_mode_pan.isChecked())

        win.btn_mode_link.click()
        self.assertEqual(win.board_view.mode, "link")
        self.assertTrue(win.btn_mode_link.isChecked())
        self.assertFalse(win.btn_mode_draw.isChecked())

        self.assertFalse(win.btn_board_undo.isEnabled())
        self.assertFalse(win.btn_board_redo.isEnabled())

    def test_settings_wrap_instead_of_clipping(self):
        self._board("One", strokes=1)
        win = self._window()
        for width in (1440, 760, 480):
            win.resize(width, 900)
            QApplication.processEvents()
            settings = win._board_settings
            needed = win._board_flow.heightForWidth(settings.width())
            self.assertLessEqual(needed, settings.height() + 1, f"width {width}: row clipped")
            for field in settings.findChildren(QWidget):
                if field.objectName() != "BoardToolField":
                    continue
                top = field.mapTo(settings, field.rect().topLeft()).y()
                self.assertGreaterEqual(top, -1, f"width {width}: field above the host")
                self.assertLessEqual(top + field.height(), settings.height() + 1, f"width {width}: field clipped")

    # --------------------------------------------------------------- canvas

    def test_zoom_cluster_grid_and_paper_swatch(self):
        self._board("Warm wall", strokes=1, background="#e4eadf")
        win = self._window()
        self.assertEqual(win.lbl_board_title.toolTip(), "Warm wall")
        self.assertIn("#E4EADF", win.btn_canvas_color.toolTip())
        self.assertFalse(win.btn_canvas_color.icon().isNull())

        self.assertTrue(win.chk_board_grid.isChecked())
        self.assertTrue(win.board_view.grid_visible)
        win.chk_board_grid.setChecked(False)
        self.assertFalse(win.board_view.grid_visible)

        start = win.board_view.transform().m11()
        win.btn_board_zoom_in.click()
        self.assertGreater(win.board_view.transform().m11(), start)
        win.btn_board_zoom_reset.click()
        self.assertAlmostEqual(win.board_view.transform().m11(), 1.0, places=2)
        self.assertEqual(win.btn_board_zoom_reset.text(), "100%")

        # The desk follows the theme, but the saved paper colour does not.
        self.assertEqual(win.board_view.background_color, "#e4eadf")
        self.assertNotEqual(win.board_view.desk_color, "#b7b8b8")
        self.assertTrue(win.board_view.desk_color.startswith("#"))


if __name__ == "__main__":
    unittest.main()
