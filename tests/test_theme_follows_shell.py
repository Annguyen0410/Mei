"""One theme, everywhere: widgets must paint the palette the shell is *showing*.

The bug this file locks down: ``prefs.get_shell_theme`` returns the *stored*
choice, and with auto day/night on the shell paints a sibling the stored name does
not mention. Everything that resolved the stored name at night kept day colours
inside a night window:

* the two dashboard charts ("Your Week", "Where time goes") painted a light card,
* the tab desk painted near-black tab titles on a near-black panel,
* the connection pill painted a light chip in the dark toolbar,
* the speed dial was generated with a bright palette.

Each case is covered below against a profile configured exactly like the one that
reported it: ``shell_theme = rose-day`` (light) with ``auto_theme = True`` at 22:00.
"""
import os
import tempfile
import time
import types
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# The shim must be active before the binding is imported (see test_browser_topbar).
import litebrowser  # noqa: F401 - litebrowser/__init__ activates the Qt shim
from litebrowser.qt import QtCore, QtWidgets

from litebrowser.browser.tab_manager import (
    TAB_META_ROLE,
    TAB_WIDGET_ROLE,
    TabListItemWidget,
    TabManager,
)
from litebrowser.core import prefs, theme_data
from litebrowser.ui import theme

QApplication = QtWidgets.QApplication
QListWidget = QtWidgets.QListWidget
QListWidgetItem = QtWidgets.QListWidgetItem

_app = QApplication.instance() or QApplication(["mei-tests"])

DAY_THEME = "rose-day"
NIGHT_THEME = "midnight-ember"  # rose-day's night sibling in prefs.resolved_auto_theme


def _at(hour: int):
    """Freeze prefs' clock at ``hour`` (auto day/night flips at 06:00/18:00)."""
    return mock.patch.object(
        prefs.time, "localtime", return_value=time.struct_time((2026, 9, 24, hour, 0, 0, 0, 0, -1))
    )


class _ThemeFollowHost(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="mei_themefollow_")
        self.base = os.path.join(self._tmp, "profile")
        prefs.ensure_profile_layout(self.base)
        prefs.set_shell_theme(self.base, DAY_THEME)
        prefs.set_auto_theme(self.base, True)

    def tearDown(self):
        prefs.set_default_base_dir("")


class TestRendererPaletteFollowsTheShell(_ThemeFollowHost):
    """``theme.palette()`` is what the dashboard charts paint with."""

    def test_it_resolves_the_night_sibling_after_dark(self):
        prefs.set_default_base_dir(self.base)
        with _at(22):
            palette = theme.palette()
        self.assertEqual(palette["MAIN_BG_ALT"], theme_data._palette(NIGHT_THEME)["MAIN_BG_ALT"])
        self.assertNotEqual(palette["MAIN_BG_ALT"], theme_data._palette(DAY_THEME)["MAIN_BG_ALT"])

    def test_it_returns_to_the_day_palette_in_the_morning(self):
        prefs.set_default_base_dir(self.base)
        with _at(9):
            palette = theme.palette()
        self.assertEqual(palette["MAIN_BG_ALT"], theme_data._palette(DAY_THEME)["MAIN_BG_ALT"])

    def test_a_night_palette_is_recognised_as_dark(self):
        self.assertTrue(theme_data.is_night_theme(NIGHT_THEME))
        self.assertFalse(theme_data.is_night_theme(DAY_THEME))


class TestRendererPaletteFollowsTheAccent(_ThemeFollowHost):
    """The other half of the same bug: accent, not just mode.

    Reported from a screenshot: a profile on ``cafe-night`` with the **rose**
    accent, whose "Your Week" chart drew a gold bar (the palette's stock accent)
    inside a window whose buttons, chips and active nav row were rose — the same
    app in two colours. The shell QSS is built with
    ``prefs.get_accent(profile_dir)``; ``theme.palette()`` resolved the palette
    alone, so every hand-painted widget was the odd one out.

    Auto day/night is off here on purpose: the subject is the accent, and a test
    that reads the clock fails on whichever runner is in the other half of the
    day — CI runs at ~06:2x UTC, this machine at ~23:xx local.
    """

    def setUp(self):
        super().setUp()
        prefs.set_auto_theme(self.base, False)
        prefs.set_shell_theme(self.base, "cafe-night")
        prefs.set_default_base_dir(self.base)

    def test_the_default_palette_carries_the_profiles_accent(self):
        prefs.set_accent(self.base, "rose")
        palette = theme.palette()
        stock = theme_data._palette("cafe-night")  # guard: the stock accent differs
        self.assertNotEqual(theme_data.ACCENTS["rose"][0], stock["ACCENT"])
        self.assertEqual(palette["ACCENT"], theme_data.ACCENTS["rose"][0])
        self.assertEqual(palette["ACCENT_HOVER"], theme_data.ACCENTS["rose"][1])

    def test_an_explicit_accent_still_wins(self):
        prefs.set_accent(self.base, "rose")
        self.assertEqual(theme.palette(accent="teal")["ACCENT"], theme_data.ACCENTS["teal"][0])

    def test_an_empty_accent_means_the_palettes_own(self):
        prefs.set_accent(self.base, "rose")
        self.assertEqual(theme.palette(accent="")["ACCENT"], theme_data._palette("cafe-night")["ACCENT"])

    def test_a_widget_can_ask_for_another_profile(self):
        other = os.path.join(self._tmp, "second")
        prefs.ensure_profile_layout(other)
        prefs.set_auto_theme(other, False)
        prefs.set_shell_theme(other, NIGHT_THEME)
        prefs.set_accent(other, "violet")
        prefs.set_accent(self.base, "rose")
        self.assertEqual(theme.palette(base_dir=other)["ACCENT"], theme_data.ACCENTS["violet"][0])
        self.assertEqual(theme.palette()["ACCENT"], theme_data.ACCENTS["rose"][0])

    def test_a_bar_is_the_accent_not_the_button_token(self):
        """``ACCENT_SOFT`` is a button surface, not a chart fill.

        On night palettes it is deliberately dark (``ACCENT_HOVER`` text sits on
        it), so as a bar it read as mud. The bar rule keeps the accent's own
        RGB and only drops the opacity, which works in every palette.
        """
        for mode in ("cafe-night", NIGHT_THEME, DAY_THEME):
            tokens = theme_data._palette(mode, "rose")
            today = theme.accent_bar_color(tokens, True)
            past = theme.accent_bar_color(tokens, False)
            with self.subTest(mode=mode):
                self.assertEqual(today.name(), tokens["ACCENT"].lower())
                self.assertEqual(today.alphaF(), 1.0)
                self.assertEqual(past.name(), tokens["ACCENT"].lower())
                self.assertLess(past.alphaF(), 1.0)
                self.assertGreater(past.alphaF(), 0.3)
                self.assertNotEqual(past.name(), tokens["ACCENT_SOFT"].lower())


class TestChartCardsAreOneSurface(_ThemeFollowHost):
    """Rendered pixels: a chart canvas must not be a second colour inside its card.

    The reported bug (twice, once per theme family): the "Your Week" and "Where
    time goes" widgets filled their whole rect with MAIN_BG_ALT while the
    #SectionCard around them painted CARD_BG.  Every other card on the dashboard
    matched, so those two read as "a different colour" as soon as the user
    switched theme — pink blocks on rose-day, off-black blocks on cafe-night.
    """

    def setUp(self):
        super().setUp()
        prefs.set_auto_theme(self.base, False)
        prefs.set_default_base_dir(self.base)

    def _corner_pixels(self, mode):
        """Paint each dashboard chart inside a real card and read the canvas."""
        from litebrowser.ui.shell.pages import _DomainWeekChart, _WeekActivityChart

        prefs.set_shell_theme(self.base, mode)
        page = types.SimpleNamespace(shell=types.SimpleNamespace(profile_dir=self.base))
        previous = _app.styleSheet()
        _app.setStyleSheet(theme.main_qss(mode))
        try:
            corners = {}
            for name, chart_cls in (("week", _WeekActivityChart), ("domains", _DomainWeekChart)):
                root = QtWidgets.QWidget()
                root.setObjectName("HomeScrollContent")
                root_layout = QtWidgets.QVBoxLayout(root)
                root_layout.setContentsMargins(0, 0, 0, 0)
                card = QtWidgets.QFrame()
                card.setObjectName("SectionCard")
                card_layout = QtWidgets.QVBoxLayout(card)
                card_layout.setContentsMargins(14, 12, 14, 12)
                chart = chart_cls(page)
                card_layout.addWidget(chart, 1)
                root_layout.addWidget(card, 1)
                root.resize(600, 320)
                root.show()
                _app.processEvents()
                image = root.grab().toImage()
                # Top-left of the canvas: no bar, label or value text lands there.
                origin = chart.mapTo(root, QtCore.QPoint(0, 0))
                corners[name] = image.pixelColor(origin.x() + 3, origin.y() + 3).name()
                root.close()
            return corners
        finally:
            _app.setStyleSheet(previous)

    def _rendered_week_chart(self, mode, accent, size=(600, 320)):
        """Render the "Your Week" chart inside a real #SectionCard, with visits.

        Inside a card on purpose: the chart canvas is transparent, so a grab of
        the widget alone composites the bars onto nothing and the blend below
        becomes untestable.
        """
        import time as _time

        from litebrowser.ui.shell.pages import _WeekActivityChart

        prefs.set_shell_theme(self.base, mode)
        prefs.set_accent(self.base, accent)
        now = int(_time.time())
        prefs.save_history_entries(
            self.base,
            [(now, "https://example.com/a"), (now, "https://example.com/b"), (now - 86400, "https://example.com/c")],
        )
        page = types.SimpleNamespace(shell=types.SimpleNamespace(profile_dir=self.base))
        previous = _app.styleSheet()
        _app.setStyleSheet(theme.main_qss(mode, accent))
        try:
            root = QtWidgets.QWidget()
            root.setObjectName("HomeScrollContent")
            root_layout = QtWidgets.QVBoxLayout(root)
            root_layout.setContentsMargins(0, 0, 0, 0)
            card = QtWidgets.QFrame()
            card.setObjectName("SectionCard")
            card_layout = QtWidgets.QVBoxLayout(card)
            card_layout.setContentsMargins(14, 12, 14, 12)
            chart = _WeekActivityChart(page)
            card_layout.addWidget(chart, 1)
            root_layout.addWidget(card, 1)
            root.resize(*size)
            root.show()
            _app.processEvents()
            chart.refresh()
            _app.processEvents()
            image = root.grab().toImage()
            root.close()
        finally:
            _app.setStyleSheet(previous)
        return image, theme_data._palette(mode, accent)

    def test_the_bars_paint_the_profiles_accent(self):
        """Pixels, not tokens: the reported bug was visible colour, not a value."""
        for mode in ("cafe-night", DAY_THEME):
            image, tokens = self._rendered_week_chart(mode, "rose")
            accent = tokens["ACCENT"].lower()
            stock = theme_data._palette(mode)["ACCENT"].lower()
            card = tokens["CARD_BG"].lower()
            colours = [
                image.pixelColor(x, y).name()
                for x in range(0, image.width(), 2)
                for y in range(0, image.height(), 2)
            ]
            with self.subTest(mode=mode):
                self.assertNotEqual(accent, stock, "guard: rose and the stock accent differ")
                self.assertIn(accent, colours, "the today bar must be the profile accent")
                self.assertNotIn(stock, colours, "and never the palette's own accent")
                # A past day is the same hue at reduced opacity, so its pixels are
                # a blend of the accent over the card: neither the accent itself
                # nor the card, and never the near-invisible ACCENT_SOFT token.
                self.assertNotIn(
                    tokens["ACCENT_SOFT"].lower(), colours, "the button token must not be a bar fill"
                )
                nearby = [
                    colour
                    for colour in colours
                    if colour not in (accent, card) and self._close_to_blend(colour, accent, card, 0.55, 14)
                ]
                self.assertTrue(nearby, "a past-day bar should be a softened accent, not mud")

    @staticmethod
    def _close_to_blend(colour, accent, back, alpha, tolerance):
        def channel(value, index):
            return int(value.lstrip("#")[index * 2:index * 2 + 2], 16)

        for index in range(3):
            blended = channel(back, index) + (channel(accent, index) - channel(back, index)) * alpha
            if abs(channel(colour, index) - blended) > tolerance:
                return False
        return True

    def test_the_canvas_paints_with_the_card_colour(self):
        for mode in ("cafe-night", DAY_THEME):
            palette = theme_data._palette(mode)
            # Guard: on this theme the two tokens differ, so the assert can fail.
            self.assertNotEqual(palette["CARD_BG"].lower(), palette["MAIN_BG_ALT"].lower())
            for name, colour in self._corner_pixels(mode).items():
                self.assertEqual(colour.lower(), palette["CARD_BG"].lower(), f"{mode} {name} chart canvas")


class _DeskHost:
    """Minimal host for the real TabManager theme path (no QWebEngine surface)."""

    # The real methods: refresh_theme delegates the per-state title tints to them.
    _apply_hibernated_visual = TabManager._apply_hibernated_visual
    _clear_hibernated_visual = TabManager._clear_hibernated_visual
    _apply_group_visual = TabManager._apply_group_visual
    _widget_for_item = TabManager._widget_for_item

    def __init__(self, base_dir, tab_list):
        self.base_dir = base_dir
        self.tab_list = tab_list
        self.browsers = [None]
        self._mem_tip = None
        self._pal = theme_data._palette(NIGHT_THEME)

    def row_state_text(self, _row_index):
        return ""


class TestTabDeskFollowsTheShell(_ThemeFollowHost):
    """Tab rows carry inline styles, so the stylesheet alone never reaches them."""

    def _row(self, title="Docs"):
        manager = types.SimpleNamespace(base_dir=self.base)
        item = QListWidgetItem()
        widget = TabListItemWidget(manager, item, title)
        item.setData(TAB_WIDGET_ROLE, widget)
        item.setData(TAB_META_ROLE, {"title": title, "url": "https://example.com", "hibernated": False})
        return item, widget

    def test_a_row_built_at_night_uses_the_night_text_colour(self):
        with _at(22):
            _item, widget = self._row()
        self.assertIn(theme_data._palette(NIGHT_THEME)["TEXT"], widget.lbl_title.styleSheet())

    def test_a_row_built_by_day_uses_the_day_text_colour(self):
        with _at(10):
            _item, widget = self._row()
        self.assertIn(theme_data._palette(DAY_THEME)["TEXT"], widget.lbl_title.styleSheet())

    def test_refresh_theme_repaints_existing_rows(self):
        """The desk must not keep yesterday's colours after the shell flips."""
        with _at(22):
            item, widget = self._row()
        self.assertIn(theme_data._palette(NIGHT_THEME)["TEXT"], widget.lbl_title.styleSheet())

        tab_list = QListWidget()
        tab_list.addItem(item)
        host = _DeskHost(self.base, tab_list)
        with _at(10):
            TabManager.refresh_theme(host)
        self.assertIn(theme_data._palette(DAY_THEME)["TEXT"], widget.lbl_title.styleSheet())
        self.assertNotIn(theme_data._palette(NIGHT_THEME)["TEXT"], widget.lbl_title.styleSheet())


class TestSpeedDialFollowsTheShell(_ThemeFollowHost):
    """The page the app renders itself (about:newtab) must match the window."""

    def test_the_page_painted_after_dark_uses_the_night_palette(self):
        from litebrowser.browser import new_tab_page

        with _at(22):
            html = new_tab_page.build_new_tab_html(self.base)
        night = theme_data._palette(NIGHT_THEME)
        day = theme_data._palette(DAY_THEME)
        self.assertIn(night["MAIN_BG"], html)
        self.assertNotIn(day["MAIN_BG"], html)

    def test_an_explicitly_dark_theme_does_not_need_auto_mode(self):
        from litebrowser.browser import new_tab_page

        prefs.set_auto_theme(self.base, False)
        prefs.set_shell_theme(self.base, "cafe-night")
        html = new_tab_page.build_new_tab_html(self.base)
        self.assertIn(theme_data._palette("cafe-night")["MAIN_BG"], html)


class TestDarkWebFollowsTheShell(_ThemeFollowHost):
    """Web pages follow the shell's light/dark mode until the user decides."""

    def test_unset_flag_follows_the_clock(self):
        with _at(22):
            self.assertTrue(prefs.effective_force_dark_web(self.base))
        with _at(10):
            self.assertFalse(prefs.effective_force_dark_web(self.base))

    def test_an_explicit_choice_wins_at_any_hour(self):
        prefs.set_force_dark_web(self.base, False)
        with _at(22):
            self.assertFalse(prefs.effective_force_dark_web(self.base))
        prefs.set_force_dark_web(self.base, True)
        with _at(10):
            self.assertTrue(prefs.effective_force_dark_web(self.base))

    def test_auto_day_night_off_means_no_surprise_dark_pages(self):
        prefs.set_auto_theme(self.base, False)
        prefs.set_shell_theme(self.base, DAY_THEME)
        self.assertFalse(prefs.effective_force_dark_web(self.base))

    def test_a_night_theme_alone_is_enough(self):
        prefs.set_auto_theme(self.base, False)
        prefs.set_shell_theme(self.base, "cafe-night")
        self.assertTrue(prefs.effective_force_dark_web(self.base))


if __name__ == "__main__":
    unittest.main()
