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
