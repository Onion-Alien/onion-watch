"""The window, built on Qt's offscreen platform: a picture becomes a trigger that
plays the default alert when it shows up, a ringing trigger raises the alarm bar
until it's stopped, a trigger can be pointed at a window (picked from a list with
thumbnails), a picture can be cut straight out of a window, and a card says when
its window isn't open. Stand-in captures only; nothing is heard."""
import threading

import numpy as np
import pytest
from conftest import SilentOutputStream, process_events
from PySide6.QtCore import QPoint, QPointF, QRect, Qt
from PySide6.QtGui import QImage, QMouseEvent
from PySide6.QtWidgets import QLabel

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
    tab.deleteLater()
    from PySide6.QtCore import QCoreApplication, QEvent
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


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
        assert "keeps playing until the game moves" in row.state.text()
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
    tab.show()      # notes are only worked out while the tab can be seen
    tab.watcher.interval = 0.01
    tab.set_watching(True)
    assert process_events(qapp, lambda: row.state.text() == "Waiting for Game to open")
    tab.set_watching(False)
    assert not row.state.text().startswith("Waiting")


def test_a_card_stops_saying_watching_once_watching_stops(tab, qapp, monkeypatch):
    monkeypatch.setattr(tab, "isVisible", lambda: True)    # the poll only paints when shown
    tab._new(as_qimage(banner()), "Rare")
    row = next(iter(tab.rows.values()))
    tab.watcher.interval = 0.01
    tab.set_watching(True)
    assert process_events(qapp, lambda: row.watching)
    tab.set_watching(False)
    assert not row.watching and "Watching" not in row.live.text()


def test_a_card_says_when_its_window_never_comes_out(tab, qapp, monkeypatch):
    """A window PrintWindow can't copy gives nothing, ever: the card says so instead
    of showing "Watching" while the trigger can never go off."""
    ref = WindowRef("game.exe", "Game", 0)

    class Blank:
        def __init__(self, ref, w, h):
            self.w, self.h, self.source, self.minimized = w, h, (W, H), False

        def grab(self):
            return None

        def resize(self, w, h):
            self.w, self.h = w, h

        def close(self):
            pass

    monkeypatch.setattr(windows, "WindowGrabber", Blank)
    monkeypatch.setattr(sw, "UNSEEN_S", 0.05)
    tab._new(as_qimage(banner()), "Rare")
    row = next(iter(tab.rows.values()))
    row.t.window = ref
    tab._store()
    tab.show()
    tab.watcher.interval = 0.01
    tab.set_watching(True)
    assert process_events(qapp, lambda: row.state.text().startswith("Game can't be captured"))
    tab.set_watching(False)
    assert not row.state.text().startswith("Game can't")


def test_a_sound_that_cant_be_played_falls_back_to_the_default(tab, monkeypatch, caplog):
    """A trigger's sound file that's gone or won't decode still rings the alarm: the
    default alert plays instead, and the log says why."""
    tab._new(as_qimage(banner()), "Rare")
    t = tab.triggers[0]
    t.sounds = ["broken"]
    monkeypatch.setattr(tab, "_playable", lambda t: list(t.sounds))
    played = []

    def play(sid, loop=False, tag=""):
        played.append(sid)
        return sid != "broken"

    monkeypatch.setattr(tab.host, "play", play)
    with caplog.at_level("WARNING"):
        assert tab._play_trigger(t) == [DEFAULT_SOUND]
    assert played == ["broken", DEFAULT_SOUND]
    assert "couldn't be played" in caplog.text


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


def cut_while(tab, monkeypatch, grabs, rect, secs=0.4):
    """Cut `rect` out of a game window whose snapshots are `grabs` (BGRA, over and
    over), the cut dialog kept open `secs`; the warnings said, as text."""
    import itertools
    import time

    from onionwatch import cutout
    from onionwatch.ui import snip
    monkeypatch.setattr(cutout, "GRAB_S", 0.02)
    monkeypatch.setattr(windows, "find", lambda r, wins=None: windows.WindowInfo(
        7, "Game", "game.exe", 7, 0, grabs[0].shape[1], grabs[0].shape[0]))
    it = itertools.cycle(grabs)
    monkeypatch.setattr(windows, "snapshot", lambda hwnd: next(it))
    said = []
    monkeypatch.setattr(triggerspanel.QMessageBox, "warning",
                        lambda _p, title, text: said.append(f"{title}: {text}"))

    def fake_exec(dlg):
        end = time.monotonic() + secs
        while time.monotonic() < end:
            time.sleep(0.01)
        dlg.view.selection = QRect(*rect)
        dlg._accept()
        return True
    monkeypatch.setattr(snip.SnipDialog, "exec", fake_exec)
    tab.set_default(WindowRef("game.exe", "Game", 0))
    tab.add_from_cut()
    return " ".join(said)


def as_bgra(gray: np.ndarray) -> np.ndarray:
    px = np.empty(gray.shape + (4,), np.uint8)
    px[..., :3] = (np.clip(gray, 0, 1)[..., None] * 255).astype(np.uint8)
    px[..., 3] = 255
    return px


def test_scenery_moving_behind_a_cut_is_learned_and_left_out(tab, monkeypatch):
    """The window kept being grabbed while the cut dialog was open: the scenery
    panning behind the banner is see-through in the picture kept."""
    rng = np.random.default_rng(5)
    wide = np.kron(rng.random((H // 6 + 1, (W + 200) // 6 + 1)), np.ones((6, 6)))
    wide = (wide * 0.6 + 0.2).astype(np.float32)
    grabs = [as_bgra(showing(wide[:H, i * 7:i * 7 + W], banner(), 120, 75)) for i in range(12)]
    said = cut_while(tab, monkeypatch, grabs, (110, 65, 110, 50))
    assert len(tab.triggers) == 1
    got = QImage(tab.triggers[0].images[0])
    assert (got.width(), got.height()) == (110, 50) and got.hasAlphaChannel()
    pic = triggerspanel.load_picture(tab.triggers[0].images[0])
    assert pic[1] is not None
    assert pic[1][10:40, 10:100].mean() > 0.95          # the banner is kept...
    assert pic[1][:, :8].mean() < 0.3                   # ...the scenery beside it isn't
    assert triggerspanel.cut_size(got) == (W, H)
    assert "Learned the background" in tab.rows[tab.triggers[0].id].state.text()
    assert "go off by mistake" not in said


def test_a_cut_with_a_look_alike_elsewhere_is_warned_about(tab, monkeypatch):
    frame = showing(showing(scene(4), banner(), 20, 20), banner(), 200, 120)
    said = cut_while(tab, monkeypatch, [as_bgra(frame)], (20, 20, 90, 30), secs=0.1)
    assert len(tab.triggers) == 1                       # kept anyway...
    assert "go off by mistake" in said                  # ...but said


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
        dlg._pick_theme("Midnight")
        assert win.cfg.theme == "Midnight"
        dlg.volume.setValue(40)
        assert win.player.volume == pytest.approx(0.4) and win.cfg.volume == pytest.approx(0.4)
        dlg.notify.setChecked(False)
        assert win.cfg.notify is False
        win.save_now()
        assert Config.load().theme == "Midnight"
    finally:
        win.quit()


def test_a_deleted_trigger_can_be_undone_or_brought_back_later(tab, monkeypatch):
    from pathlib import Path
    tab._new(as_qimage(banner()), "First")
    tab._new(as_qimage(scene(3)[:40, :60]), "Second")
    first, second = tab.triggers
    pic = Path(first.images[0])
    tab._remove(tab.rows[first.id])
    assert [t.id for t in tab.triggers] == [second.id]
    assert pic.exists()                       # kept, in the bin
    assert not tab.undo_bar.isHidden() and "First" in tab.undo_bar.label.text()
    tab.undo_bar.btn_undo.click()             # back in its old place, as it was
    assert [t.id for t in tab.triggers] == [first.id, second.id]
    cards = tab.sections[""].body_layout       # the list's one category
    assert cards.indexOf(tab.rows[first.id]) < cards.indexOf(tab.rows[second.id])
    assert tab.host.screen["deleted"] == [] and tab.triggers[0].images == [str(pic)]
    # after the Undo bar has gone, it's still in Recently deleted
    tab._remove(tab.rows[first.id])
    tab.undo_bar.finish()
    [(iid, name, _when)] = tab.deleted()
    assert name == "First"
    assert tab.restore_deleted(iid)
    assert tab.triggers[0].name == "First" and tab.deleted() == []
    # deleted for good: its picture goes too
    tab._remove(tab.rows[first.id])
    tab.forget_deleted(tab.deleted()[0][0])
    assert not pic.exists() and tab.deleted() == []


@pytest.fixture
def styled(qapp):
    """The app's real stylesheet (padding decides when the bottom bar wraps)."""
    from onionwatch import theme
    old = qapp.styleSheet()
    theme.apply(qapp, "Dark")
    yield
    qapp.setStyleSheet(old)
    theme.set_current(theme.DEFAULT)


def test_the_undo_notice_floats_without_moving_the_list(tab, qapp, styled):
    tab._new(as_qimage(banner()), "First")
    tab._new(as_qimage(scene(3)[:40, :60]), "Second")
    tab.resize(1440, 800)                     # the width the user had
    tab.show()
    qapp.processEvents()
    tools = tab.btn_watch.parentWidget()      # the bottom bar
    top, tall, bar_h = tab.scroll.y(), tab.scroll.height(), tools.height()
    assert tab.btn_bin.isHidden()
    first, second = tab.triggers
    tab._remove(tab.rows[first.id])
    qapp.processEvents()
    bar = tab.undo_bar
    assert not bar.isHidden() and "First" in bar.label.text()
    assert tab.layout().indexOf(bar) == -1    # a toast over the tab, not a row in it
    assert tab.scroll.y() == top              # the list isn't pushed down
    assert not tab.btn_bin.isHidden()         # ...or squeezed by the bin wrapping the bar
    assert tools.height() == bar_h and tab.scroll.height() == tall
    assert bar.parentWidget() is tab and tab.rect().contains(bar.geometry())
    assert bar.btn_undo.objectName() == "undobtn" and not bar.btn_close.icon().isNull()
    tab.resize(260, 600)                      # narrow: it shrinks with the tab
    qapp.processEvents()
    assert tab.rect().contains(bar.geometry()) and bar.width() <= tab.width() - 2 * bar.MARGIN
    bar.btn_undo.click()
    assert bar.isHidden() and [t.id for t in tab.triggers] == [first.id, second.id]
    tab._remove(tab.rows[first.id])
    bar.btn_close.click()                     # dismissed: still in Recently deleted
    assert bar.isHidden() and [name for _i, name, _w in tab.deleted()] == ["First"]


def test_old_deleted_triggers_are_let_go(tab):
    import time
    from pathlib import Path
    tab._new(as_qimage(banner()), "Old")
    t = tab.triggers[0]
    pic = Path(t.images[0])
    tab._remove(tab.rows[t.id])
    tab.undo_bar.finish()
    tab.host.screen["deleted"][0]["when"] = time.time() - (triggerspanel.KEEP_DAYS + 1) * 86400
    tab._prune_bin()
    assert tab.deleted() == [] and not pic.exists()


def test_a_removed_picture_can_be_undone(tab):
    from pathlib import Path
    tab._new([as_qimage(banner()), as_qimage(scene(3)[:40, :60])], "Two")
    t = tab.triggers[0]
    a, b = t.images
    tab._remove_picture(tab.rows[t.id], 0)
    assert t.images == [b] and Path(a).exists()
    tab.undo_bar.btn_undo.click()
    assert t.images == [a, b]
    tab._remove_picture(tab.rows[t.id], 0)
    tab.undo_bar.finish()                     # the bar went: now the file goes
    assert t.images == [b] and not Path(a).exists()


def test_the_recently_deleted_window_brings_triggers_back(tab):
    from onionwatch.ui.deleted import DeletedDialog
    tab._new(as_qimage(banner()), "Gone")
    tab._remove(tab.rows[tab.triggers[0].id])
    dlg = DeletedDialog(tab, triggerspanel.KEEP_DAYS)
    assert dlg.list.count() == 1 and "Gone" in dlg.list.item(0).text()
    dlg.bring_back()
    assert [t.name for t in tab.triggers] == ["Gone"]
    assert dlg.list.count() == 1 and not dlg.btn_back.isEnabled()   # "Nothing here"


def test_the_recently_deleted_button_shows_while_the_bin_has_triggers(tab):
    assert tab.btn_bin.isHidden()
    tab._new(as_qimage(banner()), "Gone")
    tab._remove(tab.rows[tab.triggers[0].id])
    assert not tab.btn_bin.isHidden() and tab.btn_bin.text() == "1"
    assert tab.btn_bin.accessibleName() == "Recently deleted (1)"
    assert tab.btn_bin.toolTip().startswith("Recently deleted (1)")
    tab.restore_deleted(tab.deleted()[0][0])
    assert tab.btn_bin.isHidden()


def test_the_delete_button_asks_first(tab, monkeypatch):
    box = triggerspanel.QMessageBox
    monkeypatch.setattr(box, "exec", lambda self: box.Cancel)
    tab._new(as_qimage(banner()), "Keep me")
    row = tab.rows[tab.triggers[0].id]
    row.btn_del.click()
    assert [t.name for t in tab.triggers] == ["Keep me"]
    monkeypatch.setattr(box, "exec", lambda self: box.Yes)
    row.btn_del.click()
    assert tab.triggers == [] and tab.deleted()[0][1] == "Keep me"


def test_toolbar_is_one_row_when_there_is_room(tab, qapp, styled):
    """Cut picture stays a button; a picture file, the copied picture and a trigger
    without a picture are in the Add menu next to it. At a normal width the whole
    bar, Look in and the settings button included, is one centred row."""
    texts = [a.text() for a in tab.btn_add.menu().actions()]
    assert texts == ["From a picture file…", "Paste the copied picture", "Without a picture…"]
    assert "Without a picture…" not in [a.text() for a in tab.btn_more.menu().actions()]
    tab.resize(1180, 700)
    tab.show()
    qapp.processEvents()
    bar = tab.toolbar
    mids = {w.mapTo(bar, w.rect().center()).y() for w in
            (tab.btn_watch, tab.btn_cut, tab.btn_add, tab.btn_more, tab.cb_where,
             tab.btn_settings)}
    assert max(mids) - min(mids) <= 1
    assert tab.cb_where.height() == tab.btn_watch.height() == tab.btn_cut.height()
    # with room to spare, Look in shows the whole "Screen 1: 320×180", not "Screen 1: 1…"
    tab.resize(1800, 700)
    qapp.processEvents()
    cb = tab.cb_where
    assert cb.maximumWidth() >= 240    # "Screen 1: 1920×1080  (main)" in Segoe UI
    assert cb.width() == min(cb.sizeHint().width(), cb.maximumWidth())


def test_a_narrow_window_keeps_the_bar_inside_it(tab, qapp, styled):
    """At 300 px the bar wraps: nothing in it runs past its edge (or stops the tab
    getting that narrow). The check speed isn't on it: it's under ⚙."""
    tab.resize(300, 700)
    tab.show()
    for _ in range(4):
        qapp.processEvents()
    bar = tab.toolbar
    assert tab.width() == 300

    def top(w):
        return w.mapTo(bar, w.rect().topLeft()).y()
    assert top(tab.cb_where) > top(tab.btn_watch)
    assert not hasattr(tab, "cb_interval")
    for w in (tab.btn_watch, tab.btn_cut, tab.btn_add, tab.btn_more, tab.cb_where,
              tab.btn_settings):
        assert w.mapTo(bar, w.rect().topRight()).x() < bar.width()
    tab.hide()


def test_processor_use_is_picked_behind_the_cog_and_kept(tab, qapp, monkeypatch):
    """The ⚙ on the bar opens Watching: picking Fast lets watching use 5 % at once
    and keeps it in the screen settings, which the next start (Onion Watch's or
    Onion Board's tab) reads back; a value no version knows falls back to 1 %."""
    from onionwatch.ui.watching import CHOICES, WatchingDialog
    assert tab.watcher.cpu_share == sw.CPU_SHARE
    shown = []
    monkeypatch.setattr(WatchingDialog, "exec", lambda self: shown.append(self) or 0)
    tab.btn_settings.click()
    dlg = shown[0]
    assert dlg.radios[sw.CPU_SHARE].isChecked()
    assert "Not watching" in dlg.now.text()
    dlg.radios[0.05].click()
    assert tab.watcher.cpu_share == 0.05 and tab.host.screen["cpu_share"] == 0.05
    dlg.radios[0.0].click()
    assert tab.watcher.cpu_share == 0.0
    assert [c[0] for c in CHOICES] == list(sw.CPU_SHARES)
    again = TriggersTab(tab.host)
    again.shutdown()
    assert again.watcher.cpu_share == 0.0
    tab.host.screen["cpu_share"] = 0.33
    odd = TriggersTab(tab.host)
    odd.shutdown()
    assert odd.watcher.cpu_share == sw.CPU_SHARE


def test_max_detection_is_picked_behind_the_cog_and_kept(tab, qapp, monkeypatch):
    """Max detection has a key of its own ("max_detect"): picking it keeps the
    processor share as it was (what an older version, or "Off", goes by), the next
    start reads it back, and a value no version knows is "off"."""
    from onionwatch.ui.watching import MAX_CHOICES, WatchingDialog
    assert tab.watcher.max_detect == "off"
    shown = []
    monkeypatch.setattr(WatchingDialog, "exec", lambda self: shown.append(self) or 0)
    tab.btn_settings.click()
    dlg = shown[0]
    assert dlg.max_radios["off"].isChecked()
    dlg.radios[0.02].click()
    dlg.max_radios["away"].click()
    assert tab.watcher.max_detect == "away" and tab.host.screen["max_detect"] == "away"
    assert tab.watcher.cpu_share == 0.02 and tab.host.screen["cpu_share"] == 0.02
    assert sorted(c[0] for c in MAX_CHOICES) == sorted(sw.MAX_DETECTS)
    again = TriggersTab(tab.host)
    again.shutdown()
    assert again.watcher.max_detect == "away" and again.watcher.cpu_share == 0.02
    tab.host.screen["max_detect"] = "turbo"
    odd = TriggersTab(tab.host)
    odd.shutdown()
    assert odd.watcher.max_detect == "off"


def test_count_me_in_off_sends_one_opt_out_and_the_eye_shows_what_is_sent(
        qapp, app_dir, fake_screen, monkeypatch):
    from onionwatch import usage
    from onionwatch.ui.mainwindow import MainWindow
    from onionwatch.ui.settingsdialog import SettingsDialog
    where = []
    monkeypatch.setattr(usage, "opt_out", lambda w: where.append(w) or True)
    win = MainWindow(Config())
    try:
        dlg = SettingsDialog(win)
        dlg.count_eye.click()
        assert dlg.count_dialog.isVisible() and len(dlg.count_dialog.findChildren(QLabel)) > 10
        dlg.count_dialog.close()
        dlg.usage.setChecked(False)
        for t in threading.enumerate():
            if t.name == "usage-opt-out":
                t.join(5)
        assert where == ["settings"] and win.cfg.usage_count is False
    finally:
        win.quit()
