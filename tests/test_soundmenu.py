"""The sound menu's list: a long one scrolls, with a gap between the rows and the scroll
bar (a highlighted row ran into it), and that gap is the list's own colour, not the
darker window colour that showed through the see-through scroll bar."""
import pytest
from PySide6.QtCore import QPoint

from onionwatch.ui.kit import theme
from onionwatch.ui.triggers.soundmenu import SoundMenu


@pytest.mark.parametrize("name", ["Hoot", "Light"])
def test_a_long_list_keeps_its_rows_off_the_scroll_bar_in_one_colour(qapp, name):
    old = qapp.styleSheet()
    theme.apply(qapp, name)
    try:
        sounds = [(f"s{i}", f"A sound with a long name {i}") for i in range(30)]
        menu = SoundMenu(sounds, [], set(), "FILE", lambda _sid: None)
        menu.resize(320, menu.sizeHint().height())
        menu.show()
        qapp.processEvents()
        lst, bar = menu.list, menu.list.verticalScrollBar()
        assert bar.isVisible()
        rows_end = lst.viewport().geometry().right()
        handle_start = bar.mapTo(lst, QPoint(bar.width() - 10, 0)).x()    # 10 px handle
        assert handle_start - rows_end >= 6
        img = menu.grab().toImage()              # as it shows: the whole menu
        y = lst.height() * 3 // 4                # below the handle
        inside = img.pixelColor(lst.mapTo(menu, QPoint(rows_end - 4, y))).name()
        gap = img.pixelColor(lst.mapTo(menu, QPoint(rows_end + 3, y))).name()
        assert gap == inside
        menu.close()
    finally:
        theme.apply(qapp, theme.DEFAULT)
        qapp.setStyleSheet(old)
