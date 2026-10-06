"""Playing now: what the triggers are playing, each with its own Stop, and Stop
all; and the Log page beside the triggers."""
from onionwatch.ui import triggerspanel
from onionwatch.ui.pages import TriggerPages

from test_categories import make, raw  # noqa: F401  (the fixture, and its triggers)


def fire(tab, tid):
    tab._fire(tid, tab._gen)


def test_the_bar_names_what_plays_and_stops_one_or_all(make):  # noqa: F811
    tab = make({"triggers": [raw(1), raw(2), raw(3, ring=True)]})
    host, now, stopped = tab.host, set(), set()
    play, stop = host.play, host.stop_tag

    def play_(sid, loop=False, tag=""):
        now.add(tag)
        return play(sid, loop, tag)

    def stop_tag(tag):
        now.discard(tag)
        stopped.add(tag)
        stop(tag)
    host.play, host.stop_tag, host.playing = play_, stop_tag, lambda: list(now)
    pages = TriggerPages(tab)
    bar = pages.playing
    assert bar.title.text() == "Nothing playing" and not bar.btn_stop_all.isEnabled()
    fire(tab, "t1")
    fire(tab, "t2")
    fire(tab, "t3")
    names = [bar.chips.itemAt(i).widget().text() for i in range(bar.chips.count())]
    assert names == ["Trigger 1", "Trigger 2", "Trigger 3 (ringing)"]
    assert bar.title.text() == "Playing now:" and bar.btn_stop_all.isEnabled()
    bar.chips.itemAt(0).widget().click()                 # Trigger 1's Stop
    assert [t.id for t, _r in tab.playing_now()] == ["t2", "t3"]
    assert "t1/s1" not in now
    bar.btn_stop_all.click()
    assert tab.playing_now() == [] and tab.host.ringing() == []
    assert bar.title.text() == "Nothing playing"
    pages.deleteLater()


def test_a_sound_that_ends_leaves_the_bar(make):  # noqa: F811
    tab = make({"triggers": [raw(1)]})
    tab.host.playing = lambda: list(tab.host.now)
    tab.host.now = ["t1/s1"]
    fire(tab, "t1")
    assert [t.id for t, _r in tab.playing_now()] == ["t1"]
    tab.host.now = []                                   # it finished by itself
    assert tab.playing_now() == []


def test_a_host_that_cant_say_counts_it_playing_a_while(make, monkeypatch):  # noqa: F811
    tab = make({"triggers": [raw(1)]})
    assert not hasattr(tab.host, "playing")             # an older Onion Board
    fire(tab, "t1")
    assert [t.id for t, _r in tab.playing_now()] == ["t1"]
    monkeypatch.setattr(triggerspanel, "GUESS_PLAYING_S", 0)
    assert tab.playing_now() == []


def test_the_log_page_follows_what_went_off(make, tmp_path):  # noqa: F811
    from PySide6.QtGui import QImage
    tab = make({"triggers": [raw(1)]})
    pages = TriggerPages(tab)
    tab.pages = pages
    assert pages.tabs.tabText(1) == "Log" and pages.log.empty.isVisibleTo(pages.log)
    tab.history.append(triggerspanel.Alert(0.0, "Rare spawn", "Game", 0.93, "appear",
                                           QImage()))
    tab.history_changed.emit()
    assert pages.tabs.tabText(1) == "Log (1)" and pages.log.list.count() == 1
    tab.show_history()                                  # More → What went off…
    assert pages.stack.currentIndex() == 1
    out = tmp_path / "log.txt"
    pages.log.save(str(out))
    assert "Rare spawn: showed up in Game, 93%" in out.read_text(encoding="utf-8")
    pages.deleteLater()


def test_log_pictures_are_small_colour_copies_of_the_grab():
    import numpy as np
    from onionwatch import screenwatch as sw
    px = np.zeros((1080, 1920, 4), np.uint8)
    px[..., 2] = 200                                   # BGRA: red
    out = sw.log_rgb((px, sw.FMT_BGRA8, 2))
    assert out.shape == (270, 480, 3) and out.dtype == np.uint8
    assert tuple(out[0, 0]) == (200, 0, 0)
    assert sw.log_rgb(None) is None


def test_colour_log_pictures_can_be_switched_off_and_stay_so(make, qapp):  # noqa: F811
    from onionwatch.ui.watching import WatchingDialog
    tab = make({"triggers": [raw(1)]})
    assert tab.watcher.color_hits                     # on by default
    dlg = WatchingDialog(tab)
    dlg.color_log.setChecked(False)
    assert not tab.watcher.color_hits and tab.host.screen["color_log"] is False
    dlg.reject()
    again = make(dict(tab.host.screen))
    assert not again.watcher.color_hits
