"""The Onion Watch logo that shows it's watching. It looks the same as ever; on Start
watching it plays a short start-up flourish that suits the theme (a laser sweep for
the dark red ones, code rain for the terminals, petals for the pink ones...), and
while it watches its eye slowly looks left and right.

The flourish is drawn on a see-through layer over the page that takes no clicks and
is gone when it ends. Nothing moves while the app is in the background
(appstate.pause_in_background): behind a game the logo holds still and costs nothing."""
from __future__ import annotations

import math
import random
import time
from dataclasses import dataclass

from PySide6.QtCore import QEvent, QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import (QColor, QConicalGradient, QFont, QLinearGradient, QPainter,
                           QPainterPath, QPen, QPixmap, QRadialGradient)
from PySide6.QtWidgets import QWidget

from onionwatch import theme
from onionwatch.style import appstate

FRAME_MS = 33          # 30 fps while it moves
BURST_S = 1.3          # the start-up flourish
SCAN_S = 3.4           # the eye looking left, right and back while it watches
SCAN_X = 0.05          # ...this far each way, in logo widths
EYE_Y = 0.60           # the eye's centre, in logo heights (theme.paint_logo's `ey`)
EYE_R = 0.155          # ...and the iris's radius
IDLE_CALM = 0.55       # the idle animation's strength while not watching (1 = watching)
EASE_RATE = 3.0        # how fast its strength, the eye's look and the laser's glow follow
                       # watching on and off (1/s): eased, never a jump
CUT_S = 0.3            # a flourish cut short (watching stopped) fades out this long
SHEEN_PERIOD = 4.5     # seconds between sheens across the logo (as Onion Board's logo)
SHEEN_TIME = 0.9       # ...and how long one takes
SQUISH_RATE = 4.0      # a click's wobble eases out this fast (1/s), as Onion Board's logo

# Which flourish each theme plays. Every theme is named (tests/test_watchlogo.py);
# one that isn't (a board's newer theme) gets "shine".
STYLES: dict[str, tuple[str, ...]] = {
    "laser": ("Blood Moon", "Vampire", "Deep Fried", "Carbon", "Midnight"),
    "code": ("Hacker", "Toxic", "Amber Terminal"),
    "neon": ("Synthwave", "Vaporwave"),
    "petals": ("Cherry Blossom", "Barbie", "Lilac", "Mint"),
    "sonar": ("Ocean", "Arctic", "Slate"),
    "embers": ("Lava", "Sunset", "Mocha", "Halloween"),
    "fireflies": ("Forest", "Swamp", "Onion"),
    "pixels": ("Retro 98", "High Contrast"),
    "comic": ("Comic Sans", "Paper"),
    "flash": ("Flashbang",),
    "confetti": ("Brainrot",),
    "shine": ("Hoot", "Dark", "Light", "Royal"),
}
_STYLE_OF = {name: style for style, names in STYLES.items() for name in names}


def style_for(theme_name: str) -> str:
    return _STYLE_OF.get(theme_name, "shine")


def _ease(t: float) -> float:
    t = min(1.0, max(0.0, t))
    return t * t * (3 - 2 * t)


def _alpha(c: QColor, a: float) -> QColor:
    c = QColor(c)
    c.setAlphaF(max(0.0, min(1.0, a)))
    return c


class WatchLogo(QWidget):
    """The logo, `px` square, centred in a `w` x `h` box. `set_watching(on)`: on plays
    the theme's flourish over `beam_host` and starts the eye looking around."""

    def __init__(self, px: int, w: int, h: int, beam_host: QWidget | None = None,
                 parent=None):
        super().__init__(parent)
        self.px = px
        self.setFixedSize(w, h)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.watching = False
        self.style_name = "shine"
        self._burst = -1.0        # seconds into the flourish, or -1
        self._scan = 0.0          # seconds of looking around (from the flourish's end)
        self._last = time.monotonic()
        self._pm = QPixmap()
        self.retheme()
        self._timer = QTimer(self)
        self._timer.setInterval(FRAME_MS)
        self._timer.timeout.connect(self._tick)
        appstate.pause_in_background(self, self._resume, self._pause)
        self.beam = _Burst(self, beam_host) if beam_host is not None else None
        self._idle = 0.0          # seconds of the idle animation
        self._on = IDLE_CALM      # intensity(), eased
        self._look_k = 0.0        # 0..1, how much the eye looks around (eased)
        self._hot = 0.0           # 0..1, the laser eye's glow while it watches (eased)
        self._cut = -1.0          # seconds into a cut flourish's fade, or -1
        self.squish = 0.0         # a click's wobble, 1 just clicked, easing to 0

    def intensity(self) -> float:
        """How strong the idle animation is: full while it watches, calmer while not
        (eased from one to the other)."""
        return self._on

    # ------------------------------------------------------------------ outside
    def retheme(self):
        """The theme changed: its colours, and its flourish."""
        self._pm = theme.themed_logo(self.px * 2)
        self._pm.setDevicePixelRatio(2)
        self.style_name = style_for(theme.current_name)
        self.update()

    def pixmap(self) -> QPixmap:
        """The logo as it rests (the same picture as ever)."""
        return self._pm

    def set_watching(self, on: bool):
        on = bool(on)
        if on == self.watching:
            return
        self.watching = on
        if self._look_k < 0.01:   # (still easing back: it carries on from where it is)
            self._scan = 0.0
        if on and self.isVisible() and appstate.active():
            self._burst, self._cut = 0.0, -1.0
            if self.beam is not None:
                self.beam.start()
            self._resume()
        elif self._burst >= 0 and self._timer.isActive():
            self._cut = 0.0       # the flourish fades out instead of vanishing
        else:
            self._burst = -1.0
            if self.beam is not None:
                self.beam.stop()
        self.update()

    def cut_fade(self) -> float:
        """1, or down to 0 while a flourish cut short fades out."""
        return 1.0 if self._cut < 0 else max(0.0, 1 - self._cut / CUT_S)

    def burst_t(self) -> float:
        return self._burst

    def look(self) -> float:
        """How far the eye looks sideways now, in logo widths (easing in after the
        flourish and back to the middle when watching stops)."""
        k = _ease(self._look_k)
        if k < 0.001:
            return 0.0
        return SCAN_X * math.sin(self._scan * 2 * math.pi / SCAN_S) * k

    def logo_rect(self) -> QRectF:
        return QRectF((self.width() - self.px) / 2, (self.height() - self.px) / 2,
                      self.px, self.px)

    def eye_center(self) -> QPointF:
        r = self.logo_rect()
        return QPointF(r.center().x() + self.look() * r.width(),
                       r.top() + r.height() * EYE_Y)

    def mousePressEvent(self, ev):
        if ev.button() == Qt.MouseButton.LeftButton:
            self.poke()
        super().mousePressEvent(ev)

    def poke(self):
        """A click: the same little wobble as Onion Board's logo."""
        self.squish = 1.0
        self._resume()
        self.update()

    # ------------------------------------------------------------------ time
    def showEvent(self, ev):
        if appstate.active():
            self._resume()
        super().showEvent(ev)

    def hideEvent(self, ev):
        self._pause()
        super().hideEvent(ev)

    def _resume(self):
        if self.isVisible() and appstate.active() and not self._timer.isActive():
            self._last = time.monotonic()
            self._timer.start()

    def _pause(self):
        self._timer.stop()
        self._burst, self._cut = -1.0, -1.0
        if self.beam is not None:
            self.beam.stop()
        self.update()

    def _tick(self):
        now = time.monotonic()
        self.step(min(0.1, now - self._last))
        self._last = now

    def step(self, dt: float):
        """Move the animation on by `dt` seconds (the tests call this directly)."""
        self._idle += dt
        self.squish = max(0.0, self.squish - dt * SQUISH_RATE)
        e = min(1.0, dt * EASE_RATE)
        self._on += ((1.0 if self.watching else IDLE_CALM) - self._on) * e
        self._hot += (float(self.watching) - self._hot) * e
        looks = self.watching and self._burst < 0
        self._look_k += (float(looks) - self._look_k) * e
        if self._look_k < 0.001 and not looks:
            self._look_k = 0.0
        if self._cut >= 0:
            self._cut += dt
            if self._cut >= CUT_S:
                self._burst = self._cut = -1.0
        if self._burst >= 0:
            self._burst += dt
            if self._burst >= BURST_S:
                self._burst = self._cut = -1.0
        elif self._look_k > 0:
            self._scan += dt
        if self.beam is not None:
            self.beam.step()
        self.update()

    # ------------------------------------------------------------------ paint
    def paintEvent(self, ev):
        p = QPainter(self)
        appstate.snap_to_pixels(p)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = self.logo_rect()
        b = self._burst
        style, t, on = self.style_name, self._idle, self.intensity()
        if self.squish > 0:   # a click's wobble, from the bottom of the tile
            k = self.squish * math.cos((1 - self.squish) * 14)
            base = QPointF(r.center().x(), r.bottom())
            p.translate(base)
            p.scale(1 + 0.08 * k, 1 - 0.1 * k)
            p.translate(-base)
        if b >= 0 and style == "confetti":   # a quick shake as it goes
            k = 1 - b / BURST_S
            p.translate(math.sin(b * 70) * 2.2 * k * k, math.cos(b * 53) * 1.4 * k * k)
        elif style == "comic":               # a little squash-and-bounce now and then
            k = comic_bounce(t)
            if k:
                base = QPointF(r.center().x(), r.bottom())
                p.translate(base)
                p.scale(1 + 0.07 * k, 1 - 0.09 * k)
                p.translate(-base)
        elif style == "pixels" and t % 1.6 < 0.16:   # an 8-bit hop
            p.translate(0, -1)
        elif style == "confetti":            # a slow wobble
            mid = r.center()
            p.translate(mid)
            p.rotate(3.5 * math.sin(t * 2.3))
            p.translate(-mid)
        look = self.look()
        if look:
            theme.paint_logo(p, r, theme.T.get("accent") or theme.BRAND[0],
                             theme.T.get("accent2") or theme.BRAND[1], look=look)
        else:
            p.drawPixmap(r.topLeft(), self._pm)
        paint_idle(p, style, _Idle(rect=r, u=float(self.px), t=t, on=on,
                                   a1=QColor(theme.T.get("accent") or theme.BRAND[0]),
                                   a2=QColor(theme.T.get("accent2") or theme.BRAND[1]),
                                   name=theme.current_name))
        if style == "laser":
            # the eye stays a little red-hot while it watches: the flourish's glow
            # settles to that, and it cools off when watching stops
            warm = (0.4 + 0.2 * math.sin(t * 3)) * self._hot
            if b >= 0:
                fade = 1.0 if b < BURST_S * 0.8 else 1 - (b - BURST_S * 0.8) / (BURST_S * 0.2)
                fade = max(0.0, fade) * self.cut_fade()
                paint_laser_eye(p, self.eye_center(), self.px * EYE_R,
                                warm + (1 - warm) * fade)
            elif warm > 0.01:
                paint_laser_eye(p, self.eye_center(), self.px * EYE_R, warm)
        p.end()


def paint_laser_eye(p: QPainter, c: QPointF, r: float, g: float):
    """A red-hot iris over the logo's eye at `c` (iris radius `r`), `g` 0..1 bright."""
    p.save()
    p.setPen(Qt.PenStyle.NoPen)
    halo = QRadialGradient(c, r * 1.9)
    halo.setColorAt(0.0, QColor(255, 60, 40, int(210 * g)))
    halo.setColorAt(0.55, QColor(255, 30, 30, int(90 * g)))
    halo.setColorAt(1.0, QColor(255, 0, 0, 0))
    p.setBrush(halo)
    p.drawEllipse(c, r * 1.9, r * 1.9)
    p.setBrush(QColor(255, 40, 40, int(255 * g)))
    p.drawEllipse(c, r, r)
    core = QRadialGradient(c, r * 0.75)
    core.setColorAt(0.0, QColor(255, 236, 228, int(255 * g)))
    core.setColorAt(1.0, QColor(255, 120, 90, 0))
    p.setBrush(core)
    p.drawEllipse(c, r * 0.75, r * 0.75)
    p.restore()


class _Burst(QWidget):
    """The start-up flourish: a see-through layer over `host` (clicks go through it),
    shown only while the logo's flourish runs."""

    def __init__(self, logo: WatchLogo, host: QWidget):
        super().__init__(host)
        self.logo = logo
        self.host = host
        self.parts: list[dict] = []
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.hide()
        host.installEventFilter(self)

    def eventFilter(self, obj, ev):
        if obj is self.host and ev.type() == QEvent.Type.Resize and self.isVisible():
            self.setGeometry(self.host.rect())
        return False

    def start(self):
        rng = random.Random()
        self.parts = [dict(a=rng.uniform(0, 2 * math.pi), v=rng.uniform(0.55, 1.0),
                           s=rng.uniform(0.7, 1.3), spin=rng.uniform(-6, 6),
                           d=rng.uniform(0, 0.25), x=rng.uniform(-1, 1),
                           w=rng.uniform(0, 2 * math.pi), i=i)
                      for i in range(22)]
        self.setGeometry(self.host.rect())
        self.raise_()
        self.show()
        self.update()

    def stop(self):
        self.hide()

    def step(self):
        if self.logo.burst_t() < 0:
            if self.isVisible():
                self.hide()
        else:
            self.update()

    def paintEvent(self, ev):
        b = self.logo.burst_t()
        if b < 0:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        logo = self.logo
        c = QPointF(logo.mapTo(self.host, logo.eye_center().toPoint()))
        lr = logo.logo_rect()
        top_left = QPointF(logo.mapTo(self.host, lr.topLeft().toPoint()))
        ctx = _Ctx(c=c, u=float(logo.px), b=b, k=b / BURST_S,
                   side=-1 if self.layoutDirection() == Qt.LayoutDirection.RightToLeft else 1,
                   a1=QColor(theme.T.get("accent", "#e3263c")),
                   a2=QColor(theme.T.get("accent2", "#ffc93c")),
                   rect=QRectF(top_left, lr.size()),
                   page=QRectF(0, 0, self.width(), self.height()),
                   parts=self.parts, name=theme.current_name)
        p.setOpacity(logo.cut_fade())
        PAINTERS.get(logo.style_name, _shine)(p, ctx)
        p.end()


@dataclass
class _Ctx:
    """What a flourish draws with: the eye `c`, the logo's size `u` and `rect`, `b`
    seconds in (`k` 0..1 of the way), `side` (-1 right to left), the theme's `a1` /
    `a2`, the `page`, the random `parts` it scatters and the theme's `name`."""
    c: QPointF
    u: float
    b: float
    k: float
    side: int
    a1: QColor
    a2: QColor
    rect: QRectF
    page: QRectF
    parts: list[dict]
    name: str

    def fade(self, start: float = 0.7) -> float:
        """1, then down to 0 over the flourish's last part."""
        return 1.0 if self.k < start else max(0.0, 1 - (self.k - start) / (1 - start))


# ---------------------------------------------------------------------- the flourishes

def _laser(p: QPainter, x: _Ctx):
    """A laser from the eye sweeps down across the page and back up, then fades."""
    b, c, r = x.b, x.c, x.u * EYE_R
    u = x.k
    ang = -3 + 33 * _ease(u / 0.55) if u < 0.55 else 30 - 18 * _ease((u - 0.55) / 0.45)
    a = math.radians(ang)
    reach = _ease(b / (BURST_S * 0.12))
    fade = x.fade(0.8)
    flicker = 0.85 + 0.15 * math.sin(b * 90)
    length = math.hypot(x.page.width(), x.page.height()) * reach
    end = QPointF(c.x() + x.side * math.cos(a) * length, c.y() + math.sin(a) * length)
    for width, colour in ((r * 5.0, QColor(255, 0, 0, int(55 * fade))),
                          (r * 2.2, QColor(255, 40, 30, int(170 * fade * flicker))),
                          (r * 0.8, QColor(255, 235, 225, int(255 * fade * flicker)))):
        grad = QLinearGradient(c, end)
        grad.setColorAt(0.0, colour)
        grad.setColorAt(1.0, _alpha(colour, 0))
        p.setPen(QPen(grad, width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawLine(c, end)
    flash = QRadialGradient(c, r * 3.5)
    flash.setColorAt(0.0, QColor(255, 240, 230, int(220 * fade)))
    flash.setColorAt(0.4, QColor(255, 40, 30, int(120 * fade)))
    flash.setColorAt(1.0, QColor(255, 0, 0, 0))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(flash)
    p.drawEllipse(c, r * 3.5, r * 3.5)
    if x.name == "Deep Fried":   # the meme: a huge lens flare on the eye
        for dx, dy, ln in ((1, 0, 90), (0, 1, 40), (0.7, 0.7, 30), (0.7, -0.7, 30)):
            a0 = QPointF(c.x() - dx * ln, c.y() - dy * ln)
            a1 = QPointF(c.x() + dx * ln, c.y() + dy * ln)
            g = QLinearGradient(a0, a1)
            g.setColorAt(0.0, QColor(255, 120, 60, 0))
            g.setColorAt(0.5, QColor(255, 250, 220, int(240 * fade)))
            g.setColorAt(1.0, QColor(255, 120, 60, 0))
            p.setPen(QPen(g, 2.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawLine(a0, a1)


GLYPHS = "01アイウエオカキクケコサシスセソ<>/*#"


def _code(p: QPainter, x: _Ctx):
    """Code rain falls past the logo and along the tab row, and brackets lock on."""
    f = QFont("Consolas")
    f.setPixelSize(10)
    f.setBold(True)
    p.setFont(f)
    fade = x.fade(0.65)
    for part in x.parts[:16]:
        i = part["i"]
        col_x = x.c.x() + x.side * (-6 + i * 11)
        head = x.c.y() - 28 + (x.b - part["d"]) * 90 * (0.7 + part["v"])
        for j in range(5):
            y = head - j * 10
            if y < x.c.y() - 30 or y > x.c.y() + 42:
                continue
            ch = GLYPHS[(i * 7 + j * 3 + int(x.b * 14)) % len(GLYPHS)]
            a = (1.0 if j == 0 else 0.75 - j * 0.14) * fade
            p.setPen(_alpha(QColor("white") if j == 0 else x.a1, a))
            p.drawText(QPointF(col_x - 3, y), ch)
    k = _ease(x.k / 0.5)
    pad = 10 * (1 - k) + 2
    r = x.rect.adjusted(-pad, -pad, pad, pad)
    p.setPen(QPen(_alpha(x.a1, fade), 1.6))
    arm = 5
    for cx, cy, sx, sy in ((r.left(), r.top(), 1, 1), (r.right(), r.top(), -1, 1),
                           (r.left(), r.bottom(), 1, -1), (r.right(), r.bottom(), -1, -1)):
        p.drawLine(QPointF(cx, cy), QPointF(cx + sx * arm, cy))
        p.drawLine(QPointF(cx, cy), QPointF(cx, cy + sy * arm))


def _rings(p: QPainter, x: _Ctx, colours, glow: bool, reach: float, delays):
    for n, d in enumerate(delays):
        t = (x.b - d) / (BURST_S * 0.75)
        if not 0 <= t <= 1:
            continue
        rad = x.u * 0.25 + _ease(t) * x.u * reach
        a = (1 - t) ** 1.3
        col = colours[n % len(colours)]
        p.setBrush(Qt.BrushStyle.NoBrush)
        if glow:
            p.setPen(QPen(_alpha(col, 0.25 * a), 7))
            p.drawEllipse(x.c, rad, rad)
        p.setPen(QPen(_alpha(col, 0.95 * a), 1.8))
        p.drawEllipse(x.c, rad, rad)


def _neon(p: QPainter, x: _Ctx):
    """Neon rings in both theme colours and a neon streak through the eye."""
    _rings(p, x, (x.a1, x.a2), True, 3.4, (0.0, 0.16, 0.32))
    t = _ease(x.k / 0.35)
    fade = x.fade(0.45)
    end = QPointF(x.c.x() + x.side * 150 * t, x.c.y())
    for width, a in ((6, 0.25), (1.6, 0.95)):
        g = QLinearGradient(x.c, end)
        g.setColorAt(0.0, _alpha(x.a2, a * fade))
        g.setColorAt(1.0, _alpha(x.a2, 0))
        p.setPen(QPen(g, width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawLine(x.c, end)


def _shape(kind: str, s: float) -> QPainterPath:
    path = QPainterPath()
    if kind == "heart":
        path.moveTo(0, s * 0.35)
        path.cubicTo(-s, -s * 0.3, -s * 0.45, -s * 1.0, 0, -s * 0.4)
        path.cubicTo(s * 0.45, -s * 1.0, s, -s * 0.3, 0, s * 0.35)
    elif kind == "petal":
        path.moveTo(0, -s)
        path.quadTo(s * 0.8, 0, 0, s)
        path.quadTo(-s * 0.8, 0, 0, -s)
    else:   # a four-point star
        for n in range(8):
            r = s if n % 2 == 0 else s * 0.32
            a = n * math.pi / 4 - math.pi / 2
            pt = QPointF(math.cos(a) * r, math.sin(a) * r)
            if n:
                path.lineTo(pt)
            else:
                path.moveTo(pt)
        path.closeSubpath()
    return path


def _petals(p: QPainter, x: _Ctx):
    """Petals, hearts or stars burst from the logo and drift down."""
    kind = {"Cherry Blossom": "petal", "Barbie": "heart"}.get(x.name, "star")
    fade = x.fade(0.55)
    p.setPen(Qt.PenStyle.NoPen)
    for part in x.parts[:18]:
        t = max(0.0, x.b - part["d"] * 0.5)
        dist = x.u * 2.6 * part["v"] * (1 - math.exp(-t * 3.2))
        px = x.c.x() + math.cos(part["a"]) * dist + math.sin(t * 3 + part["w"]) * 3
        py = x.c.y() + math.sin(part["a"]) * dist * 0.7 + 22 * t * t
        col = (x.a1, x.a2, QColor("white"))[part["i"] % 3]
        p.save()
        p.translate(px, py)
        p.rotate(math.degrees(part["spin"] * t * 0.4) + part["w"] * 57)
        p.setBrush(_alpha(col, 0.95 * fade * min(1.0, t * 8)))
        p.drawPath(_shape(kind, 3.6 * part["s"]))
        p.restore()


def _sonar(p: QPainter, x: _Ctx):
    """A sonar ping: a radar sweep round the logo and rings spreading out."""
    fade = x.fade(0.6)
    rad = x.u * 2.4
    g = QConicalGradient(x.c, -x.k * 540)
    g.setColorAt(0.0, _alpha(x.a1, 0.55 * fade))
    g.setColorAt(0.16, _alpha(x.a1, 0))
    g.setColorAt(1.0, _alpha(x.a1, 0))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(g)
    p.drawEllipse(x.c, rad, rad)
    _rings(p, x, (x.a1,), False, 3.0, (0.0, 0.25, 0.5))


def _embers(p: QPainter, x: _Ctx):
    """Embers fly off the logo like sparks in the wind, cooling as they go."""
    fade = x.fade(0.6)
    p.setPen(Qt.PenStyle.NoPen)
    hot, warm = QColor(255, 230, 140), QColor(x.a1)
    for part in x.parts:
        t = x.b - part["d"]
        if t < 0:
            continue
        life = min(1.0, t / (BURST_S * 0.8))
        px = x.c.x() + x.side * (x.u * 0.3 + t * 130 * part["v"])
        py = (x.c.y() + part["x"] * x.u * 0.4 - t * 14 * part["v"]
              + math.sin(t * 7 + part["w"]) * 4 * life)
        col = QColor.fromRgbF(hot.redF() + (warm.redF() - hot.redF()) * life,
                              hot.greenF() + (warm.greenF() - hot.greenF()) * life,
                              hot.blueF() + (warm.blueF() - hot.blueF()) * life)
        r = 1.8 * part["s"] * (1 - life * 0.5)
        p.setBrush(_alpha(col, (1 - life) * fade))
        p.drawEllipse(QPointF(px, py), r, r)


def _fireflies(p: QPainter, x: _Ctx):
    """Fireflies wake up round the logo and drift off, blinking."""
    fade = x.fade(0.6)
    glow_col = QColor(x.a1).lighter(150)
    p.setPen(Qt.PenStyle.NoPen)
    for part in x.parts[:14]:
        t = max(0.0, x.b - part["d"])
        dist = x.u * (0.6 + 2.0 * part["v"] * _ease(t / BURST_S * 1.4))
        a = part["a"] + math.sin(t * 2 + part["w"]) * 0.4
        pt = QPointF(x.c.x() + math.cos(a) * dist, x.c.y() + math.sin(a) * dist * 0.6)
        blink = 0.5 + 0.5 * math.sin(t * 9 + part["w"] * 3)
        lit = fade * min(1.0, t * 6) * (0.4 + 0.6 * blink)
        g = QRadialGradient(pt, 6)
        g.setColorAt(0.0, _alpha(QColor(255, 255, 200), lit))
        g.setColorAt(0.35, _alpha(glow_col, 0.7 * lit))
        g.setColorAt(1.0, _alpha(glow_col, 0))
        p.setBrush(g)
        p.drawEllipse(pt, 6, 6)


def _pixels(p: QPainter, x: _Ctx):
    """An 8-bit burst: rings of square pixels popping out in steps."""
    step = int(x.b * 12)                      # 12 frames a second, like an old game
    p.setPen(Qt.PenStyle.NoPen)
    for ring, (col, lag) in enumerate(((x.a1, 0), (x.a2, 3))):
        n = step - lag
        if n < 0 or n > 11:
            continue
        rad = x.u * 0.5 + n * 5
        size = 4 if n < 8 else 3 if n < 10 else 2
        p.setBrush(col)
        for i in range(12):
            a = i * math.pi / 6 + ring * math.pi / 12
            px = round((x.c.x() + math.cos(a) * rad) / 2) * 2
            py = round((x.c.y() + math.sin(a) * rad) / 2) * 2
            p.drawRect(QRectF(px - size / 2, py - size / 2, size, size))


def _comic(p: QPainter, x: _Ctx):
    """A comic-book "!" pops off the logo's corner, with impact lines round the logo
    (kept in the gap before the tabs, never on them)."""
    t = x.k
    pop = 1.25 * _ease(t / 0.18) - 0.25 * _ease((t - 0.18) / 0.15) if t < 0.33 else 1.0
    fade = x.fade(0.7)
    r = x.rect
    mid = r.center()
    p.setPen(QPen(_alpha(x.a1, fade), 1.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    for n in range(10):
        a = math.pi * (0.5 + n / 5)
        r0 = r.width() * 0.62 + 2 * pop
        r1 = r0 + 6 * pop
        p.drawLine(QPointF(mid.x() + math.cos(a) * r0, mid.y() + math.sin(a) * r0),
                   QPointF(mid.x() + math.cos(a) * r1, mid.y() + math.sin(a) * r1))
    cx = (r.right() if x.side > 0 else r.left()) + x.side * 1
    cy = r.top() + r.height() * 0.3
    rad = 8.5 * pop
    path = QPainterPath()
    for n in range(20):
        rr = rad if n % 2 == 0 else rad * 0.6
        a = n * math.pi / 10
        pt = QPointF(cx + math.cos(a) * rr, cy + math.sin(a) * rr)
        if n:
            path.lineTo(pt)
        else:
            path.moveTo(pt)
    path.closeSubpath()
    p.setPen(QPen(_alpha(QColor("#111111"), fade), 1.3))
    p.setBrush(_alpha(x.a2, fade))
    p.drawPath(path)
    f = QFont("Comic Sans MS")
    f.setPixelSize(max(1, int(11 * pop)))
    f.setBold(True)
    p.setFont(f)
    p.setPen(_alpha(QColor("#111111"), fade))
    p.drawText(QRectF(cx - 8, cy - 8, 16, 16), Qt.AlignmentFlag.AlignCenter, "!")


def _flash(p: QPainter, x: _Ctx):
    """Flashbang: the page goes white and fades back."""
    a = (1 - x.k) ** 2.2
    p.fillRect(x.page, _alpha(QColor("white"), 0.92 * a))
    g = QRadialGradient(x.c, 70)
    g.setColorAt(0.0, _alpha(QColor("white"), a))
    g.setColorAt(1.0, _alpha(QColor("white"), 0))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(g)
    p.drawEllipse(x.c, 70, 70)


def _confetti(p: QPainter, x: _Ctx):
    """Confetti in both clashing colours bursts up and rains down (the logo shakes)."""
    fade = x.fade(0.6)
    p.setPen(Qt.PenStyle.NoPen)
    for part in x.parts:
        t = x.b
        a = -0.45 + part["x"] * 0.75          # thrown out sideways, a little up
        v = 170 * part["v"]
        px = x.c.x() + x.side * math.cos(a) * v * t
        py = x.c.y() + math.sin(a) * v * t + 120 * t * t
        p.save()
        p.translate(px, py)
        p.rotate(math.degrees(part["spin"] * t) + part["w"] * 57)
        p.setBrush(_alpha((x.a1, x.a2)[part["i"] % 2], fade))
        p.drawRect(QRectF(-2.5 * part["s"], -1.3, 5 * part["s"], 2.6))
        p.restore()


def _shine(p: QPainter, x: _Ctx):
    """A glint of light sweeps across the logo and a few stars twinkle round it."""
    r = x.rect
    band = r.left() - r.width() + _ease(x.k / 0.5) * r.width() * 3
    clip = QPainterPath()
    clip.addRoundedRect(r.adjusted(r.width() * 0.04, r.height() * 0.04,
                                   -r.width() * 0.04, -r.height() * 0.04),
                        r.width() * 0.26, r.width() * 0.26)
    p.save()
    p.setClipPath(clip)
    g = QLinearGradient(QPointF(band, r.top()), QPointF(band + r.width() * 0.6, r.bottom()))
    g.setColorAt(0.0, QColor(255, 255, 255, 0))
    g.setColorAt(0.5, QColor(255, 255, 255, 200))
    g.setColorAt(1.0, QColor(255, 255, 255, 0))
    p.fillRect(r, g)
    p.restore()
    gold = QColor("#ffc93c") if x.name == "Royal" else QColor(x.a1).lighter(130)
    p.setPen(Qt.PenStyle.NoPen)
    for n, part in enumerate(x.parts[:6]):
        st = (x.b - 0.12 - n * 0.1) / 0.45
        if not 0 <= st <= 1:
            continue
        ang = -math.pi * 0.9 + n * math.pi * 0.36
        pt = QPointF(x.c.x() + math.cos(ang) * x.u * 0.95,
                     x.c.y() - x.u * 0.1 + math.sin(ang) * x.u * 0.75)
        p.save()
        p.translate(pt)
        p.setBrush(gold if n % 2 else QColor("white"))
        p.drawPath(_shape("star", math.sin(st * math.pi) * 5 * part["s"]))
        p.restore()


PAINTERS = {"laser": _laser, "code": _code, "neon": _neon, "petals": _petals,
            "sonar": _sonar, "embers": _embers, "fireflies": _fireflies,
            "pixels": _pixels, "comic": _comic, "flash": _flash,
            "confetti": _confetti, "shine": _shine}


# ---------------------------------------------------------------------- idle, on the logo

def comic_bounce(t: float) -> float:
    """0, or how far into a squash-and-bounce the comic logo is (one every 4 s): a
    squash that starts and ends still, a little stretch past it and a settle."""
    ph = (t % 4.0) / 0.6
    if ph >= 1:
        return 0.0
    return 6.5 * math.sin(math.pi * ph) ** 2 * math.cos(1.1 * math.pi * ph) * math.exp(-3 * ph)


def _tile(r: QRectF) -> QPainterPath:
    path = QPainterPath()
    s = r.width()
    path.addRoundedRect(r.adjusted(s * 0.04, s * 0.04, -s * 0.04, -s * 0.04),
                        s * 0.26, s * 0.26)
    return path


def _sheen(p: QPainter, r: QRectF, t: float, on: float):
    """A soft band of light sweeping across the tile now and then (Onion Board's logo
    does the same)."""
    ph = (t % SHEEN_PERIOD) / SHEEN_TIME
    if ph >= 1.0:
        return
    s = r.width()
    p.save()
    p.setClipPath(_tile(r))
    pos = -0.6 + 2.2 * ph
    g = QLinearGradient(QPointF(r.left() + s * (pos - 0.3), r.top()),
                        QPointF(r.left() + s * (pos + 0.3), r.bottom()))
    g.setColorAt(0.0, QColor(255, 255, 255, 0))
    g.setColorAt(0.5, QColor(255, 255, 255, int(85 + 70 * on)))
    g.setColorAt(1.0, QColor(255, 255, 255, 0))
    p.fillRect(r, g)
    p.restore()


def _scanline(p: QPainter, r: QRectF, t: float, on: float):
    """A terminal's scan line rolling down the tile."""
    ph = (t % 2.6) / 0.8
    if ph >= 1.0:
        return
    y = r.top() + r.height() * ph
    p.save()
    p.setClipPath(_tile(r))
    col = QColor(theme.T.get("accent") or theme.BRAND[0]).lighter(160)
    p.fillRect(QRectF(r.left(), y - 1, r.width(), 2), _alpha(col, 0.7 * on))
    p.fillRect(QRectF(r.left(), y - 4, r.width(), 3), _alpha(col, 0.2 * on))
    p.restore()


# ---------------------------------------------------------------------- idle, in the tile
# Drawn over the logo and kept inside its rounded tile: the logo sits in the page's
# corner with the tabs right beside it, so there's no room for anything round it.

@dataclass
class _Idle:
    """What an idle animation draws with: the logo's `rect` and size `u`, `t` seconds
    in, its strength `on`, the theme's `a1` / `a2` and `name`."""
    rect: QRectF
    u: float
    t: float
    on: float
    a1: QColor
    a2: QColor
    name: str


def paint_idle(p: QPainter, style: str, x: _Idle):
    p.save()
    p.setClipPath(_tile(x.rect))
    IDLE.get(style, _idle_shine)(p, x)
    p.restore()


def _rim(p: QPainter, x: _Idle, col: QColor, strength: float, speed: float = 1.6):
    """A soft glow round the inside of the tile's edge, breathing slowly."""
    breathe = 0.5 + 0.5 * math.sin(x.t * speed)
    a = (0.25 + 0.3 * breathe) * strength * x.on
    p.setBrush(Qt.BrushStyle.NoBrush)
    r = x.rect.adjusted(1, 1, -1, -1)
    for width, k in ((4.0, 0.45), (1.6, 1.0)):
        p.setPen(QPen(_alpha(col, a * k), width))
        p.drawRoundedRect(r, x.u * 0.24, x.u * 0.24)


def _cycle(t: float, period: float, offset: float, length: float) -> float:
    """-1, or 0..1 of the way through this round of something that happens every
    `period` seconds (from `offset`) and lasts `length`."""
    ph = ((t - offset) % period) / length
    return ph if ph < 1 else -1.0


def _idle_shine(p: QPainter, x: _Idle):
    _rim(p, x, QColor("white"), 0.6)
    _sheen(p, x.rect, x.t, x.on)


def _idle_flash(p: QPainter, x: _Idle):
    _sheen(p, x.rect, x.t, 1.0)
    ph = _cycle(x.t, 3.5, 1.0, 0.5)
    if ph >= 0:
        p.save()
        p.translate(x.rect.right() - 5, x.rect.top() + 5)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(_alpha(QColor("white"), min(1.0, x.on * 1.6)))
        p.drawPath(_shape("star", math.sin(ph * math.pi) * 4.5))
        p.restore()


def _idle_laser(p: QPainter, x: _Idle):
    _rim(p, x, QColor(255, 40, 40), 1.3, speed=2.2)
    c = QPointF(x.rect.center().x(), x.rect.top() + x.u * EYE_Y)
    breathe = 0.5 + 0.5 * math.sin(x.t * 2.2)
    g = QRadialGradient(c, x.u * 0.3)
    g.setColorAt(0.5, _alpha(QColor(255, 40, 40), 0.45 * breathe * x.on))
    g.setColorAt(1.0, _alpha(QColor(255, 0, 0), 0))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(g)
    p.drawEllipse(c, x.u * 0.3, x.u * 0.3)


def _idle_code(p: QPainter, x: _Idle):
    _rim(p, x, x.a1, 0.5)
    _scanline(p, x.rect, x.t, x.on)
    f = QFont("Consolas")
    f.setPixelSize(6)
    f.setBold(True)
    p.setFont(f)
    for n, dx in enumerate((3, x.u - 6)):
        ph = _cycle(x.t, 1.9, n * 0.9, 1.5)
        if ph < 0:
            continue
        y = x.rect.top() + ph * (x.rect.height() + 6)
        ch = GLYPHS[int(x.t * 6 + n * 5) % len(GLYPHS)]
        p.setPen(_alpha(x.a1.lighter(170), math.sin(ph * math.pi) * x.on * 1.3))
        p.drawText(QPointF(x.rect.left() + dx, y), ch)


def _idle_neon(p: QPainter, x: _Idle):
    buzz = 0.3 if int(x.t * 10) % 37 in (0, 2) else 1.0   # a neon tube flickering
    col = x.a1 if int(x.t / 3) % 2 == 0 else x.a2
    r = x.rect.adjusted(1.2, 1.2, -1.2, -1.2)
    p.setBrush(Qt.BrushStyle.NoBrush)
    for width, a in ((4.5, 0.4), (1.5, 1.0)):
        p.setPen(QPen(_alpha(col.lighter(130), a * buzz * min(1.0, x.on * 1.5)), width))
        p.drawRoundedRect(r, x.u * 0.24, x.u * 0.24)


def _idle_petals(p: QPainter, x: _Idle):
    _rim(p, x, x.a2, 0.5)
    kind = {"Cherry Blossom": "petal", "Barbie": "heart"}.get(x.name, "star")
    p.setPen(Qt.PenStyle.NoPen)
    for n in range(2):
        ph = _cycle(x.t, 3.2, n * 1.6, 2.6)
        if ph < 0:
            continue
        px = x.rect.left() + x.u * (0.2 + 0.6 * n) + math.sin(ph * 6 + n) * 2.5
        py = x.rect.top() + ph * x.rect.height()
        p.save()
        p.translate(px, py)
        p.rotate(ph * 160 + n * 90)
        p.setBrush(_alpha(QColor("white") if n else x.a2.lighter(140),
                          math.sin(ph * math.pi) * min(1.0, x.on * 1.6)))
        p.drawPath(_shape(kind, 2.4))
        p.restore()


def _idle_sonar(p: QPainter, x: _Idle):
    _rim(p, x, x.a1, 0.5)
    ph = _cycle(x.t, 2.6, 0.0, 1.4)
    if ph >= 0:
        c = QPointF(x.rect.center().x(), x.rect.top() + x.u * EYE_Y)
        rad = x.u * 0.18 + ph * x.u * 0.55
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(_alpha(QColor("white"), (1 - ph) * 0.8 * x.on), 1.2))
        p.drawEllipse(c, rad, rad)


def _idle_embers(p: QPainter, x: _Idle):
    _rim(p, x, QColor("#ff8a2b"), 1.0, speed=2.4)
    p.setPen(Qt.PenStyle.NoPen)
    hot = QColor(255, 225, 130)
    for n in range(4):
        ph = _cycle(x.t, 1.7, n * 0.43, 1.3)
        if ph < 0:
            continue
        px = x.rect.left() + x.u * (0.18 + 0.21 * n) + math.sin(ph * 9 + n) * 1.2
        py = x.rect.bottom() - 2 - ph * x.u * 0.8
        p.setBrush(_alpha(hot, (1 - ph) * min(1.0, x.on * 1.7)))
        p.drawEllipse(QPointF(px, py), 1.1, 1.1)


def _idle_fireflies(p: QPainter, x: _Idle):
    c = x.rect.center()
    p.setPen(Qt.PenStyle.NoPen)
    for n in range(2):
        a = x.t * (0.8 + 0.3 * n) + n * 3.1
        pt = QPointF(c.x() + math.cos(a) * x.u * 0.36, c.y() + math.sin(a) * x.u * 0.36)
        lit = (0.3 + 0.7 * (0.5 + 0.5 * math.sin(x.t * 4 + n * 2))) * min(1.0, x.on * 1.6)
        g = QRadialGradient(pt, 3.2)
        g.setColorAt(0.0, _alpha(QColor(255, 255, 190), lit))
        g.setColorAt(0.45, _alpha(QColor(210, 255, 120), 0.6 * lit))
        g.setColorAt(1.0, _alpha(QColor(210, 255, 120), 0))
        p.setBrush(g)
        p.drawEllipse(pt, 3.2, 3.2)


def _idle_pixels(p: QPainter, x: _Idle):
    p.setPen(Qt.PenStyle.NoPen)
    r = x.rect.adjusted(4, 4, -4, -4)
    corners = (r.topLeft(), r.topRight(), r.bottomRight(), r.bottomLeft())
    step = int(x.t * 6)                      # 6 steps a second, like an old game
    for n, pt in enumerate(corners):
        if (step + n * 3) % 8 < 2:
            p.setBrush(_alpha(QColor("white"), min(1.0, x.on * 1.7)))
            p.drawRect(QRectF(round(pt.x()) - 1, round(pt.y()) - 1, 2, 2))


def _idle_comic(p: QPainter, x: _Idle):
    _rim(p, x, QColor("#111111"), 0.5)


def _idle_confetti(p: QPainter, x: _Idle):
    p.setPen(Qt.PenStyle.NoPen)
    for n in range(3):
        ph = _cycle(x.t, 2.0, n * 0.66, 1.6)
        if ph < 0:
            continue
        px = x.rect.left() + x.u * (0.2 + 0.3 * n) + math.sin(ph * 7) * 1.5
        py = x.rect.top() + ph * x.rect.height()
        p.save()
        p.translate(px, py)
        p.rotate(ph * 400 + n * 60)
        p.setBrush(_alpha((x.a2.lighter(150), QColor("white"))[n % 2],
                          math.sin(ph * math.pi) * min(1.0, x.on * 1.6)))
        p.drawRect(QRectF(-1.6, -0.8, 3.2, 1.6))
        p.restore()


IDLE = {"laser": _idle_laser, "code": _idle_code, "neon": _idle_neon,
        "petals": _idle_petals, "sonar": _idle_sonar, "embers": _idle_embers,
        "fireflies": _idle_fireflies, "pixels": _idle_pixels, "comic": _idle_comic,
        "flash": _idle_flash, "confetti": _idle_confetti, "shine": _idle_shine}
