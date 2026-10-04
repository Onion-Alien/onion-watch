"""Watching settings, behind the cog on the Triggers bar: how much of the processor
watching may use (screenwatch.CPU_SHARES), "Max detection" (screenwatch.MAX_DETECTS),
and how often each trigger is being checked right now. A change applies at once and
is kept in the host's screen settings ("cpu_share", "max_detect"), so the same choice
holds in Onion Watch and in Onion Board's Triggers tab. "max_detect" is a key of its
own: a version without it keeps reading "cpu_share" as before."""
from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (QButtonGroup, QDialog, QDialogButtonBox, QLabel, QRadioButton,
                               QVBoxLayout)

from onionwatch import screenwatch
from onionwatch.ui.panel import card, hint_label

# (share, name, what it means); the first is the default, screenwatch.CPU_SHARE
CHOICES = [
    (0.01, "Light — up to 1 %",
     "Best while you play: your game keeps its frame rate. With a lot of pictures on, "
     "each one is checked less often."),
    (0.02, "Normal — up to 2 %",
     "Checks about twice as often as Light when there's a lot to look for."),
    (0.05, "Fast — up to 5 %",
     "For dozens of pictures that must be noticed straight away."),
    (0.0, "As fast as it can",
     "No limit: checks as often as the bar's “every” says, whatever it costs. A busy "
     "game may lose frames."),
]


# (screenwatch.MAX_DETECTS value, name, what it means); the first is the default
MAX_CHOICES = [
    ("off", "Off",
     "Keeps to the processor use above."),
    ("away", "While I'm not in the game",
     "All out only while none of the watched windows is in front and no fullscreen "
     "window covers a watched screen. Back to the share above once you're in the game."),
    ("always", "Always",
     "No limit, and it searches much harder for pictures at other sizes. Can use a "
     "whole processor core: a busy game may lose frames."),
]


def share_label(share: float) -> str:
    """"1 %", "5 %", or "no limit"."""
    return "no limit" if share <= 0 else f"{share * 100:g} %"


class WatchingDialog(QDialog):
    """Follows `panel` (a TriggersTab): its watcher's share, and the gap live."""

    def __init__(self, panel, parent=None):
        super().__init__(parent)
        self.panel = panel
        self.setWindowTitle("Watching")
        self.setMinimumWidth(420)
        v = QVBoxLayout(self)
        v.setSpacing(10)
        box, bv = card("PROCESSOR USE", "How much of your processor Onion Watch may use to "
                       "look for your pictures. More lets it check each trigger sooner when "
                       "a lot are on; less leaves more for your game.")
        self.group = QButtonGroup(self)
        self.radios: dict[float, QRadioButton] = {}
        for i, (share, name, what) in enumerate(CHOICES):
            r = QRadioButton(name)
            self.group.addButton(r, i)
            self.radios[share] = r
            bv.addWidget(r)
            hint = hint_label(what)
            hint.setContentsMargins(22, 0, 0, 4)     # under its button's text
            bv.addWidget(hint)
        current = panel.watcher.cpu_share
        (self.radios.get(current) or self.radios[screenwatch.CPU_SHARE]).setChecked(True)
        self.group.idToggled.connect(self._picked)
        v.addWidget(box)
        box, bv = card("MAX DETECTION", "Look as hard as it can, for pictures shown "
                       "bigger or smaller than they were cut too, whatever it costs.")
        self.max_group = QButtonGroup(self)
        self.max_radios: dict[str, QRadioButton] = {}
        for i, (key, name, what) in enumerate(MAX_CHOICES):
            r = QRadioButton(name)
            self.max_group.addButton(r, i)
            self.max_radios[key] = r
            bv.addWidget(r)
            hint = hint_label(what)
            hint.setContentsMargins(22, 0, 0, 4)
            bv.addWidget(hint)
        (self.max_radios.get(panel.watcher.max_detect) or self.max_radios["off"]).setChecked(True)
        self.max_group.idToggled.connect(self._picked_max)
        v.addWidget(box)
        box, bv = card("RIGHT NOW")
        self.now = QLabel()
        self.now.setWordWrap(True)
        bv.addWidget(self.now)
        v.addWidget(box)
        v.addStretch(1)                 # spare height goes below the cards, not into them
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        v.addWidget(buttons)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._show_now)
        self._timer.start(500)
        self._show_now()

    def showEvent(self, e):
        super().showEvent(e)
        # wrapped text: only now, at its width, is the height it needs known
        h = self.layout().heightForWidth(self.width())
        if h > 0:
            self.resize(self.width(), h)

    def _picked(self, i: int, on: bool):
        if on:
            self.panel.set_cpu_share(CHOICES[i][0])
            self._show_now()

    def _picked_max(self, i: int, on: bool):
        if on:
            self.panel.set_max_detect(MAX_CHOICES[i][0])
            self._show_now()

    def _show_now(self):
        self.now.setText(self.panel.watching_text())
