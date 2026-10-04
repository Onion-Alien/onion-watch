"""Windows to watch: the open ones listed, a remembered one found again, and one
window's picture copied even while other windows cover it.

The copy is PrintWindow with PW_RENDERFULLCONTENT: Windows draws the window's own
content (DirectX games included, through the desktop compositor) into our bitmap,
whatever is on top of it. That's what lets a game be watched after you alt-tab
away from it. Two things it can't do:

- a **minimized** window isn't drawn at all, so there's nothing to see
  (`WindowGrabber.minimized`); covering it with other windows is fine;
- a few games (exclusive fullscreen, some anti-cheat) come out black
  (`Watcher.black` says so); watching the screen they're on works for those.

A window is remembered as a WindowRef (program file name, title, which copy), not
by its handle, which changes every time the game starts. `find` looks it up again:
the same title from the same program first, then any window of that program. With
several copies of a game open, `nth` counts them in the order they were started, so
"copy 2" stays the second account's window for as long as both run.

Only the client area (inside the frame, without the title bar) is copied, so
pictures cut from a screenshot of the game match whether it's windowed or not.
"""
from __future__ import annotations

import ctypes
import logging
import os
import sys
from ctypes import wintypes
from dataclasses import dataclass

import numpy as np

from onionwatch.screenwatch import (_BITMAPINFOHEADER, FMT_BGRA8, CaptureLost, WindowRef,
                                    frame_rgb, gray_2x, pick, to_gray)

log = logging.getLogger(__name__)

PW_CLIENTONLY = 0x1
PW_RENDERFULLCONTENT = 0x2
GWL_EXSTYLE = -20
WS_EX_TOOLWINDOW = 0x80
GW_OWNER = 4
DWMWA_CLOAKED = 14
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
MIN_SIDE = 32           # windows smaller than this (either way) aren't worth listing


class WindowGone(OSError):
    """The window to watch isn't open (yet)."""


@dataclass
class WindowInfo:
    """An open window, as listed."""
    hwnd: int
    title: str
    exe: str            # the program's file name, lower case ("" if it can't be read)
    pid: int
    started: int        # when its process started (FILETIME ticks): orders the copies
    width: int          # its client area, in pixels
    height: int
    minimized: bool = False

    @property
    def label(self) -> str:
        return self.title or self.exe or f"Window {self.hwnd:#x}"


# --------------------------------------------------------------------------- Win32

_api = None


def _win():
    """user32 / kernel32 / dwmapi with their argument types set once (HWND and HDC
    are pointers: without argtypes a 64-bit handle can be cut down to 32 bits)."""
    global _api
    if _api is not None:
        return _api
    u = ctypes.WinDLL("user32", use_last_error=True)
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    g = ctypes.WinDLL("gdi32")
    try:
        d = ctypes.WinDLL("dwmapi")
    except OSError:
        d = None
    H = wintypes.HWND
    u.IsWindow.argtypes = [H]
    u.IsWindowVisible.argtypes = [H]
    u.IsIconic.argtypes = [H]
    u.GetWindowTextLengthW.argtypes = [H]
    u.GetWindowTextW.argtypes = [H, wintypes.LPWSTR, ctypes.c_int]
    u.GetWindowThreadProcessId.argtypes = [H, ctypes.POINTER(wintypes.DWORD)]
    u.GetWindowThreadProcessId.restype = wintypes.DWORD
    u.GetClientRect.argtypes = [H, ctypes.POINTER(wintypes.RECT)]
    u.GetWindowLongW.argtypes = [H, ctypes.c_int]
    u.GetWindow.argtypes = [H, wintypes.UINT]
    u.GetWindow.restype = H
    u.GetForegroundWindow.restype = H
    u.PrintWindow.argtypes = [H, wintypes.HDC, wintypes.UINT]
    u.GetDC.argtypes = [H]
    u.GetDC.restype = wintypes.HDC
    u.ReleaseDC.argtypes = [H, wintypes.HDC]
    k.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    k.OpenProcess.restype = wintypes.HANDLE
    k.CloseHandle.argtypes = [wintypes.HANDLE]
    k.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
                                             ctypes.POINTER(wintypes.DWORD)]
    k.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
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
    if d is not None:
        d.DwmGetWindowAttribute.argtypes = [H, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
    _api = (u, k, g, d)
    return _api


def supported() -> bool:
    return sys.platform == "win32"


class _LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]


def foreground() -> int:
    """The window in front (its handle; 0 for none)."""
    if not supported():
        return 0
    return _win()[0].GetForegroundWindow() or 0


def idle_seconds() -> float | None:
    """How long since the mouse or keyboard was last touched (anywhere in the
    session), or None when that can't be told. Reads Windows' own count: no hook,
    nothing sent anywhere."""
    if not supported():
        return None
    u = _win()[0]
    k = ctypes.WinDLL("kernel32")
    info = _LASTINPUTINFO(ctypes.sizeof(_LASTINPUTINFO), 0)
    if not u.GetLastInputInfo(ctypes.byref(info)):
        return None
    # both counts wrap every 49.7 days: the difference still comes out right
    return ((k.GetTickCount() - info.dwTime) & 0xFFFFFFFF) / 1000


def _title(u, hwnd) -> str:
    n = u.GetWindowTextLengthW(hwnd)
    if n <= 0:
        return ""
    buf = ctypes.create_unicode_buffer(n + 1)
    u.GetWindowTextW(hwnd, buf, n + 1)
    return buf.value


def _process(k, pid: int) -> tuple[str, int]:
    """(file name lower case, start time) of a process; ("", 0) if it can't be read."""
    h = k.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return "", 0
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = wintypes.DWORD(len(buf))
        exe = os.path.basename(buf.value).lower() if k.QueryFullProcessImageNameW(
            h, 0, buf, ctypes.byref(size)) else ""
        times = [wintypes.FILETIME() for _ in range(4)]
        started = 0
        if k.GetProcessTimes(h, *(ctypes.byref(t) for t in times)):
            started = (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime
        return exe, started
    finally:
        k.CloseHandle(h)


def client_size(hwnd: int) -> tuple[int, int]:
    """The window's client area in pixels; (0, 0) if it can't be read."""
    u = _win()[0]
    r = wintypes.RECT()
    if not u.GetClientRect(hwnd, ctypes.byref(r)):
        return 0, 0
    return max(0, r.right - r.left), max(0, r.bottom - r.top)


def _cloaked(d, hwnd) -> bool:
    """Hidden by the desktop compositor (a suspended Store app, a window on another
    virtual desktop): listed as visible, but there's nothing to show."""
    if d is None:
        return False
    v = wintypes.DWORD()
    return d.DwmGetWindowAttribute(hwnd, DWMWA_CLOAKED, ctypes.byref(v), 4) == 0 and bool(v.value)


def list_windows() -> list[WindowInfo]:
    """The open, titled, top-level windows a person would call a window (no tool
    windows, owned popups or invisible ones), this app's own left out, in z-order.
    Minimized ones are listed too (flagged): they may be restored later."""
    if not supported():
        return []
    u, k, _g, d = _win()
    me = os.getpid()
    found: list[WindowInfo] = []
    procs: dict[int, tuple[str, int]] = {}
    proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def cb(hwnd, _lp):
        try:
            if not u.IsWindowVisible(hwnd) or u.GetWindow(hwnd, GW_OWNER):
                return True
            if u.GetWindowLongW(hwnd, GWL_EXSTYLE) & WS_EX_TOOLWINDOW or _cloaked(d, hwnd):
                return True
            title = _title(u, hwnd)
            if not title:
                return True
            pid = wintypes.DWORD()
            u.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid.value == me:
                return True
            minimized = bool(u.IsIconic(hwnd))
            w, h = client_size(hwnd)
            if not minimized and (w < MIN_SIDE or h < MIN_SIDE):
                return True
            if pid.value not in procs:
                procs[pid.value] = _process(k, pid.value)
            exe, started = procs[pid.value]
            found.append(WindowInfo(int(hwnd), title, exe, pid.value, started, w, h, minimized))
        except OSError:
            log.debug("skipping a window that couldn't be read", exc_info=True)
        return True

    try:
        u.EnumWindows(proc(cb), 0)
    except OSError:
        log.warning("listing windows failed", exc_info=True)
    return found


def copies(ref: WindowRef, wins: list[WindowInfo]) -> list[WindowInfo]:
    """The open windows `ref` could mean, oldest process first: the same title from
    the same program when there are any, else any window of that program (a game
    whose title shows the character or the zone), else (no program known) the
    same title. When no window of that program is open at all, the same title from
    any program (the game's exe was renamed: game.exe became game_dx12.exe)."""
    same_exe = [w for w in wins if w.exe == ref.exe] if ref.exe else []
    if ref.exe and not same_exe and ref.title:
        pool = [w for w in wins if w.title == ref.title]
    elif ref.title:
        exact = [w for w in (same_exe if ref.exe else wins) if w.title == ref.title]
        pool = exact or same_exe
    else:
        pool = same_exe
    return sorted(pool, key=lambda w: (w.started, w.pid, w.hwnd))


def find(ref: WindowRef, wins: list[WindowInfo] | None = None) -> WindowInfo | None:
    """The open window `ref` means, or None: copy `nth` of the windows that fit."""
    pool = copies(ref, list_windows() if wins is None else wins)
    return pool[ref.nth] if ref.nth < len(pool) else None


def ref_for(info: WindowInfo, wins: list[WindowInfo]) -> WindowRef:
    """How to remember `info`: its program and title, and which copy it is when
    several windows fit."""
    base = WindowRef(info.exe, info.title, 0)
    pool = copies(base, wins)
    nth = next((i for i, w in enumerate(pool) if w.hwnd == info.hwnd), 0)
    return WindowRef(info.exe, info.title, nth)


# --------------------------------------------------------------------------- capture

class _Bitmap:
    """A top-down 32-bit bitmap of (w, h) selected into a memory DC, its pixels as
    a numpy view. GDI handles belong to the thread that made them."""

    def __init__(self, w: int, h: int):
        u, _k, g, _d = _win()
        self._g = g
        self.w, self.h = w, h
        self.dc = self.bmp = self._old = None
        screen = u.GetDC(None)
        try:
            self.dc = g.CreateCompatibleDC(screen)
        finally:
            u.ReleaseDC(None, screen)
        bmi = _BITMAPINFOHEADER()
        bmi.biSize = ctypes.sizeof(_BITMAPINFOHEADER)
        bmi.biWidth, bmi.biHeight = w, -h        # top-down rows
        bmi.biPlanes, bmi.biBitCount = 1, 32
        bits = ctypes.c_void_p()
        if self.dc:
            self.bmp = g.CreateDIBSection(self.dc, ctypes.byref(bmi), 0, ctypes.byref(bits),
                                          None, 0)
        if not self.dc or not self.bmp or not bits.value:
            self.close()
            raise OSError("couldn't set up window capture")
        self._old = g.SelectObject(self.dc, self.bmp)
        buf = (ctypes.c_uint8 * (w * h * 4)).from_address(bits.value)
        self.pixels = np.frombuffer(buf, np.uint8).reshape(h, w, 4)

    def close(self):
        g = self._g
        if self._old:
            g.SelectObject(self.dc, self._old)
            self._old = None
        if self.bmp:
            g.DeleteObject(self.bmp)
            self.bmp = None
        if self.dc:
            g.DeleteDC(self.dc)
            self.dc = None


def snapshot(hwnd: int) -> np.ndarray | None:
    """The window's client area at full size as (h, w, 4) BGRA uint8 (a copy), or
    None when it can't be copied (closed, minimized, too small)."""
    if not supported():
        return None
    u = _win()[0]
    if not u.IsWindow(hwnd) or u.IsIconic(hwnd):
        return None
    w, h = client_size(hwnd)
    if w < 2 or h < 2:
        return None
    bm = _Bitmap(w, h)
    try:
        if not u.PrintWindow(hwnd, bm.dc, PW_CLIENTONLY | PW_RENDERFULLCONTENT):
            return None
        out = bm.pixels.copy()
        out[..., 3] = 255       # the alpha GDI leaves is meaningless
        return out
    finally:
        bm.close()


def screen_snapshot(left: int, top: int, width: int, height: int) -> np.ndarray | None:
    """A monitor's rectangle (physical pixels) at full size as (h, w, 4) BGRA uint8,
    or None. GDI: what's on screen now, windows on top included."""
    if not supported() or width < 2 or height < 2:
        return None
    u, _k, g, _d = _win()
    g.BitBlt.argtypes = [wintypes.HDC] + [ctypes.c_int] * 4 + [wintypes.HDC] + \
        [ctypes.c_int] * 2 + [wintypes.DWORD]
    bm = _Bitmap(width, height)
    screen = u.GetDC(None)
    try:
        if not g.BitBlt(bm.dc, 0, 0, width, height, screen, left, top, 0x00CC0020):  # SRCCOPY
            return None
        out = bm.pixels.copy()
        out[..., 3] = 255
        return out
    finally:
        u.ReleaseDC(None, screen)
        bm.close()


class WindowGrabber:
    """Copies one window's client area, shrunk to (w, h), as grey (float32 0..1): the
    same interface as screenwatch.Grabber. The window is found from its WindowRef
    when this is made (WindowGone if it isn't open) and kept by its handle after
    that; once it closes, grab() raises CaptureLost and the watcher looks for it
    again. `source` is the client area's size and follows the window when it's
    resized. While it's minimized grab() gives None and `minimized` is set."""

    lost = False
    want_color = False      # also keep `color` (screenwatch.Grabber's)
    # A grab's processor time outside the watching thread, for the watcher's budget:
    # PrintWindow with full content measured about 3 ms of the whole processor per
    # call (a 1000x560 window), well under 1 ms of it in the calling thread.
    cpu_elsewhere = 0.0025
    color: np.ndarray | None = None
    raw: tuple | None = None    # the last grab's pixels as sampled: (pixels, format, factor)

    def __init__(self, ref: WindowRef, w: int, h: int, info: WindowInfo | None = None):
        self.ref = ref
        info = info or find(ref)
        if info is None:
            raise WindowGone(f"{ref.label} isn't open")
        self.hwnd = info.hwnd
        self.w, self.h = w, h
        self.minimized = False
        self.failures = 0           # PrintWindow calls in a row that failed
        self.last: np.ndarray | None = None
        self._bm: _Bitmap | None = None
        self.source = (0, 0)
        size = client_size(self.hwnd)
        if min(size) >= 2:
            self._make(size)
        else:
            self.minimized = bool(_win()[0].IsIconic(self.hwnd))
        self._layout()

    def _make(self, size: tuple[int, int]):
        if self._bm is not None:
            self._bm.close()
            self._bm = None
        self._bm = _Bitmap(*size)
        self.source = size
        self.last = None

    def _layout(self):
        """Which pixels make up the (w, h) picture, at 2x where the window allows."""
        sw, sh = self.source
        w, h = self.w, self.h
        if sw < 1 or sh < 1:
            self.factor, self.ys, self.xs = 1, np.zeros(0, np.intp), np.zeros(0, np.intp)
            return
        self.factor = n = 2 if 2 * w <= sw and 2 * h <= sh else 1
        self.ys = np.minimum(((np.arange(h * n) + 0.5) * sh / (h * n)).astype(np.intp), sh - 1)
        self.xs = np.minimum(((np.arange(w * n) + 0.5) * sw / (w * n)).astype(np.intp), sw - 1)

    def resize(self, w: int, h: int):
        """Give out (w, h) pictures from now on."""
        self.w, self.h = w, h
        self.last = None
        self._layout()

    def grab(self) -> np.ndarray | None:
        u = _win()[0]
        if not u.IsWindow(self.hwnd):
            raise CaptureLost(f"{self.ref.label} was closed")
        if u.IsIconic(self.hwnd):
            self.minimized = True
            return None
        self.minimized = False
        size = client_size(self.hwnd)
        if min(size) < 2:
            return None
        if size != self.source or self._bm is None:
            # resized (or restored from minimized): copy at the new size; the watcher
            # sees `source` change and scales the pictures for it
            self._make(size)
            self._layout()
            return None
        if not u.PrintWindow(self.hwnd, self._bm.dc, PW_CLIENTONLY | PW_RENDERFULLCONTENT):
            self.failures += 1      # the watcher says so if it keeps happening
            return self.last
        self.failures = 0
        sample = pick(self._bm.pixels, self.ys, self.xs)
        self.last = gray_2x(sample) if self.factor == 2 else to_gray(sample)
        self.color = frame_rgb(sample, factor=self.factor) if self.want_color else None
        self.raw = (sample, FMT_BGRA8, self.factor)
        return self.last

    def in_front(self) -> bool:
        """It's the window you're using now (the foreground one)."""
        u = _win()[0]
        return int(u.GetForegroundWindow() or 0) == self.hwnd

    def close(self):
        if self._bm is not None:
            self._bm.close()
            self._bm = None
