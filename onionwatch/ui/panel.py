"""Shared UI building blocks: the bar / card / divider helpers every page is built
from, and a wrapping row layout."""
from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, QSize, Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QLayout, QVBoxLayout

from onionwatch.ui import icons


def section_label(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setObjectName("section")
    return lbl


def hint_label(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setWordWrap(True)
    lbl.setObjectName("hint")
    return lbl


def vsep() -> QFrame:
    """A thin vertical divider between groups in a bar."""
    f = QFrame()
    f.setObjectName("vsep")
    f.setFixedWidth(1)
    return f


def bar(margins=(10, 8, 12, 8)) -> tuple[QFrame, QHBoxLayout]:
    """The rounded control bar along the bottom of the window."""
    f = QFrame()
    f.setObjectName("transport")
    h = QHBoxLayout(f)
    h.setContentsMargins(*margins)
    h.setSpacing(10)
    return f, h


class Flow(QLayout):
    """Lays its widgets out left to right, wrapping onto new lines (a trigger
    card's settings and sounds)."""

    def __init__(self, parent=None, gap: int = 6):
        super().__init__(parent)
        self._items, self._gap = [], gap
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, i):
        return self._items[i] if 0 <= i < len(self._items) else None

    def takeAt(self, i):
        return self._items.pop(i) if 0 <= i < len(self._items) else None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, w):
        return self._place(QRect(0, 0, w, 0), move=False)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._place(rect, move=True)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for it in self._items:
            size = size.expandedTo(it.minimumSize())
        return size

    def _place(self, rect: QRect, move: bool) -> int:
        x, y, line = rect.x(), rect.y(), 0
        for it in self._items:
            if it.isEmpty():
                continue
            hint = it.sizeHint()
            if hint.width() > rect.width() > 0:   # wider than the whole row: as narrow
                hint.setWidth(max(rect.width(), it.minimumSize().width()))   # as it goes
            if line and x + hint.width() > rect.right() + 1:
                x, y, line = rect.x(), y + line + self._gap, 0
            if move:
                it.setGeometry(QRect(QPoint(x, y), hint))
            x += hint.width() + self._gap
            line = max(line, hint.height())
        return y + line - rect.y()


def card(title: str = "", hint: str = "") -> tuple[QFrame, QVBoxLayout]:
    """A titled card, the building block of every page."""
    f = QFrame()
    f.setObjectName("card")
    v = QVBoxLayout(f)
    v.setContentsMargins(14, 8, 14, 14)
    v.setSpacing(6)
    if title:
        v.addWidget(section_label(title))
    if hint:
        v.addWidget(hint_label(hint))
    return f, v


def icon_label(name: str, tip: str = "", color: str = "muted") -> QLabel:
    """A small painted icon used as a label in the bars."""
    lbl = QLabel()
    icons.set_label_icon(lbl, name, color)
    lbl.setToolTip(tip)
    lbl.setObjectName("iconlabel")
    return lbl
