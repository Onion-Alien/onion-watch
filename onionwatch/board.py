"""Onion Watch inside Onion Board: the add-on module's entry point (module.json's
"entry"). Onion Board loads the `onionwatch` package from the module's folder,
imports this and calls create(host) with itself as the host (onionwatch.host.Host).
What comes back is the whole Triggers tab: Triggers / Log pages with the alarm
bar over them and the Playing now bar under them (ui.pages).

The board has no tray icon or settings window of Onion Watch's own: sounds are
the board's, played through the board (into the mic / cable mix), and the
settings stay in the board's config. A ringing trigger shows the red bar at the
top of the tab and flashes the taskbar button; Stop all on the board stops it too.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget

from onionwatch import __version__, i18n, theme
from onionwatch.host import API_VERSION, missing
from onionwatch.i18n import _


class IncompatibleHost(RuntimeError):
    """The host is too old for this Onion Watch (or isn't a host at all)."""


def check(host) -> None:
    """Refuse a host this version can't run in, with a message for the user."""
    lacks = missing(host)
    if lacks:
        raise IncompatibleHost(_("it isn't a triggers host (it has no {names})",
                                names=", ".join(lacks)))
    v = getattr(host, "api_version", 0)
    if not isinstance(v, int) or v < API_VERSION:
        raise IncompatibleHost(_("this Onion Watch ({version}) needs a newer {host}: update it "
                                "first", version=__version__,
                                host=getattr(host, "name", "host")))


def create(host) -> BoardPanel:
    # the board's language (its optional host.language(); Windows' on an older board),
    # set before the page's modules load: some of their text is made as they do
    i18n.follow_host(host)
    app = QApplication.instance()
    if app is not None:
        i18n.translate_qt_buttons(app)
    check(host)
    return BoardPanel(host)


class BoardPanel(QWidget):
    """The Triggers tab as Onion Board shows it. The board calls sounds_changed(),
    retheme(), cancel_pending(), stop_ringing() and shutdown() on it, and follows
    active_changed for the tab's live dot."""
    active_changed = Signal(bool)

    version = __version__
    api_version = API_VERSION

    def __init__(self, host):
        super().__init__()
        from onionwatch.ui.alarmbar import AlarmBar
        from onionwatch.ui.pages import TriggerPages
        from onionwatch.ui.triggerspanel import TriggersTab
        self.host = host
        theme.use_palette(host.palette())
        # the board owns the app's direction; on a board that hasn't mirrored the app (an
        # older one, the tab following Windows' Arabic) only this tab is mirrored
        app = QApplication.instance()
        if i18n.is_rtl() and (app is None or app.layoutDirection() != Qt.RightToLeft):
            self.setLayoutDirection(Qt.RightToLeft)
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 8, 0, 0)
        v.setSpacing(8)
        self.panel = TriggersTab(host)
        self.btn_more = self.panel.btn_more   # the board adds "Remove Onion Watch…" to it
        self.alarm = AlarmBar(self.panel)
        self.pages = TriggerPages(self.panel, top=[self.alarm])
        self.panel.pages = self.pages
        v.addWidget(self.pages, 1)
        self.panel.active_changed.connect(self.active_changed)
        self.panel.fired.connect(self._on_fired)

    def _on_fired(self, t):
        self.host.notify(t.name, self.panel.alert_text(t))
        win = self.window()
        if win is not None:
            QApplication.alert(win, 0 if t.ring else 3000)   # flash the taskbar button

    # ------------------------------------------------------------------ for the host
    def is_active(self) -> bool:
        return self.panel.is_active()

    def sounds_changed(self):
        self.panel.sounds_changed()

    def retheme(self):
        theme.use_palette(self.host.palette())
        self.panel.retheme()

    def cancel_pending(self):
        """Stop all on the board: sounds still waiting out a trigger's wait are
        dropped, and ringing stops."""
        self.panel.cancel_pending()
        self.panel.stop_ringing()

    def stop_ringing(self):
        self.alarm.stop()

    def fit_parts(self) -> dict[str, QWidget]:
        return self.panel.fit_parts()

    def shutdown(self):
        self.panel.stop_ringing()
        self.panel.shutdown()
