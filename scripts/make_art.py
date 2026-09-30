"""Render Onion Watch's artwork from code, offscreen:

    python scripts/make_art.py        -> docs/art/

- hoot.png            Hoot on a transparent background (the README's header)
- avatar.png          800 x 800, Hoot on the brand gradient (a profile picture)
- social-preview.png  2560 x 1280, GitHub's social preview (Settings -> General ->
                      Social preview): big words, the real window, Hoot in the corner.
                      Built from docs/screenshots/main.png: run screenshots.py first.
"""
from __future__ import annotations

import math
import os
import sys
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ.setdefault("QT_QPA_FONTDIR", str(Path(os.environ.get("WINDIR", r"C:\Windows"))
                                            / "Fonts"))   # offscreen has no fonts otherwise
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QPointF, QRect, QRectF, Qt  # noqa: E402
from PySide6.QtGui import (QColor, QFont, QGuiApplication, QImage, QLinearGradient,  # noqa: E402
                           QPainter, QPainterPath, QPen, QRadialGradient)

from onionwatch import owl, theme  # noqa: E402

TEAL, BLUE, YELLOW, PINK = (QColor("#1fb6a6"), QColor("#2a6fdb"), QColor("#ffd23f"),
                            QColor("#ff5c8a"))


def painter(img: QImage) -> QPainter:
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.SmoothPixmapTransform)
    return p


def rays(p: QPainter, c: QPointF, size: float, n: int = 16):
    p.save()
    p.translate(c)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(255, 255, 255, 28))
    for k in range(n):
        a0, a1 = k * 2 * math.pi / n, (k + 0.5) * 2 * math.pi / n
        path = QPainterPath(QPointF(0, 0))
        path.lineTo(math.cos(a0) * size, math.sin(a0) * size)
        path.lineTo(math.cos(a1) * size, math.sin(a1) * size)
        path.closeSubpath()
        p.drawPath(path)
    p.restore()


def glow(p: QPainter, c: QPointF, r: float, col: QColor, alpha: float = 0.55):
    g = QRadialGradient(c, r)
    k = QColor(col)
    k.setAlphaF(alpha)
    g.setColorAt(0, k)
    g.setColorAt(1, QColor(0, 0, 0, 0))
    p.setPen(Qt.NoPen)
    p.setBrush(g)
    p.drawEllipse(c, r, r)


def avatar(s: int = 800) -> QImage:
    img = QImage(s, s, QImage.Format_ARGB32_Premultiplied)
    p = painter(img)
    g = QLinearGradient(0, 0, s, s)
    g.setColorAt(0, TEAL)
    g.setColorAt(1, BLUE)
    p.fillRect(0, 0, s, s, g)
    rays(p, QPointF(s / 2, s * 0.55), s)
    glow(p, QPointF(s / 2, s * 0.55), s * 0.42, QColor("#ffffff"))
    owl.draw_owl(p, QRectF(s * 0.17, s * 0.14, s * 0.66, s * 0.78), look=0.5)
    p.end()
    return img


def font(size: int, weight=QFont.Normal) -> QFont:
    f = QFont("Segoe UI")
    f.setWeight(weight)
    f.setPixelSize(size)
    return f


def outlined(p: QPainter, s: str, x: float, y: float, f: QFont, fill: QColor,
             stroke: float = 0.0) -> QRectF:
    path = QPainterPath()
    path.addText(x, y, f, s)
    if stroke:
        p.setPen(QPen(QColor("#06101a"), stroke, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.setBrush(Qt.NoBrush)
        p.drawPath(path)
    p.setPen(Qt.NoPen)
    p.setBrush(fill)
    p.drawPath(path)
    return path.boundingRect()


def social_preview(W: int = 2560, H: int = 1280) -> QImage:
    img = QImage(W, H, QImage.Format_ARGB32_Premultiplied)
    p = painter(img)
    g = QLinearGradient(0, 0, W, H)
    g.setColorAt(0, QColor("#07202a"))
    g.setColorAt(1, QColor("#0c1a3d"))
    p.fillRect(0, 0, W, H, g)
    for c, r, col, a in ((QPointF(620, 520), 900, TEAL, 0.30),
                         (QPointF(1950, 700), 1000, BLUE, 0.28)):
        glow(p, c, r, col, a)

    # the app, right side: a 1:1 crop of the main window
    shot = QImage(str(ROOT / "docs" / "screenshots" / "main.png"))
    if shot.isNull():
        raise SystemExit("docs/screenshots/main.png is missing: run scripts/screenshots.py")
    crop = shot.copy(QRect(0, 0, min(shot.width(), 900), min(shot.height(), 700)))
    k = 1.2
    frame = QRectF(1400, 230, crop.width() * k, crop.height() * k)
    p.save()
    p.translate(frame.center())
    p.rotate(-3)
    p.translate(-frame.center())
    for w, a in ((40, 0.12), (22, 0.22), (8, 0.5)):
        col = QColor(TEAL)
        col.setAlphaF(a)
        p.setPen(QPen(col, w))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(frame, 34, 34)
    clip = QPainterPath()
    clip.addRoundedRect(frame, 34, 34)
    p.setClipPath(clip)
    p.drawImage(frame, crop)
    p.restore()

    # words, left side
    x = 130
    p.drawPixmap(QPointF(x, 150), theme.app_icon().pixmap(200, 200))
    title = outlined(p, "Onion Watch", x - 6, 560, font(156, QFont.Black), QColor("#ffffff"), 12)
    outlined(p, "Plays a sound when your", x, 690, font(80, QFont.DemiBold), QColor("#cdeff0"))
    outlined(p, "game needs you", x, 790, font(84, QFont.Black), YELLOW)
    chips = [("Watches behind other windows", TEAL), ("Several accounts", BLUE),
             ("Rings until stopped", PINK)]
    f = font(34, QFont.Bold)
    p.setFont(f)
    fm = p.fontMetrics()
    cx, cy = x, 885
    for label, col in chips:
        w = fm.horizontalAdvance(label) + 52
        if cx + w > frame.left() - 60:
            cx, cy = x, cy + 96
        r = QRectF(cx, cy, w, 76)
        p.setPen(Qt.NoPen)
        p.setBrush(col)
        p.drawRoundedRect(r, 38, 38)
        p.setPen(QColor("#06101a") if col == TEAL else QColor("#ffffff"))
        p.drawText(r, Qt.AlignCenter, label)
        cx += w + 18
    outlined(p, "Windows · free · it only looks, never touches the game", x, cy + 190,
             font(44, QFont.DemiBold), QColor("#9fc3cc"))

    # Hoot, bottom right, over the window's corner
    bh = 440
    bw = bh * owl.W / owl.H
    owl.draw_owl(p, QRectF(W - bw - 70, H - bh - 40, bw, bh), look=-0.6)
    assert title.right() < frame.left() - 40, title
    p.end()
    return img


def main(out: Path):
    QGuiApplication([])
    out.mkdir(parents=True, exist_ok=True)
    owl.owl_image(360).save(str(out / "hoot.png"))
    avatar().save(str(out / "avatar.png"))
    social_preview().save(str(out / "social-preview.png"))
    print(f"saved to {out}")


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "docs" / "art")
