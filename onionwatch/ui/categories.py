"""The triggers page's categories and profiles (the rules are onionwatch.profiles):
a category's section in the list (a header to fold it, switch it on or off and
open its menu, over its trigger cards), the Categories window (each one's colours
and picture) and the Profiles window."""
from __future__ import annotations

import uuid
from pathlib import Path

from PySide6.QtCore import QPoint, QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import (QColor, QIcon, QImage, QLinearGradient, QPainter, QPainterPath,
                           QPixmap)
from PySide6.QtWidgets import (QColorDialog, QComboBox, QDialog, QDialogButtonBox,
                               QFileDialog, QFrame, QHBoxLayout, QLabel,
                               QLineEdit, QListWidget, QListWidgetItem, QMenu, QPushButton,
                               QVBoxLayout, QWidget, QWidgetItem, QSizePolicy)

from onionwatch import profiles, theme
from onionwatch.profiles import Category, Profile
from onionwatch.ui import fit, icons
from onionwatch.ui.panel import Flow, hint_label, section_label
from onionwatch.i18n import _, ngettext

NAME = Qt.UserRole              # a list item's category name / profile id / exe
TILE = 320                      # px: the least a closed card (a tile in the grid) is wide
SMALL_TILE = 210                # ...when a number of cards to a line is asked for
MAX_PER_ROW = 6                 # the most cards to a line that can be asked for
PICTURE_PX = 128                # a category's picture is kept at most this big
HEADER_PICTURE = 26             # px: ...and shown this big in its header
BANNER_PX = 2400                # a banner is kept at most this wide (and 800 high)
BANNER_HEIGHT_NAMES = {"slim": _("Slim"), "medium": _("Medium"), "tall": _("Tall")}
# the colours to pick from in one click (any other through "Other…"): soft ones
SWATCHES = ("#d9675e", "#e0915a", "#dcc060", "#6fae6c", "#3fb3a5", "#5a90d6",
            "#7176c8", "#9a6ccb", "#cf6d98", "#a07f66", "#7d8c99", "#5b6270")
TEXT_SWATCHES = ("#f4f6f8", "#1b1e24", "#f2d98a", "#f5b98a", "#9fdcd3", "#f2a8c4")
# a tab fades from this much of its colour (over the panel's) to this much
TINT_FROM = 0.55
TINT_TO = 0.06


def mix(color: str, base: str, amount: float) -> str:
    """`amount` of `color` over `base` ("#rrggbb" both), as "#rrggbb"."""
    a, b = QColor(color), QColor(base)
    return QColor(round(a.red() * amount + b.red() * (1 - amount)),
                  round(a.green() * amount + b.green() * (1 - amount)),
                  round(a.blue() * amount + b.blue() * (1 - amount))).name()


def _panel() -> str:
    return theme.T.get("panel", "#1e2430")


def tab_css(color: str, selector: str = "QFrame#transport") -> str:
    """A category tab's background: its colour, softened, fading into the panel's
    from left to right ("" for none: the theme's plain panel)."""
    if not color:
        return ""
    a, b = mix(color, _panel(), TINT_FROM), mix(color, _panel(), TINT_TO)
    return (f"{selector} {{ border-radius:12px; background:qlineargradient(x1:0, y1:0,"
            f" x2:1, y2:0, stop:0 {a}, stop:0.55 {mix(color, _panel(), 0.22)},"
            f" stop:1 {b}); }}")


def fade_color(c: Category | None) -> str:
    """What a banner fades into at the header's ends: where the tab's colour is
    strongest (the panel's, with none), so ink() reads the same over it."""
    return mix(c.color, _panel(), TINT_FROM) if c is not None and c.color else _panel()


def ink(c: Category | None) -> str:
    """The colour a category's name is drawn in ("": the theme's): the one picked,
    else (with a colour) black or white, whichever reads best where the name is."""
    if c is None or not (c.text_color or c.color):
        return ""
    if c.text_color:
        return c.text_color
    return profiles.readable_on(mix(c.color, _panel(), TINT_FROM))


# ---------------------------------------------------------------------- pictures
def pictures_dir(data_dir) -> Path:
    """Where categories' pictures are kept (a host's data_dir / "categories")."""
    return Path(data_dir) / "categories"


def save_picture(img: QImage, data_dir) -> str:
    """Keep `img` as a category picture (at most PICTURE_PX): its name, "" if it
    couldn't be saved."""
    if img.isNull():
        return ""
    if max(img.width(), img.height()) > PICTURE_PX:
        img = img.scaled(PICTURE_PX, PICTURE_PX, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    folder = pictures_dir(data_dir)
    try:
        folder.mkdir(parents=True, exist_ok=True)
    except OSError:
        return ""
    name = f"{uuid.uuid4().hex[:12]}.png"
    return name if img.save(str(folder / name), "PNG") else ""


def save_banner(img: QImage, data_dir) -> str:
    """Keep `img` as a category banner (at most BANNER_PX wide): its name, "" if it
    couldn't be saved."""
    if img.isNull():
        return ""
    if img.width() > BANNER_PX or img.height() > BANNER_PX // 3:
        img = img.scaled(BANNER_PX, BANNER_PX // 3, Qt.KeepAspectRatio,
                         Qt.SmoothTransformation)
    folder = pictures_dir(data_dir)
    try:
        folder.mkdir(parents=True, exist_ok=True)
    except OSError:
        return ""
    name = f"{uuid.uuid4().hex[:12]}.png"
    return name if img.save(str(folder / name), "PNG") else ""


def banner_image(c: Category | None, data_dir) -> QImage | None:
    """A category's banner picture (None: none, or its file is gone)."""
    name = profiles.clean_picture(c.banner) if c is not None else ""
    if not name or not data_dir:
        return None
    img = QImage(str(pictures_dir(data_dir) / name))
    return None if img.isNull() else img


def cover_rect(img: QSize, box: QSize, x: float, y: float) -> QRectF:
    """Where to draw a picture of size `img` so it covers `box`, keeping its point
    (x, y) (fractions) in view as far as it can: the rest is cut off."""
    k = max(box.width() / max(1, img.width()), box.height() / max(1, img.height()))
    w, h = img.width() * k, img.height() * k
    return QRectF(-(w - box.width()) * x, -(h - box.height()) * y, w, h)


class BannerFrame(QFrame):
    """A category header's strip (QFrame#transport, so its colour comes from
    tab_css): with a banner, the picture across the whole of it, faded into the tab
    colour at both ends so the name and switch stay readable. `draggable`: dragging
    it moves which part shows (moved(x, y), the Categories window's preview)."""
    moved = Signal(float, float)

    def __init__(self, draggable: bool = False):
        super().__init__()
        self.setObjectName("transport")
        self.img: QImage | None = None
        self.x = self.y = 0.5
        self.fade = _panel()
        self.draggable = draggable
        self._scaled: tuple[QSize, QPixmap] | None = None
        self._drag: tuple[QPoint, float, float] | None = None

    def set_banner(self, img: QImage | None, x: float = 0.5, y: float = 0.5,
                   height: str = "", fade: str = ""):
        self.img, self.x, self.y = img, x, y
        self.fade = fade or _panel()
        self._scaled = None
        h = profiles.BANNER_HEIGHTS.get(height or profiles.DEFAULT_BANNER_HEIGHT)
        if img is not None:
            self.setMinimumHeight(h)
            self.setMaximumHeight(h)
        else:
            self.setMinimumHeight(0)
            self.setMaximumHeight(16777215)
        if self.draggable:
            self.setCursor(Qt.OpenHandCursor if img is not None else Qt.ArrowCursor)
            self.setToolTip(_("Drag the picture to pick the part that shows")
                            if img is not None else "")
        self.update()

    def _pixmap(self, rect: QRectF) -> QPixmap:
        """The picture scaled to `rect`'s size (kept while the size stays)."""
        size = QSize(round(rect.width()), round(rect.height()))
        if self._scaled is None or self._scaled[0] != size:
            self._scaled = (size, QPixmap.fromImage(self.img.scaled(
                size, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)))
        return self._scaled[1]

    def paintEvent(self, e):
        super().paintEvent(e)
        if self.img is None:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        clip = QPainterPath()
        clip.addRoundedRect(QRectF(self.rect()), 12, 12)
        p.setClipPath(clip)
        r = cover_rect(self.img.size(), self.size(), self.x, self.y)
        p.drawPixmap(r.topLeft(), self._pixmap(r))
        # the ends fade into the tab's colour: the name on the left, the counts,
        # switch and buttons on the right stay readable over any picture
        g = QLinearGradient(0, 0, self.width(), 0)
        c = QColor(self.fade)
        for at, alpha in ((0.0, 225), (0.3, 120), (0.5, 0), (0.62, 0), (0.8, 150),
                          (1.0, 225)):
            c.setAlpha(alpha)
            g.setColorAt(at, c)
        p.fillRect(self.rect(), g)
        p.end()

    def mousePressEvent(self, e):
        if self.draggable and self.img is not None and e.button() == Qt.LeftButton:
            self._drag = (e.position().toPoint(), self.x, self.y)
            self.setCursor(Qt.ClosedHandCursor)
            return
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self._drag is None:
            return super().mouseMoveEvent(e)
        start, x0, y0 = self._drag
        d = e.position().toPoint() - start
        r = cover_rect(self.img.size(), self.size(), x0, y0)
        spare_w, spare_h = r.width() - self.width(), r.height() - self.height()
        # the picture follows the mouse: dragging it right shows more of its left
        x = min(1.0, max(0.0, x0 - d.x() / spare_w)) if spare_w > 0.5 else x0
        y = min(1.0, max(0.0, y0 - d.y() / spare_h)) if spare_h > 0.5 else y0
        if (x, y) != (self.x, self.y):
            self.x, self.y = x, y
            self.update()
            self.moved.emit(x, y)

    def mouseReleaseEvent(self, e):
        if self._drag is not None:
            self._drag = None
            self.setCursor(Qt.OpenHandCursor)
            return
        super().mouseReleaseEvent(e)


def picture_pixmap(name: str, data_dir, size: int) -> QPixmap | None:
    """A category's picture, `size` px square with round corners (None: none / gone)."""
    name = profiles.clean_picture(name)
    img = QImage(str(pictures_dir(data_dir) / name)) if name and data_dir else QImage()
    if img.isNull():
        return None
    img = img.scaled(size, size, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
    x, y = (img.width() - size) // 2, (img.height() - size) // 2
    out = QPixmap(size, size)
    out.fill(Qt.transparent)
    p = QPainter(out)
    p.setRenderHint(QPainter.Antialiasing)
    path = QPainterPath()
    path.addRoundedRect(0, 0, size, size, size * 0.2, size * 0.2)
    p.setClipPath(path)
    p.drawImage(0, 0, img, x, y, size, size)
    p.end()
    return out


def look_icon(c: Category, data_dir, size: int = 20) -> QIcon:
    """A small mark of a category's look for lists: its picture, else its colour
    (an empty icon when it has neither)."""
    pm = picture_pixmap(c.image, data_dir, size)
    if pm is None:
        pm = QPixmap(size, size)
        pm.fill(Qt.transparent)
        if c.color:
            p = QPainter(pm)
            p.setRenderHint(QPainter.Antialiasing)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(mix(c.color, _panel(), 0.8)))
            p.drawRoundedRect(2, 2, size - 4, size - 4, 4, 4)
            p.end()
    return QIcon(pm)


def _height(item, w: int) -> int:
    """How tall `item` is at width `w` (its height there, not at its preferred width)."""
    h = item.heightForWidth(w) if item.hasHeightForWidth() else -1
    return max(h if h >= 0 else item.sizeHint().height(), item.minimumSize().height())


class CardGrid(Flow):
    """A category's cards as tiles, as many to a line as fit (like the sound pads):
    a closed card is a tile, all of a line as tall as its tallest. An open card,
    and anything else in it (the "empty" note), has a line of its own, the whole
    width, under the line it would have been on: the closed cards after it fill that
    line first, so no line is cut short (like a picture grid opening a preview).
    `per_row` cards to a line when it's set (as long as they'd still be readable),
    else as many as fit at their usual width."""
    per_row = 0

    def __init__(self, parent=None, gap: int = 6):
        super().__init__(parent, gap)
        # each card's height at a width, and the whole grid's: worked out once, not
        # each of the several times a layout pass asks. Forgotten whenever anything
        # in it changes (a card's size or contents, one added or taken away)
        self._tall: dict[tuple[int, int], int] = {}
        self._grid_tall: dict[int, int] = {}

    def _forget(self):
        if hasattr(self, "_tall"):      # (QLayout's own __init__ invalidates)
            self._tall.clear()
            self._grid_tall.clear()

    def invalidate(self):
        self._forget()
        super().invalidate()

    def addItem(self, item):
        self._forget()
        super().addItem(item)

    def takeAt(self, i):
        self._forget()
        return super().takeAt(i)

    def heightForWidth(self, w):
        h = self._grid_tall.get(w)
        if h is None:
            h = self._grid_tall[w] = super().heightForWidth(w)
        return h

    def _height(self, item, w: int) -> int:
        key = (id(item), w)
        h = self._tall.get(key)
        if h is None:
            h = self._tall[key] = _height(item, w)
        return h

    def insertWidget(self, i: int, w: QWidget):
        self.addChildWidget(w)
        self._items.insert(max(0, min(i, len(self._items))), QWidgetItem(w))
        self.invalidate()

    def columns(self, width: int) -> int:
        if self.per_row:
            return max(1, min(self.per_row, (width + self._gap) // (SMALL_TILE + self._gap)))
        return max(1, (width + self._gap) // (TILE + self._gap))

    def set_per_row(self, n: int):
        if n != self.per_row:
            self.per_row = n
            self.invalidate()

    def _place(self, rect: QRect, move: bool) -> int:
        cols = self.columns(rect.width())
        cw = max(1, (rect.width() - self._gap * (cols - 1)) // cols)
        y, line, under = rect.y(), [], []   # under: open cards waiting for the line to fill

        def put(items, w):
            nonlocal y
            h = max(self._height(it, w) for it in items)
            if move:
                for k, it in enumerate(items):
                    it.setGeometry(QRect(rect.x() + k * (w + self._gap), y, w, h))
            y += h + self._gap

        def end_line():
            nonlocal line, under
            if line:
                put(line, cw)
            for it in under:
                put([it], rect.width())
            line, under = [], []

        for it in self._items:
            if it.isEmpty():
                continue
            if getattr(it.widget(), "is_open", True):     # a line of its own
                if line:
                    under.append(it)
                else:
                    put([it], rect.width())
            else:
                line.append(it)
                if len(line) == cols:
                    end_line()
        end_line()
        return max(0, y - self._gap - rect.y())


class CategorySection(QWidget):
    """One category in the list: its header (fold, name, counts, switch, ⋯) and the
    cards under it. The cards are only made once it's opened (TriggersTab), so a
    library of hundreds opens quickly. When it's the only category the header is
    hidden and it stays open: the list looks as it did before categories."""
    fold_toggled = Signal(str, bool)     # name, open
    switched = Signal(str, bool)         # name, on (its switch was clicked)
    menu_wanted = Signal(str)            # name: the ⋯ button
    add_wanted = Signal(str)             # name: the + button (a new trigger in it)
    search_wanted = Signal(str)
    card_dropped = Signal(str, str, object)  # trigger id, this category, before which id
    drag_at = Signal(QPoint)             # a card is being dragged here (global position)
    MIME = "application/x-onionwatch-trigger"   # (TriggerRow.MIME)
    FOLD_CSS = "text-align:left; font-weight:700; font-size:10.5pt; padding-left:2px;"

    def __init__(self, name: str):
        super().__init__()
        self.ink = ""                   # its name's colour ("": the theme's)
        self._tip = ""                  # what clicking its name does (_show_tip)
        self._data_dir = None
        self.look: Category | None = None
        from onionwatch.ui.triggerspanel import FlowBox, Switch   # (it imports this one)
        self.name = name
        self.built = False              # its cards have been made
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(6)
        self.header = BannerFrame()   # a panel-coloured strip, like the bar (QFrame#transport)
        header_layout = QHBoxLayout(self.header)
        header_layout.setContentsMargins(8, 6, 10, 6)
        h = header_layout
        h.setSpacing(10)
        self.pic = QLabel()                 # the category's picture, if it has one
        self.pic.setFixedSize(HEADER_PICTURE, HEADER_PICTURE)
        self.pic.setCursor(Qt.PointingHandCursor)
        self.pic.mousePressEvent = lambda _e: self.btn_fold.click()
        self.pic.hide()
        h.addWidget(self.pic)
        self.btn_fold = QPushButton()
        self.btn_fold.setObjectName("fold")
        self.btn_fold.setCheckable(True)
        self.btn_fold.setCursor(Qt.PointingHandCursor)
        self.btn_fold.setStyleSheet(self.FOLD_CSS)
        self.btn_fold.toggled.connect(self._on_fold)
        self.btn_fold.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        fold_resized = self.btn_fold.resizeEvent

        def on_fold_resized(ev):            # its name refitted to its new width
            fold_resized(ev)
            self._fit_name()
        self.btn_fold.resizeEvent = on_fold_resized
        h.addWidget(self.btn_fold, 1)
        self.count = hint_label("")
        self.count.setWordWrap(False)
        h.addWidget(self.count)
        from onionwatch.ui.triggerspanel import align_control
        self.switch = Switch()
        self.switch.clicked.connect(lambda on: self.switched.emit(self.name, on))
        h.addWidget(self.switch)
        self.btn_add = QPushButton()
        self.btn_add.setObjectName("small")
        icons.set_icon(self.btn_add, "plus")
        self.btn_add.setAccessibleName(_("New trigger in this category"))
        self.btn_add.setToolTip(_("A new trigger in this category"))
        self.btn_add.clicked.connect(lambda: self.add_wanted.emit(self.name))
        align_control(self.btn_add)
        h.addWidget(self.btn_add)
        self.btn_menu = QPushButton("⋯")
        self.btn_menu.setObjectName("small")
        self.btn_menu.setStyleSheet("font-size:11pt; padding:0 10px;")
        self.btn_menu.setAccessibleName(_("Category menu"))
        self.btn_menu.setToolTip(_("A new trigger here, rename, colours and picture, turn its "
                                   "triggers on or off, save it to a file…"))
        self.btn_menu.clicked.connect(lambda: self.menu_wanted.emit(self.name))
        align_control(self.btn_menu)
        h.addWidget(self.btn_menu)
        v.addWidget(self.header)
        self.body = FlowBox(gap=8, flow_type=CardGrid)
        self.body_layout = self.body.flow
        self.empty = hint_label(_("No triggers in this category yet. Click + to make one here, "
                                  "drag one in, or pick it with Category, under a trigger's "
                                  "More options."))
        self.body_layout.addWidget(self.empty)
        v.addWidget(self.body)
        # where a dragged card would land: a line in the accent colour
        self.drop_line = QFrame(self)
        self.drop_line.setObjectName("dropline")
        self.drop_line.setStyleSheet("QFrame#dropline { background: palette(highlight);"
                                     " border-radius: 2px; }")
        self.drop_line.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.drop_line.hide()
        self.setAcceptDrops(True)
        self.set_name(name)
        self.set_open(False)

    # ------------------------------------------------------------------ dropping cards
    def _cards(self) -> list[QWidget]:
        """Its cards as laid out, in order (the ones a search hides left out)."""
        out = []
        for i in range(self.body_layout.count()):
            w = self.body_layout.itemAt(i).widget()
            if w is not None and w is not self.empty and not w.isHidden():
                out.append(w)
        return out

    def drop_spot(self, pos: QPoint) -> tuple[str | None, QRect]:
        """Where a card dropped at `pos` (in this section) goes: before which card
        (its trigger's id; None: after the last), and the line that shows it."""
        cards = self._cards() if self.body.isVisible() else []
        if not cards or not self.body.geometry().adjusted(0, -6, 0, 6).contains(pos):
            r = self.header.geometry() if self.header.isVisible() else self.body.geometry()
            if cards:
                last = cards[-1].geometry().translated(self.body.pos())
                return None, QRect(last.right() + 2, last.top(), 3, last.height())
            return None, QRect(r.left(), r.bottom() - 1, r.width(), 3)
        p = pos - self.body.pos()

        def dist(w):
            g = w.geometry()
            dx = max(g.left() - p.x(), 0, p.x() - g.right())
            dy = max(g.top() - p.y(), 0, p.y() - g.bottom())
            return dx * dx + dy * dy
        near = min(cards, key=dist)
        g = near.geometry()
        whole_line = getattr(near, "is_open", False)    # an open card: above / below
        after = p.y() > g.center().y() if whole_line else p.x() > g.center().x()
        i = cards.index(near) + (1 if after else 0)
        before = cards[i] if i < len(cards) else None
        if whole_line:
            y = g.bottom() + 3 if after else g.top() - 5
            line = QRect(g.left(), y, g.width(), 3)
        else:
            x = g.right() + 2 if after else g.left() - 5
            line = QRect(x, g.top(), 3, g.height())
        tid = getattr(getattr(before, "t", None), "id", None)
        return tid, line.translated(self.body.pos())

    def _dragged(self, ev) -> str | None:
        data = ev.mimeData()
        return bytes(data.data(self.MIME)).decode() if data.hasFormat(self.MIME) else None

    def dragEnterEvent(self, ev):
        if self._dragged(ev) is None:
            ev.ignore()
            return
        ev.acceptProposedAction()
        self.dragMoveEvent(ev)

    def dragMoveEvent(self, ev):
        if self._dragged(ev) is None:
            ev.ignore()
            return
        ev.acceptProposedAction()
        _before, line = self.drop_spot(ev.position().toPoint())
        self.drop_line.setGeometry(line)
        self.drop_line.show()
        self.drop_line.raise_()
        self.drag_at.emit(self.mapToGlobal(ev.position().toPoint()))

    def dragLeaveEvent(self, ev):
        self.drop_line.hide()
        super().dragLeaveEvent(ev)

    def dropEvent(self, ev):
        self.drop_line.hide()
        tid = self._dragged(ev)
        if tid is None:
            ev.ignore()
            return
        ev.acceptProposedAction()
        before, _line = self.drop_spot(ev.position().toPoint())
        self.card_dropped.emit(tid, self.name, before)

    @property
    def is_open(self) -> bool:
        return self.btn_fold.isChecked()

    NARROW = 420    # px: a header this narrow (the list beside the editor) drops its +

    def resizeEvent(self, event):
        super().resizeEvent(event)
        narrow = self.width() < self.NARROW
        self.count.setVisible(self.width() >= 600)
        # (a new trigger here is in the ⋯ menu too)
        self.btn_add.setVisible(not narrow)
        self.header.layout().setSpacing(6 if narrow else 10)
        self._fit_name()

    def set_name(self, name: str):
        self.name = name
        self.btn_fold.setAccessibleName(_("Category {label}", label=profiles.label(name)))
        self._fit_name()

    def _fit_name(self):
        """Its name, cut short with an … rather than clipped mid-letter when the
        header is narrow (the whole of it, and the counts, in the tooltip)."""
        full = profiles.label(self.name)
        room = self.btn_fold.width() - self.btn_fold.iconSize().width() - 16
        text = self.btn_fold.fontMetrics().elidedText(full, Qt.ElideRight, max(room, 40))
        if self.btn_fold.text() != text:
            self.btn_fold.setText(text)

    def set_open(self, on: bool):
        if self.btn_fold.isChecked() != on:
            self.btn_fold.blockSignals(True)
            self.btn_fold.setChecked(on)
            self.btn_fold.blockSignals(False)
        tint = self.ink or "muted"
        icons.set_icon(self.btn_fold, "fold_open" if on else "fold", tint, tint, size=16)
        self._tip = _("Fold this category away") if on else _("Show this category's triggers")
        self._show_tip()
        self.body.setVisible(on)

    def _on_fold(self, on: bool):
        self.set_open(on)
        self.fold_toggled.emit(self.name, on)

    def set_switch(self, on: bool, tip: str):
        self.switch.setChecked(on)
        self.switch.setToolTip(tip)

    def set_look(self, c: Category | None, data_dir=None):
        """Show category `c`'s look: its header's colour, its name's colour and its
        picture (None: the theme's plain look)."""
        self.look = c
        self.ink = ink(c)
        self.header.setStyleSheet(tab_css(c.color if c else ""))
        self.btn_fold.setStyleSheet(self.FOLD_CSS + (f" color:{self.ink};" if self.ink else ""))
        self.set_open(self.is_open)         # the fold arrow in the name's colour
        pm = picture_pixmap(c.image, data_dir, HEADER_PICTURE) if c else None
        self.pic.setPixmap(pm or QPixmap())
        self.pic.setVisible(pm is not None)
        self._data_dir = data_dir
        self._show_banner()

    def _show_banner(self):
        c = self.look
        img = banner_image(c, self._data_dir)
        self.header.set_banner(img, c.banner_x if c else 0.5, c.banner_y if c else 0.5,
                               c.banner_height if c else "", fade_color(c))

    def retheme(self):
        """The theme changed: its tab fades into the new panel colour."""
        if self.look is not None:
            self.header.setStyleSheet(tab_css(self.look.color))
            self._show_banner()

    def _show_tip(self):
        """The fold's tooltip: what a click does, and (the counts can be hidden) its
        name and numbers."""
        counts = self.count.text()
        self.btn_fold.setToolTip(profiles.label(self.name)
                                 + (f": {counts}" if counts else "") + f"\n{self._tip}")

    def set_counts(self, text: str, tone: str = ""):
        self.count.setText(text)
        self._show_tip()
        self.count.setProperty("tone", tone or None)
        self.count.style().unpolish(self.count)
        self.count.style().polish(self.count)

    def set_header_visible(self, on: bool):
        self.header.setVisible(on)

    def cards(self) -> int:
        """How many cards are in it (the empty note aside)."""
        return self.body_layout.count() - 1


def counts_text(n: int, on: int, pictures: int, cat_on: bool) -> str:
    """A category header's numbers: "12 triggers · 9 on · 14 pictures"."""
    if not n:
        return _("empty") if cat_on else _("empty · off")
    triggers = ngettext("{n} trigger", "{n} triggers", n)
    if not cat_on:
        return _("{triggers} · off", triggers=triggers)
    return _("{triggers} · {on} on · {pictures}", triggers=triggers, on=on,
             pictures=ngettext("{n} picture", "{n} pictures", pictures))


class ProfilesDialog(QDialog):
    """Make and change profiles: a name, the categories it turns on, and the
    programs (exe names, from the open windows or typed) that turn it on by itself
    when Profile is set to Automatic. Works on copies: `result_profiles` once
    accepted."""

    def __init__(self, parent, profile_list: list[Profile], categories: list[str],
                 lister=None, start: str = ""):
        super().__init__(parent)
        fit.watch(self)          # grows to fit its (translated) text
        self.setWindowTitle(_("Profiles"))
        self.resize(720, 600)
        self.profiles = [p.copy() for p in profile_list]
        self.categories = categories
        self._lister = lister
        self._loading = False
        v = QVBoxLayout(self)
        v.addWidget(hint_label(
            _("A profile is a set of categories to have on. Pick one by hand under Profile, or "
              "set Profile to Automatic: a profile then turns on while one of its programs has a "
              "window open (or is the window in front), and your own switches apply while none "
              "does.")))
        h = QHBoxLayout()
        left = QVBoxLayout()
        self.list = QListWidget()
        self.list.currentRowChanged.connect(self._show)
        left.addWidget(self.list, 1)
        lb = QHBoxLayout()
        self.btn_new = QPushButton(_("New"))
        icons.set_icon(self.btn_new, "plus", size=14)
        self.btn_new.clicked.connect(self._new)
        self.btn_delete = QPushButton(_("Delete"))
        icons.set_icon(self.btn_delete, "trash", size=14)
        self.btn_delete.clicked.connect(self._delete)
        lb.addWidget(self.btn_new)
        lb.addWidget(self.btn_delete)
        left.addLayout(lb)
        h.addLayout(left, 2)

        self.form = QWidget()
        f = QVBoxLayout(self.form)
        f.setContentsMargins(0, 0, 0, 0)
        f.addWidget(section_label(_("NAME")))
        self.name = QLineEdit()
        self.name.setMaxLength(profiles.NAME_MAX)
        self.name.textEdited.connect(self._on_name)
        f.addWidget(self.name)
        f.addWidget(section_label(_("CATEGORIES IT TURNS ON")))
        self.cats = QListWidget()
        self.cats.setMinimumHeight(140)
        self.cats.itemChanged.connect(self._on_cat)
        f.addWidget(self.cats, 2)
        f.addWidget(section_label(_("ON BY ITSELF (AUTOMATIC) WHILE")))
        wh = QHBoxLayout()
        self.when = QComboBox()
        self.when.addItem(_("one of these programs has a window open"), "running")
        self.when.addItem(_("one of these programs is the window in front"), "front")
        self.when.activated.connect(self._on_when)
        wh.addWidget(self.when, 1)
        f.addLayout(wh)
        self.apps = QListWidget()
        self.apps.setMinimumHeight(60)
        f.addWidget(self.apps, 1)
        ah = QHBoxLayout()
        self.btn_pick = QPushButton(_("Add from the open windows…"))
        self.btn_pick.setToolTip(_("Add the program of one of the windows open now"))
        icons.set_icon(self.btn_pick, "window", size=14)
        self.btn_pick.clicked.connect(self._pick_app)
        ah.addWidget(self.btn_pick)
        ah.addStretch(1)
        self.btn_rm_app = QPushButton(_("Remove"))
        self.btn_rm_app.setToolTip(_("Take the program picked in the list off this profile"))
        self.btn_rm_app.clicked.connect(self._remove_app)
        ah.addWidget(self.btn_rm_app)
        f.addLayout(ah)
        th = QHBoxLayout()
        self.app_text = QLineEdit()
        self.app_text.setPlaceholderText(_("or type a program's name: something.exe"))
        self.app_text.returnPressed.connect(self._type_app)
        th.addWidget(self.app_text, 1)
        self.btn_add_app = QPushButton(_("Add"))
        self.btn_add_app.clicked.connect(self._type_app)
        th.addWidget(self.btn_add_app)
        f.addLayout(th)
        h.addWidget(self.form, 3)
        v.addLayout(h, 1)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)
        for p in self.profiles:
            self.list.addItem(self._item(p))
        i = next((k for k, p in enumerate(self.profiles) if p.id == start), 0)
        if self.profiles:
            self.list.setCurrentRow(i)
        self._show(self.list.currentRow())

    @property
    def result_profiles(self) -> list[Profile]:
        return self.profiles

    @staticmethod
    def _item(p: Profile) -> QListWidgetItem:
        it = QListWidgetItem(p.name)
        it.setData(NAME, p.id)
        return it

    def _current(self) -> Profile | None:
        i = self.list.currentRow()
        return self.profiles[i] if 0 <= i < len(self.profiles) else None

    def _show(self, _i: int = -1):
        p = self._current()
        self.form.setEnabled(p is not None)
        self.btn_delete.setEnabled(p is not None)
        self._loading = True
        self.name.setText(p.name if p else "")
        self.cats.clear()
        for name in self.categories:
            it = QListWidgetItem(profiles.label(name))
            it.setData(NAME, name)
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Checked if p and name in p.categories else Qt.Unchecked)
            self.cats.addItem(it)
        self.when.setCurrentIndex(max(0, self.when.findData(p.when if p else "running")))
        self._fill_apps()
        self._loading = False

    def _fill_apps(self):
        p = self._current()
        self.apps.clear()
        for a in p.apps if p else []:
            it = QListWidgetItem(a)
            it.setData(NAME, a)
            self.apps.addItem(it)
        full = p is None or len(p.apps) >= profiles.MAX_APPS
        self.btn_pick.setEnabled(not full)
        self.btn_add_app.setEnabled(not full)

    def _new(self):
        p = profiles.new_profile(_("Profile {n}", n=len(self.profiles) + 1))
        if len(self.profiles) >= profiles.MAX_PROFILES:
            return
        self.profiles.append(p)
        self.list.addItem(self._item(p))
        self.list.setCurrentRow(len(self.profiles) - 1)
        self.name.setFocus()
        self.name.selectAll()

    def _delete(self):
        i = self.list.currentRow()
        if not 0 <= i < len(self.profiles):
            return
        del self.profiles[i]
        self.list.takeItem(i)
        self._show(self.list.currentRow())

    def _on_name(self, text: str):
        p = self._current()
        if p is None:
            return
        p.name = profiles.clean_name(text) or _("Profile")
        self.list.currentItem().setText(p.name)

    def _on_cat(self, it: QListWidgetItem):
        p = self._current()
        if self._loading or p is None:
            return
        name = it.data(NAME)
        if it.checkState() == Qt.Checked and name not in p.categories:
            p.categories.append(name)
        elif it.checkState() != Qt.Checked:
            p.categories = [n for n in p.categories if n != name]

    def _on_when(self, _i: int):
        p = self._current()
        if p is not None:
            p.when = self.when.currentData()

    def add_app(self, text: str) -> bool:
        p = self._current()
        exe = profiles.exe_name(text)
        if p is None or not exe or exe in p.apps or len(p.apps) >= profiles.MAX_APPS:
            return False
        p.apps.append(exe)
        self._fill_apps()
        return True

    def _type_app(self):
        if self.add_app(self.app_text.text()):
            self.app_text.clear()

    def _remove_app(self):
        p = self._current()
        it = self.apps.currentItem()
        if p is None or it is None:
            return
        p.apps = [a for a in p.apps if a != it.data(NAME)]
        self._fill_apps()

    def open_programs(self) -> list[tuple[str, str]]:
        """The programs with a window open: (exe, a window title of it), by name."""
        seen: dict[str, str] = {}
        try:
            wins = self._lister() if self._lister else []
        except OSError:
            wins = []
        for w in wins:
            if w.exe and w.exe not in seen:
                seen[w.exe] = w.title
        return sorted(seen.items())

    def _pick_app(self):
        menu = QMenu(self)
        progs = self.open_programs()
        for exe, title in progs:
            short = title if len(title) <= 50 else title[:49] + "…"
            menu.addAction(f"{exe}  —  {short}", lambda e=exe: self.add_app(e))
        if not progs:
            menu.addAction(_("No windows open")).setEnabled(False)
        menu.exec(self.btn_pick.mapToGlobal(self.btn_pick.rect().bottomLeft()))


class CategoriesDialog(QDialog):
    """Each category's look: its header's colour, its name's colour and a picture,
    with how its header will look. Works on copies: `result` (name -> look) once
    accepted. A picture picked is saved straight away (save_picture), so the copy
    only carries its name."""

    def __init__(self, parent, cats: list[Category], data_dir, start: str = ""):
        super().__init__(parent)
        fit.watch(self)          # grows to fit its (translated) text
        self.setWindowTitle(_("Categories"))
        self.resize(900, 560)
        self.data_dir = data_dir
        self.cats = [c.copy() for c in cats]
        v = QVBoxLayout(self)
        v.addWidget(hint_label(
            _("Give a category its own colours, a picture and a banner, so it's easy to spot in "
              "the list. Its triggers work just the same.")))
        # how it looks, across the whole window (as wide as it can be, like the
        # real header): with a banner, drag it to pick the part that shows
        self.preview = BannerFrame(draggable=True)
        self.preview.moved.connect(self._banner_moved)
        ph = QHBoxLayout(self.preview)
        ph.setContentsMargins(10, 8, 10, 8)
        ph.setSpacing(10)
        self.preview_pic = QLabel()
        self.preview_pic.setFixedSize(HEADER_PICTURE, HEADER_PICTURE)
        self.preview_pic.setAttribute(Qt.WA_TransparentForMouseEvents)
        ph.addWidget(self.preview_pic)
        self.preview_name = QLabel()
        self.preview_name.setAttribute(Qt.WA_TransparentForMouseEvents)
        ph.addWidget(self.preview_name, 1)
        self.preview_hint = QLabel(_("Drag the picture to move it"))
        self.preview_hint.setObjectName("muted")
        self.preview_hint.setAttribute(Qt.WA_TransparentForMouseEvents)
        ph.addWidget(self.preview_hint)
        v.addWidget(self.preview)
        h = QHBoxLayout()
        self.list = QListWidget()
        self.list.setIconSize(QSize(20, 20))
        self.list.setMinimumWidth(190)
        for c in self.cats:
            it = QListWidgetItem(look_icon(c, data_dir), profiles.label(c.name))
            it.setData(NAME, c.name)
            self.list.addItem(it)
        self.list.currentRowChanged.connect(self._show)
        h.addWidget(self.list, 2)

        f = QVBoxLayout()
        f.addWidget(section_label(_("TAB COLOUR")))
        self.color_buttons = self._swatches(f, SWATCHES, _("Theme's"), self.set_color,
                                            _("The tab's colour"))
        f.addWidget(section_label(_("TEXT COLOUR")))
        self.text_buttons = self._swatches(f, TEXT_SWATCHES, _("Automatic"),
                                           self.set_text_color,
                                           _("The name's colour. Automatic: black or white, "
                                             "whichever reads best on the tab"))
        f.addWidget(section_label(_("PICTURE")))
        pr = QHBoxLayout()
        self.btn_pick = QPushButton(_("Pick a picture…"))
        icons.set_icon(self.btn_pick, "image", size=14)
        self.btn_pick.clicked.connect(self._pick_picture)
        pr.addWidget(self.btn_pick)
        self.btn_paste = QPushButton(_("Paste"))
        self.btn_paste.setToolTip(_("Use the picture you copied"))
        self.btn_paste.clicked.connect(self._paste_picture)
        pr.addWidget(self.btn_paste)
        self.btn_no_pic = QPushButton(_("Remove"))
        self.btn_no_pic.setToolTip(_("No picture"))
        self.btn_no_pic.clicked.connect(self.remove_picture)
        pr.addWidget(self.btn_no_pic)
        pr.addStretch(1)
        f.addLayout(pr)
        f.addWidget(section_label(_("BANNER")))
        br = QHBoxLayout()
        self.btn_pick_banner = QPushButton(_("Pick a banner…"))
        icons.set_icon(self.btn_pick_banner, "image", size=14)
        self.btn_pick_banner.setToolTip(_("A wide picture across the whole header. Any size: "
                                          "drag it above to pick the part that shows"))
        self.btn_pick_banner.clicked.connect(self._pick_banner)
        br.addWidget(self.btn_pick_banner)
        self.btn_paste_banner = QPushButton(_("Paste"))
        self.btn_paste_banner.setToolTip(_("Use the picture you copied as the banner"))
        self.btn_paste_banner.clicked.connect(self._paste_banner)
        br.addWidget(self.btn_paste_banner)
        self.btn_no_banner = QPushButton(_("Remove"))
        self.btn_no_banner.setToolTip(_("No banner"))
        self.btn_no_banner.clicked.connect(self.remove_banner)
        br.addWidget(self.btn_no_banner)
        self.cb_banner_height = QComboBox()
        self.cb_banner_height.setToolTip(_("How tall the header is with its banner"))
        self.cb_banner_height.setAccessibleName(_("Banner height"))
        for key, label in BANNER_HEIGHT_NAMES.items():
            self.cb_banner_height.addItem(label, key)
        self.cb_banner_height.currentIndexChanged.connect(self._banner_height)
        br.addWidget(self.cb_banner_height)
        br.addStretch(1)
        f.addLayout(br)
        f.addStretch(1)
        self.btn_reset = QPushButton(_("Back to plain"))
        self.btn_reset.setToolTip(_("No colours, picture or banner: the theme's look"))
        self.btn_reset.clicked.connect(self.reset)
        f.addWidget(self.btn_reset, 0, Qt.AlignLeft)
        self.form = QWidget()
        self.form.setLayout(f)
        f.setContentsMargins(0, 0, 0, 0)
        h.addWidget(self.form, 3)
        v.addLayout(h, 1)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)
        names = [c.name for c in self.cats]
        self.list.setCurrentRow(names.index(start) if start in names else 0)
        self._show()

    @property
    def result(self) -> dict[str, dict]:
        return {c.name: c.full_look() for c in self.cats}

    def _swatches(self, layout, colours, plain: str, pick, tip: str) -> dict:
        """A line of colour buttons, the plain one first and "Other…" last: they
        call `pick` with a colour ("" for plain). Returns colour -> button."""
        row = QHBoxLayout()
        row.setSpacing(4)
        out = {}
        b = QPushButton(plain)
        b.setObjectName("small")
        b.setCheckable(True)
        b.setToolTip(tip)
        b.clicked.connect(lambda: pick(""))
        row.addWidget(b)
        out[""] = b
        for c in colours:
            b = QPushButton()
            b.setCheckable(True)
            b.setFixedSize(22, 22)
            b.setToolTip(c)
            b.setAccessibleName(_("Colour {c}", c=c))
            b.setStyleSheet(
                f"QPushButton {{ border:1px solid {mix(c, _panel(), 0.7)}; border-radius:11px;"
                f" padding:0; background:qlineargradient(x1:0, y1:0, x2:1, y2:1,"
                f" stop:0 {mix(c, '#ffffff', 0.85)}, stop:1 {mix(c, _panel(), 0.6)}); }}"
                f" QPushButton:hover {{ border:1px solid {theme.T.get('text', '#ffffff')}; }}"
                f" QPushButton:checked {{ border:2px solid {theme.T.get('text', '#ffffff')}; }}")
            b.clicked.connect(lambda __=False, c=c: pick(c))
            row.addWidget(b)
            out[c] = b
        other = QPushButton(_("Other…"))
        other.setObjectName("small")
        other.setToolTip(_("Any colour"))
        other.clicked.connect(lambda: self._other(pick, out))
        row.addWidget(other)
        row.addStretch(1)
        layout.addLayout(row)
        return out

    def _other(self, pick, buttons):
        c = self._current()
        now = (c.color if buttons is self.color_buttons else c.text_color) if c else ""
        col = QColorDialog.getColor(QColor(now or "#1fb6a6"), self, _("Pick a colour"))
        if col.isValid():
            pick(col.name())

    def _current(self) -> Category | None:
        i = self.list.currentRow()
        return self.cats[i] if 0 <= i < len(self.cats) else None

    def select(self, name: str):
        names = [c.name for c in self.cats]
        if name in names:
            self.list.setCurrentRow(names.index(name))

    def _show(self, _i: int = -1):
        c = self._current()
        self.form.setEnabled(c is not None)
        if c is None:
            return
        for want, buttons in ((c.color, self.color_buttons),
                              (c.text_color, self.text_buttons)):
            for k, b in buttons.items():
                b.setChecked(k == want)
        self.btn_no_pic.setEnabled(bool(c.image))
        name_ink = ink(c)
        self.preview.setStyleSheet(tab_css(c.color))
        self.preview_name.setText(profiles.label(c.name))
        self.preview_name.setStyleSheet(
            "font-weight:700; font-size:10.5pt; background:transparent;"
            + (f" color:{name_ink};" if name_ink else ""))
        pm = picture_pixmap(c.image, self.data_dir, HEADER_PICTURE)
        self.preview_pic.setPixmap(pm or QPixmap())
        self.preview_pic.setVisible(pm is not None)
        img = banner_image(c, self.data_dir)
        self.preview.set_banner(img, c.banner_x, c.banner_y, c.banner_height, fade_color(c))
        self.preview_hint.setVisible(img is not None)
        self.btn_no_banner.setEnabled(bool(c.banner))
        self.cb_banner_height.setEnabled(bool(c.banner))
        self.cb_banner_height.blockSignals(True)
        self.cb_banner_height.setCurrentIndex(max(0, self.cb_banner_height.findData(
            c.banner_height)))
        self.cb_banner_height.blockSignals(False)
        it = self.list.currentItem()
        if it is not None:
            it.setIcon(look_icon(c, self.data_dir))

    def set_color(self, color: str):
        c = self._current()
        if c is not None:
            c.color = profiles.clean_color(color)
            self._show()

    def set_text_color(self, color: str):
        c = self._current()
        if c is not None:
            c.text_color = profiles.clean_color(color)
            self._show()

    def set_picture(self, img: QImage) -> bool:
        """Give the category picked `img` as its picture."""
        c = self._current()
        name = save_picture(img, self.data_dir) if c is not None else ""
        if name:
            c.image = name
            self._show()
        return bool(name)

    def remove_picture(self):
        c = self._current()
        if c is not None:
            c.image = ""
            self._show()

    def reset(self):
        c = self._current()
        if c is not None:
            c.color = c.text_color = c.image = c.banner = ""
            self._show()

    def set_banner(self, img: QImage) -> bool:
        """Give the category picked `img` as its banner, shown from its middle."""
        c = self._current()
        name = save_banner(img, self.data_dir) if c is not None else ""
        if name:
            c.banner, c.banner_x, c.banner_y = name, 0.5, 0.5
            self._show()
        return bool(name)

    def remove_banner(self):
        c = self._current()
        if c is not None:
            c.banner = ""
            self._show()

    def _banner_moved(self, x: float, y: float):
        c = self._current()
        if c is not None:
            c.banner_x, c.banner_y = x, y

    def _banner_height(self, _i: int):
        c = self._current()
        key = self.cb_banner_height.currentData()
        if c is not None and key in profiles.BANNER_HEIGHTS:
            c.banner_height = key
            self._show()

    def _pick_banner(self):
        path, __ = QFileDialog.getOpenFileName(
            self, _("Pick a banner"), "",
            _("Pictures") + " (*.png *.jpg *.jpeg *.bmp *.gif *.webp);;"
            + _("All files") + " (*)")
        if path and not self.set_banner(QImage(path)):
            self.btn_pick_banner.setToolTip(_("That file couldn't be read as a picture"))

    def _paste_banner(self):
        from PySide6.QtWidgets import QApplication
        self.set_banner(QApplication.clipboard().image())

    def _pick_picture(self):
        path, __ = QFileDialog.getOpenFileName(
            self, _("Pick a picture"), "",
            _("Pictures") + " (*.png *.jpg *.jpeg *.bmp *.gif *.webp *.ico);;"
            + _("All files") + " (*)")
        if path and not self.set_picture(QImage(path)):
            self.btn_pick.setToolTip(_("That file couldn't be read as a picture"))

    def _paste_picture(self):
        from PySide6.QtWidgets import QApplication
        self.set_picture(QApplication.clipboard().image())
