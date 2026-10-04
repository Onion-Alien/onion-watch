"""Test setup: never touch the real %APPDATA%\\OnionWatch folder, keep Qt on the
offscreen platform (no window ever appears), and never make a sound: the output
stream is a stand-in that runs the callback at the device's pace and throws the
audio away."""
import os
import sys
import tempfile
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("ONIONWATCH_INSTANCE", "pytest")
os.environ["ONIONWATCH_HOME"] = tempfile.mkdtemp(prefix="onionwatch-test-")

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class SilentOutputStream:
    """Stands in for sounddevice.OutputStream. `blocks` counts callbacks run and
    `peak` is the loudest sample written, so a test can tell a sound played."""
    opened: list = []

    def __init__(self, *, samplerate, channels, callback, blocksize=0, **_):
        self._rate, self._chans, self._cb = int(samplerate), int(channels), callback
        self._frames = blocksize or max(1, self._rate // 100)   # 10 ms blocks
        self._stop = None
        self._thread = None
        self.peak = 0.0
        self.blocks = 0
        SilentOutputStream.opened.append(self)

    def _run(self):
        import numpy as np
        buf = np.zeros((self._frames, self._chans), dtype="float32")
        period = self._frames / self._rate
        while not self._stop.wait(period):
            try:
                self._cb(buf, self._frames, None, None)
            except Exception:  # noqa: BLE001 - a real stream would swallow it too
                return
            self.blocks += 1
            self.peak = max(self.peak, float(np.abs(buf).max()))

    def start(self):
        import threading
        if self._thread is None:
            self._stop = threading.Event()
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()

    def stop(self):
        if self._thread is not None:
            self._stop.set()
            self._thread.join(1)
            self._thread = None

    close = stop
    abort = stop

    @property
    def active(self) -> bool:
        return self._thread is not None


import sounddevice  # noqa: E402

sounddevice.OutputStream = SilentOutputStream


@pytest.fixture(scope="session")
def qapp():
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    app.setStyle("Fusion")
    return app


def process_events(app, until, timeout=8.0, step=0.02):
    """Spin the Qt event loop until `until()` is true (or the timeout passes)."""
    import time

    from PySide6.QtCore import QEventLoop
    end = time.monotonic() + timeout
    while not until() and time.monotonic() < end:
        app.processEvents(QEventLoop.AllEvents, int(step * 1000))
        time.sleep(step / 4)
    return until()


@pytest.fixture
def app_dir(tmp_path, monkeypatch):
    """A fresh app folder per test (settings.APP_DIR is read when used)."""
    from onionwatch import settings
    monkeypatch.setattr(settings, "APP_DIR", tmp_path)
    return tmp_path


def pytest_xdist_auto_num_workers(config):
    """`-n auto` (pyproject's addopts): the whole suite runs on up to 4 workers; a file
    or two runs in this process, where starting workers would cost more than it
    saves. `-n 2` / `-n 0` on the command line override it."""
    picked = [a for a in config.args if Path(a.split("::")[0]).suffix == ".py"]
    if picked and len(picked) == len(config.args) and len(picked) <= 2:
        return 0
    return min(4, os.cpu_count() or 1)


@pytest.fixture(autouse=True)
def _free_test_windows():
    """Close and free the windows a test leaves behind. Qt keeps a closed top-level
    window alive, and every stylesheet change restyles all of them: with hundreds
    left over from earlier tests, one `styled` test's setup took over 100 s."""
    from PySide6.QtWidgets import QApplication
    from shiboken6 import getCppPointer

    def key(w):
        return getCppPointer(w)[0]   # the C++ object: a wrapper's id() can change

    app = QApplication.instance()
    before = set(map(key, app.topLevelWidgets())) if app is not None else set()
    yield
    app = QApplication.instance()
    if app is None:
        return
    from PySide6.QtCore import QEvent
    for w in app.topLevelWidgets():
        if key(w) not in before:
            try:
                w.close()
                w.deleteLater()
            except RuntimeError:   # already gone on the C++ side
                pass
    app.sendPostedEvents(None, QEvent.DeferredDelete)
