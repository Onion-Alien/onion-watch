"""Pictures that weren't cut from the game (a file or a copy from the web): they say
nothing of the size they're drawn at, so they're shrunk to fit what's watched when
they're added and looked for over WIDE_SIZES. No screen is read."""
import numpy as np
from conftest import process_events
from PySide6.QtCore import QMimeData, QUrl
from PySide6.QtGui import QImage
from test_sizes import Grab, gray, scaled, world
from test_ui import as_qimage, banner, fake_screen, tab  # noqa: F401 (fixtures)

from onionwatch import screenwatch as sw
from onionwatch.screenwatch import Monitor
from onionwatch.ui import triggerspanel as tp


def web_watcher(level: np.ndarray, pic: np.ndarray, wide: bool, any_size: bool = True):
    """check(): one frame of `level` scored as the watcher would, for a picture with
    no cut size known beyond the window's own (as one from the web is added)."""
    h, w = level.shape[:2]
    grab = Grab(w, h)
    it = sw.Watched("t", [(pic, None)], 0.8, 0.0, any_size=any_size, cuts=[(w, h)],
                    wide=[wide])
    cap = sw._Capture(0, Monitor(0, 0, w, h, True))
    cap.grab = grab
    cap.fitted, cap.scaled = sw.Watcher._fit(grab, cap.mon, [it])
    frame = gray(scaled(level, grab.w / w)[:grab.h, :grab.w])
    return lambda: sw.Watcher._score(cap, frame, it, 0.0, {})[0], cap


def big_copy(level: np.ndarray, k: float) -> np.ndarray:
    """The sprite cut from the level, as a picture `k` times its size on screen (the
    big, smooth picture a web search gives)."""
    piece = level[192:256, 292:356]
    return gray(scaled(piece, k))


def test_wide_sizes_reach_far_below_any_size():
    assert sw.WIDE_SIZES[0] < 0.1 < sw.SIZES[0]
    assert min(sw.WIDE_SWEEP) < 0.05 and max(sw.WIDE_SWEEP) <= sw.WIDE_SIZES[1]
    assert set(sw.SWEEP) <= set(sw.WIDE_SWEEP) | set(sw.SWEEP)
    small = sum(f < 1 for f in sw.WIDE_SWEEP[:30])
    assert small > 20                       # smaller sizes are tried first


def test_a_picture_from_the_web_is_swept_even_without_any_size():
    it = sw.Watched("t", [(np.zeros((8, 8), np.float32), None)] * 2, 0.8, 0.0,
                    any_size=False, wide=[False, True])
    assert it.sweeping and not it.sweeps(0) and it.sweeps(1)
    assert not sw.Watched("t", [(np.zeros((8, 8), np.float32), None)], 0.8, 0.0).sweeping


def test_a_picture_five_times_too_big_is_found_only_when_its_size_is_unknown():
    level = world()
    pic = big_copy(level, 4.5)              # 288 px for a 48 px sprite (with its room)
    check, cap = web_watcher(level, pic, wide=True, any_size=False)
    scores = [check() for _ in range(80)]
    assert max(scores) >= 0.8
    look = cap.scaled["t"][0]
    assert any(0.17 < f < 0.27 for f in look.found)
    assert min(check() for _ in range(3)) >= 0.8        # kept: every check from now on

    check_old, _ = web_watcher(level, pic, wide=False)  # a cut: only half to double
    assert max(check_old() for _ in range(80)) < 0.6


def test_nothing_goes_off_for_a_web_picture_in_a_level_without_it():
    level = world()
    pic = big_copy(level, 4.5)
    empty = world(sprites=())
    check, _ = web_watcher(empty, pic, wide=True)
    assert max(check() for _ in range(80)) < 0.8


# ---------------------------------------------------------------- adding them


def test_a_file_onion_watch_did_not_cut_counts_as_from_the_web(qapp, tmp_path):
    img = QImage(400, 300, QImage.Format_ARGB32)
    img.fill(0xFF336699)
    img.save(str(tmp_path / "web.png"))
    assert tp.is_web(tp.picture_file(str(tmp_path / "web.png")))
    tp.set_cut_size(img, (1920, 1080))      # one Onion Watch kept: it knows its size
    img.save(str(tmp_path / "cut.png"))
    assert not tp.is_web(tp.picture_file(str(tmp_path / "cut.png")))


def test_a_picture_from_the_web_is_shrunk_to_fit_what_is_watched(qapp):
    img = QImage(3000, 1000, QImage.Format_ARGB32)
    img.fill(0xFF336699)
    tp.set_web(img)
    out = tp.fit_web(img, (1920, 1080))
    assert out.width() == round(1920 * tp.WEB_FILL) and out.height() <= 1080 * tp.WEB_FILL
    assert tp.is_web(out)                   # its notes go with it
    small = QImage(64, 64, QImage.Format_ARGB32)
    assert tp.fit_web(small, (1920, 1080)) is small
    huge = QImage(9000, 300, QImage.Format_ARGB32)     # over MAX_SIDE: shrunk, not refused
    assert tp.fit_web(huge, None).width() <= tp.WEB_GUESS[0]


def test_a_picture_copied_in_a_browser_counts_as_from_the_web(qapp):
    clip = qapp.clipboard()
    clip.setImage(as_qimage(banner()))      # Win+Shift+S: the picture alone
    assert not tp.copied_picture().isNull() and not tp.is_web(tp.copied_picture())
    mime = QMimeData()
    mime.setImageData(as_qimage(banner()))
    mime.setHtml('<img src="https://example.com/skull.png">')
    clip.setMimeData(mime)                  # a browser's "Copy image"
    assert tp.is_web(tp.copied_picture())


def test_a_picture_file_copied_in_explorer_can_be_pasted(qapp, tmp_path):
    as_qimage(banner()).save(str(tmp_path / "skull.png"))
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(tmp_path / "skull.png"))])
    qapp.clipboard().setMimeData(mime)
    img = tp.copied_picture()
    assert not img.isNull() and tp.is_web(img)


def test_a_web_picture_is_added_shrunk_marked_and_explained(tab, qapp, tmp_path):  # noqa: F811
    big = QImage(as_qimage(banner()).scaled(900, 300))
    big.save(str(tmp_path / "skull.png"))
    t = tab._new(tp.picture_file(str(tmp_path / "skull.png")), "Skull")
    assert t is not None
    kept = QImage(t.images[0])
    assert tp.is_web(kept) and tp.cut_size(kept) is not None    # older versions: as before
    assert kept.width() <= 320 * tp.WEB_FILL + 1                # the 320 x 180 screen
    row = tab.rows[t.id]
    assert process_events(qapp, lambda: "every size" in row.state.text())
    tab._sync()
    assert tab.watcher._items[t.id].wide == [True]


def test_a_picture_dragged_from_a_browser_is_added(tab, qapp):  # noqa: F811
    tab._new(as_qimage(banner()), "Banner")
    row = next(iter(tab.rows.values()))
    mime = QMimeData()
    mime.setImageData(as_qimage(banner()))
    img = row.dropped_picture(mime)
    assert img is not None and tp.is_web(img)
    tab._add_dropped_picture(row, img)
    assert len(row.t.images) == 2


def test_a_web_picture_turning_up_is_found_within_a_few_checks(monkeypatch):
    """No sweep turns at all: when the thing shows up, looking where the screen
    changed finds it at a fifth of the picture's size, among other triggers."""
    from test_sizes import sprite
    monkeypatch.setattr(sw, "SWEEPERS", 0)
    level = world()
    pic = big_copy(level, 4.5)
    rng = np.random.default_rng(4)
    others = [rng.random((64, 64)).astype(np.float32) for _ in range(5)]
    h, w = 540, 960
    grab = Grab(w, h)
    items = [sw.Watched("t", [(pic, None)], 0.8, 0.0, any_size=True, cuts=[(w, h)],
                        wide=[True])]
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
    shown[200:248, 300:348] = sprite()
    for _ in range(3):
        assert watcher._check(cap, frame(empty), items)["t"] < 0.8
    best = max(watcher._check(cap, frame(shown), items)["t"] for _ in range(4))
    assert best >= 0.8 and fired == ["t"]
