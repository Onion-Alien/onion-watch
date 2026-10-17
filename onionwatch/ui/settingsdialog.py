"""Settings, laid out like Onion Board's: a list of categories on the left, a page of
cards for each on the right, Done at the bottom. Audio (where the alerts play,
how loud), Alerts (a Windows notification too, closing to the tray), Appearance (the
language, then the themes, the highlight colour and Textured / Plain, as Onion
Board's), Updates and privacy (the daily update check, the anonymous usage count) and
About (the version, Send feedback / Report a problem).
Every change applies straight away, but a new language only shows once Onion Watch
restarts (Restart now)."""
from __future__ import annotations

import math
import os
import threading
import time
import webbrowser

from PySide6.QtCore import QDate, QLocale, QPointF, QRectF, QSize, Qt, QTimer
from PySide6.QtGui import (QBrush, QColor, QFont, QFontMetricsF, QImage, QLinearGradient,
                           QPainter, QPainterPath, QPen, QPixmap)
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QColorDialog, QComboBox, QDialog,
                               QFrame, QGridLayout, QHBoxLayout, QLabel, QLayout,
                               QListWidget, QListWidgetItem, QPushButton, QRadioButton,
                               QScrollArea, QSlider, QStackedWidget, QVBoxLayout, QWidget)

from onionwatch import __version__, feedback, i18n, theme
from onionwatch.sounds import DEFAULT_SOUND
from onionwatch.style import owl
from onionwatch.ui import fit, icons
from onionwatch.ui.panel import hint_label
from onionwatch.wheelguard import no_wheel
from onionwatch.i18n import _


def group_label(group: str) -> str:
    """A theme group's name (theme.GROUPS) in the current language."""
    return {"Classic": _("Classic"), "Colourful": _("Colourful"), "Wild": _("Wild"),
            "Meme": _("Meme")}.get(group, group)


_tiles: dict[str, QBrush | None] = {}


def _tile(name: str) -> QBrush | None:
    """A theme's texture as a brush for its preview card (None: the theme has none)."""
    if name not in _tiles:
        kind = theme.THEMES[name].get("texture", "")
        _tiles[name] = (QBrush(QPixmap.fromImage(theme.texture_image(kind, theme.THEMES[name])))
                        if kind in theme.TEXTURES else None)
    return _tiles[name]


_hoots: dict[tuple[str, float], QPixmap] = {}
HOOT_H = 58     # Hoot's height on a theme card
HOOT_ROOM = 10  # room above him: a tall hat reaches past his canvas


def _hoot(name: str, dpr: float) -> QPixmap:
    """Hoot as he looks in theme `name` (its look and outfit), for its card, HOOT_ROOM
    taller than him so nothing on top of his head is cut off."""
    key = (name, dpr)
    if key not in _hoots:
        w, room, h = HOOT_H * owl.W / owl.H * dpr, HOOT_ROOM * dpr, HOOT_H * dpr
        img = QImage(math.ceil(w), math.ceil(room + h), QImage.Format.Format_ARGB32_Premultiplied)
        img.fill(Qt.GlobalColor.transparent)
        p = QPainter(img)
        with theme.previewing(name):
            owl.draw_owl(p, QRectF(0, room, w, h))
        p.end()
        img.setDevicePixelRatio(dpr)
        _hoots[key] = QPixmap.fromImage(img)
    return _hoots[key]


WAVE_S = 1.7   # his hello when the mouse comes onto a card, seconds


def wave_pose(t: float) -> dict | None:
    """Hoot's hello `t` seconds after the mouse came onto his card (None: done): a little
    hop, then three waves of his wing with a happy face (Bun's on Onion Board's cards)."""
    if not 0 <= t < WAVE_S:
        return None
    k = min(1.0, t / 0.2, (WAVE_S - t) / 0.2)   # (the wing swings in and out softly)
    happy = 0.35 <= t < 1.3
    return {"hop": 3.5 * math.sin(math.pi * t / 0.3) if t < 0.3 else 0.0,
            "wave": k * math.sin(2 * math.pi * 1.9 * (t - 0.15)),
            "blink": 1.0 if happy else 0.0, "beak": 0.4 if happy else 0.0}


def limited_tip(name: str) -> str:
    """A limited-edition theme card's tooltip: until when it can be had, or that it's
    kept (as Onion Board's)."""
    if name in theme.kept:
        return _("Limited edition: this one's yours to keep.")
    last = theme.LIMITED[name]
    day = QLocale().toString(QDate(last.year, last.month, last.day), "d MMMM")
    return _("Limited edition: use it by {date} and it's yours to keep. After that it's "
             "gone for good.", date=day)


def paint_limited_tag(p: QPainter, x: float, y: float, font: QFont, max_w: float) -> None:
    """The "Limited edition" tag (as Onion Board's): a glowing pumpkin-to-purple ribbon
    with a sparkle, its top-left corner at (x, y), no wider than `max_w`."""
    text = _("Limited edition")
    f = QFont(font)
    f.setFamily(theme.FONT)
    f.setBold(True)
    f.setPointSizeF(6.8)
    fm = QFontMetricsF(f)
    star, pad, h = 9.0, 6.0, 16.0
    text = fm.elidedText(text, Qt.TextElideMode.ElideRight, max_w - 2 * pad - star - 3)
    w = min(max_w, 2 * pad + star + 3 + fm.horizontalAdvance(text))
    tag = QRectF(x, y, w, h)
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    for grow, alpha in ((3.0, 40), (1.5, 70)):   # its glow
        p.setBrush(QColor(255, 117, 24, alpha))
        p.drawRoundedRect(tag.adjusted(-grow, -grow, grow, grow), h / 2 + grow, h / 2 + grow)
    fill = QLinearGradient(tag.topLeft(), tag.topRight())
    fill.setColorAt(0, QColor("#ff7518"))
    fill.setColorAt(0.55, QColor("#e0469a"))
    fill.setColorAt(1, QColor("#8f3ff0"))
    p.setBrush(fill)
    p.setPen(QPen(QColor(255, 255, 255, 120), 1))
    p.drawRoundedRect(tag, h / 2, h / 2)
    shine = QLinearGradient(tag.topLeft(), tag.bottomLeft())   # glossy top half
    shine.setColorAt(0, QColor(255, 255, 255, 90))
    shine.setColorAt(0.5, QColor(255, 255, 255, 0))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(shine)
    p.drawRoundedRect(tag.adjusted(1, 1, -1, -h / 2), h / 2 - 1, h / 2 - 1)
    cx, cy, r = x + pad + star / 2, y + h / 2, star / 2   # a four-point sparkle
    spark = QPainterPath(QPointF(cx, cy - r))
    for px, py in ((cx + r * 0.28, cy - r * 0.28), (cx + r, cy), (cx + r * 0.28, cy + r * 0.28),
                   (cx, cy + r), (cx - r * 0.28, cy + r * 0.28), (cx - r, cy),
                   (cx - r * 0.28, cy - r * 0.28), (cx, cy - r)):
        spark.lineTo(QPointF(px, py))
    p.setBrush(QColor("#fff3b0"))
    p.drawPath(spark)
    p.setFont(f)
    at = QRectF(x + pad + star + 3, y, w, h)
    left = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
    p.setPen(QColor(0, 0, 0, 90))   # a soft drop shadow under the white text
    p.drawText(at.translated(0, 1), left, text)
    p.setPen(QColor("#ffffff"))
    p.drawText(at, left, text)
    p.restore()


class ThemeCard(QPushButton):
    """A clickable mini-preview of a theme (the same as Onion Board's): its colours, and
    with Textured on, its pattern on the panels and its glow behind them. Hoot stands in
    its corner dressed for the theme, and waves when the mouse comes onto it."""

    def __init__(self, name: str):
        super().__init__()
        self.name = name
        self.setObjectName("themecard")
        self.setCheckable(True)
        self.setFixedSize(QSize(150, 112))   # (ThemeGrid widens it to fill its column)
        self.setCursor(Qt.PointingHandCursor)
        self.setAccessibleName(name)
        if name in theme.LIMITED:
            self.setToolTip(limited_tip(name))
            self.setAccessibleDescription(_("Limited edition"))
        self._hello = None   # when Hoot started waving (time.monotonic), None: he isn't
        self._tick = QTimer(self)
        self._tick.setInterval(33)
        self._tick.timeout.connect(self._step)

    def enterEvent(self, e):
        super().enterEvent(e)
        if self._hello is None:   # (once per visit: no restart)
            self._hello = time.monotonic()
            self._tick.start()

    def _step(self):
        if self._hello is not None and wave_pose(time.monotonic() - self._hello) is None:
            self._hello = None
            self._tick.stop()
        self.update()

    def paintEvent(self, e):
        super().paintEvent(e)   # frame + checked border from the stylesheet
        t = theme.THEMES[self.name]
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(8, 8, -8, -30)
        win = QPainterPath()
        win.addRoundedRect(r, 8, 8)
        p.fillPath(win, QColor(t["bg"]))
        tile = _tile(self.name) if theme.textures_on else None
        if theme.textures_on:
            p.save()
            p.setClipPath(win)
            theme.paint_window_bg(p, r, r.topLeft(), r.width(), r.height(), tk=t)
            p.restore()
        # side panel and cards, in the theme's own colours
        p.setPen(Qt.NoPen)
        for brush in (QColor(t["panel"]), tile):
            if brush is not None:
                p.setBrush(brush)
                p.drawRoundedRect(QRectF(r.right() - 44, r.top() + 6, 38, r.height() - 12), 5, 5)
        # two columns of cards across what the side panel leaves (a wider card: wider ones)
        pw = max(40.0, (r.width() - 44 - 7 - 6 - 4) / 2)   # (40: the old fixed size)
        for i, col in enumerate(("#7c5cff", "#ff5c8a", "#1fb6ff", "#13ce66")):
            x = r.left() + 7 + (i % 2) * (pw + 4)
            y = r.top() + 7 + (i // 2) * 34
            for brush in (QColor(t["card"]), tile):
                if brush is not None:
                    p.setBrush(brush)
                    p.drawRoundedRect(QRectF(x, y, pw, 28), 5, 5)
            p.setBrush(QColor(col))
            p.drawRoundedRect(QRectF(x + 5, y + 5, 10, 3), 1.5, 1.5)
        # Hoot on the side panel, standing at its foot: the theme's look and outfit, so
        # you can see who you'd get
        hoot = _hoot(self.name, self.devicePixelRatioF() or 1.0)
        hw, hh = hoot.width() / hoot.devicePixelRatio(), hoot.height() / hoot.devicePixelRatio()
        spot = QRectF(r.right() - 3 - hw, r.bottom() - 1 - HOOT_H, hw, HOOT_H)
        pose = wave_pose(time.monotonic() - self._hello) if self._hello is not None else None
        if pose is None:
            p.drawPixmap(QRectF(spot.left(), spot.bottom() - hh, hw, hh), hoot, QRectF(hoot.rect()))
        else:   # saying hello: drawn live in his theme
            with theme.previewing(self.name):
                owl.draw_owl(p, spot.translated(0, -pose.pop("hop")), **pose)
        # name, in the theme's own font
        p.setPen(QColor(theme.T["text"]))
        f = QFont(self.font())
        f.setFamily(t.get("font", theme.FONT))
        f.setBold(True)
        p.setFont(f)
        p.drawText(QRectF(10, self.height() - 28, self.width() - 20, 22),
                   Qt.AlignLeft | Qt.AlignVCenter, self.name)
        if self.name in theme.LIMITED:   # just inside the preview's top-left corner
            paint_limited_tag(p, r.left() + 5, r.top() + 5, self.font(), r.width() - 10)
        p.end()


class ThemeGrid(QWidget):
    """Keep previews their readable size, using as many columns as fit."""

    def __init__(self, cards):
        super().__init__()
        self.cards = cards
        self.columns = 0
        self.grid = QGridLayout(self)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(12)
        self.grid.setSizeConstraint(QLayout.SetNoConstraint)
        self._reflow(1)

    def minimumSizeHint(self):
        return QSize(150, 112)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # as many columns as fit, even past this group's cards, so every group's cards
        # line up; they widen to share the width left over, with the same 12 px gap
        # across as down (as Onion Board's)
        columns = max(1, (self.width() + 12) // 162)
        self._reflow(columns)
        width = max(150, (self.width() - 12 * (columns - 1)) // columns)
        for card in self.cards:
            card.setFixedWidth(width)

    def _reflow(self, columns):
        if columns == self.columns:
            return
        for col in range(self.columns + 1):
            self.grid.setColumnStretch(col, 0)
        while self.grid.count():
            self.grid.takeAt(0)
        for i, card in enumerate(self.cards):
            self.grid.addWidget(card, i // columns, i % columns, Qt.AlignLeft)
        self.grid.setColumnStretch(columns, 1)
        self.columns = columns
        self.updateGeometry()


def _button_row() -> QHBoxLayout:
    """Buttons as wide as their text, from the start of the line."""
    row = QHBoxLayout()
    row.setSpacing(10)
    return row


class SettingsDialog(QDialog):
    WIDTH = 820    # categories + a page three theme previews wide

    def __init__(self, win, page: str = "audio"):
        super().__init__(win)
        fit.watch(self)          # grows to fit its (translated) text
        self.win = win
        self.setWindowTitle(_("Onion Watch settings"))
        self.setMinimumSize(620, 420)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 14)
        pages = (("audio", _("Audio"), "volume", self._audio),
                 ("alerts", _("Alerts"), "bell", self._alerts),
                 ("appearance", _("Appearance"), "palette", self._appearance),
                 ("updates", _("Updates and privacy"), "shield", self._updates),
                 ("about", _("About"), "star", self._about))
        self.categories = QListWidget()
        self.categories.setObjectName("settingscategories")
        self.categories.setAccessibleName(_("Settings categories"))
        self.categories.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.categories.setFixedWidth(196)
        self.pages = QStackedWidget()
        # room for a name beside its icon (borders, padding and the gap take the rest)
        room = self.categories.width() - self.categories.iconSize().width() - 24
        fm = self.categories.fontMetrics()
        for _key, title, icon, build in pages:
            self.pages.addWidget(self._scroll(build()))
            item = QListWidgetItem(icons.icon(icon, selected="on_accent"), title)
            item.setData(Qt.UserRole, icon)
            if fm.horizontalAdvance(title) > room:   # only a name cut short needs a tip
                item.setToolTip(title)
            item.setSizeHint(QSize(180, 38))
            self.categories.addItem(item)
        self.categories.currentRowChanged.connect(self.pages.setCurrentIndex)
        keys = self.page_keys = [p[0] for p in pages]
        self.categories.setCurrentRow(keys.index(page) if page in keys else 0)
        content = QHBoxLayout()
        content.setSpacing(16)
        content.addWidget(self.categories)
        content.addWidget(self.pages, 1)
        lay.addLayout(content, 1)
        done = QPushButton(_("Done"))
        done.setObjectName("primary")
        done.setDefault(True)
        done.clicked.connect(self.accept)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(done)
        lay.addLayout(row)
        self.btn_done = done
        win.update_found.connect(self._on_checked)
        self._on_volume(self.volume.value())
        self._initial_size()

    def show_page(self, key: str):
        self.categories.setCurrentRow(self.page_keys.index(key))

    # ------------------------------------------------------------------ building blocks
    @staticmethod
    def _scroll(page: QWidget) -> QScrollArea:
        """Pages scroll: a tall one is never squashed on a small screen."""
        for label in page.findChildren(QLabel):
            label.setWordWrap(True)
        sa = QScrollArea()
        sa.setWidgetResizable(True)
        sa.setFrameShape(QScrollArea.NoFrame)
        sa.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        sa.setWidget(page)
        return sa

    @staticmethod
    def _card(title: str, hint: str = ""):
        card = QFrame()
        card.setObjectName("card")
        v = QVBoxLayout(card)
        v.setContentsMargins(14, 12, 14, 14)
        v.setSpacing(8)
        t = QLabel(title.upper())
        t.setObjectName("section")
        v.addWidget(t)
        if hint:
            v.addWidget(hint_label(hint))
        return card, v

    @staticmethod
    def _page():
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 12, 0)
        v.setSpacing(12)
        return w, v

    def _initial_size(self):
        """Open big enough for the tallest page, as far as the screen allows."""
        need = max(self.pages.widget(i).widget().layout().totalSizeHint().height()
                   for i in range(self.pages.count()))
        height, width = min(need + 90, 720), self.WIDTH
        screen = self.screen()
        if screen is not None:
            avail = screen.availableGeometry()
            width, height = min(width, avail.width() - 40), min(height, avail.height() - 60)
        self.resize(max(width, self.minimumWidth()), max(height, self.minimumHeight()))

    # ------------------------------------------------------------------ pages
    def _audio(self):
        w, v = self._page()
        win, cfg = self.win, self.win.cfg
        card, cv = self._card(_("SOUND"), _("Alerts play on your speakers or headphones — "
                                            "pick the ones you'll hear when you're away from "
                                            "the game."))
        self.device = QComboBox()
        self.device.addItem(_("Windows default"), "")
        for name in win.player.devices():
            self.device.addItem(name, name)
        i = self.device.findData(cfg.device)
        if i < 0 and cfg.device:
            self.device.addItem(_("{device} (not plugged in)", device=cfg.device), cfg.device)
            i = self.device.count() - 1
        self.device.setCurrentIndex(max(i, 0))
        self.device.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        self.device.currentIndexChanged.connect(self._on_device)
        no_wheel(self.device)
        row = QHBoxLayout()
        row.addWidget(self.device)
        row.addStretch(1)
        cv.addLayout(row)
        row = QHBoxLayout()
        row.addWidget(QLabel(_("Volume")))
        self.volume = QSlider(Qt.Horizontal)
        self.volume.setRange(0, 100)
        self.volume.setValue(round(cfg.volume * 100))
        self.volume.valueChanged.connect(self._on_volume)
        row.addWidget(self.volume, 1)
        self.vol_label = QLabel()
        self.vol_label.setMinimumWidth(40)
        row.addWidget(self.vol_label)
        self.btn_test = QPushButton(_("Test"))
        icons.set_icon(self.btn_test, "play", size=14)
        self.btn_test.clicked.connect(
            lambda: win.player.play(win.library.load(DEFAULT_SOUND)))
        row.addWidget(self.btn_test)
        cv.addLayout(row)
        self.error = hint_label("")
        theme.set_tone(self.error, "warn")
        self.error.hide()
        cv.addWidget(self.error)
        v.addWidget(card)
        v.addStretch(1)
        return w

    def _alerts(self):
        w, v = self._page()
        cfg = self.win.cfg
        card, cv = self._card(_("WHEN A TRIGGER GOES OFF"))
        self.notify = QCheckBox(_("Show a Windows notification too"))
        self.notify.setChecked(cfg.notify)
        self.notify.toggled.connect(lambda on: self._set("notify", on))
        cv.addWidget(self.notify)
        self.tray = QCheckBox(_("Closing the window keeps watching from the tray"))
        self.tray.setChecked(cfg.tray)
        self.tray.toggled.connect(lambda on: self._set("tray", on))
        cv.addWidget(self.tray)
        v.addWidget(card)
        v.addStretch(1)
        return w

    def _appearance(self):
        """Language on its own, then one box for the look with two tabs, as in Onion
        Board's Settings: Themes (Textured or Plain on top, then the cards) and Colour."""
        w, v = self._page()
        v.addWidget(self._language_card())
        self.theme_cards: list[ThemeCard] = []
        themes, tv = self._card(_("Themes"))
        tv.setSpacing(6)
        style = self._texture_card()
        style.setObjectName("lookpage")   # a part of the tab: flat, its title a heading
        if (lay := style.layout()) is not None:
            lay.setContentsMargins(0, 0, 0, 0)
        tv.addWidget(style)
        tv.addSpacing(14)
        for group, names in theme.groups():
            head = QLabel(group_label(group))
            head.setObjectName("section")
            tv.addWidget(head)
            cards = []
            for name in names:
                c = ThemeCard(name)
                c.setChecked(name == theme.current_name)
                c.clicked.connect(lambda __=False, n=name: self._pick_theme(n))
                cards.append(c)
                self.theme_cards.append(c)
            tv.addWidget(ThemeGrid(cards))
            tv.addSpacing(8)
        pages = [(_("Themes"), themes), (_("Colour"), self._highlight_card())]
        v.addWidget(self._look_box(pages))
        v.addStretch(1)
        return w

    def _look_box(self, pages) -> QFrame:
        """One card holding `pages` [(tab name, card)], a tab row on top showing one at a
        time (the others hidden, so the box is only as tall as the one showing)."""
        box = QFrame()
        box.setObjectName("card")
        bv = QVBoxLayout(box)
        bv.setContentsMargins(14, 12, 14, 14)
        bv.setSpacing(10)
        row = _button_row()
        bv.addLayout(row)
        group = QButtonGroup(box)
        tabs = []
        for i, (name, card) in enumerate(pages):
            card.setObjectName("lookpage")   # not a card of its own: flat inside the box
            lay = card.layout()
            lay.setContentsMargins(0, 0, 0, 0)
            lay.itemAt(0).widget().hide()   # its title: the tab says it
            b = QPushButton(name)
            b.setObjectName("voicetab")    # the same tabs as Onion Board's
            b.setCheckable(True)
            group.addButton(b, i)
            row.addWidget(b)
            bv.addWidget(card)
            tabs.append(b)
        row.addStretch(1)
        self.look_shown = 0   # the tab showing

        def show(i):
            tabs[i].setChecked(True)
            for j, (__, card) in enumerate(pages):
                card.setVisible(j == i)
            self.look_shown = i
        group.idClicked.connect(show)
        show(0)
        self.look_tabs, self.look_pages, self.look_box = tabs, [c for __, c in pages], box
        return box

    def _texture_card(self) -> QFrame:
        """Textured or Plain: each theme's own pattern on its panels, or flat panels."""
        card, cv = self._card(_("Theme style"),
                              _("Textured gives each theme its own pattern on the panels: "
                                "scanlines, carbon fibre, waves and more. Plain keeps them flat."))
        row = _button_row()
        textured = QRadioButton(_("Textured"))
        plain = QRadioButton(_("Plain"))
        group = QButtonGroup(card)
        for b in (textured, plain):
            group.addButton(b)
            row.addWidget(b)
        row.addStretch(1)
        (textured if self.win.cfg.theme_texture else plain).setChecked(True)
        textured.toggled.connect(self._set_texture)
        self.texture_on, self.texture_off = textured, plain
        cv.addLayout(row)
        return card

    def _set_texture(self, on: bool):
        self.win.set_theme_texture(on)
        for c in self.theme_cards:   # the previews show the pattern and glow, or not
            c.update()

    def _highlight_card(self) -> QFrame:
        """Your own colour for what's on right now (Start watching while it watches),
        kept whatever the theme: for when you like a theme but not its colour."""
        card, cv = self._card(_("Highlight colour"),
                              _("What's switched on (watching for triggers) is shown in the "
                                "theme's colour. Slide to pick your own; it stays when you "
                                "change theme."))
        row = QHBoxLayout()
        row.setSpacing(10)
        swatch = QPushButton(_("On"))   # a switched-on button, as it will look
        swatch.setObjectName("power")
        swatch.setCheckable(True)
        swatch.setChecked(True)
        swatch.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        swatch.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        swatch.setFixedWidth(64)
        swatch.setAccessibleName(_("Highlight colour preview"))
        hue = QSlider(Qt.Orientation.Horizontal)
        hue.setObjectName("hue")
        hue.setRange(0, 359)
        hue.setAccessibleName(_("Highlight colour hue"))
        hue.setToolTip(_("Drag along the rainbow to pick the highlight colour"))
        no_wheel(hue)
        row.addWidget(swatch)
        row.addWidget(hue, 1)
        cv.addLayout(row)
        btns = _button_row()
        more = QPushButton(_("More colours"))
        more.setToolTip(_("Pick any colour, including how strong and how bright it is"))
        reset = QPushButton(_("Theme's colour"))
        reset.setToolTip(_("Go back to each theme's own highlight colour"))
        btns.addWidget(reset)
        btns.addWidget(more)
        btns.addStretch(1)
        cv.addLayout(btns)
        now = QLabel()
        now.setObjectName("hint")
        now.setWordWrap(True)
        cv.addWidget(now)
        self.hue_slider, self.hue_swatch, self.hue_reset, self.hue_now = hue, swatch, reset, now
        self.hue_more = more
        # arrow keys / clicks on the strip come in bursts: apply once they stop
        settle = QTimer(card, singleShot=True, interval=250)
        self.hue_settle = settle

        def own(h: int) -> str:
            """Hue `h` at the strength / brightness of the current colour (a vivid one
            when it's too grey for a hue to show)."""
            c = QColor(theme.T["live"])
            sat, val = c.hsvSaturationF(), c.valueF()
            if sat < 0.35 or val < 0.45:
                sat, val = 0.75, 0.95
            return QColor.fromHsvF(h / 360, sat, val).name()

        def preview(colour: str = ""):
            """Show `colour` on the swatch only (while dragging); "" = what's applied."""
            if colour:
                on = max(("#ffffff", "#111111"), key=lambda c: theme._contrast(c, colour))
                swatch.setStyleSheet(f"QPushButton#power:checked {{ background:{colour}; "
                                     f"border:1px solid {colour}; color:{on}; }}")
            else:
                swatch.setStyleSheet(theme.live_sheet())

        def sync():
            hue.blockSignals(True)
            h = QColor(theme.T["live"]).hsvHue()
            hue.setValue(h if h >= 0 else 0)
            hue.blockSignals(False)
            now.setText(_("Now: your own colour, in every theme.")
                        if theme.live_override else
                        _("Now: {theme}'s own colour.", theme=theme.current_name))
            preview()

        def use(colour: str, btn=None, done: str = "") -> bool:
            settle.stop()
            changed = self.win.set_live_color(colour)
            sync()
            if btn is not None and done:
                self._flash(btn, done)
            return changed

        def moved(h: int):
            preview(own(h))
            if not hue.isSliderDown():
                settle.start()
        hue.valueChanged.connect(moved)
        hue.sliderReleased.connect(lambda: use(own(hue.value())))
        settle.timeout.connect(lambda: use(own(hue.value())))

        def pick():
            c = QColorDialog.getColor(QColor(theme.T["live"]), self, _("Highlight colour"))
            if c.isValid():
                use(c.name(), more, _("✓ Changed"))

        def back():
            if not theme.live_override:
                self._flash(reset, _("✓ Already the theme's"))
            else:
                use("", reset, _("✓ Back to the theme's"))
        more.clicked.connect(pick)
        reset.clicked.connect(back)
        self._sync_highlight = sync
        sync()
        return card

    @staticmethod
    def _flash(btn: QPushButton, text: str, ms: int = 1600):
        """Say `text` on `btn` for a moment, then its own words again (it stays enabled:
        disabling a clicked button moves the focus)."""
        was = btn.property("flash_was") or btn.text()
        btn.setProperty("flash_was", was)
        btn.setMinimumWidth(btn.sizeHint().width())
        btn.setText(text)
        QTimer.singleShot(ms, btn, lambda: (btn.setText(was), btn.setProperty("flash_was", None)))

    def _language_card(self) -> QFrame:
        """The app's language: a button showing the one picked, opening a window of
        language tiles with a search (ui.langpick). The title is in Windows' language
        too, so someone who can't read this page still finds it; what it says about
        restarting is in the language picked."""
        title = _("Language")
        win_code = i18n.resolve(i18n.WINDOWS)
        if win_code not in (i18n.ENGLISH, i18n.PSEUDO, i18n.current()):
            word = i18n.in_language(win_code, lambda: _("Language"))
            title = title if word == title else f"{title} · {word}"
        card, cv = self._card(title)
        pick = QPushButton()
        icons.set_icon(pick, "browser")
        pick.setAccessibleName(_("Language"))
        pick.setToolTip(_("Pick the language Onion Watch is shown in"))
        restart = QPushButton()
        restart.setObjectName("primary")
        restart.clicked.connect(self.win.restart)
        row = _button_row()
        row.addWidget(pick)
        row.addWidget(restart)
        row.addStretch(1)   # buttons as wide as their text, not the card
        cv.addLayout(row)
        note = hint_label("")
        cv.addWidget(note)
        # ONIONWATCH_LANG overrides the setting: a restart wouldn't change anything
        forced = os.environ.get(i18n.ENV) is not None

        def show():
            setting = self.win.cfg.language
            code = i18n.resolve(setting)
            name = i18n.name_of(code)
            shown = name if setting != i18n.WINDOWS \
                else _("Windows' language") + " · " + name
            pick.setText(f"{shown}  ▾")
            later = code != i18n.current() and not forced
            if later:
                text, button = i18n.in_language(code, lambda: (
                    _("Onion Watch shows {name} after a restart.", name=name),
                    _("Restart now")))
                # (RLM: an Arabic line starting with a Latin name still reads right to left)
                note.setText("‏" + text if i18n.is_rtl(code) else text)
                restart.setText(button)
                direction = Qt.RightToLeft if i18n.is_rtl(code) else Qt.LeftToRight
                note.setLayoutDirection(direction)
                note.setAlignment((Qt.AlignRight if i18n.is_rtl(code) else Qt.AlignLeft)
                                  | Qt.AlignAbsolute)
            note.setVisible(later)
            restart.setVisible(later)

        def open_picker():
            from onionwatch.ui.langpick import LanguageDialog
            dlg = LanguageDialog(self, self.win.cfg.language)
            self.lang_dialog = dlg   # (tests reach it while it's open)
            dlg.chosen.connect(lambda code: (self._set("language", code), show()))
            dlg.exec()
            self.lang_dialog = None
            dlg.deleteLater()
        pick.clicked.connect(open_picker)
        show()
        self.lang_button, self.lang_note, self.btn_restart = pick, note, restart
        self.lang_dialog = None
        self.show_language = show
        return card

    def _pick_theme(self, name: str):
        if name != theme.current_name:
            self.win.set_theme(name)
            for i in range(self.categories.count()):
                item = self.categories.item(i)
                item.setIcon(icons.icon(item.data(Qt.UserRole), selected="on_accent"))
            self._sync_highlight()   # the theme's own colour, unless you picked one
        for c in self.theme_cards:
            c.setChecked(c.name == name)
            if c.name in theme.LIMITED:   # picked in time: now it's theirs
                c.setToolTip(limited_tip(c.name))
            c.update()

    def _updates(self):
        w, v = self._page()
        cfg = self.win.cfg
        card, cv = self._card(_("UPDATES AND PRIVACY"))
        self.update_check = QCheckBox(_("Check for new versions"))
        self.update_check.setChecked(cfg.update_check)
        self.update_check.toggled.connect(lambda on: self._set("update_check", on))
        cv.addWidget(self.update_check)
        row = _button_row()
        self.btn_check = QPushButton(_("Check now"))
        icons.set_icon(self.btn_check, "reload")
        self.btn_check.clicked.connect(self._check_now)
        row.addWidget(self.btn_check)
        row.addStretch(1)
        cv.addLayout(row)
        self.check_status = hint_label("")
        self.check_status.hide()
        cv.addWidget(self.check_status)
        row = QHBoxLayout()
        self.usage = QCheckBox(_("Count me in"))
        self.usage.setChecked(cfg.usage_count)
        self.usage.toggled.connect(self._on_usage)
        row.addWidget(self.usage)
        # the eye: what it sends, as a small table (ui/countdialog.py)
        self.count_eye = QPushButton()
        self.count_eye.setFlat(True)
        icons.set_icon(self.count_eye, "eye")
        self.count_eye.setToolTip(_("See what's sent"))
        self.count_eye.setAccessibleName(_("See what's sent"))
        self.count_eye.clicked.connect(self._show_count)
        row.addWidget(self.count_eye)
        row.addStretch(1)
        cv.addLayout(row)
        cv.addWidget(hint_label(_("Anonymous usage stats once a day, to see what to improve. "
                                  "Never your name, IP address or device info.")))
        v.addWidget(card)
        v.addStretch(1)
        return w

    def _on_usage(self, on: bool):
        if not on and self.win.cfg.usage_count:
            # Count me in switched off: one anonymous "opt-out/settings" (usage.opt_out:
            # no ID), then nothing
            from onionwatch import usage
            threading.Thread(target=usage.opt_out, args=("settings",), daemon=True,
                             name="usage-opt-out").start()
        self._set("usage_count", on)

    def _show_count(self):
        from onionwatch.ui import countdialog
        self.count_dialog = countdialog.show(self)

    def _about(self):
        w, v = self._page()
        card, cv = self._card("Onion Watch")
        cv.addWidget(hint_label(_("Onion Watch {version} — it only looks at the screen and "
                                  "plays sounds; it never clicks, types or reads a game's "
                                  "memory.", version=__version__)))
        row = _button_row()
        self.btn_feedback = QPushButton(_("Send feedback"))
        icons.set_icon(self.btn_feedback, "edit")
        self.btn_feedback.setToolTip(_("Opens a short form in your browser (no account)"))
        self.btn_feedback.clicked.connect(
            lambda: webbrowser.open(feedback.feedback_url(__version__)))
        row.addWidget(self.btn_feedback)
        self.btn_problem = QPushButton(_("Report a problem"))
        self.btn_problem.setToolTip(_("Opens a new issue on GitHub in your browser"))
        self.btn_problem.clicked.connect(
            lambda: webbrowser.open(feedback.problem_url(__version__)))
        row.addWidget(self.btn_problem)
        row.addStretch(1)
        cv.addLayout(row)
        v.addWidget(card)
        v.addStretch(1)
        return w

    # ------------------------------------------------------------------ changes
    def _check_now(self):
        self.check_status.setText(_("Checking…"))
        self.check_status.show()
        self.win.check_updates(force=True)

    def _on_checked(self, rel, err: str, force: bool):
        if not force:
            return
        if err:
            self.check_status.setText(_("Couldn't check just now ({err}).", err=err))
        elif rel is None:
            self.check_status.setText(_("You have the newest version ({version}).",
                                        version=__version__))
        else:
            self.check_status.setText(_("Onion Watch {version} is out.", version=rel.version))
        self.check_status.show()

    def _set(self, key: str, value):
        setattr(self.win.cfg, key, value)
        self.win.save_later()

    def _on_device(self, _i: int):
        name = self.device.currentData() or ""
        self.win.player.set_device(name)
        self._set("device", name)
        ok = self.win.player.play(self.win.library.load(DEFAULT_SOUND))
        self.error.setText("" if ok else _("That device couldn't be opened ({error}).",
                                           error=self.win.player.error))
        self.error.setVisible(not ok)

    def _on_volume(self, value: int):
        self.vol_label.setText(f"{value}%")
        self.win.player.volume = value / 100
        self._set("volume", value / 100)
