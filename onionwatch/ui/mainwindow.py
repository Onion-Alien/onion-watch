"""The Onion Watch window: the header, the alarm bar that appears while a trigger
is ringing, the triggers page, and the tray icon that keeps watching when the
window is closed."""
from __future__ import annotations

import logging
import threading

from PySide6.QtCore import QByteArray, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QCloseEvent
from PySide6.QtWidgets import (QApplication, QHBoxLayout, QLabel, QMainWindow, QMenu,
                               QPushButton, QSystemTrayIcon, QVBoxLayout, QWidget)

from onionwatch import __version__, theme
from onionwatch.apphost import AppHost
from onionwatch.player import Player
from onionwatch.settings import Config
from onionwatch.sounds import Library
from onionwatch.ui import icons
from onionwatch.ui.alarmbar import AlarmBar
from onionwatch.ui.pages import TriggerPages
from onionwatch.ui.triggerspanel import TriggersTab

log = logging.getLogger(__name__)

SAVE_DELAY_MS = 400


class MainWindow(QMainWindow):
    # from the update check's thread: (a newer release or None, an error or "", forced)
    update_found = Signal(object, str, bool)
    settings_changed = Signal()   # a thread changed cfg: save it on the UI thread

    def __init__(self, cfg: Config | None = None, player: Player | None = None):
        super().__init__()
        self.cfg = cfg if cfg is not None else Config.load()
        self._quitting = False
        self._told_tray = False
        self._saver = QTimer(self)
        self._saver.setSingleShot(True)
        self._saver.timeout.connect(self.save_now)
        app = QApplication.instance()
        self.cfg.theme = theme.apply(app, self.cfg.theme)
        self.setWindowTitle("Onion Watch")
        self.setWindowIcon(theme.app_icon())
        self.library = Library(self.cfg.sounds, self.save_later)
        self.player = player or Player(self.cfg.device, self.cfg.volume)

        root = QWidget()
        self.setCentralWidget(root)
        rv = QVBoxLayout(root)
        rv.setContentsMargins(14, 10, 14, 10)
        rv.setSpacing(8)

        head = QHBoxLayout()
        head.setSpacing(10)
        self.logo = QLabel()
        self.logo.setPixmap(theme.logo_pixmap(34 * 2))
        self.logo.setFixedSize(34, 34)
        self.logo.setScaledContents(True)
        head.addWidget(self.logo)
        names = QVBoxLayout()
        names.setSpacing(0)
        self.wordmark = QLabel("ONION WATCH")
        self.wordmark.setObjectName("wordmark")
        self.tagline = QLabel("an app by Onion Alien")
        self.tagline.setObjectName("tagline")
        names.addWidget(self.wordmark)
        names.addWidget(self.tagline)
        head.addLayout(names)
        head.addStretch(1)
        self.btn_settings = QPushButton()
        self.btn_settings.setToolTip("Settings: sound output, volume, notifications, theme")
        icons.set_icon(self.btn_settings, "settings")
        self.btn_settings.clicked.connect(self.open_settings)
        head.addWidget(self.btn_settings)
        rv.addLayout(head)

        self.host = AppHost(self.cfg, self.save_later, self.library, self.player,
                            notify=self._notify)
        self.triggers = TriggersTab(self.host)
        self.triggers.fired.connect(self._on_fired)
        self.triggers.active_changed.connect(self._on_active)
        # the alarm bar: shown while a trigger rings, with the one button that matters
        self.alarm = AlarmBar(self.triggers)
        self.pages = TriggerPages(self.triggers, top=[self.alarm])
        self.triggers.pages = self.pages
        rv.addWidget(self.pages, 1)

        self._make_tray()
        self.alarm.changed.connect(self.act_stop.setEnabled)
        if self.cfg.geometry:
            try:
                self.restoreGeometry(QByteArray.fromHex(self.cfg.geometry.encode()))
            except (ValueError, TypeError):
                pass
        else:
            self.resize(860, 720)
        self._on_active(self.triggers.is_active())
        self.update_found.connect(self._on_update_found)
        self.settings_changed.connect(self.save_later)
        self._checking = False

    # ------------------------------------------------------------------ settings file
    def save_later(self):
        self._saver.start(SAVE_DELAY_MS)

    def save_now(self):
        self._saver.stop()
        try:
            self.cfg.save()
        except OSError:
            log.warning("saving the settings failed", exc_info=True)

    # ------------------------------------------------------------------ tray
    def _make_tray(self):
        self.tray = QSystemTrayIcon(theme.app_icon(), self)
        menu = QMenu(self)
        act_show = QAction("Show Onion Watch", self)
        act_show.triggered.connect(self.bring_up)
        menu.addAction(act_show)
        self.act_watch = QAction("Watching", self)
        self.act_watch.setCheckable(True)
        self.act_watch.toggled.connect(lambda on: self.triggers.set_watching(on))
        menu.addAction(self.act_watch)
        self.act_stop = QAction("Stop ringing", self)
        self.act_stop.triggered.connect(self.stop_ringing)
        self.act_stop.setEnabled(False)
        menu.addAction(self.act_stop)
        menu.addSeparator()
        act_quit = QAction("Quit", self)
        act_quit.triggered.connect(self.quit)
        menu.addAction(act_quit)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._on_tray)
        self.tray.messageClicked.connect(self._on_message)
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray.show()

    def _on_tray(self, reason):
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            if self.player.ringing:
                self.stop_ringing()
            self.bring_up()

    def _on_message(self):
        self.stop_ringing()
        self.bring_up()

    def bring_up(self):
        self.setWindowState((self.windowState() & ~Qt.WindowMinimized) | Qt.WindowActive)
        self.show()
        self.raise_()
        self.activateWindow()

    def _on_active(self, on: bool):
        self.act_watch.blockSignals(True)
        self.act_watch.setChecked(on)
        self.act_watch.blockSignals(False)
        self.tray.setToolTip("Onion Watch — watching" if on else "Onion Watch — not watching")
        self.tray.setIcon(theme.app_icon(awake=on))   # the eye shuts while it isn't watching

    # ------------------------------------------------------------------ alarms
    def _on_fired(self, t):
        text = self.triggers.alert_text(t)
        self._notify(t.name, text + (" Click here to stop." if t.ring else ""))
        QApplication.alert(self, 0 if t.ring else 3000)   # flash the taskbar button

    def _notify(self, title: str, body: str):
        if self.cfg.notify and self.tray.isVisible():
            self.tray.showMessage(title, body, theme.app_icon(), 8000)

    def stop_ringing(self):
        self.alarm.stop()

    # ------------------------------------------------------------------ settings
    def open_settings(self):
        from onionwatch.ui.settingsdialog import SettingsDialog
        dlg = SettingsDialog(self)
        dlg.exec()

    def set_theme(self, name: str):
        self.cfg.theme = theme.apply(QApplication.instance(), name)
        icons.retheme()
        self.save_later()

    # ------------------------------------------------------------------ updates, count
    def check_updates(self, force: bool = False):
        """Ask GitHub for a newer version on a thread (onionwatch.updates): the daily
        check, or Settings' Check now (`force`), which also says when there's nothing
        new or it failed."""
        if self._checking:
            return
        self._checking = True
        from onionwatch import updates

        def run():
            rel, err = None, ""
            try:
                rel = updates.check(self.cfg, force)
            except Exception as e:  # noqa: BLE001 - offline, GitHub down…
                err = str(e) or type(e).__name__
            self.update_found.emit(rel, err, force)
        threading.Thread(target=run, daemon=True, name="update-check").start()

    def _on_update_found(self, rel, err: str, force: bool):
        self._checking = False
        self.save_later()   # update_checked moved on
        if rel is not None:
            from onionwatch.ui.updatedialog import UpdateDialog
            UpdateDialog(self, rel).exec()

    def send_usage(self):
        """The anonymous daily count, if it's switched on and due (onionwatch.usage)."""
        from onionwatch import usage
        usage.maybe_send(self.cfg, self.settings_changed.emit)

    # ------------------------------------------------------------------ closing
    def closeEvent(self, ev: QCloseEvent):
        if not self._quitting and self.cfg.tray and self.tray.isVisible():
            ev.ignore()
            self.hide()
            if not self._told_tray:
                self._told_tray = True
                self.tray.showMessage("Onion Watch is still watching",
                                      "It's in the tray by the clock. Right-click it to quit.",
                                      theme.app_icon(), 5000)
            self.cfg.geometry = bytes(self.saveGeometry().toHex()).decode()
            self.save_later()
            return
        self.shutdown()
        ev.accept()
        QApplication.instance().quit()

    def quit(self):
        self._quitting = True
        self.close()

    def shutdown(self):
        if getattr(self, "_shut", False):
            return
        self._shut = True
        self.triggers.shutdown()
        self.player.close()
        self.cfg.geometry = bytes(self.saveGeometry().toHex()).decode()
        self.save_now()
        self.tray.hide()

    def about(self) -> str:
        return f"Onion Watch {__version__}"
