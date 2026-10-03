"""Onion Watch as Onion Board's add-on (onionwatch.board): create() refuses a host it
can't run in, and the tab it gives back rings through the board, says so with the
board's notification and stops with the board's Stop all. Stand-in screens and a
stand-in board; nothing is heard."""
import pytest
from conftest import process_events
from fakehost import FakeHost
from test_ui import FakeGrabber, W, H, as_qimage, banner, scene, showing

from onionwatch import board, theme
from onionwatch import screenwatch as sw
from onionwatch.host import API_VERSION
from onionwatch.screenwatch import Monitor


@pytest.fixture
def tab(qapp, tmp_path, monkeypatch):
    monkeypatch.setattr(sw, "monitors", lambda: [Monitor(0, 0, W, H, True)])
    monkeypatch.setattr(sw, "open_grabber", FakeGrabber)
    monkeypatch.setattr(sw, "WORK_WIDTH", W)
    FakeGrabber.frames = [scene(1)]
    host = FakeHost(tmp_path / "board")
    tab = board.create(host)
    yield tab
    tab.shutdown()
    theme.set_current(theme.DEFAULT)


def test_a_host_it_cannot_run_in_is_refused_with_a_reason(tmp_path):
    old = FakeHost(tmp_path)
    old.api_version = API_VERSION - 1
    with pytest.raises(board.IncompatibleHost, match="needs a newer Test Board"):
        board.create(old)
    with pytest.raises(board.IncompatibleHost, match="isn't a triggers host"):
        board.create(object())


def test_it_takes_the_boards_colours_now_and_when_they_change(tab):
    assert theme.T["accent"] == "#123456"
    tab.host.colours = {"accent": "#abcdef"}
    tab.retheme()
    assert theme.T["accent"] == "#abcdef"


def test_a_ringing_trigger_notifies_and_stop_all_stops_it(tab, qapp):
    host, panel = tab.host, tab.panel
    active = []
    tab.active_changed.connect(active.append)
    panel._new(as_qimage(banner()), "Rare")
    row = next(iter(panel.rows.values()))
    row.sound.activated.emit(row.sound.findData("s2"))
    row.chk_ring.setChecked(True)
    panel.watcher.interval = 0.01
    panel.set_watching(True)
    assert active == [True] and tab.is_active()
    assert process_events(qapp, lambda: row.t.id in panel.watcher.scores)
    FakeGrabber.frames.append(showing(scene(1), banner()))
    assert process_events(qapp, lambda: host.ringing() == [row.t.id])
    assert host.notes == [("Rare", "It just showed up. Ringing until the game moves.")]
    assert tab.alarm.ringing
    tab.cancel_pending()                    # the board's Stop all
    assert host.ringing() == [] and not tab.alarm.ringing


def test_the_board_is_told_what_it_may_squeeze(tab):
    parts = tab.fit_parts()
    assert set(parts) == {"hint", "watch", "cut", "add", "paste", "interval_label"}
    tab.panel.btn_watch.setProperty("compact", True)   # the board shows it icon only
    tab.panel.btn_watch.setText("")
    tab.panel.set_watching(False)
    assert tab.panel.btn_watch.text() == ""
    assert tab.panel.btn_watch.property("full_text") == "Start watching"


def test_the_board_can_reach_the_more_menu(tab):
    """Onion Board puts "Remove Onion Watch…" last in the add-on's More menu."""
    assert tab.btn_more is tab.panel.btn_more and tab.btn_more.menu() is not None
