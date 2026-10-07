"""The triggers page as both hosts show it: a Triggers / Log tab row over the
triggers (TriggersTab) or the log of what went off (history.HistoryView), and
under both the Playing now bar: each trigger whose sound is still going, with its
own Stop, and Stop all; and the Chances button (ui.chances), unless it's switched
off in Watching settings."""
from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QPushButton, QStackedWidget,
                               QTabBar, QVBoxLayout, QWidget)

from onionwatch import theme
from onionwatch.ui import chances, icons
from onionwatch.ui.history import HistoryView
from onionwatch.i18n import _

CHECK_MS = 400          # how often the bar looks whether a sound has ended
MAX_SHOWN = 6           # triggers named on the bar; the rest as "+3 more"


class PlayingBar(QFrame):
    """Follows `panel` (a TriggersTab): what's playing now, each with a Stop."""

    def __init__(self, panel, parent=None):
        super().__init__(parent)
        self.panel = panel
        self.setObjectName("transport")
        h = QHBoxLayout(self)
        h.setContentsMargins(10, 6, 10, 6)
        h.setSpacing(8)
        self.icon = QLabel()
        h.addWidget(self.icon)
        self.title = QLabel()
        self.title.setStyleSheet("font-weight:700; background:transparent;")
        h.addWidget(self.title)
        self.chips = QHBoxLayout()
        self.chips.setSpacing(6)
        h.addLayout(self.chips)
        h.addStretch(1)
        self.btn_chances = QPushButton(_("Chances"))
        self.btn_chances.setToolTip(_("Live chances: how close every trigger is to going off, "
                                      "right now"))
        icons.set_icon(self.btn_chances, "gauge")
        self.btn_chances.clicked.connect(self.open_chances)
        h.addWidget(self.btn_chances)
        self.chances: chances.ChancesDialog | None = None
        self.show_chances_button()
        self.btn_stop_all = QPushButton(_("Stop all"))
        self.btn_stop_all.setToolTip(_("Stop every trigger's sound now (and any still waiting "
                                       "out its wait)"))
        icons.set_icon(self.btn_stop_all, "stop")
        self.btn_stop_all.clicked.connect(self.stop_all)
        h.addWidget(self.btn_stop_all)
        self._shown: list[tuple[str, bool]] | None = None
        self._check = QTimer(self)
        self._check.timeout.connect(self.update_bar)
        panel.playing_changed.connect(self.update_bar)
        panel.ringing_changed.connect(self.update_bar)
        self.update_bar()

    def update_bar(self):
        now = self.panel.playing_now()
        key = [(t.id + t.name, ring) for t, ring in now]
        if now:
            self._check.start(CHECK_MS)
        else:
            self._check.stop()
        if key == self._shown:
            return
        self._shown = key
        while self.chips.count():
            w = self.chips.takeAt(0).widget()
            if w is not None:       # hidden now: out of the layout, it'd float on top
                w.hide()
                w.deleteLater()
        self.icon.setPixmap(icons.pixmap("volume", 16, theme.T.get(
            "accent" if now else "muted", "#888888")))
        self.title.setText(_("Playing now:") if now else _("Nothing playing"))
        self.title.setObjectName("" if now else "muted")
        self.title.style().unpolish(self.title)
        self.title.style().polish(self.title)
        for t, ring in now[:MAX_SHOWN]:
            b = QPushButton(_("{name} (ringing)", name=t.name) if ring else t.name)
            b.setObjectName("small")
            icons.set_icon(b, "stop", size=12)
            b.setToolTip(_("Stop {name}", name=t.name))
            b.setAccessibleName(_("Stop {name}", name=t.name))
            b.clicked.connect(lambda __=False, tid=t.id: self.panel.stop_trigger(tid))
            self.chips.addWidget(b)
        if len(now) > MAX_SHOWN:
            more = QLabel(_("+{n} more", n=len(now) - MAX_SHOWN))
            more.setObjectName("muted")
            self.chips.addWidget(more)
        self.btn_stop_all.setEnabled(bool(now))

    def show_chances_button(self):
        """Show or hide the Chances button as Watching settings say."""
        self.btn_chances.setVisible(chances.show_button(self.panel.host))

    def open_chances(self):
        """The Live chances window (one; brought to the front if it's open)."""
        if self.chances is None:
            self.chances = chances.ChancesDialog(self.panel, self.window())
            self.chances.finished.connect(self._chances_closed)
        self.chances.show()
        self.chances.raise_()
        self.chances.activateWindow()

    def _chances_closed(self, _r=0):
        if self.chances is not None:
            self.chances.deleteLater()
            self.chances = None

    def stop_all(self):
        self.panel.stop_all_playing()
        self.update_bar()


class TriggerPages(QWidget):
    """Triggers | Log over `panel`, the Playing now bar under them. `top`: widgets
    to put between the tab row and the pages (the alarm bar)."""

    def __init__(self, panel, top=(), parent=None):
        super().__init__(parent)
        self.panel = panel
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(8)
        self.tabs = QTabBar()
        self.tabs.setDrawBase(False)
        self.tabs.setExpanding(False)
        self.tabs.addTab(_("Triggers"))
        self.tabs.addTab(_("Log"))
        self.tabs.setTabToolTip(1, _("What went off and when, newest first"))
        v.addWidget(self.tabs)
        for w in top:
            v.addWidget(w)
        self.stack = QStackedWidget()
        self.stack.addWidget(panel)
        log_page = QWidget()
        lv = QVBoxLayout(log_page)
        lv.setContentsMargins(0, 0, 0, 0)
        self.log = HistoryView(panel, log_page)
        lv.addWidget(self.log, 1)
        lv.addLayout(self.log.button_row())
        self.stack.addWidget(log_page)
        v.addWidget(self.stack, 1)
        self.playing = PlayingBar(panel)
        v.addWidget(self.playing)
        self.tabs.currentChanged.connect(self.stack.setCurrentIndex)
        panel.history_changed.connect(self._count)
        self._count()

    def _count(self):
        n = len(self.panel.history)
        self.tabs.setTabText(1, _("Log ({n})", n=n) if n else _("Log"))

    def show_log(self):
        self.tabs.setCurrentIndex(1)
