"""What went off lately: each alert with the time, the trigger, which window or
screen it was in, how strongly, and a picture of that window at the moment with a
box round what set it off. For "what woke me up?" and for setting the numbers.
Kept in memory only (TriggersTab.history): nothing is saved, unless "Save to a
file…" writes it out as text.

HistoryView is the list itself: the Log page beside the triggers (ui.pages) and,
in a window of its own, HistoryDialog (More → What went off…)."""
from __future__ import annotations

import time

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QFileDialog, QHBoxLayout, QLabel,
                               QListWidget, QListWidgetItem, QMessageBox, QPushButton,
                               QVBoxLayout, QWidget)

from onionwatch.ui.panel import hint_label
from onionwatch.ui.windowpicker import thumbnail

THUMB = QSize(160, 90)     # the window as it was, beside each line
WHAT = {"appear": "showed up", "vanish": "went away", "change": "changed",
        "still": "stood still", "colour": "bar"}


def alert_text(a) -> str:
    """One history line: "14:02:31  Rare spawn\nshowed up in Game (copy 2) · 93%"."""
    when = time.strftime("%H:%M:%S", time.localtime(a.when))
    return f"{when}  {a.name}\n{WHAT.get(a.mode, '')} in {a.place} · {round(a.score * 100)}%"


def log_line(a) -> str:
    """One alert as a line of the saved log: "2026-10-06 14:02:31  Rare spawn: showed
    up in Game (copy 2), 93%"."""
    when = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(a.when))
    return f"{when}  {a.name}: {WHAT.get(a.mode, '')} in {a.place}, {round(a.score * 100)}%"


class HistoryView(QWidget):
    """Follows `panel` (a TriggersTab): its history, newest first, live. Its Clear
    and Save to a file… buttons go where its owner puts them (button_row())."""

    def __init__(self, panel, parent=None, intro: bool = True):
        super().__init__(parent)
        self.panel = panel
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        if intro:
            v.addWidget(hint_label(
                f"The last {panel.history.maxlen} alerts, newest first, each with the "
                "window as it was checked and a box round what set it off. They're only "
                "kept until Onion Watch closes: Save to a file… keeps a copy."))
        self.list = QListWidget()
        self.list.setIconSize(THUMB)
        self.list.setSpacing(4)
        self.list.setWordWrap(True)
        v.addWidget(self.list, 1)
        self.empty = QLabel("Nothing has gone off yet.")
        self.empty.setObjectName("muted")
        self.empty.setAlignment(Qt.AlignCenter)
        v.addWidget(self.empty)
        self.btn_clear = QPushButton("Clear")
        self.btn_clear.setToolTip("Empty the list")
        self.btn_clear.clicked.connect(self._clear)
        self.btn_save = QPushButton("Save to a file…")
        self.btn_save.setToolTip("Write the list out as a text file")
        self.btn_save.clicked.connect(self.save)
        panel.history_changed.connect(self.refresh)
        self.refresh()

    def button_row(self) -> QHBoxLayout:
        """Clear and Save to a file… in a row (for a page without a dialog's buttons)."""
        h = QHBoxLayout()
        h.addWidget(self.btn_save)
        h.addWidget(self.btn_clear)
        h.addStretch(1)
        return h

    def refresh(self):
        self.list.clear()
        for a in reversed(self.panel.history):
            # no picture (a check that kept none): no empty space for one either
            it = (QListWidgetItem(QIcon(thumbnail(a.picture, THUMB)), alert_text(a))
                  if not a.picture.isNull() else QListWidgetItem(alert_text(a)))
            self.list.addItem(it)
        self.empty.setVisible(not self.panel.history)
        self.btn_clear.setEnabled(bool(self.panel.history))
        self.btn_save.setEnabled(bool(self.panel.history))

    def _clear(self):
        n = len(self.panel.history)
        if n > 1 and QMessageBox.question(
                self, "Clear the list",
                f"Clear all {n} alerts from the list? This can't be undone.") != QMessageBox.Yes:
            return
        self.panel.history.clear()
        self.refresh()

    def save(self, path: str = ""):
        if not path:
            path, _ = QFileDialog.getSaveFileName(self, "Save the log",
                                                  "Onion Watch log.txt", "Text (*.txt)")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.writelines(log_line(a) + "\n" for a in self.panel.history)
        except OSError as e:
            QMessageBox.warning(self, "Couldn't save the log", str(e))

    def detach(self):
        try:
            self.panel.history_changed.disconnect(self.refresh)
        except (RuntimeError, TypeError):
            pass


class HistoryDialog(QDialog):
    """HistoryView in a window of its own."""

    def __init__(self, panel, parent=None):
        super().__init__(parent)
        self.panel = panel
        self.setWindowTitle("What went off")
        self.resize(640, 560)
        v = QVBoxLayout(self)
        self.view = HistoryView(panel, self)
        v.addWidget(self.view, 1)
        self.list, self.empty = self.view.list, self.view.empty
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.addButton(self.view.btn_save, QDialogButtonBox.ActionRole)
        buttons.addButton(self.view.btn_clear, QDialogButtonBox.ResetRole)
        buttons.rejected.connect(self.reject)
        v.addWidget(buttons)

    def refresh(self):
        self.view.refresh()

    def _clear(self):
        self.view._clear()

    def done(self, r):
        self.view.detach()
        super().done(r)
