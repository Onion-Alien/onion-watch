"""+ New trigger: step 1 picks what it watches for (WhatPicker), step 2 where a
picture comes from (paste, drop or choose a file, cut from the game), then the
window and, for a cut or an area, the box. Also the Extra settings pills: each
changed setting shows on the card and its ✕ puts it back. Offscreen, stand-in
windows and pictures only."""
import pytest
from PySide6.QtCore import QMimeData, QPointF, Qt, QUrl
from PySide6.QtGui import QColor, QDropEvent, QImage
from PySide6.QtWidgets import QApplication, QDialog, QPushButton

from onionwatch import screenwatch as sw
from onionwatch.apphost import AppHost
from onionwatch.player import Player
from onionwatch.screenwatch import Monitor, WindowRef
from onionwatch.settings import Config
from onionwatch.sounds import Library
from onionwatch.ui import triggerspanel, whatpick
from onionwatch.ui.triggerspanel import TriggersTab
from onionwatch.ui.whatpick import CUT, FILE, PASTE, WhatPicker

GAME = WindowRef("game.exe", "Realm Online", 0)


def process_events():
    for _ in range(10):
        QApplication.processEvents()


def picture(w=90, h=30) -> QImage:
    img = QImage(w, h, QImage.Format_RGB32)
    img.fill(QColor("#336699"))
    for x in range(0, w, 6):          # some detail, so it's a picture worth matching
        for y in range(h):
            img.setPixelColor(x, y, QColor("#f0e0a0"))
    return img


@pytest.fixture
def tab(qapp, app_dir, monkeypatch):
    monkeypatch.setattr(sw, "monitors", lambda: [Monitor(0, 0, 320, 180, True)])
    monkeypatch.setattr(triggerspanel.QMessageBox, "warning", lambda *a, **k: None)
    monkeypatch.setattr(triggerspanel.QMessageBox, "information", lambda *a, **k: None)
    cfg = Config()
    tab = TriggersTab(AppHost(cfg, lambda: None, Library(cfg.sounds), Player()))
    tab.resize(1000, 700)
    yield tab
    tab.shutdown()
    tab.host.player.close()
    tab.deleteLater()


# ---------------------------------------------------------------- WhatPicker
def test_a_picture_kind_goes_on_to_step_2_and_the_others_are_done(qapp):
    for mode in whatpick.PICTURE_KINDS:
        dlg = WhatPicker()
        dlg._pick(mode)
        assert dlg.page == 1 and dlg.result() != QDialog.Accepted, mode
        assert dlg.pages[1].isVisibleTo(dlg) and not dlg.pages[0].isVisibleTo(dlg)
        dlg._show(0)                    # Back
        assert dlg.page == 0
    for mode, _name, _example in whatpick.kinds():
        if mode in whatpick.PICTURE_KINDS:
            continue
        dlg = WhatPicker()
        dlg._pick(mode)
        assert dlg.result() == QDialog.Accepted and dlg.picked == mode
        assert dlg.source is None


def test_paste_with_nothing_copied_says_so_and_stays_open(qapp):
    qapp.clipboard().clear()
    dlg = WhatPicker()
    dlg._pick("appear")
    dlg._paste()
    assert dlg.result() != QDialog.Accepted and dlg.source is None
    assert "no picture copied" in dlg.tile_paste.line.text()


def test_paste_with_a_picture_copied_is_done(qapp):
    qapp.clipboard().setImage(picture())
    dlg = WhatPicker()
    assert "copied this picture" in dlg.tile_paste.line.text()   # it shows what's copied
    dlg._paste()                        # (Ctrl+V on step 1 does nothing)
    assert dlg.result() != QDialog.Accepted
    dlg._pick("vanish")
    dlg._paste()
    assert dlg.result() == QDialog.Accepted
    assert (dlg.picked, dlg.source) == ("vanish", PASTE)
    qapp.clipboard().clear()


def test_a_picture_file_dropped_on_the_tile_is_used(qapp, tmp_path):
    path = tmp_path / "banner.png"
    picture().save(str(path))
    (tmp_path / "notes.txt").write_text("not a picture")
    dlg = WhatPicker()
    dlg._pick("appear")
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(tmp_path / "notes.txt")),
                  QUrl.fromLocalFile(str(path))])
    ev = QDropEvent(QPointF(10, 10), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
    dlg.tile_drop.dropEvent(ev)
    assert dlg.result() == QDialog.Accepted and dlg.source == FILE
    assert [p.replace("\\", "/") for p in dlg.paths] == [str(path).replace("\\", "/")]


def test_a_picture_dragged_out_of_a_browser_is_used(qapp):
    dlg = WhatPicker()
    dlg._pick("appear")
    mime = QMimeData()
    mime.setImageData(picture())
    dlg.tile_drop.dropEvent(QDropEvent(QPointF(10, 10), Qt.CopyAction, mime, Qt.LeftButton,
                                       Qt.NoModifier))
    assert dlg.source == FILE and dlg.image is not None and not dlg.image.isNull()


# ---------------------------------------------------------------- new_trigger
class FakePicker:
    """WhatPicker as if the user had picked `mode` (and `source`)."""
    answer: dict = {}

    def __init__(self, parent=None, can_paste=False):
        self.picked = FakePicker.answer["mode"]
        self.source = FakePicker.answer.get("source")
        self.paths = FakePicker.answer.get("paths", [])
        self.image = FakePicker.answer.get("image")

    def exec(self):
        return 1


@pytest.fixture
def flow(tab, monkeypatch):
    """new_trigger with every pop-up answered: the window is GAME, a cut is a
    picture, an area pick is noted."""
    monkeypatch.setattr(whatpick, "WhatPicker", FakePicker)
    asked = {"windows": [], "areas": []}

    def pick_window(current=None, heading=""):
        asked["windows"].append(heading)
        return GAME
    monkeypatch.setattr(tab, "pick_window", pick_window)
    monkeypatch.setattr(tab, "_cut", lambda src, threshold=0.0, heading="": (picture(), [], None))
    monkeypatch.setattr(tab, "_pick_area",
                        lambda row, heading="": asked["areas"].append((row.t.mode, heading)))
    return asked


@pytest.mark.parametrize("mode", ["appear", "vanish"])
@pytest.mark.parametrize("source", [PASTE, FILE, CUT])
def test_new_picture_trigger_watches_the_picked_window(tab, flow, monkeypatch, tmp_path,
                                                       mode, source):
    answer = {"mode": mode, "source": source}
    if source == PASTE:
        monkeypatch.setattr(triggerspanel, "copied_picture", picture)
    elif source == FILE:
        path = tmp_path / "Queue pop.png"
        picture().save(str(path))
        answer["paths"] = [str(path)]
    FakePicker.answer = answer
    tab.new_trigger()
    process_events()
    assert len(tab.triggers) == 1
    t = tab.triggers[0]
    assert t.mode == mode and t.sources == [GAME] and len(t.images) == 1
    assert len(flow["windows"]) == 1 and flow["windows"][0].startswith("Step 3")
    if source == FILE:
        assert t.name == "Queue pop"


@pytest.mark.parametrize("mode", ["change", "still", "colour"])
def test_new_area_trigger_watches_the_picked_window(tab, flow, mode):
    FakePicker.answer = {"mode": mode}
    tab.new_trigger()
    process_events()
    assert len(tab.triggers) == 1
    t = tab.triggers[0]
    assert t.mode == mode and t.sources == [GAME] and not t.images
    assert flow["windows"][0].startswith("Step 2")
    # a bar, or the part to watch: step 3 asks for its box; "still" needs none
    assert [m for m, _h in flow["areas"]] == ([mode] if mode != "still" else [])


def test_cancelling_a_step_makes_nothing(tab, flow, monkeypatch):
    FakePicker.answer = {"mode": "appear", "source": CUT}
    monkeypatch.setattr(tab, "pick_window", lambda current=None, heading="": None)
    tab.new_trigger()
    FakePicker.answer = {"mode": "change"}
    tab.new_trigger()
    assert tab.triggers == []


# ---------------------------------------------------------------- Extra settings pills
def test_a_changed_extra_setting_is_a_pill_and_its_x_puts_it_back(tab, flow):
    FakePicker.answer = {"mode": "still"}
    tab.new_trigger()
    process_events()
    t = tab.triggers[0]
    card = tab._card_of(t)
    assert card.rule_chips == []        # a new trigger: nothing changed, no pills
    card.chk_delay.setChecked(True)
    card.delay.setValue(2.0)
    card.chk_quiet.setChecked(True)
    process_events()
    keys = [c.property("rule") for c in card.rule_chips]
    assert keys == ["delay", "quiet"]
    assert t.delay == 2.0 and t.unfocused
    chip = card.rule_chips[0]
    x = next(b for b in chip.findChildren(QPushButton) if b.objectName() == "chipstop")
    x.click()
    process_events()
    assert not card.chk_delay.isChecked() and t.delay == 0
    assert [c.property("rule") for c in card.rule_chips] == ["quiet"]
    assert t.unfocused                  # the other one stays as it was


# ---------------------------------------------------------------- the card's colours
def test_the_card_is_styled_in_the_themes_colours_not_qts_stock_palette(tab, flow):
    """theme.py never sets Qt's palette, so palette(base) is light under a dark theme:
    the sentence's boxes came out white with white words. The card's sheet carries the
    theme's own colours, and takes the new ones when the theme changes."""
    from onionwatch import theme
    was = theme.current_name
    try:
        theme.set_current("Dark")
        FakePicker.answer = {"mode": "still"}
        tab.new_trigger()
        process_events()
        card = tab._card_of(tab.triggers[0])
        sheet = card.styleSheet()
        assert "palette(" not in sheet and theme.T["inset"] in sheet
        theme.set_current("Light")
        tab.retheme()
        assert theme.T["inset"] in card.styleSheet() and "palette(" not in card.styleSheet()
        card.show_rules()               # Extra settings: the theme's panel, not the system's
        assert theme.T["panel"] in card.rules_dlg.styleSheet()
        card.rules_dlg.accept()
    finally:
        theme.set_current(was)


def test_a_click_picks_a_kind_and_continue_goes_on(qapp):
    # one click only picks it (it could be a slip): Continue, or a double-click, goes on
    dlg = WhatPicker()
    assert not dlg.btn_next.isEnabled()
    dlg.tiles[2].click()                       # A bar runs low
    assert dlg.picked == "colour" and dlg.tiles[2].isChecked()
    assert dlg.result() != QDialog.Accepted and dlg.page == 0
    dlg.tiles[0].click()                       # changed my mind: Something shows up
    assert dlg.picked == "appear" and not dlg.tiles[2].isChecked()
    assert dlg.tiles[0].tick.isVisibleTo(dlg) and not dlg.tiles[2].tick.isVisibleTo(dlg)
    assert dlg.page == 0 and dlg.btn_next.isEnabled()
    dlg.btn_next.click()
    assert dlg.page == 1 and not dlg.btn_next.isVisibleTo(dlg)
    dlg._show(0)                               # Back: still picked
    assert dlg.tiles[0].isChecked() and dlg.btn_next.isVisibleTo(dlg)
    dlg2 = WhatPicker()
    dlg2.tiles[3].chosen.emit("change")        # a double-click
    assert dlg2.result() == QDialog.Accepted and dlg2.picked == "change"
