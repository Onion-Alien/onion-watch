"""The start-up splash (ui/splash.py): Hoot's frames draw at any screen scale, and
off Windows (the tests' offscreen platform) show() puts nothing up."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPainter

from onionwatch import theme
from onionwatch.ui import splash


def test_frames_draw_at_any_scale(qapp):
    for k in (1.0, 1.25, 2.0):
        img = QImage(round(splash.CARD_W * k), round(splash.CARD_H * k),
                     QImage.Format_ARGB32_Premultiplied)
        img.fill(Qt.transparent)
        p = QPainter(img)
        p.scale(k, k)
        splash.paint_frame(p, 0.3, splash.CARD_W, splash.CARD_H, k)
        p.end()
        assert img.pixelColor(0, 0).alpha() == 0   # no card behind him
        assert any(img.pixelColor(x, img.height() // 2).alpha() == 255
                   for x in range(img.width()))   # Hoot is in there, solid
    splash.close()
    assert not splash._sprites


def test_show_follows_the_saved_theme(qapp, tmp_path, monkeypatch):
    (tmp_path / "config.json").write_text('{"theme": "Lava"}', encoding="utf-8")
    monkeypatch.setattr(splash.settings, "APP_DIR", tmp_path)
    try:
        assert splash.show() is None   # offscreen: nothing to show
        assert theme.current_name == "Lava"
    finally:
        splash.close()
        theme.set_current(theme.DEFAULT)
