import hashlib
import math
import os
import random
import re
import time

from PyQt5.QtCore import (
    QDate,
    QFileSystemWatcher,
    QPointF,
    Qt,
    QTimer,
    QUrl,
    pyqtSignal,
)
from PyQt5.QtGui import (
    QBrush,
    QColor,
    QFont,
    QIcon,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QTextCharFormat,
    QTextCursor,
)
from PyQt5.QtWebEngineWidgets import (
    QWebEnginePage as _PersonalWebEnginePage,
)
from PyQt5.QtWebEngineWidgets import (
    QWebEngineProfile,
    QWebEngineSettings,
    QWebEngineView,
)
from PyQt5.QtWidgets import (
    QButtonGroup,
    QCalendarWidget,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QGraphicsPathItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsTextItem,
    QGraphicsView,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from litebrowser.browser.browser_page import (
    BrowserPage,
    build_text_highlight_js,
    ensure_chrome_compat_script,
    ensure_text_highlight_script,
)
from litebrowser.core import app_paths, prefs
from litebrowser.services import focus_service, life_service, personal_service, tab_sets
from litebrowser.ui import components, theme, win_titlebar

MAX_NOTE_WATCH_DIRS = 64
NEURAL_GRAPH_MAX_NOTES = 48


def _is_dark_palette(p: dict) -> bool:
    """Heuristic: MAIN_BG brightness decides whether canvas art should go dark."""
    try:
        value = str(p.get("MAIN_BG", "#000000")).lstrip("#")
        r, g, b = (int(value[i:i + 2], 16) for i in (0, 2, 4))
        return (r * 299 + g * 587 + b * 114) / 1000 < 150
    except (TypeError, ValueError):
        return False


class BoardView(QGraphicsView):
    stroke_finished = pyqtSignal()
    link_created = pyqtSignal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setRenderHint(QPainter.Antialiasing, True)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setViewportUpdateMode(QGraphicsView.FullViewportUpdate)
        self.mode = "pan"
        self.pen_color = "#6f4e37"
        self.pen_width = 3.0
        self._drawing_item = None
        self._drawing_points = []
        self._link_start = None
        self.set_mode("pan")

    def wheelEvent(self, event):
        factor = 1.12 if event.angleDelta().y() > 0 else 0.88
        zoom = self.transform().m11() * factor
        if 0.35 <= zoom <= 3.5:
            self.scale(factor, factor)
        event.accept()

    def set_mode(self, mode: str):
        self.mode = mode if mode in ("pan", "draw", "link") else "pan"
        self._link_start = None
        if self.mode in ("draw", "link"):
            self.setDragMode(QGraphicsView.NoDrag)
            self.viewport().setCursor(Qt.CrossCursor)
        else:
            self.setDragMode(QGraphicsView.ScrollHandDrag)
            self.viewport().setCursor(Qt.OpenHandCursor)

    def set_pen(self, color: str, width: float):
        self.pen_color = color or "#6f4e37"
        self.pen_width = float(width or 3.0)

    def mousePressEvent(self, event):
        if self.mode == "link" and event.button() == Qt.LeftButton and self.scene():
            hit = self.itemAt(event.pos())
            card = _find_sticky_ancestor(hit)
            if card is None:
                self._clear_link_start()
                event.accept()
                return
            if self._link_start is None:
                self._link_start = card
                self._highlight_link_card(card, True)
                event.accept()
                return
            if self._link_start is card:
                self._clear_link_start()
                event.accept()
                return
            from_id = self._link_start.node.get("id")
            to_id = card.node.get("id")
            self._clear_link_start()
            self.link_created.emit(from_id, to_id)
            event.accept()
            return
        if self.mode == "draw" and event.button() == Qt.LeftButton and self.scene():
            hit = self.itemAt(event.pos())
            if _find_sticky_ancestor(hit):
                super().mousePressEvent(event)
                return
            scene_pos = self.mapToScene(event.pos())
            stroke = {
                "id": str(int(time.time() * 1000)),
                "color": self.pen_color,
                "width": float(self.pen_width),
                "points": [{"x": float(scene_pos.x()), "y": float(scene_pos.y())}],
            }
            self._drawing_item = InkStrokeItem(stroke)
            self._drawing_points = stroke["points"]
            self.scene().addItem(self._drawing_item)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.mode == "draw" and self._drawing_item and self.scene():
            scene_pos = self.mapToScene(event.pos())
            if self._drawing_points:
                last = self._drawing_points[-1]
                if abs(last["x"] - float(scene_pos.x())) < 1.5 and abs(last["y"] - float(scene_pos.y())) < 1.5:
                    event.accept()
                    return
            self._drawing_points.append({"x": float(scene_pos.x()), "y": float(scene_pos.y())})
            self._drawing_item.set_points(self._drawing_points)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self.mode == "draw" and self._drawing_item and event.button() == Qt.LeftButton:
            self._drawing_item.set_points(self._drawing_points)
            self._drawing_item = None
            self._drawing_points = []
            self.stroke_finished.emit()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def _highlight_link_card(self, card, on: bool):
        if on:
            card._orig_pen = card.pen()
            card.setPen(QPen(QColor("#e0b878"), 3))
        elif hasattr(card, "_orig_pen"):
            card.setPen(card._orig_pen)
            del card._orig_pen

    def _clear_link_start(self):
        if self._link_start is not None:
            self._highlight_link_card(self._link_start, False)
        self._link_start = None


class NeuralGraphWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(150)
        self.setMaximumHeight(180)
        self._tick = 0.0
        self._nodes: list[dict] = []
        self._total_note_count = 0
        self._subtitle = "No notes yet"
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._advance)
        self._visible = False
        self._cached_pixmap = None
        self._dirty = True

    def set_animation_running(self, run: bool):
        if run:
            if not self._timer.isActive():
                self._timer.start(50)
        else:
            self._timer.stop()
        self._visible = run

    def set_notes(self, notes: list, *, total_note_count: int | None = None):
        raw = notes or []
        self._total_note_count = int(total_note_count) if total_note_count is not None else len(raw)
        self._nodes = []
        for note in raw:
            nid = str(note.get("id") or "")
            # Deterministic layout: builtin hash() is salted per process, which
            # reshuffled the graph on every launch (v6.4 bug).
            digest = hashlib.md5(nid.encode("utf-8") or b"mei").hexdigest()
            h = int(digest[:8], 16)
            h2 = int(digest[8:16], 16)
            self._nodes.append(
                {
                    "phase": (h % 628) / 100.0,
                    "speed": 0.012 + (h % 17) / 500.0,
                    "layer": ((h >> 8) % 200) / 100.0 - 1.0,
                    "orbit": 0.25 + ((h >> 16) % 75) / 100.0,
                    "title": (note.get("title") or "")[:28],
                    "hue": (h2 % 40) - 20,
                }
            )
        if self._total_note_count == 0:
            self._subtitle = "No notes yet"
        else:
            self._subtitle = f"{self._total_note_count} notes"
        if not self._nodes:
            for idx in range(10):
                self._nodes.append(
                    {
                        "phase": random.uniform(0.0, math.pi * 2.0),
                        "speed": random.uniform(0.012, 0.03),
                        "layer": random.uniform(-0.8, 0.8),
                        "orbit": random.uniform(0.35, 0.9),
                        "title": "",
                        "hue": 0,
                    }
                )
            self._subtitle = "Add notes to populate this graph"
        self._dirty = True
        self.update()

    def _advance(self):
        self._tick += 1.0
        self._dirty = True
        self.update()

    def paintEvent(self, event):
        if not self._visible:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        # Follow the active theme instead of hardcoded cream colors that glared
        # in every dark theme (v6.4 bug).
        p = theme.palette()
        dark = _is_dark_palette(p)
        painter.fillRect(self.rect(), QColor(p["MAIN_BG_ALT"]) if dark else QColor(p["CARD_BG"]))

        w = max(1, self.width())
        h = max(1, self.height())
        cx = w * 0.5
        cy = h * 0.52
        points = []
        for index, node in enumerate(self._nodes):
            angle = node["phase"] + self._tick * node["speed"]
            depth = math.sin(angle * 0.7 + index * 0.4 + node["layer"]) * 0.5 + 0.5
            radius_x = w * (0.14 + 0.26 * node["orbit"])
            radius_y = h * (0.10 + 0.18 * node["orbit"])
            x = cx + math.cos(angle) * radius_x * (0.65 + depth * 0.6)
            y = cy + math.sin(angle * 1.35) * radius_y + (node["layer"] * 18.0)
            size = 2.5 + depth * 6.5
            points.append((x, y, size, depth, node))

        base_rgb = (140, 170, 210) if dark else (155, 109, 60)
        for idx, (x1, y1, _s1, d1, _n1) in enumerate(points):
            limit = min(idx + 4, len(points))
            for jdx in range(idx + 1, limit):
                x2, y2, _s2, d2, _n2 = points[jdx]
                alpha = int(30 + 70 * ((d1 + d2) * 0.5))
                painter.setPen(QPen(QColor(*base_rgb, alpha), 1))
                painter.drawLine(int(x1), int(y1), int(x2), int(y2))

        accent = QColor(p["ACCENT"])
        for x, y, size, depth, node in points:
            dh = int(node.get("hue") or 0)
            glow = QColor(
                max(0, min(255, accent.red() + dh)),
                max(0, min(255, accent.green() + dh // 2)),
                max(0, min(255, accent.blue())),
                int(90 + depth * 120),
            )
            painter.setPen(Qt.NoPen)
            painter.setBrush(glow)
            painter.drawEllipse(int(x - size), int(y - size), int(size * 2), int(size * 2))

        painter.setPen(QColor(p["TEXT_MUTED"]))
        painter.drawText(12, 20, "Neural Notes Graph")
        painter.drawText(12, 36, self._subtitle)
        painter.end()


class StickyCardItem(QGraphicsRectItem):
    def __init__(self, node: dict):
        super().__init__(0, 0, 220, 120)
        self.node = node
        self._edges = []
        self.setFlags(
            QGraphicsRectItem.ItemIsMovable
            | QGraphicsRectItem.ItemIsSelectable
            | QGraphicsRectItem.ItemSendsGeometryChanges
        )
        self.setBrush(QBrush(QColor(node.get("color", "#c39d63"))))
        self.setPen(QPen(QColor("#2a2119"), 2))
        self.setPos(float(node.get("x", 40)), float(node.get("y", 40)))
        text = QGraphicsTextItem(node.get("title", "Card"), self)
        text.setDefaultTextColor(QColor("#1b140f"))
        text.setTextWidth(190)
        text.setPos(14, 12)
        body = node.get("payload", "").strip()
        if body:
            body_item = QGraphicsTextItem(body[:180], self)
            body_item.setDefaultTextColor(QColor("#2d2318"))
            body_item.setTextWidth(190)
            body_item.setPos(14, 42)

    def itemChange(self, change, value):
        if change == QGraphicsRectItem.ItemPositionHasChanged:
            for edge in self._edges:
                edge.update_path()
        return super().itemChange(change, value)


class EdgeItem(QGraphicsPathItem):
    """A dashed connector between two sticky cards that follows them as they move."""

    def __init__(self, edge: dict, from_item: StickyCardItem, to_item: StickyCardItem):
        super().__init__()
        self.edge = dict(edge or {})
        self.from_item = from_item
        self.to_item = to_item
        self.setZValue(-15)  # below cards, above ink strokes
        self.setAcceptedMouseButtons(Qt.NoButton)
        color = self.edge.get("color") or "#a36a3c"
        self.setPen(QPen(QColor(color), 2, Qt.DashLine, Qt.RoundCap, Qt.RoundJoin))
        from_item._edges.append(self)
        to_item._edges.append(self)
        self.update_path()

    def update_path(self):
        start = self.from_item.mapToScene(self.from_item.rect().center())
        end = self.to_item.mapToScene(self.to_item.rect().center())
        path = QPainterPath(QPointF(start.x(), start.y()))
        path.lineTo(QPointF(end.x(), end.y()))
        self.setPath(path)


class InkStrokeItem(QGraphicsPathItem):
    def __init__(self, stroke: dict):
        super().__init__()
        self.stroke = dict(stroke or {})
        self.setZValue(-20)
        self.setAcceptedMouseButtons(Qt.NoButton)
        self.set_points(self.stroke.get("points", []))

    def set_points(self, points):
        clean_points = []
        for point in points or []:
            try:
                clean_points.append({"x": float(point.get("x", 0.0)), "y": float(point.get("y", 0.0))})
            except Exception:
                continue
        self.stroke["points"] = clean_points
        self.stroke["color"] = self.stroke.get("color") or "#6f4e37"
        self.stroke["width"] = float(self.stroke.get("width", 3.0) or 3.0)
        self.setPath(_stroke_path(clean_points))
        pen = QPen(QColor(self.stroke["color"]), self.stroke["width"], Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
        self.setPen(pen)


def _find_sticky_ancestor(item):
    current = item
    while current is not None:
        if isinstance(current, StickyCardItem):
            return current
        current = current.parentItem()
    return None


def _stroke_path(points):
    path = QPainterPath()
    if not points:
        return path
    first = points[0]
    path.moveTo(float(first["x"]), float(first["y"]))
    if len(points) == 1:
        path.lineTo(float(first["x"]) + 0.4, float(first["y"]) + 0.4)
        return path
    for point in points[1:]:
        path.lineTo(float(point["x"]), float(point["y"]))
    return path


class MeiNotesList(QListWidget):
    """Notes list with drag-to-reorder. Records the dragged note ids on the
    owner so the categories panel can move them without decoding Qt's internal
    drag mime format."""

    def __init__(self, owner, parent=None):
        super().__init__(parent)
        self._owner = owner
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDragDropMode(self.DragDropMode.InternalMove)
        self.setDefaultDropAction(Qt.MoveAction)
        self.setSelectionMode(self.SelectionMode.SingleSelection)

    def startDrag(self, supported_actions):
        self._owner._drag_note_ids = [it.data(Qt.UserRole) for it in self.selectedItems()]
        try:
            super().startDrag(supported_actions)
        finally:
            self._owner._drag_note_ids = []

    def dropEvent(self, event):
        super().dropEvent(event)
        # InternalMove just reordered the rows — persist the new arrangement.
        self._owner._persist_note_order()


class CategoryDropList(QListWidget):
    """Drop target listing note categories. Dropping a note onto a category
    moves the note's file into that category folder."""

    def __init__(self, owner, parent=None):
        super().__init__(parent)
        self._owner = owner
        self.setAcceptDrops(True)
        self.setDragDropMode(self.DragDropMode.DropOnly)
        self.setDefaultDropAction(Qt.MoveAction)

    def dropEvent(self, event):
        target_item = self.itemAt(event.pos())
        category = target_item.data(Qt.UserRole) if target_item else ""
        note_ids = list(getattr(self._owner, "_drag_note_ids", []) or [])
        if category and note_ids:
            self._owner._move_notes_to_category(note_ids, category)
            event.accept()
        else:
            # No category target or no dragged note: ignore instead of
            # accepting a silent no-op (v6.4 swallowed every drop).
            event.ignore()


class PersonalWindow(QMainWindow):
    def __init__(self, base_dir: str, app_dir: str = None, embedded: bool = False):
        super().__init__()
        self.base_dir = prefs.ensure_profile_layout(base_dir)
        self.app_dir = app_dir or app_paths.project_root()
        self.embedded = embedded
        self.current_note_id = None
        self.current_note_category = "General"
        self._note_dirty = False
        self._suppress_note_dirty = False
        self.current_board_id = None
        self._site_preview_on = False
        self._nav_collapsed = False
        self._drag_note_ids = []
        self._current_note_image_path = ""
        self._note_find_matches = []
        self.setWindowTitle("Personal Hub - Mei")
        self.setWindowIcon(QIcon(os.path.join(self.app_dir, "icon.png")))
        self.resize(1160, 760)
        self.setMinimumSize(760 if embedded else 900, 520 if embedded else 620)
        if not self.embedded:
            win_titlebar.apply_dark_titlebar(self, enabled=True)

        root = QWidget()
        root.setObjectName("PersonalWorkspace")
        self.setCentralWidget(root)
        layout = QHBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        nav = QWidget()
        nav.setObjectName("LeftRail")
        nav_layout = QVBoxLayout(nav)
        nav_layout.setContentsMargins(8, 8, 8, 10)
        nav_layout.setSpacing(5)
        self.btn_nav_toggle = QPushButton("≪")
        self.btn_nav_toggle.setCheckable(True)
        self.btn_nav_toggle.setToolTip("Collapse / expand the sidebar")
        self.btn_nav_toggle.setObjectName("NavToggle")
        nav_layout.addWidget(self.btn_nav_toggle, 0, Qt.AlignRight)
        self.nav_header = components.page_header("Personal Hub", "Your life dashboard")
        self.nav_header._cafe_page_title.setFont(components._font(16, components.WEIGHT_BOLD))
        nav_layout.addWidget(self.nav_header)
        self.nav_buttons = {}
        for key, label, glyph in (
            ("overview", "Overview", "◧"),
            ("notes", "Notes", "✎"),
            ("tasks", "Tasks", "✓"),
            ("calendar", "Calendar", "◷"),
            ("boards", "Boards", "◌"),
            ("files", "Files", "▦"),
            ("sites", "Sites", "↗"),
        ):
            button = components.nav_button(label, glyph)
            button.clicked.connect(lambda checked, item=key: self._switch_page(item))
            self.nav_buttons[key] = button
            nav_layout.addWidget(button)
        nav_layout.addStretch(1)
        self.btn_save_set = QPushButton("Save Personal session")
        self.btn_set_root = QPushButton("Set personal root")
        nav_layout.addWidget(self.btn_save_set)
        nav_layout.addWidget(self.btn_set_root)
        layout.addWidget(nav, 0)
        self.btn_nav_toggle.toggled.connect(self._toggle_nav_collapse)

        self.stack = QStackedWidget()
        layout.addWidget(self.stack, 1)
        self.page_order = {}
        for key, widget in (
            ("overview", self._build_overview_page()),
            ("notes", self._build_notes_page()),
            ("tasks", self._build_tasks_page()),
            ("calendar", self._build_calendar_page()),
            ("boards", self._build_boards_page()),
            ("files", self._build_files_page()),
            ("sites", self._build_sites_page()),
        ):
            self.page_order[key] = self.stack.count()
            self.stack.addWidget(widget)

        self.btn_set_root.clicked.connect(self._choose_root)
        self.btn_save_set.clicked.connect(self.save_current_set)
        self.setStyleSheet(theme.main_qss(prefs.get_shell_theme(self.base_dir), prefs.get_accent(self.base_dir)))
        self._switch_page("overview")
        self.refresh_all()
        self._apply_compact_layout()
        self._setup_notes_fs_watcher()

    def _setup_notes_fs_watcher(self):
        self._notes_fs_watcher = QFileSystemWatcher(self)
        self._notes_fs_watcher.directoryChanged.connect(self._on_notes_directory_changed)
        self._notes_refresh_debounce = QTimer(self)
        self._notes_refresh_debounce.setSingleShot(True)
        self._notes_refresh_debounce.setInterval(300)
        self._notes_refresh_debounce.timeout.connect(self._refresh_notes_from_fs)
        self._notes_watch_hashes = set()
        self._sync_notes_watcher_paths()

    def _get_notes_dirs_checksum(self):
        nd = personal_service.notes_dir(self.base_dir)
        hasher = hashlib.md5()
        if os.path.isdir(nd):
            for root, subdirs, _files in os.walk(nd):
                for d in sorted(subdirs):
                    hasher.update(os.path.join(root, d).encode("utf-8"))
        return hasher.hexdigest()

    def _sync_notes_watcher_paths(self):
        if not hasattr(self, "_notes_fs_watcher"):
            return
        nd = personal_service.notes_dir(self.base_dir)
        current_hash = self._get_notes_dirs_checksum()
        if current_hash in self._notes_watch_hashes:
            return
        for p in list(self._notes_fs_watcher.directories()):
            self._notes_fs_watcher.removePath(p)
        dirs_to_watch = []
        if os.path.isdir(nd):
            dirs_to_watch.append(nd)
            for root, subdirs, _files in os.walk(nd):
                for d in subdirs:
                    dirs_to_watch.append(os.path.join(root, d))
                    if len(dirs_to_watch) >= MAX_NOTE_WATCH_DIRS:
                        break
                if len(dirs_to_watch) >= MAX_NOTE_WATCH_DIRS:
                    break
        if len(dirs_to_watch) > MAX_NOTE_WATCH_DIRS:
            dirs_to_watch = [nd] if os.path.isdir(nd) else []
        for d in dirs_to_watch:
            if os.path.isdir(d):
                self._notes_fs_watcher.addPath(d)
        self._notes_watch_hashes.add(current_hash)
        if len(self._notes_watch_hashes) > 10:
            self._notes_watch_hashes = set(list(self._notes_watch_hashes)[-5:])

    def _on_notes_directory_changed(self, _path: str):
        self._notes_refresh_debounce.start()

    def _refresh_notes_from_fs(self):
        self._sync_notes_watcher_paths()
        if hasattr(self, "notes_list"):
            self._refresh_notes()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        width = max(0, self.width())
        bucket = 600 if width < 600 else 820 if width < 820 else 980 if width < 980 else 1220 if width < 1220 else 1 << 30
        if bucket != getattr(self, "_compact_bucket", None):
            self._compact_bucket = bucket
            self._apply_compact_layout()

    def _apply_compact_layout(self):
        width = max(0, self.width())
        if getattr(self, "_nav_collapsed", False):
            nav = self.findChild(QWidget, "LeftRail")
            if nav:
                nav.setMinimumWidth(46)
                nav.setMaximumWidth(46)
            for button in getattr(self, "nav_buttons", {}).values():
                button.setVisible(False)
            self.btn_save_set.setVisible(False)
            self.btn_set_root.setVisible(False)
            self.nav_header.setVisible(False)
            self.btn_nav_toggle.setVisible(True)
            return
        self.nav_header.setVisible(True)
        compact = width < 1220
        narrow = width < 980
        tiny = width < 820
        xtiny = width < 600
        nav_width = 64 if xtiny else 98 if tiny else 112 if narrow else 126 if compact else 150
        nav = self.findChild(QWidget, "LeftRail")
        if nav:
            nav.setMinimumWidth(nav_width)
            nav.setMaximumWidth(nav_width)
        self.btn_save_set.setVisible(not tiny)
        self.btn_set_root.setVisible(not tiny)
        if hasattr(self, "nav_buttons"):
            for key, button in self.nav_buttons.items():
                button.setVisible(True)
                labels = {
                    "overview": ("Overview", "◧"),
                    "notes": ("Notes", "✎"),
                    "tasks": ("Tasks", "✓"),
                    "calendar": ("Calendar", "◷"),
                    "boards": ("Boards", "◌"),
                    "files": ("Files", "▦"),
                    "sites": ("Sites", "↗"),
                }
                label, glyph = labels.get(key, (key.title(), "◇"))
                button.setText(glyph if xtiny else f"{glyph}  {label}")
                button.setMinimumHeight(22 if xtiny else 26)
                button.setMaximumHeight(24 if xtiny else 30)

    def _toggle_nav_collapse(self, checked: bool):
        self._nav_collapsed = bool(checked)
        self.btn_nav_toggle.setText("≫" if checked else "≪")
        self._apply_compact_layout()

    def _switch_page(self, key: str):
        previous = self.stack.currentIndex()
        self.stack.setCurrentIndex(self.page_order[key])
        for name, button in self.nav_buttons.items():
            button.setChecked(name == key)
        # Pause the embedded site preview when leaving the Sites tab so it
        # stops consuming CPU / network in the background; reload the cached
        # URL when returning so the user sees the same site instantly.
        self._update_site_preview_activity(key == "sites")
        if previous != self.stack.currentIndex() and key != "sites":  # #[c] keep WebEngine preview out of QWidget compositing.
            theme.animate_entrance(self.stack.currentWidget())

    def refresh_all(self):
        now = time.time()
        if hasattr(self, "_last_refresh") and (now - self._last_refresh) < 2.0:
            return
        self._last_refresh = now
        self._refresh_overview()
        self._refresh_notes()
        self._refresh_tasks()
        self._refresh_calendar()
        self._refresh_boards()
        self._refresh_files()
        self._refresh_sites()

    def _build_overview_page(self):
        w = QWidget()
        l = QVBoxLayout(w)
        l.setContentsMargins(14, 12, 14, 14)
        l.setSpacing(8)
        tool_row = QHBoxLayout()
        tool_row.addWidget(components.section_header("Life Dashboard", "Overview of your day"))
        tool_row.addStretch(1)
        l.addLayout(tool_row)

        stats_row = QHBoxLayout()
        stat_specs = (
            ("lbl_overview_tasks", "pending tasks"),
            ("lbl_overview_events", "upcoming events"),
            ("lbl_overview_boards", "boards"),
            ("lbl_overview_notes", "notes"),
            ("lbl_overview_focus", "min focus today"),
        )
        tiles = []
        for attr, label in stat_specs:
            tile = components.stat_tile("0", label)
            tiles.append(tile)
            setattr(self, attr, tile._value)
        stats_row.addWidget(components.stat_row(tiles), 1)
        l.addLayout(stats_row)

        body = QHBoxLayout()
        self.overview_focus_list = QListWidget()
        self.overview_focus_list.setObjectName("CafeList")
        self.overview_timeline_list = QListWidget()
        self.overview_timeline_list.setObjectName("CafeList")
        body.addWidget(self._wrap_list_card("Focus", "Active tasks", self.overview_focus_list), 1)
        body.addWidget(self._wrap_list_card("Upcoming", "Calendar events", self.overview_timeline_list), 1)
        l.addLayout(body, 1)
        return w

    def _wrap_list_card(self, title_text: str, subtitle: str, list_widget: QListWidget):
        card = QFrame()
        card.setObjectName("SectionCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.addWidget(components.section_header(title_text, subtitle))
        layout.addWidget(list_widget, 1)
        return card

    def _refresh_overview(self):
        snapshot = life_service.get_dashboard_snapshot(self.base_dir)
        self.lbl_overview_tasks.setText(f"{snapshot['tasks_pending']}")
        self.lbl_overview_events.setText(f"{len(snapshot['events_upcoming'])}")
        self.lbl_overview_boards.setText(f"{snapshot['boards_total']}")
        self.lbl_overview_notes.setText(f"{len(personal_service.list_notes(self.base_dir))}")
        minutes = focus_service.today_focus_seconds(self.base_dir) // 60
        self.lbl_overview_focus.setText(f"{minutes}")
        self.overview_focus_list.clear()
        for item in [task for task in life_service.load_tasks(self.base_dir) if not task.get("completed")] [:8]:
            self.overview_focus_list.addItem(f"{item.get('title', '')} · {item.get('bucket', '')}")
        if self.overview_focus_list.count() == 0:
            self.overview_focus_list.addItem("No active tasks")
        self.overview_timeline_list.clear()
        for event in life_service.load_events(self.base_dir)[:8]:
            self.overview_timeline_list.addItem(f"{event.get('title', '')} · {_format_ts(int(event.get('starts_at', 0) or 0))}")
        if self.overview_timeline_list.count() == 0:
            self.overview_timeline_list.addItem("No calendar events yet")

    def _build_notes_page(self):
        w = QWidget()
        l = QVBoxLayout(w)
        l.setContentsMargins(12, 10, 12, 12)
        l.setSpacing(6)
        l.addWidget(components.page_header("Notes", "SafeVault notes, clips, and study notes"))
        top_row = QHBoxLayout()
        self.ed_note_search = QLineEdit()
        self.ed_note_search.setPlaceholderText("Search notes in SafeVault...")
        self.btn_note_back = QPushButton("← All notes")
        self.btn_note_back.setToolTip("Return to the full, unfiltered note list")
        self.cmb_note_category = QComboBox()
        self.cmb_note_category.setEditable(True)
        self.cmb_note_category.setMinimumWidth(130)
        self.cmb_note_font = QComboBox()
        self.cmb_note_font.addItems(["12", "14", "16", "18", "20"])
        self.btn_new_note = QPushButton("New note")
        self.btn_delete_note = QPushButton("Delete")
        self.btn_save_note = QPushButton("Save")
        self.btn_note_ai = QPushButton("Ask AI")
        self.chk_neural_graph = QCheckBox("Show neural graph")
        self.chk_neural_graph.setChecked(prefs.get_show_neural_notes_graph(self.base_dir))
        self.chk_neural_graph.toggled.connect(self._on_neural_graph_toggled)
        top_row.addWidget(self.ed_note_search, 1)
        top_row.addWidget(self.btn_note_back)
        top_row.addWidget(QLabel("Category"))
        top_row.addWidget(self.cmb_note_category)
        top_row.addWidget(QLabel("Font"))
        top_row.addWidget(self.cmb_note_font)
        top_row.addWidget(self.chk_neural_graph)
        top_row.addWidget(self.btn_new_note)
        top_row.addWidget(self.btn_delete_note)
        top_row.addWidget(self.btn_save_note)
        top_row.addWidget(self.btn_note_ai)
        l.addLayout(top_row)

        # Find-within-note toolbar.
        find_row = QHBoxLayout()
        find_row.addWidget(QLabel("Tìm"))
        self.ed_note_find = QLineEdit()
        self.ed_note_find.setPlaceholderText("Tìm và tô sáng trong note...")
        self.btn_find_prev = QPushButton("‹")
        self.btn_find_prev.setToolTip("Kết quả trước")
        self.btn_find_next = QPushButton("›")
        self.btn_find_next.setToolTip("Kết quả tiếp theo")
        self.lbl_find_count = QLabel("")
        self.lbl_find_count.setObjectName("MutedLabel")
        find_row.addWidget(self.ed_note_find, 1)
        find_row.addWidget(self.btn_find_prev)
        find_row.addWidget(self.btn_find_next)
        find_row.addWidget(self.lbl_find_count)
        l.addLayout(find_row)

        split = QSplitter(Qt.Horizontal)
        left_pane = QWidget()
        left_layout = QVBoxLayout(left_pane)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(4)
        self.notes_list = MeiNotesList(self)
        self.notes_list.setObjectName("CafeList")
        self.notes_list.currentItemChanged.connect(self._load_selected_note)
        left_layout.addWidget(self.notes_list, 1)
        categories_hint = QLabel("Kéo note vào category để di chuyển")
        categories_hint.setObjectName("MutedLabel")
        categories_hint.setWordWrap(True)
        left_layout.addWidget(categories_hint)
        self.categories_list = CategoryDropList(self)
        self.categories_list.setObjectName("CafeList")
        self.categories_list.setMaximumHeight(150)
        left_layout.addWidget(self.categories_list)
        split.addWidget(left_pane)
        editor_wrap = QWidget()
        editor_layout = QVBoxLayout(editor_wrap)
        editor_layout.setContentsMargins(0, 0, 0, 0)
        self.neural_graph = NeuralGraphWidget()
        editor_layout.addWidget(self.neural_graph)
        self.lbl_note_title = QLabel("No note selected")
        self.lbl_note_title.setObjectName("MutedLabel")
        editor_layout.addWidget(self.lbl_note_title)
        self.lbl_note_image = QLabel()
        self.lbl_note_image.setAlignment(Qt.AlignCenter)
        self.lbl_note_image.hide()
        editor_layout.addWidget(self.lbl_note_image)
        self.btn_open_note_image = QPushButton("Mở ảnh")
        self.btn_open_note_image.setToolTip("Open the attached image at full size")
        self.btn_open_note_image.hide()
        editor_layout.addWidget(self.btn_open_note_image)
        self.note_editor = QPlainTextEdit()
        self.note_editor.setPlaceholderText("Longform notes, clipped notes, study notes...")
        editor_layout.addWidget(self.note_editor, 1)
        self.lbl_note_stats = QLabel("0 words · 0 characters")
        self.lbl_note_stats.setObjectName("MutedLabel")
        editor_layout.addWidget(self.lbl_note_stats)
        split.addWidget(editor_wrap)
        split.setChildrenCollapsible(True)
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)
        split.setSizes([220, 820])
        l.addWidget(split, 1)

        self.ed_note_search.textChanged.connect(self._schedule_notes_refresh)
        self.btn_note_back.clicked.connect(self._back_to_all_notes)
        self.btn_open_note_image.clicked.connect(self._open_note_image)
        self.ed_note_find.textChanged.connect(self._find_in_note)
        self.btn_find_prev.clicked.connect(self._find_prev)
        self.btn_find_next.clicked.connect(self._find_next)
        self.cmb_note_category.currentTextChanged.connect(lambda _value: self._refresh_notes())
        self.cmb_note_font.currentTextChanged.connect(self._apply_note_font_size)
        self.btn_new_note.clicked.connect(self._create_note)
        self.btn_delete_note.clicked.connect(self._delete_note)
        self.btn_save_note.clicked.connect(self._save_note)
        self.btn_note_ai.clicked.connect(self._ask_ai_about_note)
        self.note_editor.textChanged.connect(self._on_note_text_changed)
        self._note_idle_timer = QTimer(self)
        self._note_idle_timer.setSingleShot(True)
        self._note_idle_timer.setInterval(250)
        self._note_idle_timer.timeout.connect(self._on_note_edit_idle)
        self._notes_search_timer = QTimer(self)
        self._notes_search_timer.setSingleShot(True)
        self._notes_search_timer.setInterval(250)
        self._notes_search_timer.timeout.connect(self._refresh_notes)
        if not self.embedded:
            self.btn_note_ai.hide()
        self._apply_neural_graph_visibility()
        return w

    def _schedule_notes_refresh(self):
        """Debounce list rebuilds so typing in the search box stays smooth."""
        self._notes_search_timer.start()

    def _on_neural_graph_toggled(self, checked: bool):
        prefs.set_show_neural_notes_graph(self.base_dir, checked)
        self._apply_neural_graph_visibility()
        if checked and hasattr(self, "notes_list"):
            all_notes = personal_service.list_notes(self.base_dir, "")
            self.neural_graph.set_notes(all_notes[:NEURAL_GRAPH_MAX_NOTES], total_note_count=len(all_notes))

    def _apply_neural_graph_visibility(self):
        if not hasattr(self, "neural_graph") or not hasattr(self, "chk_neural_graph"):
            return
        on = self.chk_neural_graph.isChecked()
        self.neural_graph.setVisible(on)
        if on:
            self.neural_graph.setMinimumHeight(120)
            self.neural_graph.setMaximumHeight(150)
            self.neural_graph.set_animation_running(True)
        else:
            self.neural_graph.setMinimumHeight(0)
            self.neural_graph.setMaximumHeight(0)
            self.neural_graph.set_animation_running(False)

    def _apply_note_font_size(self):
        font = self.note_editor.font()
        font.setPointSize(int(self.cmb_note_font.currentText()))
        self.note_editor.setFont(font)

    def _on_note_text_changed(self):
        self._update_note_stats()
        if self._suppress_note_dirty:
            return
        self._note_dirty = True
        self._note_idle_timer.start()

    def _on_note_edit_idle(self):
        """Autosave debounced: persist edits 250 ms after typing stops."""
        if not self._note_dirty or not self.current_note_id:
            return
        note_id = self.current_note_id
        if personal_service.save_note(self.base_dir, note_id, self.note_editor.toPlainText()):
            self._note_dirty = False
        # Find highlights were computed against the old text; offsets are now
        # stale (v6.4 jumped to wrong spans). Recompute on the edited content.
        self._find_in_note()

    def _update_note_stats(self):
        if not hasattr(self, "lbl_note_stats"):
            return
        text = self.note_editor.toPlainText()
        # Avoid building a full word list on every keystroke for large notes.
        word_count = sum(1 for _ in re.finditer(r"\S+", text))
        self.lbl_note_stats.setText("%d words · %d characters" % (word_count, len(text)))

    def _refresh_notes(self):
        query = self.ed_note_search.text().strip() if hasattr(self, "ed_note_search") else ""
        selected_category = self.cmb_note_category.currentText().strip() if hasattr(self, "cmb_note_category") else ""
        self._refresh_note_categories(keep_value=selected_category)
        # Flush pending edits BEFORE touching the list: list.clear() fires
        # currentItemChanged(None) which used to blank the editor and wipe
        # unsaved edits on every search keystroke (v6.4 data-loss bug).
        self._on_note_edit_idle()
        keep_selection = self.current_note_id
        self._suppress_note_dirty = True
        try:
            self.notes_list.clear()
        finally:
            self._suppress_note_dirty = False
        notes = []
        for note in personal_service.list_notes(self.base_dir, query):
            if selected_category and selected_category.lower() != "all" and note.get("category", "").lower() != selected_category.lower():
                continue
            notes.append(note)
        # Honour the user's drag-and-drop arrangement; unknown ids keep their
        # natural (most-recent-first) order at the end.
        order = prefs.get_note_order(self.base_dir)
        if order:
            rank = {nid: idx for idx, nid in enumerate(order)}
            notes.sort(key=lambda n: rank.get(n["id"], len(order)))
        restored = None
        for note in notes:
            item = QListWidgetItem(f"[{note.get('category', 'General')}] {note['title']}")
            item.setToolTip(note["snippet"])
            item.setData(Qt.UserRole, note["id"])
            self.notes_list.addItem(item)
            if keep_selection and note["id"] == keep_selection:
                restored = item
        # Keep the note that was open selected across filter changes; with
        # signals blocked the editor is left untouched (no wipe, no scroll jump).
        if restored is not None:
            self.notes_list.blockSignals(True)
            try:
                self.notes_list.setCurrentItem(restored)
            finally:
                self.notes_list.blockSignals(False)
            self.current_note_id = keep_selection
        if hasattr(self, "neural_graph") and getattr(self, "chk_neural_graph", None) and self.chk_neural_graph.isChecked():
            all_notes = personal_service.list_notes(self.base_dir, "")
            self.neural_graph.set_notes(all_notes[:NEURAL_GRAPH_MAX_NOTES], total_note_count=len(all_notes))
        # Empty state: a muted hint row (disabled, unselectable) instead of a
        # blank list when the search/filter matches nothing.
        if self.notes_list.count() == 0:
            hint = QListWidgetItem("No notes match — press New note to start")
            hint.setFlags(Qt.NoItemFlags)
            self.notes_list.addItem(hint)
        if hasattr(self, "_notes_fs_watcher"):
            now = time.time()
            if not hasattr(self, "_last_watcher_sync") or (now - self._last_watcher_sync) > 5.0:
                self._last_watcher_sync = now
                self._sync_notes_watcher_paths()

    def _refresh_note_categories(self, keep_value: str = ""):
        if not hasattr(self, "cmb_note_category"):
            return
        current = keep_value or self.cmb_note_category.currentText().strip() or "All"
        self.cmb_note_category.blockSignals(True)
        self.cmb_note_category.clear()
        self.cmb_note_category.addItem("All")
        for category in personal_service.list_note_categories(self.base_dir):
            self.cmb_note_category.addItem(category)
        idx = self.cmb_note_category.findText(current)
        if idx >= 0:
            self.cmb_note_category.setCurrentIndex(idx)
        else:
            self.cmb_note_category.setEditText(current)
        self.cmb_note_category.blockSignals(False)
        # Refresh the drag-and-drop category target list.
        if hasattr(self, "categories_list"):
            self.categories_list.blockSignals(True)
            self.categories_list.clear()
            for category in personal_service.list_note_categories(self.base_dir):
                drop_item = QListWidgetItem(category)
                drop_item.setData(Qt.UserRole, category)
                self.categories_list.addItem(drop_item)
            self.categories_list.blockSignals(False)

    def _create_note(self):
        title, ok = QInputDialog.getText(self, "Create note", "Note title:")
        if not ok or not (title or "").strip():
            return
        category = (self.cmb_note_category.currentText().strip() or "General")
        if category.lower() == "all":
            category = "General"
        note = personal_service.create_note(self.base_dir, title.strip(), "# " + title.strip() + "\n\n", category=category)
        # New notes appear at the top of the manual order.
        order = [nid for nid in prefs.get_note_order(self.base_dir) if nid != note["id"]]
        prefs.set_note_order(self.base_dir, [note["id"]] + order)
        self._refresh_notes()
        self.select_note(note["id"])

    def select_note(self, note_id: str):
        if not note_id:
            return
        for index in range(self.notes_list.count()):
            item = self.notes_list.item(index)
            if item.data(Qt.UserRole) == note_id:
                if self.notes_list.currentItem() is item:
                    return  # already selected; re-selecting would reset the editor
                self.notes_list.setCurrentItem(item)
                self._switch_page("notes")
                break

    def _load_selected_note(self, current, _previous):
        if not current:
            # Mid-refresh the list clear is spurious: _refresh_notes re-selects
            # the open note afterwards, so keep the editor untouched here.
            if self._suppress_note_dirty:
                return
            self.current_note_id = None
            self.current_note_category = "General"
            self.lbl_note_title.setText("No note selected")
            self.note_editor.setPlainText("")
            self._clear_note_attachments()
            self._find_in_note()
            return
        note = personal_service.read_note(self.base_dir, current.data(Qt.UserRole))
        if not note:
            return
        self.current_note_id = note["id"]
        self.current_note_category = note.get("category") or "General"
        self._note_dirty = False
        self._suppress_note_dirty = True
        try:
            prev_content = self.note_editor.toPlainText()
            if note["content"] != prev_content:
                self.note_editor.setPlainText(note["content"])
                self._render_note_attachments(note["content"])
        finally:
            self._suppress_note_dirty = False
        # The category combo is a *filter* only. Do not change it here, or the
        # note's own category would leak into the filter and hide every other note.
        self.lbl_note_title.setText(f"{note['title']}  |  {self.current_note_category}")
        self._find_in_note()

    def _back_to_all_notes(self):
        """Return to the full note list: clear any category filter + selection."""
        self.cmb_note_category.blockSignals(True)
        self.cmb_note_category.setCurrentIndex(0)  # "All"
        self.cmb_note_category.blockSignals(False)
        self.notes_list.clearSelection()
        self.notes_list.setCurrentItem(None)  # resets the editor via currentItemChanged
        self._refresh_notes()

    def _first_note_image_path(self, content: str) -> str:
        """Find the first image referenced by a note (Attachment: or ![..](..))."""
        candidates: list[str] = []
        for line in (content or "").splitlines():
            stripped = line.strip()
            if stripped.lower().startswith("attachment:"):
                candidates.append(stripped.split(":", 1)[1].strip())
            for match in re.finditer(r"!\[[^\]]*\]\(([^)]+)\)", stripped):
                candidates.append(match.group(1).strip())
        vault = prefs.vault_path(self.base_dir)
        image_exts = (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp")
        for raw in candidates:
            raw = (raw or "").strip().strip("\"'<>")
            if not raw:
                continue
            resolved = raw if os.path.isabs(raw) else os.path.join(vault, raw.replace("/", os.sep))
            if os.path.isfile(resolved) and resolved.lower().endswith(image_exts):
                return resolved
        return ""

    def _render_note_attachments(self, content: str):
        self._clear_note_attachments()
        path = self._first_note_image_path(content or "")
        if not path:
            return
        try:
            pixmap = QPixmap(path)
            if pixmap.isNull():
                return
            max_w, max_h = 460, 260
            if pixmap.width() > max_w or pixmap.height() > max_h:
                pixmap = pixmap.scaled(max_w, max_h, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self.lbl_note_image.setPixmap(pixmap)
            self.lbl_note_image.show()
            self._current_note_image_path = path
            self.btn_open_note_image.show()
        except Exception:
            self._clear_note_attachments()

    def _clear_note_attachments(self):
        self._current_note_image_path = ""
        if hasattr(self, "lbl_note_image"):
            self.lbl_note_image.clear()
            self.lbl_note_image.hide()
        if hasattr(self, "btn_open_note_image"):
            self.btn_open_note_image.hide()

    def _open_note_image(self):
        path = getattr(self, "_current_note_image_path", "")
        if path and os.path.isfile(path):
            try:
                os.startfile(path)
            except Exception:
                QMessageBox.information(self, "Notes", "Cannot open:\n" + str(path))

    def _find_in_note(self):
        """Highlight every match of the find query in the current note."""
        self._note_find_matches = []
        if not hasattr(self, "ed_note_find"):
            return
        query = self.ed_note_find.text().strip()
        selections = []
        if query and self.current_note_id:
            text = self.note_editor.toPlainText()
            lowered = text.lower()
            needle = query.lower()
            doc = self.note_editor.document()
            pos = 0
            while True:
                idx = lowered.find(needle, pos)
                if idx < 0:
                    break
                extra = QTextEdit.ExtraSelection()
                cursor = QTextCursor(doc)
                cursor.setPosition(idx)
                cursor.setPosition(idx + len(query), QTextCursor.KeepAnchor)
                extra.cursor = cursor
                extra.format.setBackground(QColor("#f2d16b"))
                extra.format.setForeground(QColor("#1b140f"))
                selections.append(extra)
                self._note_find_matches.append(idx)
                pos = idx + len(query)
        self.note_editor.setExtraSelections(selections)
        if not hasattr(self, "lbl_find_count"):
            return
        if not query:
            self.lbl_find_count.setText("")
        elif self._note_find_matches:
            self.lbl_find_count.setText(f"{len(self._note_find_matches)} kết quả")
        else:
            self.lbl_find_count.setText("Không tìm thấy")

    def _find_note_step(self, direction):
        matches = getattr(self, "_note_find_matches", [])
        if not matches:
            return
        query = self.ed_note_find.text()
        if not query:
            return
        doc = self.note_editor.document()
        current = self.note_editor.textCursor().selectionStart()
        target = -1
        if direction > 0:
            for match in matches:
                if match > current:
                    target = match
                    break
            if target < 0:
                target = matches[0]
        else:
            for match in reversed(matches):
                if match < current:
                    target = match
                    break
            if target < 0:
                target = matches[-1]
        cursor = QTextCursor(doc)
        cursor.setPosition(target)
        cursor.setPosition(target + len(query), QTextCursor.KeepAnchor)
        self.note_editor.setTextCursor(cursor)
        self.note_editor.centerCursor()

    def _find_next(self):
        self._find_note_step(1)

    def _find_prev(self):
        self._find_note_step(-1)

    def _persist_note_order(self):
        order = []
        for index in range(self.notes_list.count()):
            item = self.notes_list.item(index)
            if item is None:
                continue
            note_id = item.data(Qt.UserRole)
            if note_id:
                order.append(str(note_id))
        prefs.set_note_order(self.base_dir, order)

    def _move_notes_to_category(self, note_ids, category):
        # Flush unsaved edits first: moving rewrites the file under a new id,
        # and pending editor text would otherwise be lost (v6.4 bug).
        self._on_note_edit_idle()
        moved = 0
        open_moved = None
        for note_id in note_ids:
            note = personal_service.read_note(self.base_dir, note_id)
            if not note:
                continue
            result = personal_service.update_note(self.base_dir, note_id, note["content"], category=category)
            if result:
                moved += 1
                if note_id == self.current_note_id:
                    open_moved = result
        # update_note relocates the file, which changes the note id; the open
        # note must follow or later saves would fail silently.
        if open_moved is not None:
            self.current_note_id = open_moved["id"]
            self.current_note_category = open_moved.get("category") or category
        self._refresh_notes()
        if self.current_note_id:
            self.select_note(self.current_note_id)
        self._refresh_overview()
        if moved:
            self.lbl_note_title.setText(f"Đã chuyển {moved} note vào {category}")
        else:
            self.lbl_note_title.setText("Không chuyển được note")

    def _save_note(self):
        if not self.current_note_id:
            QMessageBox.information(self, "Notes", "Select a note first.")
            return
        # Preserve the note's own category on save; the combo is only a filter.
        category = self.current_note_category or "General"
        note = personal_service.update_note(self.base_dir, self.current_note_id, self.note_editor.toPlainText(), category=category)
        if not note:
            QMessageBox.warning(self, "Notes", "Could not save this note.")
            return
        self.current_note_id = note["id"]
        self.current_note_category = note.get("category") or "General"
        self._note_dirty = False
        self._refresh_notes()
        self.select_note(self.current_note_id)
        self._refresh_overview()

    def _ask_ai_about_note(self):
        if not self.current_note_id:
            QMessageBox.information(self, "AI", "Select a note first.")
            return
        shell = self._host_shell()
        if not shell or not hasattr(shell, "ai_page"):
            QMessageBox.information(self, "AI", "Open Personal Hub inside the main shell to use the assistant.")
            return
        title = self.lbl_note_title.text().strip() or "Current note"
        body = self.note_editor.toPlainText().strip()
        question = f"Summarize and improve this note: {title}"
        shell.ed_ai_quick.setText(question)
        shell.ai_page.ask_with_context(question, "Current note", f"Title: {title}\n\n{body[:3000]}")
        shell.switch_workspace("ai")

    def _delete_note(self):
        if not self.current_note_id:
            return
        deleted_id = self.current_note_id
        confirm = QMessageBox.question(
            self,
            "Delete note",
            "Delete this note permanently?\n\n" + (self.lbl_note_title.text() or deleted_id),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return
        personal_service.delete_note(self.base_dir, deleted_id)
        prefs.set_note_order(self.base_dir, [nid for nid in prefs.get_note_order(self.base_dir) if nid != deleted_id])
        self.current_note_id = None
        self._note_dirty = False
        self.note_editor.setPlainText("")
        self.lbl_note_title.setText("No note selected")
        self._clear_note_attachments()
        self._find_in_note()
        self._refresh_notes()
        self._refresh_overview()

    def _build_tasks_page(self):
        w = QWidget()
        l = QVBoxLayout(w)
        l.setContentsMargins(12, 10, 12, 12)
        l.setSpacing(6)
        l.addWidget(components.page_header("Tasks", "Across personal, work, and study"))
        top_row = QHBoxLayout()
        self.ed_task_title = QLineEdit()
        self.ed_task_title.setPlaceholderText("New task...")
        self.cmb_task_bucket = QComboBox()
        self.cmb_task_bucket.addItems(["personal", "work", "study"])
        self.btn_add_task = QPushButton("Add task")
        self.btn_toggle_task = QPushButton("Toggle done")
        self.btn_remove_task = QPushButton("Delete")
        top_row.addWidget(self.ed_task_title, 1)
        top_row.addWidget(self.cmb_task_bucket)
        top_row.addWidget(self.btn_add_task)
        top_row.addWidget(self.btn_toggle_task)
        top_row.addWidget(self.btn_remove_task)
        l.addLayout(top_row)
        self.tasks_list = QListWidget()
        self.tasks_list.setObjectName("CafeList")
        l.addWidget(self.tasks_list, 1)
        self.btn_add_task.clicked.connect(self._add_task)
        self.btn_toggle_task.clicked.connect(self._toggle_task)
        self.btn_remove_task.clicked.connect(self._remove_task)
        return w

    def _refresh_tasks(self):
        self.tasks_list.clear()
        for item in life_service.load_tasks(self.base_dir):
            prefix = "[x]" if item.get("completed") else "[ ]"
            due = _format_ts(int(item.get("due_at", 0) or 0)) if int(item.get("due_at", 0) or 0) else item.get("bucket", "")
            row = QListWidgetItem(f"{prefix} {item.get('title', '')} · {due}")
            row.setData(Qt.UserRole, item.get("id", ""))
            self.tasks_list.addItem(row)
        if self.tasks_list.count() == 0:
            hint = QListWidgetItem("No tasks yet — type a title above and press Add task")
            hint.setFlags(Qt.NoItemFlags)
            self.tasks_list.addItem(hint)

    def _add_task(self):
        title = self.ed_task_title.text().strip()
        if not title:
            return
        life_service.add_task(self.base_dir, title, bucket=self.cmb_task_bucket.currentText())
        self.ed_task_title.clear()
        self._refresh_tasks()
        self._refresh_overview()

    def _toggle_task(self):
        item = self.tasks_list.currentItem()
        if item and item.data(Qt.UserRole):
            life_service.toggle_task(self.base_dir, item.data(Qt.UserRole))
            self._refresh_tasks()
            self._refresh_overview()

    def _remove_task(self):
        item = self.tasks_list.currentItem()
        if item and item.data(Qt.UserRole):
            life_service.remove_task(self.base_dir, item.data(Qt.UserRole))
            self._refresh_tasks()
            self._refresh_overview()

    def _build_calendar_page(self):
        w = QWidget()
        l = QVBoxLayout(w)
        l.setContentsMargins(12, 10, 12, 12)
        l.setSpacing(6)
        l.addWidget(components.page_header("Calendar", "Events and your day view"))
        row = QHBoxLayout()
        self.btn_add_event = QPushButton("Add event")
        self.btn_remove_event = QPushButton("Delete")
        self.btn_today = QPushButton("Today")
        row.addWidget(self.btn_add_event)
        row.addWidget(self.btn_remove_event)
        row.addWidget(self.btn_today)
        row.addStretch(1)
        l.addLayout(row)
        body = QHBoxLayout()
        body.setSpacing(6)
        left_card = QFrame()
        left_card.setObjectName("SectionCard")
        left_layout = QVBoxLayout(left_card)
        left_layout.setContentsMargins(10, 10, 10, 10)
        left_layout.setSpacing(6)
        self.calendar_widget = QCalendarWidget()
        self.calendar_widget.setGridVisible(False)
        self.calendar_widget.setVerticalHeaderFormat(QCalendarWidget.NoVerticalHeader)
        self.calendar_widget.setSelectedDate(QDate.currentDate())
        left_layout.addWidget(self.calendar_widget)
        self.lbl_calendar_hint = QLabel("")
        self.lbl_calendar_hint.setWordWrap(True)
        self.lbl_calendar_hint.setObjectName("MutedLabel")
        left_layout.addWidget(self.lbl_calendar_hint)
        body.addWidget(left_card, 1)

        right_col = QVBoxLayout()
        right_col.setSpacing(6)
        self.lbl_calendar_day = QLabel("")
        self.lbl_calendar_day.setFont(QFont("Georgia", 15, QFont.Bold))
        right_col.addWidget(self.lbl_calendar_day)

        self.day_events_list = QListWidget()
        self.day_events_list.setObjectName("CafeList")
        right_col.addWidget(self._wrap_list_card("Events on selected day", "Click a date to see its events", self.day_events_list), 1)

        self.calendar_list = QListWidget()
        self.calendar_list.setObjectName("CafeList")
        right_col.addWidget(self._wrap_list_card("Upcoming", "Across all events", self.calendar_list), 1)
        body.addLayout(right_col, 1)
        l.addLayout(body, 1)
        self.btn_add_event.clicked.connect(self._add_event)
        self.btn_remove_event.clicked.connect(self._remove_event)
        self.btn_today.clicked.connect(self._jump_calendar_today)
        self.calendar_widget.selectionChanged.connect(self._refresh_calendar)
        return w

    def _refresh_calendar(self):
        events = life_service.load_events(self.base_dir)
        selected_date = self.calendar_widget.selectedDate() if hasattr(self, "calendar_widget") else QDate.currentDate()
        selected_key = selected_date.toString("yyyy-MM-dd")
        events_by_day = {}
        for item in events:
            ts = int(item.get("starts_at", 0) or 0)
            date_key = time.strftime("%Y-%m-%d", time.localtime(ts)) if ts else ""
            if not date_key:
                continue
            events_by_day.setdefault(date_key, []).append(item)

        if hasattr(self, "calendar_widget"):
            for date_key in getattr(self, "_calendar_marked_dates", set()):
                year, month, day = [int(part) for part in date_key.split("-")]
                self.calendar_widget.setDateTextFormat(QDate(year, month, day), QTextCharFormat())
            accent_fmt = QTextCharFormat()
            accent_fmt.setBackground(QColor("#d8bf95"))
            accent_fmt.setForeground(QColor("#2d2118"))
            accent_fmt.setFontWeight(QFont.DemiBold)
            for date_key in events_by_day:
                year, month, day = [int(part) for part in date_key.split("-")]
                self.calendar_widget.setDateTextFormat(QDate(year, month, day), accent_fmt)
            self._calendar_marked_dates = set(events_by_day.keys())

        day_items = events_by_day.get(selected_key, [])
        self.lbl_calendar_day.setText(selected_date.toString("dddd, MMMM d"))
        if day_items:
            self.lbl_calendar_hint.setText(f"{len(day_items)} event(s) on this day")
        else:
            self.lbl_calendar_hint.setText("No events on this day yet. Use Add event to place one on the selected date.")

        self.day_events_list.clear()
        for item in day_items:
            label = time.strftime("%H:%M", time.localtime(int(item.get("starts_at", 0) or 0)))
            row = QListWidgetItem(f"{label}  {item.get('title', '')}")
            row.setData(Qt.UserRole, item.get("id", ""))
            self.day_events_list.addItem(row)
        if self.day_events_list.count() == 0:
            placeholder = QListWidgetItem("No events scheduled")
            placeholder.setFlags(Qt.NoItemFlags)
            self.day_events_list.addItem(placeholder)
        self.calendar_list.clear()
        for item in events[:20]:
            row = QListWidgetItem(f"{item.get('title', '')} · {_format_ts(int(item.get('starts_at', 0) or 0))}")
            row.setData(Qt.UserRole, item.get("id", ""))
            self.calendar_list.addItem(row)

    def _add_event(self):
        title, ok = QInputDialog.getText(self, "Add event", "Event title:")
        if not ok or not (title or "").strip():
            return
        selected_date = self.calendar_widget.selectedDate() if hasattr(self, "calendar_widget") else QDate.currentDate()
        default_start = f"{selected_date.toString('yyyy-MM-dd')} 09:00"
        starts_at_text, ok = QInputDialog.getText(self, "Add event", "Start time (YYYY-MM-DD HH:MM):", text=default_start)
        if not ok:
            return
        try:
            starts_at = int(time.mktime(time.strptime(starts_at_text.strip(), "%Y-%m-%d %H:%M")))
        except Exception:
            QMessageBox.warning(self, "Calendar", "Invalid date format.")
            return
        life_service.add_event(self.base_dir, title.strip(), starts_at)
        self._refresh_calendar()
        self._refresh_overview()

    def _remove_event(self):
        item = self.day_events_list.currentItem() if hasattr(self, "day_events_list") else None
        if not item or not item.data(Qt.UserRole):
            item = self.calendar_list.currentItem()
        if not item or not item.data(Qt.UserRole):
            return
        if QMessageBox.question(self, "Calendar", "Delete this event?", QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return
        life_service.remove_event(self.base_dir, item.data(Qt.UserRole))
        self._refresh_calendar()
        self._refresh_overview()

    def _jump_calendar_today(self):
        self.calendar_widget.setSelectedDate(QDate.currentDate())
        self._refresh_calendar()

    def select_event(self, event_id: str):
        for event in life_service.load_events(self.base_dir):
            if event.get("id") != event_id:
                continue
            ts = int(event.get("starts_at", 0) or 0)
            if ts:
                dt = time.localtime(ts)
                self.calendar_widget.setSelectedDate(QDate(dt.tm_year, dt.tm_mon, dt.tm_mday))
            self._refresh_calendar()
            for widget in (self.day_events_list, self.calendar_list):
                for index in range(widget.count()):
                    item = widget.item(index)
                    if item.data(Qt.UserRole) == event_id:
                        widget.setCurrentItem(item)
                        return

    def _build_boards_page(self):
        w = QWidget()
        l = QVBoxLayout(w)
        l.setContentsMargins(12, 10, 12, 12)
        l.setSpacing(6)
        l.addWidget(components.page_header("Idea Boards", "Sticky cards, pan, and draw"))
        row = QHBoxLayout()
        self.btn_add_board = QPushButton("New board")
        self.btn_delete_board = QPushButton("Delete board")
        self.btn_add_card = QPushButton("Add sticky")
        self.btn_mode_pan = QPushButton("Pan")
        self.btn_mode_draw = QPushButton("Draw")
        self.btn_mode_link = QPushButton("Link")
        self.cmb_pen_color = QComboBox()
        self.cmb_pen_color.addItem("Espresso", "#6f4e37")
        self.cmb_pen_color.addItem("Caramel", "#a36a3c")
        self.cmb_pen_color.addItem("Forest", "#50624a")
        self.cmb_pen_color.addItem("Ink", "#2e2b28")
        self.cmb_pen_color.addItem("Chalk", "#e8dcc8")
        self.cmb_pen_width = QComboBox()
        self.cmb_pen_width.addItem("Fine", 2.0)
        self.cmb_pen_width.addItem("Medium", 4.0)
        self.cmb_pen_width.addItem("Bold", 6.0)
        self.btn_clear_ink = QPushButton("Clear ink")
        self.btn_clear_links = QPushButton("Clear links")
        self.btn_save_board = QPushButton("Save board")
        self.btn_mode_pan.setCheckable(True)
        self.btn_mode_draw.setCheckable(True)
        self.btn_mode_link.setCheckable(True)
        self.board_mode_group = QButtonGroup(self)
        self.board_mode_group.setExclusive(True)
        self.board_mode_group.addButton(self.btn_mode_pan)
        self.board_mode_group.addButton(self.btn_mode_draw)
        self.board_mode_group.addButton(self.btn_mode_link)
        row.addWidget(self.btn_add_board)
        row.addWidget(self.btn_delete_board)
        row.addWidget(self.btn_add_card)
        row.addWidget(self.btn_mode_pan)
        row.addWidget(self.btn_mode_draw)
        row.addWidget(self.btn_mode_link)
        row.addWidget(self.cmb_pen_color)
        row.addWidget(self.cmb_pen_width)
        row.addWidget(self.btn_clear_ink)
        row.addWidget(self.btn_clear_links)
        row.addWidget(self.btn_save_board)
        row.addStretch(1)
        l.addLayout(row)
        self.lbl_board_hint = QLabel("Keep it simple: pan the canvas, drop sticky cards, or switch to Draw to sketch directly.")
        self.lbl_board_hint.setObjectName("MutedLabel")
        l.addWidget(self.lbl_board_hint)

        split = QSplitter(Qt.Horizontal)
        self.boards_list = QListWidget()
        self.boards_list.setObjectName("CafeList")
        self.boards_list.currentItemChanged.connect(self._load_selected_board)
        split.addWidget(self.boards_list)
        self.board_scene = QGraphicsScene(self)
        self.board_scene.setSceneRect(0, 0, 2200, 1400)
        # Board canvas follows the active theme (v6.4: fixed cream background).
        _p = theme.palette()
        self.board_scene.setBackgroundBrush(QBrush(QColor(_p["CARD_BG"] if not _is_dark_palette(_p) else _p["MAIN_BG_ALT"])))
        self.board_view = BoardView()
        self.board_view.setScene(self.board_scene)
        self._board_autosave = QTimer(self)
        self._board_autosave.setSingleShot(True)
        self._board_autosave.setInterval(700)
        self._board_autosave.timeout.connect(lambda: self._save_current_board_positions(notify=False))
        self.board_view.stroke_finished.connect(self._board_autosave.start)
        split.addWidget(self.board_view)
        split.setChildrenCollapsible(True)
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)
        split.setSizes([200, 860])
        l.addWidget(split, 1)

        self.btn_add_board.clicked.connect(self._add_board)
        self.btn_delete_board.clicked.connect(self._delete_board)
        self.btn_add_card.clicked.connect(self._add_board_card)
        self.btn_mode_pan.clicked.connect(lambda: self._set_board_mode("pan"))
        self.btn_mode_draw.clicked.connect(lambda: self._set_board_mode("draw"))
        self.btn_mode_link.clicked.connect(lambda: self._set_board_mode("link"))
        self.cmb_pen_color.currentIndexChanged.connect(self._apply_board_pen)
        self.cmb_pen_width.currentIndexChanged.connect(self._apply_board_pen)
        self.btn_clear_ink.clicked.connect(self._clear_board_ink)
        self.btn_clear_links.clicked.connect(self._clear_board_links)
        self.board_view.link_created.connect(self._add_board_edge)
        self.btn_save_board.clicked.connect(self._save_current_board_positions)
        self.btn_mode_pan.setChecked(True)
        self._apply_board_pen()
        return w

    def _refresh_boards(self):
        boards = life_service.load_boards(self.base_dir)
        current = self.current_board_id
        self.boards_list.clear()
        for board in boards:
            item = QListWidgetItem(board.get("title", "Untitled board"))
            item.setData(Qt.UserRole, board.get("id", ""))
            self.boards_list.addItem(item)
        if current:
            self.open_life_item("board", current)
        elif self.boards_list.count() > 0 and self.boards_list.currentRow() < 0:
            self.boards_list.setCurrentRow(0)
        else:
            self.board_scene.clear()

    def _add_board(self):
        title, ok = QInputDialog.getText(self, "New board", "Board title:")
        if not ok:
            return
        board = life_service.add_board(self.base_dir, title.strip() or "Idea board")
        self.current_board_id = board["id"]
        self._refresh_boards()
        self._refresh_overview()

    def _delete_board(self):
        if not self.current_board_id:
            return
        confirm = QMessageBox.question(
            self,
            "Delete board",
            "Delete this board with all its cards, strokes and links?\nThis cannot be undone.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return
        life_service.remove_board(self.base_dir, self.current_board_id)
        self.current_board_id = None
        self._refresh_boards()
        self._refresh_overview()

    def _load_selected_board(self, current, _previous):
        previous_board_id = self.current_board_id
        if previous_board_id:
            self._save_current_board_positions(notify=False)
        # Cancel any pending autosave: it must not fire against the *new*
        # board after a quick switch (v6.4 saved the wrong board's positions).
        self._board_autosave.stop()
        self.board_scene.clear()
        self.current_board_id = current.data(Qt.UserRole) if current else None
        if not self.current_board_id:
            self.lbl_board_hint.setText("Create a board to start sketching ideas, tasks, or study maps.")
            return
        boards = life_service.load_boards(self.base_dir)
        for board in boards:
            if board.get("id") == self.current_board_id:
                card_by_id = {}
                for node in board.get("nodes", []):
                    item = StickyCardItem(node)
                    card_by_id[node.get("id")] = item
                    self.board_scene.addItem(item)
                for stroke in board.get("strokes", []):
                    self.board_scene.addItem(InkStrokeItem(stroke))
                for edge in board.get("edges", []):
                    from_item = card_by_id.get(edge.get("from"))
                    to_item = card_by_id.get(edge.get("to"))
                    if from_item and to_item:
                        self.board_scene.addItem(EdgeItem(edge, from_item, to_item))
                self.lbl_board_hint.setText(
                    f"{len(board.get('nodes', []))} sticky cards · {len(board.get('edges', []))} links · {len(board.get('strokes', []))} ink strokes"
                )
                break

    def _add_board_card(self):
        if not self.current_board_id:
            QMessageBox.information(self, "Boards", "Create or select a board first.")
            return
        title, ok = QInputDialog.getText(self, "New sticky", "Card title:")
        if not ok:
            return
        life_service.add_board_node(self.base_dir, self.current_board_id, title or "Card", payload="Idea, note, or task link")
        # Force the scene rebuild even if the board was already the current
        # item (re-selecting it fires no currentItemChanged, v6.4 bug).
        self._load_selected_board(self.boards_list.currentItem(), None)
        self._refresh_overview()

    def _set_board_mode(self, mode: str):
        self.board_view.set_mode(mode)
        self.btn_mode_pan.setChecked(mode == "pan")
        self.btn_mode_draw.setChecked(mode == "draw")
        self.btn_mode_link.setChecked(mode == "link")
        if mode == "draw":
            self.lbl_board_hint.setText("Draw mode is on. Drag on empty canvas to sketch. Sticky cards remain draggable.")
        elif mode == "link":
            self.lbl_board_hint.setText("Link mode: click a sticky card, then another, to draw a connection. Click empty canvas to cancel.")
        elif self.current_board_id:
            self.lbl_board_hint.setText("Pan mode is on. Scroll to zoom, drag the canvas, or move sticky cards.")
        else:
            self.lbl_board_hint.setText("Create a board to start sketching ideas, tasks, or study maps.")

    def _apply_board_pen(self):
        color = self.cmb_pen_color.currentData() or "#6f4e37"
        width = float(self.cmb_pen_width.currentData() or 3.0)
        self.board_view.set_pen(color, width)

    def _clear_board_ink(self):
        removed = False
        for item in list(self.board_scene.items()):
            if isinstance(item, InkStrokeItem):
                self.board_scene.removeItem(item)
                removed = True
        if removed:
            self.lbl_board_hint.setText("Ink strokes cleared. Sticky cards are still intact.")
            self._save_current_board_positions(notify=False)

    def _clear_board_links(self):
        removed = False
        for item in list(self.board_scene.items()):
            if isinstance(item, EdgeItem):
                self.board_scene.removeItem(item)
                removed = True
        if removed:
            self.lbl_board_hint.setText("Links cleared. Sticky cards and ink are still intact.")
            self._save_current_board_positions(notify=False)

    def _add_board_edge(self, from_id, to_id):
        if not self.current_board_id or not from_id or not to_id or from_id == to_id:
            return
        card_by_id = {}
        for item in self.board_scene.items():
            if isinstance(item, StickyCardItem):
                card_by_id[item.node.get("id")] = item
        from_item = card_by_id.get(from_id)
        to_item = card_by_id.get(to_id)
        if not from_item or not to_item:
            return
        for item in self.board_scene.items():
            if isinstance(item, EdgeItem):
                pair = {item.edge.get("from"), item.edge.get("to")}
                if pair == {from_id, to_id}:
                    return
        edge = {"id": str(int(time.time() * 1000)), "from": from_id, "to": to_id, "color": "#a36a3c"}
        self.board_scene.addItem(EdgeItem(edge, from_item, to_item))
        self.lbl_board_hint.setText("Linked two cards. Drag either card and the line follows.")
        self._save_current_board_positions(notify=False)

    def _save_current_board_positions(self, notify: bool = True):
        if not self.current_board_id:
            return
        boards = life_service.load_boards(self.base_dir)
        for board in boards:
            if board.get("id") != self.current_board_id:
                continue
            node_map = {node.get("id"): node for node in board.get("nodes", [])}
            strokes = []
            edges = []
            for item in self.board_scene.items():
                if isinstance(item, StickyCardItem):
                    node = node_map.get(item.node.get("id"))
                    if node is not None:
                        node["x"] = float(item.pos().x())
                        node["y"] = float(item.pos().y())
                elif isinstance(item, InkStrokeItem):
                    strokes.append(
                        {
                            "id": item.stroke.get("id") or str(int(time.time() * 1000)),
                            "color": item.stroke.get("color") or "#6f4e37",
                            "width": float(item.stroke.get("width", 3.0) or 3.0),
                            "points": list(item.stroke.get("points") or []),
                        }
                    )
                elif isinstance(item, EdgeItem):
                    edges.append(
                        {
                            "id": item.edge.get("id") or str(int(time.time() * 1000)),
                            "from": item.edge.get("from"),
                            "to": item.edge.get("to"),
                            "color": item.edge.get("color") or "#a36a3c",
                        }
                    )
            # QGraphicsScene.items() iterates in reverse stacking order; both
            # strokes and edges are stored in that reversed order so loading
            # them back keeps a stable z-order (v6.4 only reversed strokes,
            # flipping edge order on every save).
            board["strokes"] = list(reversed(strokes))
            board["edges"] = list(reversed(edges))
            life_service.update_board(self.base_dir, board)
            self.lbl_board_hint.setText(
                f"Saved board with {len(board.get('nodes', []))} cards, {len(edges)} links, and {len(board.get('strokes', []))} ink strokes."
            )
            if notify:
                QMessageBox.information(self, "Boards", "Board layout saved.")
            break

    def _build_files_page(self):
        w = QWidget()
        l = QVBoxLayout(w)
        l.setContentsMargins(12, 10, 12, 12)
        l.setSpacing(6)
        l.addWidget(components.page_header("Files", "Browse files in your personal root"))
        search_row = QHBoxLayout()
        self.ed_file_search = QLineEdit()
        self.ed_file_search.setPlaceholderText("Search files in personal root...")
        self.btn_file_refresh = QPushButton("Refresh")
        search_row.addWidget(self.ed_file_search, 1)
        search_row.addWidget(self.btn_file_refresh)
        l.addLayout(search_row)
        self.lbl_root = QLabel("")
        self.lbl_root.setObjectName("MutedLabel")
        l.addWidget(self.lbl_root)
        self.files_list = QListWidget()
        self.files_list.setObjectName("CafeList")
        self.files_list.itemDoubleClicked.connect(self._open_file_item)
        l.addWidget(self.files_list, 1)
        self.ed_file_search.textChanged.connect(self._schedule_files_refresh)
        self.btn_file_refresh.clicked.connect(self._refresh_files)
        self._files_search_timer = QTimer(self)
        self._files_search_timer.setSingleShot(True)
        self._files_search_timer.setInterval(250)
        self._files_search_timer.timeout.connect(self._refresh_files)
        return w

    def _schedule_files_refresh(self):
        self._files_search_timer.start()

    def _choose_root(self):
        current = prefs.get_personal_root(self.base_dir) or ""
        chosen = QFileDialog.getExistingDirectory(self, "Choose personal root", current or os.path.expanduser("~"))
        if chosen:
            prefs.set_personal_root(self.base_dir, chosen)
            self._refresh_files()

    def _refresh_files(self):
        query = self.ed_file_search.text().strip() if hasattr(self, "ed_file_search") else ""
        root = prefs.get_personal_root(self.base_dir) or ""
        self.lbl_root.setText("Root: " + (root if root else "(not set)"))
        self.files_list.clear()
        for entry in personal_service.list_root_entries(self.base_dir, query):
            label = ("[DIR] " if entry["kind"] == "dir" else "[FILE] ") + entry["name"]
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, entry["path"])
            self.files_list.addItem(item)

    def _open_file_item(self, item: QListWidgetItem):
        path = item.data(Qt.UserRole)
        if path:
            try:
                os.startfile(path)
            except Exception:
                QMessageBox.information(self, "Files", "Cannot open:\n" + str(path))

    def _build_sites_page(self):
        w = QWidget()
        l = QVBoxLayout(w)
        l.setContentsMargins(12, 10, 12, 12)
        l.setSpacing(6)
        self.sites_header = components.page_header("Sites", "Quick links and site preview")
        l.addWidget(self.sites_header)

        top_bar = QWidget()
        row = QHBoxLayout(top_bar)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(4)
        self.btn_add_site = QPushButton("Add site")
        self.btn_remove_site = QPushButton("Delete site")
        self.btn_open_site = QPushButton("Open in Browser")
        self.btn_site_ai = QPushButton("Ask AI")
        self.chk_site_preview = QCheckBox("Live preview")
        self.chk_site_preview.setToolTip("Render the selected site here (off = instant, no background load)")
        self.chk_site_preview.setChecked(False)
        row.addWidget(self.btn_add_site)
        row.addWidget(self.btn_remove_site)
        row.addWidget(self.btn_open_site)
        row.addWidget(self.btn_site_ai)
        row.addWidget(self.chk_site_preview)
        row.addStretch(1)
        l.addWidget(top_bar)
        self._sites_top_bar = top_bar

        self.lbl_sites_summary = QLabel("Personal sites stay separate from shared browser bookmarks.")
        self.lbl_sites_summary.setObjectName("MutedLabel")
        l.addWidget(self.lbl_sites_summary)

        split = QSplitter(Qt.Horizontal)
        left_card = QFrame()
        left_card.setObjectName("SectionCard")
        left_layout = QVBoxLayout(left_card)
        left_layout.setContentsMargins(10, 10, 10, 10)
        left_layout.setSpacing(5)
        left_layout.addWidget(QLabel("Saved personal sites"))
        self.sites_list = QListWidget()
        self.sites_list.setObjectName("CafeList")
        self.sites_list.currentItemChanged.connect(self._preview_site_selection)
        self.sites_list.itemDoubleClicked.connect(self._open_site_item)
        left_layout.addWidget(self.sites_list, 1)
        split.addWidget(left_card)
        self._sites_left_card = left_card

        right_card = QFrame()
        right_card.setObjectName("SectionCard")
        right_layout = QVBoxLayout(right_card)
        right_layout.setContentsMargins(10, 10, 10, 10)
        right_layout.setSpacing(5)
        title_row = QHBoxLayout()
        self.lbl_site_title = QLabel("Site preview")
        self.lbl_site_title.setObjectName("SectionTitle")
        title_row.addWidget(self.lbl_site_title)
        title_row.addStretch(1)
        self.btn_full_preview = QPushButton("Full preview")
        self.btn_full_preview.setCheckable(True)
        self.btn_full_preview.setToolTip("Expand the preview: hide the toolbars and site list")
        title_row.addWidget(self.btn_full_preview)
        right_layout.addLayout(title_row)
        self.lbl_site_url = QLabel("Select a site to preview it here.")
        self.lbl_site_url.setObjectName("MutedLabel")
        right_layout.addWidget(self.lbl_site_url)
        self.site_preview_stack = QStackedWidget()
        placeholder = QWidget()
        placeholder_layout = QVBoxLayout(placeholder)
        placeholder_layout.setContentsMargins(12, 12, 12, 12)
        placeholder_layout.setSpacing(6)
        self.lbl_site_placeholder_title = QLabel("No site selected")
        self.lbl_site_placeholder_title.setFont(QFont("Georgia", 18, QFont.Bold))
        self.lbl_site_placeholder_detail = QLabel("Choose a saved personal site on the left to preview it, or open it directly in Browser.")
        self.lbl_site_placeholder_detail.setWordWrap(True)
        self.lbl_site_placeholder_detail.setObjectName("MutedLabel")
        placeholder_layout.addStretch(1)
        placeholder_layout.addWidget(self.lbl_site_placeholder_title)
        placeholder_layout.addWidget(self.lbl_site_placeholder_detail)
        placeholder_layout.addStretch(1)
        self.site_preview_stack.addWidget(placeholder)
        # The WebEngine view is built lazily on first use: constructing it at
        # window startup spawned a Chromium renderer even for users who never
        # open the Sites page (v6.4 memory/startup cost).
        self.site_view = None
        self._placeholder_index = self.site_preview_stack.indexOf(placeholder)
        right_layout.addWidget(self.site_preview_stack, 1)
        self._site_loaded_url = ""
        split.addWidget(right_card)
        split.setChildrenCollapsible(True)
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)
        split.setSizes([220, 960])
        l.addWidget(split, 1)
        self._sites_splitter = split

        self.btn_add_site.clicked.connect(self._add_site)
        self.btn_remove_site.clicked.connect(self._remove_site)
        self.btn_open_site.clicked.connect(self._open_selected_site_in_browser)
        self.btn_site_ai.clicked.connect(self._ask_ai_about_site)
        self.chk_site_preview.toggled.connect(self._on_site_preview_toggled)
        self.btn_full_preview.toggled.connect(self._on_full_preview_toggled)
        if not self.embedded:
            self.btn_site_ai.hide()
        return w

    def _ensure_site_view(self):
        """Build the WebEngine preview on first use (lazy)."""
        if getattr(self, "site_view", None) is None:
            self.site_view = self._build_site_view()
            self.site_preview_stack.addWidget(self.site_view)
        return self.site_view

    def _refresh_sites(self):
        sites = prefs.get_personal_sites(self.base_dir)
        current_url = ""
        if self.sites_list.currentItem():
            current_url = self.sites_list.currentItem().data(Qt.UserRole) or ""
        self.sites_list.blockSignals(True)
        self.sites_list.clear()
        for site in sites:
            item = QListWidgetItem(site.get("title") or site.get("url") or "")
            item.setData(Qt.UserRole, site.get("url") or "")
            self.sites_list.addItem(item)
        self.sites_list.blockSignals(False)
        self.lbl_sites_summary.setText(f"{len(sites)} personal sites · select one to preview or double-click to open in Browser.")
        if not sites:
            self._set_site_placeholder("No personal sites yet", "Add a site to keep your private study, work, or life spaces separate from normal browser bookmarks.")
            return
        for index in range(self.sites_list.count()):
            item = self.sites_list.item(index)
            if item.data(Qt.UserRole) == current_url:
                self.sites_list.setCurrentItem(item)
                return
        self.sites_list.setCurrentRow(0)

    def _add_site(self):
        url, ok = QInputDialog.getText(self, "Add site", "URL:")
        if not ok or not (url or "").strip():
            return
        normalized_url = QUrl.fromUserInput(url.strip()).toString()
        if not normalized_url:
            QMessageBox.warning(self, "Sites", "The URL is not valid.")
            return
        title, _ = QInputDialog.getText(self, "Add site", "Display title:")
        display_title = (title or "").strip() or (QUrl(normalized_url).host() or normalized_url)
        prefs.add_personal_site(self.base_dir, normalized_url, display_title)
        self._refresh_sites()

    def _remove_site(self):
        item = self.sites_list.currentItem()
        if not item:
            return
        if QMessageBox.question(self, "Personal sites", "Remove this site from your list?", QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return
        prefs.remove_personal_site(self.base_dir, item.data(Qt.UserRole) or "")
        self._refresh_sites()

    def _build_site_view(self) -> QWebEngineView:
        """Site preview that piggybacks on the main browser profile when possible.

        Sharing the profile gives us cookies/cache/the Chrome-shape JS shim for
        free, which removes most of the perceived lag from picking a saved site
        like Cuc Quan Ly: pages stay warm in the same renderer, and a re-click
        on the same URL becomes a no-op instead of a fresh disk reload.
        """
        view = QWebEngineView()
        host_profile = self._host_browser_profile()
        if host_profile is not None:
            try:
                ensure_chrome_compat_script(host_profile)
                page = BrowserPage(host_profile, view, base_dir=self.base_dir)
                view.setPage(page)
            except Exception:
                pass
        settings = view.settings()
        try:
            settings.setAttribute(QWebEngineSettings.LocalContentCanAccessFileUrls, True)
            settings.setAttribute(QWebEngineSettings.LocalContentCanAccessRemoteUrls, True)
            settings.setAttribute(QWebEngineSettings.ScrollAnimatorEnabled, True)
            settings.setAttribute(QWebEngineSettings.ShowScrollBars, True)
            try:
                settings.setAttribute(QWebEngineSettings.Accelerated2dCanvasEnabled, True)
            except AttributeError:
                pass
            try:
                settings.setAttribute(QWebEngineSettings.WebGLEnabled, True)
            except AttributeError:
                pass
            try:
                settings.setAttribute(QWebEngineSettings.PlaybackRequiresUserGesture, True)
            except AttributeError:
                pass
            try:
                settings.setAttribute(QWebEngineSettings.DnsPrefetchEnabled, True)
            except AttributeError:
                pass
        except Exception:
            pass
        # Highlight-text-to-copy on the embedded preview too: install the
        # profile script so every future load in this view gets the helper,
        # then re-run it after each finished load in case this view runs on
        # its own (standalone) profile.
        try:
            page_profile = view.page().profile() if view.page() else None
            if page_profile is not None:
                ensure_text_highlight_script(page_profile, prefs.get_text_highlight_enabled(self.base_dir), self.base_dir)
        except Exception:
            pass
        view.loadFinished.connect(self._on_site_view_loaded)
        view.setZoomFactor(0.95)
        return view

    def _on_site_view_loaded(self, ok: bool):
        """Re-apply the highlight-to-copy helper after each preview load."""
        if not ok:
            return
        try:
            if not prefs.get_text_highlight_enabled(self.base_dir):
                return
            if self.site_view.page() is None:
                return
            self.site_view.page().runJavaScript(build_text_highlight_js(True))
        except Exception:
            pass

    def _host_browser_profile(self):
        """Return the main browser's QWebEngineProfile, or None if running standalone."""
        shell = self._host_shell()
        if shell is None:
            return None
        candidates = (
            getattr(shell, "browser_page", None),
            getattr(shell, "browser_window", None),
            getattr(shell, "main_window", None),
            shell,
        )
        for owner in candidates:
            if owner is None:
                continue
            profile = getattr(owner, "profile", None)
            if isinstance(profile, QWebEngineProfile):
                return profile
        return None

    def _update_site_preview_activity(self, active: bool) -> None:
        """Stop the embedded preview when the Sites page is hidden so it does
        not keep timers/animations/network running in the background."""
        if not hasattr(self, "site_preview_stack"):
            return
        if getattr(self, "site_view", None) is None:
            return  # lazy view not built yet — nothing to pause
        page = self.site_view.page()
        if active:
            if not getattr(self, "_site_preview_on", False):
                return
            cached = self._site_loaded_url or ""
            if cached and self.site_preview_stack.currentWidget() is self.site_view:
                if not (page and page.url().toString() == cached):
                    self.site_view.setUrl(QUrl(cached))
            return
        try:
            if page is not None:
                # "Stop" alone leaves loaded JS timers running in the background
                # (v6.4 claimed the preview "stops consuming CPU" but did not).
                # Navigating to about:blank actually unloads the site.
                page.triggerAction(_PersonalWebEnginePage.Stop)
                page.setUrl(QUrl("about:blank"))
        except Exception:
            pass

    def _preview_site_selection(self, current, _previous):
        if not current:
            self._set_site_placeholder("No site selected", "Choose a saved personal site to preview it here.")
            self._site_loaded_url = ""
            return
        url = (current.data(Qt.UserRole) or "").strip()
        title = current.text().strip() or "Personal site"
        self.lbl_site_title.setText(title)
        self.lbl_site_url.setText(url or "(empty url)")
        if not url:
            self._site_loaded_url = ""
            return
        if not self._site_preview_on:
            # Lazy preview: navigating the list must never spin up a heavy
            # WebEngine renderer (LinkLumina runs WebGL + hundreds of KB of JS).
            # Show a cheap placeholder until the user opts into a live preview.
            self._show_site_placeholder(
                "Preview paused",
                "Tick 'Live preview' to render the site here, or click 'Open in Browser' to open it as a full tab.",
            )
            return
        site_view = self._ensure_site_view()
        self.site_preview_stack.setCurrentWidget(site_view)
        if url == self._site_loaded_url:
            page = site_view.page()
            if page and page.url().toString() == url:
                return
        self._site_loaded_url = url
        site_view.setUrl(QUrl(url))

    def _set_site_placeholder(self, title: str, detail: str):
        self.lbl_site_title.setText("Site preview")
        self.lbl_site_url.setText(detail)
        self.lbl_site_placeholder_title.setText(title)
        self.lbl_site_placeholder_detail.setText(detail)
        self.site_preview_stack.setCurrentIndex(0)

    def _show_site_placeholder(self, title: str, detail: str):
        """Show the lightweight placeholder without overwriting title/URL labels."""
        self.lbl_site_placeholder_title.setText(title)
        self.lbl_site_placeholder_detail.setText(detail)
        self.site_preview_stack.setCurrentIndex(0)

    def _on_site_preview_toggled(self, checked: bool):
        self._site_preview_on = bool(checked)
        if checked:
            item = self.sites_list.currentItem()
            if item is not None:
                self._preview_site_selection(item, None)
        else:
            self._stop_preview()

    def _on_full_preview_toggled(self, checked: bool):
        """Expand the preview to the full Sites area (collapse toolbars + list)."""
        checked = bool(checked)
        for widget in (
            getattr(self, "_sites_top_bar", None),
            self.lbl_sites_summary,
            getattr(self, "sites_header", None),
        ):
            if widget is not None:
                widget.setVisible(not checked)
        if hasattr(self, "_sites_left_card"):
            self._sites_left_card.setVisible(not checked)
        self.btn_full_preview.setText("Exit full" if checked else "Full preview")
        if checked:
            # Full preview implies the user actually wants to see the site.
            if not self.chk_site_preview.isChecked():
                self.chk_site_preview.setChecked(True)
            if hasattr(self, "_sites_splitter"):
                self._sites_splitter.setSizes([0, 1200])
        elif hasattr(self, "_sites_splitter"):
            self._sites_splitter.setSizes([220, 960])

    def _stop_preview(self):
        """Unload the embedded renderer so a heavy local app stops using CPU/GPU."""
        self._site_loaded_url = ""
        try:
            page = self.site_view.page()
            if page is not None:
                page.triggerAction(_PersonalWebEnginePage.Stop)
                self.site_view.setUrl(QUrl("about:blank"))
        except Exception:
            pass
        self._show_site_placeholder(
            "Preview paused",
            "The embedded preview is unloaded to save resources. Tick 'Live preview' to load it again.",
        )

    def _open_site_item(self, item: QListWidgetItem):
        url = item.data(Qt.UserRole) or ""
        if url:
            self._open_url_in_browser(url)

    def _open_selected_site_in_browser(self):
        item = self.sites_list.currentItem()
        if item:
            self._open_url_in_browser(item.data(Qt.UserRole) or "")

    def _ask_ai_about_site(self):
        item = self.sites_list.currentItem()
        if not item:
            QMessageBox.information(self, "AI", "Select a site first.")
            return
        shell = self._host_shell()
        if not shell or not hasattr(shell, "ai_page"):
            QMessageBox.information(self, "AI", "Open Personal Hub inside the main shell to use the assistant.")
            return
        url = (item.data(Qt.UserRole) or "").strip()
        title = (item.text() or url or "Personal site").strip()
        if not url:
            QMessageBox.information(self, "AI", "This site has no URL to read.")
            return
        question = f"What is this personal site for and how should I use it: {title}"
        self._site_ai_shell = shell
        self._site_ai_question = question
        self._site_ai_meta = (title, url)
        self._site_preview_was_on_before_ai = bool(self._site_preview_on)
        already_loaded = ""
        try:
            already_loaded = self._ensure_site_view().page().url().toString()
        except Exception:
            pass
        if already_loaded == url:
            # Site is already rendered in the preview — read it straight away.
            self._on_site_ai_load_finished(True)
            return
        # Load the site in the embedded preview (even when Live preview is off)
        # and read its real content so the assistant answers from the page,
        # not just from the saved URL.
        self._site_preview_on = True
        site_view = self._ensure_site_view()
        self.site_preview_stack.setCurrentWidget(site_view)
        self._site_loaded_url = url
        try:
            site_view.loadFinished.disconnect(self._on_site_ai_load_finished)
        except Exception:
            pass
        site_view.loadFinished.connect(self._on_site_ai_load_finished)
        site_view.setUrl(QUrl(url))

    def _on_site_ai_load_finished(self, _ok: bool):
        try:
            self._ensure_site_view().loadFinished.disconnect(self._on_site_ai_load_finished)
        except Exception:
            pass
        shell = getattr(self, "_site_ai_shell", None)
        if not shell or not hasattr(shell, "ai_page"):
            return
        title, url = getattr(self, "_site_ai_meta", ("", ""))
        question = getattr(self, "_site_ai_question", "") or f"What is this personal site for and how should I use it: {title}"

        def _grab(page_text):
            body = (page_text or "").strip()
            context = f"Title: {title}\nURL: {url}\n\nSite content:\n{body[:8000]}"
            shell.ed_ai_quick.setText(question)
            shell.ai_page.ask_with_context(question, f"Personal site: {title}", context)
            shell.switch_workspace("ai")
            # If Live preview was off, unload the temporary preview again so a
            # heavy site does not keep running in the background.
            was_on = bool(getattr(self, "_site_preview_was_on_before_ai", True))
            if not was_on:
                self._stop_preview()
            self._site_preview_on = was_on

        try:
            self._ensure_site_view().page().toPlainText(_grab)
        except Exception:
            _grab("")

    def _open_url_in_browser(self, url: str):
        if not url:
            return
        shell = self._host_shell()
        if shell is not None:
            shell.switch_workspace("browser")
            shell.browser_page.url_bar.setText(url)
            shell.browser_page.navigate()
            return
        site_view = self._ensure_site_view()
        self.site_preview_stack.setCurrentWidget(site_view)
        site_view.setUrl(QUrl(url))

    def _host_shell(self):
        current = self.parent()
        while current is not None:
            if hasattr(current, "switch_workspace") and hasattr(current, "browser_page"):
                return current
            current = current.parent()
        win = self.window()
        if hasattr(win, "switch_workspace") and hasattr(win, "browser_page"):
            return win
        return None

    def open_life_item(self, kind: str, item_id: str):
        if kind == "task":
            self._switch_page("tasks")
            for index in range(self.tasks_list.count()):
                item = self.tasks_list.item(index)
                if item.data(Qt.UserRole) == item_id:
                    self.tasks_list.setCurrentItem(item)
                    break
            return
        if kind == "event":
            self._switch_page("calendar")
            self.select_event(item_id)
            return
        if kind in ("board", "board-node"):
            self._switch_page("boards")
            target_board_id = item_id
            if kind == "board-node":
                # Resolve the node's parent board; v6.4 used the node id itself
                # and could never match any board.
                target_board_id = self._find_board_for_node(item_id) or self.current_board_id
            for index in range(self.boards_list.count()):
                item = self.boards_list.item(index)
                if item.data(Qt.UserRole) == target_board_id:
                    if self.boards_list.currentItem() is not item:
                        self.boards_list.setCurrentItem(item)
                    else:
                        self._load_selected_board(item, None)  # force scene rebuild
                    return

    def _find_board_for_node(self, node_id: str) -> str:
        for board in life_service.load_boards(self.base_dir):
            for node in board.get("nodes", []) or []:
                if isinstance(node, dict) and node.get("id") == node_id:
                    return board.get("id", "")
        return ""

    def get_current_state(self):
        tabs = []
        for idx, site in enumerate(prefs.get_personal_sites(self.base_dir)):
            url = (site.get("url") or "").strip()
            if url:
                tabs.append({"url": url, "active": idx == 0})
        return tabs

    def _auto_save_set(self):
        tabs = self.get_current_state()
        if tabs:
            tab_sets.add_tab_set(self.base_dir, "personal", time.strftime("Personal auto %Y-%m-%d %H:%M"), tabs)

    def save_current_set(self):
        tabs = self.get_current_state()
        if not tabs:
            QMessageBox.information(self, "Personal", "No personal sites to save yet.")
            return
        default = time.strftime("Personal manual %Y-%m-%d %H:%M")
        name, ok = QInputDialog.getText(self, "Save Personal session", "Session name:", text=default)
        if not ok:
            return
        tab_sets.add_tab_set(self.base_dir, "personal", name or default, tabs)
        QMessageBox.information(self, "Personal", "Current personal session saved.")

    def closeEvent(self, event):
        save_errors = []
        try:
            if self.current_note_id:
                if not personal_service.save_note(self.base_dir, self.current_note_id, self.note_editor.toPlainText()):
                    save_errors.append("the open note could not be saved")
        except Exception as exc:
            save_errors.append(f"note save failed: {exc}")
        try:
            self._save_current_board_positions(notify=False)
        except Exception as exc:
            save_errors.append(f"board save failed: {exc}")
        try:
            self._auto_save_set()
        except Exception:
            pass
        if save_errors:
            QMessageBox.warning(
                self,
                "Personal Hub",
                "Some data may not have been saved:\n- " + "\n- ".join(save_errors),
            )
        event.accept()


def _format_ts(ts_value: int) -> str:
    if not ts_value:
        return "-"
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(ts_value))
