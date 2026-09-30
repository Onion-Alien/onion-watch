"""The "Recently deleted" window for triggers: newest first, with Bring back and
Delete for good. The bin itself is the panel's (TriggersTab.deleted)."""
from __future__ import annotations

import time

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QDialog, QDialogButtonBox, QHBoxLayout,
                               QListWidget, QListWidgetItem, QMessageBox, QPushButton,
                               QVBoxLayout)

from onionwatch.ui import icons
from onionwatch.ui.panel import hint_label


def ago(when: float, now: float | None = None) -> str:
    """"just now", "5 min ago", "3 hours ago", "2 days ago"."""
    s = max(0, (now or time.time()) - when)
    if s < 60:
        return "just now"
    if s < 3600:
        return f"{int(s // 60)} min ago"
    if s < 86400:
        h = int(s // 3600)
        return f"{h} hour{'s' if h != 1 else ''} ago"
    d = int(s // 86400)
    return f"{d} day{'s' if d != 1 else ''} ago"


class DeletedDialog(QDialog):
    """Follows `panel` (a TriggersTab): panel.deleted() lists the bin as
    (id, name, when), panel.restore_deleted(id) brings one back (False if it
    couldn't), panel.forget_deleted(id) drops one for good."""

    def __init__(self, panel, keep_days: int, parent=None):
        super().__init__(parent)
        self.panel = panel
        self.setWindowTitle("Recently deleted triggers")
        lay = QVBoxLayout(self)
        lay.addWidget(hint_label(f"Triggers you delete are kept here for {keep_days} days, "
                                 "pictures and all, so you can bring them back."))
        self.list = QListWidget()
        self.list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.list.setMinimumSize(360, 240)
        self.list.itemSelectionChanged.connect(self._update)
        self.list.itemDoubleClicked.connect(lambda _i: self.bring_back())
        lay.addWidget(self.list, 1)
        row = QHBoxLayout()
        self.btn_back = QPushButton("Bring back")
        self.btn_back.setObjectName("primary")
        icons.set_icon(self.btn_back, "plus", "on_accent")
        self.btn_back.clicked.connect(self.bring_back)
        row.addWidget(self.btn_back)
        self.btn_forget = QPushButton("Delete for good")
        icons.set_icon(self.btn_forget, "trash", "danger_text")
        self.btn_forget.clicked.connect(self.delete_for_good)
        row.addWidget(self.btn_forget)
        row.addStretch(1)
        lay.addLayout(row)
        box = QDialogButtonBox(QDialogButtonBox.Close)
        box.rejected.connect(self.reject)
        lay.addWidget(box)
        self.fill()

    def fill(self):
        self.list.clear()
        for iid, name, when in self.panel.deleted():
            li = QListWidgetItem(f"{name}    ·    deleted {ago(when)}")
            li.setData(Qt.UserRole, iid)
            self.list.addItem(li)
        if self.list.count():
            self.list.setCurrentRow(0)
        else:
            li = QListWidgetItem("Nothing here. Deleted triggers show up here.")
            li.setFlags(Qt.NoItemFlags)
            self.list.addItem(li)
        self._update()

    def _picked(self) -> list[str]:
        return [li.data(Qt.UserRole) for li in self.list.selectedItems()
                if li.data(Qt.UserRole)]

    def _update(self):
        on = bool(self._picked())
        self.btn_back.setEnabled(on)
        self.btn_forget.setEnabled(on)

    def bring_back(self):
        for iid in self._picked():
            if not self.panel.restore_deleted(iid):
                break   # the panel said why (e.g. too many triggers)
        self.fill()

    def delete_for_good(self):
        ids = self._picked()
        if not ids:
            return
        n = len(ids)
        if QMessageBox.question(
                self, "Delete for good",
                f"Delete {'this trigger' if n == 1 else f'these {n} triggers'} for good? "
                "This can't be undone.") != QMessageBox.Yes:
            return
        for iid in ids:
            self.panel.forget_deleted(iid)
        self.fill()
