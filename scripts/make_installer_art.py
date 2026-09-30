"""Draw the build's icon and the installer's pictures from code, offscreen
(build.ps1 runs this; the outputs are build files, not committed):

- build/onionwatch.ico                 the exe's and setup's icon (16 to 256 px)
- installer/wizard-{1,2}x.bmp          the setup wizard's side panel: Hoot on the
                                       brand gradient
- installer/wizard-small-{1,2}x.bmp    the small logo at the top right of its pages

    python scripts/make_installer_art.py
"""
from __future__ import annotations

import os
import struct
import sys
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QPointF, QRectF, Qt  # noqa: E402
from PySide6.QtGui import (QColor, QGuiApplication, QImage, QLinearGradient,  # noqa: E402
                           QPainter)

from onionwatch import owl, theme  # noqa: E402

ICON_SIZES = (16, 24, 32, 48, 64, 128, 256)


def png_bytes(img: QImage) -> bytes:
    data = QByteArray()
    buf = QBuffer(data)
    buf.open(QIODevice.WriteOnly)
    img.save(buf, "PNG")
    return bytes(data)


def write_ico(path: Path) -> None:
    """A Windows .ico holding one PNG per size (Vista and later read those)."""
    pngs = [png_bytes(theme.logo_image(s)) for s in ICON_SIZES]
    head = struct.pack("<HHH", 0, 1, len(pngs))
    offset = len(head) + 16 * len(pngs)
    entries, blobs = b"", b""
    for size, png in zip(ICON_SIZES, pngs):
        wh = 0 if size >= 256 else size
        entries += struct.pack("<BBBBHHII", wh, wh, 0, 0, 1, 32, len(png), offset)
        blobs += png
        offset += len(png)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(head + entries + blobs)


def gradient(p: QPainter, w: int, h: int) -> None:
    g = QLinearGradient(QPointF(0, 0), QPointF(w, h))
    g.setColorAt(0, QColor(theme.BRAND[0]))
    g.setColorAt(1, QColor(theme.BRAND[1]))
    p.fillRect(0, 0, w, h, g)


def side_panel(scale: int) -> QImage:
    """Inno Setup's WizardImageFile: 164 x 314 at 100 %."""
    w, h = 164 * scale, 314 * scale
    img = QImage(w, h, QImage.Format_RGB888)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    gradient(p, w, h)
    hoot = owl.owl_image(int(h * 0.42))
    p.drawImage(QPointF((w - hoot.width()) / 2, h * 0.36), hoot)
    logo = theme.logo_image(int(w * 0.42))
    p.drawImage(QPointF((w - logo.width()) / 2, h * 0.08), logo)
    p.end()
    return img


def small_logo(scale: int) -> QImage:
    """Inno Setup's WizardSmallImageFile: 55 x 55 at 100 %, on white like the page."""
    s = 55 * scale
    img = QImage(s, s, QImage.Format_RGB888)
    img.fill(Qt.white)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    logo = theme.logo_image(s)
    p.drawImage(QRectF(0, 0, s, s), logo)
    p.end()
    return img


def main() -> int:
    _app = QGuiApplication(sys.argv)   # noqa: F841 - painting needs it
    write_ico(ROOT / "build" / "onionwatch.ico")
    out = ROOT / "installer"
    out.mkdir(exist_ok=True)
    for scale in (1, 2):
        side_panel(scale).save(str(out / f"wizard-{scale}x.bmp"), "BMP")
        small_logo(scale).save(str(out / f"wizard-small-{scale}x.bmp"), "BMP")
    print("wrote build/onionwatch.ico and installer/wizard*.bmp")
    return 0


if __name__ == "__main__":
    sys.exit(main())
