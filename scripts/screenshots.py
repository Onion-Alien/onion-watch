"""Render the README screenshots offscreen from made-up demo data: no window is
shown, no screen or window is captured, nothing is heard.

    python scripts/screenshots.py [out_dir]      (default: docs/screenshots)

The "game" is drawn here with QPainter (a made-up MMO called Realm Online), the
windows in the picker are invented, and the app folder is a throwaway one.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ.setdefault("QT_QPA_FONTDIR", str(Path(os.environ.get("WINDIR", r"C:\Windows"))
                                            / "Fonts"))   # offscreen has no fonts otherwise
os.environ["ONIONWATCH_HOME"] = tempfile.mkdtemp(prefix="onionwatch-shots-")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402
from PySide6.QtCore import QPointF, QRect, QRectF, Qt  # noqa: E402
from PySide6.QtGui import (QColor, QFont, QImage, QLinearGradient, QPainter,  # noqa: E402
                           QPainterPath, QPen, QRadialGradient)
from PySide6.QtWidgets import QApplication  # noqa: E402


class _Mute:
    """A stand-in audio stream: screenshots never make a sound."""

    def __init__(self, **_):
        pass

    def start(self):
        pass

    stop = close = abort = start


import sounddevice  # noqa: E402

sounddevice.OutputStream = _Mute


def game_scene(w: int, h: int, seed: int = 0, plate: str = "", banner: str = "",
               whisper: str = "") -> QImage:
    """A made-up fantasy MMO frame: sky, hills, a health bar, maybe a rare's name
    plate, a "queue ready" banner or a whisper in the chat."""
    rng = np.random.default_rng(seed)
    img = QImage(w, h, QImage.Format_ARGB32)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    sky = QLinearGradient(0, 0, 0, h)
    sky.setColorAt(0, QColor("#2b3a67"))
    sky.setColorAt(0.55, QColor("#c98b6b"))
    sky.setColorAt(1, QColor("#3f5a3a"))
    p.fillRect(0, 0, w, h, sky)
    for layer, col in enumerate(("#4a6b4a", "#35523a", "#243d2b")):
        path = QPainterPath(QPointF(0, h))
        base = h * (0.55 + 0.12 * layer)
        for x in range(0, w + 40, 40):
            path.lineTo(x, base - rng.uniform(0, h * 0.12))
        path.lineTo(w, h)
        p.fillPath(path, QColor(col))
    glow = QRadialGradient(QPointF(w * 0.78, h * 0.28), h * 0.18)
    glow.setColorAt(0, QColor(255, 230, 180, 220))
    glow.setColorAt(1, QColor(255, 230, 180, 0))
    p.fillRect(0, 0, w, h, glow)
    # the player's frame
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(0, 0, 0, 150))
    p.drawRoundedRect(QRectF(20, 20, 260, 58), 8, 8)
    p.setBrush(QColor("#c62828"))
    p.drawRoundedRect(QRectF(78, 32, 190, 14), 4, 4)
    p.setBrush(QColor("#1565c0"))
    p.drawRoundedRect(QRectF(78, 52, 150, 12), 4, 4)
    p.setBrush(QColor("#d7b377"))
    p.drawEllipse(QRectF(28, 26, 44, 44))
    # the action bar
    for i in range(10):
        x = w / 2 - 5 * 46 + i * 46
        p.setBrush(QColor(0, 0, 0, 160))
        p.drawRoundedRect(QRectF(x, h - 60, 40, 40), 6, 6)
        p.setBrush(QColor.fromHsv(int(rng.integers(0, 360)), 120, 190))
        p.drawRoundedRect(QRectF(x + 4, h - 56, 32, 32), 4, 4)
    if plate:
        f = QFont("Georgia", 15, QFont.Bold)
        p.setFont(f)
        r = QRectF(w * 0.36, h * 0.36, 300, 50)
        p.setBrush(QColor(0, 0, 0, 170))
        p.drawRoundedRect(r, 6, 6)
        p.setPen(QColor("#ffcc33"))
        p.drawText(r.adjusted(0, 2, 0, -18), Qt.AlignCenter, plate)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#c62828"))
        p.drawRoundedRect(QRectF(r.x() + 20, r.bottom() - 14, r.width() - 40, 7), 3, 3)
        p.setPen(QPen(QColor("#ffcc33"), 2))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(QRectF(r.x() + 4, r.y() + 4, 16, 16))
    if banner:
        f = QFont("Georgia", 22, QFont.Bold)
        p.setFont(f)
        r = QRectF(w / 2 - 230, h * 0.16, 460, 64)
        p.setPen(QPen(QColor("#e0c060"), 3))
        p.setBrush(QColor(20, 20, 40, 220))
        p.drawRoundedRect(r, 10, 10)
        p.setPen(QColor("#f5e6b0"))
        p.drawText(r, Qt.AlignCenter, banner)
    if whisper:
        f = QFont("Segoe UI", 12, QFont.Bold)
        p.setFont(f)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, 140))
        p.drawRoundedRect(QRectF(20, h - 150, 420, 34), 6, 6)
        p.setPen(QColor("#ff8ad8"))
        p.drawText(QRectF(30, h - 150, 400, 34), Qt.AlignVCenter | Qt.AlignLeft, whisper)
    p.end()
    return img


def cut(img: QImage, rect: QRect) -> QImage:
    return img.copy(rect)


def main(out: Path):
    out.mkdir(parents=True, exist_ok=True)
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    from onionwatch import screenwatch, settings, theme, windows
    from onionwatch.screenwatch import Monitor, Trigger, WindowRef
    from onionwatch.settings import Config
    from onionwatch.ui.mainwindow import MainWindow

    screenwatch.monitors = lambda: [Monitor(0, 0, 2560, 1440, True)]
    acct1 = WindowRef("realmonline.exe", "Realm Online", 0)
    acct2 = WindowRef("realmonline.exe", "Realm Online", 1)
    w, h = 1280, 720
    rare = game_scene(w, h, 3, plate="Gorehowl the Ancient")
    queue = game_scene(w, h, 5, banner="Dungeon queue ready!",
                       whisper="[Mira] whispers: you there?")

    cfg = Config()
    cfg.screen = {"on": False, "interval_ms": 100, "window": acct1.to_raw(), "triggers": []}
    pics = settings.APP_DIR / "triggers"
    pics.mkdir(parents=True, exist_ok=True)
    demo = [
        ("Rare spawn: Gorehowl", cut(rare, QRect(int(w * 0.36), int(h * 0.36), 300, 34)),
         acct2, ["builtin:alarm"], True, 0.85, 0.93),
        ("Dungeon queue", cut(queue, QRect(w // 2 - 230, int(h * 0.16), 460, 64)),
         None, ["builtin:rising", "builtin:chime"], False, 0.80, 0.41),
        ("Whisper", cut(queue, QRect(20, h - 150, 230, 34)), acct1, ["builtin:ping"], False,
         0.80, 0.22),
    ]
    triggers = []
    for i, (name, img, where, sounds, ring, thr, _score) in enumerate(demo):
        t = Trigger(id=f"demo{i}", name=name, sounds=sounds, ring=ring, threshold=thr,
                    window=where, cooldown=30.0 if ring else 5.0, pick="random")
        path = pics / f"{t.id}.png"
        img.save(str(path))
        t.images = [str(path)]
        triggers.append(t.to_raw())
    cfg.screen["triggers"] = triggers

    win = MainWindow(cfg)
    win.resize(900, 820)
    tab = win.triggers
    # watching, with live scores as the watcher would show them
    tab.btn_watch.blockSignals(True)
    tab.btn_watch.setChecked(True)
    tab.btn_watch.blockSignals(False)
    tab._label_watch()
    for (_n, _i, _w, _s, _r, _t, score), row in zip(demo, tab.rows.values()):
        row.show_score(score)
    first = next(iter(tab.rows.values()))
    # ringing, as the player would say: the bar asks the host what's ringing
    win.host.ringing = lambda: [first.t.id]
    win.alarm._on_fired(first.t)
    win.show()
    app.processEvents()
    win.grab().save(str(out / "main.png"))

    # the window picker, with invented windows
    shots = {101: game_scene(640, 360, 3), 102: game_scene(640, 360, 7, plate="Gorehowl"),
             103: game_scene(640, 360, 1)}
    wins = [windows.WindowInfo(101, "Realm Online", "realmonline.exe", 1, 100, 1920, 1080),
            windows.WindowInfo(102, "Realm Online", "realmonline.exe", 2, 200, 1920, 1080),
            windows.WindowInfo(104, "Discord", "discord.exe", 4, 50, 1400, 900),
            windows.WindowInfo(103, "Starfall Tactics", "starfall.exe", 3, 300, 2560, 1440)]

    def fake_snapshot(hwnd):
        img = shots.get(hwnd)
        if img is None:
            img = QImage(640, 400, QImage.Format_ARGB32)
            img.fill(QColor("#313338"))
        img = img.convertToFormat(QImage.Format_ARGB32)
        a = np.frombuffer(img.constBits(), np.uint8, count=img.sizeInBytes())
        return a.reshape(img.height(), img.bytesPerLine())[:, :img.width() * 4] \
            .reshape(img.height(), img.width(), 4).copy()
    windows.list_windows = lambda: list(wins)
    windows.snapshot = fake_snapshot
    from onionwatch.ui.windowpicker import WindowPicker
    dlg = WindowPicker(win, acct2)
    dlg.resize(760, 520)
    dlg.show()
    while dlg._pending:
        dlg._next_thumb()
    app.processEvents()
    dlg.grab().save(str(out / "window-picker.png"))
    dlg.close()

    # cutting a picture out of the game window
    from onionwatch.ui.snip import SnipDialog
    snip = SnipDialog(rare, "Realm Online (copy 2)", win)
    snip.view.selection = QRect(int(w * 0.36), int(h * 0.36), 300, 34)
    snip._update()
    snip.resize(900, 640)
    snip.show()
    app.processEvents()
    snip.grab().save(str(out / "cut-picture.png"))
    snip.close()

    # the icon
    theme.logo_pixmap(256).save(str(out / "icon.png"))
    win.quit()
    print(f"saved to {out}")


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "docs" / "screenshots")
