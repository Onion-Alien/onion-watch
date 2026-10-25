"""A trigger's pictures on disk: cut, added from a file or pasted, the size each was
cut at (or that nobody knows it), saving, loading and deleting them, and their
thumbnails."""
from __future__ import annotations

import logging
import os
import uuid
from collections import OrderedDict
from pathlib import Path

import numpy as np
from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QImage, QPixmap
from PySide6.QtWidgets import QApplication

from onionwatch.engine import screenwatch
from onionwatch.engine.screenwatch import Picture, Trigger
from onionwatch.i18n import _
from onionwatch.ui.kit import theme

log = logging.getLogger(__name__)

PICTURE_EXTS = "*.png *.jpg *.jpeg *.bmp *.webp *.gif"
CUT_KEY = "OnionWatch cut from"   # a picture's PNG text: the size of what it was cut from
# ...and this one, set: it wasn't cut from the game (a file or a copy from the web), so
# the size it's drawn at is anyone's guess (see screenwatch.WIDE_SIZES)
WEB_KEY = "OnionWatch size unknown"
# such a picture is shrunk to fit within this share of what's watched each way when
# it's added (a picture from the web is often many times the size it's shown at)
WEB_FILL = 0.6
WEB_GUESS = (1920, 1080)          # ...what's watched, when that isn't known
THUMB = QSize(112, 64)   # an open card's pictures (card.THUMB_BIG on a wide card)


def hit_image(hit: screenwatch.Hit) -> QImage:
    """The frame a Hit was seen in, with its box drawn round what set it off."""
    from PySide6.QtGui import QPainter, QPen
    f = hit.frame
    if f is None or f.ndim < 2 or not f.size:
        return QImage()
    f = np.ascontiguousarray(f)
    h, w = f.shape[:2]
    if f.ndim == 3:
        img = QImage(f.data, w, h, w * 3, QImage.Format_RGB888).copy()
    else:
        img = QImage(f.data, w, h, w, QImage.Format_Grayscale8).copy()
    if w > screenwatch.LOG_PICTURE_W:       # kept small: 50 of them stay in memory
        img = img.scaledToWidth(screenwatch.LOG_PICTURE_W, Qt.SmoothTransformation)
        w, h = img.width(), img.height()
    img = img.convertToFormat(QImage.Format_RGB32)
    x, y, bw, bh = hit.box
    p = QPainter(img)
    p.setPen(QPen(QColor(theme.T.get("accent", "#1fb6a6")), 2))
    p.drawRect(round(x * w), round(y * h), max(2, round(bw * w)), max(2, round(bh * h)))
    p.end()
    return img


def pictures_dir(host) -> Path:
    """Where a host's trigger pictures are kept."""
    return Path(host.data_dir) / "triggers"


def load_picture(path: str) -> Picture | None:
    """A picture file as grey float32 0..1, plus which pixels count: the opaque ones
    (None when it has no transparency). Transparent parts are left out of matching."""
    return picture_of(QImage(path))


def picture_rgb(img: QImage) -> np.ndarray | None:
    """The picture's own colours, (h, w, 3) uint8 RGB: the watcher takes its colours
    in brief from them at the size it's matched at (screenwatch.tint_at)."""
    if img.isNull():
        return None
    img = img.convertToFormat(QImage.Format_ARGB32)
    h, w = img.height(), img.width()
    buf = np.frombuffer(img.constBits(), np.uint8, count=img.bytesPerLine() * h)
    return buf.reshape(h, img.bytesPerLine())[:, :w * 4].reshape(h, w, 4)[..., 2::-1].copy()


def picture_tint(img: QImage) -> np.ndarray | None:
    """The picture's colours in brief (screenwatch.tint), so a place matching it in
    grey but not in colour doesn't count."""
    if img.isNull():
        return None
    img = img.convertToFormat(QImage.Format_ARGB32)
    h, w = img.height(), img.width()
    buf = np.frombuffer(img.constBits(), np.uint8, count=img.bytesPerLine() * h)
    bgra = buf.reshape(h, img.bytesPerLine())[:, :w * 4].reshape(h, w, 4)
    rgb = bgra[..., 2::-1].astype(np.float32) * (1 / 255)
    mask = bgra[..., 3] >= 128
    return screenwatch.tint(rgb, None if mask.all() else mask)


def cut_size(img: QImage) -> tuple[int, int] | None:
    """The (w, h) of the window or screen a picture was cut from, kept in its PNG
    (see set_cut_size); None when it isn't known."""
    w, _x, h = img.text(CUT_KEY).partition("x")
    try:
        size = int(w), int(h)
    except ValueError:
        return None
    return size if 0 < min(size) and max(size) <= 65536 else None


def set_cut_size(img: QImage, size: tuple[int, int] | None):
    """Note in the picture (a text field of its PNG) the size of what it was cut from,
    so with "any size" it's looked for at the size the game draws it now."""
    if size and min(size) > 0:
        img.setText(CUT_KEY, f"{size[0]}x{size[1]}")


def is_web(img: QImage) -> bool:
    """The picture wasn't cut from the game (see WEB_KEY)."""
    return img.text(WEB_KEY) == "1"


def set_web(img: QImage):
    img.setText(WEB_KEY, "1")


def picture_file(path: str) -> QImage:
    """A picture file to look for. One Onion Watch didn't cut (it says nothing of the
    size it was cut from) counts as from the web: its size on screen is unknown."""
    img = QImage(path)
    if not img.isNull() and cut_size(img) is None:
        set_web(img)
    return img


def copied_picture() -> QImage:
    """The picture on the clipboard (null if none): a copied picture, or a picture
    file copied in Explorer. One copied from a browser or a file (the copy carries a
    link or a page snippet, where Win+Shift+S gives only the picture) counts as from
    the web, see picture_file."""
    mime = QApplication.clipboard().mimeData()
    img = QApplication.clipboard().image()
    if img.isNull():
        exts = {e[1:] for e in PICTURE_EXTS.split()}
        files = [u.toLocalFile() for u in (mime.urls() if mime is not None else [])
                 if u.isLocalFile() and Path(u.toLocalFile()).suffix.lower() in exts]
        return picture_file(files[0]) if files else img
    if mime is not None and (mime.hasHtml() or mime.hasUrls()) and cut_size(img) is None:
        set_web(img)
    return img


def fit_web(img: QImage, room: tuple[int, int] | None) -> QImage:
    """A picture from the web shrunk to fit within WEB_FILL of `room` (w, h) each way
    (WEB_GUESS when not known), its notes kept; as it is if it fits already."""
    rw, rh = room or WEB_GUESS
    f = min(WEB_FILL * rw / max(img.width(), 1), WEB_FILL * rh / max(img.height(), 1))
    if f >= 1:
        return img
    out = img.scaled(max(6, round(img.width() * f)), max(6, round(img.height() * f)),
                     Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
    for key in img.textKeys():
        out.setText(key, img.text(key))
    return out


def picture_of(img: QImage) -> Picture | None:
    """load_picture() for a picture already in memory."""
    if img.isNull():
        return None
    img = img.convertToFormat(QImage.Format_ARGB32)   # B, G, R, A in memory
    h, w = img.height(), img.width()
    buf = np.frombuffer(img.constBits(), np.uint8, count=img.bytesPerLine() * h)
    bgra = buf.reshape(h, img.bytesPerLine())[:, :w * 4].reshape(h, w, 4)
    mask = bgra[..., 3] >= 128
    return screenwatch.to_gray(bgra), (None if mask.all() else mask)


def with_alpha(img: QImage, keep: np.ndarray) -> QImage:
    """`img` with only `keep` (a (h, w) bool mask of its size) left opaque."""
    out = img.convertToFormat(QImage.Format_ARGB32)
    for key in img.textKeys():
        out.setText(key, img.text(key))
    h, w = out.height(), out.width()
    buf = np.frombuffer(out.bits(), np.uint8, count=out.bytesPerLine() * h)
    buf.reshape(h, out.bytesPerLine())[:, :w * 4].reshape(h, w, 4)[..., 3] = \
        np.where(keep, 255, 0).astype(np.uint8)
    return out


def save_picture(img: QImage, name: str, folder: Path) -> str:
    """Keep a copy of the picture as <folder>/<name>.png; returns its path. It's kept
    pixel for pixel: resized, it would no longer match the screen it was cut from.
    Written beside it first, so a failed save leaves the old picture as it was."""
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{name}.png"
    tmp = folder / f"{name}.saving"
    if not img.save(str(tmp), "PNG"):
        tmp.unlink(missing_ok=True)
        raise OSError(_("couldn't save the picture to {path}", path=path))
    os.replace(tmp, path)
    return str(path)


def picture_name(t: Trigger, folder: Path) -> str:
    """A file name (without .png) for a picture being added to `t`: <id> for the
    first, as older versions saved it, then <id>-<random> so removing and adding
    pictures never reuses a name."""
    if not t.images and not (folder / f"{t.id}.png").exists():
        return t.id
    return f"{t.id}-{uuid.uuid4().hex[:6]}"


def _num(v) -> float:
    """A number from the saved settings, whatever was written there (0 if not one)."""
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else 0.0


def delete_picture(path: str, folder: Path):
    """Remove a picture file this tab keeps in `folder` (never one the user pointed at)."""
    if path and Path(path).parent == folder:
        try:
            Path(path).unlink(missing_ok=True)
        except OSError:
            log.debug("couldn't delete %s", path, exc_info=True)


def flatness(gray: np.ndarray, mask: np.ndarray | None = None) -> float:
    """How much detail there is to recognise (the opaque part's spread of greys)."""
    px = gray if mask is None else gray[mask]
    return float(px.std()) if px.size >= 16 else 0.0


def picture_filter() -> str:
    """A file dialog's filter for the pictures it can add."""
    return _("Pictures") + f" ({PICTURE_EXTS});;" + _("All files") + " (*)"


THUMB_CACHE = 400       # thumbnails kept, so a card is made (or opened) without
_thumbs: OrderedDict = OrderedDict()    # ...reading its pictures from disk again


def thumb_pixmap(path: str, size: QSize) -> QPixmap:
    """`path`'s thumbnail, `size` at most (a null one if it can't be read). Kept for
    next time, under the file's time and length: a picture changed on disk is read
    again."""
    try:
        st = os.stat(path) if path else None
    except OSError:
        st = None
    if st is None:
        return QPixmap()
    key = (path, st.st_mtime_ns, st.st_size, size.width(), size.height())
    pm = _thumbs.get(key)
    if pm is not None:
        _thumbs.move_to_end(key)
        return pm
    from onionwatch.ui.triggers.viewer import read_image
    pm = QPixmap.fromImage(read_image(path, THUMB))
    if pm.isNull():
        return pm               # not kept: it may be readable in a moment
    pm = pm.scaled(size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    _thumbs[key] = pm
    while len(_thumbs) > THUMB_CACHE:
        _thumbs.popitem(last=False)
    return pm
