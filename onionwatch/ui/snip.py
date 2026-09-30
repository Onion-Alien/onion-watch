"""Cut the picture to look for straight out of the watched window (or screen):
the capture is shown, you drag a box around the thing to watch for, and that
piece is kept at full size, pixel for pixel. Handy for a window you've alt-tabbed
away from, where Win+Shift+S can't reach."""
from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPen
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QLabel, QSizePolicy, QVBoxLayout,
                               QWidget)

from onionwatch import theme
from onionwatch.ui.panel import hint_label

MIN_CUT = 6     # pixels each way (the smallest picture a trigger takes)


class CropView(QWidget):
    """The capture scaled to fit, with a box you drag. `selection` is in the
    capture's own pixels."""
    changed = Signal()

    def __init__(self, img: QImage):
        super().__init__()
        self.img = img
        self.selection = QRect()
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
        self.setWindowTitle(f"Cut a picture from {where}")
        self.piece: QImage | None = None
        v = QVBoxLayout(self)
        v.addWidget(hint_label(
            "Drag a box around the thing to watch for — a name plate, a banner, an icon. "
            "Keep it tight but with some detail in it (words work well). It's kept at full "
            "size, so it matches the game at this resolution."))
        self.view = CropView(img)
        self.view.changed.connect(self._update)
        v.addWidget(self.view, 1)
        self.size_label = QLabel()
        self.size_label.setObjectName("muted")
        v.addWidget(self.size_label)
        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        ok = self.buttons.button(QDialogButtonBox.Ok)
        ok.setText("Use this piece")
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
        self.size_label.setText(f"{s.width()}×{s.height()} pixels" if s.width() and s.height()
                                else "Drag a box on the picture")

    def _accept(self):
        s = self.view.selection
        if s.width() >= MIN_CUT and s.height() >= MIN_CUT:
            self.piece = self.view.img.copy(s)
            self.accept()
