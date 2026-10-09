"""The anonymous usage count (onionwatch.usage): what it sends, when, and that it
stays off for settings from before it existed, from source, and when unticked."""
import json

import pytest

from onionwatch import __version__, app, settings, usage


def cfg(**kw):
    c = settings.Config()
    for k, v in kw.items():
        setattr(c, k, v)
    return c


def test_daily_hit_and_first_start_once():
    c = cfg()
    out = usage.hits(c, 1_000_000.0)
    assert [h["path"] for h in out][:2] == [f"/onion-watch/app/{__version__}",
                                           "onion-watch/first-start"]
    assert all(h["session"] == c.stats_id and len(c.stats_id) == 32 for h in out)
    assert {h["ref"] for h in out} == {usage.user_tag(c.stats_id)}
    c.stats_sent = 1_000_000.0
    assert usage.hits(c, 1_000_000.0 + 3600) == []            # not due yet
    later = usage.hits(c, 1_000_000.0 + usage.EVERY_S)
    assert [h["path"] for h in later][0] == f"/onion-watch/app/{__version__}"
    assert not any("first-start" in h["path"] for h in later)


def test_first_start_says_where_they_heard():
    out = usage.hits(cfg(stats_heard="A YouTube video"), 1_000_000.0)
    assert out[1]["path"] == "onion-watch/first-start/heard-youtube"


@pytest.mark.parametrize("typed,tag", [
    ("Discord server", "other-discord-server"), ("onion board", "onion-board"),
    ("me@example.com", ""), ("https://x.example/a", ""), ("0211234567", ""),
    ("asdfghjkl", ""), ("one two three four", ""), ("", "")])
def test_heard_tag_drops_anything_personal(typed, tag):
    assert usage.heard_tag(typed) == tag


def test_update_event():
    assert usage.update_event("9.9.9") == f"onion-watch/update-now/{__version__}-to-9.9.9"


def test_nothing_sent_from_source_or_when_off(monkeypatch):
    monkeypatch.delenv("ONIONBOARD_NO_STATS", raising=False)   # as on anyone's PC
    sent = []
    monkeypatch.setattr(usage, "send", lambda p: sent.append(p) or True)
    assert usage.maybe_send(cfg()) is None                  # from source: never
    monkeypatch.setattr(usage.sys, "frozen", True, raising=False)
    assert usage.maybe_send(cfg(usage_count=False)) is None
    c = cfg()
    usage.maybe_send(c).join(5)
    assert len(sent) == 1 and c.stats_sent > 0


def test_nothing_sent_from_a_dev_pc(monkeypatch):
    """ONIONBOARD_NO_STATS (the developer's PCs and test VMs): never, even switched on."""
    sent = []
    monkeypatch.setattr(usage, "send", lambda p: sent.append(p) or True)
    monkeypatch.setattr(usage.sys, "frozen", True, raising=False)
    monkeypatch.setenv("ONIONBOARD_NO_STATS", "1")
    assert usage.maybe_send(cfg()) is None and sent == []


def test_old_settings_start_with_it_off(tmp_path):
    (tmp_path / settings.CONFIG).write_text(json.dumps({"theme": "Dark"}), encoding="utf-8")
    assert settings.Config.load(tmp_path).usage_count is False
    assert settings.Config.load(tmp_path / "new").usage_count is True   # a new install
    c = settings.Config.load(tmp_path)
    c.usage_count = True
    c.save(tmp_path)
    assert settings.Config.load(tmp_path).usage_count is True


@pytest.mark.parametrize("argv,on,heard", [
    (["x", "--usage-count", "off"], False, ""),
    (["x", "--usage-count", "on", "--heard-from", "reddit"], True, "reddit")])
def test_installer_switch(monkeypatch, tmp_path, argv, on, heard):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path)
    (tmp_path / settings.CONFIG).write_text(json.dumps({"theme": "Dark"}), encoding="utf-8")
    assert app.set_usage_count(argv) == 0
    c = settings.Config.load(tmp_path)
    assert (c.usage_count, c.stats_heard, c.theme) == (on, heard, "Dark")


def trig(**kw):
    d = {"id": kw.pop("id", "t1"), "name": "T", "images": ["a.png"]}
    d.update(kw)
    return d


def test_daily_count_says_how_it_is_used():
    """age, triggers, fired, lang and used/: buckets and fixed names only."""
    c = cfg(screen={"triggers": [trig(mode="colour", colour="#ff0000", ring=True),
                                 trig(id="t2", unfocused=True, category="Raids")],
                    "profiles": [{"name": "Night"}]},
            language="de", stats_fired=12)
    usage.used("pack-import")
    usage.used("nonsense")          # not in FEATURES: never sent
    usage.remember(c)
    paths = [h["path"] for h in usage.hits(c, 1_000_000.0)]
    for want in ("onion-watch/age/day-1", "onion-watch/triggers/1-10",
                 "onion-watch/fired/11-50", "onion-watch/lang/de",
                 "onion-watch/used/pack-import", "onion-watch/used/mode-colour",
                 "onion-watch/used/mode-appear", "onion-watch/used/ring",
                 "onion-watch/used/quiet-in-front", "onion-watch/used/categories",
                 "onion-watch/used/profiles"):
        assert want in paths, want
    assert not any("nonsense" in p for p in paths)
    # nothing from the triggers themselves: names, pictures, colours
    assert not any(x in json.dumps(paths) for x in ("Raids", "a.png", "ff0000", "Night"))


def test_bucket_and_age():
    assert [usage.bucket(n) for n in (0, 1, 10, 11, 50, 51)] == [
        "0", "1-10", "1-10", "11-50", "11-50", "51-plus"]
    assert usage.age_bucket(0.5) == "day-1" and usage.age_bucket(40) == "days-31-plus"


def test_daily_send_clears_what_it_sent(monkeypatch):
    monkeypatch.delenv("ONIONBOARD_NO_STATS", raising=False)
    monkeypatch.setattr(usage.sys, "frozen", True, raising=False)
    sent = []
    monkeypatch.setattr(usage, "send", lambda p, **k: sent.append(p) or True)
    c = cfg(stats_fired=3, stats_used=["history"], stats_problems=["onion-watch/error/x"])
    usage.maybe_send(c).join(5)
    paths = [h["path"] for h in sent[0]]
    assert "onion-watch/used/history" in paths and "onion-watch/error/x" in paths
    assert (c.stats_fired, c.stats_used, c.stats_problems) == (0, [], [])
    # not due: problems still go, alone
    usage.note("onion-watch/unclean-exit/0.1")
    usage.maybe_send(c).join(5)
    assert [h["path"] for h in sent[1]] == ["onion-watch/unclean-exit/0.1"]


def test_steps_once_and_never_for_an_old_install(monkeypatch):
    monkeypatch.delenv("ONIONBOARD_NO_STATS", raising=False)
    monkeypatch.setattr(usage.sys, "frozen", True, raising=False)
    sent = []
    monkeypatch.setattr(usage, "send", lambda p, **k: sent.append(p) or True)
    c = cfg()
    for _ in range(2):
        usage.step(c, "added-trigger")
    for th in __import__("threading").enumerate():
        if th.name == "usage-count":
            th.join(5)
    assert [h["path"] for p in sent for h in p] == ["onion-watch/step/added-trigger"]
    old = cfg(stats_sent=500.0)          # counted before steps existed
    usage.step(old, "trigger-fired")
    assert len(sent) == 1


def test_used_goes_to_the_board_inside_it():
    got = []
    usage.forward_to(got.append)
    try:
        usage.used("duplicate")
        usage.used("not-a-feature")
    finally:
        usage.forward_to(None)
    assert got == ["duplicate"]
    c = cfg()
    usage.remember(c)
    assert "duplicate" not in c.stats_used     # the board counts it, not this app


def test_error_event_has_type_and_our_line_only():
    try:
        usage.bucket("secret window title")     # a TypeError inside onionwatch/usage.py
    except TypeError as e:
        ev = usage.error_event(type(e), e.__traceback__)
    assert ev.startswith(f"onion-watch/error/{__version__}/TypeError@onionwatch/usage.py:")
    assert "secret" not in ev


def test_error_event_without_our_code():
    assert usage.error_event(ValueError, None) == f"onion-watch/error/{__version__}/ValueError"


def test_unclean_exit(tmp_path):
    assert usage.mark_running(tmp_path) == ""
    assert usage.mark_running(tmp_path) == f"onion-watch/unclean-exit/{__version__}"
    usage.mark_stopped(tmp_path)
    assert usage.mark_running(tmp_path) == ""


def test_opt_out_has_no_id(monkeypatch):
    monkeypatch.delenv("ONIONBOARD_NO_STATS", raising=False)
    monkeypatch.setattr(usage.sys, "frozen", True, raising=False)
    calls = []
    monkeypatch.setattr(usage, "send", lambda p, **k: calls.append((p, k)) or True)
    assert usage.opt_out("settings")
    (payload, kw), = calls
    assert payload == [{"path": "onion-watch/opt-out/settings",
                        "title": "onion-watch/opt-out/settings", "event": True}]
    assert kw["no_sessions"] is True
    assert not usage.opt_out("elsewhere")


def test_installer_off_sends_opt_out_only_when_it_was_on(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path)
    where = []
    monkeypatch.setattr(usage, "opt_out", lambda w: where.append(w) or True)
    (tmp_path / settings.CONFIG).write_text(json.dumps({"usage_count": True}),
                                            encoding="utf-8")
    assert app.set_usage_count(["x", "--usage-count", "off"]) == 0
    assert app.set_usage_count(["x", "--usage-count", "off"]) == 0   # already off
    assert where == ["installer"]


def test_uninstall_count(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path)
    sent = []
    monkeypatch.setattr(usage, "send_now", lambda c, e: sent.append(e) or True)
    assert app.uninstall_count() == 0 and sent == []     # never counted: nothing
    settings.Config(stats_id="abc").save(tmp_path)
    assert app.uninstall_count() == 0
    assert sent == [f"onion-watch/uninstall/{__version__}"]
