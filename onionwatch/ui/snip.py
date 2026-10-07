"""Cut the picture to look for straight out of the watched window (or screen):
the capture is shown, you drag a box around the thing to watch for, and that
piece is kept at full size, pixel for pixel. Handy for a window you've alt-tabbed
away from, where Win+Shift+S can't reach.

The same view picks a trigger's area (AreaDialog): the part of each window to
look in, kept as fractions so it follows the window when it's resized, and for a
colour trigger the colour to measure (a health bar's)."""
from __future__ import annotations

import numpy as np
from PySide6.QtCore import QPoint, QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPen
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QPushButton,
                               QSizePolicy, QVBoxLayout, QWidget)

from onionwatch import theme
from onionwatch.ui.panel import hint_label
from onionwatch.ui import fit
from onionwatch.i18n import _

MIN_CUT = 6     # pixels each way (the smallest picture a trigger takes)
MIN_AREA = 4    # ...and the smallest area


def pixels(img: QImage, rect: QRect | None = None) -> np.ndarray:
    """A picture's pixels (or a rectangle of them) as (h, w, 3) uint8 RGB."""
    if rect is not None:
        img = img.copy(rect)
    img = img.convertToFormat(QImage.Format_RGB888)
    h, w = img.height(), img.width()
    buf = np.frombuffer(img.constBits(), np.uint8, count=img.bytesPerLine() * h)
    return buf.reshape(h, img.bytesPerLine())[:, :w * 3].reshape(h, w, 3).copy()


def main_colour(img: QImage, rect: QRect) -> QColor:
    """The colour most of an area is (a full health bar's): the average of the
    commonest of its colours, each rounded to 16 levels."""
    px = pixels(img, rect).reshape(-1, 3)
    if not len(px):
        return QColor()
    q = px // 16
    keys = (q[:, 0].astype(np.int32) << 8) | (q[:, 1].astype(np.int32) << 4) | q[:, 2]
    top = np.bincount(keys).argmax()
    r, g, b = px[keys == top].mean(0)
    return QColor(round(r), round(g), round(b))


def to_region(rect: QRect, size: QSize) -> tuple[float, float, float, float] | None:
    """A selection in capture pixels as fractions of the capture (None: all of it)."""
    w, h = max(size.width(), 1), max(size.height(), 1)
    if rect.width() < MIN_AREA or rect.height() < MIN_AREA:
        return None
    if rect.width() >= w and rect.height() >= h:
        return None
    return (rect.x() / w, rect.y() / h, rect.width() / w, rect.height() / h)


def from_region(region, size: QSize) -> QRect:
    if region is None:
        return QRect()
    x, y, w, h = region
    return QRect(round(x * size.width()), round(y * size.height()),
                 round(w * size.width()), round(h * size.height()))


class CropView(QWidget):
    """The capture scaled to fit, with a box you drag. `selection` is in the
    capture's own pixels."""
    changed = Signal()
    picked = Signal(QPoint)     # a click while `picking` (a colour), in capture pixels

    def __init__(self, img: QImage):
        super().__init__()
        self.img = img
        self.selection = QRect()
        self.picking = False
        self._start: QPoint | None = None
        self.setMinimumSize(320, 200)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setCursor(Qt.CrossCursor)

    def sizeHint(self) -> QSize:
        return self.img.size().scaled(QSize(1100, 700), Qt.KeepAspectRatio)

    def _frame(self) -> QRectF:
        """Where the capture is drawn: fitted, centred."""
        size = self.img.size().scaled(self.size(), Qt.KeepAspectRatio)
        x = (self.width() - size.width()) / 2
        y = (self.height() - size.height()) / 2
        return QRectF(x, y, size.width(), size.height())

    def _to_image(self, pos) -> QPoint:
        f = self._frame()
        sx = self.img.width() / max(f.width(), 1)
        sy = self.img.height() / max(f.height(), 1)
        x = min(max((pos.x() - f.x()) * sx, 0), self.img.width())
        y = min(max((pos.y() - f.y()) * sy, 0), self.img.height())
        return QPoint(round(x), round(y))

    def mousePressEvent(self, ev):
        if ev.button() == Qt.LeftButton and self.picking:
            self.picked.emit(self._to_image(ev.position()))
            return
        if ev.button() == Qt.LeftButton:
            self._start = self._to_image(ev.position())
            self.selection = QRect(self._start, self._start)
            self.update()

    def mouseMoveEvent(self, ev):
        if self._start is not None:
            self.selection = QRect(self._start, self._to_image(ev.position())).normalized()
            self.update()
            self.changed.emit()

    def mouseReleaseEvent(self, ev):
        if ev.button() == Qt.LeftButton and self._start is not None:
            self._start = None
            self.changed.emit()

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        f = self._frame()
        p.drawImage(f, self.img)
        if self.selection.width() > 0 and self.selection.height() > 0:
            sx = f.width() / self.img.width()
            sy = f.height() / self.img.height()
            s = self.selection
            r = QRectF(f.x() + s.x() * sx, f.y() + s.y() * sy, s.width() * sx, s.height() * sy)
            shade = QColor(0, 0, 0, 120)
            for part in (QRectF(f.left(), f.top(), f.width(), r.top() - f.top()),
                         QRectF(f.left(), r.bottom(), f.width(), f.bottom() - r.bottom()),
                         QRectF(f.left(), r.top(), r.left() - f.left(), r.height()),
                         QRectF(r.right(), r.top(), f.right() - r.right(), r.height())):
                p.fillRect(part, shade)
            pen = QPen(QColor(theme.T.get("accent", "#7c5cff")), 2)
            p.setPen(pen)
            p.drawRect(r)
        p.end()


class SnipDialog(QDialog):
    """`piece` is the cut-out QImage once accepted."""

    def __init__(self, img: QImage, where: str, parent=None):
        super().__init__(parent)
        fit.watch(self)          # grows to fit its (translated) text
        self.setWindowTitle(_("Cut a picture from {where}", where=where))
        self.piece: QImage | None = None
        v = QVBoxLayout(self)
        v.addWidget(hint_label(
            _("Drag a box around the thing to watch for — a name plate, a banner, an icon. Keep "
              "it tight but with some detail in it (words work well). It's kept at full size, so "
              "it matches the game at this resolution.")))
        self.view = CropView(img)
        self.view.changed.connect(self._update)
        v.addWidget(self.view, 1)
        self.size_label = QLabel()
        self.size_label.setObjectName("muted")
        v.addWidget(self.size_label)
        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        ok = self.buttons.button(QDialogButtonBox.Ok)
        ok.setText(_("Use this piece"))
        ok.setObjectName("primary")
        self.buttons.accepted.connect(self._accept)
        self.buttons.rejected.connect(self.reject)
        v.addWidget(self.buttons)
        self._update()
        self.resize(self.view.sizeHint() + QSize(40, 140))

    def _update(self):
        s = self.view.selection
        ok = s.width() >= MIN_CUT and s.height() >= MIN_CUT
        self.buttons.button(QDialogButtonBox.Ok).setEnabled(ok)
        self.size_label.setText(_("{width}×{height} pixels",
                                  width=s.width(), height=s.height()) if s.width() and s.height()
                                else _("Drag a box on the picture"))

    def _accept(self):
        s = self.view.selection
        if s.width() >= MIN_CUT and s.height() >= MIN_CUT:
            self.piece = self.view.img.copy(s)
            self.accept()


class AreaDialog(QDialog):
    """Pick the part of a window to look in: drag a box, or "All of it". With
    `colour` (a colour trigger) also the colour to measure: the area's main colour
    unless you click the one you mean. Once accepted, `region` is the area
    (fractions, None: all of it) and `colour` the colour ("#rrggbb", "" without)."""

    def __init__(self, img: QImage, where: str, region=None, colour: str | None = None,
                 parent=None):
        super().__init__(parent)
        fit.watch(self)          # grows to fit its (translated) text
        self.setWindowTitle(_("Where to look in {where}", where=where))
        self.want_colour = colour is not None
        self.region = region
        self.colour = colour or ""
        v = QVBoxLayout(self)
        v.addWidget(hint_label(
            _("Drag a box tightly around the bar to measure (its full length), then check the "
              "colour below: it's the bar's main colour — click “Pick the colour” and then the "
              "bar if it's wrong.")
            if self.want_colour else
            _("Drag a box around the part of the window to look in: only there counts, so other "
              "things on screen can't set it off, and checking is quicker. It's kept as a share "
              "of the window, so it follows the window when it's resized.")))
        self.view = CropView(img)
        self.view.selection = from_region(region, img.size())
        self.view.changed.connect(self._update)
        self.view.picked.connect(self._picked)
        self._picked_by_hand = bool(self.colour)     # keep the colour it has
        v.addWidget(self.view, 1)
        row = QHBoxLayout()
        self.size_label = QLabel()
        self.size_label.setObjectName("muted")
        row.addWidget(self.size_label, 1)
        # the dialog's own from the start: shown or hidden before `row` is laid out, a
        # parentless one flashed up on the desktop as a little window of its own
        self.swatch = QLabel(self)
        self.swatch.setFixedSize(22, 22)
        self.btn_pick = QPushButton(_("Pick the colour"), self)
        self.btn_pick.setCheckable(True)
        self.btn_pick.setToolTip(_("Then click the colour in the picture"))
        self.btn_pick.toggled.connect(self._on_pick)
        for w in (self.swatch, self.btn_pick):
            w.setVisible(self.want_colour)
            row.addWidget(w)
        self.btn_all = QPushButton(_("All of it"), self)
        self.btn_all.setToolTip(_("Look in the whole window"))
        self.btn_all.clicked.connect(self._all)
        self.btn_all.setVisible(not self.want_colour)
        row.addWidget(self.btn_all)
        v.addLayout(row)
        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        ok = self.buttons.button(QDialogButtonBox.Ok)
        ok.setText(_("Use this area"))
        ok.setObjectName("primary")
        self.buttons.accepted.connect(self._accept)
        self.buttons.rejected.connect(self.reject)
        v.addWidget(self.buttons)
        self._update()
        self.resize(self.view.sizeHint() + QSize(40, 150))

    def _update(self):
        s = self.view.selection
        some = s.width() >= MIN_AREA and s.height() >= MIN_AREA
        if self.view._start is not None:
            self._picked_by_hand = False        # a new box: its own main colour
        elif self.want_colour and some and not self._picked_by_hand:
            self.colour = main_colour(self.view.img, s).name()
        self.size_label.setText(_("{width}×{height} pixels",
                                  width=s.width(), height=s.height()) if some else
                                (_("Drag a box around the bar") if self.want_colour
                                 else _("All of the window — or drag a box")))
        self.swatch.setStyleSheet(f"background:{self.colour or 'transparent'}; "
                                  "border:1px solid #888; border-radius:4px;")
        self.buttons.button(QDialogButtonBox.Ok).setEnabled(
            not self.want_colour or (some and bool(self.colour)))

    def _on_pick(self, on: bool):
        self.view.picking = on
        self.view.setCursor(Qt.PointingHandCursor if on else Qt.CrossCursor)

    def _picked(self, pos: QPoint):
        img = self.view.img
        x = min(max(pos.x(), 0), img.width() - 1)
        y = min(max(pos.y(), 0), img.height() - 1)
        px = pixels(img, QRect(max(x - 1, 0), max(y - 1, 0), 3, 3).intersected(img.rect()))
        r, g, b = px.reshape(-1, 3).mean(0)
        self.colour = QColor(round(r), round(g), round(b)).name()
        self._picked_by_hand = True
        self.btn_pick.setChecked(False)
        self._update()

    def _all(self):
        self.view.selection = QRect()
        self.view.update()
        self._update()

    def _accept(self):
        self.region = to_region(self.view.selection, self.view.img.size())
        if self.want_colour and (self.region is None or not self.colour):
            return
        self.accept()
