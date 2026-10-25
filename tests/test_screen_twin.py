"""The look-alike ("twin") check on screen captures. A window grabber keeps the whole
window at full size from its grab (`full`); a screen grabber can't afford that every
check, so it gives just the box asked for (full_gray): GDI copies it off the screen,
Desktop Duplication reads it again from the frame it already copied, turned upright
on a rotated monitor. No screen is captured: the frames are made up."""
import ctypes

import numpy as np
import pytest

from onionwatch.engine import screenwatch as sw
from onionwatch.engine.imgops import gaussian_filter
from onionwatch.engine.screenwatch import Monitor
from test_screenwatch import glyphs


@pytest.mark.parametrize("turns", [0, 1, 2, 3, -1, 4])
def test_a_box_in_the_upright_picture_is_found_in_the_frame_as_it_comes(turns):
    rng = np.random.default_rng(1)
    frame = rng.random((9, 14)).astype(np.float32)
    up = sw.upright(frame, turns)
    for box in [(0, 2, 0, 3), (1, 5, 2, 7), (up.shape[0] - 3, up.shape[0], 0, up.shape[1])]:
        y0, y1, x0, x1 = box
        fy0, fy1, fx0, fx1 = sw.frame_box(box, turns, frame.shape)
        assert np.array_equal(sw.upright(frame[fy0:fy1, fx0:fx1], turns), up[y0:y1, x0:x1])


class FakeCom:
    def __init__(self, handler=None):
        self.handler = handler
        self.p = ctypes.c_void_p(1)

    def release(self):
        pass

    def call(self, slot, *args, **kw):
        return (self.handler(slot, args) if self.handler else None) or 0


def staged(px: np.ndarray, turns: int, fmt: int = sw.FMT_BGRA8):
    """A DupGrabber whose staging texture holds `px` ((h, w, 4) in the format's own
    type: the frame as it comes, rows padded as a mapped texture's are) on a monitor
    turned `turns`."""
    fh, fw = px.shape[:2]
    row = px.reshape(fh, -1).view(np.uint8)
    pitch = row.shape[1] + 64
    buf = (ctypes.c_uint8 * (fh * pitch))()
    rows = np.frombuffer(buf, np.uint8).reshape(fh, pitch)
    rows[:, :row.shape[1]] = row
    maps = []

    def ctx(slot, args):
        if slot == sw.DupGrabber.CTX_MAP:
            m = args[4]._obj
            m.pData, m.RowPitch = ctypes.addressof(buf), pitch
            maps.append(1)
        elif slot == sw.DupGrabber.CTX_UNMAP:
            maps.pop()

    g = object.__new__(sw.DupGrabber)
    g.ctx, g.staging = FakeCom(ctx), FakeCom()
    g.turns = turns
    g._mode = (fw, fh, fmt)
    g._frame = (fw, fh)
    g.source = (fh, fw) if turns % 2 else (fw, fh)
    g.last = np.zeros((2, 2), np.float32)
    g.fresh = True                  # the staging texture holds that frame
    return g, buf, maps


@pytest.mark.parametrize("turns", [0, -1, 2, 1])
def test_duplication_reads_the_box_from_the_frame_it_gave_out(turns):
    rng = np.random.default_rng(2)
    frame = rng.integers(0, 256, (60, 90, 4), dtype=np.uint8)
    g, _buf, maps = staged(frame, turns)
    want = sw.upright(sw.to_gray(frame), turns)
    box = (5, 25, 7, 40)
    got = g.full_gray(*box)
    assert got is not None and maps == []           # unmapped again
    assert np.allclose(got, want[5:25, 7:40], atol=1e-6)
    assert g.full_gray(0, 1, 0, 30) is None         # too thin to be any use
    sw_, sh_ = g.source
    assert g.full_gray(0, sh_ + 5, 0, 10) is None   # off the frame
    g.fresh = False                                 # no frame copied in yet
    assert g.full_gray(*box) is None


def test_duplication_reads_an_hdr_frame_as_the_same_grey():
    """A float16 scRGB frame (HDR on) comes out as the grey of the 8-bit picture."""
    rng = np.random.default_rng(4)
    srgb = rng.integers(0, 256, (20, 30, 3)).astype(np.float32) / 255
    # the sRGB curve, as Windows puts an SDR picture on a 16-bit float desktop
    lin = np.where(srgb <= 0.04045, srgb / 12.92, ((srgb + 0.055) / 1.055) ** 2.4)
    lin = np.dstack([lin, np.ones((20, 30, 1), np.float32)]).astype(np.float16)
    g, _buf, _maps = staged(lin, 0, sw.FMT_RGBA16F)
    got = g.full_gray(2, 18, 3, 27)
    rgb8 = np.round(srgb * 255).astype(np.uint8)
    bgra = np.dstack([rgb8[..., ::-1], np.full((20, 30), 255, np.uint8)])
    assert np.abs(got - sw.to_gray(bgra)[2:18, 3:27]).max() < 0.01


class PlainGrab:
    """A capture with no pixels at full size at all (the twin check can't run)."""

    def __init__(self, screen: np.ndarray):
        self.screen = screen
        self.source = (screen.shape[1], screen.shape[0])
        self.w = self.h = 0
        self.asked = []

    def resize(self, w, h):
        self.w, self.h = w, h


class ScreenGrab(PlainGrab):
    """A screen grabber as the watcher sees it: no `full`, the box on request."""

    def full_gray(self, y0, y1, x0, x1):
        self.asked.append((y0, y1, x0, x1))
        return self.screen[y0:y1, x0:x1].copy()


def test_a_look_alike_on_a_watched_screen_no_longer_goes_off():
    """'WAVE 7' for 'WAVE 1' on a watched monitor (not a window) scored as the thing
    itself: the twin check only ran where the grabber kept the window's full pixels."""
    word = [0b111101101101111, 0b010010010010111, 0b111001111100111,
            0b111001111001111, 0b101101111001001]
    word = word * 2                        # long enough to fool the working size
    pic, mask = glyphs(word + [0b010110010010111])
    twin = glyphs(word + [0b111001001001001])[0]
    rng = np.random.default_rng(5)

    def check(shown, gives_box):
        screen = (rng.random((720, 1280)) * 0.3 + 0.3).astype(np.float32)
        screen[300:300 + pic.shape[0], 500:500 + pic.shape[1]][mask] = shown[mask]
        grab = (ScreenGrab if gives_box else PlainGrab)(screen)
        it = sw.Watched("t", [(pic, mask)], 0.8, 0.0, cuts=[(1280, 720)])
        cap = sw._Capture(0, Monitor(0, 0, 1280, 720, True))
        cap.grab = grab
        cap.fitted, cap.scaled = sw.Watcher._fit(grab, cap.mon, [it])
        frame = sw.shrink(screen, grab.w / 1280)[:grab.h, :grab.w]
        return sw.Watcher._score(cap, frame, it, 0.0, {})[0], grab

    sc, grab = check(twin, gives_box=False)
    assert sc >= 0.8                       # what it did before: it went off
    sc, grab = check(twin, gives_box=True)
    assert sc < 0.8 and grab.asked         # the box was looked at, at full size
    sc, grab = check(pic, gives_box=True)
    assert sc >= 0.8                       # the thing itself still does


def test_a_picture_found_on_the_half_size_frame_is_handed_on_at_its_real_place():
    """A big picture is looked for on the frame's soft half-size copy first, whose
    places are every other pixel. Its sharp check scored it where it really was, but
    the box handed on stayed the soft place: up to 5 px off at full size, past the
    twin check's few pixels of play, so a picture shown plainly in a game window
    was taken for a look-alike (0.65) and missed until another size happened to fit."""
    rng = np.random.default_rng(3)
    scenery = (gaussian_filter(rng.random((720, 1280)), 4) * 3 - 1).clip(0, 1) * 0.6 + 0.2
    pic = (gaussian_filter(rng.random((75, 231)), 3) * 4 - 1.5).clip(0, 1).astype(np.float32)
    it = sw.Watched("t", [(pic, None)], 0.8, 0.0, cuts=[(1280, 720)])
    off = []
    for y in (1, 2):
        for x in range(500, 508):
            screen = scenery.astype(np.float32)
            screen[y:y + 75, x:x + 231] = pic
            grab = ScreenGrab(screen)
            cap = sw._Capture(0, Monitor(0, 0, 1280, 720, True))
            cap.grab = grab
            cap.fitted, cap.scaled = sw.Watcher._fit(grab, cap.mon, [it])
            assert cap.scaled["t"][0].pats[0][1].soft      # matched on the half-size copy
            frame = sw.shrink(screen, grab.w / 1280)[:grab.h, :grab.w]
            sc, (y0, y1, x0, x1) = sw.Watcher._score(cap, frame, it, 0.0, {})
            k = 1280 / frame.shape[1]
            assert sc >= 0.8
            off.append(max(abs((x0 + x1) / 2 * k - 231 / 2 - x),
                           abs((y0 + y1) / 2 * k - 75 / 2 - y)))
    assert max(off) < sw.TWIN_ALIGN - 1        # within the twin check's reach
