"""The logo that shows it's watching (ui.watchlogo): the same logo as ever, a start-up
flourish that suits the theme and ends by itself, the eye looking around while it
watches, and nothing moving in the background. Offscreen, no sound."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget

from onionwatch import theme
from onionwatch.ui import watchlogo
from onionwatch.ui.watchlogo import BURST_S, PAINTERS, STYLES, WatchLogo, style_for


def make(qapp, monkeypatch, front=True):
    monkeypatch.setattr(watchlogo.appstate, "active", lambda: front)
    host = QWidget()
    host.resize(600, 300)
    logo = WatchLogo(24, 24, 34, beam_host=host, parent=host)
    host.show()
    qapp.processEvents()
    return host, logo


def test_every_theme_has_a_flourish_of_its_own_kind():
    named = [n for names in STYLES.values() for n in names]
    assert sorted(named) == sorted(theme.THEMES)        # each theme once, none left out
    assert set(STYLES) == set(PAINTERS)
    assert style_for("A theme from a newer board") == "shine"


def test_the_logo_is_the_same_picture_as_ever(qapp, monkeypatch):
    host, logo = make(qapp, monkeypatch)
    assert logo.pixmap().toImage() == theme.themed_logo(48).toImage()
    host.close()


def test_each_flourish_plays_once_and_the_eye_looks_around(qapp, monkeypatch):
    host, logo = make(qapp, monkeypatch)
    try:
        for style in STYLES:
            logo.style_name = style
            logo.set_watching(True)
            assert logo.beam.isVisible() and logo.burst_t() == 0
            for _ in range(int(BURST_S / 0.05) + 2):
                logo.step(0.05)
                logo.beam.grab()                 # every frame paints without an error
            assert logo.burst_t() < 0 and not logo.beam.isVisible(), style
            logo.step(0.8)
            assert logo.look() != 0                      # it looks around
            logo.set_watching(False)
            assert logo.look() == 0 and not logo._timer.isActive()
    finally:
        host.close()


def test_behind_a_game_nothing_moves(qapp, monkeypatch):
    host, logo = make(qapp, monkeypatch, front=False)
    logo.set_watching(True)
    assert not logo.beam.isVisible() and logo.burst_t() < 0
    assert not logo._timer.isActive()
    host.close()


def test_the_flourish_never_takes_a_click(qapp, monkeypatch):
    host, logo = make(qapp, monkeypatch)
    assert logo.beam.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    host.close()
