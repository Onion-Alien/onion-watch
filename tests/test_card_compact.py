"""Compact cards: a closed card is a short tile (a small thumbnail, the name over
one line: how it's doing and what it plays, or what's wrong; the switch), a
card is dragged to another place or category, picture files dropped on a card are
added to it, and the check speed of triggers on "Default" is picked under ⚙ (each
card says what Default is)."""
from PySide6.QtCore import QMimeData, QPoint, QPointF, QSize, Qt, QUrl
from PySide6.QtGui import QDropEvent, QEnterEvent, QMouseEvent
from PySide6.QtWidgets import QPushButton

import test_ui
from test_ui import as_qimage, banner

from onionwatch import screenwatch as sw
from onionwatch.ui.triggerspanel import TILE_THUMB, TriggerRow, TriggersTab

fake_screen, tab, styled = test_ui.fake_screen, test_ui.tab, test_ui.styled


def cards(tab, n):
    for i in range(n):
        tab._new(as_qimage(banner()), f"Card {i}")
    rows = list(tab.rows.values())
    for r in rows:
        r.set_open(False)
    return rows


def settle(qapp, tab, w=1000, h=900):
    tab.resize(w, h)
    tab.show()
    for _ in range(8):
        qapp.processEvents()


def test_a_closed_card_is_a_short_tile(tab, qapp, styled):
    a, b = cards(tab, 2)
    tab.set_list_view(False)        # an open card in the list (the list view: test_split)
    b.set_open(True)
    settle(qapp, tab)
    assert a.height() <= 80 < b.height()
    assert a.strip.thumb == TILE_THUMB and len(a.strip.thumbs) == 1
    # the name is read, not typed in; the + is on the thumbnail while the mouse is over it
    assert a.title.isVisibleTo(a) and not a.name.isVisibleTo(a)
    assert a.title.text() == "Card 0" and b.name.isVisibleTo(b)
    assert not a.btn_add_pic.isVisibleTo(a) and b.btn_add_pic.isVisibleTo(b)
    thumb = a.strip.thumbs[0]
    thumb.enterEvent(QEnterEvent(QPointF(5, 5), QPointF(5, 5), QPointF(5, 5)))
    assert thumb.plus.isVisibleTo(a) and not thumb.x.isVisibleTo(a)
    # one line under the name, starting where the name does: how it's doing and what
    # it plays, or what's wrong
    assert a.live.styleSheet() == "" and "Ready" in a.live.text()
    assert a.live.isVisibleTo(a) and a.sound_summary.isVisibleTo(a)
    assert not a.state.isVisibleTo(a)
    assert abs(a.live.geometry().center().y() - a.names.geometry().center().y()) <= 3
    assert a.live.mapTo(a, QPoint(0, 0)).x() == a.title.mapTo(a, QPoint(0, 0)).x()
    a.t.sounds.clear()
    a.set_sounds(a._sounds)
    for _ in range(4):
        qapp.processEvents()
    assert a.state.isVisibleTo(a) and not a.sound_summary.isVisibleTo(a)
    assert not a.live.isVisibleTo(a) and "sound" in a.state.text()
    assert a.state.mapTo(a, QPoint(0, 0)).x() == a.title.mapTo(a, QPoint(0, 0)).x()
    tab.hide()


def test_a_card_without_a_picture_has_a_slot_to_add_one(tab, qapp):
    a, = cards(tab, 1)
    a.t.images.clear()
    a.refresh_pictures()
    settle(qapp, tab)
    assert a.btn_add_pic.isVisibleTo(a) and not a.strip.isVisibleTo(a)
    assert a.btn_add_pic.size() == TILE_THUMB + QSize(8, 8)
    tab.hide()


def test_cards_per_row_is_picked_and_kept(tab, qapp):
    rows = cards(tab, 7)
    tab.cb_per_row.setCurrentIndex(tab.cb_per_row.findData(0))
    tab.cb_per_row.activated.emit(tab.cb_per_row.currentIndex())    # cards, not a list
    settle(qapp, tab, w=1400)
    grid = tab.sections[""].body_layout

    def across():
        for _ in range(8):
            qapp.processEvents()
        return sum(r.y() == rows[0].y() for r in rows)
    assert across() == grid.columns(grid.geometry().width()) == 4     # as many as fit
    tab.cb_per_row.setCurrentIndex(tab.cb_per_row.findData(6))
    tab.cb_per_row.activated.emit(tab.cb_per_row.currentIndex())
    assert across() == 6 and tab.host.screen["cards_per_row"] == 6
    assert all(not r.btn_open.visibleRegion().isEmpty() for r in rows)
    tab.cb_per_row.setCurrentIndex(tab.cb_per_row.findData(2))
    tab.cb_per_row.activated.emit(tab.cb_per_row.currentIndex())
    assert across() == 2
    tab.resize(400, 900)                # too narrow for two: still readable
    assert across() == 1
    again = TriggersTab(tab.host)
    again.shutdown()
    assert again.per_row == 2 and again.cb_per_row.currentData() == 2
    tab.host.screen["cards_per_row"] = "lots"       # nonsense in the file: Auto
    again = TriggersTab(tab.host)
    again.shutdown()
    assert again.per_row == 0
    tab.hide()


def test_advanced_cards_show_their_text_in_full(tab, qapp):
    a, b = cards(tab, 2)
    a.name.setText("A trigger with a name far too long to fit on one line of a tile")
    settle(qapp, tab, w=700)
    short = a.height()
    assert a.title.wordWrap() is False and a.title.toolTip() == a.name.text()
    tab.chk_advanced.setChecked(True)
    for _ in range(8):
        qapp.processEvents()
    assert a.title.wordWrap() and a.details.isVisibleTo(a) and a.height() > short
    assert a.details.mapTo(a, QPoint(0, 0)).x() == a.title.mapTo(a, QPoint(0, 0)).x()
    assert tab.host.screen["advanced_cards"] is True
    tab.chk_advanced.setChecked(False)
    for _ in range(8):
        qapp.processEvents()
    assert a.height() == short
    tab.hide()


def test_a_tile_shows_one_picture_and_how_many_more(tab, qapp):
    row, = cards(tab, 1)
    row.t.images = row.t.images * 4
    row.refresh_pictures()
    assert len(row.strip.thumbs) == 1 and row.strip.thumbs[0].more.text() == "+3"
    row.set_open(True)
    assert len(row.strip.thumbs) == 4 and row.strip.thumbs[0].more.isHidden()


def test_the_live_state_says_off_when_switched_off(tab):
    row, = cards(tab, 1)
    row.chk_on.setChecked(False)
    row.show_score(None)
    assert "Off" in row.live.text()
    row.chk_on.setChecked(True)
    row.show_score(0.97)
    assert "97%" in row.live.text() and "<b>" in row.live.text()   # it would go off


def test_the_plus_adds_a_picture_three_ways(tab, qapp):
    row, = cards(tab, 1)
    got = []
    for signal in (row.cut_wanted, row.pictures_wanted, row.paste_wanted):
        signal.disconnect()         # not the tab's: they'd open a file dialog, a cut...
    row.cut_wanted.connect(lambda r: got.append("cut"))
    row.pictures_wanted.connect(lambda r: got.append("files"))
    row.paste_wanted.connect(lambda r: got.append("paste"))
    qapp.clipboard().clear()
    menu = row._add_menu()
    acts = menu.actions()
    assert [a.text() for a in acts] == ["Cut from window…", "Picture files…",
                                        "Paste the copied picture"]
    assert not acts[2].isEnabled()          # nothing copied
    acts[0].trigger()
    acts[1].trigger()
    qapp.clipboard().setImage(as_qimage(banner()))
    row._add_menu().actions()[2].trigger()
    assert got == ["cut", "files", "paste"]


def test_picture_files_dropped_on_a_card_are_added(tab, tmp_path):
    row, = cards(tab, 1)
    path = tmp_path / "plate.png"
    as_qimage(banner()[:20, :40]).save(str(path))
    other = tmp_path / "notes.txt"
    other.write_text("x")
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(path)), QUrl.fromLocalFile(str(other))])
    assert TriggerRow.picture_files(mime) == [str(path).replace("\\", "/")]
    ev = QDropEvent(QPointF(10, 10), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
    row.dropEvent(ev)
    assert len(row.t.images) == 2 and len(tab.host.screen["triggers"][0]["images"]) == 2


def test_a_click_opens_and_a_drag_picks_the_card_up(tab, monkeypatch):
    row, = cards(tab, 1)
    picked = []
    monkeypatch.setattr(row, "drag", lambda: picked.append(row))

    def ev(kind, x, y, buttons=Qt.LeftButton):
        p = QPointF(x, y)
        return QMouseEvent(kind, p, row.mapToGlobal(p), Qt.LeftButton, buttons,
                           Qt.NoModifier)
    row.mousePressEvent(ev(QMouseEvent.MouseButtonPress, 150, 90))
    row.mouseReleaseEvent(ev(QMouseEvent.MouseButtonRelease, 150, 90, Qt.NoButton))
    assert row.is_open and not picked
    row.set_open(False)
    row.mousePressEvent(ev(QMouseEvent.MouseButtonPress, 150, 90))
    row.mouseMoveEvent(ev(QMouseEvent.MouseMove, 190, 95))
    row.mouseReleaseEvent(ev(QMouseEvent.MouseButtonRelease, 190, 95, Qt.NoButton))
    assert picked == [row] and not row.is_open      # a drag doesn't open it


def test_a_card_is_moved_before_another_and_the_order_is_kept(tab):
    a, b, c = cards(tab, 3)
    tab.reorder(c.t.id, "", a.t.id)
    assert [t.name for t in tab.triggers] == ["Card 2", "Card 0", "Card 1"]
    assert [d["name"] for d in tab.host.screen["triggers"]] == ["Card 2", "Card 0", "Card 1"]
    sec = tab.sections[""]
    assert sec._cards() == [c, a, b]
    tab.reorder(c.t.id, "", None)                  # after the last
    assert sec._cards() == [a, b, c]
    again = TriggersTab(tab.host)                  # the next start reads it back
    again.shutdown()
    assert [t.name for t in again.triggers] == ["Card 0", "Card 1", "Card 2"]


def test_a_card_dragged_to_another_category_moves_there(tab):
    a, b = cards(tab, 2)
    tab.groups.ensure("Raids")
    tab._layout_sections()
    tab.reorder(a.t.id, "Raids", None)
    assert a.t.category == "Raids" and tab.host.screen["trigger_categories"] == {
        a.t.id: "Raids"}


def test_where_a_dragged_card_lands(tab, qapp):
    a, b, c = cards(tab, 3)
    settle(qapp, tab)
    sec = tab.sections[""]

    def at(row, dx):
        g = row.geometry().translated(sec.body.pos())
        return QPoint(g.center().x() + dx, g.center().y())
    assert sec.drop_spot(at(b, -20))[0] == b.t.id      # left half: before it
    assert sec.drop_spot(at(b, 20))[0] == c.t.id       # right half: before the next
    assert sec.drop_spot(at(c, 20))[0] is None         # after the last
    mime = QMimeData()
    mime.setData(sec.MIME, a.t.id.encode())
    ev = QDropEvent(QPointF(at(c, 20)), Qt.MoveAction, mime, Qt.LeftButton, Qt.NoModifier)
    sec.dropEvent(ev)
    assert [t.name for t in tab.triggers] == ["Card 1", "Card 2", "Card 0"]
    assert sec.drop_line.isHidden()
    tab.hide()


def test_the_check_speed_is_picked_under_the_cog(tab, monkeypatch):
    """Not on the bottom bar: under ⚙, for every trigger left on Default. Each card's
    Check every says what Default is, and the next start reads it back."""
    from onionwatch.ui.watching import WatchingDialog
    row, = cards(tab, 1)
    shown = []
    monkeypatch.setattr(WatchingDialog, "exec", lambda self: shown.append(self) or 0)
    tab.btn_settings.click()
    dlg = shown[0]
    assert dlg.speed.currentData() == sw.DEFAULT_INTERVAL_MS
    assert row.interval.itemText(0) == f"Default ({sw.DEFAULT_INTERVAL_MS} ms)"
    dlg.speed.setCurrentIndex(dlg.speed.findData(250))
    assert tab.watcher.interval == 0.25 and tab.host.screen["interval_ms"] == 250
    assert row.interval.itemText(0) == "Default (250 ms)"
    assert dlg.speed.itemText(dlg.speed.findData(16)) == "16 ms (every frame)"
    again = TriggersTab(tab.host)
    again.shutdown()
    assert again.default_interval == 250


def test_a_card_without_room_for_more_pictures_has_no_plus(tab):
    row, = cards(tab, 1)
    row.t.images = row.t.images * sw.MAX_PICTURES
    row.refresh_pictures()
    assert not row.btn_add_pic.isEnabled()



def test_a_closed_card_makes_its_editor_only_when_opened(qapp, styled):
    """A tile is just its header: the editor (most of a card's widgets) is made the
    first time it opens, with the trigger's sounds, category and speed in it."""
    t = sw.Trigger(id="t1", name="Lazy", sounds=["s1"])
    row = TriggerRow(t, [("s1", "Bell"), ("s2", "Horn")], [], open_=False)
    row.set_categories(["Main", "Other"])
    row.set_default_interval(250)
    assert not row.built
    assert "Bell" in row.sound_summary.text()
    row.set_sounds([("s1", "Gong")])            # renamed meanwhile: the tile says so
    assert "Gong" in row.sound_summary.text() and not row.built
    row.set_open(True)
    assert row.built
    assert [c.findChild(QPushButton, "chipname").text() for c in row.chips] == ["Gong"]
    assert row.interval.itemText(0) == "Default (250 ms)"
    assert row.cb_category.count() >= 2
    row.deleteLater()


def test_asking_a_closed_card_for_its_editor_makes_it(qapp, styled):
    row = TriggerRow(sw.Trigger(id="t2", name="Ask"), [], [], open_=False)
    assert not row.built
    row.cooldown.setValue(3)                     # (code that reaches into the editor)
    assert row.built
    row.deleteLater()


def test_cards_get_the_sounds_again_only_when_they_changed(tab, qapp, styled):
    rows = cards(tab, 3)
    calls = []
    for r in rows:
        orig = r.set_sounds
        r.set_sounds = lambda s, orig=orig: (calls.append(1), orig(s))
    tab.sounds_changed()
    first = len(calls)
    tab.sounds_changed()                         # a tab show with nothing new
    assert len(calls) == first
    tab.sounds_changed(force=True)               # the theme changed, say
    assert len(calls) == first + 3
