"""Pictures found at other sizes than they were cut at ("any size"), the colour check
that keeps look-alikes out, and the cap on how much of the processor watching may
use. The 'game' is made up here: textured tiles and a sprite, scaled the way a game
scales its textures when its window changes size. No screen is read."""
import time

import numpy as np
import pytest

from onionwatch import screenwatch as sw
from onionwatch.screenwatch import Monitor, Trigger

ORANGE = (200, 100, 50)     # these two are all but the same grey (luma ~124)...
TEAL = (60, 160, 120)       # ...so only their colours tell them apart
DARK = (30, 25, 20)


def sprite(colour=ORANGE, n=6, cell=8) -> np.ndarray:
    """A 48 x 48 gem-like sprite (RGB uint8): a pattern of coloured and dark cells."""
    rng = np.random.default_rng(5)
    on = rng.random((n, n)) < 0.5
    on[0, 0], on[0, 1] = True, False
    rgb = np.where(on[..., None], np.array(colour, np.uint8), np.array(DARK, np.uint8))
    return np.kron(rgb, np.ones((cell, cell, 1), np.uint8)).astype(np.uint8)


def world(sprites=((ORANGE, 300, 200),), seed=1) -> np.ndarray:
    """A 540 x 960 RGB level: grassy tiles, a stone path, and sprites at (x, y)."""
    rng = np.random.default_rng(seed)
    tiles = rng.random((34, 60))
    g = np.kron(tiles, np.ones((16, 16)))[:540, :960]
    img = np.stack([60 + 40 * g, 110 + 60 * g, 50 + 30 * g], -1)
    img[330:380] = 120 + 20 * g[330:380, :, None]
    for colour, x, y in sprites:
        img[y:y + 48, x:x + 48] = sprite(colour)
    return np.clip(img, 0, 255).astype(np.uint8)


def scaled(rgb: np.ndarray, k: float) -> np.ndarray:
    """The level drawn k times the size (the game's textures resampled)."""
    return np.stack([np.clip(np.round(sw.resize(rgb[..., c].astype(np.float32), k)), 0, 255)
                     for c in range(3)], -1).astype(np.uint8)


def gray(rgb: np.ndarray) -> np.ndarray:
    return sw.to_gray(rgb[..., ::-1])


def cut(rgb: np.ndarray, x=292, y=192, s=64) -> tuple[np.ndarray, np.ndarray]:
    """The sprite with a little of the level around it, as someone would cut it:
    (grey, tint)."""
    piece = rgb[y:y + s, x:x + s]
    return gray(piece), sw.tint(piece.astype(np.float32) / 255)


class Grab:
    """The capture as the watcher sees it: its size, and the pixels of the last grab
    for the colour check."""

    def __init__(self, w, h):
        self.source = (w, h)
        self.w = self.h = 0

    def resize(self, w, h):
        self.w, self.h = w, h


def watcher_on(rgb: np.ndarray, pic, tint, cut_from=(960, 540), any_size=True):
    """(check, capture): check() scores one frame of `rgb` as the watcher would."""
    h, w = rgb.shape[:2]
    grab = Grab(w, h)
    it = sw.Watched("t", [(pic, None)], 0.8, 0.0, any_size=any_size, cuts=[cut_from],
                    tints=[tint] if tint is not None else [])
    cap = sw._Capture(0, Monitor(0, 0, w, h, True))
    cap.grab = grab
    cap.fitted, cap.scaled = sw.Watcher._fit(grab, cap.mon, [it])
    small = scaled(rgb, grab.w / w)[:grab.h, :grab.w]
    grab.raw = (np.dstack([small[..., ::-1], np.full(small.shape[:2], 255, np.uint8)]),
                sw.FMT_BGRA8, 1)
    frame = gray(small)
    return (lambda: sw.Watcher._score(cap, frame, it, 0.0, {})[0]), cap


def test_sizes_are_predicted_from_what_the_picture_was_cut_from():
    assert sw.sizes_for(None, (1280, 720)) == [1.0]
    assert sw.sizes_for((1920, 1080), (1920, 1080)) == [1.0]
    assert sw.sizes_for((1920, 1080), (1280, 720)) == pytest.approx([1.0, 2 / 3])
    got = sw.sizes_for((1920, 1080), (1024, 768))     # 4:3: by height, then by width
    assert got == pytest.approx([1.0, 768 / 1080, 1024 / 1920])
    assert sw.sizes_for((1920, 1080), (640, 360)) == [1.0]   # a third: out of range


def test_a_picture_cut_fullscreen_is_found_in_a_smaller_window():
    level = world()
    pic, tint = cut(level)
    small = scaled(level, 2 / 3)                     # the game in a 640 x 360 window
    check, _cap = watcher_on(small, pic, tint)
    assert check() > 0.9                             # at once: the size was predicted
    check_off, _ = watcher_on(small, pic, tint, any_size=False)
    assert check_off() < 0.6                         # what it did before "any size"


def test_a_picture_is_found_bigger_too():
    level = world()
    pic, tint = cut(level)
    check, _cap = watcher_on(scaled(level, 1.5), pic, tint)     # a 1440 x 810 window
    assert check() > 0.9


def test_a_cut_out_is_found_at_another_size_on_another_background():
    """A cut-out (transparent round it) matches whatever is behind it, at any size."""
    gem = gray(sprite())
    mask = np.ones(gem.shape, bool)
    mask[:8, :8] = mask[-8:, -8:] = False             # clipped corners
    level = world(sprites=())
    level[200:248, 300:348][mask] = sprite()[mask]
    rng = np.random.default_rng(4)                   # somewhere else entirely
    level[:, :200] = (rng.random((540, 200, 1)) * 255).astype(np.uint8)
    small = scaled(level, 2 / 3)
    h, w = small.shape[:2]
    grab = Grab(w, h)
    it = sw.Watched("t", [(gem, mask)], 0.8, 0.0, any_size=True, cuts=[(960, 540)])
    cap = sw._Capture(0, Monitor(0, 0, w, h, True))
    cap.grab = grab
    cap.fitted, cap.scaled = sw.Watcher._fit(grab, cap.mon, [it])
    frame = gray(scaled(small, grab.w / w)[:grab.h, :grab.w])
    assert sw.Watcher._score(cap, frame, it, 0.0, {})[0] > 0.85


def test_the_sweep_finds_a_size_nothing_predicted_and_keeps_it():
    """Same window, but the game's UI scale (or the camera) made everything 25 %
    bigger: nothing predicts that, so the sweep has to find it."""
    level = world()
    pic, tint = cut(level)
    big = scaled(level, 1.25)[:540, :960]
    check, cap = watcher_on(big, pic, tint)
    scores = [check() for _ in range(20)]
    assert max(scores[:10]) >= 0.8
    # a size a little off matches too: the sweep goes on until one matches well
    look = cap.scaled["t"][0]
    assert any(1.1 < f < 1.4 for f in look.found)
    assert min(check() for _ in range(5)) >= 0.9     # from now on, every check


def test_a_look_alike_in_other_colours_does_not_count():
    """A teal gem where the orange one was is the same grey: only its colours say
    it's not the same thing. The same gem in a darker scene still counts."""
    level = world()
    pic, tint = cut(level)
    other = world(sprites=((TEAL, 300, 200),))
    assert sw.match(gray(other), pic)[0] > 0.95      # grey alone can't tell
    check, _ = watcher_on(other, pic, tint)
    assert check() < 0.6
    check, _ = watcher_on((level * 0.6).astype(np.uint8), pic, tint)
    assert check() > 0.9
    check, _ = watcher_on(other, pic, None)          # no colours known: grey only
    assert check() > 0.95


def test_the_real_one_is_found_beside_a_look_alike():
    """The look-alike scoring best in grey mustn't hide the real one next to it."""
    level = world(sprites=((TEAL, 500, 100), (ORANGE, 300, 200)))
    pic, tint = cut(world())
    check, _ = watcher_on(scaled(level, 2 / 3), pic, tint)
    assert check() > 0.85


def test_nothing_goes_off_in_a_level_without_it():
    level = world(sprites=())
    pic, tint = cut(world())
    for k in (1.0, 2 / 3):
        check, _ = watcher_on(scaled(level, k), pic, tint)
        assert max(check() for _ in range(40)) < 0.7      # the sweep going all the while


def test_triggers_look_at_any_size_unless_told_not_to():
    assert Trigger.from_raw({"id": "a"}).any_size is True        # older configs too
    t = Trigger(id="a", any_size=False)
    assert Trigger.from_raw(t.to_raw()).any_size is False


# --------------------------------------------------------------------------- speed

def test_pick_takes_whole_pixels_like_indexing_each_channel():
    rng = np.random.default_rng(2)
    rows = (rng.random((50, 83 * 4 + 12)) * 255).astype(np.uint8)
    px = sw.frame_view(rows, sw.FMT_BGRA8, 83)          # a mapped frame: rows padded
    ys, xs = rng.integers(0, 50, 20), rng.integers(0, 83, 31)
    assert np.array_equal(sw.pick(px, ys, xs), px[ys[:, None], xs[None, :]])
    half = rows.view(np.uint8)[:, :80 * 4].reshape(50, 40, 8).view(np.float16)
    got = sw.pick(half, ys, xs % 40)                     # HDR frames: 8 bytes a pixel
    assert np.array_equal(got.view(np.uint16),
                          half[ys[:, None], (xs % 40)[None, :]].view(np.uint16))


def test_gray_2x_is_the_same_as_before():
    rng = np.random.default_rng(3)
    x = (rng.random((20, 30, 4)) * 255).astype(np.uint8)
    y = (x[..., 0].astype(np.uint32) * 29 + x[..., 1].astype(np.uint32) * 150
         + x[..., 2].astype(np.uint32) * 77)
    want = y.reshape(10, 2, 15, 2).sum((1, 3))              # the old sums, exactly
    assert np.array_equal(np.round(sw.gray_2x(x).astype(np.float64) * (256 * 4 * 255)), want)


class SlowGrabber:
    """A capture that takes 10 ms of the processor a grab."""

    def __init__(self, mon, w, h):
        self.w, self.h = w, h

    def grab(self):
        end = time.thread_time() + 0.01
        while time.thread_time() < end:
            pass
        return np.full((self.h, self.w), 0.5, np.float32)

    def close(self):
        pass


class WaitingGrabber(SlowGrabber):
    """One that waits 10 ms a grab (PrintWindow waiting on the game), using next to no
    processor time, and says its grab costs 1 ms elsewhere."""

    cpu_elsewhere = 0.001

    def grab(self):
        time.sleep(0.01)
        return np.full((self.h, self.w), 0.5, np.float32)


def test_checks_are_spaced_out_to_keep_to_the_processor_share(monkeypatch):
    """Checks taking 10 ms, allowed a quarter of one core: a check at most every
    40 ms, whatever the interval asks for."""
    monkeypatch.setattr(sw, "monitors", lambda: [Monitor(0, 0, 320, 180, True)])
    monkeypatch.setattr(sw, "CPU_SHARE", 0.25)
    monkeypatch.setattr(sw, "CORES", 1)
    w = sw.Watcher(lambda _t: None, grabber=SlowGrabber)
    w.interval = 0.001
    w.set_items([sw.Watched("t", [(np.eye(20, dtype=np.float32), None)], 0.8, 0.0)])
    w.start()
    try:
        time.sleep(0.5)
    finally:
        w.stop()
    assert w.gap >= 0.035


def test_waiting_for_a_grab_is_not_counted_but_its_cost_elsewhere_is(monkeypatch):
    """Grabs that wait 10 ms on the clock but cost 1 ms (elsewhere) and a little of
    the thread, allowed a quarter of one core: checks well under 40 ms apart, and
    no closer than the 4 ms the 1 ms elsewhere alone asks for."""
    monkeypatch.setattr(sw, "monitors", lambda: [Monitor(0, 0, 320, 180, True)])
    monkeypatch.setattr(sw, "CPU_SHARE", 0.25)
    monkeypatch.setattr(sw, "CORES", 1)
    w = sw.Watcher(lambda _t: None, grabber=WaitingGrabber)
    w.interval = 0.001
    w.set_items([sw.Watched("t", [(np.eye(20, dtype=np.float32), None)], 0.8, 0.0)])
    w.start()
    try:
        time.sleep(3.5)                 # the first check (setting up) falls out of PACE_S
    finally:
        w.stop()
    assert 0.004 <= w.gap < 0.03


def test_a_quick_check_keeps_the_interval():
    w = sw.Watcher(lambda _t: None)
    assert w.gap == w.interval


# --------------------------------------------------------------------------- pictures

def test_a_picture_keeps_the_size_it_was_cut_from(qapp, tmp_path):
    from PySide6.QtGui import QImage

    from onionwatch.ui import triggerspanel as tp
    img = QImage(40, 30, QImage.Format_ARGB32)
    img.fill(0xFF336699)
    assert tp.cut_size(img) is None
    tp.set_cut_size(img, (1920, 1080))
    path = tp.save_picture(img, "p", tmp_path)
    assert tp.cut_size(QImage(path)) == (1920, 1080)
    assert tp.picture_tint(QImage(path)) is not None


def test_triggers_take_turns_to_sweep():
    """Dozens of "any size" triggers whose pictures aren't showing: only SWEEPERS of
    them sweep each check (the work stays flat), and every one gets its turn."""
    level = world()
    pic, _tint = cut(level)
    h, w = 540, 960
    grab = Grab(w, h)
    items = [sw.Watched(f"t{i}", [(pic, None)], 0.8, 0.0, any_size=True, cuts=[(w, h)])
             for i in range(10)]
    cap = sw._Capture(0, Monitor(0, 0, w, h, True))
    cap.grab = grab
    cap.fitted, cap.scaled = sw.Watcher._fit(grab, cap.mon, items)
    blank = np.random.default_rng(9).random((grab.h, grab.w)).astype(np.float32)
    watcher = sw.Watcher(lambda *_a: None)
    swept = []
    for _ in range(5):
        before = dict(cap.swept)
        watcher._check(cap, blank, items)
        swept.append({k for k, v in cap.swept.items() if before.get(k) != v})
    assert all(len(s) == sw.SWEEPERS for s in swept)
    assert set().union(*swept) == {it.id for it in items}     # 5 checks x 2: all ten


def test_changed_boxes_are_the_patches_that_changed():
    rng = np.random.default_rng(3)
    a = rng.random((200, 320)).astype(np.float32)
    b = a.copy()
    b[40:70, 100:150] += 0.5
    b[150:160, 10:20] -= 0.5
    boxes = sw.changed_boxes(a, b)
    assert boxes[0][0] <= 40 and boxes[0][1] >= 70 and boxes[0][2] <= 100 and boxes[0][3] >= 150
    assert boxes[0][1] - boxes[0][0] <= 48 and boxes[0][3] - boxes[0][2] <= 72   # just about it
    assert len(boxes) == 2
    assert sw.changed_boxes(a, a) == []                 # nothing changed
    assert sw.changed_boxes(a, a + 0.5) == []           # all of it: nothing to narrow down


def test_a_thing_turning_up_at_another_size_is_found_at_once(monkeypatch):
    """A picture shows up 40 % bigger than it was cut, among nine other "any size"
    triggers. No sweep turns at all: looking at every size where the screen changed
    finds it on the check it turned up, and its size is kept."""
    monkeypatch.setattr(sw, "SWEEPERS", 0)
    level = world()
    pic, tint = cut(level)
    rng = np.random.default_rng(4)
    others = [rng.random(pic.shape).astype(np.float32) for _ in range(9)]
    h, w = 540, 960
    grab = Grab(w, h)
    items = [sw.Watched("t", [(pic, None)], 0.8, 0.0, any_size=True, cuts=[(w, h)],
                        tints=[tint])]
    items += [sw.Watched(f"o{i}", [(o, None)], 0.8, 0.0, any_size=True, cuts=[(w, h)])
              for i, o in enumerate(others)]
    cap = sw._Capture(0, Monitor(0, 0, w, h, True))
    cap.grab = grab
    cap.fitted, cap.scaled = sw.Watcher._fit(grab, cap.mon, items)
    fired = []
    watcher = sw.Watcher(lambda tid, *_a: fired.append(tid))

    def frame(rgb):
        small = scaled(rgb, grab.w / w)[:grab.h, :grab.w]
        grab.raw = (np.dstack([small[..., ::-1], np.full(small.shape[:2], 255, np.uint8)]),
                    sw.FMT_BGRA8, 1)
        return gray(small)

    empty = world(sprites=())
    shown = empty.copy()
    big = np.kron(sprite(), np.ones((1, 1, 1), np.uint8))
    big = scaled(big, 1.4)
    shown[200:200 + big.shape[0], 300:300 + big.shape[1]] = big
    for _ in range(3):
        assert watcher._check(cap, frame(empty), items)["t"] < 0.8
    assert watcher._check(cap, frame(shown), items)["t"] >= 0.8
    assert fired == ["t"]
    assert any(1.25 < f < 1.6 for f in cap.scaled["t"][0].found)
    assert not cap.hunts or all("t" not in h[2] for h in cap.hunts)


def test_a_cut_out_with_room_around_it_is_hunted_at_a_size_bigger_than_what_changed(
        monkeypatch):
    """The screen changes only where a thing's own pixels are (text: its strokes), but
    a cut-out has see-through room around them. Sizes were tried only up to a little
    bigger than the changed patch, so a word drawn 1.6 times the size was never
    tried at its size there: the room counts now (HUNT_FITS)."""
    monkeypatch.setattr(sw, "SWEEPERS", 0)
    level = world()
    s, m0 = 120, 36                                 # the sprite with 36 px all round
    piece = level[200 - m0:200 - m0 + s, 300 - m0:300 - m0 + s]
    mask = np.zeros((s, s), bool)
    mask[m0:m0 + 48, m0:m0 + 48] = True
    h, w = 540, 960
    grab = Grab(w, h)
    it = sw.Watched("t", [(gray(piece), mask)], 0.8, 0.0, any_size=True, cuts=[(w, h)])
    cap = sw._Capture(0, Monitor(0, 0, w, h, True))
    cap.grab = grab
    cap.fitted, cap.scaled = sw.Watcher._fit(grab, cap.mon, [it])
    watcher = sw.Watcher(lambda *_a: None)

    def frame(rgb):
        return gray(scaled(rgb, grab.w / w)[:grab.h, :grab.w])

    empty = world(sprites=())
    shown = empty.copy()
    big = scaled(sprite(), 1.4)
    shown[200:200 + big.shape[0], 300:300 + big.shape[1]] = big
    for _ in range(2):
        watcher._check(cap, frame(empty), [it])
    assert watcher._check(cap, frame(shown), [it])["t"] >= 0.8
    assert any(1.25 < f < 1.6 for f in cap.scaled["t"][0].found)


def test_colours_taken_at_the_matching_size_also_count():
    """A place counts when its colours agree with the picture's at full size or at
    the size it's matched at (tint_at): thin parts of a cut-out (letters' strokes)
    only agree at the latter. Here the full-size tint is made wrong on purpose."""
    level = world()
    x, y, s = 292, 192, 64
    rgb = level[y:y + s, x:x + s].copy()
    pic, tint = cut(level)
    wrong = tint[..., ::-1].copy()          # the colours the other way round
    h, w = level.shape[:2]

    def score(colours):
        grab = Grab(w, h)
        it = sw.Watched("t", [(pic, None)], 0.8, 0.0, cuts=[(w, h)], tints=[wrong],
                        colours=colours)
        cap = sw._Capture(0, Monitor(0, 0, w, h, True))
        cap.grab = grab
        cap.fitted, cap.scaled = sw.Watcher._fit(grab, cap.mon, [it])
        small = scaled(level, grab.w / w)[:grab.h, :grab.w]
        grab.raw = (np.dstack([small[..., ::-1], np.full(small.shape[:2], 255, np.uint8)]),
                    sw.FMT_BGRA8, 1)
        return sw.Watcher._score(cap, gray(small), it, 0.0, {})[0]

    assert score([]) < 0.8                  # the wrong full-size tint alone: kept down
    assert score([rgb]) >= 0.9              # its colours at the matching size agree
