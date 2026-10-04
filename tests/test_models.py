"""Pictures that aren't text: a shaded 3D "creature" (rendered here, see
creature()) cut out with a transparent background, as players cut models out of
their games, looked for in coloured landscapes it wasn't cut from. It must be
found over another background (another colour too), in the dark, further away,
partly hidden; and an empty landscape or another creature must not set it off.

The stand-in capture hands the watcher BGRA like the real one, so the colour
check runs. Two things that went wrong with real game models are pinned here: the
colour check counted the game's background showing through a cut-out (so the
right place failed it), and a slim figure softened at half size kept a few dozen
pixels, which matched empty scenes. Nothing is drawn on screen."""
import time

import numpy as np
import pytest

from onionwatch import screenwatch as sw
from onionwatch.screenwatch import Monitor

W, H = 640, 360
SKIN = np.array([0.55, 0.35, 0.75], np.float32)      # a purple beast
STONE = np.array([0.6, 0.6, 0.62], np.float32)       # a grey golem


def creature(h: int, golem: bool = False, seed: int = 0, slim: float = 1.0,
             colour=SKIN) -> tuple[np.ndarray, np.ndarray]:
    """A 3D-looking creature (RGB, its mask): spheres and ellipsoids lit from the
    top left with a little shine, and a bumpy skin. The beast has a body, a head,
    a snout, four legs and a tail; `golem` stands on two legs instead. `slim`
    narrows every part (a thin figure)."""
    w = int(h * 1.5)
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    depth = np.full((h, w), -np.inf, np.float32)
    shade = np.zeros((h, w), np.float32)
    light = np.array([-0.5, -0.6, 0.62], np.float32)
    light /= np.linalg.norm(light)
    parts = [  # centre x, y (fractions of w, h), radii x, y, z (of h), brightness
        (0.48, 0.45, 0.42, 0.24, 0.3, 0.75),        # body
        (0.86, 0.28, 0.16, 0.15, 0.15, 0.85),       # head
        (0.97, 0.33, 0.07, 0.05, 0.06, 0.6),        # snout
        (0.30, 0.75, 0.06, 0.2, 0.06, 0.55),        # legs
        (0.42, 0.78, 0.06, 0.2, 0.06, 0.5),
        (0.60, 0.77, 0.06, 0.2, 0.06, 0.55),
        (0.72, 0.75, 0.06, 0.2, 0.06, 0.5),
        (0.12, 0.38, 0.12, 0.04, 0.04, 0.45),       # tail
    ]
    if golem:
        parts = [
            (0.5, 0.42, 0.22, 0.26, 0.2, 0.7),      # chest
            (0.5, 0.1, 0.1, 0.1, 0.1, 0.85),        # head
            (0.25, 0.4, 0.07, 0.25, 0.07, 0.6),     # arms
            (0.75, 0.4, 0.07, 0.25, 0.07, 0.6),
            (0.42, 0.82, 0.08, 0.18, 0.08, 0.5),    # legs
            (0.58, 0.82, 0.08, 0.18, 0.08, 0.5),
        ]
    for cx, cy, rx, ry, rz, b in parts:
        rx *= slim
        nx = (xx - cx * w) / (rx * h)
        ny = (yy - cy * h) / (ry * h)
        r2 = nx * nx + ny * ny
        inside = r2 < 1.0
        nz = np.sqrt(np.clip(1.0 - r2, 0.0, 1.0))
        z = nz * rz
        front = inside & (z > depth)
        n = np.stack([nx / rx, ny / ry, nz / rz], -1)
        n /= np.linalg.norm(n, axis=-1, keepdims=True) + 1e-6
        lam = np.clip(n @ light, 0.0, 1.0)
        spec = np.clip(n @ np.array([0, 0, 1], np.float32), 0, 1) ** 24 * 0.25
        val = b * (0.25 + 0.75 * lam) + spec
        depth[front], shade[front] = z[front], val[front]
    mask = np.isfinite(depth)
    rng = np.random.default_rng(seed)
    bumps = rng.random((h // 3 + 1, w // 3 + 1)).astype(np.float32)
    skin = np.kron(bumps, np.ones((3, 3), np.float32))[:h, :w]
    lum = np.clip(shade * (0.85 + 0.3 * skin), 0, 1) * mask
    rgb = np.clip(lum[..., None] * colour * 1.4, 0, 1)
    # trim to the creature, as a cut-out would be
    ys, xs = np.nonzero(mask)
    box = np.s_[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    return rgb[box].astype(np.float32), mask[box]


def landscape(seed: int, sky=(0.45, 0.65, 0.9), land=(0.3, 0.55, 0.25)) -> np.ndarray:
    """A game world (RGB): a sky that darkens upwards, rolling hills, trees, a bumpy
    ground."""
    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    sky, land = np.asarray(sky, np.float32), np.asarray(land, np.float32)
    img = (0.6 + 0.4 * yy / H)[..., None] * sky
    for k in range(3):                               # hills, far to near
        a, f, p = rng.uniform(15, 40), rng.uniform(0.005, 0.02), rng.uniform(0, 6)
        ridge = H * (0.45 + 0.12 * k) + a * np.sin(xx * f + p)
        img = np.where((yy > ridge)[..., None], land * rng.uniform(0.6, 1.4), img)
    for _ in range(14):                              # trees
        tx, ty, r = rng.uniform(0, W), rng.uniform(H * 0.4, H * 0.9), rng.uniform(8, 26)
        tree = (xx - tx) ** 2 + ((yy - ty) * 0.6) ** 2 < r * r
        img = np.where(tree[..., None], land * rng.uniform(0.3, 0.6), img)
    noise = np.kron(rng.random((H // 4, W // 4)).astype(np.float32), np.ones((4, 4)))
    return np.clip(img + (noise[..., None] - 0.5) * 0.1, 0, 1).astype(np.float32)


def place(scene: np.ndarray, pic: tuple, x: int, y: int, light: float = 1.0,
          cover: float = 0.0) -> np.ndarray:
    """The scene with the creature standing in it at (x, y), the whole frame lit by
    `light`, the right `cover` of the creature behind a stone pillar."""
    s = scene.copy()
    rgb, m = pic
    h, w = m.shape
    view = s[y:y + h, x:x + w]
    view[m] = rgb[m]
    if cover:
        cw = int(w * cover)
        s[y:y + h, x + w - cw:x + w] = landscape(99)[:h, :cw] * 0.7
    return np.clip(s * light, 0, 1)


def shrink(pic: tuple, f: float) -> tuple:
    rgb, m = pic
    h, w = round(m.shape[0] * f), round(m.shape[1] * f)
    ys = (np.arange(h) / f).astype(int)
    xs = (np.arange(w) / f).astype(int)
    return rgb[ys][:, xs], m[ys][:, xs]


def bgra(rgb: np.ndarray) -> np.ndarray:
    px = np.empty((*rgb.shape[:2], 4), np.uint8)
    px[..., 2::-1] = np.round(np.clip(rgb, 0, 1) * 255).astype(np.uint8)
    px[..., 3] = 255
    return px


class Shot:
    """A capture that always sees one frame, handed out like Grabber's: grey, and
    the pixels as sampled (`raw`) for the colour check."""
    frame: np.ndarray | None = None      # BGRA

    def __init__(self, mon, w, h, tries=1):
        self.w, self.h = w, h
        self.raw = None

    def grab(self):
        px = Shot.frame
        self.raw = (px, sw.FMT_BGRA8, 1)
        return sw.to_gray(px)

    def resize(self, w, h):
        self.w, self.h = w, h

    def close(self):
        pass


def watched(pic: tuple) -> sw.Watched:
    """The cut-out as the triggers page hands it over: grey, mask, colours."""
    rgb, m = pic
    gray = sw.to_gray(bgra(rgb))
    return sw.Watched("t", [(gray, m)], 0.8, 0.0, any_size=True, cuts=[(W, H)],
                      tints=[sw.tint(rgb, m)])


@pytest.fixture
def watch(monkeypatch):
    monkeypatch.setattr(sw, "monitors", lambda: [Monitor(0, 0, W, H, True)])
    monkeypatch.setattr(sw, "open_grabber", Shot)
    monkeypatch.setattr(sw, "WORK_WIDTH", W)
    made = []

    def run(pic, frame, seconds=4.0) -> tuple[bool, float]:
        """Look for the cut-out `pic` (any size) in `frame` (RGB): (went off, best)."""
        fired = []
        w = sw.Watcher(fired.append)
        made.append(w)
        w.interval = 0.005
        w.set_items([watched(pic)])
        Shot.frame = bgra(frame)
        w.start()
        best, end = 0.0, time.monotonic() + seconds
        while not fired and time.monotonic() < end:
            best = max(best, w.scores.get("t", 0.0))
            time.sleep(0.01)
        best = max(best, w.scores.get("t", 0.0))
        w.stop()
        return bool(fired), best
    yield run
    for w in made:
        w.stop()


BEAST = creature(90)
DESERT = dict(sky=(0.95, 0.75, 0.45), land=(0.8, 0.6, 0.3))


@pytest.mark.parametrize("what, frame", [
    ("over another landscape", lambda: place(landscape(2), BEAST, 300, 180)),
    ("elsewhere, over a third", lambda: place(landscape(3), BEAST, 60, 120)),
    # the colour check must only look under the cut-out, not at the desert behind it
    ("over a desert", lambda: place(landscape(6, **DESERT), BEAST, 240, 150)),
    ("at dusk (55 % light)", lambda: place(landscape(2), BEAST, 300, 180, light=0.55)),
    ("partly behind a pillar", lambda: place(landscape(4), BEAST, 200, 200, cover=0.2)),
    ("further away (75 %)", lambda: place(landscape(5), shrink(BEAST, 0.75), 250, 200)),
])
def test_a_cut_out_model_is_found_in_other_scenes(watch, what, frame):
    fired, best = watch(BEAST, frame())
    assert fired, f"{what}: best {best:.2f}"


@pytest.mark.parametrize("what, frame", [
    ("an empty landscape", lambda: landscape(2)),
    ("an empty desert", lambda: landscape(6, **DESERT)),
    ("a different creature", lambda: place(
        landscape(2), creature(90, golem=True, seed=7, colour=SKIN), 300, 180)),
])
def test_scenes_without_the_model_stay_quiet(watch, what, frame):
    fired, best = watch(BEAST, frame(), seconds=2.5)
    assert not fired, f"{what}: went off at {best:.2f}"


def test_the_colour_check_only_looks_under_a_cut_out():
    """The right place for a cut-out, over a background of another colour, keeps
    its score: what shows through its transparent part doesn't count."""
    rgb, m = BEAST
    frame = place(landscape(6, **DESERT), BEAST, 240, 150)
    h, w = m.shape
    box = (150, 150 + h, 240, 240 + w)
    raw = (bgra(frame), sw.FMT_BGRA8, 1)
    want = sw.tint(rgb, m)
    assert sw.Watcher._tint_factor(raw, box, want, m) == 1.0
    # without the mask the desert takes the score down: that's what used to happen
    # (by 0.87 here; a floating island cut from a green scene, shown over blue sky, lost
    # half, from 0.99 to 0.46)
    assert sw.Watcher._tint_factor(raw, box, want) < 0.9


def test_a_slim_figure_does_not_match_empty_scenes(watch):
    """Softened at half size, a slim figure once kept a few dozen pixels, and those
    matched almost anything (SOFT_MASK_MIN)."""
    slim = creature(64, golem=True, slim=0.35, colour=STONE)
    assert int(slim[1].sum()) < 4 * sw.SOFT_MASK_MIN       # small enough to matter
    for seed in (2, 3, 4):
        fired, best = watch(slim, landscape(seed, land=(0.5, 0.5, 0.5)), seconds=2.0)
        assert not fired, f"landscape {seed}: went off at {best:.2f}"
    fired, best = watch(slim, place(landscape(2), slim, 300, 180))
    assert fired, f"the figure itself: best {best:.2f}"


def test_the_colour_check_allows_for_the_whole_scene_s_light_but_not_another_colour():
    """Darker, brighter, washed out, tinted or a night filter over the whole scene
    keeps the colours' gap near nothing; the same creature in other colours doesn't."""
    rgb, m = BEAST
    frame = place(landscape(2), BEAST, 300, 180)
    h, w = m.shape
    want = sw.tint(rgb, m)
    here = frame[180:180 + h, 300:300 + w]
    for lit in (here * 0.45, here * 0.65 + 0.35, here * 0.5 + 0.5 * 0.5,
                here * 0.73 + np.array([1.0, 0.47, 0.0]) * 0.27,
                here * 0.41 + np.array([0.0, 0.08, 0.35]) * 0.59):
        assert sw.tint_gap(want, sw.tint(lit, m)) < 0.05
    green = here[..., [1, 2, 0]]                    # the purple beast, green
    assert sw.tint_gap(want, sw.tint(green, m)) > sw.TINT_OK + sw.TINT_SPAN


def test_the_colour_check_lets_a_tight_cut_out_with_one_cell_covered_pass():
    """A tight cut-out has only a few cells to compare: something over one of them
    pulled the light change fitted to all of them off, so the others looked off too,
    and a creature matching at 0.86 was thrown out. Fitted again without each cell
    in turn, the rest agree; in other colours they still don't."""
    pic = np.zeros((40, 40, 3), np.float32)
    pic[:20, :20], pic[:20, 20:] = (0.7, 0.3, 0.3), (0.3, 0.6, 0.3)
    pic[20:, :20], pic[20:, 20:] = (0.3, 0.35, 0.7), (0.7, 0.65, 0.2)
    keep = np.zeros((40, 40), bool)
    keep[10:30, 10:30] = True                       # 4 cells
    want = sw.tint(pic, keep)
    covered = pic.copy()
    covered[20:, 20:] = (0.19, 0.2, 0.24)
    assert sw.tint_gap(want, sw.tint(covered, keep)) < sw.TINT_OK
    for twin in (pic[..., [1, 2, 0]], covered[..., [1, 2, 0]]):
        assert sw.tint_gap(want, sw.tint(twin, keep)) > sw.TINT_OK + sw.TINT_SPAN
    old = sw.TINT_FEW_CELLS
    try:
        sw.TINT_FEW_CELLS = 0
        assert sw.tint_gap(want, sw.tint(covered, keep)) > sw.TINT_OK
    finally:
        sw.TINT_FEW_CELLS = old
