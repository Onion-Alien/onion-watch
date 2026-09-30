"""What went off lately: each alert with the time, the trigger, which window or
screen it was in, how strongly, and a picture of that window at the moment with a
box round what set it off. For "what woke me up?" and for setting the numbers.
Kept in memory only (TriggersTab.history): nothing is saved."""
from __future__ import annotations

import time

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QLabel, QListWidget, QListWidgetItem,
                               QPushButton, QVBoxLayout)

from onionwatch.ui.panel import hint_label
from onionwatch.ui.windowpicker import thumbnail

THUMB = QSize(256, 144)
WHAT = {"appear": "showed up", "vanish": "went away", "change": "changed",
        "still": "stood still", "colour": "bar"}


def alert_text(a) -> str:
    """One history line: "14:02:31  Rare spawn\nshowed up in Game (copy 2) · 93%"."""
    when = time.strftime("%H:%M:%S", time.localtime(a.when))
    return f"{when}  {a.name}\n{WHAT.get(a.mode, '')} in {a.place} · {round(a.score * 100)}%"


class HistoryDialog(QDialog):
    """Follows `panel` (a TriggersTab): its history, newest first, live."""

    def __init__(self, panel, parent=None):
        super().__init__(parent)
        self.panel = panel
        self.setWindowTitle("What went off")
        self.resize(640, 560)
        v = QVBoxLayout(self)
        v.addWidget(hint_label(
            f"The last {panel.history.maxlen} alerts, newest first, each with the window as "
            "it was checked and a box round what set it off. They're only kept until "
            "Onion Watch closes."))
        self.list = QListWidget()
        self.list.setIconSize(THUMB)
        self.list.setSpacing(4)
        self.list.setWordWrap(True)
        v.addWidget(self.list, 1)
        self.empty = QLabel("Nothing has gone off yet.")
        self.empty.setObjectName("muted")
        self.empty.setAlignment(Qt.AlignCenter)
        v.addWidget(self.empty)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        self.btn_clear = QPushButton("Clear")
        buttons.addButton(self.btn_clear, QDialogButtonBox.ResetRole)
        self.btn_clear.clicked.connect(self._clear)
        buttons.rejected.connect(self.reject)
        v.addWidget(buttons)
        panel.history_changed.connect(self.refresh)
        self.refresh()

    def refresh(self):
        self.list.clear()
        for a in reversed(self.panel.history):
            it = QListWidgetItem(QIcon(thumbnail(a.picture, THUMB)), alert_text(a))
            self.list.addItem(it)
        self.empty.setVisible(not self.panel.history)
        self.btn_clear.setEnabled(bool(self.panel.history))

    def _clear(self):
        self.panel.history.clear()
        self.refresh()

    def done(self, r):
        try:
            self.panel.history_changed.disconnect(self.refresh)
        except (RuntimeError, TypeError):
            pass
        super().done(r)
