"""Render the README screenshots offscreen from made-up demo data: no window is
shown, no screen or window is captured, nothing is heard.

    python scripts/screenshots.py [out_dir] [--theme NAME]   (default: docs/screenshots)

Onion Board's website uses copies of the same (Dark) pictures.

The "game" is game_scene.svg (the website demo's scene) with a made-up HUD on top, the
windows in the picker are invented, and the app folder is a throwaway one.
"""
from __future__ import annotations

import os
import re
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
from PySide6.QtCore import QByteArray, QRect, QRectF, Qt  # noqa: E402
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPen  # noqa: E402
from PySide6.QtSvg import QSvgRenderer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402


THEME = "Dark"   # the README and both websites use this theme, like Onion Board's pictures


class _Mute:
    """A stand-in audio stream: screenshots never make a sound."""

    def __init__(self, **_):
        pass

    def start(self):
        pass

    stop = close = abort = start


import sounddevice  # noqa: E402

sounddevice.OutputStream = _Mute


HP_BAR = QRectF(78, 32, 190, 14)     # the player's health bar in game_scene



def fill_view(dlg, app):
    """Widen a cutting dialog until its picture fills the view: the dialog has a
    minimum height, and a 900-wide one would show grey bands above and below."""
    dlg.resize(900, 1)
    app.processEvents()
    v = dlg.view
    fit = v.img.size().scaled(v.size(), Qt.KeepAspectRatio)
    extra = round((v.height() - fit.height()) * v.img.width() / v.img.height())
    if extra > 0:
        dlg.resize(dlg.width() + extra, dlg.height())

SCENE = Path(__file__).with_name("game_scene.svg").read_text(encoding="utf-8")
PLATE = QRectF(150, 44, 160, 30)     # the name plate, in game_scene.svg's own units
SLOTS = ("#7c5cff", "#ff5c8a", "#ffcf40", "#4fc3b0", "#ffd45e", "#5a7dff")


def scene_rect(w: int, h: int, r: QRectF = PLATE) -> QRect:
    """Where a part of game_scene.svg lands in a w x h frame (it fills the frame,
    centred, cropping the sides like the website does)."""
    s = max(w / 460, h / 200)
    x0, y0 = (w - 460 * s) / 2, (h - 200 * s) / 2
    return QRect(round(x0 + r.x() * s), round(y0 + r.y() * s),
                 round(r.width() * s), round(r.height() * s))


def banner_rect(w: int, h: int) -> QRect:
    return QRect(w // 2 - 230, int(h * 0.05), 460, 64)


def game_scene(w: int, h: int, seed: int = 0, plate: str = "", banner: str = "",
               whisper: str = "", hp: float = 1.0) -> QImage:
    """A made-up fantasy game frame: the website demo's dusk scene (castle, arch,
    a little knight), a health bar (`hp` full), and maybe a rare one out of the arch
    with its name on the plate, a "queue ready" banner or a whisper in the chat."""
    rng = np.random.default_rng(seed)
    svg = SCENE.replace('<g class="knight">',
                        f'<g class="knight" transform="translate({rng.uniform(-25, 45):.0f} 0)">')
    if plate:
        svg = re.sub(r'<g class="runes".*?</g>', "", svg)
    else:
        svg = re.sub(r'\n  <g class="rare">.*?\n  </g>', "", svg, flags=re.S)
    img = QImage(w, h, QImage.Format_ARGB32)
    img.fill(QColor("#140f33"))
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.TextAntialiasing)
    whole = QRectF(scene_rect(w, h, QRectF(0, 0, 460, 200)))
    QSvgRenderer(QByteArray(svg.encode())).render(p, whole)
    frame, edge = QColor(16, 11, 34, 185), QPen(QColor("#6f5fa0"), 1.5)
    # the player's frame
    p.setPen(edge)
    p.setBrush(frame)
    p.drawRoundedRect(QRectF(20, 20, 260, 58), 8, 8)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor("#3a1414"))
    p.drawRoundedRect(HP_BAR, 4, 4)
    p.setBrush(QColor("#c62828"))
    p.drawRoundedRect(QRectF(HP_BAR.x(), HP_BAR.y(), HP_BAR.width() * hp, HP_BAR.height()),
                      4, 4)
    p.setBrush(QColor("#5a7dff"))
    p.drawRoundedRect(QRectF(78, 52, 150, 12), 4, 4)
    p.setPen(QPen(QColor("#2b2340"), 2))
    p.setBrush(QColor("#c9cede"))
    p.drawEllipse(QRectF(28, 26, 44, 44))
    # the action bar
    for i in range(10):
        x = w / 2 - 5 * 46 + i * 46
        p.setPen(edge)
        p.setBrush(frame)
        p.drawRoundedRect(QRectF(x, h - 60, 40, 40), 6, 6)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(SLOTS[int(rng.integers(0, len(SLOTS)))]))
        p.drawRoundedRect(QRectF(x + 5, h - 55, 30, 30), 4, 4)
    if plate:
        r = QRectF(scene_rect(w, h))
        f = QFont("Georgia")
        f.setBold(True)
        f.setPixelSize(max(10, round(r.height() * 0.42)))
        p.setFont(f)
        p.setPen(QColor("#ffcc33"))
        p.drawText(r, Qt.AlignCenter, plate)
    if banner:
        f = QFont("Georgia", 22, QFont.Bold)
        p.setFont(f)
        r = QRectF(banner_rect(w, h))
        p.setPen(QPen(QColor("#ffcf40"), 3))
        p.setBrush(QColor(16, 11, 34, 225))
        p.drawRoundedRect(r, 10, 10)
        p.setPen(QColor("#fff3d1"))
        p.drawText(r, Qt.AlignCenter, banner)
    if whisper:
        f = QFont("Segoe UI", 12, QFont.Bold)
        p.setFont(f)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, 150))
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
    from onionwatch.engine import screenwatch, windows
    from onionwatch.core import settings
    from onionwatch.ui.kit import theme
    from onionwatch.engine.screenwatch import Monitor, Trigger, WindowRef
    from onionwatch.core.settings import Config
    from onionwatch.ui.window.mainwindow import MainWindow

    screenwatch.monitors = lambda: [Monitor(0, 0, 2560, 1440, True)]
    acct1 = WindowRef("realmonline.exe", "Realm Online", 0)
    acct2 = WindowRef("realmonline.exe", "Realm Online", 1)
    w, h = 1280, 720
    rare = game_scene(w, h, 3, plate="Gorehowl the Ancient")
    queue = game_scene(w, h, 5, banner="Dungeon queue ready!",
                       whisper="[Mira] whispers: you there?")

    cfg = Config(theme=THEME)
    cfg.screen = {"on": False, "interval_ms": 100, "window": acct1.to_raw(), "triggers": []}
    pics = settings.APP_DIR / "triggers"
    pics.mkdir(parents=True, exist_ok=True)
    every = WindowRef(acct1.exe, acct1.title, 0, True)
    bar = (HP_BAR.x() / w, HP_BAR.y() / h, HP_BAR.width() / w, HP_BAR.height() / h)
    demo = [
        ("Rare spawn: Gorehowl", cut(rare, scene_rect(w, h)),
         [every], ["builtin:alarm"], True, 0.85, 0.93, {}),
        ("Health low", None, [acct1], ["builtin:bell"], True, 0.30, 0.64,
         {"mode": "colour", "colour": "#c62828", "region": bar, "hold": 1.0}),
        ("Dungeon queue", cut(queue, banner_rect(w, h)),
         [], ["builtin:rising", "builtin:chime"], True, 0.80, 0.41, {"stop": "focus"}),
        ("Whisper", cut(queue, QRect(20, h - 150, 230, 34)), [acct1, acct2], ["builtin:ping"],
         False, 0.80, 0.22, {}),
    ]
    triggers = []
    for i, (name, img, where, sounds, ring, thr, _score, extra) in enumerate(demo):
        t = Trigger(id=f"demo{i}", name=name, sounds=sounds, ring=ring, sources=where,
                    cooldown=30.0 if ring else 5.0, pick="random", **extra)
        if t.uses_pictures:
            t.threshold = thr
            path = pics / f"{t.id}.png"
            img.save(str(path))
            t.images = [str(path)]
        else:
            t.level = thr
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
    for (*_x, score, _e), row in zip(demo, tab.rows.values()):
        row.show_score(score)
    queue = list(tab.rows.values())[2]
    queue.set_open(True)                # one card open, to show what's in one
    # no trigger ringing: the alarm bar is red in every theme and would drown it out
    win.show()
    for _ in range(3):      # rows that wrap settle their height over a few passes
        app.processEvents()
    win.grab().save(str(out / "main.png"))

    # Audit the real layout at compact widths and with advanced controls visible.
    # All data remains synthetic, including the pictures in the expanded card.
    for width, height, name, advanced in (
            (1200, 900, "wide", True), (600, 900, "compact", False),
            (360, 900, "narrow", True)):
        queue.btn_tune.setChecked(advanced)
        win.resize(width, height)
        for _ in range(12):
            app.processEvents()
        tab.scroll.ensureWidgetVisible(queue)
        app.processEvents()
        win.grab().save(str(out / f"{name}.png"))
    queue.btn_tune.setChecked(False)
    win.resize(900, 820)
    for _ in range(12):
        app.processEvents()

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
    from onionwatch.ui.triggers.windowpicker import WindowPicker
    from onionwatch.engine import screenwatch
    screenwatch.monitors = lambda: [Monitor(0, 0, 1920, 1080, True)]   # not this PC's
    dlg = WindowPicker(win, [every], multi=True)
    dlg.list.setCurrentRow(1)
    dlg.resize(760, 560)
    dlg.show()
    while dlg._pending:
        dlg._next_thumb()
    app.processEvents()
    dlg.grab().save(str(out / "window-picker.png"))
    dlg.close()

    # cutting a picture out of the game window
    from onionwatch.ui.triggers.snip import SnipDialog
    snip = SnipDialog(rare, "Realm Online (copy 2)", win)
    snip.view.selection = scene_rect(w, h)
    snip._update()
    snip.show()
    fill_view(snip, app)
    app.processEvents()
    snip.grab().save(str(out / "cut-picture.png"))
    snip.close()

    # the health bar a colour trigger measures
    from onionwatch.ui.triggers.snip import AreaDialog
    hurt = game_scene(w, h, 3, hp=0.55)
    area = AreaDialog(hurt, "Realm Online", bar, "#c62828", win)
    area.show()
    fill_view(area, app)
    app.processEvents()
    area.grab().save(str(out / "health-bar.png"))
    area.close()

    # a bigger library in categories, a profile turned on by the game being open
    from onionwatch.engine import profiles
    win.host.ringing = lambda: []
    win.alarm.hide()
    tab.set_watching(False, remember=False)
    for name in ("Raid bosses", "Dungeons and queues", "Rare spawns", "Fishing"):
        tab.new_category(name)
    # each category's own colour and picture (the pictures drawn here: an emoji each)
    from onionwatch.ui.triggers import categories as catui

    def emoji_picture(ch: str) -> str:
        img = QImage(128, 128, QImage.Format_ARGB32)
        img.fill(Qt.transparent)
        p = QPainter(img)
        p.setFont(QFont("Segoe UI Emoji", 64))
        p.drawText(QRect(0, 0, 128, 128), Qt.AlignCenter, ch)
        p.end()
        return catui.save_picture(img, tab.host.data_dir)

    tab.set_category_looks({
        "Raid bosses": {"color": "#d9675e", "image": emoji_picture("🐉")},
        "Dungeons and queues": {"color": "#5a90d6", "image": emoji_picture("🏰")},
        "Rare spawns": {"color": "#dcc060", "image": emoji_picture("💎")},
        "Fishing": {"color": "#3fb3a5", "image": emoji_picture("🎣")}})
    moves = {"demo0": "Rare spawns", "demo1": "Raid bosses", "demo2": "Dungeons and queues"}
    for t in list(tab.triggers):
        if t.id in moves:
            tab.move_trigger(t, moves[t.id])
    extra = [("Raid bosses", "Boss ability", 11), ("Dungeons and queues", "Ready check", 5),
             ("Rare spawns", "Rare spawn", 37), ("Fishing", "Bobber", 120)]
    for cat, name, n in extra:
        open_ = cat == "Dungeons and queues"     # (folded categories' cards aren't made)
        for k in range(n):
            tab.triggers.append(Trigger(id=f"{cat[:4]}{k}", name=f"{name} {k + 1}",
                                        sounds=["builtin:chime"], category=cat,
                                        enabled=k % 4 != 3, mode="change" if open_ else "appear",
                                        images=[] if open_ else ["x.png"]))
    tab.groups.find("Fishing").on = False
    raids = profiles.new_profile("Realm Online raids")
    raids.categories = ["Raid bosses", "Dungeons and queues", ""]
    raids.apps = ["realmonline.exe"]
    tab._lister = lambda: list(wins)      # the invented windows: the game is open
    tab._front = lambda: 104
    tab.profilectl.set_profiles([raids])
    tab.profilectl.set_profile(profiles.AUTO)
    for c in tab.groups.categories:
        c.open = c.name == "Dungeons and queues"
    tab._drop_section("Dungeons and queues")
    tab._layout_sections()
    for row in tab.rows.values():
        row.set_open(False)
    win.resize(1040, 640)
    app.processEvents()
    for _ in range(3):
        app.processEvents()
    win.grab().save(str(out / "categories.png"))
    tab.show_search()
    tab.search_text.setText("Ready check 3")
    for _ in range(12):
        app.processEvents()
    win.grab().save(str(out / "search-global.png"))
    tab.search_text.clear()
    tab.show_search("Dungeons and queues")
    tab.search_text.setText("Ready")
    for _ in range(12):
        app.processEvents()
    win.grab().save(str(out / "search-category.png"))
    win.resize(360, 900)
    for _ in range(12):
        app.processEvents()
    win.grab().save(str(out / "search-narrow.png"))

    # the icon
    theme.logo_pixmap(256).save(str(out / "icon.png"))
    win.quit()
    empty = MainWindow(Config(theme=THEME))
    empty.resize(860, 720)
    empty.show()
    for _ in range(12):
        app.processEvents()
    empty.grab().save(str(out / "empty.png"))
    empty.quit()
    print(f"saved to {out}")


if __name__ == "__main__":
    args = sys.argv[1:]
    if "--theme" in args:
        i = args.index("--theme")
        THEME = args[i + 1]
        del args[i:i + 2]
    main(Path(args[0]) if args else ROOT / "docs" / "screenshots")
