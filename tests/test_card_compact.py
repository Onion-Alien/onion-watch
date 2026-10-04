"""Compact cards: a closed card is a short tile (a small thumbnail, a + to add a
picture, the switches, the name with the live state beside it, then one line), a
card is dragged to another place or category, picture files dropped on a card are
added to it, and the check speed of triggers on "Default" is picked under ⚙ (each
card says what Default is)."""
from PySide6.QtCore import QMimeData, QPoint, QPointF, Qt, QUrl
from PySide6.QtGui import QDropEvent, QMouseEvent

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
    b.set_open(True)
    settle(qapp, tab)
    assert a.height() <= 120 < b.height()
    assert a.strip.thumb == TILE_THUMB and len(a.strip.thumbs) == 1
    assert a.btn_add_pic.isVisibleTo(a)
    # the live state sits beside the name, with no box of its own
    assert abs(a.live.geometry().center().y() - a.name_line.geometry().center().y()) <= 2
    assert a.live.styleSheet() == "" and "Ready" in a.live.text()
    # one line under the name: what it plays, or what's wrong
    assert a.sound_summary.isVisibleTo(a) and not a.state.isVisibleTo(a)
    a.t.sounds.clear()
    a.set_sounds(a._sounds)
    assert a.state.isVisibleTo(a) and not a.sound_summary.isVisibleTo(a)
    assert "sound" in a.state.text()
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

