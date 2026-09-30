"""The triggers panel on a host that is only onionwatch.host.Host (as Onion Board
is): the settings, sounds, playing and pictures all go through the host, a sound
file is added in the background, and ringing stops only the rings. Stand-in
screens, nothing heard."""
import pytest
from conftest import process_events
from fakehost import FakeHost
from test_ui import FakeGrabber, W, H, as_qimage, banner, scene, showing  # noqa: F401

from onionwatch import host as hostmod
from onionwatch import screenwatch as sw
from onionwatch import theme
from onionwatch.apphost import AppHost
from onionwatch.player import Player
from onionwatch.screenwatch import Monitor
from onionwatch.settings import Config
from onionwatch.sounds import Library
from onionwatch.ui import triggerspanel
from onionwatch.ui.alarmbar import AlarmBar
from onionwatch.ui.triggerspanel import TriggersTab


@pytest.fixture
def board(qapp, tmp_path, monkeypatch):
    monkeypatch.setattr(sw, "monitors", lambda: [Monitor(0, 0, W, H, True)])
    monkeypatch.setattr(sw, "open_grabber", FakeGrabber)
    monkeypatch.setattr(sw, "WORK_WIDTH", W)
    monkeypatch.setattr(triggerspanel.QMessageBox, "information", lambda *a, **k: None)
    FakeGrabber.frames = [scene(1)]
    host = FakeHost(tmp_path / "board")
    tab = TriggersTab(host)
    tab.resize(800, 600)
    yield host, tab
    tab.shutdown()


def test_both_hosts_have_the_whole_interface(app_dir):
    assert hostmod.missing(FakeHost(app_dir)) == []
    assert hostmod.missing(AppHost(Config(), lambda: None, Library([]), Player())) == []
    assert hostmod.missing(object())    # and something that isn't one is told apart


def test_a_new_trigger_is_kept_in_the_host(board):
    host, tab = board
    tab._new(as_qimage(banner()), "Died")
    t = tab.triggers[0]
    assert t.sounds == []                       # the board has no default sound
    assert host.screen["triggers"][0]["id"] == t.id and host.saves
    assert t.images[0].startswith(str(host.data_dir / "triggers"))


def test_a_match_plays_through_the_host_and_rings_until_stopped(board, qapp):
    host, tab = board
    tab._new(as_qimage(banner()), "Died")
    row = next(iter(tab.rows.values()))
    row.sound.activated.emit(row.sound.findData("s1"))
    row.chk_ring.setChecked(True)
    bar = AlarmBar(tab)
    tab.watcher.interval = 0.01
    tab.set_watching(True)
    assert process_events(qapp, lambda: row.t.id in tab.watcher.scores)
    FakeGrabber.frames.append(showing(scene(1), banner()))
    assert process_events(qapp, lambda: host.played == [("s1", True, row.t.id)])
    assert bar.ringing and "Died" in bar.text.text()
    host.play("s2")                             # a pad played on the board meanwhile
    bar.btn_stop.click()
    assert host.ringing() == [] and not bar.ringing
    assert host.played[-1] == ("s2", False, "")   # ...isn't a ring, so it was left alone


def test_a_sound_file_is_added_in_the_background(board, monkeypatch):
    host, tab = board
    tab._new(as_qimage(banner()), "Died")
    row = next(iter(tab.rows.values()))
    monkeypatch.setattr(triggerspanel.QFileDialog, "getOpenFileName",
                        lambda *a, **k: ("C:/sounds/wow.m4a", ""))
    row.sound.activated.emit(row.sound.findData(triggerspanel.FILE))
    assert host.adding and row.state.text() == "Adding the sound…"
    host.finish_adding("s9", "Wow")
    assert row.t.sounds == ["s9"] and host.screen["triggers"][0]["sounds"] == ["s9"]
    assert [c.findChild(triggerspanel.QPushButton, "chipname").text()
            for c in row.chips] == ["Wow"]
    # one the board gives up on is said so, and nothing is added
    row.sound.activated.emit(row.sound.findData(triggerspanel.FILE))
    host.finish_adding(None)
    assert row.t.sounds == ["s9"] and "couldn't be added" in row.state.text()


def test_a_sound_file_the_host_refuses_is_said_so(board, monkeypatch):
    host, tab = board
    tab._new(as_qimage(banner()), "Died")
    row = next(iter(tab.rows.values()))
    said = []
    monkeypatch.setattr(triggerspanel.QMessageBox, "warning", lambda *a: said.append(a[2]))
    monkeypatch.setattr(triggerspanel.QFileDialog, "getOpenFileName",
                        lambda *a, **k: ("C:/sounds/x.txt", ""))
    host.refuse = "x.txt isn't a sound"
    row.sound.activated.emit(row.sound.findData(triggerspanel.FILE))
    assert said == ["x.txt isn't a sound"] and row.t.sounds == []


def test_an_older_board_trigger_loads_as_it_was_saved(qapp, tmp_path, monkeypatch):
    """What Onion Board 1.4 saved in Config.screen (a screen for the default, a
    trigger on screen 2, a sound import that never finished) comes back as it was."""
    monkeypatch.setattr(sw, "monitors", lambda: [Monitor(0, 0, W, H, True),
                                                 Monitor(W, 0, W, H, False)])
    pic = tmp_path / "board" / "triggers" / "old.png"
    pic.parent.mkdir(parents=True)
    as_qimage(banner()).save(str(pic))
    screen = {"on": False, "interval_ms": 250, "monitor": 1, "triggers": [
        {"id": "old", "name": "Died", "images": [str(pic)], "sounds": ["s1", "s2"],
         "pick": "order", "delay": 1.5, "cooldown": 7.0, "threshold": 0.7, "enabled": True,
         "pending": "fp-that-never-arrived", "monitor": 1, "image": str(pic), "sound": "s1"}]}
    host = FakeHost(tmp_path / "board", screen)
    tab = TriggersTab(host)
    try:
        t = tab.triggers[0]
        assert (t.name, t.images, t.sounds, t.pick) == ("Died", [str(pic)], ["s1", "s2"],
                                                        "order")
        assert (t.delay, t.cooldown, t.threshold, t.monitor) == (1.5, 7.0, 0.7, 1)
        assert t.window is None and t.ring is False and t.pending == ""
        assert tab.watcher.default == 1 and tab.watcher.interval == 0.25
    finally:
        tab.shutdown()


def test_the_panel_takes_the_hosts_colours(board):
    host, tab = board
    try:
        theme.use_palette({"accent": "#123456", "made_up": "#000000", 3: "bad"})
        assert theme.T["accent"] == "#123456"
        assert theme.T["bg"] == theme.THEMES[theme.DEFAULT]["bg"]    # one it didn't give
        tab.retheme()
    finally:
        theme.set_current(theme.DEFAULT)
