"""Cleaning up a picture cut as a rectangle. The scenery around the thing comes with
it, and that scenery makes a trigger miss when the scene behind it moves, or go off
(and then never re-arm) wherever the same scenery is.

While the cut dialog is open the same window keeps being grabbed (for a screen, the
cut's area a few times after it), and the frames are used twice:

learn_mask(): the thing stays put while scenery moving behind it changes from
frame to frame, so pixels that kept changing are scenery: leaving them out makes
the picture a cut-out. Nothing is learned from a scene that didn't move, from a
pixel that changed once and then stayed (the thing going away over a still scene),
or when the cut's border (scenery, around the thing) stood still while something
inside it moved (the thing animating).

choose(): that cut-out isn't always better: a small thin thing (a lightning bolt,
a short word) left on its own can look like plenty of scenery. So both pictures
are tried on the frames, as the watcher would see them: how well each still
matches its own place as the scene moved, and how well anywhere else. The one
with the wider gap between the two is kept, and a gap that's narrow even so is
worth telling the user about (it may be missed, or go off by mistake)."""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from onionwatch import screenwatch

TOL = 24            # a channel moving more than this (of 255) counts as a change
MIN_FRAMES = 3      # frames after the cut needed to learn anything
KEEP_MIN = 0.04     # what's kept must be at least this share of the picture...
KEEP_MAX = 0.97     # ...and what's left out at least 1 - this
EDGE = 2            # px: the cut's border, where there's scenery around the thing...
EDGE_MOVED = 0.5    # ...at least this share of which must be what moved: otherwise it's
                    # the thing moving (an idle animation, a glow) over a still scene
PAD = 3             # px (at the working size) a place may be off by, frame to frame
BETTER = 0.03       # the cut-out is kept only if its gap is wider by this much
NARROW = 0.15       # a gap narrower than this is worth a warning
ELSEWHERE_FRAMES = 4    # frames looked through for a match elsewhere


def _rgb(px: np.ndarray) -> np.ndarray:
    return px[..., :3].astype(np.int16)


def learn_mask(frames: list[np.ndarray]) -> tuple[np.ndarray | None, float]:
    """The thing's pixels (True = keep) in `frames[0]`, the cut rectangle (h, w, 3 or
    4 uint8), from the same rectangle in later frames, in the order they were
    grabbed; frames of another size are skipped. Returns (mask or None, the share of
    the picture left out)."""
    if not frames:
        return None, 0.0
    first = _rgb(frames[0])
    later = [_rgb(f) for f in frames[1:] if f.shape[:2] == frames[0].shape[:2]]
    if len(later) < MIN_FRAMES:
        return None, 0.0
    moved = np.zeros(first.shape[:2], np.int32)      # frames it differed from the cut in
    events = np.zeros(first.shape[:2], np.int32)     # frames it changed from the one before
    prev = first
    for f in later:
        moved += np.abs(f - first).max(-1) > TOL
        events += np.abs(f - prev).max(-1) > TOL
        prev = f
    scenery = (events >= 2) & (moved >= max(2, math.ceil(len(later) / 2)))
    if min(scenery.shape) <= 2 * EDGE:
        return None, 0.0
    edge = np.ones(scenery.shape, bool)
    edge[EDGE:-EDGE, EDGE:-EDGE] = False
    if float(scenery[edge].mean()) < EDGE_MOVED:
        return None, 0.0
    keep = ~scenery
    share = float(keep.mean())
    if not KEEP_MIN <= share <= KEEP_MAX:
        return None, 0.0
    return keep, 1.0 - share


@dataclass
class Fit:
    """How a picture did on the frames: `here`, its worst score at its own place;
    `away`, its best anywhere else. The gap between them is the margin."""
    here: float
    away: float

    @property
    def gap(self) -> float:
        return self.here - self.away


def fit(frames: list[np.ndarray], rect: tuple[int, int, int, int],
        mask: np.ndarray | None) -> Fit:
    """Try the picture cut at `rect` (x, y, w, h) out of `frames[0]` (whole frames,
    (H, W, 3 or 4) uint8, the cut's first), with `mask` (its shape) or as the
    rectangle, on all of them at the working size the watcher would use."""
    x, y, w, h = rect
    grays = [screenwatch.to_gray(f) for f in frames if f.shape == frames[0].shape]
    H, W = grays[0].shape
    scale = screenwatch.work_scale(W, [min(w, h)])
    small = [screenwatch.shrink(g, scale) for g in grays]
    pic = screenwatch.shrink(grays[0][y:y + h, x:x + w], scale)
    m = None if mask is None else screenwatch.shrink_mask(mask, scale)
    p = screenwatch.Pattern(pic, m)
    if not p.ok:
        return Fit(0.0, 1.0)
    ph, pw = p.shape
    ax, ay = round(x * scale), round(y * scale)
    here = 1.0
    for g in small[1:]:
        y0, x0 = max(0, ay - PAD), max(0, ax - PAD)
        area = g[y0:ay + ph + PAD, x0:ax + pw + PAD]
        if area.shape[0] < ph or area.shape[1] < pw:
            continue
        here = min(here, screenwatch.find(screenwatch.Frame(area), p)[0])
    away = 0.0
    step = max(1, len(small) // ELSEWHERE_FRAMES)
    for g in small[::step][:ELSEWHERE_FRAMES]:
        for sc, (px, py) in screenwatch.find_peaks(screenwatch.Frame(g), p, 4, -1.0):
            if abs(px - ax) > pw / 2 or abs(py - ay) > ph / 2:
                away = max(away, sc)
                break
    return Fit(here, away)


def choose(frames: list[np.ndarray], rect: tuple[int, int, int, int]
           ) -> tuple[np.ndarray | None, Fit, Fit | None]:
    """learn_mask() from the frames, then fit() both the rectangle and the learned
    cut-out: (the mask to use or None for the rectangle, the rectangle's Fit, the
    cut-out's or None when nothing was learned)."""
    x, y, w, h = rect
    same = [f for f in frames if f.shape == frames[0].shape]
    keep, _left = learn_mask([f[y:y + h, x:x + w] for f in same])
    plain = fit(same, rect, None)
    if keep is None:
        return None, plain, None
    cut = fit(same, rect, keep)
    return (keep if cut.gap > plain.gap + BETTER else None), plain, cut
