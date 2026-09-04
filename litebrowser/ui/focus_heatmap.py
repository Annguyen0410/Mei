"""Review-page extraction from personal_window.py (was 2900+ lines).

FocusHeatmap paints a 12-week streak grid; ReviewMixin owns the flashcard
review page (queue, flip, SM-2 grading, keyboard shortcuts). They only touch
attributes PersonalWindow already owns (base_dir, nav_buttons, _flash).
"""

from PyQt5.QtGui import QColor, QPainter, QPen
from PyQt5.QtWidgets import QWidget

from litebrowser.services import focus_service
from litebrowser.ui import theme


class FocusHeatmap(QWidget):
    """Duolingo-style 12-week streak grid from focus_sessions.json.

    One small rounded cell per day; intensity follows minutes focused.
    Pure theme painting, no chart dependency. The math lives in
    focus_service.compute_daily_minutes / compute_streaks so this view and
    the dashboard can never disagree."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._minutes = {}  # day-key -> minutes
        self._streak = 0
        self._longest = 0
        self.setToolTip("Focus minutes per day — keep the chain alive")
        self.setMinimumHeight(58)

    def refresh(self, base_dir: str):
        sessions = focus_service.focus_journal(base_dir, limit=200)
        self._minutes = focus_service.compute_daily_minutes(sessions)
        self._streak, self._longest = focus_service.compute_streaks(self._minutes)
        self.update()

    def paintEvent(self, _event):
        import datetime as _dt

        painter = QPainter(self)
        p = theme.palette()
        painter.fillRect(self.rect(), QColor(p["CARD_BG"]))
        cell = 11
        gap = 3
        cols = 12
        rows = 7
        left, top = 8, 8
        today = _dt.date.today()
        painter.setPen(QColor(p["TEXT_MUTED"]))
        painter.drawText(left, top + 8, f"🔥 Focus streak: {self._streak} days · longest {self._longest}")
        gy = top + 16
        max_minutes = max([1] + list(self._minutes.values()))
        for col in range(cols):
            for row in range(rows):
                days_back = (cols - 1 - col) * rows + (rows - 1 - row)
                day = today - _dt.timedelta(days=days_back)
                key = day.isoformat()
                minutes = self._minutes.get(key, 0)
                if minutes <= 0:
                    color = QColor(p["MAIN_BG_ALT"])
                else:
                    t = min(1.0, minutes / max_minutes)
                    base = QColor(p["ACCENT"])
                    soft = QColor(p["MAIN_BG_ALT"])
                    color = QColor(
                        int(soft.red() + (base.red() - soft.red()) * t),
                        int(soft.green() + (base.green() - soft.green()) * t),
                        int(soft.blue() + (base.blue() - soft.blue()) * t),
                    )
                painter.setPen(QPen(QColor(p["BORDER_SOFT"]), 1))
                painter.setBrush(color)
                painter.drawRoundedRect(left + col * (cell + gap), gy + row * (cell + gap), cell, cell, 3, 3)
        painter.end()
