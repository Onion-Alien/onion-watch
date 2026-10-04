"""Trigger categories and profiles (onionwatch.profiles): no Qt, no windows."""
from onionwatch import profiles as pf
from onionwatch.screenwatch import Trigger


def test_an_old_config_loads_with_everything_uncategorised_and_on():
    screen = {"triggers": [{"id": "a", "name": "Rare"}], "on": True}
    t = Trigger.from_raw(screen["triggers"][0])
    assert t.category == ""
    g = pf.Groups.load(screen, [t.category])
    assert g.names() == [""] and g.mode == ""
    assert g.active() == {""}
    assert pf.label("") == "Uncategorised"


def test_a_trigger_keeps_its_category_and_older_fields_alone():
    t = Trigger.from_raw({"id": "a", "category": "  Raid   bosses ", "threshold": 0.9})
    assert t.category == "Raid bosses" and t.threshold == 0.9
    raw = t.to_raw()
    assert raw["category"] == "Raid bosses"
    assert Trigger.from_raw(raw).category == "Raid bosses"
    assert Trigger.from_raw({"id": "b", "category": 5}).category == ""
    assert len(Trigger.from_raw({"id": "c", "category": "x" * 500}).category) == 60


def test_groups_round_trip_and_bad_entries_are_dropped():
    screen = {"categories": [{"name": "Raids", "on": False, "open": True},
                             {"name": "Raids"}, "junk", {"name": 3},
                             {"name": "Fishing"}],
              "profiles": [{"id": "p1", "name": "Evening", "apps": ["C:\\Games\\Game.EXE",
                                                                   "other", 7],
                            "when": "front", "categories": ["Raids", 4]},
                           {"id": "p1"}, {"name": "no id"}],
              "profile": "p1"}
    g = pf.Groups.load(screen, ["Fishing", "Bags"])
    assert g.names() == ["Raids", "Fishing", "Bags"]
    assert not g.find("Raids").on and g.find("Raids").open
    assert g.find("Bags").on
    (p,) = g.profiles
    assert p.apps == ["game.exe", "other.exe"] and p.when == "front"
    assert p.categories == ["Raids"] and g.mode == "p1"
    out = {}
    g.save(out)
    again = pf.Groups.load(out)
    assert again.names() == g.names() and again.profiles == g.profiles
    assert pf.Groups.load({"profile": "gone"}).mode == ""


def test_manual_a_picked_profile_and_auto():
    g = pf.Groups()
    for n in ("", "Raids", "Fishing", "Bags"):
        g.ensure(n)
    g.find("Bags").on = False
    raid = pf.new_profile("Raid night")
    raid.categories = ["Raids", "Bags"]
    raid.apps = ["game.exe"]
    fish = pf.new_profile("Fishing")
    fish.categories = ["Fishing"]
    fish.apps = ["other.exe"]
    g.profiles = [raid, fish]
    assert g.active() == {"", "Raids", "Fishing"}          # manual
    g.mode = raid.id
    assert g.active() == {"Raids", "Bags"}
    g.mode = pf.AUTO
    assert g.active([]) == {"", "Raids", "Fishing"}        # nothing running: manual
    assert g.active([fish.id]) == {"Fishing"}
    assert g.active([raid.id, fish.id]) == {"Raids", "Bags", "Fishing"}


def test_flipping_a_switch_changes_whatever_is_in_charge():
    g = pf.Groups()
    g.ensure("Raids")
    p = pf.new_profile()
    g.profiles = [p, pf.new_profile()]
    assert g.set_on("Raids", False) and not g.find("Raids").on
    g.mode = p.id
    assert g.set_on("Raids", True) and p.categories == ["Raids"]
    assert g.find("Raids").on is False                       # manual's switch left alone
    g.mode = pf.AUTO
    assert not g.set_on("Raids", False, [p.id, g.profiles[1].id])   # two in charge


def test_rename_and_remove_follow_into_profiles():
    g = pf.Groups()
    for n in ("A", "B"):
        g.ensure(n)
    p = pf.new_profile()
    p.categories = ["A", "B"]
    g.profiles = [p]
    assert g.rename("A", "C")
    assert g.names() == ["C", "B"] and p.categories == ["B", "C"]
    assert g.rename("C", "B")                                # into another: one
    assert g.names() == ["B"] and p.categories == ["B"]
    assert g.remove("B") == 0 and g.names() == [] and p.categories == []
    assert g.remove("nope") == -1
    g.ensure("x")
    g.ensure("")
    assert g.names() == ["", "x"]                            # Uncategorised at the top


def test_exe_names():
    assert pf.exe_name('  "C:\\Program Files\\Game\\Game.exe" ') == "game.exe"
    assert pf.exe_name("notepad") == "notepad.exe"
    assert pf.exe_name("thing.bin") == "thing.bin"
    assert pf.exe_name("   ") == "" and pf.exe_name(None) == ""


def test_app_watch_running_and_front_with_linger():
    run = pf.new_profile()
    run.apps = ["game.exe"]
    front = pf.new_profile()
    front.apps, front.when = ["other.exe"], "front"
    idle = pf.new_profile()                                  # no programs: never by itself
    w = pf.AppWatch()
    ps = [run, front, idle]
    assert not w.update(ps, set(), "", 0.0) and w.matched == []
    assert w.update(ps, {"game.exe", "other.exe"}, "explorer.exe", 1.0)
    assert w.matched == [run.id]                             # other.exe open but not in front
    assert w.update(ps, {"game.exe", "other.exe"}, "other.exe", 2.0)
    assert w.matched == [run.id, front.id]
    assert not w.update(ps, {"game.exe", "other.exe"}, "chat.exe", 2.0 + pf.FRONT_LINGER)
    assert w.update(ps, {"other.exe"}, "chat.exe", 3.0 + pf.FRONT_LINGER)
    assert w.matched == []


def test_a_renamed_program_is_swapped_in_every_profile_in_its_place():
    g = pf.Groups.load({"profiles": [
        {"id": "p1", "name": "Evening", "apps": ["chat.exe", "game.exe", "music.exe"]},
        {"id": "p2", "name": "Both", "apps": ["game.exe", "game_dx12.exe"]},
        {"id": "p3", "name": "Other", "apps": ["other.exe"]}]})
    assert g.replace_app("Game.EXE", "game_dx12")
    assert [p.apps for p in g.profiles] == [["chat.exe", "game_dx12.exe", "music.exe"],
                                            ["game_dx12.exe"], ["other.exe"]]
    assert not g.replace_app("game.exe", "anything.exe")    # nothing uses it now
    assert not g.replace_app("other.exe", "other.exe") and not g.replace_app("", "x.exe")
    # saved as before: an older version loads it as it is
    screen: dict = {}
    g.save(screen)
    assert pf.Groups.load(screen).profiles[0].apps == g.profiles[0].apps
