"""Categories and profiles on the triggers page: a big library, a manageable set on."""
import time
import zipfile

import pytest
from fakehost import FakeHost

from onionwatch import packs, profiles
from onionwatch import screenwatch as sw
from onionwatch.screenwatch import Trigger
from onionwatch.ui import triggerspanel
from onionwatch.ui.triggerspanel import TriggersTab
from onionwatch.windows import WindowInfo


def raw(i, cat="", **kw):
    """A trigger that needs no picture ("change"), with a sound: ready to watch."""
    return {"id": f"t{i}", "name": f"Trigger {i}", "mode": "change", "sounds": ["s1"],
            "category": cat, **kw}


@pytest.fixture
def make(qapp, tmp_path, monkeypatch):
    monkeypatch.setattr(triggerspanel.QMessageBox, "information", lambda *a, **k: None)
    monkeypatch.setattr(triggerspanel.QMessageBox, "warning", lambda *a, **k: None)
    monkeypatch.setattr(sw, "monitors", lambda: [sw.Monitor(0, 0, 320, 180, True)])
    made = []

    def make(screen):
        tab = TriggersTab(FakeHost(tmp_path, screen))
        tab._lister = lambda: []
        tab._front = lambda: 0
        tab.watched = []
        tab.watcher.set_items = lambda items: tab.watched.append([i.id for i in items])
        made.append(tab)
        return tab
    yield make
    for tab in made:
        tab.shutdown()
        tab.deleteLater()
    from PySide6.QtCore import QCoreApplication, QEvent
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


def watched(tab) -> list[str]:
    tab.btn_watch.blockSignals(True)
    tab.btn_watch.setChecked(True)
    tab.btn_watch.blockSignals(False)
    tab._sync()
    return tab.watched[-1]


def test_an_old_list_looks_as_it_did(make):
    tab = make({"triggers": [raw(1), raw(2)]})
    assert set(tab.rows) == {"t1", "t2"}
    assert list(tab.sections) == [""] and tab.sections[""].header.isHidden()
    assert tab.groupbar.isHidden()
    assert watched(tab) == ["t1", "t2"]
    tab._store()
    s = tab.host.screen
    assert [d["id"] for d in s["triggers"]] == ["t1", "t2"]
    assert s["categories"][0]["name"] == "" and s["profile"] == ""


def test_hundreds_of_triggers_open_fast_and_build_when_opened(make, qapp):
    screen = {"triggers": [raw(i, f"Cat {i % 3}") for i in range(300)],
              "categories": [{"name": f"Cat {k}", "on": True} for k in range(3)]}
    tab = make(screen)
    assert tab.rows == {}                          # every category folded: no cards made
    assert not tab.sections["Cat 0"].header.isHidden()
    assert "" not in tab.sections                   # Uncategorised is empty: not shown
    assert "300 triggers on" in tab.lbl_counts.text()
    tab.sections["Cat 1"].btn_fold.click()
    assert len(tab.rows) == triggerspanel.BUILD_NOW
    qapp.processEvents()
    assert len(tab.rows) < 100                      # the rest a few at a time...
    for _ in range(200):
        if len(tab.rows) == 100:
            break
        qapp.processEvents()
    assert len(tab.rows) == 100                     # ...until they're all made
    assert all(tab.rows[t.id].parentWidget() is tab.sections["Cat 1"].body
               for t in tab.triggers if t.category == "Cat 1")
    saved = {c["name"]: c for c in tab.host.screen["categories"]}
    assert saved["Cat 1"]["open"] and not saved["Cat 0"]["open"]


def test_a_category_switched_off_is_not_watched_and_keeps_its_triggers_switches(make):
    tab = make({"triggers": [raw(1, "A"), raw(2, "A", enabled=False), raw(3, "B")]})
    assert watched(tab) == ["t1", "t3"]
    tab._on_switch("A", False)
    assert tab.watched[-1] == ["t3"]
    assert [t.enabled for t in tab.triggers] == [True, False, True]
    assert "off" in tab.sections["A"].count.text()
    assert "1 of 3 triggers on" in tab.lbl_counts.text()
    tab._on_switch("A", True)
    assert tab.watched[-1] == ["t1", "t3"]          # just the one that was on
    tab.set_category_triggers("A", True)
    assert watched(tab) == ["t1", "t2", "t3"]


def test_a_trigger_moves_between_categories_from_its_card(make):
    tab = make({"triggers": [raw(1), raw(2)]})
    row = tab.rows["t1"]
    assert row.cb_category.findData(triggerspanel.NEW_CATEGORY) >= 0
    tab.new_category("Raids")
    assert not tab.sections[""].header.isHidden()   # two categories: headers show
    assert tab.sections[""].is_open                  # ...and the old list stays open
    row.category_wanted.emit(row, "Raids")
    t1 = tab.triggers[0]
    assert t1.category == "Raids" and tab.host.screen["triggers"][0]["category"] == "Raids"
    assert tab.rows["t1"].parentWidget() is tab.sections["Raids"].body
    assert "in Raids" in tab.rows["t1"]._tune_summary()
    # a new trigger goes in the category last opened or used
    tab.add_area_trigger()
    assert tab.triggers[-1].category == "Raids"


def test_rename_and_delete_a_category_with_undo(make, monkeypatch):
    tab = make({"triggers": [raw(1, "Old"), raw(2)]})
    p = profiles.new_profile("Evening")
    p.categories = ["Old"]
    tab.set_profiles([p])
    assert tab.rename_category("Old", "New")
    assert tab.triggers[0].category == "New" and p.categories == ["New"]
    assert "Old" not in tab.sections and "New" in tab.sections
    assert tab.delete_category("New", ask=False)
    assert tab.triggers[0].category == "" and "New" not in tab.sections
    assert tab.groups.profiles[0].categories == []
    tab.undo_bar.btn_undo.click()
    assert tab.triggers[0].category == "New" and "New" in tab.sections
    assert tab.groups.profiles[0].categories == ["New"]
    assert not tab.rename_category("", "Something")   # Uncategorised keeps its name


def test_a_profile_picked_by_hand_and_automatic_by_program(make):
    tab = make({"triggers": [raw(1, "Raids"), raw(2, "Fishing"), raw(3)]})
    raid = profiles.new_profile("Raid night")
    raid.categories, raid.apps = ["Raids"], ["game.exe"]
    tab.set_profiles([raid])
    assert not tab.groupbar.isHidden()
    assert watched(tab) == ["t1", "t2", "t3"]       # Manual: every switch on
    tab.set_profile(raid.id)
    assert tab.watched[-1] == ["t1"]
    tab._on_switch("Fishing", True)                  # edits the profile in charge
    assert raid.categories == ["Raids", "Fishing"] and tab.watched[-1] == ["t1", "t2"]
    tab._on_switch("Fishing", False)
    tab.set_profile(profiles.AUTO)
    assert tab._app_timer.isActive()
    assert tab.watched[-1] == ["t1", "t2", "t3"]     # game.exe isn't open: Manual's
    assert "your switches apply" in tab.lbl_counts.text()
    tab._lister = lambda: [WindowInfo(5, "The Game", "game.exe", 1, 0, 800, 600)]
    tab._check_apps()
    assert tab.watched[-1] == ["t1"] and "Raid night" in tab.lbl_counts.text()
    tab._lister = lambda: []
    tab._check_apps()
    assert tab.watched[-1] == ["t1", "t2", "t3"]
    tab.set_profile("")
    assert not tab._app_timer.isActive()
    assert tab.host.screen["profile"] == "" and tab.host.screen["profiles"][0]["apps"] == [
        "game.exe"]


def test_the_profiles_window_edits_copies(make, qapp):
    from onionwatch.ui.categories import ProfilesDialog
    tab = make({"triggers": [raw(1, "Raids")]})
    lister = [WindowInfo(5, "The Game", "Game.exe", 1, 0, 800, 600)]
    dlg = ProfilesDialog(tab, [], tab.groups.names(), lambda: lister)
    dlg._new()
    p = dlg.result_profiles[0]
    assert dlg.open_programs() == [("Game.exe", "The Game")]
    assert dlg.add_app("Game.exe") and not dlg.add_app("game")  # already in, as game.exe
    assert dlg.add_app("C:\\Tools\\other") and p.apps == ["game.exe", "other.exe"]
    item = dlg.cats.item(tab.groups.names().index("Raids"))
    item.setCheckState(triggerspanel.Qt.Checked)
    assert p.categories == ["Raids"]
    assert tab.groups.profiles == []                  # nothing changed until OK
    tab.set_profiles(dlg.result_profiles)
    assert tab.cb_profile.findData(p.id) >= 0 and tab.cb_profile.findData(profiles.AUTO) >= 0
    dlg.deleteLater()


def test_too_many_pictures_on_is_said(make):
    tab = make({"triggers": [raw(1, "A")]})
    tab.btn_watch.blockSignals(True)
    tab.btn_watch.setChecked(True)
    tab.btn_watch.blockSignals(False)
    tab.watcher.scores = {"t1": 0.0}
    tab.watcher.gap = 2.0
    tab._heavy_since = time.monotonic() - triggerspanel.HEAVY_FOR - 1
    tab._show_warning()
    assert "checked only every 2.0 s" in tab.warn.text()
    tab._heavy_since = None
    tab._show_warning()
    assert "checked only" not in tab.warn.text()


def test_packs_carry_categories(make, tmp_path, monkeypatch):
    tab = make({"triggers": [raw(1, "Raids"), raw(2)]})
    path = tmp_path / "pack.zip"
    packs.write_pack(path, tab.triggers, dict(tab.host.sounds()))
    found = packs.read_pack(path)
    assert [t.category for t, _p, _s in found] == ["Raids", ""]
    other = make({"triggers": []})
    assert other.add_pack(found) == 2
    assert [t.category for t in other.triggers] == ["Raids", ""]
    assert "Raids" in other.sections
    # a pack without categories (an older one) lands in one named after its file
    old = tmp_path / "Onion Watch Fishing.zip"
    with zipfile.ZipFile(old, "w") as z:
        z.writestr("triggers.json", '{"format": "onion-watch-triggers", "version": 1, '
                   '"triggers": [{"id": "x", "mode": "change"}]}')
    monkeypatch.setattr(triggerspanel.QFileDialog, "getOpenFileName",
                        lambda *a, **k: (str(old), ""))
    other.import_triggers()
    assert other.triggers[-1].category == "Fishing"


def test_an_older_version_opening_the_settings_loses_no_triggers(make, monkeypatch):
    """Versions before categories load only the first 50 of "triggers" and save just
    those back: the rest are kept where they never look."""
    monkeypatch.setattr(triggerspanel, "BUILD_NOW", 4)   # it's about the file, not cards
    tab = make({"triggers": [raw(i) for i in range(120)]})
    tab._store()
    s = tab.host.screen
    assert len(s["triggers"]) == triggerspanel.OLD_TRIGGERS == 50
    assert len(s["more_triggers"]) == 70
    # an older version: loads the first 50, deletes one, renames one, saves its list
    old = s["triggers"][:50]
    del old[3]
    old[0] = {**old[0], "name": "Renamed in the old version"}
    s["triggers"] = old
    again = make(s)
    assert len(again.triggers) == 119
    assert again.triggers[0].name == "Renamed in the old version"
    assert "t3" not in {t.id for t in again.triggers} and again.triggers[-1].id == "t119"
    # the same trigger in both lists (a hand-edited file) counts once
    s["more_triggers"].append(s["triggers"][0])
    assert len(make(s).triggers) == 119


def test_an_older_version_saving_its_triggers_keeps_their_categories(make):
    """An older version doesn't know Trigger.category and saves its triggers back
    without it: the categories come back from where it never looks."""
    tab = make({"triggers": [raw(1, "Raids"), raw(2), raw(3, "Fishing")]})
    tab._store()
    s = tab.host.screen
    assert s["trigger_categories"] == {"t1": "Raids", "t3": "Fishing"}
    s["triggers"] = [{k: v for k, v in d.items() if k != "category"} for d in s["triggers"]]
    s["triggers"].append({"id": "t9", "mode": "change"})     # one it added
    again = make(s)
    assert [t.category for t in again.triggers] == ["Raids", "", "Fishing", ""]
    assert again.groups.names() == ["", "Raids", "Fishing"]
    # a category this version took away again isn't brought back from the side copy
    again.move_trigger(again.triggers[0], "")
    assert "t1" not in s["trigger_categories"]
    assert make(s).triggers[0].category == ""


def test_a_pack_holds_hundreds_now():
    assert packs.MAX_PACK_TRIGGERS >= triggerspanel.MAX_TRIGGERS >= 500
    assert Trigger.from_raw(raw(1, "Raids")).category == "Raids"


def test_change_window_moves_everything_that_looked_in_it_with_undo(make, monkeypatch):
    """The game's program was renamed: one "Change window…" moves the default Look
    in, every trigger's copies of that window ("every copy" stays every copy) and
    the profiles' program to the new one, saved once, and Undo puts it all back."""
    old = {"exe": "game.exe", "title": "Game", "nth": 0}
    screen = {"window": old,
              "triggers": [raw(1, windows=[old, {**old, "nth": 1}], screens=[0]),
                           raw(2, windows=[{**old, "every": True}]),
                           raw(3, windows=[{"exe": "other.exe", "title": "Other", "nth": 0}]),
                           raw(4)],
              "profiles": [{"id": "p1", "name": "Evening", "apps": ["chat.exe", "game.exe"],
                            "categories": [""]},
                           {"id": "p2", "name": "Work", "apps": ["other.exe"]}]}
    tab = make(screen)
    host = tab.host
    t1, t2, t3, t4 = tab.triggers
    before = {t.id: t.to_raw() for t in tab.triggers}
    ref = sw.WindowRef("game.exe", "Game", 0)
    new = sw.WindowRef("game_dx12.exe", "Game", 0)
    monkeypatch.setattr(tab, "pick_window", lambda current=None: new if current == ref else None)
    saves = host.saves
    assert tab.change_window(ref)
    assert host.saves == saves + 1                          # saved once
    assert tab.watcher.default == new and host.screen["window"] == new.to_raw()
    assert t1.sources == [0, new, sw.WindowRef("game_dx12.exe", "Game", 1)]
    assert t2.sources == [sw.WindowRef("game_dx12.exe", "Game", 0, True)]
    assert t3.sources == [sw.WindowRef("other.exe", "Other", 0)] and t4.sources == []
    assert [p.apps for p in tab.groups.profiles] == [["chat.exe", "game_dx12.exe"],
                                                     ["other.exe"]]
    # as saved: what an older version reads (its one `window`) points at it too
    saved = {d["id"]: d for d in host.screen["triggers"]}
    assert saved["t1"]["window"] == new.to_raw()
    assert saved["t2"]["windows"] == [{**new.to_raw(), "every": True}]
    assert host.screen["profiles"][0]["apps"] == ["chat.exe", "game_dx12.exe"]
    loaded = [sw.Trigger.from_raw(d) for d in host.screen["triggers"]]
    assert [t.sources for t in loaded] == [t.sources for t in tab.triggers]
    bar = tab.undo_bar
    assert not bar.isHidden() and "2 triggers" in bar.label.toolTip()
    bar.btn_undo.click()
    assert {t.id: t.to_raw() for t in tab.triggers} == before
    assert tab.watcher.default == ref and host.screen["window"] == old
    assert host.screen["profiles"][0]["apps"] == ["chat.exe", "game.exe"]
    # cancelled, the same window again, or nothing using it: nothing changes
    assert not tab.change_window(sw.WindowRef("nope.exe", "Nope"))
    monkeypatch.setattr(tab, "pick_window", lambda current=None: current)
    assert not tab.change_window(ref)
    assert not tab.retarget_window(sw.WindowRef("nope.exe", "Nope"), new)
    assert host.screen["window"] == old


def test_a_card_waiting_for_its_window_offers_to_change_it(make, monkeypatch):
    old = {"exe": "game.exe", "title": "Game", "nth": 0}
    tab = make({"triggers": [raw(1, windows=[old])]})
    t = tab.triggers[0]
    tab._set_open(tab.sections[""], True)
    row = tab.rows[t.id]
    ref = sw.WindowRef.from_raw(old)
    assert row.btn_retarget.isHidden()
    tab.watcher.failed = frozenset({ref})
    tab.watcher.where = {t.id: [ref]}
    tab._poll()
    assert row.state.text() == "Waiting for Game to open" and not row.btn_retarget.isHidden()
    new = sw.WindowRef("game_dx12.exe", "Game", 0)
    monkeypatch.setattr(tab, "pick_window", lambda current=None: new)
    row.btn_retarget.click()
    assert t.sources == [new] and row.btn_retarget.isHidden()


def test_cards_never_flash_up_as_windows_of_their_own(make, qapp):
    """Building cards (opening the page, a new category, a trigger moved into it) shows
    no widget of a card while it has no parent: on Windows each one flashed up on the
    desktop as a little blank window of its own, and lagged the app."""
    from PySide6.QtCore import QEvent, QObject
    from PySide6.QtWidgets import QWidget
    stray = []

    class Spy(QObject):
        def eventFilter(self, obj, ev):
            if (ev.type() == QEvent.Show and isinstance(obj, QWidget) and obj.isWindow()
                    and obj.parent() is None):
                stray.append(type(obj).__name__)
            return False

    spy = Spy()
    qapp.installEventFilter(spy)
    try:
        tab = make({"triggers": [raw(1, ring=True), raw(2, mode="appear", ring=True),
                                 raw(3, mode="appear")]})
        name = tab.new_category("Flash test")
        for t in list(tab.triggers):
            tab.move_trigger(t, name)
        qapp.processEvents()
    finally:
        qapp.removeEventFilter(spy)
    assert stray == []
