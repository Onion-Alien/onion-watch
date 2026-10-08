"""The language picker: a window of tiles, one per language, each with its first
letters in its own script ("De", "日本", "Ру", "ع") and its own name, plus its name in
the language showing. A search box on top filters them as you type, in any of those
names, English or the code. No flags: Windows doesn't draw flag emoji, and a flag is a
country, not a language. Settings → Appearance → Language opens it.

The same window as Onion Board's (soundboard/ui/langpick.py), plus a first tile for
following Windows' language, which standalone Onion Watch does when none is picked.
Only the standard library and PySide6 here: the add-on may import nothing else."""
from __future__ import annotations

import unicodedata

from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath
from PySide6.QtWidgets import (QDialog, QGridLayout, QLabel, QLineEdit, QPushButton,
                               QScrollArea, QVBoxLayout, QWidget)

from onionwatch import i18n, theme
from onionwatch.i18n import _

COLUMNS = 3            # narrow on purpose: three tiles across is enough to scan
TILE = QSize(168, 70)


# marks the first letters would get wrong: Arabic's would be the article's alef, and
# both Bahasas would read "Ba"; Windows' own tile
MARKS = {"ar": "ع", "id": "In", "ms": "Me", i18n.WINDOWS: "Win"}


def glyph(code: str, own: str) -> str:
    """The tile's mark: the first letters of a language's own name, as many as read as
    one sign (two for most, with Hindi's vowel signs kept on their letter)."""
    if code in MARKS:
        return MARKS[code]
    first = own.split()[0] if own.split() else own
    out = first[:2]
    while len(first) > len(out) and unicodedata.category(first[len(out)]) in ("Mn", "Mc"):
        out = first[:len(out) + 1]   # हि, not ह and a stray vowel sign
    return out


def name_in(code: str, lang: str | None = None) -> str:
    """Language `code`'s name in language `lang` (default: the one showing), from
    CLDR ("Japanisch" in German); the English name where the table hasn't one."""
    from onionwatch.langnames_data import NAMES
    lang = i18n.current() if lang is None else lang
    english = NAMES["en"].get(code, code)
    if lang == i18n.PSEUDO:
        return i18n.pseudo(english)
    return NAMES.get(lang, {}).get(code) or english


def other_name(code: str) -> str:
    """`code`'s name in the language showing ("German" in English), "" when that's
    its own name anyway."""
    return "" if code == i18n.current() else name_in(code)


def _fold(s: str) -> str:
    """Lower case without accents: "espanol" finds Español."""
    return "".join(c for c in unicodedata.normalize("NFKD", s.casefold())
                   if not unicodedata.combining(c))


def search_words(code: str, own: str, other: str = "") -> str:
    english = name_in(code, i18n.ENGLISH) if code else "windows"
    return _fold(" ".join((own, other or other_name(code), english, code)))


def _two_lines(text: str, fm: QFontMetrics, width: int) -> list[str]:
    """`text` on one line, or broken at a space onto two ("Español / (España)"): a
    long name keeps its region instead of losing it to "…"."""
    if fm.horizontalAdvance(text) <= width or " " not in text:
        return [fm.elidedText(text, Qt.ElideRight, width)]
    cut = max((i for i, c in enumerate(text) if c == " "
               and fm.horizontalAdvance(text[:i]) <= width), default=text.index(" "))
    return [fm.elidedText(text[:cut], Qt.ElideRight, width),
            fm.elidedText(text[cut + 1:], Qt.ElideRight, width)]


class LangTile(QPushButton):
    """One language: its mark in a round badge, its own name, its name in the language
    showing underneath. `code` "" is Windows' language (`other`: which one that is)."""

    def __init__(self, code: str, own: str, parent=None, other: str | None = None):
        super().__init__(parent)
        self.code, self.own = code, own
        self.other = other_name(code) if other is None else other
        if self.other.casefold() == own.casefold():
            self.other = ""
        self.mark = glyph(code, own)
        self.words = search_words(code, own, self.other)
        self.setObjectName("themecard")   # the theme previews' frame and checked border
        self.setCheckable(True)
        self.setFixedSize(TILE)
        self.setCursor(Qt.PointingHandCursor)
        self.setAccessibleName(f"{own} {self.other}".strip())
        # each tile in its own direction: Arabic reads right to left in an English window
        # (Windows' tile is in the language showing)
        self.setLayoutDirection(Qt.RightToLeft if i18n.is_rtl(code or None)
                                else Qt.LeftToRight)

    def paintEvent(self, e):
        super().paintEvent(e)
        t = theme.T
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        rtl = self.layoutDirection() == Qt.RightToLeft
        h = self.height()
        badge = QRectF(self.width() - 12 - 38 if rtl else 12, (h - 38) / 2, 38, 38)
        path = QPainterPath()
        path.addEllipse(badge)
        p.fillPath(path, QColor(t["accent"] if self.isChecked() else t["card_hi"]))
        f = QFont(self.font())
        f.setBold(True)
        f.setPointSizeF(f.pointSizeF() * (1.0 if len(self.mark) > 2
                                          else 1.25 if len(self.mark) > 1 else 1.45))
        p.setFont(f)
        p.setPen(QColor(t["on_accent"] if self.isChecked() else t["text_hi"]))
        p.drawText(badge, Qt.AlignCenter, self.mark)
        text = QRectF(12, 0, self.width() - 12 - 38 - 22, h) if rtl \
            else QRectF(badge.right() + 10, 0, self.width() - badge.right() - 20, h)
        align = (Qt.AlignRight if rtl else Qt.AlignLeft) | Qt.AlignAbsolute | Qt.AlignVCenter
        bold = QFont(self.font())
        bold.setBold(True)
        small = QFont(self.font())
        small.setPointSizeF(small.pointSizeF() * 0.88)
        bfm, sfm = QFontMetrics(bold), QFontMetrics(small)
        width = int(text.width())
        lines = [(own, bold, t["text"]) for own in _two_lines(self.own, bfm, width)]
        if self.other:
            lines.append((sfm.elidedText(self.other, Qt.ElideRight, width), small, t["muted"]))
        heights = [QFontMetrics(f).height() for __, f, __ in lines]
        if sum(heights) > h - 6 and len(lines) == 3:   # tall script: the name on one line
            lines[:2] = [(bfm.elidedText(self.own, Qt.ElideRight, width), bold, t["text"])]
            heights[:2] = [bfm.height()]
        y = (h - sum(heights)) / 2
        for (line, font, colour), lh in zip(lines, heights):
            p.setFont(font)
            p.setPen(QColor(colour))
            p.drawText(QRectF(text.left(), y, text.width(), lh), align, line)
            y += lh
        p.end()


class LanguageDialog(QDialog):
    """Pick a language: `picked` is the code clicked (None when closed with ✕/Esc; ""
    is Windows' language, offered when `windows` is True)."""
    chosen = Signal(str)

    def __init__(self, parent=None, current: str | None = None, windows: bool = True):
        super().__init__(parent)
        self.setWindowTitle(_("Language"))
        self.setWindowFlag(Qt.WindowContextHelpButtonHint, False)
        self.picked: str | None = None
        current = i18n.current() if current is None else current
        v = QVBoxLayout(self)
        v.setContentsMargins(16, 16, 16, 16)
        v.setSpacing(12)
        self.search = QLineEdit()
        self.search.setPlaceholderText(_("Search languages…"))
        self.search.setClearButtonEnabled(True)
        self.search.setAccessibleName(_("Search languages"))
        self.search.textChanged.connect(self._filter)
        self.search.returnPressed.connect(self._pick_first)
        v.addWidget(self.search)
        holder = QWidget()
        self.grid = QGridLayout(holder)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(8)
        self.grid.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        english, *rest = i18n.available()
        self.tiles: list[LangTile] = []
        if windows:
            win = i18n.resolve(i18n.WINDOWS)
            self.tiles.append(LangTile(i18n.WINDOWS, _("Windows' language"),
                                       other=name_in(win, win)))
        for code, own in [english, *sorted(rest, key=lambda c: _fold(c[1]))]:
            self.tiles.append(LangTile(code, own))
        for tile in self.tiles:
            tile.setChecked(tile.code == current)
            tile.clicked.connect(lambda __=False, c=tile.code: self._pick(c))
        self.none = QLabel()
        self.none.setObjectName("hint")
        self.none.setAlignment(Qt.AlignCenter)
        self.none.setWordWrap(True)
        self.none.hide()
        self._place(self.tiles)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setWidget(holder)
        width = COLUMNS * TILE.width() + (COLUMNS - 1) * 8
        scroll.setFixedWidth(width + scroll.verticalScrollBar().sizeHint().width() + 4)
        v.addWidget(scroll, 1)
        v.addWidget(self.none)
        self.resize(scroll.width() + 32, 520)
        self.search.setFocus()   # type straight away

    def _place(self, tiles):
        for t in self.tiles:
            self.grid.removeWidget(t)
            t.hide()
        for i, t in enumerate(tiles):
            self.grid.addWidget(t, i // COLUMNS, i % COLUMNS)
            t.show()

    def visible_tiles(self) -> list[LangTile]:
        return [t for t in self.tiles if not t.isHidden()]

    def _filter(self, text: str):
        want = _fold(text.strip())
        shown = [t for t in self.tiles if want in t.words] if want else self.tiles
        self._place(shown)
        self.none.setText(_("No language matches “{text}”", text=text.strip()))
        self.none.setVisible(not shown)

    def _pick_first(self):
        shown = self.visible_tiles()
        if shown:
            self._pick(shown[0].code)

    def _pick(self, code: str):
        self.picked = code
        for t in self.tiles:
            t.setChecked(t.code == code)
        self.chosen.emit(code)
        self.accept()
