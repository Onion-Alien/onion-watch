"""Onion Watch's engine: watch a screen or one window for pictures you picked (a
rare spawn's name plate, a queue-pop banner, a "YOU DIED") and say when one appears.

A screen is captured with Windows' Desktop Duplication (DXGI, over ctypes:
`DupGrabber`), which also sees fullscreen games; where that isn't available it
falls back to plain GDI (`Grabber`), which sees borderless and windowed games but
can come out black for exclusive-fullscreen ones (`Watcher.black` says so). A
window is captured on its own (onionwatch.windows.WindowGrabber), so it's still
seen while other windows cover it. Either way the picture is sampled at about
twice a working width of a few hundred pixels, then turned grey and averaged down
2x2. Each picture is shrunk by the same factor and found with normalised
cross-correlation, all of it done with FFTs: the frame's spectrum is worked out
once per check and shared by every picture (and every size of it), each picture's
once per size of the area it's looked in (`Frame`, `Pattern`). A match scores the
same whatever the game's brightness, and nothing is downloaded or installed.
Transparent parts of a picture are left out of the comparison (`match(..., mask)`),
so a cut-out icon matches whatever is behind it.

A match only holds within a few percent of the size a picture was cut at, so with
"any size" (`Watched.any_size`) each picture is also looked for at the sizes the
game would draw it at now: scaled from the size of the window or screen it was cut
from (`Watched.cuts`) to the size being watched, by height and by width, which
covers a game cut fullscreen and played in a window. Sizes nothing predicts (an
in-game UI scale, a picture from before sizes were kept) are swept for, a couple of
sizes a check, the triggers taking turns (SWEEPERS); one found is kept (`Look`). At
any size but its own a picture and the frame are both softened a little first
(BLUR), as a game drawing something at another size doesn't draw a resized copy of
it.

Watching is kept to about CPU_SHARE of the computer's processor, so it doesn't cost
a game frames: when the checks take longer than that allows (a slow computer, a lot
of pictures, a game using every core) they're spaced out further than `interval`.
A 1080p screen with one picture costs a few milliseconds per check.

`Gate` decides when a score is a new appearance: it fires once when a picture shows
up, then waits for it to go away before it can fire again (and never sooner than
the trigger's cooldown), so a death screen that stays up for five seconds plays
its sound once.

Each trigger can name what it's looked for in: a screen (an index into
monitors()) or a window (`WindowRef`); the rest use the default. `Watcher` keeps
one capture per screen or window in use and grabs each every tick, so triggers
on two game windows and a second monitor all work at once.

A trigger can hold several pictures (up to MAX_PICTURES): every one is matched
each tick, its live score is the best of them, and any one of them reaching the
threshold counts as the trigger showing up. The pictures are shrunk once, when
they change or the capture's size does, never per tick.
"""
from __future__ import annotations

import ctypes
import logging
import math
import os
import sys
import threading
import time
import uuid
from ctypes import wintypes
from dataclasses import asdict, dataclass, field

import numpy as np

from onionwatch.imgops import (binary_erosion, gaussian_filter, irfft2, next_fast_len, rfft2,
                              zoom_linear)

log = logging.getLogger(__name__)

WORK_WIDTH = 480        # the screen is shrunk to about this wide before matching
MIN_SIDE = 12           # ...but never so far that a picture's short side drops below this
MAX_ZOOM = 2            # ...nor ever kept above this many times WORK_WIDTH (small pictures)
MASK_MIN = 16           # a cut-out with fewer opaque pixels than this once shrunk is unreliable
# ...and softened (see BLUR) it needs this many: a few dozen blurred pixels of a
# slim figure correlate with almost anything (a cut-out game model scored 0.97 in
# an empty scene; under a few hundred, 0.75 in many, too high to re-arm). Below it,
# that size is matched sharp, where the figure keeps several times as many
SOFT_MASK_MIN = 400
# "any size": a picture is looked for from SIZES[0] to SIZES[1] times the size it
# was cut at. A game drawing a picture at another size doesn't give a resized copy
# of it (text especially is drawn afresh), so at any size but the one it was cut at
# the picture and the frame are both softened by BLUR px first, for pictures at
# least BLUR_MIN_SIDE px each way (at the size they're matched). That keeps a match
# within SAME of the right size scoring about 0.85-0.95 where it would drop to 0.5,
# so sizes that close count as one. The sweep steps SWEEP_STEP apart, and a step
# scoring within PROMISING of the threshold is tried again either side of it.
SIZES = (0.5, 2.0)
SAME = 0.025
SWEEP_STEP = 1.06
SWEEP_PER_CHECK = 2     # sizes a trigger sweeps on its turn
# triggers that get a turn to sweep, per capture per check: the ones that waited
# longest. Sweeping is most of the work for a picture that isn't showing, so with
# dozens of triggers on, each sweeping every check would space the checks out by
# seconds (see CPU_SHARE); taking turns costs the same however many there are
SWEEPERS = 2
SWEEP_MIN_SIDE = 6      # ...skipping those that shrink a picture below this
PROMISING = 0.15
SWEEP_DONE = 0.9        # a match scoring less may be at a size a little off: keep sweeping
BLUR = 1.5
BLUR_MIN_SIDE = 16
MAX_FOUND = 3           # sizes the sweep found kept per picture
SPECTRA_MB = 48         # at most this much of the pictures' spectra is kept between checks
CPU_SHARE = 0.01        # watching uses about this share of the whole processor, at most
# A match is judged on grey, which can't tell a green slime from a red one, or a
# wooden crate from a metal one once softened. So a place scoring within TINT_NEAR
# of the threshold (the best PEAKS places of each picture and size) also has its
# colours compared with the picture's: the hue of each of TINT_GRID x TINT_GRID
# cells (tint(); brightness doesn't change a hue, so a darker scene still passes,
# and cells darker than TINT_DARK have too little colour to say). A gap past
# TINT_OK (a colour grade over a whole scene makes about 0.15) takes the score
# down, to nothing TINT_SPAN further on.
TINT_GRID = 4
TINT_NEAR = 0.2
PEAKS = 3
TINT_DARK = 0.06
TINT_OK = 0.2
TINT_SPAN = 0.2
CORES = os.cpu_count() or 1
REARM_MARGIN = 0.08     # a match must fall this far below the threshold to count as gone
FLAT_STD = 2 / 255      # screen windows flatter than this never match (blank areas)
BLACK_LEVEL = 3 / 255   # a whole frame darker than this is a capture that can't see the game
INTERVALS_MS = (16, 33, 50, 100, 250, 500)
DEFAULT_INTERVAL_MS = 100
RETRY_S = 1.0           # how often a lost capture is tried again
GIVE_UP_S = 20.0        # ...and how long before the whole capture is set up afresh
WINDOW_RETRY_S = 2.0    # how often a window that isn't open (or was closed) is looked for
DUP_RETRY_S = 30.0     # how often a screen on the GDI fallback tries duplication again
UNSEEN_S = 5.0         # a capture giving nothing this long (and UNSEEN_GRABS grabs) is said
UNSEEN_GRABS = 3       # ...to be one that can't be seen (`Watcher.unseen`)
MAX_SCREENS = 64        # a trigger's saved screen index beyond this is nonsense
MAX_PICTURES = 100      # pictures one trigger can look for (extras in a config are dropped)
MAX_SOUNDS = 100        # ...and sounds it can play
PICKS = ("random", "order", "all")   # Trigger.pick: which of its sounds play when it fires
MAX_SOURCES = 16        # windows and screens one trigger can look in
# Trigger.mode: what counts as the trigger going off
#   appear  one of its pictures shows up (the first kind there was)
#   vanish  its picture goes away, having been seen
#   change  something changes in its area
#   still   nothing changes in its area for `hold` seconds (a game stuck or idle)
#   colour  the share of its area in one colour goes below (or above) `level`: a
#           health bar running low
MODES = ("appear", "vanish", "change", "still", "colour")
PICTURE_MODES = ("appear", "vanish")
DIFF_LEVEL = 10 / 255   # a pixel that moved more than this counts as changed
CHANGE_GAP = 0.5        # "change" / "still" compare the area with how it was this long ago
COLOUR_TOL = 0.12       # a pixel this close (each of R, G, B, 0..1) counts as the colour
LEVEL_MARGIN = 0.03     # a level must move back this far past its line to count as over
MAX_HOLD = 3600.0       # seconds: the longest "must last" / "still for"
# Trigger.stop: what stops a ringing trigger, besides the Stop button
#   moves   anything moves in its area once it has settled (you're back and
#           playing), or it goes away
#   gone    it goes away: the picture is gone, the bar filled up again...
#   focus   you switch to its window (alt-tab back to the game); for a screen, to
#           any other window than the one in front when it started
#   input   the mouse or keyboard is touched (the UI checks that, not the watcher)
#   manual  only Stop
STOPS = ("moves", "gone", "focus", "input", "manual")
STOP_MOVE = 0.02        # "moves": this share of the area changing stops the ringing
STOP_SETTLE = 0.5       # ...once it has stood still this long (a fade-in doesn't count)
STOP_LEAST = 1.0        # seconds a ring always lasts, so it's heard at least once


class CaptureLost(OSError):
    """The capture can't be brought back by itself (raised from grab()): close the
    grabber and open a new one."""


def _ids(*values, limit: int) -> list[str]:
    """The non-empty strings in `values` (each a string or a list of them), each once,
    in order, at most `limit` of them: a trigger's pictures or sounds as saved."""
    out: list[str] = []
    for v in values:
        for s in ([v] if isinstance(v, str) else v if isinstance(v, list) else []):
            if isinstance(s, str) and s and s not in out:
                out.append(s)
                if len(out) >= limit:
                    return out
    return out


@dataclass(frozen=True)
class WindowRef:
    """A window to watch, as it's remembered: the program's file name ("game.exe",
    lower case) and the window's title. Several open windows can fit (two copies of
    the same game): `nth` picks one of them, counting from the copy started first.
    Found again by onionwatch.windows.find, also after a restart."""
    exe: str = ""
    title: str = ""
    nth: int = 0
    # every copy that fits instead of one (all of a multi-boxer's game windows,
    # also ones started later): the watcher looks in each of them
    every: bool = False

    @property
    def label(self) -> str:
        name = self.title or self.exe or "Window"
        if self.every:
            return f"{name} (every copy)"
        return name + (f" (copy {self.nth + 1})" if self.nth else "")

    @classmethod
    def from_raw(cls, d) -> WindowRef | None:
        if not isinstance(d, dict):
            return None
        exe, title, nth = d.get("exe", ""), d.get("title", ""), d.get("nth", 0)
        if not isinstance(exe, str) or not isinstance(title, str) or not (exe or title):
            return None
        if not isinstance(nth, int) or isinstance(nth, bool) or not 0 <= nth < 64:
            nth = 0
        every = d.get("every") is True
        return cls(exe[:260].lower(), title[:260], 0 if every else nth, every)

    def to_raw(self) -> dict:
        d = {"exe": self.exe, "title": self.title, "nth": self.nth}
        if self.every:
            d["every"] = True      # older versions don't know it: they watch the first copy
        return d


@dataclass
class Trigger:
    """The pictures to watch for and what to play when one shows up (stored in
    Config.screen["triggers"]). Older versions kept one picture in `image` and one
    sound in `sound`; those load as one-item lists and are saved back beside the
    lists (to_raw) so a config still opens in one of them."""
    id: str
    name: str = "Trigger"
    # the pictures, PNGs inside library.APP_DIR / "triggers": any of them showing
    # up fires the trigger
    images: list[str] = field(default_factory=list)
    sounds: list[str] = field(default_factory=list)   # sound ids from the board
    pick: str = "random"      # which of them play: "random" (a shuffle bag), "order", "all"
    delay: float = 0.0        # seconds between the match and the sound
    cooldown: float = 3.0     # seconds before this trigger can play again
    threshold: float = 0.80   # how alike (0..1) the screen must be to count as a match
    enabled: bool = True
    # a sound file picked here that's still being added to the board: its fingerprint,
    # so the trigger takes the new sound's id once the import finishes
    pending: str = ""
    # where to look: screens (indexes into monitors()) and windows (WindowRef), each
    # watched on its own, any of them counting. Empty: the default picked at the
    # bottom of the window. A screen that isn't plugged in falls back to the default.
    sources: list = field(default_factory=list)
    # keep playing its sound over and over until it's stopped (an alarm), not just once
    ring: bool = False
    # ...and what stops the ringing by itself (STOPS)
    stop: str = "moves"
    # what counts as it going off (MODES), and for the modes without pictures how
    # much: "change" / "still" the share of the area that moved, "colour" the share
    # in `colour` ("#rrggbb"), going `below` it (or above)
    mode: str = "appear"
    level: float = 0.05
    below: bool = True
    colour: str = ""
    # the part of each window / screen to look in, as fractions of it (x, y, w, h):
    # it follows the window when it's resized. None: all of it
    region: tuple[float, float, float, float] | None = None
    # it must go on this long before it counts (a flicker doesn't); "still": how
    # long nothing may change
    hold: float = 0.0
    # stay quiet while its window is the one in front (you're playing it)
    unfocused: bool = False
    # find its pictures at other sizes too (cut fullscreen, played in a window)
    any_size: bool = True

    @property
    def source(self) -> int | WindowRef | None:
        """The first place it's looked in, or None for the default."""
        return self.sources[0] if self.sources else None

    @property
    def windows(self) -> list[WindowRef]:
        return [s for s in self.sources if isinstance(s, WindowRef)]

    @property
    def screens(self) -> list[int]:
        return [s for s in self.sources if not isinstance(s, WindowRef)]

    @property
    def window(self) -> WindowRef | None:
        """Its first window (what older versions knew: one window a trigger)."""
        return next(iter(self.windows), None)

    @window.setter
    def window(self, ref: WindowRef | None):
        """Look in just this window (None: in no window, keeping its screens)."""
        self.sources = [ref] if ref is not None else self.screens

    @property
    def monitor(self) -> int | None:
        return next(iter(self.screens), None)

    @monitor.setter
    def monitor(self, m: int | None):
        """Look on just this screen, unless it has windows (they win, as they did)."""
        if m is None:
            self.sources = self.windows
        elif not self.windows:
            self.sources = [m]

    @property
    def uses_pictures(self) -> bool:
        return self.mode in PICTURE_MODES

    @property
    def number(self) -> float:
        """The number it's judged by: `threshold` for a picture, else `level`."""
        return self.threshold if self.uses_pictures else self.level

    @property
    def rgb(self) -> tuple[float, float, float] | None:
        return hex_rgb(self.colour)

    @property
    def image(self) -> str:
        """The first picture ("" without one): what older code and the saved `image` see.
        Setting it makes that the only picture."""
        return self.images[0] if self.images else ""

    @image.setter
    def image(self, path: str):
        self.images = [path] if path else []

    @property
    def sound(self) -> str:
        return self.sounds[0] if self.sounds else ""

    @sound.setter
    def sound(self, sid: str):
        self.sounds = [sid] if sid else []

    @classmethod
    def from_raw(cls, d: dict) -> Trigger | None:
        if not isinstance(d, dict) or not isinstance(d.get("id"), str) or not d["id"]:
            return None
        t = cls(id=d["id"])
        t.sources = _sources(d)
        t.images = _ids(d.get("image"), d.get("images"), limit=MAX_PICTURES)
        t.sounds = _ids(d.get("sound"), d.get("sounds"), limit=MAX_SOUNDS)
        if d.get("pick") in PICKS:
            t.pick = d["pick"]
        if d.get("mode") in MODES:
            t.mode = d["mode"]
        if d.get("stop") in STOPS:
            t.stop = d["stop"]
        t.region = _region(d.get("region"))
        if hex_rgb(d.get("colour")) is not None:
            t.colour = d["colour"].lower()
        for k, default in list(vars(t).items()):
            if k in ("sources", "images", "sounds", "pick", "mode", "stop", "region", "colour"):
                continue
            v = d.get(k, default)
            if isinstance(default, bool):
                ok = isinstance(v, bool)
            elif isinstance(default, float):
                ok = isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)
            else:
                ok = isinstance(v, type(default))
            if ok:
                setattr(t, k, float(v) if isinstance(default, float) else v)
        t.delay = min(max(t.delay, 0.0), 60.0)
        t.cooldown = min(max(t.cooldown, 0.0), 600.0)
        t.threshold = min(max(t.threshold, 0.3), 0.99)
        t.level = min(max(t.level, 0.01), 0.99)
        t.hold = min(max(t.hold, 0.0), MAX_HOLD)
        return t

    def to_raw(self) -> dict:
        """What's saved: the fields, plus the first picture and sound under the old
        names so an older version of the app still shows something for it, and the
        places looked in as `screens` and `windows`, with the first of each under
        the old `monitor` and `window` (an older version watches just that one)."""
        d = asdict(self)
        del d["sources"]
        d["screens"] = self.screens
        d["windows"] = [w.to_raw() for w in self.windows]
        d["monitor"] = self.monitor
        d["window"] = self.window.to_raw() if self.window is not None else None
        d["region"] = list(self.region) if self.region is not None else None
        d["image"], d["sound"] = self.image, self.sound
        return d

    def copy(self, new_id: str) -> Trigger:
        """The same trigger under another id (its pictures still to be copied)."""
        t = Trigger.from_raw({**self.to_raw(), "id": new_id})
        assert t is not None
        return t


def _screen(m) -> int | None:
    return m if isinstance(m, int) and not isinstance(m, bool) and 0 <= m < MAX_SCREENS \
        else None


def _sources(d: dict) -> list:
    """Where a saved trigger looks: `screens` and `windows` as this version saves
    them, else an older version's one `window` (which won over its `monitor`)."""
    out: list = []
    screens, wins = d.get("screens"), d.get("windows")
    if isinstance(screens, list) or isinstance(wins, list):
        cand = [_screen(m) for m in (screens if isinstance(screens, list) else [])]
        cand += [WindowRef.from_raw(w) for w in (wins if isinstance(wins, list) else [])]
    else:
        ref = WindowRef.from_raw(d.get("window"))
        cand = [ref if ref is not None else _screen(d.get("monitor"))]
    for c in cand:
        if c is not None and c not in out and len(out) < MAX_SOURCES:
            out.append(c)
    return out


def _region(r) -> tuple[float, float, float, float] | None:
    """A saved area (x, y, w, h as fractions), kept inside the window, or None."""
    if not isinstance(r, (list, tuple)) or len(r) != 4 or not all(
            isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)
            for v in r):
        return None
    x, y = min(max(float(r[0]), 0.0), 1.0), min(max(float(r[1]), 0.0), 1.0)
    w, h = min(float(r[2]), 1.0 - x), min(float(r[3]), 1.0 - y)
    if w < 0.002 or h < 0.002:
        return None
    if x == 0 and y == 0 and w >= 1 and h >= 1:
        return None                     # all of it
    return (round(x, 5), round(y, 5), round(w, 5), round(h, 5))


def hex_rgb(text) -> tuple[float, float, float] | None:
    """"#rrggbb" -> (r, g, b) in 0..1, or None."""
    if not isinstance(text, str) or len(text) != 7 or text[0] != "#" or not all(
            c in "0123456789abcdefABCDEF" for c in text[1:]):
        return None
    v = int(text[1:], 16)
    return ((v >> 16) & 255) / 255, ((v >> 8) & 255) / 255, (v & 255) / 255


# --------------------------------------------------------------------------- matching

def to_gray(bgra: np.ndarray) -> np.ndarray:
    """(h, w, 4) BGRA / (h, w, 3) BGR uint8 -> (h, w) float32 luma in 0..1."""
    b, g, r = (bgra[..., i].astype(np.float32) for i in range(3))
    return (0.114 / 255) * b + (0.587 / 255) * g + (0.299 / 255) * r


class Frame:
    """A grey screen (or part of one) prepared for matching, shared by every picture
    checked against it: its spectrum, and its square's for each window's brightness
    and contrast, are worked out once, when first needed. Its mean is taken off
    first: a match doesn't care, and the sums stay small enough for float32."""

    def __init__(self, gray: np.ndarray):
        self.s = gray.astype(np.float32)
        self.s -= np.float32(self.s.mean(dtype=np.float64))
        h, w = self.s.shape
        # the FFTs' size: a correlation over the frame's size is enough, as a
        # picture's valid places never wrap around it
        self.n = (next_fast_len(h), next_fast_len(w))
        self._spec: np.ndarray | None = None
        self._spec2: np.ndarray | None = None
        self._sums: dict = {}
        self._totals: tuple | None = None
        self._soft: Frame | None = None

    def soft(self) -> Frame:
        """The frame softened by BLUR px and, having lost its finest detail, at half
        size: a quarter of the work for every picture matched on it (kept: they
        share it)."""
        if self._soft is None:
            self._soft = Frame(gaussian_filter(self.s, BLUR, step=2))
        return self._soft

    @property
    def shape(self) -> tuple[int, int]:
        return self.s.shape

    def spectrum(self) -> np.ndarray:
        if self._spec is None:
            self._spec = rfft2(self.s, self.n)
        return self._spec

    def corr(self, spec: np.ndarray, pspec: np.ndarray, shape: tuple[int, int]) -> np.ndarray:
        """A correlation over every place a (h, w) picture fits whole."""
        (sh, sw), (th, tw) = self.s.shape, shape
        return irfft2(spec * pspec, self.n, (sh - th + 1, sw - tw + 1))

    def sums(self, p: Pattern) -> tuple[np.ndarray, np.ndarray]:
        """The sum and the sum of squares under the picture's opaque part in each
        place: kept for the frame, since pictures of one size share their box."""
        got = self._sums.get(p.key)
        if got is None:
            if p.box:
                got = self.box_sums(p.shape)
            else:
                if self._spec2 is None:
                    self._spec2 = rfft2(self.s * self.s, self.n)
                m = p.spectra(self.n)[1]
                got = (self.corr(self.spectrum(), m, p.shape),
                       self.corr(self._spec2, m, p.shape))
            self._sums[p.key] = got
        return got

    def box_sums(self, shape: tuple[int, int]) -> tuple[np.ndarray, np.ndarray]:
        """sums() for a picture with no see-through part, from the frame's running
        totals (an integral image of it and of its square, made once): four lookups
        a place instead of two more transforms, and exact."""
        if self._totals is None:
            s = self.s.astype(np.float64)
            self._totals = (_integral(s), _integral(s * s))
        th, tw = shape
        return tuple((ii[th:, tw:] - ii[:-th, tw:] - ii[th:, :-tw] + ii[:-th, :-tw]
                      ).astype(np.float32) for ii in self._totals)


def _integral(a: np.ndarray) -> np.ndarray:
    """`a`'s integral image, a row and a column of zeros in front: [y, x] is the sum
    of a[:y, :x]."""
    ii = np.zeros((a.shape[0] + 1, a.shape[1] + 1))
    ii[1:, 1:] = a.cumsum(0).cumsum(1)
    return ii


class Pattern:
    """A picture made ready to be looked for: its mean taken off (under its opaque
    part), its transparent parts zeroed, and, when `keep` is set, its spectrum kept
    for the frame size it's matched against (a capture's area keeps its size, so
    that's worked out once, not every check)."""

    def __init__(self, tmpl: np.ndarray, mask: np.ndarray | None = None, keep: bool = False,
                 soft: tuple[int, int] | None = None, kept: float = 1.0):
        th, tw = tmpl.shape
        # `soft`: made like Frame.soft(), matched there, and this big at full size
        self.soft = soft is not None
        self.size = soft or (th, tw)
        self.flat = FLAT_STD * min(kept, 1.0)   # a window this flat is blank (see Look.pattern)
        self.shape = (th, tw)
        self.box = mask is None or bool(mask.all())
        m = np.ones((th, tw)) if self.box else mask.astype(np.float64)
        self.count = float(m.sum())
        t = tmpl.astype(np.float64)
        t = (t - float((t * m).sum()) / max(self.count, 1.0)) * m
        self.norm = math.sqrt(float((t * t).sum()))
        self.ok = th >= 2 and tw >= 2 and self.count >= 4 and self.norm >= 1e-6
        self.t = t.astype(np.float32)
        self.m = None if self.box else m.astype(np.float32)
        self.key = ("box", th, tw) if self.box else self
        self.keep = keep
        self._spec: tuple | None = None       # (FFT size, picture's, mask's)

    def spectra(self, n: tuple[int, int]) -> tuple[np.ndarray, np.ndarray | None]:
        """(the picture's spectrum, its mask's or None for a box) at FFT size `n`,
        conjugated: multiplied by a frame's, they make a correlation."""
        if self._spec is not None and self._spec[0] == n:
            return self._spec[1], self._spec[2]
        t = np.conj(rfft2(self.t, n))
        m = None if self.box else np.conj(rfft2(self.m, n))
        if self.keep:
            self._spec = (n, t, m)
        return t, m


def find(f: Frame, p: Pattern) -> tuple[float, tuple[int, int]]:
    """match() for a prepared frame and picture (a soft one on the frame's soft
    copy, its place given at full size)."""
    return find_peaks(f, p)[0]


def find_peaks(f: Frame, p: Pattern, n: int = 1, floor: float = 1.0
               ) -> list[tuple[float, tuple[int, int]]]:
    """The best place, then (up to `n` in all) the next best ones scoring at least
    `floor`, each at least half the picture away from those before it."""
    k = 2 if p.soft else 1
    if p.soft:
        f = f.soft()
    (th, tw), (sh, sw) = p.shape, f.shape
    if not p.ok or th > sh or tw > sw:
        return [(0.0, (0, 0))]
    num = f.corr(f.spectrum(), p.spectra(f.n)[0], p.shape)
    s1, s2 = f.sums(p)
    var = s2 - s1 * s1 * np.float32(1 / p.count)   # count * each window's variance
    ok = var > np.float32(p.count * p.flat * p.flat)
    np.sqrt(var, out=var, where=ok)
    score = np.zeros(num.shape, np.float32)
    np.divide(num, var, out=score, where=ok)
    out = []
    while True:
        i = int(np.argmax(score))
        y, x = divmod(i, score.shape[1])
        sc = float(min(score.flat[i] / p.norm, 1.0))
        if out and sc < floor:
            break
        out.append((sc, (k * x, k * y)))
        if len(out) >= n or sc < floor:
            break
        score[max(0, y - th // 2):y + th // 2 + 1, max(0, x - tw // 2):x + tw // 2 + 1] = 0
    return out


def match(screen: np.ndarray | Frame, tmpl: np.ndarray,
          mask: np.ndarray | None = None) -> tuple[float, tuple[int, int]]:
    """Best normalised cross-correlation of `tmpl` anywhere in `screen` (2-D float
    grey, or a Frame of it): (score in -1..1, (x, y) of its top-left corner). 0 when
    it can't match at all (bigger than the screen, or a flat picture). `mask` (the
    picture's shape, true = counts) leaves out its transparent parts: each window's
    brightness and contrast are taken under the mask too."""
    return find(screen if isinstance(screen, Frame) else Frame(screen), Pattern(tmpl, mask))


def work_scale(screen_w: int, tmpl_sides: list[int]) -> float:
    """How much to shrink the screen (and every picture) before matching: down to
    about WORK_WIDTH, but keeping the smallest picture at least MIN_SIDE px. A tiny
    picture can't push it past MAX_ZOOM x WORK_WIDTH: every check would get slow
    (a whole 4K screen matched at full size takes over a second)."""
    if screen_w <= 0:
        return 1.0
    scale = WORK_WIDTH / screen_w
    cap = MAX_ZOOM * scale
    if tmpl_sides:
        scale = max(scale, MIN_SIDE / max(min(tmpl_sides), 1))
    return min(1.0, scale, cap)


def shrink_mask(mask: np.ndarray, scale: float) -> np.ndarray:
    """A picture's opaque part at `scale`. Shrunk pixels that were wholly opaque match
    best (the others blend in whatever is behind the picture), but a thin outline has
    next to none of them: then the cut-off is eased, down to half opaque, until there
    are enough to compare."""
    m = resize(mask, scale)
    loose = m >= 0.5
    enough = max(MASK_MIN, int(loose.sum()) // 3)
    for cut in (0.99, 0.75):
        keep = m >= cut
        if int(keep.sum()) >= enough:
            return keep
    return loose


def shrink(gray: np.ndarray, scale: float) -> np.ndarray:
    """Area-average `gray` by `scale` (<= 1), the way the HALFTONE screen shrink does,
    so a picture and the screen it was cut from end up alike
    (the screen's shrink is close to an area average too: see Grabber)."""
    if scale >= 0.999:
        return gray.astype(np.float32)
    h, w = gray.shape
    nh, nw = max(1, round(h * scale)), max(1, round(w * scale))
    ys = np.linspace(0, h, nh + 1).astype(int)
    xs = np.linspace(0, w, nw + 1).astype(int)
    ii = np.zeros((h + 1, w + 1))
    ii[1:, 1:] = gray.astype(np.float64).cumsum(0).cumsum(1)
    tot = ii[ys[1:]][:, xs[1:]] - ii[ys[:-1]][:, xs[1:]] - ii[ys[1:]][:, xs[:-1]] + \
        ii[ys[:-1]][:, xs[:-1]]
    area = np.outer(np.diff(ys), np.diff(xs)).clip(min=1)
    return (tot / area).astype(np.float32)


def resize(gray: np.ndarray, scale: float) -> np.ndarray:
    """shrink(), or for `scale` over 1 (a picture looked for bigger than it was cut)
    a smooth enlargement."""
    if scale <= 1.001:
        return shrink(gray, scale)
    h, w = gray.shape
    nh, nw = max(1, round(h * scale)), max(1, round(w * scale))
    return zoom_linear(gray.astype(np.float32), (nh, nw))


def near(a: float, b: float) -> bool:
    """Two sizes close enough that a match at one holds at the other."""
    return abs(math.log(a / b)) < SAME


def sizes_for(cut: tuple[int, int] | None, now: tuple[int, int]) -> list[float]:
    """The sizes (times the size it was cut at) a picture cut from something `cut`
    (w, h) big is drawn at in something `now` big: the same size (a game that draws
    it the same whatever its window), and scaled with the height or the width (one
    that scales it with the window). [1.0] when `cut` isn't known."""
    out = [1.0]
    if cut and min(cut) > 0 and min(now) > 0:
        for f in (now[1] / cut[1], now[0] / cut[0]):
            if SIZES[0] <= f <= SIZES[1] and not any(near(f, g) for g in out):
                out.append(f)
    return out


def tint(rgb: np.ndarray, mask: np.ndarray | None = None) -> np.ndarray | None:
    """A picture's colours in brief: the mean colour (0..1 RGB) of each of TINT_GRID
    x TINT_GRID cells, (G, G, 3), NaN where a cut-out has nothing. None when it's
    too small to tell."""
    h, w = rgb.shape[:2]
    g = TINT_GRID
    if h < g or w < g:
        return None
    ys = np.linspace(0, h, g + 1).astype(int)[:-1]
    xs = np.linspace(0, w, g + 1).astype(int)[:-1]
    wt = np.ones((h, w), np.float32) if mask is None else mask.astype(np.float32)
    rgb = rgb[..., :3].astype(np.float32) * wt[..., None]
    sums = np.add.reduceat(np.add.reduceat(rgb, ys, 0), xs, 1)
    n = np.add.reduceat(np.add.reduceat(wt, ys, 0), xs, 1)
    area = np.outer(np.diff(np.append(ys, h)), np.diff(np.append(xs, w)))
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where((n >= 0.5 * area)[..., None], sums / n[..., None], np.nan)


def tint_gap(want: np.ndarray, got: np.ndarray) -> float:
    """How far apart two tints' hues are: per cell, the difference of their shares
    of red, green and blue (0 to 2), over the cells bright enough in both to have a
    colour; the mean of the worst quarter of them (a picture is often mostly
    background, which would water a difference down). A dimmer copy is 0 apart."""
    a, b = want.reshape(-1, 3), got.reshape(-1, 3)
    lum = np.array([0.299, 0.587, 0.114])
    with np.errstate(invalid="ignore", divide="ignore"):
        ok = (np.minimum(a @ lum, b @ lum) >= TINT_DARK)
        d = np.abs(a / a.sum(1, keepdims=True) - b / b.sum(1, keepdims=True)).sum(1)
    d = d[ok & ~np.isnan(d)]
    if not d.size:
        return 0.0
    return float(np.sort(d)[-max(1, d.size // 4):].mean())


def tint_factor(gap: float) -> float:
    return min(1.0, max(0.0, 1.0 - (gap - TINT_OK) / TINT_SPAN))


# nearest the size it was cut at first: small changes are the likeliest
SWEEP = sorted((f for f in (SWEEP_STEP ** i for i in range(-40, 41)) if SIZES[0] <= f <= SIZES[1]),
               key=lambda f: abs(math.log(f)))


class Look:
    """One picture as a capture looks for it: a Pattern for each size it's looked for
    every check (`pats`: the size it was cut at first, then with "any size" the sizes
    sizes_for() predicts and ones the sweep found), and with "any size" the sweep's
    place (`todo`, the sizes left to try, and `next`)."""

    def __init__(self, gray: np.ndarray, mask: np.ndarray | None, scale: float,
                 sizes: list[float], sweep: bool, found: list[float] = (),
                 tint: np.ndarray | None = None):
        self.gray, self.mask, self.scale = gray, mask, scale
        self.tint = tint                        # its colours (see tint()), if known
        self.pats: list[tuple[float, Pattern]] = []
        self.found: list[float] = []
        for f in sizes:
            self._add(f)
        self.todo = SWEEP if sweep else []
        self.next = 0
        for f in found:
            self.keep(f)

    def pattern(self, f: float) -> Pattern:
        """The picture at `f` times the size it was cut at, shrunk like the frame,
        and softened at any size but its own (see BLUR)."""
        s = self.scale * f
        g = resize(self.gray, s)
        m = None if self.mask is None else shrink_mask(self.mask, s)
        if near(f, 1.0) or min(g.shape) < BLUR_MIN_SIDE:
            return Pattern(g, m)
        # like Frame.soft(): half size, softened as much (a half-size shrink has
        # softened it a little already)
        gray, hm = self.gray, None
        if self.mask is not None:
            # a cut-out: its see-through part filled with its own mean so softening
            # doesn't smear black into its edge, and a pixel less of it compared
            # (the frame's softened edge has whatever is behind the picture in it)
            gray = np.where(self.mask, self.gray, np.float32(self.gray[self.mask].mean()))
            hm = binary_erosion(shrink_mask(self.mask, s / 2))
            if int(hm.sum()) < SOFT_MASK_MIN:
                return Pattern(g, m)
        soft = gaussian_filter(resize(gray, s / 2), BLUR / 2)
        # softening takes contrast away, the frame's as much as the picture's: a window
        # counts as flat by what it had before
        was = g if m is None else g[m]
        now = soft if hm is None else soft[hm]
        return Pattern(soft, hm, soft=g.shape,
                       kept=float(now.std()) / max(float(was.std()), 1e-6))

    def _add(self, f: float, p: Pattern | None = None) -> bool:
        if not SIZES[0] - 1e-9 <= f <= SIZES[1] + 1e-9 or any(near(f, g) for g, _p in self.pats):
            return False
        self.pats.append((f, p or self.pattern(f)))
        return True

    def keep(self, f: float, p: Pattern | None = None):
        """Look for it at this size every check from now on (the sweep found it
        there). Only the latest MAX_FOUND found sizes are kept."""
        if not self._add(f, p):
            return
        self.found.append(f)
        if len(self.found) > MAX_FOUND:
            old = self.found.pop(0)
            self.pats = [(g, q) for g, q in self.pats if g != old]

    def sweep_sizes(self, n: int) -> list[float]:
        """The next `n` sizes to sweep: ones not already looked for every check, and
        not so small the picture is lost."""
        out: list[float] = []
        side = min(self.gray.shape) * self.scale
        for _ in range(len(self.todo)):
            if len(out) >= n:
                break
            f = self.todo[self.next % len(self.todo)]
            self.next += 1
            if side * f >= SWEEP_MIN_SIDE and not any(near(f, g) for g, _p in self.pats):
                out.append(f)
        return out


@dataclass
class Gate:
    """Turns a stream of yes / no / in-between answers ("is it showing?") into "it
    just happened" moments: it fires once when the answer turns yes (and has stayed
    yes for `hold` seconds), then waits for a clear no before it can fire again,
    and never sooner than the cooldown. A yes during the cooldown is used up
    without firing, so something that stays up isn't played the moment the
    cooldown ends. `mode` is the Trigger.mode it was made for."""
    armed: bool = True
    last: float = -math.inf
    since: float | None = None      # when the current yes began
    mode: str = "appear"

    def step(self, state: bool | None, now: float, cooldown: float, hold: float = 0.0) -> bool:
        if state:
            if not self.armed:
                return False
            if self.since is None:
                self.since = now
            if now - self.since < hold:
                return False
            self.armed, self.since = False, None
            if now - self.last < cooldown:
                return False
            self.last = now
            return True
        self.since = None
        if state is False:
            self.armed = True
        return False

    def update(self, score: float, now: float, threshold: float, cooldown: float) -> bool:
        """step() for a picture's match score ("appear")."""
        return self.step(verdict("appear", score, threshold), now, cooldown)


@dataclass
class Quieter:
    """A ringing trigger waiting for what stops it by itself (Trigger.stop: "moves",
    "gone" or "focus"), judged in the place it went off. step() is given each check
    of that place: the trigger's area, its verdict there and what's in front (for a
    window: whether it is; for a screen: the window in front), and says when to stop."""
    how: str
    source: object
    since: float                    # when the ringing started
    ref: np.ndarray | None = None   # "moves": the area once it stood still
    last: np.ndarray | None = None  # ...the area as this still stretch began
    still_since: float = 0.0
    front0: object = None           # "focus" on a screen: the window in front at first
    seen: bool = False

    def step(self, area: np.ndarray | None, state: bool | None, front, now: float) -> bool:
        first, self.seen = not self.seen, True
        if first:
            self.front0 = front
        if now - self.since < STOP_LEAST:
            return False
        if self.how == "focus":
            if isinstance(self.source, WindowRef):
                return front is True
            return not first and front != self.front0 and bool(front)
        if state is False:              # it's over: gone, or the bar is back
            return True
        if self.how != "moves" or area is None:
            return False
        if self.ref is not None:
            if self.ref.shape == area.shape:
                return changed_share(area, self.ref) >= STOP_MOVE
            self.ref = None             # the window was resized: settle again
        if self.last is None or self.last.shape != area.shape \
                or changed_share(area, self.last) >= STOP_MOVE:
            self.last, self.still_since = area.copy(), now
        elif now - self.still_since >= STOP_SETTLE:
            self.ref = self.last
        return False


def new_gate(mode: str) -> Gate:
    """A gate for `mode`. "vanish" starts disarmed: it has to be seen before it can
    go away."""
    return Gate(armed=mode != "vanish", mode=mode)


def verdict(mode: str, score: float, level: float, below: bool = True) -> bool | None:
    """Whether a trigger's condition holds for `score` (True), clearly doesn't
    (False) or is in between (None: a score wobbling around the line doesn't fire
    it again and again)."""
    if mode == "appear":
        return True if score >= level else False if score < level - REARM_MARGIN else None
    if mode == "vanish":
        return True if score < level - REARM_MARGIN else False if score >= level else None
    if mode == "change":
        return True if score >= level else False if score < level / 2 else None
    if mode == "still":
        return score < level
    if below:                   # "colour"
        return True if score < level else False if score >= level + LEVEL_MARGIN else None
    return True if score >= level else False if score < level - LEVEL_MARGIN else None


def region_box(region, shape: tuple[int, int],
               least: tuple[int, int] = (2, 2)) -> tuple[int, int, int, int]:
    """The pixels (y0, y1, x0, x1) of an area (fractions x, y, w, h; None: all) in a
    frame of `shape`, grown to at least `least` (h, w) around its middle so a
    picture always fits, and kept inside the frame."""
    h, w = shape
    if region is None:
        return 0, h, 0, w
    x, y, rw, rh = region
    x0, x1 = math.floor(x * w), math.ceil((x + rw) * w)
    y0, y1 = math.floor(y * h), math.ceil((y + rh) * h)

    def grow(a: int, b: int, need: int, size: int) -> tuple[int, int]:
        need = min(max(need, 2), size)
        if b - a < need:
            a -= (need - (b - a)) // 2
            a = min(max(a, 0), size - need)
            b = a + need
        return max(a, 0), min(b, size)
    y0, y1 = grow(y0, y1, least[0], h)
    x0, x1 = grow(x0, x1, least[1], w)
    return y0, y1, x0, x1


def changed_share(now: np.ndarray, before: np.ndarray) -> float:
    """How much of an area moved between two grey copies of it (0..1)."""
    if now.shape != before.shape or not now.size:
        return 0.0
    return float(np.count_nonzero(np.abs(now - before) > DIFF_LEVEL)) / now.size


def colour_share(rgb: np.ndarray, colour: tuple[float, float, float]) -> float:
    """How much of an (h, w, 3) RGB area is `colour`, give or take COLOUR_TOL (0..1)."""
    if not rgb.size:
        return 0.0
    near = (np.abs(rgb - np.asarray(colour, np.float32)) <= COLOUR_TOL).all(-1)
    return float(np.count_nonzero(near)) / near.size


@dataclass(frozen=True)
class Hit:
    """A trigger going off: where (the screen or window, one copy of it), the box
    it was seen in (fractions of that window / screen: the picture, or the area),
    and the score."""
    source: int | WindowRef
    box: tuple[float, float, float, float]
    score: float
    # the check's own small copy of the window then: (h, w) grey or (h, w, 3) RGB
    # uint8, for the history (kept in memory only, never saved)
    frame: np.ndarray | None = field(default=None, compare=False, repr=False)


# --------------------------------------------------------------------------- capture

def supported() -> tuple[bool, str]:
    if sys.platform != "win32":
        return False, "Onion Watch only works on Windows."
    return True, ""


@dataclass
class Monitor:
    left: int
    top: int
    width: int
    height: int
    primary: bool = False

    @property
    def label(self) -> str:
        return f"{self.width}×{self.height}" + ("  (main)" if self.primary else "")


def monitors() -> list[Monitor]:
    """The monitors in physical pixels, the main one first."""
    if sys.platform != "win32":
        return []
    user32 = ctypes.windll.user32
    found: list[Monitor] = []

    class MONITORINFO(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                    ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]

    proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HMONITOR, wintypes.HDC,
                              ctypes.POINTER(wintypes.RECT), wintypes.LPARAM)

    def cb(hmon, _hdc, _rect, _lp):
        mi = MONITORINFO()
        mi.cbSize = ctypes.sizeof(MONITORINFO)
        if user32.GetMonitorInfoW(hmon, ctypes.byref(mi)):
            r = mi.rcMonitor
            found.append(Monitor(r.left, r.top, r.right - r.left, r.bottom - r.top,
                                 bool(mi.dwFlags & 1)))
        return True

    try:
        user32.EnumDisplayMonitors(None, None, proc(cb), 0)
    except OSError:
        log.warning("listing monitors failed", exc_info=True)
    found.sort(key=lambda m: (not m.primary, m.left, m.top))
    return found


class _BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG),
                ("biHeight", wintypes.LONG), ("biPlanes", wintypes.WORD),
                ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
                ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD),
                ("biClrImportant", wintypes.DWORD)]


def gray_2x(bgra: np.ndarray) -> np.ndarray:
    """(2h, 2w, 4) BGRA uint8 -> (h, w) float32 luma in 0..1, each output pixel the
    average of a 2x2 block. Integer maths: a quarter the cost of float colour."""
    h, w = bgra.shape[0] // 2, bgra.shape[1] // 2
    x = bgra[:2 * h, :2 * w]
    y = x[..., 0] * np.uint16(29)                              # luma * 256
    y += x[..., 1] * np.uint16(150)
    y += x[..., 2] * np.uint16(77)
    s = y[0::2, 0::2].astype(np.uint32)
    s += y[1::2, 0::2]
    s += y[0::2, 1::2]
    s += y[1::2, 1::2]
    return s.astype(np.float32) * np.float32(1 / (256 * 4 * 255))


def pick(px: np.ndarray, ys: np.ndarray, xs: np.ndarray) -> np.ndarray:
    """px[ys][:, xs]: the rows, then the columns of those rows (a copy). A pixel of 4
    or 8 bytes is moved as one number, about three times quicker than channel by
    channel."""
    if px.ndim == 3 and px.strides[2] == px.itemsize:
        word = {4: np.uint32, 8: np.uint64}.get(px.shape[2] * px.itemsize)
        if word is not None and px.strides[1] == px.shape[2] * px.itemsize:
            return px.view(word)[ys][:, xs].view(px.dtype)
    return px[ys][:, xs]


# DXGI_FORMAT values a duplicated desktop comes in, and their bytes per pixel.
FMT_BGRA8, FMT_BGRX8 = 87, 88   # B8G8R8A8_UNORM / B8G8R8X8_UNORM: the usual SDR desktop
FMT_RGBA16F = 10                # R16G16B16A16_FLOAT: HDR ("advanced colour") on, scRGB linear
FMT_RGB10A2 = 24                # R10G10B10A2_UNORM: a 10-bit desktop
FRAME_FORMATS = {FMT_BGRA8: 4, FMT_BGRX8: 4, FMT_RGBA16F: 8, FMT_RGB10A2: 4}


def frame_view(rows: np.ndarray, fmt: int, width: int) -> np.ndarray:
    """The pixels of a mapped frame's rows ((h, pitch) uint8) one entry per pixel in the
    format's own type: (h, w, 4) uint8 BGRA for the 8-bit formats, (h, w, 4) float16
    RGBA for RGBA16F, (h, w) uint32 for RGB10A2. A view, no copy."""
    bpp = FRAME_FORMATS.get(fmt)
    if bpp is None:
        raise OSError(f"unsupported duplication format {fmt}")
    px = rows[:, :width * bpp]
    if fmt == FMT_RGBA16F:
        return px.view(np.float16).reshape(rows.shape[0], width, 4)
    if fmt == FMT_RGB10A2:
        return px.view(np.uint32).reshape(rows.shape[0], width)
    return px.reshape(rows.shape[0], width, 4)


def frame_gray(sample: np.ndarray, fmt: int, factor: int = 1) -> np.ndarray:
    """Pixels sampled from a duplicated frame (see frame_view for their shape) ->
    (h, w) float32 luma in 0..1 on the same scale as the pictures, which are 8-bit
    sRGB screenshots turned grey by to_gray. With `factor` 2 each output pixel is
    the average of a 2x2 block, as gray_2x does."""
    if fmt in (FMT_BGRA8, FMT_BGRX8):
        return gray_2x(sample) if factor == 2 else to_gray(sample)
    if fmt == FMT_RGBA16F:
        # scRGB: linear light, 1.0 is SDR white and highlights go above it. Clip to
        # SDR and put the sRGB curve back on, so grey matches an 8-bit screenshot.
        rgb = np.clip(sample[..., :3].astype(np.float32), 0.0, 1.0) ** (1 / 2.2)
    elif fmt == FMT_RGB10A2:
        # 10 bits each, R lowest; already gamma-encoded like the 8-bit desktop.
        u = sample.astype(np.uint32)
        rgb = np.stack([(u >> sh) & 1023 for sh in (0, 10, 20)], -1).astype(np.float32) / 1023
    else:
        raise OSError(f"unsupported duplication format {fmt}")
    y = 0.299 * rgb[..., 0] + 0.587 * rgb[..., 1] + 0.114 * rgb[..., 2]
    if factor == 2:
        h, w = y.shape[0] // 2, y.shape[1] // 2
        y = y[:2 * h, :2 * w].reshape(h, 2, w, 2).mean((1, 3), dtype=np.float32)
    return y.astype(np.float32)


def frame_rgb(sample: np.ndarray, fmt: int = FMT_BGRA8, factor: int = 1) -> np.ndarray:
    """frame_gray() in colour: (h, w, 3) float32 RGB in 0..1, sRGB like a screenshot.
    Only made for a capture with a "colour" trigger on it (Grabber.want_color)."""
    if fmt in (FMT_BGRA8, FMT_BGRX8):
        rgb = sample[..., 2::-1].astype(np.float32) * (1 / 255)
    elif fmt == FMT_RGBA16F:
        rgb = np.clip(sample[..., :3].astype(np.float32), 0.0, 1.0) ** (1 / 2.2)
    elif fmt == FMT_RGB10A2:
        u = sample.astype(np.uint32)
        rgb = np.stack([(u >> sh) & 1023 for sh in (0, 10, 20)], -1).astype(np.float32) / 1023
    else:
        raise OSError(f"unsupported duplication format {fmt}")
    if factor == 2:
        h, w = rgb.shape[0] // 2, rgb.shape[1] // 2
        rgb = rgb[:2 * h, :2 * w].reshape(h, 2, w, 2, 3).mean((1, 3), dtype=np.float32)
    return rgb.astype(np.float32)


class Grabber:
    """Copies one monitor, shrunk to (w, h), as grey (float32 0..1). The copy is
    taken at twice that size with GDI's plain pixel-dropping shrink (COLORONCOLOR:
    ~1 ms of CPU, where the smoother HALFTONE costs over 10) and each 2x2 block is
    then averaged, so thin text still shows. GDI handles belong to the thread that
    made them: create, use and close it on the watcher thread. `source` is the size
    in pixels of what's being copied (the monitor); `lost` is never set here."""

    SRCCOPY = 0x00CC0020
    COLORONCOLOR = 3
    lost = False
    fallback = False        # opened because duplication wasn't there (open_grabber)
    want_color = False      # also keep `color`, the same picture in RGB (frame_rgb)
    color: np.ndarray | None = None
    raw: tuple | None = None    # the last grab's pixels as sampled: (pixels, format, factor)

    def __init__(self, src: Monitor, w: int, h: int):
        self.src, self.w, self.h = src, w, h
        self.source = (src.width, src.height)
        self.factor = 2 if 2 * w <= src.width and 2 * h <= src.height else 1
        cw, ch = w * self.factor, h * self.factor
        self.cw, self.ch = cw, ch
        self.screen_dc = self.dc = self.bmp = self._old = None
        u, g = ctypes.windll.user32, ctypes.windll.gdi32
        self._u, self._g = u, g
        u.GetDC.restype = wintypes.HDC
        u.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
        g.CreateCompatibleDC.restype = wintypes.HDC
        g.CreateCompatibleDC.argtypes = [wintypes.HDC]
        g.CreateDIBSection.restype = wintypes.HBITMAP
        g.CreateDIBSection.argtypes = [wintypes.HDC, ctypes.c_void_p, wintypes.UINT,
                                       ctypes.POINTER(ctypes.c_void_p), wintypes.HANDLE,
                                       wintypes.DWORD]
        g.SelectObject.restype = wintypes.HGDIOBJ
        g.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
        g.DeleteObject.argtypes = [wintypes.HGDIOBJ]
        g.DeleteDC.argtypes = [wintypes.HDC]
        g.SetStretchBltMode.argtypes = [wintypes.HDC, ctypes.c_int]
        g.StretchBlt.argtypes = [wintypes.HDC] + [ctypes.c_int] * 4 + [wintypes.HDC] + \
            [ctypes.c_int] * 4 + [wintypes.DWORD]
        self.screen_dc = u.GetDC(None)
        self.dc = g.CreateCompatibleDC(self.screen_dc)
        bmi = _BITMAPINFOHEADER()
        bmi.biSize = ctypes.sizeof(_BITMAPINFOHEADER)
        bmi.biWidth, bmi.biHeight = cw, -ch        # top-down rows
        bmi.biPlanes, bmi.biBitCount = 1, 32
        bits = ctypes.c_void_p()
        if self.dc:
            self.bmp = g.CreateDIBSection(self.dc, ctypes.byref(bmi), 0, ctypes.byref(bits),
                                          None, 0)
        if not self.dc or not self.bmp or not bits.value:
            self.close()
            raise OSError("couldn't set up screen capture")
        self._old = g.SelectObject(self.dc, self.bmp)
        g.SetStretchBltMode(self.dc, self.COLORONCOLOR)
        buf = (ctypes.c_uint8 * (cw * ch * 4)).from_address(bits.value)
        self.pixels = np.frombuffer(buf, np.uint8).reshape(ch, cw, 4)

    def grab(self) -> np.ndarray | None:
        s = self.src
        if not self._g.StretchBlt(self.dc, 0, 0, self.cw, self.ch, self.screen_dc,
                                  s.left, s.top, s.width, s.height, self.SRCCOPY):
            return None
        self.color = frame_rgb(self.pixels, FMT_BGRA8, self.factor) if self.want_color else None
        self.raw = (self.pixels, FMT_BGRA8, self.factor)
        return gray_2x(self.pixels) if self.factor == 2 else to_gray(self.pixels)

    def resize(self, w: int, h: int):
        """Copy at a new size from now on."""
        self.close()
        self.__init__(self.src, w, h)

    def close(self):
        g, u = self._g, self._u
        if self._old:
            g.SelectObject(self.dc, self._old)
            self._old = None
        if self.bmp:
            g.DeleteObject(self.bmp)
            self.bmp = None
        if self.dc:
            g.DeleteDC(self.dc)
            self.dc = None
        if self.screen_dc:
            u.ReleaseDC(None, self.screen_dc)
            self.screen_dc = None


def _guid(text: str) -> ctypes.Array:
    """A COM interface id as the 16 bytes Windows expects."""
    return (ctypes.c_ubyte * 16).from_buffer_copy(uuid.UUID(text).bytes_le)


IID_IDXGIFactory1 = "770aae78-f26f-4dba-a829-253c83d1b387"
IID_IDXGIOutput1 = "00cddea8-939b-4b83-a340-a685226666cc"
IID_ID3D11Texture2D = "6f15aaf2-d208-4e89-9ab4-489535d34f9c"
DXGI_ERROR_NOT_FOUND = 0x887A0002
DXGI_ERROR_ACCESS_LOST = 0x887A0026
DXGI_ERROR_WAIT_TIMEOUT = 0x887A0027


def _hr(v: int) -> int:
    return v & 0xFFFFFFFF


class _COM:
    """A COM pointer called by vtable slot (the interfaces are only ever used here,
    so no type library is needed)."""

    def __init__(self):
        self.p = ctypes.c_void_p()

    def __bool__(self):
        return bool(self.p.value)

    def call(self, index: int, *args, restype=ctypes.c_long, argtypes=()):
        vtbl = ctypes.cast(self.p, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)))[0]
        fn = ctypes.WINFUNCTYPE(restype, ctypes.c_void_p, *argtypes)(vtbl[index])
        return fn(self.p, *args)

    def query(self, iid: str) -> _COM:
        out = _COM()
        hr = self.call(0, ctypes.byref(_guid(iid)), ctypes.byref(out.p),
                       argtypes=(ctypes.c_void_p, ctypes.c_void_p))
        if hr < 0:
            raise OSError(f"QueryInterface failed (0x{_hr(hr):08X})")
        return out

    def release(self):
        if self.p.value:
            self.call(2, restype=ctypes.c_ulong)
            self.p = ctypes.c_void_p()


class _OUTPUT_DESC(ctypes.Structure):
    _fields_ = [("DeviceName", wintypes.WCHAR * 32), ("DesktopCoordinates", wintypes.RECT),
                ("AttachedToDesktop", wintypes.BOOL), ("Rotation", ctypes.c_uint),
                ("Monitor", wintypes.HMONITOR)]


class _TEXTURE2D_DESC(ctypes.Structure):
    _fields_ = [("Width", ctypes.c_uint), ("Height", ctypes.c_uint),
                ("MipLevels", ctypes.c_uint), ("ArraySize", ctypes.c_uint),
                ("Format", ctypes.c_uint), ("SampleCount", ctypes.c_uint),
                ("SampleQuality", ctypes.c_uint), ("Usage", ctypes.c_uint),
                ("BindFlags", ctypes.c_uint), ("CPUAccessFlags", ctypes.c_uint),
                ("MiscFlags", ctypes.c_uint)]


class _MAPPED(ctypes.Structure):
    _fields_ = [("pData", ctypes.c_void_p), ("RowPitch", ctypes.c_uint),
                ("DepthPitch", ctypes.c_uint)]


class _OUTDUPL_DESC(ctypes.Structure):
    """DXGI_OUTDUPL_DESC: the mode the duplicated frames come in."""
    _fields_ = [("Width", ctypes.c_uint), ("Height", ctypes.c_uint),
                ("RefreshNum", ctypes.c_uint), ("RefreshDen", ctypes.c_uint),
                ("Format", ctypes.c_uint), ("ScanlineOrdering", ctypes.c_uint),
                ("Scaling", ctypes.c_uint), ("Rotation", ctypes.c_uint),
                ("DesktopImageInSystemMemory", wintypes.BOOL)]


_unknown_formats: set[int] = set()     # DXGI formats already reported (see _duplicate)

# DXGI_MODE_ROTATION -> np.rot90 turns that bring a duplicated frame upright. The
# frames of a rotated (portrait) output come in the panel's own orientation, so a
# 1080x1920 portrait desktop hands over 1920x1080 frames turned on their side.
# 0 (unspecified) and 1 (identity) need nothing.
FRAME_TURNS = {2: -1, 3: 2, 4: 1}      # 90: turn clockwise; 180; 270: anticlockwise


def upright(gray: np.ndarray, turns: int) -> np.ndarray:
    """A picture sampled from a duplicated frame, turned `turns` quarter turns
    (np.rot90's k) so it's the way the desktop shows it."""
    return np.ascontiguousarray(np.rot90(gray, turns)) if turns % 4 else gray


class DupGrabber:
    """Desktop Duplication (IDXGIOutputDuplication): the frames the graphics card
    shows, so fullscreen games are seen too, where GDI may only see black. Same
    interface as Grabber. Each frame is copied to a CPU-readable texture and sampled
    at twice (w, h), then averaged 2x2. Everything lives on the thread that made it.

    The frames are the size of the output's *current mode*, not of the desktop
    rectangle: a game in exclusive fullscreen at another resolution changes it (the
    duplication is lost and remade, and `source` follows), and a process that isn't
    DPI-aware is told a scaled-down rectangle. The staging texture and the sampling
    are laid out from the mode, since a copy between textures of different sizes is
    dropped without a word and the picture would just freeze or stay black.

    A rotated (portrait) output hands over frames in the panel's orientation: they
    are sampled as they come and the picture turned upright (FRAME_TURNS), so
    `source` and the pictures given out are always the way the desktop shows them.

    While the duplication is lost (a mode switch, the UAC or lock screen) grab()
    gives None and `lost` is set; it's tried again every RETRY_S. If that keeps
    failing for GIVE_UP_S, grab() raises CaptureLost so the owner starts over."""

    # vtable slots (IUnknown 0-2, IDXGIObject 3-6, ID3D11DeviceChild 3-6)
    FACTORY_ENUM_ADAPTERS1 = 12
    ADAPTER_ENUM_OUTPUTS = 7
    OUTPUT_GET_DESC = 7
    OUTPUT1_DUPLICATE = 22
    DUP_GET_DESC = 7
    DUP_ACQUIRE = 8
    DUP_RELEASE_FRAME = 14
    DEVICE_CREATE_TEXTURE2D = 5
    TEX_GET_DESC = 10               # ID3D11Texture2D::GetDesc
    CTX_MAP, CTX_UNMAP, CTX_COPY_RESOURCE = 14, 15, 47
    USAGE_STAGING, CPU_ACCESS_READ, MAP_READ = 3, 0x20000, 1
    turns = 0                       # FRAME_TURNS for the output's rotation
    want_color = False              # as Grabber's
    color: np.ndarray | None = None
    raw: tuple | None = None    # the last grab's pixels as sampled: (pixels, format, factor)

    def __init__(self, src: Monitor, w: int, h: int):
        self.src, self.w, self.h = src, w, h
        self.source = (src.width, src.height)     # the frames' size, upright; see _duplicate
        self._frame = self.source                 # ...as the frames come (see turns)
        self.factor = 1
        self.device, self.ctx, self.output1 = _COM(), _COM(), _COM()
        self.dup, self.staging = _COM(), _COM()
        self._mode: tuple[int, int, int] | None = None   # the staging texture's (w, h, format)
        self.last: np.ndarray | None = None
        self.lost = False
        self._lost_at = 0.0
        self._lost_since = 0.0
        try:
            self._open()
            for _ in range(5):          # the first real frame follows soon after opening
                if self.grab(timeout_ms=100) is not None:
                    break
        except Exception:
            self.close()
            raise

    def _open(self):
        dxgi, d3d = ctypes.windll.dxgi, ctypes.windll.d3d11
        factory = _COM()
        hr = dxgi.CreateDXGIFactory1(ctypes.byref(_guid(IID_IDXGIFactory1)),
                                     ctypes.byref(factory.p))
        if hr < 0:
            raise OSError(f"CreateDXGIFactory1 failed (0x{_hr(hr):08X})")
        try:
            adapter, output = self._find_output(factory)
        finally:
            factory.release()
        try:
            d3d.D3D11CreateDevice.argtypes = [
                ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p,
                ctypes.c_uint, ctypes.c_uint, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
            hr = d3d.D3D11CreateDevice(adapter.p, 0, None, 0, None, 0, 7,   # 7: SDK version
                                       ctypes.byref(self.device.p), None,
                                       ctypes.byref(self.ctx.p))
            if hr < 0:
                raise OSError(f"D3D11CreateDevice failed (0x{_hr(hr):08X})")
            self.output1 = output.query(IID_IDXGIOutput1)
        finally:
            adapter.release()
            output.release()
        self._duplicate()

    def _find_output(self, factory: _COM) -> tuple[_COM, _COM]:
        """The graphics card and output showing self.src (matched by position)."""
        s = self.src
        for i in range(16):
            adapter = _COM()
            hr = factory.call(self.FACTORY_ENUM_ADAPTERS1, i, ctypes.byref(adapter.p),
                              argtypes=(ctypes.c_uint, ctypes.c_void_p))
            if hr < 0:
                break
            for j in range(16):
                output = _COM()
                hr = adapter.call(self.ADAPTER_ENUM_OUTPUTS, j, ctypes.byref(output.p),
                                  argtypes=(ctypes.c_uint, ctypes.c_void_p))
                if hr < 0:
                    break
                d = _OUTPUT_DESC()
                output.call(self.OUTPUT_GET_DESC, ctypes.byref(d), argtypes=(ctypes.c_void_p,))
                r = d.DesktopCoordinates
                if ((r.left, r.top, r.right - r.left, r.bottom - r.top)
                        == (s.left, s.top, s.width, s.height)):
                    self.turns = FRAME_TURNS.get(int(d.Rotation), 0)
                    return adapter, output
                output.release()
            adapter.release()
        raise OSError("no graphics output shows that monitor")

    def _duplicate(self):
        """(Re)start the duplication and lay out the staging texture and the sampling
        for the mode its frames come in."""
        self.dup.release()
        hr = self.output1.call(self.OUTPUT1_DUPLICATE, self.device.p, ctypes.byref(self.dup.p),
                               argtypes=(ctypes.c_void_p, ctypes.c_void_p))
        if hr < 0:
            raise OSError(f"DuplicateOutput failed (0x{_hr(hr):08X})")
        d = _OUTDUPL_DESC()
        self.dup.call(self.DUP_GET_DESC, ctypes.byref(d), restype=None,
                      argtypes=(ctypes.c_void_p,))
        if d.Rotation > 4 or d.Width < 2 or d.Height < 2:
            raise OSError(f"unusable duplication mode {d.Width}x{d.Height} "
                          f"rotation {d.Rotation}")
        if d.Rotation > 1:
            self.turns = FRAME_TURNS[int(d.Rotation)]
        mode = (int(d.Width), int(d.Height), int(d.Format))
        if mode[2] not in FRAME_FORMATS:
            if mode[2] not in _unknown_formats:
                _unknown_formats.add(mode[2])
                log.info("desktop duplication gives frames in DXGI format %d, which isn't "
                         "supported: falling back to GDI", mode[2])
            raise OSError(f"unsupported duplication format {mode[2]}")
        if mode != self._mode:
            self._make_staging(mode)

    def _make_staging(self, mode: tuple[int, int, int]):
        """A CPU-readable copy of the frames in `mode` (w, h, DXGI format). The mode the
        duplication announces isn't always the one its frames come in: an HDR desktop
        announces 16-bit float yet hands over 8-bit BGRA textures, and CopyResource
        between different formats silently copies nothing. So grab() checks every
        frame's own description and calls this again when it differs."""
        self.staging.release()
        desc = _TEXTURE2D_DESC(mode[0], mode[1], 1, 1, mode[2], 1, 0,
                               self.USAGE_STAGING, 0, self.CPU_ACCESS_READ, 0)
        hr = self.device.call(self.DEVICE_CREATE_TEXTURE2D, ctypes.byref(desc), None,
                              ctypes.byref(self.staging.p),
                              argtypes=(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p))
        if hr < 0:
            raise OSError(f"CreateTexture2D failed (0x{_hr(hr):08X})")
        self._mode = mode
        self._frame = mode[:2]
        self.source = mode[1::-1] if self.turns % 2 else mode[:2]
        self.last = None
        self._layout()

    def _layout(self):
        """Which frame pixels make up the (w, h) picture, at 2x where the frame allows.
        For a frame on its side that's an (h, w) sample, turned upright in grab()."""
        sw, sh = self._frame
        w, h = (self.h, self.w) if self.turns % 2 else (self.w, self.h)
        self.factor = n = 2 if 2 * w <= sw and 2 * h <= sh else 1
        self.ys = ((np.arange(h * n) + 0.5) * sh / (h * n)).astype(np.intp)
        self.xs = ((np.arange(w * n) + 0.5) * sw / (w * n)).astype(np.intp)

    def resize(self, w: int, h: int):
        """Give out (w, h) pictures from now on."""
        self.w, self.h = w, h
        self.last = None
        self._layout()

    def grab(self, timeout_ms: int = 0) -> np.ndarray | None:
        if not self.dup:
            now = time.monotonic()
            if now - self._lost_at < RETRY_S:
                return None
            self._lost_at = now
            try:
                self._duplicate()
            except OSError as e:
                if now - self._lost_since > GIVE_UP_S:
                    raise CaptureLost(f"screen capture lost ({e})") from e
                return None
            self.lost = False
        info = (ctypes.c_ubyte * 64)()              # DXGI_OUTDUPL_FRAME_INFO (48 bytes)
        res = _COM()
        hr = self.dup.call(self.DUP_ACQUIRE, timeout_ms, ctypes.byref(info), ctypes.byref(res.p),
                           argtypes=(ctypes.c_uint, ctypes.c_void_p, ctypes.c_void_p))
        code = _hr(hr)
        if code == DXGI_ERROR_WAIT_TIMEOUT:
            return self.last                        # nothing new on screen
        if code == DXGI_ERROR_ACCESS_LOST:
            # a display mode switch (a game going fullscreen), the UAC / lock screen
            self.dup.release()
            self.lost = True
            self._lost_at = self._lost_since = time.monotonic()
            return None
        if hr < 0:
            # the graphics card was reset or removed (a driver update or crash, a laptop
            # switching cards): only a new device can see the screen again
            raise CaptureLost(f"AcquireNextFrame failed (0x{code:08X})")
        # LastPresentTime 0: only the mouse moved, or the frame a new duplication
        # starts with. The picture is unchanged, so skip the copy, except for the
        # very first frame: on a screen where nothing moves (a static death screen,
        # a launcher) it's the only one carrying the picture, and it isn't blank.
        if int.from_bytes(bytes(info[:8]), "little", signed=True) == 0 and self.last is not None:
            res.release()
            self.dup.call(self.DUP_RELEASE_FRAME)
            return self.last
        try:
            tex = res.query(IID_ID3D11Texture2D)
            try:
                td = _TEXTURE2D_DESC()
                tex.call(self.TEX_GET_DESC, ctypes.byref(td), restype=None,
                         argtypes=(ctypes.c_void_p,))
                got = (int(td.Width), int(td.Height), int(td.Format))
                if got != self._mode:
                    if got[2] not in FRAME_FORMATS:
                        if got[2] not in _unknown_formats:
                            _unknown_formats.add(got[2])
                            log.info("desktop duplication frames come in DXGI format %d, "
                                     "which isn't supported: falling back to GDI", got[2])
                        raise CaptureLost(f"unsupported duplication format {got[2]}")
                    log.info("duplicated frames are %dx%d in DXGI format %d (the mode said "
                             "%dx%d format %d): reading them as they come", *got, *self._mode)
                    self._make_staging(got)
                self.ctx.call(self.CTX_COPY_RESOURCE, self.staging.p, tex.p, restype=None,
                              argtypes=(ctypes.c_void_p, ctypes.c_void_p))
            finally:
                tex.release()
        finally:
            res.release()
            self.dup.call(self.DUP_RELEASE_FRAME)
        m = _MAPPED()
        hr = self.ctx.call(self.CTX_MAP, self.staging.p, 0, self.MAP_READ, 0, ctypes.byref(m),
                           argtypes=(ctypes.c_void_p, ctypes.c_uint, ctypes.c_int,
                                     ctypes.c_uint, ctypes.c_void_p))
        if hr < 0:
            raise CaptureLost(f"Map failed (0x{_hr(hr):08X})")
        try:
            sw, rows = self._frame
            fmt = self._mode[2]
            pitch = m.RowPitch
            buf = (ctypes.c_uint8 * (rows * pitch)).from_address(m.pData)
            img = np.frombuffer(buf, np.uint8).reshape(rows, pitch)
            px = frame_view(img, fmt, sw)
            sample = pick(px, self.ys, self.xs)      # a copy, taken while mapped
        finally:
            self.ctx.call(self.CTX_UNMAP, self.staging.p, 0, restype=None,
                          argtypes=(ctypes.c_void_p, ctypes.c_uint))
        self.last = upright(frame_gray(sample, fmt, self.factor), self.turns)
        self.raw = (np.rot90(sample, self.turns) if self.turns % 4 else sample, fmt, self.factor)
        self.color = (upright(frame_rgb(sample, fmt, self.factor), self.turns)
                      if self.want_color else None)
        return self.last

    def close(self):
        for c in (self.staging, self.dup, self.output1, self.ctx, self.device):
            try:
                c.release()
            except OSError:
                log.debug("releasing a capture object failed", exc_info=True)


def open_grabber(src: Monitor, w: int, h: int, tries: int = 1):
    """Desktop Duplication where it works, else GDI. `tries` > 1 gives duplication a
    few goes (RETRY_S apart) before settling for GDI: right after a display mode
    switch it can fail for a moment, and GDI only sees black in fullscreen games."""
    err = None
    for i in range(max(1, tries)):
        try:
            return DupGrabber(src, w, h)
        except (OSError, AttributeError) as e:
            err = e
        if i + 1 < tries:
            time.sleep(RETRY_S)
    log.info("desktop duplication unavailable (%s): capturing with GDI", err)
    g = Grabber(src, w, h)
    g.fallback = True       # the watcher tries duplication again now and then
    return g


# --------------------------------------------------------------------------- watcher

Picture = tuple[np.ndarray, "np.ndarray | None"]   # grey 0..1, opaque mask (None: all of it)


@dataclass
class Watched:
    """A trigger as the watcher thread sees it: its pictures (full size, grey, each
    with the mask of its opaque part), where it's looked for, and what it's judged
    by. `threshold` is its mode's one number (Trigger.number); `sources` are its
    screens and windows (empty: the default), `source` the one place older code
    gives. Each place has its own Gate, so two game windows showing the same thing
    each go off once. With `any_size` its pictures are looked for at other sizes too
    (see Look); `cuts` holds the (w, h) each picture was cut from, or None. `tints`,
    when given, has a place's colours checked too before it counts (see TINT_OK)."""
    id: str
    pictures: list[Picture]
    threshold: float
    cooldown: float
    source: int | WindowRef | None = None
    sources: list = field(default_factory=list)
    mode: str = "appear"
    below: bool = True
    colour: tuple[float, float, float] | None = None
    region: tuple[float, float, float, float] | None = None
    hold: float = 0.0
    unfocused: bool = False
    any_size: bool = False
    cuts: list = field(default_factory=list)
    tints: list = field(default_factory=list)       # each picture's tint(), or None
    gates: dict = field(default_factory=dict)       # place -> its Gate

    def __post_init__(self):
        if not self.sources and self.source is not None:
            self.sources = [self.source]

    def gate_for(self, place) -> Gate:
        g = self.gates.get(place)
        if g is None or g.mode != self.mode:
            g = self.gates[place] = new_gate(self.mode)
        return g

    @property
    def uses_pictures(self) -> bool:
        return self.mode in PICTURE_MODES

    def cut(self, i: int) -> tuple[int, int] | None:
        return self.cuts[i] if i < len(self.cuts) else None

    def sizes(self, i: int, now: tuple[int, int]) -> list[float]:
        """The sizes picture `i` is looked for at every check in something `now` big."""
        return sizes_for(self.cut(i), now) if self.any_size else [1.0]

    def sides_at(self, now: tuple[int, int]) -> list[int]:
        """Each picture's short side at the smallest size it's looked for at every
        check in something `now` big, for work_scale."""
        if not self.uses_pictures:
            return []
        return [max(1, round(min(g.shape) * min(self.sizes(i, now))))
                for i, (g, _m) in enumerate(self.pictures)]

    @property
    def most_is_worst(self) -> bool:
        """Its score going up means closer to going off (so over several places the
        highest is the one to show): not for "vanish", "still" or "colour" below."""
        return self.mode in ("appear", "change") or (self.mode == "colour" and not self.below)


def is_black(gray: np.ndarray) -> bool:
    """A whole frame too dark to be a game: the capture can't see it."""
    return float(gray.max()) < BLACK_LEVEL


def expand(src, wins) -> list:
    """The places `src` stands for: a WindowRef for every copy is each copy open
    now (`wins`, from onionwatch.windows.list_windows), or its first while none is
    (so it's waited for); anything else is itself."""
    if not isinstance(src, WindowRef) or not src.every:
        return [src]
    n = 0
    if wins:
        from onionwatch.windows import copies
        n = len(copies(src, wins))
    return [WindowRef(src.exe, src.title, i) for i in range(max(n, 1))]


class _Capture:
    """One screen or window as the watching thread captures it: its grabber, the
    pictures shrunk to what that grabber sees, and where it is in coming back from
    a loss. `source` is a screen index or a WindowRef; `mon` the screen's Monitor."""

    def __init__(self, source: int | WindowRef, mon: Monitor | None = None):
        self.source = source
        self.mon = mon
        self.grab = None
        self.scaled: dict[str, list[Look]] = {}   # each trigger's pictures, shrunk
        self.fitted = (0, 0)        # the source size the pictures are scaled for
        self.scores: dict[str, float] = {}
        self.refs: dict[str, tuple[float, np.ndarray]] = {}   # "change" / "still": (when, area)
        self.turns: dict[str, int] = {}   # "any size": which picture each trigger sweeps next
        self.swept: dict[str, int] = {}   # ...and the check it last swept on (SWEEPERS)
        self.checks = 0             # checks made on this capture
        self.reopen_since = 0.0     # > 0: the capture was lost (or never opened); trying again
        self.next_try = 0.0         # ...not before this time
        self.opened = False         # it has captured at some point
        self.failing = False        # grabs keep failing (said once in the log)
        self.error = ""             # why the last open failed
        self.black = False
        self.lost = False
        self.minimized = False      # a window that's minimized (nothing to see)
        self.next_dup = 0.0         # on the GDI fallback: when to try duplication again
        self.misses = 0             # grabs in a row that gave nothing to look at
        self.miss_since = 0.0       # ...since when

    @property
    def is_window(self) -> bool:
        return isinstance(self.source, WindowRef)

    def in_front(self) -> bool:
        f = getattr(self.grab, "in_front", None)
        try:
            return bool(f()) if f is not None else False
        except OSError:
            return False

    def close(self):
        if self.grab is not None:
            self.grab.close()
            self.grab = None


class Watcher:
    """The watching thread. `on_fire(trigger_id)` is called from that thread when a
    trigger goes off (`on_fire(trigger_id, hit)` with a Hit when made with
    hits=True); `scores` holds each trigger's latest score for the UI to show.

    Each trigger is looked for in its own screens and windows (`Watched.sources`),
    or in `default` when it has none: one capture per screen / window in use, each
    grabbed every tick. A window for every copy of a game stands for each copy
    open, listed again every WINDOW_RETRY_S so a copy started later is picked up. A
    window that isn't open is looked for again every WINDOW_RETRY_S (its triggers
    wait there meanwhile); the other captures carry on.

    A trigger that's ringing can be handed over with quiet_on(): `on_quiet(id)` is
    then called from the thread once what stops it by itself happens (Quieter).

    `grabber(mon, w, h)`, `window_grabber(ref, w, h)`, `lister()` (the open
    windows) and `front()` (the window in front) stand in for the real ones (tests)."""

    def __init__(self, on_fire, grabber=None, window_grabber=None, lister=None,
                 hits: bool = False, on_quiet=None, front=None):
        self._on_fire = on_fire
        self._on_quiet = on_quiet
        self._front = front
        self._quiet: dict[str, Quieter] = {}    # ringing trigger id -> what stops it
        self._hits = hits
        self._grabber = grabber
        self._window_grabber = window_grabber
        self._lister = lister
        self._lock = threading.Lock()
        self._items: dict[str, Watched] = {}
        self._changed = True              # pictures / default changed: rescale
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.interval = DEFAULT_INTERVAL_MS / 1000
        self.default: int | WindowRef = 0  # where triggers that don't pick are looked for
        self.scores: dict[str, float] = {}
        self.black = False                # a capture only sees black
        self.lost = False                 # a capture dropped out; it's being brought back
        self.error = ""
        self.check_ms = 0.0               # how long the last check took
        self.gap = self.interval          # the time between checks: `interval`, or more
                                          # when that would use over CPU_SHARE
        # All replaced whole by the thread, like `scores`:
        # triggers whose own screen isn't there (watched on the default instead)
        self.fell_back: frozenset[str] = frozenset()
        # screens that couldn't be captured for GIVE_UP_S, and windows that can't be
        # captured right now (not open): source -> why. Their triggers wait until they can.
        self.failed: dict = {}
        self.minimized: frozenset = frozenset()   # windows that are minimized
        self.blacked: frozenset = frozenset()     # sources that only come out black
        # sources that have given nothing to look at for UNSEEN_S (a window
        # PrintWindow can't copy): watching them can't set anything off
        self.unseen: frozenset = frozenset()
        self.where: dict[str, tuple] = {}         # trigger id -> the places it's looked in
        self.detail: dict[str, dict] = {}         # trigger id -> {place: its score there}

    # set from the UI thread
    def set_items(self, items: list[Watched]):
        with self._lock:
            old = self._items
            for it in items:              # keep a trigger's gates across edits
                if it.id in old:
                    it.gates = old[it.id].gates
            self._items = {it.id: it for it in items}
            self._changed = True
            # the thread replaces `scores` whole rather than changing it, so a copy is safe
            self.scores = {k: v for k, v in self.scores.items() if k in self._items}

    def quiet_on(self, tid: str, source, how: str):
        """Trigger `tid` started ringing after going off in `source`: watch there for
        what stops it ("moves", "gone", "focus"; anything else: nothing)."""
        with self._lock:
            if how in ("moves", "gone", "focus"):
                self._quiet[tid] = Quieter(how, source, time.monotonic())
            else:
                self._quiet.pop(tid, None)

    def quiet_off(self, tid: str | None = None):
        """It stopped ringing (None: they all did)."""
        with self._lock:
            if tid is None:
                self._quiet.clear()
            else:
                self._quiet.pop(tid, None)

    def _front_window(self) -> int:
        """The window in front (0: none, or it can't be told)."""
        try:
            if self._front is not None:
                return self._front()
            from onionwatch.windows import foreground
            return foreground()
        except OSError:
            return 0

    def set_default(self, source: int | WindowRef):
        with self._lock:
            self.default = source
            self._changed = True

    def rescan(self):
        """The screens changed (one plugged in or out): list them again."""
        with self._lock:
            self._changed = True

    @property
    def running(self) -> bool:
        """Watching: a thread is going and hasn't been told to stop."""
        return (self._thread is not None and self._thread.is_alive()
                and not self._stop.is_set())

    def start(self):
        if self.running:
            return
        # each run has its own stop switch: a thread that stop() couldn't wait out (a
        # slow check) still sees its own and ends, instead of carrying on beside the new one
        self._stop = stop = threading.Event()
        self.error = ""
        self._thread = threading.Thread(target=self._run, args=(stop,), name="screenwatch",
                                        daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        t = self._thread
        if t is not None and t is not threading.current_thread():
            t.join(2.0)
        if t is not None and not t.is_alive():
            self._thread = None
        self.scores = {}
        self.detail = {}
        self.fell_back, self.failed = frozenset(), {}
        self.minimized = self.blacked = self.unseen = frozenset()
        self.where = {}
        self.black = self.lost = False

    # the thread
    def _windows(self) -> list:
        """The open windows, for the triggers watching every copy of a game."""
        try:
            if self._lister is not None:
                return list(self._lister())
            from onionwatch.windows import list_windows
            return list_windows()
        except OSError:
            log.debug("listing windows failed", exc_info=True)
            return []

    def _run(self, stop: threading.Event | None = None):
        stop = stop or self._stop
        caps: dict = {}                          # source -> _Capture: only those in use
        groups: dict = {}                        # source -> the triggers looked for there
        wins: list | None = None                 # the open windows, when "every copy" is used
        listed = -math.inf
        cost: float | None = None                # a check's time, averaged
        worked = False                           # a screen was captured since Start
        tick_errors: dict = {}                   # source -> a check that failed, logged once
        try:
            while not stop.is_set():
                t0 = time.perf_counter()
                with self._lock:
                    items = list(self._items.values())
                    changed, self._changed = self._changed, False
                    default = self.default
                now = time.monotonic()
                every = any(isinstance(s, WindowRef) and s.every
                            for s in [default, *(s for it in items for s in it.sources)])
                relist = every and now - listed >= WINDOW_RETRY_S
                if relist:
                    wins, listed = self._windows(), now
                if (changed or relist or (items and not caps)
                        or any(c.grab is None for c in caps.values())):
                    mons = monitors()
                    old_groups = groups
                    groups, fell_back, where = self._assign(items, default, len(mons),
                                                            wins if every else None)
                    screens_needed = any(not isinstance(k, WindowRef) for k in groups)
                    if screens_needed and not mons:
                        # right after a loss the screen may be gone for a moment
                        # (a cable, a dock, a mode switch): wait for it like a reopen
                        # Once watching has worked it never gives up: a monitor asleep
                        # overnight or a dock unplugged comes back, and so must the alarms
                        if not worked and not any(
                                c.reopen_since and now - c.reopen_since <= GIVE_UP_S
                                for c in caps.values() if not c.is_window):
                            raise OSError("no monitor found")
                        self.lost = True
                        stop.wait(RETRY_S)
                        continue
                    self.fell_back = frozenset(fell_back)
                    self.where = where
                    for k in list(caps):        # sources no trigger needs, or screens that changed
                        if k not in groups or (not caps[k].is_window and caps[k].mon != mons[k]):
                            caps.pop(k).close()
                    for k, group in groups.items():
                        cap = caps.get(k)
                        if cap is None:
                            caps[k] = _Capture(k, None if isinstance(k, WindowRef) else mons[k])
                        elif cap.grab is not None and (
                                changed or [i.id for i in group]
                                != [i.id for i in old_groups.get(k, [])]):
                            cap.fitted, cap.scaled = self._fit(cap.grab, cap.mon, group,
                                                               cap.scaled, cap.fitted)
                now = time.monotonic()
                for k, cap in caps.items():
                    if cap.grab is None and now >= cap.next_try:
                        self._open(cap, groups[k])
                    elif getattr(cap.grab, "fallback", False) and now >= cap.next_dup:
                        self._retry_dup(cap, groups[k])
                live = [c for c in caps.values() if c.grab is not None]
                self.failed = {c.source: c.error for c in caps.values()
                               if c.grab is None and c.error
                               and (c.is_window or now - c.reopen_since > GIVE_UP_S)}
                screens = [c for c in caps.values() if not c.is_window]
                if screens and len(screens) == len(caps) and not live:
                    # nothing can be captured. A first start that fails is an error; a
                    # loss is given GIVE_UP_S of tries (the mode may still be switching)
                    if not worked and all(
                            c.error and (not c.opened or now - c.reopen_since > GIVE_UP_S)
                            for c in screens):
                        raise OSError(next(c.error for c in screens if c.error))
                worked = worked or any(not c.is_window for c in live)
                for cap in live:
                    try:
                        self._tick(cap, groups.get(cap.source, []))
                    except Exception:  # noqa: BLE001 - one odd frame mustn't end watching
                        if cap.source not in tick_errors:
                            log.exception("checking %r failed; watching goes on", cap.source)
                        tick_errors[cap.source] = True
                self.lost = any(c.lost for c in caps.values())
                self.blacked = frozenset(c.source for c in live if c.black)
                self.black = bool(self.blacked)
                self.minimized = frozenset(c.source for c in live if c.minimized)
                now = time.monotonic()
                self.unseen = frozenset(c.source for c in live if c.misses >= UNSEEN_GRABS
                                        and now - c.miss_since >= UNSEEN_S)
                if not stop.is_set():           # stop() has cleared them already
                    self.detail, self.scores = self._gather(items, caps)
                spent = time.perf_counter() - t0
                self.check_ms = spent * 1000
                # keep to CPU_SHARE of the processor: a check's time (on the clock,
                # so a busy computer counts too) sets how far apart they must be
                cost = spent if cost is None else cost + (spent - cost) * 0.2
                self.gap = max(self.interval, cost / (CPU_SHARE * CORES))
                stop.wait(max(0.001, self.gap - spent))
        except Exception as e:  # noqa: BLE001 - say so in the window instead of dying quietly
            log.exception("screen watching stopped")
            if not stop.is_set():
                self.error = str(e) or type(e).__name__
        finally:
            for cap in caps.values():
                cap.close()

    @staticmethod
    def _gather(items: list[Watched], caps: dict) -> tuple[dict, dict]:
        """Each trigger's score in each place, and the one to show: the place
        closest to setting it off. New dicts (the UI reads them meanwhile)."""
        detail: dict[str, dict] = {}
        for c in caps.values():
            if c.grab is None:
                continue
            for k, v in c.scores.items():
                detail.setdefault(k, {})[c.source] = v
        scores = {}
        for it in items:
            got = detail.get(it.id)
            if got:
                scores[it.id] = (max if it.most_is_worst else min)(got.values())
        return {k: v for k, v in detail.items() if k in scores}, scores

    @staticmethod
    def _assign(items: list[Watched], default: int | WindowRef, n: int,
                wins: list | None = None) -> tuple[dict, set[str], dict]:
        """Where each trigger is looked for: its own windows and screens, or
        `default` when it has none or for a screen that isn't among the `n` there
        are; a window for every copy is each copy in `wins`. Returns ({place: its
        triggers}, the ids that fell back to the default, {id: its places})."""
        if not isinstance(default, WindowRef):
            default = default if 0 <= default < n else 0
        groups: dict = {}
        fell_back: set[str] = set()
        where: dict[str, tuple] = {}
        for it in items:
            places: list = []
            for src in it.sources or [None]:
                if src is None:
                    src = default
                elif not isinstance(src, WindowRef) and not 0 <= src < n:
                    fell_back.add(it.id)
                    src = default
                for k in expand(src, wins):
                    if k not in places:
                        places.append(k)
            for k in places:
                groups.setdefault(k, []).append(it)
            where[it.id] = tuple(places)
        return groups, fell_back, where

    def _open(self, cap: _Capture, items: list[Watched]) -> bool:
        """Open the capture (a fresh start after a loss gives duplication a few goes).
        A failure is kept on the capture and tried again later: a screen RETRY_S apart
        at first, every GIVE_UP_S once it's clearly not coming back; a window every
        WINDOW_RETRY_S (it may be a game that isn't started yet)."""
        now = time.monotonic()
        sides = [s for i in items for s in i.sides_at(
            (cap.mon.width, cap.mon.height) if cap.mon else (0, 0))]
        try:
            if cap.is_window:
                opener = self._window_grabber
                if opener is None:
                    from onionwatch.windows import WindowGrabber as opener
                cap.grab = opener(cap.source, WORK_WIDTH, WORK_WIDTH * 9 // 16)
            else:
                mon = cap.mon
                scale = work_scale(mon.width, sides)
                w, h = max(1, round(mon.width * scale)), max(1, round(mon.height * scale))
                opener = self._grabber or open_grabber
                if cap.reopen_since and opener is open_grabber:
                    cap.grab = opener(mon, w, h, tries=3)
                else:
                    cap.grab = opener(mon, w, h)
        except OSError as e:
            cap.error = str(e) or type(e).__name__
            if not cap.reopen_since:
                cap.reopen_since = now
            if cap.is_window:
                cap.next_try = now + WINDOW_RETRY_S
                return False
            slow = now - cap.reopen_since > GIVE_UP_S
            if slow and cap.source not in self.failed:
                log.info("screen %d can't be captured (%s): its triggers wait until it can",
                         cap.source + 1, cap.error)
            cap.next_try = now + (GIVE_UP_S if slow else RETRY_S)
            return False
        cap.reopen_since, cap.error = 0.0, ""
        cap.opened, cap.lost = True, False
        cap.next_dup, cap.misses = now + DUP_RETRY_S, 0
        cap.fitted, cap.scaled = self._fit(cap.grab, cap.mon, items, cap.scaled,
                                              cap.fitted)
        return True

    def _retry_dup(self, cap: _Capture, items: list[Watched]) -> bool:
        """A screen on the GDI fallback tries Desktop Duplication again (every
        DUP_RETRY_S): a lock or UAC screen up for longer than GIVE_UP_S leaves the
        capture on GDI, which sees black in a fullscreen game. Taken once it works."""
        cap.next_dup = time.monotonic() + DUP_RETRY_S
        try:
            dup = DupGrabber(cap.mon, cap.grab.w, cap.grab.h)
        except (OSError, AttributeError):
            return False
        log.info("desktop duplication works again: screen %d is captured with it",
                 cap.source + 1)
        cap.grab.close()
        cap.grab, cap.misses = dup, 0
        cap.fitted, cap.scaled = self._fit(cap.grab, cap.mon, items, cap.scaled,
                                              cap.fitted)
        return True

    def _tick(self, cap: _Capture, items: list[Watched]):
        """Grab the screen / window once and check its triggers against it."""
        try:
            gray = cap.grab.grab()
        except OSError as e:
            # CaptureLost, or any other failure of a capture that did work (a
            # graphics driver reset, the window closed): open it afresh rather than
            # stop watching
            if not cap.failing:
                log.info("capture lost (%s): starting it afresh", e)
            cap.failing = True
            cap.close()
            cap.reopen_since = time.monotonic()
            cap.next_try = cap.reopen_since + (WINDOW_RETRY_S if cap.is_window else RETRY_S)
            cap.lost = not cap.is_window
            cap.error = str(e) or type(e).__name__
            cap.scores = {}
            cap.refs = {}
            cap.misses = 0
            return
        cap.failing = False
        cap.lost = bool(getattr(cap.grab, "lost", False))
        cap.minimized = bool(getattr(cap.grab, "minimized", False))
        if ((gray is None and not cap.lost and not cap.minimized)
                or getattr(cap.grab, "failures", 0)):
            # nothing to look at (PrintWindow can't copy the window, say): counted,
            # so a capture that never gives anything is said (`unseen`)
            if not cap.misses:
                cap.miss_since = time.monotonic()
            cap.misses += 1
        else:
            cap.misses = 0
        if getattr(cap.grab, "source", cap.fitted) != cap.fitted:
            # the frames changed size (a game switched display mode, a window was
            # resized): scale the pictures for what the capture really sees
            cap.fitted, cap.scaled = self._fit(cap.grab, cap.mon, items, cap.scaled,
                                              cap.fitted)
            return
        if gray is not None:
            cap.black = is_black(gray)
            cap.scores = self._check(cap, gray, items)

    @staticmethod
    def _fit(grab, mon: Monitor | None, items: list[Watched], old: dict | None = None,
             was: tuple[int, int] = (0, 0)) -> tuple[tuple[int, int], dict]:
        """Shrink the pictures for the size the grabber really copies (`source`; the
        monitor's when it doesn't say), and have it give out pictures that size too
        (in colour as well when a "colour" trigger needs it). With "any size" each
        picture is made ready at the sizes it may be drawn at now as well, and the
        sizes the sweep found in `old` (the last fit, for something `was` big) carry
        over, scaled with the height. Done once per change, not per tick: a trigger
        with a hundred pictures keeps them all shrunk, and the first SPECTRA_MB of
        their spectra. Returns (source size, {id: [Look]})."""
        sw, sh = getattr(grab, "source", None) or (mon.width, mon.height)
        scale = work_scale(sw, [s for i in items for s in i.sides_at((sw, sh))])
        w, h = max(1, round(sw * scale)), max(1, round(sh * scale))
        if (w, h) != (getattr(grab, "w", w), getattr(grab, "h", h)):
            grab.resize(w, h)
        try:
            grab.want_color = any(i.mode == "colour" for i in items)
        except AttributeError:
            pass
        ratio = sh / was[1] if was[1] > 0 else 1.0
        spectrum = next_fast_len(h) * (next_fast_len(w) // 2 + 1) * 8
        room = SPECTRA_MB * 2 ** 20
        scaled = {}
        for i in items:
            if not i.uses_pictures:
                continue
            before = (old or {}).get(i.id) or []
            looks = []
            for k, (g, m) in enumerate(i.pictures):
                found = ([f * ratio for f in before[k].found]
                         if i.any_size and k < len(before) and isinstance(before[k], Look) else [])
                look = Look(g, m, scale, i.sizes(k, (sw, sh)), i.any_size, found,
                            i.tints[k] if k < len(i.tints) else None)
                for _f, p in look.pats:
                    need = spectrum * (1 if p.box else 2)
                    if room >= need:
                        p.keep, room = True, room - need
                looks.append(look)
            scaled[i.id] = looks
        return (sw, sh), scaled

    def _check(self, cap: _Capture, gray: np.ndarray, items: list[Watched]) -> dict[str, float]:
        """Check every trigger against one frame of `cap` and fire the ones that go
        off. Returns the scores (a new dict: the UI thread reads `scores` while this
        runs, so it's only ever swapped whole)."""
        black = is_black(gray)
        now = time.monotonic()
        fh, fw = gray.shape
        frames: dict = {}                # an area -> its Frame, shared by its pictures
        scores = {}
        judged = {}
        if not black:
            # those that swept longest ago are scored first, so they get the turns
            budget = [SWEEPERS]
            for it in sorted(items, key=lambda i: cap.swept.get(i.id, -1)):
                judged[it.id] = self._score(cap, gray, it, now, frames, budget)
        cap.checks += 1
        for it in items:
            gate = it.gate_for(cap.source)
            if black:
                scores[it.id] = 0.0
                if it.mode == "appear":
                    gate.step(False, now, it.cooldown)
                continue
            score, box = judged[it.id]
            scores[it.id] = 0.0 if score is None else score
            if score is None:
                continue
            state = verdict(it.mode, score, it.threshold, it.below)
            q = self._quiet.get(it.id)
            if q is not None and q.source == cap.source:
                self._step_quiet(it, q, cap, gray, state, now)
            if not gate.step(state, now, it.cooldown, it.hold):
                continue
            if it.unfocused and cap.is_window and cap.in_front():
                log.debug("trigger %s went off in the window in front: kept quiet", it.id)
                continue
            y0, y1, x0, x1 = box
            rgb = getattr(cap.grab, "color", None)
            pic = rgb if rgb is not None and rgb.shape[:2] == gray.shape else gray
            hit = Hit(cap.source, (x0 / fw, y0 / fh, (x1 - x0) / fw, (y1 - y0) / fh), score,
                      (np.clip(pic, 0, 1) * 255).astype(np.uint8))
            try:
                if self._hits:
                    self._on_fire(it.id, hit)
                else:
                    self._on_fire(it.id)
            except Exception:  # noqa: BLE001
                log.exception("trigger callback failed")
        return scores

    def _step_quiet(self, it: Watched, q: Quieter, cap: _Capture, gray: np.ndarray,
                    state: bool | None, now: float):
        """Check a ringing trigger's Quieter against this frame; once it says so, let
        it go and call on_quiet."""
        y0, y1, x0, x1 = region_box(it.region, gray.shape)
        area = gray[y0:y1, x0:x1]
        front = None
        if q.how == "focus":
            front = cap.in_front() if cap.is_window else self._front_window()
        elif q.how == "moves":
            if it.mode == "colour":
                area = None         # a bar draining further isn't you: until it's back
            elif it.mode == "change":
                state = None        # a change is over at once: only movement after it
        if not q.step(area, state, front, now):
            return
        with self._lock:
            if self._quiet.get(it.id) is not q:
                return                  # stopped, or rung again, meanwhile
            del self._quiet[it.id]
        log.debug("trigger %s: ringing stopped by itself (%s)", it.id, q.how)
        if self._on_quiet is not None:
            try:
                self._on_quiet(it.id)
            except Exception:  # noqa: BLE001
                log.exception("quiet callback failed")

    @staticmethod
    def _score(cap: _Capture, gray: np.ndarray, it: Watched, now: float,
               frames: dict, budget: list[int] | None = None
               ) -> tuple[float | None, tuple[int, int, int, int]]:
        """A trigger's score in one frame (None: nothing to judge yet) and the box
        (y0, y1, x0, x1) it's about: where its best picture is, or its area. With
        "any size" it sweeps a step too when it isn't matched well, if `budget` (the
        turns left this check, taken one) has a turn left; None: always."""
        if it.uses_pictures:
            looks = cap.scaled.get(it.id) or []
            least = (max((lk.pats[0][1].shape[0] for lk in looks), default=2),
                     max((lk.pats[0][1].shape[1] for lk in looks), default=2))
            box = region_box(it.region, gray.shape, least)
            y0, y1, x0, x1 = box
            f = frames.get(box)
            if f is None:
                f = frames[box] = Frame(gray[y0:y1, x0:x1])
            raw = getattr(cap.grab, "raw", None)
            near_ = it.threshold - TINT_NEAR

            def judge(p: Pattern, lk: Look) -> tuple[float, tuple]:
                """The picture's best place at this size: (score, box), the score
                taken down when the colours there aren't the picture's."""
                top: tuple = (0.0, box)
                check = raw is not None and lk.tint is not None
                for sc, (mx, my) in find_peaks(f, p, PEAKS if check else 1, near_):
                    b = (y0 + my, y0 + my + p.size[0], x0 + mx, x0 + mx + p.size[1])
                    if check and sc >= near_:
                        sc *= Watcher._tint_factor(raw, b, lk.tint, lk.mask)
                    if sc > top[0]:
                        top = (sc, b)
                return top

            best, at = 0.0, box
            for lk in looks:
                for _s, p in lk.pats:
                    sc, b = judge(p, lk)
                    if sc > best:
                        best, at = sc, b
            if (best < max(it.threshold, SWEEP_DONE) and it.any_size
                    and (budget is None or budget[0] > 0)):
                if budget is not None:
                    budget[0] -= 1
                cap.swept[it.id] = cap.checks
                sc, b = Watcher._sweep(cap, it, looks, judge, f.shape, best)
                if sc > best:
                    best, at = sc, b
            return best, (at if it.mode == "appear" else box)
        box = region_box(it.region, gray.shape)
        y0, y1, x0, x1 = box
        if it.mode == "colour":
            rgb = getattr(cap.grab, "color", None)
            if rgb is None or it.colour is None or rgb.shape[:2] != gray.shape:
                return None, box
            return colour_share(rgb[y0:y1, x0:x1], it.colour), box
        area = gray[y0:y1, x0:x1]            # "change" / "still"
        ref = cap.refs.get(it.id)
        if ref is None or ref[1].shape != area.shape:
            cap.refs[it.id] = (now, area.copy())
            return None, box
        score = changed_share(area, ref[1])
        if now - ref[0] >= CHANGE_GAP:
            cap.refs[it.id] = (now, area.copy())
        return score, box

    @staticmethod
    def _tint_factor(raw: tuple, box: tuple, want: np.ndarray,
                     mask: np.ndarray | None = None) -> float:
        """How much of a score stands, going by the colours of `box` (y0, y1, x0, x1
        in the frame) in the grab's own pixels `raw` against the picture's tint.
        The box is also tried a pixel off each way (where a match lands can be a
        pixel out, and on a small picture that shifts its cells a lot). A cut-out's
        `mask` (its own size) is laid over the box, so only what's under its opaque
        part counts, as it did for the picture's tint: the game's background showing
        through it would otherwise make the colours of the right place disagree."""
        px, fmt, k = raw
        y0, y1, x0, x1 = box
        h, w = px.shape[0] // k, px.shape[1] // k
        try:
            rgb = frame_rgb(px[max(0, y0 - 1) * k:min(h, y1 + 1) * k,
                               max(0, x0 - 1) * k:min(w, x1 + 1) * k], fmt, k)
        except (OSError, ValueError):
            return 1.0
        under = None
        if mask is not None and not mask.all() and y1 > y0 and x1 > x0:
            mh, mw = mask.shape
            under = mask[(np.arange(y1 - y0) * mh // (y1 - y0))[:, None],
                         np.arange(x1 - x0) * mw // (x1 - x0)]
        oy, ox = y0 - max(0, y0 - 1), x0 - max(0, x0 - 1)
        best = None
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                a, c = oy + dy, ox + dx
                if a < 0 or c < 0 or a + y1 - y0 > rgb.shape[0] or c + x1 - x0 > rgb.shape[1]:
                    continue
                got = tint(rgb[a:a + y1 - y0, c:c + x1 - x0], under)
                if got is not None:
                    gap = tint_gap(want, got)
                    best = gap if best is None else min(best, gap)
        return 1.0 if best is None else tint_factor(best)

    @staticmethod
    def _sweep(cap: _Capture, it: Watched, looks: list[Look], judge,
               area: tuple[int, int], beat: float = 0.0) -> tuple[float, tuple]:
        """One step of a trigger's sweep: its next SWEEP_PER_CHECK sizes, one picture
        at a time in turn, each judged by `judge(pattern, look)` -> (score, box). A
        size within PROMISING of the threshold is tried again either side of it (the
        sweep's steps are wider than a match holds), and if one matches the picture
        is looked for at that size every check from then on, if it did better than
        `beat` (the best at the sizes already looked for). `area` is the (h, w)
        looked in. Returns the best (score, box) it tried."""
        best: tuple = (0.0, None)
        todo = [lk for lk in looks if lk.todo]
        if not todo:
            return best
        turn = cap.turns.get(it.id, 0)
        cap.turns[it.id] = turn + 1
        lk = todo[turn % len(todo)]
        (gh, gw), (fh, fw) = lk.gray.shape, area
        kept = None
        for s in lk.sweep_sizes(SWEEP_PER_CHECK):
            if gh * lk.scale * s > fh or gw * lk.scale * s > fw:
                continue                    # bigger than the area at this size
            p = lk.pattern(s)
            sc, at = judge(p, lk)
            if sc > best[0]:
                best, kept = (sc, at), (s, p)
            if sc < it.threshold - PROMISING:
                continue
            for g in (s / SWEEP_STEP ** 0.5, s * SWEEP_STEP ** 0.5):
                p = lk.pattern(g)
                sc, at = judge(p, lk)
                if sc > best[0]:
                    best, kept = (sc, at), (g, p)
        if kept is not None and best[0] >= max(it.threshold, beat + 0.01):
            kept[1].keep = True
            lk.keep(*kept)
            log.info("trigger %s: a picture found at %.0f%% of the size it was cut at",
                     it.id, kept[0] * 100)
        return best
