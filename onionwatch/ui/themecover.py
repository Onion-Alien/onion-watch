"""A still of each window over it while the theme changes, faded in and out, with Hoot
in the middle (the style kit's cover: onionwatch/style/cover.py, Onion Board's too).

Restyling every widget takes a moment, and a frame painted part way through showed
the app half styled. So the main window and any window open over it (Settings) show
a picture of themselves, dimming with Hoot in the new theme's colours until the new
theme is in, then fade to it. A highlight colour change is a plain blend."""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QDialog, QMainWindow, QWidget

from onionwatch import theme
from onionwatch.style import bunnyfit
from onionwatch.style import cover as kit
from onionwatch.style.owl import H as OWL_H
from onionwatch.style.owl import W as OWL_W
from onionwatch.style.owl import draw_owl

HOOT_H = 96


def hoot(name: str, dpr: float = 1.0) -> QPixmap:
    """Hoot in theme `name`'s colours and outfit (before the switch has happened)."""
    w, h = round(HOOT_H * OWL_W / OWL_H), HOOT_H
    pm = QPixmap(round(w * dpr), round(h * dpr))
    pm.setDevicePixelRatio(dpr)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    draw_owl(p, QRectF(0, 0, w, h), 0.0, QColor(theme.tokens(name)["accent"]),
             look_y=0.4, outfit=bunnyfit.outfit(name))
    p.end()
    return pm


def windows() -> list[QWidget]:
    """The app's windows on screen: the main one and the dialogs open over it."""
    return [w for w in QApplication.topLevelWidgets()
            if isinstance(w, (QMainWindow, QDialog)) and kit.on_screen(w)]


def covered(name: str):
    """Covers over every window for a `with` block, in theme `name`'s colours."""
    def make(w: QWidget) -> kit.Cover:
        return kit.Cover(w, QColor(theme.tokens(name)["bg"]),
                         hoot(name, w.devicePixelRatioF() or 1.0))
    return kit.covered(windows(), make)


def blended():
    """A plain blend over every window for a `with` block (the highlight colour)."""
    return kit.covered(windows())
