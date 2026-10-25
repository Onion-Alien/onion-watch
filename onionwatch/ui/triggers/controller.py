"""The base of the triggers page's feature controllers (ui/triggers/*control.py), and
what the page and they share.

Each one is a QObject the page (TriggersTab) owns, not a plain object: a timer or
signal aimed at one of its methods then stops with the page (Qt drops a connection
when its receiver goes), as it did when the method was the page's own."""
from __future__ import annotations

import functools
import logging
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject
from PySide6.QtWidgets import QMessageBox

from onionwatch.i18n import _

if TYPE_CHECKING:
    from onionwatch.ui.triggers.triggerspanel import TriggersTab

log = logging.getLogger(__name__)

MAX_TRIGGERS = 500      # in all; how many can be on at once is up to the computer


class Controller(QObject):
    """One feature of a TriggersTab (``tab``), owned by it."""

    def __init__(self, tab: TriggersTab):
        super().__init__(tab)
        self.tab = tab


def needs_part(fallback=None):
    """For a method (the page's or a controller's) that opens a window from one of Onion
    Watch's own files, imported inside it: when that file is missing or out of step (an
    update that only half went in once crashed "Recently deleted"), say so plainly and
    return `fallback` instead. The import stays a plain one in the method, outside any
    `try`, so scripts/buildtools/build_module.py still sees the file is needed and packs it."""
    def wrap(method):
        @functools.wraps(method)
        def run(self, *args, **kwargs):
            try:
                return method(self, *args, **kwargs)
            except ImportError:
                log.exception("part of Onion Watch is missing (%s)", method.__name__)
                QMessageBox.warning(
                    getattr(self, "tab", self), _("Part of Onion Watch is missing"),
                    _("This window can't open: one of Onion Watch's files is missing, most "
                      "likely because an update didn't finish.\n\nUpdate or reinstall Onion "
                      "Watch to fix it. Your triggers and pictures are safe."))
                return fallback
        return run
    return wrap
