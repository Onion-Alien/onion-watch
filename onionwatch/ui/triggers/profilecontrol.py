"""Profiles on the triggers page: the Profile list (Manual, each profile, Automatic,
Edit profiles), switching between them, editing them, and Automatic's look at which
programs are open every APP_POLL_MS. The profiles themselves (which categories each
switches on, for which programs) are onionwatch.engine.profiles, kept in
TriggersTab.groups.

TriggersTab makes one ``ProfileControl`` (``TriggersTab.profilectl``)."""
from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

from PySide6.QtCore import QTimer

from onionwatch.engine import profiles
from onionwatch.i18n import _
from onionwatch.ui.triggers.categories import ProfilesDialog
from onionwatch.ui.triggers.controller import Controller

if TYPE_CHECKING:
    from onionwatch.ui.triggers.triggerspanel import TriggersTab

log = logging.getLogger(__name__)

APP_POLL_MS = 2000      # how often Automatic profiles look at which programs are open
EDIT_PROFILES = "__edit_profiles__"   # the Profile list's "Edit profiles"


class ProfileControl(Controller):
    """The profiles of one TriggersTab (``tab``)."""

    def __init__(self, tab: TriggersTab):
        super().__init__(tab)
        self._app_timer = QTimer(self)
        self._app_timer.setInterval(APP_POLL_MS)
        self._app_timer.timeout.connect(self._check_apps)

    def _fill_profiles(self):
        tab = self.tab
        cb, g = tab.cb_profile, tab.groups
        cb.blockSignals(True)
        cb.clear()
        cb.addItem(_("Manual (your switches)"), "")
        for p in g.profiles:
            cb.addItem(p.name, p.id)
        if g.profiles:
            cb.addItem(_("Automatic (by program)"), profiles.AUTO)
        cb.insertSeparator(cb.count())
        cb.addItem(_("Edit profiles"), EDIT_PROFILES)
        cb.setCurrentIndex(max(0, cb.findData(g.mode)))
        cb.blockSignals(False)
        tab.groupbar.setVisible(tab._grouped())

    def _profile_state(self) -> str:
        """Who decides what's on, in a few words, when it isn't Manual."""
        g = self.tab.groups
        if g.mode != profiles.AUTO:
            return ""
        ps = g.in_charge(self.tab.apps.matched)
        if not ps:
            return _("no profile's program is open: your switches apply")
        return _("on now: {names}", names=", ".join(p.name for p in ps))

    def set_profile(self, mode: str):
        """Manual (""), a profile's id, or profiles.AUTO."""
        tab = self.tab
        g = tab.groups
        if mode != profiles.AUTO and mode and g.profile(mode) is None:
            mode = ""
        g.mode = mode
        tab._save_groups()
        self._fill_profiles()
        self._update_app_timer()
        tab._apply_active(force=True)

    def _on_profile(self, _i: int):
        cb, g = self.tab.cb_profile, self.tab.groups
        want = cb.currentData()
        if want == EDIT_PROFILES:
            cb.setCurrentIndex(max(0, cb.findData(g.mode)))
            self.edit_profiles()
            return
        self.set_profile(want or "")

    def edit_profiles(self):
        tab = self.tab
        g = tab.groups
        start = g.mode if g.profile(g.mode) else ""
        dlg = ProfilesDialog(tab, g.profiles, g.names(), tab._lister, start)
        if dlg.exec():
            self.set_profiles(dlg.result_profiles)

    def set_profiles(self, ps: list):
        tab = self.tab
        g = tab.groups
        g.profiles = ps[:profiles.MAX_PROFILES]
        mode = g.mode
        if mode == profiles.AUTO and not ps:
            mode = ""
        tab.apps.matched = [m for m in tab.apps.matched if g.profile(m)]
        self.set_profile(mode)
        tab._layout_sections()

    def _update_app_timer(self):
        """Automatic looks at the open programs every APP_POLL_MS (only then)."""
        g = self.tab.groups
        if g.mode == profiles.AUTO and any(p.apps for p in g.profiles):
            if not self._app_timer.isActive():
                self._app_timer.start()
            self._check_apps()
        else:
            self._app_timer.stop()
            self.tab.apps.matched = []

    def _check_apps(self):
        """Which profiles' programs are open (or in front) now; a change switches
        their categories on or off. A ring going on isn't stopped by it."""
        tab = self.tab
        try:
            wins = tab._lister()
            fg = tab._front()
        except OSError:
            log.debug("couldn't list the windows for the profiles", exc_info=True)
            return
        running = {w.exe for w in wins if w.exe}
        front = next((w.exe for w in wins if w.hwnd == fg), "")
        if tab.apps.update(tab.groups.profiles, running, front, time.monotonic()):
            log.info("profiles on now: %s", ", ".join(
                p.name for p in tab.groups.in_charge(tab.apps.matched)) or "none")
            tab._apply_active(force=True)
