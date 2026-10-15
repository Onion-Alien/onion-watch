"""Screen triggers on a desktop Windows composes in 16-bit float: HDR, or Windows 11's
automatic colour management on an SDR screen. Duplicated the old way
(DuplicateOutput), such a desktop comes as 8-bit BGRA holding *linear* light: a game
clearing its screen to (0.8, 0.2, 0.2) read as (0.6, 0.03, 0.03), and every grey was
far too dark to match pictures cut from screenshots. Now the duplication asks for
16-bit float frames (DuplicateOutput1), reads them with the exact sRGB curve, and
re-encodes linear 8-bit frames should only the old way work. The numbers are the
ones a real duplication of such a screen gave. Fake COM objects, no Direct3D."""
import ctypes
import logging

import numpy as np
import pytest

from onionwatch import screenwatch as sw


def bgra(r, g, b) -> np.ndarray:
    return np.array([[[b, g, r, 255]]], np.uint8)


def test_linear_8_bit_frames_give_the_grey_of_the_screenshot():
    # what the screen showed (GDI read it) and what the old duplication handed over
    shown, handed = bgra(204, 51, 51), bgra(154, 8, 8)
    want = sw.to_gray(shown)[0, 0]
    assert abs(float(sw.to_gray(handed)[0, 0]) - want) > 0.1        # read as is: far off
    got = sw.frame_gray(handed, sw.FMT_BGRA8_LINEAR)[0, 0]
    assert got == pytest.approx(want, abs=0.01)
    rgb = sw.frame_rgb(handed, sw.FMT_BGRA8_LINEAR)[0, 0]
    assert rgb == pytest.approx([0.8, 0.2, 0.2], abs=0.02)
    # factor 2 averages the re-encoded pixels, as the 8-bit desktop's are
    block = np.tile(handed, (2, 2, 1))
    assert sw.frame_gray(block, sw.FMT_BGRA8_LINEAR, 2)[0, 0] == pytest.approx(want, abs=0.01)
    assert sw.log_rgb((block, sw.FMT_BGRA8_LINEAR, 2))[0, 0].tolist() == pytest.approx(
        [204, 51, 51], abs=6)


def test_float_frames_use_the_exact_srgb_curve():
    # Windows put the stand-in game's 0.8 / 0.2 on the desktop as 0.604 / 0.033: the
    # sRGB curve, not a 2.2 power (that read 0.795 / 0.21)
    px = np.array([[[0.604, 0.033, 0.033, 1.0]]], np.float16)
    assert sw.frame_rgb(px, sw.FMT_RGBA16F)[0, 0] == pytest.approx([0.8, 0.2, 0.2], abs=0.002)
    # every 8-bit level comes back as itself
    levels = np.arange(256) / 255
    lin = np.where(levels <= 0.04045, levels / 12.92, ((levels + 0.055) / 1.055) ** 2.4)
    px = np.zeros((1, 256, 4), np.float16)
    px[0, :, :3] = lin[:, None]
    got = sw.frame_rgb(px, sw.FMT_RGBA16F)[0, :, 0]
    assert np.abs(got - levels).max() < 0.6 / 255


class FakeCom:
    def __init__(self, handler=None):
        self.handler = handler
        self.p = ctypes.c_void_p(1)
        self.released = 0

    def __bool__(self):
        return True

    def release(self):
        self.released += 1

    def call(self, slot, *args, **kw):
        return self.handler(slot, args) if self.handler else 0


def _grabber(new_hr=0, old_hr=0, announced=sw.FMT_RGBA16F):
    """A DupGrabber whose DuplicateOutput1 / DuplicateOutput answer new_hr / old_hr."""
    calls = []

    def output5(slot, args):
        calls.append(("new", slot, list(args[3][:args[2]])))
        return new_hr

    def output1(slot, args):
        calls.append(("old", slot))
        return old_hr

    def dup(slot, args):
        if slot == sw.DupGrabber.DUP_GET_DESC:
            d = args[0]._obj
            d.Width, d.Height, d.Format, d.Rotation = 1920, 1080, announced, 1
        return 0

    g = object.__new__(sw.DupGrabber)
    g.device, g.staging = FakeCom(), FakeCom()
    g.output5, g.output1, g.dup = FakeCom(output5), FakeCom(output1), FakeCom(dup)
    g._mode = None
    g.w, g.h = 320, 180
    return g, calls


def test_the_duplication_asks_for_float_frames_first(monkeypatch):
    monkeypatch.setattr(sw, "sdr_white", lambda name: 1.0)
    g, calls = _grabber()
    g._duplicate()
    assert calls == [("new", sw.DupGrabber.OUTPUT5_DUPLICATE1, [sw.FMT_RGBA16F, sw.FMT_BGRA8])]
    assert g.announced == sw.FMT_RGBA16F and g._mode == (1920, 1080, sw.FMT_RGBA16F)


def test_the_old_way_is_kept_when_the_new_one_is_refused(monkeypatch, caplog):
    monkeypatch.setattr(sw, "sdr_white", lambda name: 1.0)
    g, calls = _grabber(new_hr=-2147024891)                 # E_ACCESSDENIED
    with caplog.at_level(logging.INFO, logger="onionwatch.screenwatch"):
        g._duplicate()
    assert [c[0] for c in calls] == ["new", "old"]
    assert g.output5 is None                                # not asked again
    assert any("the old way" in r.message for r in caplog.records)
    calls.clear()
    g._duplicate()
    assert calls == [("old", sw.DupGrabber.OUTPUT1_DUPLICATE)]


def test_a_moment_both_ways_fail_does_not_give_up_on_the_new_one(monkeypatch):
    """Right after a display mode switch both refuse for a moment: the next try must
    still ask for float frames, or a colour managed screen reads dark from then on."""
    monkeypatch.setattr(sw, "sdr_white", lambda name: 1.0)
    g, calls = _grabber(new_hr=-2005270494, old_hr=-2005270494)   # NOT_CURRENTLY_AVAILABLE
    with pytest.raises(OSError, match="DuplicateOutput failed"):
        g._duplicate()
    assert g.output5 is not None


def test_8_bit_frames_of_a_float_desktop_are_read_as_linear(monkeypatch):
    monkeypatch.setattr(sw, "sdr_white", lambda name: 1.0)
    g, _calls = _grabber(new_hr=-1)
    g.output5 = None                                        # only the old way works
    g._duplicate()
    g._make_staging((1920, 1080, sw.FMT_BGRA8))             # the frames' own format
    px, fmt = g._as_read(bgra(154, 8, 8))
    assert fmt == sw.FMT_BGRA8_LINEAR
    # an 8-bit desktop announced as 8-bit is read as it is
    g2, _ = _grabber(announced=sw.FMT_BGRA8)
    g2._duplicate()
    assert g2._as_read(bgra(154, 8, 8))[1] == sw.FMT_BGRA8


def test_hdr_frames_are_brought_to_sdr_white(monkeypatch):
    """With HDR on, SDR white sits at the brightness slider's level (2.5 = 200 nits),
    not at 1.0: read as it comes, everything brighter than 80 nits clipped to white."""
    monkeypatch.setattr(sw, "sdr_white", lambda name: 2.5)
    g, _calls = _grabber()
    g._duplicate()
    assert g.white == 2.5
    px = np.zeros((1, 2, 4), np.float16)
    px[0, 0, :3] = 2.5                          # SDR white
    px[0, 1, :3] = 0.214 * 2.5                  # mid grey (128)
    got, fmt = g._as_read(px)
    gray = sw.frame_gray(got, fmt)[0]
    assert gray[0] == pytest.approx(1.0, abs=0.002)
    assert gray[1] == pytest.approx(128 / 255, abs=0.005)


def test_sdr_white_is_1_for_a_name_no_screen_has():
    assert sw.sdr_white("no such screen") == 1.0
