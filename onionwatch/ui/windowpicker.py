"""Pick a window to watch: every open window with a live thumbnail, its title and
its program, so two copies of the same game can be told apart."""
from __future__ import annotations

import logging

import numpy as np
from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QColor, QIcon, QImage, QPixmap
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QHBoxLayout, QListWidget,
                               QListWidgetItem, QPushButton, QVBoxLayout)

from onionwatch import windows
from onionwatch.screenwatch import WindowRef
from onionwatch.ui import icons
from onionwatch.ui.panel import hint_label

log = logging.getLogger(__name__)

THUMB = QSize(224, 126)


def bgra_image(px: np.ndarray) -> QImage:
    """(h, w, 4) BGRA uint8 -> a QImage that owns its own copy."""
    h, w = px.shape[:2]
    px = np.ascontiguousarray(px)
    return QImage(px.data, w, h, w * 4, QImage.Format_ARGB32).copy()


def thumbnail(img: QImage, size: QSize = THUMB) -> QPixmap:
    """`img` fitted into `size` and centred on a transparent tile (all tiles line up)."""
    pm = QPixmap(size)
    pm.fill(QColor(0, 0, 0, 0))
    if img.isNull():
        return pm
    scaled = img.scaled(size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    from PySide6.QtGui import QPainter
    p = QPainter(pm)
    p.drawImage((size.width() - scaled.width()) // 2, (size.height() - scaled.height()) // 2,
                scaled)
    p.end()
    return pm


class WindowPicker(QDialog):
    """`chosen` is the WindowRef picked (None until OK)."""

    def __init__(self, parent=None, current: WindowRef | None = None):
        super().__init__(parent)
        self.setWindowTitle("Pick a window to watch")
        self.resize(760, 560)
        self.chosen: WindowRef | None = None
        self._current = current
        self._wins: list[windows.WindowInfo] = []
        v = QVBoxLayout(self)
        v.addWidget(hint_label(
            "Pick the game window. It's watched even while other windows cover it, so "
            "you can alt-tab away — but not while it's minimized. With two copies of a "
            "game open, the thumbnails show which is which."))
        self.list = QListWidget()
        self.list.setViewMode(QListWidget.IconMode)
        self.list.setIconSize(THUMB)
        self.list.setGridSize(THUMB + QSize(24, 64))
        self.list.setResizeMode(QListWidget.Adjust)
        self.list.setMovement(QListWidget.Static)
        self.list.setWordWrap(True)
        self.list.setUniformItemSizes(True)
        self.list.itemDoubleClicked.connect(lambda _i: self._accept())
        self.list.currentItemChanged.connect(lambda *_: self._enable())
        v.addWidget(self.list, 1)
        row = QHBoxLayout()
        self.btn_refresh = QPushButton("Refresh")
        icons.set_icon(self.btn_refresh, "reload")
        self.btn_refresh.clicked.connect(self.refresh)
        row.addWidget(self.btn_refresh)
        row.addStretch(1)
        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.buttons.button(QDialogButtonBox.Ok).setText("Watch this window")
        self.buttons.button(QDialogButtonBox.Ok).setObjectName("primary")
        self.buttons.accepted.connect(self._accept)
        self.buttons.rejected.connect(self.reject)
        row.addWidget(self.buttons)
        v.addLayout(row)
        self._pending: list[QListWidgetItem] = []
        self._thumbs = QTimer(self)
        self._thumbs.setInterval(0)
        self._thumbs.timeout.connect(self._next_thumb)
        self.refresh()

    def refresh(self):
        """List the windows again; thumbnails fill in one by one (each is a capture)."""
        self._thumbs.stop()
        self.list.clear()
        self._wins = windows.list_windows()
        placeholder = QIcon(thumbnail(QImage()))
        self._pending = []
        pick = None
        for w in self._wins:
            ref = windows.ref_for(w, self._wins)
            text = w.label if len(w.label) <= 60 else w.label[:59] + "…"
            sub = w.exe or "?"
            if ref.nth:
                sub += f" · copy {ref.nth + 1}"
            if w.minimized:
                sub += " · minimized"
            it = QListWidgetItem(placeholder, f"{text}\n{sub}")
            it.setData(Qt.UserRole, ref)
            it.setData(Qt.UserRole + 1, w.hwnd)
            it.setToolTip(f"{w.title}\n{w.exe} — {w.width}×{w.height}")
            self.list.addItem(it)
            self._pending.append(it)
            if ref == self._current:
                pick = it
        if pick is not None:
            self.list.setCurrentItem(pick)
        self._enable()
        self._thumbs.start()

    def _next_thumb(self):
        if not self._pending:
            self._thumbs.stop()
            return
        it = self._pending.pop(0)
        try:
            px = windows.snapshot(int(it.data(Qt.UserRole + 1)))
        except OSError:
            px = None
        if px is not None:
            it.setIcon(QIcon(thumbnail(bgra_image(px))))

    def _enable(self):
        self.buttons.button(QDialogButtonBox.Ok).setEnabled(self.list.currentItem() is not None)

    def _accept(self):
        it = self.list.currentItem()
        if it is None:
            return
        self.chosen = it.data(Qt.UserRole)
        self.accept()
