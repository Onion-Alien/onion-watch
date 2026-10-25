"""Limited-edition themes (Halloween), as in Onion Board: on offer until their last day,
kept for good by whoever used one in time, gone for everyone else after; their tag and
the lantern logo."""
import datetime

import pytest

from onionwatch.ui.kit import theme
from onionwatch.core.settings import Config
from test_ui import fake_screen  # noqa: F401 (a fixture)

DAY = datetime.timedelta(days=1)


def _last():
    return theme.LIMITED["Halloween"]


def test_halloween_is_the_first_card_then_hoot():
    assert theme.GROUPS[0][1][:3] == ["Halloween", "Hoot", "Dark"]
    names = [n for __, ns in theme.GROUPS for n in ns]
    assert sorted(names) == sorted(theme.THEMES)   # every theme once


def test_on_offer_until_its_last_day_then_gone(monkeypatch):
    monkeypatch.setattr(theme, "kept", set())
    assert theme.offered("Halloween", _last())
    assert not theme.offered("Halloween", _last() + DAY)
    names = [n for __, ns in theme.groups(_last() + DAY) for n in ns]
    assert "Halloween" not in names and "Hoot" in names


def test_used_in_time_its_kept_for_good(monkeypatch):
    monkeypatch.setattr(theme, "kept", set())
    assert not theme.keep("Halloween", _last() + DAY)
    assert theme.keep("Halloween", _last())
    assert theme.offered("Halloween", _last() + 365 * DAY)


def test_a_missed_limited_theme_falls_back(monkeypatch):
    monkeypatch.setattr(theme, "kept", set())
    monkeypatch.setattr(theme, "_today", lambda: _last() + DAY)
    try:
        assert theme.set_current("Halloween") == theme.DEFAULT
    finally:
        theme.set_current(theme.DEFAULT)


@pytest.fixture
def win(qapp, app_dir, fake_screen, monkeypatch):  # noqa: F811
    from onionwatch.ui.window.mainwindow import MainWindow
    monkeypatch.setattr(theme, "kept", set())
    w = MainWindow(Config())
    yield w
    w.quit()
    theme.set_current(theme.DEFAULT)


def test_using_it_keeps_and_saves_it(win):
    win.set_theme("Halloween")
    assert win.cfg.kept_themes == ["Halloween"]
    win.set_theme("Hoot")
    assert win.cfg.kept_themes == ["Halloween"]


def test_the_card_has_the_tag_and_says_until_when(qapp, monkeypatch):
    from onionwatch.ui.settings.settingsdialog import ThemeCard, limited_tip
    monkeypatch.setattr(theme, "kept", set())
    card, plain = ThemeCard("Halloween"), ThemeCard("Hoot")
    assert card.toolTip() == limited_tip("Halloween") and "31" in card.toolTip()
    assert plain.toolTip() == ""
    theme.kept.add("Halloween")
    assert limited_tip("Halloween") != card.toolTip()


@pytest.mark.parametrize("awake", [True, False])
def test_halloween_carves_the_logo_into_a_lantern(qapp, awake):
    t = theme.THEMES["Halloween"]
    lantern = theme.logo_pixmap(64, t["accent"], t["accent2"], awake).toImage()
    onion = theme.logo_pixmap(64, "#ff7517", t["accent2"], awake).toImage()
    assert lantern != onion
    side = lantern.pixelColor(18, 40)   # pumpkin orange, not the white onion
    assert side.red() > 180 and side.blue() < 120
