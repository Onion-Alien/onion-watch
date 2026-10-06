"""Settings: where the alerts play (speakers or headphones), how loud, whether a
Windows notification shows too, closing to the tray, the colour theme and the language,
and updates and privacy (the daily update check, the anonymous usage count, Send
feedback / Report a problem). Every change applies straight away, but a new language
only shows once Onion Watch restarts (Restart now)."""
from __future__ import annotations

import webbrowser

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QHBoxLayout,
                               QLabel, QPushButton, QSlider, QVBoxLayout)

from onionwatch import __version__, feedback, i18n, theme
from onionwatch.sounds import DEFAULT_SOUND
from onionwatch.ui import fit, icons
from onionwatch.ui.panel import card, hint_label
from onionwatch.wheelguard import no_wheel
from onionwatch.i18n import _


def group_label(group: str) -> str:
    """A theme group's name (theme.GROUPS) in the current language."""
    return {"Classic": _("Classic"), "Colourful": _("Colourful"), "Wild": _("Wild"),
            "Meme": _("Meme")}.get(group, group)


class SettingsDialog(QDialog):
    def __init__(self, win):
        super().__init__(win)
        fit.watch(self)          # grows to fit its (translated) text
        self.win = win
        cfg = win.cfg
        self.setWindowTitle(_("Onion Watch settings"))
        self.setMinimumWidth(460)
        v = QVBoxLayout(self)
        v.setSpacing(10)

        box, bv = card(_("SOUND"), _("Alerts play on your speakers or headphones — pick the "
                                     "ones you'll hear when you're away from the game."))
        self.device = QComboBox()
        self.device.addItem(_("Windows default"), "")
        for name in win.player.devices():
            self.device.addItem(name, name)
        i = self.device.findData(cfg.device)
        if i < 0 and cfg.device:
            self.device.addItem(_("{device} (not plugged in)", device=cfg.device), cfg.device)
            i = self.device.count() - 1
        self.device.setCurrentIndex(max(i, 0))
        self.device.currentIndexChanged.connect(self._on_device)
        no_wheel(self.device)
        bv.addWidget(self.device)
        row = QHBoxLayout()
        row.addWidget(QLabel(_("Volume")))
        self.volume = QSlider(Qt.Horizontal)
        self.volume.setRange(0, 100)
        self.volume.setValue(round(cfg.volume * 100))
        self.volume.valueChanged.connect(self._on_volume)
        row.addWidget(self.volume, 1)
        self.vol_label = QLabel()
        self.vol_label.setMinimumWidth(40)
        row.addWidget(self.vol_label)
        self.btn_test = QPushButton(_("Test"))
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

        box, bv = card(_("WHEN A TRIGGER GOES OFF"))
        self.notify = QCheckBox(_("Show a Windows notification too"))
        self.notify.setChecked(cfg.notify)
        self.notify.toggled.connect(lambda on: self._set("notify", on))
        bv.addWidget(self.notify)
        self.tray = QCheckBox(_("Closing the window keeps watching from the tray"))
        self.tray.setChecked(cfg.tray)
        self.tray.toggled.connect(lambda on: self._set("tray", on))
        bv.addWidget(self.tray)
        v.addWidget(box)

        box, bv = card(_("LOOK"))
        self.theme = QComboBox()
        for group, names in theme.GROUPS:
            for name in names:
                self.theme.addItem(f"{name}  ·  {group_label(group)}", name)
        self.theme.setCurrentIndex(max(self.theme.findData(cfg.theme), 0))
        self.theme.currentIndexChanged.connect(
            lambda _i: win.set_theme(self.theme.currentData()))
        no_wheel(self.theme)
        bv.addWidget(self.theme)
        row = QHBoxLayout()
        row.addWidget(QLabel(_("Language")))
        self.language = QComboBox()
        self.language.setAccessibleName(_("Language"))
        self.language.addItem(_("Windows' language"), i18n.WINDOWS)
        for code, name in i18n.available():
            self.language.addItem(name, code)
        i = self.language.findData(cfg.language)
        self.language.setCurrentIndex(max(i, 0))
        self.language.currentIndexChanged.connect(self._on_language)
        no_wheel(self.language)
        row.addWidget(self.language, 1)
        bv.addLayout(row)
        self.restart_row = QHBoxLayout()
        self.restart_note = hint_label(_("Restart Onion Watch to finish"))
        theme.set_tone(self.restart_note, "warn")
        self.restart_row.addWidget(self.restart_note, 1)
        self.btn_restart = QPushButton(_("Restart now"))
        self.btn_restart.clicked.connect(win.restart)
        self.restart_row.addWidget(self.btn_restart)
        bv.addLayout(self.restart_row)
        self._started_in = getattr(win, "started_language", cfg.language)
        self._show_restart()
        v.addWidget(box)

        box, bv = card(_("UPDATES AND PRIVACY"))
        row = QHBoxLayout()
        self.update_check = QCheckBox(_("Check for new versions"))
        self.update_check.setChecked(cfg.update_check)
        self.update_check.toggled.connect(lambda on: self._set("update_check", on))
        row.addWidget(self.update_check, 1)
        self.btn_check = QPushButton(_("Check now"))
        self.btn_check.clicked.connect(self._check_now)
        row.addWidget(self.btn_check)
        bv.addLayout(row)
        self.check_status = hint_label("")
        self.check_status.hide()
        bv.addWidget(self.check_status)
        self.usage = QCheckBox(_("Count me in: an anonymous \"still here\""))
        self.usage.setChecked(cfg.usage_count)
        self.usage.toggled.connect(lambda on: self._set("usage_count", on))
        bv.addWidget(self.usage)
        bv.addWidget(hint_label(_("Once a day: the version and a random number made on this PC, "
                                  "so we know people use it. Never your triggers, pictures, "
                                  "windows or games.")))
        v.addWidget(box)
        win.update_found.connect(self._on_checked)

        foot = QLabel(_("Onion Watch {version} — it only looks at the screen and plays sounds; "
                        "it never clicks, types or reads a game's memory.", version=__version__))
        foot.setObjectName("hint")
        foot.setWordWrap(True)
        v.addWidget(foot)
        row = QHBoxLayout()
        self.btn_feedback = QPushButton(_("Send feedback"))
        self.btn_feedback.setToolTip(_("Opens a short form in your browser (no account)"))
        self.btn_feedback.clicked.connect(
            lambda: webbrowser.open(feedback.feedback_url(__version__)))
        row.addWidget(self.btn_feedback)
        self.btn_problem = QPushButton(_("Report a problem"))
        self.btn_problem.setToolTip(_("Opens a new issue on GitHub in your browser"))
        self.btn_problem.clicked.connect(
            lambda: webbrowser.open(feedback.problem_url(__version__)))
        row.addWidget(self.btn_problem)
        row.addStretch(1)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        row.addWidget(buttons)
        v.addLayout(row)
        self._on_volume(self.volume.value())
        # never narrower than its contents: a translation's long checkbox or buttons
        self.setMinimumWidth(max(460, v.minimumSize().width()))

    def _check_now(self):
        self.check_status.setText(_("Checking…"))
        self.check_status.show()
        self.win.check_updates(force=True)

    def _on_checked(self, rel, err: str, force: bool):
        if not force:
            return
        if err:
            self.check_status.setText(_("Couldn't check just now ({err}).", err=err))
        elif rel is None:
            self.check_status.setText(_("You have the newest version ({version}).",
                                        version=__version__))
        else:
            self.check_status.setText(_("Onion Watch {version} is out.", version=rel.version))
        self.check_status.show()

    def _on_language(self, _i: int):
        self._set("language", self.language.currentData() or i18n.WINDOWS)
        self._show_restart()

    def _show_restart(self):
        """The Restart now line, while the language picked isn't the one showing."""
        changed = self.win.cfg.language != self._started_in
        self.restart_note.setVisible(changed)
        self.btn_restart.setVisible(changed)

    def _set(self, key: str, value):
        setattr(self.win.cfg, key, value)
        self.win.save_later()

    def _on_device(self, _i: int):
        name = self.device.currentData() or ""
        self.win.player.set_device(name)
        self._set("device", name)
        ok = self.win.player.play(self.win.library.load(DEFAULT_SOUND))
        self.error.setText("" if ok else _("That device couldn't be opened ({error}).",
                                           error=self.win.player.error))
        self.error.setVisible(not ok)

    def _on_volume(self, value: int):
        self.vol_label.setText(f"{value}%")
        self.win.player.volume = value / 100
        self._set("volume", value / 100)
