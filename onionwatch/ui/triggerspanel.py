"""The triggers page: play a sound when a picture shows up in a game — a rare
spawn's name plate, a queue-ready banner, "YOU DIED". Each trigger is a card: the
pictures to look for (cut from the watched window, files, or pasted after
Win+Shift+S; any of them showing up counts), the sounds to play and which of them
(one at random, in turn, or all at once), once or ringing until it's stopped, how
long to wait before playing, how soon it may play again, how close a match must
be, with the live match next to it so the number is easy to set, and where to
look: a window (watched even while other windows cover it) or a screen — "Same as
below" being the one picked at the bottom of the page.

The watching itself (capture and matching on a worker thread) is
onionwatch.screenwatch, windows are onionwatch.windows. Everything else comes from
the host (onionwatch.host: the Onion Watch app, or Onion Board): the saved triggers
(host.screen), the sounds and playing them, and the folder the pictures are kept
in (host.data_dir / "triggers").
"""
from __future__ import annotations

import logging
import math
import os
import time
import uuid
from collections import deque
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PySide6.QtCore import QEvent, QPoint, QRect, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFontMetrics, QIcon, QImage, QPixmap
from PySide6.QtWidgets import (QApplication, QBoxLayout, QCheckBox, QComboBox, QDoubleSpinBox,
                               QFileDialog, QFrame, QHBoxLayout, QLabel, QLineEdit, QMenu,
                               QMessageBox, QPushButton, QScrollArea, QSizePolicy, QSpinBox,
                               QVBoxLayout, QWidget)

from onionwatch import owl, packs, profiles, screenwatch, theme, windows
from onionwatch.screenwatch import (INTERVALS_MS, MAX_PICTURES, MAX_SOUNDS, Monitor, Picture,
                                    Trigger, Watched, WindowRef)
from onionwatch.shuffle import ShuffleBag
from onionwatch.ui import icons
from onionwatch.ui.categories import CategorySection, ProfilesDialog, counts_text
from onionwatch.ui.history import HistoryDialog
from onionwatch.ui.panel import Flow, UndoBar, card, hint_label
from onionwatch.ui.windowpicker import places_label
from onionwatch.wheelguard import no_wheel

log = logging.getLogger(__name__)

PICTURE_EXTS = "*.png *.jpg *.jpeg *.bmp *.webp *.gif"
ADD = "__add__"         # the sound list's "+ Add sound…" entry (its resting state)
FILE = "__file__"       # ...its "Choose a sound file…" entry
PICK_WINDOW = "__pick_window__"   # a "Look in" list's "Pick a window…" entry
DEFAULT = "__default__"           # ...its "Same as below" entry
PLACES = "__places__"             # ...the trigger's own windows and screens
NEW_CATEGORY = "__new_category__"   # a card's Category list's "New category…" entry
POLL_MS = 150           # how often the live match numbers refresh
MAX_TRIGGERS = 500      # in all; how many can be on at once is up to the computer
MAX_SIDE = 8192         # bigger pictures are refused (kept pixel for pixel, never resized)
CUT_KEY = "OnionWatch cut from"   # a picture's PNG text: the size of what it was cut from
THUMB = QSize(96, 54)
STRIP_THUMBS = 3        # thumbnails a card's strip shows before it scrolls
CHIP_CHARS = 24         # a sound chip's name is cut to this many characters
PICKS = (("random", "Random"), ("order", "In order"), ("all", "All at once"))
MODES = (("appear", "it shows up"), ("vanish", "it goes away"),
         ("change", "the area changes"), ("still", "the area stops changing"),
         ("colour", "a bar runs low"))
LEVELS = {"change": 0.05, "still": 0.01, "colour": 0.30}   # a new mode's starting level
# what stops a ringing trigger by itself (Trigger.stop): its words on the card, on
# its state line and in the alert, and a tooltip
UNTILS = {
    "moves": ("until the game moves", "Rings until the game moves",
              "Ringing until the game moves.",
              "Stops once anything moves where it looks (you're back and playing), or "
              "when it goes away. It waits for the screen to settle first, so a fade-in "
              "doesn't stop it. A bar: once it's back over its line."),
    "focus": ("until I switch to the game", "Rings until you switch to the game",
              "Ringing until you switch to it.",
              "Stops when you alt-tab back to its window. Watching a whole screen: when "
              "you switch to any other window."),
    "gone": ("until it's gone", "Rings until it's gone", "Ringing until it's gone.",
             "Stops when the picture goes away (or the bar is back, or the area settles)."),
    "input": ("until I touch mouse or keys", "Rings until you touch the mouse or keyboard",
              "Ringing until you touch the mouse or keyboard.",
              "Stops as soon as you move the mouse or press a key, anywhere."),
    "manual": ("until I click Stop", "Rings until stopped", "Ringing until you stop it.",
               "Only the Stop button on the red bar (or the tray icon) stops it."),
}
INPUT_POLL_MS = 100     # how often an "input" ring checks for the mouse or keyboard


HISTORY = 50            # alerts kept in the history (in memory only)
APP_POLL_MS = 2000      # how often Automatic profiles look at which programs are open
BUILD_NOW = 60          # an opened category's cards made at once; the rest a few at a
BUILD_STEP = 20         # ...time, so a category of hundreds doesn't freeze the window
HEAVY_GAP = 0.5         # s: checks spaced out further than this (to keep to 1 % of the
HEAVY_FOR = 5.0         # ...processor) for this long: say too many pictures are on
EDIT_PROFILES = "__edit_profiles__"   # the Profile list's "Edit profiles…"
KEEP_DAYS = 30          # deleted triggers stay in Recently deleted this long
MAX_DELETED = 50        # ...and at most this many of them


@dataclass
class Alert:
    """Something that went off, for the history: when, which trigger, where, how
    strongly, and what the watched window looked like then (the check's own small
    copy, the box around what set it off drawn on it)."""
    when: float
    name: str
    place: str
    score: float
    mode: str
    picture: QImage

    @classmethod
    def of(cls, t: Trigger, hit: screenwatch.Hit, place: str) -> Alert:
        return cls(time.time(), t.name, place, hit.score, t.mode, hit_image(hit))


def hit_image(hit: screenwatch.Hit) -> QImage:
    """The frame a Hit was seen in, with its box drawn round what set it off."""
    from PySide6.QtGui import QPainter, QPen
    f = hit.frame
    if f is None or f.ndim < 2 or not f.size:
        return QImage()
    f = np.ascontiguousarray(f)
    h, w = f.shape[:2]
    if f.ndim == 3:
        img = QImage(f.data, w, h, w * 3, QImage.Format_RGB888).copy()
    else:
        img = QImage(f.data, w, h, w, QImage.Format_Grayscale8).copy()
    img = img.convertToFormat(QImage.Format_RGB32)
    x, y, bw, bh = hit.box
    p = QPainter(img)
    p.setPen(QPen(QColor(theme.T.get("accent", "#1fb6a6")), 2))
    p.drawRect(round(x * w), round(y * h), max(2, round(bw * w)), max(2, round(bh * h)))
    p.end()
    return img


def pictures_dir(host) -> Path:
    """Where a host's trigger pictures are kept."""
    return Path(host.data_dir) / "triggers"


def load_picture(path: str) -> Picture | None:
    """A picture file as grey float32 0..1, plus which pixels count: the opaque ones
    (None when it has no transparency). Transparent parts are left out of matching."""
    return picture_of(QImage(path))


def picture_tint(img: QImage) -> np.ndarray | None:
    """The picture's colours in brief (screenwatch.tint), so a place matching it in
    grey but not in colour doesn't count."""
    if img.isNull():
        return None
    img = img.convertToFormat(QImage.Format_ARGB32)
    h, w = img.height(), img.width()
    buf = np.frombuffer(img.constBits(), np.uint8, count=img.bytesPerLine() * h)
    bgra = buf.reshape(h, img.bytesPerLine())[:, :w * 4].reshape(h, w, 4)
    rgb = bgra[..., 2::-1].astype(np.float32) * (1 / 255)
    mask = bgra[..., 3] >= 128
    return screenwatch.tint(rgb, None if mask.all() else mask)


def cut_size(img: QImage) -> tuple[int, int] | None:
    """The (w, h) of the window or screen a picture was cut from, kept in its PNG
    (see set_cut_size); None when it isn't known."""
    w, _x, h = img.text(CUT_KEY).partition("x")
    try:
        size = int(w), int(h)
    except ValueError:
        return None
    return size if 0 < min(size) and max(size) <= 65536 else None


def set_cut_size(img: QImage, size: tuple[int, int] | None):
    """Note in the picture (a text field of its PNG) the size of what it was cut from,
    so with "any size" it's looked for at the size the game draws it now."""
    if size and min(size) > 0:
        img.setText(CUT_KEY, f"{size[0]}x{size[1]}")


def picture_of(img: QImage) -> Picture | None:
    """load_picture() for a picture already in memory."""
    if img.isNull():
        return None
    img = img.convertToFormat(QImage.Format_ARGB32)   # B, G, R, A in memory
    h, w = img.height(), img.width()
    buf = np.frombuffer(img.constBits(), np.uint8, count=img.bytesPerLine() * h)
    bgra = buf.reshape(h, img.bytesPerLine())[:, :w * 4].reshape(h, w, 4)
    mask = bgra[..., 3] >= 128
    return screenwatch.to_gray(bgra), (None if mask.all() else mask)


def save_picture(img: QImage, name: str, folder: Path) -> str:
    """Keep a copy of the picture as <folder>/<name>.png; returns its path. It's kept
    pixel for pixel: resized, it would no longer match the screen it was cut from.
    Written beside it first, so a failed save leaves the old picture as it was."""
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{name}.png"
    tmp = folder / f"{name}.saving"
    if not img.save(str(tmp), "PNG"):
        tmp.unlink(missing_ok=True)
        raise OSError(f"couldn't save the picture to {path}")
    os.replace(tmp, path)
    return str(path)


def picture_name(t: Trigger, folder: Path) -> str:
    """A file name (without .png) for a picture being added to `t`: <id> for the
    first, as older versions saved it, then <id>-<random> so removing and adding
    pictures never reuses a name."""
    if not t.images and not (folder / f"{t.id}.png").exists():
        return t.id
    return f"{t.id}-{uuid.uuid4().hex[:6]}"


def _num(v) -> float:
    """A number from the saved settings, whatever was written there (0 if not one)."""
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else 0.0


def delete_picture(path: str, folder: Path):
    """Remove a picture file this tab keeps in `folder` (never one the user pointed at)."""
    if path and Path(path).parent == folder:
        try:
            Path(path).unlink(missing_ok=True)
        except OSError:
            log.debug("couldn't delete %s", path, exc_info=True)


def narrow(combo: QComboBox, chars: int) -> QComboBox:
    """A list that doesn't grow to its longest entry (the window must fit 300 px)."""
    combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
    combo.setMinimumContentsLength(chars)
    return combo


class WideCombo(QComboBox):
    """A list as wide as its longest entry when there's room ("Screen 2: 1920×1080"
    isn't cut off) that still gives way when the window is small. A plain
    AdjustToContents list can never be narrower than its entries, and the tab, so
    the whole window, then can't shrink below it (the window must fit 300 px)."""

    MIN_WIDTH = 90

    def __init__(self, parent: QWidget | None = None, min_width: int = MIN_WIDTH):
        super().__init__(parent)
        self.min_width = min_width
        self.setSizeAdjustPolicy(QComboBox.AdjustToContents)   # sizeHint: the entries
        pol = self.sizePolicy()
        pol.setHorizontalPolicy(QSizePolicy.Maximum)   # up to that, down to min_width
        self.setSizePolicy(pol)

    def minimumSizeHint(self) -> QSize:
        s = super().minimumSizeHint()
        return QSize(min(s.width(), self.min_width), s.height())


def labelled(text: str, w: QWidget) -> QWidget:
    """`text` and its control kept together on one line of a wrapping row."""
    box = QWidget()
    box.setObjectName("labelled")   # see-through, whichever program's stylesheet is in use
    box.setStyleSheet("QWidget#labelled { background: transparent; }")
    h = QHBoxLayout(box)
    h.setContentsMargins(0, 0, 0, 0)
    h.setSpacing(6)
    if text:
        h.addWidget(QLabel(text))
    h.addWidget(w)
    return box


def flatness(gray: np.ndarray, mask: np.ndarray | None = None) -> float:
    """How much detail there is to recognise (the opaque part's spread of greys)."""
    px = gray if mask is None else gray[mask]
    return float(px.std()) if px.size >= 16 else 0.0


def plural(n: int, word: str) -> str:
    return f"{n} {word}" + ("" if n == 1 else "s")


class Thumb(QWidget):
    """One picture in a card's strip: the thumbnail (click to see it big, with the
    trigger's other pictures) with a ✕ in its corner while the mouse is over it."""
    clicked = Signal(int)
    removed = Signal(int)

    def __init__(self, index: int, path: str):
        super().__init__()
        self.index = index
        self.pic = QPushButton(self)
        self.pic.setFixedSize(THUMB + QSize(8, 8))
        self.pic.setIconSize(THUMB)
        self.pic.setCursor(Qt.PointingHandCursor)
        self.pic.clicked.connect(lambda: self.clicked.emit(self.index))
        pm = QPixmap(path) if path else QPixmap()
        if pm.isNull():
            self.pic.setIcon(icons.icon("image", "muted"))
            self.pic.setToolTip(f"{Path(path).name}: this picture can't be read — click to "
                                "open it and swap it for another file")
        else:
            self.pic.setIcon(pm.scaled(THUMB, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            self.pic.setToolTip(f"{Path(path).name} ({pm.width()}×{pm.height()})\n"
                                "Click to see it big")
        self.setFixedSize(self.pic.size())
        self.x = QPushButton("✕", self)
        self.x.setObjectName("danger")
        self.x.setStyleSheet("padding:0; font-size:8pt;")
        self.x.setFixedSize(18, 18)
        self.x.setToolTip("Remove this picture")
        self.x.move(self.width() - self.x.width() - 3, 3)
        self.x.clicked.connect(lambda: self.removed.emit(self.index))
        self.x.hide()

    def enterEvent(self, ev):
        self.x.show()
        self.x.raise_()
        super().enterEvent(ev)

    def leaveEvent(self, ev):
        self.x.hide()
        super().leaveEvent(ev)


class Strip(QScrollArea):
    """A card's pictures in a row: up to STRIP_THUMBS wide, scrolling sideways
    past that, so a trigger with a hundred pictures stays a short card."""
    picture_clicked = Signal(int)
    picture_removed = Signal(int)

    def __init__(self):
        super().__init__()
        self.setFrameShape(QFrame.NoFrame)
        self.setWidgetResizable(True)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.box = QWidget()
        self.row = QHBoxLayout(self.box)
        self.row.setContentsMargins(0, 0, 0, 0)
        self.row.setSpacing(4)
        self.row.addStretch(1)
        self.setWidget(self.box)
        self.thumbs: list[Thumb] = []
        self._h = 0
        self._fit_height()

    @property
    def slot(self) -> int:
        return THUMB.width() + 8 + self.row.spacing()

    def set_paths(self, paths: list[str]):
        for th in self.thumbs:
            self.row.removeWidget(th)
            th.setParent(None)   # out of the strip now, not when the event loop gets to it
            th.deleteLater()
        self.thumbs = []
        for i, p in enumerate(paths):
            th = Thumb(i, p)
            th.clicked.connect(self.picture_clicked)
            th.removed.connect(self.picture_removed)
            self.row.insertWidget(i, th)
            self.thumbs.append(th)
        self.updateGeometry()
        self._fit_height()

    def sizeHint(self) -> QSize:
        n = min(max(len(self.thumbs), 1), STRIP_THUMBS)
        return QSize(n * self.slot, self._h)

    def minimumSizeHint(self) -> QSize:
        return QSize(self.slot, self._h)

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self._fit_height()

    def _fit_height(self):
        """The thumbnails' height, plus the scrollbar's only when there's more than fits."""
        h = THUMB.height() + 8
        if len(self.thumbs) * self.slot - self.row.spacing() > self.viewport().width():
            h += self.horizontalScrollBar().sizeHint().height()
        if h != self._h:
            self._h = h
            self.setFixedHeight(h)


def fill_sources(cb: QComboBox, mons: list[Monitor], places: list,
                 default_label: str = "", pick_label: str = "Pick a window…") -> None:
    """Fill a "Look in" list: "Same as below" (when `default_label`), each screen,
    the chosen window(s), then `pick_label`. The current choice is selected: the
    places when there are some (one screen, or its windows and screens in a few
    words), else the default (or the first screen)."""
    cb.blockSignals(True)
    cb.clear()
    current = 0
    if default_label:
        cb.addItem(default_label, DEFAULT)
    one = places[0] if len(places) == 1 and not isinstance(places[0], WindowRef) else None
    for i, m in enumerate(mons):
        cb.addItem(icons.icon("apps", "muted"), f"Screen {i + 1}: {m.label}", i)
        if one == i:
            current = cb.count() - 1
    if not mons and not default_label:
        cb.addItem(icons.icon("apps", "muted"), "Main screen", 0)
    if one is not None and not 0 <= one < len(mons) and mons:
        cb.addItem(f"Screen {one + 1} (not plugged in)", one)
        current = cb.count() - 1
    if places and one is None:
        cb.addItem(icons.icon("window"), places_label(places), PLACES)
        cb.setItemData(cb.count() - 1, "\n".join(
            p.label if isinstance(p, WindowRef) else f"Screen {p + 1}" for p in places),
            Qt.ToolTipRole)
        current = cb.count() - 1
    cb.insertSeparator(cb.count())
    cb.addItem(icons.icon("window", "muted"), pick_label, PICK_WINDOW)
    cb.setCurrentIndex(current)
    cb.blockSignals(False)


def source_label(src, mons: list[Monitor]) -> str:
    if isinstance(src, WindowRef):
        return src.label
    if isinstance(src, int) and len(mons) > 1:
        return f"screen {src + 1}"
    return "the screen"


def swatch(colour: str, size: int = 14) -> QIcon:
    pm = QPixmap(size, size)
    pm.fill(QColor(colour) if colour else QColor(0, 0, 0, 0))
    return QIcon(pm)


class FlowBox(QWidget):
    """A wrapping row (Flow) that takes the height its lines need at its width. A
    Flow's height-for-width isn't passed up through the scrolling list of cards,
    so on its own a row that wraps overlaps what's below it, or runs off the edge."""

    def __init__(self, gap: int = 6, parent=None):
        super().__init__(parent)
        self.flow = Flow(self, gap=gap)

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self._fit()

    def showEvent(self, ev):
        super().showEvent(ev)
        self._fit()

    def _fit(self):
        h = self.flow.heightForWidth(max(self.width(), 1))
        if h != self.minimumHeight():
            self.setMinimumHeight(h)


class BarFlow(Flow):
    """The bottom bar's Flow: an item that doesn't fit the rest of a line gives way,
    down to its minimum (a Pair: to what keeps it on one line), before it wraps, and
    is as tall as it needs at the width it gets (a Pair on two lines)."""

    def _place(self, rect: QRect, move: bool) -> int:
        x, y, line = rect.x(), rect.y(), 0
        for it in self._items:
            if it.isEmpty():
                continue
            wid = it.widget()
            pair = wid if isinstance(wid, Pair) else None
            hint, least = it.sizeHint(), it.minimumSize().width()
            keep = pair.one_line_width() if pair else least
            if line and x + keep > rect.right() + 1:        # doesn't fit here: next line
                x, y, line = rect.x(), y + line + self._gap, 0
            w = max(least, min(hint.width(), rect.right() + 1 - x))
            # (asked directly: Qt asks a widget's layout, not the widget)
            h = pair.heightForWidth(w) if pair else hint.height()
            if move:
                it.setGeometry(QRect(QPoint(x, y), QSize(w, h)))
            x += w + self._gap
            line = max(line, h)
        return y + line - rect.y()


class Pair(QWidget):
    """Two labelled controls that read as one ("Look in [game] every [100 ms]"): on
    one line while it's wide enough for both, the second under the first when it
    isn't. A label never ends up apart from its control."""

    GAP, STACKED = 10, 6    # px between them: side by side, one under the other

    def __init__(self, first: QWidget, second: QWidget, parent=None):
        super().__init__(parent)
        self.setObjectName("labelled")      # see-through, like labelled()'s boxes
        self.setStyleSheet("QWidget#labelled { background: transparent; }")
        self.first, self.second = first, second
        self.box = QBoxLayout(QBoxLayout.LeftToRight, self)
        self.box.setContentsMargins(0, 0, 0, 0)
        self.box.setSpacing(self.GAP)
        self.box.addWidget(first, 0, Qt.AlignLeft)
        self.box.addWidget(second, 0, Qt.AlignLeft)
        self.box.addStretch(1)

    def one_line_width(self) -> int:
        """The least it can be with both on one line."""
        return (self.first.minimumSizeHint().width() + self.GAP
                + self.second.minimumSizeHint().width())

    def _one_line(self, w: int) -> bool:
        return w >= self.one_line_width()

    def sizeHint(self) -> QSize:
        a, b = self.first.sizeHint(), self.second.sizeHint()
        return QSize(a.width() + self.GAP + b.width(), max(a.height(), b.height()))

    def minimumSizeHint(self) -> QSize:
        a, b = self.first.minimumSizeHint(), self.second.minimumSizeHint()
        return QSize(max(a.width(), b.width()), max(a.height(), b.height()))

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, w: int) -> int:
        a, b = self.first.sizeHint().height(), self.second.sizeHint().height()
        return max(a, b) if self._one_line(w) else a + self.STACKED + b

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        one = self._one_line(self.width())
        self.box.setDirection(QBoxLayout.LeftToRight if one else QBoxLayout.TopToBottom)
        self.box.setSpacing(self.GAP if one else self.STACKED)


class Switch(QCheckBox):
    """An on / off switch: a checkbox drawn as a sliding pill, in the theme's colours."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(40, 22)

    def sizeHint(self):
        return QSize(40, 22)

    def hitButton(self, pos):
        return self.rect().contains(pos)

    def paintEvent(self, _e):
        from PySide6.QtCore import QRectF
        from PySide6.QtGui import QPainter
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        on = self.isChecked()
        p.setBrush(QColor(theme.T.get("accent" if on else "off", "#888888")))
        p.drawRoundedRect(QRectF(0, 0, 40, 22), 11, 11)
        p.setBrush(QColor(theme.T.get("on_accent", "#ffffff") if on else "#ffffff"))
        p.drawEllipse(QRectF(21 if on else 3, 3, 16, 16))


def divider() -> QFrame:
    """A thin line between a card's parts, in the palette's colours (the host's theme
    doesn't know about it)."""
    f = QFrame()
    f.setObjectName("carddivider")
    f.setFixedHeight(1)
    f.setStyleSheet("QFrame#carddivider { background: palette(mid); border: none; }")
    return f


def indented(parent: QVBoxLayout, spacing: int = 8) -> QVBoxLayout:
    """A column under a section's title, set in a little so the title stands out."""
    box = QWidget()
    box.setObjectName("labelled")
    box.setStyleSheet("QWidget#labelled { background: transparent; }")
    col = QVBoxLayout(box)
    col.setContentsMargins(SECTION_INDENT, 0, 0, 0)
    col.setSpacing(spacing)
    parent.addWidget(box)
    return col


SECTION_INDENT = 20     # px: a section's settings, in from its title


def section_title(icon: str, text: str) -> QPushButton:
    """A card section's title: its icon and name in capitals (not clickable)."""
    b = QPushButton(text.upper())
    b.setObjectName("fold")
    b.setFocusPolicy(Qt.NoFocus)
    b.setAttribute(Qt.WA_TransparentForMouseEvents)
    b.setStyleSheet("text-align:left; padding-left:0;")
    icons.set_icon(b, icon, "section", size=13)
    return b


class TriggerRow(QFrame):
    """One trigger's card: a header (pictures, name, what it does, the live match,
    on / off) that opens to three parts: what to watch for, what happens then, and
    the fine-tuning, folded away behind a line summing it up."""
    changed = Signal(object)             # row: a setting changed
    pictures_wanted = Signal(object)     # row: "+ Add pictures…" (files)
    paste_wanted = Signal(object)        # row: "Paste picture"
    cut_wanted = Signal(object)          # row: "Cut from window…"
    picture_view = Signal(object, int)   # row, index: a thumbnail was clicked: show it big
    picture_swap = Signal(object, int)   # row, index: swap that picture for another file
    picture_removed = Signal(object, int)  # row, index
    sound_file_wanted = Signal(object)   # row: "Choose a sound file…"
    window_wanted = Signal(object)       # row: "Pick windows…"
    area_wanted = Signal(object)         # row: "Area…"
    duplicate = Signal(object)           # row: "Duplicate"
    category_wanted = Signal(object, str)  # row, category: moved there (NEW_CATEGORY: ask)
    hear = Signal(str)                   # a sound chip was clicked: play that sound id
    test = Signal(object)
    remove = Signal(object)

    def __init__(self, t: Trigger, sounds: list[tuple[str, str]],
                 screens: list[Monitor] = (), open_: bool = False):
        super().__init__()
        self.setObjectName("card")
        self.t = t
        self.missing: list[str] = []    # its sounds that are no longer in the library
        self.fallback = False           # its own screen isn't there: the default is watched
        self.note: tuple[str, str] | None = None   # (text, tone) from watching: not open…
        self._screens = 0               # how many screens there are
        self._mons: list[Monitor] = []
        self._sounds: list[tuple[str, str]] = []   # the sounds as last given
        self._narrow = False            # too narrow for the header's thumbnail
        v = QVBoxLayout(self)
        v.setContentsMargins(14, 12, 14, 12)
        v.setSpacing(10)

        # the header, always shown: its pictures, name, what it does (or what's wrong),
        # the live match, on / off, and open / close. Click it to open the rest
        top = QHBoxLayout()
        top.setSpacing(14)
        self.strip = Strip()
        self.strip.setToolTip("The pictures to look for: any of them showing up plays the "
                              "sound. Click one to see it big.")
        self.strip.picture_clicked.connect(lambda i: self.picture_view.emit(self, i))
        self.strip.picture_removed.connect(lambda i: self.picture_removed.emit(self, i))
        top.addWidget(self.strip, 0, Qt.AlignTop)
        self.badge = QLabel()           # instead of the strip, for a trigger without pictures
        self.badge.setObjectName("iconlabel")
        self.badge.setFixedSize(THUMB + QSize(8, 8))
        self.badge.setAlignment(Qt.AlignCenter)
        top.addWidget(self.badge, 0, Qt.AlignTop)
        names = QVBoxLayout()
        names.setSpacing(4)
        self.name = QLineEdit(t.name)
        # a title until you click it. Styled here, in the palette's colours, rather than
        # in the theme: the host's theme (Onion Board's) doesn't know about it
        self.name.setObjectName("cardname")
        self.name.setStyleSheet(
            "QLineEdit#cardname { background:transparent; border:1px solid transparent;"
            " padding:2px 3px; font-size:11pt; font-weight:700; }"
            "QLineEdit#cardname:hover { border-color:palette(mid); }"
            "QLineEdit#cardname:focus { background:palette(base);"
            " border-color:palette(highlight); }")
        self.name.setToolTip("Click to rename it")
        self.name.setMinimumWidth(50)
        self.name.setPlaceholderText("Name, e.g. Rare spawn")
        self.name.setMaxLength(60)
        self.name.setCursorPosition(0)          # a long name shows its start, not its end
        self.name.editingFinished.connect(self._on_name)
        self.name.editingFinished.connect(lambda: self.name.setCursorPosition(0))
        # as wide as the name, not the whole card: the hover / editing box hugs it
        self.name.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)   # up to that
        self.name.textChanged.connect(self._fit_name)
        self._fit_name()
        line = QHBoxLayout()            # the name takes what it needs, the rest is empty
        line.setSpacing(0)
        line.addWidget(self.name, 100)
        line.addStretch(1)
        names.addLayout(line)
        self.state = QLabel()
        self.state.setObjectName("hint")
        self.state.setIndent(4)     # lines up with the name's text (its border + padding)
        self.state.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        names.addWidget(self.state)
        names.addStretch(1)
        top.addLayout(names, 1)
        self.live = QLabel("—")
        self.live.setMinimumWidth(48)
        self.live.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        top.addWidget(self.live, 0, Qt.AlignTop)
        self.chk_on = Switch()
        self.chk_on.setToolTip("Watch for this trigger (switch it off to keep it but pause it)")
        self.chk_on.setChecked(t.enabled)
        self.chk_on.toggled.connect(self._on_enabled)
        top.addWidget(self.chk_on, 0, Qt.AlignTop)
        self.btn_open = QPushButton()
        self.btn_open.setObjectName("fold")
        self.btn_open.setCheckable(True)
        self.btn_open.setFixedWidth(30)
        self.btn_open.toggled.connect(self.set_open)
        top.addWidget(self.btn_open, 0, Qt.AlignTop)
        v.addLayout(top)

        self.body = QWidget()
        sp = self.body.sizePolicy()
        sp.setHeightForWidth(True)          # its rows wrap: taller when narrower
        self.body.setSizePolicy(sp)
        bv = QVBoxLayout(self.body)
        bv.setContentsMargins(0, 0, 0, 0)
        bv.setSpacing(6)
        v.addWidget(self.body)

        # WATCH FOR: what sets it off, where, in which part, and its pictures. One
        # line under the header; the sections below it are set apart by space alone
        bv.addWidget(divider())
        bv.addSpacing(4)
        bv.addWidget(section_title("triggers", "Watch for"))
        watch_col = indented(bv, 10)
        watch = FlowBox(gap=10)
        row = watch.flow
        self.mode = WideCombo(min_width=120)
        for key, label in MODES:
            self.mode.addItem(label, key)
        self.mode.setCurrentIndex(max(self.mode.findData(t.mode), 0))
        self.mode.setToolTip(
            "What sets it off:\n"
            "• it shows up: one of its pictures appears\n"
            "• it goes away: its picture disappears (a buff running out, a bobber)\n"
            "• the area changes: anything moves in its area (a chat line, the minimap)\n"
            "• the area stops changing: nothing moves for a while (stuck, idle, "
            "disconnected)\n"
            "• a bar runs low: less of its area is one colour (a health bar)")
        no_wheel(self.mode)
        self.mode.activated.connect(self._on_mode)
        row.addWidget(labelled("When", self.mode))
        self.where = WideCombo(min_width=120)
        self.where.setToolTip("Where to look: game windows (watched even while other windows "
                              "cover them, but not while they're minimized) or whole "
                              "screens. “Pick windows…” can tick several, or every copy of "
                              "a game. “Same as below” is the choice at the bottom.")
        no_wheel(self.where)
        self.where.activated.connect(self._on_where)
        self.where_box = labelled("in", self.where)
        row.addWidget(self.where_box)
        self.btn_area = QPushButton()
        self.btn_area.setObjectName("small")
        self.btn_area.clicked.connect(lambda: self.area_wanted.emit(self))
        row.addWidget(self.btn_area)
        watch_col.addWidget(watch)
        self._watch_row = row
        self.chk_quiet = QCheckBox("Not while I'm in that window")
        self.chk_quiet.setToolTip("Stay quiet while the window it went off in is the one "
                                  "you're using: you can see it yourself")
        self.chk_quiet.setChecked(t.unfocused)
        self.chk_quiet.toggled.connect(self._on_quiet)
        self.btn_dup = QPushButton("Duplicate")
        self.btn_dup.setObjectName("small")
        self.btn_dup.setToolTip("Make a copy of this trigger (pictures, sounds and all)")
        self.btn_dup.clicked.connect(lambda: self.duplicate.emit(self))
        self.btn_del = QPushButton("Delete")
        self.btn_del.setObjectName("small")
        self.btn_del.setToolTip("Delete this trigger (Recently deleted keeps it a while)")
        icons.set_icon(self.btn_del, "trash", size=13)
        self.btn_del.clicked.connect(lambda: self.remove.emit(self))

        self.pictures_box = FlowBox(gap=10)
        self.pictures_box.setObjectName("labelled")
        self.pictures_box.setStyleSheet("QWidget#labelled { background: transparent; }")
        row = self.pictures_box.flow
        self.count = QLabel()
        self.count.setObjectName("muted")
        row.addWidget(self.count)
        self.btn_cut = QPushButton("Cut from window…")
        self.btn_cut.setObjectName("small")
        self.btn_cut.setToolTip("Cut a picture out of the window (or screen) this trigger "
                                "watches, and add it")
        icons.set_icon(self.btn_cut, "crop", size=13)
        self.btn_cut.clicked.connect(lambda: self.cut_wanted.emit(self))
        row.addWidget(self.btn_cut)
        self.btn_pictures = QPushButton("+ Add pictures…")
        self.btn_pictures.setObjectName("small")
        self.btn_pictures.setToolTip(f"Add picture files to this trigger (up to {MAX_PICTURES}): "
                                     "any of them showing up plays the sound")
        self.btn_pictures.clicked.connect(lambda: self.pictures_wanted.emit(self))
        row.addWidget(self.btn_pictures)
        self.btn_paste = QPushButton("Paste picture")
        self.btn_paste.setObjectName("small")
        self.btn_paste.setToolTip("Add the picture you copied (Win+Shift+S cuts a piece of "
                                  "the screen) to this trigger")
        self.btn_paste.clicked.connect(lambda: self.paste_wanted.emit(self))
        row.addWidget(self.btn_paste)
        self.chk_size = QCheckBox("Any size")
        self.chk_size.setToolTip(
            "Find the pictures even when the game shows them bigger or smaller than when "
            "they were cut: cut in fullscreen, played in a window, or another UI scale.\n"
            "Untick it if a picture only ever shows at one size and it goes off by mistake.")
        self.chk_size.setChecked(t.any_size)
        self.chk_size.toggled.connect(self._on_size)
        row.addWidget(self.chk_size)
        watch_col.addWidget(self.pictures_box)

        # THEN: "Play", the chips (one per sound), "+ Add sound…", the Play mode, "Ring"
        # and until, the test button: a wrapping row, rebuilt by _layout_sounds when the
        # chips change
        bv.addSpacing(8)
        bv.addWidget(section_title("bell", "Then"))
        then_col = indented(bv)
        self.sounds_box = FlowBox(gap=10)
        self.sounds_row = self.sounds_box.flow
        self.lbl_play = QLabel("Play")
        self.chips: list[QFrame] = []
        self.sound = QComboBox()
        narrow(self.sound, 10)
        self.sound.setToolTip("Add a sound to play: a built-in alert, or a sound file of yours")
        no_wheel(self.sound)
        self.sound.activated.connect(self._on_sound)
        self.pick = WideCombo()
        for key, label in PICKS:
            self.pick.addItem(label, key)
        self.pick.setCurrentIndex(max(self.pick.findData(t.pick), 0))
        self.pick.setToolTip("With several sounds: play one at random (each once before any "
                             "repeats), take them in turn, or play them all at once")
        no_wheel(self.pick)
        self.pick.currentIndexChanged.connect(self._on_pick)
        self.chk_ring = QCheckBox("Ring")
        self.chk_ring.setToolTip("Keep playing the sound over and over — for when you're "
                                 "away from the keyboard. The Stop button on the red bar "
                                 "always stops it; pick what else does next to it.")
        self.chk_ring.setChecked(t.ring)
        self.chk_ring.toggled.connect(self._on_ring)
        self.until = WideCombo()
        for key, (label, *_rest) in UNTILS.items():
            self.until.addItem(label, key)
            self.until.setItemData(self.until.count() - 1, UNTILS[key][3], Qt.ToolTipRole)
        self.until.setCurrentIndex(max(self.until.findData(t.stop), 0))
        self.until.setToolTip("What stops the ringing by itself")
        self.until.setVisible(t.ring)
        no_wheel(self.until)
        self.until.currentIndexChanged.connect(self._on_until)
        self.btn_test = QPushButton("Test")
        self.btn_test.setToolTip("Play now, as the trigger would, to check it")
        icons.set_icon(self.btn_test, "play", size=14)
        self.btn_test.clicked.connect(lambda: self.test.emit(self))
        then_col.addWidget(self.sounds_box)

        # FINE-TUNE: the numbers, folded away behind a line saying what they are
        bv.addSpacing(8)
        tune = QHBoxLayout()
        tune.setSpacing(12)
        self.btn_tune = QPushButton("FINE-TUNE")
        self.btn_tune.setObjectName("fold")
        self.btn_tune.setCheckable(True)
        self.btn_tune.setToolTip("How alike, how long, how often, and when to keep quiet")
        icons.set_icon(self.btn_tune, "setup", "section", "section", size=13)
        self.btn_tune.toggled.connect(self._on_tune)
        tune.addWidget(self.btn_tune)
        self.tune_text = QLabel()
        self.tune_text.setObjectName("hint")
        self.tune_text.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        tune.addWidget(self.tune_text, 1)
        tune.addWidget(self.btn_dup)    # on Fine-tune's line: no row of their own
        tune.addWidget(self.btn_del)
        bv.addLayout(tune)
        tune_col = indented(bv)
        self.tune = FlowBox(gap=12)
        self.tune.setVisible(False)
        row = self.tune.flow
        self._tune_row = row
        self.delay = QDoubleSpinBox()
        self.delay.setRange(0.0, 60.0)
        self.delay.setDecimals(1)
        self.delay.setSingleStep(0.5)
        self.delay.setSuffix(" s")
        self.delay.setValue(t.delay)
        self.delay.setToolTip("How long after it goes off to play the sound "
                              "(0 = straight away)")
        row.addWidget(labelled("Wait", self.delay))
        self.cooldown = QDoubleSpinBox()
        self.cooldown.setRange(0.0, 600.0)
        self.cooldown.setDecimals(0)
        self.cooldown.setSingleStep(1.0)
        self.cooldown.setSuffix(" s")
        self.cooldown.setValue(t.cooldown)
        self.cooldown.setToolTip("After playing, ignore this trigger for this long. It also "
                                 "has to stop before it can play again.")
        row.addWidget(labelled("Not again for", self.cooldown))
        self.hold = QDoubleSpinBox()
        self.hold.setRange(0.0, screenwatch.MAX_HOLD)
        self.hold.setDecimals(1)
        self.hold.setSingleStep(0.5)
        self.hold.setSuffix(" s")
        self.hold.setValue(t.hold)
        self.lbl_hold = QLabel()
        self.hold_box = hold = labelled("", self.hold)
        hold.layout().insertWidget(0, self.lbl_hold)
        row.addWidget(hold)
        self.threshold = QSpinBox()
        self.threshold.setObjectName("stepper")   # arrows like Wait / Not again for
        self.threshold.setSuffix(" %")
        self.below = WideCombo(min_width=70)
        self.below.addItem("below", True)
        self.below.addItem("above", False)
        self.below.setCurrentIndex(0 if t.below else 1)
        self.below.setToolTip("Go off when less of the area is the colour (a bar running "
                              "low), or when more of it is")
        no_wheel(self.below)
        self.below.currentIndexChanged.connect(self._on_below)
        self.lbl_number = QLabel()
        self.match_box = match = labelled("", self.threshold)
        match.layout().insertWidget(0, self.lbl_number)
        match.layout().insertWidget(1, self.below)
        row.addWidget(match)
        self._in: dict = {match: row, hold: row}   # box -> the Flow it's in now
        row.addWidget(self.chk_quiet)
        self.cb_category = WideCombo(min_width=120)
        self.cb_category.setToolTip("The category this trigger is in: a whole category can "
                                    "be switched on or off at once")
        no_wheel(self.cb_category)
        self.cb_category.activated.connect(self._on_category)
        row.addWidget(labelled("Category", self.cb_category))
        tune_col.addWidget(self.tune)
        for w in (self.delay, self.cooldown, self.hold, self.threshold):
            no_wheel(w)
            w.valueChanged.connect(self._on_numbers)

        self._flash = QTimer(self)
        self._flash.setSingleShot(True)
        self._flash.timeout.connect(self._update_state)
        self._show_mode()
        self.set_sounds(sounds)
        self.set_screens(list(screens))
        self.refresh_pictures()
        self._update_state()
        self.btn_open.setChecked(open_)
        self.set_open(open_)

    def _fit_name(self, _text: str = ""):
        """The name box as wide as its text (or the hint while it's empty), plus room
        to type, never wider than the card lets it be."""
        self.name.ensurePolished()      # its style sheet's 11 pt bold, not the default
        fm = QFontMetrics(self.name.font())
        text = self.name.text() or self.name.placeholderText()
        self.name.setMaximumWidth(fm.horizontalAdvance(text) + 32)

    # ------------------------------------------------------------------ open / closed
    @property
    def is_open(self) -> bool:
        return not self.body.isHidden()

    def set_open(self, on: bool):
        """Show the whole card, or just its header."""
        self.body.setVisible(on)
        if self.btn_open.isChecked() != on:
            self.btn_open.blockSignals(True)
            self.btn_open.setChecked(on)
            self.btn_open.blockSignals(False)
        icons.set_icon(self.btn_open, "fold_open" if on else "fold", "muted", "muted", size=16)
        self.btn_open.setToolTip("Close this trigger" if on else "Open this trigger to change it")

    NARROW = 380        # px: below this the header's thumbnail goes, for the rest to fit

    def changeEvent(self, ev):
        super().changeEvent(ev)
        if ev.type() in (QEvent.StyleChange, QEvent.FontChange):   # a theme was applied
            self._fit_name()

    def showEvent(self, ev):
        super().showEvent(ev)
        self._fit_name()          # polished by now: the host's fonts are in

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        narrow = self.width() < self.NARROW
        if narrow != self._narrow:
            self._narrow = narrow
            self._show_thumb()
        # Duplicate / Delete share Fine-tune's line: shorter a bit before the card is
        # narrow, or that line would stop it getting any narrower
        short = self.width() < self.NARROW + 80
        self.btn_dup.setText("Copy" if short else "Duplicate")
        self.btn_del.setText("" if short else "Delete")

    def _show_thumb(self):
        """The header's pictures (or the badge of a trigger without), unless the card
        is too narrow for them."""
        pics = self.t.uses_pictures
        self.strip.setVisible(pics and not self._narrow)
        self.badge.setVisible(not pics and not self._narrow)

    def mousePressEvent(self, ev):
        """A click on the header (not on one of its controls) opens or closes the card."""
        if ev.button() == Qt.LeftButton and (not self.is_open
                                             or ev.position().y() < self.body.y()):
            self.set_open(not self.is_open)
            ev.accept()
            return
        super().mousePressEvent(ev)

    def _on_tune(self, on: bool):
        self.tune.setVisible(on)

    def _tune_summary(self) -> str:
        """The fine-tuning in a line: "Match 80 % · any size · plays at once · …"."""
        t = self.t
        name = {"appear": "Match", "vanish": "Match", "change": "Changes over",
                "still": "Moves under", "colour": "Colour below" if t.below
                else "Colour above"}[t.mode]
        parts = []
        if t.uses_pictures:     # (otherwise the level is shown under Watch for)
            parts += [f"{name} {round(t.number * 100)} %",
                      "any size" if t.any_size else "one size"]
        if t.hold and t.mode != "still":
            parts.append(f"must last {t.hold:g} s")
        parts.append(f"waits {t.delay:g} s" if t.delay else "plays at once")
        parts.append(f"not again for {t.cooldown:g} s")
        if t.unfocused:
            parts.append("quiet while you're in it")
        if t.category:
            parts.append(f"in {t.category}")
        return " · ".join(parts)

    # ------------------------------------------------------------------ view
    def _place(self, box: QWidget, main: bool):
        """Put a setting under Watch for (`main`: it's what the trigger is about, a
        bar's level) or in Fine-tune."""
        want = self._watch_row if main else self._tune_row
        if self._in[box] is not want:
            self._in[box].removeWidget(box)
            want.addWidget(box)
            self._in[box] = want
            box.show()

    def _show_mode(self):
        """Show the controls the trigger's mode uses, labelled for it."""
        t = self.t
        pics = t.uses_pictures
        self._place(self.match_box, not pics)          # a bar's level, how much changes
        self._place(self.hold_box, t.mode == "still")  # how long nothing may move
        self._show_thumb()
        self.pictures_box.setVisible(pics)
        if not pics:
            self.badge.setPixmap(icons.pixmap(
                {"change": "live", "still": "pause", "colour": "palette"}.get(t.mode, "triggers"),
                28, theme.T.get("muted", "#888888")))
        self.below.setVisible(t.mode == "colour")
        self.threshold.blockSignals(True)
        if pics:
            self.threshold.setRange(30, 99)
            self.threshold.setValue(round(t.threshold * 100))
        else:
            self.threshold.setRange(1, 99)
            self.threshold.setValue(round(t.level * 100))
        self.threshold.blockSignals(False)
        self.lbl_number.setText({"appear": "Match", "vanish": "Match",
                                 "change": "Changes over", "still": "Moves under",
                                 "colour": "Colour"}[t.mode])
        self.threshold.setToolTip({
            "appear": "How alike the picture must be to count. Lower it if the picture is "
                      "missed, raise it if it plays by mistake — the live number helps.",
            "vanish": "How alike the picture must be to count as there; it's gone once it "
                      "drops below this.",
            "change": "How much of the area must change at once to count. Raise it if small "
                      "animations set it off.",
            "still": "Anything moving less than this much of the area counts as nothing "
                     "happening.",
            "colour": "How much of the area is the colour, as a share: a bar that's full "
                      "reads about 100 %, half empty about 50 %.",
        }[t.mode])
        self.live.setToolTip("Right now: how well it matches (the best of its pictures)"
                             if pics else "Right now, in the place closest to going off")
        self.lbl_hold.setText("Still for" if t.mode == "still" else "Must last")
        self.hold.setToolTip(
            "How long nothing may change before it plays" if t.mode == "still" else
            "It only counts once it has gone on this long, so a flicker or a loading "
            "screen doesn't set it off (0 = at once)")
        self._label_area()

    def _label_area(self):
        t = self.t
        colour = t.mode == "colour"
        if colour:
            self.btn_area.setText("Bar and colour…" if t.region is None or not t.colour
                                  else "Bar: set")
            self.btn_area.setIcon(swatch(t.colour) if t.colour else QIcon())
            self.btn_area.setToolTip("Drag a box around the bar to measure and check its colour")
        else:
            self.btn_area.setText("Area: all" if t.region is None else "Area: part")
            self.btn_area.setIcon(QIcon())
            self.btn_area.setToolTip("Look in only part of each window: drag a box around it. "
                                     "Fewer false alarms, quicker checks.")

    def set_sounds(self, sounds: list[tuple[str, str]]):
        """The sounds on offer: fill the "+ Add sound" list and redraw the chips."""
        self._sounds = list(sounds)
        cb = self.sound
        cb.blockSignals(True)
        cb.clear()
        cb.addItem("+ Add sound…", ADD)
        for sid, name in sounds:
            cb.addItem(name, sid)
        cb.insertSeparator(cb.count())
        cb.addItem(icons.icon("folder"), "Choose a sound file…", FILE)
        cb.setCurrentIndex(0)
        cb.blockSignals(False)
        names = dict(sounds)
        self.missing = [sid for sid in self.t.sounds if sid not in names]
        old, self.chips = self.chips, []
        for sid in self.t.sounds:
            self.chips.append(self._chip(names.get(sid, "Removed sound"), sid,
                                         warn=sid not in names))
        self.pick.setVisible(len(self.t.sounds) > 1)
        self._layout_sounds()
        for chip in old:
            # off the card now: a chip waiting for the event loop to delete it is still
            # a child of the card, and one never laid out paints its frame at Qt's
            # default size over the card
            chip.setParent(None)
            chip.deleteLater()
        self._update_state()

    def _layout_sounds(self):
        """Put the sounds row's widgets back in order (the Flow layout has no insert)."""
        while self.sounds_row.count():
            self.sounds_row.takeAt(0)
        for w in (self.lbl_play, *self.chips, self.sound, self.pick, self.chk_ring,
                  self.until, self.btn_test):
            self.sounds_row.addWidget(w)
        self.sounds_row.invalidate()
        self.sounds_box._fit()

    def _chip(self, text: str, sid: str, warn: bool = False) -> QFrame:
        """A sound the trigger plays: its name (click to hear it) and a ✕."""
        chip = QFrame()
        chip.setObjectName("chip")
        h = QHBoxLayout(chip)
        h.setContentsMargins(4, 0, 2, 0)
        h.setSpacing(2)
        name = QPushButton(text if len(text) <= CHIP_CHARS else text[:CHIP_CHARS - 1] + "…")
        name.setObjectName("chipname")
        if warn:
            name.setToolTip("This sound file is gone — pick another")
            name.setStyleSheet(f"color:{theme.status('warn')};")
        else:
            name.setToolTip(f"{text} — click to hear it")
            name.clicked.connect(lambda _=False, s=sid: self.hear.emit(s))
        h.addWidget(name)
        x = QPushButton("✕")
        x.setObjectName("chipstop")
        x.setFixedSize(22, 22)
        x.setToolTip("Take this sound off the trigger")
        x.clicked.connect(lambda _=False, s=sid: self._remove_sound(s))
        h.addWidget(x)
        return chip

    def set_screens(self, mons: list[Monitor]):
        """Fill the "Look in" list with the screens there are now."""
        t = self.t
        self._mons = list(mons)
        self._screens = len(mons)
        fill_sources(self.where, mons, t.sources, "Same as below", "Pick windows…")
        self.fallback = any(not 0 <= m < len(mons) for m in t.screens)
        self._update_state()

    def refresh_pictures(self):
        """Redraw the strip after the trigger's pictures changed."""
        t = self.t
        self.strip.set_paths(t.images)
        self.count.setText(plural(len(t.images), "picture") if t.images else "No picture")
        room = len(t.images) < MAX_PICTURES
        for b in (self.btn_pictures, self.btn_paste, self.btn_cut):
            b.setEnabled(room)
        self._update_state()

    def show_score(self, score: float | None):
        if score is None:
            self.live.setText("—")
            self.live.setStyleSheet("")
            return
        pct = max(0, round(score * 100))
        hit = screenwatch.verdict(self.t.mode, score, self.t.number, self.t.below) is True
        self.live.setText(f"{pct}%")
        self.live.setStyleSheet(f"color:{theme.status('ok')}; font-weight:600;" if hit else "")

    def set_note(self, note: tuple[str, str] | None):
        """What watching says about this trigger's window or screen (not open,
        minimized, black), or None."""
        if note != self.note:
            self.note = note
            if not self._flash.isActive():
                self._update_state()

    def flash(self, text: str, ms: int = 2500, tone: str = "ok"):
        self.state.setText(text)
        theme.set_tone(self.state, tone)
        self._flash.start(ms)

    def _what(self) -> str:
        """When it plays, in words: "as soon as it shows up"…"""
        t = self.t
        n = round(t.number * 100)
        return {
            "appear": f"{t.delay:g} s after it shows up" if t.delay else "as soon as it shows up",
            "vanish": "when its picture goes away",
            "change": "when something changes in its area",
            "still": f"when nothing has moved for {t.hold:g} s",
            "colour": f"when the colour is {'below' if t.below else 'above'} {n}% of the bar",
        }[t.mode]

    def _update_state(self):
        t = self.t
        n = len(t.sounds)
        if t.uses_pictures and not t.images:
            text, tone = "No picture yet — Cut from window…, Add pictures… or Paste", "warn"
        elif t.mode == "colour" and (not t.colour or t.region is None):
            text, tone = "Pick the bar to measure — Bar and colour…", "warn"
        elif not n:
            text, tone = "Pick the sound to play", "warn"
        elif len(self.missing) == n:
            text, tone = ("Its sound file is gone — pick another" if n == 1 else
                          "Its sound files are gone — pick others"), "warn"
        elif self.fallback:
            where = "the screen picked below" if self._screens > 1 else "the main screen"
            text, tone = (f"Screen {t.monitor + 1} isn't plugged in, so it's looked for "
                          f"on {where}"), "warn"
        elif self.note is not None:
            text, tone = self.note
        else:
            how = UNTILS[t.stop][1] if t.ring else "Plays"
            what = self._what()
            if n > 1:
                sounds = {"random": f"one of its {n} sounds at random",
                          "order": f"its {n} sounds in turn",
                          "all": f"all {n} sounds at once"}[t.pick]
                text = f"{how}: {sounds}, {what}"
            else:
                text = f"{how} {what}"
            if len(t.sources) > 1 or any(isinstance(s, WindowRef) and s.every
                                         for s in t.sources):
                text += f", in {places_label(t.sources).lower()}" if len(t.sources) > 1 \
                    else f", in {t.sources[0].label}"
            tone = ""
        self.state.setText(text)
        theme.set_tone(self.state, tone)
        self.tune_text.setText(self._tune_summary())

    # ------------------------------------------------------------------ edits
    def _on_name(self):
        name = self.name.text().strip() or "Trigger"
        if name != self.t.name:
            self.t.name = name
            self.changed.emit(self)

    def set_categories(self, names: list[str]):
        """The categories it can be put in (onionwatch.profiles), its own picked."""
        cb = self.cb_category
        cb.blockSignals(True)
        cb.clear()
        for n in names if self.t.category in names else [*names, self.t.category]:
            cb.addItem(profiles.label(n), n)
        cb.insertSeparator(cb.count())
        cb.addItem("New category…", NEW_CATEGORY)
        cb.setCurrentIndex(max(0, cb.findData(self.t.category)))
        cb.blockSignals(False)

    def _on_category(self, _i: int):
        want = self.cb_category.currentData()
        self.cb_category.setCurrentIndex(max(0, self.cb_category.findData(self.t.category)))
        if want is not None and want != self.t.category:
            self.category_wanted.emit(self, want)

    def _on_enabled(self, on: bool):
        self.t.enabled = on
        self.changed.emit(self)

    def _on_ring(self, on: bool):
        self.t.ring = on
        self.until.setVisible(on)
        self._update_state()
        self.changed.emit(self)

    def _on_until(self, _i: int):
        self.t.stop = self.until.currentData()
        self._update_state()
        self.changed.emit(self)

    def _on_quiet(self, on: bool):
        self.t.unfocused = on
        self._update_state()
        self.changed.emit(self)

    def _on_size(self, on: bool):
        self.t.any_size = on
        self._update_state()
        self.changed.emit(self)

    def _on_mode(self, i: int):
        key = self.mode.itemData(i)
        t = self.t
        if key not in screenwatch.MODES or key == t.mode:
            return
        t.mode = key
        if key in LEVELS:
            t.level = LEVELS[key]
        if key == "still" and t.hold < 1:
            t.hold = 10.0
        elif t.hold == 10.0:
            t.hold = 0.0            # the "still" default, not a wait the user picked
        self.hold.blockSignals(True)
        self.hold.setValue(t.hold)
        self.hold.blockSignals(False)
        self._show_mode()
        self._update_state()
        self.changed.emit(self)
        if key == "colour" and (not t.colour or t.region is None):
            self.area_wanted.emit(self)     # nothing to measure yet: pick the bar

    def _on_below(self, i: int):
        below = bool(self.below.itemData(i))
        if below != self.t.below:
            self.t.below = below
            self._update_state()
            self.changed.emit(self)

    def _on_sound(self, i: int):
        """An entry of the "+ Add sound" list was picked: add it to the trigger."""
        sid = self.sound.itemData(i)
        self.sound.blockSignals(True)
        self.sound.setCurrentIndex(0)
        self.sound.blockSignals(False)
        if sid == FILE:
            self.sound_file_wanted.emit(self)
            return
        if not sid or sid == ADD or sid in self.t.sounds:
            return
        if len(self.t.sounds) >= MAX_SOUNDS:
            self.flash(f"A trigger can play up to {MAX_SOUNDS} sounds", 4000, "warn")
            return
        self.t.sounds.append(sid)
        self.set_sounds(self._sounds)
        self.changed.emit(self)

    def _remove_sound(self, sid: str):
        if sid not in self.t.sounds:
            return
        self.t.sounds.remove(sid)
        self.set_sounds(self._sounds)
        self.changed.emit(self)

    def _on_pick(self, i: int):
        key = self.pick.itemData(i)
        if key in screenwatch.PICKS and key != self.t.pick:
            self.t.pick = key
            self._update_state()
            self.changed.emit(self)

    def _on_where(self, i: int):
        data = self.where.itemData(i)
        t = self.t
        if data == PICK_WINDOW:
            self.set_screens(self._mons)       # back to the current choice until one is picked
            self.window_wanted.emit(self)
            return
        if data == PLACES:
            return
        places = [data] if isinstance(data, int) and not isinstance(data, bool) else []
        if places == t.sources:
            return
        t.sources = places
        self.note = None
        self.set_screens(self._mons)
        self.changed.emit(self)

    def set_places(self, places: list):
        """Look in these windows and screens from now on."""
        self.t.sources = list(places)
        self.note = None
        self.set_screens(self._mons)
        self.changed.emit(self)

    def _on_numbers(self, _v=None):
        t = self.t
        t.delay = round(self.delay.value(), 1)
        t.cooldown = float(self.cooldown.value())
        t.hold = round(self.hold.value(), 1)
        if t.uses_pictures:
            t.threshold = self.threshold.value() / 100
        else:
            t.level = self.threshold.value() / 100
        self._update_state()
        self.changed.emit(self)


class TriggersTab(QWidget):
    """The list of triggers, the on / off switch and the watcher behind them.
    `host` (onionwatch.host.Host) keeps the settings and has the sounds."""
    active_changed = Signal(bool)       # watching or not
    fired = Signal(object)              # a Trigger just went off (its sound started)
    ringing_changed = Signal()          # a sound started or stopped ringing
    history_changed = Signal()          # something went off (TriggersTab.history)
    _fired = Signal(str, object)        # from the watcher thread: trigger id, Hit
    _quieted = Signal(str)              # ...a ringing trigger's stop happened (Quieter)

    def __init__(self, host):
        super().__init__()
        self.host = host
        s = host.screen
        self.triggers: list[Trigger] = []
        for d in s.get("triggers", []) if isinstance(s.get("triggers"), list) else []:
            t = Trigger.from_raw(d)
            if t is not None and len(self.triggers) < MAX_TRIGGERS:
                t.pending = ""      # an older Onion Board's sound import, long over
                self.triggers.append(t)
        self.rows: dict[str, TriggerRow] = {}   # the cards made so far (open categories')
        # the categories and profiles (onionwatch.profiles), and the categories on now
        self.groups = profiles.Groups.load(s, [t.category for t in self.triggers])
        self.groups.ensure(profiles.UNCATEGORISED)
        self.apps = profiles.AppWatch()
        self._active = self.groups.active()
        self.sections: dict[str, CategorySection] = {}
        self._lister = windows.list_windows     # the open windows, and the one in front
        self._front = windows.foreground        # (tests stand in for them)
        self._last_category = ""    # where a new trigger goes: the category last opened
        self._heavy_since: float | None = None  # checks spaced out past HEAVY_GAP since
        self._gap_shown = ""        # the check gap as the counts line last said it
        self._mons: list[Monitor] = []      # the screens as last listed
        self._fell_back: frozenset[str] = frozenset()   # watcher.fell_back as last seen
        self._gray: dict[str, tuple[float, Picture]] = {}   # picture path -> (mtime, picture)
        self._cuts: dict[str, tuple[int, int] | None] = {}  # ...-> the size it was cut from
        self._tints: dict[str, np.ndarray | None] = {}      # ...-> its colours in brief
        self._gen = 0                   # bumped to drop sounds still waiting to play
        self._bag = ShuffleBag()        # "Random": each trigger's sounds, each once per round
        self._order: dict[str, int] = {}   # "In order": each trigger's next sound
        self.watcher = screenwatch.Watcher(self._fired.emit, hits=True,
                                           on_quiet=self._quieted.emit)
        self._fired.connect(self._on_fired)
        self._quieted.connect(self._stop_by_itself)
        # "input" rings: trigger id -> when it started ringing (time.monotonic)
        self._input_waits: dict[str, float] = {}
        self._played: dict[str, set[str]] = {}       # trigger id -> sounds it played (tagged)
        self._ring_sounds: dict[str, list[str]] = {}  # ...-> what its ring is playing
        self._ring_how: dict[str, str] = {}           # ...-> what stops that ring (Trigger.stop)
        self._input_poll = QTimer(self)
        self._input_poll.timeout.connect(self._check_input)
        self._hits: dict[str, screenwatch.Hit] = {}     # each trigger's latest, for alerts
        # what went off lately, newest last (kept in memory only, never saved)
        self.history: deque[Alert] = deque(maxlen=HISTORY)
        interval = s.get("interval_ms", screenwatch.DEFAULT_INTERVAL_MS)
        if interval not in INTERVALS_MS:
            interval = screenwatch.DEFAULT_INTERVAL_MS
        self.watcher.interval = interval / 1000
        self.watcher.default = self._saved_default()

        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(8)
        head, hv = card("Play a sound when something shows up in your game",
                        "Pick the game window, cut out the thing to watch for — a rare "
                        "spawn's name, a “queue ready” banner, a message — and choose the "
                        "sound. Onion Watch keeps looking at that window while you're "
                        "alt-tabbed into another game or away from the keyboard, and plays "
                        "the sound (or rings until you're back) the moment it appears. It "
                        "only looks: it never clicks, types or touches the game.")
        hv.itemAt(0).widget().setWordWrap(True)
        self.hint = hv.itemAt(1).widget()
        self.warn = hint_label("")
        theme.set_tone(self.warn, "warn")
        self.warn.setVisible(False)
        # no banner: the explanation is behind an ⓘ (the host's own, by Onion Board's
        # tabs, or one in the button row here); only the warning shows, when there is one
        self.info = (hv.itemAt(0).widget().text(), self.hint.text())
        tab_info = getattr(host, "tab_info", None)
        if callable(tab_info):
            tab_info(*self.info)
        v.addWidget(self.warn)
        head.hide()
        v.addWidget(head)
        # "Deleted X · Undo" floats over the top of the tab: not in the layout, so
        # showing it never pushes the list down
        self.undo_bar = UndoBar(parent=self)

        # the profile in charge and how much is on: there once there are categories
        # or profiles (a plain list of triggers looks as it always did)
        self.groupbar = QWidget()
        gb = QHBoxLayout(self.groupbar)
        gb.setContentsMargins(4, 0, 4, 0)
        gb.setSpacing(12)
        self.cb_profile = WideCombo(min_width=150)
        self.cb_profile.setMaximumWidth(240)
        self.cb_profile.setToolTip("Which categories are on: your own switches (Manual), a "
                                   "profile's, or Automatic: the profile of the program "
                                   "that's open")
        no_wheel(self.cb_profile)
        self.cb_profile.activated.connect(self._on_profile)
        gb.addWidget(labelled("Profile", self.cb_profile))
        self.lbl_counts = hint_label("")     # wraps rather than widen a narrow window
        self.lbl_counts.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        gb.addWidget(self.lbl_counts, 1)
        v.addWidget(self.groupbar)
        self._app_timer = QTimer(self)
        self._app_timer.setInterval(APP_POLL_MS)
        self._app_timer.timeout.connect(self._check_apps)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.list = QWidget()
        self.list_layout = QVBoxLayout(self.list)
        self.list_layout.setContentsMargins(0, 0, 0, 0)
        self.list_layout.setSpacing(14)
        self.empty = QWidget()
        ev = QVBoxLayout(self.empty)
        ev.setContentsMargins(0, 24, 0, 0)
        ev.setSpacing(10)
        self.hoot = owl.OwlWidget(96)   # waiting (sadly) for something to watch
        ev.addWidget(self.hoot, 0, Qt.AlignHCenter)
        hint = hint_label("No triggers yet. Pick your game window below, then click "
                          "Cut picture… and drag a box around the thing to watch for.")
        hint.setAlignment(Qt.AlignCenter)
        ev.addWidget(hint)
        self.list_layout.addWidget(self.empty)
        self.list_layout.addStretch(1)
        self.scroll.setWidget(self.list)
        v.addWidget(self.scroll, 1)

        f = QFrame()
        f.setObjectName("transport")
        h = BarFlow(f, gap=8)
        h.setContentsMargins(12, 10, 12, 10)
        self.btn_watch = QPushButton()
        self.btn_watch.setObjectName("live")
        self.btn_watch.setCheckable(True)
        self.btn_watch.setToolTip("Watch for the pictures above")
        icons.set_icon(self.btn_watch, "triggers", checked_color="#ffffff")
        self.btn_watch.toggled.connect(self.set_watching)
        h.addWidget(self.btn_watch)
        self.btn_cut = QPushButton("Cut picture…")
        self.btn_cut.setObjectName("primary")
        self.btn_cut.setToolTip("A new trigger: cut a picture out of the window (or screen) "
                                "picked on the right")
        icons.set_icon(self.btn_cut, "crop", "on_accent")
        self.btn_cut.clicked.connect(self.add_from_cut)
        self.hoot.clicked.connect(lambda: self.btn_cut.setFocus(Qt.OtherFocusReason))
        h.addWidget(self.btn_cut)
        # the other ways to make a trigger, in one menu next to it: a picture file,
        # the copied picture, or none at all (a part of the window to watch)
        self.btn_add = QPushButton("Add")
        self.btn_add.setToolTip("A new trigger from a picture file, from the picture you "
                                "copied, or one without a picture")
        icons.set_icon(self.btn_add, "plus")
        add_menu = QMenu(self.btn_add)
        self.act_add_file = add_menu.addAction(icons.icon("plus"), "From a picture file…",
                                               self.add_from_file)
        self.act_paste = add_menu.addAction(icons.icon("image"), "Paste the copied picture",
                                            self.add_from_clipboard)
        self.act_paste.setToolTip("Win+Shift+S cuts a piece of the screen to paste here")
        add_menu.addAction("Without a picture…", self.add_area_trigger)
        add_menu.setToolTipsVisible(True)

        def add_about_to_show():
            self.act_paste.setEnabled(not QApplication.clipboard().image().isNull())
        add_menu.aboutToShow.connect(add_about_to_show)
        self.btn_add.setMenu(add_menu)
        h.addWidget(self.btn_add)
        self.btn_more = QPushButton("More")
        self.btn_more.setToolTip("What went off lately, saving or loading triggers, and "
                                 "recently deleted ones")
        icons.set_icon(self.btn_more, "history")
        menu = QMenu(self.btn_more)
        menu.addAction("What went off…", self.show_history)
        menu.addSeparator()
        menu.addAction("New category…", self.new_category)
        menu.addAction("Profiles…", self.edit_profiles)
        menu.addSeparator()
        self.act_export = menu.addAction("Save triggers to a file…", self.export_triggers)
        menu.addAction("Load triggers from a file…", self.import_triggers)
        menu.addSeparator()
        self.act_bin = menu.addAction(icons.icon("trash"), "Recently deleted…",
                                      self.show_deleted)

        def about_to_show():
            self.act_export.setEnabled(bool(self.triggers))
            n = len(self._bin())
            self.act_bin.setText(f"Recently deleted ({n})…" if n else "Recently deleted…")
        menu.aboutToShow.connect(about_to_show)
        self.btn_more.setMenu(menu)
        h.addWidget(self.btn_more)
        self.cb_where = WideCombo(min_width=140)
        self.cb_where.setMaximumWidth(190)   # a long window title doesn't stretch the bar
        self.cb_where.setToolTip("Where triggers that say “Same as below” look: your game's "
                                 "window, or a whole screen")
        self.cb_where.activated.connect(self._on_where)
        no_wheel(self.cb_where)
        look = labelled("Look in", self.cb_where)
        # six characters ("100 ms") when there's room, just enough for them when the
        # window is small
        self.cb_interval = narrow(WideCombo(min_width=110), 6)
        for ms in INTERVALS_MS:
            label = f"{ms} ms" + (" (every frame)" if ms == 16 else "")
            self.cb_interval.addItem(label, ms)
        self.cb_interval.setCurrentIndex(self.cb_interval.findData(interval))
        self.cb_interval.setToolTip("How often to look. Faster reacts sooner; 100 ms is a tenth "
                                    "of a second. Watching never takes more than about 1 % of "
                                    "your processor, so your games keep their frame rate: on a "
                                    "slow computer, or with many pictures, it looks less often "
                                    "than this.")
        self.cb_interval.currentIndexChanged.connect(self._on_interval)
        no_wheel(self.cb_interval)
        # "Look in [game] every [100 ms]": one group, beside the buttons when there's
        # room (the list gives way first), on a line of its own when not, and on two
        # in a narrow window, "every" always with its list
        every = labelled("every", self.cb_interval)
        self.lbl_interval = every.layout().itemAt(0).widget()
        self.look = Pair(look, every)
        h.addWidget(self.look)
        # last: the bin (only while it holds something) and the ⓘ
        if not callable(getattr(host, "tab_info", None)):
            self.btn_info = QPushButton("ⓘ")
            self.btn_info.setObjectName("small")
            self.btn_info.setCursor(Qt.PointingHandCursor)
            self.btn_info.setToolTip("What is this?")
            self.btn_info.clicked.connect(
                lambda: QMessageBox.information(self, *self.info))
            h.addWidget(self.btn_info)
        self.btn_bin = QPushButton()     # the bin's icon and count (_label_bin)
        icons.set_icon(self.btn_bin, "trash")
        self.btn_bin.clicked.connect(self.show_deleted)
        h.addWidget(self.btn_bin)
        v.addWidget(f)

        ok, why = screenwatch.supported()
        if not ok:
            self.warn.setText(why)
            self.warn.setVisible(True)
            self.btn_watch.setEnabled(False)
        self._fill_sources()
        self._layout_sections()
        self._fill_profiles()
        self._update_app_timer()
        self._prune_bin()
        self._label_bin()
        self.poll = QTimer(self)
        self.poll.timeout.connect(self._poll)
        self._label_watch()
        if ok and s.get("on") and self.triggers:
            self.btn_watch.setChecked(True)    # it was on when the app last closed

    # ------------------------------------------------------------------ the default
    def _saved_default(self) -> int | WindowRef:
        s = self.host.screen
        ref = WindowRef.from_raw(s.get("window"))
        if ref is not None:
            return ref
        mon = s.get("monitor", 0)
        return mon if isinstance(mon, int) and not isinstance(mon, bool) else 0

    def set_default(self, src: int | WindowRef):
        """Where triggers without their own window / screen look."""
        self.watcher.set_default(src)
        if isinstance(src, WindowRef):
            self.host.screen["window"] = src.to_raw()
        else:
            self.host.screen["window"] = None
            self.host.screen["monitor"] = src
        self.host.save()
        self._fill_sources()

    def _on_where(self, i: int):
        data = self.cb_where.itemData(i)
        if data == PICK_WINDOW:
            self._fill_sources()            # back to the current choice until one is picked
            ref = self.pick_window(self.watcher.default
                                   if isinstance(self.watcher.default, WindowRef) else None)
            if ref is not None:
                self.set_default(ref)
        elif isinstance(data, int) and not isinstance(data, bool):
            self.set_default(data)

    def pick_window(self, current: WindowRef | None = None) -> WindowRef | None:
        from onionwatch.ui.windowpicker import WindowPicker
        dlg = WindowPicker(self, current)
        return dlg.chosen if dlg.exec() else None

    def pick_places(self, current: list) -> list | None:
        """The windows and screens a trigger looks in, picked in a list (None:
        cancelled)."""
        from onionwatch.ui.windowpicker import WindowPicker
        dlg = WindowPicker(self, current, multi=True)
        return dlg.places if dlg.exec() else None

    def _pick_for(self, row: TriggerRow):
        places = self.pick_places(row.t.sources)
        if places:
            row.set_places(places)

    # ------------------------------------------------------------------ watching
    @property
    def pictures(self) -> Path:
        """The folder the trigger pictures are kept in."""
        return pictures_dir(self.host)

    def showEvent(self, ev):
        super().showEvent(ev)
        self.sounds_changed()     # the host's sounds may have been renamed meanwhile
        self._fill_sources()      # ...and screens plugged in or out

    def is_active(self) -> bool:
        return self.btn_watch.isChecked()

    def set_watching(self, on: bool, remember: bool = True):
        """Start / stop watching. `remember`: keep it as the setting for next launch
        (not when watching stopped by itself: it's tried again then)."""
        if self.btn_watch.isChecked() != on:
            self.btn_watch.blockSignals(True)
            self.btn_watch.setChecked(on)
            self.btn_watch.blockSignals(False)
        if on:
            self._fill_sources()
            self._sync()
            self.watcher.start()
            self.poll.start(POLL_MS)
        else:
            self.watcher.stop()
            self.poll.stop()
            self.cancel_pending()
            if remember and self.host.ringing():
                self.stop_ringing()     # you switched it off: you're here
            for row in self.rows.values():
                row.show_score(None)
                row.set_note(None)
        if remember:
            self.host.screen["on"] = on
            self.host.save()
        self._label_watch()
        self._show_warning()
        self.active_changed.emit(on)

    def _label_watch(self):
        text = "Watching" if self.is_active() else "Start watching"
        self.btn_watch.setProperty("full_text", text)   # a host that shows it icon only
        if not self.btn_watch.property("compact"):       # reads it back when there's room
            self.btn_watch.setText(text)

    def fit_parts(self) -> dict[str, QWidget]:
        """What a host may hide, or show as an icon only, when its window gets small:
        "hint" (the explanation at the top), the buttons "watch", "cut" and "add"
        (icon only), "interval_label" ("every"). Pasting is in the Add menu now: a
        host asking for "paste" gets nothing, and leaves it be."""
        return {"hint": self.hint, "watch": self.btn_watch, "cut": self.btn_cut,
                "add": self.btn_add, "interval_label": self.lbl_interval}

    def cancel_pending(self):
        """Drop sounds that are still waiting out their delay (switched off, Stop all)."""
        self._gen += 1

    def stop_ringing(self):
        for tag in self.host.ringing():
            self.host.stop_tag(tag)
        self._forget_ring()
        self.ringing_changed.emit()

    def _watch_ring(self, t: Trigger):
        """`t` just started ringing: watch for what stops it by itself (Trigger.stop)."""
        self._forget_ring(t.id)
        self._ring_how[t.id] = t.stop
        hit = self._hits.get(t.id)
        if t.stop == "input":
            self._input_waits[t.id] = time.monotonic()
            self._input_poll.start(INPUT_POLL_MS)
        elif hit is not None:
            self.watcher.quiet_on(t.id, hit.source, t.stop)

    def _forget_ring(self, tid: str | None = None):
        """Stop watching for what stops trigger `tid`'s ringing (None: every one's)."""
        self.watcher.quiet_off(tid)
        if tid is None:
            self._input_waits.clear()
        else:
            self._input_waits.pop(tid, None)
        if not self._input_waits:
            self._input_poll.stop()

    def _check_input(self):
        """The "input" rings: stop each once the mouse or keyboard has been touched
        since it began (after the first STOP_LEAST seconds, so it's heard)."""
        idle = windows.idle_seconds()
        if idle is None:
            return
        now = time.monotonic()
        for tid, since in list(self._input_waits.items()):
            if idle < now - since - screenwatch.STOP_LEAST:
                self._stop_by_itself(tid)

    def _stop_by_itself(self, tid: str):
        """What stops trigger `tid`'s ringing happened: stop it."""
        self._forget_ring(tid)
        if tid not in self.host.ringing():
            return
        self.host.stop_tag(tid)
        t = next((t for t in self.triggers if t.id == tid), None)
        log.info("trigger %r stopped ringing by itself", t.name if t else tid)
        row = self.rows.get(tid)
        if row is not None:
            row.flash("Stopped ringing — you're back", 4000)
        self.ringing_changed.emit()

    def retheme(self):
        """The theme changed (onionwatch.theme.T has the new colours): redraw what
        was coloured by hand."""
        icons.retheme()
        self.undo_bar.restyle()
        self.sounds_changed()         # the chips of sounds that are gone
        for row in self.rows.values():
            row._show_mode()           # the badge of a trigger without pictures
            row.show_score(self.watcher.scores.get(row.t.id) if self.is_active() else None)

    def shutdown(self):
        self._input_poll.stop()
        self.poll.stop()
        self.watcher.stop()
        self.cancel_pending()

    def _sync(self):
        """Hand the watcher the triggers that can fire, pictures loaded and grey."""
        items = []
        for t in self.triggers:
            if not (self.is_on(t) and self.ready(t) and self._playable(t)):
                continue
            got = [(p, path) for path in (t.images if t.uses_pictures else [])
                   if (p := self._picture(path)) is not None]
            if got or not t.uses_pictures:
                items.append(Watched(t.id, [p for p, _path in got], t.number, t.cooldown,
                                     sources=list(t.sources), mode=t.mode, below=t.below,
                                     colour=t.rgb, region=t.region, hold=t.hold,
                                     unfocused=t.unfocused, any_size=t.any_size,
                                     cuts=[self._cuts.get(path) for _p, path in got],
                                     tints=[self._tints.get(path) for _p, path in got]))
        self.watcher.set_items(items)

    @staticmethod
    def ready(t: Trigger) -> bool:
        """It has what it needs to be watched for (sounds aside): pictures, or for a
        colour trigger the bar and its colour."""
        if t.uses_pictures:
            return bool(t.images)
        if t.mode == "colour":
            return bool(t.colour) and t.region is not None
        return True

    def _picture(self, path: str) -> Picture | None:
        try:
            mtime = Path(path).stat().st_mtime
        except OSError:
            return None
        got = self._gray.get(path)
        if got is not None and got[0] == mtime:
            return got[1]
        img = QImage(path)
        pic = picture_of(img)
        if pic is not None:
            self._gray[path] = (mtime, pic)
            self._cuts[path] = cut_size(img)
            self._tints[path] = picture_tint(img)
        return pic

    def _playable(self, t: Trigger) -> list[str]:
        """The trigger's sounds that are still in the library, in its order."""
        have = {sid for sid, _name in self.host.sounds()}
        return [sid for sid in t.sounds if sid in have]

    def _on_fired(self, tid: str, hit: screenwatch.Hit | None = None):
        t = next((t for t in self.triggers if t.id == tid), None)
        if t is None or not self.is_active() or not self._playable(t):
            return
        if hit is not None:
            self._hits[tid] = hit
            self.history.append(Alert.of(t, hit, self.place_name(hit.source)))
            self.history_changed.emit()
        gen = self._gen
        if t.delay > 0:
            row = self.rows.get(tid)
            if row is not None:
                row.flash(f"Seen{self._in(tid)}! Playing in {t.delay:g} s…",
                          int(t.delay * 1000) + 1500)
            QTimer.singleShot(int(t.delay * 1000), self, lambda: self._fire(tid, gen))
        else:
            self._fire(tid, gen)

    def _fire(self, tid: str, gen: int):
        t = next((t for t in self.triggers if t.id == tid), None)
        if gen != self._gen or t is None or not self.is_on(t):
            return
        if self._play_trigger(t):
            log.info("trigger %r matched", t.name)
            row = self.rows.get(tid)
            if row is not None:
                row.flash(("Ringing" if t.ring else "Played") + self._in(tid) + "!", 4000)
            if t.ring:
                self._watch_ring(t)
            self.fired.emit(t)

    def place_name(self, place) -> str:
        """A window or screen as the alerts name it: "Game (copy 2)", "screen 2"."""
        return source_label(place, self._mons)

    def _in(self, tid: str) -> str:
        """" in Game (copy 2)" for a trigger looking in more than one place (else
        ""): which one it went off in."""
        hit = self._hits.get(tid)
        places = self.watcher.where.get(tid, ())
        if hit is None or len(places) < 2:
            return ""
        return f" in {self.place_name(hit.source)}"

    def alert_text(self, t: Trigger) -> str:
        """The words of a notification for `t` going off: what happened and where."""
        where = self._in(t.id).strip()
        what = {"appear": "It just showed up", "vanish": "It went away",
                "change": "Something changed", "still": "Nothing has moved for a while",
                "colour": "The bar ran low" if t.below else "The bar filled up"}[t.mode]
        what += f" {where}." if where else "."
        return what + (" " + UNTILS[t.stop][2] if t.ring else "")

    def _play_trigger(self, t: Trigger, test: bool = False) -> list[str]:
        """Play the trigger's sound(s) the way its Play setting says: one at random
        (a shuffle bag: each once before any repeats, never twice running), the next
        in turn, or all of them; ringing (over and over) when it's set to, except for a
        test. Sounds no longer in the library are skipped; when none of the chosen
        ones will play (a file gone or undecodable), the host's default sound
        does. Returns what played."""
        pool = self._playable(t)
        if not pool:
            return []
        if t.pick == "all":
            chosen = pool
        elif t.pick == "order":
            n, i = len(t.sounds), self._order.get(t.id, 0)
            chosen = []
            for _ in range(n):
                sid, i = t.sounds[i % n], i + 1
                if sid in pool:
                    chosen = [sid]
                    break
            self._order[t.id] = i % n
        else:
            chosen = [self._bag.next(t.id, pool)]
        ring = t.ring and not test
        if ring:
            self.host.stop_tag(t.id)        # one ring per trigger, not a pile of them

        def play(sid: str) -> bool:
            if ring:
                return self.host.play(sid, loop=True, tag=t.id)
            tag = self._shot_tag(t.id, sid)
            self.host.stop_tag(tag)         # pressed again: from the start, not twice
            if not self.host.play(sid, tag=tag):
                return False
            self._played.setdefault(t.id, set()).add(sid)
            return True
        played = [sid for sid in chosen if play(sid)]
        fallback = self.host.default_sound
        if not played and fallback and fallback not in chosen:
            # its sound file is gone or won't decode: an alarm that makes no sound is
            # worse than the wrong one, so the default alert plays instead
            log.warning("trigger %r: its sound couldn't be played, playing the default "
                        "alert instead", t.name)
            if play(fallback):
                played = [fallback]
        if ring and played:
            self._ring_sounds[t.id] = played
            self.ringing_changed.emit()
        return played

    def _poll(self):
        w = self.watcher
        if not w.running and self.is_active():
            # the thread died (_show_warning says why): stop, but leave the setting on
            self.set_watching(False, remember=False)
            return
        if w.fell_back != self._fell_back:
            # a trigger's own screen went away (or came back) while watching
            self._fell_back = w.fell_back
            self._fill_sources()
        for tid, row in self.rows.items():
            row.set_note(self._notes(w.where.get(tid, ())))
        heavy = w.gap > HEAVY_GAP and w.gap > w.interval * 1.05
        if not heavy:
            self._heavy_since = None
        elif self._heavy_since is None:
            self._heavy_since = time.monotonic()
        if not self.isVisible():
            return
        if self._gap_text() != self._gap_shown:
            self._refresh_counts()
        for tid, row in self.rows.items():
            row.show_score(w.scores.get(tid))
        self._show_warning()

    def _notes(self, places) -> tuple[str, str] | None:
        """What to say on a card about the places it's looked in: the first problem."""
        return next((n for n in map(self._note, places) if n is not None), None)

    def _note(self, src) -> tuple[str, str] | None:
        """What to say on a card about the window / screen it's looked for in."""
        w = self.watcher
        if src is None:
            return None
        name = source_label(src, self._mons)
        if src in w.failed:
            if isinstance(src, WindowRef):
                return f"Waiting for {name} to open", "warn"
            return f"Screen {src + 1} can't be captured — waiting for it", "warn"
        if src in w.minimized:
            return (f"{name} is minimized, so it can't be seen — restore it (covering it "
                    "with other windows is fine)"), "warn"
        if src in w.unseen:
            if isinstance(src, WindowRef):
                return (f"{name} can't be captured: nothing comes out of it. Pick its "
                        "screen under Look in instead."), "warn"
            return f"Screen {src + 1} gives no picture — waiting for one", "warn"
        if src in w.blacked:
            if isinstance(src, WindowRef):
                return (f"{name} comes out black. Some games can only be seen on the "
                        "screen: pick its screen under Look in instead."), "warn"
            return ("The screen looks all black. If the game is in exclusive fullscreen, "
                    "set it to Borderless or Windowed."), "warn"
        return None

    def _show_warning(self):
        w, why = self.watcher, ""
        ok, unsupported = screenwatch.supported()
        if not ok:
            why = unsupported
        elif w.error:
            why = f"Watching stopped: {w.error}"
        elif self.is_active() and w.lost:
            why = ("Waiting for the screen to come back. A game switching to or from "
                   "fullscreen does this for a moment.")
        elif self.is_active() and not w.scores and not w.failed and not any(
                self.is_on(t) and self.ready(t) and t.sounds for t in self.triggers):
            if any(t.enabled and self.ready(t) and t.sounds for t in self.triggers):
                why = ("Nothing to watch for: the triggers that could go off are all in "
                       "categories that are off now.")
            else:
                why = ("Nothing to watch for yet: each trigger needs a sound, and a "
                       "picture (or its bar) to look for.")
        elif (self.is_active() and self._heavy_since is not None
              and time.monotonic() - self._heavy_since >= HEAVY_FOR):
            why = (f"Each trigger is checked only every {w.gap:.1f} s: "
                   f"{plural(self._counts()[2], 'picture')} are on, more than this "
                   "computer looks for in 1 % of its processor. Switch off a category, or "
                   "give triggers an Area to look in, to check more often.")
        self.warn.setText(why)
        self.warn.setVisible(bool(why))

    def _on_interval(self, _i: int):
        ms = self.cb_interval.currentData()
        self.watcher.interval = ms / 1000
        self.host.screen["interval_ms"] = ms
        self.host.save()

    def _fill_sources(self):
        """List the screens again: the "Look in" at the bottom (the default) and each
        card's own. A change while watching is passed on to the watcher."""
        mons = screenwatch.monitors()
        d = self.watcher.default
        fill_sources(self.cb_where, mons, [d])
        for row in self.rows.values():
            row.set_screens(mons)
        if mons != self._mons and self.watcher.running:
            self.watcher.rescan()
        self._mons = mons

    # ------------------------------------------------------------------ categories
    # Triggers sit in categories (Trigger.category, onionwatch.profiles), each a
    # section of the list. A section's cards are only made once it's opened, so a
    # library of hundreds opens at once, and a trigger is watched for only while
    # it's on and so is its category (is_on): one that's off costs nothing.
    def is_on(self, t: Trigger) -> bool:
        """It's switched on, and so is its category (by hand or by a profile)."""
        return t.enabled and t.category in self._active

    def _grouped(self) -> bool:
        """There's more than the one category, or a profile: show the sections'
        headers and the Profile line."""
        return len(self.groups.categories) > 1 or bool(self.groups.profiles)

    def _shown_categories(self) -> list[str]:
        """The categories with a section: all of them, but Uncategorised only while
        a trigger is in it or it's the only one."""
        have = {t.category for t in self.triggers}
        names = self.groups.names()
        return [n for n in names if n or n in have or len(names) == 1]

    def _new_category(self) -> str:
        """The category a new trigger goes in: the one last opened, if it's still there."""
        return self._last_category if self.groups.find(self._last_category) else ""

    def _section_of(self, t: Trigger) -> CategorySection:
        self.groups.ensure(t.category)
        if t.category not in self.sections:
            self._layout_sections()
        return self.sections[t.category]

    def _make_section(self, name: str) -> CategorySection:
        sec = CategorySection(name)
        sec.fold_toggled.connect(self._on_fold)
        sec.switched.connect(self._on_switch)
        sec.menu_wanted.connect(self._category_menu)
        self.sections[name] = sec
        return sec

    def _drop_section(self, name: str):
        sec = self.sections.pop(name, None)
        if sec is None:
            return
        for tid in [tid for tid, r in self.rows.items() if r.parentWidget() is sec.body]:
            self._drop_row(tid)
        self.list_layout.removeWidget(sec)
        sec.setParent(None)
        sec.deleteLater()

    def _layout_sections(self):
        """Make, order and label the sections, and make the open ones' cards."""
        names = self._shown_categories()
        for n in list(self.sections):
            if n not in names:
                self._drop_section(n)
        lone = len(names) == 1
        for i, n in enumerate(names):
            sec = self.sections.get(n) or self._make_section(n)
            if self.list_layout.indexOf(sec) != i + 1:
                self.list_layout.removeWidget(sec)
                self.list_layout.insertWidget(i + 1, sec)     # after the "no triggers" note
            sec.set_header_visible(not lone)
            c = self.groups.find(n)
            if lone:
                c.open = True       # and still open once a second category comes along
            sec.set_open(c.open)
            if c.open:
                self._build(sec)
        self.empty.setVisible(not self.triggers)
        self.groupbar.setVisible(self._grouped())
        self._refresh_switches()
        self._refresh_counts()

    def _set_open(self, sec: CategorySection, on: bool):
        c = self.groups.ensure(sec.name)
        c.open = on
        sec.set_open(on)
        if on:
            self._last_category = sec.name
            self._build(sec)

    def _on_fold(self, name: str, on: bool):
        sec = self.sections.get(name)
        if sec is None:
            return
        self._set_open(sec, on)
        self.groups.save(self.host.screen)
        self.host.save()

    def _build(self, sec: CategorySection, need: Trigger | None = None):
        """Make the cards of `sec`'s triggers: BUILD_NOW now (and `need`), the rest
        BUILD_STEP at a time after."""
        todo = [t for t in self.triggers if t.category == sec.name and t.id not in self.rows]
        if sec.built and not todo:
            return
        sec.built = True
        one = len(self.triggers) == 1
        for t in todo[:BUILD_NOW]:
            self._place_row(t, sec, open_=one)
        if need is not None and need.id not in self.rows:
            self._place_row(need, sec, open_=True)
        if len(todo) > BUILD_NOW:
            QTimer.singleShot(0, self, lambda: self._build_more(sec))
        self._refresh_counts()

    def _build_more(self, sec: CategorySection):
        if self.sections.get(sec.name) is not sec or not sec.is_open:
            sec.built = False           # gone or folded meanwhile: the rest when reopened
            return
        todo = [t for t in self.triggers if t.category == sec.name and t.id not in self.rows]
        for t in todo[:BUILD_STEP]:
            self._place_row(t, sec)
        if len(todo) > BUILD_STEP:
            QTimer.singleShot(0, self, lambda: self._build_more(sec))

    def _counts(self) -> tuple[int, int, int]:
        """(triggers, on, pictures on) over the whole list."""
        on = [t for t in self.triggers if self.is_on(t)]
        return (len(self.triggers), len(on),
                sum(len(t.images) for t in on if t.uses_pictures))

    def _gap_text(self) -> str:
        if not self.is_active() or not self.watcher.running:
            return ""
        return f"each checked every {self.watcher.gap:.1f} s"

    def _refresh_counts(self):
        """The numbers on the sections' headers and the Profile line."""
        per: dict[str, list[int]] = {}
        for t in self.triggers:
            n = per.setdefault(t.category, [0, 0, 0])
            n[0] += 1
            if t.enabled:
                n[1] += 1
                if t.uses_pictures:
                    n[2] += len(t.images)
        for name, sec in self.sections.items():
            n, on, pics = per.get(name, (0, 0, 0))
            cat_on = name in self._active
            sec.set_counts(counts_text(n, on, pics, cat_on), "" if cat_on else "warn")
            sec.empty.setVisible(not n and not sec.header.isHidden())
        total, on, pics = self._counts()
        parts = [f"{on} of {plural(total, 'trigger')} on", plural(pics, "picture")]
        self._gap_shown = self._gap_text()
        if self._gap_shown:
            parts.append(self._gap_shown)
        state = self._profile_state()
        self.lbl_counts.setText(" · ".join(parts) + (f"  —  {state}" if state else ""))
        self.lbl_counts.setToolTip(
            "Triggers on, and the pictures they look for. Each picture on takes a share of "
            "the 1 % of the processor watching keeps to: with too many, each is checked "
            "less often. Turn off what you don't need now, or give triggers an Area.")

    def _refresh_switches(self):
        """Each section's switch: is it on now, and who says so."""
        ps = self.groups.in_charge(self.apps.matched)
        if not ps:
            tip = ("Switch the whole category on or off. Its triggers keep their own "
                   "switches, so turning it back on brings back just the ones that were on.")
        elif len(ps) == 1:
            tip = (f"On or off as the profile “{ps[0].name}” says: switching it changes "
                   "that profile.")
        else:
            tip = (f"On or off as the profiles {', '.join(p.name for p in ps)} say (Automatic). "
                   "Change them under More → Profiles….")
        for name, sec in self.sections.items():
            sec.set_switch(name in self._active, tip)

    def _apply_active(self, force: bool = False) -> bool:
        """Work out which categories are on again; hand the watcher what changed."""
        active = self.groups.active(self.apps.matched)
        changed = active != self._active
        self._active = active
        if changed or force:
            if self.is_active():
                self._sync()
            self._refresh_switches()
            self._refresh_counts()
            self._show_warning()
        return changed

    def _on_switch(self, name: str, on: bool):
        """A category's switch was clicked."""
        if not self.groups.set_on(name, on, self.apps.matched):
            names = ", ".join(p.name for p in self.groups.in_charge(self.apps.matched))
            QMessageBox.information(self, "Set by profiles",
                                    f"The profiles {names} say which categories are on now "
                                    "(Profile is Automatic). Change them under More → "
                                    "Profiles….")
            self._refresh_switches()
            return
        self._save_groups()
        self._apply_active(force=True)
        if name not in self._active:        # you switched it off: its rings stop too
            for t in self.triggers:
                if t.category == name:
                    self._silence(t.id, ring=True)

    def _save_groups(self):
        self.groups.save(self.host.screen)
        self.host.save()

    def new_category(self, name: str | None = None) -> str | None:
        """Make a category (asked for when `name` isn't given): its name, or None."""
        if name is None:
            from PySide6.QtWidgets import QInputDialog
            name, ok = QInputDialog.getText(self, "New category", "Name of the category:")
            if not ok:
                return None
        name = profiles.clean_name(name)
        if not name:
            return None
        if self.groups.find(name) is None:
            if len(self.groups.categories) >= profiles.MAX_CATEGORIES:
                QMessageBox.information(self, "Too many categories",
                                        f"You can have up to {profiles.MAX_CATEGORIES}.")
                return None
            self.groups.ensure(name).open = True
        self._last_category = name
        self._categories_changed()
        return name

    def _categories_changed(self):
        """Categories were added, renamed, removed or moved: the sections, the cards'
        Category lists and the profiles follow."""
        self._layout_sections()
        names = self.groups.names()
        for row in self.rows.values():
            row.set_categories(names)
        self._apply_active(force=True)
        self._save_groups()

    def _move_to(self, row: TriggerRow, name: str):
        """A card's Category was changed."""
        if name == NEW_CATEGORY:
            name = self.new_category()
            if name is None:
                return
        self.move_trigger(row.t, name)

    def move_trigger(self, t: Trigger, name: str):
        """Put `t` in category `name` (made if need be). Its card moves there, if
        that category is open."""
        self._drop_row(t.id)
        t.category = profiles.clean_name(name)
        self.groups.ensure(t.category)
        self._last_category = t.category
        self._layout_sections()
        sec = self.sections.get(t.category)
        if sec is not None and sec.is_open and sec.built:
            row = self._place_row(t, sec)
            row.flash(f"Moved to {profiles.label(t.category)}")
        self._store()

    def rename_category(self, old: str, new: str) -> bool:
        new = profiles.clean_name(new)
        if old == profiles.UNCATEGORISED or not new or new == old:
            return False
        was_open = self.groups.find(old).open if self.groups.find(old) else False
        if not self.groups.rename(old, new):
            return False
        for t in self.triggers:
            if t.category == old:
                t.category = new
        self._drop_section(old)
        self._drop_section(new)
        self.groups.find(new).open = self.groups.find(new).open or was_open
        if self._last_category == old:
            self._last_category = new
        self._categories_changed()
        self._store()
        return True

    def set_category_triggers(self, name: str, on: bool):
        """Switch every trigger in a category on (or off), each one's own switch."""
        for t in self.triggers:
            if t.category != name or t.enabled == on:
                continue
            t.enabled = on
            row = self.rows.get(t.id)
            if row is not None:
                row.chk_on.blockSignals(True)
                row.chk_on.setChecked(on)
                row.chk_on.blockSignals(False)
                row._update_state()
            if not on:
                self._silence(t.id, ring=True)
        self._store()

    def move_category(self, name: str, step: int):
        self.groups.move(name, step)
        self._categories_changed()

    def delete_category(self, name: str, ask: bool = True) -> bool:
        """Take a category away: its triggers go to Uncategorised (nothing is
        deleted), with an Undo bar."""
        if name == profiles.UNCATEGORISED or self.groups.find(name) is None:
            return False
        moved = [t for t in self.triggers if t.category == name]
        if ask:
            box = QMessageBox(QMessageBox.Question, "Delete category",
                              f"Delete the category “{name}”?\n\n"
                              + (f"Its {plural(len(moved), 'trigger')} move to "
                                 f"{profiles.UNCATEGORISED_LABEL}: none is deleted."
                                 if moved else "It's empty."),
                              QMessageBox.Yes | QMessageBox.Cancel, self)
            box.button(QMessageBox.Yes).setText("Delete")
            box.setDefaultButton(QMessageBox.Cancel)
            if box.exec() != QMessageBox.Yes:
                return False
        before: dict = {}
        self.groups.save(before)
        self.groups.remove(name)
        for t in moved:
            t.category = profiles.UNCATEGORISED
            self._drop_row(t.id)
        self._drop_section(name)
        if self.groups.mode and self.groups.mode != profiles.AUTO \
                and self.groups.profile(self.groups.mode) is None:
            self.groups.mode = ""
        self._categories_changed()
        self._store()
        ids = {t.id for t in moved}

        def undo():
            self.groups = profiles.Groups.load(before, [t.category for t in self.triggers])
            self.groups.ensure(profiles.UNCATEGORISED)
            for t in self.triggers:
                if t.id in ids:
                    self._drop_row(t.id)
                    t.category = name
            self._drop_section(profiles.UNCATEGORISED)
            self._categories_changed()
            self._fill_profiles()
            self._store()
        self.undo_bar.show_for(f"Deleted the category “{name}”", undo,
                               tip="Put it back, its triggers and all")
        return True

    def export_category(self, name: str):
        ts = [t for t in self.triggers if t.category == name]
        if ts:
            self.export_triggers(ts, profiles.label(name))

    def _category_menu(self, name: str):
        """A section's ⋯ menu."""
        sec = self.sections.get(name)
        if sec is None:
            return
        menu = QMenu(sec.btn_menu)
        named = name != profiles.UNCATEGORISED
        n = sum(t.category == name for t in self.triggers)
        if named:
            menu.addAction("Rename…", lambda: self._ask_rename(name))
        a = menu.addAction("Turn all its triggers on",
                           lambda: self.set_category_triggers(name, True))
        a.setEnabled(n > 0)
        a = menu.addAction("Turn all its triggers off",
                           lambda: self.set_category_triggers(name, False))
        a.setEnabled(n > 0)
        menu.addSeparator()
        i = self.groups.names().index(name) if self.groups.find(name) else 0
        menu.addAction("Move up", lambda: self.move_category(name, -1)).setEnabled(i > 0)
        menu.addAction("Move down", lambda: self.move_category(name, 1)).setEnabled(
            i < len(self.groups.categories) - 1)
        menu.addSeparator()
        menu.addAction("Save to a file…", lambda: self.export_category(name)).setEnabled(n > 0)
        if named:
            menu.addAction(icons.icon("trash"), "Delete category…",
                           lambda: self.delete_category(name))
        menu.exec(sec.btn_menu.mapToGlobal(sec.btn_menu.rect().bottomLeft()))

    def _ask_rename(self, name: str):
        from PySide6.QtWidgets import QInputDialog
        new, ok = QInputDialog.getText(self, "Rename category", "New name:", text=name)
        if ok:
            self.rename_category(name, new)

    # ------------------------------------------------------------------ profiles
    def _fill_profiles(self):
        cb, g = self.cb_profile, self.groups
        cb.blockSignals(True)
        cb.clear()
        cb.addItem("Manual (your switches)", "")
        for p in g.profiles:
            cb.addItem(p.name, p.id)
        if g.profiles:
            cb.addItem("Automatic (by program)", profiles.AUTO)
        cb.insertSeparator(cb.count())
        cb.addItem("Edit profiles…", EDIT_PROFILES)
        cb.setCurrentIndex(max(0, cb.findData(g.mode)))
        cb.blockSignals(False)
        self.groupbar.setVisible(self._grouped())

    def _profile_state(self) -> str:
        """Who decides what's on, in a few words, when it isn't Manual."""
        if self.groups.mode != profiles.AUTO:
            return ""
        ps = self.groups.in_charge(self.apps.matched)
        if not ps:
            return "no profile's program is open: your switches apply"
        return "on now: " + ", ".join(p.name for p in ps)

    def set_profile(self, mode: str):
        """Manual (""), a profile's id, or profiles.AUTO."""
        g = self.groups
        if mode != profiles.AUTO and mode and g.profile(mode) is None:
            mode = ""
        g.mode = mode
        self._save_groups()
        self._fill_profiles()
        self._update_app_timer()
        self._apply_active(force=True)

    def _on_profile(self, _i: int):
        want = self.cb_profile.currentData()
        if want == EDIT_PROFILES:
            self.cb_profile.setCurrentIndex(max(0, self.cb_profile.findData(self.groups.mode)))
            self.edit_profiles()
            return
        self.set_profile(want or "")

    def edit_profiles(self):
        start = self.groups.mode if self.groups.profile(self.groups.mode) else ""
        dlg = ProfilesDialog(self, self.groups.profiles, self.groups.names(), self._lister,
                             start)
        if dlg.exec():
            self.set_profiles(dlg.result_profiles)

    def set_profiles(self, ps: list):
        self.groups.profiles = ps[:profiles.MAX_PROFILES]
        mode = self.groups.mode
        if mode == profiles.AUTO and not ps:
            mode = ""
        self.apps.matched = [m for m in self.apps.matched if self.groups.profile(m)]
        self.set_profile(mode)
        self._layout_sections()

    def _update_app_timer(self):
        """Automatic looks at the open programs every APP_POLL_MS (only then)."""
        g = self.groups
        if g.mode == profiles.AUTO and any(p.apps for p in g.profiles):
            if not self._app_timer.isActive():
                self._app_timer.start()
            self._check_apps()
        else:
            self._app_timer.stop()
            self.apps.matched = []

    def _check_apps(self):
        """Which profiles' programs are open (or in front) now; a change switches
        their categories on or off. A ring going on isn't stopped by it."""
        try:
            wins = self._lister()
            fg = self._front()
        except OSError:
            log.debug("couldn't list the windows for the profiles", exc_info=True)
            return
        running = {w.exe for w in wins if w.exe}
        front = next((w.exe for w in wins if w.hwnd == fg), "")
        if self.apps.update(self.groups.profiles, running, front, time.monotonic()):
            log.info("profiles on now: %s", ", ".join(
                p.name for p in self.groups.in_charge(self.apps.matched)) or "none")
            self._apply_active(force=True)

    # ------------------------------------------------------------------ the list
    def sounds_changed(self):
        sounds = self.host.sounds()
        for row in self.rows.values():
            row.set_sounds(sounds)
        # a sound taken off the board (or the app) stops wherever a trigger played it
        have = {sid for sid, _name in sounds}
        for tid in list(self._played):
            self._silence(tid, [s for s in self._played[tid] if s not in have])
        for tid, ringing in list(self._ring_sounds.items()):
            if tid in self.host.ringing() and not set(ringing) & have:
                self._silence(tid, [], ring=True)

    def _add_row(self, t: Trigger, at: int | None = None, open_: bool = True) -> TriggerRow:
        """The card of `t` (already in self.triggers), made if it isn't yet, in its
        category, which is opened to show it. `at` is past: a card goes where its
        trigger is in self.triggers."""
        sec = self._section_of(t)
        if not sec.is_open:
            self._set_open(sec, True)
        self._build(sec, need=t)
        return self.rows.get(t.id) or self._place_row(t, sec, open_)

    def _make_row(self, t: Trigger, open_: bool) -> TriggerRow:
        """A card for `t`, opened unless `open_` is false (the cards made for the
        list at start, when there's more than one)."""
        row = TriggerRow(t, self.host.sounds(), self._mons, open_=open_)
        row.set_categories(self.groups.names())
        row.category_wanted.connect(self._move_to)
        row.changed.connect(self._row_changed)
        row.pictures_wanted.connect(self._add_picture_files)
        row.paste_wanted.connect(self._paste_picture)
        row.cut_wanted.connect(self._cut_picture)
        row.picture_view.connect(self._view_picture)
        row.picture_swap.connect(self._change_picture)
        row.picture_removed.connect(self._remove_picture)
        row.sound_file_wanted.connect(self._choose_sound_file)
        row.window_wanted.connect(self._pick_for)
        row.area_wanted.connect(self._pick_area)
        row.duplicate.connect(self._duplicate)
        row.hear.connect(lambda sid, r=row: self._hear(r.t, sid))
        row.test.connect(lambda r: self._play_trigger(r.t, test=True))
        row.remove.connect(self.ask_remove)
        self.rows[t.id] = row
        return row

    def _place_row(self, t: Trigger, sec: CategorySection, open_: bool = False) -> TriggerRow:
        """Put `t`'s card (made if need be) in `sec` where it is in self.triggers."""
        row = self.rows.get(t.id) or self._make_row(t, open_)
        old = row.parentWidget()
        if old is not None and old.layout() is not None:
            old.layout().removeWidget(row)
        before = 0
        for x in self.triggers:
            if x is t:
                break
            r = self.rows.get(x.id)
            if x.category == t.category and r is not None and r.parentWidget() is sec.body:
                before += 1
        sec.body_layout.insertWidget(before + 1, row)      # after its "empty" note
        sec.empty.setVisible(False)
        self.empty.setVisible(False)
        return row

    def _drop_row(self, tid: str):
        """Throw a trigger's card away (the trigger stays)."""
        row = self.rows.pop(tid, None)
        if row is None:
            return
        parent = row.parentWidget()
        if parent is not None and parent.layout() is not None:
            parent.layout().removeWidget(row)
        row.setParent(None)   # gone from the list now, not when the event loop gets to it
        row.deleteLater()

    def _row_changed(self, row: TriggerRow):
        """A card was edited: save, and silence what it no longer plays. A sound
        taken off it stops (its preview, its test, its ring); a trigger switched off
        stops all of them; Ring unticked stops the ring; a new "until" applies to
        the ring going now."""
        t = row.t
        self._silence(t.id, [sid for sid in self._played.get(t.id, ()) if sid not in t.sounds])
        if t.id in self.host.ringing():
            gone = not set(self._ring_sounds.get(t.id, ())) & set(t.sounds) \
                and self.host.default_sound not in self._ring_sounds.get(t.id, ())
            if not (t.enabled and t.ring) or gone:
                self._silence(t.id, [], ring=True)
            elif self._ring_how.get(t.id) != t.stop:
                self._watch_ring(t)
        if not t.enabled:
            self._silence(t.id, ring=True)
        self._store()

    # Every sound a trigger plays is tagged, so it can be stopped again: a ring with
    # the trigger's id (what the alarm bar asks the host about), anything else with
    # the trigger and the sound, and a preview of a sound on its card with "hear:"
    # in front (a host plays that to you alone, not into a call).
    @staticmethod
    def _shot_tag(tid: str, sid: str) -> str:
        return f"{tid}/{sid}"

    @staticmethod
    def _hear_tag(tid: str, sid: str) -> str:
        return f"hear:{tid}/{sid}"

    def _hear(self, t: Trigger, sid: str):
        """A sound on `t`'s card was clicked: play it to check it (again from the
        start if it's still going)."""
        tag = self._hear_tag(t.id, sid)
        self.host.stop_tag(tag)
        if self.host.play(sid, tag=tag):
            self._played.setdefault(t.id, set()).add(sid)

    def _silence(self, tid: str, sids=None, ring: bool = False):
        """Stop what trigger `tid` played: the sounds `sids` (None: all it played,
        previews and tests too), and with `ring` its ring."""
        played = self._played.get(tid, set())
        for sid in list(played if sids is None else sids):
            self.host.stop_tag(self._shot_tag(tid, sid))
            self.host.stop_tag(self._hear_tag(tid, sid))
            played.discard(sid)
        if ring and tid in self.host.ringing():
            self.host.stop_tag(tid)
            self._forget_ring(tid)
            self.ringing_changed.emit()

    def _store(self):
        self.host.screen["triggers"] = [t.to_raw() for t in self.triggers]
        self.groups.save(self.host.screen)
        self.host.save()
        self._refresh_counts()
        if self.is_active():
            self._sync()
        self._show_warning()

    def _new(self, img: QImage | list[QImage], name: str) -> Trigger | None:
        """A new trigger from a picture (or several), playing the default alert until
        another sound is picked; None when no picture could be used."""
        if len(self.triggers) >= MAX_TRIGGERS:
            QMessageBox.information(self, "Too many triggers",
                                    f"You can have up to {MAX_TRIGGERS} triggers.")
            return None
        t = Trigger(id=uuid.uuid4().hex[:12], name=name[:60] or "Trigger",
                    sounds=[self.host.default_sound] if self.host.default_sound else [],
                    category=self._new_category())
        if not self._add_pictures(t, [img] if isinstance(img, QImage) else list(img)):
            return None
        self.triggers.append(t)
        row = self._add_row(t)
        self._store()
        QTimer.singleShot(0, row, lambda: self.scroll.ensureWidgetVisible(row))
        row.name.setFocus()
        row.name.selectAll()
        return t

    def _check_picture(self, img: QImage) -> tuple[Picture | None, tuple[str, str]]:
        """Whether a picture can be looked for: (its grey and mask, ()) or (None,
        (why not, in detail))."""
        if img.isNull():
            return None, ("Not a picture", "That picture couldn't be read.")
        if min(img.width(), img.height()) < 6:
            return None, ("Picture too small",
                          "Cut a bigger piece: at least 6 pixels each way.")
        if max(img.width(), img.height()) > MAX_SIDE:
            return None, ("Picture too big", "Cut a smaller piece: at most "
                          f"{MAX_SIDE} pixels each way.")
        pic = picture_of(img)
        if pic is None or flatness(*pic) < screenwatch.FLAT_STD:
            return None, ("Picture is one plain colour",
                          "There's nothing in it to recognise. Cut a piece with some detail, "
                          "like the words or an icon. (Transparent parts don't count.)")
        return pic, ()

    def _add_pictures(self, t: Trigger, imgs: list[QImage], names: list[str] = (),
                      at: int | None = None) -> int:
        """Add pictures to a trigger (`at`: replace that one instead). Each is checked
        before it's saved, so a refused picture never replaces or joins the others;
        what was refused, and what may not be found, is said once for the lot.
        Returns how many were added."""
        refused: list[tuple[str, str, str]] = []      # (name, title, text)
        notes: list[tuple[str, str]] = []             # (name, note)
        added = left_out = 0
        # a pasted or loaded picture doesn't say what it was cut from: most likely
        # what the trigger watches, as it is now
        here = self._source_size(t.source if t.source is not None else self.watcher.default)
        for i, img in enumerate(imgs):
            if not img.isNull() and cut_size(img) is None:
                set_cut_size(img, here)
            name = names[i] if i < len(names) else f"Picture {len(t.images) + 1}"
            if at is None and len(t.images) >= MAX_PICTURES:
                left_out = len(imgs) - i
                break
            pic, why = self._check_picture(img)
            if pic is None:
                refused.append((name, *why))
                continue
            try:
                path = save_picture(img, picture_name(t, self.pictures), self.pictures)
            except OSError as e:
                refused.append((name, "Couldn't keep the picture", str(e)))
                continue
            if at is not None and 0 <= at < len(t.images):
                old, t.images[at] = t.images[at], path
                delete_picture(old, self.pictures)
                self._gray.pop(old, None)
                self._cuts.pop(old, None)
                at = None                   # a second picture would only be added
            else:
                t.images.append(path)
            added += 1
            for note in self._picture_notes(pic, t):
                notes.append((name, note))
        row = self.rows.get(t.id)
        if row is not None:
            row.refresh_pictures()
            if left_out:
                row.flash(f"A trigger can look for up to {MAX_PICTURES} pictures — "
                          f"{plural(left_out, 'picture')} not added", 4000, "warn")
        self._say(refused, "Some pictures couldn't be used")
        self._say([(n, "This picture may not be found", note) for n, note in notes],
                  "Some pictures may not be found")
        return added

    def _say(self, items: list[tuple[str, str, str]], title: str):
        """One warning for a list of (picture name, title, text): the picture's own
        title when there's only one, `title` with the names when there are more."""
        if len(items) == 1:
            QMessageBox.warning(self, items[0][1], items[0][2])
        elif items:
            QMessageBox.warning(self, title, "\n\n".join(f"{n}: {text}" for n, _t, text in items))

    def _source_size(self, src) -> tuple[int, int] | None:
        """The size in pixels of a window / screen being watched; None if unknown."""
        if isinstance(src, WindowRef):
            info = windows.find(src)
            return (info.width, info.height) if info is not None and info.width else None
        mons = screenwatch.monitors()
        if not mons:
            return None
        mon = mons[src] if isinstance(src, int) and 0 <= src < len(mons) else mons[0]
        return mon.width, mon.height

    def _picture_notes(self, pic: Picture, t: Trigger) -> list[str]:
        """What may stop a picture being found where it's watched (it's kept anyway:
        it may be meant for a window that isn't open yet)."""
        src = t.source if t.source is not None else self.watcher.default
        size = self._source_size(src)
        if size is None:
            return []
        sw, sh = size
        what = "window" if isinstance(src, WindowRef) else "screen"
        gray, mask = pic
        h, w = gray.shape
        notes = []
        smallest = screenwatch.SIZES[0] if t.any_size else 1.0
        if w * smallest > sw or h * smallest > sh:
            notes.append(f"It's bigger than the {what} being watched ({sw}×{sh}), so it can't "
                         f"be found there. Cut it from that {what} at the size it's shown.")
            return notes
        top = screenwatch.work_scale(sw, [1])     # the most detail a check keeps
        need = math.ceil(screenwatch.MIN_SIDE / top)
        if min(w, h) < need:
            notes.append(f"It's very small for a {sw}-pixel-wide {what}, so it may be missed "
                         "or match the wrong thing. A bigger piece (at least "
                         f"{need} pixels each way) works better.")
        scale = screenwatch.work_scale(sw, [min(w, h)])
        if mask is not None and int(screenwatch.shrink_mask(mask, scale).sum()) < \
                screenwatch.MASK_MIN:
            notes.append("Most of it is see-through and what's left is thin, so there's "
                         "almost nothing to compare once it's scaled down for checking. "
                         "Keep more of the background around it, or use a picture "
                         "without transparency.")
        return notes

    # ------------------------------------------------------------------ cutting
    def capture(self, src) -> tuple[QImage | None, str]:
        """A full-size picture of a window or screen to cut from: (image, its name),
        or (None, why not)."""
        from onionwatch.ui.windowpicker import bgra_image
        if isinstance(src, WindowRef):
            info = windows.find(src)
            if info is None:
                return None, f"{src.label} isn't open. Start it, then try again."
            if info.minimized:
                return None, f"{src.label} is minimized. Restore it, then try again."
            px = windows.snapshot(info.hwnd)
            if px is None:
                return None, f"{src.label} couldn't be copied."
            return bgra_image(px), src.label
        mons = screenwatch.monitors()
        if not mons:
            return None, "No screen was found."
        mon = mons[src] if isinstance(src, int) and 0 <= src < len(mons) else mons[0]
        win = self.window()
        # take our own window out of the way first: it's probably on that screen
        was = win.windowOpacity()
        win.setWindowOpacity(0.0)
        QApplication.processEvents()
        from PySide6.QtCore import QThread
        QThread.msleep(200)
        try:
            px = windows.screen_snapshot(mon.left, mon.top, mon.width, mon.height)
        finally:
            win.setWindowOpacity(was)
        if px is None:
            return None, "The screen couldn't be copied."
        return bgra_image(px), source_label(src, mons)

    def _cut(self, src) -> QImage | None:
        img, where = self.capture(src)
        if img is None:
            QMessageBox.information(self, "Can't cut a picture", where)
            return None
        if float(np.asarray(img.constBits(), np.uint8).reshape(-1, 4)[:, :3].max()) < 8:
            QMessageBox.information(self, "It comes out black",
                                    f"{where} comes out black, so there's nothing to cut. "
                                    "Some games can only be seen on the screen: pick its "
                                    "screen under Look in instead.")
            return None
        from onionwatch.ui.snip import SnipDialog
        dlg = SnipDialog(img, where, self)
        if not dlg.exec() or dlg.piece is None:
            return None
        set_cut_size(dlg.piece, (img.width(), img.height()))
        return dlg.piece

    def add_from_cut(self):
        piece = self._cut(self.watcher.default)
        if piece is not None:
            self._new(piece, f"Trigger {len(self.triggers) + 1}")

    def _cut_picture(self, row: TriggerRow):
        src = row.t.source if row.t.source is not None else self.watcher.default
        piece = self._cut(src)
        if piece is not None and self._add_pictures(row.t, [piece]):
            self._store()

    # ------------------------------------------------------------------ files
    def add_from_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Picture to look for", str(Path.home()),
                                              f"Pictures ({PICTURE_EXTS});;All files (*)")
        if path:
            self._new(QImage(path), Path(path).stem)

    def add_from_clipboard(self):
        img = QApplication.clipboard().image()
        if img.isNull():
            QMessageBox.information(self, "No picture copied",
                                    "Copy a picture first: press Win+Shift+S, drag around "
                                    "the thing to look for, then click Paste.")
            return
        self._new(img, f"Trigger {len(self.triggers) + 1}")

    def _add_picture_files(self, row: TriggerRow):
        """The card's "+ Add pictures…": any number of files onto this trigger."""
        paths, _ = QFileDialog.getOpenFileNames(self, "Pictures to look for", str(Path.home()),
                                                f"Pictures ({PICTURE_EXTS});;All files (*)")
        if paths and self._add_pictures(row.t, [QImage(p) for p in paths],
                                        [Path(p).name for p in paths]):
            self._store()

    def _paste_picture(self, row: TriggerRow):
        """The card's "Paste picture": the copied picture onto this trigger."""
        img = QApplication.clipboard().image()
        if img.isNull():
            QMessageBox.information(self, "No picture copied",
                                    "Copy a picture first: press Win+Shift+S, drag around "
                                    "the thing to look for, then click Paste picture.")
            return
        if self._add_pictures(row.t, [img]):
            self._store()

    def _view_picture(self, row: TriggerRow, index: int = 0):
        """A thumbnail was clicked: its picture big, with the trigger's others."""
        from onionwatch.ui.viewer import PictureViewer
        t = row.t

        def made_from(img: QImage) -> str:
            size = cut_size(img)
            return f"cut from a {size[0]}×{size[1]} view" if size else ""

        def swap(i: int):
            r = self.rows.get(t.id)
            if r is not None:
                self._change_picture(r, i)

        def remove(i: int):
            r = self.rows.get(t.id)
            if r is not None:
                self._remove_picture(r, i)

        PictureViewer(f"Pictures of “{t.name}”", lambda: t.images, index, swap, remove,
                      made_from, self).exec()

    def _change_picture(self, row: TriggerRow, index: int = 0):
        """Swap one of the trigger's pictures for a file."""
        path, _ = QFileDialog.getOpenFileName(self, "Picture to look for", str(Path.home()),
                                              f"Pictures ({PICTURE_EXTS});;All files (*)")
        if path and self._add_pictures(row.t, [QImage(path)], [Path(path).name], at=index):
            self._store()

    def _remove_picture(self, row: TriggerRow, index: int):
        """Take a picture off a trigger. Its file stays until the Undo bar goes."""
        t = row.t
        if not 0 <= index < len(t.images):
            return
        path = t.images.pop(index)
        row.refresh_pictures()
        self._store()

        def undo():
            r = self.rows.get(t.id)
            if r is None or len(t.images) >= MAX_PICTURES or path in t.images:
                done()
                return
            t.images.insert(min(index, len(t.images)), path)
            r.refresh_pictures()
            self._store()

        def done():
            if not self._picture_used(path):
                delete_picture(path, self.pictures)
                self._gray.pop(path, None)
        self.undo_bar.show_for(f"Removed a picture from “{t.name}”", undo, done)

    def _choose_sound_file(self, row: TriggerRow):
        exts = " ".join(f"*{e}" for e in sorted(self.host.audio_exts))
        path, _ = QFileDialog.getOpenFileName(self, "Sound to play", str(Path.home()),
                                              f"Audio ({exts});;All files (*)")
        if not path:
            return
        tid = row.t.id
        row.flash("Adding the sound…", 60_000)
        try:
            self.host.add_sound(path, lambda sid: self._sound_added(tid, sid))
        except OSError as e:
            row.flash("", 0)
            QMessageBox.warning(self, "Can't use that sound", str(e))

    def _sound_added(self, tid: str, sid: str | None):
        """A sound file picked on a card has been added to the host (sid), or couldn't
        be (None): put it on that trigger, if it's still there."""
        t = next((t for t in self.triggers if t.id == tid), None)
        row = self.rows.get(tid)
        if row is not None:
            row.flash("", 0)
        if t is not None and sid and sid not in t.sounds and len(t.sounds) < MAX_SOUNDS:
            t.sounds.append(sid)
        self.sounds_changed()
        if t is not None and sid:
            self._store()
        elif row is not None and not sid:
            row.flash("That sound couldn't be added", 4000, "warn")

    def ask_remove(self, row: TriggerRow):
        """The card's delete button: ask first, then delete (to Recently deleted)."""
        box = QMessageBox(QMessageBox.Question, "Delete trigger",
                          f"Delete the trigger “{row.t.name}”?\n\nIt goes to Recently "
                          f"deleted, where you can bring it back for {KEEP_DAYS} days.",
                          QMessageBox.Yes | QMessageBox.Cancel, self)
        box.button(QMessageBox.Yes).setText("Delete")
        box.setDefaultButton(QMessageBox.Cancel)
        if box.exec() == QMessageBox.Yes:
            self._remove(row)

    def _remove(self, row: TriggerRow):
        """Delete a trigger: it goes to Recently deleted (pictures and all), with an
        Undo bar for the next few seconds."""
        t = row.t
        index = next((i for i, x in enumerate(self.triggers) if x.id == t.id), 0)
        entry = {"id": uuid.uuid4().hex[:12], "when": time.time(), "index": index,
                 "trigger": t.to_raw()}
        self.host.screen["deleted"] = self._bin() + [entry]
        self.triggers = [x for x in self.triggers if x.id != t.id]
        self._bag.forget(t.id)
        self._order.pop(t.id, None)
        self.host.stop_tag(t.id)
        self._silence(t.id, ring=True)
        self._forget_ring(t.id)
        for d in (self._played, self._ring_sounds, self._ring_how):
            d.pop(t.id, None)
        self._drop_row(t.id)
        for path in t.images:
            self._gray.pop(path, None)   # the file stays, in the bin
        self._layout_sections()
        self._prune_bin()
        self._store()
        self.ringing_changed.emit()
        if not self.triggers and self.is_active():
            self.set_watching(False)
        self._label_bin()
        self.undo_bar.show_for(f"Deleted “{t.name}”",
                               lambda: self.restore_deleted(entry["id"]),
                               tip=f"Put it back, exactly as it was. Later: Recently "
                                   f"deleted (kept {KEEP_DAYS} days)")

    # ------------------------------------------------------------------ recently deleted
    def _bin(self) -> list[dict]:
        """host.screen["deleted"], oldest first: {id, when, index, trigger (to_raw)}."""
        raw = self.host.screen.get("deleted")
        return [d for d in raw if isinstance(d, dict) and isinstance(d.get("trigger"), dict)
                and isinstance(d.get("id"), str)] if isinstance(raw, list) else []

    def _label_bin(self):
        """The "Recently deleted (n)" button: there while the bin has triggers in it."""
        n = len(self._bin())
        # just the bin and how many: a compact button that never makes the bar wrap
        self.btn_bin.setText(str(n))
        what = f"Recently deleted ({n})"
        self.btn_bin.setToolTip(f"{what}…\nTriggers you deleted: bring them back, pictures "
                                "and all")
        self.btn_bin.setAccessibleName(what)
        self.btn_bin.setVisible(n > 0)

    def _picture_used(self, path: str, but: dict | None = None) -> bool:
        """Whether a live trigger, or one in the bin (other than `but`), has this file."""
        if any(path in x.images for x in self.triggers):
            return True
        for d in self._bin():
            if d is not but and d["id"] != (but or {}).get("id"):
                t = Trigger.from_raw(d["trigger"])
                if t is not None and path in t.images:
                    return True
        return False

    def _prune_bin(self):
        """Let go of deleted triggers older than KEEP_DAYS or past MAX_DELETED, and
        their pictures."""
        all_ = self._bin()
        cutoff = time.time() - KEEP_DAYS * 86400
        kept = [d for d in all_ if _num(d.get("when")) >= cutoff][-MAX_DELETED:]
        if len(kept) == len(all_):
            return
        self.host.screen["deleted"] = kept
        for d in all_:
            if d not in kept:
                self._drop_pictures(d)
        self.host.save()

    def _drop_pictures(self, entry: dict):
        """Delete a binned trigger's picture files (it's gone from the bin already, or
        about to be)."""
        t = Trigger.from_raw(entry.get("trigger", {}))
        for path in t.images if t is not None else []:
            if not self._picture_used(path, but=entry):
                delete_picture(path, self.pictures)

    def deleted(self) -> list[tuple[str, str, float]]:
        """The bin for the Recently deleted window: (id, name, when), newest first."""
        return [(d["id"], str(d["trigger"].get("name") or "Trigger"), _num(d.get("when")))
                for d in reversed(self._bin())]

    def restore_deleted(self, entry_id: str) -> bool:
        """Bring a deleted trigger back where it was, as it was."""
        all_ = self._bin()
        entry = next((d for d in all_ if d["id"] == entry_id), None)
        if entry is None:
            return False
        if len(self.triggers) >= MAX_TRIGGERS:
            QMessageBox.information(self, "Too many triggers",
                                    f"You can have up to {MAX_TRIGGERS} triggers. Delete "
                                    "one to bring this one back.")
            return False
        t = Trigger.from_raw(entry["trigger"])
        if t is None:
            return False
        if any(x.id == t.id for x in self.triggers):
            t = t.copy(uuid.uuid4().hex[:12])   # its id was taken meanwhile (a loaded pack)
        t.images = [p for p in t.images if Path(p).exists()]
        t.pending = ""
        self.host.screen["deleted"] = [d for d in all_ if d is not entry]
        index = min(max(int(_num(entry.get("index"))), 0), len(self.triggers))
        self.triggers.insert(index, t)
        row = self._add_row(t, at=index)
        self._store()
        self._label_bin()
        QTimer.singleShot(0, row, lambda: self.scroll.ensureWidgetVisible(row))
        return True

    def forget_deleted(self, entry_id: str):
        """Delete one from the bin for good."""
        all_ = self._bin()
        entry = next((d for d in all_ if d["id"] == entry_id), None)
        if entry is None:
            return
        self.host.screen["deleted"] = [d for d in all_ if d is not entry]
        self._drop_pictures(entry)
        self.host.save()
        self._label_bin()

    def show_deleted(self):
        from onionwatch.ui.deleted import DeletedDialog
        self.undo_bar.finish()
        DeletedDialog(self, KEEP_DAYS, self).exec()
        self._label_bin()

    # ------------------------------------------------------------------ areas, copies
    def _pick_area(self, row: TriggerRow):
        """The card's "Area…" / "Bar and colour…": drag the part of the window to look
        in (and for a colour trigger, check its colour)."""
        from onionwatch.ui.snip import AreaDialog
        t = row.t
        src = t.source if t.source is not None else self.watcher.default
        img, where = self.capture(src)
        if img is None:
            QMessageBox.information(self, "Can't show the window", where)
            return
        dlg = AreaDialog(img, where, t.region, t.colour if t.mode == "colour" else None, self)
        if not dlg.exec():
            return
        t.region = dlg.region
        if t.mode == "colour":
            t.colour = dlg.colour
        row._label_area()
        row._update_state()
        self._store()

    def _duplicate(self, row: TriggerRow):
        """A copy of the trigger (its pictures copied too), just below it."""
        if len(self.triggers) >= MAX_TRIGGERS:
            QMessageBox.information(self, "Too many triggers",
                                    f"You can have up to {MAX_TRIGGERS} triggers.")
            return
        t = row.t.copy(uuid.uuid4().hex[:12])
        t.name = row.t.name[:53] + " (copy)"
        t.images = []
        for path in row.t.images:
            img = QImage(path)
            if img.isNull():
                continue
            try:
                t.images.append(save_picture(img, picture_name(t, self.pictures), self.pictures))
            except OSError:
                log.warning("couldn't copy the picture %s", path, exc_info=True)
        self._insert(t, after=row.t)

    def _insert(self, t: Trigger, after: Trigger | None = None) -> TriggerRow:
        """Add a finished trigger to the list (after `after`, else at the end)."""
        i = self.triggers.index(after) + 1 if after in self.triggers else len(self.triggers)
        self.triggers.insert(i, t)
        row = self._add_row(t)
        self._store()
        QTimer.singleShot(0, row, lambda: self.scroll.ensureWidgetVisible(row))
        return row

    def add_area_trigger(self):
        """A new trigger that watches an area rather than looking for a picture: it
        starts as "the area stops changing" (a game stuck or idle); the card picks
        another kind."""
        if len(self.triggers) >= MAX_TRIGGERS:
            QMessageBox.information(self, "Too many triggers",
                                    f"You can have up to {MAX_TRIGGERS} triggers.")
            return
        t = Trigger(id=uuid.uuid4().hex[:12], name=f"Trigger {len(self.triggers) + 1}",
                    sounds=[self.host.default_sound] if self.host.default_sound else [],
                    mode="still", level=LEVELS["still"], hold=10.0,
                    category=self._new_category())
        row = self._insert(t)
        row.name.setFocus()
        row.name.selectAll()

    def show_history(self):
        HistoryDialog(self, self).exec()

    # ------------------------------------------------------------------ packs
    def export_triggers(self, triggers: list[Trigger] | None = None, name: str = ""):
        """Save triggers to a pack: all of them, or `triggers` (a category, `name`)."""
        triggers = self.triggers if triggers is None else triggers
        if not triggers:
            return
        file = f"Onion Watch {name}.zip" if name else "Onion Watch triggers.zip"
        file = "".join("_" if c in '\\/:*?"<>|' else c for c in file)
        path, _ = QFileDialog.getSaveFileName(self, "Save triggers", str(Path.home() / file),
                                              "Trigger packs (*.zip)")
        if not path:
            return
        try:
            packs.write_pack(path, triggers, dict(self.host.sounds()))
        except OSError as e:
            QMessageBox.warning(self, "Couldn't save the triggers", str(e))
            return
        QMessageBox.information(
            self, "Triggers saved",
            f"{plural(len(triggers), 'trigger')} saved to {Path(path).name}, pictures "
            "and all, each in its category. Sounds go by name: sound files of yours "
            "aren't in it.")

    def import_triggers(self):
        path, _ = QFileDialog.getOpenFileName(self, "Load triggers", str(Path.home()),
                                              "Trigger packs (*.zip);;All files (*)")
        if not path:
            return
        try:
            found = packs.read_pack(path)
        except packs.PackError as e:
            QMessageBox.warning(self, "Can't load those triggers", str(e))
            return
        if found and not any(t.category for t, _p, _s in found):
            # a pack without categories (an older one): its triggers go in one named
            # after the file, so they stay together
            name = profiles.clean_name(Path(path).stem.removeprefix("Onion Watch "))
            for t, _p, _s in found:
                t.category = name
        added = self.add_pack(found)
        if found and not added:
            QMessageBox.information(self, "Too many triggers",
                                    f"You can have up to {MAX_TRIGGERS} triggers.")
        elif not found:
            QMessageBox.information(self, "No triggers", "That file has no triggers in it.")

    def add_pack(self, found) -> int:
        """Add the triggers read from a pack (packs.read_pack): each gets a new id,
        its pictures are kept like cut ones, and its sounds are the host's of the
        same id or name, else the default. Each keeps its category (made if need be).
        Returns how many were added."""
        have = self.host.sounds()
        ids, by_name = {sid for sid, _n in have}, {n.lower(): sid for sid, n in have}
        added = 0
        for t, pics, sounds in found:
            if len(self.triggers) >= MAX_TRIGGERS:
                break
            t.id = uuid.uuid4().hex[:12]
            t.enabled = True
            t.images = []
            for data in pics:
                img = QImage()
                if not img.loadFromData(data) or self._check_picture(img)[0] is None:
                    continue
                try:
                    t.images.append(save_picture(img, picture_name(t, self.pictures),
                                                 self.pictures))
                except OSError:
                    log.warning("couldn't keep a picture from a pack", exc_info=True)
            mapped = []
            for sid, name in sounds or [(sid, "") for sid in t.sounds]:
                got = sid if sid in ids else by_name.get(name.lower()) if name else None
                if got and got not in mapped:
                    mapped.append(got)
            if not mapped and self.host.default_sound:
                mapped = [self.host.default_sound]
            t.sounds = mapped
            self._insert(t)
            added += 1
        return added
