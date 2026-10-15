"""Fullscreen games, in front and alt-tabbed away from.

A window that fills its screen and is the one in front (a fullscreen game being
played) is read off that screen with Desktop Duplication, since PrintWindow sees an
exclusive-fullscreen game as black; alt-tab away and the window is copied again.
A screen is duplicated once per process (Windows refuses a second), so a screen
watched both as a screen and as a fullscreen game's window shares it (DupView).
And "you're in the game" still holds after a game changes the screen's resolution.
No real screen or window is read: the frames and windows are made up."""
import ctypes
import threading
import time
from ctypes import wintypes

import numpy as np
import pytest

from onionwatch import screenwatch as sw
from onionwatch import windows
from onionwatch.screenwatch import Monitor, WindowRef
from test_screen_twin import FakeCom, staged
from test_screenwatch import fake_screen  # noqa: F401 (a fixture)
from test_screenwatch import banner, pics, run_until, scene, with_banner

GAME = WindowRef("game.exe", "Game", 0)


# --------------------------------------------------------------------------- sharing

def frame(seed=0, h=120, w=200) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return rng.integers(0, 256, (h, w, 4), dtype=np.uint8)


class Released(FakeCom):
    def __init__(self, log):
        super().__init__()
        self.log = log

    def release(self):
        self.log.append(self)


def shared(px: np.ndarray, hmon=7, mon=None):
    """A DupGrabber holding frame `px`, open and shared, whose next frames come from
    `frames` (one per grab that finds something new)."""
    g, buf, _maps = staged(px, 0)
    released = []
    g.dup, g.output1, g.device = Released(released), Released(released), Released(released)
    g.src = mon or Monitor(0, 0, px.shape[1], px.shape[0], True, hmon)
    g.hmon, g.w, g.h = hmon, 50, 30
    g.factor, g.ys, g.xs = sw.dup_layout(g._frame, 0, g.w, g.h)
    g.last, g.lost = None, False
    g.copies = []

    def acquire(timeout_ms=0):
        if not g.copies:
            return False
        nxt = g.copies.pop(0)
        rows = np.frombuffer(buf, np.uint8).reshape(nxt.shape[0], -1)
        rows[:, :nxt.shape[1] * 4] = nxt.reshape(nxt.shape[0], -1)
        g.serial += 1
        g.fresh = True
        return True
    g._acquire = acquire
    g.serial, g.fresh = 1, True
    sw._shared.append(g)
    return g, released


@pytest.fixture(autouse=True)
def no_shared():
    sw._shared.clear()
    yield
    sw._shared.clear()


def want(px: np.ndarray, w: int, h: int) -> np.ndarray:
    n, ys, xs = sw.dup_layout((px.shape[1], px.shape[0]), 0, w, h)
    sample = sw.pick(px, ys, xs)
    return sw.gray_2x(sample) if n == 2 else sw.to_gray(sample)


def test_a_screen_open_already_is_shared_not_duplicated_twice(monkeypatch):
    px = frame(1)
    g, _released = shared(px)
    monkeypatch.setattr(sw.DupGrabber, "__init__", lambda *_a: pytest.fail("duplicated twice"))
    # found by its handle even though a game has changed the screen's resolution since
    view = sw.share_dup(Monitor(0, 0, 1280, 720, True, 7), 40, 24)
    assert isinstance(view, sw.DupView) and g.users == 2
    assert view.source == g.source
    got = view.grab()
    assert got.shape == (24, 40) and np.allclose(got, want(px, 40, 24), atol=1e-6)
    # ...and each reader sees every new frame, whoever grabbed it first
    nxt = frame(2)
    g.copies.append(nxt)
    assert np.allclose(g.grab(), want(nxt, 50, 30), atol=1e-6)
    assert np.allclose(view.grab(), want(nxt, 40, 24), atol=1e-6)
    assert view.grab() is view.last                 # nothing new: not sampled again


def test_the_screen_is_let_go_once_nobody_reads_it(monkeypatch):
    g, released = shared(frame(1))
    view = sw.share_dup(Monitor(0, 0, 1, 1, True, 7), 40, 24)
    g.close()                       # the screen's trigger went; the window still reads it
    assert released == [] and g in sw._shared
    assert view.grab() is not None
    view.close()
    view.close()                    # twice is harmless
    assert len(released) == 3 and sw._shared == []



def test_a_screen_duplicated_on_another_thread_is_not_shared(monkeypatch):
    """A duplication's Direct3D objects belong to the thread that opened it: shared
    with another thread, one let go of it in the middle of the other's grab (a crash
    in AcquireNextFrame's release). Another thread opens its own."""
    g, _released = shared(frame(1))
    g.thread = threading.get_ident() + 1                 # opened on another thread
    made = []
    monkeypatch.setattr(sw, "DupGrabber", lambda mon, w, h: made.append(mon) or "its own")
    assert sw.share_dup(g.src, 40, 24) == "its own" and made == [g.src]
    g.thread = threading.get_ident()
    assert isinstance(sw.share_dup(g.src, 40, 24), sw.DupView) and len(made) == 1

def test_a_view_of_a_lost_screen_is_lost_too():
    g, _released = shared(frame(1))
    view = sw.share_dup(g.src, 40, 24)

    def broken(timeout_ms=0):
        g._die()
        raise sw.CaptureLost("AcquireNextFrame failed")
    g._acquire = broken
    with pytest.raises(sw.CaptureLost):
        view.grab()
    assert g.dead and sw._shared == []
    with pytest.raises(sw.CaptureLost):
        view.grab()


# --------------------------------------------------------------------------- windows

class FakeUser32:
    def __init__(self, state):
        self.state = state

    def IsWindow(self, _h):
        return True

    def IsIconic(self, _h):
        return self.state["minimized"]

    def PrintWindow(self, _h, dc, _flags):
        self.state["printed"] += 1
        dc[...] = self.state["window"]           # exclusive fullscreen: all black
        return True

    def GetForegroundWindow(self):
        return self.state["front"]


class FakeBitmap:
    def __init__(self, w, h):
        self.pixels = np.zeros((h, w, 4), np.uint8)
        self.dc = self.pixels

    def close(self):
        pass


class FakeScreen:
    """share_dup's stand-in: the game's screen, as Desktop Duplication sees it."""

    def __init__(self, state, w, h):
        self.state, self.w, self.h = state, w, h
        self.source = state["screen_size"]
        self.lost = False
        self.factor, self.raw, self.color = 1, ("raw",), None
        self.closed = False
        state["opened"] += 1

    def resize(self, w, h):
        self.w, self.h = w, h

    def grab(self):
        self.source = self.state["screen_size"]
        self.lost = self.state["switching"]
        return None if self.lost else np.full((self.h, self.w), 0.5, np.float32)

    def full_gray(self, *box):
        return ("screen", box)

    def full_rgb(self, *box):
        return None

    def close(self):
        self.closed = True
        self.state["closed"] += 1


SIZE = (320, 180)


@pytest.fixture
def game(monkeypatch):
    """A fullscreen game (hwnd 5) that PrintWindow sees as black, its screen, and who
    is in front; `fills` is the monitor it fills (None: windowed)."""
    state = {"front": 5, "minimized": False, "printed": 0, "opened": 0, "closed": 0,
             "window": 0, "switching": False, "screen_size": SIZE, "size": SIZE,
             "fills": Monitor(0, 0, *SIZE, True, 9), "share_fails": False, "alone": False}
    u = FakeUser32(state)
    monkeypatch.setattr(windows, "_win", lambda: (u, None, None, None))
    monkeypatch.setattr(windows, "_Bitmap", FakeBitmap)
    monkeypatch.setattr(windows, "client_size", lambda _h: state["size"])

    def share(mon, w, h):
        if state["share_fails"]:
            raise OSError("DuplicateOutput failed")
        return FakeScreen(state, w, h)

    def grabber():
        g = windows.WindowGrabber(GAME, 160, 90, info=windows.WindowInfo(
            5, "Game", "game.exe", 1, 0, *SIZE))
        g._front = lambda: state["front"]
        g._fills_screen = lambda _h: state["fills"]
        g._alone = lambda _h, _m: state["alone"]
        g._share = share
        return g
    return state, grabber


def test_a_fullscreen_game_in_front_is_read_off_its_screen(game):
    state, make = game
    g = make()
    got = g.grab()
    assert got is not None and float(got.mean()) == pytest.approx(0.5)   # not black
    assert g.on_screen and state["printed"] == 0 and g.cpu_elsewhere == 0
    assert g.raw == ("raw",) and g.full is None
    assert g.full_gray(0, 4, 0, 4) == ("screen", (0, 4, 0, 4))   # the twin check reads it
    g.resize(80, 45)
    assert g.grab().shape == (45, 80)


def test_alt_tabbed_away_it_is_copied_again_and_back_in_front_read_off_the_screen(game):
    state, make = game
    g = make()
    assert g.grab() is not None and g.on_screen
    state["front"] = 77                         # alt-tabbed to another window
    state["window"] = 200                       # (a borderless game: PrintWindow sees it)
    got = g.grab()
    assert not g.on_screen and state["printed"] == 1
    assert float(got.mean()) > 0.5 and g.cpu_elsewhere == g.PRINT_CPU
    assert g.full is not None and g.full_gray(0, 4, 0, 4) is None
    state["front"] = 5                          # back in the game
    assert float(g.grab().mean()) == pytest.approx(0.5)
    assert g.on_screen and state["printed"] == 1
    # the screen was kept for tabbing back: not set up again
    assert state["opened"] == 1 and state["closed"] == 0
    g.close()
    assert state["closed"] == 1


def test_a_screen_not_read_for_a_while_is_let_go(game, monkeypatch):
    state, make = game
    g = make()
    g.grab()
    monkeypatch.setattr(windows, "DUP_IDLE_S", 0.0)
    state["front"] = 77
    time.sleep(0.01)
    g.grab()
    assert state["closed"] == 1 and g._dup is None
    state["front"] = 5
    assert g.grab() is not None and g.on_screen and state["opened"] == 2


def test_a_game_moved_to_another_screen_is_read_off_that_one(game):
    state, make = game
    g = make()
    g.grab()
    state["fills"] = Monitor(-320, 0, *SIZE, False, 10)
    assert g.grab() is not None and g.on_screen
    assert state["opened"] == 2 and state["closed"] == 1 and g._dup_mon == 10


def test_a_windowed_game_in_front_is_copied_as_before(game):
    state, make = game
    state["fills"] = None
    g = make()
    g.grab()
    assert not g.on_screen and state["printed"] == 1 and state["opened"] == 0


def test_a_minimized_game_is_flagged(game):
    state, make = game
    g = make()
    g.grab()
    state["minimized"], state["front"] = True, 77   # exclusive fullscreen alt-tabbed
    assert g.grab() is None and g.minimized
    state["minimized"], state["front"] = False, 5
    assert g.grab() is not None and g.on_screen


def test_a_resolution_switch_waits_for_the_screen_instead_of_copying_black(game):
    state, make = game
    g = make()
    g.grab()
    state["size"] = (200, 120)                  # the game switched resolution
    assert g.grab() is None                     # the window's new size first
    state["switching"] = True
    assert g.grab() is None and state["printed"] == 0
    state["switching"], state["screen_size"] = False, (200, 120)
    assert g.grab() is not None and g.on_screen and g.source == (200, 120)


def test_a_screen_that_cant_be_duplicated_falls_back_to_copying_the_window(game, monkeypatch):
    state, make = game
    state["share_fails"] = True
    g = make()
    g.grab()
    g.grab()
    assert not g.on_screen and state["printed"] == 2
    assert g._dup_said                          # said once, tried again after RETRY_S
    monkeypatch.setattr(windows, "RETRY_S", 0.0)
    g._dup_next = 0.0
    state["share_fails"] = False
    g.grab()
    assert g.on_screen


def test_a_screen_showing_something_else_is_not_taken_for_the_window(game):
    state, make = game
    state["screen_size"] = (640, 360)           # not the window's pixels
    g = make()
    g.grab()
    assert not g.on_screen and state["printed"] == 1 and state["closed"] == 1



def test_an_exclusive_game_out_of_front_still_on_its_screen_is_read_off_it(game, monkeypatch):
    """Clicked onto another monitor, an exclusive-fullscreen game can keep its screen
    without being minimized; PrintWindow sees it as black then. While nothing else
    shows on its screen it's read off that screen, without a black frame between,
    and copied again every DARK_RECHECK_S to see whether it still needs to be."""
    state, make = game
    g = make()
    assert g.grab() is not None and g.on_screen
    state["front"], state["alone"] = 77, True
    got = g.grab()                               # copied black, so read off the screen
    assert float(got.mean()) == pytest.approx(0.5) and g.on_screen and g.dark
    assert state["printed"] == 1
    assert float(g.grab().mean()) == pytest.approx(0.5) and state["printed"] == 1
    monkeypatch.setattr(windows, "DARK_RECHECK_S", 0.0)
    g._recheck_at = 0.0                          # time to copy it again: still black
    assert float(g.grab().mean()) == pytest.approx(0.5) and state["printed"] == 2
    state["window"] = 200                        # it's drawn into its window again
    g._recheck_at = 0.0
    assert float(g.grab().mean()) > 0.5 and not g.on_screen and not g.dark
    assert state["opened"] == 1                  # one duplication all along


def test_an_exclusive_game_out_of_front_with_a_window_over_it_is_copied(game):
    state, make = game
    g = make()
    g.grab()
    state["front"], state["alone"] = 77, False   # something else shows on its screen
    assert float(g.grab().max()) == 0.0 and not g.on_screen
    assert g.dark and state["printed"] == 1
    assert float(g.grab().max()) == 0.0 and state["printed"] == 2


class ZUser32:
    """Windows above the game, top first: (class, visible, minimized, rect)."""

    def __init__(self, above):
        self.above = above

    def GetWindow(self, h, _cmd):
        i = (len(self.above) if h == 5 else h - 100) - 1
        return 100 + i if i >= 0 else None

    def _w(self, h):
        return self.above[h - 100]

    def IsWindowVisible(self, h):
        return self._w(h)[1]

    def IsIconic(self, h):
        return self._w(h)[2]

    def GetWindowRect(self, h, ref):
        r = ref._obj
        r.left, r.top, r.right, r.bottom = self._w(h)[3]
        return True

    def GetClassNameW(self, h, buf, _n):
        buf.value = self._w(h)[0]
        return len(buf.value)


@pytest.mark.parametrize("above, alone", [
    ([], True),
    ([("Shell_SecondaryTrayWnd", True, False, (-1920, 1040, 0, 1080))], True),
    ([("Discord", True, False, (0, 0, 800, 600))], True),             # on the other screen
    ([("Discord", False, False, (-1900, 0, -900, 600))], True),       # hidden
    ([("Discord", True, True, (-1900, 0, -900, 600))], True),         # minimized
    ([("Toast", True, False, (-400, 900, -10, 1000))], False),
    ([("Discord", True, False, (0, 0, 800, 600)),
      ("Overlay", True, False, (-1920, 0, 0, 1080))], False),
])
def test_alone_on_screen_looks_at_every_window_above(monkeypatch, above, alone):
    monkeypatch.setattr(windows, "_win", lambda: (ZUser32(above), None, None, None))
    monkeypatch.setattr(windows, "supported", lambda: True)
    mon = Monitor(-1920, 0, 1920, 1080, False, 9)
    assert windows.alone_on_screen(5, mon) is alone


# --------------------------------------------------------------------------- in the game

class RectUser32:
    def __init__(self, rect):
        self.rect = rect

    def GetWindowRect(self, _h, ref):
        r = ref._obj
        r.left, r.top, r.right, r.bottom = self.rect
        return True


def test_a_game_at_another_resolution_still_fills_its_screen(monkeypatch):
    """A game in exclusive fullscreen at 1280x720 on a 2560x1440 screen: the screen
    was listed at 2560x1440, but it's 1280x720 now, and the game fills it (so you're
    in the game, not away: max detection stays off)."""
    monkeypatch.setattr(windows, "supported", lambda: True)
    monkeypatch.setattr(windows, "_win", lambda: (RectUser32((0, 0, 1280, 720)), None, None,
                                                  None))
    now = Monitor(0, 0, 1280, 720, True, 3)
    monkeypatch.setattr(windows, "_monitor", lambda h: now if h == 3 else None)
    listed = Monitor(0, 0, 2560, 1440, True, 3)
    assert windows.fills(11, listed)
    assert not windows.fills(11, Monitor(0, 0, 2560, 1440, True))   # handle unknown: as before


def test_a_monitor_keeps_its_handle_out_of_comparisons():
    assert Monitor(0, 0, 10, 10, True, 1) == Monitor(0, 0, 10, 10, True, 2)


def test_the_window_rect_is_read_through_a_real_rect():
    """RectUser32 fills the RECT fills() passes, as user32 does."""
    r = wintypes.RECT()
    RectUser32((1, 2, 3, 4)).GetWindowRect(0, ctypes.byref(r))
    assert (r.left, r.top, r.right, r.bottom) == (1, 2, 3, 4)


@pytest.mark.parametrize("front, fills, quiet", [
    (7, True, True),            # a fullscreen game you're playing covers the screen
    (7, False, False),          # something else is in front
    (0, True, False),           # can't be told: it plays
])
def test_stay_quiet_on_a_screen_while_a_fullscreen_game_fills_it(fake_screen, front, fills,  # noqa: F811
                                                                  quiet):
    fake_screen.frames = [scene()]
    fired = []
    w = sw.Watcher(fired.append, front=lambda: front, fills=lambda *_a: fills)
    w.interval = 0.01
    w.set_items([sw.Watched("t", pics(banner()), 0.8, 0.0, unfocused=True)])
    w.start()
    try:
        assert run_until(lambda: "t" in w.scores)
        fake_screen.frames = [with_banner(scene())]
        assert run_until(lambda: w.scores.get("t", 0) > 0.95)
        time.sleep(0.1)
        assert bool(fired) != quiet
    finally:
        w.stop()
