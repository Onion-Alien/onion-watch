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
    assert [h["path"] for h in out] == [f"/onion-watch/app/{__version__}",
                                       "onion-watch/first-start"]
    assert all(h["session"] == c.stats_id and len(c.stats_id) == 32 for h in out)
    c.stats_sent = 1_000_000.0
    assert usage.hits(c, 1_000_000.0 + 3600) == []            # not due yet
    later = usage.hits(c, 1_000_000.0 + usage.EVERY_S)
    assert [h["path"] for h in later] == [f"/onion-watch/app/{__version__}"]


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
    sent = []
    monkeypatch.setattr(usage, "send", lambda p: sent.append(p) or True)
    assert usage.maybe_send(cfg()) is None                  # from source: never
    monkeypatch.setattr(usage.sys, "frozen", True, raising=False)
    assert usage.maybe_send(cfg(usage_count=False)) is None
    c = cfg()
    usage.maybe_send(c).join(5)
    assert len(sent) == 1 and c.stats_sent > 0


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
