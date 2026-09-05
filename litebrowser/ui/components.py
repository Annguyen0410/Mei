"""Reusable modern UI building blocks shared by every Mei window.

These small helpers give all surfaces (shell, browser, AI, Personal, dialogs)
a coherent design language: a page header strip, an icon-led page title,
stat tiles, section cards with headers, and empty-state hints. They only
compose plain Qt widgets + object names, so styling stays in ``theme.py``.
"""
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor, QFont
from PyQt5.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


def _font(size: int, weight: int) -> QFont:
    font = QFont()
    font.setPixelSize(size)
    font.setWeight(min(max(int(weight), 0), 99))
    return font


# Qt5 weight enums are the scoped ``QFont::Weight``; the un-scoped names aren't
# available as attributes on ``QFont`` in every PyQt build, so use the ints.
WEIGHT_NORMAL = 50
WEIGHT_DEMI = 63
WEIGHT_BOLD = 75


def page_header(title: str = "", subtitle: str = "") -> QWidget:
    """A calm, icon-led page header shared by full workspace pages."""
    header = QWidget()
    header.setObjectName("PageHeader")
    layout = QHBoxLayout(header)
    layout.setContentsMargins(4, 4, 4, 6)
    layout.setSpacing(10)

    glyph = QLabel("◈")
    glyph.setObjectName("PageGlyph")
    layout.addWidget(glyph, 0, Qt.AlignVCenter)

    text_col = QVBoxLayout()
    text_col.setContentsMargins(0, 0, 0, 0)
    text_col.setSpacing(1)
    lbl_title = QLabel(title)
    lbl_title.setObjectName("PageTitle")
    lbl_title.setFont(_font(18, WEIGHT_DEMI))
    text_col.addWidget(lbl_title)
    if subtitle:
        lbl_sub = QLabel(subtitle)
        lbl_sub.setObjectName("PageSubtitle")
        lbl_sub.setFont(_font(11, WEIGHT_NORMAL))
        text_col.addWidget(lbl_sub)
    layout.addLayout(text_col, 1)
    header._cafe_page_title = lbl_title
    header._cafe_page_glyph = glyph
    return header


def stat_tile(value: str = "0", label: str = "") -> QFrame:
    """An evenly weighted stat tile: big value on top, small muted label below."""
    card = QFrame()
    card.setObjectName("StatTile")
    card.setMinimumWidth(96)
    layout = QVBoxLayout(card)
    layout.setContentsMargins(10, 8, 10, 8)
    layout.setSpacing(2)

    value_lbl = QLabel(value)
    value_lbl.setObjectName("StatValue")
    value_lbl.setFont(_font(20, WEIGHT_BOLD))
    value_lbl.setAlignment(Qt.AlignCenter)
    layout.addWidget(value_lbl)

    label_lbl = QLabel(label)
    label_lbl.setObjectName("StatLabel")
    label_lbl.setFont(_font(11, WEIGHT_NORMAL))
    label_lbl.setAlignment(Qt.AlignCenter)
    label_lbl.setWordWrap(True)
    layout.addWidget(label_lbl)

    card._value = value_lbl
    card._label = label_lbl
    return card


def stat_row(tiles) -> QWidget:
    """An evenly distributed row of stat tiles (tiles: list of QFrame from stat_tile).

    Every column gets equal stretch so the tiles spread across the full
    available width; rows wrap every 5 tiles (works for any count, not just
    multiples of 5).
    """
    wrap = QWidget()
    wrap.setObjectName("StatRow")
    grid = QGridLayout(wrap)
    grid.setContentsMargins(0, 0, 0, 0)
    grid.setSpacing(8)
    per_row = max(1, len(tiles)) if 0 < len(tiles) <= 5 else 5
    for idx, tile in enumerate(tiles):
        row, col = divmod(idx, per_row)
        grid.addWidget(tile, row, col)
    for col in range(per_row):
        grid.setColumnStretch(col, 1)
    for row in range((len(tiles) + per_row - 1) // per_row):
        grid.setRowStretch(row, 1)
    return wrap


def section_header(title: str, subtitle: str = "", action: QPushButton | None = None) -> QWidget:
    """A section title row with an optional trailing action button."""
    row = QWidget()
    row.setObjectName("SectionHeaderRow")
    layout = QHBoxLayout(row)
    layout.setContentsMargins(2, 6, 2, 2)
    layout.setSpacing(8)

    text_col = QVBoxLayout()
    text_col.setContentsMargins(0, 0, 0, 0)
    text_col.setSpacing(1)
    lbl = QLabel(title)
    lbl.setObjectName("SectionTitle")
    lbl.setFont(_font(12, WEIGHT_BOLD))
    text_col.addWidget(lbl)
    if subtitle:
        sub = QLabel(subtitle)
        sub.setObjectName("MutedLabel")
        # Wrap instead of forcing the row to a full-text minimum width: in
        # narrow columns an un-wrapped subtitle made whole cards (and the
        # dashboards around them) overflow their viewport.
        sub.setWordWrap(True)
        text_col.addWidget(sub)
    layout.addLayout(text_col, 1)
    if action is not None:
        layout.addWidget(action, 0, Qt.AlignVCenter)
    return row


def empty_state(text: str, hint: str = "") -> QFrame:
    """A centered, muted empty-state panel used where a list is empty."""
    card = QFrame()
    card.setObjectName("EmptyState")
    layout = QVBoxLayout(card)
    layout.setContentsMargins(18, 18, 18, 18)
    layout.setSpacing(6)
    layout.setAlignment(Qt.AlignCenter)

    glyph = QLabel("✦")
    glyph.setObjectName("EmptyGlyph")
    glyph.setAlignment(Qt.AlignCenter)
    layout.addWidget(glyph)

    lbl = QLabel(text)
    lbl.setAlignment(Qt.AlignCenter)
    lbl.setObjectName("MutedLabel")
    layout.addWidget(lbl)
    card._empty_title = lbl

    if hint:
        sub = QLabel(hint)
        sub.setAlignment(Qt.AlignCenter)
        sub.setObjectName("MutedLabel")
        layout.addWidget(sub)
    else:
        sub = None
    card._empty_hint = sub
    return card


def hint_list_item(text: str, glyph: str = "✦") -> object:
    """A non-interactive placeholder row for empty lists, tinted with the
    active theme's muted color (plain addItem rows ignored the theme)."""
    from litebrowser.ui import theme

    item = QListWidgetItem(f"{glyph}  {text}")
    item.setFlags(Qt.NoItemFlags)
    try:
        p = theme.palette()
        item.setForeground(QColor(p["TEXT_MUTED"]))
        font = item.font()
        font.setItalic(True)
        item.setFont(font)
    except Exception:
        pass
    return item


def nav_button(label: str, glyph: str = "◆", tooltip: str = "") -> QPushButton:
    """A rail navigation button with a leading glyph and muted label styling."""
    button = QPushButton(f"{glyph}  {label}")
    button.setObjectName("NavButton")
    button.setCheckable(True)
    button.setToolTip(tooltip or label)
    return button


def action_tile(glyph: str, label: str, hint: str = "") -> QPushButton:
    """A large launcher tile (glyph on top, label below) for dashboard quick actions."""
    button = QPushButton()
    button.setObjectName("ActionTile")
    layout = QVBoxLayout(button)
    layout.setContentsMargins(8, 12, 8, 10)
    layout.setSpacing(4)
    layout.setAlignment(Qt.AlignCenter)
    g = QLabel(glyph)
    g.setObjectName("ActionGlyph")
    g.setAlignment(Qt.AlignCenter)
    layout.addWidget(g)
    lbl = QLabel(label)
    lbl.setObjectName("ActionLabel")
    lbl.setAlignment(Qt.AlignCenter)
    layout.addWidget(lbl)
    if hint:
        h = QLabel(hint)
        h.setObjectName("ActionHint")
        h.setAlignment(Qt.AlignCenter)
        layout.addWidget(h)
    button._label = lbl
    return button


def chip(text: str, checkable: bool = True, checked: bool | None = None) -> QPushButton:
    """A small pill/chip button, optionally checkable, used as filter toggles."""
    button = QPushButton(text)
    button.setObjectName("Chip")
    if checkable:
        button.setCheckable(True)
        if checked is not None:
            button.setChecked(checked)
    return button


def badge(text: str, kind: str = "plain") -> QLabel:
    """A small status badge with an accent variant."""
    lbl = QLabel(text)
    lbl.setObjectName("BadgeAccent" if kind == "accent" else "Badge")
    return lbl
