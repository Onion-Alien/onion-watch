"""The engine's cheaper ways of doing the same work give the same answers: the
bounded answer cache (_Capture.twins), the HDR lookup table and the whole-number
2x2 colour sums."""
from __future__ import annotations

import numpy as np
import pytest

from onionwatch import screenwatch as sw


def _answer(n_bytes: int, score: float = 0.5):
    return (np.zeros(1), bytes(n_bytes), score)


def test_answers_hold_at_most_their_limit_and_the_one_used_longest_ago_goes():
    a = sw.Answers(mb=1.0)
    for i in range(5):                                   # 5 x 300 KB > 1 MB
        a[("twin", f"t{i}", 10, 10)] = _answer(300_000)
        if i == 2:
            assert a.get(("twin", "t0", 10, 10)) is not None   # used: kept
    assert a.bytes <= a.limit
    assert ("twin", "t0", 10, 10) in a                  # used lately
    assert ("twin", "t1", 10, 10) not in a              # the oldest unused went
    assert list(a)[-1] == ("twin", "t4", 10, 10)
    assert a.get(("twin", "nope", 1, 1), "x") == "x"


def test_answers_replace_and_pop_keep_the_count_of_bytes_right():
    a = sw.Answers(mb=1.0)
    k = ("cover", "t", 5, 5)
    a[k] = _answer(1000)
    a[k] = _answer(5000)
    assert len(a) == 1 and a.bytes == 5000 + sw._ANSWER_COST
    assert a.pop(k)[2] == 0.5 and a.bytes == 0 and len(a) == 0
    assert a.pop(k, None) is None
    with pytest.raises(KeyError):
        a.pop(k)
    a[k] = _answer(10)
    a.clear()
    assert a.bytes == 0 and not a


def test_one_answer_bigger_than_the_limit_is_still_kept():
    a = sw.Answers(mb=0.001)
    a[("twin", "t", 1, 1)] = _answer(50_000)
    assert len(a) == 1                                   # until the next one comes


def test_a_captures_answers_stay_bounded_over_a_long_evening():
    cap = sw._Capture(0)
    assert isinstance(cap.twins, sw.Answers)
    for i in range(2000):                                # a new box size every check
        cap.twins[("cover", f"t{i % 50}", 100 + i, 200)] = _answer(64_000)
    assert cap.twins.bytes <= sw.TWINS_MB * 2 ** 20


def test_the_hdr_table_gives_what_the_curve_worked_out_gave():
    bits = np.arange(65536, dtype=np.uint32).astype(np.uint16)
    v = bits.view(np.float16)
    v = v[np.isfinite(v)]
    old = np.clip(v.astype(np.float32), 0.0, 1.0) ** (1 / 2.2)
    np.testing.assert_array_equal(sw._hdr_levels(v), old)
    px = np.array([[[np.nan, np.inf, -np.inf, 1]]], np.float16)
    assert sw._hdr_levels(px[..., :3]).tolist() == [[[0.0, 1.0, 0.0]]]


def test_hdr_grey_and_colour_are_as_before():
    rng = np.random.default_rng(1)
    px = (rng.random((20, 30, 4)) * 1.6 - 0.1).astype(np.float16)
    rgb = np.clip(px[..., :3].astype(np.float32), 0.0, 1.0) ** (1 / 2.2)
    np.testing.assert_array_equal(sw.frame_rgb(px, sw.FMT_RGBA16F), rgb)
    y = 0.299 * rgb[..., 0] + 0.587 * rgb[..., 1] + 0.114 * rgb[..., 2]
    np.testing.assert_array_equal(sw.frame_gray(px, sw.FMT_RGBA16F), y.astype(np.float32))


@pytest.mark.parametrize("shape", [(4, 4), (27, 48), (541, 961)])
def test_colour_2x2_sums_match_averaging_floats(shape):
    rng = np.random.default_rng(2)
    px = rng.integers(0, 256, (*shape, 4), dtype=np.uint8)
    rgb = px[..., 2::-1].astype(np.float32) * (1 / 255)
    h, w = shape[0] // 2, shape[1] // 2
    want = rgb[:2 * h, :2 * w].reshape(h, 2, w, 2, 3).mean((1, 3), dtype=np.float32)
    got = sw.frame_rgb(px, sw.FMT_BGRA8, 2)
    assert got.shape == want.shape and got.dtype == np.float32
    np.testing.assert_allclose(got, want, rtol=0, atol=1e-6)
