"""Recently deleted on the triggers page: the bin of deleted triggers (kept in
host.screen["deleted"], pictures and all), its button, letting old ones go, bringing
one back where it was, and deleting one for good. Deleting a trigger is the page's
(TriggersTab._remove); it puts it here.

TriggersTab makes one ``BinControl`` (``TriggersTab.binctl``)."""
from __future__ import annotations

import time
import uuid
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QMessageBox

from onionwatch.core import usage
from onionwatch.engine.screenwatch import Trigger
from onionwatch.i18n import _
from onionwatch.ui.triggers.controller import MAX_TRIGGERS, Controller, needs_part
from onionwatch.ui.triggers.pictures import _num, delete_picture

KEEP_DAYS = 30          # deleted triggers stay in Recently deleted this long
MAX_DELETED = 50        # ...and at most this many of them


class BinControl(Controller):
    """Recently deleted for one TriggersTab (``tab``)."""

    def _bin(self) -> list[dict]:
        """host.screen["deleted"], oldest first: {id, when, index, trigger (to_raw)}."""
        raw = self.tab.host.screen.get("deleted")
        return [d for d in raw if isinstance(d, dict) and isinstance(d.get("trigger"), dict)
                and isinstance(d.get("id"), str)] if isinstance(raw, list) else []

    def _label_bin(self):
        """The "Recently deleted (n)" button: there while the bin has triggers in it."""
        n = len(self._bin())
        btn = self.tab.btn_bin
        # just the bin and how many: a compact button that never makes the bar wrap
        btn.setText(str(n))
        what = _("Recently deleted ({n})", n=n)
        btn.setToolTip(what + "…\n" + _("Triggers you deleted: bring them back, "
                                        "pictures and all"))
        btn.setAccessibleName(what)
        btn.setVisible(n > 0)

    def _picture_used(self, path: str, but: dict | None = None) -> bool:
        """Whether a live trigger, or one in the bin (other than `but`), has this file."""
        if any(path in x.images for x in self.tab.triggers):
            return True
        for d in self._bin():
            if d is not but and d["id"] != (but or {}).get("id"):
                t = Trigger.from_raw(d["trigger"])
                if t is not None and path in t.images:
                    return True
        return False

    def _prune_bin(self):
        """Let go of deleted triggers older than KEEP_DAYS or past MAX_DELETED, and
        their pictures."""
        all_ = self._bin()
        cutoff = time.time() - KEEP_DAYS * 86400
        kept = [d for d in all_ if _num(d.get("when")) >= cutoff][-MAX_DELETED:]
        if len(kept) == len(all_):
            return
        self.tab.host.screen["deleted"] = kept
        for d in all_:
            if d not in kept:
                self._drop_pictures(d)
        self.tab.host.save()

    def _drop_pictures(self, entry: dict):
        """Delete a binned trigger's picture files (it's gone from the bin already, or
        about to be)."""
        t = Trigger.from_raw(entry.get("trigger", {}))
        for path in t.images if t is not None else []:
            if not self._picture_used(path, but=entry):
                delete_picture(path, self.tab.pictures)

    def deleted(self) -> list[tuple[str, str, float]]:
        """The bin for the Recently deleted window: (id, name, when), newest first."""
        return [(d["id"], str(d["trigger"].get("name") or _("Trigger")), _num(d.get("when")))
                for d in reversed(self._bin())]

    def restore_deleted(self, entry_id: str) -> bool:
        """Bring a deleted trigger back where it was, as it was."""
        tab = self.tab
        all_ = self._bin()
        entry = next((d for d in all_ if d["id"] == entry_id), None)
        if entry is None:
            return False
        if len(tab.triggers) >= MAX_TRIGGERS:
            QMessageBox.information(tab, _("Too many triggers"),
                                    _("You can have up to {max_triggers} triggers. Delete one to "
                                      "bring this one back.", max_triggers=MAX_TRIGGERS))
            return False
        t = Trigger.from_raw(entry["trigger"])
        if t is None:
            return False
        if any(x.id == t.id for x in tab.triggers):
            t = t.copy(uuid.uuid4().hex[:12])   # its id was taken meanwhile (a loaded pack)
        t.images = [p for p in t.images if Path(p).exists()]
        t.pending = ""
        tab.host.screen["deleted"] = [d for d in all_ if d is not entry]
        index = min(max(int(_num(entry.get("index"))), 0), len(tab.triggers))
        tab.triggers.insert(index, t)
        row = tab._add_row(t, at=index)
        tab._store()
        self._label_bin()
        # tab.scroll is the page's QScrollArea: pyright sees QWidget.scroll(), the method
        # it shadows
        QTimer.singleShot(0, row, lambda: tab.scroll.ensureWidgetVisible(row))  # pyright: ignore[reportAttributeAccessIssue]
        usage.used("restore-deleted")
        return True

    def forget_deleted(self, entry_id: str):
        """Delete one from the bin for good."""
        all_ = self._bin()
        entry = next((d for d in all_ if d["id"] == entry_id), None)
        if entry is None:
            return
        self.tab.host.screen["deleted"] = [d for d in all_ if d is not entry]
        self._drop_pictures(entry)
        self.tab.host.save()
        self._label_bin()

    @needs_part()
    def show_deleted(self):
        from onionwatch.ui.triggers.deleted import DeletedDialog
        tab = self.tab
        tab.undo_bar.finish()
        DeletedDialog(tab, KEEP_DAYS, self).exec()
        self._label_bin()
