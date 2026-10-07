"""Watching settings, behind the cog on the Triggers bar: how often triggers left on
"Default" are checked (screenwatch.INTERVALS_MS; each card can pick its own), how much
of the processor watching may use (screenwatch.CPU_SHARES), "Max detection"
(screenwatch.MAX_DETECTS), whether the Log's pictures are in colour, and how often each
trigger is being checked right now. A change applies at once and is kept in the host's
screen settings ("interval_ms", "cpu_share", "max_detect", "color_log"), so the same
choice holds in Onion Watch and in Onion Board's Triggers tab. "max_detect" is a key
of its own: a version without it keeps reading "cpu_share" as before."""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QApplication, QButtonGroup, QCheckBox, QComboBox, QDialog,
                               QDialogButtonBox, QFrame, QHBoxLayout, QLabel, QRadioButton,
                               QScrollArea, QVBoxLayout, QWidget)

from onionwatch import screenwatch
from onionwatch.ui.panel import card, hint_label
from onionwatch.ui import fit
from onionwatch.i18n import _

# (share, name, what it means); the first is the default, screenwatch.CPU_SHARE
CHOICES = [
    (0.01, _("Light — up to 1 %"),
     _("Best while you play: your game keeps its frame rate. With a lot of pictures on, "
       "each one is checked less often.")),
    (0.02, _("Normal — up to 2 %"),
     _("Checks about twice as often as Light when there's a lot to look for.")),
    (0.05, _("Fast — up to 5 %"),
     _("For dozens of pictures that must be noticed straight away.")),
    (0.0, _("As fast as it can"),
     _("No limit: checks each trigger as often as its check speed says, whatever it "
       "costs. A busy game may lose frames.")),
]


# (screenwatch.MAX_DETECTS value, name, what it means); the first is the default
MAX_CHOICES = [
    ("off", _("Off"),
     _("Keeps to the processor use above.")),
    ("away", _("While I'm not in the game"),
     _("All out only while none of the watched windows is in front and no fullscreen "
       "window covers a watched screen. Back to the share above once you're in the game.")),
    ("always", _("Always"),
     _("No limit, and it searches much harder for pictures at other sizes. Can use a "
       "whole processor core: a busy game may lose frames.")),
]


def share_label(share: float) -> str:
    """"1 %", "5 %", or "no limit"."""
    return _("no limit") if share <= 0 else f"{share * 100:g} %"


class WatchingDialog(QDialog):
    """Follows `panel` (a TriggersTab): its watcher's share, and the gap live."""

    def __init__(self, panel, parent=None):
        super().__init__(parent)
        fit.watch(self)          # grows to fit its (translated) text
        self.panel = panel
        self.setWindowTitle(_("Watching"))
        self.setMinimumWidth(420)
        outer = QVBoxLayout(self)
        outer.setSpacing(10)
        # the cards scroll when they're taller than the screen (a long translation on a
        # small screen) instead of being squashed over each other
        self.body = QWidget()
        self.body.setObjectName("watchingbody")
        self.body.setStyleSheet("QWidget#watchingbody { background: transparent; }")
        v = QVBoxLayout(self.body)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(10)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.setStyleSheet("QScrollArea { background: transparent; }")
        self.scroll.viewport().setAutoFillBackground(False)
        self.scroll.setWidget(self.body)
        outer.addWidget(self.scroll, 1)
        from onionwatch.ui.triggerspanel import interval_label
        box, bv = card(_("CHECK SPEED"), _("How often each trigger left on “Default” looks. "
                                   "A trigger can have its own speed: “Check every”, on its "
                                   "card."))
        line = QHBoxLayout()
        line.addWidget(QLabel(_("Default: every")))
        self.speed = QComboBox()
        self.speed.setAccessibleName(_("Default check speed"))
        for ms in screenwatch.INTERVALS_MS:
            self.speed.addItem(interval_label(ms), ms)
        self.speed.setCurrentIndex(max(0, self.speed.findData(panel.default_interval)))
        self.speed.setToolTip(_("Faster notices sooner: 100 ms is a tenth of a second. Watching "
                                "still keeps to the processor use below, so with a lot on it may "
                                "check less often than this."))
        self.speed.currentIndexChanged.connect(self._picked_speed)
        line.addWidget(self.speed)
        line.addStretch(1)
        bv.addLayout(line)
        v.addWidget(box)
        box, bv = card(_("PROCESSOR USE"), _("How much of your processor Onion Watch may use to "
                                     "look for your pictures. More lets it check each trigger "
                                     "sooner when a lot are on; less leaves more for your "
                                     "game."))
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
        box, bv = card(_("MAX DETECTION"), _("Look as hard as it can, for pictures shown "
                                     "bigger or smaller than they were cut too, whatever it "
                                     "costs."))
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
        box, bv = card(_("LOG PICTURES"), _("Each alert in the Log shows the window as it was "
                                    "when the trigger went off."))
        self.color_log = QCheckBox(_("In colour"))
        self.color_log.setChecked(panel.watcher.color_hits)
        self.color_log.setToolTip(_("Off: black and white. Either way it's the picture watching "
                                    "already took, copied only when a trigger goes off, so it "
                                    "doesn't slow watching down"))
        self.color_log.toggled.connect(panel.set_color_log)
        bv.addWidget(self.color_log)
        v.addWidget(box)
        box, bv = card(_("LIVE CHANCES"), _("A Chances button on the bottom bar opens a "
                                    "window with every trigger's chance of going off, live."))
        from onionwatch.ui import chances
        self.show_chances = QCheckBox(_("Show the Chances button"))
        self.show_chances.setChecked(chances.show_button(panel.host))
        self.show_chances.toggled.connect(panel.set_show_chances)
        bv.addWidget(self.show_chances)
        v.addWidget(box)
        box, bv = card(_("RIGHT NOW"))
        self.now = QLabel()
        self.now.setWordWrap(True)
        bv.addWidget(self.now)
        v.addWidget(box)
        v.addStretch(1)                 # spare height goes below the cards, not into them
        self.buttons = QDialogButtonBox(QDialogButtonBox.Close)
        self.buttons.rejected.connect(self.reject)
        outer.addWidget(self.buttons)
        # never narrower than its contents: a translation's long radio buttons
        bar = self.scroll.verticalScrollBar().sizeHint().width()
        self.setMinimumWidth(max(420, v.minimumSize().width() + bar + 24))
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._show_now)
        self._timer.start(500)
        self._show_now()

    def showEvent(self, e):
        super().showEvent(e)
        # wrapped text: only now, at its width, is the height it needs known: all of
        # the cards, as far as the screen allows (the rest scrolls)
        m = self.layout().contentsMargins()
        need = (self.body.layout().totalHeightForWidth(self.scroll.viewport().width())
                + self.buttons.sizeHint().height() + self.layout().spacing()
                + m.top() + m.bottom() + 2)
        screen = self.screen() or QApplication.primaryScreen()
        room = screen.availableGeometry().height() - (self.frameGeometry().height()
                                                       - self.height())
        self.resize(self.width(), max(min(need, room), 300))

    def _picked_speed(self, _i: int):
        self.panel.set_default_interval(self.speed.currentData())
        self._show_now()

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
