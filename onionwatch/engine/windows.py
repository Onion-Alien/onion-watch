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

PrintWindow also waits for the window's program to draw it: a game that's "Not
Responding" (or stuck loading) would hold it, and every other window's checks, for as
long as it hangs. So a window that doesn't answer at once isn't copied (`answering`,
`WindowGrabber.hung`) until it does again.

So a fullscreen game you're playing (it's in front and fills its screen, exclusive or
borderless) is read off that screen instead, with Desktop Duplication: the same
pixels, it works in exclusive fullscreen too, and it costs less than PrintWindow.
Alt-tab away and it's back to PrintWindow (an exclusive-fullscreen game minimizes
then, which `minimized` says).

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
import time
from ctypes import wintypes
from dataclasses import dataclass

import numpy as np

from onionwatch.engine import screenwatch
from onionwatch.engine.screenwatch import (_BITMAPINFOHEADER, FMT_BGRA8, RETRY_S, CaptureLost,
                                           Monitor, WindowRef, frame_rgb, gray_2x, is_black, pick,
                                           to_gray)
from onionwatch.i18n import _

log = logging.getLogger(__name__)

PW_CLIENTONLY = 0x1
PW_RENDERFULLCONTENT = 0x2
GWL_EXSTYLE = -20
WS_EX_TOOLWINDOW = 0x80
GW_OWNER = 4
GW_HWNDPREV = 3
# the taskbars: an exclusive-fullscreen game owns its screen, nothing else is drawn
# there, but a taskbar stays above it in the window order
TASKBARS = ("Shell_TrayWnd", "Shell_SecondaryTrayWnd")
DWMWA_CLOAKED = 14
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
MIN_SIDE = 32           # windows smaller than this (either way) aren't worth listing
# a fullscreen game's screen duplication is kept this long after it was last read
# (alt-tabbed away), so tabbing back doesn't set up a new one (~60 ms) every time
DUP_IDLE_S = 30.0
# a game not in front that's read off its screen because copying it gave black is
# copied again this often, to see whether it still does
DARK_RECHECK_S = 2.0
MONITOR_DEFAULTTONULL = 0
WM_NULL = 0
SMTO_ABORTIFHUNG = 0x2
# a window that takes longer than this to answer is busy (hung, loading): not copied
# this check. A game answers within a frame or two
ANSWER_MS = 50


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
        return self.title or self.exe or _("Window {hwnd:#x}", hwnd=self.hwnd)


# --------------------------------------------------------------------------- Win32

_api = None


class _MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]


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
    u.GetWindowRect.argtypes = [H, ctypes.POINTER(wintypes.RECT)]
    u.GetWindowLongW.argtypes = [H, ctypes.c_int]
    u.GetWindow.argtypes = [H, wintypes.UINT]
    u.GetWindow.restype = H
    u.GetClassNameW.argtypes = [H, wintypes.LPWSTR, ctypes.c_int]
    u.GetForegroundWindow.restype = H
    u.PrintWindow.argtypes = [H, wintypes.HDC, wintypes.UINT]
    u.IsHungAppWindow.argtypes = [H]
    u.SendMessageTimeoutW.argtypes = [H, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM,
                                      wintypes.UINT, wintypes.UINT,
                                      ctypes.POINTER(ctypes.c_size_t)]
    u.SendMessageTimeoutW.restype = ctypes.c_ssize_t
    u.GetDC.argtypes = [H]
    u.ClientToScreen.argtypes = [H, ctypes.POINTER(wintypes.POINT)]
    u.MonitorFromWindow.argtypes = [H, wintypes.DWORD]
    u.MonitorFromWindow.restype = wintypes.HMONITOR
    u.GetMonitorInfoW.argtypes = [wintypes.HMONITOR, ctypes.POINTER(_MONITORINFO)]
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


def answering(hwnd: int) -> bool:
    """The window's program answers: Windows hasn't marked it "Not Responding" (it
    does after 5 s) and it takes a message within ANSWER_MS. PrintWindow on a window
    that doesn't waits until it does, however long that is."""
    u = _win()[0]
    if u.IsHungAppWindow(hwnd):
        return False
    out = ctypes.c_size_t()
    return bool(u.SendMessageTimeoutW(hwnd, WM_NULL, 0, 0, SMTO_ABORTIFHUNG, ANSWER_MS,
                                      ctypes.byref(out)))


def client_size(hwnd: int) -> tuple[int, int]:
    """The window's client area in pixels; (0, 0) if it can't be read."""
    u = _win()[0]
    r = wintypes.RECT()
    if not u.GetClientRect(hwnd, ctypes.byref(r)):
        return 0, 0
    return max(0, r.right - r.left), max(0, r.bottom - r.top)


def _monitor(hmon) -> Monitor | None:
    """Monitor `hmon` as it is now (a game may have switched its display mode since
    it was listed), or None."""
    if not hmon:
        return None
    mi = _MONITORINFO()
    mi.cbSize = ctypes.sizeof(_MONITORINFO)
    if not _win()[0].GetMonitorInfoW(hmon, ctypes.byref(mi)):
        return None
    r = mi.rcMonitor
    return Monitor(r.left, r.top, r.right - r.left, r.bottom - r.top, bool(mi.dwFlags & 1),
                   int(hmon))


def fills(hwnd: int, mon) -> bool:
    """Window `hwnd` covers the whole of monitor `mon` (left, top, width, height in
    physical pixels): a fullscreen or borderless game. The monitor is taken as it is
    now when its handle is known: a game in exclusive fullscreen at another
    resolution changes its size. False when it can't be told."""
    if not supported() or not hwnd:
        return False
    now = _monitor(getattr(mon, "handle", 0))
    if now is not None:
        mon = now
    r = wintypes.RECT()
    if not _win()[0].GetWindowRect(hwnd, ctypes.byref(r)):
        return False
    return (r.left <= mon.left and r.top <= mon.top and r.right >= mon.left + mon.width
            and r.bottom >= mon.top + mon.height)


def screen_filled(hwnd: int) -> Monitor | None:
    """The monitor window `hwnd`'s client area covers exactly, as it is now (a
    fullscreen game, exclusive or borderless), or None."""
    if not supported() or not hwnd:
        return None
    u = _win()[0]
    mon = _monitor(u.MonitorFromWindow(hwnd, MONITOR_DEFAULTTONULL))
    r = wintypes.RECT()
    at = wintypes.POINT(0, 0)
    if (mon is None or not u.GetClientRect(hwnd, ctypes.byref(r))
            or not u.ClientToScreen(hwnd, ctypes.byref(at))):
        return None
    if (at.x, at.y, r.right - r.left, r.bottom - r.top) != (mon.left, mon.top, mon.width,
                                                            mon.height):
        return None
    return mon


def alone_on_screen(hwnd: int, mon: Monitor) -> bool:
    """Nothing shows over window `hwnd` on `mon`: every window above it is hidden,
    minimized, cloaked, a taskbar (TASKBARS) or on another screen."""
    if not supported() or not hwnd:
        return False
    u, _k, _g, d = _win()
    r = wintypes.RECT()
    name = ctypes.create_unicode_buffer(32)
    h = u.GetWindow(hwnd, GW_HWNDPREV)
    for _step in range(2000):                   # (the order can change while it's walked)
        if not h:
            return True
        if (u.IsWindowVisible(h) and not u.IsIconic(h) and u.GetWindowRect(h, ctypes.byref(r))
                and r.left < mon.left + mon.width and r.right > mon.left
                and r.top < mon.top + mon.height and r.bottom > mon.top
                and not _cloaked(d, h)
                and not (u.GetClassNameW(h, name, 32) and name.value in TASKBARS)):
            return False
        h = u.GetWindow(h, GW_HWNDPREV)
    return False


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


def follow(ref: WindowRef, wins: list[WindowInfo], taken=(), was: int | None = None,
           before=None) -> WindowInfo | None:
    """The window a capture of `ref` opens now, or None (it waits). Copies are told
    apart by when they started, but a copy that closes and starts again is the
    newest then: copy `nth` would be another copy's window. So a window another
    capture has (`taken`, its handles) is never taken twice; after a loss the same
    window comes back if it's still there (`was`), else only a window that wasn't
    open when it was lost (`before`, the copies' handles then): the copy that was
    started again, not the one somebody else is playing. Otherwise copy `nth`."""
    pool = copies(ref, wins)
    free = [w for w in pool if w.hwnd not in taken]
    if was is not None:
        back = next((w for w in free if w.hwnd == was), None)
        if back is not None:
            return back
    if before is not None:
        return next((w for w in free if w.hwnd not in before), None)
    if ref.nth < len(pool) and pool[ref.nth].hwnd not in taken:
        return pool[ref.nth]
    return None


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
            raise OSError(_("couldn't set up window capture"))
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
    resized. While it's minimized grab() gives None and `minimized` is set, and the
    first copy after it's restored is thrown away: Windows hands back the frame from
    before it was minimized then (a picture that went away meanwhile would fire).

    A window that fills its screen is read off that screen (Desktop Duplication)
    while it's in front, as PrintWindow often sees an exclusive-fullscreen game as
    black. Out of front it's copied again, unless that comes out black while
    nothing else shows on its screen: an exclusive game that lost focus but kept its
    screen (you clicked onto another monitor), still read off it then. The first
    copy after it was read off its screen is thrown away too (unless it's black):
    Windows can hand back one from before then, from before it went fullscreen,
    say (a picture that went away meanwhile would fire)."""

    lost = False
    follows = True          # opened on the window follow() picks (the watcher's)
    want_color = False      # also keep `color` (screenwatch.Grabber's)
    # A grab's processor time outside the watching thread, for the watcher's budget:
    # PrintWindow with full content measured about 3 ms of the whole processor per
    # call (a 1000x560 window), well under 1 ms of it in the calling thread.
    # Read off the screen it's next to nothing (the graphics card copies it).
    PRINT_CPU = 0.0025
    cpu_elsewhere = PRINT_CPU
    on_screen = False       # the last grab read it off its screen (a fullscreen game)
    # stand-ins for tests: the window in front, the monitor a window fills, and how
    # its screen is duplicated (screenwatch.share_dup)
    _front = staticmethod(foreground)
    _fills_screen = staticmethod(screen_filled)
    _alone = staticmethod(alone_on_screen)
    _share = staticmethod(screenwatch.share_dup)
    _answers = staticmethod(answering)
    color: np.ndarray | None = None
    raw: tuple | None = None    # the last grab's pixels as sampled: (pixels, format, factor)
    # ...and all of the window's own (BGRA, a view of the bitmap: only good until the
    # next grab; None when the last grab didn't copy it)
    full: np.ndarray | None = None

    def __init__(self, ref: WindowRef, w: int, h: int, info: WindowInfo | None = None):
        self.ref = ref
        info = info or find(ref)
        if info is None:
            raise WindowGone(_("{name} isn't open", name=ref.label))
        self.hwnd = info.hwnd
        self.w, self.h = w, h
        self.minimized = False
        self.stale = False          # restored from minimized: the next copy is old
        self.left_screen = False    # was read off its screen: the next copy may be old
        self.failures = 0           # PrintWindow calls in a row that failed
        self.hung = False           # its program isn't answering: not copied (answering)
        self.last: np.ndarray | None = None
        self._bm: _Bitmap | None = None
        self._dup = None            # its screen's duplication, while it's read off it
        self._dup_mon = 0           # ...that screen's handle
        self._dup_used = 0.0        # ...and when it was last read
        self._dup_next = 0.0        # ...not tried again before this (it failed)
        self._dup_said = False      # ...which the log said once
        self.dark = False           # out of front, copying it gave black (see the class)
        self._recheck_at = 0.0      # ...read off its screen until then, then copied again
        self.source = (0, 0)
        size = client_size(self.hwnd)
        if min(size) >= 2:
            self._make(size)
        else:
            self.minimized = self.stale = bool(_win()[0].IsIconic(self.hwnd))
        self._layout()

    def _make(self, size: tuple[int, int]):
        self.full = None
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
        if self._dup is not None:
            self._dup.resize(w, h)

    def grab(self) -> np.ndarray | None:
        u = _win()[0]
        if not u.IsWindow(self.hwnd):
            raise CaptureLost(_("{name} was closed", name=self.ref.label))
        if u.IsIconic(self.hwnd):
            self.minimized = self.stale = True
            self.last = None        # not given out again for a failed copy once it's back
            self._off_screen()
            return None
        self.minimized = False
        self.full = None
        size = client_size(self.hwnd)
        if min(size) < 2:
            return None
        if size != self.source or self._bm is None:
            # resized (or restored from minimized): copy at the new size; the watcher
            # sees `source` change and scales the pictures for it
            self._make(size)
            self._layout()
            return None
        front = self._front() == self.hwnd
        mon = None
        if front:
            mon = self._fills_screen(self.hwnd)
        elif self.dark and time.monotonic() < self._recheck_at:
            mon = self._fills_screen(self.hwnd)
            if mon is not None and not self._alone(self.hwnd, mon):
                mon = None
        if mon is not None:
            done, gray = self._from_screen(mon)
            if done:
                self.stale = False          # read off the screen: what it shows now
                return gray
        else:
            if self.on_screen:
                self.left_screen = True
            self._off_screen()
        if not self._print():
            return self.last
        if client_size(self.hwnd) != size:
            # resized while it was copied: PrintWindow drew it at its new size into the
            # bitmap for the old one (shrunk into a corner or cut off), so a picture on
            # it would look gone. Thrown away; the next grab copies it at its new size
            self.last = None
            return None
        if self.stale:
            # the first PrintWindow after a restore can give the frame from before
            # it was minimized: thrown away, the next grab gets what it shows now
            self.stale = False
            self.last = None
            return None
        left, self.left_screen = self.left_screen, False
        self.dark = not front and self.last is not None and is_black(self.last)
        if left and not self.dark:
            # copied again after being read off its screen: this copy can be from
            # before that (a window gone fullscreen gave its old, smaller frame in a
            # corner of the new size, the rest black). Thrown away; a black one is
            # the exclusive-fullscreen case below, read off the screen
            self.last = None
            return None
        if self.dark:
            # an exclusive-fullscreen game out of front: its screen still shows it
            # while nothing else is over it there. Read it off that screen at once,
            # so it doesn't blink black in between
            mon = self._fills_screen(self.hwnd)
            if mon is not None and self._alone(self.hwnd, mon):
                self._recheck_at = time.monotonic() + DARK_RECHECK_S
                done, gray = self._from_screen(mon)
                if done and gray is not None:
                    return gray
        return self.last

    def _print(self) -> bool:
        """Copy the window with PrintWindow into `last` (and full, raw, color)."""
        u, bm = _win()[0], self._bm
        if bm is None:
            return False
        if not self._answers(self.hwnd):
            # PrintWindow would wait for it, and every other window's checks with it:
            # nothing to look at until it answers again (tried every check)
            if not self.hung:
                log.info("%s isn't answering: not copied until it does", self.ref.label)
            self.hung = True
            self.last = None
            return False
        self.hung = False
        if not u.PrintWindow(self.hwnd, bm.dc, PW_CLIENTONLY | PW_RENDERFULLCONTENT):
            self.failures += 1      # the watcher says so if it keeps happening
            return False
        self.failures = 0
        self.full = bm.pixels
        sample = pick(bm.pixels, self.ys, self.xs)
        self.last = gray_2x(sample) if self.factor == 2 else to_gray(sample)
        self.color = frame_rgb(sample, factor=self.factor) if self.want_color else None
        self.raw = (sample, FMT_BGRA8, self.factor)
        self.on_screen = False
        return True

    def _from_screen(self, mon: Monitor) -> tuple[bool, np.ndarray | None]:
        """The window fills `mon` and is in front: read it off that screen. (True,
        the picture or None while the screen is switching modes), or (False, None)
        when it can't be read that way and PrintWindow is to copy it."""
        now = time.monotonic()
        if self._dup is not None and mon.handle != self._dup_mon:
            self._leave_screen()                # moved to another screen
        if self._dup is None:
            if now < self._dup_next:
                return False, None
            try:
                self._dup = self._share(mon, self.w, self.h)
                self._dup_mon = mon.handle
            except (OSError, AttributeError) as e:
                self._dup_next = now + RETRY_S
                if not self._dup_said:
                    self._dup_said = True
                    log.info("%s fills its screen, but that screen can't be duplicated "
                             "(%s): copying the window instead", self.ref.label, e)
                return False, None
        d = self._dup
        d.want_color = self.want_color
        try:
            gray = d.grab()
        except OSError:
            self._leave_screen()
            self._dup_next = now + RETRY_S
            return False, None
        if tuple(d.source) != self.source:
            if gray is None or d.lost:
                return True, None               # the display mode is still switching
            self._leave_screen()                # not this window's pixels after all
            self._dup_next = now + RETRY_S
            return False, None
        self.on_screen = True
        self._dup_used = now
        self.cpu_elsewhere = 0.0
        self.failures = 0
        self.full = None
        if gray is not None:
            self.last = gray
            self.factor = d.factor
            self.raw = d.raw
            self.color = d.color
        return True, gray

    def _off_screen(self):
        """Not read off its screen now (alt-tabbed away, minimized, windowed): copied
        with PrintWindow. The duplication is kept for DUP_IDLE_S in case you're
        back soon."""
        self.on_screen = False
        self.cpu_elsewhere = self.PRINT_CPU
        if self._dup is not None and time.monotonic() - self._dup_used > DUP_IDLE_S:
            self._leave_screen()

    def _leave_screen(self):
        if self._dup is not None:
            self._dup.close()
            self._dup = None
        self.on_screen = False
        self.cpu_elsewhere = self.PRINT_CPU

    def full_gray(self, y0: int, y1: int, x0: int, x1: int) -> np.ndarray | None:
        """While it's read off its screen, the screen's own pixels (the twin check);
        otherwise `full` has them, and this gives None."""
        d = self._dup if self.on_screen else None
        return None if d is None else d.full_gray(y0, y1, x0, x1)

    def full_rgb(self, y0: int, y1: int, x0: int, x1: int) -> np.ndarray | None:
        d = self._dup if self.on_screen else None
        return None if d is None else d.full_rgb(y0, y1, x0, x1)

    def in_front(self) -> bool:
        """It's the window you're using now (the foreground one)."""
        u = _win()[0]
        return int(u.GetForegroundWindow() or 0) == self.hwnd

    def close(self):
        self._leave_screen()
        self.full = None
        if self._bm is not None:
            self._bm.close()
            self._bm = None
