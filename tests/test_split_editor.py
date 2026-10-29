"""A wide window: the list of triggers on the left, and the one picked in it on the
right, in an editor of its own. Narrower, the list is the whole width again and a
card opens in it."""
import test_ui
from PySide6.QtWidgets import QLabel
from test_ui import as_qimage, banner

from onionwatch.ui.triggers.triggerspanel import LIST_WIDTH, SPLIT_MIN

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


def test_switching_back_reuses_the_editor_without_restyling_the_tile(tab, qapp, monkeypatch):
    first, second = two(tab)
    wide(tab, qapp)
    tab._select(first)
    original = tab.editor
    sheets = []
    monkeypatch.setattr(first, "setStyleSheet", sheets.append)
    tab._select(second)
    assert original.isHidden()
    tab._select(first)
    assert tab.editor is original and not original.isHidden()
    assert first.property("selected") and not second.property("selected")
    assert sheets == []


def test_cached_editor_is_rebuilt_after_a_trigger_or_sound_library_change(tab, qapp):
    first, second = two(tab)
    wide(tab, qapp)
    tab._select(first)
    original = tab.editor
    tab._select(second)
    first.t.cooldown = 17
    tab._select(first)
    assert tab.editor is not original and tab.editor.cooldown.value() == 17
    original = tab.editor
    tab._select(second)
    tab.host.sounds = lambda: [("new", "New sound")]
    tab._select(first)
    assert tab.editor is not original and ("new", "New sound") in tab.editor.sound.sounds()


def test_editor_cache_is_bounded_and_dropped_when_the_editor_closes(tab, qapp):
    two(tab)
    for i in range(5):
        tab._new(as_qimage(banner()), f"Extra {i}")
    wide(tab, qapp)
    for row in tab.rows.values():
        tab._select(row)
        assert len(tab._editor_cache) <= 3
    tab._drop_editor()
    assert not tab._editor_cache and tab.editor is None


def test_saved_edits_discard_hidden_editors(tab, qapp):
    first, second = two(tab)
    wide(tab, qapp)
    tab._select(first)
    tab._select(second)
    assert tab._editor_cache
    tab.editor.name.setText("Changed")
    tab.editor.name.editingFinished.emit()
    assert not tab._editor_cache


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
    tab.editor.btn_del.click()
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


def test_the_view_box_says_cards_when_too_narrow_for_the_list(tab, qapp):
    """List and editor picked in a window too narrow for it shows cards: the View box
    said "List and editor" all the same. It says what's on screen, and goes back."""
    from onionwatch.ui.triggers.triggerspanel import LIST_VIEW
    two(tab)
    tab.set_list_view(True)
    cb = tab.cb_per_row
    wide(tab, qapp, SPLIT_MIN - 60)
    assert not tab.split and cb.currentData() == LIST_VIEW
    assert cb.currentText() == "Cards (too narrow)"
    wide(tab, qapp)
    assert tab.split and cb.currentText() == "List and editor"
    tab.set_list_view(False)          # cards picked: the entry's own name
    wide(tab, qapp, SPLIT_MIN - 60)
    assert cb.itemText(cb.findData(LIST_VIEW)) == "List and editor"


def test_a_trigger_moved_to_another_category_stays_picked(tab, qapp):
    first, _second = two(tab)
    tab.new_category("Raids")
    wide(tab, qapp)
    first.set_open(True)
    ed = tab.editor
    ed.cb_category.setCurrentIndex(ed.cb_category.findData("Raids"))
    ed.cb_category.activated.emit(ed.cb_category.currentIndex())
    tile = tab.rows[first.t.id]         # a new card, in Raids
    assert tile.selected and tab.editor.t is first.t
    assert tab.editor.cb_category.currentData() == "Raids"


def test_a_duplicate_is_picked_in_the_editor(tab, qapp):
    first, _second = two(tab)
    wide(tab, qapp)
    first.set_open(True)
    tab.editor.btn_dup.click()
    copy = tab.editor.t
    assert copy is not first.t and copy.name.endswith("(copy)")
    assert tab.rows[copy.id].selected and not tab.rows[first.t.id].selected


def test_pads_fill_the_page_until_one_is_picked_then_share_it(tab, qapp):
    """The Pads view: every trigger a pad, the whole width; a click opens it in the
    editor beside the pads (PADS_SHARE of the width at first), its handle dragged
    to share the width out (kept), its ✕ putting the pads back across it all."""
    from onionwatch.ui.triggers.triggerspanel import PADS_SHARE
    first, second = two(tab)
    wide(tab, qapp, 1300)
    tab.set_list_view(True, pads=True)
    assert tab.host.screen["view"] == "pads"
    assert first.pad and second.pad and first.btn_open.isHidden()
    if tab.editor is not None:
        tab.editor.btn_close.click()
    for _ in range(3):
        qapp.processEvents()
    assert tab.editor is None and tab.editor_scroll.isHidden()
    assert not tab.splitter.handle(1).isEnabled()
    first.set_open(True)                                    # a click on a pad
    for _ in range(3):
        qapp.processEvents()
    assert tab.editor is not None and tab.editor.t is first.t and first.selected
    assert not tab.editor.btn_close.isHidden() and tab.splitter.handle(1).isEnabled()
    a, b = tab.splitter.sizes()
    assert abs(a / (a + b) - PADS_SHARE) < 0.02
    tab.splitter.moveSplitter(a + 200, 1)                   # dragged wider
    a2, b2 = tab.splitter.sizes()
    assert a2 > a and tab.host.screen["pads_split"] == round(a2 / (a2 + b2), 3)
    second.set_open(True)                                   # another pad: same share
    assert tab.splitter.sizes()[0] == a2
    tab.editor.btn_close.click()
    assert tab.editor is None and tab.editor_scroll.isHidden()
    tab.set_list_view(True)                                 # the list again
    for _ in range(3):
        qapp.processEvents()
    assert not first.pad and tab.scroll.width() == LIST_WIDTH and tab.editor is not None


def test_an_empty_window_never_says_the_same_thing_twice(tab, qapp):
    """No triggers yet: the list's box says how to start, and what Watch needs (a game
    window, something to cut out, a sound) shows beside it instead of the editor's
    "+ New trigger" again; with no editor beside it, under the list's box."""
    wide(tab, qapp)
    assert tab.split and not tab.editor_scroll.isHidden()
    assert any("+ New trigger" in lb.text() for lb in tab.empty.findChildren(QLabel))
    assert "+ New trigger" not in tab.editor_hint.text()
    assert tab.editor_hint.text() == tab.about        # the tab's own explanation
    assert tab.empty_about.isHidden()                       # said once, not twice
    tab.resize(SPLIT_MIN - 100, 700)                        # the list alone
    for _ in range(3):
        qapp.processEvents()
    assert not tab.split and not tab.empty_about.isHidden()
    assert tab.empty_about.text() == tab.about
    tab._new(as_qimage(banner()), "First")                  # one made: pick it, says the box
    wide(tab, qapp)
    assert "+ New trigger" in tab.editor_hint.text()
