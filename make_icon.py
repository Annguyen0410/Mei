# -*- coding: utf-8 -*-
"""Generate the Mei brand icon: a light-brown rounded square with a hot tea
cup (steam rising). Emits icon.png (640x640) and a multi-size icon.ico.

Run:  .venv\\Scripts\\python.exe make_icon.py
"""
import io
import os
import struct
import sys

from PyQt5.QtCore import QBuffer, QByteArray, QIODevice, QPointF, Qt
from PyQt5.QtGui import (
    QColor,
    QFont,
    QImage,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QRadialGradient,
)

SIZE = 640
BG_TOP = QColor(244, 230, 208)      # light warm sand
BG_BOTTOM = QColor(214, 186, 148)   # light brown
CUP_BODY = QColor(252, 248, 240)    # cream porcelain
CUP_SHADE = QColor(228, 212, 186)   # soft shading on the cup
TEA = QColor(178, 120, 62)          # amber tea
TEA_DEEP = QColor(140, 92, 46)
SAUCER = QColor(202, 170, 130)
STEAM = QColor(255, 255, 255, 200)


def _draw(painter, scale=1.0):
    """Draw the icon in a 640x640 coordinate space scaled by ``scale``."""
    p = painter
    p.setRenderHint(QPainter.Antialiasing, True)
    p.setRenderHint(QPainter.SmoothPixmapTransform, True)
    if scale != 1.0:
        p.scale(scale, scale)

    # --- Background: light brown rounded square with a soft radial glow ---
    margin = 26
    rect = (margin, margin, SIZE - 2 * margin, SIZE - 2 * margin)
    bg = QLinearGradient(rect[0], rect[1], rect[0], rect[1] + rect[3])
    bg.setColorAt(0.0, BG_TOP)
    bg.setColorAt(1.0, BG_BOTTOM)
    path = QPainterPath()
    path.addRoundedRect(*rect, 150, 150)
    p.fillPath(path, bg)
    glow = QRadialGradient(QPointF(SIZE / 2, rect[1] + rect[3] * 0.35), rect[3] * 0.85)
    glow.setColorAt(0.0, QColor(255, 250, 240, 70))
    glow.setColorAt(1.0, QColor(255, 250, 240, 0))
    p.fillPath(path, glow)

    cx = SIZE / 2

    # --- Steam rising above the cup (three soft curls) ---
    p.setPen(QPen(STEAM, 15 * (1 if scale < 0.5 else 1), Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    for offset, amp in ((-42, 16), (0, 22), (42, 16)):
        steam = QPainterPath(QPointF(cx + offset, 236))
        steam.cubicTo(
            QPointF(cx + offset - amp, 196),
            QPointF(cx + offset + amp, 176),
            QPointF(cx + offset, 138),
        )
        p.drawPath(steam)

    # --- Saucer ---
    saucer_top = 472
    p.setPen(QPen(QColor(180, 148, 108), 4))
    p.setBrush(SAUCER)
    p.drawEllipse(QPointF(cx, saucer_top), 158, 26)
    p.setBrush(QColor(222, 196, 158))
    p.drawEllipse(QPointF(cx, saucer_top - 2), 118, 18)

    # --- Cup body (rounded trapezoid) ---
    cup_top_y, cup_bottom_y = 258, 466
    top_half, bottom_half = 92, 70
    cup = QPainterPath()
    cup.moveTo(cx - top_half, cup_top_y)
    cup.lineTo(cx + top_half, cup_top_y)
    cup.lineTo(cx + bottom_half, cup_bottom_y)
    cup.lineTo(cx - bottom_half, cup_bottom_y)
    cup.closeSubpath()
    p.setPen(QPen(QColor(196, 170, 138), 5))
    p.setBrush(CUP_BODY)
    p.drawPath(cup)

    # Cup shading (soft vertical gradient on the body)
    shade = QLinearGradient(cx - top_half, 0, cx + top_half, 0)
    shade.setColorAt(0.0, QColor(228, 212, 186, 90))
    shade.setColorAt(0.5, QColor(255, 255, 255, 0))
    shade.setColorAt(1.0, QColor(180, 152, 118, 80))
    p.setPen(Qt.NoPen)
    p.setBrush(shade)
    p.drawPath(cup)

    # --- Tea surface (amber ellipse at the cup mouth) ---
    tea = QPainterPath()
    tea.addEllipse(QPointF(cx, cup_top_y), top_half - 2, 14)
    tea_brush = QLinearGradient(0, cup_top_y - 14, 0, cup_top_y + 14)
    tea_brush.setColorAt(0.0, TEA)
    tea_brush.setColorAt(1.0, TEA_DEEP)
    p.setPen(QPen(QColor(120, 78, 38), 3))
    p.setBrush(tea_brush)
    p.drawPath(tea)

    # --- Handle (right side) ---
    p.setPen(QPen(QColor(196, 170, 138), 12, Qt.SolidLine, Qt.RoundCap))
    handle = QPainterPath()
    handle.moveTo(cx + top_half - 4, cup_top_y + 34)
    handle.cubicTo(
        QPointF(cx + top_half + 58, cup_top_y + 40),
        QPointF(cx + top_half + 58, cup_bottom_y - 52),
        QPointF(cx + bottom_half - 2, cup_bottom_y - 46),
    )
    p.drawPath(handle)


def render(size: int) -> QImage:
    image = QImage(size, size, QImage.Format_ARGB32)
    image.fill(Qt.transparent)
    painter = QPainter(image)
    _draw(painter, scale=size / SIZE)
    painter.end()
    return image


def _png_bytes(image: QImage) -> bytes:
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.WriteOnly)
    image.save(buf, "PNG")
    buf.close()
    return bytes(ba.data())


def build_ico(sizes=(256, 128, 64, 48, 32, 16)) -> bytes:
    """Assemble a multi-size ICO using PNG-compressed entries (Vista+)."""
    entries = []
    for size in sizes:
        data = _png_bytes(render(size))
        entries.append((size, data))
    header = struct.pack("<HHH", 0, 1, len(entries))
    offset = 6 + 16 * len(entries)
    out = bytearray(header)
    for size, data in entries:
        dim = 0 if size >= 256 else size
        out += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(data), offset)
        offset += len(data)
    for _size, data in entries:
        out += data
    return bytes(out)


def main():
    root = os.path.dirname(os.path.abspath(__file__))
    png_path = os.path.join(root, "icon.png")
    ico_path = os.path.join(root, "icon.ico")
    render(SIZE).save(png_path, "PNG")
    with open(ico_path, "wb") as fh:
        fh.write(build_ico())
    print("wrote", png_path, os.path.getsize(png_path), "bytes")
    print("wrote", ico_path, os.path.getsize(ico_path), "bytes")


if __name__ == "__main__":
    sys.exit(main())
