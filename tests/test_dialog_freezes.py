"""The trigger page's windows open without freezing it: pictures are read on a thread,
and a file of Onion Watch missing after an update that only half went in gives a
plain message, not a crash."""
import sys
import time

import pytest
from PySide6.QtWidgets import QMessageBox

import test_ui
from conftest import process_events
from onionwatch.ui import viewer
from test_card_layout import new_card

fake_screen, tab = test_ui.fake_screen, test_ui.tab


def test_a_slow_picture_does_not_hold_up_the_viewer(tab, qapp, monkeypatch):
    row = new_card(tab)
    original = viewer.read_image

    def slow(path, size):
        time.sleep(1.0)                 # a huge picture, or a busy disk
        return original(path, size)

    monkeypatch.setattr(viewer, "read_image", slow)
    start = time.perf_counter()
    v = viewer.PictureViewer("Picture", lambda: row.t.images)
    qapp.processEvents()
    assert time.perf_counter() - start < 0.6
    assert v.view.img.isNull() and v.view.loading
    assert process_events(qapp, lambda: not v.view.img.isNull())
    assert not v.view.loading and "px" in v.info.text()
    v.deleteLater()


def test_a_quick_picture_is_there_on_the_first_paint(tab, qapp):
    row = new_card(tab)
    v = viewer.PictureViewer("Picture", lambda: row.t.images)
    assert not v.view.img.isNull() and "px" in v.info.text()
    assert process_events(qapp, lambda: not v.tiles or not v.tiles[0].icon().isNull())
    v.deleteLater()


@pytest.mark.parametrize("module, open_it", [
    ("onionwatch.ui.deleted", lambda tab, row: tab.show_deleted()),
    ("onionwatch.ui.watching", lambda tab, row: tab.show_watching()),
    ("onionwatch.ui.viewer", lambda tab, row: tab._view_picture(row, 0)),
])
def test_a_missing_part_says_so_plainly(tab, monkeypatch, module, open_it):
    row = new_card(tab)
    monkeypatch.setitem(sys.modules, module, None)     # its file is gone
    said = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: said.append(a[2]))
    open_it(tab, row)
    assert said and "update" in said[0].lower() and "reinstall" in said[0].lower()
