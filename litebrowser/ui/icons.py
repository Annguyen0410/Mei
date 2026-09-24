"""Programmatically drawn icons that follow the active theme.

Qt stylesheets cannot recolor icons, so theme-following icons are painted
with QPainter into a pixmap and re-generated whenever the theme/accent
changes (the shell does this in refresh_shell).
"""
from litebrowser.qt import QtCore, QtGui

Qt = QtCore.Qt
QPointF, QRectF = QtCore.QPointF, QtCore.QRectF
QColor, QIcon, QPainter, QPen, QPixmap = (
    QtGui.QColor,
    QtGui.QIcon,
    QtGui.QPainter,
    QtGui.QPen,
    QtGui.QPixmap,
)

__all__ = ["search_icon"]


def search_icon(color: str = "#9ca3af") -> QIcon:
    """A magnifying-glass search glyph drawn in ``color``."""
    pm = QPixmap(32, 32)
    pm.fill(Qt.transparent)
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.Antialiasing, True)
    pen = QPen(QColor(color))
    pen.setWidth(3)
    pen.setCapStyle(Qt.RoundCap)
    painter.setPen(pen)
    painter.drawEllipse(QRectF(6.0, 6.0, 15.0, 15.0))
    handle_pen = QPen(QColor(color))
    handle_pen.setWidth(4)
    handle_pen.setCapStyle(Qt.RoundCap)
    painter.setPen(handle_pen)
    painter.drawLine(QPointF(19.0, 19.0), QPointF(25.5, 25.5))
    painter.end()
    return QIcon(pm)