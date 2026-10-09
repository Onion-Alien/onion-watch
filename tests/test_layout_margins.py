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


def test_more_options_is_top_right_and_test_duplicate_delete_share_a_line(tab, qapp):
    tab._new(as_qimage(banner()), "Rare")
    row = list(tab.rows.values())[-1]
    tab.resize(1100, 700)
    tab.show()
    qapp.processEvents()
    row = tab.editor or row         # a wide window: the trigger is in the editor

    def centre(w):
        return w.mapTo(row, w.rect().center())
    assert abs(centre(row.btn_tune).y() - centre(row.mode).y()) <= 2      # the When line
    assert centre(row.btn_tune).x() > centre(row.mode).x()
    test_y = centre(row.btn_test).y()
    for b in (row.btn_dup, row.btn_del):
        assert abs(centre(b).y() - test_y) <= 2
    assert test_y > centre(row.cb_category).y()                         # under the rest


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
    if tab.editor is not None:      # a wide window: the trigger is in the editor
        row = tab.editor
        row.btn_tune.setChecked(True)
        for _ in range(12):
            qapp.processEvents()
    controls = [row.mode, row.where, row.btn_area, row.interval, row.sound, row.until,
                row.btn_test, row.delay, row.cooldown, row.threshold, row.btn_tune,
                row.btn_dup, row.btn_del]
    assert len({w.height() for w in controls}) == 1
    for w in controls:
        assert w.mapTo(row, w.rect().topLeft()).x() >= 0
        assert w.mapTo(row, w.rect().topRight()).x() < row.width()
    # each label under More options sits on its control's centre line
    for group in row.tune.groups:
        for lab, w, _inner in group:
            if lab is not None and w.isVisibleTo(row.tune):
                assert abs(lab.mapTo(row, lab.rect().center()).y()
                           - w.mapTo(row, w.rect().center()).y()) <= 1


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
