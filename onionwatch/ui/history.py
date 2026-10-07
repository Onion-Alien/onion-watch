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
from onionwatch.ui import fit
from onionwatch.i18n import _

THUMB = QSize(160, 90)     # the window as it was, beside each line
WHAT = {"appear": _("showed up"), "vanish": _("went away"), "change": _("changed"),
        "still": _("stood still"), "colour": _("bar")}


def alert_text(a) -> str:
    """One history line: "14:02:31  Rare spawn\nshowed up in Game (copy 2) · 93%"."""
    when = time.strftime("%H:%M:%S", time.localtime(a.when))
    return f"{when}  {a.name}\n" + _("{what} in {place} · {score}%", what=WHAT.get(a.mode, ""),
                                     place=a.place, score=round(a.score * 100))


def log_line(a) -> str:
    """One alert as a line of the saved log: "2026-10-06 14:02:31  Rare spawn: showed
    up in Game (copy 2), 93%"."""
    when = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(a.when))
    return f"{when}  {a.name}: " + _("{what} in {place}, {score}%", what=WHAT.get(a.mode, ""),
                                     place=a.place, score=round(a.score * 100))


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
                _("The last {maxlen} alerts, newest first, each with the window as it was "
                  "checked and a box round what set it off. They're only kept until Onion Watch "
                  "closes: Save to a file… keeps a copy.", maxlen=panel.history.maxlen)))
        self.list = QListWidget()
        self.list.setIconSize(THUMB)
        self.list.setSpacing(4)
        self.list.setWordWrap(True)
        v.addWidget(self.list, 1)
        self.empty = QLabel(_("Nothing has gone off yet."))
        self.empty.setObjectName("muted")
        self.empty.setAlignment(Qt.AlignCenter)
        v.addWidget(self.empty)
        self.btn_clear = QPushButton(_("Clear"))
        self.btn_clear.setToolTip(_("Empty the list"))
        self.btn_clear.clicked.connect(self._clear)
        self.btn_save = QPushButton(_("Save to a file…"))
        self.btn_save.setToolTip(_("Write the list out as a text file"))
        self.btn_save.clicked.connect(self.save)
        self._shown: list = []      # the alerts in the list, oldest first
        self._behind = False        # history changed while it was hidden
        panel.history_changed.connect(self._changed)
        self.refresh()

    def button_row(self) -> QHBoxLayout:
        """Clear and Save to a file… in a row (for a page without a dialog's buttons)."""
        h = QHBoxLayout()
        h.addWidget(self.btn_save)
        h.addWidget(self.btn_clear)
        h.addStretch(1)
        return h

    @staticmethod
    def _item(a) -> QListWidgetItem:
        # no picture (a check that kept none): no empty space for one either
        return (QListWidgetItem(QIcon(thumbnail(a.picture, THUMB)), alert_text(a))
                if not a.picture.isNull() else QListWidgetItem(alert_text(a)))

    def refresh(self):
        """Fill the list again from the history."""
        self.list.clear()
        self._shown = list(self.panel.history)
        self._behind = False
        for a in reversed(self._shown):
            self.list.addItem(self._item(a))
        self._label()

    def _changed(self):
        """Something went off (or the history was cleared): only the new alerts are
        added at the top and the ones the history let go of taken off the bottom, and
        only once the list is on screen."""
        if not self.isVisible():
            self._behind = True
            self._label()
            return
        self._catch_up()

    def _catch_up(self):
        now = list(self.panel.history)
        shown = self._shown
        start = next((i for i, a in enumerate(shown) if now and a is now[0]), None)
        kept = len(shown) - start if start is not None else 0
        if start is None and shown or any(a is not b for a, b in zip(shown[start or 0:], now)):
            self.refresh()          # not just more of the same (cleared, or another list)
            return
        for _i in range(start or 0):           # the oldest, at the bottom
            self.list.takeItem(self.list.count() - 1)
        for a in now[kept:]:
            self.list.insertItem(0, self._item(a))
        self._shown = now
        self._behind = False
        self._label()

    def showEvent(self, ev):
        super().showEvent(ev)
        if self._behind:
            self._catch_up()

    def _label(self):
        self.empty.setVisible(not self.panel.history)
        self.btn_clear.setEnabled(bool(self.panel.history))
        self.btn_save.setEnabled(bool(self.panel.history))

    def _clear(self):
        n = len(self.panel.history)
        if n > 1 and QMessageBox.question(
                self, _("Clear the list"),
                _("Clear all {n} alerts from the list? This can't be undone.",
                  n=n)) != QMessageBox.Yes:
            return
        self.panel.history.clear()
        self.refresh()

    def save(self, path: str = ""):
        if not path:
            path, __ = QFileDialog.getSaveFileName(self, _("Save the log"),
                                                  _("Onion Watch log") + ".txt",
                                                  _("Text") + " (*.txt)")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.writelines(log_line(a) + "\n" for a in self.panel.history)
        except OSError as e:
            QMessageBox.warning(self, _("Couldn't save the log"), str(e))

    def detach(self):
        try:
            self.panel.history_changed.disconnect(self._changed)
        except (RuntimeError, TypeError):
            pass


class HistoryDialog(QDialog):
    """HistoryView in a window of its own."""

    def __init__(self, panel, parent=None):
        super().__init__(parent)
        fit.watch(self)          # grows to fit its (translated) text
        self.panel = panel
        self.setWindowTitle(_("What went off"))
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
