"""Picture windows stay owned, paint immediately, and do not decode on resize."""
import time

from PySide6.QtCore import QCoreApplication, QEvent, QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

import test_ui
from onionwatch.ui import viewer
from test_card_layout import new_card

fake_screen, tab = test_ui.fake_screen, test_ui.tab


def drain(qapp):
    qapp.processEvents()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


def test_resize_does_not_decode_again(tab, qapp, monkeypatch):
    row = new_card(tab)
    v = viewer.PictureViewer("Picture", lambda: row.t.images)
    v.show()
    drain(qapp)
    original = viewer.QImage
    reads = []

    def image(*args):
        reads.append(args)
        return original(*args)

    monkeypatch.setattr(viewer, "QImage", image)
    for width in (640, 700, 800):
        v.resize(width, 400)
        drain(qapp)
    v.close()
    v.deleteLater()
    assert not reads


def test_rebuilt_thumbnails_never_become_top_level(tab, qapp):
    row = new_card(tab)
    tab.show()
    drain(qapp)
    before = set(QApplication.topLevelWidgets())
    row.refresh_pictures()
    assert not set(QApplication.topLevelWidgets()) - before


def test_twenty_opens_paint_picture_once_and_leave_no_windows(tab, qapp, monkeypatch):
    row = new_card(tab)
    row.set_open(False)
    tab.show()
    tab.watcher.interval = 0.016
    tab.set_watching(True)  # synthetic screen and silent audio from the fixture
    drain(qapp)
    before = set(QApplication.topLevelWidgets())
    painted = []
    original_paint = viewer.PictureView.paintEvent

    def paint(self, event):
        painted.append(not self.img.isNull())
        original_paint(self, event)

    monkeypatch.setattr(viewer.PictureView, "paintEvent", paint)
    elapsed = []
    for _ in range(20):
        thumb = row.strip.thumbs[0]
        QTest.mouseMove(thumb.pic, QPoint(10, 10))
        start = time.perf_counter()
        thumb.pic.click()
        thumb.pic.click()  # queued/repeated activation must reuse the dialog
        drain(qapp)
        dialogs = [w for w in QApplication.topLevelWidgets()
                   if isinstance(w, viewer.PictureViewer) and w.isVisible()]
        assert len(dialogs) == 1
        assert all(painted) and painted
        elapsed.append(time.perf_counter() - start)
        assert all(w is dialogs[0] or w.windowType() == Qt.ToolTip
                   for w in set(QApplication.topLevelWidgets()) - before)
        dialogs[0].close()
        drain(qapp)
        assert not [w for w in QApplication.topLevelWidgets()
                    if w not in before and w.windowType() != Qt.ToolTip]
    assert max(elapsed) < 1.0


def test_advanced_is_saved_and_new_cards_inherit_it(tab):
    row = new_card(tab)
    row.set_open(False)
    tab.chk_advanced.setChecked(True)
    assert tab.host.screen["advanced_cards"] is True
    assert not row.details.isHidden()
    other = new_card(tab)
    other.set_open(False)
    assert not other.details.isHidden()
    assert "Cooldown:" in other.details.text()
    tab.chk_advanced.setChecked(False)
    assert other.details.isHidden()
