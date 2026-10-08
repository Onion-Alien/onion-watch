"""The language picker window (the same as Onion Board's, plus Windows' language):
a tile per language, search in any name, Enter or a click picks, ✕ / Esc picks
nothing. And Settings → Appearance → Language, which opens it."""
import pytest
from PySide6.QtCore import Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QDialog, QLabel

from onionwatch import i18n
from onionwatch.settings import Config
from onionwatch.ui.langpick import LanguageDialog, glyph
from test_ui import fake_screen  # noqa: F401 (a fixture)


@pytest.fixture(autouse=True)
def english(monkeypatch):
    monkeypatch.delenv(i18n.ENV, raising=False)
    monkeypatch.setattr(i18n, "windows_language", lambda: "en-US")
    i18n.set_language("en")
    yield
    i18n.set_language("en")


def test_a_tile_per_language_windows_then_english_the_one_picked_ticked(qapp):
    d = LanguageDialog(current="en")
    codes = [t.code for t in d.tiles]
    assert codes[:2] == [i18n.WINDOWS, "en"] and set(codes[1:]) == set(i18n.codes())
    assert [t.code for t in d.tiles if t.isChecked()] == ["en"]
    de = next(t for t in d.tiles if t.code == "de")
    assert (de.own, de.other, de.mark) == ("Deutsch", "German", "De")
    assert d.tiles[0].own == "Windows' language" and d.tiles[0].other == "English"
    assert [t.code for t in LanguageDialog(current="").tiles if t.isChecked()] == [""]
    assert i18n.WINDOWS not in [t.code for t in LanguageDialog(windows=False).tiles]


def test_search_finds_a_language_by_any_of_its_names(qapp):
    d = LanguageDialog()

    def find(text):
        d.search.setText(text)
        return [t.code for t in d.visible_tiles()]
    assert find("deutsch") == ["de"] and find("GERMAN") == ["de"] and find("de") != []
    assert find("日本") == ["ja"] and find("japanese") == ["ja"]
    assert set(find("espanol")) == {"es-419", "es"}           # without the accent
    assert set(find("portug")) == {"pt-BR", "pt-PT"}
    assert find("български") == ["bg"] and find("pt-pt") == ["pt-PT"]
    assert find("windows") == [i18n.WINDOWS]
    assert find("zz-nothing") == [] and d.none.isVisibleTo(d)
    assert len(find("")) == len(d.tiles) and not d.none.isVisibleTo(d)


def test_a_click_or_enter_picks_and_esc_picks_nothing(qapp):
    d = LanguageDialog()
    got = []
    d.chosen.connect(got.append)
    next(t for t in d.tiles if t.code == "ko").click()
    assert got == ["ko"] and d.picked == "ko" and d.result() == QDialog.Accepted
    d = LanguageDialog()
    d.search.setText("svenska")
    QTest.keyClick(d.search, Qt.Key_Return)
    assert d.picked == "sv"
    d = LanguageDialog()
    d.show()
    QTest.keyClick(d, Qt.Key_Escape)
    assert d.picked is None and d.result() == QDialog.Rejected


def test_names_under_each_tile_are_in_the_language_showing(qapp):
    i18n.set_language("de")
    d = LanguageDialog()
    ja = next(t for t in d.tiles if t.code == "ja")
    assert ja.other == "Japanisch"
    assert next(t for t in d.tiles if t.code == "de").other == ""   # its own name already
    assert d.windowTitle() == "Sprache"


def test_marks_read_as_one_sign_in_each_script():
    assert glyph("hi", "हिन्दी") == "हि"           # the vowel sign stays on its letter
    assert glyph("ar", "العربية") == "ع"
    assert glyph("ja", "日本語") == "日本"
    assert glyph("id", "Bahasa Indonesia") != glyph("ms", "Bahasa Melayu")


def test_the_window_stays_narrow(qapp):
    assert LanguageDialog().width() <= 620


# ------------------------------------------------------------------ Settings
@pytest.fixture
def win(qapp, app_dir, fake_screen, monkeypatch):  # noqa: F811
    from onionwatch.ui.mainwindow import MainWindow
    w = MainWindow(Config())
    w.restarts = []
    monkeypatch.setattr(w, "restart", lambda: w.restarts.append(1))
    yield w
    w.quit()


def test_language_is_first_on_appearance_and_opens_the_picker(win, monkeypatch):
    from onionwatch.ui.settingsdialog import SettingsDialog
    monkeypatch.setattr(i18n, "windows_language", lambda: "de-DE")
    win.cfg.language = "en"
    d = SettingsDialog(win, "appearance")
    btn = d.lang_button
    card = btn.parentWidget()
    assert card.parentWidget().layout().itemAt(0).widget() is card    # first on the page
    # the title in Windows' language too: found by someone who can't read English
    assert card.findChild(QLabel).text() == "LANGUAGE · SPRACHE"
    assert btn.text().startswith("English") and not d.btn_restart.isVisibleTo(d)

    def in_the_picker():
        dlg = d.lang_dialog
        dlg.search.setText("japanese")                               # English name
        assert [t.code for t in dlg.visible_tiles()] == ["ja"]
        dlg.search.returnPressed.emit()                              # Enter picks it
    QTimer.singleShot(0, in_the_picker)
    btn.click()
    assert win.cfg.language == "ja" and not win.restarts   # saved, no surprise restart
    assert btn.text().startswith("日本語")
    # what happens next, in the language picked
    assert d.lang_note.text() == i18n.in_language(
        "ja", lambda: i18n._("Onion Watch shows {name} after a restart.", name="日本語"))
    assert "Onion Watch" in d.lang_note.text() and d.lang_note.text() != "Onion Watch shows"
    assert d.btn_restart.text() == i18n.in_language("ja", lambda: i18n._("Restart now"))
    assert d.btn_restart.isVisibleTo(d)
    d.btn_restart.click()
    assert win.restarts == [1]
    assert Config.load().language == "ja" or win.save_now() is None and \
        Config.load().language == "ja"
    d.close()


def test_closing_the_picker_changes_nothing(win):
    from onionwatch.ui.settingsdialog import SettingsDialog
    win.cfg.language = ""
    d = SettingsDialog(win, "appearance")
    before = d.lang_button.text()
    QTimer.singleShot(0, lambda: d.lang_dialog.reject())
    d.lang_button.click()
    assert win.cfg.language == "" and d.lang_button.text() == before
    assert before.startswith("Windows' language · English")
    d.close()


def test_windows_language_back_from_a_picked_one(win):
    from onionwatch.ui.settingsdialog import SettingsDialog
    win.cfg.language = "de"
    d = SettingsDialog(win, "appearance")
    assert d.btn_restart.isVisibleTo(d)         # German picked, English showing
    QTimer.singleShot(0, lambda: d.lang_dialog.tiles[0].click())
    d.lang_button.click()
    assert win.cfg.language == i18n.WINDOWS
    assert not d.btn_restart.isVisibleTo(d)     # Windows' is English: nothing to restart for
    d.close()


def test_arabic_restart_note_reads_right_to_left(win):
    from onionwatch.ui.settingsdialog import SettingsDialog
    win.cfg.language = "ar"
    d = SettingsDialog(win, "appearance")
    assert d.lang_note.layoutDirection() == Qt.RightToLeft
    assert d.lang_note.text().startswith("‏")
    d.close()


def test_settings_pages_like_the_boards(win):
    from onionwatch.ui.settingsdialog import SettingsDialog
    d = SettingsDialog(win)
    assert d.categories.count() == d.pages.count() == 5
    for key in d.page_keys:
        d.show_page(key)
        assert d.pages.currentIndex() == d.page_keys.index(key)
    assert d.width() <= 900
    d.close()


def test_settings_list_names_have_no_tip_saying_the_same(win):
    """Hovering a page name that fits shows nothing: the tip only repeated it. A name
    cut short (a long translation) still shows in full on hover."""
    from onionwatch.ui.settingsdialog import SettingsDialog
    d = SettingsDialog(win)
    items = [d.categories.item(i) for i in range(d.categories.count())]
    assert not next(it for it in items if it.text() == "Audio").toolTip()
    fm = d.categories.fontMetrics()
    for it in items:
        room = d.categories.width() - d.categories.iconSize().width() - 24
        cut = fm.horizontalAdvance(it.text()) > room
        assert it.toolTip() == (it.text() if cut else "")
    d.close()
