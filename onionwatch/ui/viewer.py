"""A trigger's pictures, big: click a thumbnail on a card and its picture opens
here, scaled up to fill the window (small cut-outs in sharp, whole pixels, so you
can see exactly what was taken), over a checkerboard where it's see-through. The
other pictures of the trigger are along the bottom; ← and → go through them, F11
(or a double-click) goes full screen, and a picture can be swapped for a file or
taken off from here.

Pictures are read on a thread of their own: a big one, or a busy disk, never holds up
the window (it once froze Onion Board for 5 s). A quick one is still there on the
first paint."""
from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor, wait
from pathlib import Path

from PySide6.QtCore import QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QIcon, QImage, QImageReader, QKeySequence, QPainter, QShortcut
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QLabel, QPushButton, QScrollArea,
                               QSizePolicy, QVBoxLayout, QWidget)

from onionwatch import theme
from onionwatch.ui import fit, icons
from onionwatch.ui.windowpicker import thumbnail
from onionwatch.i18n import _

TILE = QSize(96, 54)    # a thumbnail along the bottom
CHECK = 10              # px: a square of the see-through checkerboard
MAX_ZOOM = 12           # a tiny cut-out is shown at most this many times its size
BIG = QSize(2048, 2048)  # the picture itself is read at most this big
WAIT_S = 0.15           # how long opening waits for it before showing "Loading…"
POLL_MS = 30            # how often the window looks for pictures that are read

# QImage and QImageReader may be used off the UI thread, and reading lets go of
# Python's lock, so the window keeps answering while a picture is read
_readers = ThreadPoolExecutor(max_workers=2, thread_name_prefix="onionwatch-picture")


def read_image(path: str, size: QSize) -> QImage:
    """Decode at display size, without a full-size photo for a thumbnail."""
    reader = QImageReader(path)
    original = reader.size()
    if original.isValid() and (original.width() > size.width()
                               or original.height() > size.height()):
        reader.setScaledSize(original.scaled(size, Qt.KeepAspectRatio))
    return reader.read()


def _read(path: str, size: QSize) -> tuple[QSize, QImage]:
    """(its own size, the picture at most `size`), on a reader thread."""
    return QImageReader(path).size(), read_image(path, size)


class PictureView(QWidget):
    """One picture, as big as fits: blown up in whole steps (crisp pixels) when it's
    small, smoothly shrunk when it's bigger than the view. A double-click asks for
    full screen (`toggled`)."""
    toggled = Signal()

    def __init__(self):
        super().__init__()
        self.img = QImage()
        self.loading = False            # it's being read: "Loading…", not "can't be read"
        self.setMinimumSize(240, 160)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def set_image(self, img: QImage, loading: bool = False):
        self.img = img
        self.loading = loading
        self.update()

    def zoom(self) -> float:
        """How many times its own size the picture is drawn."""
        if self.img.isNull():
            return 1.0
        pad = 24
        room = min((self.width() - pad) / self.img.width(),
                   (self.height() - pad) / self.img.height())
        if room >= 1:
            return float(min(int(room), MAX_ZOOM))   # whole steps: every pixel the same size
        return max(room, 0.01)

    def picture_rect(self) -> QRectF:
        z = self.zoom()
        w, h = self.img.width() * z, self.img.height() * z
        return QRectF((self.width() - w) / 2, (self.height() - h) / 2, w, h)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(theme.T.get("inset", "#151d23")))
        if self.img.isNull():
            p.setPen(QColor(theme.T.get("muted", "#888888")))
            p.drawText(self.rect(), Qt.AlignCenter,
                       _("Loading picture…") if self.loading
                       else _("This picture can't be read"))
            return
        r = self.picture_rect()
        if self.img.hasAlphaChannel():      # see-through parts: a checkerboard behind
            p.save()
            p.setClipRect(r)
            light, dark = QColor("#cfcfcf"), QColor("#9a9a9a")
            y, row = int(r.top()), 0
            while y < r.bottom():
                x, col = int(r.left()), row % 2
                while x < r.right():
                    p.fillRect(x, y, CHECK, CHECK, light if col % 2 == 0 else dark)
                    x, col = x + CHECK, col + 1
                y, row = y + CHECK, row + 1
            p.restore()
        p.setRenderHint(QPainter.SmoothPixmapTransform, self.zoom() < 1)
        p.drawImage(r, self.img)
        p.setPen(QColor(theme.T.get("border_hi", "#4f6b7c")))
        p.drawRect(r.adjusted(-1, -1, 0, 0))

    def mouseDoubleClickEvent(self, ev):
        if ev.button() == Qt.LeftButton:
            self.toggled.emit()
        super().mouseDoubleClickEvent(ev)


class PictureViewer(QDialog):
    """A trigger's pictures (`paths`, read again from `get_paths` after a change),
    starting at `index`. `swap(i)` and `remove(i)` are the card's own: swap a
    picture for a file, take one off (with its Undo bar)."""

    def __init__(self, title: str, get_paths: Callable[[], list[str]], index: int = 0,
                 swap: Callable[[int], None] | None = None,
                 remove: Callable[[int], None] | None = None,
                 describe: Callable[[QImage], str] | None = None, parent=None):
        super().__init__(parent)
        fit.watch(self)          # grows to fit its (translated) text
        self.setWindowTitle(title)
        self.setWindowFlag(Qt.WindowMaximizeButtonHint, True)
        self.get_paths, self.swap, self.remove = get_paths, swap, remove
        self.describe = describe
        self.paths: list[str] = []
        self.index = index
        self._loaded_path = None
        self._image_size = QSize()
        self._big: Future | None = None              # the picture shown, being read
        self._tile_jobs: list[tuple[int, Future]] = []
        self._poll = QTimer(self)
        self._poll.setInterval(POLL_MS)
        self._poll.timeout.connect(self._collect)
        scr = self.screen().availableGeometry() if self.screen() else None
        self.resize(min(1100, scr.width() - 80) if scr else 1000,
                    min(760, scr.height() - 80) if scr else 700)

        v = QVBoxLayout(self)
        v.setContentsMargins(12, 12, 12, 12)
        v.setSpacing(10)
        self.info = QLabel()
        self.info.setObjectName("hint")
        self.info.setWordWrap(True)
        v.addWidget(self.info)

        mid = QHBoxLayout()
        mid.setSpacing(8)
        self.btn_prev = QPushButton()
        self.btn_prev.setToolTip(_("The picture before (←)"))
        icons.set_icon(self.btn_prev, "back", size=18)
        self.btn_prev.setFixedSize(40, 64)
        self.btn_prev.clicked.connect(lambda: self.go(self.index - 1))
        mid.addWidget(self.btn_prev, 0, Qt.AlignVCenter)
        self.view = PictureView()
        self.view.setToolTip(_("Double-click for full screen"))
        self.view.toggled.connect(self.toggle_full)
        mid.addWidget(self.view, 1)
        self.btn_next = QPushButton()
        self.btn_next.setToolTip(_("The next picture (→)"))
        icons.set_icon(self.btn_next, "forward", size=18)
        self.btn_next.setFixedSize(40, 64)
        self.btn_next.clicked.connect(lambda: self.go(self.index + 1))
        mid.addWidget(self.btn_next, 0, Qt.AlignVCenter)
        v.addLayout(mid, 1)

        self.tiles_area = QScrollArea()
        self.tiles_area.setFrameShape(QScrollArea.NoFrame)
        self.tiles_area.setWidgetResizable(True)
        self.tiles_area.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.tiles_area.setFixedHeight(TILE.height() + 12
                                       + self.tiles_area.horizontalScrollBar().sizeHint().height())
        box = QWidget()
        self.tiles_row = QHBoxLayout(box)
        self.tiles_row.setContentsMargins(0, 0, 0, 0)
        self.tiles_row.setSpacing(6)
        self.tiles_row.addStretch(1)
        self.tiles_area.setWidget(box)
        self.tiles: list[QPushButton] = []
        v.addWidget(self.tiles_area)

        foot = QHBoxLayout()
        foot.setSpacing(8)
        # the dialog's own from the start: shown before foot is laid out, a parentless
        # button flashed up on the desktop as a little window of its own
        self.btn_swap = QPushButton(_("Swap for a file…"), self)
        icons.set_icon(self.btn_swap, "folder", size=14)
        self.btn_swap.clicked.connect(self._swap)
        self.btn_swap.setVisible(swap is not None)
        foot.addWidget(self.btn_swap)
        self.btn_remove = QPushButton(_("Remove"), self)
        self.btn_remove.setObjectName("danger")
        self.btn_remove.setToolTip(_("Take this picture off the trigger (Undo brings it back)"))
        icons.set_icon(self.btn_remove, "trash", size=14)
        self.btn_remove.clicked.connect(self._remove)
        self.btn_remove.setVisible(remove is not None)
        foot.addWidget(self.btn_remove)
        foot.addStretch(1)
        self.btn_full = QPushButton(_("Full screen"))
        self.btn_full.setToolTip(_("Fill the screen with it (F11, or double-click the picture)"))
        self.btn_full.clicked.connect(self.toggle_full)
        foot.addWidget(self.btn_full)
        close = QPushButton(_("Close"))
        close.clicked.connect(self.reject)
        foot.addWidget(close)
        v.addLayout(foot)

        for keys, fn in (("Left", lambda: self.go(self.index - 1)),
                         ("Right", lambda: self.go(self.index + 1)),
                         ("F11", self.toggle_full), ("F", self.toggle_full)):
            QShortcut(QKeySequence(keys), self, fn)
        self.reload()

    # ------------------------------------------------------------------ pictures
    def reload(self):
        """Read the trigger's pictures again (one was swapped or taken off)."""
        self.paths = list(self.get_paths())
        self._loaded_path = None
        self._big = None
        self._tile_jobs = []            # a reader still busy with an old one is ignored
        for b in self.tiles:
            self.tiles_row.removeWidget(b)
            b.hide()
            b.deleteLater()
        self.tiles = []
        for i, p in enumerate(self.paths):
            b = QPushButton()
            b.setCheckable(True)
            b.setFixedSize(TILE + QSize(8, 8))
            b.setIconSize(TILE)
            b.setCursor(Qt.PointingHandCursor)
            b.setToolTip(Path(p).name)
            b.clicked.connect(lambda _c=False, i=i: self.go(i))
            self.tiles_row.insertWidget(i, b)
            self.tiles.append(b)
        self.tiles_area.setVisible(len(self.paths) > 1)
        if not self.paths:
            self.accept()               # the last one was taken off: nothing to show
            return
        self.go(min(self.index, len(self.paths) - 1))
        self._tile_jobs = [(i, _readers.submit(read_image, p, TILE))
                           for i, p in enumerate(self.paths)]
        self._poll.start()

    def _collect(self):
        """Put up what the reader threads have finished: the picture, thumbnails."""
        big = self._big
        if big is not None and big.done():
            self._big = None
            self._show_read(big)
        waiting = []
        for i, job in self._tile_jobs:
            if not job.done():
                waiting.append((i, job))
            elif i < len(self.tiles):
                img = job.result() if job.exception() is None else QImage()
                self.tiles[i].setIcon(QIcon(thumbnail(img, TILE)))
        self._tile_jobs = waiting
        if self._big is None and not waiting:
            self._poll.stop()

    def _show_read(self, job: Future):
        size, img = job.result() if job.exception() is None else (QSize(), QImage())
        self._image_size = size
        self.view.set_image(img)
        self._label()

    def go(self, index: int):
        if not self.paths:
            return
        self.index = index % len(self.paths)      # round from the last back to the first
        path = self.paths[self.index]
        if path != self._loaded_path:
            self._loaded_path = path
            job = _readers.submit(_read, path, BIG)
            wait([job], timeout=WAIT_S)     # most are small cut-outs: here at once
            if job.done():
                self._big = None
                self._show_read(job)
            else:
                self._big = job
                self._image_size = QSize()
                self.view.set_image(QImage(), loading=True)
                self._poll.start()
        for i, b in enumerate(self.tiles):
            b.setChecked(i == self.index)
        if self.tiles:
            self.tiles_area.ensureWidgetVisible(self.tiles[self.index])
        many = len(self.paths) > 1
        self.btn_prev.setVisible(many)
        self.btn_next.setVisible(many)
        self._label()

    def _label(self):
        """The line above the picture: which one, its name, its size, its zoom."""
        if not self.paths:
            return
        path, img, many = self.paths[self.index], self.view.img, len(self.paths) > 1
        parts = [_("Picture {n} of {total}", n=self.index + 1, total=len(self.paths))
                 if many else "",
                 Path(path).name]
        if not img.isNull():
            if self._image_size.isValid():
                parts.append(f"{self._image_size.width()}×{self._image_size.height()} px")
            if self.describe:
                parts.append(self.describe(img))
            z = self.view.zoom()
            if z > 1:
                parts.append(_("shown {zoom:g}× bigger", zoom=z))
        self.info.setText(" · ".join(p for p in parts if p))

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self._label()                   # the "shown 4× bigger" follows the window

    # ------------------------------------------------------------------ actions
    def _swap(self):
        if self.swap is not None:
            self.swap(self.index)
            self.reload()

    def _remove(self):
        if self.remove is not None:
            self.remove(self.index)
            self.reload()

    def toggle_full(self):
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()
        self.btn_full.setText(_("Leave full screen") if self.isFullScreen() else _("Full screen"))

    def keyPressEvent(self, ev):
        if ev.key() == Qt.Key_Escape and self.isFullScreen():   # Esc: out of full screen first
            self.toggle_full()
            ev.accept()
            return
        super().keyPressEvent(ev)
