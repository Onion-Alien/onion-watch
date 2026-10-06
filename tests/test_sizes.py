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


def test_a_size_matching_only_between_the_sweeps_steps_is_found():
    """Text drawn afresh at another size can match only within a pixel or so of it
    (WAVE 12 at 85 %: 0.86 there, 0.73 3 % either side). Halfway between sweep steps
    isn't close enough: the sweep tries finer about its best before giving up."""
    pic, _tint = cut(world())
    lk = sw.Look(pic, None, 0.5, [1.0], True)
    sizes = {}
    made = lk.pattern

    def pattern(f):
        p = made(f)
        sizes[id(p)] = f
        return p

    lk.pattern = pattern
    right = 0.853

    def judge(p, _lk, *_a):
        return 0.86 - 10 * abs(np.log(sizes[id(p)] / right)), (0, 10, 0, 10)

    it = sw.Watched("t", [(pic, None)], 0.8, 0.0, any_size=True)
    cap = sw._Capture(0, Monitor(0, 0, 960, 540, True))
    best = max(sw.Watcher._sweep(cap, it, [lk], judge, lambda _lk: (540, 960))[0]
               for _ in range(len(sw.SWEEP)))
    assert best >= 0.8
    assert any(abs(f / right - 1) < 0.01 for f in lk.found)



def test_a_size_found_finely_counts_only_with_the_things_shape_at_full_size():
    """Scenery can fit one of the finely tried sizes just well enough at the working
    size: there the picture is matched again on the screen's own pixels, its light's
    slow changes taken off. The thing keeps its shape; grass at the same size doesn't."""
    pic, _tint = cut(world())
    lk = sw.Look(pic, None, 0.5, [1.0], True)
    k = 0.85
    big = gray(scaled(world(), k))
    full = (lambda y0, y1, x0, x1: big[y0:y1, x0:x1]), big.shape
    shape = (big.shape[0] // 2, big.shape[1] // 2)
    s = round(64 * k / 2)
    y, x = round(192 * k / 2), round(292 * k / 2)
    assert sw.Watcher._fine_shape(full, (y, y + s, x, x + s), lk, shape) >= sw.FINE_SHAPE
    for gy, gx in ((20, 30), (100, 300), (170, 200), (60, 400)):
        assert sw.Watcher._fine_shape(full, (gy, gy + s, gx, gx + s), lk, shape) < 0.3
    # without the full-size pixels a size found finely doesn't count
    assert sw.Watcher._fine_shape(None, (y, y + s, x, x + s), lk, shape) == 0.0

def test_a_picture_partly_covered_by_a_flat_thing_still_counts(monkeypatch):
    """A window or a dark box over a corner of the thing: those pixels are flat on
    the screen and nothing like the picture, so they're left out (cover_score) and
    the rest decides, colours included. Scenery with a flat patch doesn't count,
    nor does the thing under something that isn't flat."""
    level = world(sprites=())
    level[200:296, 300:396] = sprite(cell=16)        # a big one, as covers go
    pic, tint = cut(level, s=112)
    covered = level.copy()
    covered[250:330, 344:430] = (40, 40, 40)          # a dark box over a corner of it
    full = np.dstack([covered[..., ::-1], np.full(covered.shape[:2], 255, np.uint8)])
    check, cap = watcher_on(covered, pic, tint, any_size=False)
    cap.grab.full = full
    monkeypatch.setattr(sw, "COVER_ON", False)
    assert check() < 0.8
    monkeypatch.setattr(sw, "COVER_ON", True)
    cap.cover_left = 1                               # _check sets it each check
    assert check() >= 0.9
    # the same box over grass where the gem isn't, and noise over the gem: no
    rng = np.random.default_rng(3)
    for y, x, fill in ((60, 600, (40, 40, 40)), (262, 352, None)):
        other = (world(sprites=()) if fill is not None else level).copy()
        other[y:y + 68, x:x + 78] = (fill if fill is not None
                                     else (rng.random((68, 78, 3)) * 255).astype(np.uint8))
        check, cap = watcher_on(other, pic, tint, any_size=False)
        cap.grab.full = np.dstack([other[..., ::-1], np.full(other.shape[:2], 255, np.uint8)])
        cap.cover_left = 1
        assert check() < 0.8
    # pixels flat on the screen where the picture has detail are left out; not the rest
    sc, share = sw.cover_score(gray(covered)[188:308, 288:408], pic, None)
    assert sc > 0.97 and 0.1 < share < 0.4


def test_a_small_match_counts_only_with_the_things_shape_at_full_size():
    """A small picture that is mostly flat, with one busy corner, matches any dark
    place with something bright in that corner at the working size. At full size the
    corner's shape tells them apart, even when the size found is a few % off."""
    rng = np.random.default_rng(3)
    pic = np.full((24, 44), 0.08, np.float32) + rng.normal(0, 0.01, (24, 44)).astype(np.float32)
    pic[14:22, 2:10] = np.indices((8, 8)).sum(0) % 2 * 0.8 + 0.1      # a checker patch
    lk = sw.Look(pic, None, 0.375, [1.0], True)
    screen = (np.full((720, 1280), 0.08, np.float32)
              + rng.normal(0, 0.01, (720, 1280)).astype(np.float32))
    real = sw.resize(pic, 0.9)
    rh, rw = real.shape
    screen[300:300 + rh, 500:500 + rw] = real
    screen[114:122, 802:810] = 0.85                                   # a bright square
    full = (lambda y0, y1, x0, x1: screen[y0:y1, x0:x1]), screen.shape
    shape = (270, 480)
    k = 0.375
    # the sweep's size is coarser than 0.9: the real one found at 0.94 of its size
    s = (round(24 * 0.94 * k), round(44 * 0.94 * k))
    box = (round(300 * k), round(300 * k) + s[0], round(500 * k), round(500 * k) + s[1])
    assert sw.Watcher._small_shape(full, box, lk, shape) >= sw.SMALL_SHAPE
    decoy = (round(100 * k), round(100 * k) + s[0], round(800 * k), round(800 * k) + s[1])
    assert sw.Watcher._small_shape(full, decoy, lk, shape) < sw.SMALL_SHAPE
    # kept per place and size: the same pixels aren't worked out again
    seen: dict = {}
    a = sw.Watcher._small_shape(full, box, lk, shape, seen, "t")
    assert len(seen) == 1 and sw.Watcher._small_shape(full, box, lk, shape, seen, "t") == a


def test_a_cut_outs_shape_is_judged_on_its_own_pixels():
    """A cut-out turned up on other scenery: what shows around it isn't the picture's,
    so only its opaque part is compared."""
    rng = np.random.default_rng(4)
    yy, xx = np.indices((40, 40))
    mask = (yy - 20) ** 2 + (xx - 20) ** 2 < 15 ** 2
    thing = (np.sin(xx / 2.0) * np.cos(yy / 3.0) * 0.3 + 0.5).astype(np.float32)
    scenery = rng.random((44, 44)).astype(np.float32)
    area = scenery.copy()
    area[2:42, 2:42] = np.where(mask, thing, area[2:42, 2:42])
    assert sw.cut_structure(area, thing, mask, (2, 2)) > 0.95
    other = rng.random((44, 44)).astype(np.float32)
    assert sw.cut_structure(other, thing, mask, (2, 2)) < 0.3


def test_a_cut_out_found_well_under_its_size_must_keep_more_of_its_shape():
    """Shrunk well under the size it was cut at, a cut-out is a smooth blob that
    scenery fits: it has to keep CUT_LOW_SHAPE at full size, however big it is on the
    frame. A rectangle, or a cut-out near its size, is checked as before."""
    yy, xx = np.indices((120, 160))
    mask = (yy - 60) ** 2 / 50 ** 2 + (xx - 80) ** 2 / 70 ** 2 < 1
    gray = (np.sin(xx / 5) * np.cos(yy / 7) * 0.3 + 0.5).astype(np.float32)
    cut = sw.Look(gray, mask, 0.375, [1.0], True)
    box = sw.Look(gray, None, 0.375, [1.0], True)
    low = cut.pattern(0.6)
    assert low.size[0] * low.size[1] >= sw.SMALL_AREA       # not a small match
    assert sw.Watcher._shape_bar(low, cut) == sw.CUT_LOW_SHAPE
    assert sw.Watcher._shape_bar(cut.pattern(1.0), cut) is None
    assert sw.Watcher._shape_bar(box.pattern(0.6), box) is None
    small = sw.Look(gray[:40, :50], None, 0.375, [1.0], True)
    assert sw.Watcher._shape_bar(small.pattern(1.0), small) == sw.SMALL_SHAPE


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
    monkeypatch.setattr(sw, "PACE_S", 0.6)   # dozens of checks still fit in the window
    w = sw.Watcher(lambda _t: None, grabber=WaitingGrabber)
    w.interval = 0.001
    w.set_items([sw.Watched("t", [(np.eye(20, dtype=np.float32), None)], 0.8, 0.0)])
    w.start()
    try:
        time.sleep(1.0)                 # the first check (setting up) falls out of PACE_S
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


def test_a_big_changed_patch_is_hunted_over_several_checks_nearest_sizes_first(monkeypatch):
    """A size looked for about a patch costs by the area it's looked in: about a big
    patch (a moving game) that's the whole frame, so a check's budget covers only a few
    sizes there, the ones nearest the picture's own first, and the rest wait for the
    next checks. A small patch still has all its sizes looked for at once."""
    from types import SimpleNamespace

    monkeypatch.setattr(sw, "HUNT_PER_CHECK", round(len(sw.HUNT_SIZES) / sw.HUNT_SMALL / 2))
    tried = []
    lk = SimpleNamespace(gray=np.zeros((40, 40), np.float32), scale=1.0, ratio=1.0, pats=[],
                         hunt_sizes=sw.HUNT_SIZES, lo=sw.SIZES[0], hi=sw.SIZES[1],
                         hunt_pattern=lambda g: SimpleNamespace(ok=True),
                         keep=lambda *_a: None)
    it = SimpleNamespace(id="t", threshold=0.8)

    def judge(_p, _lk, _area, _fine=False):
        return 0.0, None

    def hunt(box, budget):
        cap = SimpleNamespace(last=(np.zeros((300, 400), np.float32), None),
                              hunts=[[box, 0, ["t"], {}]])
        before = len(tried)
        sw.Watcher._hunt(cap, it, [lk], lambda p, lk_, a, f=False: (
            tried.append(p) or judge(p, lk_, a, f)), 0.0, budget)
        return cap.hunts[0], len(tried) - before

    whole = sw.HUNT_SIZES
    h, n = hunt((0, 300, 0, 400), [sw.HUNT_PER_CHECK])
    assert 0 < n < len(whole) and "t" in h[2] and h[3]["t"] == n
    budget = [sw.HUNT_PER_CHECK]
    cap = SimpleNamespace(last=(np.zeros((300, 400), np.float32), None), hunts=[h])
    sizes = []
    lk.hunt_pattern = lambda g: sizes.append(g) or SimpleNamespace(ok=True)
    sw.Watcher._hunt(cap, it, [lk], judge, 0.0, budget)
    assert sizes and len(sizes) == min(n, len(whole) - n)   # the next ones
    assert all(abs(np.log(a)) <= abs(np.log(b)) + 1e-9 for a, b in zip(sizes, sizes[1:]))
    assert min(abs(np.log(f)) for f in sizes) >= max(
        abs(np.log(f)) for f in sorted(whole, key=lambda f: abs(np.log(f)))[:n]) - 1e-9
    if 2 * n >= len(whole):
        assert "t" not in h[2]                             # all looked for: done there
    h, n = hunt((100, 140, 150, 200), [sw.HUNT_PER_CHECK])   # small: all at once
    assert "t" not in h[2] and n == len(whole)


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


def panel(fill=(150, 30, 30), w=160, h=96) -> np.ndarray:
    """A popup (RGB uint8): a panel in one colour, a light rim and a few white marks
    (its writing)."""
    p = np.empty((h, w, 3), np.float32)
    p[:] = np.array(fill, np.float32) * np.linspace(0.7, 1.1, h)[:, None, None]
    p[:2], p[-2:], p[:, :2], p[:, -2:] = 230, 230, 230, 230
    rng = np.random.default_rng(7)
    for _ in range(9):
        x, y = rng.integers(20, w - 30), rng.integers(30, h - 50)
        p[y:y + 18, x:x + 4] = 255
        p[y:y + 4, x:x + 14] = 255
    return np.clip(p, 0, 255).astype(np.uint8)


def test_a_dark_box_over_a_coloured_popup_is_told_by_its_colour(monkeypatch):
    """A dark grey box over a corner of a dark red popup is the popup's grey: grey
    can't tell where it is (cover_score), so the colours fail and it's missed. By
    colour it's plain (colour_cover): the rest of the popup decides. A popup in other
    colours with the same box still doesn't count, nor one with noise over it."""
    level = world(sprites=())
    level[200:296, 300:460] = panel()
    piece = level[192:304, 292:468].copy()
    pic, tint = gray(piece), sw.tint(piece.astype(np.float32) / 255)

    def watch(rgb):
        h, w = rgb.shape[:2]
        grab = Grab(w, h)
        it = sw.Watched("t", [(pic, None)], 0.8, 0.0, any_size=False, cuts=[(960, 540)],
                        tints=[tint], colours=[piece])
        cap = sw._Capture(0, Monitor(0, 0, w, h, True))
        cap.grab = grab
        cap.fitted, cap.scaled = sw.Watcher._fit(grab, cap.mon, [it])
        small = scaled(rgb, grab.w / w)[:grab.h, :grab.w]
        grab.raw = (np.dstack([small[..., ::-1], np.full(small.shape[:2], 255, np.uint8)]),
                    sw.FMT_BGRA8, 1)
        grab.full = np.dstack([rgb[..., ::-1], np.full(rgb.shape[:2], 255, np.uint8)])
        frame = gray(small)

        def check(tries=1):
            cap.cover_left, cap.fresh_left, cap.colour_left = tries, 0, tries
            return sw.Watcher._score(cap, frame, it, 0.0, {})[0]
        return check, cap

    covered = level.copy()
    covered[260:300, 400:464] = (48, 52, 60)        # a dark grey box over a corner
    monkeypatch.setattr(sw, "COLOUR_COVER", False)
    check, _cap = watch(covered)
    assert check() < 0.8
    monkeypatch.setattr(sw, "COLOUR_COVER", True)
    check, _cap = watch(covered)
    assert check() >= 0.9
    assert check(tries=0) >= 0.9        # worked out once while its pixels stay the same
    other = level.copy()
    other[200:296, 300:460] = panel(fill=(20, 80, 90))   # the same grey, other colours
    other[260:300, 400:464] = (48, 52, 60)
    check, _cap = watch(other)
    assert check() < 0.8
    noisy = level.copy()
    rng = np.random.default_rng(3)
    noisy[260:300, 400:464] = (rng.random((40, 64, 3)) * 255).astype(np.uint8)
    check, _cap = watch(noisy)
    assert check() < 0.8



def test_a_cover_is_tried_at_once_where_something_just_appeared(monkeypatch):
    """The tries at a covered place are few a check (COVER_PER_CHECK), and scenery
    near other triggers can take them all; a place where the frame just changed (a
    hunt's patch: something was shown) has tries of its own (COVER_FRESH). Each answer
    is kept while the place's pixels stay the same, at no cost."""
    level = world(sprites=())
    level[200:296, 300:396] = sprite(cell=16)
    pic, tint = cut(level, s=112)
    covered = level.copy()
    covered[250:330, 344:430] = (40, 40, 40)
    check, cap = watcher_on(covered, pic, tint, any_size=False)
    cap.grab.full = np.dstack([covered[..., ::-1], np.full(covered.shape[:2], 255, np.uint8)])
    cap.cover_left, cap.fresh_left = 0, 1               # the others took this check's
    assert check() < 0.8
    fy, fx = cap.grab.h / 540, cap.grab.w / 960
    cap.hunts.append([(round(250 * fy), round(330 * fy), round(344 * fx), round(430 * fx)),
                      cap.checks, ["t"], {}])
    assert check() >= 0.9
    assert cap.fresh_left == 0
    cap.hunts.clear()
    assert check() >= 0.9                               # kept: the same pixels
