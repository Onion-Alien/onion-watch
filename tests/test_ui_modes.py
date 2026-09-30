# ruff: noqa: F811 - the fixtures come from test_ui
"""The triggers page's newer parts, offscreen: a card switched to another kind of
trigger shows its own controls, a trigger without a picture goes off and lands in
the history with a picture of the moment, one card looks in several windows, the
area and bar dialog, Duplicate, saving triggers to a file and loading them back,
and the window picker's "every copy". Stand-in captures only; nothing is heard."""
import numpy as np
from conftest import process_events
from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtGui import QColor, QImage
from test_ui import (H, W, FakeGrabber, as_qimage, banner, fake_screen, scene,  # noqa: F401
                     showing, tab)

from onionwatch import packs, windows
from onionwatch import screenwatch as sw
from onionwatch.screenwatch import WindowRef
from onionwatch.ui import snip
from onionwatch.ui.history import HistoryDialog, alert_text

GAME = WindowRef("game.exe", "Game", 0)
GAME2 = WindowRef("game.exe", "Game", 1)


def picture_row(tab):
    tab._new(as_qimage(banner()), "Rare")
    return next(iter(tab.rows.values()))


def test_switching_the_kind_of_trigger_shows_its_controls(tab):
    row = picture_row(tab)
    assert row.pictures_box.isVisibleTo(row) and not row.badge.isVisibleTo(row)
    assert row.lbl_number.text() == "Match" and row.threshold.value() == 80
    row.mode.setCurrentIndex(row.mode.findData("change"))
    row.mode.activated.emit(row.mode.currentIndex())
    t = row.t
    assert t.mode == "change" and t.level == 0.05
    assert not row.pictures_box.isVisibleTo(row) and row.badge.isVisibleTo(row)
    assert row.lbl_number.text() == "Changes over" and row.threshold.value() == 5
    assert tab.host.screen["triggers"][0]["mode"] == "change"
    row.threshold.setValue(12)
    assert t.level == 0.12 and t.threshold == 0.8          # the picture's number is kept
    row.mode.setCurrentIndex(row.mode.findData("still"))
    row.mode.activated.emit(row.mode.currentIndex())
    assert t.hold == 10.0 and row.lbl_hold.text() == "Still for"
    assert "nothing has moved for 10 s" in row.state.text()


def test_a_bar_trigger_asks_for_its_bar(tab, monkeypatch):
    row = picture_row(tab)
    asked = []
    row.area_wanted.connect(asked.append)
    monkeypatch.setattr(tab, "_pick_area", lambda r: None)
    row.mode.setCurrentIndex(row.mode.findData("colour"))
    row.mode.activated.emit(row.mode.currentIndex())
    assert asked == [row] and row.below.isVisibleTo(row)
    assert row.state.text().startswith("Pick the bar")
    assert not tab.ready(row.t)
    row.t.colour, row.t.region = "#cc2020", (0.1, 0.1, 0.3, 0.05)
    assert tab.ready(row.t)


def test_a_trigger_without_a_picture_goes_off_and_is_in_the_history(tab, qapp, monkeypatch):
    monkeypatch.setattr(sw, "CHANGE_GAP", 0.02)
    tab.add_area_trigger()
    t = tab.triggers[-1]
    assert t.mode == "still" and t.images == [] and tab.ready(t)
    row = tab.rows[t.id]
    row.hold.setValue(0.2)
    fired = []
    tab.fired.connect(fired.append)
    tab.watcher.interval = 0.01
    tab.set_watching(True)
    assert process_events(qapp, lambda: fired == [t])
    assert tab.alert_text(t) == "Nothing has moved for a while."
    a = tab.history[-1]
    assert a.name == t.name and a.mode == "still" and a.place == "the screen"
    assert (a.picture.width(), a.picture.height()) == (W, H)
    dlg = HistoryDialog(tab)
    assert dlg.list.count() == 1 and "stood still in the screen" in alert_text(a)
    dlg._clear()
    assert not tab.history and dlg.empty.isVisibleTo(dlg)
    dlg.reject()


def test_one_card_looks_in_several_windows(tab, monkeypatch):
    row = picture_row(tab)
    monkeypatch.setattr(tab, "pick_places", lambda current: [0, GAME, GAME2])
    tab._pick_for(row)
    assert row.t.sources == [0, GAME, GAME2]
    assert row.where.currentText() == "3 places"
    raw = tab.host.screen["triggers"][0]
    assert raw["windows"] == [GAME.to_raw(), GAME2.to_raw()] and raw["screens"] == [0]
    assert "in 3 places" in row.state.text()
    row.where.setCurrentIndex(0)                    # "Same as below"
    row.where.activated.emit(0)
    assert row.t.sources == []


def test_the_area_is_dragged_on_the_window(tab, monkeypatch):
    row = picture_row(tab)
    px = np.zeros((H, W, 4), np.uint8)
    px[..., 3] = 255
    monkeypatch.setattr(windows, "find", lambda r, wins=None: windows.WindowInfo(
        7, "Game", "game.exe", 7, 0, W, H))
    monkeypatch.setattr(windows, "snapshot", lambda hwnd: px)

    def fake_exec(dlg):
        dlg.view.selection = QRect(W // 2, 0, W // 2, H // 2)
        dlg._accept()
        return True
    monkeypatch.setattr(snip.AreaDialog, "exec", fake_exec)
    row.t.sources = [GAME]
    tab._pick_area(row)
    assert row.t.region == (0.5, 0.0, 0.5, 0.5) and row.btn_area.text() == "Area: part"
    assert tab.host.screen["triggers"][0]["region"] == [0.5, 0.0, 0.5, 0.5]


def test_the_bar_dialog_finds_the_bar_colour(qapp):
    img = QImage(200, 100, QImage.Format_RGB32)
    img.fill(QColor(20, 20, 40))
    for x in range(10, 150):
        for y in range(10, 20):
            img.setPixelColor(x, y, QColor(200, 30, 30))
    dlg = snip.AreaDialog(img, "Game", colour="")
    dlg.view.selection = QRect(10, 10, 180, 10)     # the bar's full length, 140 of it red
    dlg._update()
    assert dlg.colour == "#c81e1e"
    dlg._picked(snip.QPoint(5, 50))                 # a click picks another
    assert dlg.colour == "#141428"
    dlg._accept()
    assert dlg.region == (0.05, 0.1, 0.9, 0.1)
    assert snip.to_region(QRect(0, 0, 200, 100), QSize(200, 100)) is None   # all of it


def test_duplicate_copies_the_trigger_and_its_pictures(tab):
    row = picture_row(tab)
    row.t.sources = [GAME]
    tab._duplicate(row)
    a, b = tab.triggers
    assert b.name == "Rare (copy)" and b.id != a.id and b.sources == [GAME]
    assert len(b.images) == 1 and b.images != a.images
    assert QImage(b.images[0]).size() == QImage(a.images[0]).size()
    assert tab.list_layout.indexOf(tab.rows[b.id]) == tab.list_layout.indexOf(row) + 1


def test_triggers_are_saved_to_a_file_and_loaded_back(tab, tmp_path):
    row = picture_row(tab)
    row.t.mode, row.t.sources = "vanish", [GAME]
    tab.add_area_trigger()
    path = tmp_path / "pack.zip"
    assert packs.write_pack(path, tab.triggers, dict(tab.host.sounds())) == 1
    found = packs.read_pack(path)
    assert [t.mode for t, _p, _s in found] == ["vanish", "still"]
    before = {t.id for t in tab.triggers}
    assert tab.add_pack(found) == 2
    new = [t for t in tab.triggers if t.id not in before]
    assert new[0].mode == "vanish" and new[0].sources == [GAME] and len(new[0].images) == 1
    assert new[0].images[0] != row.t.images[0]
    assert new[0].sounds == row.t.sounds                     # the same sound, by id
    bad = tmp_path / "bad.zip"
    bad.write_bytes(b"not a zip")
    try:
        packs.read_pack(bad)
    except packs.PackError as e:
        assert "isn't a trigger pack" in str(e)
    else:
        raise AssertionError("a bad pack was read")


def test_the_picker_ticks_several_places_and_every_copy(qapp, monkeypatch):
    wins = [windows.WindowInfo(1, "Game", "game.exe", 1, 100, W, H),
            windows.WindowInfo(2, "Game", "game.exe", 2, 200, W, H),
            windows.WindowInfo(3, "Notes", "notepad.exe", 3, 50, W, H)]
    monkeypatch.setattr(windows, "list_windows", lambda: list(wins))
    monkeypatch.setattr(windows, "snapshot", lambda hwnd: None)
    monkeypatch.setattr(sw, "monitors", lambda: [sw.Monitor(0, 0, W, H, True)])
    from onionwatch.ui.windowpicker import WindowPicker
    dlg = WindowPicker(None, [GAME2], multi=True)
    items = [dlg.list.item(i) for i in range(dlg.list.count())]
    screens = [it for it in items if isinstance(it.data(Qt.UserRole), int)]
    assert len(screens) == 1                         # the fake screen
    assert dlg._ticked() == [GAME2]
    first = next(it for it in items if it.data(Qt.UserRole) == GAME)
    dlg.list.setCurrentItem(first)
    dlg.chk_every.setChecked(True)
    assert dlg._ticked() == [WindowRef("game.exe", "Game", 0, True)]   # copy 2 is in it
    screens[0].setCheckState(Qt.Checked)
    dlg._accept()
    assert dlg.places == [0, WindowRef("game.exe", "Game", 0, True)]
    # reopened with that, the every-copy tick is shown on the first copy
    again = WindowPicker(None, dlg.places, multi=True)
    assert again._ticked() == [0, WindowRef("game.exe", "Game", 0, True)]


def test_the_picker_keeps_a_ticked_window_that_is_not_open(qapp, monkeypatch):
    monkeypatch.setattr(windows, "list_windows", lambda: [])
    monkeypatch.setattr(sw, "monitors", lambda: [])
    from onionwatch.ui.windowpicker import WindowPicker
    dlg = WindowPicker(None, [GAME2], multi=True)
    assert dlg._ticked() == [GAME2] and "not open now" in dlg.list.item(
        dlg.list.count() - 1).text()


def test_a_card_says_which_window_went_off(tab, qapp, monkeypatch):
    row = picture_row(tab)
    t = row.t
    frames = {GAME: scene(1), GAME2: showing(scene(2), banner())}

    class Grab:
        def __init__(self, ref, w, h):
            self.ref, self.w, self.h, self.source = ref, W, H, (W, H)

        def resize(self, w, h):
            pass

        def grab(self):
            return frames[self.ref]

        def close(self):
            pass
    monkeypatch.setattr(tab.watcher, "_window_grabber", Grab)
    monkeypatch.setattr(sw, "WINDOW_RETRY_S", 0.05)
    t.sources = [GAME, GAME2]
    tab._store()
    fired = []
    tab.fired.connect(fired.append)
    tab.watcher.interval = 0.01
    tab.set_watching(True)
    assert process_events(qapp, lambda: fired == [t])
    assert tab.alert_text(t) == "It just showed up in Game (copy 2)."
    assert tab.history[-1].place == "Game (copy 2)"
