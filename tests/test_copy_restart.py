"""Several copies of one game: a copy that's closed and started again is the
newest copy then, and its triggers follow it there, never onto a copy somebody
else is playing. Stand-in windows and captures only."""
import time

import numpy as np
import pytest

from onionwatch.engine import screenwatch as sw
from onionwatch.engine import windows
from onionwatch.engine.screenwatch import Monitor, Watched, WindowRef
from onionwatch.engine.windows import WindowInfo

W, H = 320, 180
COPY = [WindowRef("game.exe", "Game", n) for n in range(3)]


def scene(seed=0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return rng.random((H, W)).astype(np.float32) * 0.5 + 0.1


def banner() -> np.ndarray:
    y, x = np.mgrid[0:30, 0:90]
    return (((x // 6 + y // 5) % 2) * 0.8 + 0.1).astype(np.float32)


def showing(screen, pic, x=110, y=70):
    s = screen.copy()
    h, w = pic.shape
    s[y:y + h, x:x + w] = pic
    return s


def info(hwnd, started):
    return WindowInfo(hwnd, "Game", "game.exe", hwnd, started, W, H)


class Copies:
    """Open game windows (hwnd -> (when it started, what it shows)); a capture is of
    copy `nth` of them by start order when it's opened, then of that window."""

    def __init__(self):
        self.open: dict[int, list] = {}
        cs = self

        class Grab:
            def __init__(self, ref, w, h):
                pool = cs.listing()
                if ref.nth >= len(pool):
                    raise windows.WindowGone("not open")
                self.hwnd = pool[ref.nth].hwnd
                self.w, self.h, self.source, self.minimized = w, h, (W, H), False

            def resize(self, w, h):
                self.w, self.h = w, h

            def grab(self):
                if self.hwnd not in cs.open:
                    raise sw.CaptureLost("closed")
                return cs.open[self.hwnd][1]

            def close(self):
                pass

        self.Grab = Grab

    def listing(self) -> list[WindowInfo]:
        return windows.copies(COPY[0], [info(h, s) for h, (s, _f) in self.open.items()])


@pytest.fixture
def cs(monkeypatch):
    monkeypatch.setattr(sw, "monitors", lambda: [Monitor(0, 0, W, H, True)])
    monkeypatch.setattr(sw, "WORK_WIDTH", W)
    monkeypatch.setattr(sw, "WINDOW_RETRY_S", 0.05)
    return Copies()


def run_until(cond, timeout=5.0):
    end = time.monotonic() + timeout
    while not cond() and time.monotonic() < end:
        time.sleep(0.005)
    return cond()


def test_a_restarted_copy_keeps_its_triggers():
    """follow(): the same window back, else one that wasn't open at the loss; a
    window another capture has is never taken."""
    wins = [info(12, 2), info(13, 3), info(14, 4)]
    assert windows.follow(COPY[0], wins, taken={12, 13}, was=11, before={11, 12, 13}).hwnd == 14
    assert windows.follow(COPY[0], wins[:2], taken={12, 13}, was=11, before={11, 12, 13}) is None
    assert windows.follow(COPY[0], wins[:2], taken=set(), was=11, before={11, 12, 13}) is None
    assert windows.follow(COPY[0], wins, taken=set(), was=13, before={11, 12, 13}).hwnd == 13
    # a first start finds copy nth, as before
    assert windows.follow(COPY[1], wins).hwnd == 13
    assert windows.follow(COPY[1], wins, taken={13}) is None


def test_a_closed_copy_s_trigger_waits_for_it_not_the_next_copy(cs):
    fired = []
    for h in (11, 12, 13):
        cs.open[h] = [h, scene(h)]
    w = sw.Watcher(lambda tid, hit: fired.append(tid), hits=True,
                   grabber=lambda *a, **k: pytest.fail("the screen was captured"),
                   window_grabber=cs.Grab, lister=cs.listing)
    w.interval = 0.01
    w.set_items([Watched(f"copy{n + 1}", [(banner(), None)], 0.8, 0.0, source=COPY[n])
                 for n in range(3)])
    w.start()
    try:
        assert run_until(lambda: len(w.scores) == 3)
        del cs.open[11]                                 # copy 1 is closed...
        time.sleep(0.3)
        cs.open[12][1] = showing(scene(12), banner())  # ...copy 2's picture: copy 2's only
        assert run_until(lambda: "copy2" in fired)
        time.sleep(0.3)
        assert "copy1" not in fired
        cs.open[12][1] = scene(12)
        cs.open[14] = [14, showing(scene(14), banner())]   # copy 1 started again: the newest
        assert run_until(lambda: "copy1" in fired)
        time.sleep(0.3)
        assert fired.count("copy2") == 1 and "copy3" not in fired
    finally:
        w.stop()


def test_a_window_made_again_at_once_is_followed():
    """The new window already open when the loss is seen (it's in `before`): the one
    window that wasn't a copy when the capture opened (`peers`) is it; another
    copy is never taken, and two new ones can't be told apart."""
    wins = [info(12, 2), info(13, 3), info(14, 4)]
    assert windows.follow(COPY[0], wins[2:], was=11, before={11, 14}, peers=set()).hwnd == 14
    assert windows.follow(COPY[0], wins, was=11, before={11, 12, 13, 14},
                          peers={12, 13}).hwnd == 14
    assert windows.follow(COPY[0], wins[:2], was=11, before={11, 12, 13}, peers={12, 13}) is None
    assert windows.follow(COPY[0], wins, was=11, before={11, 12, 13, 14}, peers={12}) is None
    assert windows.follow(COPY[0], wins, taken={14}, was=11, before={11, 12, 13, 14},
                          peers={12, 13}) is None


def test_a_game_that_makes_its_window_again_keeps_its_trigger(cs):
    """A game closes its window and opens a new one between two checks (a restart, a
    switch to full screen): the trigger looks in the new window, not nowhere."""
    fired = []
    cs.open[11] = [1, scene(11)]
    w = sw.Watcher(lambda tid, hit: fired.append(tid), hits=True,
                   grabber=lambda *a, **k: pytest.fail("the screen was captured"),
                   window_grabber=cs.Grab, lister=cs.listing)
    w.interval = 0.01
    w.set_items([Watched("game", [(banner(), None)], 0.8, 0.0, source=COPY[0])])
    w.start()
    try:
        assert run_until(lambda: len(w.scores) == 1)
        cs.open = {15: [5, showing(scene(15), banner())]}   # gone and back in one step
        assert run_until(lambda: "game" in fired)
    finally:
        w.stop()
