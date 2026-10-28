"""A window resized while it's being copied: PrintWindow draws it at its new size into
the bitmap made for the old one, so that copy is the window shrunk into a corner (or
cut off), and a picture on it looks gone for one check: a "vanish" trigger went off
and an "appear" one fired again for a picture that never went away. Stand-in window
only: no real window is read."""
import numpy as np
import pytest

from onionwatch.engine import windows
from onionwatch.engine.screenwatch import WindowRef
from onionwatch.engine.windows import WindowInfo

W, H = 320, 180
GAME = WindowRef("game.exe", "Game", 0)


class FakeUser32:
    """One window; `shrink_in_copy` resizes it to half while PrintWindow copies it."""

    def __init__(self):
        self.size = (W, H)
        self.shrink_in_copy = False

    def IsWindow(self, _h):
        return True

    def IsIconic(self, _h):
        return False

    def GetForegroundWindow(self):
        return 0

    def IsHungAppWindow(self, _h):
        return False

    def SendMessageTimeoutW(self, *_a):
        return 1

    def PrintWindow(self, _h, dc, _flags):
        if self.shrink_in_copy:
            self.shrink_in_copy = False
            self.size = (W // 2, H // 2)
        w, h = self.size
        dc[..., :3] = 0
        dc[:h, :w, :3] = 200            # the window as it is now, from the corner
        return True


class FakeBitmap:
    def __init__(self, w, h):
        self.pixels = np.zeros((h, w, 4), np.uint8)
        self.dc = self.pixels

    def close(self):
        pass


@pytest.fixture
def user32(monkeypatch):
    u = FakeUser32()
    monkeypatch.setattr(windows, "_win", lambda: (u, None, None, None))
    monkeypatch.setattr(windows, "_Bitmap", FakeBitmap)
    monkeypatch.setattr(windows, "client_size", lambda _h: u.size)
    return u


def test_a_copy_taken_while_the_window_is_resized_is_thrown_away(user32):
    g = windows.WindowGrabber(GAME, W, H, info=WindowInfo(1, GAME.title, GAME.exe, 1, 0, W, H))
    first = g.grab()
    assert first is not None and float(first.min()) > 0.5     # all of it drawn
    user32.shrink_in_copy = True
    assert g.grab() is None             # not the half-drawn copy
    assert g.grab() is None and g.source == (W // 2, H // 2)  # the new size, made afresh
    again = g.grab()
    assert again is not None and float(again.min()) > 0.5
