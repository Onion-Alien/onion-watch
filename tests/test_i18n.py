"""Translations: lookup with English fallback, placeholders, plural forms, picking the
language (the app's setting, Onion Board's), Qt's own buttons, the pseudo-language,
the extract script and the shipped catalogs."""
import importlib.util
import json
from pathlib import Path

import pytest

from onionwatch import i18n
from onionwatch.i18n import _, ngettext

ROOT = Path(__file__).resolve().parent.parent


def extract_script():
    spec = importlib.util.spec_from_file_location(
        "i18n_extract", ROOT / "scripts" / "i18n_extract.py")
    ex = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ex)
    return ex


@pytest.fixture
def langs(tmp_path, monkeypatch):
    d = tmp_path / "lang"
    d.mkdir()
    (d / "de.json").write_text(json.dumps({
        "_meta": {"name": "Deutsch"},
        "Add a picture": "Bild hinzufügen",
        "Deleted “{name}”": "„{name}“ gelöscht",
        "{n} trigger": ["{n} Trigger", "{n} Trigger"],
        "Untranslated": "",
    }, ensure_ascii=False), encoding="utf-8")
    (d / "ru.json").write_text(json.dumps({
        "_meta": {"name": "Русский"},
        "{n} trigger": ["{n} триггер", "{n} триггера", "{n} триггеров"],
    }, ensure_ascii=False), encoding="utf-8")
    (d / "pt-BR.json").write_text(json.dumps({"_meta": {"name": "Português (Brasil)"}}),
                                  encoding="utf-8")
    monkeypatch.setattr(i18n, "LANG_DIR", d)
    monkeypatch.delenv(i18n.ENV, raising=False)
    yield d
    i18n.set_language(i18n.ENGLISH)


def test_english_is_the_text_as_written():
    assert i18n.current() == "en"
    assert _("Add a picture") == "Add a picture"
    assert _("Deleted “{name}”", name="Boss") == "Deleted “Boss”"
    assert ngettext("{n} trigger", "{n} triggers", 1) == "1 trigger"
    assert ngettext("{n} trigger", "{n} triggers", 3) == "3 triggers"


def test_a_catalog_translates_and_falls_back_to_english(langs):
    assert i18n.set_language("de") == "de"
    assert _("Add a picture") == "Bild hinzufügen"
    assert _("Deleted “{name}”", name="Boss") == "„Boss“ gelöscht"
    assert _("Untranslated") == "Untranslated"       # empty: English
    assert _("Never seen") == "Never seen"
    assert ngettext("{n} trigger", "{n} triggers", 5) == "5 Trigger"


def test_russian_plural_forms(langs):
    i18n.set_language("ru")
    got = {n: ngettext("{n} trigger", "{n} triggers", n) for n in (1, 2, 5, 11, 21, 22, 112)}
    assert got == {1: "1 триггер", 2: "2 триггера", 5: "5 триггеров", 11: "11 триггеров",
                   21: "21 триггер", 22: "22 триггера", 112: "112 триггеров"}


def test_a_broken_placeholder_in_a_translation_shows_it_unfilled(langs):
    (langs / "de.json").write_text(json.dumps({"Hi {name}": "Hallo {nme}"}), encoding="utf-8")
    i18n.set_language("de")
    assert _("Hi {name}", name="x") == "Hallo {nme}"


def test_unknown_or_unreadable_language_is_english(langs):
    (langs / "fr.json").write_text("{not json", encoding="utf-8")
    assert i18n.set_language("fr") == "en"
    assert i18n.set_language("zz") == "en"
    assert _("Add a picture") == "Add a picture"


def test_available_lists_each_catalog_by_its_own_name(langs):
    (langs / "xx.json").write_text("{}", encoding="utf-8")   # never offered
    assert i18n.available() == [("en", "English"), ("de", "Deutsch"),
                                ("pt-BR", "Português (Brasil)"), ("ru", "Русский")]


def test_resolve_follows_windows_and_matches_regions(langs, monkeypatch):
    monkeypatch.setattr(i18n, "windows_language", lambda: "de-AT")
    assert i18n.resolve(i18n.WINDOWS) == "de"
    monkeypatch.setattr(i18n, "windows_language", lambda: "pt-PT")
    assert i18n.resolve("") == "pt-BR"
    monkeypatch.setattr(i18n, "windows_language", lambda: "ja-JP")
    assert i18n.resolve("") == "en"
    assert i18n.resolve("ru") == "ru" and i18n.resolve("en") == "en"
    assert i18n.resolve("xx") == "xx"


def test_startup_reads_the_setting_or_the_env(langs, tmp_path, monkeypatch):
    monkeypatch.setattr(i18n, "windows_language", lambda: "en-GB")
    assert i18n.startup(tmp_path) == "en"                       # no settings yet
    (tmp_path / "config.json").write_text(json.dumps({"language": "de"}), encoding="utf-8")
    assert i18n.startup(tmp_path) == "de" and _("Add a picture") == "Bild hinzufügen"
    (tmp_path / "config.json").write_text(json.dumps({"language": 5}), encoding="utf-8")
    assert i18n.startup(tmp_path) == "en"
    monkeypatch.setenv(i18n.ENV, "xx")
    assert i18n.startup(tmp_path) == "xx"


def test_inside_onion_board_the_page_follows_the_board(langs, monkeypatch):
    monkeypatch.setattr(i18n, "windows_language", lambda: "ru-RU")

    class Board:
        def language(self):
            return "de"

    class OldBoard:            # before language(): Windows' language
        pass

    class Broken:
        def language(self):
            raise RuntimeError("oops")

    assert i18n.follow_host(Board()) == "de"
    assert i18n.follow_host(OldBoard()) == "ru"
    assert i18n.follow_host(Broken()) == "ru"
    Board.language = lambda self: "en"      # the board in English: English, not Windows'
    assert i18n.follow_host(Board()) == "en"
    Board.language = lambda self: "ja"      # one Onion Watch doesn't have
    assert i18n.follow_host(Board()) == "en"


def test_pseudo_language_marks_and_lengthens_but_keeps_placeholders():
    i18n.set_language(i18n.PSEUDO)
    try:
        t = _("Settings")
        assert t.startswith("[") and t.endswith("~]") and len(t) >= len("Settings") * 1.3
        assert "Šéttîñĝš" in t and i18n.is_pseudo(t)
        t = _("Moved “{name}” to <b>{place}</b>", name="Boss", place="Game")
        assert "Boss" in t and "<b>Game</b>" in t and i18n.is_pseudo(t)
        assert "2" in ngettext("{n} trigger", "{n} triggers", 2)
        assert not i18n.is_pseudo("Settings")
    finally:
        i18n.set_language(i18n.ENGLISH)


def test_unwrapped_texts_finds_text_that_skipped_the_translator(qapp):
    from PySide6.QtWidgets import QLabel, QPushButton, QVBoxLayout, QWidget
    i18n.set_language(i18n.PSEUDO)
    try:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.addWidget(QLabel(_("Wrapped")))
        lay.addWidget(QPushButton("Not wrapped"))
        lay.addWidget(QLabel("42 %"))   # no words: fine
        b = QPushButton(_("Ok"))
        b.setToolTip("Raw tip")
        lay.addWidget(b)
        found = i18n.unwrapped_texts(w)
        assert ("QPushButton", "Not wrapped") in found and ("QPushButton", "Raw tip") in found
        assert len(found) == 2
        w.deleteLater()
    finally:
        i18n.set_language(i18n.ENGLISH)


def test_qt_standard_buttons_follow_the_language(qapp, langs):
    from PySide6.QtWidgets import QDialogButtonBox
    i18n.set_language(i18n.PSEUDO)
    try:
        assert i18n.translate_qt_buttons(qapp)
        box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        assert all(i18n.is_pseudo(b.text()) for b in box.buttons())
        i18n.set_language(i18n.ENGLISH)          # back in English: Qt's own words again
        box = QDialogButtonBox(QDialogButtonBox.Cancel)
        assert box.buttons()[0].text() == "Cancel"
    finally:
        i18n.set_language(i18n.ENGLISH)


def test_extract_finds_texts_plurals_and_a_shadowed_translator(tmp_path):
    ex = extract_script()
    src = tmp_path / "pkg"
    src.mkdir()
    (src / "a.py").write_text(
        "from onionwatch import i18n\n"
        "from onionwatch.i18n import _, ngettext\n"
        "def f(n):\n"
        "    return _('Hello'), ngettext('{n} trigger', '{n} triggers', n), i18n._('Engine')\n"
        "def g():\n"
        "    path, _ = 1, 2\n"
        "    return _('Oops')\n"
        "def h(x):\n"
        "    return _(x)\n", encoding="utf-8")
    texts, plural, problems = ex.scan(src)
    assert set(texts) == {"Hello", "{n} trigger", "Oops", "Engine"} and plural["{n} trigger"]
    assert any("g() assigns `_`" in p for p in problems)
    assert any("plain string" in p for p in problems)
    missing, unused = ex.compare(texts, {"_meta": {}, "Hello": "Hallo", "Gone": "Weg"})
    assert missing == ["Engine", "Oops", "{n} trigger"] and unused == ["Gone"]


def test_the_source_has_no_shadowed_translator():
    _texts, _plural, problems = extract_script().scan()
    assert problems == []


def test_every_shipped_catalog_is_complete_and_keeps_the_placeholders():
    """Each language in onionwatch/lang translates every wrapped text, with the same
    {placeholders} and markup, and the right number of plural forms."""
    import re
    ex = extract_script()
    texts, plural, _problems = ex.scan()
    cats = ex.catalogs()
    assert set(cats) == {"de", "es", "fr", "pt-BR", "ru", "zh-CN", "zh-TW", "ja", "ko",
                         "hi", "id", "vi", "th", "tr", "it", "pl", "uk", "nl", "ar",
                         "es-419", "pt-PT", "fil", "ms", "cs", "hu", "ro", "el", "bg",
                         "sv", "da", "nb", "fi"}
    ph = re.compile(r"\{[^{}]*\}|<[^<>]*>|&[a-z]+;")
    for code, (_path, cat) in cats.items():
        missing, unused = ex.compare(texts, cat)
        assert (missing, unused) == ([], []), code
        assert isinstance(cat["_meta"].get("name"), str), code
        forms = i18n.forms(code)
        for key, value in cat.items():
            if key.startswith("_"):
                continue
            assert isinstance(value, list) == plural[key], (code, key)
            for v in value if isinstance(value, list) else [value]:
                assert set(ph.findall(v)) == set(ph.findall(key)), (code, key, v)
            if plural[key]:
                assert len(value) == forms, (code, key)


def test_plural_rules_pick_the_right_form():
    pl, ar, ja = i18n.PLURALS["pl"], i18n.PLURALS["ar"], i18n.PLURALS["ja"]
    assert [pl(n) for n in (1, 2, 5, 12, 22, 25)] == [0, 1, 2, 2, 1, 2]
    assert [ar(n) for n in (0, 1, 2, 3, 11, 100)] == [0, 1, 2, 3, 4, 5]
    assert {ja(n) for n in (0, 1, 2, 5, 100)} == {0}
    # every rule stays inside its language's number of forms
    assert set(i18n.FORMS) <= set(i18n.PLURALS)
    for code, rule in i18n.PLURALS.items():
        assert {rule(n) for n in range(250)} == set(range(i18n.forms(code))), code


def test_chinese_follows_the_region_not_just_the_language(langs, monkeypatch):
    for code in ("zh-CN", "zh-TW"):
        (langs / f"{code}.json").write_text(json.dumps({"_meta": {"name": code}}),
                                            encoding="utf-8")
    for name in ("zh-TW", "zh-HK", "zh-MO", "zh-Hant", "zh-Hant-HK", "zh-Hant-TW"):
        assert i18n.resolve(name) == "zh-TW", name
    for name in ("zh-CN", "zh-SG", "zh", "zh-Hans", "zh-Hans-SG"):
        assert i18n.resolve(name) == "zh-CN", name
    monkeypatch.setattr(i18n, "windows_language", lambda: "zh-HK")
    assert i18n.resolve(i18n.WINDOWS) == "zh-TW"
    (langs / "zh-TW.json").unlink()      # no Traditional catalog: English, not Simplified
    assert i18n.resolve("zh-HK") == "en"
    assert i18n.resolve("de-AT") == "de"


def test_arabic_is_right_to_left(langs):
    assert i18n.is_rtl("ar") and not i18n.is_rtl("de") and not i18n.is_rtl()
    (langs / "ar.json").write_text(json.dumps({"_meta": {"name": "العربية"}},
                                              ensure_ascii=False), encoding="utf-8")
    i18n.set_language("ar")
    assert i18n.is_rtl()


def test_more_plural_rules_and_regions(langs, monkeypatch):
    cs, ro, fil = i18n.PLURALS["cs"], i18n.PLURALS["ro"], i18n.PLURALS["fil"]
    assert [cs(n) for n in (1, 2, 4, 5, 0)] == [0, 1, 1, 2, 2]
    assert [ro(n) for n in (1, 0, 2, 19, 20, 101, 120)] == [0, 1, 1, 1, 2, 1, 2]
    assert [fil(n) for n in (1, 2, 3, 4, 5, 6, 10, 14)] == [0, 0, 0, 1, 0, 1, 0, 1]
    for code in ("es-419", "pt-PT", "nb"):
        (langs / f"{code}.json").write_text(json.dumps({"_meta": {"name": code}}),
                                            encoding="utf-8")
    (langs / "es.json").write_text(json.dumps({"_meta": {"name": "es"}}), encoding="utf-8")
    assert i18n.resolve("es-ES") == "es" and i18n.resolve("es") == "es"
    for name in ("es-MX", "es-AR", "es-CO", "es-US", "es-419"):
        assert i18n.resolve(name) == "es-419", name
    assert i18n.resolve("pt-BR") == "pt-BR" and i18n.resolve("pt") == "pt-BR"
    assert i18n.resolve("pt-PT") == "pt-PT" and i18n.resolve("pt-AO") == "pt-PT"
    assert i18n.resolve("nn-NO") == "nb" and i18n.resolve("nb-NO") == "nb"
    (langs / "es-419.json").unlink()      # no Latin American catalog: Spain's, not English
    assert i18n.resolve("es-MX") == "es"
