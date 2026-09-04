"""Shell dashboard pages (Home, Library, Settings, History)."""
import os
import socket
import time

from PyQt5.QtCore import QSize, Qt, QTimer, QUrl
from PyQt5.QtGui import QColor, QDesktopServices, QGuiApplication, QIcon, QImage, QPainter, QPen, QPixmap
from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from litebrowser.core import app_paths, app_version, prefs, storage_utils
from litebrowser.core import time_utils as _time_utils
from litebrowser.services import (
    android_bridge_service,
    brief_service,
    focus_service,
    history_service,
    life_service,
    personal_service,
    retriever,
)
from litebrowser.ui import components, dialogs, theme


def _dedupe_library_items(items: list) -> list:
    """First occurrence wins; same kind+id from search_everything vs retriever counts once.

    Imperfect: same entity may appear under different ids (e.g. URL vs saved_page id).
    """
    seen: set[tuple[str, str]] = set()
    out = []
    for item in items:
        key = (str(item.get("kind") or "").strip().lower(), str(item.get("id") or "").strip().lower())
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def _format_ts(ts_value: int) -> str:
    """Backward-compatible alias; the canonical helper lives in core.time_utils."""
    return _time_utils.format_ts(ts_value)


def _panel(title: str, subtitle: str = "", action: QPushButton | None = None) -> tuple[QFrame, QVBoxLayout]:
    """Create a roomy, card-like section used by the calm secondary screens."""
    card = QFrame()
    card.setObjectName("SectionCard")
    layout = QVBoxLayout(card)
    layout.setContentsMargins(14, 12, 14, 14)
    layout.setSpacing(8)
    layout.addWidget(components.section_header(title, subtitle, action))
    return card, layout


def _activity_item(kind: str, title: str, detail: str = "", meta: str = "") -> QListWidgetItem:
    """Build a scan-friendly two-line list row while retaining normal list semantics."""
    kind_label = (kind or "item").replace("-", " ").upper()
    raw_heading = (title or "Untitled").strip()
    raw_secondary = "  ·  ".join(part for part in (meta.strip(), detail.strip()) if part)
    heading = raw_heading if len(raw_heading) <= 108 else raw_heading[:105].rstrip() + "..."
    secondary = raw_secondary if len(raw_secondary) <= 168 else raw_secondary[:165].rstrip() + "..."
    text = f"{kind_label}  {heading}"
    if secondary:
        text += f"\n{secondary}"
    row = QListWidgetItem(text)
    row.setToolTip("\n".join(part for part in (raw_heading, raw_secondary) if part))
    row.setSizeHint(QSize(0, 54 if secondary else 34))
    return row





class _DomainWeekChart(QWidget):
    """Top domains this week as horizontal theme bars — the wellbeing view.

    Distraction domains tint with DANGER so the balance is honest at a glance."""

    _SCARY = ("facebook.com", "instagram.com", "tiktok.com", "x.com", "twitter.com", "reddit.com", "netflix.com", "youtube.com")

    def __init__(self, page):
        super().__init__()
        self._page = page
        self._rows = []  # (domain, count, scary?)
        self.setMinimumHeight(200)

    def refresh(self):
        from litebrowser.core import prefs as _prefs
        from urllib.parse import urlparse as _urlparse

        entries = _prefs.load_history_entries(self._page.shell.profile_dir)
        midnight = time.mktime(time.localtime()[:3] + (0, 0, 0, 0, 0, -1))
        counts = {}
        for ts, url in entries:
            ts = int(ts or 0)
            if ts < midnight - 6 * 86400:
                continue
            host = _urlparse(url).netloc.removeprefix("www.").lower() if "://" in url else ""
            if host:
                counts[host] = counts.get(host, 0) + 1
        ranked = sorted(counts.items(), key=lambda kv: -kv[1])[:6]
        self._rows = [
            (d, c, any(d == s or d.endswith("." + s) for s in self._SCARY))
            for d, c in ranked
        ]
        self.update()

    def paintEvent(self, _event):
        from litebrowser.ui import theme as _theme

        painter = QPainter(self)
        w, h = self.width(), self.height()
        p = _theme.palette()
        painter.fillRect(self.rect(), QColor(p["MAIN_BG_ALT"]))
        if not self._rows:
            painter.setPen(QColor(p["TEXT_MUTED"]))
            painter.drawText(self.rect(), Qt.AlignCenter, "No browsing this week yet.")
            painter.end()
            return
        top = 8
        row_h = max(18, (h - 16) // max(1, len(self._rows)))
        max_count = max(c for _d, c, _s in self._rows) or 1
        label_w = int(min(150, w * 0.4))
        bar_x = label_w + 10
        bar_w_max = max(30, w - bar_x - 46)
        for i, (domain, count, scary) in enumerate(self._rows):
            y = top + i * row_h
            painter.setPen(QColor(p["TEXT"]))
            painter.drawText(6, y, label_w, row_h, Qt.AlignVCenter | Qt.AlignLeft, domain[:22])
            bar_w = int(bar_w_max * count / max_count)
            color = QColor(p["DANGER"]) if scary else QColor(p["ACCENT"])
            painter.setPen(Qt.NoPen)
            painter.setBrush(color)
            painter.drawRoundedRect(bar_x, y + (row_h - 12) // 2, max(4, bar_w), 12, 4, 4)
            painter.setPen(QColor(p["TEXT_MUTED"]))
            painter.drawText(bar_x + max(4, bar_w) + 6, y, 40, row_h, Qt.AlignVCenter, str(count))
        painter.end()


class _WeekActivityChart(QWidget):
    """A quiet 7-day bar chart of browsing counts, painted with the theme.

    Pure QWidget painting: no chart dependency, follows the accent, and the
    today bar highlights so 'how much did I browse today' answers itself."""

    def __init__(self, page):
        super().__init__()
        self._page = page
        self._counts = [0] * 7
        self._day_labels = [""] * 7
        self.setMinimumHeight(200)

    def refresh(self):
        import time as _time

        from litebrowser.core import prefs as _prefs

        base_dir = self._page.shell.profile_dir
        entries = _prefs.load_history_entries(base_dir)
        today = _time.localtime()
        midnight_today = _time.mktime((today.tm_year, today.tm_mon, today.tm_mday, 0, 0, 0, 0, 0, -1))
        counts = [0] * 7
        for ts, _url in entries:
            age_days = int((midnight_today - int(ts or 0)) // 86400)
            if 0 <= age_days < 7:
                counts[6 - age_days] += 1
        self._counts = counts
        try:
            from datetime import datetime as _dt

            self._day_labels = [
                (_dt.now() - __import__("datetime").timedelta(days=6 - i)).strftime("%a") for i in range(7)
            ]
        except Exception:
            self._day_labels = [""] * 7
        self.update()

    def paintEvent(self, _event):
        from litebrowser.ui import theme as _theme

        painter = QPainter(self)
        w, h = self.width(), self.height()
        p = _theme.palette()
        painter.fillRect(self.rect(), QColor(p["MAIN_BG_ALT"]))
        # Vertical zones that never overlap or clip, bottom to top:
        #   [day labels] 4px .. bars .. [value labels above the bars]
        # The day labels keep a generous clear margin under them so the text
        # never touches (or looks sliced by) the card's bottom border.
        value_zone = 16  # counts drawn above each bar
        label_zone = 22  # day-of-week labels (with room under the descenders)
        top = 6 + value_zone  # tallest bar tops stop here (labels sit above)
        bottom = max(top + 4, h - label_zone - 4)  # bar baseline
        max_count = max(self._counts or [0]) or 1
        side = 12
        bar_w = max(10, min(52, (w - side * 2 - 6 * 8) // 7))
        step = (w - side * 2) / 7.0
        for i, count in enumerate(self._counts):
            x = side + int(i * step + (step - bar_w) / 2.0)
            is_today = i == 6
            if count <= 0:
                # No visits: draw a faint baseline dot instead of a stub bar,
                # so empty days do not masquerade as activity.
                color = QColor(p["MAIN_BG_ALT"]).lighter(103)
                painter.setPen(Qt.NoPen)
                painter.setBrush(QColor(p["BORDER_SOFT"]))
                painter.drawRoundedRect(x + (bar_w - 5) // 2, bottom - 5, 5, 5, 2, 2)
                continue
            bar_h = int((count / max_count) * max(8, bottom - top))
            y = bottom - bar_h
            color = QColor(p["ACCENT"] if is_today else p["ACCENT_SOFT"])
            painter.setPen(QPen(QColor(p["INPUT_BORDER"]), 1))
            painter.setBrush(color)
            painter.drawRoundedRect(x, y, bar_w, max(4, bar_h), 4, 4)
            painter.setPen(QColor(p["TEXT"]))
            painter.drawText(x, max(0, y - 14), bar_w, 13, Qt.AlignCenter, str(count))
        # Day labels sit comfortably above the card edge (never flush/cut).
        painter.setPen(QColor(p["TEXT_MUTED"]))
        label_y = h - label_zone
        for i in range(7):
            x = side + int(i * step + (step - bar_w) / 2.0)
            label = self._day_labels[i] if i < len(self._day_labels) else ""
            painter.drawText(x, label_y + 2, bar_w, label_zone - 6, Qt.AlignCenter, label[:3])
        painter.end()


class HomeDashboardPage(QWidget):
    def __init__(self, shell):
        super().__init__()
        self.shell = shell
        self.setObjectName("HomeDashboard")
        # The dashboard is ~1050px tall at its natural size.  Without a scroll
        # area a shorter viewport (half-screen shell, small laptop) squeezed
        # every row below its minimum: launcher tiles collapsed into glued
        # strips with their labels clipped away.  Scrolling keeps every tile
        # at full size and lets the page breathe at any window height.
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.home_scroll = QScrollArea()
        self.home_scroll.setObjectName("HomeScroll")
        self.home_scroll.setWidgetResizable(True)
        self.home_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.home_scroll.setFrameShape(QFrame.NoFrame)
        content = QWidget()
        content.setObjectName("HomeScrollContent")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(18, 18, 18, 16)
        content_layout.setSpacing(12)
        self.home_scroll.setWidget(content)
        layout.addWidget(self.home_scroll)
        layout = content_layout

        hero = QFrame()
        hero.setObjectName("HeroCard")
        hero_layout = QVBoxLayout(hero)
        hero_layout.setContentsMargins(20, 18, 20, 18)
        hero_layout.setSpacing(12)

        brand_row = QHBoxLayout()
        # Time-of-day greeting: the home hero greets like the new-tab page
        # does (v6.4 used a static tagline on Home only).
        try:
            from litebrowser.browser.new_tab_page import cafe_greeting

            _eyebrow, headline = cafe_greeting()
        except Exception:
            headline = "Your quiet corner of the web"
        brand = QLabel(headline)
        brand.setObjectName("HeroTitle")
        brand.setFont(components._font(26, components.WEIGHT_BOLD))
        # Wrap instead of forcing a ~1000px minimum width: the long greeting
        # used to make the whole dashboard min-width wider than most shell
        # viewports, so narrow windows clipped the right edge.
        brand.setWordWrap(True)
        brand_row.addWidget(brand, 1)
        self.lbl_today = QLabel(time.strftime("%A, %d %B · %H:%M"))
        self.lbl_today.setObjectName("HeroBadge")
        brand_row.addWidget(self.lbl_today, 0, Qt.AlignVCenter)
        self._clock_timer = QTimer(self)
        self._clock_timer.timeout.connect(self._tick_clock)
        self._clock_timer.start(1000)
        self.lbl_home_version = QLabel(f"v{app_version.APP_VERSION}")
        self.lbl_home_version.setObjectName("HeroBadge")
        brand_row.addWidget(self.lbl_home_version, 0, Qt.AlignVCenter)
        hero_layout.addLayout(brand_row)

        subtitle = QLabel(
            "A small local-first workspace for browsing, thinking, and keeping the things worth returning to."
        )
        subtitle.setWordWrap(True)
        subtitle.setObjectName("HeroSubtitle")
        hero_layout.addWidget(subtitle)

        command_row = QHBoxLayout()
        command_row.setSpacing(8)
        self.ed_home_command = QLineEdit()
        self.ed_home_command.setObjectName("HomeCommand")
        self.ed_home_command.setPlaceholderText("Search, open a link, or type a command such as /task ...")
        command_row.addWidget(self.ed_home_command, 1)
        self.btn_home_command = QPushButton("Go")
        self.btn_home_command.setObjectName("TopAccentButton")
        command_row.addWidget(self.btn_home_command)
        hero_layout.addLayout(command_row)

        launcher = QWidget()
        launcher.setObjectName("HomeLaunchGrid")
        launcher_grid = QGridLayout(launcher)
        launcher_grid.setContentsMargins(0, 2, 0, 0)
        launcher_grid.setHorizontalSpacing(9)
        launcher_grid.setVerticalSpacing(9)
        launch_specs = (
            ("↗", "Browser", "Tabs & web", "browser"),
            ("✦", "Ask AI", "RAG assistant", "ai"),
            ("◌", "Personal", "Life hub", "personal"),
            ("✓", "Quick Task", "Add a task", "task"),
            ("☕", "Café Focus", "25-min pour", "focus"),
            ("▦", "Library", "Everything", "library"),
            ("◷", "History", "All activity", "history"),
            ("⚙", "Settings", "Tune it all", "settings"),
            ("?", "Help", "Guide & tools", "guide"),
        )
        self._launch_tiles = []
        for index, (glyph, label, hint, key) in enumerate(launch_specs):
            tile = components.action_tile(glyph, label, hint)
            self._launch_tiles.append(tile)
            row, column = divmod(index, 3)
            launcher_grid.addWidget(tile, row, column)
            launcher_grid.setColumnStretch(column, 1)
        hero_layout.addWidget(launcher)

        cmd_row = QHBoxLayout()
        cmd_row.setSpacing(6)
        self.lbl_quick_commands = QLabel("Quick commands")
        self.lbl_quick_commands.setObjectName("MutedLabel")
        cmd_row.addWidget(self.lbl_quick_commands)
        for cmd, tip in (("/task ", "Create task"), ("/note ", "Create note"), ("/board ", "New board"), ("/focus 25", "Start pour"), ("/hub", "Project Hub"), ("/cql", "Cục Quản Lý")):
            chip = components.chip(cmd, checkable=False)
            chip.setToolTip(tip)
            chip.clicked.connect(lambda checked=False, c=cmd, s=shell: self._send_quick_command(c, s))
            cmd_row.addWidget(chip)
        cmd_row.addStretch(1)
        hero_layout.addLayout(cmd_row)
        layout.addWidget(hero)

        stats_row = QHBoxLayout()
        stat_specs = [
            (self, "task", "pending tasks"),
            (self, "events", "upcoming events"),
            (self, "pages", "saved pages"),
            (self, "boards", "boards"),
            (self, "focus", "min focused today"),
        ]
        self._stat_labels = {}
        tiles = []
        for owner, key, label in stat_specs:
            tile = components.stat_tile("0", label)
            tiles.append(tile)
            self._stat_labels[key] = tile._value
        stats_row.addWidget(components.stat_row(tiles), 1)
        layout.addLayout(stats_row)

        # Dashboard 2.0: 7-day browsing activity mini bar chart (pure paint,
        # no chart lib) driven straight from history timestamps.
        self.week_chart = _WeekActivityChart(self)
        self.domain_chart = _DomainWeekChart(self)
        charts_row = QHBoxLayout()
        for title_text, subtitle, chart in (
            ("Your Week", "Pages visited per day (last 7 days)", self.week_chart),
            ("Where time goes", "Top domains this week — your digital wellbeing", self.domain_chart),
        ):
            card = QFrame()
            card.setObjectName("SectionCard")
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(14, 12, 14, 12)
            card_layout.setSpacing(6)
            card_layout.addWidget(components.section_header(title_text, subtitle))
            card_layout.addWidget(chart, 1)
            charts_row.addWidget(card, 1)
        layout.addLayout(charts_row, 1)

        self.btn_brief_refresh = QPushButton("↻ Refresh")
        self.btn_brief_refresh.clicked.connect(self._refresh_brief)
        self.brief_card = QFrame()
        self.brief_card.setObjectName("SectionCard")
        brief_layout = QVBoxLayout(self.brief_card)
        brief_layout.setContentsMargins(14, 12, 14, 12)
        brief_layout.setSpacing(8)
        brief_layout.addWidget(
            components.section_header("Morning Brief", "A local digest of your day", self.btn_brief_refresh)
        )
        self.lbl_brief = QLabel("Pouring your brief...")
        self.lbl_brief.setObjectName("HeroSubtitle")
        self.lbl_brief.setWordWrap(True)
        brief_layout.addWidget(self.lbl_brief)
        layout.addWidget(self.brief_card)

        sections = QHBoxLayout()
        self.recent_notes = QListWidget()
        self.recent_notes.setObjectName("CafeList")
        self.recent_tasks = QListWidget()
        self.recent_tasks.setObjectName("CafeList")
        self.recent_closed = QListWidget()
        self.recent_closed.setObjectName("CafeList")
        notes_card = self._card_with_list("Recent Notes", "From SafeVault", self.recent_notes)
        tasks_card = self._card_with_list("Today's Focus", "Active tasks & pours", self.recent_tasks)
        closed_card = self._card_with_list("Recently Closed", "Tabs you closed", self.recent_closed)
        sections.addWidget(notes_card, 1)
        sections.addWidget(tasks_card, 1)
        sections.addWidget(closed_card, 1)
        layout.addLayout(sections, 1)

        self.btn_browser, self.btn_ai, self.btn_personal, self.btn_task, self.btn_focus, self.btn_library, self.btn_history, self.btn_settings, self.btn_guide = self._launch_tiles

        self.btn_browser.clicked.connect(lambda: self.shell.switch_workspace("browser"))
        self.btn_ai.clicked.connect(lambda: self.shell.switch_workspace("ai"))
        self.btn_personal.clicked.connect(lambda: self.shell.switch_workspace("personal"))
        self.btn_task.clicked.connect(self.shell.quick_task_dialog)
        self.btn_focus.clicked.connect(self._start_focus)
        self.btn_library.clicked.connect(lambda: self.shell.switch_workspace("library"))
        self.btn_history.clicked.connect(lambda: self.shell.switch_workspace("history"))
        self.btn_settings.clicked.connect(lambda: self.shell.switch_workspace("settings"))
        self.btn_guide.clicked.connect(lambda: dialogs.show_browser_control_center(self.shell.browser_page))
        self.recent_closed.itemDoubleClicked.connect(self._open_recent_closed)

    def _tick_clock(self):
        self.lbl_today.setText(time.strftime("%A, %d %B · %H:%M:%S"))

    def resizeEvent(self, event):
        """Trim secondary hero chrome on narrow viewports.

        The hero keeps its natural (wrap-friendly) width, so at small shell
        sizes these extras would be the only things forcing horizontal
        overflow; dropping them lets the dashboard fit without a sideways
        scrollbar."""
        super().resizeEvent(event)
        width = max(0, self.width())
        if hasattr(self, "lbl_home_version"):
            self.lbl_home_version.setVisible(width >= 1150)
        if hasattr(self, "lbl_quick_commands"):
            self.lbl_quick_commands.setVisible(width >= 1000)

    def _open_recent_closed(self, item):
        url = item.data(Qt.UserRole) or ""
        if not url:
            return
        self.shell.switch_workspace("browser")
        self.shell.browser_page.add_new_tab(QUrl(url), item.text())

    def _send_quick_command(self, cmd: str, shell):
        shell.omnibar.setText(cmd)
        shell.handle_omnibar()

    def _card_with_list(self, title_text: str, subtitle: str, list_widget: QListWidget):
        card = QFrame()
        card.setObjectName("SectionCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(12, 12, 12, 12)
        header = components.section_header(title_text, subtitle)
        layout.addWidget(header)
        # A generous floor keeps the Recent Notes / Today's Focus / Recently
        # Closed cards from collapsing into a single cramped row on shorter
        # viewports; extra window height then grows them further.
        list_widget.setMinimumHeight(220)
        layout.addWidget(list_widget, 1)
        return card

    def _start_focus(self):
        from litebrowser.services import focus_service
        focus_service.start_focus(self.shell.profile_dir, minutes=25, label="Home quick pour")
        self.shell.refresh_shell()
        QMessageBox.information(self, "Café Focus", "25-minute pour started. Track it with /status or /focus.")

    def refresh(self):
        snapshot = life_service.get_dashboard_snapshot(self.shell.profile_dir)
        self._stat_labels["task"].setText(str(snapshot["tasks_pending"]))
        self._stat_labels["events"].setText(str(len(snapshot["events_upcoming"])))
        self._stat_labels["pages"].setText(str(snapshot["saved_pages_total"]))
        self._stat_labels["boards"].setText(str(snapshot["boards_total"]))
        self._stat_labels["focus"].setText(f"{focus_service.today_focus_seconds(self.shell.profile_dir) // 60}")
        if getattr(self, "week_chart", None) is not None:
            self.week_chart.refresh()
        if getattr(self, "domain_chart", None) is not None:
            self.domain_chart.refresh()

        self.recent_notes.clear()
        for note in personal_service.list_notes(self.shell.profile_dir)[:8]:
            self.recent_notes.addItem(note["title"])
        if self.recent_notes.count() == 0:
            self.recent_notes.addItem(components.hint_list_item("No notes yet"))

        self.recent_tasks.clear()
        tasks = [item for item in life_service.load_tasks(self.shell.profile_dir) if not item.get("completed")][:8]
        for task in tasks:
            due = _format_ts(int(task.get("due_at", 0) or 0)) if int(task.get("due_at", 0) or 0) else task.get("bucket", "")
            self.recent_tasks.addItem(f"{task.get('title', '')} - {due}")
        if self.recent_tasks.count() == 0:
            self.recent_tasks.addItem(components.hint_list_item("No active tasks", "○"))

        self.recent_closed.clear()
        state = prefs.session_state_load(self.shell.profile_dir)
        closed = [entry for entry in state.get("recently_closed", []) if entry.get("kind") == "tab" and entry.get("url")][:10]
        for entry in closed:
            row = QListWidgetItem((entry.get("title") or entry.get("url") or "").strip() or entry.get("url"))
            row.setToolTip(entry.get("url", ""))
            row.setData(Qt.UserRole, entry.get("url", ""))
            self.recent_closed.addItem(row)
        if self.recent_closed.count() == 0:
            self.recent_closed.addItem(components.hint_list_item("Nothing closed recently", "○"))

        self.brief_card.setVisible(prefs.get_show_morning_brief(self.shell.profile_dir))
        self._refresh_brief()

    def _refresh_brief(self):
        brief = brief_service.build_morning_brief(self.shell.profile_dir)
        self.lbl_brief.setText(brief_service.brief_text(brief))


class LibraryPage(QWidget):
    def __init__(self, shell):
        super().__init__()
        self.shell = shell
        self.setObjectName("LibraryWorkspace")
        self._last_results = []
        self._library_filter = "all"
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 18)
        layout.setSpacing(12)

        hero = QFrame()
        hero.setObjectName("HeroCard")
        hero_layout = QVBoxLayout(hero)
        hero_layout.setContentsMargins(16, 14, 16, 14)
        hero_layout.setSpacing(10)
        heading = QHBoxLayout()
        page = components.page_header("Library", "A calm shelf for pages, notes, tasks, and ideas")
        heading.addWidget(page, 1)
        self.lbl_library_scope = components.badge("PRIVATE SHELF", "accent")
        heading.addWidget(self.lbl_library_scope, 0, Qt.AlignTop)
        hero_layout.addLayout(heading)

        search_row = QHBoxLayout()
        search_row.setSpacing(8)
        self.ed_search = QLineEdit()
        self.ed_search.setPlaceholderText("Search your saved pages, notes, tasks, boards, and calendar...")
        self.ed_search.setMinimumWidth(280)
        search_row.addWidget(self.ed_search, 1)
        self.btn_refresh = QPushButton("Refresh")
        self.btn_refresh.setObjectName("TopAccentButton")
        search_row.addWidget(self.btn_refresh)
        hero_layout.addLayout(search_row)

        filter_row = QHBoxLayout()
        filter_row.setSpacing(6)
        filter_label = QLabel("SHOW")
        filter_label.setObjectName("MutedLabel")
        filter_row.addWidget(filter_label)
        self.library_filter_buttons = {}
        for key, label in (
            ("all", "Everything"),
            ("pages", "Pages"),
            ("notes", "Notes"),
            ("tasks", "Tasks"),
            ("events", "Events"),
            ("boards", "Boards"),
        ):
            button = components.chip(label, checked=key == "all")
            button.clicked.connect(lambda checked=False, value=key: self._set_library_filter(value))
            self.library_filter_buttons[key] = button
            filter_row.addWidget(button)
        filter_row.addStretch(1)
        hero_layout.addLayout(filter_row)
        layout.addWidget(hero)

        self.library_stats = {
            "results": components.stat_tile("0", "on this shelf"),
            "pages": components.stat_tile("0", "saved pages"),
            "notes": components.stat_tile("0", "notes"),
            "tasks": components.stat_tile("0", "tasks"),
        }
        layout.addWidget(components.stat_row(list(self.library_stats.values())))

        shelf_card, shelf_layout = _panel("Browse your shelf", "Open any item to continue where you left off")
        self.lbl_summary = QLabel("Preparing your shelf...")
        self.lbl_summary.setObjectName("MutedLabel")
        shelf_layout.addWidget(self.lbl_summary)

        self.list_widget = QListWidget()
        self.list_widget.setObjectName("CafeList")
        self.list_widget.setSpacing(2)
        shelf_layout.addWidget(self.list_widget, 1)
        layout.addWidget(shelf_card, 1)

        self.ed_search.returnPressed.connect(self.refresh)
        self.btn_refresh.clicked.connect(self.refresh)
        self.list_widget.itemDoubleClicked.connect(self._open_item)

    def _set_library_filter(self, value: str):
        self._library_filter = value
        for key, button in self.library_filter_buttons.items():
            button.blockSignals(True)
            button.setChecked(key == value)
            button.blockSignals(False)
        self.refresh()

    @staticmethod
    def _matches_library_filter(item: dict, value: str) -> bool:
        if value == "all":
            return True
        kind = (item.get("kind") or "").lower()
        mapping = {
            "pages": {"saved-page", "browser-visit", "bookmark"},
            "notes": {"note", "vault_note"},
            "tasks": {"task"},
            "events": {"event", "calendar"},
            "boards": {"board", "board-node"},
        }
        return kind in mapping.get(value, set())

    def refresh(self, query: str | None = None):
        q = query if query is not None else self.ed_search.text().strip()
        self.ed_search.setText(q)
        items = []
        if q:
            items.extend(life_service.search_everything(self.shell.profile_dir, q))
            for score, doc in retriever.search(self.shell.profile_dir, q, top_k=10):
                mapped_kind = doc.source
                mapped_id = doc.url
                subtitle = doc.url or doc.snippet
                if doc.source == "vault_note":
                    mapped_kind = "note"
                    mapped_id = doc.meta.get("note_id", "")
                    subtitle = doc.snippet
                elif doc.source == "task":
                    mapped_kind = "task"
                    mapped_id = doc.meta.get("task_id", "")
                elif doc.source == "calendar":
                    mapped_kind = "event"
                    mapped_id = doc.meta.get("event_id", "")
                elif doc.source == "board":
                    mapped_kind = "board"
                    mapped_id = doc.meta.get("board_id", "")
                elif doc.source == "board_note":
                    mapped_kind = "board-node"
                    mapped_id = doc.meta.get("board_id", "")
                elif doc.source == "saved_page":
                    mapped_kind = "saved-page"
                    mapped_id = doc.meta.get("saved_page_id", "")
                items.append({"kind": mapped_kind, "title": doc.title or doc.url, "id": mapped_id, "subtitle": subtitle})
            items = _dedupe_library_items(items)
        else:
            for page in life_service.load_saved_pages(self.shell.profile_dir)[:20]:
                items.append({"kind": "saved-page", "title": page.get("title", ""), "id": page.get("id", ""), "subtitle": page.get("url", "")})
            for note in personal_service.list_notes(self.shell.profile_dir)[:20]:
                items.append({"kind": "note", "title": note.get("title", ""), "id": note.get("id", ""), "subtitle": note.get("snippet", "")})
            for task in life_service.load_tasks(self.shell.profile_dir)[:20]:
                items.append({"kind": "task", "title": task.get("title", ""), "id": task.get("id", ""), "subtitle": task.get("bucket", "")})
        items = [item for item in items if self._matches_library_filter(item, self._library_filter)]
        self._last_results = items
        self.list_widget.clear()
        for item in items:
            list_item = _activity_item(
                item.get("kind", ""),
                item.get("title", ""),
                item.get("subtitle", ""),
            )
            list_item.setData(Qt.UserRole, item)
            self.list_widget.addItem(list_item)
        if self.list_widget.count() == 0:
            empty = QListWidgetItem("No items matched this view.\nTry another shelf or a shorter search.")
            empty.setFlags(Qt.NoItemFlags)
            empty.setSizeHint(QSize(0, 54))
            self.list_widget.addItem(empty)
            self.lbl_summary.setText("No items matched this view.")
        else:
            scope = self.library_filter_buttons.get(self._library_filter).text().lower()
            self.lbl_summary.setText(f"{len(items)} {scope} ready to reopen")
        self.library_stats["results"]._value.setText(str(len(items)))
        self.library_stats["pages"]._value.setText(str(len(life_service.load_saved_pages(self.shell.profile_dir))))
        self.library_stats["notes"]._value.setText(str(len(personal_service.list_notes(self.shell.profile_dir))))
        self.library_stats["tasks"]._value.setText(str(len(life_service.load_tasks(self.shell.profile_dir))))

    def _open_item(self, item: QListWidgetItem):
        data = item.data(Qt.UserRole) or {}
        if data:
            self.shell.open_library_item(data)


class SettingsPage(QWidget):
    def __init__(self, shell):
        super().__init__()
        self.shell = shell
        self.setObjectName("SettingsWorkspace")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 18)
        layout.setSpacing(12)

        hero = QFrame()
        hero.setObjectName("HeroCard")
        hero_layout = QVBoxLayout(hero)
        hero_layout.setContentsMargins(16, 14, 16, 14)
        hero_layout.setSpacing(8)
        title_row = QHBoxLayout()
        title_row.addWidget(
            components.page_header(
                "Settings & Profile Center",
                "Shape your workspace, protect your data, and keep every device in step.",
            ),
            1,
        )
        self.lbl_settings_profile = components.badge("LOCAL PROFILE", "accent")
        title_row.addWidget(self.lbl_settings_profile, 0, Qt.AlignTop)
        hero_layout.addLayout(title_row)
        hero_note = QLabel("Your choices are saved to this profile. Changes to the theme take effect across the entire workspace.")
        hero_note.setObjectName("HeroSubtitle")
        hero_note.setWordWrap(True)
        hero_layout.addWidget(hero_note)
        layout.addWidget(hero)

        self.settings_scroll = QScrollArea()
        self.settings_scroll.setObjectName("SettingsScroll")
        self.settings_scroll.setWidgetResizable(True)
        self.settings_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        content = QWidget()
        content.setObjectName("SettingsContent")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 2, 0)
        content_layout.setSpacing(12)
        self.settings_scroll.setWidget(content)
        layout.addWidget(self.settings_scroll, 1)

        account_card = QFrame()
        account_card.setObjectName("SectionCard")
        account_layout = QVBoxLayout(account_card)
        account_layout.setContentsMargins(12, 12, 12, 12)
        account_layout.setSpacing(6)
        account_layout.addWidget(components.section_header("Account", "Profile identity & local sync readiness"))
        account_summary = QHBoxLayout()
        self.lbl_account_initial = QLabel("LB")
        self.lbl_account_initial.setObjectName("HeroBadge")
        self.lbl_account_initial.setMinimumWidth(42)
        self.lbl_account_initial.setAlignment(Qt.AlignCenter)
        account_summary.addWidget(self.lbl_account_initial, 0, Qt.AlignTop)
        account_copy = QVBoxLayout()
        self.lbl_account_summary = QLabel("Personal workspace")
        self.lbl_account_summary.setFont(components._font(13, components.WEIGHT_BOLD))
        account_copy.addWidget(self.lbl_account_summary)
        self.lbl_account_detail = QLabel("Stored locally on this device")
        self.lbl_account_detail.setObjectName("MutedLabel")
        account_copy.addWidget(self.lbl_account_detail)
        account_summary.addLayout(account_copy, 1)
        account_layout.addLayout(account_summary)
        self.ed_display_name = QLineEdit()
        self.ed_display_name.setPlaceholderText("Display name")
        self.ed_email = QLineEdit()
        self.ed_email.setPlaceholderText("Email")
        self.chk_sync_enabled = QCheckBox("Keep a local profile snapshot (no remote server yet)")
        account_layout.addWidget(self.ed_display_name)
        account_layout.addWidget(self.ed_email)
        account_layout.addWidget(self.chk_sync_enabled)
        self.btn_save_account = QPushButton("Save account")
        self.btn_save_account.setObjectName("TopAccentButton")
        account_layout.addWidget(self.btn_save_account, 0, Qt.AlignLeft)
        content_layout.addWidget(account_card)

        ui_card = QFrame()
        ui_card.setObjectName("SectionCard")
        ui_layout = QVBoxLayout(ui_card)
        ui_layout.setContentsMargins(12, 12, 12, 12)
        ui_layout.setSpacing(6)
        ui_layout.addWidget(components.section_header("Interface", "Density, theme, accent, and performance"))
        self.cmb_density = QComboBox()
        self.cmb_density.addItems(["compact", "comfortable", "tablet"])
        self.cmb_theme = QComboBox()
        # Pretty display names + a live color swatch per entry (a bare key
        # list like 'sand-day' told users nothing about the vibe).
        self._theme_ids = []
        for mode_id in sorted(theme.PALETTES.keys()):
            pal = theme._palette(mode_id, None)
            self.cmb_theme.addItem(theme.theme_display_name(mode_id))
            self._theme_ids.append(mode_id)
            pixmap = QPixmap(34, 18)
            pixmap.fill(QColor(pal["CARD_BG"]))
            painter = QPainter(pixmap)
            painter.setPen(QPen(QColor(pal["BORDER_SOFT"]), 1))
            painter.drawRect(0, 0, 33, 17)
            painter.setBrush(QColor(pal["ACCENT"]))
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(3, 4, 12, 10, 2, 2)
            painter.setBrush(QColor(pal["MAIN_BG_ALT"]))
            painter.drawRoundedRect(18, 4, 12, 10, 2, 2)
            painter.end()
            self.cmb_theme.setItemIcon(self.cmb_theme.count() - 1, QIcon(pixmap))
        self.cmb_accent = QComboBox()
        for accent_id in sorted(theme.ACCENTS.keys()):
            self.cmb_accent.addItem(theme.accent_display_name(accent_id))
            pixmap = QPixmap(24, 18)
            pixmap.fill(QColor("transparent"))
            painter = QPainter(pixmap)
            painter.setPen(QPen(QColor(theme._palette(theme.DEFAULT_THEME, None)["BORDER_SOFT"]), 1))
            painter.setBrush(QColor(theme.ACCENTS[accent_id][0]))
            painter.drawRoundedRect(3, 3, 18, 12, 4, 4)
            painter.end()
            self.cmb_accent.setItemIcon(self.cmb_accent.count() - 1, QIcon(pixmap))
        self.spin_max_live_tabs = QSpinBox()
        self.spin_max_live_tabs.setRange(1, 32)
        self.spin_max_live_tabs.setToolTip("Fewer live tabs = lighter RAM/CPU when hundreds of tabs are open.")
        self.chk_auto_theme = QCheckBox("Auto day / night (flips the café palette with the clock)")
        self.chk_auto_theme.setToolTip(
            "On: day palettes from 6:00 to 18:00, their night siblings otherwise.\n"
            "Pairs: Latte Cream ↔ Midnight Mocha, Sakura ↔ Ember Night, Matcha ↔ Matcha Night..."
        )
        controls_grid = QGridLayout()
        controls_grid.setContentsMargins(0, 0, 0, 0)
        controls_grid.setHorizontalSpacing(10)
        controls_grid.setVerticalSpacing(5)
        for column, (label, control) in enumerate(
            (
                ("Density", self.cmb_density),
                ("Theme", self.cmb_theme),
                ("Accent color", self.cmb_accent),
                ("Max live tabs", self.spin_max_live_tabs),
            )
        ):
            field = QWidget()
            field_layout = QVBoxLayout(field)
            field_layout.setContentsMargins(0, 0, 0, 0)
            field_layout.setSpacing(4)
            field_label = QLabel(label)
            field_label.setObjectName("MutedLabel")
            field_layout.addWidget(field_label)
            field_layout.addWidget(control)
            controls_grid.addWidget(field, 0, column)
            controls_grid.setColumnStretch(column, 1)
        ui_layout.addLayout(controls_grid)
        ui_layout.addWidget(self.chk_auto_theme)
        self.btn_save_ui = QPushButton("Apply UI preferences")
        self.btn_save_ui.setObjectName("TopAccentButton")
        ui_layout.addWidget(self.btn_save_ui, 0, Qt.AlignLeft)
        content_layout.addWidget(ui_card)

        extras_card = QFrame()
        extras_card.setObjectName("SectionCard")
        extras_layout = QVBoxLayout(extras_card)
        extras_layout.setContentsMargins(12, 12, 12, 12)
        extras_layout.setSpacing(6)
        extras_layout.addWidget(components.section_header("Interface extras", "Little touches you can turn on or off"))
        self.chk_new_tab_steam = QCheckBox("Animated steam on the new-tab café cup")
        self.chk_new_tab_greeting = QCheckBox("Café time-greeting on the new-tab hero")
        self.chk_show_brief = QCheckBox("Show Morning Brief card on Home")
        self.chk_shield = QCheckBox("🛡 Distraction Shield — always block social/autoplay hosts (also auto-on during focus pours)")
        extras_layout.addWidget(self.chk_new_tab_steam)
        extras_layout.addWidget(self.chk_new_tab_greeting)
        extras_layout.addWidget(self.chk_show_brief)
        extras_layout.addWidget(self.chk_shield)
        content_layout.addWidget(extras_card)

        sync_card = QFrame()
        sync_card.setObjectName("SectionCard")
        sync_layout = QVBoxLayout(sync_card)
        sync_layout.setContentsMargins(12, 12, 12, 12)
        sync_layout.setSpacing(6)
        sync_layout.addWidget(components.section_header("Self-hosted sync", "Push / pull your profile to your own endpoint"))
        sync_help = QLabel(
            "Point both machines at the same HTTP endpoint (a tiny API you run — see README). "
            "Data travels with a Bearer token; nothing is sent to any cloud."
        )
        sync_help.setWordWrap(True)
        sync_help.setObjectName("MutedLabel")
        sync_layout.addWidget(sync_help)
        self.chk_sync_enabled = QCheckBox("Enable sync")
        sync_layout.addWidget(self.chk_sync_enabled)
        sync_layout.addWidget(QLabel("Endpoint (e.g. http://192.168.1.10:8901)"))
        self.ed_sync_endpoint = QLineEdit()
        self.ed_sync_endpoint.setPlaceholderText("http://127.0.0.1:8901")
        sync_layout.addWidget(self.ed_sync_endpoint)
        sync_layout.addWidget(QLabel("Bearer token"))
        self.ed_sync_token = QLineEdit()
        self.ed_sync_token.setPlaceholderText("Shared secret")
        self.ed_sync_token.setEchoMode(QLineEdit.Password)
        sync_layout.addWidget(self.ed_sync_token)
        sync_row = QHBoxLayout()
        self.btn_sync_now = QPushButton("Sync now (push + pull)")
        self.btn_save_sync = QPushButton("Save sync settings")
        self.btn_save_sync.setObjectName("TopAccentButton")
        sync_row.addWidget(self.btn_sync_now)
        sync_row.addWidget(self.btn_save_sync)
        sync_row.addStretch(1)
        sync_layout.addLayout(sync_row)
        self.lbl_sync_status = QLabel("")
        self.lbl_sync_status.setWordWrap(True)
        self.lbl_sync_status.setObjectName("MutedLabel")
        sync_layout.addWidget(self.lbl_sync_status)
        content_layout.addWidget(sync_card)

        mobile_card = QFrame()
        mobile_card.setObjectName("SectionCard")
        mobile_layout = QVBoxLayout(mobile_card)
        mobile_layout.setContentsMargins(12, 12, 12, 12)
        mobile_layout.setSpacing(6)
        mobile_layout.addWidget(
            components.section_header("Mobile / Android bridge", "Phone ↔ desktop sync over HTTP + JSON")
        )
        mobile_help = QLabel(
            "Set the same token in the app and desktop. Enable “Listen on LAN” only on trusted "
            "networks; use your PC’s IPv4 in the app (e.g. 192.168.x.x)."
        )
        mobile_help.setWordWrap(True)
        mobile_help.setObjectName("MutedLabel")
        mobile_layout.addWidget(mobile_help)
        self.chk_mobile_bridge = QCheckBox("Enable mobile bridge receiver")
        mobile_layout.addWidget(self.chk_mobile_bridge)
        port_row = QHBoxLayout()
        port_row.addWidget(QLabel("Port"))
        self.spin_mobile_port = QSpinBox()
        self.spin_mobile_port.setRange(1, 65535)
        self.spin_mobile_port.setValue(prefs.MOBILE_BRIDGE_DEFAULT_PORT)
        port_row.addWidget(self.spin_mobile_port)
        port_row.addStretch(1)
        mobile_layout.addLayout(port_row)
        self.chk_mobile_lan = QCheckBox("Listen on LAN (0.0.0.0 — reachable from Wi‑Fi devices)")
        mobile_layout.addWidget(self.chk_mobile_lan)
        mobile_layout.addWidget(QLabel("Shared token (Bearer)"))
        self.ed_mobile_token = QLineEdit()
        self.ed_mobile_token.setPlaceholderText("Paste token or generate below")
        mobile_layout.addWidget(self.ed_mobile_token)
        self.lbl_mobile_status = QLabel("")
        self.lbl_mobile_status.setWordWrap(True)
        self.lbl_mobile_status.setObjectName("MutedLabel")
        self.lbl_mobile_status.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.lbl_mobile_status.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.lbl_mobile_status.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        self.lbl_mobile_status.setMinimumHeight(76)
        mobile_layout.addWidget(self.lbl_mobile_status)
        mobile_layout.addSpacing(4)
        token_row = QHBoxLayout()
        self.btn_mobile_token_gen = QPushButton("Generate token")
        self.btn_save_mobile = QPushButton("Save mobile bridge settings")
        self.btn_save_mobile.setObjectName("TopAccentButton")
        token_row.addWidget(self.btn_mobile_token_gen)
        token_row.addWidget(self.btn_save_mobile)
        token_row.addStretch(1)
        mobile_layout.addLayout(token_row)

        mobile_layout.addSpacing(6)
        mobile_layout.addWidget(
            components.section_header("Quick pairing", "Scan with Mei Remote or copy the code into the app")
        )
        self.btn_copy_pairing = QPushButton("Copy pairing code")
        self.btn_copy_pairing.setObjectName("TopAccentButton")
        mobile_layout.addWidget(self.btn_copy_pairing, 0, Qt.AlignLeft)
        self.lbl_pairing_code = QLabel("")
        self.lbl_pairing_code.setObjectName("MutedLabel")
        self.lbl_pairing_code.setWordWrap(True)
        self.lbl_pairing_code.setTextInteractionFlags(Qt.TextSelectableByMouse)
        mobile_layout.addWidget(self.lbl_pairing_code)
        self.lbl_pairing_qr = QLabel()
        self.lbl_pairing_qr.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.lbl_pairing_qr.setMinimumSize(220, 220)
        mobile_layout.addWidget(self.lbl_pairing_qr)
        content_layout.addWidget(mobile_card)

        backup_card = QFrame()
        backup_card.setObjectName("SectionCard")
        backup_layout = QVBoxLayout(backup_card)
        backup_layout.setContentsMargins(12, 12, 12, 12)
        backup_layout.setSpacing(6)
        backup_layout.addWidget(components.section_header("Data location & backup", "Where your profile lives"))
        self.lbl_backup_paths = QLabel("")
        self.lbl_backup_paths.setWordWrap(True)
        self.lbl_backup_paths.setObjectName("MutedLabel")
        self.lbl_backup_paths.setTextInteractionFlags(Qt.TextSelectableByMouse)
        backup_layout.addWidget(self.lbl_backup_paths)
        backup_hint = QLabel(
            "Use History → Export backup: .zip with profile.json + vault/; tick “Include BrowserData” "
            "there to pack WebEngine state in the same zip."
        )
        backup_hint.setWordWrap(True)
        backup_hint.setObjectName("MutedLabel")
        backup_layout.addWidget(backup_hint)
        open_row = QHBoxLayout()
        self.btn_open_profile_folder = QPushButton("Open profile folder")
        self.btn_open_data_folder = QPushButton("Open runtime data folder")
        open_row.addWidget(self.btn_open_profile_folder)
        open_row.addWidget(self.btn_open_data_folder)
        open_row.addStretch(1)
        backup_layout.addLayout(open_row)
        content_layout.addWidget(backup_card)

        guide_card = QFrame()
        guide_card.setObjectName("SectionCard")
        guide_layout = QVBoxLayout(guide_card)
        guide_layout.setContentsMargins(12, 12, 12, 12)
        guide_layout.setSpacing(6)
        guide_layout.addWidget(components.section_header("Help & Browser Tools", "Consolidated help panel"))
        guide_copy = QLabel("Open one consolidated help panel for shell commands, browser tools, AI workflow, and Personal Hub usage.")
        guide_copy.setWordWrap(True)
        guide_copy.setObjectName("MutedLabel")
        guide_layout.addWidget(guide_copy)
        self.btn_open_help_tools = QPushButton("Open help & browser tools")
        guide_layout.addWidget(self.btn_open_help_tools, 0, Qt.AlignLeft)
        content_layout.addWidget(guide_card)

        updates_card = QFrame()
        updates_card.setObjectName("SectionCard")
        updates_layout = QVBoxLayout(updates_card)
        updates_layout.setContentsMargins(12, 12, 12, 12)
        updates_layout.setSpacing(6)
        updates_layout.addWidget(components.section_header("App Updates", "Compare your installed build"))
        self.lbl_app_version = QLabel("")
        self.lbl_app_version.setObjectName("MutedLabel")
        updates_layout.addWidget(self.lbl_app_version)
        self.lbl_update_status = QLabel("Check for updates to compare your installed build with the latest published release.")
        self.lbl_update_status.setWordWrap(True)
        self.lbl_update_status.setObjectName("MutedLabel")
        updates_layout.addWidget(self.lbl_update_status)
        self.btn_check_updates = QPushButton("Check for updates")
        self.btn_install_update = QPushButton("Download and install update")
        self.btn_open_release_page = QPushButton("Open release page")
        self.btn_check_updates.setObjectName("TopAccentButton")
        update_actions = QHBoxLayout()
        update_actions.addWidget(self.btn_check_updates)
        update_actions.addWidget(self.btn_install_update)
        update_actions.addWidget(self.btn_open_release_page)
        update_actions.addStretch(1)
        updates_layout.addLayout(update_actions)
        content_layout.addWidget(updates_card)
        content_layout.addStretch(1)

        self.btn_save_account.clicked.connect(self.save_account)
        self.btn_save_ui.clicked.connect(self.save_ui)
        self.btn_sync_now.clicked.connect(self.sync_now)
        self.btn_save_sync.clicked.connect(self.save_sync)
        self.btn_mobile_token_gen.clicked.connect(self._generate_mobile_token)
        self.btn_save_mobile.clicked.connect(self.save_mobile_bridge)
        self.btn_copy_pairing.clicked.connect(self._copy_pairing)
        self.btn_open_help_tools.clicked.connect(lambda: dialogs.show_browser_control_center(self.shell.browser_page))
        self.btn_check_updates.clicked.connect(lambda: self.shell.run_update_check(manual=True))
        self.btn_install_update.clicked.connect(self.shell.install_available_update)
        self.btn_open_release_page.clicked.connect(lambda: self.shell.open_release_page())
        self.btn_open_profile_folder.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(self.shell.profile_dir))
        )
        self.btn_open_data_folder.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(app_paths.data_root(self.shell.app_dir)))
        )

    def refresh(self):
        account = life_service.load_sync_account(self.shell.profile_dir)
        state = life_service.load_sync_state(self.shell.profile_dir)
        prefs_data = prefs.load_prefs(self.shell.profile_dir)
        self.ed_display_name.setText(account.get("display_name", ""))
        self.ed_email.setText(account.get("email", ""))
        self.chk_sync_enabled.setChecked(bool(state.get("enabled")))
        display_name = (account.get("display_name") or "").strip()
        email = (account.get("email") or "").strip()
        identity = display_name or email or "Mei user"
        initials = "".join(part[0] for part in identity.replace("@", " ").split()[:2]).upper() or "LB"
        self.lbl_account_initial.setText(initials[:2])
        self.lbl_account_summary.setText(identity)
        sync_label = "Local snapshot enabled" if state.get("enabled") else "Stored locally on this device"
        self.lbl_account_detail.setText(sync_label)
        self.lbl_settings_profile.setText("LOCAL SNAPSHOT" if state.get("enabled") else "LOCAL PROFILE")
        density = prefs_data.get("shell_density", "comfortable")
        theme_name = prefs_data.get("shell_theme", theme.DEFAULT_THEME)
        accent = prefs_data.get("accent", "brass")
        idx = self.cmb_density.findText(density)
        if idx >= 0:
            self.cmb_density.setCurrentIndex(idx)
        # Theme/accent combos store pretty labels; map back through ids.
        try:
            theme_idx = self._theme_ids.index(theme_name)
            self.cmb_theme.setCurrentIndex(theme_idx)
        except (ValueError, AttributeError):
            pass
        accent_id = accent if accent in theme.ACCENTS else "brass"
        accent_idx = next(
            (i for i in range(self.cmb_accent.count()) if self.cmb_accent.itemText(i) == theme.accent_display_name(accent_id)),
            -1,
        )
        if accent_idx >= 0:
            self.cmb_accent.setCurrentIndex(accent_idx)
        self.spin_max_live_tabs.setValue(prefs.get_max_live_tabs(self.shell.profile_dir))
        self.chk_new_tab_steam.setChecked(prefs.get_new_tab_steam(self.shell.profile_dir))
        self.chk_new_tab_greeting.setChecked(prefs.get_new_tab_greeting(self.shell.profile_dir))
        self.chk_show_brief.setChecked(prefs.get_show_morning_brief(self.shell.profile_dir))
        self.chk_shield.setChecked(prefs.get_pref(self.shell.profile_dir, "shield_always_on", False))
        self.chk_auto_theme.setChecked(prefs.get_auto_theme(self.shell.profile_dir))
        self.chk_sync_enabled.setChecked(prefs.get_sync_enabled(self.shell.profile_dir))
        self.ed_sync_endpoint.setText(prefs.get_sync_endpoint(self.shell.profile_dir))
        self.ed_sync_token.setText(prefs.get_sync_token(self.shell.profile_dir))
        self._refresh_sync_status()
        self.lbl_app_version.setText(f"Installed version: {app_version.APP_VERSION}")
        self.lbl_update_status.setText(self.shell.update_status_text)
        self.btn_install_update.setEnabled(bool(getattr(self.shell, "_pending_update_info", None) and self.shell._pending_update_info.has_update))
        self.chk_mobile_bridge.setChecked(prefs.get_mobile_bridge_enabled(self.shell.profile_dir))
        self.spin_mobile_port.setValue(prefs.get_mobile_bridge_port(self.shell.profile_dir))
        self.chk_mobile_lan.setChecked(prefs.get_mobile_bridge_lan(self.shell.profile_dir))
        self.ed_mobile_token.setText(prefs.get_mobile_bridge_token(self.shell.profile_dir))
        self._refresh_mobile_bridge_status()
        self._refresh_pairing()
        profiles_root = app_paths.profiles_root(self.shell.app_dir)
        data_root = app_paths.data_root(self.shell.app_dir)
        self.lbl_backup_paths.setText(
            f"Active profile (notes, prefs, SafeVault, BrowserData, sessions):\n{self.shell.profile_dir}\n\n"
            f"Profiles root:\n{profiles_root}\n\n"
            f"Runtime data root:\n{data_root}"
        )

    def _local_ipv4_hint(self) -> str:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except OSError:
            return ""

    def _refresh_mobile_bridge_status(self):
        port = prefs.get_mobile_bridge_port(self.shell.profile_dir)
        lan = prefs.get_mobile_bridge_lan(self.shell.profile_dir)
        if android_bridge_service.is_running():
            ip_hint = self._local_ipv4_hint()
            if lan and ip_hint:
                self.lbl_mobile_status.setText(
                    f"Running — point the Android app at http://{ip_hint}:{port}/ (LAN). Emulator: http://10.0.2.2:{port}/"
                )
            elif lan:
                self.lbl_mobile_status.setText(f"Running on 0.0.0.0:{port} — use this PC’s LAN IPv4 in the app.")
            else:
                self.lbl_mobile_status.setText(f"Running on 127.0.0.1:{port} — phone must use LAN mode + firewall if testing from another device.")
        else:
            self.lbl_mobile_status.setText("Stopped — enable and save, or fix port conflict.")
        self.lbl_mobile_status.updateGeometry()
        parent = self.lbl_mobile_status.parentWidget()
        if parent and parent.layout():
            parent.layout().activate()

    def _refresh_pairing(self):
        self._current_pairing_code = android_bridge_service.pairing_code(
            self.shell.profile_dir, lan_ip=self._local_ipv4_hint()
        )
        self.lbl_pairing_code.setText(
            "Mã ghép nối (Mở Mei Remote → Cài đặt → Dán mã hoặc quét QR):\n" + self._current_pairing_code
        )
        try:
            png = android_bridge_service.pairing_qr_png(self._current_pairing_code)
            image = QImage.fromData(png, "PNG")
            self.lbl_pairing_qr.setPixmap(QPixmap.fromImage(image))
        except Exception:
            self.lbl_pairing_qr.clear()

    def _copy_pairing(self):
        code = getattr(self, "_current_pairing_code", "")
        if code:
            QGuiApplication.clipboard().setText(code)
            QMessageBox.information(self, "Quick pairing", "Pairing code copied — paste it into Mei Remote.")

    def _generate_mobile_token(self):
        self.ed_mobile_token.setText(prefs.generate_mobile_bridge_token())

    def save_mobile_bridge(self):
        prefs.set_mobile_bridge_enabled(self.shell.profile_dir, self.chk_mobile_bridge.isChecked())
        prefs.set_mobile_bridge_port(self.shell.profile_dir, self.spin_mobile_port.value())
        prefs.set_mobile_bridge_lan(self.shell.profile_dir, self.chk_mobile_lan.isChecked())
        token = self.ed_mobile_token.text().strip()
        if self.chk_mobile_bridge.isChecked() and not token:
            token = prefs.generate_mobile_bridge_token()
            self.ed_mobile_token.setText(token)
        prefs.set_mobile_bridge_token(self.shell.profile_dir, token)
        ok = android_bridge_service.restart(self.shell.profile_dir)
        self.shell.refresh_shell()
        self._refresh_mobile_bridge_status()
        self._refresh_pairing()
        if self.chk_mobile_bridge.isChecked() and not ok:
            QMessageBox.warning(self, "Mobile bridge", "Could not start the listener (port may be in use).")
        else:
            QMessageBox.information(self, "Mobile bridge", "Mobile bridge settings saved.")

    def save_account(self):
        life_service.save_sync_account(
            self.shell.profile_dir,
            self.ed_email.text().strip(),
            self.ed_display_name.text().strip(),
            enabled=self.chk_sync_enabled.isChecked(),
        )
        self.shell.refresh_shell()
        QMessageBox.information(self, "Settings", "Profile account state saved.")

    def _refresh_sync_status(self):
        from litebrowser.services import sync_service
        last = sync_service.last_sync(self.shell.profile_dir)
        if last:
            self.lbl_sync_status.setText("Last sync: %s" % _time_utils.format_ts(last))
        else:
            self.lbl_sync_status.setText("Never synced yet — save settings, then press \u201cSync now\u201d.")

    def save_sync(self):
        prefs.set_sync_enabled(self.shell.profile_dir, self.chk_sync_enabled.isChecked())
        prefs.set_sync_endpoint(self.shell.profile_dir, self.ed_sync_endpoint.text())
        prefs.set_sync_token(self.shell.profile_dir, self.ed_sync_token.text())
        self.shell.refresh_shell()
        QMessageBox.information(self, "Sync", "Sync settings saved.")

    def sync_now(self):
        from litebrowser.services import sync_service
        endpoint = self.ed_sync_endpoint.text().strip()
        token = self.ed_sync_token.text().strip()
        ok, msg = sync_service.sync_now(self.shell.profile_dir, endpoint, token)
        self._refresh_sync_status()
        QMessageBox.information(self, "Sync", msg if ok else msg)

    def save_ui(self):
        # Combos carry display labels; map back to stable theme/accent ids.
        try:
            theme_id = self._theme_ids[self.cmb_theme.currentIndex()]
        except (AttributeError, IndexError):
            theme_id = theme.DEFAULT_THEME
        selected_label = self.cmb_accent.currentText()
        accent_id = next(
            (key for key in theme.ACCENTS if theme.accent_display_name(key) == selected_label),
            "brass",
        )
        prefs.set_shell_theme(self.shell.profile_dir, theme_id)
        prefs.set_accent(self.shell.profile_dir, accent_id)
        prefs.set_max_live_tabs(self.shell.profile_dir, self.spin_max_live_tabs.value())
        prefs.set_new_tab_steam(self.shell.profile_dir, self.chk_new_tab_steam.isChecked())
        prefs.set_new_tab_greeting(self.shell.profile_dir, self.chk_new_tab_greeting.isChecked())
        prefs.set_show_morning_brief(self.shell.profile_dir, self.chk_show_brief.isChecked())
        prefs.save_pref(self.shell.profile_dir, "shield_always_on", self.chk_shield.isChecked())
        prefs.set_auto_theme(self.shell.profile_dir, self.chk_auto_theme.isChecked())
        # Keep the shell's auto-theme watcher in sync with the new setting.
        if hasattr(self.shell, "_sync_auto_theme_timer"):
            self.shell._sync_auto_theme_timer()
        data = prefs.load_prefs(self.shell.profile_dir)
        data["shell_density"] = self.cmb_density.currentText()
        prefs.save_prefs(self.shell.profile_dir, data)
        self.shell.refresh_shell()
        QMessageBox.information(self, "Settings", "UI preferences saved.")


class HistoryPage(QWidget):
    def __init__(self, shell):
        super().__init__()
        self.shell = shell
        self.setObjectName("HistoryWorkspace")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 18)
        layout.setSpacing(12)

        hero = QFrame()
        hero.setObjectName("HeroCard")
        hero_layout = QVBoxLayout(hero)
        hero_layout.setContentsMargins(16, 14, 16, 14)
        hero_layout.setSpacing(8)
        title_row = QHBoxLayout()
        page = components.page_header("Activity History", "Every saved action, kept readable and close at hand")
        title_row.addWidget(page, 1)
        self.lbl_history_scope = components.badge("ALL ACTIVITY", "accent")
        title_row.addWidget(self.lbl_history_scope, 0, Qt.AlignTop)
        hero_layout.addLayout(title_row)

        controls_row = QHBoxLayout()
        controls_row.setSpacing(8)
        self.cmb_kind = QComboBox()
        self.cmb_kind.addItems(["all", "browser-visit", "bookmark", "note", "task", "calendar", "board", "download", "saved-page", "ai-question", "account"])
        controls_row.addWidget(self.cmb_kind)
        self.ed_search = QLineEdit()
        self.ed_search.setPlaceholderText("Search URLs, notes, tasks, AI questions, downloads, boards...")
        self.ed_search.setMinimumWidth(240)
        controls_row.addWidget(self.ed_search, 1)
        self.btn_refresh = QPushButton("Refresh")
        self.btn_export = QPushButton("Export backup")
        self.btn_import = QPushButton("Import backup")
        self.btn_clear_activity = QPushButton("Clear all")
        self.btn_refresh.setObjectName("TopAccentButton")
        controls_row.addWidget(self.btn_refresh)
        controls_row.addWidget(self.btn_export)
        controls_row.addWidget(self.btn_import)
        controls_row.addWidget(self.btn_clear_activity)
        hero_layout.addLayout(controls_row)
        layout.addWidget(hero)

        self.history_stats = {
            "all": components.stat_tile("0", "activity records"),
            "visits": components.stat_tile("0", "browser visits"),
            "workspace": components.stat_tile("0", "workspace updates"),
        }
        layout.addWidget(components.stat_row(list(self.history_stats.values())))

        self.lbl_summary = QLabel("")
        self.lbl_summary.setObjectName("MutedLabel")
        activity_card, activity_layout = _panel(
            "Your activity",
            "A readable timeline of browser visits and workspace changes",
        )
        activity_layout.addWidget(self.lbl_summary)

        self.chk_zip_include_browser_data = QCheckBox(
            "Include BrowserData in zip (WebEngine cache, localStorage for sites like Cục Quản Lý — large & slow)"
        )
        self.chk_zip_include_browser_data.setObjectName("MutedLabel")
        layout.addWidget(self.chk_zip_include_browser_data)

        self.list_widget = QListWidget()
        self.list_widget.setObjectName("CafeList")
        self.list_widget.setSpacing(2)
        activity_layout.addWidget(self.list_widget, 1)
        layout.addWidget(activity_card, 1)

        self.ed_search.returnPressed.connect(self.refresh)
        self.cmb_kind.currentIndexChanged.connect(self.refresh)
        self.btn_refresh.clicked.connect(self.refresh)
        self.btn_export.clicked.connect(self.export_backup)
        self.btn_import.clicked.connect(self.import_backup)
        self.btn_clear_activity.clicked.connect(self.clear_activity)

    def clear_activity(self):
        if QMessageBox.question(
            self,
            "History",
            "Delete ALL activity records? This cannot be undone.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        ) != QMessageBox.Yes:
            return
        removed = history_service.clear_activity(self.shell.profile_dir)
        self.refresh()
        QMessageBox.information(self, "History", "Cleared %d activity records." % removed)

    def refresh(self):
        kind = self.cmb_kind.currentText()
        query = self.ed_search.text().strip()
        items = history_service.list_activity(self.shell.profile_dir, query=query, kind="" if kind == "all" else kind)
        self.list_widget.clear()
        for item in items:
            stamp = _format_ts(int(item.get("ts", 0) or 0))
            row = _activity_item(item.get("kind", ""), item.get("title", ""), item.get("detail", ""), stamp)
            row.setData(Qt.UserRole, item)
            self.list_widget.addItem(row)
        if self.list_widget.count() == 0:
            self.list_widget.addItem("No activity matched your search.")
        self.lbl_summary.setText(
            f"{len(items)} activity records · Zip export: profile.json + vault/. Optionally tick below to also pack "
            "BrowserData/ (full in-browser state). JSON export inlines vault as base64. Import restores zip contents; "
            "restart the app after import if BrowserData was included."
        )

    def export_backup(self):
        default = os.path.join(self.shell.profile_dir, f"litebrowser-profile-backup-{time.strftime('%Y%m%d-%H%M')}.zip")
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Export profile backup", default, "Zip bundle (*.zip);;JSON (*.json)"
        )
        if not file_path:
            return
        lower = file_path.lower()
        if lower.endswith(".json"):
            payload = history_service.export_profile_payload(self.shell.profile_dir, inline_vault_files=True)
            storage_utils.write_json(file_path, payload)
        else:
            if not lower.endswith(".zip"):
                file_path = file_path + ".zip"
            inc_bd = self.chk_zip_include_browser_data.isChecked()
            if inc_bd:
                confirm = QMessageBox.question(
                    self,
                    "Export backup",
                    "Including BrowserData can create a very large archive and take a long time. Continue?",
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.Yes,
                )
                if confirm != QMessageBox.Yes:
                    return
            if not history_service.export_profile_to_zip(
                self.shell.profile_dir, file_path, include_browser_data=inc_bd
            ):
                QMessageBox.warning(self, "History", "Could not write the backup zip file.")
                return
        QMessageBox.information(self, "History", "Profile backup exported successfully.")

    def import_backup(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Import profile backup", "", "Backup (*.zip *.json);;Zip (*.zip);;JSON (*.json)"
        )
        if not file_path:
            return
        if not history_service.import_profile_from_path(self.shell.profile_dir, file_path):
            QMessageBox.warning(self, "History", "Backup file is not valid.")
            return
        self.shell.refresh_shell()
        self.refresh()
        msg = "Profile backup imported. Your data has been restored into this profile."
        if file_path.lower().endswith(".zip"):
            msg += "\n\nIf this backup included BrowserData, close and restart Mei so WebEngine loads the restored profile cleanly."
        QMessageBox.information(self, "History", msg)
