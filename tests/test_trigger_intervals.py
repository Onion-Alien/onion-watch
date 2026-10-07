"""Independent trigger cadence, shared capture and backwards-compatible settings."""
from types import SimpleNamespace

import numpy as np
import pytest

from onionwatch import screenwatch as sw
import test_ui
from test_card_layout import new_card

fake_screen, tab = test_ui.fake_screen, test_ui.tab


@pytest.mark.parametrize("raw, expected", [(None, 0), (True, 0), ("50", 0),
                                           (-1, 0), (1, 16), (1000000, 60000), (50, 50)])
def test_interval_roundtrip(raw, expected):
    t = sw.Trigger.from_raw({"id": "a", "interval_ms": raw})
    assert t.interval_ms == expected
    assert sw.Trigger.from_raw(t.to_raw()).interval_ms == expected


def test_card_override_reaches_watcher_and_default_remains(tab):
    row = new_card(tab)
    tab.set_watching(True)
    default = tab.watcher.interval
    row.interval.setCurrentIndex(row.interval.findData(50))
    assert row.t.interval_ms == 50
    assert tab.host.screen["triggers"][0]["interval_ms"] == 50
    assert tab.watcher._items[row.t.id].interval_ms == 50
    assert tab.watcher.interval == default
    row.interval.setCurrentIndex(0)
    assert row.t.interval_ms == 0


def test_fast_and_slow_triggers_share_frames_without_running_together(monkeypatch):
    watcher = sw.Watcher(lambda *_: None)
    watcher.interval = 0.25
    cap = sw._Capture(0)
    cap.fitted = (100, 100)
    cap.grab = SimpleNamespace(grab=lambda: np.ones((100, 100), np.float32))
    fast = sw.Watched("fast", [], .8, 0, interval_ms=50)
    slow = sw.Watched("slow", [], .8, 0, interval_ms=500)
    inherited = sw.Watched("default", [], .8, 0)
    seen = []
    now = [10.0]
    monkeypatch.setattr(sw.time, "monotonic", lambda: now[0])

    def check(_cap, _gray, items):
        seen.extend(it.id for it in items)
        return {it.id: .5 for it in items}

    monkeypatch.setattr(watcher, "_check", check)
    for tick in range(11):
        now[0] = 10 + tick * .05
        watcher._tick(cap, [fast, slow, inherited])
    assert seen.count("fast") == 11
    assert seen.count("slow") == 2
    assert seen.count("default") == 3
    assert cap.scores == {"fast": .5, "slow": .5, "default": .5}


class TimedScreen:
    """A capture showing frames(now) at the (virtual) time it's grabbed, counting grabs."""

    def __init__(self, frames, clock):
        self.frames, self.clock, self.grabs = frames, clock, 0

    def grab(self):
        self.grabs += 1
        return self.frames(self.clock[0])


def test_a_capture_is_only_grabbed_when_one_of_its_triggers_is_due(monkeypatch):
    """The loop goes round at the fastest trigger's pace (here 50 ms, on another
    window): a capture whose only trigger checks every 500 ms is grabbed for its own
    checks, not on every round in between."""
    watcher = sw.Watcher(lambda *_: None)
    now = [10.0]
    monkeypatch.setattr(sw.time, "monotonic", lambda: now[0])
    fast_cap, slow_cap = sw._Capture(0), sw._Capture(1)
    for cap in (fast_cap, slow_cap):
        cap.fitted = (100, 100)
        cap.grab = TimedScreen(lambda t: np.ones((100, 100), np.float32), now)
    fast = sw.Watched("fast", [], .8, 0, interval_ms=50)
    slow = sw.Watched("slow", [], .8, 0, interval_ms=500)
    seen = []

    def check(cap, _gray, items):
        seen.extend((cap.source, it.id) for it in items)
        return {it.id: .5 for it in items}

    monkeypatch.setattr(watcher, "_check", check)
    grabbed = []
    for tick in range(21):
        now[0] = 10 + tick * .05
        grabbed.append((watcher._tick(fast_cap, [fast]), watcher._tick(slow_cap, [slow])))
    assert fast_cap.grab.grabs == 21 and seen.count((0, "fast")) == 21
    assert slow_cap.grab.grabs == 3 and seen.count((1, "slow")) == 3     # 0, 0.5, 1.0 s
    assert [i for i, (_f, s) in enumerate(grabbed) if s] == [0, 10, 20]
    assert slow_cap.scores == {"slow": .5}


@pytest.mark.parametrize("mode", ["change", "still"])
def test_change_and_still_judge_the_same_frames_with_fewer_grabs(monkeypatch, mode):
    """"change" / "still" compare an area with itself CHANGE_GAP ago: grabbing only at
    a trigger's own checks gives the very scores (and alarms) grabbing every round of
    a faster loop gave, since only its checks ever looked at those frames."""
    def frames(t):
        k = int(round((t - 10) / .05))           # the picture changes every 0.3 s
        return np.full((60, 80), 0.2 + 0.3 * ((k // 6) % 3), np.float32)

    def run(step):
        watcher = sw.Watcher(lambda tid, *_: fired.append((now[0], tid)))
        cap = sw._Capture(0)
        cap.fitted = (80, 60)
        cap.grab = TimedScreen(frames, now)
        it = sw.Watched("t", [], 0.5, 0.0, mode=mode, interval_ms=500)
        scores = []
        for tick in range(0, 81, step):
            now[0] = 10 + tick * .05
            if watcher._tick(cap, [it]):
                scores.append((round(now[0], 2), cap.scores.get("t")))
        return scores, cap.grab.grabs

    now = [10.0]
    monkeypatch.setattr(sw.time, "monotonic", lambda: now[0])
    fired = []
    every_round, grabs = run(1)                  # the loop going round every 50 ms
    fired_fast, fired[:] = list(fired), []
    own_pace, own_grabs = run(10)                # ...and only at the trigger's own times
    assert every_round == own_pace and fired_fast == fired
    assert grabs == own_grabs == 9
    assert any(s for _t, s in every_round)       # it did see something change
