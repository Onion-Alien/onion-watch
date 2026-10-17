"""The logo that shows it's watching (ui.watchlogo): the same logo as ever, a start-up
flourish that suits the theme and ends by itself, the eye looking around while it
watches, and nothing moving in the background. Offscreen, no sound."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget

from onionwatch import theme
from onionwatch.ui import watchlogo
from onionwatch.ui.watchlogo import BURST_S, IDLE, PAINTERS, STYLES, WatchLogo, style_for


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
    assert set(STYLES) == set(PAINTERS) == set(IDLE)
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
            was = logo.look()
            logo.step(0.033)
            assert abs(logo.look() - was) < 0.01         # eases back, never a snap
            for _ in range(60):
                logo.step(0.05)
            assert logo.look() == 0 and logo.burst_t() < 0
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


def test_it_idles_in_every_theme_while_nothing_is_watched(qapp, monkeypatch):
    host, logo = make(qapp, monkeypatch)
    try:
        assert logo._timer.isActive() and not logo.watching
        for style in STYLES:
            logo.style_name = style
            for _ in range(12):
                logo.step(0.37)
                logo.grab()                      # every frame paints without an error
    finally:
        host.close()


def _jumps(logo, secs, fps=30):
    """The biggest frame-to-frame change of the eye, the strength and the laser glow."""
    worst, last = [0.0, 0.0], None
    for _ in range(round(secs * fps)):
        logo.step(1 / fps)
        now = (logo.look(), logo.intensity())
        if last:
            worst = [max(w, abs(a - b)) for w, a, b in zip(worst, now, last)]
        last = now
    return worst


def test_starting_and_stopping_eases_instead_of_snapping(qapp, monkeypatch):
    host, logo = make(qapp, monkeypatch)
    try:
        logo.style_name = "laser"
        logo.set_watching(True)
        look, calm = _jumps(logo, BURST_S + 2)         # flourish, then looking round
        assert logo.intensity() > 0.95 and look < 0.01 and calm < 0.06
        logo.set_watching(False)
        look, calm = _jumps(logo, 2.0)
        assert abs(logo.intensity() - watchlogo.IDLE_CALM) < 0.01
        assert look < 0.01 and calm < 0.06
        logo.set_watching(True)                        # stopped mid-flourish:
        logo.step(0.3)
        logo.set_watching(False)
        assert logo.beam.isVisible() and 0 < logo.cut_fade() <= 1   # it fades out
        for _ in range(10):
            logo.step(0.05)
        assert logo.burst_t() < 0 and not logo.beam.isVisible()
    finally:
        host.close()


def test_the_comic_bounce_starts_and_ends_still():
    from onionwatch.ui.watchlogo import comic_bounce
    k = [comic_bounce(i / 60) for i in range(60 * 8)]
    assert max(k) > 0.9 and min(k) < -0.3                 # a squash, a stretch past it
    assert max(abs(b - a) for a, b in zip(k, k[1:])) < 0.2


def test_a_click_wobbles_it_like_the_board_logo(qapp, monkeypatch):
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QMouseEvent
    host, logo = make(qapp, monkeypatch)
    mid = QPointF(logo.width() / 2, logo.height() / 2)
    press = QMouseEvent(QMouseEvent.Type.MouseButtonPress, mid, logo.mapToGlobal(mid),
                        Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
                        Qt.KeyboardModifier.NoModifier)
    logo.mousePressEvent(press)
    assert logo.squish == 1.0
    logo.grab()                         # paints mid-wobble without trouble
    for _ in range(10):
        logo.step(0.05)
    assert logo.squish == 0.0           # and it settles by itself, in a quarter second
    host.close()
