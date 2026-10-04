"""Watching windows: a remembered window is found again (the right copy of a game
open twice), a trigger fires from its window, a window that isn't open is waited
for without stopping the rest, one that closes is looked for again, and a
minimized one is flagged. Stand-in captures only: no real window is ever read."""
import time

import numpy as np
import pytest

from onionwatch import screenwatch as sw
from onionwatch import windows
from onionwatch.screenwatch import Monitor, Trigger, Watched, WindowRef
from onionwatch.windows import WindowInfo

W, H = 320, 180


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


def info(hwnd, title, exe="game.exe", started=0, pid=None, minimized=False):
    return WindowInfo(hwnd, title, exe, pid or hwnd, started, W, H, minimized)


# --------------------------------------------------------------------------- finding

def test_a_window_is_found_by_its_title_and_program():
    wins = [info(1, "Notes", "notepad.exe"), info(2, "Game", "game.exe")]
    assert windows.find(WindowRef("game.exe", "Game"), wins).hwnd == 2
    # another program with a window open: its windows only, whatever their titles
    wins.append(info(3, "Other", "other.exe"))
    assert windows.find(WindowRef("other.exe", "Game"), wins).hwnd == 3
    assert windows.find(WindowRef("other.exe", "Nope"), wins).hwnd == 3


def test_a_renamed_program_is_found_by_its_exact_title():
    """game.exe became game_dx12.exe (a launcher change): with no game.exe open at
    all, a window with exactly the remembered title is taken from any program."""
    wins = [info(1, "Notes", "notepad.exe"), info(9, "Game", "game_dx12.exe", started=200),
            info(4, "Game", "game_dx12.exe", started=100), info(6, "Game - Chat", "chat.exe")]
    assert [w.hwnd for w in windows.copies(WindowRef("game.exe", "Game"), wins)] == [4, 9]
    assert windows.find(WindowRef("game.exe", "Game", 1), wins).hwnd == 9
    assert windows.find(WindowRef("game.exe", "Game", 2), wins) is None
    # only an exact title counts, and an empty one never falls back
    assert windows.find(WindowRef("game.exe", "Gam"), wins) is None
    assert windows.find(WindowRef("game.exe", ""), wins) is None
    # once a game.exe window is open again, it's the one meant
    wins.append(info(2, "Game - Loading", "game.exe"))
    assert [w.hwnd for w in windows.copies(WindowRef("game.exe", "Game"), wins)] == [2]


def test_a_title_that_changed_still_finds_the_program():
    """Games that put the character or zone in their title are still found."""
    wins = [info(5, "MyGame - Stormwind", "mygame.exe")]
    assert windows.find(WindowRef("mygame.exe", "MyGame - Ironforge"), wins).hwnd == 5


def test_two_copies_of_a_game_are_told_apart_by_when_they_started():
    wins = [info(9, "Game", started=200), info(4, "Game", started=100), info(7, "Notes", "n.exe")]
    first, second = windows.copies(WindowRef("game.exe", "Game"), wins)
    assert (first.hwnd, second.hwnd) == (4, 9)
    assert windows.ref_for(wins[0], wins) == WindowRef("game.exe", "Game", 1)
    assert windows.ref_for(wins[1], wins) == WindowRef("game.exe", "Game", 0)
    assert windows.find(WindowRef("game.exe", "Game", 1), wins).hwnd == 9
    # the second copy closed: copy 2 waits instead of watching the first one
    assert windows.find(WindowRef("game.exe", "Game", 1), wins[1:]) is None


def test_a_window_ref_is_saved_and_checked_when_loaded():
    t = Trigger(id="a", sources=[WindowRef("game.exe", "Game", 1)])
    raw = t.to_raw()
    assert raw["window"] == {"exe": "game.exe", "title": "Game", "nth": 1}
    back = Trigger.from_raw(raw)
    assert back.window == WindowRef("game.exe", "Game", 1) and back.source == back.window
    for bad in ("game", {"exe": 3}, {"exe": "", "title": ""}, [1]):
        assert Trigger.from_raw({"id": "a", "window": bad}).window is None
    assert WindowRef.from_raw({"exe": "Game.EXE", "title": "x", "nth": -2}) == \
        WindowRef("game.exe", "x", 0)
    assert Trigger.from_raw({"id": "a", "monitor": 1}).source == 1


# --------------------------------------------------------------------------- watching

class FakeWindows:
    """Stands in for WindowGrabber: `open` holds the windows that are open (by ref)
    and the frame each shows; `minimized` those minimized."""

    def __init__(self):
        self.open: dict[WindowRef, np.ndarray] = {}
        self.minimized: set[WindowRef] = set()
        self.made: list = []
        fw = self

        class Grab:
            def __init__(self, ref, w, h):
                if ref not in fw.open:
                    raise windows.WindowGone(f"{ref.label} isn't open")
                self.ref, self.w, self.h = ref, W, H
                self.source = (W, H)
                self.minimized = False
                fw.made.append(self)

            def resize(self, w, h):
                self.w, self.h = w, h

            def grab(self):
                if self.ref not in fw.open:
                    raise sw.CaptureLost(f"{self.ref.label} was closed")
                self.minimized = self.ref in fw.minimized
                return None if self.minimized else fw.open[self.ref]

            def close(self):
                pass

        self.Grab = Grab


@pytest.fixture
def fake(monkeypatch):
    monkeypatch.setattr(sw, "monitors", lambda: [Monitor(0, 0, W, H, True)])
    monkeypatch.setattr(sw, "WORK_WIDTH", W)
    monkeypatch.setattr(sw, "WINDOW_RETRY_S", 0.05)
    return FakeWindows()


def run_until(cond, timeout=5.0):
    end = time.monotonic() + timeout
    while not cond() and time.monotonic() < end:
        time.sleep(0.005)
    return cond()


GAME1 = WindowRef("game.exe", "Game", 0)
GAME2 = WindowRef("game.exe", "Game", 1)


def watcher(fake, fired, **kw):
    screen = lambda mon, w, h: pytest.fail("the screen was captured")   # noqa: E731
    w = sw.Watcher(fired.append, grabber=screen, window_grabber=fake.Grab, **kw)
    w.interval = 0.01
    return w


def test_a_trigger_fires_from_its_window(fake):
    fired = []
    fake.open[GAME1] = scene(1)
    w = watcher(fake, fired)
    w.set_items([Watched("t", [(banner(), None)], 0.8, 0.0, source=GAME1)])
    w.start()
    try:
        assert run_until(lambda: "t" in w.scores)
        assert not fired
        fake.open[GAME1] = showing(scene(1), banner())
        assert run_until(lambda: fired == ["t"])
        assert w.where["t"] == (GAME1,)
    finally:
        w.stop()


def test_each_copy_of_a_game_is_watched_on_its_own(fake):
    """Two accounts, two windows: the banner in the second fires only its trigger."""
    fired = []
    fake.open[GAME1] = scene(1)
    fake.open[GAME2] = scene(2)
    w = watcher(fake, fired)
    w.set_items([Watched("one", [(banner(), None)], 0.8, 0.0, source=GAME1),
                 Watched("two", [(banner(), None)], 0.8, 0.0, source=GAME2)])
    w.start()
    try:
        assert run_until(lambda: {"one", "two"} <= set(w.scores))
        fake.open[GAME2] = showing(scene(2), banner())
        assert run_until(lambda: fired == ["two"])
        time.sleep(0.1)
        assert fired == ["two"]
    finally:
        w.stop()


def test_a_window_that_is_not_open_is_waited_for_without_stopping_the_rest(fake):
    fired = []
    fake.open[GAME1] = scene(1)
    w = watcher(fake, fired)
    w.set_items([Watched("here", [(banner(), None)], 0.8, 0.0, source=GAME1),
                 Watched("later", [(banner(), None)], 0.8, 0.0, source=GAME2)])
    w.start()
    try:
        assert run_until(lambda: GAME2 in w.failed and "here" in w.scores)
        assert "isn't open" in w.failed[GAME2] and w.running and not w.error
        fake.open[GAME2] = showing(scene(2), banner())    # the second copy starts
        assert run_until(lambda: fired == ["later"])
        assert run_until(lambda: GAME2 not in w.failed)
    finally:
        w.stop()


def test_nothing_open_at_all_waits_instead_of_stopping(fake):
    w = watcher(fake, [])
    w.set_items([Watched("t", [(banner(), None)], 0.8, 0.0, source=GAME1)])
    w.start()
    try:
        assert run_until(lambda: GAME1 in w.failed)
        time.sleep(0.2)
        assert w.running and not w.error
    finally:
        w.stop()


def test_a_window_closed_while_watched_is_looked_for_again(fake):
    fired = []
    fake.open[GAME1] = scene(1)
    w = watcher(fake, fired)
    w.set_items([Watched("t", [(banner(), None)], 0.8, 0.0, source=GAME1)])
    w.start()
    try:
        assert run_until(lambda: "t" in w.scores)
        del fake.open[GAME1]                            # the game was closed
        assert run_until(lambda: GAME1 in w.failed)
        assert w.running and "t" not in w.scores
        fake.open[GAME1] = showing(scene(1), banner())  # ...and started again
        assert run_until(lambda: fired == ["t"])
        assert len(fake.made) >= 2
    finally:
        w.stop()


def test_a_minimized_window_is_flagged(fake):
    fake.open[GAME1] = scene(1)
    w = watcher(fake, [])
    w.set_items([Watched("t", [(banner(), None)], 0.8, 0.0, source=GAME1)])
    w.start()
    try:
        assert run_until(lambda: "t" in w.scores)
        fake.minimized.add(GAME1)
        assert run_until(lambda: GAME1 in w.minimized)
        fake.minimized.clear()
        assert run_until(lambda: GAME1 not in w.minimized)
    finally:
        w.stop()


def test_triggers_without_their_own_follow_a_default_window(fake):
    fired = []
    fake.open[GAME1] = showing(scene(1), banner())
    w = watcher(fake, fired)
    w.default = GAME1
    w.set_items([Watched("t", [(banner(), None)], 0.8, 0.0)])
    w.start()
    try:
        assert run_until(lambda: fired == ["t"])
        assert w.where["t"] == (GAME1,)
    finally:
        w.stop()


def test_a_resized_window_has_its_pictures_scaled_again(fake):
    """The window doubles in size: the picture must be found at the new scale."""
    fired = []
    big = np.kron(showing(scene(1), banner()), np.ones((2, 2), np.float32))
    fake.open[GAME1] = scene(1)
    w = watcher(fake, fired)
    w.set_items([Watched("t", [(np.kron(banner(), np.ones((2, 2), np.float32)), None)],
                         0.8, 0.0, source=GAME1)])
    w.start()
    try:
        assert run_until(lambda: len(fake.made) == 1 and "t" in w.scores)
        g = fake.made[0]
        g.source = (2 * W, 2 * H)                      # resized: frames come in bigger
        fake.open[GAME1] = big[::2, ::2]               # ...shrunk by the scaled capture
        assert run_until(lambda: fired == ["t"])
    finally:
        w.stop()


def test_a_window_that_never_comes_out_is_flagged(fake, monkeypatch):
    """PrintWindow failing every time gives no picture at all: after a while the
    window is listed in `unseen` (its cards say so) instead of quietly "Watching"."""
    monkeypatch.setattr(sw, "UNSEEN_S", 0.05)
    fake.open[GAME1] = None                        # open, but nothing comes out
    w = watcher(fake, [])
    w.set_items([Watched("t", [(banner(), None)], 0.8, 0.0, source=GAME1)])
    w.start()
    try:
        assert run_until(lambda: GAME1 in w.unseen)
        fake.open[GAME1] = scene(1)                # ...and now it does
        assert run_until(lambda: GAME1 not in w.unseen and "t" in w.scores)
    finally:
        w.stop()


@pytest.mark.parametrize("in_front, heavy", [(True, False), (False, True)])
def test_max_detection_while_away_from_a_watched_window(fake, in_front, heavy):
    """"away": all out only while the watched game's window isn't the one in front."""
    fake.open[GAME1] = scene(1)

    class Grab(fake.Grab):
        def in_front(self):
            return in_front
    w = sw.Watcher(lambda *_a: None, grabber=lambda *_a: pytest.fail("screen captured"),
                   window_grabber=Grab, front=lambda: 5,
                   fills=lambda *_a: pytest.fail("a window's capture has no screen"))
    w.interval = 0.01
    w.max_detect = "away"
    w.set_items([Watched("t", [(banner(), None)], 0.8, 0.0, source=GAME1)])
    w.start()
    try:
        assert run_until(lambda: "t" in w.scores)
        time.sleep(0.1)
        assert w.heavy == heavy
    finally:
        w.stop()
