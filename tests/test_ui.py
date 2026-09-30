"""The window, built on Qt's offscreen platform: a picture becomes a trigger that
plays the default alert when it shows up, a ringing trigger raises the alarm bar
until it's stopped, a trigger can be pointed at a window (picked from a list with
thumbnails), a picture can be cut straight out of a window, and a card says when
its window isn't open. Stand-in captures only; nothing is heard."""
import numpy as np
import pytest
from conftest import SilentOutputStream, process_events
from PySide6.QtCore import QPoint, QPointF, QRect, Qt
from PySide6.QtGui import QImage, QMouseEvent

from onionwatch import screenwatch as sw
from onionwatch import windows
from onionwatch.apphost import AppHost
from onionwatch.player import Player
from onionwatch.screenwatch import Monitor, WindowRef
from onionwatch.settings import Config
from onionwatch.sounds import DEFAULT_SOUND, Library
from onionwatch.ui import triggerspanel
from onionwatch.ui.triggerspanel import PICK_WINDOW, TriggersTab

W, H = 320, 180


def scene(seed=0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return rng.random((H, W)).astype(np.float32) * 0.5 + 0.1


def banner() -> np.ndarray:
    y, x = np.mgrid[0:30, 0:90]
    return (((x // 6 + y // 5) % 2) * 0.8 + 0.1).astype(np.float32)


def showing(screen, pic, x=110, y=70):
    s = screen.copy()
    h, w = pic.shape
    s[y:y + h, x:x + w] = pic
    return s


def as_qimage(gray: np.ndarray) -> QImage:
    g = (np.clip(gray, 0, 1) * 255).astype(np.uint8)
    h, w = g.shape
    return QImage(g.tobytes(), w, h, w, QImage.Format_Grayscale8).copy()


class FakeGrabber:
    frames: list = []

    def __init__(self, mon, w, h, tries=1):
        self.w, self.h = w, h

    def grab(self):
        f = FakeGrabber.frames
        return f[-1] if f else None

    def resize(self, w, h):
        self.w, self.h = w, h

    def close(self):
        pass


@pytest.fixture
def fake_screen(monkeypatch):
    monkeypatch.setattr(sw, "monitors", lambda: [Monitor(0, 0, W, H, True)])
    monkeypatch.setattr(sw, "open_grabber", FakeGrabber)    # never the real screen
    monkeypatch.setattr(sw, "WORK_WIDTH", W)
    FakeGrabber.frames = [scene(1)]
    return FakeGrabber


@pytest.fixture
def tab(qapp, app_dir, fake_screen, monkeypatch):
    monkeypatch.setattr(triggerspanel.QMessageBox, "warning", lambda *a, **k: None)
    monkeypatch.setattr(triggerspanel.QMessageBox, "information", lambda *a, **k: None)
    cfg = Config()
    lib = Library(cfg.sounds)
    tab = TriggersTab(AppHost(cfg, lambda: None, lib, Player()))
    tab.resize(800, 600)
    yield tab
    tab.shutdown()
    tab.host.player.close()


def test_a_pasted_picture_becomes_a_trigger_that_plays_the_default_alert(tab, qapp):
    qapp.clipboard().setImage(as_qimage(banner()))
    tab.add_from_clipboard()
    assert len(tab.triggers) == 1
    t = tab.triggers[0]
    assert t.sounds == [DEFAULT_SOUND] and len(t.images) == 1
    fired = []
    tab.fired.connect(fired.append)
    tab.watcher.interval = 0.01
    tab.set_watching(True)
    assert process_events(qapp, lambda: t.id in tab.watcher.scores)
    SilentOutputStream.opened.clear()
    FakeGrabber.frames.append(showing(scene(1), banner()))
    assert process_events(qapp, lambda: fired == [t])
    assert process_events(qapp, lambda: SilentOutputStream.opened
                          and SilentOutputStream.opened[-1].peak > 0.1)
    assert tab.host.screen["on"] is True and tab.host.screen["triggers"][0]["id"] == t.id


def test_a_ringing_trigger_raises_the_alarm_bar_until_stopped(qapp, app_dir, fake_screen):
    from onionwatch.ui.mainwindow import MainWindow
    cfg = Config()
    win = MainWindow(cfg)
    try:
        qapp.clipboard().setImage(as_qimage(banner()))
        win.triggers.add_from_clipboard()
        row = next(iter(win.triggers.rows.values()))
        row.chk_ring.setChecked(True)
        assert cfg.screen["triggers"][0]["ring"] is True
        assert row.state.text().startswith("Rings until stopped")
        win.triggers._fire(row.t.id, win.triggers._gen)
        assert win.player.ringing == [row.t.id]
        assert not win.alarm.isHidden() and row.t.name in win.alarm.text.text()
        win.alarm.btn_stop.click()
        assert win.player.ringing == [] and win.alarm.isHidden()
        # the test button never rings
        row.btn_test.click()
        assert win.player.ringing == []
    finally:
        win.quit()


def test_a_card_can_be_pointed_at_a_window(tab, monkeypatch):
    tab._new(as_qimage(banner()), "Rare")
    row = next(iter(tab.rows.values()))
    ref = WindowRef("game.exe", "Game", 1)
    monkeypatch.setattr(tab, "pick_places", lambda current: [ref])
    i = row.where.findData(PICK_WINDOW)
    row.where.setCurrentIndex(i)
    row.where.activated.emit(i)
    assert row.t.window == ref and row.t.source == ref
    assert row.where.currentText() == "Game (copy 2)"
    assert tab.host.screen["triggers"][0]["window"] == {"exe": "game.exe", "title": "Game",
                                                       "nth": 1}
    # back to the default
    row.where.setCurrentIndex(0)
    row.where.activated.emit(0)
    assert row.t.window is None and row.t.source is None


def test_the_default_can_be_a_window(tab, monkeypatch):
    ref = WindowRef("game.exe", "Game", 0)
    monkeypatch.setattr(tab, "pick_window", lambda current=None: ref)
    i = tab.cb_where.findData(PICK_WINDOW)
    tab.cb_where.activated.emit(i)
    assert tab.watcher.default == ref
    assert tab.host.screen["window"] == ref.to_raw()
    assert tab.cb_where.currentText() == "Game"
    tab.cb_where.activated.emit(0)                  # screen 1
    assert tab.watcher.default == 0 and tab.host.screen["window"] is None


def test_a_card_says_when_its_window_is_not_open(tab, qapp, monkeypatch):
    ref = WindowRef("game.exe", "Game", 0)
    monkeypatch.setattr(windows, "find", lambda r, wins=None: None)
    monkeypatch.setattr(sw, "WINDOW_RETRY_S", 0.05)
    tab._new(as_qimage(banner()), "Rare")
    row = next(iter(tab.rows.values()))
    row.t.window = ref
    tab._store()
    tab.watcher.interval = 0.01
    tab.set_watching(True)
    assert process_events(qapp, lambda: row.state.text() == "Waiting for Game to open")
    tab.set_watching(False)
    assert not row.state.text().startswith("Waiting")


def test_a_picture_is_cut_straight_out_of_a_window(tab, monkeypatch):
    ref = WindowRef("game.exe", "Game", 0)
    px = np.zeros((H, W, 4), np.uint8)
    px[..., :3] = (showing(scene(2), banner())[..., None] * 255).astype(np.uint8)
    px[..., 3] = 255
    monkeypatch.setattr(windows, "find", lambda r, wins=None: windows.WindowInfo(
        7, "Game", "game.exe", 7, 0, W, H))
    monkeypatch.setattr(windows, "snapshot", lambda hwnd: px)
    from onionwatch.ui import snip

    def fake_exec(dlg):
        dlg.view.selection = QRect(110, 70, 90, 30)
        dlg._accept()
        return True
    monkeypatch.setattr(snip.SnipDialog, "exec", fake_exec)
    tab.set_default(ref)
    tab.add_from_cut()
    assert len(tab.triggers) == 1
    got = QImage(tab.triggers[0].images[0])
    assert (got.width(), got.height()) == (90, 30)


def test_the_crop_view_maps_a_drag_to_the_capture_pixels(qapp):
    from onionwatch.ui.snip import CropView
    view = CropView(as_qimage(scene(3)))
    view.resize(W * 2, H * 2)                      # shown at twice the size

    def ev(kind, x, y):
        return QMouseEvent(kind, QPointF(x, y), QPointF(x, y), Qt.LeftButton, Qt.LeftButton,
                           Qt.NoModifier)
    view.mousePressEvent(ev(QMouseEvent.MouseButtonPress, 20, 40))
    view.mouseMoveEvent(ev(QMouseEvent.MouseMove, 220, 100))
    view.mouseReleaseEvent(ev(QMouseEvent.MouseButtonRelease, 220, 100))
    assert view.selection == QRect(QPoint(10, 20), QPoint(110, 50)).normalized()


def test_the_window_picker_lists_windows_and_tells_copies_apart(qapp, monkeypatch):
    wins = [windows.WindowInfo(1, "Game", "game.exe", 1, 100, W, H),
            windows.WindowInfo(2, "Game", "game.exe", 2, 200, W, H),
            windows.WindowInfo(3, "Notes", "notepad.exe", 3, 50, W, H, minimized=True)]
    monkeypatch.setattr(windows, "list_windows", lambda: list(wins))
    monkeypatch.setattr(windows, "snapshot", lambda hwnd: np.full((H, W, 4), 90, np.uint8))
    from onionwatch.ui.windowpicker import WindowPicker
    dlg = WindowPicker(None, WindowRef("game.exe", "Game", 1))
    texts = [dlg.list.item(i).text() for i in range(dlg.list.count())]
    assert texts == ["Game\ngame.exe", "Game\ngame.exe · copy 2",
                     "Notes\nnotepad.exe · minimized"]
    assert dlg.list.currentRow() == 1                 # the current choice is selected
    process_events(qapp, lambda: not dlg._pending)
    dlg.list.setCurrentRow(0)
    dlg._accept()
    assert dlg.chosen == WindowRef("game.exe", "Game", 0)


def test_settings_change_the_theme_and_volume_live(qapp, app_dir, fake_screen):
    from onionwatch.ui.mainwindow import MainWindow
    from onionwatch.ui.settingsdialog import SettingsDialog
    win = MainWindow(Config())
    try:
        dlg = SettingsDialog(win)
        dlg.theme.setCurrentIndex(dlg.theme.findData("Midnight"))
        assert win.cfg.theme == "Midnight"
        dlg.volume.setValue(40)
        assert win.player.volume == pytest.approx(0.4) and win.cfg.volume == pytest.approx(0.4)
        dlg.notify.setChecked(False)
        assert win.cfg.notify is False
        win.save_now()
        assert Config.load().theme == "Midnight"
    finally:
        win.quit()
