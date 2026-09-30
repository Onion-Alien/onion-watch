"""Settings: where the alerts play (speakers or headphones), how loud, whether a
Windows notification shows too, closing to the tray, and the colour theme. Every
change applies straight away."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QHBoxLayout,
                               QLabel, QPushButton, QSlider, QVBoxLayout)

from onionwatch import __version__, theme
from onionwatch.sounds import DEFAULT_SOUND
from onionwatch.ui import icons
from onionwatch.ui.panel import card, hint_label
from onionwatch.wheelguard import no_wheel


class SettingsDialog(QDialog):
    def __init__(self, win):
        super().__init__(win)
        self.win = win
        cfg = win.cfg
        self.setWindowTitle("Onion Watch settings")
        self.setMinimumWidth(460)
        v = QVBoxLayout(self)
        v.setSpacing(10)

        box, bv = card("SOUND", "Alerts play on your speakers or headphones — pick the ones "
                       "you'll hear when you're away from the game.")
        self.device = QComboBox()
        self.device.addItem("Windows default", "")
        for name in win.player.devices():
            self.device.addItem(name, name)
        i = self.device.findData(cfg.device)
        if i < 0 and cfg.device:
            self.device.addItem(f"{cfg.device} (not plugged in)", cfg.device)
            i = self.device.count() - 1
        self.device.setCurrentIndex(max(i, 0))
        self.device.currentIndexChanged.connect(self._on_device)
        no_wheel(self.device)
        bv.addWidget(self.device)
        row = QHBoxLayout()
        row.addWidget(QLabel("Volume"))
        self.volume = QSlider(Qt.Horizontal)
        self.volume.setRange(0, 100)
        self.volume.setValue(round(cfg.volume * 100))
        self.volume.valueChanged.connect(self._on_volume)
        row.addWidget(self.volume, 1)
        self.vol_label = QLabel()
        self.vol_label.setMinimumWidth(40)
        row.addWidget(self.vol_label)
        self.btn_test = QPushButton("Test")
        icons.set_icon(self.btn_test, "play", size=14)
        self.btn_test.clicked.connect(
            lambda: win.player.play(win.library.load(DEFAULT_SOUND)))
        row.addWidget(self.btn_test)
        bv.addLayout(row)
        self.error = hint_label("")
        theme.set_tone(self.error, "warn")
        self.error.hide()
        bv.addWidget(self.error)
        v.addWidget(box)

        box, bv = card("WHEN A TRIGGER GOES OFF")
        self.notify = QCheckBox("Show a Windows notification too")
        self.notify.setChecked(cfg.notify)
        self.notify.toggled.connect(lambda on: self._set("notify", on))
        bv.addWidget(self.notify)
        self.tray = QCheckBox("Closing the window keeps watching from the tray")
        self.tray.setChecked(cfg.tray)
        self.tray.toggled.connect(lambda on: self._set("tray", on))
        bv.addWidget(self.tray)
        v.addWidget(box)

        box, bv = card("LOOK")
        self.theme = QComboBox()
        for group, names in theme.GROUPS:
            for name in names:
                self.theme.addItem(f"{name}  ·  {group}", name)
        self.theme.setCurrentIndex(max(self.theme.findData(cfg.theme), 0))
        self.theme.currentIndexChanged.connect(
            lambda _i: win.set_theme(self.theme.currentData()))
        no_wheel(self.theme)
        bv.addWidget(self.theme)
        v.addWidget(box)

        foot = QLabel(f"Onion Watch {__version__} — it only looks at the screen and plays "
                      "sounds; it never clicks, types or reads a game's memory.")
        foot.setObjectName("hint")
        foot.setWordWrap(True)
        v.addWidget(foot)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        v.addWidget(buttons)
        self._on_volume(self.volume.value())

    def _set(self, key: str, value):
        setattr(self.win.cfg, key, value)
        self.win.save_later()

    def _on_device(self, _i: int):
        name = self.device.currentData() or ""
        self.win.player.set_device(name)
        self._set("device", name)
        ok = self.win.player.play(self.win.library.load(DEFAULT_SOUND))
        self.error.setText("" if ok else f"That device couldn't be opened "
                           f"({self.win.player.error}).")
        self.error.setVisible(not ok)

    def _on_volume(self, value: int):
        self.vol_label.setText(f"{value}%")
        self.win.player.volume = value / 100
        self._set("volume", value / 100)
