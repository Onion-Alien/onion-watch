"""The watcher: the matcher finds a picture in a made-up screen whatever its
brightness and after shrinking, the gate fires once per appearance (and respects
the cooldown), and the watcher thread runs on a fake capture (the real screen is
never read). Ported from Onion Board's Triggers tests."""
import time

import numpy as np
import pytest

from onionwatch import screenwatch as sw
from onionwatch.screenwatch import Gate, Monitor, Trigger

W, H = 320, 180
SCREENS = [Monitor(0, 0, W, H, True), Monitor(W, 0, W, H)]


def scene(seed=0) -> np.ndarray:
    """A busy grey 'game screen' (blurred noise, so it has shapes, not static)."""
    rng = np.random.default_rng(seed)
    x = rng.random((H // 4, W // 4)).astype(np.float32)
    return np.kron(x, np.ones((4, 4), np.float32)) * 0.6 + 0.1


def banner() -> np.ndarray:
    """A 'YOU DIED'-ish picture: bars of text on a dark band."""
    b = np.full((24, 90), 0.05, np.float32)
    for i, x in enumerate(range(4, 86, 9)):
        b[5:19, x:x + 5] = 0.9 if i % 2 else 0.7
        b[11:13, x:x + 8] = 0.8
    return b


def with_banner(screen: np.ndarray, x=110, y=70, gain=1.0, lift=0.0) -> np.ndarray:
    s = screen.copy()
    b = banner()
    s[y:y + b.shape[0], x:x + b.shape[1]] = b * gain + lift
    return s


# --------------------------------------------------------------------------- matching

def test_match_finds_the_picture_and_where_it_is():
    score, (x, y) = sw.match(with_banner(scene(), 110, 70), banner())
    assert score > 0.99 and (x, y) == (110, 70)
    assert sw.match(scene(), banner())[0] < 0.6      # not on screen: a poor match


def test_match_ignores_brightness_and_contrast():
    """A darker or washed-out game (gamma, a flash, HDR) still matches."""
    s = with_banner(scene(), gain=0.5, lift=0.2)
    assert sw.match(s, banner())[0] > 0.99


def test_match_gives_up_on_flat_or_oversized_pictures():
    assert sw.match(scene(), np.full((20, 20), 0.5, np.float32))[0] == 0.0
    assert sw.match(scene(), np.random.default_rng(1).random((H + 1, 10)))[0] == 0.0
    blank = np.zeros((H, W), np.float32)             # a blank screen matches nothing
    assert sw.match(blank, banner())[0] == 0.0


def test_transparent_parts_of_a_picture_are_ignored():
    """A cut-out icon (transparent around it) matches whatever is behind it."""
    tmpl = np.full((40, 120), 0.0, np.float32)        # transparent parts saved as black
    b = banner()
    tmpl[8:32, 15:105] = b
    mask = np.zeros(tmpl.shape, bool)
    mask[8:32, 15:105] = True
    s = with_banner(scene(3), 110, 70)                # busy background, not black
    assert sw.match(s, tmpl)[0] < 0.9                 # the black border spoils a plain match
    score, (x, y) = sw.match(s, tmpl, mask)
    assert score > 0.99 and (x, y) == (95, 62)
    assert sw.match(scene(3), tmpl, mask)[0] < 0.6    # and it's still not everywhere


def test_a_picture_cut_at_full_size_matches_the_shrunk_screen():
    big = np.kron(with_banner(scene(), 100, 60), np.ones((4, 4), np.float32))
    tmpl = np.kron(banner(), np.ones((4, 4), np.float32))
    scale = sw.work_scale(big.shape[1], [min(tmpl.shape)])
    assert scale < 1
    small = sw.shrink(big, scale)
    assert sw.match(small, sw.shrink(tmpl, scale))[0] > 0.95


def test_work_scale_keeps_small_pictures_readable():
    assert sw.work_scale(1920, []) == pytest.approx(sw.WORK_WIDTH / 1920)
    assert sw.work_scale(1920, [80]) == pytest.approx(sw.DETAIL_SIDE / 80)
    assert sw.work_scale(400, []) == 1.0


def test_one_tiny_picture_cannot_make_every_check_full_size():
    """A 6-px picture used to mean matching the whole 4K screen at full size (over a
    second a check, for every trigger): the zoom stops at MAX_ZOOM x WORK_WIDTH."""
    cap = sw.MAX_ZOOM * sw.WORK_WIDTH
    assert sw.work_scale(3840, [6]) == pytest.approx(cap / 3840)
    assert sw.work_scale(1920, [6]) == pytest.approx(cap / 1920)
    assert sw.work_scale(cap // 2, [6]) == 1.0


def outline(h=70, w=240, stroke=3) -> tuple[np.ndarray, np.ndarray]:
    """A cut-out of outlined 'letters': thin strokes, transparent everywhere else."""
    gray = np.zeros((h, w), np.float32)
    mask = np.zeros((h, w), bool)
    for i in range(6):
        x = 8 + i * 38
        box = np.zeros((h, w), bool)
        box[10:58, x:x + 28] = True
        box[10 + stroke:58 - stroke, x + stroke:x + 28 - stroke] = False
        box[34:34 + stroke, x:x + 28] = True
        gray[box] = 1.0 if i % 2 else 0.3
        mask |= box
    return gray, mask


def test_a_cut_out_with_thin_lines_is_still_found():
    """Shrinking the mask used to keep only pixels that were wholly opaque, so 3-px
    outlines wore away to nothing and the picture could never match."""
    gray, mask = outline()
    rng = np.random.default_rng(9)
    screen = np.kron(rng.random((136, 241)).astype(np.float32),
                     np.ones((8, 8), np.float32))[:1080, :1920] * 0.6 + 0.1
    screen[500:570, 800:1040][mask] = gray[mask]
    scale = sw.work_scale(1920, [min(gray.shape)])
    m = sw.shrink_mask(mask, scale)
    assert m.sum() >= sw.MASK_MIN
    score = sw.match(sw.shrink(screen, scale), sw.shrink(gray, scale), m)[0]
    assert score > 0.8
    assert sw.match(sw.shrink(scene(), 1.0), sw.shrink(gray, scale), m)[0] < 0.6


def test_thin_text_cut_out_is_matched_sharp_at_its_own_size():
    """Small text cut out of its scenery (2-px strokes) was looked for on a half-size
    blurred copy first: its strokes smeared into something any scenery matched, so
    the place it was shown at was never checked (a real 'Level Up!' line, missed)."""
    gray, mask = outline(46, 240, stroke=2)
    assert sw.thin(mask, 0.26) and not sw.thin(np.ones((46, 240), bool), 0.26)
    assert not sw.thin(outline(46, 240, stroke=8)[1], 0.26)
    look = sw.Look(gray, mask, 0.52, [1.0], True)
    assert not look.pats[0][1].soft
    blob = np.zeros((46, 240), bool)
    blob[4:42, 10:230] = True
    assert sw.Look(gray, blob, 0.52, [1.0], True).pats[0][1].soft


def glyphs(codes, h=40) -> tuple[np.ndarray, np.ndarray]:
    """A line of blocky white 'glyphs' with a black outline, cut out: one glyph per
    code (a 5x3 bit pattern), like big game text."""
    w = len(codes) * 24 + 8
    ink = np.zeros((h, w), bool)
    for i, c in enumerate(codes):
        bits = np.array([(c >> k) & 1 for k in range(15)], bool).reshape(5, 3)
        ink[5:35, 8 + i * 24:8 + i * 24 + 18] = np.kron(bits, np.ones((6, 6), bool))
    edge = np.zeros_like(ink)
    for dy in (-2, 0, 2):
        for dx in (-2, 0, 2):
            edge |= np.roll(np.roll(ink, dy, 0), dx, 1)
    gray = np.where(ink, 1.0, 0.05).astype(np.float32)
    return gray, edge


def test_a_look_alike_with_one_glyph_different_is_told_apart():
    """'WAVE 7' scored like 'WAVE 1' (0.93-0.95 at the window's own pixels, as much
    at the working size): one glyph in six. Matched in strips on the window's own
    pixels, every strip of the thing itself is near exact, a twin's different glyph
    isn't. Other scenery behind the cut-out, or a flat cover, doesn't count."""
    word = [0b111101101101111, 0b010010010010111, 0b111001111100111,
            0b111001111001111, 0b101101111001001]
    gray, mask = glyphs(word + [0b010110010010111])
    twin = glyphs(word + [0b111001001001001])[0]
    rng = np.random.default_rng(3)
    for _ in range(4):
        area = (rng.random((gray.shape[0] + 6, gray.shape[1] + 6)) * 0.5 + 0.2
                ).astype(np.float32)
        real = area.copy()
        real[3:-3, 3:-3][mask] = gray[mask]
        assert sw.one_part_off(real, gray, mask) == 1.0
        other = area.copy()
        other[3:-3, 3:-3][mask] = twin[mask]
        assert sw.one_part_off(other, gray, mask) < 0.75
        covered = real.copy()
        covered[3:-3, 3 + 120:3 + 152] = 0.2
        assert sw.one_part_off(covered, gray, mask) == 1.0


def test_the_twin_check_runs_again_only_when_the_pixels_change(monkeypatch):
    """A thing that stays up is matched every check, and the twin check's few ms on
    each would space all the checks out (the pacing goes by what they cost): its
    answer is kept while the window's pixels there stay the same."""
    word = [0b111101101101111, 0b010010010010111, 0b111001111100111,
            0b111001111001111, 0b101101111001001]
    gray, mask = glyphs(word + [0b010110010010111])
    twin = glyphs(word + [0b111001001001001])[0]
    th, tw = gray.shape
    lk = sw.Look(gray, mask, 1.0, [1.0], False)
    rng = np.random.default_rng(4)
    scene = (rng.random((120, 240)) * 0.5 + 0.2).astype(np.float32)

    def window(pic):
        g = scene.copy()
        g[30:30 + th, 40:40 + tw][mask] = pic[mask]
        return np.repeat((g * 255).astype(np.uint8)[:, :, None], 4, axis=2)

    calls = []
    real_one = sw.one_part_off
    monkeypatch.setattr(sw, "one_part_off", lambda *a: calls.append(1) or real_one(*a))
    box, seen = (30, 30 + th, 40, 40 + tw), {}
    full = window(gray)
    assert sw.Watcher._twin(full, box, lk, full.shape[:2], seen, "t") == 1.0
    assert sw.Watcher._twin(full.copy(), box, lk, full.shape[:2], seen, "t") == 1.0
    assert len(calls) == 1
    other = window(twin)                    # the look-alike comes up in its place
    assert sw.Watcher._twin(other, box, lk, other.shape[:2], seen, "t") < 0.75
    assert sw.Watcher._twin(other, box, lk, other.shape[:2], seen, "t") < 0.75
    assert len(calls) == 2
    # another picture of the same size isn't given the first one's answer
    lk2 = sw.Look(gray.copy(), mask, 1.0, [1.0], False)
    assert sw.Watcher._twin(other, box, lk2, other.shape[:2], seen, "t") < 0.75
    assert len(calls) == 3


def test_strips_are_matched_a_pixel_off_each_way_at_once():
    rng = np.random.default_rng(6)
    for _ in range(20):
        t = rng.random((14, 9)).astype(np.float32)
        m = (rng.random((14, 9)) > 0.3).astype(np.float32)
        a = rng.random((20, 30)).astype(np.float32)
        y, x = int(rng.integers(0, 7)), int(rng.integers(0, 22))
        want = max((sw._ncc_masked(a[y + dy:y + dy + 14, x + dx:x + dx + 9], t, m)
                    for dy in (-1, 0, 1) for dx in (-1, 0, 1)
                    if y + dy >= 0 and x + dx >= 0 and y + dy + 14 <= 20 and x + dx + 9 <= 30),
                   default=-1.0)
        assert sw._ncc_shifted(a, t, m, y, x) == pytest.approx(want, abs=1e-6)


def test_a_rectangle_over_smooth_sky_is_not_matched_by_the_sky_alone():
    # a faint figure cut with a lot of sky around it: the sky's gradient alone matches
    # the plain way, but not once the light's slow changes are taken off (structure())
    ys = np.linspace(0.1, 0.9, H, dtype=np.float32)[:, None]
    sky = np.repeat(ys, W, 1) + np.linspace(0, 0.1, W, dtype=np.float32)[None, :]
    fig = np.zeros((18, 12), np.float32)
    fig[2:6, 3:9] = 0.15                    # a face
    fig[8:16, 1:11:3] = -0.15               # arms and legs
    shown = sky.copy()
    shown[80:98, 150:162] += fig
    pic = shown[40:140, 110:200].copy()
    p = sw.Pattern(pic)
    empty = sky * 0.9 + 0.03                # later, a little darker
    plain, at = sw.match(empty, pic)
    assert plain >= 0.95
    assert sw.structure(sw.Frame(empty), p, at) < 0.5
    back = empty.copy()
    back[80:98, 150:162] += fig * 0.9
    plain, at = sw.match(back, pic)
    assert at == (110, 40)
    assert sw.structure(sw.Frame(back), p, at) >= 0.9


def test_gray_2x_averages_blocks_into_luma():
    px = np.zeros((4, 4, 4), np.uint8)
    px[:2, :2, 2] = 255                              # a red block
    px[2:, 2:, :3] = 255                             # a white block
    g = sw.gray_2x(px)
    assert g.shape == (2, 2)
    assert g[0, 0] == pytest.approx(77 / 256, abs=0.01) and g[1, 1] == pytest.approx(1.0, abs=0.01)
    assert g[0, 1] == 0.0


# --------------------------------------------------------------------------- gate

def test_gate_fires_once_per_appearance():
    g = Gate()
    seq = [0.1, 0.9, 0.95, 0.9, 0.78, 0.9, 0.2, 0.9]   # 0.78: dipped, but not gone
    fired = [g.update(s, t, 0.8, 0.0) for t, s in enumerate(seq)]
    assert fired == [False, True, False, False, False, False, False, True]


def test_gate_waits_out_the_cooldown():
    g = Gate()
    assert g.update(0.9, 0.0, 0.8, 5.0)
    assert not g.update(0.1, 1.0, 0.8, 5.0)
    assert not g.update(0.9, 2.0, 0.8, 5.0)          # back too soon: ignored...
    assert not g.update(0.1, 3.0, 0.8, 5.0)
    assert g.update(0.9, 6.0, 0.8, 5.0)              # ...but fine after 5 s


def test_trigger_settings_are_checked_when_loaded():
    t = Trigger.from_raw({"id": "a", "name": 3, "delay": -1, "cooldown": "x",
                          "threshold": 5, "enabled": 1, "sound": "s1"})
    assert (t.name, t.delay, t.cooldown, t.threshold, t.enabled, t.sound) == \
        ("Trigger", 0.0, 3.0, 0.99, True, "s1")
    assert Trigger.from_raw({"name": "no id"}) is None and Trigger.from_raw("x") is None
    assert Trigger.from_raw({"id": "b", "delay": 2}).delay == 2.0


# --------------------------------------------------------------------------- watcher

class FakeGrabber:
    """Stands in for the screen: hands out the frames in `FakeGrabber.frames`."""
    frames: list = []
    made: list = []

    def __init__(self, mon, w, h):
        self.size = (w, h)
        self.closed = False
        FakeGrabber.made.append(self)

    def grab(self):
        f = FakeGrabber.frames
        return f.pop(0) if len(f) > 1 else (f[0] if f else None)

    def close(self):
        self.closed = True


@pytest.fixture
def fake_screen(monkeypatch):
    monkeypatch.setattr(sw, "monitors", lambda: [Monitor(0, 0, W, H, True)])
    monkeypatch.setattr(sw, "Grabber", FakeGrabber)
    monkeypatch.setattr(sw, "open_grabber", FakeGrabber)   # never the real screen
    monkeypatch.setattr(sw, "WORK_WIDTH", W)
    FakeGrabber.frames, FakeGrabber.made = [], []
    return FakeGrabber


def pics(*grays) -> list:
    """Watched.pictures for pictures without transparency."""
    return [(g, None) for g in grays]


def run_until(cond, timeout=5.0):
    end = time.monotonic() + timeout
    while not cond() and time.monotonic() < end:
        time.sleep(0.005)
    return cond()


def test_watcher_fires_when_the_picture_appears(fake_screen):
    plain, hit = scene(), with_banner(scene())
    fake_screen.frames = [plain, plain, hit, hit, hit, plain, plain, hit, plain]
    fired = []
    w = sw.Watcher(fired.append)
    w.interval = 0.001
    w.set_items([sw.Watched("t1", pics(banner()), 0.8, 0.0)])
    w.start()
    try:
        assert run_until(lambda: len(fake_screen.frames) == 1 and len(fired) >= 2)
    finally:
        w.stop()
    assert fired == ["t1", "t1"] and fake_screen.made[0].closed
    assert not w.running and w.scores == {}


def test_watcher_says_when_it_only_sees_black(fake_screen):
    fake_screen.frames = [np.zeros((H, W), np.float32)]
    w = sw.Watcher(lambda _t: None)
    w.interval = 0.001
    w.set_items([sw.Watched("t1", pics(banner()), 0.8, 0.0)])
    w.start()
    try:
        assert run_until(lambda: w.black)
    finally:
        w.stop()


def test_watcher_reports_a_capture_that_fails(monkeypatch):
    def broken(*_a):
        raise OSError("no screen")
    monkeypatch.setattr(sw, "monitors", lambda: [Monitor(0, 0, W, H, True)])
    w = sw.Watcher(lambda _t: None, grabber=broken)
    w.set_items([sw.Watched("t1", pics(banner()), 0.8, 0.0)])
    w.start()
    assert run_until(lambda: not w.running)
    assert w.error == "no screen"


class ModeGrabber(FakeGrabber):
    """A capture whose frames come at `source` size, like Desktop Duplication's: it
    says so, and gives out frames at whatever size the watcher asks for."""
    source = (W, H)
    resized: list = []
    lost = False

    def __init__(self, mon, w, h):
        super().__init__(mon, w, h)
        self.w, self.h = w, h

    def resize(self, w, h):
        self.w, self.h = w, h
        self.size = (w, h)
        ModeGrabber.resized.append((w, h))


def test_watcher_scales_the_pictures_to_the_screen_the_capture_really_sees(monkeypatch):
    """The monitor is listed as WxH but the frames come in at twice that (a game's
    mode, or a DPI-unaware view of the desktop): the pictures are shrunk to match
    what the frames show."""
    monkeypatch.setattr(sw, "monitors", lambda: [Monitor(0, 0, W, H, True)])
    monkeypatch.setattr(sw, "WORK_WIDTH", W)
    # the 24 px banner mustn't itself ask for more detail than the frames have
    monkeypatch.setattr(sw, "DETAIL_SIDE", 12)
    # the real screen: 2x the size, the banner at its real size (in real pixels)
    big = with_banner(np.kron(scene(), np.ones((2, 2), np.float32)), x=220, y=140)
    ModeGrabber.source, ModeGrabber.resized = (2 * W, 2 * H), []
    FakeGrabber.frames, FakeGrabber.made = [sw.shrink(big, 0.5)], []   # a (W, H) sample of it
    fired = []
    w = sw.Watcher(fired.append, grabber=ModeGrabber)
    w.interval = 0.001
    w.set_items([sw.Watched("t1", pics(banner()), 0.8, 0.0)])
    w.start()
    try:
        assert run_until(lambda: fired)
        score = w.scores["t1"]
    finally:
        w.stop()
    assert score > 0.8
    assert ModeGrabber.resized == []      # the working size didn't change, only the scale


def test_watcher_refits_when_the_screen_changes_mode(monkeypatch):
    """Mid-run the frames change size (a game went fullscreen at another
    resolution): the pictures are rescaled, nothing dies, and matching goes on."""
    monkeypatch.setattr(sw, "monitors", lambda: [Monitor(0, 0, W, H, True)])
    monkeypatch.setattr(sw, "WORK_WIDTH", W)
    ModeGrabber.source, ModeGrabber.resized = (W, H), []
    plain = scene()
    FakeGrabber.frames, FakeGrabber.made = [plain, plain, plain, plain], []
    fired = []
    w = sw.Watcher(fired.append, grabber=ModeGrabber)
    w.interval = 0.001
    w.set_items([sw.Watched("t1", pics(banner()), 0.8, 0.0)])
    w.start()
    try:
        assert run_until(lambda: "t1" in w.scores)
        # the mode switches to a smaller screen that shows the banner at its real size
        small = with_banner(scene()[:H // 2, :W // 2], x=10, y=20)
        FakeGrabber.frames = [small]
        ModeGrabber.source = (W // 2, H // 2)
        assert run_until(lambda: fired)
    finally:
        w.stop()
    assert ModeGrabber.resized == [(W // 2, H // 2)] and not w.error


def test_watcher_reopens_a_capture_that_is_lost(monkeypatch):
    """A grab that raises CaptureLost closes the grabber, says `lost`, and opens a
    new one a moment later instead of stopping."""
    monkeypatch.setattr(sw, "monitors", lambda: [Monitor(0, 0, W, H, True)])
    monkeypatch.setattr(sw, "WORK_WIDTH", W)
    monkeypatch.setattr(sw, "RETRY_S", 0.05)
    seen_lost = []

    class Losing(FakeGrabber):
        def grab(self):
            if len(FakeGrabber.made) == 1:
                raise sw.CaptureLost("gone")
            return super().grab()

    FakeGrabber.frames, FakeGrabber.made = [with_banner(scene())], []
    fired = []
    w = sw.Watcher(fired.append, grabber=Losing)
    w.interval = 0.001
    w.set_items([sw.Watched("t1", pics(banner()), 0.8, 0.0)])
    w.start()
    try:
        assert run_until(lambda: (seen_lost.append(w.lost), fired)[1])
    finally:
        w.stop()
    assert len(FakeGrabber.made) == 2 and FakeGrabber.made[0].closed
    assert any(seen_lost) and not w.error


def test_watcher_reopens_after_any_capture_error(monkeypatch):
    """A graphics driver reset makes a grab fail with some other error than
    CaptureLost: the capture is opened afresh instead of watching stopping."""
    monkeypatch.setattr(sw, "monitors", lambda: [Monitor(0, 0, W, H, True)])
    monkeypatch.setattr(sw, "WORK_WIDTH", W)
    monkeypatch.setattr(sw, "RETRY_S", 0.05)

    class Resetting(FakeGrabber):
        def grab(self):
            if len(FakeGrabber.made) == 1:
                raise OSError("AcquireNextFrame failed (0x887A0005)")
            return super().grab()

    FakeGrabber.frames, FakeGrabber.made = [with_banner(scene())], []
    fired = []
    w = sw.Watcher(fired.append, grabber=Resetting)
    w.interval = 0.001
    w.set_items([sw.Watched("t1", pics(banner()), 0.8, 0.0)])
    w.start()
    try:
        assert run_until(lambda: fired)
    finally:
        w.stop()
    assert len(FakeGrabber.made) == 2 and FakeGrabber.made[0].closed and not w.error


def test_watcher_waits_for_a_screen_that_is_gone_for_a_moment(monkeypatch):
    """After a loss the monitor list can be empty for a moment (a cable, a dock):
    that's waited out like the rest of the reopen, not the end of watching."""
    monkeypatch.setattr(sw, "WORK_WIDTH", W)
    monkeypatch.setattr(sw, "RETRY_S", 0.05)
    mons = [Monitor(0, 0, W, H, True)]
    monkeypatch.setattr(sw, "monitors", lambda: list(mons))

    class Unplugged(FakeGrabber):
        def grab(self):
            if len(FakeGrabber.made) == 1:
                mons.clear()
                raise sw.CaptureLost("gone")
            return super().grab()

    FakeGrabber.frames, FakeGrabber.made = [with_banner(scene())], []
    fired = []
    w = sw.Watcher(fired.append, grabber=Unplugged)
    w.interval = 0.001
    w.set_items([sw.Watched("t1", pics(banner()), 0.8, 0.0)])
    w.start()
    try:
        assert run_until(lambda: not mons)
        time.sleep(0.2)
        assert w.running and w.lost and not w.error
        mons.append(Monitor(0, 0, W, H, True))            # ...and it's back
        assert run_until(lambda: fired)
    finally:
        w.stop()
    assert not w.error


def test_a_gdi_fallback_tries_desktop_duplication_again(monkeypatch):
    """A lock screen longer than GIVE_UP_S leaves the capture on GDI (duplication
    can't start while it's up), which sees black in a fullscreen game: duplication
    is tried again every DUP_RETRY_S, and taken once it works."""
    monkeypatch.setattr(sw, "monitors", lambda: [Monitor(0, 0, W, H, True)])
    monkeypatch.setattr(sw, "WORK_WIDTH", W)
    monkeypatch.setattr(sw, "DUP_RETRY_S", 0.05)
    locked = [True]
    gdi: list = []

    class Gdi(FakeGrabber):
        def __init__(self, mon, w, h):
            super().__init__(mon, w, h)
            self.w, self.h = w, h
            gdi.append(self)

        def grab(self):
            return np.zeros((H, W), np.float32)      # a fullscreen game: black to GDI

    class Dup(FakeGrabber):
        def __init__(self, mon, w, h):
            if locked[0]:
                raise OSError("DuplicateOutput failed (0x887A0004)")
            super().__init__(mon, w, h)
            self.w, self.h = w, h

    monkeypatch.setattr(sw, "Grabber", Gdi)
    monkeypatch.setattr(sw, "DupGrabber", Dup)
    FakeGrabber.frames, FakeGrabber.made = [with_banner(scene())], []
    fired = []
    w = sw.Watcher(fired.append)
    w.interval = 0.001
    w.set_items([sw.Watched("t1", pics(banner()), 0.8, 0.0)])
    w.start()
    try:
        assert run_until(lambda: w.black)                # stuck on GDI, seeing black
        locked[0] = False                                # unlocked: duplication works
        assert run_until(lambda: fired)
    finally:
        w.stop()
    assert len(gdi) == 1 and gdi[0].closed and not w.error


def test_stop_then_start_during_a_slow_check_leaves_one_thread(monkeypatch):
    """stop() gives up waiting after 2 s; the old thread must still end on its own
    rather than carry on beside the new one."""
    monkeypatch.setattr(sw, "monitors", lambda: [Monitor(0, 0, W, H, True)])
    monkeypatch.setattr(sw, "WORK_WIDTH", W)
    slow = sw.threading.Event()

    class Slow(FakeGrabber):
        def grab(self):
            if len(FakeGrabber.made) == 1 and not slow.is_set():
                slow.set()
                time.sleep(2.5)                  # a hung driver call, say
            return scene()

    FakeGrabber.frames, FakeGrabber.made = [], []
    w = sw.Watcher(lambda _t: None, grabber=Slow)
    w.interval = 0.01
    w.set_items([sw.Watched("t1", pics(banner()), 0.8, 0.0)])
    w.start()
    try:
        assert slow.wait(2)
        w.stop()                                 # times out: the grab is still going
        assert not w.running
        w.start()
        assert w.running
        assert run_until(lambda: sum(t.name == "screenwatch"
                                     for t in sw.threading.enumerate()) == 1)
        assert w.running
    finally:
        w.stop()
    assert run_until(lambda: not any(t.name == "screenwatch" for t in sw.threading.enumerate()))


def capture(scaled) -> sw._Capture:
    """A screen capture as _check sees it, its pictures already shrunk."""
    cap = sw._Capture(0)
    cap.scaled = {k: [sw.Look(g, m, 1.0, [1.0], False) for g, m in v] for k, v in scaled.items()}
    return cap


def test_scores_are_replaced_whole_not_changed_in_place(fake_screen):
    """The UI thread reads and prunes `scores` while the watcher writes it."""
    w = sw.Watcher(lambda _t: None)
    items = [sw.Watched("t1", pics(banner()), 0.8, 0.0)]
    old = w.scores = {"gone": 0.5}
    new = w._check(capture({"t1": [(banner(), None)]}), with_banner(scene()), items)
    assert old == {"gone": 0.5} and new["t1"] > 0.99
    w.scores = {"t1": 0.9, "gone": 0.5}
    w.set_items(items)
    assert w.scores == {"t1": 0.9}


class FakeDup:
    """A duplication that answers AcquireNextFrame with `hr`."""

    def __init__(self, hr):
        self.hr = hr

    def __bool__(self):
        return True

    def call(self, *_a, **_k):
        return self.hr

    def release(self):
        pass


def test_a_graphics_reset_is_a_lost_capture_not_the_end():
    g = object.__new__(sw.DupGrabber)
    g.dup, g.last, g.lost = FakeDup(0x887A0005 - (1 << 32)), None, False   # DEVICE_REMOVED
    with pytest.raises(sw.CaptureLost):
        g.grab()


def test_a_duplication_that_fails_while_warming_up_is_released(monkeypatch):
    closed = []

    def failing_grab(self, timeout_ms=0):
        raise sw.CaptureLost("no frame")
    monkeypatch.setattr(sw.DupGrabber, "_open", lambda self: None)
    monkeypatch.setattr(sw.DupGrabber, "grab", failing_grab)
    monkeypatch.setattr(sw.DupGrabber, "close", lambda self: closed.append(self))
    with pytest.raises(sw.CaptureLost):
        sw.DupGrabber(Monitor(0, 0, W, H, True), W, H)
    assert len(closed) == 1


# --------------------------------------------------------------------------- the tab

def badge() -> np.ndarray:
    """A second picture the banner never matches (its negative: correlation -1)."""
    return 1 - banner()


def showing(screen: np.ndarray, pic: np.ndarray, x=110, y=70) -> np.ndarray:
    s = screen.copy()
    s[y:y + pic.shape[0], x:x + pic.shape[1]] = pic
    return s


class ScreenGrabber(FakeGrabber):
    """One capture per screen: each grab hands out what `shown` says that screen
    (by index) is showing right now."""
    shown: dict = {}

    def __init__(self, mon, w, h):
        super().__init__(mon, w, h)
        self.mon = mon

    def grab(self):
        return ScreenGrabber.shown.get(self.mon.left // W)


@pytest.fixture
def two_screens(monkeypatch):
    monkeypatch.setattr(sw, "monitors", lambda: list(SCREENS))
    monkeypatch.setattr(sw, "Grabber", ScreenGrabber)
    monkeypatch.setattr(sw, "open_grabber", ScreenGrabber)   # never the real screens
    monkeypatch.setattr(sw, "WORK_WIDTH", W)
    FakeGrabber.made, ScreenGrabber.shown = [], {}
    return ScreenGrabber


def test_each_trigger_is_looked_for_on_its_own_screen(two_screens):
    """Two triggers, one per screen: each fires only when ITS screen shows its
    picture, and each screen is captured once, not once per trigger."""
    fired = []
    w = sw.Watcher(fired.append)
    w.interval = 0.001
    w.set_items([sw.Watched("a", pics(banner()), 0.8, 0.0, source=0),
                 sw.Watched("b", pics(badge()), 0.8, 0.0, source=1)])
    # each picture on the other one's screen: nothing fires
    two_screens.shown = {0: showing(scene(), badge()), 1: showing(scene(1), banner())}
    w.start()
    try:
        assert run_until(lambda: {"a", "b"} <= w.scores.keys())
        time.sleep(0.05)
        assert fired == [] and max(w.scores.values()) < 0.6
        # ...and on their own: both fire
        two_screens.shown = {0: showing(scene(), banner()), 1: showing(scene(1), badge())}
        assert run_until(lambda: len(fired) == 2)
    finally:
        w.stop()
    assert sorted(fired) == ["a", "b"]
    assert sorted(g.mon.left for g in two_screens.made) == [0, W]
    assert all(g.closed for g in two_screens.made)


def test_a_trigger_without_a_screen_follows_the_picker(two_screens):
    """No screen of its own: the one picked at the bottom, live as it changes. A
    screen two triggers share is opened once, and only screens in use at all."""
    two_screens.shown = {0: scene(), 1: showing(scene(1), banner())}
    fired = []
    w = sw.Watcher(fired.append)
    w.interval = 0.001
    w.default = 1
    w.set_items([sw.Watched("t", pics(banner()), 0.8, 0.0),
                 sw.Watched("u", pics(badge()), 0.8, 0.0, source=1)])
    w.start()
    try:
        assert run_until(lambda: fired == ["t"])
        assert [g.mon.left for g in two_screens.made] == [W]
        w.set_default(0)                     # the picker moves: the banner isn't there
        assert run_until(lambda: [g.mon.left for g in two_screens.made] == [W, 0])
        assert run_until(lambda: w.scores.get("t", 1.0) < 0.6)
        assert fired == ["t"] and not two_screens.made[0].closed   # "u" still needs it
    finally:
        w.stop()


def test_a_trigger_screen_is_remembered_and_checked_when_loaded():
    assert Trigger.from_raw({"id": "a", "monitor": 1}).monitor == 1
    for bad in (None, "1", True, -1, 1.5, sw.MAX_SCREENS):
        assert Trigger.from_raw({"id": "a", "monitor": bad}).monitor is None
    assert Trigger.from_raw({"id": "a"}).monitor is None          # an older config
    raw = Trigger(id="a", sources=[1]).to_raw()
    assert raw["monitor"] == 1 and Trigger.from_raw(raw).monitor == 1


def test_a_screen_that_is_not_there_falls_back_to_the_picker(fake_screen):
    fake_screen.frames = [with_banner(scene())]
    fired = []
    w = sw.Watcher(fired.append)
    w.interval = 0.001
    w.set_items([sw.Watched("t", pics(banner()), 0.8, 0.0, source=3)])
    w.start()
    try:
        assert run_until(lambda: fired)
        assert w.fell_back == {"t"} and len(fake_screen.made) == 1
    finally:
        w.stop()
    assert w.fell_back == frozenset()


def test_a_screen_that_cannot_be_captured_does_not_stop_the_other(two_screens, monkeypatch):
    monkeypatch.setattr(sw, "RETRY_S", 0.02)
    monkeypatch.setattr(sw, "GIVE_UP_S", 0.1)
    tried = []

    def opener(mon, w, h, tries=1):
        if mon.left:
            tried.append(time.monotonic())
            raise OSError("no second screen")
        return two_screens(mon, w, h)

    two_screens.shown = {0: showing(scene(), banner())}
    fired = []
    w = sw.Watcher(fired.append, grabber=opener)
    w.interval = 0.001
    w.set_items([sw.Watched("a", pics(banner()), 0.8, 0.0, source=0),
                 sw.Watched("b", pics(badge()), 0.8, 0.0, source=1)])
    w.start()
    try:
        assert run_until(lambda: fired == ["a"])
        assert run_until(lambda: w.failed == {1: "no second screen"})
        assert w.running and not w.error and "b" not in w.scores
    finally:
        w.stop()
    assert len(tried) >= 2 and w.failed == {}


def stripes() -> np.ndarray:
    """A third picture, unlike the banner and the badge (blocks of noise)."""
    rng = np.random.default_rng(5)
    return np.kron(rng.random((6, 22)).astype(np.float32), np.ones((4, 4), np.float32))


def test_a_trigger_with_several_pictures_fires_when_any_of_them_shows(fake_screen):
    """Three pictures on one trigger: the second one showing up fires it, and its
    live score is the best of its pictures (the one that's there)."""
    plain = scene()
    fake_screen.frames = [plain, plain, showing(plain, badge()), showing(plain, badge()), plain]
    fired = []
    w = sw.Watcher(fired.append)
    w.interval = 0.001
    w.set_items([sw.Watched("t", pics(banner(), badge(), stripes()), 0.8, 0.0)])
    w.start()
    try:
        assert run_until(lambda: fired)
        assert w.scores["t"] > 0.99
        assert run_until(lambda: len(fake_screen.frames) == 1 and w.scores["t"] < 0.6)
    finally:
        w.stop()
    assert fired == ["t"]


def test_the_live_score_is_the_best_of_the_pictures():
    w = sw.Watcher(lambda _t: None)
    frame = showing(scene(), badge())
    scaled = {"both": [(banner(), None), (badge(), None)], "one": [(banner(), None)]}
    items = [sw.Watched("both", pics(banner(), badge()), 0.8, 0.0),
             sw.Watched("one", pics(banner()), 0.8, 0.0)]
    scores = w._check(capture(scaled), frame, items)
    assert scores["both"] > 0.99 and scores["one"] < 0.6
    assert w._check(capture({}), frame, items)["both"] == 0.0     # no pictures fitted yet


def test_a_hundred_pictures_are_shrunk_once_not_every_tick(fake_screen, monkeypatch):
    """The pictures are scaled in _fit (on a change) and reused by every _check."""
    fits = []
    real_fit = sw.Watcher._fit
    monkeypatch.setattr(sw.Watcher, "_fit", staticmethod(
        lambda *a: (fits.append(1), real_fit(*a))[1]))
    fake_screen.frames = [scene()]
    w = sw.Watcher(lambda _t: None)
    w.interval = 0.001
    w.set_items([sw.Watched("t", pics(*[banner()] * 100), 0.8, 0.0)])
    w.start()
    try:
        assert run_until(lambda: "t" in w.scores)
        time.sleep(0.1)
    finally:
        w.stop()
    assert fits == [1]


def test_old_and_odd_trigger_configs_load_their_pictures_and_sounds():
    old = Trigger.from_raw({"id": "a", "image": "p.png", "sound": "s1"})
    assert old.images == ["p.png"] and old.sounds == ["s1"] and old.pick == "random"
    assert old.image == "p.png" and old.sound == "s1"
    raw = old.to_raw()
    assert raw["image"] == "p.png" and raw["images"] == ["p.png"] and raw["sound"] == "s1"
    assert Trigger.from_raw(raw).images == ["p.png"]
    both = Trigger.from_raw({"id": "a", "image": "a.png", "images": ["a.png", "b.png"],
                             "sounds": ["s1", "s1", "", 3, "s2"], "pick": "order"})
    assert both.images == ["a.png", "b.png"] and both.sounds == ["s1", "s2"]
    assert both.pick == "order"
    odd = Trigger.from_raw({"id": "a", "images": "x.png", "sounds": 5, "pick": "weird"})
    assert odd.images == ["x.png"] and odd.sounds == [] and odd.pick == "random"
    assert Trigger.from_raw({"id": "a", "images": None}).images == []
    assert Trigger(id="a").to_raw()["image"] == ""


def test_watching_outlasts_a_long_screen_loss(monkeypatch):
    """A monitor asleep overnight or a dock unplugged: once watching has worked it
    keeps trying, past GIVE_UP_S, and fires again when the screen is back."""
    monkeypatch.setattr(sw, "RETRY_S", 0.01)
    monkeypatch.setattr(sw, "GIVE_UP_S", 0.05)
    mons = [Monitor(0, 0, W, H, True)]
    monkeypatch.setattr(sw, "monitors", lambda: list(mons))
    state = {"gone": False}

    class Flaky:
        def __init__(self, mon, w, h, tries=1):
            if state["gone"]:
                raise OSError("screen gone")
            self.source = (w, h)

        def grab(self):
            if state["gone"]:
                raise OSError("lost")
            return with_banner(scene())

        def close(self):
            pass

    fired = []
    w = sw.Watcher(fired.append, grabber=Flaky)
    w.interval = 0.001
    w.set_items([sw.Watched("t", pics(banner()), 0.8, 0.0)])
    w.start()
    try:
        assert run_until(lambda: fired)
        state["gone"] = True
        mons.clear()                                  # the monitor went to sleep
        time.sleep(0.4)                               # many times GIVE_UP_S
        assert w.running and not w.error
        n = len(fired)
        mons.append(Monitor(0, 0, W, H, True))
        state["gone"] = False
        assert run_until(lambda: len(fired) > n or (w.scores.get("t", 0) > 0.99))
        assert w.running and not w.error
    finally:
        w.stop()


def test_one_bad_check_does_not_end_watching(fake_screen, monkeypatch):
    fake_screen.frames = [with_banner(scene())]
    real = sw.Watcher._tick
    calls = {"n": 0}

    def tick(self, cap, items):
        calls["n"] += 1
        if calls["n"] == 2:
            raise ValueError("an odd frame")
        return real(self, cap, items)

    monkeypatch.setattr(sw.Watcher, "_tick", tick)
    w = sw.Watcher(lambda _t: None)
    w.interval = 0.001
    w.set_items([sw.Watched("t", pics(banner()), 0.8, 0.0)])
    w.start()
    try:
        assert run_until(lambda: calls["n"] > 5)
        assert w.running and not w.error
    finally:
        w.stop()


def test_processor_use_sets_how_far_apart_checks_are(fake_screen, monkeypatch):
    """A check costing 20 ms of the processor, of four cores: at 1 % they're 0.5 s
    apart, at 5 % 0.1 s, and with no limit as often as `interval` asks."""
    monkeypatch.setattr(sw, "CORES", 4)
    fake_screen.frames = [scene()]
    real = FakeGrabber.grab

    def slow(self):
        end = time.thread_time() + 0.02
        while time.thread_time() < end:
            pass
        return real(self)
    monkeypatch.setattr(FakeGrabber, "grab", slow)
    gaps = {}
    for share in (0.01, 0.05, 0.0):
        w = sw.Watcher(lambda *_a: None)
        w.interval = 0.01
        w.cpu_share = share
        w.set_items([sw.Watched("t", pics(banner()), 0.8, 0.0)])
        w.start()
        try:
            assert run_until(lambda w=w: "t" in w.scores)
            time.sleep(0.9)
            gaps[share] = w.gap
        finally:
            w.stop()
    assert 0.3 < gaps[0.01] < 1.5
    assert gaps[0.05] == pytest.approx(gaps[0.01] / 5, rel=0.6)
    assert gaps[0.0] == w.interval


def test_the_processor_watching_uses_is_measured(fake_screen, monkeypatch):
    """Watcher.cpu_used: its own thread's time over CPU_MEASURE_S, as a share of the
    whole processor (a check that only sleeps uses next to none)."""
    monkeypatch.setattr(sw, "CPU_MEASURE_S", 0.2)
    fake_screen.frames = [scene()]
    w = sw.Watcher(lambda *_a: None)
    w.interval = 0.01
    w.set_items([sw.Watched("t", pics(banner()), 0.8, 0.0)])
    assert w.cpu_used is None
    w.start()
    try:
        assert run_until(lambda: w.cpu_used is not None)
    finally:
        w.stop()
    assert 0.0 <= w.cpu_used <= 1.0


def test_a_rectangle_turning_up_on_other_scenery_keeps_its_structure():
    """structure() takes each place's light from its own pixels, as it does the
    picture's: the scenery around where a thing turned up (other than where it was
    cut) mustn't count. A HUD panel cut over a bright sky, shown over dark rocks,
    scored 0.58 instead of 1.0."""
    rng = np.random.default_rng(11)
    panel = np.kron(rng.random((6, 10)), np.ones((6, 6))).astype(np.float32) * 0.5 + 0.25
    bright = np.full((H, W), 0.95, np.float32)
    dark = (rng.random((H, W)) * 0.1).astype(np.float32)
    for back in (bright, dark):
        back[60:96, 100:160] = panel
    p = sw.Pattern(bright[60:96, 100:160].copy())
    assert sw.structure(sw.Frame(bright), p, (100, 60)) >= 0.95
    assert sw.structure(sw.Frame(dark), p, (100, 60)) >= 0.95


def test_max_detection_lifts_the_processor_cap(fake_screen, monkeypatch):
    """"always": checks as often as `interval` asks whatever the share, with the
    bigger sweep and hunt budgets; "off" keeps to the share."""
    monkeypatch.setattr(sw, "CORES", 4)
    fake_screen.frames = [scene()]
    real = FakeGrabber.grab

    def slow(self):
        end = time.thread_time() + 0.02
        while time.thread_time() < end:
            pass
        return real(self)
    monkeypatch.setattr(FakeGrabber, "grab", slow)
    for how in ("off", "always"):
        w = sw.Watcher(lambda *_a: None)
        w.interval = 0.01
        w.cpu_share = 0.01
        w.max_detect = how
        w.set_items([sw.Watched("t", pics(banner()), 0.8, 0.0)])
        w.start()
        try:
            assert run_until(lambda w=w: "t" in w.scores)
            time.sleep(0.6)
            if how == "off":
                assert not w.heavy and w.gap > 0.3
            else:
                assert w.heavy and w.gap == w.interval
                assert w._sweeps is not None and w._sweeps[0] <= sw.MAX_SWEEPERS
        finally:
            w.stop()


@pytest.mark.parametrize("front, fills, heavy", [
    (0, False, False),          # the window in front can't be told: you may be playing
    (7, True, False),           # a fullscreen window covers the watched screen
    (7, False, True),           # something else in front, not filling it: away
])
def test_max_detection_while_away_from_a_watched_screen(fake_screen, front, fills, heavy):
    fake_screen.frames = [scene()]
    seen = []

    def filled(hwnd, mon):
        seen.append((hwnd, mon))
        return fills
    w = sw.Watcher(lambda *_a: None, front=lambda: front, fills=filled)
    w.interval = 0.01
    w.max_detect = "away"
    w.set_items([sw.Watched("t", pics(banner()), 0.8, 0.0)])
    w.start()
    try:
        assert run_until(lambda: "t" in w.scores)
        time.sleep(0.1)
        assert w.heavy == heavy
        assert all(h == front and m.width == W for h, m in seen)
    finally:
        w.stop()



def test_an_exact_shrink_takes_each_pixel_its_share_of_the_old_ones():
    # each new pixel is the mean of what it covers, parts of old pixels included:
    # whole-pixel bins would take one old pixel here and two there
    rng = np.random.default_rng(1)
    img = rng.random((20, 50)).astype(np.float32)

    def overlap(n, size):           # weights[new, old]: how much of `old` each covers
        e = np.linspace(0, size, n + 1)
        k = np.arange(size)
        return np.clip(np.minimum(e[1:, None], k + 1) - np.maximum(e[:-1, None], k), 0, None)
    want_y, want_x = overlap(18, 20), overlap(45, 50)
    want = (want_y @ img @ want_x.T) / np.outer(want_y.sum(1), want_x.sum(1))
    got = sw.shrink(img, 0.9, exact=True)
    assert got.shape == (18, 45)
    assert np.allclose(got, want, atol=1e-5)
    assert not np.allclose(sw.shrink(img, 0.9, exact=False), want, atol=1e-2)
    assert sw.SHRINK_EXACT & 1       # the frame's own second shrink uses it
