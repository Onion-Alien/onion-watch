"""The logo that shows it's watching (ui.watchlogo): shut while nothing is watched,
a laser sweep on Start watching that ends by itself, and still while in the
background. Offscreen, no sound."""
from PySide6.QtWidgets import QWidget

from onionwatch.ui import watchlogo
from onionwatch.ui.watchlogo import BURST_S, WatchLogo


def make(qapp, monkeypatch, front=True):
    monkeypatch.setattr(watchlogo.appstate, "active", lambda: front)
    host = QWidget()
    host.resize(600, 300)
    logo = WatchLogo(24, 24, 34, beam_host=host, parent=host)
    host.show()
    qapp.processEvents()
    return host, logo


def test_the_eye_opens_fires_the_laser_once_and_shuts_again(qapp, monkeypatch):
    host, logo = make(qapp, monkeypatch)
    assert logo.glow() == 0 and logo.pixmap() is logo._asleep
    logo.set_watching(True)
    assert logo.beam.isVisible() and logo.burst_t() == 0
    for _ in range(int(BURST_S / 0.05) + 2):
        logo.step(0.05)
    assert logo.burst_t() < 0 and not logo.beam.isVisible()   # the sweep ends by itself
    assert logo.glow() > 0.4 and logo.pixmap() is logo._awake
    x0 = logo.eye_center().x()
    logo.step(0.8)
    assert logo.eye_center().x() != x0                         # it looks around
    logo.set_watching(False)
    for _ in range(20):
        logo.step(0.05)
    assert logo.glow() == 0 and logo.pixmap() is logo._asleep
    host.close()


def test_behind_a_game_it_lights_up_without_moving(qapp, monkeypatch):
    host, logo = make(qapp, monkeypatch, front=False)
    logo.set_watching(True)
    assert not logo.beam.isVisible() and logo.burst_t() < 0
    assert not logo._timer.isActive() and logo.glow() > 0.4
    host.close()


def test_the_beam_never_takes_a_click(qapp, monkeypatch):
    from PySide6.QtCore import Qt
    host, logo = make(qapp, monkeypatch)
    assert logo.beam.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    host.close()
