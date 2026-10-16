"""A window restored from minimized: Windows' first copy of it then can be the frame
from before it was minimized, so that copy is never checked (a picture that went
away while it was minimized mustn't fire). Stand-in windows only."""
import numpy as np

from onionwatch import windows
from test_fullscreen import game  # noqa: F401 (a fixture)


def test_the_first_copy_after_a_restore_is_thrown_away(game):  # noqa: F811
    state, make = game
    state["fills"] = None                       # a windowed game: copied with PrintWindow
    state["front"] = 77
    state["window"] = 200                       # what it showed before it was minimized
    g = make()
    assert g.grab() is not None and state["printed"] == 1
    state["minimized"] = True
    assert g.grab() is None and g.minimized and g.last is None
    state["minimized"] = False
    assert g.grab() is None and not g.minimized     # the old frame: not given out
    assert state["printed"] == 2 and g.last is None
    state["window"] = 30                        # what it shows now
    got = g.grab()
    assert got is not None and float(np.mean(got)) < 0.2
    assert g.grab() is not None and state["printed"] == 4   # then every copy counts


def test_a_window_minimized_when_watching_starts_skips_its_first_copy_too(game):  # noqa: F811
    state, make = game
    state["fills"], state["front"], state["minimized"] = None, 77, True
    state["size"] = (0, 0)                      # a minimized window has no client area
    g = make()
    assert g.minimized and g.grab() is None
    state["minimized"], state["size"], state["window"] = False, (320, 180), 200
    assert g.grab() is None                     # the bitmap is made at its real size
    assert g.grab() is None and state["printed"] == 1     # the stale copy
    assert g.grab() is not None


def test_a_failed_copy_after_a_restore_gives_nothing_old(game, monkeypatch):  # noqa: F811
    state, make = game
    state["fills"], state["front"], state["window"] = None, 77, 200
    g = make()
    assert g.grab() is not None
    state["minimized"] = True
    g.grab()
    state["minimized"] = False
    monkeypatch.setattr(windows._win()[0], "PrintWindow", lambda *_a: False)
    assert g.grab() is None and g.failures == 1
