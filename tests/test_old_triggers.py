"""Triggers saved by every older version still load and still watch.

old_triggers.json holds, for each release, two triggers exactly as that release
saved them (one on and ringing, one off), made by running that release's own
Trigger.to_raw, plus the Triggers tab's formats from Onion Board before Onion
Watch: one `image` / `sound`, then the lists, then the 0.6+ fields."""
import json
from pathlib import Path

import pytest
from fakehost import FakeHost
from PySide6.QtGui import QColor, QImage

from onionwatch.engine import screenwatch as sw
from onionwatch.engine.screenwatch import Trigger, WindowRef
from onionwatch.ui import triggerspanel
from onionwatch.ui.triggerspanel import TriggersTab

SAVED = {v: ts for v, ts in json.loads(
    (Path(__file__).parent / "old_triggers.json").read_text(encoding="utf-8")).items()
    if not v.startswith("_")}
GAME = WindowRef("game.exe", "Made-up Game", 0)


def test_every_release_is_in_the_fixture():
    assert len(SAVED) == 36 and {"board-1", "0.2.0", "0.5.6", "0.6.0", "0.9.6"} <= set(SAVED)


@pytest.mark.parametrize("version", list(SAVED))
def test_main_loads_what_each_version_saved(version):
    for d in SAVED[version]:
        t = Trigger.from_raw(d)
        assert t is not None, d["id"]
        on = d["id"].endswith("-on")
        assert t.images == [f"triggers/{d['id']}.png"]
        assert t.sounds == (["snd-alarm"] if version in ("board-1", "board-2")
                            else ["snd-alarm", "snd-horn"])
        assert t.threshold == 0.87 and t.cooldown == 4.5
        assert t.enabled is on
        if not version.startswith("board-"):     # Onion Board's tab had no ring or window
            assert t.ring is on
            assert t.sources == [GAME]
        assert t.uses_pictures


@pytest.fixture
def tab(qapp, tmp_path, monkeypatch):
    """Every saved trigger in one config, as a 0.6+ version splits it (the first 50 in
    "triggers", the rest in "more_triggers"), its pictures and sounds really there."""
    monkeypatch.setattr(triggerspanel.QMessageBox, "information", lambda *a, **k: None)
    monkeypatch.setattr(triggerspanel.QMessageBox, "warning", lambda *a, **k: None)
    monkeypatch.setattr(sw, "monitors", lambda: [sw.Monitor(0, 0, 320, 180, True)])
    img = QImage(64, 32, QImage.Format.Format_RGB32)
    img.fill(QColor("#203040"))
    for x in range(8, 56):
        img.setPixelColor(x, 16, QColor("#f0e020"))
    raws = []
    for ts in SAVED.values():
        for d in ts:
            pic = tmp_path / d["image"]
            pic.parent.mkdir(exist_ok=True)
            img.save(str(pic))
            d = json.loads(json.dumps(d).replace("triggers/", f"{tmp_path.as_posix()}/triggers/"))
            raws.append(d)
    host = FakeHost(tmp_path, {"triggers": raws[:triggerspanel.OLD_TRIGGERS],
                               "more_triggers": raws[triggerspanel.OLD_TRIGGERS:]})
    host.board += [("snd-alarm", "Alarm"), ("snd-horn", "Horn")]
    t = TriggersTab(host)
    t._lister = lambda: []
    t._front = lambda: 0
    watched: list = []
    monkeypatch.setattr(t.watcher, "set_items", watched.append)
    yield t, raws, watched
    t.shutdown()
    t.deleteLater()
    from PySide6.QtCore import QCoreApplication, QEvent
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_every_old_trigger_that_was_on_is_watched(tab):
    t, raws, watched = tab
    assert [x.id for x in t.triggers] == [d["id"] for d in raws]
    t.btn_watch.blockSignals(True)
    t.btn_watch.setChecked(True)
    t.btn_watch.blockSignals(False)
    t._sync()
    got = {w.id: w for w in watched[-1]}
    assert set(got) == {d["id"] for d in raws if d["enabled"]}
    for w in got.values():
        assert len(w.pictures) == 1 and w.threshold == 0.87
        if not w.id.startswith("board-"):
            assert w.sources == [GAME]
