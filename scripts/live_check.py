"""The real thing, end to end, on this PC: real windows, real PrintWindow capture,
the real watcher, the Triggers tab as Onion Board loads it (onionwatch.board on a
stand-in board that records what it plays). No fakes between the window and the
match.

It starts two copies of a stand-in "game" (this script with --game, separate
processes like two game clients, same program and title), and a third window that
covers the second copy. Then:

  1. cuts the banner out of copy 2's window (Cut from window…) and makes a trigger
     that watches copy 2 ("copy 2" of that program and title);
  2. shows the banner in copy 1 only: the trigger must stay quiet;
  3. shows it in copy 2, while it's covered: the trigger must play its sound
     through the host;
  4. closes copy 2: the card must say it's waiting for the window to open.

The windows appear for a few seconds at the top left of the main screen and never
take the keyboard focus. Nothing is saved outside a temp folder.

Usage: .venv\\Scripts\\python scripts\\live_check.py      (exits 0 and prints PASS)
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TITLE = "Onion Watch Live Check Game"
W, H = 640, 360
BANNER = (200, 150, 240, 56)        # x, y, w, h of the "rare spawn" plate in the game


def game(ctrl: str, x: int, y: int, cover: bool = False) -> int:
    """A stand-in game window: a busy, fixed background, and the rare-spawn plate
    while the control file says "banner". With `cover`, just a plain window on top."""
    from PySide6.QtCore import QRect, Qt, QTimer
    from PySide6.QtGui import QColor, QFont, QPainter
    from PySide6.QtWidgets import QApplication, QWidget

    app = QApplication(sys.argv)

    class Game(QWidget):
        def __init__(self):
            super().__init__()
            self.show_banner = False
            self.setWindowTitle("Covering window" if cover else TITLE)
            self.setAttribute(Qt.WA_ShowWithoutActivating)
            self.setWindowFlag(Qt.WindowDoesNotAcceptFocus)
            if cover:   # a window shown without taking the focus isn't always put on top
                self.setWindowFlag(Qt.WindowStaysOnTopHint)
            self.setFixedSize(W + 120 if cover else W, H + 120 if cover else H)
            self.move(x, y)
            t = QTimer(self)
            t.timeout.connect(self.check)
            t.start(50)

        def check(self):
            try:
                want = Path(ctrl).read_text().strip() == "banner"
            except OSError:
                want = False
            if want != self.show_banner:
                self.show_banner = want
                self.update()

        def paintEvent(self, _e):
            p = QPainter(self)
            if cover:
                p.fillRect(self.rect(), QColor("#3a3f4b"))
                p.setPen(QColor("white"))
                p.drawText(self.rect(), Qt.AlignCenter, "another window on top")
                return
            for i in range(0, W, 16):               # a busy, fixed "game world"
                for j in range(0, H, 16):
                    v = (i * 7 + j * 13) % 97
                    p.fillRect(i, j, 16, 16, QColor(20 + v, 60 + v // 2, 40 + (v * 3) % 90))
            if self.show_banner:
                bx, by, bw, bh = BANNER
                p.fillRect(bx, by, bw, bh, QColor("#1b1b1b"))
                p.setPen(QColor("#ffcc33"))
                p.setFont(QFont("Segoe UI", 16, QFont.Bold))
                p.drawText(QRect(bx, by, bw, bh), Qt.AlignCenter, "RARE: Gorehowl")

    g = Game()
    g.show()
    return app.exec()


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="onionwatch-live-"))
    os.environ["ONIONWATCH_HOME"] = str(tmp / "home")
    sys.path.insert(0, str(ROOT))
    sys.path.insert(0, str(ROOT / "tests"))      # the stand-in board (fakehost)
    procs = []
    ctrl1, ctrl2 = tmp / "copy1.txt", tmp / "copy2.txt"
    for c in (ctrl1, ctrl2):
        c.write_text("none")

    # the base Python with this one's paths: a venv's python.exe is a launcher that
    # runs the real one as a child, and the window would belong to that child
    env = dict(os.environ, PYTHONPATH=os.pathsep.join(p for p in sys.path if p))

    def start(*args):
        p = subprocess.Popen([getattr(sys, "_base_executable", sys.executable), __file__,
                              "--game", *map(str, args)], env=env)
        procs.append(p)
        return p

    ok = False
    try:
        start(ctrl1, 40, 40)
        time.sleep(1.0)                  # copy 1 starts first: that's how copies are told apart
        copy2 = start(ctrl2, 120, 90)
        time.sleep(1.0)
        start(tmp / "none.txt", 100, 70, "cover")   # on top of copy 2
        time.sleep(1.5)

        from PySide6.QtWidgets import QApplication
        app = QApplication([])
        from fakehost import FakeHost

        from onionwatch import board, windows
        from onionwatch import screenwatch as sw
        from onionwatch.screenwatch import WindowRef

        def spin(until, timeout=10.0):
            end = time.monotonic() + timeout
            while not until() and time.monotonic() < end:
                app.processEvents()
                time.sleep(0.02)
            return until()

        wins = [w for w in windows.list_windows() if w.title == TITLE]
        print(f"windows found: {len(wins)} copies of {TITLE!r} ({wins[0].exe if wins else '-'})")
        assert len(wins) == 2, "both copies should be listed"
        ref = WindowRef(wins[0].exe, TITLE, 1)
        info2 = windows.find(ref)
        assert info2 is not None and info2.pid == copy2.pid, "copy 2 is the second one started"

        # copy 2 really is covered: what's on screen at its middle belongs to another window
        import ctypes
        from ctypes import wintypes
        u = ctypes.windll.user32
        u.WindowFromPoint.restype = wintypes.HWND
        r = wintypes.RECT()
        u.GetWindowRect(wintypes.HWND(info2.hwnd), ctypes.byref(r))
        on_top = u.WindowFromPoint(wintypes.POINT((r.left + r.right) // 2,
                                                  (r.top + r.bottom) // 2))
        covered = int(on_top or 0) != info2.hwnd
        print(f"copy 2 covered by another window: {covered}")
        assert covered

        # 1. cut the banner out of copy 2 (shown for a moment), as "Cut from window…" does
        host = FakeHost(tmp / "board")
        tab = board.create(host)
        panel = tab.panel
        ctrl2.write_text("banner")
        time.sleep(0.4)
        px = windows.snapshot(info2.hwnd)
        assert px is not None, "copy 2 could be copied"
        from onionwatch.ui.windowpicker import bgra_image
        bx, by, bw, bh = BANNER
        piece = bgra_image(px).copy(bx - 6, by - 6, bw + 12, bh + 12)
        ctrl2.write_text("none")
        panel._new(piece, "Rare spawn")
        t = panel.triggers[0]
        t.window, t.sounds = ref, ["s1"]
        panel.rows[t.id].set_screens(panel._mons)
        panel._store()
        print(f"trigger: watches {ref.label}, {len(t.images)} picture cut from the window")

        panel.watcher.interval = 0.05
        panel.set_watching(True)
        assert spin(lambda: t.id in panel.watcher.scores), "watching copy 2"
        time.sleep(0.5)
        quiet = panel.watcher.scores.get(t.id, 0)
        print(f"match with nothing showing: {quiet:.0%}")

        # 2. the banner in copy 1 only: must stay quiet
        ctrl1.write_text("banner")
        time.sleep(1.5)
        app.processEvents()
        print(f"banner in copy 1 -> played: {host.played} (should be nothing), "
              f"copy 2 match {panel.watcher.scores.get(t.id, 0):.0%}")
        assert host.played == [], "copy 1's banner must not set off copy 2's trigger"

        # 3. the banner in copy 2, still covered: must play
        t0 = time.monotonic()
        ctrl2.write_text("banner")
        assert spin(lambda: host.played, 5.0), "copy 2's banner should play the sound"
        took = time.monotonic() - t0
        print(f"banner in covered copy 2 -> played {host.played} after {took:.2f} s, "
              f"match {panel.watcher.scores.get(t.id, 0):.0%}")
        assert host.played == [("s1", False, t.id)]

        # 4. copy 2 closes: the card says it's waiting for it
        copy2.kill()
        row = panel.rows[t.id]
        assert spin(lambda: row.state.text().startswith("Waiting for"), 10.0), row.state.text()
        print(f"copy 2 closed -> card says: {row.state.text()!r}")
        panel.set_watching(False)
        tab.shutdown()
        _ = sw
        ok = True
    finally:
        for p in procs:
            p.kill()
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--game":
        a = sys.argv[2:]
        sys.exit(game(a[0], int(a[1]), int(a[2]), cover=len(a) > 3))
    sys.exit(main())
