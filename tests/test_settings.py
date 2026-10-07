"""Settings: a config.json that can't be read is kept aside, not overwritten."""
import json

from onionwatch.settings import CONFIG, Config


def test_an_unreadable_config_is_kept_aside_before_defaults(tmp_path):
    bad = tmp_path / CONFIG
    bad.write_text('{"theme": "Midnight", oops', encoding="utf-8")
    cfg = Config.load(tmp_path)
    assert cfg == Config()
    kept = tmp_path / (CONFIG + ".bad")
    assert kept.read_text(encoding="utf-8") == '{"theme": "Midnight", oops'
    cfg.save(tmp_path)                       # the next save doesn't lose it
    assert kept.exists() and json.loads(bad.read_text(encoding="utf-8"))


def test_a_config_that_isnt_an_object_is_kept_aside_too(tmp_path):
    (tmp_path / CONFIG).write_text("[1, 2]", encoding="utf-8")
    assert Config.load(tmp_path) == Config()
    assert (tmp_path / (CONFIG + ".bad")).read_text(encoding="utf-8") == "[1, 2]"


def test_a_locked_config_is_left_where_it_is(tmp_path, monkeypatch):
    from pathlib import Path
    (tmp_path / CONFIG).write_text('{"theme": "Midnight"}', encoding="utf-8")

    def locked(self, *a, **k):
        raise PermissionError("in use")

    monkeypatch.setattr(Path, "read_text", locked)
    assert Config.load(tmp_path) == Config()
    monkeypatch.undo()
    assert (tmp_path / CONFIG).exists() and not (tmp_path / (CONFIG + ".bad")).exists()


def test_the_language_is_kept_and_settings_from_a_newer_version_arent_lost(tmp_path):
    """Config.language round-trips; keys this version doesn't know (written by a newer
    one) are saved back as they were, so going back a version loses nothing."""
    (tmp_path / CONFIG).write_text(json.dumps(
        {"theme": "Midnight", "language": "de", "future_thing": {"a": [1, 2]},
         "screen": {"on": True}}), encoding="utf-8")
    cfg = Config.load(tmp_path)
    assert (cfg.theme, cfg.language) == ("Midnight", "de")
    cfg.theme = "Ocean"
    cfg.save(tmp_path)
    raw = json.loads((tmp_path / CONFIG).read_text(encoding="utf-8"))
    assert raw["future_thing"] == {"a": [1, 2]} and raw["theme"] == "Ocean"
    assert raw["language"] == "de"
    # settings from before the language setting: Windows' language
    (tmp_path / CONFIG).write_text(json.dumps({"theme": "Midnight"}), encoding="utf-8")
    assert Config.load(tmp_path).language == ""
