"""The "a new version is out" dialog: what's new, and Update now / Later / Skip this
version. Update now downloads the installer (onionwatch.updates: SHA-256 checked)
with a progress bar, then starts it and quits so it can replace the files; the
installer opens Onion Watch again. A copy running from source (or a release with no
installer the app can check) gets "Open its page" instead."""
from __future__ import annotations

import logging
import threading
import webbrowser

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QLabel, QProgressBar, QPushButton,
                               QVBoxLayout)

from onionwatch import __version__, updates, usage
from onionwatch.ui.panel import hint_label
from onionwatch.ui import fit
from onionwatch.i18n import _

log = logging.getLogger(__name__)


class _Relay(QObject):
    """Carries the download thread's news to the UI thread."""
    progress = Signal(int, int)
    done = Signal(object)
    failed = Signal(str)


class UpdateDialog(QDialog):
    def __init__(self, win, rel: updates.Release):
        super().__init__(win)
        fit.watch(self)          # grows to fit its (translated) text
        self.win, self.rel = win, rel
        self._cancel = threading.Event()
        self._busy = False
        self.setWindowTitle(_("Update Onion Watch"))
        self.setMinimumWidth(440)
        v = QVBoxLayout(self)
        v.setSpacing(10)
        head = QLabel(_("Onion Watch {version} is out", version=rel.version))
        head.setObjectName("section")
        v.addWidget(head)
        v.addWidget(hint_label(_("You have {version}. Your triggers, pictures and sounds stay as "
                                 "they are.", version=__version__)))
        if rel.notes:
            notes = QLabel(rel.notes)
            notes.setWordWrap(True)
            notes.setTextFormat(Qt.PlainText)
            v.addWidget(notes)
        self.bar = QProgressBar()
        self.bar.hide()
        v.addWidget(self.bar)
        self.status = hint_label("")
        self.status.hide()
        v.addWidget(self.status)

        row = QHBoxLayout()
        self.btn_skip = QPushButton(_("Skip this version"))
        self.btn_skip.clicked.connect(self._skip)
        row.addWidget(self.btn_skip)
        row.addStretch(1)
        self.btn_later = QPushButton(_("Later"))
        self.btn_later.clicked.connect(self.reject)
        row.addWidget(self.btn_later)
        self.installable = updates.can_install() and bool(rel.asset_url)
        self.btn_go = QPushButton(_("Update now") if self.installable else _("Open its page"))
        self.btn_go.setDefault(True)
        self.btn_go.clicked.connect(self._go)
        row.addWidget(self.btn_go)
        v.addLayout(row)

        self.relay = _Relay(self)
        self.relay.progress.connect(self._on_progress)
        self.relay.done.connect(self._on_done)
        self.relay.failed.connect(self._on_failed)

    def _skip(self):
        self.win.cfg.update_skip = self.rel.version
        self.win.save_later()
        self.reject()

    def _go(self):
        if self._busy:          # the button is Cancel while downloading
            self._cancel.set()
            return
        if not self.installable:
            webbrowser.open(self.rel.url)
            self.accept()
            return
        self._busy = True
        self._cancel.clear()
        self.btn_go.setText(_("Cancel"))
        self.btn_skip.hide()
        self.btn_later.hide()
        self.bar.setRange(0, 0)
        self.bar.show()
        self.status.setText(_("Downloading the update…"))
        self.status.show()
        threading.Thread(target=self._download, daemon=True, name="update-download").start()

    def _download(self):
        try:
            path = updates.download(self.rel, self.relay.progress.emit, self._cancel.is_set)
        except updates.UpdateError as e:
            self.relay.failed.emit(str(e))
            return
        except Exception as e:  # noqa: BLE001 - shown, not crashed on
            log.warning("update download failed", exc_info=True)
            self.relay.failed.emit(str(e))
            return
        self.relay.done.emit(path)

    def _on_progress(self, done: int, total: int):
        if total > 0:
            self.bar.setRange(0, 1000)
            self.bar.setValue(min(1000, done * 1000 // total))
            self.status.setText(_("Downloading the update… {done} of {total} MB",
                                  done=done >> 20, total=total >> 20))

    def _on_failed(self, msg: str):
        self._busy = False
        self.bar.hide()
        self.btn_go.setText(_("Try again"))
        self.btn_later.show()
        self.btn_skip.show()
        self.status.setText(_("Not updated: {reason}", reason=msg) if msg != "cancelled"
                            else _("Cancelled."))

    def _on_done(self, path):
        self.status.setText(_("Installing… Onion Watch closes and opens again by itself."))
        t = usage.maybe_send(self.win.cfg, event=usage.update_event(self.rel.version))
        if t is not None:
            t.join(3)   # a moment for the count; the update doesn't wait on it
        try:
            updates.start_install(path)
        except OSError as e:
            self._on_failed(_("the installer couldn't be started ({error})", error=e))
            return
        self.accept()
        self.win.quit()
