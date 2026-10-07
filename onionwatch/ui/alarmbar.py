"""The alarm bar: a red strip that shows while a trigger rings, naming it, with the
one button that matters. Used by the Onion Watch window and, inside Onion Board,
at the top of the Triggers tab."""
from __future__ import annotations

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton

from onionwatch.ui import icons
from onionwatch.i18n import _

CHECK_MS = 500      # a ring can also end by itself (its trigger deleted, Stop all)


class AlarmBar(QFrame):
    """Follows `panel` (a TriggersTab): shown while any of its triggers rings."""
    changed = Signal(bool)      # ringing or not

    def __init__(self, panel, parent=None):
        super().__init__(parent)
        self.panel = panel
        self.setObjectName("alarm")
        self.setStyleSheet("QFrame#alarm { background:#e53935; border-radius:12px; }"
                           "QFrame#alarm QLabel { color:white; font-weight:700; "
                           "background:transparent; }"
                           "QFrame#alarm QPushButton { background:white; color:#b71c1c; "
                           "border:none; font-weight:800; padding:6px 18px; "
                           "border-radius:8px; }")
        h = QHBoxLayout(self)
        h.setContentsMargins(14, 8, 10, 8)
        self.icon = QLabel()
        self.icon.setPixmap(icons.pixmap("bell", 22, "#ffffff"))
        h.addWidget(self.icon)
        self.text = QLabel()
        self.text.setWordWrap(True)
        h.addWidget(self.text, 1)
        self.btn_stop = QPushButton(_("Stop"))
        self.btn_stop.setToolTip(_("Stop the ringing"))
        self.btn_stop.clicked.connect(self.stop)
        h.addWidget(self.btn_stop)
        self.hide()
        self._names: dict[str, str] = {}      # trigger id -> its name, while it rings
        self._on = False
        panel.fired.connect(self._on_fired)
        panel.ringing_changed.connect(self.update_bar)
        self._check = QTimer(self)
        self._check.timeout.connect(self.update_bar)
        self._check.start(CHECK_MS)

    def _on_fired(self, t):
        if t.ring:
            self._names[t.id] = t.name
        self.update_bar()

    def update_bar(self):
        tags = self.panel.host.ringing()
        names = [self._names.get(tag, _("A trigger")) for tag in dict.fromkeys(tags)]
        for tag in list(self._names):
            if tag not in tags:
                del self._names[tag]
        if names:
            text = names[0] if len(names) == 1 else _("{names} and {last}",
                                                      names=", ".join(names[:-1]),
                                                      last=names[-1])
            self.text.setText(_("{text} — ringing", text=text))
        self.setVisible(bool(names))
        if bool(names) != self._on:
            self._on = bool(names)
            self.changed.emit(self._on)

    @property
    def ringing(self) -> bool:
        return self._on

    def stop(self):
        self.panel.stop_ringing()
        self._names.clear()
        self.update_bar()
