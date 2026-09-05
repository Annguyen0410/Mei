"""Personal-space extraction (was 2900+ lines).

FocusHeatmap paints a 12-week daily streak strip with a month date axis;
ReviewMixin owns the flashcard review page (queue, flip, SM-2 grading,
keyboard shortcuts). They only touch attributes PersonalWindow already owns
(base_dir, nav_buttons, _flash).
"""

from PyQt5.QtCore import QSize, Qt
from PyQt5.QtGui import QColor, QFontMetrics, QPainter, QPen
from PyQt5.QtWidgets import QWidget

from litebrowser.core import prefs
from litebrowser.services import focus_service
from litebrowser.ui import theme

_DAYS = 12 * 7  # twelve weeks, one cell per day, oldest → today
_GAP = 1  # px between neighbouring days
_WEEK_GAP = 6  # extra px between week blocks (GitHub-contribution style)
_CELL_MIN = 4
_CELL_MAX = 18
_MARGIN = 16  # horizontal padding around the strip
_TITLE_TOP = 15  # baseline of the streak headline
_AXIS_TOP = 25  # top of the month date-axis text
_STRIP_TOP = _AXIS_TOP + 13  # y of the row of day cells
_BOTTOM_PAD = 8
_CAPTION_PAD = 15  # extra room for the "today" date caption under the strip


class FocusHeatmap(QWidget):
    """Horizontal daily-activity strip from focus_sessions.json.

    One square cell per calendar day (oldest on the left, today on the
    right), painted wide so it fills the card's horizontal space.  A month
    date-axis sits above the strip - labels read ``Jun 2026  Jul  Aug  Sep``
    - and today is ringed and captioned so the row reads as a real calendar
    instead of an anonymous bar.  Intensity follows minutes focused; the math
    lives in focus_service.compute_daily_minutes / compute_streaks so this
    view and the dashboard can never disagree.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._minutes = {}  # day-key -> minutes
        self._streak = 0
        self._longest = 0
        self._base_dir = ""
        self._tokens = None
        self.setToolTip("Focus minutes per day — keep the chain alive")
        self.setMinimumHeight(self._content_height(_CELL_MIN))

    def _resolve_palette(self, base_dir: str) -> dict:
        """Theme tokens for the profile hosting this widget.

        The dashboard re-polishes with the profile's *effective* theme (auto
        day/night included) and accent, so painting must follow the same
        resolution - not theme.palette(), which only reads the stored default
        profile theme and painted a light panel inside a dark dashboard.
        """
        try:
            mode = prefs.resolved_auto_theme(base_dir) if base_dir else prefs.get_shell_theme(base_dir)
            accent = prefs.get_accent(base_dir)
            return theme.palette_tokens(mode, accent)
        except Exception:
            return theme.palette()

    def refresh(self, base_dir: str):
        self._base_dir = base_dir or ""
        self._tokens = self._resolve_palette(self._base_dir)
        sessions = focus_service.focus_journal(self._base_dir, limit=200)
        self._minutes = focus_service.compute_daily_minutes(sessions)
        self._streak, self._longest = focus_service.compute_streaks(self._minutes)
        self.update()

    # -- sizing --------------------------------------------------------
    def _cell_size(self, width: int) -> int:
        separators = (_DAYS // 7 - 1) * _WEEK_GAP
        available = max(1, int(width) - 2 * _MARGIN - (_DAYS - 1) * _GAP - separators)
        return max(_CELL_MIN, min(_CELL_MAX, available // _DAYS))

    def _content_height(self, cell: int) -> int:
        extra = _CAPTION_PAD if cell >= 5 else 0
        return _STRIP_TOP + cell + _BOTTOM_PAD + extra

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width: int):
        return self._content_height(self._cell_size(width))

    def sizeHint(self):
        return QSize(560, self._content_height(_CELL_MAX))

    # -- painting ------------------------------------------------------
    def paintEvent(self, _event):
        import datetime as _dt

        painter = QPainter(self)
        p = self._tokens if isinstance(self._tokens, dict) else theme.palette()
        painter.fillRect(self.rect(), QColor(p["CARD_BG"]))

        cell = self._cell_size(self.width())
        today = _dt.date.today()

        title_font = painter.font()
        title_font.setBold(True)
        painter.setFont(title_font)
        painter.setPen(QColor(p["TEXT"]))
        painter.drawText(
            _MARGIN, _TITLE_TOP, f"🔥 Focus streak: {self._streak} days · longest {self._longest}"
        )

        # Column x positions; week blocks separated so the strip reads like a
        # GitHub contribution calendar rather than one dense line.
        x = _MARGIN
        cols = []
        for col in range(_DAYS):
            if col > 0 and col % 7 == 0:
                x += _WEEK_GAP
            cols.append((col, x))
            x += cell + _GAP

        # ---- month date-axis: label each month start, with the year on the
        # first label and on every January (reads as day/month/year).
        axis_font = painter.font()
        axis_font.setBold(False)
        if axis_font.pointSize() > 7:
            axis_font.setPointSize(axis_font.pointSize() - 1)
        painter.setFont(axis_font)
        fm = QFontMetrics(axis_font)
        prev_right = _MARGIN - 1
        shown_year = None
        for col, day_x in cols:
            days_back = _DAYS - 1 - col
            day = today - _dt.timedelta(days=days_back)
            is_month_start = day.day == 1
            if not is_month_start and col != 0:
                continue
            if is_month_start and shown_year is not None and day.year == shown_year:
                text = day.strftime("%b")
            else:
                text = day.strftime("%b %Y")
            shown_year = day.year
            text_w = fm.horizontalAdvance(text)
            if day_x < prev_right + 4:  # would collide with the previous label
                continue
            if day_x + text_w > self.width() - _MARGIN:  # would pass the padding
                break
            painter.setPen(QColor(p["TEXT_MUTED"]))
            painter.drawText(day_x, _AXIS_TOP, text)
            prev_right = day_x + text_w

        # ---- day cells: one square per calendar day ----
        max_minutes = max([1] + list(self._minutes.values()))
        today_col_x = None
        for col, day_x in cols:
            days_back = _DAYS - 1 - col
            day = today - _dt.timedelta(days=days_back)
            minutes = self._minutes.get(day.isoformat(), 0)
            if minutes <= 0:
                # Faint-but-visible block so the strip reads as a day
                # calendar instead of invisible gaps between active days.
                base = QColor(p["MAIN_BG_ALT"])
                color = QColor(
                    min(255, base.red() + 14),
                    min(255, base.green() + 14),
                    min(255, base.blue() + 14),
                )
            else:
                t = min(1.0, minutes / max_minutes)
                base = QColor(p["ACCENT"])
                soft = QColor(p["MAIN_BG_ALT"])
                color = QColor(
                    int(soft.red() + (base.red() - soft.red()) * t),
                    int(soft.green() + (base.green() - soft.green()) * t),
                    int(soft.blue() + (base.blue() - soft.blue()) * t),
                )
            painter.setPen(Qt.NoPen)
            painter.setBrush(color)
            painter.drawRoundedRect(day_x, _STRIP_TOP, cell, cell, 2, 2)
            if col == _DAYS - 1:
                today_col_x = day_x
        if today_col_x is not None:
            # Accent ring marks "today" so oldest → today reads clearly.
            painter.setPen(QPen(QColor(p["ACCENT"]), 2))
            painter.setBrush(Qt.NoBrush)
            painter.drawRoundedRect(
                today_col_x - 2, _STRIP_TOP - 2, cell + 4, cell + 4, 4, 4
            )
            if cell >= 5:
                # Date caption under the strip, right-aligned at the card
                # padding so it can never be clipped by the card edge.
                cap = today.strftime("%b %d, %Y · today")
                painter.setPen(QColor(p["TEXT_MUTED"]))
                cap_w = fm.horizontalAdvance(cap)
                painter.drawText(self.width() - _MARGIN - cap_w, _STRIP_TOP + cell + 12, cap)
        painter.end()
