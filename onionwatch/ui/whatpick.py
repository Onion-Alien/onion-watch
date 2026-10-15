"""New trigger, the first steps: "What should it watch for?", a tile per kind of
trigger (a picture showing up or going away, a bar running low, a chat line changing,
everything going still), each with a little drawing of it in a made-up game; then,
for every kind, where its picture comes from: for a picture kind the picture to look
for, for the others a picture of the game to drag the bar's or the area's box on.
Pasting it and dropping it come first; taking it from the game as it is now is the
third way. The triggers page does the rest: which window to watch, and cutting the
picture or picking the area."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import (QColor, QImage, QKeySequence, QLinearGradient, QPainter,
                           QPainterPath, QPen, QPixmap, QShortcut)
from PySide6.QtWidgets import (QApplication, QDialog, QFileDialog, QGridLayout, QHBoxLayout,
                               QLabel, QPushButton, QVBoxLayout, QWidget)

from onionwatch import theme
from onionwatch.i18n import _
from onionwatch.ui import icons
from onionwatch.ui.panel import (DIALOG_MARGIN, DIALOG_SPACING, TITLE_GAP, add_title,
                                 hint_label, title_label)

PASTE, FILE, CUT = "paste", "file", "cut"   # where a picture comes from
PICTURE_KINDS = ("appear", "vanish")
EXTS = (".png", ".jpg", ".jpeg", ".bmp", ".webp", ".gif")
ART = QSize(196, 84)              # a tile's drawing
TICK = 24                         # the picked tile's ✓


def kinds() -> list[tuple[str, str, str]]:
    """(mode, title, an example) for each tile, in the order they're shown."""
    return [("appear", _("Something shows up"), _("A rare spawn, a queue pop, YOU DIED")),
            ("vanish", _("Something goes away"), _("A buff runs out, a loading screen ends")),
            ("colour", _("A bar runs low"), _("Health, mana, a timer bar")),
            ("change", _("A chat line changes"), _("A whisper, a new message, anything moving")),
            ("still", _("Everything stops moving"), _("You're stuck, idle or disconnected"))]


def draw_art(p: QPainter, r: QRectF, mode: str):
    """A tile's drawing: a bit of a made-up game showing what that kind watches for.
    A game picture, so its colours are the game's in every theme."""
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    sky = QLinearGradient(r.topLeft(), r.bottomRight())
    sky.setColorAt(0, QColor(43, 58, 82))
    sky.setColorAt(1, QColor(28, 36, 51))
    clip = QPainterPath()
    clip.addRoundedRect(r, 8, 8)
    p.setClipPath(clip)
    p.fillRect(r, sky)
    gold, plate = QColor(201, 162, 39), QColor(16, 21, 31)
    line = QColor(255, 255, 255, 46)
    if mode in ("appear", "vanish"):
        b = QRectF(0, 0, r.width() * 0.6, 20)
        b.moveCenter(r.center())
        if mode == "vanish":
            p.setOpacity(0.3)
        p.setPen(QPen(gold, 1))
        p.setBrush(plate)
        p.drawRoundedRect(b, 2, 2)
        p.setOpacity(1)
        if mode == "appear":    # a ring round it: that's the one it's looking for
            p.setPen(QPen(QColor(theme.T.get("accent", "#1fb6a6")), 2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(r.adjusted(2, 2, -2, -2), 7, 7)
    elif mode == "colour":
        bar = QRectF(r.left() + 14, r.top() + 16, r.width() * 0.7, 11)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(59, 26, 29))
        p.drawRoundedRect(bar, 3, 3)
        p.setBrush(QColor(224, 72, 72))
        p.drawRoundedRect(QRectF(bar.left(), bar.top(), bar.width() * 0.28, bar.height()), 3, 3)
        mana = QRectF(bar.left(), bar.bottom() + 6, bar.width() * 0.8, 7)
        p.setBrush(QColor(30, 70, 140))
        p.drawRoundedRect(mana, 3, 3)
    elif mode == "change":
        p.setPen(Qt.PenStyle.NoPen)
        for i, (w, c) in enumerate(((0.8, line), (0.65, line), (0.5, QColor(127, 212, 255)))):
            p.setBrush(c)
            p.drawRoundedRect(QRectF(r.left() + 14, r.top() + 16 + i * 16,
                                     (r.width() - 28) * w, 7), 3, 3)
    else:   # still: lines that stopped, and z z
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(line)
        p.drawRoundedRect(QRectF(r.left() + 14, r.top() + 22, (r.width() - 28) * 0.8, 7), 3, 3)
        p.drawRoundedRect(QRectF(r.left() + 14, r.top() + 38, (r.width() - 28) * 0.45, 7), 3, 3)
        f = p.font()
        f.setBold(True)
        f.setPointSizeF(12)
        p.setFont(f)
        p.setPen(QColor(159, 179, 200))
        p.drawText(r.adjusted(0, 0, -12, -6),
                   Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom, "z z")
    p.restore()


class Tile(QPushButton):
    """A big choice: a picture on top (`art`, a widget), a name, a line under it."""

    def __init__(self, title: str, line: str, art: QWidget, parent=None):
        super().__init__(parent)
        self.setObjectName("kindtile")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAccessibleName(title)
        self.setToolTip(line)
        v = QVBoxLayout(self)
        v.setContentsMargins(12, 12, 12, 12)
        v.setSpacing(6)
        self.art = art
        art.setParent(self)
        art.setFixedSize(ART)
        art.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        v.addWidget(art)
        self.name = QLabel(title)
        self.name.setObjectName("kindname")
        self.name.setWordWrap(True)
        self.name.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        v.addWidget(self.name)
        self.line = QLabel(line)
        self.line.setObjectName("hint")
        self.line.setWordWrap(True)
        self.line.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        v.addWidget(self.line)
        v.addStretch(1)
        self.setMinimumWidth(ART.width() + 24)

    def sizeHint(self):
        lay = self.layout()
        return lay.sizeHint() if lay is not None else super().sizeHint()


class Drawing(QWidget):
    """A kind's drawing (draw_art)."""

    def __init__(self, mode: str):
        super().__init__()
        self.mode = mode

    def paintEvent(self, _e):
        p = QPainter(self)
        draw_art(p, QRectF(self.rect()), self.mode)
        p.end()


class KindTile(Tile):
    """One kind of trigger: its drawing, what it's called and an example. A click
    picks it (Continue goes on); a double-click picks it and goes on."""
    chosen = Signal(str)        # mode: double-clicked

    def __init__(self, mode: str, title: str, example: str, parent=None):
        super().__init__(title, example, Drawing(mode), parent)
        self.mode = mode
        self.setProperty("pick", True)
        self.setCheckable(True)
        self.setAutoExclusive(True)
        # the picked one's ✓, in its top-right corner over the drawing
        self.tick = QLabel("✓", self)
        self.tick.setObjectName("kindtick")
        self.tick.setFixedSize(TICK, TICK)
        self.tick.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.tick.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.tick.hide()
        self.toggled.connect(self.tick.setVisible)

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self.tick.move(self.width() - TICK - 6, 6)

    def mouseDoubleClickEvent(self, ev):
        if ev.button() == Qt.MouseButton.LeftButton:
            self.setChecked(True)
            self.chosen.emit(self.mode)
        else:
            super().mouseDoubleClickEvent(ev)


class Picture(QLabel):
    """A source tile's picture: an icon in a soft box, or the copied picture itself."""

    def __init__(self, icon: str):
        super().__init__()
        self.icon = icon
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setObjectName("sourceart")
        self.show_icon()

    def show_icon(self):
        self.setPixmap(icons.pixmap(self.icon, 40, theme.T.get("muted", "#888888")))

    def show_image(self, img: QImage):
        pm = QPixmap.fromImage(img).scaled(ART - QSize(16, 16), Qt.AspectRatioMode.KeepAspectRatio,
                                           Qt.TransformationMode.SmoothTransformation)
        self.setPixmap(pm)


def tile_css() -> str:
    """The tiles' look in the current theme's colours (theme.py never sets Qt's
    palette, so palette(...) here would be Qt's stock light one under a dark theme)."""
    t = theme.T
    return (
        f"QPushButton#kindtile {{ background: {t['card']}; border: 1px solid {t['border']};"
        " border-radius: 12px; text-align: left; padding: 0; }"
        "QPushButton#kindtile:hover, QPushButton#kindtile:focus {"
        f" border: 2px solid {t['accent']}; }}"
        # step 1's tiles: hover only hints, the picked one is filled and ringed
        # (focus alone draws nothing: the first tile has it at the start, and it would
        # look picked)
        'QPushButton#kindtile[pick="true"]:focus {'
        f" border: 1px solid {t['border']}; }}"
        'QPushButton#kindtile[pick="true"]:hover {'
        f" border: 2px solid {t['muted']}; }}"
        'QPushButton#kindtile[pick="true"]:checked {'
        f" border: 2px solid {t['accent']}; background: {t['inset']}; }}"
        f'QPushButton#kindtile[drop="true"] {{ border: 2px solid {t["border"]}; }}'
        'QPushButton#kindtile[drop="true"]:hover, QPushButton#kindtile[dragging="true"] {'
        f" border: 2px solid {t['accent']}; }}"
        f"QLabel#kindtick {{ background: {t['accent']}; color: {t['on_accent']};"
        f" border-radius: {TICK // 2}px; font-size: 11pt; font-weight: 700; }}"
        # Continue stays off until a tile is picked: it mustn't look ready
        f"QPushButton#primary:disabled {{ background: {t['btn']}; color: {t['muted']}; }}"
        "QLabel#kindname { font-size: 11pt; font-weight: 700; background: transparent; }"
        f"QLabel#sourceart {{ background: {t['inset']}; border-radius: 8px; }}"
        "QPushButton#kindtile QLabel#hint { background: transparent; }"
    )


class DropTile(Tile):
    """"Drop it here": takes picture files, or a picture dragged out of a browser."""

    def __init__(self, title: str, line: str, picker: WhatPicker):
        super().__init__(title, line, Picture("image"), picker)
        self.picker = picker
        self.setProperty("drop", True)
        self.setAcceptDrops(True)

    @staticmethod
    def _files(mime) -> list[str]:
        if mime is None:        # (an empty clipboard has no data at all)
            return []
        return [u.toLocalFile() for u in mime.urls()
                if u.isLocalFile() and Path(u.toLocalFile()).suffix.lower() in EXTS]

    def _mark(self, on: bool):
        self.setProperty("dragging", on)
        self.style().unpolish(self)
        self.style().polish(self)

    def dragEnterEvent(self, ev):
        mime = ev.mimeData()
        if self._files(mime) or mime.hasImage():
            ev.acceptProposedAction()
            self._mark(True)
        else:
            ev.ignore()

    def dragLeaveEvent(self, ev):
        self._mark(False)
        super().dragLeaveEvent(ev)

    def dropEvent(self, ev):
        self._mark(False)
        mime = ev.mimeData()
        files = self._files(mime)
        if files:
            ev.acceptProposedAction()
            self.picker.use_files(files)
        elif mime.hasImage():
            img = QImage(mime.imageData())
            if not img.isNull():
                ev.acceptProposedAction()
                self.picker.use_image(img)


def step2_texts(mode: str) -> dict[str, str]:
    """Step 2's words for a kind: the picture to look for, or for a bar, a chat line or
    everything still, a picture of the game to drag the box on."""
    if mode in PICTURE_KINDS:
        return {"title": _("Step 2: the picture to look for"),
                "hint": _("Any picture of it works: one off Google, a screenshot, a file, or "
                          "cut from the game as it is now."),
                "drop": _("Drag a picture in from your browser or a folder, or click to "
                          "choose a file."),
                "cut": _("Cut it from the game"),
                "cut_line": _("Drag a box round it in the game window, as it is right now.")}
    title, box = {
        "colour": (_("Step 2: a picture of the game with the bar in it"),
                   _("Drag a box round the bar in the game window, as it is right now.")),
        "change": (_("Step 2: a picture of the game with the chat in it"),
                   _("Drag a box round the chat in the game window, as it is right now.")),
    }.get(mode, (_("Step 2: a picture of the game"),
                 _("Drag a box round the part to watch in the game window, as it is right "
                   "now.")))
    return {"title": title,
            "hint": _("A screenshot of the whole game window works (Alt+Print Screen in the "
                      "game copies one), or take it from the game as it is now. Next you pick "
                      "the game's window and drag a box on the picture."),
            "drop": _("Drag a screenshot of the game in from a folder, or click to choose "
                      "one."),
            "cut": _("Take it from the game"),
            "cut_line": box}


class WhatPicker(QDialog):
    """Steps 1 and 2 of New trigger. Once accepted: `picked`, the kind (a mode), and
    `source` (PASTE, FILE or CUT), with FILE `paths` (picture files) or `image` (a
    picture dragged in from a browser). For a picture kind that's the picture to look
    for; for the others a picture of the game, to drag the bar's or area's box on."""

    def __init__(self, parent=None, can_paste: bool = False):
        super().__init__(parent)
        self.setWindowTitle(_("New trigger"))
        self.picked: str | None = None
        self.source: str | None = None
        self.paths: list[str] = []
        self.image: QImage | None = None
        self.setStyleSheet(tile_css())
        v = QVBoxLayout(self)
        v.setContentsMargins(DIALOG_MARGIN, DIALOG_MARGIN, DIALOG_MARGIN, DIALOG_MARGIN)
        v.setSpacing(DIALOG_SPACING)
        self.pages: list[QWidget] = []     # the steps, one shown at a time

        # step 1: what
        what = QWidget()
        w = QVBoxLayout(what)
        w.setContentsMargins(0, 0, 0, 0)
        w.setSpacing(12)
        add_title(w, _("Step 1: what should it watch for?"),
                  _("Pick one. You can change everything on the trigger afterwards."))
        grid = QGridLayout()
        grid.setSpacing(12)
        self.tiles: list[KindTile] = []
        for i, (mode, name, example) in enumerate(kinds()):
            tile = KindTile(mode, name, example, self)
            tile.clicked.connect(lambda __=False, m=mode: self._select(m))
            tile.chosen.connect(self._pick)
            grid.addWidget(tile, i // 3, i % 3)
            self.tiles.append(tile)
        w.addLayout(grid)
        self.pages.append(what)
        v.addWidget(what)

        # step 2, for a picture: where it comes from
        src = QWidget()
        s = QVBoxLayout(src)
        s.setContentsMargins(0, 0, 0, 0)
        s.setSpacing(12)
        # its words depend on the kind picked: _show_texts() fills them in
        self.src_title = title_label("")
        s.addWidget(self.src_title)
        self.src_hint = hint_label(" ")
        self.src_hint.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        s.addSpacing(TITLE_GAP - s.spacing())
        s.addWidget(self.src_hint)
        row = QHBoxLayout()
        row.setSpacing(12)
        self.paste_art = Picture("copy")
        self.tile_paste = Tile(_("Paste it"), "", self.paste_art, self)
        self.tile_paste.clicked.connect(self._paste)
        row.addWidget(self.tile_paste)
        self.tile_drop = DropTile(_("Drop it here"), "", self)
        self.tile_drop.clicked.connect(self._choose)
        row.addWidget(self.tile_drop)
        self.tile_cut = Tile("", "", Picture("crop"), self)
        self.tile_cut.clicked.connect(lambda: self._done(CUT))
        row.addWidget(self.tile_cut)
        s.addLayout(row)
        self.pages.append(src)
        v.addWidget(src)
        QShortcut(QKeySequence.StandardKey.Paste, self, self._paste)
        QApplication.clipboard().dataChanged.connect(self._show_clipboard)
        self._show_clipboard()

        foot = QHBoxLayout()
        foot.setSpacing(8)
        self.btn_back = QPushButton(_("Back"))
        self.btn_back.setProperty("quiet", True)
        icons.set_icon(self.btn_back, "back", size=14)
        self.btn_back.clicked.connect(lambda: self._show(0))
        foot.addWidget(self.btn_back)
        foot.addStretch(1)
        self.btn_next = QPushButton(_("Continue"))
        self.btn_next.setObjectName("primary")
        self.btn_next.setDefault(True)
        self.btn_next.setEnabled(False)          # until a tile is picked
        self.btn_next.clicked.connect(lambda: self.picked and self._pick(self.picked))
        foot.addWidget(self.btn_next)
        cancel = QPushButton(_("Cancel"))
        cancel.clicked.connect(self.reject)
        foot.addWidget(cancel)
        v.addLayout(foot)
        self._show(0)

    def _show(self, page: int):
        """A step, the pop-up as tall as that step needs."""
        self.page = page
        for i, w in enumerate(self.pages):
            w.setVisible(i == page)
        self.btn_back.setVisible(page == 1)
        self.btn_next.setVisible(page == 0)
        self.adjustSize()

    def _copied(self) -> QImage:
        """The picture copied now (null if none): itself, or a copied picture file."""
        cb = QApplication.clipboard()
        img = cb.image()
        if img.isNull():
            files = DropTile._files(cb.mimeData())
            if files:
                img = QImage(files[0])
        return img

    def _game_shot(self) -> bool:
        """Step 2 wants a picture of the whole game (a bar, a chat line, everything
        still), not of the thing to look for."""
        return self.picked is not None and self.picked not in PICTURE_KINDS

    def _show_texts(self):
        """Step 2's words for the kind picked."""
        texts = step2_texts(self.picked or "appear")
        self.src_title.setText(texts["title"])
        self.src_hint.setText(texts["hint"])
        self.tile_drop.line.setText(texts["drop"])
        self.tile_cut.name.setText(texts["cut"])
        self.tile_cut.setAccessibleName(texts["cut"])
        self.tile_cut.line.setText(texts["cut_line"])
        self.tile_cut.setToolTip(texts["cut_line"])
        self._show_clipboard()

    def _show_clipboard(self):
        img = self._copied()
        if img.isNull():
            self.paste_art.show_icon()
            self.tile_paste.line.setText(
                _("Nothing copied yet. Click the game, press Alt+Print Screen, then click "
                  "here (or Ctrl+V).") if self._game_shot() else
                _("Nothing copied yet. Right-click a picture on the web, Copy image, then "
                  "click here (or Ctrl+V)."))
        else:
            self.paste_art.show_image(img)
            self.tile_paste.line.setText(_("You've copied this picture: click to use it (or "
                                           "Ctrl+V)."))

    def _select(self, mode: str):
        """A tile was clicked: it's the one picked, Continue goes on with it."""
        self.picked = mode
        self.btn_next.setEnabled(True)

    def _pick(self, mode: str):
        """Go on with `mode`: to where the picture comes from, or done."""
        self.picked = mode
        for tile in self.tiles:
            if tile.mode == mode:
                tile.setChecked(True)
        self._show_texts()
        self._show(1)

    def _paste(self):
        if self.page != 1:
            return
        if self._copied().isNull():
            self.tile_paste.line.setText(
                _("There's no picture copied. Click the game and press Alt+Print Screen "
                  "first.") if self._game_shot() else
                _("There's no picture copied. Right-click a picture on the web and pick Copy "
                  "image first."))
            return
        self._done(PASTE)

    def _choose(self):
        paths, __ = QFileDialog.getOpenFileNames(
            self, _("Pictures to look for"), str(Path.home()),
            _("Pictures") + " (" + " ".join("*" + e for e in EXTS) + ")")
        if paths:
            self.use_files(paths)

    def use_files(self, paths: list[str]):
        self.paths = list(paths)
        self._done(FILE)

    def use_image(self, img: QImage):
        self.image = img
        self._done(FILE)

    def _done(self, source: str):
        self.source = source
        self.accept()
