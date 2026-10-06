"""Live chances: the card's little bar, and the Chances window behind the Playing
now bar's button, which Watching settings can hide."""
from onionwatch.ui import chances
from onionwatch.ui.pages import TriggerPages
from onionwatch.ui.watching import WatchingDialog

from test_categories import make, raw  # noqa: F401  (the fixture, and its triggers)


def watching(tab, monkeypatch, scores):
    """Pretend watching is on and has these scores."""
    monkeypatch.setattr(type(tab.watcher), "running", property(lambda _w: True))
    monkeypatch.setattr(tab, "is_active", lambda: True)
    tab.watcher.scores = dict(scores)


def test_the_window_lists_the_triggers_closest_first(make, monkeypatch):  # noqa: F811
    tab = make({"triggers": [raw(1, level=0.5), raw(2, level=0.5), raw(3, level=0.5),
                             raw(4, enabled=False)]})
    watching(tab, monkeypatch, {"t1": 0.1, "t2": 0.7, "t3": 0.45})
    dlg = chances.ChancesDialog(tab)
    assert dlg._order == ["t2", "t3", "t1"]         # over the line, nearly, far off
    assert dlg.rows["t2"].word.text().endswith("70%</span>")
    assert dlg.rows["t2"].bar.hot and not dlg.rows["t3"].bar.hot
    assert "t4" not in dlg.rows                     # off: only when asked for
    dlg.show_off.setChecked(True)
    assert "Off" in dlg.rows["t4"].word.text()
    dlg.sort.setCurrentIndex(1)                     # list order
    assert dlg._order == ["t1", "t2", "t3", "t4"]
    assert "1</span>" in dlg.stat_hot.text()
    dlg.deleteLater()


def test_not_watching_says_so(make):  # noqa: F811
    tab = make({"triggers": [raw(1)]})
    dlg = chances.ChancesDialog(tab)
    assert "Ready" in dlg.rows["t1"].word.text() and dlg.rows["t1"].bar.score is None
    assert "Not watching" in dlg.foot.text()
    dlg.deleteLater()


def test_a_card_draws_its_score_as_a_bar(make, monkeypatch):  # noqa: F811
    tab = make({"triggers": [raw(1, level=0.5)]})
    row = next(iter(tab.rows.values()))
    row.watching = True
    row.show_score(0.62)
    assert row.live.meter == (0.62, 0.5, True, False) and "62%" in row.live.text()
    assert row.live.size() == row.live.meter_size()
    row.show_score(None)
    assert row.live.meter is None and "Watching" in row.live.text()


def test_the_chances_button_can_be_hidden(make):  # noqa: F811
    tab = make({"triggers": [raw(1)]})
    pages = TriggerPages(tab)
    tab.pages = pages
    bar = pages.playing
    assert bar.btn_chances.isVisibleTo(bar)
    bar.btn_chances.click()
    assert bar.chances is not None and bar.chances.isVisible()
    bar.chances.accept()
    assert bar.chances is None
    dlg = WatchingDialog(tab)
    dlg.show_chances.setChecked(False)
    assert tab.host.screen["show_chances"] is False and not bar.btn_chances.isVisibleTo(bar)
    dlg.show_chances.setChecked(True)
    assert bar.btn_chances.isVisibleTo(bar)
    dlg.deleteLater()
    pages.deleteLater()
