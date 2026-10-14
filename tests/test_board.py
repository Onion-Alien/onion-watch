"""Onion Watch as Onion Board's add-on (onionwatch.board): create() refuses a host it
can't run in, and the tab it gives back rings through the board, says so with the
board's notification and stops with the board's Stop all. Stand-in screens and a
stand-in board; nothing is heard."""
import inspect

import shiboken6

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget
from conftest import process_events
from fakehost import FakeHost
from test_ui import FakeGrabber, W, H, as_qimage, banner, scene, showing

from onionwatch import board, theme
from onionwatch import screenwatch as sw
from onionwatch.host import API_VERSION
from onionwatch.screenwatch import Monitor
from onionwatch.ui.pages import TriggerPages


@pytest.fixture
def tab(qapp, tmp_path, monkeypatch):
    monkeypatch.setattr(sw, "monitors", lambda: [Monitor(0, 0, W, H, True)])
    monkeypatch.setattr(sw, "open_grabber", FakeGrabber)
    monkeypatch.setattr(sw, "WORK_WIDTH", W)
    FakeGrabber.frames = [scene(1)]
    host = FakeHost(tmp_path / "board")
    tab = board.create(host)
    yield tab
    tab.shutdown()
    theme.set_current(theme.DEFAULT)


def test_a_host_it_cannot_run_in_is_refused_with_a_reason(tmp_path):
    old = FakeHost(tmp_path)
    old.api_version = API_VERSION - 1
    with pytest.raises(board.IncompatibleHost, match="needs a newer Test Board"):
        board.create(old)
    with pytest.raises(board.IncompatibleHost, match="isn't a triggers host"):
        board.create(object())


def test_it_takes_the_boards_colours_now_and_when_they_change(tab):
    assert theme.T["accent"] == "#123456"
    tab.host.colours = {"accent": "#abcdef"}
    tab.retheme()
    assert theme.T["accent"] == "#abcdef"


def test_the_tab_shows_the_logo_left_of_its_tabs(tab):
    # the board has no Onion Watch header, so the owl sits in the tab row; the app's
    # own window shows it in its header instead (TriggerPages' default: none)
    pages = tab.pages
    assert pages.logo is not None and pages.logo.toolTip() == "Onion Watch"
    row = pages.layout().itemAt(0).layout()
    assert row.itemAt(0).widget() is pages.logo and row.itemAt(1).widget() is pages.tabs
    assert inspect.signature(TriggerPages).parameters["logo"].default is False
    # ...and only the board gets the Settings tab: the app has its own Settings window
    assert inspect.signature(TriggerPages).parameters["settings_menu"].default is None


def test_a_ringing_trigger_notifies_and_stop_all_stops_it(tab, qapp):
    host, panel = tab.host, tab.panel
    active = []
    tab.active_changed.connect(active.append)
    panel._new(as_qimage(banner()), "Rare")
    row = next(iter(panel.rows.values()))
    row.sound.activated.emit(row.sound.findData("s2"))
    row.chk_ring.setChecked(True)
    panel.watcher.interval = 0.01
    panel.set_watching(True)
    assert active == [True] and tab.is_active()
    assert process_events(qapp, lambda: row.t.id in panel.watcher.scores)
    FakeGrabber.frames.append(showing(scene(1), banner()))
    assert process_events(qapp, lambda: host.ringing() == [row.t.id])
    assert host.notes == [("Rare", "It just showed up. Ringing until the game moves.")]
    assert tab.alarm.ringing
    tab.cancel_pending()                    # the board's Stop all
    assert host.ringing() == [] and not tab.alarm.ringing


def test_the_board_is_told_what_it_may_squeeze(tab):
    parts = tab.fit_parts()
    # new triggers: + New trigger; the check speed: under ⚙ (an older board asking for
    # "cut", "add" or "interval_label" gets nothing, and leaves it be)
    assert set(parts) == {"hint", "watch"}
    tab.panel.btn_watch.setProperty("compact", True)   # the board shows it icon only
    tab.panel.btn_watch.setText("")
    tab.panel.set_watching(False)
    assert tab.panel.btn_watch.text() == ""
    assert tab.panel.btn_watch.property("full_text") == "Start watching"


def test_a_board_can_have_the_tab_made_on_its_page(qapp, tmp_path):
    """create(host, parent): made where it goes, not moved in finished (that restyled
    every widget again and made the board's tab slow to open)."""
    page = QWidget()
    tab = board.create(FakeHost(tmp_path / "board"), parent=page)
    try:
        assert tab.parent() is page
        assert tab.pages.parent() is tab and tab.panel.parent() is tab.pages.stack
    finally:
        tab.shutdown()
        theme.set_current(theme.DEFAULT)


def test_opening_the_tab_makes_no_closed_cards_editor(tab, qapp):
    """The Playing now bar checks every card's Test button: a card whose editor isn't
    made yet is skipped, not made (that made all of them, every time the tab opened)."""
    panel = tab.panel
    for name in ("One", "Two", "Three"):
        panel._new(as_qimage(banner()), name)
    host = tab.host
    tab.shutdown()
    again = board.create(host)
    try:
        rows = list(again.panel.rows.values())
        assert len(rows) == 3
        assert not any(r.built for r in rows if not r.is_open)
        assert again.pages.playing.panel.playing_now() == []
        assert not any(r.built for r in rows if not r.is_open)
    finally:
        again.shutdown()


def test_the_boards_remove_item_is_a_button_on_the_settings_tab(tab, qapp):
    """Onion Board puts "Remove Onion Watch…" last in the menu of the add-on's
    btn_more: that menu is the Settings tab's, never the triggers' More menu."""
    menu = tab.btn_more.menu()
    assert menu is not None and tab.btn_more is not tab.panel.btn_more
    settings = tab.pages.settings
    assert tab.pages.tabs.count() == 3 and tab.pages.tabs.tabText(2) == "Settings"
    tab.pages.show_settings()
    tab.show()
    process_events(qapp, lambda: settings.isVisible())
    assert settings.remove_card.isHidden()          # nothing added: a bundled add-on
    removed = []
    menu.addSeparator()
    menu.addAction("Remove Onion Watch…", lambda: removed.append(True))
    tab.pages.tabs.setCurrentIndex(0)
    tab.pages.show_settings()
    process_events(qapp, lambda: settings.isVisible())
    assert not settings.remove_card.isHidden()
    assert settings.btn_remove.text() == "Remove Onion Watch…"
    settings.btn_remove.click()
    assert removed == [True]
    assert "Remove" not in " ".join(a.text() for a in tab.panel.btn_more.menu().actions())


def test_the_chip_on_the_bottom_bar_opens_the_settings_tab(tab):
    tab.panel.show_watching()
    assert tab.pages.tabs.currentIndex() == 2


def test_the_owl_is_the_boards_onion_size_on_its_line(tab):
    from onionwatch.ui.pages import LOGO_BOX, LOGO_PX
    assert (LOGO_PX, LOGO_BOX) == (24, 34)      # Onion Board's sidebar.LOGO and its box
    assert tab.pages.logo.size().width() == LOGO_PX
    assert tab.pages.logo.size().height() == LOGO_BOX
    assert tab.layout().contentsMargins().top() == 0


@pytest.mark.parametrize("board_rtl", [False, True])
def test_in_arabic_the_tab_is_mirrored_unless_the_board_already_is(
        qapp, tmp_path, monkeypatch, board_rtl):
    from PySide6.QtCore import Qt

    from onionwatch import i18n
    monkeypatch.setattr(sw, "monitors", lambda: [Monitor(0, 0, W, H, True)])
    monkeypatch.setattr(sw, "open_grabber", FakeGrabber)
    monkeypatch.setenv(i18n.ENV, "ar")
    qapp.setLayoutDirection(Qt.RightToLeft if board_rtl else Qt.LeftToRight)
    try:
        tab = board.create(FakeHost(tmp_path / "board"))
        assert tab.layoutDirection() == Qt.RightToLeft
        # the board mirrored the app: the tab follows it rather than setting its own
        assert tab.testAttribute(Qt.WA_SetLayoutDirection) != board_rtl
        tab.shutdown()
    finally:
        qapp.setLayoutDirection(Qt.LeftToRight)
        i18n.set_language(i18n.ENGLISH)
        theme.set_current(theme.DEFAULT)


@pytest.mark.parametrize("lang, word", [("bg", "Тригери"), ("sw", "Triggers")])
def test_the_tab_follows_the_boards_language_and_has_no_picker_of_its_own(
        qapp, tmp_path, monkeypatch, lang, word):
    """A board in Bulgarian (one of the newer languages) gets a Bulgarian tab; a board
    language Onion Watch hasn't got (Swahili) gets English, without errors. Either way
    the only language setting is the board's: the tab has none."""
    from PySide6.QtWidgets import QWidget

    from onionwatch import i18n
    monkeypatch.setattr(sw, "monitors", lambda: [Monitor(0, 0, W, H, True)])
    monkeypatch.setattr(sw, "open_grabber", FakeGrabber)
    monkeypatch.delenv(i18n.ENV, raising=False)
    host = FakeHost(tmp_path / "board")
    host.language = lambda: lang
    try:
        tab = board.create(host)
        assert i18n.current() == (lang if lang != "sw" else "en")
        assert i18n._("Triggers") == word
        names = " ".join(w.objectName() + type(w).__name__ for w in tab.findChildren(QWidget))
        assert "LanguageDialog" not in names and "LangTile" not in names
        assert not hasattr(tab.panel, "lang_button")
        tab.shutdown()
    finally:
        i18n.set_language(i18n.ENGLISH)
        theme.set_current(theme.DEFAULT)


def test_text_made_as_modules_load_is_in_the_boards_language(monkeypatch):
    """Onion Board imports every file of the add-on before create(host): Onion Watch's
    i18n takes the board's language as it loads (_board_language_now, run at the end of
    the module), so module-level text (Hoot's lines, the trigger modes…) isn't left in
    English."""
    import sys
    import types

    from onionwatch import i18n
    board = types.ModuleType("soundboard.i18n")
    board.current = lambda: "de"
    monkeypatch.setitem(sys.modules, i18n.BOARD_I18N, board)
    monkeypatch.delenv(i18n.ENV, raising=False)
    try:
        i18n._board_language_now()
        assert i18n.current() == "de"
        assert i18n._("let's watch something!") == "lass uns was beobachten!"
        board.current = lambda: "zz"          # a language Onion Watch hasn't got: English
        i18n._board_language_now()
        assert i18n.current() == "en"
        i18n.set_language("ru")
        monkeypatch.delitem(sys.modules, i18n.BOARD_I18N)   # standalone: untouched
        i18n._board_language_now()
        assert i18n.current() == "ru"
    finally:
        i18n.set_language(i18n.ENGLISH)


def test_the_logo_takes_the_boards_colours(tab):
    # like Onion Board's own mark: the theme's accent, not Onion Watch's fixed teal
    before = tab.pages.logo.pixmap().toImage()
    tab.host.colours = {"accent": "#e0306a", "accent2": "#ffd400"}
    tab.retheme()
    after = tab.pages.logo.pixmap().toImage()
    assert after != before
    tab.host.colours = {"accent": "#123456"}
    tab.retheme()
    assert tab.pages.logo.pixmap().toImage() == before    # and back with the board's


def test_the_play_menu_searches_and_shows_the_boards_categories(tab, qapp):
    panel = tab.panel
    tab.host.sound_categories = lambda: [("Memes", ["s2"])]
    panel._new(as_qimage(banner()), "Rare")
    row = panel.editor if panel.editor is not None else next(iter(panel.rows.values()))
    row.sound.showPopup()
    menu = row.sound.menu
    names = dict(tab.host.sounds())
    assert menu.category.isVisibleTo(menu) and menu.category.itemText(1) == "Memes"
    assert menu.shown() == [sid for sid, _n in tab.host.sounds()]
    menu.category.setCurrentIndex(1)
    assert menu.shown() == ["s2"]
    menu.category.setCurrentIndex(0)
    menu.search.setText(names["s2"][:3].upper())          # any case
    assert "s2" in menu.shown()
    menu.search.setText("zzz no such sound")
    assert menu.shown() == [] and menu.empty.isVisibleTo(menu)
    menu.search.setText(names["s2"])
    menu.search.returnPressed.emit()                      # Enter picks the first
    assert "s2" in row.t.sounds and row.sound.menu is None
    row.sound.showPopup()                                  # on the trigger: not pickable
    menu = row.sound.menu
    menu.search.setText(names["s2"])
    item = menu.list.item(0)
    assert item.data(256) == "s2" and not item.flags() & Qt.ItemFlag.ItemIsEnabled
    menu.close()


def test_the_sentence_choices_all_wear_the_accent(tab):
    tab.panel._new(as_qimage(banner()), "Rare")
    row = tab.panel.editor if tab.panel.editor is not None else next(iter(tab.panel.rows.values()))
    assert {c.property("token") for c in (row.mode, row.where, row.pick, row.until)} == {"accent"}


def test_the_play_menu_stays_open_with_the_category_list(tab, qapp):
    # the category list was shown before it had a parent: a window of its own for a
    # moment, which closed the menu as soon as it opened
    tab.host.sound_categories = lambda: [("Memes", ["s2"])]
    tab.show()
    tab.panel._new(as_qimage(banner()), "Rare")
    row = tab.panel.editor if tab.panel.editor is not None else next(iter(tab.panel.rows.values()))
    row.sound.showPopup()
    menu = row.sound.menu
    for _ in range(10):
        qapp.processEvents()
    assert shiboken6.isValid(menu) and menu.isVisible()
    menu.close()
    tab.hide()
