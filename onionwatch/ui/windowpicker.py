"""Pick a window to watch: every open window with a live thumbnail, its title and
its program, so two copies of the same game can be told apart.

With `multi` it picks the places one trigger looks in: tick any number of windows
and screens, and for a game open more than once, "every copy" watches all of its
copies, also ones started later (one trigger for all your accounts)."""
from __future__ import annotations

import logging

import numpy as np
from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QColor, QIcon, QImage, QPixmap
from PySide6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox, QHBoxLayout, QListWidget,
                               QListWidgetItem, QPushButton, QVBoxLayout)

from onionwatch import screenwatch, theme, windows
from onionwatch.screenwatch import MAX_SOURCES, WindowRef
from onionwatch.ui import icons
from onionwatch.ui.panel import hint_label

log = logging.getLogger(__name__)

THUMB = QSize(224, 126)
PLACE = Qt.UserRole          # an item's WindowRef (or screen index)
HWND = Qt.UserRole + 1       # ...its window handle, for the thumbnail
BASE = Qt.UserRole + 2       # ...its own WindowRef, while it stands for every copy


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


def places_label(places: list) -> str:
    """A trigger's places in a few words: "Game (copy 2)", "Screen 2", "3 places"."""
    if not places:
        return ""
    if len(places) == 1:
        p = places[0]
        return p.label if isinstance(p, WindowRef) else f"Screen {p + 1}"
    return f"{len(places)} places"


class WindowPicker(QDialog):
    """`chosen` is the WindowRef picked (None until OK). With `multi`, `places` is the
    list ticked instead (windows, "every copy" windows and screen indexes), and
    `current` the list ticked to begin with."""

    def __init__(self, parent=None, current=None, multi: bool = False):
        super().__init__(parent)
        self.multi = multi
        self.setWindowTitle("Where to look" if multi else "Pick a window to watch")
        self.resize(760, 600)
        self.chosen: WindowRef | None = None
        self.places: list = []
        self._current = list(current or []) if multi else current
        self._wins: list[windows.WindowInfo] = []
        v = QVBoxLayout(self)
        v.addWidget(hint_label(
            "Tick every window (and screen) to look in: any of them counts, and each is "
            "watched on its own, so the alert says which one it was. Windows are watched "
            "even while other windows cover them, but not while they're minimized."
            if multi else
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
        self.list.itemDoubleClicked.connect(self._double)
        self.list.currentItemChanged.connect(lambda *_: self._enable())
        self.list.itemChanged.connect(lambda _i: self._enable())
        if multi:
            # tick boxes that read on a picked (accent) tile too: an outline, filled when ticked
            # (each state styled in full: Qt ignores :checked on top of a plain ::indicator)
            t = theme.T
            box = "width:16px; height:16px; border-radius:4px; "
            self.list.setStyleSheet(
                f"QListView::indicator:unchecked {{ {box}"
                f"border:2px solid {t.get('muted', '#888888')}; background:transparent; }}"
                f"QListView::indicator:checked {{ {box}"
                f"border:2px solid {t.get('text', '#ffffff')}; "
                f"background:{t.get('accent', '#1fb6a6')}; "
                f"image:url(\"{theme._check_url(t.get('on_accent', '#ffffff'))}\"); }}")
        v.addWidget(self.list, 1)
        self.chk_every = QCheckBox("Every copy of this game, also ones started later")
        self.chk_every.setToolTip("For playing several accounts: one trigger watches all the "
                                  "game's windows, and says which one it was")
        self.chk_every.toggled.connect(self._on_every)
        self.chk_every.setVisible(multi)
        v.addWidget(self.chk_every)
        row = QHBoxLayout()
        self.btn_refresh = QPushButton("Refresh")
        icons.set_icon(self.btn_refresh, "reload")
        self.btn_refresh.clicked.connect(self.refresh)
        row.addWidget(self.btn_refresh)
        row.addStretch(1)
        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.buttons.button(QDialogButtonBox.Ok).setText(
            "Look in these" if multi else "Watch this window")
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

    # ------------------------------------------------------------------ the list
    def _ticked(self) -> list:
        """What's ticked now (multi), in the list's order."""
        return [self.list.item(i).data(PLACE) for i in range(self.list.count())
                if self.list.item(i).checkState() == Qt.Checked]

    def refresh(self):
        """List the windows (and screens) again; thumbnails fill in one by one (each
        is a capture)."""
        self._thumbs.stop()
        keep = self._ticked() if self.multi and self.list.count() else None
        want = keep if keep is not None else (self._current if self.multi else [])
        self.list.blockSignals(True)
        self.list.clear()
        self._wins = windows.list_windows()
        placeholder = QIcon(thumbnail(QImage()))
        self._pending = []
        pick = None
        if self.multi:
            for i, m in enumerate(screenwatch.monitors()):
                it = QListWidgetItem(icons.icon("apps", "muted"), f"Screen {i + 1}\n{m.label}")
                it.setData(PLACE, i)
                it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
                it.setCheckState(Qt.Checked if i in want else Qt.Unchecked)
                it.setToolTip("The whole screen, windows on top included")
                self.list.addItem(it)
        seen_every: set = set()
        for w in self._wins:
            ref = windows.ref_for(w, self._wins)
            text = w.label if len(w.label) <= 60 else w.label[:59] + "…"
            sub = w.exe or "?"
            if ref.nth:
                sub += f" · copy {ref.nth + 1}"
            if w.minimized:
                sub += " · minimized"
            it = QListWidgetItem(placeholder, f"{text}\n{sub}")
            it.setData(PLACE, ref)
            it.setData(HWND, w.hwnd)
            it.setData(BASE, ref)
            it.setToolTip(f"{w.title}\n{w.exe} — {w.width}×{w.height}")
            if self.multi:
                it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
                every = WindowRef(ref.exe, ref.title, 0, True)
                if every in want and every not in seen_every and ref.nth == 0:
                    seen_every.add(every)
                    self._set_every(it, True)
                    it.setCheckState(Qt.Checked)
                else:
                    it.setCheckState(Qt.Checked if ref in want else Qt.Unchecked)
            self.list.addItem(it)
            self._pending.append(it)
            if ref == self._current or (self.multi and pick is None and ref in want):
                pick = it
        if self.multi:
            # places ticked before that aren't open now (a game not started yet): kept,
            # so OK doesn't drop them
            for p in want:
                if isinstance(p, WindowRef) and p not in seen_every and not any(
                        self.list.item(i).data(PLACE) == p for i in range(self.list.count())):
                    it = QListWidgetItem(icons.icon("window", "muted"),
                                         f"{p.label}\nnot open now")
                    it.setData(PLACE, p)
                    it.setData(BASE, p)
                    it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
                    it.setCheckState(Qt.Checked)
                    self.list.addItem(it)
        self.list.blockSignals(False)
        if pick is not None:
            self.list.setCurrentItem(pick)
        self._enable()
        self._thumbs.start()

    def _set_every(self, it: QListWidgetItem, on: bool):
        base = it.data(BASE)
        if not isinstance(base, WindowRef):
            return
        ref = WindowRef(base.exe, base.title, 0, True) if on else base
        it.setData(PLACE, ref)
        first = it.text().split("\n", 1)[0]
        sub = (base.exe or "?") + (" · every copy" if on else
                                   (f" · copy {base.nth + 1}" if base.nth else ""))
        it.setText(f"{first}\n{sub}")

    def _on_every(self, on: bool):
        it = self.list.currentItem()
        if it is None or not isinstance(it.data(BASE), WindowRef):
            return
        base = it.data(BASE)
        self.list.blockSignals(True)
        for i in range(self.list.count()):
            other = self.list.item(i)
            b = other.data(BASE)
            if other is not it and isinstance(b, WindowRef) and (b.exe, b.title) == (
                    base.exe, base.title) and on:
                self._set_every(other, False)
                other.setCheckState(Qt.Unchecked)   # covered by the every-copy one
        self._set_every(it, on)
        if on:
            it.setCheckState(Qt.Checked)
        self.list.blockSignals(False)
        self._enable()

    def _next_thumb(self):
        if not self._pending:
            self._thumbs.stop()
            return
        it = self._pending.pop(0)
        try:
            px = windows.snapshot(int(it.data(HWND)))
        except OSError:
            px = None
        if px is not None:
            it.setIcon(QIcon(thumbnail(bgra_image(px))))

    def _enable(self):
        it = self.list.currentItem()
        if self.multi:
            n = len(self._ticked())
            self.buttons.button(QDialogButtonBox.Ok).setEnabled(0 < n <= MAX_SOURCES)
            is_win = it is not None and isinstance(it.data(BASE), WindowRef)
            self.chk_every.blockSignals(True)
            self.chk_every.setEnabled(is_win)
            self.chk_every.setChecked(is_win and it.data(PLACE).every)
            self.chk_every.blockSignals(False)
            return
        self.buttons.button(QDialogButtonBox.Ok).setEnabled(it is not None)

    def _double(self, it: QListWidgetItem):
        if self.multi:
            it.setCheckState(Qt.Unchecked if it.checkState() == Qt.Checked else Qt.Checked)
        else:
            self._accept()

    def _accept(self):
        if self.multi:
            self.places = self._ticked()[:MAX_SOURCES]
            if self.places:
                self.accept()
            return
        it = self.list.currentItem()
        if it is None:
            return
        self.chosen = it.data(PLACE)
        self.accept()
