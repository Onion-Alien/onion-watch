"""Padding the eye notices: the bottom bar's buttons sit inside its margins (also
on a wrapped second line), and a trigger card's Duplicate / Delete share Fine-tune's
line instead of taking a row of their own."""
from PySide6.QtWidgets import QWidget

import test_ui
from test_ui import as_qimage, banner

fake_screen, tab = test_ui.fake_screen, test_ui.tab   # the same stand-ins


def test_the_bottom_bar_keeps_its_margins_when_it_wraps(tab, qapp):
    tab.resize(700, 600)
    tab.show()
    qapp.processEvents()
    bar = tab.btn_watch.parentWidget()
    m = bar.layout().contentsMargins()
    assert m.top() > 0 and m.left() > 0
    kids = [w for w in bar.findChildren(QWidget)
            if w.parentWidget() is bar and w.isVisible()]
    for w in kids:
        g = w.geometry()
        assert g.top() >= m.top() and g.left() >= m.left()
        assert g.bottom() <= bar.height() - m.bottom()
    assert len({w.y() for w in kids}) > 1     # it did wrap at this width


def test_duplicate_and_delete_sit_on_fine_tunes_line(tab, qapp):
    tab._new(as_qimage(banner()), "Rare")
    row = list(tab.rows.values())[-1]
    tab.resize(1100, 700)
    tab.show()
    qapp.processEvents()
    tune_y = row.btn_tune.mapTo(row, row.btn_tune.rect().center()).y()
    for b in (row.btn_dup, row.btn_del):
        assert abs(b.mapTo(row, b.rect().center()).y() - tune_y) <= 2
