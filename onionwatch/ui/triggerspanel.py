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
onionwatch.screenwatch, windows are onionwatch.windows. Triggers are kept in
Config.screen and their pictures in %APPDATA%\\OnionWatch\\triggers.
"""
from __future__ import annotations

import logging
import math
import os
import uuid
from pathlib import Path

import numpy as np
from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog,
                               QFrame, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton,
                               QScrollArea, QSizePolicy, QSpinBox, QVBoxLayout, QWidget)

from onionwatch import screenwatch, settings, theme, windows
from onionwatch.screenwatch import (INTERVALS_MS, MAX_PICTURES, MAX_SOUNDS, Monitor, Picture,
                                    Trigger, Watched, WindowRef)
from onionwatch.shuffle import ShuffleBag
from onionwatch.sounds import AUDIO_EXTS, DEFAULT_SOUND
from onionwatch.ui import icons
from onionwatch.ui.panel import Flow, card, hint_label
from onionwatch.wheelguard import no_wheel

log = logging.getLogger(__name__)

PICTURE_EXTS = "*.png *.jpg *.jpeg *.bmp *.webp *.gif"
ADD = "__add__"         # the sound list's "+ Add sound…" entry (its resting state)
FILE = "__file__"       # ...its "Choose a sound file…" entry
PICK_WINDOW = "__pick_window__"   # a "Look in" list's "Pick a window…" entry
DEFAULT = "__default__"           # ...its "Same as below" entry
POLL_MS = 150           # how often the live match numbers refresh
MAX_TRIGGERS = 50
MAX_SIDE = 8192         # bigger pictures are refused (kept pixel for pixel, never resized)
THUMB = QSize(80, 45)
STRIP_THUMBS = 3        # thumbnails a card's strip shows before it scrolls
CHIP_CHARS = 24         # a sound chip's name is cut to this many characters
PICKS = (("random", "Random"), ("order", "In order"), ("all", "All at once"))


def pictures_dir() -> Path:
    return settings.APP_DIR / "triggers"


def load_picture(path: str) -> Picture | None:
    """A picture file as grey float32 0..1, plus which pixels count: the opaque ones
    (None when it has no transparency). Transparent parts are left out of matching."""
    return picture_of(QImage(path))


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


def save_picture(img: QImage, name: str) -> str:
    """Keep a copy of the picture as <name>.png; returns its path. It's kept pixel for
    pixel: resized, it would no longer match the screen it was cut from. Written
    beside it first, so a failed save leaves the old picture as it was."""
    folder = pictures_dir()
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{name}.png"
    tmp = folder / f"{name}.saving"
    if not img.save(str(tmp), "PNG"):
        tmp.unlink(missing_ok=True)
        raise OSError(f"couldn't save the picture to {path}")
    os.replace(tmp, path)
    return str(path)


def picture_name(t: Trigger) -> str:
    """A file name (without .png) for a picture being added to `t`: <id> for the
    first, as older versions saved it, then <id>-<random> so removing and adding
    pictures never reuses a name."""
    if not t.images and not (pictures_dir() / f"{t.id}.png").exists():
        return t.id
    return f"{t.id}-{uuid.uuid4().hex[:6]}"


def delete_picture(path: str):
    """Remove a picture file this tab keeps (never one the user pointed at)."""
    if path and Path(path).parent == pictures_dir():
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
    """One picture in a card's strip: the thumbnail (click to swap it for another
    file) with a ✕ in its corner while the mouse is over it."""
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
                                "swap it for another file")
        else:
            self.pic.setIcon(pm.scaled(THUMB, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            self.pic.setToolTip(f"{Path(path).name} ({pm.width()}×{pm.height()})\n"
                                "Click to swap it for another file")
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


def fill_sources(cb: QComboBox, mons: list[Monitor], window: WindowRef | None,
                 monitor: int | None, default_label: str = "") -> None:
    """Fill a "Look in" list: "Same as below" (when `default_label`), each screen, the
    chosen window, then "Pick a window…". The current choice is selected: the window,
    else the screen, else the default (or the first screen)."""
    cb.blockSignals(True)
    cb.clear()
    current = 0
    if default_label:
        cb.addItem(default_label, DEFAULT)
    for i, m in enumerate(mons):
        cb.addItem(icons.icon("apps", "muted"), f"Screen {i + 1}: {m.label}", i)
        if window is None and monitor == i:
            current = cb.count() - 1
    if not mons and not default_label:
        cb.addItem(icons.icon("apps", "muted"), "Main screen", 0)
    if monitor is not None and window is None and not 0 <= monitor < len(mons) and mons:
        cb.addItem(f"Screen {monitor + 1} (not plugged in)", monitor)
        current = cb.count() - 1
    if window is not None:
        cb.addItem(icons.icon("window"), window.label, window)
        current = cb.count() - 1
    cb.insertSeparator(cb.count())
    cb.addItem(icons.icon("window", "muted"), "Pick a window…", PICK_WINDOW)
    cb.setCurrentIndex(current)
    cb.blockSignals(False)


def source_label(src, mons: list[Monitor]) -> str:
    if isinstance(src, WindowRef):
        return src.label
    if isinstance(src, int) and len(mons) > 1:
        return f"screen {src + 1}"
    return "the screen"


class TriggerRow(QFrame):
    """One trigger's card."""
    changed = Signal(object)             # row: a setting changed
    pictures_wanted = Signal(object)     # row: "+ Add pictures…" (files)
    paste_wanted = Signal(object)        # row: "Paste picture"
    cut_wanted = Signal(object)          # row: "Cut from window…"
    picture_swap = Signal(object, int)   # row, index: swap that picture for another file
    picture_removed = Signal(object, int)  # row, index
    sound_file_wanted = Signal(object)   # row: "Choose a sound file…"
    window_wanted = Signal(object)       # row: "Pick a window…"
    hear = Signal(str)                   # a sound chip was clicked: play that sound id
    test = Signal(object)
    remove = Signal(object)

    def __init__(self, t: Trigger, sounds: list[tuple[str, str]],
                 screens: list[Monitor] = ()):
        super().__init__()
        self.setObjectName("card")
        self.t = t
        self.missing: list[str] = []    # its sounds that are no longer in the library
        self.fallback = False           # its own screen isn't there: the default is watched
        self.note: tuple[str, str] | None = None   # (text, tone) from watching: not open…
        self._screens = 0               # how many screens there are
        self._mons: list[Monitor] = []
        self._sounds: list[tuple[str, str]] = []   # the sounds as last given
        v = QVBoxLayout(self)
        v.setContentsMargins(12, 8, 12, 10)
        v.setSpacing(6)

        top = QHBoxLayout()
        top.setSpacing(10)
        self.strip = Strip()
        self.strip.setToolTip("The pictures to look for: any of them showing up plays the sound")
        self.strip.picture_clicked.connect(lambda i: self.picture_swap.emit(self, i))
        self.strip.picture_removed.connect(lambda i: self.picture_removed.emit(self, i))
        top.addWidget(self.strip, 0, Qt.AlignTop)
        names = QVBoxLayout()
        names.setSpacing(4)
        self.name = QLineEdit(t.name)
        self.name.setMinimumWidth(50)
        self.name.setPlaceholderText("Name, e.g. Rare spawn")
        self.name.setMaxLength(60)
        self.name.editingFinished.connect(self._on_name)
        names.addWidget(self.name)
        self.state = QLabel()
        self.state.setObjectName("hint")
        self.state.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        names.addWidget(self.state)
        names.addStretch(1)
        top.addLayout(names, 1)
        self.chk_on = QCheckBox("On")
        self.chk_on.setToolTip("Watch for this trigger (untick to keep it but pause it)")
        self.chk_on.setChecked(t.enabled)
        self.chk_on.toggled.connect(self._on_enabled)
        top.addWidget(self.chk_on, 0, Qt.AlignTop)
        self.btn_del = QPushButton("✕")
        self.btn_del.setObjectName("small")
        self.btn_del.setFixedWidth(26)
        self.btn_del.setToolTip("Delete this trigger")
        self.btn_del.clicked.connect(lambda: self.remove.emit(self))
        top.addWidget(self.btn_del, 0, Qt.AlignTop)
        v.addLayout(top)

        row = Flow(gap=8)
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
        v.addLayout(row)

        # "Play", the chips (one per sound), "+ Add sound…", the Play mode, "Ring", the
        # test button: a wrapping row, rebuilt by _layout_sounds when the chips change
        self.sounds_row = Flow(gap=6)
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
        self.chk_ring = QCheckBox("Ring until stopped")
        self.chk_ring.setToolTip("Keep playing the sound over and over until you stop it "
                                 "(in this window, from the tray icon or the notification) — "
                                 "for when you're away from the keyboard")
        self.chk_ring.setChecked(t.ring)
        self.chk_ring.toggled.connect(self._on_ring)
        self.btn_test = QPushButton()
        self.btn_test.setToolTip("Play now, as the trigger would, to check it")
        icons.set_icon(self.btn_test, "play", size=14)
        self.btn_test.clicked.connect(lambda: self.test.emit(self))
        v.addLayout(self.sounds_row)

        row = Flow(gap=10)
        self.where = WideCombo(min_width=120)
        self.where.setToolTip("Where to look for the pictures: a game window (watched even "
                              "while other windows cover it, but not while it's minimized) "
                              "or a whole screen. “Same as below” is the choice at the "
                              "bottom of the window.")
        no_wheel(self.where)
        self.where.activated.connect(self._on_where)
        self.where_box = labelled("Look in", self.where)
        row.addWidget(self.where_box)
        self.delay = QDoubleSpinBox()
        self.delay.setRange(0.0, 60.0)
        self.delay.setDecimals(1)
        self.delay.setSingleStep(0.5)
        self.delay.setSuffix(" s")
        self.delay.setValue(t.delay)
        self.delay.setToolTip("How long after a picture shows up to play the sound "
                              "(0 = straight away)")
        row.addWidget(labelled("Wait", self.delay))
        self.cooldown = QDoubleSpinBox()
        self.cooldown.setRange(0.0, 600.0)
        self.cooldown.setDecimals(0)
        self.cooldown.setSingleStep(1.0)
        self.cooldown.setSuffix(" s")
        self.cooldown.setValue(t.cooldown)
        self.cooldown.setToolTip("After playing, ignore this trigger for this long. Its "
                                 "picture also has to go away before it can play again.")
        row.addWidget(labelled("Not again for", self.cooldown))
        self.threshold = QSpinBox()
        self.threshold.setObjectName("stepper")   # arrows like Wait / Not again for
        self.threshold.setRange(30, 99)
        self.threshold.setSuffix(" %")
        self.threshold.setValue(round(t.threshold * 100))
        self.threshold.setToolTip("How alike the picture must be to count. Lower it if the "
                                  "picture is missed, raise it if it plays by mistake — "
                                  "the live number on the right helps.")
        self.live = QLabel("—")
        self.live.setMinimumWidth(64)
        self.live.setToolTip("How well it matches right now (the best of its pictures)")
        match = labelled("Match", self.threshold)
        match.layout().addWidget(self.live)
        row.addWidget(match)
        v.addLayout(row)
        for w in (self.delay, self.cooldown, self.threshold):
            no_wheel(w)
            w.valueChanged.connect(self._on_numbers)

        self._flash = QTimer(self)
        self._flash.setSingleShot(True)
        self._flash.timeout.connect(self._update_state)
        self.set_sounds(sounds)
        self.set_screens(list(screens))
        self.refresh_pictures()
        self._update_state()

    # ------------------------------------------------------------------ view
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
                  self.btn_test):
            self.sounds_row.addWidget(w)
        self.sounds_row.invalidate()

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
        fill_sources(self.where, mons, t.window, t.monitor, "Same as below")
        self.fallback = (t.window is None and t.monitor is not None
                         and not 0 <= t.monitor < len(mons))
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
        hit = score >= self.t.threshold
        self.live.setText(f"now {pct}%")
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

    def _update_state(self):
        t = self.t
        n = len(t.sounds)
        if not t.images:
            text, tone = "No picture yet — Cut from window…, Add pictures… or Paste", "warn"
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
            wait = f"{t.delay:g} s after it shows up" if t.delay else "as soon as it shows up"
            how = "Rings until stopped" if t.ring else "Plays"
            if n > 1:
                what = {"random": f"one of its {n} sounds at random",
                        "order": f"its {n} sounds in turn",
                        "all": f"all {n} sounds at once"}[t.pick]
                text = f"{how}: {what}, {wait}"
            else:
                text = f"{how} {wait}"
            tone = ""
        self.state.setText(text)
        theme.set_tone(self.state, tone)

    # ------------------------------------------------------------------ edits
    def _on_name(self):
        name = self.name.text().strip() or "Trigger"
        if name != self.t.name:
            self.t.name = name
            self.changed.emit(self)

    def _on_enabled(self, on: bool):
        self.t.enabled = on
        self.changed.emit(self)

    def _on_ring(self, on: bool):
        self.t.ring = on
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
        if isinstance(data, WindowRef):
            return
        m = data if isinstance(data, int) and not isinstance(data, bool) else None
        if m == t.monitor and t.window is None:
            return
        t.window, t.monitor = None, m
        self.note = None
        self.set_screens(self._mons)
        self.changed.emit(self)

    def _on_numbers(self, _v=None):
        t = self.t
        t.delay = round(self.delay.value(), 1)
        t.cooldown = float(self.cooldown.value())
        t.threshold = self.threshold.value() / 100
        self._update_state()
        self.changed.emit(self)


class TriggersTab(QWidget):
    """The list of triggers, the on / off switch and the watcher behind them.
    `library` is the sounds.Library on offer, `player` the player.Player they go to."""
    active_changed = Signal(bool)       # watching or not
    fired = Signal(object)              # a Trigger just went off (its sound started)
    ringing_changed = Signal()          # a sound started or stopped ringing
    _fired = Signal(str)                # from the watcher thread

    def __init__(self, cfg, save_cb, library, player):
        super().__init__()
        self.cfg, self._save, self.library, self.player = cfg, save_cb, library, player
        if not isinstance(cfg.screen, dict):
            cfg.screen = {}
        s = cfg.screen
        self.triggers: list[Trigger] = []
        for d in s.get("triggers", []) if isinstance(s.get("triggers"), list) else []:
            t = Trigger.from_raw(d)
            if t is not None and len(self.triggers) < MAX_TRIGGERS:
                self.triggers.append(t)
        self.rows: dict[str, TriggerRow] = {}
        self._mons: list[Monitor] = []      # the screens as last listed
        self._fell_back: frozenset[str] = frozenset()   # watcher.fell_back as last seen
        self._gray: dict[str, tuple[float, Picture]] = {}   # picture path -> (mtime, picture)
        self._gen = 0                   # bumped to drop sounds still waiting to play
        self._bag = ShuffleBag()        # "Random": each trigger's sounds, each once per round
        self._order: dict[str, int] = {}   # "In order": each trigger's next sound
        self.watcher = screenwatch.Watcher(self._fired.emit)
        self._fired.connect(self._on_fired)
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
                        "the sound (or rings until you stop it) the moment it appears. It "
                        "only looks: it never clicks, types or touches the game.")
        hv.itemAt(0).widget().setWordWrap(True)
        self.hint = hv.itemAt(1).widget()
        self.warn = hint_label("")
        theme.set_tone(self.warn, "warn")
        self.warn.setVisible(False)
        hv.addWidget(self.warn)
        v.addWidget(head)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.list = QWidget()
        self.list_layout = QVBoxLayout(self.list)
        self.list_layout.setContentsMargins(0, 0, 0, 0)
        self.list_layout.setSpacing(6)
        self.empty = hint_label("No triggers yet. Pick your game window below, then click "
                                "Cut picture… and drag a box around the thing to watch for.")
        self.empty.setAlignment(Qt.AlignCenter)
        self.list_layout.addWidget(self.empty)
        self.list_layout.addStretch(1)
        self.scroll.setWidget(self.list)
        v.addWidget(self.scroll, 1)

        f = QFrame()
        f.setObjectName("transport")
        h = Flow(f, gap=8)
        h.setContentsMargins(10, 8, 12, 8)
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
        h.addWidget(self.btn_cut)
        self.btn_add = QPushButton("Add picture…")
        self.btn_add.setToolTip("A new trigger from a picture file (PNG, JPG…)")
        icons.set_icon(self.btn_add, "plus")
        self.btn_add.clicked.connect(self.add_from_file)
        h.addWidget(self.btn_add)
        self.btn_paste = QPushButton("Paste")
        self.btn_paste.setToolTip("A new trigger from the picture you copied (Win+Shift+S "
                                  "cuts a piece of the screen)")
        icons.set_icon(self.btn_paste, "image")
        self.btn_paste.clicked.connect(self.add_from_clipboard)
        h.addWidget(self.btn_paste)
        self.cb_where = WideCombo(min_width=140)
        self.cb_where.setToolTip("Where triggers that say “Same as below” look: your game's "
                                 "window, or a whole screen")
        self.cb_where.activated.connect(self._on_where)
        no_wheel(self.cb_where)
        h.addWidget(labelled("Look in", self.cb_where))
        # six characters ("100 ms") when there's room, just enough for them when the
        # window is small
        self.cb_interval = narrow(WideCombo(min_width=110), 6)
        for ms in INTERVALS_MS:
            label = f"{ms} ms" + (" (every frame)" if ms == 16 else "")
            self.cb_interval.addItem(label, ms)
        self.cb_interval.setCurrentIndex(self.cb_interval.findData(interval))
        self.cb_interval.setToolTip("How often to look. Faster reacts sooner but uses more of "
                                    "your processor; 100 ms is a tenth of a second.")
        self.cb_interval.currentIndexChanged.connect(self._on_interval)
        no_wheel(self.cb_interval)
        every = labelled("Check every", self.cb_interval)
        self.lbl_interval = every.layout().itemAt(0).widget()
        h.addWidget(every)
        v.addWidget(f)

        ok, why = screenwatch.supported()
        if not ok:
            self.warn.setText(why)
            self.warn.setVisible(True)
            self.btn_watch.setEnabled(False)
        self._fill_sources()
        for t in self.triggers:
            self._add_row(t)
        self.poll = QTimer(self)
        self.poll.timeout.connect(self._poll)
        self._label_watch()
        if ok and s.get("on") and self.triggers:
            self.btn_watch.setChecked(True)    # it was on when the app last closed

    # ------------------------------------------------------------------ the default
    def _saved_default(self) -> int | WindowRef:
        s = self.cfg.screen
        ref = WindowRef.from_raw(s.get("window"))
        if ref is not None:
            return ref
        mon = s.get("monitor", 0)
        return mon if isinstance(mon, int) and not isinstance(mon, bool) else 0

    def set_default(self, src: int | WindowRef):
        """Where triggers without their own window / screen look."""
        self.watcher.set_default(src)
        if isinstance(src, WindowRef):
            self.cfg.screen["window"] = src.to_raw()
        else:
            self.cfg.screen["window"] = None
            self.cfg.screen["monitor"] = src
        self._save()
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

    def _pick_for(self, row: TriggerRow):
        ref = self.pick_window(row.t.window)
        if ref is not None:
            row.t.window, row.t.monitor = ref, None
            row.note = None
            row.set_screens(self._mons)
            self._store()

    # ------------------------------------------------------------------ watching
    def showEvent(self, ev):
        super().showEvent(ev)
        self._fill_sources()      # screens may have been plugged in or out

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
            for row in self.rows.values():
                row.show_score(None)
                row.set_note(None)
        if remember:
            self.cfg.screen["on"] = on
            self._save()
        self._label_watch()
        self._show_warning()
        self.active_changed.emit(on)

    def _label_watch(self):
        self.btn_watch.setText("Watching" if self.is_active() else "Start watching")

    def cancel_pending(self):
        """Drop sounds that are still waiting out their delay (switched off)."""
        self._gen += 1

    def stop_ringing(self):
        self.player.stop_all()
        self.ringing_changed.emit()

    def shutdown(self):
        self.poll.stop()
        self.watcher.stop()
        self.cancel_pending()

    def _sync(self):
        """Hand the watcher the triggers that can fire, pictures loaded and grey."""
        items = []
        for t in self.triggers:
            if not (t.enabled and t.images and self._playable(t)):
                continue
            pics = [p for p in map(self._picture, t.images) if p is not None]
            if pics:
                items.append(Watched(t.id, pics, t.threshold, t.cooldown, source=t.source))
        self.watcher.set_items(items)

    def _picture(self, path: str) -> Picture | None:
        try:
            mtime = Path(path).stat().st_mtime
        except OSError:
            return None
        got = self._gray.get(path)
        if got is not None and got[0] == mtime:
            return got[1]
        pic = load_picture(path)
        if pic is not None:
            self._gray[path] = (mtime, pic)
        return pic

    def _playable(self, t: Trigger) -> list[str]:
        """The trigger's sounds that are still in the library, in its order."""
        have = self.library.ids()
        return [sid for sid in t.sounds if sid in have]

    def _on_fired(self, tid: str):
        t = next((t for t in self.triggers if t.id == tid), None)
        if t is None or not self.is_active() or not self._playable(t):
            return
        gen = self._gen
        if t.delay > 0:
            row = self.rows.get(tid)
            if row is not None:
                row.flash(f"Seen! Playing in {t.delay:g} s…", int(t.delay * 1000) + 1500)
            QTimer.singleShot(int(t.delay * 1000), self, lambda: self._fire(tid, gen))
        else:
            self._fire(tid, gen)

    def _fire(self, tid: str, gen: int):
        t = next((t for t in self.triggers if t.id == tid), None)
        if gen != self._gen or t is None or not t.enabled:
            return
        if self._play_trigger(t):
            log.info("trigger %r matched", t.name)
            row = self.rows.get(tid)
            if row is not None:
                row.flash("Ringing!" if t.ring else "Played!", 4000)
            self.fired.emit(t)

    def _play_trigger(self, t: Trigger, test: bool = False) -> list[str]:
        """Play the trigger's sound(s) the way its Play setting says: one at random
        (a shuffle bag: each once before any repeats, never twice running), the next
        in turn, or all of them; ringing (over and over) when it's set to, except for a
        test. Sounds no longer in the library are skipped. Returns what played."""
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
            self.player.stop_tag(t.id)      # one ring per trigger, not a pile of them
        played = [sid for sid in chosen
                  if self.player.play(self.library.load(sid), loop=ring, tag=t.id)]
        if ring and played:
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
            row.set_note(self._note(w.where.get(tid)))
        if not self.isVisible():
            return
        for tid, row in self.rows.items():
            row.show_score(w.scores.get(tid))
        self._show_warning()

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
                t.enabled and t.images and t.sounds for t in self.triggers):
            why = "Nothing to watch for yet: each trigger needs a picture and a sound."
        self.warn.setText(why)
        self.warn.setVisible(bool(why))

    def _on_interval(self, _i: int):
        ms = self.cb_interval.currentData()
        self.watcher.interval = ms / 1000
        self.cfg.screen["interval_ms"] = ms
        self._save()

    def _fill_sources(self):
        """List the screens again: the "Look in" at the bottom (the default) and each
        card's own. A change while watching is passed on to the watcher."""
        mons = screenwatch.monitors()
        d = self.watcher.default
        fill_sources(self.cb_where, mons, d if isinstance(d, WindowRef) else None,
                     d if isinstance(d, int) else 0)
        for row in self.rows.values():
            row.set_screens(mons)
        if mons != self._mons and self.watcher.running:
            self.watcher.rescan()
        self._mons = mons

    # ------------------------------------------------------------------ the list
    def sounds_changed(self):
        sounds = self.library.listing()
        for row in self.rows.values():
            row.set_sounds(sounds)

    def _add_row(self, t: Trigger) -> TriggerRow:
        row = TriggerRow(t, self.library.listing(), self._mons)
        row.changed.connect(lambda _r: self._store())
        row.pictures_wanted.connect(self._add_picture_files)
        row.paste_wanted.connect(self._paste_picture)
        row.cut_wanted.connect(self._cut_picture)
        row.picture_swap.connect(self._change_picture)
        row.picture_removed.connect(self._remove_picture)
        row.sound_file_wanted.connect(self._choose_sound_file)
        row.window_wanted.connect(self._pick_for)
        row.hear.connect(lambda sid: self.player.play(self.library.load(sid)))
        row.test.connect(lambda r: self._play_trigger(r.t, test=True))
        row.remove.connect(self._remove)
        self.rows[t.id] = row
        self.list_layout.insertWidget(self.list_layout.count() - 1, row)
        self.empty.setVisible(False)
        return row

    def _store(self):
        self.cfg.screen["triggers"] = [t.to_raw() for t in self.triggers]
        self._save()
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
                    sounds=[DEFAULT_SOUND])
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
        for i, img in enumerate(imgs):
            name = names[i] if i < len(names) else f"Picture {len(t.images) + 1}"
            if at is None and len(t.images) >= MAX_PICTURES:
                left_out = len(imgs) - i
                break
            pic, why = self._check_picture(img)
            if pic is None:
                refused.append((name, *why))
                continue
            try:
                path = save_picture(img, picture_name(t))
            except OSError as e:
                refused.append((name, "Couldn't keep the picture", str(e)))
                continue
            if at is not None and 0 <= at < len(t.images):
                old, t.images[at] = t.images[at], path
                delete_picture(old)
                self._gray.pop(old, None)
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
        if w > sw or h > sh:
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
        return dlg.piece if dlg.exec() else None

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

    def _change_picture(self, row: TriggerRow, index: int = 0):
        """Swap one of the trigger's pictures for a file."""
        path, _ = QFileDialog.getOpenFileName(self, "Picture to look for", str(Path.home()),
                                              f"Pictures ({PICTURE_EXTS});;All files (*)")
        if path and self._add_pictures(row.t, [QImage(path)], [Path(path).name], at=index):
            self._store()

    def _remove_picture(self, row: TriggerRow, index: int):
        t = row.t
        if not 0 <= index < len(t.images):
            return
        path = t.images.pop(index)
        delete_picture(path)
        self._gray.pop(path, None)
        row.refresh_pictures()
        self._store()

    def _choose_sound_file(self, row: TriggerRow):
        exts = " ".join(f"*{e}" for e in sorted(AUDIO_EXTS))
        path, _ = QFileDialog.getOpenFileName(self, "Sound to play", str(Path.home()),
                                              f"Audio ({exts});;All files (*)")
        if not path:
            return
        try:
            sid = self.library.add_file(path)
        except OSError as e:
            QMessageBox.warning(self, "Can't use that sound", str(e))
            return
        if sid not in row.t.sounds and len(row.t.sounds) < MAX_SOUNDS:
            row.t.sounds.append(sid)
        self.sounds_changed()
        self._store()

    def _remove(self, row: TriggerRow):
        t = row.t
        self.triggers = [x for x in self.triggers if x.id != t.id]
        self.rows.pop(t.id, None)
        self._bag.forget(t.id)
        self._order.pop(t.id, None)
        self.player.stop_tag(t.id)
        self.list_layout.removeWidget(row)
        row.setParent(None)   # gone from the list now, not when the event loop gets to it
        row.deleteLater()
        for path in t.images:
            delete_picture(path)
            self._gray.pop(path, None)
        self.empty.setVisible(not self.triggers)
        self._store()
        self.ringing_changed.emit()
        if not self.triggers and self.is_active():
            self.set_watching(False)
