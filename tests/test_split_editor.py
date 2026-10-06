"""A wide window: the list of triggers on the left, and the one picked in it on the
right, in an editor of its own. Narrower, the list is the whole width again and a
card opens in it."""
import test_ui
from test_ui import as_qimage, banner

from onionwatch.ui.triggerspanel import LIST_WIDTH, SPLIT_MIN

fake_screen, tab = test_ui.fake_screen, test_ui.tab   # the same stand-ins


def wide(tab, qapp, width=SPLIT_MIN + 200):
    tab.resize(width, 700)
    tab.show()
    for _ in range(3):
        qapp.processEvents()


def two(tab):
    tab._new(as_qimage(banner()), "First")
    tab._new(as_qimage(banner()), "Second")
    return [tab.rows[t.id] for t in tab.triggers]


def test_a_wide_window_shows_the_list_beside_an_editor(tab, qapp):
    first, second = two(tab)
    wide(tab, qapp)
    assert tab.split and tab.editor is not None
    assert tab.scroll.width() == LIST_WIDTH
    assert not first.is_open and not second.is_open        # the list stays tiles
    picked = tab.rows[tab.editor.t.id]                      # a card that was open
    assert tab.editor.is_open and picked.selected
    assert [r.selected for r in (first, second)].count(True) == 1
    first.set_open(True)                                    # a click on a tile
    assert not first.is_open and tab.editor.t is first.t and first.selected


def test_the_editor_and_the_list_card_keep_in_step(tab, qapp):
    first, _second = two(tab)
    wide(tab, qapp)
    first.set_open(True)
    ed = tab.editor
    ed.name.setText("Renamed")
    ed.name.editingFinished.emit()
    assert first.t.name == "Renamed" and first.title.text() == "Renamed"
    ed.chk_on.setChecked(False)
    assert not first.chk_on.isChecked()
    first.chk_on.setChecked(True)
    assert ed.chk_on.isChecked()


def test_deleting_the_picked_trigger_moves_the_editor_on(tab, qapp, monkeypatch):
    box = test_ui.triggerspanel.QMessageBox
    monkeypatch.setattr(box, "exec", lambda self: box.Yes)
    first, second = two(tab)
    wide(tab, qapp)
    first.set_open(True)
    tab.editor.act_del.trigger()
    assert [t.name for t in tab.triggers] == ["Second"]
    assert tab.editor is not None and tab.editor.t is second.t


def test_a_narrow_window_opens_the_card_in_the_list_again(tab, qapp):
    two(tab)
    wide(tab, qapp)
    picked = tab.rows[tab.editor.t.id]
    tab.resize(SPLIT_MIN - 100, 700)
    for _ in range(3):
        qapp.processEvents()
    assert not tab.split and tab.editor is None and tab.editor_scroll.isHidden()
    assert picked.is_open and not picked.selected        # it opens where it is
