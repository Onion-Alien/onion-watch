"""A game that stops answering ("Not Responding", or stuck loading) mustn't hold up the
other windows: PrintWindow waits for a window's program to draw it, so one hung game
would keep every other window's triggers from firing for as long as it hangs. It
isn't copied until it answers again. Stand-in windows only: no real window is read."""
import threading
import time

import numpy as np
import pytest

from onionwatch import screenwatch as sw
from onionwatch import windows
from onionwatch.screenwatch import Monitor, Watched, WindowRef
from onionwatch.windows import WindowInfo
from test_windows import H, W, banner, run_until, scene, showing

HUNG = WindowRef("slow.exe", "Slow game", 0)
OK = WindowRef("game.exe", "Game", 0)
HWND = {HUNG: 1, OK: 2}


class FakeUser32:
    """Two windows by handle: the picture each shows, and whether its program answers.
    PrintWindow on one that doesn't waits until it does, as Windows' does."""

    def __init__(self):
        self.frames = {1: scene(1), 2: scene(2)}
        self.marked = set()         # Windows says "Not Responding" (after 5 s)
        self.busy = set()           # doesn't answer messages (yet to be marked)
        self.answered = threading.Event()
        self.printed = {1: 0, 2: 0}

    def IsWindow(self, _h):
        return True

    def IsIconic(self, _h):
        return False

    def GetForegroundWindow(self):
        return 0

    def IsHungAppWindow(self, h):
        return h in self.marked

    def SendMessageTimeoutW(self, h, *_a):
        return 0 if h in self.busy or h in self.marked else 1

    def PrintWindow(self, h, dc, _flags):
        if h in self.busy or h in self.marked:
            self.answered.wait(5)       # held until the game answers again
        self.printed[h] += 1
        dc[..., :3] = (self.frames[h] * 255).astype(np.uint8)[..., None]
        return True


class FakeBitmap:
    def __init__(self, w, h):
        self.pixels = np.zeros((h, w, 4), np.uint8)
        self.dc = self.pixels

    def close(self):
        pass


@pytest.fixture
def user32(monkeypatch):
    u = FakeUser32()
    monkeypatch.setattr(windows, "_win", lambda: (u, None, None, None))
    monkeypatch.setattr(windows, "_Bitmap", FakeBitmap)
    monkeypatch.setattr(windows, "client_size", lambda _h: (W, H))
    monkeypatch.setattr(sw, "monitors", lambda: [Monitor(0, 0, W, H, True)])
    monkeypatch.setattr(sw, "WORK_WIDTH", W)
    yield u
    u.answered.set()                # never leave a check waiting


def grabber(ref, w, h):
    return windows.WindowGrabber(ref, w, h, info=WindowInfo(
        HWND[ref], ref.title, ref.exe, HWND[ref], 0, W, H))


@pytest.mark.parametrize("how", ["marked", "busy"])
def test_a_hung_window_is_not_copied_until_it_answers(user32, how):
    g = grabber(HUNG, W, H)
    assert g.grab() is not None and user32.printed[1] == 1
    getattr(user32, how).add(1)
    t0 = time.monotonic()
    assert g.grab() is None and g.hung      # nothing old given out either
    assert time.monotonic() - t0 < 0.5 and user32.printed[1] == 1
    getattr(user32, how).discard(1)
    assert g.grab() is not None and not g.hung and user32.printed[1] == 2


def test_a_hung_game_does_not_hold_up_the_other_windows(user32):
    fired = []
    w = sw.Watcher(fired.append, grabber=lambda *_a: pytest.fail("the screen was captured"),
                   window_grabber=grabber, front=lambda: 0)
    w.interval, w.cpu_share = 0.01, 0.0     # checks back to back
    w.set_items([Watched("hung", [(banner(), None)], 0.8, 0.0, source=HUNG),
                 Watched("ok", [(banner(), None)], 0.8, 0.0, source=OK)])
    w.start()
    try:
        assert run_until(lambda: {"hung", "ok"} <= set(w.scores))
        user32.marked.add(1)                    # the slow game stops answering
        time.sleep(0.05)
        user32.frames[2] = showing(scene(2), banner())
        t0 = time.monotonic()
        assert run_until(lambda: "ok" in fired, timeout=3.0)
        assert time.monotonic() - t0 < 1.0      # not after the hang
        assert "hung" not in fired and HUNG not in w.unseen
        user32.frames[1] = showing(scene(1), banner())
        user32.marked.discard(1)                # it answers again: watched as before
        user32.answered.set()
        assert run_until(lambda: "hung" in fired)
    finally:
        w.stop()


def test_answering_asks_windows_without_waiting_on_a_marked_window(monkeypatch):
    sent = []

    class U:
        hung = False

        def IsHungAppWindow(self, _h):
            return self.hung

        def SendMessageTimeoutW(self, h, msg, _w, _l, flags, ms, _out):
            sent.append((msg, flags, ms))
            return 1

    u = U()
    monkeypatch.setattr(windows, "_win", lambda: (u, None, None, None))
    assert windows.answering(5)
    assert sent == [(windows.WM_NULL, windows.SMTO_ABORTIFHUNG, windows.ANSWER_MS)]
    u.hung = True
    assert not windows.answering(5) and len(sent) == 1
