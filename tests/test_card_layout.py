"""The trigger card: a header that opens to a sentence ("When … in … / Play …"),
the rules it has on as chips and the rules themselves. New cards open; at start the
cards are closed (one alone stays open); a click on the header opens and closes it;
a bar's level is shown in the sentence, a picture's match in the rules; a narrow card drops its
thumbnail; and a row that wraps takes the height it needs."""
import test_ui
from test_ui import as_qimage, banner

from PySide6.QtWidgets import QPushButton

from onionwatch.ui.triggers.cardkit import FlowBox

fake_screen, tab = test_ui.fake_screen, test_ui.tab   # the same stand-ins


def new_card(tab):
    tab._new(as_qimage(banner()), "Rare")
    return list(tab.rows.values())[-1]


def test_a_new_card_opens_and_its_header_closes_it(tab, qapp):
    row = new_card(tab)
    assert row.is_open and row.btn_open.isChecked()
    row.btn_open.click()
    assert not row.is_open and row.body.isHidden()
    row.set_open(True)
    assert row.is_open and row.btn_open.isChecked()


def test_the_rules_it_has_on_are_chips_with_a_cross_each(tab):
    row = new_card(tab)
    assert not row.rules_dlg.isVisible()    # the extra settings: in a pop-up, shut
    assert row._rules() == [] and not row.rule_chips      # all left as they come
    assert row.rules_box.flow.itemAt(0).widget() is row.btn_tune
    row.chk_ring.setChecked(True)       # (the sentence says the ringing)
    assert row._rules() == []
    row.chk_quiet.setChecked(True)
    row.chk_size.setChecked(False)
    row.cooldown.setValue(10)
    assert not row.delay.isEnabled()    # a number only while its box is ticked
    row.chk_delay.setChecked(True)
    assert row.delay.value() == 1.0 and row.delay.isEnabled() and row.t.delay == 1.0
    assert row._tune_summary() == ("Exact size only · Wait 1 s before playing · "
                                   "Rest 10 s after playing · Quiet while you're in the window")
    assert len(row.rule_chips) == 4
    row.btn_tune.click()
    assert not row.tune.isHidden() and len(row.rule_chips) == 4   # the same, open or not
    row.rule_chips[1].findChild(QPushButton, "chipstop").click()  # its ✕ takes it off
    assert row.t.delay == 0 and not row.chk_delay.isChecked() and not row.delay.isEnabled()
    row.chk_cooldown.setChecked(False)          # no rest at all is a rule of its own
    assert row.t.cooldown == 0 and "No rest after playing" in row._tune_summary()
    for chip in list(row.rule_chips):
        chip.findChild(QPushButton, "chipstop").click()
    assert row._rules() == [] and row.t.any_size and not row.t.unfocused
    assert row.t.cooldown == 3.0 and row.chk_cooldown.isChecked()


def test_a_bars_level_is_under_watch_for_a_pictures_match_in_fine_tune(tab, monkeypatch):
    monkeypatch.setattr(tab, "_pick_area", lambda r: None)   # it asks for the bar
    row = new_card(tab)
    assert row._in[row.match_box] is row._tune_row
    row.mode.setCurrentIndex(row.mode.findData("colour"))
    row._on_mode(row.mode.currentIndex())
    assert row._in[row.match_box] is row._watch_row
    assert not row._tune_summary().startswith("Match")       # not said twice
    row.mode.setCurrentIndex(row.mode.findData("still"))
    row._on_mode(row.mode.currentIndex())
    assert row._in[row.hold_box] is row._watch_row           # how long nothing moves


def test_a_narrow_card_drops_its_thumbnail(tab, qapp):
    row = new_card(tab)
    tab.resize(800, 600)
    tab.show()
    qapp.processEvents()
    assert row.strip.isVisibleTo(row)
    tab.resize(300, 600)
    for _ in range(8):     # Duplicate / Delete shorten first, then it narrows
        qapp.processEvents()
    assert row.width() < row.NARROW and not row.strip.isVisibleTo(row)
    tab.hide()


def test_a_row_that_wraps_takes_the_height_it_needs(qapp):
    from PySide6.QtWidgets import QPushButton
    box = FlowBox(gap=6)
    for i in range(8):
        box.flow.addWidget(QPushButton(f"Button number {i}"))
    box.resize(900, 10)
    box._fit()
    one = box.minimumHeight()
    box.resize(250, 10)
    box._fit()
    assert box.minimumHeight() > 2 * one


def test_a_thumbnail_opens_its_picture_big(tab, monkeypatch):
    from onionwatch.ui.triggers import viewer
    seen = []
    monkeypatch.setattr(viewer.PictureViewer, "open",
                        lambda self: seen.append((self.index, list(self.paths))) or 0)
    row = new_card(tab)
    tab._add_pictures(row.t, [as_qimage(banner()[:, ::-1])])
    row.strip.thumbs[1].pic.click()
    assert seen == [(1, row.t.images)]


def test_the_viewer_goes_round_and_takes_pictures_off(tab, qapp):
    from onionwatch.ui.triggers.viewer import PictureViewer
    row = new_card(tab)
    tab._add_pictures(row.t, [as_qimage(banner()[:, ::-1]), as_qimage(banner()[::-1])])
    v = PictureViewer("x", lambda: row.t.images, 2,
                      remove=lambda i: tab._remove_picture(row, i))
    assert v.index == 2 and len(v.tiles) == 3
    v.go(3)
    assert v.index == 0 and v.tiles[0].isChecked()
    v.go(-1)
    assert v.index == 2
    v._remove()
    assert len(row.t.images) == 2 and len(v.paths) == 2 and v.index == 1
    v._remove()
    v._remove()
    assert not row.t.images and v.result() == v.DialogCode.Accepted   # nothing left: it closes
    v.deleteLater()


def test_a_small_picture_is_shown_in_whole_pixels(qapp):
    from onionwatch.ui.triggers.viewer import MAX_ZOOM, PictureView
    pv = PictureView()
    pv.resize(800, 600)
    pv.set_image(as_qimage(banner()))       # 90 × 30
    assert pv.zoom() == 8
    pv.set_image(as_qimage(banner()[:4, :4]))
    assert pv.zoom() == MAX_ZOOM


def test_closed_card_switch_is_centered_beside_picture(tab, qapp):
    row = new_card(tab)
    row.set_open(False)
    tab.resize(1100, 650)
    tab.show()
    for _ in range(6):
        qapp.processEvents()
    picture = row.strip.thumbs[0].pic
    middle = picture.mapTo(row, picture.rect().center()).y()
    control = row.chk_on
    assert abs(control.mapTo(row, control.rect().center()).y() - middle) <= 1
    # beside the editor a click picks the card: no open / close arrow on it
    assert tab.split and row.btn_open.isHidden()
    tab.resize(600, 650)
    for _ in range(6):
        qapp.processEvents()
    assert not tab.split and not row.btn_open.isHidden()
    assert {label.contentsMargins().left()
            for label in (row.state, row.sound_summary, row.details)} == {6}


def test_closed_cards_are_tiles_side_by_side_an_open_one_the_whole_width(tab, qapp):
    rows = [new_card(tab) for _ in range(4)]
    tab.set_list_view(False)
    for r in rows:
        r.set_open(False)
    rows[2].set_open(True)
    tab.resize(1000, 2000)
    tab.show()
    for _ in range(8):
        qapp.processEvents()
    a, b, c, d = (r.geometry() for r in rows)            # 1000 px: three tiles a line
    assert a.y() == b.y() and b.x() > a.right()          # tiles side by side
    assert d.y() == a.y() and d.x() > b.right()          # the one after the open card
    #                                                      fills the line: none cut short
    assert a.width() < c.width() and c.y() > a.bottom()  # the open one under it, wider
    assert rows[2].names.y() < rows[2].body.y()          # its header on one line
    assert rows[0].names.y() > rows[0].chk_on.y()        # a tile's name under its switch
    tab.hide()
