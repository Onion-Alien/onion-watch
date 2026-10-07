"""Shared UI building blocks: the bar / card / divider helpers every page is built
from, and a wrapping row layout."""
from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, QSize, Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QLayout, QVBoxLayout

from onionwatch.ui import icons
from onionwatch.i18n import _


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
        m = self.contentsMargins()
        inner = QRect(0, 0, w - m.left() - m.right(), 0)
        return self._place(inner, move=False) + m.top() + m.bottom()

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._place(rect.marginsRemoved(self.contentsMargins()), move=True)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for it in self._items:
            size = size.expandedTo(it.minimumSize())
        m = self.contentsMargins()
        return size + QSize(m.left() + m.right(), m.top() + m.bottom())

    def _place(self, rect: QRect, move: bool) -> int:
        x, y, line = rect.x(), rect.y(), 0
        pending = []

        def place_line():
            if move:
                for item, left, size in pending:
                    item.setGeometry(QRect(QPoint(left, y + (line - size.height()) // 2), size))

        for it in self._items:
            if it.isEmpty():
                continue
            hint = it.sizeHint()
            if hint.width() > rect.width() > 0:   # wider than the whole row: as narrow
                hint.setWidth(max(rect.width(), it.minimumSize().width()))   # as it goes
            if line and x + hint.width() > rect.right() + 1:
                place_line()
                pending.clear()
                x, y, line = rect.x(), y + line + self._gap, 0
            pending.append((it, x, hint))
            x += hint.width() + self._gap
            line = max(line, hint.height())
        place_line()
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


def _cross_icon(colour: str, size: int = 10):
    """A thin ✕ for a close button, painted so no font can turn it into a box."""
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
    scale = 2
    pm = QPixmap(size * scale, size * scale)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(QPen(QColor(colour), 1.6 * scale, Qt.SolidLine, Qt.RoundCap))
    a, b = 1.5 * scale, size * scale - 1.5 * scale
    p.drawLine(QPointF(a, a), QPointF(b, b))
    p.drawLine(QPointF(a, b), QPointF(b, a))
    p.end()
    pm.setDevicePixelRatio(scale)
    return QIcon(pm)


class UndoBar(QFrame):
    """"Deleted X · Undo" for a few seconds after something is thrown away.
    show_for(text, undo, done): Undo calls `undo`; the bar timing out, being
    dismissed, or showing something else calls `done` (if given) instead.

    Given a `parent` it's a toast: it floats over the top of the parent, centred,
    and is never part of a layout, so showing it moves nothing. Without one it's a
    plain row for a layout."""
    SECONDS = 10
    MARGIN = 8          # from the parent's edges, as a toast
    MAX_TEXT = 420      # the longest the message gets before it's cut short (…)

    def __init__(self, tip: str = "", parent=None):
        super().__init__(parent)
        from PySide6.QtCore import QTimer
        from PySide6.QtGui import QColor
        from PySide6.QtWidgets import QGraphicsDropShadowEffect, QPushButton
        self.setObjectName("undotoast")
        self._tip, self._text = tip, ""
        h = QHBoxLayout(self)
        h.setContentsMargins(12, 5, 5, 5)
        h.setSpacing(8)
        self.label = QLabel()
        self.label.setTextFormat(Qt.PlainText)   # names are user / web text
        h.addWidget(self.label, 1)
        self.btn_undo = QPushButton(_("Undo"))
        self.btn_undo.setObjectName("undobtn")
        self.btn_undo.setToolTip(tip or _("Put it back, exactly as it was"))
        self.btn_undo.setCursor(Qt.PointingHandCursor)
        self.btn_undo.clicked.connect(self.undo)
        h.addWidget(self.btn_undo)
        self.btn_close = QPushButton()            # a painted cross (restyle)
        self.btn_close.setObjectName("undoclose")
        self.btn_close.setToolTip(_("Dismiss"))
        self.btn_close.setFixedSize(22, 22)
        self.btn_close.setIconSize(QSize(10, 10))
        self.btn_close.setCursor(Qt.PointingHandCursor)
        self.btn_close.clicked.connect(self.finish)
        h.addWidget(self.btn_close)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.finish)
        self._undo = self._done = None
        self.floating = parent is not None
        if self.floating:
            shadow = QGraphicsDropShadowEffect(self)
            shadow.setBlurRadius(18)
            shadow.setOffset(0, 3)
            shadow.setColor(QColor(0, 0, 0, 110))
            self.setGraphicsEffect(shadow)
            parent.installEventFilter(self)      # follow the parent's size
        self.restyle()
        self.hide()

    def restyle(self):
        """Colour it from the current theme (call again when the theme changes). It
        has its own sheet, so a host's rules for other buttons can't wash Undo out."""
        from onionwatch import theme
        base = theme.THEMES[theme.DEFAULT]
        t = {k: theme.T.get(k, base[k]) for k in (
            "card_hi", "border_hi", "text_hi", "text", "muted", "accent", "accent_hi",
            "on_accent", "btn_hover")}
        self.setStyleSheet(f"""
QFrame#undotoast {{ background:{t['card_hi']}; border:1px solid {t['border_hi']};
    border-radius:10px; }}
QFrame#undotoast QLabel {{ background:transparent; border:none; color:{t['text_hi']}; }}
QFrame#undotoast QPushButton#undobtn {{ background:{t['accent']}; color:{t['on_accent']};
    border:none; border-radius:6px; padding:3px 14px; font-weight:600; }}
QFrame#undotoast QPushButton#undobtn:hover {{ background:{t['accent_hi']}; }}
QFrame#undotoast QPushButton#undoclose {{ background:transparent; color:{t['muted']};
    border:none; border-radius:11px; padding:0; font-size:9pt; }}
QFrame#undotoast QPushButton#undoclose:hover {{ background:{t['btn_hover']};
    color:{t['text']}; }}
""")
        self.btn_close.setIcon(_cross_icon(t["muted"]))

    def show_for(self, text: str, undo, done=None, tip: str | None = None):
        self.finish()
        self._text = text
        self.btn_undo.setToolTip(tip or self._tip)
        self.label.setToolTip(text)
        self._undo, self._done = undo, done
        self.show()
        self._place()
        self._timer.start(self.SECONDS * 1000)

    def _place(self):
        """Cut the message to fit and, as a toast, centre it along the top."""
        p = self.parentWidget() if self.floating else None
        room = self.MAX_TEXT
        if p is not None:
            lay = self.layout()
            m = lay.contentsMargins()
            fixed = (m.left() + m.right() + 2 * lay.spacing()
                     + self.btn_undo.sizeHint().width() + self.btn_close.width() + 2)
            room = max(40, min(room, p.width() - 2 * self.MARGIN - fixed))
        self.label.setText(self.label.fontMetrics().elidedText(self._text, Qt.ElideRight,
                                                               room))
        if p is None:
            return
        hint = self.sizeHint()
        w = max(1, min(hint.width(), p.width() - 2 * self.MARGIN))
        self.setGeometry((p.width() - w) // 2, self.MARGIN, w, hint.height())
        self.raise_()

    def eventFilter(self, obj, ev):
        from PySide6.QtCore import QEvent
        if obj is self.parentWidget() and ev.type() == QEvent.Resize and not self.isHidden():
            self._place()
        return False

    def undo(self):
        cb, self._undo, self._done = self._undo, None, None
        self._timer.stop()
        self.hide()
        if cb is not None:
            cb()

    def finish(self):
        cb, self._undo, self._done = self._done, None, None
        self._timer.stop()
        self.hide()
        if cb is not None:
            cb()
