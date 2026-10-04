"""Learning a cut-out while cutting (cutout.py): from a few grabs of the same window,
scenery moving behind a thing is left out of its picture, and nothing is learned
when the scene stood still, when the thing went away over a still scene, or when
the thing moved inside a still border. Made-up RGB frames only."""
import time

import numpy as np

from onionwatch import cutout

W, H = 480, 270
RECT = (180, 110, 120, 40)      # x, y, w, h: the cut, the word plus scenery around it


def scenery(seed=0, w=W + 200, h=H) -> np.ndarray:
    """Busy blocky colour scenery, wider than a frame so it can pan."""
    rng = np.random.default_rng(seed)
    x = rng.random((h // 6 + 1, w // 6 + 1, 3)).astype(np.float32)
    return (np.kron(x, np.ones((6, 6, 1), np.float32))[:h, :w] * 200 + 30).astype(np.uint8)


def word(img: np.ndarray, x=200, y=120, on=True) -> np.ndarray:
    """A white 'word' with a black outline: letters of bars, the sort a name plate has."""
    out = img.copy()
    if not on:
        return out
    for i, lx in enumerate(range(x, x + 80, 10)):
        h = 20 if i % 2 else 14
        out[y - 2:y + h + 2, lx - 2:lx + 8] = 0
        out[y:y + h, lx:lx + 6] = 255
        out[y + h // 2:y + h // 2 + 2, lx:lx + 10] = 255
    return out


def panning(n=6, step=7, seed=0, **kw) -> list[np.ndarray]:
    bg = scenery(seed)
    return [word(bg[:, i * step:i * step + W], **kw) for i in range(n)]


def cut(frames):
    x, y, w, h = RECT
    return [f[y:y + h, x:x + w] for f in frames]


def test_scenery_moving_behind_a_word_is_left_out():
    frames = panning()
    keep, left = cutout.learn_mask(cut(frames))
    assert keep is not None and 0.3 < left < 0.97
    x, y, w, h = RECT
    letters = word(np.full((H, W, 3), 128, np.uint8)) != 128
    letters = letters.any(-1)[y:y + h, x:x + w]
    assert keep[letters].mean() > 0.95           # the word is kept...
    assert keep[:, :8].mean() < 0.2              # ...the scenery left of it isn't


def test_choose_keeps_the_cut_out_when_it_does_better():
    mask, plain, cut_fit = cutout.choose(panning(8), RECT)
    assert cut_fit is not None
    assert mask is not None and cut_fit.gap > plain.gap
    assert cut_fit.here > 0.9                    # still found where it is


def test_a_still_scene_teaches_nothing():
    frames = [word(scenery()[:, :W])] * 6
    assert cutout.learn_mask(cut(frames))[0] is None
    mask, plain, cut_fit = cutout.choose(frames, RECT)
    assert mask is None and cut_fit is None and plain.here > 0.99


def test_a_thing_going_away_over_a_still_scene_teaches_nothing():
    bg = scenery()[:, :W]
    frames = [word(bg)] + [word(bg, on=False)] * 5
    assert cutout.learn_mask(cut(frames))[0] is None


def test_a_thing_animating_inside_a_still_border_teaches_nothing():
    bg = scenery()[:, :W]
    rng = np.random.default_rng(3)
    frames = []
    for _ in range(6):
        f = word(bg)
        f[118:142, 198:282] = rng.integers(0, 255, (24, 84, 3), np.uint8)   # a glow / sparkle
        frames.append(f)
    assert cutout.learn_mask(cut(frames))[0] is None


def test_too_few_frames_or_other_sizes_teach_nothing():
    frames = panning(3)
    assert cutout.learn_mask(cut(frames))[0] is None        # 2 after the cut: too few
    odd = cut(panning(6))
    odd[2:] = [f[:-1] for f in odd[2:]]                     # resized mid-way: skipped
    assert cutout.learn_mask(odd)[0] is None
    assert cutout.learn_mask([])[0] is None


def test_big_grabs_are_kept_smaller_and_the_mask_comes_back_full_size(monkeypatch):
    """A window too big to keep RING grabs of at full size is grabbed k times smaller;
    the mask learned is still the cut's own size."""
    monkeypatch.setattr(cutout, "GRAB_S", 0.01)
    monkeypatch.setattr(cutout, "RING_BYTES", W * H * 4 * (cutout.RING + 1))   # k = 2
    big = [np.kron(f, np.ones((2, 2, 1), np.uint8)) for f in panning(10)]
    it = iter(big[1:] * 50)
    rec = cutout.Recorder(big[0], lambda: next(it)).start()
    assert rec.k == 2
    time.sleep(0.3)
    x, y, w, h = RECT
    keep, plain, cut_fit = cutout.learn(rec, (2 * x, 2 * y, 2 * w, 2 * h))
    assert keep is not None and keep.shape == (2 * h, 2 * w)
    assert cut_fit.gap > plain.gap


def test_no_grabber_means_just_the_cut():
    rec = cutout.Recorder(word(scenery()[:, :W]), None).start()
    keep, plain, cut_fit = cutout.learn(rec, RECT)
    assert keep is None and cut_fit is None and plain.here == 1.0


def test_notes_say_what_may_go_wrong():
    assert cutout.notes(cutout.Fit(0.95, 0.4), 0.8) == []
    assert "missed" in cutout.notes(cutout.Fit(0.7, 0.4), 0.8)[0]
    assert "by mistake" in cutout.notes(cutout.Fit(0.95, 0.75), 0.8)[0]
