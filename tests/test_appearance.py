"""Settings → Appearance, laid out like Onion Board's: Language, then one box with tabs
(Themes, Colour, Theme style). The highlight colour and Textured / Plain apply at once,
are saved, and are back on the next start."""
import pytest
from PySide6.QtWidgets import QApplication

from onionwatch import theme
from onionwatch.settings import Config
from test_ui import fake_screen  # noqa: F401 (a fixture)


@pytest.fixture
def win(qapp, app_dir, fake_screen, monkeypatch):  # noqa: F811
    from onionwatch.ui.mainwindow import MainWindow
    w = MainWindow(Config())
    yield w
    w.quit()
    theme.textures_on = False
    theme.set_live("")
    theme.set_current(theme.DEFAULT)


@pytest.fixture
def dlg(win):
    from onionwatch.ui.settingsdialog import SettingsDialog
    d = SettingsDialog(win, "appearance")
    yield d
    d.close()


def test_the_look_box_has_onion_boards_tabs(dlg):
    assert [b.text() for b in dlg.look_tabs] == ["Themes", "Colour", "Theme style"]
    assert dlg.look_shown == 0
    dlg.look_tabs[2].click()
    assert dlg.look_shown == 2 and dlg.look_pages[2].isVisibleTo(dlg)
    assert not dlg.look_pages[0].isVisibleTo(dlg)
    assert len(dlg.theme_cards) == len(theme.THEMES)


def test_textured_patterns_the_cards_and_is_kept(win, dlg):
    dlg._pick_theme("Carbon")
    assert dlg.texture_off.isChecked() and "/tex-carbon" not in theme.stylesheet()
    dlg.texture_on.setChecked(True)
    assert win.cfg.theme_texture and theme.textures_on
    assert "/tex-carbon" in QApplication.instance().styleSheet()
    dlg.texture_off.setChecked(True)
    assert not win.cfg.theme_texture and not theme.textures_on
    assert "/tex-carbon" not in QApplication.instance().styleSheet()


def test_own_highlight_colour_in_every_theme(win, dlg):
    dlg._pick_theme("Dark")
    own = dlg.hue_now.text()
    assert own == "Now: Dark's own colour."
    assert win.set_live_color("#ff3300")
    assert win.cfg.live_color == "#ff3300" and theme.T["live"] != theme.THEMES["Dark"]["live"]
    assert win.triggers.btn_watch.styleSheet() == theme.live_sheet()   # Start watching's
    assert theme.T["live"] in theme.live_sheet()
    dlg._sync_highlight()
    assert dlg.hue_now.text() == "Now: your own colour, in every theme."
    dlg._pick_theme("Royal")   # it stays when the theme changes
    assert theme.live_override == "#ff3300" and win.cfg.theme == "Royal"
    dlg.hue_reset.click()      # back to each theme's own
    assert win.cfg.live_color == "" and theme.T["live"] == theme.THEMES["Royal"]["live"]


def test_saved_look_is_back_on_the_next_start(qapp, app_dir, fake_screen):  # noqa: F811
    from onionwatch.ui.mainwindow import MainWindow
    w = MainWindow(Config(theme="Carbon", live_color="#00AA55", theme_texture=True))
    try:
        assert theme.textures_on and theme.live_override == "#00aa55"
        assert "/tex-carbon" in qapp.styleSheet()
    finally:
        w.quit()
        theme.textures_on = False
        theme.set_live("")
        theme.set_current(theme.DEFAULT)


def test_a_damaged_colour_setting_is_dropped(qapp, app_dir, fake_screen):  # noqa: F811
    from onionwatch.ui.mainwindow import MainWindow
    w = MainWindow(Config(live_color="red; }"))
    try:
        assert theme.live_override == "" and w.cfg.live_color == ""
    finally:
        w.quit()
        theme.set_current(theme.DEFAULT)


def test_inside_the_board_its_colour_and_textured_are_followed():
    class Host:
        def palette(self):
            return dict(theme.THEMES["Lava"])

        def style(self):
            return {"theme": "Lava", "live_color": "#123456", "textures": True}
    try:
        theme.follow_host(Host())
        assert theme.live_override == "#123456" and theme.textures_on
    finally:
        theme.textures_on = False
        theme.set_live("")
        theme.set_current(theme.DEFAULT)


def test_a_theme_switch_covers_every_window_and_fades(win, dlg):
    """The main window and Settings each get a still of themselves with Hoot in the
    new theme while every widget restyles: it fades in over a few frames (never a
    flash) and out once the new theme is in. A colour change is a plain blend."""
    from PySide6.QtCore import QEvent
    from onionwatch.style import cover as kit
    from onionwatch.ui import themecover
    import time
    win.show()
    dlg.show()
    QApplication.processEvents()
    seen, ks = [], []
    real = kit.Cover.repaint
    kit.Cover.repaint = lambda self: (ks.append(self.k), real(self))[1]
    apply = theme.apply

    def during(app, name, live=None):
        seen.extend(c.parentWidget() for w in themecover.windows()
                    for c in w.findChildren(kit.Cover) if c.isVisible())
        return apply(app, name, live)
    theme.apply = during
    try:
        new = next(n for n in theme.THEMES if n != theme.current_name)
        win.set_theme(new)
        with themecover.blended() as plain:
            assert all(c.scrim is None and c.mascot is None for c in plain)
    finally:
        theme.apply = apply
        kit.Cover.repaint = real
    assert theme.current_name == new
    assert win in seen and dlg in seen
    assert ks[:2] == [0.0, 0.0] and 1.0 in ks
    assert max(b - a for a, b in zip(ks, ks[1:])) < 0.7   # faded in, not one jump
    end = time.monotonic() + 3
    while any(w.findChildren(kit.Cover) for w in (win, dlg)) and time.monotonic() < end:
        QApplication.processEvents()
        QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert not win.findChildren(kit.Cover) and not dlg.findChildren(kit.Cover)
