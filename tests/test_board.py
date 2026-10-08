"""Onion Watch as Onion Board's add-on (onionwatch.board): create() refuses a host it
can't run in, and the tab it gives back rings through the board, says so with the
board's notification and stops with the board's Stop all. Stand-in screens and a
stand-in board; nothing is heard."""
import pytest
from conftest import process_events
from fakehost import FakeHost
from test_ui import FakeGrabber, W, H, as_qimage, banner, scene, showing

from onionwatch import board, theme
from onionwatch import screenwatch as sw
from onionwatch.host import API_VERSION
from onionwatch.screenwatch import Monitor


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
    # paste: in Add; the check speed: under ⚙ (an older board asking for "interval_label"
    # gets nothing, and leaves it be)
    assert set(parts) == {"hint", "watch", "cut", "add"}
    tab.panel.btn_watch.setProperty("compact", True)   # the board shows it icon only
    tab.panel.btn_watch.setText("")
    tab.panel.set_watching(False)
    assert tab.panel.btn_watch.text() == ""
    assert tab.panel.btn_watch.property("full_text") == "Start watching"


def test_the_board_can_reach_the_more_menu(tab):
    """Onion Board puts "Remove Onion Watch…" last in the add-on's More menu."""
    assert tab.btn_more is tab.panel.btn_more and tab.btn_more.menu() is not None


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
