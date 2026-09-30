"""What a trigger can do beyond "a picture shows up": look in several windows and
screens at once (each going off on its own, saying which it was), in every copy
of a game (also one started later), only in part of each window, and go off when
its picture goes away, when its area changes or stops changing, or when a colour
(a health bar) runs low; wait for it to last; stay quiet in the window you're
playing. Stand-in captures only: no real window or screen is read."""
import time

import numpy as np
import pytest

from onionwatch import screenwatch as sw
from onionwatch.screenwatch import Gate, Hit, Monitor, Trigger, Watched, WindowRef
from onionwatch.windows import WindowGone, WindowInfo

W, H = 320, 180
GAME1, GAME2, GAME3 = (WindowRef("game.exe", "Game", i) for i in range(3))
EVERY = WindowRef("game.exe", "Game", every=True)


def scene(seed=0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    x = rng.random((H // 4, W // 4)).astype(np.float32)
    return np.kron(x, np.ones((4, 4), np.float32)) * 0.6 + 0.1


def banner() -> np.ndarray:
    b = np.full((24, 90), 0.05, np.float32)
    for i, x in enumerate(range(4, 86, 9)):
        b[5:19, x:x + 5] = 0.9 if i % 2 else 0.7
        b[11:13, x:x + 8] = 0.8
    return b


def showing(screen, x=110, y=70):
    s = screen.copy()
    b = banner()
    s[y:y + b.shape[0], x:x + b.shape[1]] = b
    return s


def run_until(cond, timeout=5.0):
    end = time.monotonic() + timeout
    while not cond() and time.monotonic() < end:
        time.sleep(0.005)
    return cond()


class Windows:
    """Stand-in windows: `open` maps a window (by ref) to the frame it shows (grey,
    or (grey, rgb) for colour); `front` is the one in front."""

    def __init__(self):
        self.open: dict[WindowRef, object] = {}
        self.front: WindowRef | None = None
        ws = self

        class Grab:
            want_color = False
            color = None

            def __init__(self, ref, w, h):
                if ref not in ws.open:
                    raise WindowGone(f"{ref.label} isn't open")
                self.ref, self.w, self.h, self.source = ref, W, H, (W, H)

            def resize(self, w, h):
                self.w, self.h = w, h

            def grab(self):
                if self.ref not in ws.open:
                    raise sw.CaptureLost("closed")
                f = ws.open[self.ref]
                if isinstance(f, tuple):
                    f, self.color = f
                return f

            def in_front(self):
                return ws.front == self.ref

            def close(self):
                pass

        self.Grab = Grab

    def listing(self) -> list[WindowInfo]:
        """The open windows as list_windows gives them (copies in order)."""
        return [WindowInfo(i + 1, r.title, r.exe, i + 1, i, W, H)
                for i, r in enumerate(sorted(self.open, key=lambda r: r.nth))]


@pytest.fixture
def ws(monkeypatch):
    monkeypatch.setattr(sw, "monitors", lambda: [Monitor(0, 0, W, H, True)])
    monkeypatch.setattr(sw, "WORK_WIDTH", W)
    monkeypatch.setattr(sw, "WINDOW_RETRY_S", 0.05)
    return Windows()


def watcher(ws, fired, **kw):
    w = sw.Watcher(lambda tid, hit: fired.append((tid, hit)), hits=True,
                   grabber=lambda *a, **k: pytest.fail("the screen was captured"),
                   window_grabber=ws.Grab, lister=ws.listing, **kw)
    w.interval = 0.01
    return w


# --------------------------------------------------------------------------- saving

def test_several_places_are_saved_and_older_versions_see_the_first():
    t = Trigger(id="a", sources=[1, GAME2, EVERY], mode="colour", colour="#FF0000",
                region=(0.1, 0.2, 0.3, 0.4), hold=2.5, unfocused=True, level=0.3)
    raw = t.to_raw()
    assert raw["screens"] == [1] and raw["monitor"] == 1
    assert raw["windows"][1] == {"exe": "game.exe", "title": "Game", "nth": 0, "every": True}
    assert raw["window"] == GAME2.to_raw()          # what an older version watches
    back = Trigger.from_raw(raw)
    assert back.sources == [1, GAME2, EVERY] and back.mode == "colour"
    assert back.region == (0.1, 0.2, 0.3, 0.4) and back.colour == "#ff0000"
    assert (back.hold, back.unfocused, back.level) == (2.5, True, 0.3)
    assert back.rgb == (1.0, 0.0, 0.0)
    # an older version's config: one window, which won over its screen
    old = Trigger.from_raw({"id": "a", "monitor": 1, "window": GAME2.to_raw()})
    assert old.sources == [GAME2] and old.mode == "appear" and old.region is None


def test_odd_saved_values_are_checked():
    t = Trigger.from_raw({"id": "a", "mode": "explode", "region": [0.5, 0.5, 9, 0.0001],
                          "colour": "#12345z", "hold": -3, "level": 7,
                          "screens": [0, 0, "x", -1], "windows": [{"exe": ""}, 3]})
    assert t.mode == "appear" and t.region is None and t.colour == ""
    assert t.hold == 0.0 and t.level == 0.99 and t.sources == [0]
    assert Trigger.from_raw({"id": "a", "region": [0, 0, 1, 1]}).region is None   # all of it
    assert sw._region([0.9, 0.9, 0.5, 0.5]) == (0.9, 0.9, 0.1, 0.1)
    many = Trigger.from_raw({"id": "a", "screens": list(range(40))})
    assert len(many.sources) == sw.MAX_SOURCES


def test_setting_one_window_or_screen_the_old_way():
    t = Trigger(id="a", sources=[0, GAME1])
    t.window = GAME2
    assert t.sources == [GAME2] and t.source == GAME2
    t.monitor = 1                     # a window wins, as it did
    assert t.sources == [GAME2]
    t.window = None
    assert t.sources == []
    t.monitor = 1
    assert t.sources == [1] and t.monitor == 1


def test_a_copy_is_the_same_trigger_under_a_new_id():
    t = Trigger(id="a", name="Rare", sources=[GAME1], mode="vanish", images=["x.png"])
    c = t.copy("b")
    assert c.id == "b" and c.name == "Rare" and c.sources == [GAME1] and c.mode == "vanish"
    assert c.images == ["x.png"] and c.images is not t.images


# --------------------------------------------------------------------------- deciding

def test_the_gate_waits_for_it_to_last():
    g = Gate()
    assert not g.step(True, 0.0, 0.0, hold=1.0)
    assert not g.step(True, 0.5, 0.0, hold=1.0)
    assert g.step(True, 1.1, 0.0, hold=1.0)
    assert not g.step(True, 2.0, 0.0, hold=1.0)       # once per appearance
    g.step(False, 3.0, 0.0)
    assert not g.step(True, 3.1, 0.0, hold=1.0)
    g.step(None, 3.5, 0.0)                            # a wobble starts the wait again
    assert not g.step(True, 4.2, 0.0, hold=1.0)
    assert g.step(True, 5.3, 0.0, hold=1.0)


def test_verdicts_for_each_mode():
    assert sw.verdict("appear", 0.9, 0.8) is True and sw.verdict("appear", 0.5, 0.8) is False
    assert sw.verdict("appear", 0.78, 0.8) is None
    assert sw.verdict("vanish", 0.5, 0.8) is True and sw.verdict("vanish", 0.9, 0.8) is False
    assert sw.verdict("change", 0.2, 0.1) is True and sw.verdict("change", 0.01, 0.1) is False
    assert sw.verdict("still", 0.0, 0.01) is True and sw.verdict("still", 0.2, 0.01) is False
    assert sw.verdict("colour", 0.2, 0.3) is True
    assert sw.verdict("colour", 0.32, 0.3) is None and sw.verdict("colour", 0.5, 0.3) is False
    assert sw.verdict("colour", 0.5, 0.3, below=False) is True


def test_an_area_is_grown_to_fit_the_picture_and_kept_inside():
    assert sw.region_box(None, (100, 200)) == (0, 100, 0, 200)
    assert sw.region_box((0.25, 0.5, 0.5, 0.5), (100, 200)) == (50, 100, 50, 150)
    y0, y1, x0, x1 = sw.region_box((0.98, 0.0, 0.01, 0.01), (100, 200), (30, 40))
    assert (y1 - y0, x1 - x0) == (30, 40) and x1 == 200 and y0 == 0


def test_changed_and_colour_shares():
    a = np.zeros((10, 10), np.float32)
    b = a.copy()
    b[:5] = 0.5
    assert sw.changed_share(b, a) == 0.5 and sw.changed_share(a, a) == 0.0
    rgb = np.zeros((10, 10, 3), np.float32)
    rgb[:, :3] = (0.8, 0.1, 0.1)                     # 30 % of the bar is red
    assert sw.colour_share(rgb, (0.85, 0.12, 0.1)) == pytest.approx(0.3)


def test_frame_rgb_matches_the_grey_sampling():
    px = np.zeros((4, 4, 4), np.uint8)
    px[..., 2] = 255                                 # red, in BGRA
    rgb = sw.frame_rgb(px, sw.FMT_BGRA8, 2)
    assert rgb.shape == (2, 2, 3) and np.allclose(rgb[0, 0], (1, 0, 0))


# --------------------------------------------------------------------------- watching

def test_one_trigger_watches_two_windows_and_says_which_went_off(ws):
    ws.open = {GAME1: scene(1), GAME2: scene(2)}
    fired = []
    w = watcher(ws, fired)
    w.set_items([Watched("t", [(banner(), None)], 0.8, 0.0, sources=[GAME1, GAME2])])
    w.start()
    try:
        assert run_until(lambda: set(w.detail.get("t", {})) == {GAME1, GAME2})
        assert w.where["t"] == (GAME1, GAME2)
        ws.open[GAME2] = showing(scene(2))
        assert run_until(lambda: len(fired) == 1)
        tid, hit = fired[0]
        assert tid == "t" and hit.source == GAME2 and hit.score > 0.95
        x, y, bw, bh = hit.box
        assert (round(x * W), round(y * H), round(bw * W), round(bh * H)) == (110, 70, 90, 24)
        assert w.scores["t"] > 0.95                      # the best of the two
        ws.open[GAME1] = showing(scene(1))               # the other one too: its own gate
        assert run_until(lambda: len(fired) == 2)
        assert fired[1][1].source == GAME1
        time.sleep(0.1)
        assert len(fired) == 2                           # each once per appearance
    finally:
        w.stop()


def test_every_copy_picks_up_a_copy_started_later(ws):
    ws.open = {GAME1: scene(1)}
    fired = []
    w = watcher(ws, fired)
    w.set_items([Watched("t", [(banner(), None)], 0.8, 0.0, sources=[EVERY])])
    w.start()
    try:
        assert run_until(lambda: w.where.get("t") == (GAME1,))
        ws.open[GAME2] = scene(2)
        assert run_until(lambda: w.where.get("t") == (GAME1, GAME2))
        ws.open[GAME3] = showing(scene(3))
        assert run_until(lambda: fired and fired[0][1].source == GAME3)
    finally:
        w.stop()


def test_every_copy_waits_while_none_is_open(ws):
    fired = []
    w = watcher(ws, fired)
    w.set_items([Watched("t", [(banner(), None)], 0.8, 0.0, sources=[EVERY])])
    w.start()
    try:
        assert run_until(lambda: GAME1 in w.failed)      # "waiting for Game to open"
        ws.open[GAME1] = showing(scene(1))
        assert run_until(lambda: len(fired) == 1)
    finally:
        w.stop()


def test_an_area_only_looks_in_that_part(ws):
    ws.open = {GAME1: showing(scene(1), x=10, y=10)}          # top left
    fired = []
    w = watcher(ws, fired)
    w.set_items([Watched("t", [(banner(), None)], 0.8, 0.0, sources=[GAME1],
                         region=(0.5, 0.5, 0.5, 0.5))])        # bottom right
    w.start()
    try:
        assert run_until(lambda: "t" in w.scores)
        time.sleep(0.05)
        assert w.scores["t"] < 0.6 and not fired
        ws.open[GAME1] = showing(scene(1), x=200, y=130)
        assert run_until(lambda: len(fired) == 1)
        x, y, _w, _h = fired[0][1].box
        assert (round(x * W), round(y * H)) == (200, 130)
    finally:
        w.stop()


def test_it_goes_off_when_the_picture_goes_away(ws):
    ws.open = {GAME1: scene(1)}
    fired = []
    w = watcher(ws, fired)
    w.set_items([Watched("t", [(banner(), None)], 0.8, 0.0, sources=[GAME1], mode="vanish")])
    w.start()
    try:
        assert run_until(lambda: "t" in w.scores)
        time.sleep(0.05)
        assert not fired                              # never seen: nothing went away
        ws.open[GAME1] = showing(scene(1))
        assert run_until(lambda: w.scores.get("t", 0) > 0.95)
        assert not fired
        ws.open[GAME1] = scene(1)
        assert run_until(lambda: len(fired) == 1)
    finally:
        w.stop()


def test_it_goes_off_when_the_area_changes_and_when_it_stops(ws, monkeypatch):
    monkeypatch.setattr(sw, "CHANGE_GAP", 0.02)
    ws.open = {GAME1: scene(1)}
    fired = []
    w = watcher(ws, fired)
    w.set_items([Watched("moved", [], 0.05, 0.0, sources=[GAME1], mode="change",
                         region=(0.0, 0.0, 0.5, 0.5)),
                 Watched("idle", [], 0.01, 0.0, sources=[GAME1], mode="still", hold=0.2)])
    w.start()
    try:
        assert run_until(lambda: ("idle", ) == tuple(t for t, _h in fired))  # still for 0.2 s
        ws.open[GAME1] = scene(2)                     # everything moves
        assert run_until(lambda: [t for t, _h in fired] == ["idle", "moved"])
        time.sleep(0.1)
        ws.open[GAME1] = scene(3)                     # the idle trigger re-armed on the move
        assert run_until(lambda: [t for t, _h in fired].count("idle") == 2)
    finally:
        w.stop()


def test_a_colour_bar_running_low_goes_off(ws):
    def bar(full: float):
        rgb = np.zeros((H, W, 3), np.float32)
        rgb[10:20, 10:10 + int(100 * full)] = (0.8, 0.1, 0.1)
        return scene(1), rgb
    ws.open = {GAME1: bar(1.0)}
    fired = []
    w = watcher(ws, fired)
    area = (10 / W, 10 / H, 100 / W, 10 / H)
    w.set_items([Watched("hp", [], 0.3, 0.0, sources=[GAME1], mode="colour",
                         colour=(0.8, 0.1, 0.1), region=area)])
    w.start()
    try:
        assert run_until(lambda: w.scores.get("hp", 0) > 0.95)
        ws.open[GAME1] = bar(0.5)
        time.sleep(0.05)
        assert not fired
        ws.open[GAME1] = bar(0.2)
        assert run_until(lambda: len(fired) == 1)
        assert fired[0][1].score == pytest.approx(0.2, abs=0.02)
    finally:
        w.stop()


def test_it_stays_quiet_in_the_window_you_are_playing(ws):
    ws.open = {GAME1: scene(1), GAME2: scene(2)}
    ws.front = GAME1
    fired = []
    w = watcher(ws, fired)
    w.set_items([Watched("t", [(banner(), None)], 0.8, 0.0, sources=[GAME1, GAME2],
                         unfocused=True)])
    w.start()
    try:
        assert run_until(lambda: len(w.detail.get("t", {})) == 2)
        ws.open[GAME1] = showing(scene(1))
        time.sleep(0.1)
        assert not fired
        ws.open[GAME2] = showing(scene(2))
        assert run_until(lambda: [h.source for _t, h in fired] == [GAME2])
    finally:
        w.stop()


def test_the_score_shown_is_the_place_closest_to_going_off():
    items = [Watched("a", [], 0.8, 0.0), Watched("v", [], 0.8, 0.0, mode="vanish")]
    c1, c2 = sw._Capture(GAME1), sw._Capture(GAME2)
    for c in (c1, c2):
        c.grab = object()
    c1.scores, c2.scores = {"a": 0.2, "v": 0.9}, {"a": 0.7, "v": 0.3}
    detail, scores = sw.Watcher._gather(items, {GAME1: c1, GAME2: c2})
    assert scores == {"a": 0.7, "v": 0.3}
    assert detail["a"] == {GAME1: 0.2, GAME2: 0.7}


def test_a_hit_says_where():
    h = Hit(GAME2, (0.1, 0.2, 0.3, 0.4), 0.9)
    assert h.source.label == "Game (copy 2)" and EVERY.label == "Game (every copy)"
