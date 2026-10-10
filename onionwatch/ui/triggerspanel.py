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

import dataclasses
import functools
import logging
import math
import os
import time
import uuid
from collections import OrderedDict, deque
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PySide6.QtCore import QEvent, QPoint, QRect, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (QColor, QFontMetrics, QIcon, QImage, QKeySequence, QPainter,
                           QPixmap, QShortcut)
from PySide6.QtWidgets import (QAbstractSpinBox, QApplication, QBoxLayout, QCheckBox,
                               QComboBox, QDoubleSpinBox,
                               QFileDialog, QFrame, QGridLayout, QHBoxLayout, QLabel,
                               QLineEdit, QMenu, QMessageBox, QPushButton, QScrollArea,
                               QSizePolicy, QSpacerItem, QSpinBox, QStyle, QStyleOptionComboBox,
                               QStyleOptionSpinBox,
                               QVBoxLayout, QWidget)

from onionwatch import cutout, owl, packs, profiles, screenwatch, theme, usage, windows
from onionwatch.screenwatch import (INTERVALS_MS, MAX_PICTURES, MAX_SOUNDS, Monitor, Picture,
                                    Trigger, Watched, WindowRef)
from onionwatch.shuffle import ShuffleBag
from onionwatch.ui import icons
from onionwatch.ui.categories import (MAX_PER_ROW, CategoriesDialog, CategorySection,
                                      ProfilesDialog,
                                      counts_text)
from onionwatch.ui.chances import LiveLabel, goes_below
from onionwatch.ui.history import THUMB as LOG_THUMB, HistoryDialog
from onionwatch.ui.panel import Flow, UndoBar, card, hint_label
from onionwatch.ui.watching import share_label
from onionwatch.ui.windowpicker import places_label
from onionwatch.wheelguard import no_wheel
from onionwatch.i18n import _, ngettext

log = logging.getLogger(__name__)


def needs_part(fallback=None):
    """For a TriggersTab method that opens a window from one of Onion Watch's own
    files, imported inside it: when that file is missing or out of step (an update that
    only half went in once crashed "Recently deleted"), say so plainly and return
    `fallback` instead. The import stays a plain one in the method, outside any `try`,
    so scripts/build_module.py still sees the file is needed and packs it."""
    def wrap(method):
        @functools.wraps(method)
        def run(self, *args, **kwargs):
            try:
                return method(self, *args, **kwargs)
            except ImportError:
                log.exception("part of Onion Watch is missing (%s)", method.__name__)
                QMessageBox.warning(
                    self, _("Part of Onion Watch is missing"),
                    _("This window can't open: one of Onion Watch's files is missing, most "
                      "likely because an update didn't finish.\n\nUpdate or reinstall Onion "
                      "Watch to fix it. Your triggers and pictures are safe."))
                return fallback
        return run
    return wrap

PICTURE_EXTS = "*.png *.jpg *.jpeg *.bmp *.webp *.gif"
ADD = "__add__"         # the sound list's "+ Add sound…" entry (its resting state)
FILE = "__file__"       # ...its "Choose a sound file…" entry
PICK_WINDOW = "__pick_window__"   # a "Look in" list's "Pick a window…" entry
DEFAULT = "__default__"           # ...its "Same as below" entry
PLACES = "__places__"             # ...the trigger's own windows and screens
NEW_CATEGORY = "__new_category__"   # a card's Category list's "New category…" entry
POLL_MS = 150           # how often the live match numbers refresh
MAX_TRIGGERS = 500      # in all; how many can be on at once is up to the computer
# Versions before categories load only the first 50 of Config.screen["triggers"] and
# save just those back. So only the first OLD_TRIGGERS are kept there and the rest
# under "more_triggers", which those versions never read or write: opening the same
# settings in one of them (an older Onion Board add-on, say) can't lose any
OLD_TRIGGERS = 50
SEARCH_MIN = 200        # px: the search box never gets narrower (it was squeezed to "Sea…")
SEARCH_ROOM = 260       # px it keeps before the view's controls go to a line of their own
LIST_VIEW = -1          # the View list's "List and editor"
SPLIT_MIN = 760         # px: from this wide, the list on the left and one trigger's editor
LIST_WIDTH = 300        # ...on the right; the list is this wide
MAX_SIDE = 8192         # bigger pictures are refused (kept pixel for pixel, never resized)
CUT_KEY = "OnionWatch cut from"   # a picture's PNG text: the size of what it was cut from
# ...and this one, set: it wasn't cut from the game (a file or a copy from the web), so
# the size it's drawn at is anyone's guess (see screenwatch.WIDE_SIZES)
WEB_KEY = "OnionWatch size unknown"
# such a picture is shrunk to fit within this share of what's watched each way when
# it's added (a picture from the web is often many times the size it's shown at)
WEB_FILL = 0.6
WEB_GUESS = (1920, 1080)          # ...what's watched, when that isn't known
THUMB = QSize(112, 64)
STRIP_THUMBS = 3        # thumbnails a card's strip shows before it scrolls
CHIP_CHARS = 24         # a sound chip's name is cut to this many characters
PICKS = (("random", _("Play one at random")), ("order", _("Play them in turn")),
         ("all", _("Play all at once")))
MODES = (("appear", _("The picture shows up")), ("vanish", _("The picture goes away")),
         ("change", _("Something changes in an area")),
         ("still", _("An area stops changing")), ("colour", _("A bar runs low")))
LEVELS = {"change": 0.05, "still": 0.01, "colour": 0.30}   # a new mode's starting level
# what stops a ringing trigger by itself (Trigger.stop): its words on the card, on
# its state line and in the alert, and a tooltip
UNTILS = {
    "moves": (_("until the game moves"), _("keeps playing until the game moves"),
              _("Ringing until the game moves."),
              _("Stops once anything moves where it looks (you're back and playing), or "
                "when it goes away. It waits for the screen to settle first, so a fade-in "
                "doesn't stop it. A bar: once it's back over its line.")),
    "focus": (_("until I switch to the game"),
              _("keeps playing until you switch to the game"),
              _("Ringing until you switch to it."),
              _("Stops when you alt-tab back to its window. Watching a whole screen: when "
                "you switch to any other window.")),
    "gone": (_("until it's gone"), _("keeps playing until it's gone"),
             _("Ringing until it's gone."),
             _("Stops when the picture goes away (or the bar is back, or the area settles).")),
    "input": (_("until I touch mouse or keys"),
              _("keeps playing until you touch the mouse or keyboard"),
              _("Ringing until you touch the mouse or keyboard."),
              _("Stops as soon as you move the mouse or press a key, anywhere.")),
    "manual": (_("until I click Stop"), _("keeps playing until you click Stop"),
               _("Ringing until you stop it."),
               _("Only the Stop button on the red bar (or the tray icon) stops it.")),
}
INPUT_POLL_MS = 100     # how often an "input" ring checks for the mouse or keyboard


GUESS_PLAYING_S = 8     # a sound counts as playing this long when the host can't say
HISTORY = 50            # alerts kept in the history (in memory only)
APP_POLL_MS = 2000      # how often Automatic profiles look at which programs are open
BUILD_NOW = 8           # an opened category's cards made at once (the first ones, on
BUILD_STEP_MS = 40      # ...screen); the rest this long at a time, so the window never
                        # ...freezes, however many there are (a card takes ~20-30 ms)
SCREEN_LEARN_MS = 1300  # a screen cut's frames for the cut-out: grabbed this long after
HEAVY_GAP = 0.5         # s: checks spaced out further than this (to keep to the share of
HEAVY_FOR = 5.0         # ...the processor picked) for this long: say too many pictures are on
EDIT_PROFILES = "__edit_profiles__"   # the Profile list's "Edit profiles…"
KEEP_DAYS = 30          # deleted triggers stay in Recently deleted this long
MAX_DELETED = 50        # ...and at most this many of them


@dataclass
class Alert:
    """Something that went off, for the history: when, which trigger, where, how
    strongly, and what the watched window looked like then (the check's own small
    copy, the box around what set it off drawn on it, kept at the size the Log shows
    it: 50 of them stay in memory)."""
    when: float
    name: str
    place: str
    score: float
    mode: str
    picture: QImage

    @classmethod
    def of(cls, t: Trigger, hit: screenwatch.Hit, place: str) -> Alert:
        img = hit_image(hit)
        if img.width() > LOG_THUMB.width() or img.height() > LOG_THUMB.height():
            # what the Log's thumbnail would make of it anyway (windowpicker.thumbnail)
            img = img.scaled(LOG_THUMB, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        return cls(time.time(), t.name, place, hit.score, t.mode, img)


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
    if w > screenwatch.LOG_PICTURE_W:       # kept small: 50 of them stay in memory
        img = img.scaledToWidth(screenwatch.LOG_PICTURE_W, Qt.SmoothTransformation)
        w, h = img.width(), img.height()
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


def picture_rgb(img: QImage) -> np.ndarray | None:
    """The picture's own colours, (h, w, 3) uint8 RGB: the watcher takes its colours
    in brief from them at the size it's matched at (screenwatch.tint_at)."""
    if img.isNull():
        return None
    img = img.convertToFormat(QImage.Format_ARGB32)
    h, w = img.height(), img.width()
    buf = np.frombuffer(img.constBits(), np.uint8, count=img.bytesPerLine() * h)
    return buf.reshape(h, img.bytesPerLine())[:, :w * 4].reshape(h, w, 4)[..., 2::-1].copy()


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


def is_web(img: QImage) -> bool:
    """The picture wasn't cut from the game (see WEB_KEY)."""
    return img.text(WEB_KEY) == "1"


def set_web(img: QImage):
    img.setText(WEB_KEY, "1")


def picture_file(path: str) -> QImage:
    """A picture file to look for. One Onion Watch didn't cut (it says nothing of the
    size it was cut from) counts as from the web: its size on screen is unknown."""
    img = QImage(path)
    if not img.isNull() and cut_size(img) is None:
        set_web(img)
    return img


def copied_picture() -> QImage:
    """The picture on the clipboard (null if none): a copied picture, or a picture
    file copied in Explorer. One copied from a browser or a file (the copy carries a
    link or a page snippet, where Win+Shift+S gives only the picture) counts as from
    the web, see picture_file."""
    mime = QApplication.clipboard().mimeData()
    img = QApplication.clipboard().image()
    if img.isNull():
        exts = {e[1:] for e in PICTURE_EXTS.split()}
        files = [u.toLocalFile() for u in (mime.urls() if mime is not None else [])
                 if u.isLocalFile() and Path(u.toLocalFile()).suffix.lower() in exts]
        return picture_file(files[0]) if files else img
    if mime is not None and (mime.hasHtml() or mime.hasUrls()) and cut_size(img) is None:
        set_web(img)
    return img


def fit_web(img: QImage, room: tuple[int, int] | None) -> QImage:
    """A picture from the web shrunk to fit within WEB_FILL of `room` (w, h) each way
    (WEB_GUESS when not known), its notes kept; as it is if it fits already."""
    rw, rh = room or WEB_GUESS
    f = min(WEB_FILL * rw / max(img.width(), 1), WEB_FILL * rh / max(img.height(), 1))
    if f >= 1:
        return img
    out = img.scaled(max(6, round(img.width() * f)), max(6, round(img.height() * f)),
                     Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
    for key in img.textKeys():
        out.setText(key, img.text(key))
    return out


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


def with_alpha(img: QImage, keep: np.ndarray) -> QImage:
    """`img` with only `keep` (a (h, w) bool mask of its size) left opaque."""
    out = img.convertToFormat(QImage.Format_ARGB32)
    for key in img.textKeys():
        out.setText(key, img.text(key))
    h, w = out.height(), out.width()
    buf = np.frombuffer(out.bits(), np.uint8, count=out.bytesPerLine() * h)
    buf.reshape(h, out.bytesPerLine())[:, :w * 4].reshape(h, w, 4)[..., 3] = \
        np.where(keep, 255, 0).astype(np.uint8)
    return out


def save_picture(img: QImage, name: str, folder: Path) -> str:
    """Keep a copy of the picture as <folder>/<name>.png; returns its path. It's kept
    pixel for pixel: resized, it would no longer match the screen it was cut from.
    Written beside it first, so a failed save leaves the old picture as it was."""
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{name}.png"
    tmp = folder / f"{name}.saving"
    if not img.save(str(tmp), "PNG"):
        tmp.unlink(missing_ok=True)
        raise OSError(_("couldn't save the picture to {path}", path=path))
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
    """A list as wide as the entry it shows when there's room ("Screen 2: 1920×1080"
    isn't cut off, "it shows up" isn't padded out to its longest entry's width) that
    still gives way when the window is small; its open list is as wide as its longest
    entry. A plain AdjustToContents list can never be narrower than its entries, and
    the tab, so the whole window, then can't shrink below it (the window must fit
    300 px)."""

    MIN_WIDTH = 90

    def __init__(self, parent: QWidget | None = None, min_width: int = MIN_WIDTH):
        super().__init__(parent)
        self.min_width = min_width
        self.setSizeAdjustPolicy(QComboBox.AdjustToContents)   # (the open list's width)
        pol = self.sizePolicy()
        pol.setHorizontalPolicy(QSizePolicy.Maximum)   # up to that, down to min_width
        self.setSizePolicy(pol)
        self.currentIndexChanged.connect(self.updateGeometry)   # its width follows it

    def sizeHint(self) -> QSize:
        s = super().sizeHint()          # the longest entry's
        opt = QStyleOptionComboBox()
        self.initStyleOption(opt)
        text = self.fontMetrics().horizontalAdvance(self.currentText())
        if not self.itemIcon(self.currentIndex()).isNull():
            text += self.iconSize().width() + 4
        w = self.style().sizeFromContents(QStyle.CT_ComboBox, opt,
                                          QSize(text, s.height()), self).width()
        return QSize(min(s.width(), w + 4), s.height())

    def minimumSizeHint(self) -> QSize:
        s = super().minimumSizeHint()
        return QSize(min(s.width(), self.min_width, self.sizeHint().width()), s.height())

    def showPopup(self):
        # open as wide as the longest entry, however narrow the list is shut
        self.view().setMinimumWidth(super().sizeHint().width())
        super().showPopup()


def _spin_hint(sb, s: QSize) -> QSize:
    """`s` (a number box's size hint) trimmed to its longest number, suffix and all:
    Qt leaves room for a few more letters than it ever shows."""
    fm = sb.fontMetrics()
    text = max(fm.horizontalAdvance(sb.prefix() + sb.textFromValue(v) + sb.suffix())
               for v in (sb.minimum(), sb.maximum()))
    opt = QStyleOptionSpinBox()
    sb.initStyleOption(opt)
    opt.rect = QRect(0, 0, s.width(), s.height())
    edit = sb.style().subControlRect(QStyle.CC_SpinBox, opt, QStyle.SC_SpinBoxEditField, sb)
    return QSize(s.width() - max(0, edit.width() - text - 8), s.height())


class FitSpin(QSpinBox):
    """A whole-number box as wide as its numbers (see _spin_hint)."""

    def sizeHint(self) -> QSize:
        return _spin_hint(self, super().sizeHint())

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()


class FitDoubleSpin(QDoubleSpinBox):
    """A number box as wide as its numbers (see _spin_hint)."""

    def sizeHint(self) -> QSize:
        return _spin_hint(self, super().sizeHint())

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()


def _row_width(widgets: list[QWidget], gap: int = 8, least: bool = True) -> int:
    """The width the shown `widgets` need side by side, `gap` px apart: the least
    they can do with, or (`least` False) what they'd like."""
    shown = [w for w in widgets if not w.isHidden()]
    return (sum(max(w.minimumWidth(),
                    (w.minimumSizeHint() if least else w.sizeHint()).width())
                for w in shown)
            + gap * max(0, len(shown) - 1))


def labelled(text: str, w: QWidget, in_card: bool = False) -> QWidget:
    """`text` and its control kept together on one line of a wrapping row
    (`in_card`: a card's, see-through by the card's style sheet)."""
    box = QWidget()
    box.setObjectName("labelled")   # see-through, whichever program's stylesheet is in use
    if not in_card:
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


def picture_filter() -> str:
    """A file dialog's filter for the pictures it can add."""
    return _("Pictures") + f" ({PICTURE_EXTS});;" + _("All files") + " (*)"


def pictures(n: int) -> str:
    return ngettext("{n} picture", "{n} pictures", n)


def triggers(n: int) -> str:
    return ngettext("{n} trigger", "{n} triggers", n)


def interval_label(ms: int) -> str:
    """A check speed in a list: "250 ms", "16 ms (every frame)"."""
    return _("{ms} ms (every frame)", ms=ms) if ms == 16 else _("{ms} ms", ms=ms)


def paint_plate(widget: QWidget):
    """The rounded plate a card's picture (or its icon) sits on, in the theme's
    background colour: painted, so it follows a theme change."""
    p = QPainter(widget)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(theme.T.get("bg", "#888888")))
    p.drawRoundedRect(QRectF(widget.rect()), 8, 8)
    p.end()


class Plate(QLabel):
    """An icon on a plate: what a card shows when its trigger has no pictures."""

    def paintEvent(self, ev):
        paint_plate(self)
        super().paintEvent(ev)


class ElideLabel(QLabel):
    """A label that can keep to one line, cut short with an … (set_elide) and the
    whole text as its tooltip, rather than wrap or be clipped mid-letter."""

    def __init__(self, text: str = ""):
        super().__init__()
        self._full = ""
        self._elide = False
        self.setText(text)

    def text(self) -> str:
        return self._full

    def setText(self, text: str):
        self._full = text
        self._fit()

    def set_elide(self, on: bool):
        self._elide = on
        self.setWordWrap(not on)
        self._fit()

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self._fit()

    def _fit(self):
        text = self._full
        if self._elide:
            text = self.fontMetrics().elidedText(text, Qt.ElideRight,
                                                 max(0, self.contentsRect().width()))
        if text != QLabel.text(self):
            QLabel.setText(self, text)
            self.setToolTip(self._full if text != self._full else "")


THUMB_CACHE = 400       # thumbnails kept, so a card is made (or opened) without
_thumbs: OrderedDict = OrderedDict()    # ...reading its pictures from disk again


def thumb_pixmap(path: str, size: QSize) -> QPixmap:
    """`path`'s thumbnail, `size` at most (a null one if it can't be read). Kept for
    next time, under the file's time and length: a picture changed on disk is read
    again."""
    try:
        st = os.stat(path) if path else None
    except OSError:
        st = None
    if st is None:
        return QPixmap()
    key = (path, st.st_mtime_ns, st.st_size, size.width(), size.height())
    pm = _thumbs.get(key)
    if pm is not None:
        _thumbs.move_to_end(key)
        return pm
    from onionwatch.ui.viewer import read_image
    pm = QPixmap.fromImage(read_image(path, THUMB))
    if pm.isNull():
        return pm               # not kept: it may be readable in a moment
    pm = pm.scaled(size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    _thumbs[key] = pm
    while len(_thumbs) > THUMB_CACHE:
        _thumbs.popitem(last=False)
    return pm


class Thumb(QWidget):
    """One picture in a card's strip: the thumbnail (click to see it big, with the
    trigger's other pictures) on a rounded plate, with a ✕ in its corner while the
    mouse is over it. A closed card's one thumbnail (`tile`) has a + there instead
    (add a picture), and "+3" in the other corner when there are more."""
    clicked = Signal(int)
    removed = Signal(int)
    add = Signal()

    def __init__(self, index: int, path: str, size: QSize = THUMB, tile: bool = False):
        super().__init__()
        self.index = index
        self.tile = tile
        self.pic = QPushButton(self)
        self.pic.setObjectName("thumb")     # just the picture: the plate is painted here
        self.pic.setFixedSize(size + QSize(8, 8))
        self.pic.setIconSize(size)
        self.pic.setCursor(Qt.PointingHandCursor)
        self.pic.clicked.connect(lambda: self.clicked.emit(self.index))
        pm = thumb_pixmap(path, size)
        if pm.isNull():
            self.pic.setIcon(icons.icon("image", "muted"))
            self.pic.setToolTip(_("{name}: this picture can't be read — click to open it and "
                                  "swap it for another file", name=Path(path).name))
        else:
            self.pic.setIcon(pm)
            self.pic.setToolTip(_("{name}\nClick to see it big", name=Path(path).name))
        self.setFixedSize(self.pic.size())
        small = size.height() < THUMB.height()
        self.x = QPushButton("✕", self)
        self.x.setObjectName("danger")
        self.x.setProperty("corner", "small" if small else "big")     # (CARD_CSS)
        self.x.setFixedSize(*((14, 14) if small else (18, 18)))
        self.x.setToolTip(_("Remove this picture"))
        self.x.move(self.width() - self.x.width() - 3, 3)
        self.x.clicked.connect(lambda: self.removed.emit(self.index))
        self.x.hide()
        self.plus = QPushButton("+", self)
        self.plus.setObjectName("thumbadd")
        self.plus.setFixedSize(18, 18)
        self.plus.setCursor(Qt.PointingHandCursor)
        self.plus.setAccessibleName(_("Add a picture"))
        self.plus.setToolTip(_("Add another picture to this trigger"))
        self.plus.move(self.width() - self.plus.width() - 3, 3)
        self.plus.clicked.connect(self.add)
        self.plus.hide()
        self.can_add = True
        self.more = QLabel(self)
        self.more.setObjectName("thumbmore")
        self.more.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.more.hide()

    def set_more(self, n: int):
        """"+n" in the corner: n more pictures than the strip shows."""
        self.more.setVisible(n > 0)
        if n > 0:
            self.more.setText(f"+{n}")
            self.more.adjustSize()
            self.more.move(self.width() - self.more.width() - 4,
                           self.height() - self.more.height() - 4)
            self.pic.setToolTip(self.pic.toolTip() + "\n" + ngettext(
                "{n} more picture: click to see them all",
                "{n} more pictures: click to see them all", n))

    def paintEvent(self, _ev):
        paint_plate(self)

    def enterEvent(self, ev):
        corner = self.plus if self.tile else self.x
        if corner is self.x or self.can_add:
            corner.show()
            corner.raise_()
        super().enterEvent(ev)

    def leaveEvent(self, ev):
        self.x.hide()
        self.plus.hide()
        super().leaveEvent(ev)


TILE_THUMB = QSize(60, 36)  # a closed card's (a tile's) one thumbnail


class Strip(QScrollArea):
    """A card's pictures in a row: up to `shown` wide, scrolling sideways past that,
    so a trigger with a hundred pictures stays a short card. A closed card shows
    one, small, with "+3" on it for the rest (set_look)."""
    picture_clicked = Signal(int)
    picture_removed = Signal(int)
    add_wanted = Signal()               # the + on a closed card's thumbnail

    def __init__(self):
        super().__init__()
        self.can_add = True             # there's room for another picture
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
        self.paths: list[str] = []
        self.thumb = THUMB          # its thumbnails' size
        self.shown = STRIP_THUMBS   # how many it's wide
        self._h = 0
        self._fit_height()

    @property
    def slot(self) -> int:
        return self.thumb.width() + 8 + self.row.spacing()

    def set_look(self, thumb: QSize, shown: int):
        """Thumbnails this big, this many of them side by side."""
        if (thumb, shown) == (self.thumb, self.shown):
            return
        self.thumb, self.shown = thumb, shown
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff if shown == 1
                                          else Qt.ScrollBarAsNeeded)
        self.set_paths(self.paths)

    def set_paths(self, paths: list[str]):
        self.paths = list(paths)
        for th in self.thumbs:
            self.row.removeWidget(th)
            th.hide()           # retain ownership until deferred deletion
            th.deleteLater()
        self.thumbs = []
        # one shown of several: the rest are seen by clicking it (the viewer goes round)
        for i, p in enumerate(paths[:1] if self.shown == 1 else paths):
            th = Thumb(i, p, self.thumb, tile=self.shown == 1)
            th.can_add = self.can_add
            th.clicked.connect(self.picture_clicked)
            th.removed.connect(self.picture_removed)
            th.add.connect(self.add_wanted)
            self.row.insertWidget(i, th)
            self.thumbs.append(th)
        if self.shown == 1 and self.thumbs:
            self.thumbs[0].set_more(len(paths) - 1)
        self.updateGeometry()
        self._fit_height()

    def set_can_add(self, on: bool):
        self.can_add = on
        for th in self.thumbs:
            th.can_add = on

    def sizeHint(self) -> QSize:
        n = min(max(len(self.thumbs), 1), self.shown)
        return QSize(n * self.slot - self.row.spacing(), self._h)

    def minimumSizeHint(self) -> QSize:
        return QSize(self.slot - self.row.spacing(), self._h)

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self._fit_height()

    def _fit_height(self):
        """The thumbnails' height, plus the scrollbar's only when there's more than fits."""
        h = self.thumb.height() + 8
        if (self.shown > 1 and
                len(self.thumbs) * self.slot - self.row.spacing() > self.viewport().width()):
            h += self.horizontalScrollBar().sizeHint().height()
        if h != self._h:
            self._h = h
            self.setFixedHeight(h)


def fill_sources(cb: QComboBox, mons: list[Monitor], places: list,
                 default_label: str = "", pick_label: str = "") -> None:
    """Fill a "Look in" list: "Default (…)" (when `default_label`), each screen,
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
        cb.addItem(icons.icon("apps", "muted"), _("Screen {n}", n=i + 1) + f": {m.label}", i)
        if one == i:
            current = cb.count() - 1
    if not mons and not default_label:
        cb.addItem(icons.icon("apps", "muted"), _("Main screen"), 0)
    if one is not None and not 0 <= one < len(mons) and mons:
        cb.addItem(_("Screen {n} (not plugged in)", n=one + 1), one)
        current = cb.count() - 1
    if places and one is None:
        cb.addItem(icons.icon("window"), places_label(places), PLACES)
        cb.setItemData(cb.count() - 1, "\n".join(
            p.label if isinstance(p, WindowRef) else _("Screen {n}", n=p + 1) for p in places),
            Qt.ToolTipRole)
        current = cb.count() - 1
    cb.insertSeparator(cb.count())
    cb.addItem(icons.icon("window", "muted"), pick_label or _("Pick a window…"), PICK_WINDOW)
    cb.setCurrentIndex(current)
    cb.blockSignals(False)


def source_label(src, mons: list[Monitor]) -> str:
    if isinstance(src, WindowRef):
        return src.label
    if isinstance(src, int) and len(mons) > 1:
        return _("screen {n}", n=src + 1)
    return _("the screen")


def retarget(src, old: WindowRef, new: WindowRef):
    """`src` (a screen or a WindowRef) after the window `old` was swapped for `new`
    (Change window…): a WindowRef of `old`'s program and title becomes `new`'s. The
    copy `old` named takes the copy picked; other copies keep theirs, and one for
    every copy stays every copy. Anything else stays as it is."""
    if not isinstance(src, WindowRef) or (src.exe, src.title) != (old.exe, old.title):
        return src
    if src.every:
        return WindowRef(new.exe, new.title, 0, True)
    return WindowRef(new.exe, new.title, new.nth if src.nth == old.nth else src.nth)


def retargeted(sources: list, old: WindowRef, new: WindowRef) -> list:
    """A trigger's places with `old` swapped for `new` (see retarget), each once."""
    out: list = []
    for s in sources:
        s = retarget(s, old, new)
        if s not in out:
            out.append(s)
    return out


def swatch(colour: str, size: int = 14) -> QIcon:
    pm = QPixmap(size, size)
    pm.fill(QColor(colour) if colour else QColor(0, 0, 0, 0))
    return QIcon(pm)


ALIGN_CSS = "padding-top:4px; padding-bottom:4px; font-size:9pt;"


def align_control(widget: QWidget, in_card: bool = False):
    """One readable control size in both the standalone app and the Board module.
    `in_card`: a card's control, styled by the card's one style sheet (CARD_CSS)
    rather than a sheet of its own each, which made a card slow to make."""
    if in_card:
        polished = widget.testAttribute(Qt.WA_WState_Polished)
        widget.setProperty("aligned", True)
        if polished:            # a property doesn't restyle what's already styled
            widget.style().unpolish(widget)
            widget.style().polish(widget)
        widget.ensurePolished()
        # as a style sheet of its own would: sizes it worked out unstyled are dropped
        QApplication.sendEvent(widget, QEvent(QEvent.StyleChange))
    else:
        widget.setStyleSheet(ALIGN_CSS)
        widget.ensurePolished()
    widget.setFixedHeight(max(34, widget.fontMetrics().height() + 16))
    if isinstance(widget, QPushButton):
        widget.setCursor(Qt.PointingHandCursor)
        if widget.menu():
            widget.setStyleSheet(widget.styleSheet() + "padding-right:24px;")


class FlowBox(QWidget):
    """A wrapping row (Flow) that takes the height its lines need at its width. A
    Flow's height-for-width isn't passed up through the scrolling list of cards,
    so on its own a row that wraps overlaps what's below it, or runs off the edge."""

    def __init__(self, gap: int = 6, parent=None, flow_type=Flow):
        super().__init__(parent)
        self.flow = flow_type(self, gap=gap)

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self._fit()

    def showEvent(self, ev):
        super().showEvent(ev)
        self._fit()

    def event(self, ev):
        result = super().event(ev)
        if ev.type() == QEvent.LayoutRequest:
            self._fit()
        return result

    def _fit(self):
        h = self.flow.heightForWidth(max(self.width(), 1))
        if h != self.minimumHeight():
            self.setMinimumHeight(h)


class ElidedLabel(QLabel):
    """One line cut short a whole part at a time ("12 of 40 triggers on · …") where
    it doesn't fit, never a letter sliced in half at the edge or a lone "1" or "·"
    (the Profile line's counts in a window too narrow for them)."""

    SEPARATORS = ("  —  ", " · ")

    def _ends(self) -> list[int]:
        full = self.text()
        return sorted(i for sep in self.SEPARATORS
                      for i in range(len(full)) if full.startswith(sep, i))

    def least_width(self) -> int:
        """How wide it must be to show its first part."""
        ends = self._ends()
        text = self.text()[:ends[0]] + " …" if ends else self.text()
        return self.fontMetrics().horizontalAdvance(text) + 4

    def sizeHint(self):     # (its full width would squeeze everything beside it)
        return QSize(self.least_width(), super().sizeHint().height())

    def minimumSizeHint(self):
        return QSize(0, super().minimumSizeHint().height())

    def shown_text(self) -> str:
        width, fm = self.contentsRect().width(), self.fontMetrics()
        full = self.text()
        if fm.horizontalAdvance(full) <= width:
            return full
        for end in reversed(self._ends()):
            text = full[:end] + " …"
            if fm.horizontalAdvance(text) <= width:
                return text
        return ""

    def paintEvent(self, ev):
        r = self.contentsRect()
        text = self.shown_text()
        p = QPainter(self)
        self.style().drawItemText(p, r, int(self.alignment()), self.palette(),
                                  self.isEnabled(), text, self.foregroundRole())
        p.end()


class BarFlow(Flow):
    """The bottom bar's Flow: an item that doesn't fit the rest of a line gives way,
    down to its minimum (a Pair: to what keeps it on one line), before it wraps, and
    is as tall as it needs at the width it gets (a Pair on two lines)."""

    def _place(self, rect: QRect, move: bool) -> int:
        x, y, line = rect.x(), rect.y(), 0
        pending = []

        def place_line():
            if move:
                for item, left, size in pending:
                    item.setGeometry(QRect(QPoint(left, y + (line - size.height()) // 2), size))

        items = [it for it in self._items if not it.isEmpty()]
        for i, it in enumerate(items):
            wid = it.widget()
            pair = wid if isinstance(wid, Pair) else None
            hint, least = it.sizeHint(), it.minimumSize().width()
            keep = pair.one_line_width() if pair else least
            if line and x + keep > rect.right() + 1:        # doesn't fit here: next line
                place_line()
                pending.clear()
                x, y, line = rect.x(), y + line + self._gap, 0
            room = rect.right() + 1 - x
            # leave the items after it their least on this line when it can give way
            # that far (a wide Look in pushed the ⚙ onto a line of its own)
            rest = sum(self._gap + later.minimumSize().width() for later in items[i + 1:])
            if room - rest >= keep:
                room -= rest
            w = max(least, min(hint.width(), room))
            # (asked directly: Qt asks a widget's layout, not the widget)
            h = pair.heightForWidth(w) if pair else hint.height()
            pending.append((it, x, QSize(w, h)))
            x += w + self._gap
            line = max(line, h)
        place_line()
        return y + line - rect.y()


def tall(w: QWidget) -> int:
    """How tall `w` really is: its size hint, or its fixed height (align_control's 34 px)
    when that's more. The hint alone cut the bottom off the Ring list."""
    return max(w.sizeHint().height(), w.minimumHeight())


def control_height(widget: QWidget) -> int:
    """The one height align_control gives a control (a label beside it matches it)."""
    return max(34, widget.fontMetrics().height() + 16)


def capital(text: str) -> str:
    """ "then play" -> "Then play" (nothing changes where there are no capitals)."""
    return text[:1].upper() + text[1:]


class ShrinkButton(QPushButton):
    """A button that, short of room, shows just its icon (its tooltip still says
    what it does), so a narrow card isn't held wide by it."""

    def __init__(self, text: str, parent=None):
        super().__init__(text, parent)
        self._text = text
        self._hint: QSize | None = None
        self.setAccessibleName(text)     # (still said with just its icon showing)
        # (a button's Minimum policy makes its full width its least)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)

    def _full(self) -> QSize:
        """Its size with its words (worked out while they're showing)."""
        if self.text() or self._hint is None:
            shown = self.text()
            if not shown:
                self.blockSignals(True)
                QPushButton.setText(self, self._text)
            self._hint = super().sizeHint()
            if not shown:
                QPushButton.setText(self, "")
                self.blockSignals(False)
        return self._hint

    def sizeHint(self) -> QSize:
        return self._full()

    def minimumSizeHint(self) -> QSize:
        return QSize(self.iconSize().width() + 22, self._full().height())

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        want = "" if ev.size().width() < self._full().width() else self._text
        if self.text() != want:
            self.setText(want)


class TuneGrid(QWidget):
    """More options as tidy columns: each column a group (finding it, timing, the
    rest), each setting its label then its control, the labels in a column one width
    so the controls line up, the columns spread over the whole width. Fewer columns
    when it's narrow. A setting moved up to the When line (`removeWidget`) leaves its
    place until it comes back (`addWidget`)."""

    GAP = 28    # px between columns

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("labelled")     # see-through (CARD_CSS)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.grid = QGridLayout(self)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setHorizontalSpacing(6)
        self.grid.setVerticalSpacing(8)
        self.groups: list[list[tuple]] = []   # [(label, widget, inner label), …] each
        self.out: set = set()
        self._cols = 0

    def add_group(self, items: list[tuple]):
        for lab, w, inner in items:
            for x in (lab, w):
                if x is not None:
                    x.setParent(self)
            for x in (lab, inner):
                if x is not None:
                    x.setObjectName("formlabel")    # the controls' font size
            if isinstance(w, QCheckBox):
                w.setObjectName("formcheck")
            elif isinstance(w, Pair) and isinstance(w.first, QCheckBox):
                w.first.setObjectName("formcheck")
        self.groups.append(items)

    def removeWidget(self, w: QWidget):
        self.out.add(w)
        self.grid.removeWidget(w)
        self.relayout()

    def addWidget(self, w: QWidget):
        w.setParent(self)
        w.show()
        self.out.discard(w)
        self.relayout()

    def _columns(self, n: int) -> list[list[tuple]]:
        shown = [[it for it in g if it[1] not in self.out and it[1].isVisibleTo(self)]
                 for g in self.groups]
        if n >= len(shown):
            return shown
        # fewer columns than groups: a group stays whole, under the shortest column
        cols: list[list[tuple]] = [[] for _i in range(n)]
        for i, g in enumerate(shown):
            target = cols[i] if i < n else min(cols, key=len)
            target.extend(g)
        return cols

    @staticmethod
    def _label_w(col: list[tuple]) -> int:
        return max([x.sizeHint().width() for lab, _w, inner in col for x in (lab, inner)
                    if x is not None] or [0])

    def relayout(self):
        """Lay it out in as many columns (3, 2, 1) as fit its width."""
        width = self.width()
        for n in (3, 2, 1):
            self._lay(n)
            if width <= 0 or n == 1 or self.grid.sizeHint().width() <= width:
                break
        self.updateGeometry()

    def _lay(self, n: int):
        g = self.grid
        while g.count():
            g.takeAt(0)
        for c in range(g.columnCount()):
            g.setColumnStretch(c, 0)
            g.setColumnMinimumWidth(c, 0)
        self._cols = n
        # packed left: the space left over goes to an empty column at the end
        g.addItem(QSpacerItem(0, 0, QSizePolicy.Expanding, QSizePolicy.Minimum), 0, 3 * n)
        g.setColumnStretch(3 * n, 1000)
        for group in self.groups:
            for lab, w, _inner in group:
                if lab is not None:
                    lab.setVisible(w not in self.out and w.isVisibleTo(self))
        for c, col in enumerate(self._columns(n)):
            lc = 3 * c
            lw = self._label_w(col)
            g.setColumnMinimumWidth(lc, lw)
            # room a wide row (Ring and its list) needs goes to the controls' column,
            # never the labels': the controls stay lined up (packed left: no spreading)
            g.setColumnStretch(lc + 1, 1)
            if c < n - 1:
                g.setColumnMinimumWidth(lc + 2, self.GAP - 12)
            # the number boxes in a column one width, so their arrows line up too
            spins = [sp for _lab, w, _inner in col
                     for sp in ([w] if isinstance(w, QAbstractSpinBox) else [])
                     + w.findChildren(QAbstractSpinBox)]
            for sp in spins:
                sp.setMinimumWidth(0)
            widest = max([sp.sizeHint().width() for sp in spins] or [0])
            for sp in spins:
                sp.setMinimumWidth(widest)
            for r, (lab, w, inner) in enumerate(col):
                if lab is not None:
                    if isinstance(w, QComboBox):    # never squeezed to cut its text
                        w.setMinimumWidth(w.sizeHint().width())
                    lab.setFixedHeight(control_height(w))
                    g.addWidget(lab, r, lc, Qt.AlignLeft | Qt.AlignVCenter)
                    g.addWidget(w, r, lc + 1, Qt.AlignLeft | Qt.AlignVCenter)
                else:
                    # (a Pair's height-for-width comes out 0 in a grid cell, and it
                    # stays on one line: its sizeHint alone lets it be squeezed)
                    w.setMinimumHeight(control_height(w))
                    if isinstance(w, Pair):
                        w.setMinimumWidth(w.first.sizeHint().width() + w.GAP
                                          + w.second.sizeHint().width())
                    if inner is not None:       # its label inside it, as wide as the rest
                        inner.setFixedWidth(lw)
                    g.addWidget(w, r, lc, 1, 2, Qt.AlignLeft | Qt.AlignVCenter)

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        if ev.size().width() != ev.oldSize().width():
            self.relayout()


class Pair(QWidget):
    """Two labelled controls that read as one ("Look in [game] every [100 ms]"): on
    one line while it's wide enough for both, the second under the first when it
    isn't. A label never ends up apart from its control."""

    GAP, STACKED = 10, 6    # px between them: side by side, one under the other

    def __init__(self, first: QWidget, second: QWidget, parent=None):
        super().__init__(parent)
        self.setObjectName("labelled")      # see-through, like labelled()'s (CARD_CSS)
        self.first, self.second = first, second
        self.box = QBoxLayout(QBoxLayout.LeftToRight, self)
        self.box.setContentsMargins(0, 0, 0, 0)
        self.box.setSpacing(self.GAP)
        self.box.addWidget(first, 0, Qt.AlignLeft)
        self.box.addWidget(second, 0, Qt.AlignLeft)
        self.box.addStretch(1)

    def one_line_width(self) -> int:
        """The least it can be with both on one line."""
        if self.second.isHidden():
            return self.first.minimumSizeHint().width()
        return (self.first.minimumSizeHint().width() + self.GAP
                + self.second.minimumSizeHint().width())

    def _one_line(self, w: int) -> bool:
        return w >= self.one_line_width()

    def sizeHint(self) -> QSize:
        if self.second.isHidden():
            return self.first.sizeHint()
        a, b = self.first.sizeHint(), self.second.sizeHint()
        return QSize(a.width() + self.GAP + b.width(), max(tall(self.first), tall(self.second)))

    def minimumSizeHint(self) -> QSize:
        if self.second.isHidden():
            return self.first.minimumSizeHint()
        a, b = self.first.minimumSizeHint(), self.second.minimumSizeHint()
        return QSize(max(a.width(), b.width()), max(a.height(), b.height()))

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, w: int) -> int:
        if self.second.isHidden():
            return tall(self.first)
        a, b = tall(self.first), tall(self.second)
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
        right = on != self.isRightToLeft()     # mirrored: on is on the left
        p.drawEllipse(QRectF(21 if right else 3, 3, 16, 16))


def divider() -> QFrame:
    """A thin line between a card's parts, in the palette's colours (the host's theme
    doesn't know about it)."""
    f = QFrame()
    f.setObjectName("carddivider")
    f.setFixedHeight(1)         # (coloured by CARD_CSS)
    return f


def indented(parent: QVBoxLayout, spacing: int = 8) -> QVBoxLayout:
    """A column under a section's title, set in a little so the title stands out."""
    box = QWidget()
    box.setObjectName("labelled")   # see-through (CARD_CSS)
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
    b.setProperty("section", True)      # (CARD_CSS)
    icons.set_icon(b, icon, "section", size=13)
    return b


# a card's own looks, in one style sheet on the card rather than one on each of its
# widgets (a card has dozens: a sheet each made a card slow to make). In the
# palette's colours: the host's theme (Onion Board's) doesn't know about them
CARD_CSS = (
    "QWidget#labelled { background: transparent; }"      # labelled(), indented()...
    "QFrame#carddivider { background: palette(mid); border: none; }"
    # a sound on the card: the shape and height of the boxes beside it, not a pill
    "QLabel#formlabel, QCheckBox#formcheck { font-size: 9pt; }"
    "QFrame#chip { border-radius: 8px; }"
    "QFrame#chip QPushButton#chipname { font-size: 9pt; font-weight: normal;"
    " padding: 0 4px; }"
    "QComboBox#addsound { padding: 0 0 0 9px; }"
    "QComboBox#addsound::drop-down { width: 0; border: none; }"
    "QComboBox#addsound::down-arrow { image: none; }"
    "QFrame#chip QPushButton#chipstop { border-radius: 6px; }"
    'QPushButton#fold[section="true"] { text-align:left; padding-left:0; }'
    f'*[aligned="true"], *[aligned="true"] * {{ {ALIGN_CSS} }}'     # align_control()
    # a picture in the strip (Thumb): its plate is painted; its ✕, its + and its "+3"
    "QPushButton#thumb { background:transparent; border:none; padding:0; }"
    'QPushButton#danger[corner="small"] { padding:0; font-size:7pt; }'
    'QPushButton#danger[corner="big"] { padding:0; font-size:8pt; }'
    "QPushButton#thumbadd { background:palette(highlight);"
    " color:palette(highlighted-text); border:none; border-radius:9px; padding:0;"
    " font-size:10pt; font-weight:700; }"
    "QLabel#thumbmore { background: rgba(0,0,0,170); color: white;"
    " border-radius: 4px; padding: 0 3px; font-size: 7pt; font-weight: 700; }"
    # the dashed + after the pictures
    "QPushButton#addpic { background:transparent; border:1px dashed palette(mid);"
    " border-radius:8px; padding:0; font-size:12pt; color:palette(window-text); }"
    "QPushButton#addpic:hover { border-color:palette(highlight);"
    " color:palette(highlight); }"
    "QPushButton#addpic:disabled { border-color:transparent; color:transparent; }"
    # the name: a title until you click it (open), or just read (closed)
    "QLineEdit#cardname { background:transparent; border:1px solid transparent;"
    " padding:2px 3px; font-size:11pt; font-weight:700; }"
    "QLineEdit#cardname:hover { border-color:palette(mid); }"
    "QLineEdit#cardname:focus { background:palette(base);"
    " border-color:palette(highlight); }"
    "QLabel#cardtitle { font-size:10.5pt; font-weight:700; }"
)
CARD_HOVER = "QFrame#card:hover { border-color:palette(highlight); }"
# the trigger the editor on the right is showing, in the list
CARD_SELECTED = "QFrame#card { border:2px solid palette(highlight); }"


class TriggerRow(QFrame):
    """One trigger's card: a header (pictures, name, what it does, the live match,
    on / off) that opens to three parts: what to watch for, what happens then, and
    the fine-tuning, folded away behind a line summing it up. Closed, it's a tile in
    its category's grid: the same header, small (a picture, the name over how it's
    doing and what it plays, the switch); open, it's the whole width."""
    changed = Signal(object)             # row: a setting changed
    pictures_wanted = Signal(object)     # row: "+ Add pictures…" (files)
    paste_wanted = Signal(object)        # row: "Paste picture"
    cut_wanted = Signal(object)          # row: "Cut from window…"
    picture_view = Signal(object, int)   # row, index: a thumbnail was clicked: show it big
    picture_swap = Signal(object, int)   # row, index: swap that picture for another file
    picture_removed = Signal(object, int)  # row, index
    sound_file_wanted = Signal(object)   # row: "Choose a sound file…"
    window_wanted = Signal(object)       # row: "Pick windows…"
    retarget_wanted = Signal(object)     # WindowRef: "Change window…" on a window not open
    area_wanted = Signal(object)         # row: "Area…"
    duplicate = Signal(object)           # row: "Duplicate"
    category_wanted = Signal(object, str)  # row, category: moved there (NEW_CATEGORY: ask)
    hear = Signal(str)                   # a sound chip was clicked: play that sound id
    test = Signal(object)
    remove = Signal(object)
    files_dropped = Signal(object, list)   # row, picture files dropped on it
    picture_dropped = Signal(object, object)  # row, a picture (QImage) dropped on it

    def __init__(self, t: Trigger, sounds: list[tuple[str, str]],
                 screens: list[Monitor] = (), open_: bool = False,
                 parent: QWidget | None = None):
        super().__init__(parent)
        if parent is not None:      # until it's laid out, the size a card made on its
            self.resize(640, 480)   # own starts at: not "too narrow" (_fit_narrow)
        self.setObjectName("card")
        self.t = t
        self.advanced = False
        self.watching = False
        self.cooldown_until = 0.0
        self.sound_details = lambda _sid: _("Volume / hotkey: sound settings")
        self.missing: list[str] = []    # its sounds that are no longer in the library
        self.fallback = False           # its own screen isn't there: the default is watched
        self.note: tuple[str, str] | None = None   # (text, tone) from watching: not open…
        self.waiting: WindowRef | None = None       # the window the note waits for
        self._screens = 0               # how many screens there are
        self._mons: list[Monitor] = []
        self._sounds: list[tuple[str, str]] = []   # the sounds as last given
        self._narrow = False            # too narrow for the header's thumbnail
        self._press: QPoint | None = None   # where a press on the header began (a drag?)
        # with the list beside an editor: opening the card shows it there instead
        self.on_open = None
        self.pinned = False             # it's that editor: always open, not dragged
        self.selected = False           # it's the one the editor is showing
        self.setAcceptDrops(True)           # picture files dropped on it are added
        v = QVBoxLayout(self)
        v.setContentsMargins(10, 8, 10, 8)
        v.setSpacing(6)

        # the header, always shown: its pictures (and a + to add more), name, what it
        # does (or what's wrong), the live match, on / off, and open / close. Click it
        # to open the rest, drag it to move it. Laid out by _arrange: on one line while
        # open; closed, a small thumbnail and the switches over the name and the rest
        self.top = top = QGridLayout()
        top.setHorizontalSpacing(8)
        top.setVerticalSpacing(2)
        self.strip = Strip()
        self.strip.setToolTip(_("The pictures to look for: any of them showing up plays the "
                                "sound. Click one to see it big."))
        self.strip.picture_clicked.connect(lambda i: self.picture_view.emit(self, i))
        self.strip.picture_removed.connect(lambda i: self.picture_removed.emit(self, i))
        self.strip.add_wanted.connect(self._show_add_menu)
        self.btn_add_pic = QPushButton("+")
        # a dashed slot after the pictures (open), or where the first one goes
        self.btn_add_pic.setObjectName("addpic")
        self.btn_add_pic.setAccessibleName(_("Add a picture"))
        self.btn_add_pic.setToolTip(_("Add a picture: cut it from the window, pick files or "
                                      "paste the one you copied. You can also drop picture files "
                                      "on the card."))
        self.btn_add_pic.setCursor(Qt.PointingHandCursor)
        self.btn_add_pic.clicked.connect(self._show_add_menu)
        # the header's pieces belong to the card from the start: _arrange moves them
        # between layouts, and a piece shown while it had no parent flashed up on the
        # desktop as a little blank window of its own (and lagged the app)
        self.pics = QWidget(self)       # the strip and its +, side by side
        self.pics.setObjectName("labelled")
        pics = QHBoxLayout(self.pics)
        pics.setContentsMargins(0, 0, 0, 0)
        pics.setSpacing(4)
        pics.addWidget(self.strip)
        pics.addWidget(self.btn_add_pic)
        self.badge = Plate(self)          # instead of the strip, for a trigger without pictures
        self.badge.setObjectName("iconlabel")
        self.badge.setAlignment(Qt.AlignCenter)
        self.names = QWidget(self)        # under the name: what it does (or what's wrong)...
        self.names.setObjectName("labelled")      # see-through, like labelled()'s boxes
        names = QVBoxLayout(self.names)
        names.setContentsMargins(0, 0, 0, 0)
        names.setSpacing(2)
        self.name = QLineEdit(t.name)
        # a title until you click it (styled by CARD_CSS)
        self.name.setObjectName("cardname")
        self.name.setToolTip(_("Click to rename it"))
        self.name.setMinimumWidth(50)
        self.name.setPlaceholderText(_("Name, e.g. Rare spawn"))
        self.name.setMaxLength(60)
        self.name.setCursorPosition(0)          # a long name shows its start, not its end
        self.setStyleSheet(CARD_CSS + CARD_HOVER)
        self.name.editingFinished.connect(self._on_name)
        self.name.editingFinished.connect(lambda: self.name.setCursorPosition(0))
        # as wide as the name, not the whole card: the hover / editing box hugs it
        self.name.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)   # up to that
        self.name.textChanged.connect(self._fit_name)
        self._fit_name()
        self.name_line = QWidget(self)    # the name takes what it needs, the rest is empty
        self.name_line.setObjectName("labelled")
        line = QHBoxLayout(self.name_line)
        line.setContentsMargins(0, 0, 0, 0)
        line.setSpacing(0)
        line.addWidget(self.name, 100)
        # a closed card's name is just read (a click anywhere on the card opens it)
        self.title = ElideLabel()
        self.title.setObjectName("cardtitle")
        self.title.setContentsMargins(6, 0, 0, 0)
        self.title.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.title.set_elide(True)
        self.name.textChanged.connect(self._show_title)
        self._show_title()
        line.addWidget(self.title, 100)
        line.addStretch(1)
        self.state = ElideLabel()
        self.state.setObjectName("hint")
        self.state.set_elide(True)      # one line: the whole of it is its tooltip
        self.state.setIndent(0)
        self.state.setContentsMargins(6, 0, 0, 0)  # title's border, padding and text inset
        self.state.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        # on "Waiting for <game> to open": point everything that looked in that
        # window at another one (the game's program was renamed, a new launcher...)
        self.btn_retarget = QPushButton(_("Change window…"))
        self.btn_retarget.setObjectName("small")
        self.btn_retarget.setToolTip(
            _("Pick the window to look in instead. Every trigger, the default Look in and the "
              "profiles that used this window (or its program) move to the new one."))
        self.btn_retarget.clicked.connect(
            lambda: self.waiting is not None and self.retarget_wanted.emit(self.waiting))
        self.btn_retarget.setVisible(False)
        state_line = QHBoxLayout()
        state_line.setSpacing(6)
        state_line.addWidget(self.state, 1)
        state_line.addWidget(self.btn_retarget)
        names.addLayout(state_line)
        self.sound_summary = ElideLabel()
        self.sound_summary.setObjectName("muted")
        self.sound_summary.setContentsMargins(6, 0, 0, 0)
        self.sound_summary.setWordWrap(True)
        self.sound_summary.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        names.addWidget(self.sound_summary)
        self.details = QLabel(self)
        self.details.setContentsMargins(6, 0, 0, 0)
        self.details.setObjectName("hint")
        self.details.setWordWrap(True)
        self.details.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.details.setParent(self)    # under a closed card's header (_arrange)
        self.details.hide()
        # what it's doing right now: a coloured dot and a word, or the live match
        self.live = LiveLabel(self)
        self.live.setTextFormat(Qt.RichText)
        self.live.setIndent(0)
        self.live.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self._live_shown = ""
        self._live_room: QSize | None = None    # a score's size (_fit_live)
        self._live_score = False            # it's showing a score
        self._score: float | None = None    # the score shown (show_score)
        self.chk_on = Switch(self)
        self.chk_on.setToolTip(_("Watch for this trigger (switch it off to keep it but pause it)"))
        self.chk_on.setChecked(t.enabled)
        self.chk_on.toggled.connect(self._on_enabled)
        self.btn_open = QPushButton(self)
        self.btn_open.setObjectName("fold")
        self.btn_open.setCheckable(True)
        self.btn_open.setFixedSize(28, 28)
        self.btn_open.setAccessibleName(_("Edit trigger"))
        self.btn_open.toggled.connect(self.set_open)
        self._tile: bool | None = None      # how the header is laid out now (_arrange)
        self._said: bool | None = None      # a tile's line is saying what's wrong
        v.addLayout(top)

        self.body = QWidget()
        sp = self.body.sizePolicy()
        sp.setHeightForWidth(True)          # its rows wrap: taller when narrower
        self.body.setSizePolicy(sp)
        bv = QVBoxLayout(self.body)
        bv.setContentsMargins(0, 0, 0, 2)     # the card's 8 at the bottom: 10, as at its sides
        bv.setSpacing(10)    # room between the editor's rows: at 4 they looked packed
        v.addWidget(self.body)
        v.addStretch(1)     # a tile taller than it needs (its line's tallest): space below
        # the editor under the header is made the first time the card opens
        # (_build_body): a closed tile is just its header, and most never open
        self._built = False
        self._categories: list[str] | None = None   # set_categories, kept till then
        self._default_ms: int | None = None          # set_default_interval, likewise
        self.default_place = ""         # where "Default" looks (set_default_place)

        self._flash = QTimer(self)
        self._flash.setSingleShot(True)
        self._flash.timeout.connect(self._update_state)
        self._show_mode()
        self.set_sounds(sounds)
        self.set_screens(list(screens))
        if not open_:   # its pictures made once, at the size they're shown (_arrange)
            self.strip.set_look(TILE_THUMB, 1)
        self.refresh_pictures()
        self._update_state()
        self.show_score(None)
        self.btn_open.setChecked(open_)
        self.set_open(open_)

    # the editor's widgets, made by _build_body: asking a closed card for one makes it
    EDITOR = frozenset({
        "mode", "where", "where_box", "_watch_row", "sounds_box", "sounds_row",
        "lbl_play", "chips", "sound", "pick", "btn_test", "btn_tune", "tune_text",
        "btn_dup", "btn_del", "tune", "tune_div", "_tune_row", "btn_area", "interval",
        "chk_size", "chk_ring", "until", "ring_box", "delay", "cooldown", "hold",
        "lbl_hold", "hold_box", "threshold", "below", "lbl_number", "match_box", "_in",
        "chk_quiet", "cb_category"})

    def __getattr__(self, name: str):
        # (only for what isn't there: a closed card's editor, made now)
        if name in TriggerRow.EDITOR and self.__dict__.get("_built") is False:
            self._build_body()
            return getattr(self, name)
        raise AttributeError(f"{type(self).__name__!r} object has no attribute {name!r}")

    @property
    def built(self) -> bool:
        """Its editor has been made (it was opened, or something needed it)."""
        return self._built

    def _build_body(self):
        """Make the editor: the "When … in …" sentence, the sounds, More options."""
        if self._built:
            return
        self._built = True
        t = self.t
        bv = self.body.layout()
        # the card reads as a sentence: "When [it shows up] in [the game], then play
        # [Ready] [Chime] [+ Add sound…]  ▶ Test". The pictures are the header's (its +
        # adds more); everything else is folded away under More options, behind a line
        # summing it up
        bv.addWidget(divider())
        bv.addSpacing(2)
        # When / Look in / Then play / Category: one row each, the labels in one
        # column (the controls' font size), the controls lined up after them
        form = QGridLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(8)
        form.setColumnStretch(1, 1)

        def form_label(text: str, icon: str) -> QWidget:
            box = QWidget()
            box.setObjectName("labelled")       # see-through (CARD_CSS)
            h = QHBoxLayout(box)
            h.setContentsMargins(0, 0, 0, 0)
            h.setSpacing(7)
            pic = QLabel()
            pic.setPixmap(icons.icon(icon, "muted").pixmap(15, 15))
            h.addWidget(pic)
            lab = QLabel(capital(text))
            lab.setObjectName("formlabel")
            h.addWidget(lab)
            box.setFixedHeight(control_height(lab))
            return box
        sentence = FlowBox(gap=8)
        row = sentence.flow
        self.mode = WideCombo(min_width=120)
        for key, label in MODES:
            self.mode.addItem(capital(label), key)     # a choice of its own, not mid-sentence
        self.mode.setCurrentIndex(max(self.mode.findData(t.mode), 0))
        self.mode.setToolTip(
            _("What sets it off:\n• it shows up: one of its pictures appears\n• it goes away: "
              "its picture disappears (a buff running out, a bobber)\n• the area changes: "
              "anything moves in its area (a chat line, the minimap)\n• the area stops changing: "
              "nothing moves for a while (stuck, idle, disconnected)\n• a bar runs low: less of "
              "its area is one colour (a health bar)"))
        no_wheel(self.mode)
        self.mode.activated.connect(self._on_mode)
        row.addWidget(self.mode)
        self.where = WideCombo(min_width=120)
        self.where.setToolTip(_("Where to look: game windows (watched even while other windows "
                                "cover them, but not while they're minimized) or whole screens. "
                                "“Pick windows…” can tick several, or every copy of a game. "
                                "“Default” is the Look in on the bottom bar."))
        no_wheel(self.where)
        self.where.activated.connect(self._on_where)
        self.where_box = self.where
        form.addWidget(form_label(_("When"), "history"), 0, 0, Qt.AlignTop | Qt.AlignLeft)
        form.addWidget(sentence, 0, 1)
        self.btn_tune = ShrinkButton(_("More options"))
        form.addWidget(self.btn_tune, 0, 2, Qt.AlignTop)     # (no left/right: it may shrink)
        form.addWidget(form_label(_("Look in"), "window"), 1, 0, Qt.AlignTop | Qt.AlignLeft)
        form.addWidget(self.where, 1, 1, Qt.AlignLeft)
        self._watch_row = row
        self.sounds_box = FlowBox(gap=8)
        self.sounds_row = self.sounds_box.flow
        self.lbl_play = form_label(_("then play"), "volume")
        self.chips: list[QFrame] = []
        self.sound = QComboBox()        # a square +: its list opens wide enough
        self.sound.setObjectName("addsound")
        self.sound.setAccessibleName(_("+ Add sound…"))
        self.sound.view().setMinimumWidth(260)
        self.sound.setToolTip(_("Add a sound to play: a built-in alert, or a sound file of yours"))
        no_wheel(self.sound)
        self.sound.activated.connect(self._on_sound)
        self.pick = WideCombo(self)    # (shown before it's in the row: no flash)
        for key, label in PICKS:
            self.pick.addItem(label, key)
        self.pick.setCurrentIndex(max(self.pick.findData(t.pick), 0))
        self.pick.setToolTip(_("With several sounds: play one at random (each once before any "
                               "repeats), take them in turn, or play them all at once"))
        no_wheel(self.pick)
        self.pick.currentIndexChanged.connect(self._on_pick)
        self.btn_test = QPushButton(_("Test"), self)
        self.btn_test.setObjectName("small")
        icons.set_icon(self.btn_test, "play", size=14)
        self.btn_test.clicked.connect(lambda: self.test.emit(self))
        form.addWidget(self.lbl_play, 2, 0, Qt.AlignTop | Qt.AlignLeft)
        form.addWidget(self.sounds_box, 2, 1)
        self.cb_category = WideCombo(min_width=120)
        self.cb_category.setToolTip(_("The category this trigger is in: a whole category can be "
                                      "switched on or off at once"))
        no_wheel(self.cb_category)
        self.cb_category.activated.connect(self._on_category)
        form.addWidget(form_label(_("Category"), "folder"), 3, 0, Qt.AlignTop | Qt.AlignLeft)
        form.addWidget(self.cb_category, 3, 1, Qt.AlignLeft)
        bv.addLayout(form)

        # the bottom line: Test, Duplicate, Delete, and what More options has changed
        tune = QHBoxLayout()
        tune.setSpacing(12)
        self.btn_tune.setObjectName("small")
        self.btn_tune.setCheckable(True)
        self.btn_tune.setToolTip(_("Where in the window, how alike, how long, how often, "
                                   "ringing, and when to keep quiet"))
        icons.set_icon(self.btn_tune, "setup", size=14)
        self.btn_tune.toggled.connect(self._on_tune)
        self.tune_text = ElideLabel()
        self.tune_text.setObjectName("hint")
        self.tune_text.setWordWrap(True)    # wraps when narrow, never cut short
        self.tune_text.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        tune.addWidget(self.btn_test)
        # Duplicate and Delete in words, not behind a ⋯ nobody could read
        self.btn_dup = QPushButton(_("Duplicate"))
        self.btn_dup.setObjectName("small")
        self.btn_dup.setToolTip(_("Make a copy of this trigger (pictures, sounds and all)"))
        self.btn_dup.clicked.connect(lambda: self.duplicate.emit(self))
        tune.addWidget(self.btn_dup)
        self.btn_del = QPushButton(_("Delete"))
        self.btn_del.setObjectName("small")
        icons.set_icon(self.btn_del, "trash", size=14)
        self.btn_del.setToolTip(_("Delete this trigger (Recently deleted keeps it a while)"))
        self.btn_del.clicked.connect(lambda: self.remove.emit(self))
        tune.addWidget(self.btn_del)
        tune.addSpacing(6)
        tune.addWidget(self.tune_text, 100)
        tune.addStretch(1)      # with nothing to sum up the buttons keep their size
        self._tune_line = tune      # (added under the options, below)
        # opened: three columns. Timing (wait, must last, not again for); what it looks
        # at (the area, how alike, how often); then the tick boxes together. A line
        # sets them apart from the rest above (the editor's 10 px either side of it)
        self.tune_div = divider()
        self.tune_div.setVisible(False)
        bv.addWidget(self.tune_div)
        self.tune = TuneGrid()
        self.tune.setVisible(False)
        self._tune_row = self.tune
        self.btn_area = QPushButton(self.tune)
        self.btn_area.setObjectName("small")
        self.btn_area.clicked.connect(lambda: self.area_wanted.emit(self))
        self.interval = WideCombo(min_width=100)
        self.interval.addItem(_("Default"), 0)       # its text: set_default_interval
        for ms in sorted(set(INTERVALS_MS) | {t.interval_ms} - {0}):
            self.interval.addItem(interval_label(ms), ms)
        self.interval.setCurrentIndex(max(0, self.interval.findData(t.interval_ms)))
        self.interval.setToolTip(_("How often this trigger is checked. Default is the speed set "
                                   "under ⚙ (Watching settings, on the bottom bar), for every "
                                   "trigger left on Default. Watching keeps to its share of your "
                                   "processor, so with a lot on it may check less often."))
        no_wheel(self.interval)
        self.interval.currentIndexChanged.connect(self._on_interval)
        self.chk_size = QCheckBox(_("Find it at any size"))
        self.chk_size.setToolTip(
            _("Find the pictures even when the game shows them bigger or smaller than when they "
              "were cut: cut in fullscreen, played in a window, or another UI scale.\nUntick it "
              "if a picture only ever shows at one size and it goes off by mistake."))
        self.chk_size.setChecked(t.any_size)
        self.chk_size.toggled.connect(self._on_size)
        self.threshold = FitSpin()
        self.threshold.setObjectName("stepper")   # arrows like Wait / Not again for
        self.threshold.setSuffix(" %")
        self.below = WideCombo(min_width=70)
        self.below.addItem("below", True)
        self.below.addItem("above", False)
        self.below.setCurrentIndex(0 if t.below else 1)
        self.below.setToolTip(_("Go off when less of the area is the colour (a bar running low), "
                                "or when more of it is"))
        no_wheel(self.below)
        self.below.currentIndexChanged.connect(self._on_below)
        self.lbl_number = QLabel()
        self.match_box = match = labelled("", self.threshold, in_card=True)
        match.layout().insertWidget(0, self.lbl_number)
        match.layout().insertWidget(1, self.below)
        self.chk_ring = QCheckBox(_("Keep playing"))
        self.chk_ring.setToolTip(_("Keep playing the sound over and over — for when you're away "
                                   "from the keyboard. The Stop button on the red bar always "
                                   "stops it; pick what else does next to it."))
        self.chk_ring.setChecked(t.ring)
        self.chk_ring.toggled.connect(self._on_ring)
        self.until = WideCombo(self)   # (shown before it's in its Pair: no flash)
        for key, (label, *_rest) in UNTILS.items():
            self.until.addItem(label, key)
            self.until.setItemData(self.until.count() - 1, UNTILS[key][3], Qt.ToolTipRole)
        self.until.setCurrentIndex(max(self.until.findData(t.stop), 0))
        self.until.setToolTip(_("What stops the ringing by itself"))
        self.until.setVisible(t.ring)
        no_wheel(self.until)
        self.until.currentIndexChanged.connect(self._on_until)
        self.ring_box = Pair(self.chk_ring, self.until)
        self.delay = FitDoubleSpin()
        self.delay.setRange(0.0, 60.0)
        self.delay.setDecimals(1)
        self.delay.setSingleStep(0.5)
        self.delay.setSuffix(" s")
        self.delay.setValue(t.delay)
        self.delay.setToolTip(_("How long after it goes off to play the sound (0 = straight away)"))
        self.cooldown = FitDoubleSpin()
        self.cooldown.setRange(0.0, 600.0)
        self.cooldown.setDecimals(0)
        self.cooldown.setSingleStep(1.0)
        self.cooldown.setSuffix(" s")
        self.cooldown.setValue(t.cooldown)
        self.cooldown.setToolTip(_("After playing, ignore this trigger for this long. It also "
                                   "has to stop before it can play again."))
        self.hold = FitDoubleSpin()
        self.hold.setRange(0.0, screenwatch.MAX_HOLD)
        self.hold.setDecimals(1)
        self.hold.setSingleStep(0.5)
        self.hold.setSuffix(" s")
        self.hold.setValue(t.hold)
        self.lbl_hold = QLabel()
        self.hold_box = hold = labelled("", self.hold, in_card=True)
        hold.layout().insertWidget(0, self.lbl_hold)
        # box -> where it is now: More options, or up on the When line
        self._in: dict = {match: self.tune, hold: self.tune, self.btn_area: self.tune}
        self.chk_quiet = QCheckBox(_("Stay quiet while I'm in that window"))
        self.chk_quiet.setToolTip(_("Stay quiet while the window it went off in is the one "
                                    "you're using: you can see it yourself"))
        self.chk_quiet.setChecked(t.unfocused)
        self.chk_quiet.toggled.connect(self._on_quiet)
        self.tune.add_group([(QLabel(_("Delay")), self.delay, None),
                             (None, hold, self.lbl_hold),
                             (QLabel(_("Cooldown")), self.cooldown, None)])
        self.tune.add_group([(QLabel(_("Area")), self.btn_area, None),
                             (None, match, self.lbl_number),
                             (QLabel(_("Check every")), self.interval, None)])
        self.tune.add_group([(None, self.ring_box, None), (None, self.chk_size, None),
                             (None, self.chk_quiet, None)])
        bv.addWidget(self.tune)
        bv.addSpacing(4)
        bv.addLayout(tune)          # Test, Duplicate, Delete: last, under everything
        for w in (self.delay, self.cooldown, self.hold, self.threshold):
            no_wheel(w)
            w.valueChanged.connect(self._on_numbers)
        self._show_mode_body()
        self._fill_sounds()
        fill_sources(self.where, self._mons, t.sources, self._default_label(),
                     _("Pick windows…"))
        if self._categories is not None:
            self.set_categories(self._categories)
        if self._default_ms is not None:
            self.set_default_interval(self._default_ms)
        self._set_tune_text()
        for control in (self.mode, self.where, self.btn_area, self.interval, self.sound,
                        self.pick, self.until, self.btn_test, self.btn_tune, self.btn_dup,
                        self.btn_del, self.delay,
                        self.cooldown, self.hold, self.threshold, self.below, self.cb_category):
            align_control(control, in_card=True)
        self.sound.setFixedWidth(self.sound.height())     # square, like the +
        self.tune.relayout()        # (the controls' sizes are their real ones now)

    def _show_title(self, _text: str = ""):
        self.title.setText(self.name.text().strip() or _("No name"))

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
        """Show the whole card, or just its header (or, beside the editor, show it
        there and stay a tile)."""
        if on and self.on_open is not None:
            self.on_open(self)
            on = False
        if self.pinned:
            on = True
        if on:
            self._build_body()
        self.body.setVisible(on)
        self._arrange(not on)
        if self.btn_open.isChecked() != on:
            self.btn_open.blockSignals(True)
            self.btn_open.setChecked(on)
            self.btn_open.blockSignals(False)
        icons.set_icon(self.btn_open, "fold_open" if on else "fold", "muted", "muted", size=16)
        self.btn_open.setToolTip(_("Close this trigger") if on else _("Open this trigger to change "
                                                                   "it"))

    def _arrange(self, tile: bool):
        """The header as a tile's (a small picture, the name over one line: how it's
        doing and what it plays, or what's wrong; the switch) or the open card's (the
        whole width: its pictures, the name to type in over what it does and plays,
        the live state and the switch)."""
        if tile == self._tile:
            return
        self._tile = tile
        top = self.top
        for widget in (self.pics, self.badge, self.name_line, self.names, self.live,
                       self.details, self.chk_on, self.btn_open):
            top.removeWidget(widget)
        for col in range(5):
            top.setColumnStretch(col, 0)
        size = TILE_THUMB if tile else THUMB
        self.strip.set_look(size, 1 if tile else STRIP_THUMBS)
        self.badge.setFixedSize(size + QSize(8, 8))
        self.btn_open.setFixedSize(20 if tile else 28, 28)
        middle = Qt.AlignVCenter
        top.addWidget(self.pics, 0, 0, 2, 1, Qt.AlignLeft | middle)
        top.addWidget(self.badge, 0, 0, 2, 1, Qt.AlignLeft | middle)
        if tile:
            top.addWidget(self.name_line, 0, 1, 1, 2, Qt.AlignBottom)
            top.addWidget(self.live, 1, 1, Qt.AlignLeft | Qt.AlignTop)
            top.addWidget(self.names, 1, 2, Qt.AlignTop)    # (_fit_lines moves it)
            top.addWidget(self.chk_on, 0, 3, 2, 1, middle)
            top.addWidget(self.btn_open, 0, 4, 2, 1, middle)
            top.addWidget(self.details, 2, 1, 1, 2)     # under the name, like its line
            top.setColumnStretch(2, 1)
            self.setCursor(Qt.PointingHandCursor)
            self.setToolTip(_("Click to open it, drag to move it"))
        else:
            top.addWidget(self.name_line, 0, 1, Qt.AlignBottom)
            top.addWidget(self.names, 1, 1, Qt.AlignTop)
            top.addWidget(self.live, 0, 2, 2, 1, middle)
            top.addWidget(self.chk_on, 0, 3, 2, 1, middle)
            top.addWidget(self.btn_open, 0, 4, 2, 1, middle)
            top.setColumnStretch(1, 1)
            self.unsetCursor()
            self.setToolTip("")
        self.title.setVisible(tile)
        self.name.setVisible(not tile)
        self.live.setAlignment((Qt.AlignLeft if tile else Qt.AlignRight) | middle)
        self.live.setContentsMargins(6 if tile else 0, 0, 0, 0)
        self._live_room = None          # sized again for its margins
        self._fit_live()
        self.details.setVisible(tile and self.advanced)
        self._fit_text()
        self._said = None
        self._fit_lines()
        self._narrow = None             # re-decided for the new layout
        self._fit_narrow()
        self._show_thumb()
        self.updateGeometry()

    def _fit_text(self):
        """A closed card keeps its name and its line to one line each, cut short with
        an …; with Show more info on it's as tall as it takes to read all of them."""
        whole = bool(self._tile) and self.advanced
        self.title.set_elide(not whole)
        self.state.set_elide(not whole)
        self.sound_summary.set_elide(bool(self._tile) and not whole)

    def _fit_lines(self):
        """A tile has one line under its name: what's wrong (or a note, or a flash)
        when there's something to say, else how it's doing and what it plays. Open,
        all of them."""
        say = bool(self.state.property("tone")) or self.btn_retarget.isVisibleTo(self)
        self.state.setVisible(not self._tile or say)
        self.sound_summary.setVisible(not self._tile or not say)
        self.live.setVisible(not self._tile or not say)
        if self._tile and say != self._said:    # under the name, where the state was
            self._said = say
            self.top.removeWidget(self.names)
            self.top.addWidget(self.names, 1, 1 if say else 2, 1, 2 if say else 1,
                               Qt.AlignTop)

    NARROW = 440        # px: below this the header's thumbnails go, for the rest to fit

    def changeEvent(self, ev):
        super().changeEvent(ev)
        if ev.type() in (QEvent.StyleChange, QEvent.FontChange):   # a theme was applied
            self._fit_name()
            if hasattr(self, "live"):   # (not yet while it's being made)
                self._live_shown = ""   # the dot's colour is the theme's
                self._live_room = None  # ...and its font
                self.show_score(self._score)    # (the score it had: a restyle isn't news)

    def showEvent(self, ev):
        super().showEvent(ev)
        self._fit_name()          # polished by now: the host's fonts are in

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self._fit_narrow()

    def _fit_narrow(self):
        narrow = not self._tile and self.width() < self.NARROW
        if narrow != self._narrow:
            self._narrow = narrow
            self._show_thumb()

    def _show_thumb(self):
        """The header's pictures (or the badge of a trigger without), unless the card
        is too narrow for them."""
        pics = self.t.uses_pictures
        self.pics.setVisible(pics and not self._narrow)
        self.badge.setVisible(not pics and not self._narrow)
        # the +: with no picture yet it's the slot the first one goes in; after that
        # it follows the open card's pictures, and is on a closed card's thumbnail
        some = bool(self.t.images)
        size = TILE_THUMB if self._tile else THUMB
        self.strip.setVisible(some)
        self.btn_add_pic.setVisible(not some or not self._tile)
        self.btn_add_pic.setFixedSize(28 if some else size.width() + 8, size.height() + 8)

    # ------------------------------------------------------------------ click, drag, drop
    MIME = "application/x-onionwatch-trigger"   # a card being dragged: its trigger's id

    def _on_header(self, pos) -> bool:
        return not self.pinned and (not self.is_open or pos.y() < self.body.y())

    def mousePressEvent(self, ev):
        """A press on the header (not on one of its controls): a click opens or closes
        the card, a drag moves it (to another place, or another category)."""
        if ev.button() == Qt.LeftButton and self._on_header(ev.position()):
            self._press = ev.position().toPoint()
            ev.accept()
            return
        self._press = None
        super().mousePressEvent(ev)

    def mouseMoveEvent(self, ev):
        if (self._press is not None and ev.buttons() & Qt.LeftButton
                and (ev.position().toPoint() - self._press).manhattanLength()
                >= QApplication.startDragDistance()):
            self._press = None
            self.drag()
            return
        super().mouseMoveEvent(ev)

    def mouseReleaseEvent(self, ev):
        if ev.button() == Qt.LeftButton and self._press is not None:
            self._press = None
            self.set_open(not self.is_open)
            ev.accept()
            return
        super().mouseReleaseEvent(ev)

    def drag(self):
        """Pick the card up: the category it's dropped on puts it there (categories)."""
        from PySide6.QtCore import QMimeData
        from PySide6.QtGui import QDrag, QPainter
        mime = QMimeData()
        mime.setData(self.MIME, self.t.id.encode())
        d = QDrag(self)
        d.setMimeData(mime)
        shot = self.grab(QRect(0, 0, self.width(), self.body.y() if self.is_open
                               else self.height()))
        if shot.width() > 320:
            shot = shot.scaledToWidth(320, Qt.SmoothTransformation)
        faded = QPixmap(shot.size())
        faded.fill(Qt.transparent)
        p = QPainter(faded)
        p.setOpacity(0.8)
        p.drawPixmap(0, 0, shot)
        p.end()
        d.setPixmap(faded)
        d.setHotSpot(QPoint(min(24, faded.width() // 2), min(24, faded.height() // 2)))
        d.exec(Qt.MoveAction)

    @staticmethod
    def picture_files(mime) -> list[str]:
        """The picture files in a drag (by their extension), if any."""
        exts = {e[1:] for e in PICTURE_EXTS.split()}
        return [u.toLocalFile() for u in mime.urls()
                if u.isLocalFile() and Path(u.toLocalFile()).suffix.lower() in exts]

    @staticmethod
    def dropped_picture(mime) -> QImage | None:
        """A picture itself in a drag (one dragged from a browser), if there is one."""
        if not mime.hasImage():
            return None
        img = QImage(mime.imageData())
        if img.isNull():
            return None
        set_web(img)
        return img

    def dragEnterEvent(self, ev):
        mime = ev.mimeData()
        if self.t.uses_pictures and (self.picture_files(mime) or mime.hasImage()):
            ev.acceptProposedAction()
            self.setStyleSheet(CARD_CSS + "QFrame#card { border-color:palette(highlight); }")
        else:
            ev.ignore()             # a card being moved: the category takes it

    def _unmark(self):
        self.setStyleSheet(CARD_CSS + (CARD_SELECTED if self.selected else CARD_HOVER))

    def set_selected(self, on: bool):
        """Mark it as the one the editor beside the list is showing."""
        if on != self.selected:
            self.selected = on
            self._unmark()

    def dragLeaveEvent(self, ev):
        self._unmark()
        super().dragLeaveEvent(ev)

    def dropEvent(self, ev):
        self._unmark()
        files = self.picture_files(ev.mimeData())
        if files:
            ev.acceptProposedAction()
            self.files_dropped.emit(self, files)
        elif (img := self.dropped_picture(ev.mimeData())) is not None:
            ev.acceptProposedAction()
            self.picture_dropped.emit(self, img)

    def _add_menu(self) -> QMenu:
        """The header's +: the ways to add a picture."""
        menu = QMenu(self)
        menu.addAction(icons.icon("crop"), _("Cut from window…"),
                       lambda: self.cut_wanted.emit(self))
        menu.addAction(icons.icon("plus"), _("Picture files…"),
                       lambda: self.pictures_wanted.emit(self))
        paste = menu.addAction(icons.icon("image"), _("Paste the copied picture"),
                               lambda: self.paste_wanted.emit(self))
        paste.setEnabled(not QApplication.clipboard().image().isNull())
        return menu

    def _show_add_menu(self):
        b = self.btn_add_pic if self.btn_add_pic.isVisible() else self.strip
        self._add_menu().exec(b.mapToGlobal(QPoint(0, b.height())))

    def _on_tune(self, on: bool):
        self.tune.setVisible(on)
        self.tune_div.setVisible(on)
        self.tune_text.setVisible(not on and bool(self.tune_text.text()))  # the controls say it

    def _set_tune_text(self):
        text = self._tune_summary()
        self.tune_text.setText(text)
        self.tune_text.setVisible(bool(text) and not self.btn_tune.isChecked())

    def _tune_summary(self) -> str:
        """What's been changed under More options, in a line: "Match 90 % · one size".
        Only what's off its default, and not what the card already says (ringing and
        the wait are in its header, its category is the section it's in): empty when
        nothing is."""
        t, d = self.t, Trigger(id="")
        parts = []
        if t.uses_pictures:     # (otherwise the level is in the When line)
            if round(t.number * 100) != round(d.threshold * 100):
                parts.append(_("Match {n} %", n=round(t.number * 100)))
            if not t.any_size:
                parts.append(_("exact size only"))
        if t.hold and t.mode != "still":
            parts.append(_("only if it lasts {s:g} s", s=t.hold))
        if t.delay and t.mode != "appear":      # (appear: the header says it)
            parts.append(_("delay {s:g} s", s=t.delay))
        if t.cooldown != d.cooldown:
            parts.append(_("cooldown {s:g} s", s=t.cooldown))
        if t.uses_pictures and t.region is not None:
            parts.append(_("part of the window"))
        if t.unfocused:
            parts.append(_("quiet while you're in the window"))
        return " · ".join(parts)

    # ------------------------------------------------------------------ view
    def _place(self, box: QWidget, main: bool):
        """Put a setting in the "When … in …" line (`main`: it's what the trigger is
        about, a bar's level) or under More options."""
        want = self._watch_row if main else self.tune
        if self._in[box] is not want:
            self._in[box].removeWidget(box)
            want.addWidget(box)
            self._in[box] = want
            box.show()

    def _show_mode(self):
        """Show the controls the trigger's mode uses, labelled for it."""
        t = self.t
        pics = t.uses_pictures
        self._show_thumb()
        if not pics:
            self.badge.setPixmap(icons.pixmap(
                {"change": "live", "still": "pause", "colour": "palette"}.get(t.mode, "triggers"),
                28, theme.T.get("muted", "#888888")))
        self.live.setToolTip(_("Right now: how well it matches (the best of its pictures)")
                             if pics else _("Right now, in the place closest to going off"))
        if self._built:
            self._show_mode_body()

    def _show_mode_body(self):
        """The editor's part of _show_mode."""
        t = self.t
        pics = t.uses_pictures
        self._place(self.match_box, not pics)          # a bar's level, how much changes
        self._place(self.hold_box, t.mode == "still")  # how long nothing may move
        self._place(self.btn_area, not pics)           # the bar, the area that changes
        self.chk_size.setVisible(pics)
        self.below.setVisible(t.mode == "colour")
        self.threshold.blockSignals(True)
        if pics:
            self.threshold.setRange(30, 99)
            self.threshold.setValue(round(t.threshold * 100))
        else:
            self.threshold.setRange(1, 99)
            self.threshold.setValue(round(t.level * 100))
        self.threshold.blockSignals(False)
        self.lbl_number.setText({"appear": _("Match"), "vanish": _("Match"),
                                 "change": _("Amount of change"),
                                 "still": _("Still if under"),
                                 "colour": _("Colour")}[t.mode])
        self.threshold.setToolTip({
            "appear": _("How alike the picture must be to count. Lower it if the picture is "
                        "missed, raise it if it plays by mistake — the live number helps."),
            "vanish": _("How alike the picture must be to count as there; it's gone once it "
                        "drops below this."),
            "change": _("How much of the area must change at once to count. Raise it if small "
                        "animations set it off."),
            "still": _("Anything moving less than this much of the area counts as nothing "
                       "happening."),
            "colour": _("How much of the area is the colour, as a share: a bar that's full "
                        "reads about 100 %, half empty about 50 %."),
        }[t.mode])
        self.lbl_hold.setText(_("Still for") if t.mode == "still" else _("Only if it lasts"))
        for lab in (self.lbl_number, self.lbl_hold):     # (the grid sizes them again)
            lab.setMinimumWidth(0)
            lab.setMaximumWidth(16777215)
        self.hold.setToolTip(
            _("How long nothing may change before it plays") if t.mode == "still" else
            _("It only counts once it has gone on this long, so a flicker or a loading screen "
              "doesn't set it off (0 = at once)"))
        self._label_area()
        self.tune.relayout()

    def _label_area(self):
        if not self._built:
            return
        t = self.t
        colour = t.mode == "colour"
        if colour:
            self.btn_area.setText(_("Bar and colour…") if t.region is None or not t.colour
                                  else _("Bar: set"))
            self.btn_area.setIcon(swatch(t.colour) if t.colour else QIcon())
            self.btn_area.setToolTip(_("Drag a box around the bar to measure and check its colour"))
        else:
            self.btn_area.setText(_("Whole window…") if t.region is None
                                  else _("Part of the window…"))
            self.btn_area.setIcon(QIcon())
            self.btn_area.setToolTip(_("Look in only part of each window: drag a box around it. "
                                       "Fewer false alarms, quicker checks."))

    def set_sounds(self, sounds: list[tuple[str, str]]):
        """The sounds on offer: fill the "+ Add sound" list and redraw the chips (once
        the editor is made: a closed tile only names them)."""
        self._sounds = list(sounds)
        names = dict(sounds)
        self.missing = [sid for sid in self.t.sounds if sid not in names]
        if self._built:
            self._fill_sounds()
        self._update_state()

    def _fill_sounds(self):
        sounds = self._sounds
        cb = self.sound
        cb.blockSignals(True)
        cb.clear()
        cb.addItem(icons.icon("plus"), "", ADD)     # what the closed box shows
        for sid, name in sounds:
            cb.addItem(name, sid)
        cb.insertSeparator(cb.count())
        cb.addItem(icons.icon("folder"), _("Choose a sound file…"), FILE)
        cb.setCurrentIndex(0)
        cb.view().setRowHidden(0, True)                # ...but not a choice in the list
        cb.blockSignals(False)
        names = dict(sounds)
        old, self.chips = self.chips, []
        for sid in self.t.sounds:
            self.chips.append(self._chip(names.get(sid, _("Removed sound")), sid,
                                         warn=sid not in names))
        self.pick.setVisible(len(self.t.sounds) > 1)
        self._layout_sounds()
        for chip in old:
            # off the card now: a chip waiting for the event loop to delete it is still
            # a child of the card, and one never laid out paints its frame at Qt's
            # default size over the card
            chip.setParent(None)
            chip.deleteLater()

    def _layout_sounds(self):
        """Put the sounds row's widgets back in order (the Flow layout has no insert)."""
        while self.sounds_row.count():
            self.sounds_row.takeAt(0)
        for w in (*self.chips, self.sound, self.pick):
            self.sounds_row.addWidget(w)
        self.sounds_row.invalidate()
        self.sounds_box._fit()

    def _chip(self, text: str, sid: str, warn: bool = False) -> QFrame:
        """A sound the trigger plays: its name (click to hear it) and a ✕."""
        chip = QFrame()
        chip.setObjectName("chip")
        chip.setFixedHeight(control_height(chip))
        h = QHBoxLayout(chip)
        h.setContentsMargins(4, 0, 2, 0)
        h.setSpacing(2)
        name = QPushButton(text if len(text) <= CHIP_CHARS else text[:CHIP_CHARS - 1] + "…")
        name.setObjectName("chipname")
        if warn:
            name.setToolTip(_("This sound file is gone — pick another"))
            name.setStyleSheet(f"color:{theme.status('warn')};")
        else:
            name.setToolTip(_("{text} — click to hear it", text=text))
            name.clicked.connect(lambda __=False, s=sid: self.hear.emit(s))
        h.addWidget(name)
        x = QPushButton("✕")
        x.setObjectName("chipstop")
        x.setFixedSize(22, 22)
        x.setToolTip(_("Take this sound off the trigger"))
        x.clicked.connect(lambda __=False, s=sid: self._remove_sound(s))
        h.addWidget(x)
        return chip

    def set_screens(self, mons: list[Monitor]):
        """Fill the "Look in" list with the screens there are now."""
        t = self.t
        self._mons = list(mons)
        self._screens = len(mons)
        if self._built:
            fill_sources(self.where, mons, t.sources, self._default_label(),
                         _("Pick windows…"))
        self.fallback = any(not 0 <= m < len(mons) for m in t.screens)
        self._update_state()

    def refresh_pictures(self):
        """Redraw the strip after the trigger's pictures changed."""
        t = self.t
        self.strip.set_paths(t.images)
        room = len(t.images) < MAX_PICTURES
        self.btn_add_pic.setEnabled(room)
        self.strip.set_can_add(room)
        self._show_thumb()
        self._update_state()

    def show_score(self, score: float | None):
        """The live state, a coloured dot and a word: Off, Waiting, Cooldown, Ready,
        Watching, or while watching how well it matches (bold once it would go off)."""
        self._score = score
        T = theme.T
        muted, accent = T.get("muted", "#888888"), T.get("accent", "#1fb6a6")
        bold, meter = False, None
        if not self.t.enabled:
            word, dot = _("Off"), T.get("off", muted)
        elif self.note:
            word, dot = _("Waiting"), theme.status("warn")
        elif self.watching and time.monotonic() < self.cooldown_until:
            word, dot = _("Cooldown"), theme.status("warn")
        elif score is None:
            word, dot = (_("Watching"), accent) if self.watching else (_("Ready"), muted)
        else:
            bold = screenwatch.verdict(self.t.mode, score, self.t.number, self.t.below) is True
            word = f"{max(0, round(score * 100))}%"
            dot = theme.status("ok") if bold else accent
            meter = (score, self.t.number, bold, goes_below(self.t))
        self.live.set_meter(meter)
        text = (f'<span style="color:{dot}">●</span>&nbsp;'
                + (f"<b>{word}</b>" if bold else word))
        if text != self._live_shown:        # every POLL_MS on every card: only on a change
            self._live_shown = text
            self.live.setText(text)
            self._live_score = len(word) <= 4 and word.endswith("%")    # 0% to 100%
            self._fit_live()

    def _fit_live(self):
        """The live state's label as big as its text, but a score always as big as
        the widest one ("100%", bold): a label that can't change size doesn't ask for
        a new layout, so a score changing every check never moves the card's other
        parts, or makes the page lay all its cards out again."""
        live = self.live
        if self._live_score:
            if self._live_room is None:     # (again after a theme or the margins change)
                self._live_room = live.meter_size()
            size = self._live_room
        else:
            size = live.sizeHint()
        if live.minimumSize() != size or live.maximumSize() != size:
            live.setFixedSize(size)

    def set_note(self, note: tuple[str, str] | None, waiting: WindowRef | None = None):
        """What watching says about this trigger's window or screen (not open,
        minimized, black), or None; `waiting`: the window it says isn't open."""
        if note != self.note or waiting != self.waiting:
            self.note = note
            self.waiting = waiting
            if not self._flash.isActive():
                self._update_state()

    def flash(self, text: str, ms: int = 2500, tone: str = "ok"):
        self.state.setText(text)
        theme.set_tone(self.state, tone)
        self._fit_lines()
        self._flash.start(ms)

    def _what(self) -> str:
        """When it plays, in words: "as soon as it shows up"…"""
        t = self.t
        n = round(t.number * 100)
        return {
            "appear": _("{s:g} s after it shows up", s=t.delay) if t.delay
            else _("as soon as it shows up"),
            "vanish": _("when its picture goes away"),
            "change": _("when something changes in its area"),
            "still": _("when nothing has moved for {s:g} s", s=t.hold),
            "colour": _("when the colour is below {n}% of the bar", n=n) if t.below
            else _("when the colour is above {n}% of the bar", n=n),
        }[t.mode]

    def _update_state(self):
        t = self.t
        n = len(t.sounds)
        retarget = False
        if t.uses_pictures and not t.images:
            text, tone = _("No picture yet — click + to add one"), "warn"
        elif t.mode == "colour" and (not t.colour or t.region is None):
            text, tone = _("Pick the bar to measure — Bar and colour…"), "warn"
        elif not n:
            text, tone = _("Pick the sound to play"), "warn"
        elif len(self.missing) == n:
            text, tone = (_("Its sound file is gone — pick another") if n == 1 else
                          _("Its sound files are gone — pick others")), "warn"
        elif self.fallback:
            text = (_("Screen {n} isn't plugged in, so it's looked for on the screen picked "
                      "below", n=t.monitor + 1) if self._screens > 1 else
                    _("Screen {n} isn't plugged in, so it's looked for on the main screen",
                      n=t.monitor + 1))
            tone = "warn"
        elif self.note is not None:
            text, tone = self.note
            retarget = self.waiting is not None
        else:
            # when, then what it does, each a whole phrase of its own (no English
            # glued into another language's sentence)
            parts = [capital(self._what())]
            if t.ring:
                parts.append(UNTILS[t.stop][1])
            elif n <= 1:
                parts.append(_("plays its sound once"))
            if n > 1:
                parts.append({"random": _("one of its {n} sounds at random", n=n),
                              "order": _("its {n} sounds in turn", n=n),
                              "all": _("all {n} sounds at once", n=n)}[t.pick])
            text = " · ".join(parts)
            if len(t.sources) > 1 or any(isinstance(s, WindowRef) and s.every
                                         for s in t.sources):
                place = places_label(t.sources) if len(t.sources) > 1 else t.sources[0].label
                text += _(", in {place}", place=place)
            tone = ""
        self.state.setText(text)
        theme.set_tone(self.state, tone)
        self.btn_retarget.setVisible(retarget)
        self._fit_lines()
        if self._built:
            self._set_tune_text()
        sounds = dict(self._sounds)
        self.sound_summary.setText("♪ " + (", ".join(sounds.get(s, _("Removed sound"))
                                                    for s in t.sounds) or _("Choose a sound")))
        where = places_label(t.sources) if t.sources else _("Default window / screen")
        interval = f"{t.interval_ms} ms" if t.interval_ms else _("default")
        self.details.setText(
            _("Look in: {where}\n{mode} · check every {interval}\nCooldown: {cooldown:g} s · "
              "{size}\nArea: {area} · {pictures}\n",
              where=where, mode=dict(MODES)[t.mode], interval=interval, cooldown=t.cooldown,
              size=_("Any size") if t.any_size else _("Original size"),
              area=_("custom") if t.region else _("whole view"),
              pictures=pictures(len(t.images)))
            + "\n".join(self.sound_details(sid) for sid in t.sounds))
        self.details.setVisible(self.advanced and bool(self._tile))

    def set_advanced(self, on: bool):
        self.advanced = on
        self.details.setVisible(on and bool(self._tile))
        self._fit_text()
        self.updateGeometry()

    # ------------------------------------------------------------------ edits
    def _on_interval(self, _index):
        self.t.interval_ms = self.interval.currentData()
        self._update_state()
        self.changed.emit(self)

    def _default_label(self) -> str:
        """The Look in list's first choice: the bottom bar's, by name."""
        return (_("Default ({place})", place=self.default_place) if self.default_place
                else _("Default"))

    def set_default_place(self, place: str):
        """Say where "Default" looks now (the Look in on the bottom bar)."""
        self.default_place = place
        if self._built and self.where.count() and self.where.itemData(0) == DEFAULT:
            self.where.setItemText(0, self._default_label())

    def set_default_interval(self, ms: int):
        """Say what "Default" is now (the speed picked under ⚙)."""
        self._default_ms = ms
        if self._built:
            self.interval.setItemText(0, _("Default ({ms} ms)", ms=ms))

    def _on_name(self):
        name = self.name.text().strip() or _("Trigger")
        if name != self.t.name:
            self.t.name = name
            self.changed.emit(self)

    def set_categories(self, names: list[str]):
        """The categories it can be put in (onionwatch.profiles), its own picked."""
        self._categories = list(names)
        if not self._built:
            return
        cb = self.cb_category
        cb.blockSignals(True)
        cb.clear()
        for n in names if self.t.category in names else [*names, self.t.category]:
            cb.addItem(profiles.label(n), n)
        cb.insertSeparator(cb.count())
        cb.addItem(_("New category…"), NEW_CATEGORY)
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
            self.flash(_("A trigger can play up to {n} sounds", n=MAX_SOUNDS), 4000, "warn")
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
        self.note = self.waiting = None
        self.set_screens(self._mons)
        self.changed.emit(self)

    def set_places(self, places: list):
        """Look in these windows and screens from now on."""
        self.t.sources = list(places)
        self.note = self.waiting = None
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
    trigger_added = Signal()            # a new trigger was made (not one brought back)
    ringing_changed = Signal()          # a sound started or stopped ringing
    history_changed = Signal()          # something went off (TriggersTab.history)
    playing_changed = Signal()          # a trigger's sound started, or was stopped
    _fired = Signal(str, object)        # from the watcher thread: trigger id, Hit
    _quieted = Signal(str)              # ...a ringing trigger's stop happened (Quieter)

    def __init__(self, host):
        super().__init__()
        self.host = host
        s = host.screen
        self.triggers: list[Trigger] = []
        saved = [d for k in ("triggers", "more_triggers")
                 for d in (s.get(k) if isinstance(s.get(k), list) else [])]
        # each trigger's category, kept apart too: an older version saves its
        # triggers back without one (see _store)
        cats = s.get("trigger_categories") if isinstance(s.get("trigger_categories"),
                                                          dict) else {}
        for d in saved:
            t = Trigger.from_raw(d)
            if (t is not None and len(self.triggers) < MAX_TRIGGERS
                    and all(x.id != t.id for x in self.triggers)):
                t.pending = ""      # an older Onion Board's sound import, long over
                if "category" not in d:
                    t.category = profiles.clean_name(cats.get(t.id, ""))
                self.triggers.append(t)
        self.rows: dict[str, TriggerRow] = {}   # the cards made so far (open categories')
        self.cooldowns: dict[str, float] = {}   # trigger id -> its cooldown's end (monotonic)
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
        self._wide: dict[str, bool] = {}                    # ...-> not cut from the game
        self._web_added = 0             # pictures from the web the last _add_pictures took
        self._tints: dict[str, np.ndarray | None] = {}      # ...-> its colours in brief
        self._colours: dict[str, np.ndarray | None] = {}    # ...-> its colours (RGB)
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
        self._sounds_shown: list | None = None  # the host's sounds the cards last got
        self._ring_how: dict[str, str] = {}           # ...-> what stops that ring (Trigger.stop)
        self._live: dict[str, float] = {}             # ...-> when it went off, while it plays
        self.pages = None               # the Triggers / Log pages it's shown in (ui.pages)
        self._input_poll = QTimer(self)
        self._input_poll.timeout.connect(self._check_input)
        self._hits: dict[str, screenwatch.Hit] = {}     # each trigger's latest, for alerts
        # what went off lately, newest last (kept in memory only, never saved)
        self.history: deque[Alert] = deque(maxlen=HISTORY)
        interval = s.get("interval_ms", screenwatch.DEFAULT_INTERVAL_MS)
        if interval not in INTERVALS_MS:
            interval = screenwatch.DEFAULT_INTERVAL_MS
        self.watcher.interval = interval / 1000
        share = s.get("cpu_share", screenwatch.CPU_SHARE)
        self.watcher.cpu_share = (share if share in screenwatch.CPU_SHARES
                                  else screenwatch.CPU_SHARE)
        most = s.get("max_detect", "off")
        self.watcher.max_detect = most if most in screenwatch.MAX_DETECTS else "off"
        self.watcher.color_hits = s.get("color_log") is not False
        self.watcher.default = self._saved_default()

        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(12)
        head, hv = card(_("Play a sound when something shows up in your game"),
                        _("Pick the game window, cut out the thing to watch for — a rare "
                          "spawn's name, a “queue ready” banner, a message — and choose the "
                          "sound. Onion Watch keeps looking at that window while you're "
                          "alt-tabbed into another game or away from the keyboard, and plays "
                          "the sound (or rings until you're back) the moment it appears. It "
                          "only looks: it never clicks, types or touches the game."))
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
        gb.setSpacing(4)
        self.cb_profile = WideCombo(min_width=150)
        self.cb_profile.setMaximumWidth(240)
        self.cb_profile.setToolTip(_("Which categories are on: your own switches (Manual), a "
                                     "profile's, or Automatic: the profile of the program that's "
                                     "open"))
        no_wheel(self.cb_profile)
        self.cb_profile.activated.connect(self._on_profile)
        gb.addWidget(labelled(_("Profile"), self.cb_profile), 0, Qt.AlignLeft)
        self.btn_categories = QPushButton()
        self.btn_categories.setAccessibleName(_("Categories"))
        self.btn_categories.setToolTip(_("Categories: give each one its own colours and a picture"))
        icons.set_icon(self.btn_categories, "palette")
        self.btn_categories.clicked.connect(lambda: self.edit_categories())
        align_control(self.btn_categories)
        gb.addWidget(self.btn_categories)
        self.lbl_counts = ElidedLabel()     # cut short rather than widen a narrow window
        self.lbl_counts.setObjectName("hint")
        self.lbl_counts.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        # one line over the list: the search box, always there, then (once there are
        # categories or profiles) the category to search and the profile in charge
        self.search_bar = QWidget()
        bar_layout = QVBoxLayout(self.search_bar)
        bar_layout.setContentsMargins(0, 0, 0, 0)
        bar_layout.setSpacing(8)
        self.search_line = QWidget()
        search_layout = QBoxLayout(QBoxLayout.LeftToRight, self.search_line)
        search_layout.setContentsMargins(0, 0, 0, 0)
        search_layout.setSpacing(8)
        bar_layout.addWidget(self.search_line)
        self.search_text = QLineEdit()
        self.search_text.setPlaceholderText(_("Search triggers"))
        self.search_text.setAccessibleName(_("Search triggers"))
        self.search_text.setToolTip(_("Find a trigger by name, category, window or sound "
                                      "(Ctrl+F). Esc clears it."))
        self.search_text.setClearButtonEnabled(True)
        self._search_icon = self.search_text.addAction(icons.icon("search", "muted"),
                                                       QLineEdit.LeadingPosition)
        align_control(self.search_text)
        self.search_text.setMinimumWidth(SEARCH_MIN)
        # + New trigger: one without a picture (it watches part of the window), right
        # where the list starts; a picture one is Cut picture… in the bar below
        self.btn_new = QPushButton(_("New trigger"))
        self.btn_new.setToolTip(_("A new trigger without a picture: it watches part of the "
                                  "window, and its card says what it waits for. To watch for "
                                  "a picture, use Cut picture… below."))
        icons.set_icon(self.btn_new, "plus")
        self.btn_new.clicked.connect(self.add_area_trigger)
        align_control(self.btn_new)
        search_layout.addWidget(self.btn_new)
        search_layout.addWidget(self.search_text, 3)
        self.search_scope = WideCombo(min_width=140)
        self.search_scope.setAccessibleName(_("Search category"))
        no_wheel(self.search_scope)
        align_control(self.search_scope)
        search_layout.addWidget(self.search_scope)
        self.btn_clear_search = QPushButton(_("Clear"))
        self.btn_clear_search.setToolTip(_("Show every trigger again (Esc)"))
        align_control(self.btn_clear_search)
        search_layout.addWidget(self.btn_clear_search)
        self.search_summary = hint_label("")
        self.search_summary.setWordWrap(False)
        search_layout.addWidget(self.search_summary)
        search_layout.addWidget(self.lbl_counts, 4)
        search_layout.addStretch(1)
        # how the cards look, and the profile: at the end of the line while the search
        # box keeps its room there, else on a line of their own under it (_fit_top)
        self.view_bar = QWidget()
        view_layout = QBoxLayout(QBoxLayout.LeftToRight, self.view_bar)
        view_layout.setContentsMargins(0, 0, 0, 0)
        view_layout.setSpacing(8)
        search_layout.addWidget(self.view_bar)
        self.cb_per_row = WideCombo(min_width=110)
        self.cb_per_row.setAccessibleName(_("View"))
        self.cb_per_row.setToolTip(_("List and editor: the triggers in a list, the one you pick "
                                     "beside it (in a window wide enough). Or cards side by side "
                                     "that open where they are: as many as fit at their usual "
                                     "size (Auto), or a number of your own."))
        self.cb_per_row.addItem(_("List and editor"), LIST_VIEW)
        self.cb_per_row.addItem(_("Auto per row"), 0)
        for k in range(1, MAX_PER_ROW + 1):
            self.cb_per_row.addItem(_("{k} per row", k=k), k)
        per_row = host.screen.get("cards_per_row")
        self.per_row = per_row if type(per_row) is int and 0 < per_row <= MAX_PER_ROW else 0
        # (a key of its own: an older version reads cards_per_row, and knows no list)
        self.list_view = host.screen.get("view") != "cards"
        self.cb_per_row.setCurrentIndex(self.cb_per_row.findData(
            LIST_VIEW if self.list_view else self.per_row))
        no_wheel(self.cb_per_row)
        align_control(self.cb_per_row)
        self.cb_per_row.activated.connect(self._on_view)
        view_layout.addWidget(self.cb_per_row)
        self.chk_advanced = QCheckBox(_("Show more info"))
        self.chk_advanced.setToolTip(_("Closed cards show more: every name in full, and each "
                                       "trigger's settings"))
        self.chk_advanced.setChecked(host.screen.get("advanced_cards") is True)
        self.chk_advanced.toggled.connect(self._on_advanced)
        view_layout.addWidget(self.chk_advanced)
        view_layout.addWidget(self.groupbar)
        # side by side only sets no minimum: below 600 px resizeEvent stacks it instead
        self.search_bar.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        v.addWidget(self.search_bar)
        self._search_ids: set[str] | None = None
        self.search_text.textChanged.connect(self._apply_search)
        self.search_scope.currentIndexChanged.connect(self._apply_search)
        self.btn_clear_search.clicked.connect(self.clear_search)
        self.find_shortcut = QShortcut(QKeySequence.Find, self)
        self.find_shortcut.activated.connect(self.show_search)
        self.close_search_shortcut = QShortcut(QKeySequence("Escape"), self.search_bar)
        self.close_search_shortcut.setContext(Qt.WidgetWithChildrenShortcut)
        self.close_search_shortcut.activated.connect(self.clear_search)
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
        self.list_layout.setSpacing(10)
        self.empty, ev = card()
        ev.setContentsMargins(16, 24, 16, 24)
        ev.setSpacing(10)
        self.hoot = owl.OwlWidget(96)   # waiting (sadly) for something to watch
        ev.addWidget(self.hoot, 0, Qt.AlignHCenter)
        hint = hint_label(_("No triggers yet. Pick your game window below, then click Cut "
                            "picture… and drag a box around the thing to watch for. Or "
                            "click + New trigger above for one without a picture."))
        hint.setAlignment(Qt.AlignCenter)
        ev.addWidget(hint)
        self.list_layout.addWidget(self.empty)
        self.no_results = hint_label(_("No matching triggers. Try another search or clear "
                                       "filters."))
        self.no_results.setAlignment(Qt.AlignCenter)
        self.no_results.hide()
        v.addWidget(self.no_results)
        self.list_layout.addStretch(1)
        self.scroll.setWidget(self.list)
        # a wide window: the list on the left, the trigger picked in it on the right
        # (_set_split). Narrower, the list is the whole width and a card opens in it
        self.body = QWidget()
        bh = QHBoxLayout(self.body)
        bh.setContentsMargins(0, 0, 0, 0)
        bh.setSpacing(10)
        bh.addWidget(self.scroll, 1)
        self.editor_scroll = QScrollArea()
        self.editor_scroll.setWidgetResizable(True)
        self.editor_scroll.setFrameShape(QFrame.NoFrame)
        self.editor_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.editor_pane = QWidget()
        ep = QVBoxLayout(self.editor_pane)
        ep.setContentsMargins(0, 0, 0, 0)
        ep.setSpacing(8)
        # nothing picked: match the empty list's card, with the hint in its middle
        self.editor_empty, ee = card()
        ee.setContentsMargins(32, 24, 32, 24)
        ee.setSpacing(10)
        ee.addStretch(1)
        mark = QLabel()
        icons.set_label_icon(mark, "triggers", size=40)
        ee.addWidget(mark, 0, Qt.AlignHCenter)
        hint = hint_label(_("Pick a trigger on the left to change it, or click Cut "
                            "picture… below to make one."))
        hint.setAlignment(Qt.AlignCenter)
        ee.addWidget(hint)
        ee.addStretch(1)
        ep.addWidget(self.editor_empty, 1)
        ep.addStretch(0)        # under a picked trigger: the gap (_empty_shown)
        self.editor_scroll.setWidget(self.editor_pane)
        self.editor_scroll.hide()
        bh.addWidget(self.editor_scroll, 1)
        self.editor: TriggerRow | None = None   # the trigger shown on the right
        self.split = False
        v.addWidget(self.body, 1)

        f = QFrame()
        f.setObjectName("transport")
        self.toolbar = f
        # roomier buttons than elsewhere: the bar's few big actions read as buttons, not a
        # packed strip (only padding: their colours stay the theme's)
        f.setStyleSheet("QPushButton { padding: 8px 16px; }")
        h = BarFlow(f, gap=18)   # room between them: at 10 the bar looked packed
        h.setContentsMargins(14, 10, 14, 10)
        self.btn_watch = QPushButton()
        self.btn_watch.setObjectName("live")
        self.btn_watch.setCheckable(True)
        self.btn_watch.setToolTip(_("Watch for the pictures above"))
        icons.set_icon(self.btn_watch, "triggers", checked_color="#ffffff")
        self.btn_watch.toggled.connect(self.set_watching)
        h.addWidget(self.btn_watch)
        self.btn_cut = QPushButton(_("Cut picture…"))
        self.btn_cut.setObjectName("primary")
        self.btn_cut.setToolTip(_("A new trigger: cut a picture out of the window (or screen) "
                                  "picked in Look in"))
        icons.set_icon(self.btn_cut, "crop", "on_accent")
        self.btn_cut.clicked.connect(self.add_from_cut)
        self.hoot.clicked.connect(lambda: self.btn_cut.setFocus(Qt.OtherFocusReason))
        h.addWidget(self.btn_cut)
        # the other ways to make a trigger, in one menu next to it: a picture file,
        # the copied picture, or none at all (a part of the window to watch)
        self.btn_add = QPushButton(_("Add"))
        self.btn_add.setToolTip(_("A new trigger from a picture file, from the picture you "
                                  "copied, or one without a picture"))
        icons.set_icon(self.btn_add, "plus")
        add_menu = QMenu(self.btn_add)
        self.act_add_file = add_menu.addAction(icons.icon("plus"), _("From a picture file…"),
                                               self.add_from_file)
        self.act_paste = add_menu.addAction(icons.icon("image"), _("Paste the copied picture"),
                                            self.add_from_clipboard)
        self.act_paste.setToolTip(_("Win+Shift+S cuts a piece of the screen to paste here"))
        add_menu.addAction(_("Without a picture…"), self.add_area_trigger)
        add_menu.setToolTipsVisible(True)

        def add_about_to_show():
            self.act_paste.setEnabled(not QApplication.clipboard().image().isNull())
        add_menu.aboutToShow.connect(add_about_to_show)
        self.btn_add.setMenu(add_menu)
        h.addWidget(self.btn_add)
        self.btn_more = QPushButton(_("More"))
        self.btn_more.setToolTip(_("What went off lately, saving or loading triggers, and "
                                   "recently deleted ones"))
        icons.set_icon(self.btn_more, "history")
        menu = QMenu(self.btn_more)
        menu.addAction(_("What went off…"), self.show_history)
        menu.addSeparator()
        menu.addAction(_("New category…"), self.new_category)
        self.act_categories = menu.addAction(icons.icon("palette"), _("Categories…"),
                                             lambda: self.edit_categories())
        menu.addAction(_("Profiles…"), self.edit_profiles)
        menu.addSeparator()
        self.act_export = menu.addAction(_("Save triggers to a file…"), self.export_triggers)
        menu.addAction(_("Load triggers from a file…"), self.import_triggers)
        menu.addSeparator()
        self.act_bin = menu.addAction(icons.icon("trash"), _("Recently deleted…"),
                                      self.show_deleted)

        def about_to_show():
            self.act_export.setEnabled(bool(self.triggers))
            self.act_categories.setEnabled(self._named_categories())
            n = len(self._bin())
            self.act_bin.setText(_("Recently deleted ({n})…", n=n) if n else _("Recently deleted…"))
        menu.aboutToShow.connect(about_to_show)
        self.btn_more.setMenu(menu)
        h.addWidget(self.btn_more)
        self.cb_where = WideCombo(min_width=140)
        # as wide as "Screen 1: 1920×1080" when there's room (at 150 it always read
        # "Screen 1: 1…"); a long window title stays in the popup and the tooltip
        self.cb_where.setMaximumWidth(260)
        self.cb_where.setToolTip(_("Where triggers set to “Default” look: your game's "
                                   "window, or a whole screen"))
        self.cb_where.activated.connect(self._on_where)
        no_wheel(self.cb_where)
        # beside the buttons when there's room (the list gives way first), on a line of
        # its own when not. How often triggers on "Default" are checked is under ⚙
        # (set_default_interval): each card has its own "Check every" too
        self.look = labelled(_("Look in"), self.cb_where)
        h.addWidget(self.look)
        # the watching settings (check speed, processor use), then last the ⓘ and the
        # bin (only while it holds something)
        self.btn_settings = QPushButton()
        self.btn_settings.setFixedWidth(34)
        self.btn_settings.setToolTip(_("Watching settings: how often triggers on Default are "
                                       "checked, and how much of your processor it may use"))
        self.btn_settings.setAccessibleName(_("Watching settings"))
        icons.set_icon(self.btn_settings, "settings")
        self.btn_settings.clicked.connect(self.show_watching)
        h.addWidget(self.btn_settings)
        if not callable(getattr(host, "tab_info", None)):
            self.btn_info = QPushButton(_("Help"))
            self.btn_info.setObjectName("small")
            self.btn_info.setCursor(Qt.PointingHandCursor)
            self.btn_info.clicked.connect(
                lambda: QMessageBox.information(self, *self.info))
            self.btn_info.setParent(self)
            self.btn_info.hide()
            menu.addSeparator()
            menu.addAction(_("Help…"), self.btn_info.click)
        self.btn_bin = QPushButton()     # the bin's icon and count (_label_bin)
        icons.set_icon(self.btn_bin, "trash")
        self.btn_bin.clicked.connect(self.show_deleted)
        h.addWidget(self.btn_bin)
        for control in (self.btn_watch, self.btn_cut, self.btn_add, self.btn_more,
                        self.cb_where, self.btn_settings, self.btn_bin):
            align_control(control)
        if hasattr(self, "btn_info"):
            align_control(self.btn_info)
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

    # ------------------------------------------------------------------ search
    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit_top()
        self._set_split(self.list_view and self.width() >= SPLIT_MIN)

    # ------------------------------------------------------------------ list and editor
    def _set_split(self, on: bool):
        """The list on the left and the picked trigger's editor on the right (a wide
        window), or the list alone with cards opening in it."""
        if on == self.split:
            return
        self.split = on
        self.scroll.setMaximumWidth(LIST_WIDTH if on else 16777215)
        self.scroll.setMinimumWidth(LIST_WIDTH if on else 0)
        self.body.layout().setStretch(0, 0 if on else 1)
        self.editor_scroll.setVisible(on)
        picked = self.editor.t.id if self.editor is not None else None
        for row in self.rows.values():
            row.on_open = self._select if on else None
            if on and row.is_open:
                picked = picked or row.t.id
                row.set_open(False)
        if on:
            if picked is None and self.triggers:
                picked = self.triggers[0].id
            if picked in self.rows:
                self._select(self.rows[picked])
        else:
            self._drop_editor()
            if picked in self.rows:
                self.rows[picked].set_open(True)

    def _select(self, row: TriggerRow):
        """Show `row`'s trigger in the editor on the right."""
        t = row.t
        if self.editor is not None and self.editor.t is t:
            return
        self._drop_editor()
        ed = TriggerRow(t, self.host.sounds(), self._mons, open_=True,
                        parent=self.editor_pane)
        ed.pinned = True
        ed.btn_open.hide()
        ed.setStyleSheet(CARD_CSS)
        self._wire(ed)
        ed.set_categories(self.groups.names())
        ed.set_default_interval(self.default_interval)
        ed.set_default_place(places_label([self.watcher.default]))
        ed.set_open(True)
        ed.watching = row.watching
        ed.show_score(row._score)       # what its tile shows, until the next check
        self.editor = ed
        self.editor_pane.layout().insertWidget(0, ed)
        self._empty_shown(False)
        for r in self.rows.values():
            r.set_selected(r.t is t)

    def _drop_editor(self):
        ed, self.editor = self.editor, None
        if ed is not None:
            self.editor_pane.layout().removeWidget(ed)
            ed.setParent(None)
            ed.deleteLater()
        for r in self.rows.values():
            r.set_selected(False)
        self._empty_shown(True)

    def _empty_shown(self, on: bool):
        """The nothing-picked box, filling the pane; or the gap under a picked trigger."""
        ep = self.editor_pane.layout()
        ep.setStretch(ep.count() - 1, 0 if on else 1)
        self.editor_empty.setVisible(on)

    def _cards(self) -> list[TriggerRow]:
        """Every card made: the list's, and the editor."""
        return [*self.rows.values(), *([self.editor] if self.editor is not None else [])]

    def _views(self, tid: str) -> list[TriggerRow]:
        """The cards showing trigger `tid`: its one in the list, and the editor."""
        return [r for r in (self.rows.get(tid), self.editor)
                if r is not None and r.t.id == tid]

    def _sync_views(self):
        """After an edit, the list's card and the editor show the same trigger: the
        one that wasn't edited catches up."""
        ed = self.editor
        if ed is None:
            return
        tile = self.rows.get(ed.t.id)
        t = ed.t
        for r in (tile, ed):
            if r is None:
                continue
            if r.name.text() != t.name and not r.name.hasFocus():
                r.name.setText(t.name)
            if r.chk_on.isChecked() != t.enabled:
                r.chk_on.blockSignals(True)
                r.chk_on.setChecked(t.enabled)
                r.chk_on.blockSignals(False)
            r.refresh_pictures()
        if ed.cb_category.currentData() != t.category:     # moved by its tile, a drag...
            ed.set_categories(self.groups.names())
        if tile is not None:
            tile.set_sounds(self.host.sounds())
            tile._show_mode()
            tile._update_state()

    def _fit_top(self):
        """The line over the list: stacked in a narrow window, and only the parts
        there's a use for (the category to search and the profile once there are
        categories, Clear and the count while searching, else what's on)."""
        width = self.width()
        stacked = width < 600
        self.search_line.layout().setDirection(
            QBoxLayout.TopToBottom if stacked else QBoxLayout.LeftToRight)
        self.search_text.setMaximumWidth(16777215 if stacked else 360)
        grouped = self._grouped()
        active = self._search_ids is not None
        self.search_scope.setVisible(grouped)
        self.btn_clear_search.setVisible(active)
        self.search_summary.setVisible(active)
        self.lbl_counts.setVisible(grouped and not active and not stacked)
        self.groupbar.setVisible(grouped)
        self.btn_categories.setEnabled(self._named_categories())
        # the view's controls share the search's line only while they, the search box
        # (SEARCH_ROOM) and the counts' first part fit there at their usual widths (a
        # layout short of room squeezes the search box first); else they go under it,
        # one above the other when even a line of their own is too narrow for them
        line = [self.search_scope, self.btn_clear_search, self.search_summary]
        view = [self.cb_per_row, self.chk_advanced, self.groupbar]
        counts = 0 if self.lbl_counts.isHidden() else self.lbl_counts.least_width() + 8
        wanted = SEARCH_ROOM + 8 + counts + _row_width(line + view, least=False)
        one_line = not stacked and width >= wanted
        self.view_bar.layout().setDirection(
            QBoxLayout.TopToBottom if stacked or width < _row_width(view)
            else QBoxLayout.LeftToRight)
        self.search_text.setMinimumWidth(SEARCH_ROOM if one_line else SEARCH_MIN)
        target = self.search_line.layout() if one_line else self.search_bar.layout()
        if self.view_bar.parentWidget() is not target.parentWidget():
            self.view_bar.parentWidget().layout().removeWidget(self.view_bar)
            target.addWidget(self.view_bar)
        target.setAlignment(self.view_bar, Qt.Alignment() if stacked else Qt.AlignLeft)

    def _on_view(self, i: int):
        n = self.cb_per_row.itemData(i)
        if n == LIST_VIEW:
            self.set_list_view(True)
        else:
            self.set_list_view(False)
            self.set_per_row(n)

    def set_list_view(self, on: bool):
        """The list beside an editor, or cards that open where they are; kept for the
        next start."""
        self.list_view = on
        self.host.screen["view"] = "list" if on else "cards"
        self.host.save()
        want = self.cb_per_row.findData(LIST_VIEW if on else self.per_row)
        if self.cb_per_row.currentIndex() != want:
            self.cb_per_row.setCurrentIndex(want)
        self._set_split(on and self.width() >= SPLIT_MIN)

    def set_per_row(self, n: int):
        """`n` closed cards to a line (0: as many as fit), kept for the next start."""
        self.per_row = n if 0 < n <= MAX_PER_ROW else 0
        self.host.screen["cards_per_row"] = self.per_row
        self.host.save()
        want = self.cb_per_row.findData(LIST_VIEW if self.list_view else self.per_row)
        if self.cb_per_row.currentIndex() != want:
            self.cb_per_row.setCurrentIndex(want)
        for sec in self.sections.values():
            sec.body_layout.set_per_row(self.per_row)
            sec.body._fit()

    def show_search(self, category: str | None = None):
        """Put the cursor in the search box (Ctrl+F), to search `category` if given."""
        if category is not None:
            self.search_scope.setCurrentIndex(max(0, self.search_scope.findData(category)))
        self.search_text.setFocus()
        self.search_text.selectAll()

    def clear_search(self):
        self.search_text.blockSignals(True)
        self.search_scope.blockSignals(True)
        self.search_text.clear()
        self.search_scope.setCurrentIndex(0)
        self.search_text.blockSignals(False)
        self.search_scope.blockSignals(False)
        self._apply_search()

    def _search_categories(self):
        scope = self.search_scope.currentData()
        self.search_scope.blockSignals(True)
        self.search_scope.clear()
        self.search_scope.addItem(_("All categories"), None)
        for name in self.groups.names():
            self.search_scope.addItem(profiles.label(name), name)
        self.search_scope.setCurrentIndex(max(0, self.search_scope.findData(scope)))
        self.search_scope.blockSignals(False)

    def _apply_search(self, *__):
        """Filter model data, including unbuilt/folded cards, without changing watching."""
        words = self.search_text.text().casefold().split()
        scope = self.search_scope.currentData()
        active = bool(words) or scope is not None
        was_active = self._search_ids is not None
        sounds = dict(self.host.sounds())
        self._search_ids = set() if active else None
        if active:
            for t in self.triggers:
                text = " ".join([t.name, profiles.label(t.category),
                                 *[f"{s.label} {s.exe}"
                                   for s in (t.sources or [self.watcher.default])
                                   if isinstance(s, WindowRef)],
                                 *[sounds.get(s, s) for s in t.sounds]]).casefold()
                if (scope is None or t.category == scope) and all(w in text for w in words):
                    self._search_ids.add(t.id)
        for name, sec in self.sections.items():
            matches = any(t.category == name and self._matches_search(t) for t in self.triggers)
            sec.setVisible(matches if active else True)
            sec.set_open(matches if active else self.groups.find(name).open)
            if sec.is_open and (active or was_active):
                self._build(sec)
        # a card shown in a shown grid lays the whole grid out there and then, so with
        # hundreds of cards to show, clearing a search took a quarter of a second. A
        # grid with several to show hides while they're shown: shown again, it's laid
        # out once
        change = [(row, self._matches_search(row.t)) for row in self.rows.values()]
        change = [(row, on) for row, on in change if row.isHidden() == on]
        showing: dict[QWidget, int] = {}
        for row, on in change:
            body = row.parentWidget()
            if on and body is not None and not body.isHidden():
                showing[body] = showing.get(body, 0) + 1
        focus = QApplication.focusWidget()      # (hidden, it would lose the cursor)
        bodies = [body for body, n in showing.items()
                  if n > 1 and not (focus and body.isAncestorOf(focus))]
        for body in bodies:
            body.hide()
        for row, on in change:
            row.setVisible(on)
        for body in bodies:
            body.show()
        self.no_results.setVisible(active and not self._search_ids)
        self.empty.setVisible(not self.triggers and not active)
        self.search_summary.setText(
            _("{n} of {n2}", n=len(self._search_ids), n2=len(self.triggers)) if active else "")
        self.search_summary.setToolTip(_("Matching triggers; watching is unchanged"))
        self._fit_top()

    def _matches_search(self, trigger: Trigger) -> bool:
        return self._search_ids is None or trigger.id in self._search_ids

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
        self._put_default(src)
        self.host.save()
        self._fill_sources()

    def _put_default(self, src: int | WindowRef):
        self.watcher.set_default(src)
        if isinstance(src, WindowRef):
            self.host.screen["window"] = src.to_raw()
        else:
            self.host.screen["window"] = None
            self.host.screen["monitor"] = src

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
        usage.used("pick-windows")
        places = self.pick_places(row.t.sources)
        if places:
            row.set_places(places)

    def change_window(self, old: WindowRef) -> bool:
        """"Change window…" on a card waiting for `old`: pick another window, and
        everything that looked in `old` looks in it instead (retarget_window)."""
        new = self.pick_window(old)
        if new is None or new == old:
            return False
        return self.retarget_window(old, new)

    def retarget_window(self, old: WindowRef, new: WindowRef) -> bool:
        """Swap the window `old` for `new` everywhere at once: the default Look in,
        every trigger's places (copies and "every copy" ones too, see retarget), and
        `old`'s program for `new`'s in the profiles. Saved once, with an Undo bar.
        False if nothing used `old`."""
        before_default = self.watcher.default
        before_sources = {t.id: list(t.sources) for t in self.triggers}
        before_apps = {p.id: list(p.apps) for p in self.groups.profiles}
        default = retarget(before_default, old, new)
        moved = []
        for t in self.triggers:
            places = retargeted(t.sources, old, new)
            if places != t.sources:
                t.sources = places
                moved.append(t)
        apps = bool(old.exe and new.exe) and self.groups.replace_app(old.exe, new.exe)
        if default == before_default and not moved and not apps:
            return False
        ids = {t.id for t in moved}
        before_sources = {k: v for k, v in before_sources.items() if k in ids}
        before_apps = {p.id: before_apps[p.id] for p in self.groups.profiles
                       if p.id in before_apps and p.apps != before_apps[p.id]}
        if default != before_default:
            self._put_default(default)

        def refresh():
            for t in self.triggers:
                row = self.rows.get(t.id)
                if row is not None and t.id in ids:
                    row.note = row.waiting = None
                    row.set_screens(self._mons)
            self._fill_sources()
            self._update_app_timer()
            self._store()
        refresh()

        def undo():
            if self.watcher.default == default:
                self._put_default(before_default)
            for t in self.triggers:
                if t.id in ids:
                    t.sources = before_sources[t.id]
            for p in self.groups.profiles:
                if p.id in before_apps:
                    p.apps = before_apps[p.id]
            refresh()
        what = [triggers(len(moved))] if moved else []
        if default != before_default:
            what.append(_("the default Look in"))
        if apps:
            what.append(_("profiles"))
        self.undo_bar.show_for(_("Moved {what} to {place}", what=", ".join(what),
                                 place=new.label), undo,
                               tip=_("Look in {place} again", place=old.label))
        return True

    # ------------------------------------------------------------------ watching
    @property
    def pictures(self) -> Path:
        """The folder the trigger pictures are kept in."""
        return pictures_dir(self.host)

    def showEvent(self, ev):
        super().showEvent(ev)
        self.sounds_changed()     # the host's sounds may have been renamed meanwhile
        self._fill_sources()      # ...and screens plugged in or out
        if self.poll.isActive() and self._on_screen():
            self._show_poll()     # what watching found while it was hidden

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
            usage.used("watching")
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
            for row in self._cards():
                row.watching = False    # else the card keeps saying "Watching"
                row.show_score(None)
                row.set_note(None)
        if remember:
            self.host.screen["on"] = on
            self.host.save()
        self._label_watch()
        self._show_warning()
        self.active_changed.emit(on)

    def _label_watch(self):
        text = _("Watching") if self.is_active() else _("Start watching")
        self.btn_watch.setProperty("full_text", text)   # a host that shows it icon only
        if not self.btn_watch.property("compact"):       # reads it back when there's room
            self.btn_watch.setText(text)

    def fit_parts(self) -> dict[str, QWidget]:
        """What a host may hide, or show as an icon only, when its window gets small:
        "hint" (the explanation at the top), the buttons "watch", "cut" and "add"
        (icon only). Pasting is in the Add menu now, and the check speed under ⚙: a
        host asking for "paste" or "interval_label" gets nothing, and leaves it be."""
        return {"hint": self.hint, "watch": self.btn_watch, "cut": self.btn_cut,
                "add": self.btn_add}

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
        for row in self._views(tid):
            row.flash(_("Stopped ringing — you're back"), 4000)
        self.ringing_changed.emit()

    def retheme(self):
        """The theme changed (onionwatch.theme.T has the new colours): redraw what
        was coloured by hand."""
        icons.retheme()
        self._search_icon.setIcon(icons.icon("search", "muted"))
        self.undo_bar.restyle()
        for sec in self.sections.values():
            sec.retheme()             # category tabs fade into the new panel colour
        self.sounds_changed(force=True)   # the chips of sounds that are gone
        for row in self._cards():
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
                                     interval_ms=t.interval_ms,
                                     cuts=[self._cuts.get(path) for _p, path in got],
                                     wide=[self._wide.get(path, False) for _p, path in got],
                                     tints=[self._tints.get(path) for _p, path in got],
                                     colours=[self._colours.get(path) for _p, path in got]))
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
            self._wide[path] = is_web(img)
            self._tints[path] = picture_tint(img)
            self._colours[path] = picture_rgb(img)
        return pic

    def _playable(self, t: Trigger) -> list[str]:
        """The trigger's sounds that are still in the library, in its order."""
        have = {sid for sid, _name in self.host.sounds()}
        return [sid for sid in t.sounds if sid in have]

    def _on_fired(self, tid: str, hit: screenwatch.Hit | None = None):
        t = next((t for t in self.triggers if t.id == tid), None)
        if t is None or not self.is_active() or not self._playable(t):
            return
        self.cooldowns[tid] = time.monotonic() + t.cooldown
        for row in self._views(tid):
            row.cooldown_until = time.monotonic() + t.cooldown
        if hit is not None:
            # where it went off is all that's needed later (_watch_ring, _in): not the
            # picture of the window, which the history keeps small
            self._hits[tid] = dataclasses.replace(hit, frame=None)
            self.history.append(Alert.of(t, hit, self.place_name(hit.source)))
            self.history_changed.emit()
        gen = self._gen
        if t.delay > 0:
            for row in self._views(tid):
                place = self._in(tid)
                row.flash(_("Seen in {place}! Playing in {s:g} s…", place=place, s=t.delay)
                          if place else _("Seen! Playing in {s:g} s…", s=t.delay),
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
            for row in self._views(tid):
                place = self._in(tid)
                if place:
                    text = (_("Ringing in {place}!", place=place) if t.ring
                            else _("Played in {place}!", place=place))
                else:
                    text = _("Ringing!") if t.ring else _("Played!")
                row.flash(text, 4000)
            if t.ring:
                self._watch_ring(t)
            self._live[t.id] = time.monotonic()
            self.playing_changed.emit()
            usage.used("went-off")
            self.fired.emit(t)

    def place_name(self, place) -> str:
        """A window or screen as the alerts name it: "Game (copy 2)", "screen 2"."""
        return source_label(place, self._mons)

    def _in(self, tid: str) -> str:
        """"Game (copy 2)" for a trigger looking in more than one place (else ""):
        which one it went off in."""
        hit = self._hits.get(tid)
        places = self.watcher.where.get(tid, ())
        if hit is None or len(places) < 2:
            return ""
        return self.place_name(hit.source)

    def alert_text(self, t: Trigger) -> str:
        """The words of a notification for `t` going off: what happened and where."""
        where = self._in(t.id)
        what = {"appear": _("It just showed up"), "vanish": _("It went away"),
                "change": _("Something changed"), "still": _("Nothing has moved for a while"),
                "colour": _("The bar ran low") if t.below else _("The bar filled up")}[t.mode]
        what = _("{what} in {place}.", what=what, place=where) if where else what + "."
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
            for __ in range(n):
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
        heavy = w.gap > HEAVY_GAP and w.gap > w.interval * 1.05
        if not heavy:
            self._heavy_since = None
        elif self._heavy_since is None:
            self._heavy_since = time.monotonic()
        # the rest is only for the eye: nothing while the tab is hidden or its window
        # minimised (showEvent catches up, and so does the next check after a restore)
        if self._on_screen():
            self._show_poll()

    def _on_screen(self) -> bool:
        return self.isVisible() and not self.window().isMinimized()

    def _show_poll(self):
        """What watching says on each card (notes, live scores) and at the bottom."""
        w = self.watcher
        for row in self._cards():
            row.set_note(*self._first_note(w.where.get(row.t.id, ())))
        if self._gap_text() != self._gap_shown:
            self._refresh_counts()
        for row in self._cards():
            row.watching = w.running and self.is_on(row.t)
            row.show_score(w.scores.get(row.t.id))
        self._show_warning()

    def _first_note(self, places) -> tuple[tuple[str, str] | None, WindowRef | None]:
        """What to say on a card about the places it's looked in: the first problem,
        and the window it's about when that one isn't open (for "Change window…")."""
        for src in places:
            note = self._note(src)
            if note is not None:
                waiting = src if isinstance(src, WindowRef) and src in self.watcher.failed \
                    else None
                return note, waiting
        return None, None

    def _note(self, src) -> tuple[str, str] | None:
        """What to say on a card about the window / screen it's looked for in."""
        w = self.watcher
        if src is None:
            return None
        name = source_label(src, self._mons)
        if src in w.failed:
            if isinstance(src, WindowRef):
                return _("Waiting for {name} to open", name=name), "warn"
            return _("Screen {n} can't be captured — waiting for it", n=src + 1), "warn"
        if src in w.minimized:
            return _("{name} is minimized, so it can't be seen — restore it (covering it "
                     "with other windows is fine)", name=name), "warn"
        if src in w.unseen:
            if isinstance(src, WindowRef):
                return _("{name} can't be captured: nothing comes out of it. Pick its "
                         "screen under Look in instead.", name=name), "warn"
            return _("Screen {n} gives no picture — waiting for one", n=src + 1), "warn"
        if src in w.blacked:
            if isinstance(src, WindowRef):
                return _("{name} comes out black. Some games can only be seen on the "
                         "screen: pick its screen under Look in instead.", name=name), "warn"
            return _("The screen looks all black. If the game is in exclusive fullscreen, "
                     "set it to Borderless or Windowed."), "warn"
        return None

    def _show_warning(self):
        w, why = self.watcher, ""
        ok, unsupported = screenwatch.supported()
        if not ok:
            why = unsupported
        elif w.error:
            why = _("Watching stopped: {error}", error=w.error)
        elif self.is_active() and w.lost:
            why = _("Waiting for the screen to come back. A game switching to or from "
                    "fullscreen does this for a moment.")
        elif self.is_active() and not w.scores and not w.failed and not any(
                self.is_on(t) and self.ready(t) and t.sounds for t in self.triggers):
            if any(t.enabled and self.ready(t) and t.sounds for t in self.triggers):
                why = _("Nothing to watch for: the triggers that could go off are all in "
                        "categories that are off now.")
            else:
                why = _("Nothing to watch for yet: each trigger needs a sound, and a "
                        "picture (or its bar) to look for.")
        elif (self.is_active() and self._heavy_since is not None
              and time.monotonic() - self._heavy_since >= HEAVY_FOR):
            n = self._counts()[2]
            why = ngettext("Each trigger is checked only every {s:.1f} s: {n} picture is on, "
                           "more than this computer looks for in {share} of its processor. "
                           "Let it use more under ⚙, switch off a category, or give triggers "
                           "an Area to look in, to check more often.",
                           "Each trigger is checked only every {s:.1f} s: {n} pictures are on, "
                           "more than this computer looks for in {share} of its processor. "
                           "Let it use more under ⚙, switch off a category, or give triggers "
                           "an Area to look in, to check more often.",
                           n, s=w.gap, share=share_label(w.cpu_share))
        self.warn.setText(why)
        self.warn.setVisible(bool(why))

    @property
    def default_interval(self) -> int:
        """How often (ms) triggers left on "Default" are checked."""
        return round(self.watcher.interval * 1000)

    def set_default_interval(self, ms: int):
        """The check speed of triggers on "Default" (Watching settings), kept, and
        shown on every card's "Check every"."""
        if ms not in INTERVALS_MS:
            return
        self.watcher.interval = ms / 1000
        self.host.screen["interval_ms"] = ms
        self.host.save()
        for row in self._cards():
            row.set_default_interval(ms)

    def _on_advanced(self, on: bool):
        self.host.screen["advanced_cards"] = on
        self.host.save()
        for row in self.rows.values():
            row.set_advanced(on)

    def _fill_sources(self):
        """List the screens again: the "Look in" at the bottom (the default) and each
        card's own. A change while watching is passed on to the watcher."""
        mons = screenwatch.monitors()
        d = self.watcher.default
        fill_sources(self.cb_where, mons, [d])
        place = places_label([d])
        for row in self._cards():
            row.set_default_place(place)
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
        sec.add_wanted.connect(self._category_add_menu)
        sec.search_wanted.connect(self.show_search)
        sec.body_layout.set_per_row(self.per_row)
        sec.card_dropped.connect(self.reorder)
        sec.drag_at.connect(self._scroll_for_drag)
        sec.set_look(self.groups.find(name), self.host.data_dir)
        self.sections[name] = sec
        return sec

    def _named_categories(self) -> bool:
        """There's a category of the user's own (the Categories window has a use)."""
        return any(n != profiles.UNCATEGORISED for n in self.groups.names())

    def edit_categories(self, start: str = ""):
        """The Categories window: each category's colours and picture."""
        if not start:
            start = next((n for n in self.groups.names() if n != profiles.UNCATEGORISED),
                         "")
        dlg = CategoriesDialog(self, self.groups.categories, self.host.data_dir, start)
        if dlg.exec():
            self.set_category_looks(dlg.result)

    def set_category_looks(self, looks: dict):
        """Give categories their looks (name -> Category.full_look(); a category
        left out keeps its own) and show them."""
        for c in self.groups.categories:
            if c.name in looks:
                c.set_full_look(looks[c.name])
        for name, sec in self.sections.items():
            sec.set_look(self.groups.find(name), self.host.data_dir)
        self._save_groups()

    def reorder(self, tid: str, category: str, before: str | None = None):
        """A card was dragged: put its trigger in `category`, just before trigger
        `before` (None: after the category's last). The list's order is what's saved,
        so it's kept, also by older versions."""
        t = next((x for x in self.triggers if x.id == tid), None)
        if t is None or before == tid:
            return
        cat = profiles.clean_name(category)
        rest = [x for x in self.triggers if x is not t]
        at = next((i for i, x in enumerate(rest) if x.id == before and x.category == cat),
                  None)
        if at is None:      # after the category's last, or at the end
            at = max((i + 1 for i, x in enumerate(rest) if x.category == cat),
                     default=len(rest))
        if rest[:at] + [t] + rest[at:] == self.triggers and t.category == cat:
            return          # dropped where it already was
        self.triggers[:] = rest[:at] + [t] + rest[at:]
        if t.category != cat:
            self.move_trigger(t, cat)       # places its card, and saves
            return
        sec = self.sections.get(cat)
        if sec is not None and t.id in self.rows:
            self._place_row(t, sec)
        self._store()

    def _scroll_for_drag(self, at: QPoint):
        """A card dragged near the top or bottom of the list scrolls it."""
        vp = self.scroll.viewport()
        y = vp.mapFromGlobal(at).y()
        bar = self.scroll.verticalScrollBar()
        edge = 40
        if y < edge:
            bar.setValue(bar.value() - (edge - y))
        elif y > vp.height() - edge:
            bar.setValue(bar.value() + (y - vp.height() + edge))

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
        self._refresh_switches()
        self._refresh_counts()

        self._search_categories()
        self._apply_search()

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
        if self._search_ids is not None:
            return   # search temporarily opens categories; never persist those folds
        self._set_open(sec, on)
        self.groups.save(self.host.screen)
        self.host.save()

    def _build(self, sec: CategorySection, need: Trigger | None = None):
        """Make the cards of `sec`'s triggers: BUILD_NOW now (and `need`), the rest
        a few at a time after (_build_more)."""
        todo = [t for t in self.triggers if t.category == sec.name and t.id not in self.rows
                and self._matches_search(t)]
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
        todo = [t for t in self.triggers if t.category == sec.name and t.id not in self.rows
                and self._matches_search(t)]
        until = time.perf_counter() + BUILD_STEP_MS / 1000
        made = 0
        for t in todo:
            if made and time.perf_counter() > until:
                break
            self._place_row(t, sec)
            made += 1
        if len(todo) > made:
            QTimer.singleShot(0, self, lambda: self._build_more(sec))

    def _counts(self) -> tuple[int, int, int]:
        """(triggers, on, pictures on) over the whole list."""
        on = [t for t in self.triggers if self.is_on(t)]
        return (len(self.triggers), len(on),
                sum(len(t.images) for t in on if t.uses_pictures))

    @needs_part()
    def show_watching(self):
        from onionwatch.ui.watching import WatchingDialog
        WatchingDialog(self, self).exec()

    def set_cpu_share(self, share: float):
        """How much of the processor watching may use (screenwatch.CPU_SHARES), kept."""
        self.watcher.cpu_share = share
        self.host.screen["cpu_share"] = share
        self.host.save()

    def set_max_detect(self, how: str):
        """"Max detection" (screenwatch.MAX_DETECTS), kept in a key of its own: the
        processor share stays as picked, for when it's off (and older versions)."""
        self.watcher.max_detect = how
        self.host.screen["max_detect"] = how
        self.host.save()

    def set_color_log(self, on: bool):
        """The Log's pictures in colour (on) or grey, kept as "color_log"."""
        self.watcher.color_hits = on
        self.host.screen["color_log"] = on
        self.host.save()

    def set_show_chances(self, on: bool):
        """The Chances button on the Playing now bar, shown or not ("show_chances")."""
        self.host.screen["show_chances"] = on
        self.host.save()
        if self.pages is not None:
            self.pages.playing.show_chances_button()

    def watching_text(self) -> str:
        """How often each trigger is checked now, for the Watching dialog."""
        pics = pictures(self._counts()[2])
        if not self.is_active() or not self.watcher.running:
            return _("Not watching right now ({pictures} on).", pictures=pics)
        w = self.watcher
        if w.heavy:
            text = _("Each trigger is checked every {s:.2f} s (max detection is on), with "
                     "{pictures} on.", s=w.gap, pictures=pics)
        elif w.gap > w.interval * 1.05:
            text = _("Each trigger is checked every {s:.2f} s (the most it can in that share), "
                     "with {pictures} on.", s=w.gap, pictures=pics)
        else:
            text = _("Each trigger is checked every {s:.2f} s, with {pictures} on.",
                     s=w.gap, pictures=pics)
        if any(t.interval_ms for t in self.triggers if self.is_on(t)):
            text = _("Watching ticks every {s:.2f} s, with {pictures} on. Each trigger follows "
                     "its own interval (or the default); the shared processor limit can make "
                     "checks slower.", s=w.gap, pictures=pics)
        if w.cpu_used is not None:
            text += "\n" + _("Watching is using about {share:.2f} % of your processor "
                             "({core:.0f} % of one core).", share=w.cpu_used * 100,
                             core=w.cpu_used * screenwatch.CORES * 100)
        return text

    def _gap_text(self) -> str:
        if not self.is_active() or not self.watcher.running:
            return ""
        if any(t.interval_ms for t in self.triggers if self.is_on(t)):
            return _("watching tick {s:.2f} s · individual intervals", s=self.watcher.gap)
        return _("each checked every {s:.1f} s", s=self.watcher.gap)

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
        parts = [ngettext("{on} of {n} trigger on", "{on} of {n} triggers on", total, on=on),
                 pictures(pics)]
        self._gap_shown = self._gap_text()
        if self._gap_shown:
            parts.append(self._gap_shown)
        state = self._profile_state()
        self.lbl_counts.setText(" · ".join(parts) + (f"  —  {state}" if state else ""))
        self.lbl_counts.setToolTip(
            _("Triggers on, and the pictures they look for. Each picture on takes a share of the "
              "processor watching keeps to (⚙): with too many, each is checked less often. Turn "
              "off what you don't need now, or give triggers an Area."))

    def _refresh_switches(self):
        """Each section's switch: is it on now, and who says so."""
        ps = self.groups.in_charge(self.apps.matched)
        if not ps:
            tip = _("Switch the whole category on or off. Its triggers keep their own "
                    "switches, so turning it back on brings back just the ones that were on.")
        elif len(ps) == 1:
            tip = _("On or off as the profile “{name}” says: switching it changes "
                    "that profile.", name=ps[0].name)
        else:
            tip = _("On or off as the profiles {names} say (Automatic). "
                    "Change them under More → Profiles….", names=", ".join(p.name for p in ps))
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
            QMessageBox.information(self, _("Set by profiles"),
                                    _("The profiles {names} say which categories are on now "
                                      "(Profile is Automatic). Change them under More → "
                                      "Profiles….", names=names))
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
            name, ok = QInputDialog.getText(self, _("New category"), _("Name of the category:"))
            if not ok:
                return None
        name = profiles.clean_name(name)
        if not name:
            return None
        if self.groups.find(name) is None:
            if len(self.groups.categories) >= profiles.MAX_CATEGORIES:
                QMessageBox.information(self, _("Too many categories"),
                                        _("You can have up to {max_categories}.",
                                          max_categories=profiles.MAX_CATEGORIES))
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
        for row in self._cards():
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
            row.flash(_("Moved to {category}", category=profiles.label(t.category)))
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
            box = QMessageBox(QMessageBox.Question, _("Delete category"),
                              _("Delete the category “{name}”?", name=name) + "\n\n"
                              + (ngettext("Its {n} trigger moves to {uncategorised}: none is "
                                          "deleted.",
                                          "Its {n} triggers move to {uncategorised}: none is "
                                          "deleted.", len(moved),
                                          uncategorised=profiles.label(profiles.UNCATEGORISED))
                                 if moved else _("It's empty.")),
                              QMessageBox.Yes | QMessageBox.Cancel, self)
            box.button(QMessageBox.Yes).setText(_("Delete"))
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
        self.undo_bar.show_for(_("Deleted the category “{name}”", name=name), undo,
                               tip=_("Put it back, its triggers and all"))
        return True

    def export_category(self, name: str):
        ts = [t for t in self.triggers if t.category == name]
        if ts:
            self.export_triggers(ts, profiles.label(name))

    def add_in_category(self, name: str, make):
        """Make a new trigger (`make`: add_from_cut and co.) in this category: it's
        opened first, so the new one goes in it and shows."""
        sec = self.sections.get(name)
        if sec is not None and not sec.btn_fold.isChecked():
            sec.btn_fold.setChecked(True)      # opens it (and makes it the last opened)
        self._last_category = name
        make()

    def _fill_new_here(self, menu: QMenu, name: str):
        """The ways to make a trigger, each putting it in this category."""
        menu.addAction(icons.icon("crop"), _("Cut it from the window"),
                       lambda: self.add_in_category(name, self.add_from_cut))
        menu.addAction(icons.icon("plus"), _("From a picture file…"),
                       lambda: self.add_in_category(name, self.add_from_file))
        a = menu.addAction(icons.icon("image"), _("Paste the copied picture"),
                           lambda: self.add_in_category(name, self.add_from_clipboard))
        a.setEnabled(not QApplication.clipboard().image().isNull())
        menu.addAction(_("Without a picture…"),
                       lambda: self.add_in_category(name, self.add_area_trigger))

    def _pop_menu(self, menu: QMenu, under: QWidget):
        """Show a menu under a button (tests swap this for one that doesn't wait)."""
        menu.exec(under.mapToGlobal(under.rect().bottomLeft()))

    def _category_add_menu(self, name: str):
        """A section's + button: the ways to make a new trigger in it."""
        sec = self.sections.get(name)
        if sec is None:
            return
        menu = QMenu(sec.btn_add)
        self._fill_new_here(menu, name)
        self._pop_menu(menu, sec.btn_add)

    def _category_menu(self, name: str):
        """A section's ⋯ menu."""
        sec = self.sections.get(name)
        if sec is None:
            return
        menu = QMenu(sec.btn_menu)
        named = name != profiles.UNCATEGORISED
        n = sum(t.category == name for t in self.triggers)
        self._fill_new_here(menu.addMenu(icons.icon("plus"), _("New trigger here")), name)
        menu.addSeparator()
        if named:
            menu.addAction(_("Rename…"), lambda: self._ask_rename(name))
        menu.addAction(icons.icon("palette"), _("Colours and picture…"),
                       lambda: self.edit_categories(name))
        menu.addAction(icons.icon("search"), _("Search this category"),
                       lambda: self.show_search(name))
        a = menu.addAction(_("Turn all its triggers on"),
                           lambda: self.set_category_triggers(name, True))
        a.setEnabled(n > 0)
        a = menu.addAction(_("Turn all its triggers off"),
                           lambda: self.set_category_triggers(name, False))
        a.setEnabled(n > 0)
        menu.addSeparator()
        i = self.groups.names().index(name) if self.groups.find(name) else 0
        menu.addAction(_("Move up"), lambda: self.move_category(name, -1)).setEnabled(i > 0)
        menu.addAction(_("Move down"), lambda: self.move_category(name, 1)).setEnabled(
            i < len(self.groups.categories) - 1)
        menu.addSeparator()
        menu.addAction(_("Save to a file…"), lambda: self.export_category(name)).setEnabled(n > 0)
        if named:
            menu.addAction(icons.icon("trash"), _("Delete category…"),
                           lambda: self.delete_category(name))
        self._pop_menu(menu, sec.btn_menu)

    def _ask_rename(self, name: str):
        from PySide6.QtWidgets import QInputDialog
        new, ok = QInputDialog.getText(self, _("Rename category"), _("New name:"), text=name)
        if ok:
            self.rename_category(name, new)

    # ------------------------------------------------------------------ profiles
    def _fill_profiles(self):
        cb, g = self.cb_profile, self.groups
        cb.blockSignals(True)
        cb.clear()
        cb.addItem(_("Manual (your switches)"), "")
        for p in g.profiles:
            cb.addItem(p.name, p.id)
        if g.profiles:
            cb.addItem(_("Automatic (by program)"), profiles.AUTO)
        cb.insertSeparator(cb.count())
        cb.addItem(_("Edit profiles…"), EDIT_PROFILES)
        cb.setCurrentIndex(max(0, cb.findData(g.mode)))
        cb.blockSignals(False)
        self.groupbar.setVisible(self._grouped())

    def _profile_state(self) -> str:
        """Who decides what's on, in a few words, when it isn't Manual."""
        if self.groups.mode != profiles.AUTO:
            return ""
        ps = self.groups.in_charge(self.apps.matched)
        if not ps:
            return _("no profile's program is open: your switches apply")
        return _("on now: {names}", names=", ".join(p.name for p in ps))

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
    def sounds_changed(self, force: bool = False):
        """The host's sounds may have changed: give the cards the new list. Only when
        it did (or `force`: a trigger's own sounds or the theme changed), since every
        tab show and board pad move lands here, and remaking every card's list and
        chips is slow with many triggers."""
        sounds = list(self.host.sounds())
        if force or sounds != self._sounds_shown:
            self._sounds_shown = sounds
            for row in self._cards():
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
        if self._search_ids is not None:
            self.clear_search()   # the newly added/restored card must be visible to edit
        sec = self._section_of(t)
        if not sec.is_open:
            self._set_open(sec, True)
        self._build(sec, need=t)
        row = self.rows.get(t.id) or self._place_row(t, sec, open_)
        if open_ and self.split:        # (its card may have been made closed, with others)
            self._select(row)
        return row

    def _make_row(self, t: Trigger, open_: bool, parent: QWidget | None = None) -> TriggerRow:
        """A card for `t`, opened unless `open_` is false (the cards made for the
        list at start, when there's more than one). Made in `parent` (where it goes):
        moved there afterwards, its every widget would be styled all over again."""
        split = self.split
        row = TriggerRow(t, self.host.sounds(), self._mons, open_=open_ and not split,
                         parent=parent)
        self._wire(row)
        row.set_advanced(self.chk_advanced.isChecked())
        row.set_categories(self.groups.names())
        row.set_default_interval(self.default_interval)
        row.set_default_place(places_label([self.watcher.default]))
        self.rows[t.id] = row
        if split:
            row.on_open = self._select
            if open_:
                self._select(row)
            elif self.editor is not None and self.editor.t is t:
                row.set_selected(True)      # made again (moved, found by a search...)
        return row

    def _wire(self, row: TriggerRow):
        """Connect a card (the list's, or the editor) to the tab."""
        row.sound_details = getattr(self.host, "sound_details", row.sound_details)
        row._update_state()
        row.files_dropped.connect(self._add_dropped_files)
        row.picture_dropped.connect(self._add_dropped_picture)
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
        row.retarget_wanted.connect(self.change_window)
        row.area_wanted.connect(self._pick_area)
        row.duplicate.connect(self._duplicate)
        row.hear.connect(lambda sid, r=row: self._hear(r.t, sid))
        row.test.connect(lambda r: self.test_trigger(r.t))
        row.remove.connect(self.ask_remove)

    def _place_row(self, t: Trigger, sec: CategorySection, open_: bool = False) -> TriggerRow:
        """Put `t`'s card (made if need be) in `sec` where it is in self.triggers."""
        row = self.rows.get(t.id) or self._make_row(t, open_, sec.body)
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
        row.setVisible(self._matches_search(t))
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
        raws = [t.to_raw() for t in self.triggers]
        self.host.screen["triggers"] = raws[:OLD_TRIGGERS]      # (see OLD_TRIGGERS)
        self.host.screen["more_triggers"] = raws[OLD_TRIGGERS:]
        # older versions drop a field they don't know when they save a trigger: its
        # category is kept here as well, where they never look
        self.host.screen["trigger_categories"] = {t.id: t.category for t in self.triggers
                                                  if t.category}
        self.groups.save(self.host.screen)
        self.host.save()
        self._sync_views()
        self._refresh_counts()
        if self._search_ids is not None:
            self._apply_search()
        if self.is_active():
            self._sync()
        self._show_warning()

    def _new(self, img: QImage | list[QImage], name: str, notes: list[str] = ()
             ) -> Trigger | None:
        """A new trigger from a picture (or several), playing the default alert until
        another sound is picked; None when no picture could be used. `notes`: see
        _add_pictures."""
        if len(self.triggers) >= MAX_TRIGGERS:
            QMessageBox.information(self, _("Too many triggers"),
                                    _("You can have up to {max_triggers} triggers.",
                                      max_triggers=MAX_TRIGGERS))
            return None
        t = Trigger(id=uuid.uuid4().hex[:12], name=name[:60] or _("Trigger"),
                    sounds=[self.host.default_sound] if self.host.default_sound else [],
                    category=self._new_category())
        if not self._add_pictures(t, [img] if isinstance(img, QImage) else list(img),
                                  notes=notes):
            return None
        self.triggers.append(t)
        row = self._add_row(t)
        if self._web_added:
            self._web_tip(row)
        self._store()
        self.trigger_added.emit()
        QTimer.singleShot(0, row, lambda: self.scroll.ensureWidgetVisible(row))
        row.name.setFocus()
        row.name.selectAll()
        return t

    def _check_picture(self, img: QImage) -> tuple[Picture | None, tuple[str, str]]:
        """Whether a picture can be looked for: (its grey and mask, ()) or (None,
        (why not, in detail))."""
        if img.isNull():
            return None, (_("Not a picture"), _("That picture couldn't be read."))
        if min(img.width(), img.height()) < 6:
            return None, (_("Picture too small"),
                          _("Cut a bigger piece: at least 6 pixels each way."))
        if max(img.width(), img.height()) > MAX_SIDE:
            return None, (_("Picture too big"), _("Cut a smaller piece: at most "
                                                  "{n} pixels each way.", n=MAX_SIDE))
        pic = picture_of(img)
        if pic is None or flatness(*pic) < screenwatch.FLAT_STD:
            return None, (_("Picture is one plain colour"),
                          _("There's nothing in it to recognise. Cut a piece with some detail, "
                            "like the words or an icon. (Transparent parts don't count.)"))
        return pic, ()

    def _add_pictures(self, t: Trigger, imgs: list[QImage], names: list[str] = (),
                      at: int | None = None, notes: list[str] = ()) -> int:
        """Add pictures to a trigger (`at`: replace that one instead). Each is checked
        before it's saved, so a refused picture never replaces or joins the others;
        what was refused, and what may not be found (`notes`: more of that, from how
        a cut did while it was cut), is said once for the lot.
        Returns how many were added."""
        refused: list[tuple[str, str, str]] = []      # (name, title, text)
        extra, notes = list(notes), []                # notes: (name, note)
        added = left_out = 0
        # a pasted or loaded picture doesn't say what it was cut from: most likely
        # what the trigger watches, as it is now
        here = self._source_size(t.source if t.source is not None else self.watcher.default)
        web = 0
        for i, img in enumerate(imgs):
            if not img.isNull() and is_web(img):
                img = fit_web(img, here)
            if not img.isNull() and cut_size(img) is None:
                set_cut_size(img, here)
            name = names[i] if i < len(names) else _("Picture {n}", n=len(t.images) + 1)
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
                refused.append((name, _("Couldn't keep the picture"), str(e)))
                continue
            if at is not None and 0 <= at < len(t.images):
                old, t.images[at] = t.images[at], path
                delete_picture(old, self.pictures)
                self._gray.pop(old, None)
                self._cuts.pop(old, None)
                self._wide.pop(old, None)
                at = None                   # a second picture would only be added
            else:
                t.images.append(path)
            added += 1
            web += is_web(img)
            for note in self._picture_notes(pic, t, is_web(img)) + extra:
                notes.append((name, note))
        self._web_added = web
        row = self.rows.get(t.id)
        if row is not None:
            row.refresh_pictures()
            if web:
                self._web_tip(row)
            if left_out:
                row.flash(ngettext("A trigger can look for up to {max} pictures — {n} "
                                   "picture not added",
                                   "A trigger can look for up to {max} pictures — {n} "
                                   "pictures not added", left_out, max=MAX_PICTURES),
                          4000, "warn")
        self._say(refused, _("Some pictures couldn't be used"))
        self._say([(n, _("This picture may not be found"), note) for n, note in notes],
                  _("Some pictures may not be found"))
        return added

    @staticmethod
    def _web_tip(row: TriggerRow):
        """Said on the card when a picture not cut from the game is added (once the
        card's been redrawn for it: that sets its line back)."""
        text = _("From the web: looked for at every size. Never found? Cut it from the game.")
        QTimer.singleShot(0, row, lambda: row.flash(text, 9000, "warn"))

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

    def _picture_notes(self, pic: Picture, t: Trigger, web: bool = False) -> list[str]:
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
        smallest = (screenwatch.WIDE_SIZES[0] if web else
                    screenwatch.SIZES[0] if t.any_size else 1.0)
        if w * smallest > sw or h * smallest > sh:
            notes.append(
                _("It's bigger than the window being watched ({w}×{h}), so it can't be found "
                  "there. Cut it from that window at the size it's shown.", w=sw, h=sh)
                if what == "window" else
                _("It's bigger than the screen being watched ({w}×{h}), so it can't be found "
                  "there. Cut it from that screen at the size it's shown.", w=sw, h=sh))
            return notes
        top = screenwatch.work_scale(sw, [1])     # the most detail a check keeps
        need = math.ceil(screenwatch.MIN_SIDE / top)
        if min(w, h) < need:
            notes.append(
                _("It's very small for a {w}-pixel-wide window, so it may be missed or match "
                  "the wrong thing. A bigger piece (at least {n} pixels each way) works "
                  "better.", w=sw, n=need) if what == "window" else
                _("It's very small for a {w}-pixel-wide screen, so it may be missed or match "
                  "the wrong thing. A bigger piece (at least {n} pixels each way) works "
                  "better.", w=sw, n=need))
        scale = screenwatch.work_scale(sw, [min(w, h)])
        if mask is not None and int(screenwatch.shrink_mask(mask, scale).sum()) < \
                screenwatch.MASK_MIN:
            notes.append(_("Most of it is see-through and what's left is thin, so there's "
                           "almost nothing to compare once it's scaled down for checking. "
                           "Keep more of the background around it, or use a picture "
                           "without transparency."))
        return notes

    # ------------------------------------------------------------------ cutting
    def capture(self, src) -> tuple[QImage | None, str]:
        """A full-size picture of a window or screen to cut from: (image, its name),
        or (None, why not)."""
        from onionwatch.ui.windowpicker import bgra_image
        px, where, _again = self._grab(src)
        return (None if px is None else bgra_image(px)), where

    def _grab(self, src) -> tuple[np.ndarray | None, str, object]:
        """capture() as pixels: (BGRA, its name, how to grab it again: a function
        for a window, the Monitor for a screen) or (None, why not, None)."""
        if isinstance(src, WindowRef):
            info = windows.find(src)
            if info is None:
                return None, _("{name} isn't open. Start it, then try again.",
                               name=src.label), None
            if info.minimized:
                return None, _("{name} is minimized. Restore it, then try again.",
                               name=src.label), None
            px = windows.snapshot(info.hwnd)
            if px is None:
                return None, _("{name} couldn't be copied.", name=src.label), None
            return px, src.label, lambda: windows.snapshot(info.hwnd)
        mons = screenwatch.monitors()
        if not mons:
            return None, _("No screen was found."), None
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
            return None, _("The screen couldn't be copied."), None
        return px, source_label(src, mons), mon

    @needs_part(fallback=(None, [], ""))
    def _cut(self, src, threshold: float = Trigger.threshold
             ) -> tuple[QImage | None, list[str], str]:
        """Cut a picture from a window or screen: (the piece or None, what's worth
        warning about it, a line to flash when it was made a cut-out). While a
        window's cut dialog is open the window keeps being grabbed (a screen, for a
        moment after it): scenery moving behind the thing is learned and left out
        (cutout.py), and a piece that may be missed or go off by mistake is said."""
        from onionwatch.ui.windowpicker import bgra_image
        px, where, again = self._grab(src)
        if px is None:
            QMessageBox.information(self, _("Can't cut a picture"), where)
            return None, [], ""
        if float(px[..., :3].max()) < 8:
            QMessageBox.information(self, _("It comes out black"),
                                    _("{where} comes out black, so there's nothing to cut. Some "
                                      "games can only be seen on the screen: pick its screen "
                                      "under Look in instead.", where=where))
            return None, [], ""
        img = bgra_image(px)
        from onionwatch.ui.snip import SnipDialog
        rec = cutout.Recorder(px, again if callable(again) else None)
        if callable(again):
            rec.start()
        dlg = SnipDialog(img, where, self)
        if not dlg.exec() or dlg.piece is None:
            rec.stop()
            return None, [], ""
        piece = dlg.piece
        s = dlg.view.selection
        rect = (s.x(), s.y(), piece.width(), piece.height())
        if isinstance(again, Monitor):
            rec.stop()
            self._grab_screen_after(rec, again, rect)
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            keep, plain, cut = cutout.learn(rec, rect)
        except Exception:       # learning is a bonus: the plain cut still works
            log.exception("learning the cut's background failed")
            keep, plain, cut = None, None, None
        finally:
            QApplication.restoreOverrideCursor()
        flash = ""
        if keep is not None:
            piece = with_alpha(piece, keep)
            flash = _("Learned the background: {share:.0%} of the picture is scenery and "
                      "left out", share=1 - float(keep.mean()))
        set_cut_size(piece, (img.width(), img.height()))
        kept = cut if keep is not None else plain
        what = "window" if isinstance(src, WindowRef) else "screen"
        return piece, ([] if kept is None else cutout.notes(kept, threshold, what)), flash

    def _grab_screen_after(self, rec: cutout.Recorder, mon: Monitor,
                           rect: tuple[int, int, int, int]):
        """A screen's frames for the cut-out: grabbed for SCREEN_LEARN_MS once the
        cut dialog has closed (it covered the screen while open), our window hidden
        only when it's over the piece."""
        from PySide6.QtCore import QElapsedTimer, QThread
        win = self.window()
        g = win.frameGeometry()
        dpr = win.devicePixelRatioF() or 1.0
        x, y, w, h = rect
        over = (g.left() * dpr < mon.left + x + w and g.right() * dpr > mon.left + x
                and g.top() * dpr < mon.top + y + h and g.bottom() * dpr > mon.top + y)
        was = win.windowOpacity()
        if over:
            win.setWindowOpacity(0.0)
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            QApplication.processEvents()
            QThread.msleep(150)
            rec.restart(lambda: windows.screen_snapshot(mon.left, mon.top, mon.width,
                                                        mon.height))
            clock = QElapsedTimer()
            clock.start()
            while clock.elapsed() < SCREEN_LEARN_MS:
                QApplication.processEvents()
                QThread.msleep(20)
        finally:
            QApplication.restoreOverrideCursor()
            if over:
                win.setWindowOpacity(was)

    def add_from_cut(self):
        usage.used("cut-from-window")
        piece, notes, flash = self._cut(self.watcher.default)
        if piece is not None:
            t = self._new(piece, _("Trigger {n}", n=len(self.triggers) + 1), notes)
            if t is not None and flash and t.id in self.rows:
                self.rows[t.id].flash(flash, 5000)

    def _cut_picture(self, row: TriggerRow):
        usage.used("cut-from-window")
        src = row.t.source if row.t.source is not None else self.watcher.default
        piece, notes, flash = self._cut(src, row.t.threshold)
        if piece is not None and self._add_pictures(row.t, [piece], notes=notes):
            self._store()
            if flash:
                row.flash(flash, 5000)

    # ------------------------------------------------------------------ files
    def add_from_file(self):
        usage.used("picture-file")
        path, __ = QFileDialog.getOpenFileName(self, _("Picture to look for"), str(Path.home()),
                                              picture_filter())
        if path:
            self._new(picture_file(path), Path(path).stem)

    def add_from_clipboard(self):
        usage.used("paste-picture")
        img = copied_picture()
        if img.isNull():
            QMessageBox.information(self, _("No picture copied"),
                                    _("Copy a picture first: press Win+Shift+S, drag around the "
                                      "thing to look for, then click Paste."))
            return
        self._new(img, _("Trigger {n}", n=len(self.triggers) + 1))

    def _add_picture_files(self, row: TriggerRow):
        """The card's "+ Add pictures…": any number of files onto this trigger."""
        usage.used("picture-file")
        paths, __ = QFileDialog.getOpenFileNames(self, _("Pictures to look for"),
                                                str(Path.home()), picture_filter())
        if paths and self._add_pictures(row.t, [picture_file(p) for p in paths],
                                        [Path(p).name for p in paths]):
            self._store()

    def _add_dropped_files(self, row: TriggerRow, paths: list[str]):
        """Picture files dropped on a card: onto its trigger."""
        usage.used("picture-file")
        if paths and self._add_pictures(row.t, [picture_file(p) for p in paths],
                                        [Path(p).name for p in paths]):
            self._store()

    def _add_dropped_picture(self, row: TriggerRow, img: QImage):
        """A picture dragged from a browser and dropped on a card: onto its trigger."""
        if self._add_pictures(row.t, [img]):
            self._store()

    def _paste_picture(self, row: TriggerRow):
        """The card's "Paste picture": the copied picture onto this trigger."""
        usage.used("paste-picture")
        img = copied_picture()
        if img.isNull():
            QMessageBox.information(self, _("No picture copied"),
                                    _("Copy a picture first: press Win+Shift+S, drag around the "
                                      "thing to look for, then click “Paste the copied picture”."))
            return
        if self._add_pictures(row.t, [img]):
            self._store()

    @needs_part()
    def _view_picture(self, row: TriggerRow, index: int = 0):
        """A thumbnail was clicked: its picture big, with the trigger's others."""
        from onionwatch.ui.viewer import PictureViewer
        t = row.t
        viewers = getattr(self, "_picture_viewers", None)
        if viewers is None:
            viewers = self._picture_viewers = {}
        if t.id in viewers:
            viewers[t.id].go(index)
            viewers[t.id].raise_()
            viewers[t.id].activateWindow()
            return

        def made_from(img: QImage) -> str:
            if is_web(img):
                return _("not cut from the game: looked for at any size")
            size = cut_size(img)
            return _("cut from a {w}×{h} view", w=size[0], h=size[1]) if size else ""

        def swap(i: int):
            r = self.rows.get(t.id)
            if r is not None:
                self._change_picture(r, i)

        def remove(i: int):
            r = self.rows.get(t.id)
            if r is not None:
                self._remove_picture(r, i)

        viewer = PictureViewer(_("Pictures of “{name}”", name=t.name), lambda: t.images, index,
                               swap,
                               remove, made_from, self)
        viewers[t.id] = viewer
        viewer.setAttribute(Qt.WA_DeleteOnClose)
        viewer.finished.connect(lambda _result: viewers.pop(t.id, None))
        viewer.open()

    def _change_picture(self, row: TriggerRow, index: int = 0):
        """Swap one of the trigger's pictures for a file."""
        path, __ = QFileDialog.getOpenFileName(self, _("Picture to look for"), str(Path.home()),
                                              picture_filter())
        if path and self._add_pictures(row.t, [picture_file(path)], [Path(path).name],
                                       at=index):
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
        self.undo_bar.show_for(_("Removed a picture from “{name}”", name=t.name), undo, done)

    def _choose_sound_file(self, row: TriggerRow):
        exts = " ".join(f"*{e}" for e in sorted(self.host.audio_exts))
        path, __ = QFileDialog.getOpenFileName(self, _("Sound to play"), str(Path.home()),
                                              _("Audio") + f" ({exts});;" + _("All files") + " (*)")
        if not path:
            return
        tid = row.t.id
        row.flash(_("Adding the sound…"), 60_000)
        try:
            self.host.add_sound(path, lambda sid: self._sound_added(tid, sid))
        except OSError as e:
            row.flash("", 0)
            QMessageBox.warning(self, _("Can't use that sound"), str(e))

    def _sound_added(self, tid: str, sid: str | None):
        """A sound file picked on a card has been added to the host (sid), or couldn't
        be (None): put it on that trigger, if it's still there."""
        t = next((t for t in self.triggers if t.id == tid), None)
        row = self.rows.get(tid)
        if row is not None:
            row.flash("", 0)
        if t is not None and sid and sid not in t.sounds and len(t.sounds) < MAX_SOUNDS:
            t.sounds.append(sid)
        self.sounds_changed(force=True)
        if t is not None and sid:
            self._store()
        elif row is not None and not sid:
            row.flash(_("That sound couldn't be added"), 4000, "warn")

    def ask_remove(self, row: TriggerRow):
        """The card's delete button: ask first, then delete (to Recently deleted)."""
        box = QMessageBox(QMessageBox.Question, _("Delete trigger"),
                          _("Delete the trigger “{name}”?\n\nIt goes to Recently deleted, where "
                            "you can bring it back for {keep_days} days.",
                            name=row.t.name, keep_days=KEEP_DAYS),
                          QMessageBox.Yes | QMessageBox.Cancel, self)
        box.button(QMessageBox.Yes).setText(_("Delete"))
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
        if self.editor is not None and self.editor.t.id == t.id:
            self._drop_editor()         # the editor moves on to the next one
            nxt = self.triggers[min(index, len(self.triggers) - 1)] if self.triggers else None
            if nxt is not None and nxt.id in self.rows:
                self._select(self.rows[nxt.id])
        for path in t.images:
            self._gray.pop(path, None)   # the file stays, in the bin
        self._layout_sections()
        self._prune_bin()
        self._store()
        self.ringing_changed.emit()
        if not self.triggers and self.is_active():
            self.set_watching(False)
        self._label_bin()
        self.undo_bar.show_for(_("Deleted “{name}”", name=t.name),
                               lambda: self.restore_deleted(entry["id"]),
                               tip=_("Put it back, exactly as it was. Later: Recently "
                                     "deleted (kept {n} days)", n=KEEP_DAYS))

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
        what = _("Recently deleted ({n})", n=n)
        self.btn_bin.setToolTip(what + "…\n" + _("Triggers you deleted: bring them back, "
                                                 "pictures and all"))
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
        return [(d["id"], str(d["trigger"].get("name") or _("Trigger")), _num(d.get("when")))
                for d in reversed(self._bin())]

    def restore_deleted(self, entry_id: str) -> bool:
        """Bring a deleted trigger back where it was, as it was."""
        all_ = self._bin()
        entry = next((d for d in all_ if d["id"] == entry_id), None)
        if entry is None:
            return False
        if len(self.triggers) >= MAX_TRIGGERS:
            QMessageBox.information(self, _("Too many triggers"),
                                    _("You can have up to {max_triggers} triggers. Delete one to "
                                      "bring this one back.", max_triggers=MAX_TRIGGERS))
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
        usage.used("restore-deleted")
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

    @needs_part()
    def show_deleted(self):
        from onionwatch.ui.deleted import DeletedDialog
        self.undo_bar.finish()
        DeletedDialog(self, KEEP_DAYS, self).exec()
        self._label_bin()

    # ------------------------------------------------------------------ areas, copies
    @needs_part()
    def _pick_area(self, row: TriggerRow):
        """The card's "Area…" / "Bar and colour…": drag the part of the window to look
        in (and for a colour trigger, check its colour)."""
        from onionwatch.ui.snip import AreaDialog
        t = row.t
        src = t.source if t.source is not None else self.watcher.default
        img, where = self.capture(src)
        if img is None:
            QMessageBox.information(self, _("Can't show the window"), where)
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
        usage.used("duplicate")
        if len(self.triggers) >= MAX_TRIGGERS:
            QMessageBox.information(self, _("Too many triggers"),
                                    _("You can have up to {max_triggers} triggers.",
                                      max_triggers=MAX_TRIGGERS))
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
        self.trigger_added.emit()
        QTimer.singleShot(0, row, lambda: self.scroll.ensureWidgetVisible(row))
        return row

    def add_area_trigger(self):
        """A new trigger that watches an area rather than looking for a picture: it
        starts as "the area stops changing" (a game stuck or idle); the card picks
        another kind."""
        usage.used("area-trigger")
        if len(self.triggers) >= MAX_TRIGGERS:
            QMessageBox.information(self, _("Too many triggers"),
                                    _("You can have up to {max_triggers} triggers.",
                                      max_triggers=MAX_TRIGGERS))
            return
        t = Trigger(id=uuid.uuid4().hex[:12], name=_("Trigger {n}", n=len(self.triggers) + 1),
                    sounds=[self.host.default_sound] if self.host.default_sound else [],
                    mode="still", level=LEVELS["still"], hold=10.0,
                    category=self._new_category())
        row = self._insert(t)
        row.name.setFocus()
        row.name.selectAll()

    def show_history(self):
        usage.used("history")
        if self.pages is not None:
            self.pages.show_log()
        else:
            HistoryDialog(self, self).exec()

    # ------------------------------------------------------------------ playing now
    def playing_now(self) -> list[tuple[Trigger, bool]]:
        """The triggers whose sound is still going, oldest first, each with whether
        it rings. A host that can say which sounds are playing (Host.playing) says
        when one ends; with one that can't, a one-shot counts as playing for
        GUESS_PLAYING_S after it went off."""
        ringing = set(self.host.ringing())
        tags = None
        playing = getattr(self.host, "playing", None)
        if callable(playing):
            try:
                tags = set(playing())
            except Exception:  # noqa: BLE001 - a host's bug mustn't break the bar
                log.warning("the host couldn't say what's playing", exc_info=True)
        out, now = [], time.monotonic()
        for tid, since in list(self._live.items()):
            t = next((x for x in self.triggers if x.id == tid), None)
            ring = tid in ringing
            if t is not None and (ring or (
                    any(tag.startswith(tid + "/") for tag in tags) if tags is not None
                    else now - since < GUESS_PLAYING_S)):
                out.append((t, ring))
            else:
                del self._live[tid]
        self._show_tests({t.id for t, __ in out})
        return out

    def test_trigger(self, t: Trigger):
        """A card's Test: play it as it would go off, shown in Playing now like any
        other; pressed again while it plays (it says Stop then), stop it."""
        usage.used("test")
        if any(x.id == t.id for x, __ in self.playing_now()):
            self.stop_trigger(t.id)
            return
        if self._play_trigger(t, test=True):
            self._live[t.id] = time.monotonic()
            self.playing_changed.emit()

    def _show_tests(self, live: set[str]):
        """Each card's Test says Stop while its trigger plays."""
        for row in [*self.rows.values(), self.editor]:
            if row is None:
                continue
            on = row.t.id in live
            if row.btn_test.property("stops") != on:
                row.btn_test.setProperty("stops", on)
                row.btn_test.setText(_("Stop") if on else _("Test"))
                icons.set_icon(row.btn_test, "stop" if on else "play", size=14)

    def stop_trigger(self, tid: str):
        """Stop what trigger `tid` is playing now, its ring too (Playing now's Stop)."""
        self._silence(tid, ring=True)
        if self._live.pop(tid, None) is not None:
            t = next((x for x in self.triggers if x.id == tid), None)
            log.info("trigger %r stopped by hand", t.name if t else tid)
        for row in self._views(tid):
            row.flash(_("Stopped"), 2500)
        self.playing_changed.emit()

    def stop_all_playing(self):
        """Stop every trigger's sound, and drop any still waiting out its wait."""
        self.cancel_pending()
        for tid in list(self._live):
            self._silence(tid, ring=True)
        self._live.clear()
        self.stop_ringing()
        self.playing_changed.emit()

    # ------------------------------------------------------------------ packs
    def export_triggers(self, triggers: list[Trigger] | None = None, name: str = ""):
        """Save triggers to a pack: all of them, or `triggers` (a category, `name`)."""
        triggers = self.triggers if triggers is None else triggers
        if not triggers:
            return
        file = f"Onion Watch {name}.zip" if name else "Onion Watch triggers.zip"
        file = "".join("_" if c in '\\/:*?"<>|' else c for c in file)
        path, __ = QFileDialog.getSaveFileName(self, _("Save triggers"), str(Path.home() / file),
                                              _("Trigger packs") + " (*.zip)")
        if not path:
            return
        from onionwatch.ui.categories import pictures_dir as category_pictures_dir
        names = {t.category for t in triggers}
        cats = [c for c in self.groups.categories if c.name in names]
        try:
            packs.write_pack(path, triggers, dict(self.host.sounds()), cats,
                             category_pictures_dir(self.host.data_dir))
        except OSError as e:
            QMessageBox.warning(self, _("Couldn't save the triggers"), str(e))
            return
        usage.used("pack-export")
        QMessageBox.information(
            self, _("Triggers saved"),
            ngettext("{n} trigger saved to {name}, pictures and all, each in its category "
                     "with its colours, picture and banner. Sounds go by name: sound files of "
                     "yours aren't in it.",
                     "{n} triggers saved to {name}, pictures and all, each in its category "
                     "with its colours, picture and banner. Sounds go by name: sound files of "
                     "yours aren't in it.", len(triggers), name=Path(path).name))

    def import_triggers(self):
        path, __ = QFileDialog.getOpenFileName(self, _("Load triggers"), str(Path.home()),
                                              _("Trigger packs") + " (*.zip);;"
                                              + _("All files") + " (*)")
        if not path:
            return
        try:
            found = packs.read_pack(path)
        except packs.PackError as e:
            QMessageBox.warning(self, _("Can't load those triggers"), str(e))
            return
        if found and not any(t.category for t, _p, _s in found):
            # a pack without categories (an older one): its triggers go in one named
            # after the file, so they stay together
            name = profiles.clean_name(Path(path).stem.removeprefix("Onion Watch "))
            for t, _p, _s in found:
                t.category = name
        added = self.add_pack(found)
        if added:
            usage.used("pack-import")
            self.add_pack_looks(packs.read_categories(path))
        if found and not added:
            QMessageBox.information(self, _("Too many triggers"),
                                    _("You can have up to {max_triggers} triggers.",
                                      max_triggers=MAX_TRIGGERS))
        elif not found:
            QMessageBox.information(self, _("No triggers"), _("That file has no triggers in it."))

    def add_pack_looks(self, looks: dict):
        """Give the categories a pack brought their looks (packs.read_categories),
        each picture kept like a picked one. A category that already has a look
        or banner of its own keeps it."""
        from onionwatch.ui.categories import save_banner, save_picture as save_category_picture
        changed = {}
        for name, (look, pic, wide) in looks.items():
            c = self.groups.find(name)
            if c is None:
                continue
            new = c.full_look()
            if not c.look():
                new.update({k: v for k, v in look.items() if k != "banner"})
                img = QImage()
                if pic and img.loadFromData(pic):
                    new["image"] = save_category_picture(img, self.host.data_dir)
            img = QImage()
            if not c.banner and wide and img.loadFromData(wide):
                b = save_banner(img, self.host.data_dir)
                if b:
                    new["banner"] = {**look.get("banner", {}), "image": b}
            if new != c.full_look():
                changed[name] = new
        if changed:
            self.set_category_looks(changed)

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
