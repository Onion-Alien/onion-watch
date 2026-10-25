"""Padding the eye notices: the bottom bar's buttons sit inside its margins (also
on a wrapped second line), and a trigger card's Test and ⋯ (Duplicate / Delete) share
More options' line instead of taking a row of their own."""
import os

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


def test_the_sentence_then_the_rules_then_test_duplicate_delete_on_one_line(tab, qapp):
    tab._new(as_qimage(banner()), "Rare")
    row = list(tab.rows.values())[-1]
    tab.resize(1100, 700)
    tab.show()
    qapp.processEvents()
    row = tab.editor or row         # a wide window: the trigger is in the editor

    def centre(w):
        return w.mapTo(row, w.rect().center())
    when, play = centre(row.mode).y(), centre(row.sound).y()
    assert abs(centre(row.where).y() - when) <= 2                       # "When … in …"
    assert when < play < centre(row.chk_ring).y() < centre(row.btn_tune).y()
    test_y = centre(row.btn_test).y()
    assert test_y > centre(row.btn_tune).y()                            # under the rest
    for b in (row.cb_category, row.btn_dup, row.btn_del):
        assert abs(centre(b).y() - test_y) <= 2
        assert centre(b).x() > centre(row.btn_test).x()


@pytest.mark.parametrize("width", [360, 600, 900, 1200])
def test_controls_fit_and_share_heights_across_window_sizes(tab, qapp, styled, width):
    tab._new(as_qimage(banner()), "Rare")
    row = list(tab.rows.values())[-1]
    row.chk_ring.setChecked(True)
    tab.resize(width, 900)
    tab.show()
    for _ in range(12):
        qapp.processEvents()
    assert tab.width() == width
    row = tab.editor or row         # a wide window: the trigger is in the editor
    # the card's sentence and buttons fit the card; the extra settings fit their pop-up
    card = [row.mode, row.where, row.sound, row.until, row.btn_test, row.btn_tune,
            row.btn_dup, row.btn_del]
    row.show_rules()
    dlg = row.rules_dlg
    for _ in range(12):
        qapp.processEvents()
    extra = [row.btn_area, row.interval, row.delay, row.cooldown, row.threshold]
    assert len({w.height() for w in card + extra}) == 1
    for box, controls in ((row, card), (dlg, extra)):
        for w in controls:
            assert w.mapTo(box, w.rect().topLeft()).x() >= 0
            assert w.mapTo(box, w.rect().topRight()).x() < box.width()
    # each rule's tick box (or label) sits on its control's centre line
    for group in row.tune.groups:
        for lab, w, _inner in group:
            if lab is not None and w.isVisibleTo(row.tune):
                assert abs(lab.mapTo(dlg, lab.rect().center()).y()
                           - w.mapTo(dlg, w.rect().center()).y()) <= 1
    dlg.accept()


@pytest.mark.parametrize("width", [500, 1100])
def test_the_ring_list_isnt_cut_off_at_the_bottom(tab, qapp, styled, width):
    tab._new(as_qimage(banner()), "Rare")
    row = list(tab.rows.values())[-1]
    row.chk_ring.setChecked(True)
    tab.resize(width, 900)
    tab.show()
    for _ in range(12):
        qapp.processEvents()
    row = tab.editor or row         # a wide window: the trigger is in the editor
    pair = row.ring_box     # was 26 px tall round a 34 px list: its bottom edge gone
    assert row.until.geometry().bottom() <= pair.height() - 1
    assert pair.geometry().bottom() <= pair.parentWidget().height() - 1


@pytest.mark.parametrize("size, roomy", [((440, 750), False), ((440, 1000), True),
                                         ((1100, 750), True)])
def test_the_empty_list_fits_without_a_scroll_bar(qapp, app_dir, fake_screen, styled,
                                                   size, roomy):
    """Hoot and both paragraphs fit the smallest window; only there does the card's
    padding tighten, never at a size where the roomy one fits."""
    from onionwatch.core.settings import Config
    from onionwatch.ui import triggerspanel
    from onionwatch.ui.mainwindow import MainWindow
    win = MainWindow(Config())
    try:
        win.resize(*size)
        win.show()
        for _ in range(10):
            qapp.processEvents()
        tab = win.triggers
        assert tab.empty.isVisible()
        # (only with the real fonts: the stand-in font without QT_QPA_FONTDIR is wider)
        if os.environ.get("QT_QPA_FONTDIR"):
            assert tab.scroll.verticalScrollBar().maximum() == 0
        lay = tab.empty.layout()
        m = lay.contentsMargins()
        padding = (m.top(), m.bottom(), lay.spacing())
        assert padding == (triggerspanel.EMPTY_ROOMY if roomy else triggerspanel.EMPTY_TIGHT)
    finally:
        win.quit()
