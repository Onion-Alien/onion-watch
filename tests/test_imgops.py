"""imgops against the scipy calls it replaced: the same results for the arguments the
matcher uses. The FFTs are checked both ways: through scipy.fft, and through numpy as
in a host without it."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from onionwatch import imgops

sfft = pytest.importorskip("scipy.fft")
ndi = pytest.importorskip("scipy.ndimage")

@pytest.fixture(params=["scipy", "numpy"])
def backend(request, monkeypatch):
    """imgops's FFTs through scipy.fft, then as a host without it has them."""
    if request.param == "numpy":
        monkeypatch.setattr(imgops, "_sfft", None)
    return request.param


SHAPES = [(1, 1), (1, 9), (2, 3), (5, 13), (27, 48), (135, 240), (270, 480)]


def _gray(shape, seed=0):
    return (np.random.default_rng(seed).random(shape) * 255).astype(np.float32)


def test_next_fast_len_is_scipys():
    for n in range(1, 4100):
        assert imgops.next_fast_len(n) == sfft.next_fast_len(n, True), n
    for n in (6000, 10007, 65537):
        assert imgops.next_fast_len(n) == sfft.next_fast_len(n, True), n


def test_next_fast_len_refuses_zero():
    with pytest.raises(ValueError):
        imgops.next_fast_len(0)


@pytest.mark.parametrize("shape", [(27, 48), (135, 240), (262, 474)])
def test_ffts_match_scipys(shape, backend):
    a = _gray(shape) - 128
    n = (sfft.next_fast_len(shape[0], True), sfft.next_fast_len(shape[1], True))
    want, got = sfft.rfft2(a, n), imgops.rfft2(a, n)
    assert got.dtype == want.dtype == np.complex64 and got.shape == want.shape
    np.testing.assert_allclose(got, want, rtol=0, atol=1e-5 * np.abs(want).max())
    # a correlation the way Frame.corr makes one, and a picture padded to the frame
    t = np.conj(sfft.rfft2(_gray((9, 14), 1), n))
    want, got = sfft.irfft2(want * t, n), imgops.irfft2(got * t, n)
    assert got.dtype == want.dtype == np.float32 and got.shape == want.shape
    np.testing.assert_allclose(got, want, rtol=0, atol=1e-5 * np.abs(want).max())


@pytest.mark.parametrize("shape", SHAPES)
@pytest.mark.parametrize("sigma", [0.75, 1.5, 4.0])
def test_gaussian_filter_matches_scipys_to_the_bit(shape, sigma):
    a = _gray(shape)
    want = ndi.gaussian_filter(a, sigma, mode="nearest")
    got = imgops.gaussian_filter(a, sigma)
    assert got.dtype == want.dtype and got.shape == want.shape
    np.testing.assert_array_equal(got, want)


def test_gaussian_filter_of_a_strided_view():
    a = _gray((60, 80))[::2, 1::3]          # Frame.soft() slices, resize() may hand views
    np.testing.assert_array_equal(imgops.gaussian_filter(a, 1.5),
                                  ndi.gaussian_filter(a, 1.5, mode="nearest"))


@pytest.mark.parametrize("shape", SHAPES)
@pytest.mark.parametrize("scale", [1.01, 1.3, 1.5, 2.0, 2.7])
def test_zoom_linear_matches_scipys(shape, scale):
    # how screenwatch.resize() calls it: a float32 picture, the size rounded
    a = _gray(shape)
    h, w = shape
    nh, nw = max(1, round(h * scale)), max(1, round(w * scale))
    want = ndi.zoom(a, (nh / h, nw / w), order=1, grid_mode=True, mode="nearest")
    got = imgops.zoom_linear(a, (nh, nw))
    assert got.dtype == want.dtype == np.float32 and got.shape == want.shape == (nh, nw)
    np.testing.assert_allclose(got, want, rtol=0, atol=1e-4)


def test_zoom_linear_of_a_mask():
    # shrink_mask() enlarges a picture's bool mask through resize()
    m = np.random.default_rng(2).random((17, 23)) > 0.4
    want = ndi.zoom(m.astype(np.float32), (34 / 17, 46 / 23), order=1, grid_mode=True,
                    mode="nearest")
    np.testing.assert_allclose(imgops.zoom_linear(m.astype(np.float32), (34, 46)), want,
                               rtol=0, atol=1e-6)


@pytest.mark.parametrize("shape", SHAPES)
def test_binary_erosion_matches_scipys(shape):
    for seed, keep in ((0, 0.3), (1, 0.05), (2, 0.0)):
        m = np.random.default_rng(seed).random(shape) >= keep
        want = ndi.binary_erosion(m)
        got = imgops.binary_erosion(m)
        assert got.dtype == want.dtype == bool
        np.testing.assert_array_equal(got, want)


@pytest.mark.parametrize("shape", SHAPES + [(271, 481)])
def test_gaussian_filter_every_other_pixel_is_scipys_sliced(shape):
    # Frame.soft() keeps every other row and column: worked out alone, to the bit
    a = _gray(shape)
    want = ndi.gaussian_filter(a, 1.5, mode="nearest")[::2, ::2]
    np.testing.assert_array_equal(imgops.gaussian_filter(a, 1.5, step=2), want)


def test_scipy_is_loaded_by_the_first_transform_not_with_the_engine():
    """Onion Board builds the triggers page at start: watching off must not load
    scipy (and its second maths library's threads)."""
    code = ("import sys\n"
            "from onionwatch import board, imgops, screenwatch\n"
            "assert not [m for m in sys.modules if m.startswith('scipy')], 'loaded early'\n"
            "import numpy as np\n"
            "imgops.rfft2(np.ones((4, 6), np.float32), (4, 6))\n"
            "assert 'scipy.fft' in sys.modules\n")
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
    subprocess.run([sys.executable, "-c", code], check=True, env=env,
                   cwd=Path(__file__).resolve().parent.parent, timeout=120)


def test_without_scipy_the_transforms_are_numpys(monkeypatch):
    monkeypatch.setattr(imgops, "_sfft", imgops._NOT_YET)
    monkeypatch.setitem(sys.modules, "scipy.fft", None)     # import scipy.fft fails
    a = _gray((27, 48)) - 128
    n = (27, 48)
    got = imgops.rfft2(a, n)
    assert imgops._sfft is None
    want = sfft.rfft2(a, n)
    np.testing.assert_allclose(got, want, rtol=0, atol=1e-5 * np.abs(want).max())
    np.testing.assert_allclose(imgops.irfft2(got, n), a, rtol=0, atol=1e-3)


def test_irfft2_kept_corner_is_the_whole_ones(backend):
    a = _gray((40, 60)) - 128
    n = (45, 64)
    spec = imgops.rfft2(a, n)
    whole = sfft.irfft2(spec, n)
    got = imgops.irfft2(spec, n, (31, 50))
    assert got.shape == (31, 50)
    np.testing.assert_allclose(got, whole[:31, :50], rtol=0, atol=1e-5 * np.abs(whole).max())


@pytest.mark.parametrize("shape", [(2, 2), (7, 3), (24, 40), (270, 480)])
def test_box_sums_match_the_transforms_they_replace(shape):
    # a box picture's window sums used to be two correlations with scipy.fft
    from onionwatch.screenwatch import Frame
    f = Frame(_gray((270, 480), 3))
    th, tw = shape
    n = f.n
    box = np.conj(sfft.rfft2(np.ones(shape, np.float32), n))
    sh, sw = f.shape
    for got, x in zip(f.box_sums(shape), (f.s, f.s * f.s), strict=True):
        want = sfft.irfft2(sfft.rfft2(x, n) * box, n)[:sh - th + 1, :sw - tw + 1]
        assert got.dtype == np.float32 and got.shape == want.shape
        np.testing.assert_allclose(got, want, rtol=0, atol=2e-6 * np.abs(want).max() + 1e-3)
