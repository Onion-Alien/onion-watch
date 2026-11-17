"""A picture found at another size has to match sharp at full size too ("any size",
RESIZED_SHARP). A "[bot] name" badge cut off a dark web page was found at 75 % of its
size on the page's file list, a row of "folder icon + name", at 0.92, and went off
every few seconds while the badge wasn't on screen at all. The page here is made up:
drawn with Qt, no screenshot. Drawn rows don't fool the soft match the way that page's
did (that took its exact pixels), so the check itself is tested on them, and the
whole watcher on the badge drawn afresh at other sizes: still found."""
from types import SimpleNamespace

import numpy as np
import pytest
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPen

from onionwatch.engine import screenwatch as sw
from onionwatch.engine import windows as wn
from onionwatch.engine.screenwatch import WindowRef
from onionwatch.ui.triggers.pictures import (cut_size, is_web, picture_of, picture_rgb,
                                             picture_tint, set_cut_size)

W, H = 1600, 900
BACK = QColor(13, 17, 23)
REF = WindowRef("browser.exe", "A page", 0)
NAMES = ["assets", "changelog.d", "docs", "installer", "licenses", "modules", "native",
         "packs", "scripts", "site", "soundboard", "streamdeck", "tests"]


@pytest.fixture(scope="module", autouse=True)
def qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def font(px: float, bold=False) -> QFont:
    f = QFont("Segoe UI")
    f.setPixelSize(max(1, round(px)))
    f.setBold(bold)
    return f


def draw_badge(p: QPainter, x: float, y: float, k: float = 1.0):
    """A round blue avatar and a bold name next to it, `k` times its size."""
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(31, 111, 235))
    p.drawEllipse(QRectF(x + 8 * k, y + 13 * k, 34 * k, 34 * k))
    p.setBrush(QColor(255, 255, 255))
    p.drawRoundedRect(QRectF(x + 16 * k, y + 22 * k, 18 * k, 12 * k), 3 * k, 3 * k)
    p.setPen(QColor(240, 246, 252))
    p.setFont(font(19 * k, True))
    p.drawText(QRectF(x + 52 * k, y, 200 * k, 60 * k), Qt.AlignVCenter | Qt.AlignLeft,
               "helperbot[bot]")


def badge() -> QImage:
    """The picture as cut: the badge on the page's dark background."""
    img = QImage(252, 60, QImage.Format_ARGB32)
    img.fill(BACK)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    draw_badge(p, 0, 0)
    p.end()
    set_cut_size(img, (W, H))
    return img


def page(badge_k: float | None = None) -> QImage:
    """A dark file list: rows of a grey folder icon and a white name. With
    `badge_k`, the badge drawn that much smaller or bigger off to the side."""
    img = QImage(W, H, QImage.Format_ARGB32)
    img.fill(BACK)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    for i, name in enumerate(NAMES):
        y = 120 + i * 52
        p.setPen(QPen(QColor(48, 54, 61), 1))
        p.drawLine(260, y, 1100, y)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(145, 152, 161))
        p.drawRoundedRect(QRectF(290, y + 17, 22, 18), 3, 3)
        p.drawRect(QRectF(290, y + 14, 10, 5))
        p.setPen(QColor(240, 246, 252))
        p.setFont(font(20))
        p.drawText(QRectF(330, y, 400, 52), Qt.AlignVCenter | Qt.AlignLeft, name)
    if badge_k is not None:
        draw_badge(p, 1200, 400, badge_k)
    p.end()
    return img


class Grab:
    """The window as WindowGrabber gives it: sampled small, and all of it in `full`."""
    want_color = False
    color = None
    cpu_elsewhere = 0.0
    lost = minimized = False

    def __init__(self, img: QImage):
        a = img.convertToFormat(QImage.Format_ARGB32)
        self.px = np.frombuffer(bytes(a.constBits()), np.uint8).reshape(
            a.height(), a.bytesPerLine() // 4, 4)[:, :a.width()].copy()
        self.source = (self.px.shape[1], self.px.shape[0])
        self.w = self.h = 0

    def resize(self, w, h):
        self.w, self.h = w, h
        wn.WindowGrabber._layout(self)

    def grab(self):
        self.full = self.px
        s = wn.pick(self.px, self.ys, self.xs)
        self.raw = (s, sw.FMT_BGRA8, self.factor)
        return sw.gray_2x(s) if self.factor == 2 else sw.to_gray(s)


def fires(scene: QImage, monkeypatch, checks=60) -> list:
    """What an "any size" trigger for the badge sets off in `scene` over `checks` checks."""
    now = [1000.0]
    monkeypatch.setattr(sw.time, "monotonic", lambda: now[0])
    pic = badge()
    it = sw.Watched("t", [picture_of(pic)], 0.8, 3.0, sources=[REF], any_size=True,
                    replay=True, cuts=[cut_size(pic)], wide=[is_web(pic)],
                    tints=[picture_tint(pic)], colours=[picture_rgb(pic)])
    hits: list = []
    watcher = sw.Watcher(lambda _tid, hit=None: hits.append(hit), hits=True)
    watcher.default = REF
    cap = sw._Capture(REF)
    cap.grab = Grab(scene)
    cap.fitted, cap.scaled = sw.Watcher._fit(cap.grab, None, [it])
    for _ in range(checks):
        now[0] += 0.5
        watcher._tick(cap, [it])
    return hits


def sharp_at(scene: QImage, box_full: tuple[int, int, int, int]) -> float:
    """Watcher._resized_sharp for the badge at `box_full` (x, y, w, h in the scene's
    own pixels), the frame matched on a third of the scene's size."""
    g = Grab(scene)
    full = sw.Watcher._full_size(SimpleNamespace(full=g.px, source=g.source))
    pic = badge().convertToFormat(QImage.Format_ARGB32)
    px = np.frombuffer(bytes(pic.constBits()), np.uint8).reshape(
        pic.height(), pic.bytesPerLine() // 4, 4)[:, :pic.width()]
    lk = SimpleNamespace(gray=sw.to_gray(px), mask=None)
    shape = (H // 3, W // 3)
    x, y, w, h = box_full
    box = (y // 3, (y + h) // 3, x // 3, (x + w) // 3)
    assert sw.Watcher._resized(full, box, lk, shape)
    return sw.Watcher._resized_sharp(full, box, lk, shape, {}, "t")


@pytest.mark.parametrize("row", [1, 4, 10])
def test_a_row_of_icon_and_name_fails_the_sharp_check(row):
    """The box a soft match at 75 % gave on a file list row: the badge isn't there."""
    y = 120 + row * 52
    assert sharp_at(page(), (285, y + 4, 189, 45)) < sw.RESIZED_SHARP


@pytest.mark.parametrize("k", [0.7, 0.8, 1.15, 1.3])
def test_the_badge_drawn_afresh_passes_the_sharp_check(k):
    """The badge laid out again at another size, in a box a sweep step too big."""
    box = (1200 - 6, 400 - 4, round(252 * k * 1.06) + 6, round(60 * k * 1.06) + 4)
    assert sharp_at(page(k), box) >= sw.RESIZED_SHARP


def test_a_page_of_rows_sets_nothing_off(monkeypatch):
    assert fires(page(), monkeypatch) == []


@pytest.mark.parametrize("k", [0.7, 0.8, 1.15, 1.3])
def test_the_badge_itself_is_still_found_at_another_size(monkeypatch, k):
    hits = fires(page(k), monkeypatch)
    assert hits, "the badge wasn't found"
    x, y, w, h = hits[0].box
    assert x * W > 1150 and abs(y * H - 400) < 60       # where the badge is, not a row
