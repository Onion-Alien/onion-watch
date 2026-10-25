"""The icon-to-words gap on Onion Watch's buttons (the same 8 px as Onion Board's)."""
from fakehost import FakeHost

from onionwatch.engine import screenwatch as sw
from onionwatch.ui.triggers.triggerspanel import TriggersTab


def test_bar_buttons_keep_the_icon_gap_until_a_host_makes_them_icon_only(
        qapp, tmp_path, monkeypatch):
    """Watching: 8 px from icon to words (Qt's 4 + 4 empty pixels),
    none once Onion Board shows it icon only (its "compact" property, then no words)."""
    monkeypatch.setattr(sw, "monitors", lambda: [sw.Monitor(0, 0, 320, 180, True)])
    tab = TriggersTab(FakeHost(tmp_path, {}))
    tab._lister = lambda: []
    tab._front = lambda: 0
    tab._label_watch()
    for b in (tab.btn_watch,):
        assert b.iconSize().width() == 22, b.text()
        full = b.text()
        b.setProperty("compact", True)
        b.setText("")
        qapp.processEvents()
        assert b.iconSize().width() == 18
        b.setProperty("compact", False)
        b.setText(full)
        qapp.processEvents()
        assert b.iconSize().width() == 22
    tab.shutdown()
    tab.deleteLater()
