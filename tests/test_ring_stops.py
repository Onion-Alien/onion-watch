"""What stops a ringing trigger by itself (Trigger.stop): the game moving once it
has settled, the thing going away, switching to the game, or the mouse or
keyboard — and the Stop button for all of them. Stand-in captures only."""
import time

import numpy as np
from conftest import process_events
import test_ui
from test_ui import FakeGrabber, as_qimage, banner, scene, showing

from onionwatch import screenwatch as sw
from onionwatch import windows
from onionwatch.screenwatch import Quieter, Trigger, WindowRef

fake_screen, tab = test_ui.fake_screen, test_ui.tab   # the same stand-ins

AREA = np.zeros((40, 40), np.float32)


def moved(share: float) -> np.ndarray:
    """AREA with `share` of it changed."""
    a = AREA.copy()
    a.reshape(-1)[:round(a.size * share)] = 1.0
    return a


def test_the_stop_setting_is_saved_and_checked():
    t = Trigger(id="a")
    assert t.stop == "moves"                          # the default: you're back and playing
    t.stop = "focus"
    assert Trigger.from_raw(t.to_raw()).stop == "focus"
    assert Trigger.from_raw({"id": "b", "stop": "explode"}).stop == "moves"


def test_a_ring_always_lasts_a_moment():
    q = Quieter("gone", 0, since=0.0)
    assert not q.step(AREA, False, None, 0.5)         # gone already, but it's heard first
    assert q.step(AREA, False, None, sw.STOP_LEAST)


def test_gone_waits_for_a_clear_no():
    q = Quieter("gone", 0, since=0.0)
    t = sw.STOP_LEAST
    assert not q.step(moved(0.5), True, None, t)      # moving doesn't matter
    assert not q.step(AREA, None, None, t + 0.1)      # in between: not yet
    assert q.step(AREA, False, None, t + 0.2)


def test_moves_waits_for_the_screen_to_settle_then_stops_on_any_movement():
    q = Quieter("moves", 0, since=0.0)
    t = sw.STOP_LEAST
    # a death screen fading in: changing every check, so it can't stop it
    for i in range(10):
        assert not q.step(moved(0.1 + i * 0.05), True, None, t + i * 0.1)
    t += 1.0
    still = moved(0.55)
    for i in range(10):                               # now it stands still...
        assert not q.step(still, True, None, t + i * 0.1)
    assert q.ref is not None
    lit = still.copy()
    lit[-1, :5] = 0.5                                 # ...a blinking cursor is too small
    assert not q.step(lit, True, None, t + 1.1)
    # you're back: a lot of it moves
    assert q.step(moved(0.9), True, None, t + 1.2)


def test_moves_that_never_settles_still_stops_when_it_goes_away():
    q = Quieter("moves", 0, since=0.0)
    t = sw.STOP_LEAST
    for i in range(20):
        assert not q.step(moved((i % 2) * 0.5), True, None, t + i * 0.1)
    assert q.step(moved(0.5), False, None, t + 2.1)


def test_focus_stops_when_its_window_comes_to_the_front():
    q = Quieter("focus", WindowRef("game.exe", "Game"), since=0.0)
    assert not q.step(AREA, True, False, 0.0)
    assert not q.step(AREA, False, False, 2.0)        # gone, but you haven't looked yet
    assert q.step(AREA, True, True, 2.1)              # alt-tabbed back


def test_focus_on_a_screen_stops_when_another_window_comes_to_the_front():
    q = Quieter("focus", 0, since=0.0)
    assert not q.step(AREA, True, 111, 0.0)           # the browser you're reading
    assert not q.step(AREA, True, 111, 2.0)
    assert not q.step(AREA, True, 0, 2.1)             # nothing in front for a moment
    assert q.step(AREA, True, 222, 2.2)               # switched to the game


def test_the_watcher_says_when_a_ring_stops_by_itself(fake_screen, monkeypatch):
    """The watcher thread hands the stop over once the picture goes away, in the
    place it went off."""
    monkeypatch.setattr(sw, "STOP_LEAST", 0.0)
    plain, hit = scene(1), showing(scene(1), banner())
    FakeGrabber.frames = [plain]
    quiet = []
    w = sw.Watcher(lambda tid, h: w.quiet_on(tid, h.source, "gone"), hits=True,
                   on_quiet=quiet.append)
    w.interval = 0.001
    w.set_items([sw.Watched("t1", [(banner(), None)], 0.8, 0.0)])
    w.start()
    try:
        FakeGrabber.frames.append(hit)
        assert wait(lambda: "t1" in w._quiet)
        assert quiet == []
        FakeGrabber.frames.append(plain)
        assert wait(lambda: quiet == ["t1"])
        assert "t1" not in w._quiet
    finally:
        w.stop()


def wait(cond, timeout=5.0):
    end = time.monotonic() + timeout
    while not cond() and time.monotonic() < end:
        time.sleep(0.005)
    return cond()


def ringing_card(tab, stop: str):
    tab._new(as_qimage(banner()), "Queue")
    row = next(iter(tab.rows.values()))
    row.chk_ring.setChecked(True)
    row.until.setCurrentIndex(row.until.findData(stop))
    assert row.t.stop == stop and not row.until.isHidden()
    return row


def test_a_card_picks_what_stops_its_ring(tab):
    row = ringing_card(tab, "focus")
    assert tab.host.screen["triggers"][0]["stop"] == "focus"
    assert row.state.text().startswith("Rings until you switch to the game")
    assert tab.alert_text(row.t).endswith("Ringing until you switch to it.")
    row.chk_ring.setChecked(False)
    assert row.until.isHidden()


def test_touching_the_mouse_or_keyboard_stops_an_input_ring(tab, qapp, monkeypatch):
    monkeypatch.setattr(sw, "STOP_LEAST", 0.0)
    idle = [60.0]
    monkeypatch.setattr(windows, "idle_seconds", lambda: idle[0])
    row = ringing_card(tab, "input")
    tab._fire(row.t.id, tab._gen)
    assert tab.host.ringing() == [row.t.id]
    qapp.processEvents()
    assert tab.host.ringing() == [row.t.id]           # nothing touched since it began
    idle[0] = 0.0
    assert process_events(qapp, lambda: tab.host.ringing() == [])
    assert not tab._input_waits and not tab._input_poll.isActive()


def test_the_watcher_stopping_it_stops_the_sound_and_stop_forgets_it(tab, qapp):
    row = ringing_card(tab, "gone")
    tid = row.t.id
    tab._hits[tid] = sw.Hit(0, (0, 0, 1, 1), 0.9)
    tab._fire(tid, tab._gen)
    assert tid in tab.watcher._quiet
    tab._quieted.emit(tid)
    assert tab.host.ringing() == [] and tid not in tab.watcher._quiet
    assert "you're back" in row.state.text()
    tab._fire(tid, tab._gen)                          # rang again; Stop clears it all
    tab.stop_ringing()
    assert tab.host.ringing() == [] and not tab.watcher._quiet


def test_manual_rings_wait_for_stop(tab):
    row = ringing_card(tab, "manual")
    tab._hits[row.t.id] = sw.Hit(0, (0, 0, 1, 1), 0.9)
    tab._fire(row.t.id, tab._gen)
    assert row.t.id not in tab.watcher._quiet and not tab._input_waits
    assert tab.host.ringing() == [row.t.id]
