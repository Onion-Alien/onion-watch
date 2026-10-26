"""The small widgets and helpers a trigger card is built from: lists and number
boxes that fit their text, labels that cut their words short, the picture strip,
flowing rows, the tune grid, switches, section titles and the cards' style sheet."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QEvent, QPoint, QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (QAbstractSpinBox, QApplication, QBoxLayout, QCheckBox, QComboBox,
                               QDoubleSpinBox, QFrame, QGridLayout, QHBoxLayout, QLabel,
                               QPushButton, QScrollArea, QSizePolicy, QSpacerItem, QSpinBox, QStyle,
                               QStyleOptionComboBox, QStyleOptionSpinBox, QVBoxLayout, QWidget)

from onionwatch.engine.screenwatch import Monitor, WindowRef
from onionwatch.i18n import _, ngettext
from onionwatch.ui.kit import icons, theme
from onionwatch.ui.kit.panel import Flow
from onionwatch.ui.triggers.pictures import THUMB, thumb_pixmap
from onionwatch.ui.triggers.windowpicker import places_label

PICK_WINDOW = "__pick_window__"   # a "Look in" list's "Pick a window" entry
DEFAULT = "__default__"           # ...its "Same as below" entry
PLACES = "__places__"             # ...the trigger's own windows and screens
STRIP_THUMBS = 3        # thumbnails a card's strip shows before it scrolls


def narrow(combo: QComboBox, chars: int) -> QComboBox:
    """A list that doesn't grow to its longest entry (the window must fit 300 px)."""
    combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
    combo.setMinimumContentsLength(chars)
    return combo


class WideCombo(QComboBox):
    """A list as wide as the entry it shows when there's room ("Screen 2: 1920×1080"
    isn't cut off, "it shows up" isn't padded out to its longest entry's width) that
    still gives way when the window is small; its open list is as wide as its longest
    entry. A plain AdjustToContents list can never be narrower than its entries, and
    the tab, so the whole window, then can't shrink below it (the window must fit
    300 px)."""

    MIN_WIDTH = 90

    def __init__(self, parent: QWidget | None = None, min_width: int = MIN_WIDTH):
        super().__init__(parent)
        self.min_width = min_width
        self.setSizeAdjustPolicy(QComboBox.AdjustToContents)   # (the open list's width)
        pol = self.sizePolicy()
        pol.setHorizontalPolicy(QSizePolicy.Maximum)   # up to that, down to min_width
        self.setSizePolicy(pol)
        self.currentIndexChanged.connect(self.updateGeometry)   # its width follows it

    def sizeHint(self) -> QSize:
        s = super().sizeHint()          # the longest entry's
        opt = QStyleOptionComboBox()
        self.initStyleOption(opt)
        text = self.fontMetrics().horizontalAdvance(self.currentText())
        if not self.itemIcon(self.currentIndex()).isNull():
            text += self.iconSize().width() + 4
        w = self.style().sizeFromContents(QStyle.CT_ComboBox, opt,
                                          QSize(text, s.height()), self).width()
        return QSize(min(s.width(), w + 4), s.height())

    def minimumSizeHint(self) -> QSize:
        s = super().minimumSizeHint()
        return QSize(min(s.width(), self.min_width, self.sizeHint().width()), s.height())

    def showPopup(self):
        # open as wide as the longest entry, however narrow the list is shut
        self.view().setMinimumWidth(super().sizeHint().width())
        super().showPopup()


def _spin_hint(sb, s: QSize) -> QSize:
    """`s` (a number box's size hint) trimmed to its longest number, suffix and all:
    Qt leaves room for a few more letters than it ever shows."""
    fm = sb.fontMetrics()
    text = max(fm.horizontalAdvance(sb.prefix() + sb.textFromValue(v) + sb.suffix())
               for v in (sb.minimum(), sb.maximum()))
    opt = QStyleOptionSpinBox()
    sb.initStyleOption(opt)
    opt.rect = QRect(0, 0, s.width(), s.height())
    edit = sb.style().subControlRect(QStyle.CC_SpinBox, opt, QStyle.SC_SpinBoxEditField, sb)
    return QSize(s.width() - max(0, edit.width() - text - 8), s.height())


class FitSpin(QSpinBox):
    """A whole-number box as wide as its numbers (see _spin_hint)."""

    def sizeHint(self) -> QSize:
        return _spin_hint(self, super().sizeHint())

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()


class FitDoubleSpin(QDoubleSpinBox):
    """A number box as wide as its numbers (see _spin_hint)."""

    def sizeHint(self) -> QSize:
        return _spin_hint(self, super().sizeHint())

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()


def labelled(text: str, w: QWidget, in_card: bool = False) -> QWidget:
    """`text` and its control kept together on one line of a wrapping row
    (`in_card`: a card's, see-through by the card's style sheet)."""
    box = QWidget()
    box.setObjectName("labelled")   # see-through, whichever program's stylesheet is in use
    if not in_card:
        box.setStyleSheet("QWidget#labelled { background: transparent; }")
    h = QHBoxLayout(box)
    h.setContentsMargins(0, 0, 0, 0)
    h.setSpacing(6)
    if text:
        h.addWidget(QLabel(text))
    h.addWidget(w)
    return box


def pictures(n: int) -> str:
    return ngettext("{n} picture", "{n} pictures", n)


def triggers(n: int) -> str:
    return ngettext("{n} trigger", "{n} triggers", n)


def interval_label(ms: int) -> str:
    """A check speed in a list: "250 ms", "16 ms (every frame)"."""
    return _("{ms} ms (every frame)", ms=ms) if ms == 16 else _("{ms} ms", ms=ms)


def paint_plate(widget: QWidget):
    """The rounded plate a card's picture (or its icon) sits on, in the theme's
    background colour: painted, so it follows a theme change."""
    p = QPainter(widget)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(theme.T.get("bg", "#888888")))
    p.drawRoundedRect(QRectF(widget.rect()), 8, 8)
    p.end()


class Plate(QLabel):
    """An icon on a plate: what a card shows when its trigger has no pictures."""

    def paintEvent(self, ev):
        paint_plate(self)
        super().paintEvent(ev)


class ElideLabel(QLabel):
    """A label that can keep to one line, cut short with an … (set_elide) and the
    whole text as its tooltip, rather than wrap or be clipped mid-letter."""

    def __init__(self, text: str = ""):
        super().__init__()
        self._full = ""
        self._elide = False
        self.setText(text)

    def text(self) -> str:
        return self._full

    def setText(self, text: str):
        self._full = text
        self._fit()

    def set_elide(self, on: bool):
        self._elide = on
        self.setWordWrap(not on)
        self._fit()

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self._fit()

    def _fit(self):
        text = self._full
        if self._elide:
            text = self.fontMetrics().elidedText(text, Qt.ElideRight,
                                                 max(0, self.contentsRect().width()))
        if text != QLabel.text(self):
            QLabel.setText(self, text)
            self.setToolTip(self._full if text != self._full else "")


class Thumb(QWidget):
    """One picture in a card's strip: the thumbnail (click to see it big, with the
    trigger's other pictures) on a rounded plate, with a ✕ in its corner while the
    mouse is over it. A closed card's one thumbnail (`tile`) has a + there instead
    (add a picture), and "+3" in the other corner when there are more."""
    clicked = Signal(int)
    removed = Signal(int)
    add = Signal()

    def __init__(self, index: int, path: str, size: QSize = THUMB, tile: bool = False):
        super().__init__()
        self.index = index
        self.tile = tile
        self.pic = QPushButton(self)
        self.pic.setObjectName("thumb")     # just the picture: the plate is painted here
        self.pic.setFixedSize(size + QSize(8, 8))
        self.pic.setIconSize(size)
        self.pic.setCursor(Qt.PointingHandCursor)
        self.pic.clicked.connect(lambda: self.clicked.emit(self.index))
        pm = thumb_pixmap(path, size)
        if pm.isNull():
            self.pic.setIcon(icons.icon("image", "muted"))
            self.pic.setToolTip(_("{name}: this picture can't be read — click to open it and "
                                  "swap it for another file", name=Path(path).name))
        else:
            self.pic.setIcon(pm)
            self.pic.setToolTip(_("{name}\nClick to see it big", name=Path(path).name))
        self.setFixedSize(self.pic.size())
        small = size.height() < THUMB.height()
        self.x = QPushButton("✕", self)
        self.x.setObjectName("danger")
        self.x.setProperty("corner", "small" if small else "big")     # (CARD_CSS)
        self.x.setFixedSize(*((14, 14) if small else (18, 18)))
        self.x.setToolTip(_("Remove this picture"))
        self.x.move(self.width() - self.x.width() - 3, 3)
        self.x.clicked.connect(lambda: self.removed.emit(self.index))
        self.x.hide()
        self.plus = QPushButton("+", self)
        self.plus.setObjectName("thumbadd")
        self.plus.setFixedSize(18, 18)
        self.plus.setCursor(Qt.PointingHandCursor)
        self.plus.setAccessibleName(_("Add a picture"))
        self.plus.setToolTip(_("Add another picture to this trigger"))
        self.plus.move(self.width() - self.plus.width() - 3, 3)
        self.plus.clicked.connect(self.add)
        self.plus.hide()
        self.can_add = True
        self.more = QLabel(self)
        self.more.setObjectName("thumbmore")
        self.more.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.more.hide()

    def set_more(self, n: int):
        """"+n" in the corner: n more pictures than the strip shows."""
        self.more.setVisible(n > 0)
        if n > 0:
            self.more.setText(f"+{n}")
            self.more.adjustSize()
            self.more.move(self.width() - self.more.width() - 4,
                           self.height() - self.more.height() - 4)
            self.pic.setToolTip(self.pic.toolTip() + "\n" + ngettext(
                "{n} more picture: click to see them all",
                "{n} more pictures: click to see them all", n))

    def paintEvent(self, _ev):
        paint_plate(self)

    def enterEvent(self, ev):
        corner = self.plus if self.tile else self.x
        if corner is self.x or self.can_add:
            corner.show()
            corner.raise_()
        super().enterEvent(ev)

    def leaveEvent(self, ev):
        self.x.hide()
        self.plus.hide()
        super().leaveEvent(ev)


class Strip(QScrollArea):
    """A card's pictures in a row: up to `shown` wide, scrolling sideways past that,
    so a trigger with a hundred pictures stays a short card. A closed card shows
    one, small, with "+3" on it for the rest (set_look)."""
    picture_clicked = Signal(int)
    picture_removed = Signal(int)
    add_wanted = Signal()               # the + on a closed card's thumbnail

    def __init__(self):
        super().__init__()
        self.can_add = True             # there's room for another picture
        self.setFrameShape(QFrame.NoFrame)
        self.setWidgetResizable(True)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.box = QWidget()
        self.row = QHBoxLayout(self.box)
        self.row.setContentsMargins(0, 0, 0, 0)
        self.row.setSpacing(4)
        self.row.addStretch(1)
        self.setWidget(self.box)
        self.thumbs: list[Thumb] = []
        self.paths: list[str] = []
        self.thumb = THUMB          # its thumbnails' size
        self.shown = STRIP_THUMBS   # how many it's wide
        self._h = 0
        self._fit_height()

    @property
    def slot(self) -> int:
        return self.thumb.width() + 8 + self.row.spacing()

    def set_look(self, thumb: QSize, shown: int):
        """Thumbnails this big, this many of them side by side."""
        if (thumb, shown) == (self.thumb, self.shown):
            return
        self.thumb, self.shown = thumb, shown
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff if shown == 1
                                          else Qt.ScrollBarAsNeeded)
        self.set_paths(self.paths)

    def set_paths(self, paths: list[str]):
        self.paths = list(paths)
        for th in self.thumbs:
            self.row.removeWidget(th)
            th.hide()           # retain ownership until deferred deletion
            th.deleteLater()
        self.thumbs = []
        # one shown of several: the rest are seen by clicking it (the viewer goes round)
        for i, p in enumerate(paths[:1] if self.shown == 1 else paths):
            th = Thumb(i, p, self.thumb, tile=self.shown == 1)
            th.can_add = self.can_add
            th.clicked.connect(self.picture_clicked)
            th.removed.connect(self.picture_removed)
            th.add.connect(self.add_wanted)
            self.row.insertWidget(i, th)
            self.thumbs.append(th)
        if self.shown == 1 and self.thumbs:
            self.thumbs[0].set_more(len(paths) - 1)
        self.updateGeometry()
        self._fit_height()

    def set_can_add(self, on: bool):
        self.can_add = on
        for th in self.thumbs:
            th.can_add = on

    def sizeHint(self) -> QSize:
        n = min(max(len(self.thumbs), 1), self.shown)
        return QSize(n * self.slot - self.row.spacing(), self._h)

    def minimumSizeHint(self) -> QSize:
        return QSize(self.slot - self.row.spacing(), self._h)

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self._fit_height()

    def _fit_height(self):
        """The thumbnails' height, plus the scrollbar's only when there's more than fits."""
        h = self.thumb.height() + 8
        if (self.shown > 1 and
                len(self.thumbs) * self.slot - self.row.spacing() > self.viewport().width()):
            h += self.horizontalScrollBar().sizeHint().height()
        if h != self._h:
            self._h = h
            self.setFixedHeight(h)


def fill_sources(cb: QComboBox, mons: list[Monitor], places: list,
                 default_label: str = "", pick_label: str = "") -> None:
    """Fill a "Look in" list: "Default (…)" (when `default_label`), each screen,
    the chosen window(s), then `pick_label`. The current choice is selected: the
    places when there are some (one screen, or its windows and screens in a few
    words), else the default (or the first screen)."""
    cb.blockSignals(True)
    cb.clear()
    current = 0
    if default_label:
        cb.addItem(default_label, DEFAULT)
    one = places[0] if len(places) == 1 and not isinstance(places[0], WindowRef) else None
    for i, m in enumerate(mons):
        cb.addItem(icons.icon("apps", "muted"), _("Screen {n}", n=i + 1) + f": {m.label}", i)
        if one == i:
            current = cb.count() - 1
    if not mons and not default_label:
        cb.addItem(icons.icon("apps", "muted"), _("Main screen"), 0)
    if one is not None and not 0 <= one < len(mons) and mons:
        cb.addItem(_("Screen {n} (not plugged in)", n=one + 1), one)
        current = cb.count() - 1
    if places and one is None:
        cb.addItem(icons.icon("window"), places_label(places), PLACES)
        cb.setItemData(cb.count() - 1, "\n".join(
            p.label if isinstance(p, WindowRef) else _("Screen {n}", n=p + 1) for p in places),
            Qt.ToolTipRole)
        current = cb.count() - 1
    cb.insertSeparator(cb.count())
    cb.addItem(icons.icon("window", "muted"), pick_label or _("Pick a window"), PICK_WINDOW)
    cb.setCurrentIndex(current)
    cb.blockSignals(False)


def source_label(src, mons: list[Monitor]) -> str:
    if isinstance(src, WindowRef):
        return src.label
    if isinstance(src, int) and len(mons) > 1:
        return _("screen {n}", n=src + 1)
    return _("the screen")


def retarget(src, old: WindowRef, new: WindowRef):
    """`src` (a screen or a WindowRef) after the window `old` was swapped for `new`
    (Change window…): a WindowRef of `old`'s program and title becomes `new`'s. The
    copy `old` named takes the copy picked; other copies keep theirs, and one for
    every copy stays every copy. Anything else stays as it is."""
    if not isinstance(src, WindowRef) or (src.exe, src.title) != (old.exe, old.title):
        return src
    if src.every:
        return WindowRef(new.exe, new.title, 0, True)
    return WindowRef(new.exe, new.title, new.nth if src.nth == old.nth else src.nth)


def retargeted(sources: list, old: WindowRef, new: WindowRef) -> list:
    """A trigger's places with `old` swapped for `new` (see retarget), each once."""
    out: list = []
    for s in sources:
        s = retarget(s, old, new)
        if s not in out:
            out.append(s)
    return out


def swatch(colour: str, size: int = 14) -> QIcon:
    pm = QPixmap(size, size)
    pm.fill(QColor(colour) if colour else QColor(0, 0, 0, 0))
    return QIcon(pm)


ALIGN_CSS = "padding-top:4px; padding-bottom:4px; font-size:9pt;"


def align_control(widget: QWidget, in_card: bool = False):
    """One readable control size in both the standalone app and the Board module.
    `in_card`: a card's control, styled by the card's one style sheet (CARD_CSS)
    rather than a sheet of its own each, which made a card slow to make."""
    if in_card:
        polished = widget.testAttribute(Qt.WA_WState_Polished)
        widget.setProperty("aligned", True)
        if polished:            # a property doesn't restyle what's already styled
            widget.style().unpolish(widget)
            widget.style().polish(widget)
        widget.ensurePolished()
        # as a style sheet of its own would: sizes it worked out unstyled are dropped
        QApplication.sendEvent(widget, QEvent(QEvent.StyleChange))
    else:
        widget.setStyleSheet(ALIGN_CSS)
        widget.ensurePolished()
    widget.setFixedHeight(max(34, widget.fontMetrics().height() + 16))
    if isinstance(widget, QPushButton):
        widget.setCursor(Qt.PointingHandCursor)
        if widget.menu():
            widget.setStyleSheet(widget.styleSheet() + "padding-right:24px;")


class FlowBox(QWidget):
    """A wrapping row (Flow) that takes the height its lines need at its width. A
    Flow's height-for-width isn't passed up through the scrolling list of cards,
    so on its own a row that wraps overlaps what's below it, or runs off the edge."""

    def __init__(self, gap: int = 6, parent=None, flow_type=Flow):
        super().__init__(parent)
        self.flow = flow_type(self, gap=gap)

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self._fit()

    def showEvent(self, ev):
        super().showEvent(ev)
        self._fit()

    def event(self, ev):
        result = super().event(ev)
        if ev.type() == QEvent.LayoutRequest:
            self._fit()
        return result

    def _fit(self):
        h = self.flow.heightForWidth(max(self.width(), 1))
        if h != self.minimumHeight():
            self.setMinimumHeight(h)


class ElidedLabel(QLabel):
    """One line cut short a whole part at a time ("12 of 40 triggers on · …") where
    it doesn't fit, never a letter sliced in half at the edge or a lone "1" or "·"
    (the Profile line's counts in a window too narrow for them)."""

    SEPARATORS = ("  —  ", " · ")

    def _ends(self) -> list[int]:
        full = self.text()
        return sorted(i for sep in self.SEPARATORS
                      for i in range(len(full)) if full.startswith(sep, i))

    def least_width(self) -> int:
        """How wide it must be to show its first part."""
        ends = self._ends()
        text = self.text()[:ends[0]] + " …" if ends else self.text()
        return self.fontMetrics().horizontalAdvance(text) + 4

    def sizeHint(self):     # (its full width would squeeze everything beside it)
        return QSize(self.least_width(), super().sizeHint().height())

    def minimumSizeHint(self):
        return QSize(0, super().minimumSizeHint().height())

    def shown_text(self) -> str:
        width, fm = self.contentsRect().width(), self.fontMetrics()
        full = self.text()
        if fm.horizontalAdvance(full) <= width:
            return full
        for end in reversed(self._ends()):
            text = full[:end] + " …"
            if fm.horizontalAdvance(text) <= width:
                return text
        return ""

    def paintEvent(self, ev):
        r = self.contentsRect()
        text = self.shown_text()
        p = QPainter(self)
        self.style().drawItemText(p, r, int(self.alignment()), self.palette(),
                                  self.isEnabled(), text, self.foregroundRole())
        p.end()


class BarFlow(Flow):
    """The bottom bar's Flow: an item that doesn't fit the rest of a line gives way,
    down to its minimum (a Pair: to what keeps it on one line), before it wraps, and
    is as tall as it needs at the width it gets (a Pair on two lines)."""

    def _place(self, rect: QRect, move: bool) -> int:
        x, y, line = rect.x(), rect.y(), 0
        pending = []

        def place_line():
            if move:
                for item, left, size in pending:
                    item.setGeometry(QRect(QPoint(left, y + (line - size.height()) // 2), size))

        items = [it for it in self._items if not it.isEmpty()]
        for i, it in enumerate(items):
            wid = it.widget()
            pair = wid if isinstance(wid, Pair) else None
            hint, least = it.sizeHint(), it.minimumSize().width()
            keep = pair.one_line_width() if pair else least
            if line and x + keep > rect.right() + 1:        # doesn't fit here: next line
                place_line()
                pending.clear()
                x, y, line = rect.x(), y + line + self._gap, 0
            room = rect.right() + 1 - x
            # leave the items after it their least on this line when it can give way
            # that far (a wide Look in pushed the ⚙ onto a line of its own)
            rest = sum(self._gap + later.minimumSize().width() for later in items[i + 1:])
            if room - rest >= keep:
                room -= rest
            w = max(least, min(hint.width(), room))
            # (asked directly: Qt asks a widget's layout, not the widget)
            h = pair.heightForWidth(w) if pair else hint.height()
            pending.append((it, x, QSize(w, h)))
            x += w + self._gap
            line = max(line, h)
        place_line()
        return y + line - rect.y()


def tall(w: QWidget) -> int:
    """How tall `w` really is: its size hint, or its fixed height (align_control's 34 px)
    when that's more. The hint alone cut the bottom off the Ring list."""
    return max(w.sizeHint().height(), w.minimumHeight())


def control_height(widget: QWidget) -> int:
    """The one height align_control gives a control (a label beside it matches it)."""
    return max(34, widget.fontMetrics().height() + 16)


def capital(text: str) -> str:
    """ "then play" -> "Then play" (nothing changes where there are no capitals)."""
    return text[:1].upper() + text[1:]


def mid_sentence(text: str) -> str:
    """ "The picture shows up" -> "the picture shows up", for a choice in the middle of
    the card's sentence (nothing changes where there are no capitals)."""
    return text[:1].lower() + text[1:]


class ShrinkButton(QPushButton):
    """A button that, short of room, shows just its icon (its tooltip still says
    what it does), so a narrow card isn't held wide by it."""

    def __init__(self, text: str, parent=None):
        super().__init__(text, parent)
        self._text = text
        self._hint: QSize | None = None
        self.setAccessibleName(text)     # (still said with just its icon showing)
        # (a button's Minimum policy makes its full width its least)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)

    def _full(self) -> QSize:
        """Its size with its words (worked out while they're showing)."""
        if self.text() or self._hint is None:
            shown = self.text()
            if not shown:
                self.blockSignals(True)
                QPushButton.setText(self, self._text)
            self._hint = super().sizeHint()
            if not shown:
                QPushButton.setText(self, "")
                self.blockSignals(False)
        return self._hint

    def sizeHint(self) -> QSize:
        return self._full()

    def minimumSizeHint(self) -> QSize:
        return QSize(self.iconSize().width() + 22, self._full().height())

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        want = "" if ev.size().width() < self._full().width() else self._text
        if self.text() != want:
            self.setText(want)


class TuneGrid(QWidget):
    """The card's rules as tidy columns: each column a group under its heading (when
    it plays, where it looks, how often), each rule its tick box (or label) then its
    number or button, the tick boxes in a column one width so the controls line up.
    Fewer columns when it's narrow. A setting moved up into the sentence
    (`removeWidget`) takes its row with it until it comes back (`addWidget`)."""

    GAP = 28    # px between columns
    ROW_GAP, HEAD_GAP = 6, 16   # px between rules, and above a group's heading (a rule's
    # hint has none: it sits right under its rule)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("labelled")     # see-through (CARD_CSS)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.grid = QGridLayout(self)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setHorizontalSpacing(6)
        self.grid.setVerticalSpacing(0)     # the gaps are rows of their own (_lay)
        self.groups: list[list[tuple]] = []   # [(label, widget, inner label), …] each
        self.out: set = set()
        self._cols = 0
        self.max_cols = 3

    def add_group(self, items: list[tuple], title: str = ""):
        if title:       # its heading: a row of its own at the top of the group
            head = QLabel(title, self)
            head.setObjectName("hint")
            head.setProperty("rulehead", True)      # (CARD_CSS)
            items = [(None, head, None), *items]
        for lab, w, inner in items:
            for x in (lab, w):
                if x is not None:
                    x.setParent(self)
            for x in (lab, inner):
                if x is not None:       # the controls' font size
                    x.setObjectName("formcheck" if isinstance(x, QCheckBox) else "formlabel")
            if isinstance(w, QCheckBox):
                w.setObjectName("formcheck")
            elif isinstance(w, Pair) and isinstance(w.first, QCheckBox):
                w.first.setObjectName("formcheck")
        self.groups.append(items)

    def removeWidget(self, w: QWidget):
        self.out.add(w)
        self.grid.removeWidget(w)
        self.relayout()

    def addWidget(self, w: QWidget):
        w.setParent(self)
        w.show()
        self.out.discard(w)
        self.relayout()

    def _columns(self, n: int) -> list[list[tuple]]:
        shown = [[it for it in g if it[1] not in self.out and it[1].isVisibleTo(self)]
                 for g in self.groups]
        if n >= len(shown):
            return shown
        # fewer columns than groups: a group stays whole, under the shortest column
        cols: list[list[tuple]] = [[] for _i in range(n)]
        for i, g in enumerate(shown):
            target = cols[i] if i < n else min(cols, key=len)
            target.extend(g)
        return cols

    @staticmethod
    def _label_w(col: list[tuple]) -> int:
        return max([x.sizeHint().width() for lab, _w, inner in col for x in (lab, inner)
                    if x is not None] or [0])

    def relayout(self):
        """Lay it out in as many columns (3, 2, 1) as fit its width."""
        width = self.width()
        for n in range(min(3, self.max_cols), 0, -1):
            self._lay(n)
            if width <= 0 or n == 1 or self.grid.sizeHint().width() <= width:
                break
        self.updateGeometry()

    def _lay(self, n: int):
        g = self.grid
        while g.count():
            g.takeAt(0)
        for c in range(g.columnCount()):
            g.setColumnStretch(c, 0)
            g.setColumnMinimumWidth(c, 0)
        self._cols = n
        # packed left: the space left over goes to an empty column at the end
        g.addItem(QSpacerItem(0, 0, QSizePolicy.Expanding, QSizePolicy.Minimum), 0, 3 * n)
        g.setColumnStretch(3 * n, 1000)
        for group in self.groups:
            rows = 0
            for lab, w, _inner in group:
                if w.property("rulehint"):      # shown with its rule
                    rule = w.property("rule_of")
                    w.setVisible(rule not in self.out and not rule.isHidden())
                    continue
                if w.property("rulehead"):
                    continue
                here = w not in self.out and not w.isHidden()
                rows += here
                if lab is not None:
                    lab.setVisible(here)
            for _lab, w, _inner in group:       # a heading over nothing goes too
                if w.property("rulehead"):
                    w.setVisible(bool(rows))
        for c, col in enumerate(self._columns(n)):
            lc = 3 * c
            lw = self._label_w(col)
            g.setColumnMinimumWidth(lc, lw)
            # room a wide row (Ring and its list) needs goes to the controls' column,
            # never the labels': the controls stay lined up (packed left: no spreading)
            g.setColumnStretch(lc + 1, 1)
            if c < n - 1:
                g.setColumnMinimumWidth(lc + 2, self.GAP - 12)
            # the number boxes in a column one width, so their arrows line up too
            spins = [sp for _lab, w, _inner in col
                     for sp in ([w] if isinstance(w, QAbstractSpinBox) else [])
                     + w.findChildren(QAbstractSpinBox)]
            for sp in spins:
                sp.setMinimumWidth(0)
            widest = max([sp.sizeHint().width() for sp in spins] or [0])
            for sp in spins:
                sp.setMinimumWidth(widest)
            row = 0
            for i, (lab, w, inner) in enumerate(col):
                gap = (0 if not i or w.property("rulehint") else
                       self.HEAD_GAP if w.property("rulehead") else self.ROW_GAP)
                if gap:
                    g.addItem(QSpacerItem(0, gap, QSizePolicy.Policy.Minimum, QSizePolicy.Fixed),
                              row, lc)
                    row += 1
                if lab is not None:
                    if isinstance(w, QComboBox):    # never squeezed to cut its text
                        w.setMinimumWidth(w.sizeHint().width())
                    lab.setFixedHeight(control_height(w))
                    g.addWidget(lab, row, lc, Qt.AlignLeft | Qt.AlignVCenter)
                    g.addWidget(w, row, lc + 1, Qt.AlignLeft | Qt.AlignVCenter)
                elif w.property("rulehead"):
                    g.addWidget(w, row, lc, 1, 2, Qt.AlignLeft | Qt.AlignBottom)
                elif w.property("rulehint"):
                    g.addWidget(w, row, lc, 1, 2, Qt.AlignLeft | Qt.AlignTop)
                else:
                    # (a Pair's height-for-width comes out 0 in a grid cell, and it
                    # stays on one line: its sizeHint alone lets it be squeezed)
                    w.setMinimumHeight(control_height(w))
                    if isinstance(w, Pair):
                        w.setMinimumWidth(w.first.sizeHint().width() + w.GAP
                                          + w.second.sizeHint().width())
                    if inner is not None:       # its label inside it, as wide as the rest
                        inner.setFixedWidth(lw)
                    g.addWidget(w, row, lc, 1, 2, Qt.AlignLeft | Qt.AlignVCenter)
                row += 1

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        if ev.size().width() != ev.oldSize().width():
            self.relayout()


def rule_hint(text: str, rule: QWidget) -> QLabel:
    """A line under a rule saying what it's for, shown while the rule is."""
    lab = QLabel(text)
    lab.setObjectName("hint")
    lab.setProperty("rulehint", True)       # (CARD_CSS: small, under the tick box's words)
    lab.setProperty("rule_of", rule)
    return lab


class Pair(QWidget):
    """Two labelled controls that read as one ("Look in [game] every [100 ms]"): on
    one line while it's wide enough for both, the second under the first when it
    isn't. A label never ends up apart from its control."""

    GAP, STACKED = 10, 6    # px between them: side by side, one under the other

    def __init__(self, first: QWidget, second: QWidget, parent=None):
        super().__init__(parent)
        self.setObjectName("labelled")      # see-through, like labelled()'s (CARD_CSS)
        self.first, self.second = first, second
        self.box = QBoxLayout(QBoxLayout.LeftToRight, self)
        self.box.setContentsMargins(0, 0, 0, 0)
        self.box.setSpacing(self.GAP)
        self.box.addWidget(first, 0, Qt.AlignLeft)
        self.box.addWidget(second, 0, Qt.AlignLeft)
        self.box.addStretch(1)

    def one_line_width(self) -> int:
        """The least it can be with both on one line."""
        if self.second.isHidden():
            return self.first.minimumSizeHint().width()
        return (self.first.minimumSizeHint().width() + self.GAP
                + self.second.minimumSizeHint().width())

    def _one_line(self, w: int) -> bool:
        return w >= self.one_line_width()

    def sizeHint(self) -> QSize:
        if self.second.isHidden():
            return self.first.sizeHint()
        a, b = self.first.sizeHint(), self.second.sizeHint()
        return QSize(a.width() + self.GAP + b.width(), max(tall(self.first), tall(self.second)))

    def minimumSizeHint(self) -> QSize:
        if self.second.isHidden():
            return self.first.minimumSizeHint()
        a, b = self.first.minimumSizeHint(), self.second.minimumSizeHint()
        return QSize(max(a.width(), b.width()), max(a.height(), b.height()))

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, w: int) -> int:
        if self.second.isHidden():
            return tall(self.first)
        a, b = tall(self.first), tall(self.second)
        return max(a, b) if self._one_line(w) else a + self.STACKED + b

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        one = self._one_line(self.width())
        self.box.setDirection(QBoxLayout.LeftToRight if one else QBoxLayout.TopToBottom)
        self.box.setSpacing(self.GAP if one else self.STACKED)


class Switch(QCheckBox):
    """An on / off switch: a checkbox drawn as a sliding pill, in the theme's colours."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(40, 22)

    def sizeHint(self):
        return QSize(40, 22)

    def hitButton(self, pos):
        return self.rect().contains(pos)

    def paintEvent(self, _e):
        from PySide6.QtCore import QRectF
        from PySide6.QtGui import QPainter
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        on = self.isChecked()
        p.setBrush(QColor(theme.T.get("accent" if on else "off", "#888888")))
        p.drawRoundedRect(QRectF(0, 0, 40, 22), 11, 11)
        p.setBrush(QColor(theme.T.get("on_accent", "#ffffff") if on else "#ffffff"))
        right = on != self.isRightToLeft()     # mirrored: on is on the left
        p.drawEllipse(QRectF(21 if right else 3, 3, 16, 16))


def divider() -> QFrame:
    """A thin line between a card's parts, in the palette's colours (the host's theme
    doesn't know about it)."""
    f = QFrame()
    f.setObjectName("carddivider")
    f.setFixedHeight(1)         # (coloured by CARD_CSS)
    return f


def indented(parent: QVBoxLayout, spacing: int = 8) -> QVBoxLayout:
    """A column under a section's title, set in a little so the title stands out."""
    box = QWidget()
    box.setObjectName("labelled")   # see-through (CARD_CSS)
    col = QVBoxLayout(box)
    col.setContentsMargins(SECTION_INDENT, 0, 0, 0)
    col.setSpacing(spacing)
    parent.addWidget(box)
    return col


SECTION_INDENT = 20     # px: a section's settings, in from its title


def section_title(icon: str, text: str) -> QPushButton:
    """A card section's title: its icon and name in capitals (not clickable)."""
    b = QPushButton(text.upper())
    b.setObjectName("fold")
    b.setFocusPolicy(Qt.NoFocus)
    b.setAttribute(Qt.WA_TransparentForMouseEvents)
    b.setProperty("section", True)      # (CARD_CSS)
    icons.set_icon(b, icon, "section", size=13)
    return b


# a card's own looks, in one style sheet on the card rather than one on each of its
# widgets (a card has dozens: a sheet each made a card slow to make). In the
# palette's colours: the host's theme (Onion Board's) doesn't know about them
CARD_CSS = (
    "QWidget#labelled { background: transparent; }"      # labelled(), indented()...
    "QFrame#carddivider { background: palette(mid); border: none; }"
    # a sound on the card: the shape and height of the boxes beside it, not a pill
    "QLabel#formlabel, QCheckBox#formcheck { font-size: 9pt; }"
    # the card's sentence: its words a little bigger than the rules' labels
    "QLabel#sentenceword, QCheckBox#sentencecheck { font-size: 11pt; }"
    # its choices: big rounded buttons with a heavier bottom edge in the accent colour
    # (token="accent"); the sounds' chips (token="true") plain, the + a thin outline
    'QComboBox[token="true"], QComboBox[token="accent"], QFrame#chip[token="true"] {'
    " background: palette(base); border: 1px solid palette(mid);"
    " border-bottom: 3px solid palette(mid); border-radius: 9px; font-size: 10pt;"
    " font-weight: 600; }"
    'QComboBox[token="accent"] { border-color: palette(highlight); color: palette(highlight); }'
    'QComboBox#addsound[token="true"] { border-bottom-width: 1px; }'
    'QFrame#chip[token="true"] QPushButton#chipname { font-size: 10pt; font-weight: 600;'
    " background: transparent; }"
    # the extra settings it has changed: pills
    'QFrame#chip[pill="true"] { border-radius: 14px; }'
    'QLabel#hint[rulehint="true"] { font-size: 8pt; padding-left: 26px; }'

    'QLabel#hint[rulehead="true"] { font-size: 8pt; font-weight: 700; }'
    "QFrame#chip QLabel#rulename { font-size: 9pt; padding: 0 2px 0 4px; }"
    # Duplicate and Delete: quiet, no box until the mouse is over them
    'QPushButton#small[quiet="true"] { background: transparent; }'
    'QPushButton#small[quiet="true"]:hover { background: palette(button); }'
    "QFrame#chip { border-radius: 8px; }"
    "QFrame#chip QPushButton#chipname { font-size: 9pt; font-weight: normal;"
    " padding: 0 4px; }"
    "QComboBox#addsound { padding: 0 0 0 9px; }"
    "QComboBox#addsound::drop-down { width: 0; border: none; }"
    "QComboBox#addsound::down-arrow { image: none; }"
    "QFrame#chip QPushButton#chipstop { border-radius: 6px; }"
    'QPushButton#fold[section="true"] { text-align:left; padding-left:0; }'
    f'*[aligned="true"], *[aligned="true"] * {{ {ALIGN_CSS} }}'     # align_control()
    # a picture in the strip (Thumb): its plate is painted; its ✕, its + and its "+3"
    "QPushButton#thumb { background:transparent; border:none; padding:0; }"
    'QPushButton#danger[corner="small"] { padding:0; font-size:7pt; }'
    'QPushButton#danger[corner="big"] { padding:0; font-size:8pt; }'
    "QPushButton#thumbadd { background:palette(highlight);"
    " color:palette(highlighted-text); border:none; border-radius:9px; padding:0;"
    " font-size:10pt; font-weight:700; }"
    "QLabel#thumbmore { background: rgba(0,0,0,170); color: white;"
    " border-radius: 4px; padding: 0 3px; font-size: 7pt; font-weight: 700; }"
    # the outlined + after the pictures
    "QPushButton#addpic { background:transparent; border:1px solid palette(mid);"
    " border-radius:8px; padding:0; font-size:12pt; color:palette(window-text); }"
    "QPushButton#addpic:hover { border-color:palette(highlight);"
    " color:palette(highlight); }"
    "QPushButton#addpic:disabled { border-color:transparent; color:transparent; }"
    # the name: a title until you click it (open), or just read (closed)
    "QLineEdit#cardname { background:transparent; border:1px solid transparent;"
    " padding:2px 3px; font-size:11pt; font-weight:700; }"
    'QLineEdit#cardname[big="true"] { font-size:13pt; }'      # a wide open card's
    "QLineEdit#cardname:hover { border-color:palette(mid); }"
    "QLineEdit#cardname:focus { background:palette(base);"
    " border-color:palette(highlight); }"
    "QLabel#cardtitle { font-size:10.5pt; font-weight:700; }"
    # The picked trigger's frame; hover keeps the host's usual card fill.
    'QFrame#card[selected="true"] { border:2px solid palette(highlight); }'
)
# theme.py styles with its own colours and never sets Qt's palette, so palette(...) in
# a style sheet is Qt's stock light one whatever the theme: card_css() puts the
# theme's colours in instead (CARD_CSS keeps the palette names, to read)
_PALETTE = (("color: palette(highlight)", "color: {accent_text}"),
            ("color:palette(highlight)", "color:{accent_text}"),
            ("palette(highlighted-text)", "{on_accent}"), ("palette(highlight)", "{accent}"),
            ("palette(window-text)", "{text}"), ("palette(base)", "{inset}"),
            ("palette(button)", "{btn_hover}"), ("palette(mid)", "{border}"))


def card_css(extra: str = "") -> str:
    """CARD_CSS (and `extra`) in the current theme's colours."""
    css = CARD_CSS + extra
    for name, token in _PALETTE:
        css = css.replace(name, token.format_map(theme.T))
    return css
