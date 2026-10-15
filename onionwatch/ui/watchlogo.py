"""The Onion Watch logo that shows whether it's watching: the eye shut while nothing
is watched; on Start watching it snaps open and fires a laser sweep across the page,
then keeps glowing red (a slow pulse and a glint) for as long as it watches.

The glow only moves while the app is in front (appstate.pause_in_background): behind a
game it holds still, red, and costs nothing."""
from __future__ import annotations

import math
import time

from PySide6.QtCore import QEvent, QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import (QColor, QLinearGradient, QPainter, QPen, QPixmap,
                           QRadialGradient)
from PySide6.QtWidgets import QWidget

from onionwatch import theme
from onionwatch.style import appstate

FRAME_MS = 33          # 30 fps while it moves
PULSE_S = 1.8          # one breath of the red glow
SCAN_S = 3.4           # the eye looking left, right and back
SCAN_X = 0.075         # ...this far each way, in logo widths
BURST_S = 1.25         # the laser sweep on Start watching
FADE_S = 0.35          # the glow dying down on Stop
EYE_Y = 0.60           # the eye's centre, in logo heights (theme.paint_logo's `ey`)
EYE_R = 0.155          # ...and the iris's radius
HOT = QColor(255, 40, 40)
CORE = QColor(255, 236, 228)


def _ease(t: float) -> float:
    t = min(1.0, max(0.0, t))
    return t * t * (3 - 2 * t)


class WatchLogo(QWidget):
    """The logo, `px` square, centred in a `w` x `h` box. `set_watching(on)` opens and
    shuts the eye; `beam_host`: the widget the laser sweeps across (it's drawn on a
    see-through layer over it, gone again when the sweep ends)."""

    def __init__(self, px: int, w: int, h: int, beam_host: QWidget | None = None,
                 parent=None):
        super().__init__(parent)
        self.px = px
        self.setFixedSize(w, h)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.watching = False
        self._open = 0.0          # 0 shut .. 1 fully lit (eased in and out)
        self._t = 0.0             # seconds of glow, for the pulse
        self._burst = -1.0        # seconds into the laser sweep, or -1
        self._scan = 0.0          # seconds of looking around (from the sweep's end)
        self._last = time.monotonic()
        self._asleep = self._awake = self._blank = QPixmap()
        self.retheme()
        self._timer = QTimer(self)
        self._timer.setInterval(FRAME_MS)
        self._timer.timeout.connect(self._tick)
        appstate.pause_in_background(self, self._resume, self._pause)
        self.beam = _Beam(self, beam_host) if beam_host is not None else None

    # ------------------------------------------------------------------ outside
    def retheme(self):
        """The theme changed: both eyes in its colours."""
        self._asleep = theme.themed_logo(self.px * 2, awake=False)
        self._awake = theme.themed_logo(self.px * 2, awake=True)
        self._blank = theme.themed_logo(self.px * 2, eye=False)   # under the red eye
        for pm in (self._asleep, self._awake, self._blank):
            pm.setDevicePixelRatio(2)
        self.update()

    def pixmap(self) -> QPixmap:
        """The logo as it rests now (open while watching, shut while not)."""
        return self._awake if self.watching else self._asleep

    def set_watching(self, on: bool):
        on = bool(on)
        if on == self.watching:
            return
        self.watching = on
        moving = self.isVisible() and appstate.active()
        if on and moving:
            self._burst = self._scan = 0.0
            if self.beam is not None:
                self.beam.start()
        elif not moving:          # no show to put on: straight to how it rests
            self._open = 1.0 if on else 0.0
            self._burst = -1.0
        if not on and self.beam is not None:
            self.beam.stop()
        if moving:
            self._resume()
        self.update()

    def eye_center(self) -> QPointF:
        """The eye's centre in this widget's coordinates: looking around while it
        watches (straight ahead while the laser fires)."""
        r = self._logo_rect()
        look = math.sin(self._scan * 2 * math.pi / SCAN_S)
        return QPointF(r.center().x() + look * SCAN_X * r.width(),
                       r.top() + r.height() * EYE_Y)

    def burst_t(self) -> float:
        return self._burst

    # ------------------------------------------------------------------ time
    def showEvent(self, ev):
        if appstate.active():
            self._resume()
        super().showEvent(ev)

    def hideEvent(self, ev):
        self._pause()
        super().hideEvent(ev)

    def _resume(self):
        if self.watching or self._open > 0:
            self._last = time.monotonic()
            self._timer.start()

    def _pause(self):
        self._timer.stop()
        # held still, it rests the way it should look: lit while watching
        self._open = 1.0 if self.watching else 0.0
        self._burst = -1.0
        if self.beam is not None:
            self.beam.stop()
        self.update()

    def _tick(self):
        now = time.monotonic()
        self.step(min(0.1, now - self._last))
        self._last = now
        if not self.watching and self._open <= 0:
            self._timer.stop()

    def step(self, dt: float):
        """Move the animation on by `dt` seconds (the tests call this directly)."""
        self._t += dt
        if self.watching:
            self._open = min(1.0, self._open + dt / 0.15)
        else:
            self._open = max(0.0, self._open - dt / FADE_S)
        if self._burst >= 0:
            self._burst += dt
            if self._burst >= BURST_S:
                self._burst = -1.0
        elif self.watching:
            self._scan += dt
        if self.beam is not None:
            self.beam.step()
        self.update()

    # ------------------------------------------------------------------ paint
    def _logo_rect(self) -> QRectF:
        return QRectF((self.width() - self.px) / 2, (self.height() - self.px) / 2,
                      self.px, self.px)

    def glow(self) -> float:
        """How bright the eye burns now, 0..1: a flash as the laser fires, then a
        slow breath."""
        g = 0.72 + 0.28 * math.sin(self._t * 2 * math.pi / PULSE_S)
        if self._burst >= 0:
            b = self._burst
            g = max(g, 1.0 if b < BURST_S * 0.8 else 1.0 - (b - BURST_S * 0.8) / (BURST_S * 0.2))
        return g * _ease(self._open)

    def paintEvent(self, ev):
        p = QPainter(self)
        appstate.snap_to_pixels(p)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = self._logo_rect()
        lit = self.watching or self._open > 0
        p.drawPixmap(r.topLeft(), self._blank if lit else self._asleep)
        g = self.glow()
        if g > 0:
            paint_laser_eye(p, self.eye_center(), self.px * EYE_R, g, self._t)
        p.end()


def paint_laser_eye(p: QPainter, c: QPointF, r: float, g: float, t: float):
    """A red-hot iris over the logo's eye at `c` (iris radius `r`), `g` 0..1 bright:
    a glow round it, a white-hot pupil and a twinkling flare."""
    p.save()
    p.setPen(Qt.PenStyle.NoPen)
    halo = QRadialGradient(c, r * 1.9)
    halo.setColorAt(0.0, QColor(255, 60, 40, int(210 * g)))
    halo.setColorAt(0.55, QColor(255, 30, 30, int(90 * g)))
    halo.setColorAt(1.0, QColor(255, 0, 0, 0))
    p.setBrush(halo)
    p.drawEllipse(c, r * 1.9, r * 1.9)
    p.setBrush(HOT)
    p.drawEllipse(c, r, r)
    core = QRadialGradient(c, r * 0.75)
    core.setColorAt(0.0, CORE)
    core.setColorAt(1.0, QColor(255, 120, 90, 0))
    p.setBrush(core)
    p.drawEllipse(c, r * 0.75 * (0.8 + 0.2 * g), r * 0.75 * (0.8 + 0.2 * g))
    # the flare: a thin cross that twinkles a little out of step with the pulse
    tw = g * (0.75 + 0.25 * math.sin(t * 5.3))
    for dx, dy, length in ((1, 0, r * 3.4), (0, 1, r * 2.0)):
        a = QPointF(c.x() - dx * length * tw, c.y() - dy * length * tw)
        b = QPointF(c.x() + dx * length * tw, c.y() + dy * length * tw)
        grad = QLinearGradient(a, b)
        grad.setColorAt(0.0, QColor(255, 80, 60, 0))
        grad.setColorAt(0.5, QColor(255, 235, 225, int(230 * tw)))
        grad.setColorAt(1.0, QColor(255, 80, 60, 0))
        p.setPen(QPen(grad, max(0.8, r * 0.28), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawLine(a, b)
    p.restore()


class _Beam(QWidget):
    """The laser sweep: a see-through layer over `host` (clicks go through it), shown
    only while the logo's burst runs. The beam leaves the eye, swings down across the
    page and back like it's scanning the screen, then fades."""

    def __init__(self, logo: WatchLogo, host: QWidget):
        super().__init__(host)
        self.logo = logo
        self.host = host
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

    def angle(self, b: float) -> float:
        """The beam's slope in degrees below level, `b` seconds in: out level, down
        across the page, and back up a little."""
        u = b / BURST_S
        if u < 0.55:
            return -3 + 33 * _ease(u / 0.55)
        return 30 - 18 * _ease((u - 0.55) / 0.45)

    def paintEvent(self, ev):
        b = self.logo.burst_t()
        if b < 0:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        c = self.logo.mapTo(self.host, self.logo.eye_center().toPoint())
        c = QPointF(c)
        # the beam reaches out over the first tenth of the sweep, fades in its last fifth
        reach = _ease(b / (BURST_S * 0.12))
        fade = 1.0 if b < BURST_S * 0.8 else max(0.0, 1 - (b - BURST_S * 0.8) / (BURST_S * 0.2))
        flicker = 0.85 + 0.15 * math.sin(b * 90)
        rtl = self.layoutDirection() == Qt.LayoutDirection.RightToLeft
        side = -1 if rtl else 1
        a = math.radians(self.angle(b))
        length = math.hypot(self.width(), self.height()) * reach
        end = QPointF(c.x() + side * math.cos(a) * length, c.y() + math.sin(a) * length)
        r = self.logo.px * EYE_R
        for width, colour in ((r * 5.0, QColor(255, 0, 0, int(55 * fade))),
                              (r * 2.2, QColor(255, 40, 30, int(170 * fade * flicker))),
                              (r * 0.8, QColor(255, 235, 225, int(255 * fade * flicker)))):
            grad = QLinearGradient(c, end)
            grad.setColorAt(0.0, colour)
            tail = QColor(colour)
            tail.setAlpha(0)
            grad.setColorAt(1.0, tail)
            p.setPen(QPen(grad, width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawLine(c, end)
        # the muzzle flash at the eye
        flash = QRadialGradient(c, r * 3.5)
        flash.setColorAt(0.0, QColor(255, 240, 230, int(220 * fade)))
        flash.setColorAt(0.4, QColor(255, 40, 30, int(120 * fade)))
        flash.setColorAt(1.0, QColor(255, 0, 0, 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(flash)
        p.drawEllipse(c, r * 3.5, r * 3.5)
        p.end()
