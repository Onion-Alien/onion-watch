"""No piece of a screen is shown while it has no parent: on Windows each one flashed up
on the desktop as a little blank window of its own for a moment, and lagged the app."""
from PySide6.QtCore import QEvent, QObject
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QWidget

from onionwatch import windows
from onionwatch import screenwatch as sw
from onionwatch.ui import snip
from onionwatch.ui.viewer import PictureViewer
from onionwatch.ui.windowpicker import WindowPicker
from test_categories import make, raw  # noqa: F401 - the fixture

W, H = 320, 180


def windows_shown(qapp, build) -> list[str]:
    """What `build()` shows (or gives a native window) while it has no parent."""
    stray = []

    class Spy(QObject):
        def eventFilter(self, obj, ev):
            if (ev.type() in (QEvent.Show, QEvent.WinIdChange) and isinstance(obj, QWidget)
                    and obj.isWindow() and obj.parent() is None):
                stray.append(type(obj).__name__)
            return False

    spy = Spy()
    qapp.installEventFilter(spy)
    try:
        build()
        qapp.processEvents()
    finally:
        qapp.removeEventFilter(spy)
    return stray


def test_a_card_with_several_sounds_shows_its_play_mode_inside_the_card(make, qapp):  # noqa: F811
    assert windows_shown(qapp, lambda: make({"triggers": [raw(1, sounds=["s1", "s2"])]})) == []


def test_the_picture_viewer_shows_swap_and_remove_inside_it(qapp, tmp_path):
    img = QImage(40, 30, QImage.Format_RGB32)
    img.fill(QColor("red"))
    path = str(tmp_path / "pic.png")
    img.save(path)
    made = []
    assert windows_shown(qapp, lambda: made.append(PictureViewer(
        "Pictures", lambda: [path], swap=lambda i: None, remove=lambda i: None))) == []
    assert made[0].btn_swap.parent() is made[0] and made[0].btn_remove.parent() is made[0]


def test_the_area_dialog_shows_its_buttons_inside_it(qapp):
    img = QImage(200, 100, QImage.Format_RGB32)
    img.fill(QColor(20, 20, 40))
    assert windows_shown(qapp, lambda: snip.AreaDialog(img, "Game")) == []
    assert windows_shown(qapp, lambda: snip.AreaDialog(img, "Game", colour="")) == []


def test_the_window_picker_shows_every_copy_inside_it(qapp, monkeypatch):
    monkeypatch.setattr(windows, "list_windows",
                        lambda: [windows.WindowInfo(1, "Game", "game.exe", 1, 100, W, H)])
    monkeypatch.setattr(windows, "snapshot", lambda hwnd: None)
    monkeypatch.setattr(sw, "monitors", lambda: [sw.Monitor(0, 0, W, H, True)])
    assert windows_shown(qapp, lambda: WindowPicker(None, [], multi=True)) == []
