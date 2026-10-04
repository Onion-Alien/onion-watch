"""The start-up splash: Hoot hopping about in the middle of the screen, flapping at
the top of each hop, from the moment the QApplication exists until the main window
is up. Just Hoot on the desktop (no card or caption), in the saved theme's colours
(read straight from config.json; the rest of the settings load later).

Start-up builds the window on the UI thread, so a Qt splash would only move in
fits and starts. Instead a thread of its own draws each frame into a QImage at the
monitor's real resolution (QPainter on a QImage is fine off the UI thread) and
hands it to a native layered window: Hoot hops smoothly however busy the UI thread
is. His poses are drawn once as sprites, so a frame is a single image draw (light
on the GIL the UI thread needs). Windows only; elsewhere show() shows nothing.
"""
from __future__ import annotations

import json
import logging
import math
import sys
import threading
import time

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter

from onionwatch import settings, theme
from onionwatch.owl import H as OWL_H
from onionwatch.owl import W as OWL_W
from onionwatch.owl import draw_owl

log = logging.getLogger(__name__)

CARD_W, CARD_H = 420, 330   # logical px; the window is this times the screen's scale
HOOT_H = 192
HOOT_W = HOOT_H * OWL_W / OWL_H
HOP = 0.62       # seconds per hop
HOP_PX = 46      # how high he gets
ROAM_PX = 95     # how far he wanders either side of the middle
FPS = 60
# while it's up, Python hands the GIL over every 0.5 ms instead of every 5: each frame
# takes the GIL many times, and a busy UI thread would otherwise hold it 5 ms each
SWITCH_S = 0.0005

_splash: Splash | None = None
_sprites: dict[tuple, QImage] = {}   # Hoot drawn once per (pose, scale)


def _sprite(flap: float, tufts: float, blink: float, scale: float) -> QImage:
    """Hoot in this pose, drawn once at `scale` (device px per logical px) with room
    to spare for the stretch."""
    key = (round(flap, 1), round(tufts), blink, scale)
    img = _sprites.get(key)
    if img is None:
        over = scale * 1.25
        img = QImage(round(HOOT_W * over), round(HOOT_H * over),
                     QImage.Format_ARGB32_Premultiplied)
        img.fill(Qt.transparent)
        p = QPainter(img)
        draw_owl(p, QRectF(0, 0, img.width(), img.height()), 0.0,
                 blink=blink, flap=key[0], tufts=key[1])
        p.end()
        _sprites[key] = img
    return img


def paint_frame(p: QPainter, t: float, w: float, h: float, scale: float = 1.0):
    """One frame of Hoot hopping, `t` seconds in, on a `w` x `h` (logical px) canvas
    that `p` maps onto `scale` device px per logical px."""
    u = (t % HOP) / HOP                     # 0..1 through this hop
    air = 4 * u * (1 - u)                   # 0 on the ground, 1 at the top
    land = max(0.0, 1 - u / 0.18)           # just landed: squash, tufts droop
    wander = math.sin(t * 0.9)
    facing = 1 if math.cos(t * 0.9) >= 0 else -1   # the way he's heading
    stretch = 1 + 0.08 * air - 0.14 * land   # taller in the air, squat on landing
    foot_x = w / 2 + wander * ROAM_PX
    foot_y = h - 18
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.SmoothPixmapTransform)
    # a soft shadow on the ground, smaller while he's up
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(0, 0, 0, round(70 - 40 * air)))
    sw = HOOT_W * 0.62 * (1 - 0.35 * air)
    p.drawEllipse(QRectF(foot_x - sw / 2, foot_y - 7, sw, 14))
    # Hoot, squashed about his feet and mirrored to face where he's going
    p.save()
    p.translate(foot_x, foot_y - HOP_PX * air)
    p.scale(facing / stretch ** 0.5, stretch)
    blink = 1.0 if (t % 2.7) > 2.55 else 0.0
    p.drawImage(QRectF(-HOOT_W / 2, -HOOT_H, HOOT_W, HOOT_H),
                _sprite(0.8 * air, 12 * land - 8 * air, blink, scale))
    p.restore()


class Splash:
    """A click-through, never-activated layered window owned by a thread that draws
    and shows every frame itself (see the module docstring)."""

    def __init__(self):
        self._stop = threading.Event()
        self._up = threading.Event()
        self.ok = False   # the window came up and showed its first frame
        self._switch = sys.getswitchinterval()
        sys.setswitchinterval(SWITCH_S)
        self._thread = threading.Thread(target=self._run, name="splash", daemon=True)
        self._thread.start()
        self._up.wait(1.0)   # the first frame is on screen (or it gave up)

    def isVisible(self) -> bool:
        return self.ok and self._thread.is_alive() and not self._stop.is_set()

    def close(self):
        self._stop.set()
        self._thread.join(1.0)
        sys.setswitchinterval(self._switch)

    def _run(self):
        try:
            self._loop()
        except Exception:  # noqa: BLE001 - a splash must never stop the app starting
            log.debug("splash failed", exc_info=True)
        finally:
            self._up.set()

    def _loop(self):
        import ctypes
        from ctypes import wintypes as wt

        user, gdi = ctypes.windll.user32, ctypes.windll.gdi32
        Hd = ctypes.c_void_p
        user.CreateWindowExW.restype = Hd
        user.CreateWindowExW.argtypes = [wt.DWORD, wt.LPCWSTR, wt.LPCWSTR, wt.DWORD,
                                         ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                         ctypes.c_int, Hd, Hd, Hd, Hd]
        user.MonitorFromPoint.restype = Hd
        user.MonitorFromPoint.argtypes = [wt.POINT, wt.DWORD]
        user.GetMonitorInfoW.argtypes = [Hd, Hd]
        user.ShowWindow.argtypes = [Hd, ctypes.c_int]
        user.DestroyWindow.argtypes = [Hd]
        user.PeekMessageW.argtypes = [Hd, Hd, wt.UINT, wt.UINT, wt.UINT]
        user.TranslateMessage.argtypes = [Hd]
        user.DispatchMessageW.argtypes = [Hd]
        user.UpdateLayeredWindow.argtypes = [Hd, Hd, Hd, Hd, Hd, Hd, wt.DWORD, Hd, wt.DWORD]
        gdi.CreateCompatibleDC.restype = Hd
        gdi.CreateCompatibleDC.argtypes = [Hd]
        gdi.CreateDIBSection.restype = Hd
        gdi.CreateDIBSection.argtypes = [Hd, Hd, wt.UINT, ctypes.POINTER(Hd), Hd, wt.DWORD]
        gdi.SelectObject.restype = Hd
        gdi.SelectObject.argtypes = [Hd, Hd]
        gdi.DeleteObject.argtypes = [Hd]
        gdi.DeleteDC.argtypes = [Hd]

        # centred on the work area of the monitor the mouse is on, at that monitor's
        # scale (the process is per-monitor DPI aware by now: Qt set that up)
        pt = wt.POINT()
        user.GetCursorPos(ctypes.byref(pt))
        mon = user.MonitorFromPoint(pt, 2)   # MONITOR_DEFAULTTONEAREST

        class MONITORINFO(ctypes.Structure):
            _fields_ = [("cbSize", wt.DWORD), ("rcMonitor", wt.RECT), ("rcWork", wt.RECT),
                        ("dwFlags", wt.DWORD)]

        mi = MONITORINFO(cbSize=ctypes.sizeof(MONITORINFO))
        user.GetMonitorInfoW(mon, ctypes.byref(mi))
        dpi_x, dpi_y = wt.UINT(96), wt.UINT(96)
        try:
            ctypes.windll.shcore.GetDpiForMonitor(Hd(mon), 0, ctypes.byref(dpi_x),
                                                  ctypes.byref(dpi_y))
        except Exception:  # noqa: BLE001 - no per-monitor DPI: 100 %
            pass
        k = dpi_x.value / 96
        w, h = round(CARD_W * k), round(CARD_H * k)
        wa = mi.rcWork
        x = (wa.left + wa.right) // 2 - w // 2
        y = (wa.top + wa.bottom) // 2 - h // 2

        # WS_EX_LAYERED | TOPMOST | TOOLWINDOW | NOACTIVATE | TRANSPARENT (click-through)
        ex = 0x80000 | 0x8 | 0x80 | 0x08000000 | 0x20
        hwnd = user.CreateWindowExW(ex, "Static", "Onion Watch", 0x80000000,   # WS_POPUP
                                    x, y, w, h, None, None, None, None)
        if not hwnd:
            return

        class BITMAPINFOHEADER(ctypes.Structure):
            _fields_ = [("biSize", wt.DWORD), ("biWidth", wt.LONG), ("biHeight", wt.LONG),
                        ("biPlanes", wt.WORD), ("biBitCount", wt.WORD),
                        ("biCompression", wt.DWORD), ("biSizeImage", wt.DWORD),
                        ("biXPelsPerMeter", wt.LONG), ("biYPelsPerMeter", wt.LONG),
                        ("biClrUsed", wt.DWORD), ("biClrImportant", wt.DWORD)]

        class BLENDFUNCTION(ctypes.Structure):
            _fields_ = [("op", ctypes.c_ubyte), ("flags", ctypes.c_ubyte),
                        ("alpha", ctypes.c_ubyte), ("fmt", ctypes.c_ubyte)]

        bih = BITMAPINFOHEADER(biSize=ctypes.sizeof(BITMAPINFOHEADER), biWidth=w,
                               biHeight=-h, biPlanes=1, biBitCount=32)   # top-down BGRA
        dc = gdi.CreateCompatibleDC(None)
        bits = Hd()
        dib = gdi.CreateDIBSection(dc, ctypes.byref(bih), 0, ctypes.byref(bits), None, 0)
        old = gdi.SelectObject(dc, dib)
        img = QImage(w, h, QImage.Format_ARGB32_Premultiplied)   # premultiplied BGRA, as GDI wants
        nbytes = w * h * 4
        size, src, dst = wt.SIZE(w, h), wt.POINT(0, 0), wt.POINT(x, y)
        blend = BLENDFUNCTION(0, 0, 255, 1)   # AC_SRC_OVER, per-pixel alpha
        msg = wt.MSG()
        t0 = time.monotonic()
        try:
            while not self._stop.is_set():
                start = time.monotonic()
                img.fill(Qt.transparent)
                p = QPainter(img)
                try:
                    p.scale(k, k)   # drawn at the monitor's real resolution, never stretched
                    paint_frame(p, start - t0, CARD_W, CARD_H, k)
                finally:
                    p.end()   # never leave img mid-paint: Qt aborts when it's freed
                ctypes.memmove(bits, bytes(img.constBits()), nbytes)
                user.UpdateLayeredWindow(hwnd, None, ctypes.byref(dst), ctypes.byref(size),
                                         dc, ctypes.byref(src), 0, ctypes.byref(blend), 2)
                if not self._up.is_set():
                    user.ShowWindow(hwnd, 4)   # SW_SHOWNOACTIVATE
                    self.ok = True
                    self._up.set()
                while user.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1):   # PM_REMOVE
                    user.TranslateMessage(ctypes.byref(msg))
                    user.DispatchMessageW(ctypes.byref(msg))
                self._stop.wait(max(0.0, 1 / FPS - (time.monotonic() - start)))
        finally:
            user.DestroyWindow(hwnd)
            gdi.SelectObject(dc, old)
            gdi.DeleteObject(dib)
            gdi.DeleteDC(dc)


def show() -> Splash | None:
    """Put the splash up, centred on the screen the mouse is on (Windows only)."""
    global _splash
    try:
        cfg = json.loads((settings.APP_DIR / settings.CONFIG).read_text(encoding="utf-8-sig"))
        theme.set_current(cfg.get("theme", theme.APP_DEFAULT))
    except Exception:  # noqa: BLE001 - first launch, or unreadable: his own theme
        theme.set_current(theme.APP_DEFAULT)
    if QGuiApplication.platformName() != "windows":
        return None
    _splash = Splash()
    if not _splash.ok:
        _splash.close()
        _splash = None
    return _splash


def close():
    """Take the splash down (the window is up, or start-up failed)."""
    global _splash
    if _splash is not None:
        _splash.close()
        _splash = None
    _sprites.clear()
