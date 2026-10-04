"""The few image operations the matcher needs. The FFTs are scipy.fft's when the
program has it (Onion Board and the Onion Watch app ship scipy.fft, and nothing else
of scipy: it does many rows at once, about three times as fast as numpy) and
numpy's otherwise; the rest is numpy alone, giving what the scipy.ndimage call it
replaced gave, for the arguments the matcher uses (tests/test_imgops.py holds each
one to scipy)."""
from __future__ import annotations

import functools

import numpy as np

try:
    import scipy.fft as _sfft
except ImportError:         # an add-on host without it: numpy's, slower, same results
    _sfft = None


def rfft2(a: np.ndarray, n: tuple[int, int]) -> np.ndarray:
    """The 2-D spectrum of real float32 `a` zero-padded to `n`, as complex64
    (scipy.fft.rfft2(a, n)). Without scipy it's worked out in float64: numpy's float32
    transforms take twice as long."""
    if _sfft is not None:
        return _sfft.rfft2(a, n)
    rows = np.fft.rfft(np.asarray(a, dtype=np.float64), n[1], axis=1)
    return np.fft.fft(rows, n[0], axis=0).astype(np.complex64)


def irfft2(spec: np.ndarray, n: tuple[int, int], keep: tuple[int, int] | None = None
           ) -> np.ndarray:
    """The real (h, w) = `n` image a spectrum from rfft2() is of (scipy.fft.irfft2), or
    only its top-left `keep` (h, w): rows past that aren't transformed at all."""
    fft = _sfft or np.fft
    cols = fft.ifft(spec, n[0], axis=0)
    if keep is not None:
        cols = cols[:keep[0]]
    out = fft.irfft(cols, n[1], axis=1)
    return out if keep is None else out[:, :keep[1]]


@functools.lru_cache(maxsize=256)
def next_fast_len(n: int) -> int:
    """The smallest size >= n made of 2s, 3s and 5s: a quick real FFT
    (scipy.fft.next_fast_len(n, real=True))."""
    if n < 1:
        raise ValueError("next_fast_len needs a size of at least 1")
    best = 1 << (n - 1).bit_length()        # a power of two always works
    p5 = 1
    while p5 < best:
        p35 = p5
        while p35 < best:
            # the smallest power of two that brings p35 up to n
            q = -(-n // p35)
            m = p35 * (1 << (q - 1).bit_length())
            if m < best:
                best = m
            p35 *= 3
        p5 *= 5
    return best


def gaussian_filter(a: np.ndarray, sigma: float, step: int = 1) -> np.ndarray:
    """`a` (2-D) softened by a Gaussian of `sigma` px, its edge pixels repeated past
    it, in its own dtype (scipy.ndimage.gaussian_filter(a, sigma, mode="nearest")),
    or only every `step`-th row and column of that ([::step, ::step]), worked out
    without the rest."""
    a = np.asarray(a)
    r = int(4.0 * sigma + 0.5)
    x = np.arange(-r, r + 1, dtype=np.float64)
    k = np.exp(-0.5 / (sigma * sigma) * x * x)
    k /= k.sum()
    # one axis at a time (the second on the transpose), in float64 and rounded to
    # the dtype in between, the way scipy does it: the same numbers to the bit
    out = _smooth_rows(a, k, step).astype(a.dtype)
    return np.ascontiguousarray(_smooth_rows(out.T, k, step).astype(a.dtype).T)


def _smooth_rows(a: np.ndarray, k: np.ndarray, step: int = 1) -> np.ndarray:
    """`a` correlated down its first axis with the odd, symmetric kernel `k`, the
    first and last rows repeated past the edge: every `step`-th row of that."""
    r = len(k) // 2
    n = a.shape[0]
    end = (n - 1) // step * step + 1      # p[i:i + end:step]: rows i, i + step, ... wanted
    p = np.empty((n + 2 * r, *a.shape[1:]))
    p[r:r + n] = a
    p[:r] = a[0]
    p[r + n:] = a[-1]
    out = p[r:r + end:step] * k[r]
    tmp = np.empty_like(out)
    for j in range(1, r + 1):     # pairs from the centre out, as scipy adds them
        np.add(p[r - j:r - j + end:step], p[r + j:r + j + end:step], out=tmp)
        tmp *= k[r + j]
        out += tmp
    return out


def zoom_linear(a: np.ndarray, shape: tuple[int, int]) -> np.ndarray:
    """`a` (2-D) resized to `shape` by straight-line interpolation between pixel
    centres, edge pixels repeated past the edge, as float32
    (scipy.ndimage.zoom(a, shape / a.shape, order=1, grid_mode=True, mode="nearest"))."""
    out = np.asarray(a, dtype=np.float64)
    for axis, size in enumerate(shape):
        lo, hi, f = _taps(out.shape[axis], size)
        if axis == 0:
            out = out[lo] * (1.0 - f)[:, None] + out[hi] * f[:, None]
        else:
            out = out[:, lo] * (1.0 - f) + out[:, hi] * f
    return out.astype(np.float32)


def _taps(n_in: int, n_out: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """For each output pixel along one axis: the two input pixels either side of
    where its centre lands, and how far it is towards the second."""
    c = (np.arange(n_out) + 0.5) * (n_in / n_out) - 0.5
    i = np.floor(c)
    f = c - i
    i = i.astype(np.intp)
    return np.clip(i, 0, n_in - 1), np.clip(i + 1, 0, n_in - 1), f


def binary_erosion(mask: np.ndarray) -> np.ndarray:
    """`mask` (2-D) with every set pixel that touches an unset one, or the edge, side
    on cleared (scipy.ndimage.binary_erosion(mask))."""
    p = np.pad(np.asarray(mask, dtype=bool), 1)
    return (p[1:-1, 1:-1] & p[:-2, 1:-1] & p[2:, 1:-1] & p[1:-1, :-2] & p[1:-1, 2:])
