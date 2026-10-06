"""Padding the eye notices: the bottom bar's buttons sit inside its margins (also
on a wrapped second line), and a trigger card's Test and ⋯ (Duplicate / Delete) share
More options' line instead of taking a row of their own."""
from PySide6.QtWidgets import QWidget
import pytest

import test_ui
from test_ui import as_qimage, banner

fake_screen, tab = test_ui.fake_screen, test_ui.tab   # the same stand-ins
styled = test_ui.styled


def test_the_bottom_bar_keeps_its_margins_when_it_wraps(tab, qapp):
    tab.resize(480, 600)        # narrow enough to wrap (the check speed is under ⚙ now)
    tab.show()
    qapp.processEvents()
    bar = tab.toolbar
    m = bar.layout().contentsMargins()
    assert m.top() > 0 and m.left() > 0
    kids = [w for w in bar.findChildren(QWidget)
            if w.parentWidget() is bar and w.isVisible()]
    for w in kids:
        g = w.geometry()
        assert g.top() >= m.top() and g.left() >= m.left()
        assert g.bottom() <= bar.height() - m.bottom()
    assert len({w.y() for w in kids}) > 1     # it did wrap at this width


def test_test_and_the_menu_sit_on_more_options_line(tab, qapp):
    tab._new(as_qimage(banner()), "Rare")
    row = list(tab.rows.values())[-1]
    tab.resize(1100, 700)
    tab.show()
    qapp.processEvents()
    tune_y = row.btn_tune.mapTo(row, row.btn_tune.rect().center()).y()
    for b in (row.btn_test, row.btn_menu):
        assert abs(b.mapTo(row, b.rect().center()).y() - tune_y) <= 2


@pytest.mark.parametrize("width", [360, 600, 900, 1200])
def test_controls_fit_and_share_heights_across_window_sizes(tab, qapp, styled, width):
    tab._new(as_qimage(banner()), "Rare")
    row = list(tab.rows.values())[-1]
    row.btn_tune.setChecked(True)
    row.chk_ring.setChecked(True)
    tab.resize(width, 900)
    tab.show()
    for _ in range(12):
        qapp.processEvents()
    assert tab.width() == width
    controls = [row.mode, row.where, row.btn_area, row.interval, row.sound, row.until,
                row.btn_test, row.delay, row.cooldown, row.threshold, row.btn_menu]
    assert len({w.height() for w in controls}) == 1
    for w in controls:
        assert w.mapTo(row, w.rect().topLeft()).x() >= 0
        assert w.mapTo(row, w.rect().topRight()).x() < row.width()
    # Mixed-height labels and checkboxes sit on the same centre line as the buttons
    # (when there's room for them on one line).
    if width >= 900:
        assert abs(row.chk_size.mapTo(row, row.chk_size.rect().center()).y()
                   - row.btn_area.mapTo(row, row.btn_area.rect().center()).y()) <= 1


@pytest.mark.parametrize("width", [500, 1100])
def test_the_ring_list_isnt_cut_off_at_the_bottom(tab, qapp, styled, width):
    tab._new(as_qimage(banner()), "Rare")
    row = list(tab.rows.values())[-1]
    row.chk_ring.setChecked(True)
    tab.resize(width, 900)
    tab.show()
    for _ in range(12):
        qapp.processEvents()
    pair = row.ring_box     # was 26 px tall round a 34 px list: its bottom edge gone
    assert row.until.geometry().bottom() <= pair.height() - 1
    assert pair.geometry().bottom() <= pair.parentWidget().height() - 1
