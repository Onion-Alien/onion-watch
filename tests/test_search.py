"""Search the model, even when hundreds of cards haven't been built yet."""
from copy import deepcopy

import pytest

import test_categories
from test_categories import raw, watched

make = test_categories.make


def visible_ids(tab):
    return {tid for tid, row in tab.rows.items()
            if not row.isHidden() and not tab.sections[row.t.category].isHidden()}


def test_global_search_finds_a_folded_unbuilt_trigger_and_restores_folds(make, qapp):
    tab = make({"triggers": [raw(i, f"Cat {i % 3}") for i in range(300)]})
    assert not tab.rows
    before = deepcopy(tab.host.screen)
    tab.show_search()
    tab.search_text.setText("  TRIGGER   299 ")
    for _ in range(5):
        qapp.processEvents()
    assert visible_ids(tab) == {"t299"}
    assert set(tab.rows) == {"t299"}  # don't construct 299 irrelevant cards
    assert tab.search_summary.text() == "1 of 300"
    assert tab.sections["Cat 2"].is_open
    assert tab.host.screen == before
    assert all(not c.open for c in tab.groups.categories)
    tab.clear_search()
    assert all(not s.is_open and not s.isHidden() for s in tab.sections.values())


def test_category_search_combines_scope_and_text_and_does_not_change_watching(make):
    tab = make({"triggers": [raw(1, "Raids", name="Health low"),
                             raw(2, "Fishing", name="Health low"),
                             raw(3, "Raids", name="Ready check")]})
    before = watched(tab)
    tab.sections["Raids"].search_wanted.emit("Raids")     # its ⋯ menu's "Search this category"
    assert tab.search_scope.currentData() == "Raids"
    assert visible_ids(tab) == {"t1", "t3"}
    tab.search_text.setText("health")
    assert visible_ids(tab) == {"t1"}
    assert watched(tab) == before
    tab.search_scope.setCurrentIndex(0)
    assert visible_ids(tab) == {"t1", "t2"}
    tab.search_text.setText("not here")
    assert not visible_ids(tab) and not tab.no_results.isHidden()
    tab.close_search_shortcut.activated.emit()      # Esc: the box stays, emptied
    assert not tab.search_bar.isHidden() and tab.no_results.isHidden()
    assert tab.search_text.text() == "" and tab.search_scope.currentData() is None
    assert tab._search_ids is None


def test_search_matches_category_window_and_sound_and_updates_after_edits(make):
    tab = make({"triggers": [raw(1, "Raids", windows=[
        {"exe": "example.exe", "title": "Realm Online", "index": 0}]), raw(2)]})
    tab.search_text.setText("raids")
    assert visible_ids(tab) == {"t1"}
    tab.search_text.setText("realm")
    assert visible_ids(tab) == {"t1"}
    sound_name = dict(tab.host.sounds())["s1"]
    tab.search_text.setText(sound_name)
    assert visible_ids(tab) == {"t1", "t2"}
    tab.search_text.setText("Trigger 1")
    row = tab.rows["t1"]
    row.name.setText("Renamed")
    row.name.editingFinished.emit()
    assert not visible_ids(tab) and not tab.no_results.isHidden()
    tab.search_text.setText("renamed")
    assert visible_ids(tab) == {"t1"}


def test_changing_query_during_lazy_build_does_not_leak_old_results(make, qapp):
    tab = make({"triggers": [raw(i, f"Cat {i % 2}") for i in range(300)]})
    tab.search_text.setText("trigger")
    tab.search_text.setText("trigger 299")
    for _ in range(20):
        qapp.processEvents()
    assert visible_ids(tab) == {"t299"}
    tab.show_search("Cat 1")
    tab.delete_category("Cat 1", ask=False)
    assert tab.search_scope.currentData() is None
    assert visible_ids(tab) == {"t299"}


def test_category_controls_fit_in_a_narrow_window(make, qapp):
    from PySide6.QtWidgets import QPushButton
    tab = make({"triggers": [raw(1, "Dungeons and queues"), raw(2, "Raids")]})
    tab.resize(360, 900)
    tab.show_search("Dungeons and queues")
    tab.show()
    for _ in range(12):
        qapp.processEvents()
    assert tab.width() == 360
    for sec in tab.sections.values():
        if sec.isHidden():
            continue
        for button in sec.header.findChildren(QPushButton):
            assert button.mapTo(tab, button.rect().topRight()).x() < tab.width()


@pytest.mark.parametrize("width", [900, 1040])
@pytest.mark.parametrize("theme_name", ["Retro 98", "Dark"])
def test_the_search_box_stays_usable_beside_categories_and_a_profile(make, qapp, width,
                                                                     theme_name):
    """With categories, a profile and the counts, the line over the list once had no
    room left for the search box: "Sea…", and "Ready" typed showed as "eady"."""
    from PySide6.QtWidgets import QWidget

    from onionwatch import profiles, theme
    from onionwatch.ui.triggerspanel import SEARCH_MIN
    old = qapp.styleSheet()
    theme.apply(qapp, theme_name)
    try:
        tab = make({"triggers": [raw(i, f"Cat {i % 3}") for i in range(30)]})
        tab.set_profiles([profiles.new_profile("Realm Online raids")])
        tab.set_profile(profiles.AUTO)
        tab.resize(width, 640)
        tab.show()
        tab.search_text.setText("Ready check 3")
        for _ in range(12):
            qapp.processEvents()
        assert not tab.groupbar.isHidden() and not tab.search_scope.isHidden()
        box = tab.search_text
        assert box.width() >= max(240, SEARCH_MIN)
        text = box.fontMetrics().horizontalAdvance(box.text())
        assert text + 60 < box.width()      # the typed text, the icon and the clear button
        bar = tab.search_bar
        for w in bar.findChildren(QWidget):   # everything on the bar fits inside it
            if w.isVisibleTo(bar) and w.parentWidget() in (tab.search_line, tab.view_bar):
                assert w.mapTo(bar, w.rect().topLeft()).x() >= 0
                assert w.mapTo(bar, w.rect().topRight()).x() < bar.width()
        tab.search_text.clear()
        for _ in range(5):
            qapp.processEvents()
        counts = tab.lbl_counts
        assert counts.isVisible()
        shown = counts.shown_text()      # whole parts, never a lone "1" or a trailing "·"
        assert shown and counts.text().startswith(shown.removesuffix(" …"))
        assert not shown.rstrip(" …").endswith("·")
    finally:
        qapp.setStyleSheet(old)
        theme.set_current(theme.DEFAULT)
