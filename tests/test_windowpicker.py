"""Card input and saved window targets, with offscreen Qt and synthetic windows."""
import json

import numpy as np
import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QDialogButtonBox, QStyle, QStyleOptionViewItem

from onionwatch import screenwatch as sw
from onionwatch import windows
from onionwatch.ui.windowpicker import WindowPicker


@pytest.fixture
def picker(qapp, monkeypatch):
    monkeypatch.setattr(windows, "list_windows", lambda: [
        windows.WindowInfo(10, "Game", "game.exe", 100, 1, 320, 180)])
    monkeypatch.setattr(windows, "snapshot", lambda hwnd: np.zeros((18, 32, 4), np.uint8))
    monkeypatch.setattr(sw, "monitors", lambda: [sw.Monitor(0, 0, 320, 180, True)])
    dlg = WindowPicker(multi=True)
    dlg.show()  # conftest uses Qt's offscreen platform
    qapp.processEvents()
    return dlg


def indicator_point(picker, item):
    option = QStyleOptionViewItem()
    option.initFrom(picker.list)
    option.rect = picker.list.visualItemRect(item)
    picker.list.itemDelegate().initStyleOption(option, picker.list.indexFromItem(item))
    rect = picker.list.style().subElementRect(QStyle.SE_ItemViewItemCheckIndicator,
                                            option, picker.list)
    assert not rect.isEmpty()
    return rect.center()


@pytest.mark.parametrize("part", ["thumbnail", "label", "indicator"])
def test_repeated_card_clicks_toggle_once_after_thumbnail_updates(picker, qapp, part):
    item = picker.list.item(1)
    rect = picker.list.visualItemRect(item)
    point = (indicator_point(picker, item) if part == "indicator" else
             QPoint(rect.center().x(), rect.bottom() - 5) if part == "label" else rect.center())
    assert picker.list.itemAt(point) is item
    ok = picker.buttons.button(QDialogButtonBox.Ok)
    for expected in (Qt.Checked, Qt.Unchecked, Qt.Checked, Qt.Unchecked):
        item.setToolTip("Updated thumbnail metadata")
        QTest.mouseClick(picker.list.viewport(), Qt.LeftButton, pos=point)
        qapp.processEvents()
        assert item.checkState() == expected
        assert ok.isEnabled() == (expected == Qt.Checked)


def test_card_keyboard_right_click_and_disabled_items(picker):
    item = picker.list.item(0)
    picker.list.setCurrentItem(item)
    QTest.keyClick(picker.list, Qt.Key_Space)
    assert item.checkState() == Qt.Checked
    point = picker.list.visualItemRect(item).center()
    QTest.mouseClick(picker.list.viewport(), Qt.RightButton, pos=point)
    assert item.checkState() == Qt.Checked
    item.setFlags(item.flags() & ~Qt.ItemIsEnabled)
    QTest.mouseClick(picker.list.viewport(), Qt.LeftButton, pos=point)
    assert item.checkState() == Qt.Checked


def test_refresh_keeps_selection_and_cards_remain_clickable(picker, qapp):
    item = picker.list.item(1)
    QTest.mouseClick(picker.list.viewport(), Qt.LeftButton,
                     pos=picker.list.visualItemRect(item).center())
    picked = picker._ticked()
    picker.refresh()
    qapp.processEvents()
    assert picker._ticked() == picked
    item = picker.list.item(1)
    QTest.mouseClick(picker.list.viewport(), Qt.LeftButton,
                     pos=picker.list.visualItemRect(item).center())
    assert picker._ticked() == []


def test_double_click_does_not_add_a_second_toggle(picker):
    item = picker.list.item(1)
    point = picker.list.visualItemRect(item).center()
    QTest.mouseClick(picker.list.viewport(), Qt.LeftButton, pos=point)
    assert item.checkState() == Qt.Checked
    QTest.mouseDClick(picker.list.viewport(), Qt.LeftButton, pos=point)
    assert item.checkState() == Qt.Checked
    QTest.mouseRelease(picker.list.viewport(), Qt.LeftButton, pos=point)
    assert item.checkState() == Qt.Checked
    QTest.mouseClick(picker.list.viewport(), Qt.LeftButton, pos=point)
    assert item.checkState() == Qt.Unchecked


def test_single_window_picker_still_accepts_on_double_click(picker, qapp):
    dlg = WindowPicker()
    dlg.show()
    qapp.processEvents()
    item = dlg.list.item(0)
    point = dlg.list.visualItemRect(item).center()
    QTest.mouseClick(dlg.list.viewport(), Qt.LeftButton, pos=point)
    assert dlg.chosen is None
    QTest.mouseDClick(dlg.list.viewport(), Qt.LeftButton, pos=point)
    assert dlg.chosen == item.data(Qt.UserRole)


def test_saved_picker_targets_survive_new_pids_and_handles(picker, monkeypatch):
    picker.list.item(0).setCheckState(Qt.Checked)
    picker.list.item(1).setCheckState(Qt.Checked)
    picker._accept()
    raw = json.loads(json.dumps(sw.Trigger(id="saved", sources=picker.places).to_raw()))
    loaded = sw.Trigger.from_raw(raw)
    new_window = windows.WindowInfo(99, "Game", "game.exe", 999, 50, 320, 180)
    monkeypatch.setattr(windows, "list_windows", lambda: [new_window])
    assert windows.find(loaded.window) == new_window
    reopened = WindowPicker(current=loaded.sources, multi=True)
    assert reopened._ticked() == picker.places
    assert "pid" not in raw["windows"][0] and "hwnd" not in raw["windows"][0]
