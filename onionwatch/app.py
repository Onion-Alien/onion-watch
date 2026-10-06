"""Application entry point: logging, single instance, the window."""
from __future__ import annotations

import ctypes
import logging
import logging.handlers
import os
import sys

from PySide6.QtWidgets import QApplication

from onionwatch import __version__, settings
from onionwatch.singleinstance import claim_single_instance, listen_for_second_launch

log = logging.getLogger(__name__)

LOG_NAME = "onionwatch.log"
TRAY_ARG = "--tray"      # start hidden in the tray


def setup_logging() -> None:
    """All logging to %APPDATA%\\OnionWatch\\onionwatch.log (3 x 1 MB): the app runs
    under pythonw.exe, where nothing else would ever see an error.
    ONIONWATCH_DEBUG=1 logs at DEBUG level."""
    settings.APP_DIR.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    root.setLevel(logging.DEBUG if os.environ.get("ONIONWATCH_DEBUG") else logging.INFO)
    for h in list(root.handlers):
        root.removeHandler(h)
    h = logging.handlers.RotatingFileHandler(settings.APP_DIR / LOG_NAME, maxBytes=1_000_000,
                                             backupCount=2, encoding="utf-8")
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(threadName)s "
                                     "%(name)s: %(message)s"))
    root.addHandler(h)
    if sys.stderr is not None:
        root.addHandler(logging.StreamHandler(sys.stderr))

    def hook(t, e, tb):
        log.critical("unhandled exception", exc_info=(t, e, tb))
    sys.excepthook = hook


def selftest() -> int:
    """`OnionWatch.exe --selftest`: prove a build can load everything it ships,
    without a window, a device or a capture. Prints OK and returns 0."""
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    for mod in ("numpy", "scipy.fft", "sounddevice", "soundfile", "soxr"):
        __import__(mod)
    _app = QApplication(sys.argv)   # noqa: F841 - kept alive while the imports run
    from onionwatch import sounds, theme
    from onionwatch.ui import mainwindow, settingsdialog, snip, windowpicker  # noqa: F401
    theme.app_icon()
    sounds.Library([]).load(sounds.DEFAULT_SOUND)
    print(f"OK: Onion Watch {__version__} self-test passed")
    return 0


def set_usage_count(argv: list[str]) -> int:
    """`OnionWatch.exe --usage-count on|off [--heard-from <answer>]`: the installer's
    "Count me in" box (and its "Where did you hear about Onion Watch?" page), saved
    to config.json before the app's first start, so an unticked box means nothing is
    ever sent. Other settings are kept; nothing connects; no window. 0 once saved."""
    i = argv.index("--usage-count")
    on = argv[i + 1:i + 2] == ["on"]
    cfg = settings.Config.load()
    cfg.usage_count = on
    if on and "--heard-from" in argv:
        j = argv.index("--heard-from")
        cfg.stats_heard = " ".join(argv[j + 1:j + 2])[:40]
    try:
        cfg.save()
    except OSError as e:
        print(f"FAIL: couldn't save the settings ({e})", file=sys.stderr)
        return 1
    log.info("--usage-count: %s", "on" if on else "off")
    print(f"OK: the anonymous usage count is {'on' if on else 'off'}")
    return 0


def main():
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    setup_logging()
    if "--usage-count" in sys.argv:
        sys.exit(set_usage_count(sys.argv))
    log.info("Onion Watch %s starting", __version__)
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("OnionWatch.App")
    except Exception:  # noqa: BLE001
        log.debug("SetCurrentProcessExplicitAppUserModelID failed", exc_info=True)
    app = QApplication(sys.argv)
    app.setApplicationName("Onion Watch")
    app.setQuitOnLastWindowClosed(False)     # the tray keeps it going
    if not claim_single_instance():
        log.info("another Onion Watch is running; asked it to come to the front")
        sys.exit(0)
    holder = {}
    app.instance_server = listen_for_second_launch(app, lambda: holder.get("w"))
    from onionwatch.ui import splash
    if TRAY_ARG not in sys.argv:   # Hoot hops about while the window is built
        splash.show()
    app.setStyle("Fusion")
    from onionwatch import theme
    app.setWindowIcon(theme.app_icon())
    from onionwatch.ui.mainwindow import MainWindow
    try:
        w = holder["w"] = MainWindow()
    except BaseException:
        splash.close()
        raise
    app.aboutToQuit.connect(w.shutdown)
    # new versions (updates.py) and the anonymous count (usage.py): each at most once a
    # day, unless switched off, also for a copy left running for days
    from PySide6.QtCore import QTimer
    from onionwatch import updates
    updates.cleanup()   # installers from an earlier update
    QTimer.singleShot(30_000, w.check_updates)
    QTimer.singleShot(40_000, w.send_usage)
    recheck = QTimer(w)
    recheck.timeout.connect(w.check_updates)
    recheck.timeout.connect(w.send_usage)
    recheck.start(6 * 3600 * 1000)
    if TRAY_ARG not in sys.argv or app.instance_server.show_requested:
        w.show()
    splash.close()
    sys.exit(app.exec())
