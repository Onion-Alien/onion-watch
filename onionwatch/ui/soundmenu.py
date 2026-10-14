"""The "+" after Play on a trigger card: the sounds to add, with a search box and (when
the host sorts its sounds into categories, as Onion Board does) a category list over
them, and "Choose a sound file" under them. It's a QComboBox to everything else (its
items are the sounds, `activated` says which was picked); only its open list is this
menu."""
from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import (QComboBox, QFrame, QHBoxLayout, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QPushButton, QVBoxLayout, QWidget)

from onionwatch import theme
from onionwatch.i18n import _
from onionwatch.ui import icons
from onionwatch.wheelguard import no_wheel

WIDTH = 300            # the menu's width, at least
LIST_ROWS = 10         # sounds shown before it scrolls

Groups = list[tuple[str, list[str]]]     # (category name, its sound ids), in tab order


def matches(name: str, words: list[str]) -> bool:
    """Every word typed is somewhere in the name (any case)."""
    low = name.casefold()
    return all(w in low for w in words)


def menu_css() -> str:
    t = theme.T
    return (f"QFrame#soundmenu {{ background: {t['card']}; border: 1px solid {t['border']};"
            " border-radius: 10px; }"
            f"QFrame#soundmenu QListWidget {{ background: {t['inset']}; border: none;"
            " border-radius: 8px; padding: 2px; }"
            "QFrame#soundmenu QListWidget::item { padding: 2px 6px; border-radius: 6px; }"
            f"QFrame#soundmenu QListWidget::item:selected {{ background: {t['accent']};"
            f" color: {t['on_accent']}; }}"
            "QFrame#soundmenu QListWidget::item:hover:!selected {"
            f" background: {t['btn_hover']}; }}"
            f"QFrame#soundmenu QLabel#hint {{ color: {t['muted']}; padding: 8px; }}"
            "QFrame#soundmenu QPushButton { text-align: left; }")


class SoundMenu(QFrame):
    """The open list: search, category, the sounds, "Choose a sound file". `picked(sid)`
    once one is clicked (or Enter); the FILE id for "Choose a sound file"."""

    last_group = ""          # the category picked last time: the next menu opens on it

    def __init__(self, sounds: list[tuple[str, str]], groups: Groups, taken: set[str],
                 file_id: str, picked: Callable[[str], None], parent: QWidget | None = None):
        super().__init__(parent, Qt.WindowType.Popup)
        self.setObjectName("soundmenu")
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setStyleSheet(menu_css())
        self.sounds = sounds
        self.groups = {name: set(ids) for name, ids in groups}
        self.taken = taken
        self.file_id = file_id
        self._picked = picked
        v = QVBoxLayout(self)
        v.setContentsMargins(8, 8, 8, 8)
        v.setSpacing(6)
        top = QHBoxLayout()
        top.setSpacing(6)
        self.search = QLineEdit()
        self.search.setPlaceholderText(_("Search sounds"))
        self.search.setClearButtonEnabled(True)
        self.search.addAction(icons.icon("search", "muted"),
                              QLineEdit.ActionPosition.LeadingPosition)
        self.search.textChanged.connect(self._fill)
        self.search.returnPressed.connect(self._enter)
        self.search.installEventFilter(self)
        top.addWidget(self.search, 1)
        self.category = QComboBox(self)
        self.category.setToolTip(_("Show the sounds of one category"))
        self.category.addItem(_("All sounds"), "")
        for name, __ in groups:
            self.category.addItem(name, name)
        self.category.setCurrentIndex(max(self.category.findData(SoundMenu.last_group), 0))
        no_wheel(self.category)
        self.category.currentIndexChanged.connect(self._on_category)
        top.addWidget(self.category)
        # (made in the menu: shown before it has a parent, it would be a window of
        # its own for a moment, and that closes the menu)
        self.category.setVisible(bool(groups))
        v.addLayout(top)
        self.list = QListWidget()
        self.list.setUniformItemSizes(True)
        self.list.itemClicked.connect(self._on_item)
        self.list.itemActivated.connect(self._on_item)
        v.addWidget(self.list, 1)
        self.empty = QLabel()
        self.empty.setObjectName("hint")
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty.setWordWrap(True)
        v.addWidget(self.empty)
        self.btn_file = QPushButton(_("Choose a sound file"))
        self.btn_file.setProperty("quiet", True)
        icons.set_icon(self.btn_file, "folder", size=14)
        self.btn_file.clicked.connect(lambda: self._pick(self.file_id))
        v.addWidget(self.btn_file)
        self._fill()

    def _on_category(self):
        SoundMenu.last_group = self.category.currentData() or ""
        self._fill()

    def shown(self) -> list[str]:
        """The sound ids the list shows now."""
        return [self.list.item(i).data(Qt.ItemDataRole.UserRole)
                for i in range(self.list.count())]

    def _fill(self):
        words = self.search.text().casefold().split()
        group = self.category.currentData() or ""
        ids = self.groups.get(group) if group else None
        self.list.clear()
        for sid, name in self.sounds:
            if (ids is not None and sid not in ids) or not matches(name, words):
                continue
            item = QListWidgetItem(name)
            item.setData(Qt.ItemDataRole.UserRole, sid)
            if sid in self.taken:          # already on the trigger: shown, not pickable
                item.setFlags(Qt.ItemFlag.NoItemFlags)
                item.setToolTip(_("Already on this trigger"))
            self.list.addItem(item)
        if not self.sounds:
            self.empty.setText(_("No sounds yet: choose a sound file"))
        elif not self.list.count():
            self.empty.setText(_("No sounds match"))
        self.empty.setVisible(not self.list.count())
        self.list.setVisible(bool(self.list.count()))
        first = next((i for i in range(self.list.count())
                      if self.list.item(i).flags() & Qt.ItemFlag.ItemIsEnabled), -1)
        self.list.setCurrentRow(first)
        rows = min(max(self.list.count(), 1), LIST_ROWS)
        self.list.setFixedHeight(rows * self.list.sizeHintForRow(0) + 8 if self.list.count() else 0)
        self.adjustSize()

    def _on_item(self, item: QListWidgetItem):
        if item.flags() & Qt.ItemFlag.ItemIsEnabled:
            self._pick(item.data(Qt.ItemDataRole.UserRole))

    def _enter(self):
        item = self.list.currentItem()
        if item is not None:
            self._on_item(item)

    def eventFilter(self, obj, ev):
        # Up / Down in the search box move through the list: type, arrow, Enter
        if obj is self.search and ev.type() == ev.Type.KeyPress and ev.key() in (
                Qt.Key.Key_Down, Qt.Key.Key_Up, Qt.Key.Key_PageDown, Qt.Key.Key_PageUp):
            self.list.keyPressEvent(ev)
            return True
        return super().eventFilter(obj, ev)

    def _pick(self, sid: str):
        self.close()
        self._picked(sid)

    def open_under(self, w: QWidget):
        """Show it under `w` (above, when there's no room below), the search box ready."""
        self.setMinimumWidth(max(WIDTH, w.width()))
        self.adjustSize()
        at = w.mapToGlobal(QPoint(0, w.height() + 4))
        scr = w.screen().availableGeometry()
        if at.y() + self.height() > scr.bottom():
            at.setY(w.mapToGlobal(QPoint(0, 0)).y() - self.height() - 4)
        at.setX(max(scr.left(), min(at.x(), scr.right() - self.width())))
        self.move(at)
        self.show()
        self.search.setFocus()


class SoundBox(QComboBox):
    """The "+": a combo box whose items are [the + itself, the sounds..., FILE]; opening
    it shows a SoundMenu. `groups()` gives the host's categories (empty: no category
    list); `taken()` the sounds already on the trigger."""

    def __init__(self, file_id: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.file_id = file_id
        self.groups: Callable[[], Groups] = list
        self.taken: Callable[[], set[str]] = set
        self.menu: SoundMenu | None = None

    def sounds(self) -> list[tuple[str, str]]:
        out = []
        for i in range(self.count()):
            sid = self.itemData(i)
            if isinstance(sid, str) and sid and sid != self.file_id and self.itemText(i):
                out.append((sid, self.itemText(i)))
        return out

    def showPopup(self):
        groups = self.groups()       # (the panel's sound_groups: never raises)
        self.menu = menu = SoundMenu(self.sounds(), groups, set(self.taken()), self.file_id,
                                     self._picked, self)
        menu.destroyed.connect(lambda *__: self._forget(menu))   # closed: deleted
        menu.open_under(self)

    def _forget(self, menu: SoundMenu):
        if self.menu is menu:
            self.menu = None

    def hidePopup(self):
        menu, self.menu = self.menu, None
        if menu is not None:
            try:
                menu.close()
            except RuntimeError:     # it closed itself already, and is deleted
                pass
        super().hidePopup()

    def _picked(self, sid: str):
        self.menu = None
        i = self.findData(sid)
        if i >= 0:
            self.activated.emit(i)
