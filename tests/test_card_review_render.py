"""Optional offscreen review images, generated only when a destination is requested."""
import os
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage, QPainter

from onionwatch import theme
import test_ui
from test_card_layout import new_card

fake_screen, tab = test_ui.fake_screen, test_ui.tab
os.environ.setdefault("QT_QPA_FONTDIR", str(Path(os.environ.get("WINDIR", "C:/Windows"))
                                           / "Fonts"))


@pytest.mark.skipif(not os.environ.get("ONIONWATCH_CARD_REVIEW"), reason="review images opt-in")
@pytest.mark.parametrize("palette", ["Dark", "Light", "Retro 98"])
@pytest.mark.parametrize("advanced", [False, True])
@pytest.mark.parametrize("width", [300, 1100])
def test_render_cards(tab, qapp, palette, advanced, width):
    theme.apply(qapp, palette)
    for name, interval in (("Rare spawn", 50), ("Queue ready", 250), ("Health low", 500)):
        row = new_card(tab)
        picture = QImage(240, 100, QImage.Format_RGB32)
        picture.fill(QColor("#152e40"))
        painter = QPainter(picture)
        painter.setPen(QColor("#8ae1be"))
        painter.drawText(picture.rect(), Qt.AlignCenter, name.upper())
        painter.end()
        picture.save(row.t.images[0])
        row.refresh_pictures()
        row.name.setText(name)
        row._on_name()
        row.interval.setCurrentIndex(row.interval.findData(interval))
        row.set_open(False)
    tab.chk_advanced.setChecked(advanced)
    tab.resize(width, 800)
    tab.show()
    for _ in range(12):
        qapp.processEvents()
    tab.chk_advanced.setFocus()
    tab.scroll.verticalScrollBar().setValue(0)
    qapp.processEvents()
    assert tab.width() == width
    out = Path(os.environ["ONIONWATCH_CARD_REVIEW"])
    out.mkdir(parents=True, exist_ok=True)
    name = f"{palette}-{'advanced' if advanced else 'simple'}-{width}.png"
    assert tab.grab().save(str(out / name))
