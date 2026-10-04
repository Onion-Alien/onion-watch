"""The triggers page's categories and profiles (the rules are onionwatch.profiles):
a category's section in the list (a header to fold it, switch it on or off and
open its menu, over its trigger cards) and the Profiles window."""
from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, Qt, Signal
from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QFrame, QHBoxLayout,
                               QLineEdit, QListWidget, QListWidgetItem, QMenu, QPushButton,
                               QVBoxLayout, QWidget, QWidgetItem, QSizePolicy)

from onionwatch import profiles
from onionwatch.profiles import Profile
from onionwatch.ui import icons
from onionwatch.ui.panel import Flow, hint_label, section_label

NAME = Qt.UserRole              # a list item's category name / profile id / exe
TILE = 260                      # px: the least a closed card (a tile in the grid) is wide


def _height(item, w: int) -> int:
    """How tall `item` is at width `w` (its height there, not at its preferred width)."""
    h = item.heightForWidth(w) if item.hasHeightForWidth() else -1
    return max(h if h >= 0 else item.sizeHint().height(), item.minimumSize().height())


class CardGrid(Flow):
    """A category's cards as tiles, as many to a line as fit (like the sound pads):
    a closed card is a tile, all of a line as tall as its tallest. An open card,
    and anything else in it (the "empty" note), has a line of its own, the whole
    width, under the line it would have been on: the closed cards after it fill that
    line first, so no line is cut short (like a picture grid opening a preview)."""

    def insertWidget(self, i: int, w: QWidget):
        self.addChildWidget(w)
        self._items.insert(max(0, min(i, len(self._items))), QWidgetItem(w))
        self.invalidate()

    def columns(self, width: int) -> int:
        return max(1, (width + self._gap) // (TILE + self._gap))

    def _place(self, rect: QRect, move: bool) -> int:
        cols = self.columns(rect.width())
        cw = max(1, (rect.width() - self._gap * (cols - 1)) // cols)
        y, line, under = rect.y(), [], []   # under: open cards waiting for the line to fill

        def put(items, w):
            nonlocal y
            h = max(_height(it, w) for it in items)
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
    search_wanted = Signal(str)
    card_dropped = Signal(str, str, object)  # trigger id, this category, before which id
    drag_at = Signal(QPoint)             # a card is being dragged here (global position)
    MIME = "application/x-onionwatch-trigger"   # (TriggerRow.MIME)

    def __init__(self, name: str):
        super().__init__()
        from onionwatch.ui.triggerspanel import FlowBox, Switch   # (it imports this one)
        self.name = name
        self.built = False              # its cards have been made
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(6)
        self.header = QFrame()
        self.header.setObjectName("transport")   # a panel-coloured strip, like the bar
        header_layout = QHBoxLayout(self.header)
        header_layout.setContentsMargins(8, 6, 10, 6)
        h = header_layout
        h.setSpacing(10)
        self.btn_fold = QPushButton()
        self.btn_fold.setObjectName("fold")
        self.btn_fold.setCheckable(True)
        self.btn_fold.setCursor(Qt.PointingHandCursor)
        self.btn_fold.setStyleSheet("text-align:left; font-weight:700; font-size:10.5pt;"
                                    " padding-left:2px;")
        self.btn_fold.toggled.connect(self._on_fold)
        self.btn_fold.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        h.addWidget(self.btn_fold, 1)
        self.count = hint_label("")
        self.count.setWordWrap(False)
        h.addWidget(self.count)
        self.btn_search = QPushButton("Search")
        self.btn_search.setObjectName("small")
        self.btn_search.setToolTip("Search within this category")
        self.btn_search.clicked.connect(lambda: self.search_wanted.emit(self.name))
        from onionwatch.ui.triggerspanel import align_control
        align_control(self.btn_search)
        h.addWidget(self.btn_search)
        self.switch = Switch()
        self.switch.clicked.connect(lambda on: self.switched.emit(self.name, on))
        h.addWidget(self.switch)
        self.btn_menu = QPushButton("⋯")
        self.btn_menu.setObjectName("small")
        self.btn_menu.setStyleSheet("font-size:11pt; padding:0 10px;")
        self.btn_menu.setAccessibleName("Category menu")
        self.btn_menu.setToolTip("Rename, turn its triggers on or off, save it to a file…")
        self.btn_menu.clicked.connect(lambda: self.menu_wanted.emit(self.name))
        align_control(self.btn_menu)
        h.addWidget(self.btn_menu)
        v.addWidget(self.header)
        self.body = FlowBox(gap=8, flow_type=CardGrid)
        self.body_layout = self.body.flow
        self.empty = hint_label("No triggers in this category yet. Drag one here, or "
                                "pick it with Category, under a trigger's Fine-tune.")
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

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.count.setVisible(self.width() >= 600)

    def set_name(self, name: str):
        self.name = name
        self.btn_fold.setText(profiles.label(name))
        self.btn_fold.setAccessibleName(f"Category {profiles.label(name)}")

    def set_open(self, on: bool):
        if self.btn_fold.isChecked() != on:
            self.btn_fold.blockSignals(True)
            self.btn_fold.setChecked(on)
            self.btn_fold.blockSignals(False)
        icons.set_icon(self.btn_fold, "fold_open" if on else "fold", "muted", "muted", size=16)
        self.btn_fold.setToolTip("Fold this category away" if on else
                                 "Show this category's triggers")
        self.body.setVisible(on)

    def _on_fold(self, on: bool):
        self.set_open(on)
        self.fold_toggled.emit(self.name, on)

    def set_switch(self, on: bool, tip: str):
        self.switch.setChecked(on)
        self.switch.setToolTip(tip)

    def set_counts(self, text: str, tone: str = ""):
        self.count.setText(text)
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
    def plural(k, word):
        return f"{k} {word}" + ("" if k == 1 else "s")
    if not n:
        return "empty" if cat_on else "empty · off"
    if not cat_on:
        return f"{plural(n, 'trigger')} · off"
    return f"{plural(n, 'trigger')} · {on} on · {plural(pictures, 'picture')}"


class ProfilesDialog(QDialog):
    """Make and change profiles: a name, the categories it turns on, and the
    programs (exe names, from the open windows or typed) that turn it on by itself
    when Profile is set to Automatic. Works on copies: `result_profiles` once
    accepted."""

    def __init__(self, parent, profile_list: list[Profile], categories: list[str],
                 lister=None, start: str = ""):
        super().__init__(parent)
        self.setWindowTitle("Profiles")
        self.resize(720, 600)
        self.profiles = [p.copy() for p in profile_list]
        self.categories = categories
        self._lister = lister
        self._loading = False
        v = QVBoxLayout(self)
        v.addWidget(hint_label(
            "A profile is a set of categories to have on. Pick one by hand under Profile, "
            "or set Profile to Automatic: a profile then turns on while one of its "
            "programs has a window open (or is the window in front), and your own "
            "switches apply while none does."))
        h = QHBoxLayout()
        left = QVBoxLayout()
        self.list = QListWidget()
        self.list.currentRowChanged.connect(self._show)
        left.addWidget(self.list, 1)
        lb = QHBoxLayout()
        self.btn_new = QPushButton("New")
        icons.set_icon(self.btn_new, "plus", size=14)
        self.btn_new.clicked.connect(self._new)
        self.btn_delete = QPushButton("Delete")
        icons.set_icon(self.btn_delete, "trash", size=14)
        self.btn_delete.clicked.connect(self._delete)
        lb.addWidget(self.btn_new)
        lb.addWidget(self.btn_delete)
        left.addLayout(lb)
        h.addLayout(left, 2)

        self.form = QWidget()
        f = QVBoxLayout(self.form)
        f.setContentsMargins(0, 0, 0, 0)
        f.addWidget(section_label("NAME"))
        self.name = QLineEdit()
        self.name.setMaxLength(profiles.NAME_MAX)
        self.name.textEdited.connect(self._on_name)
        f.addWidget(self.name)
        f.addWidget(section_label("CATEGORIES IT TURNS ON"))
        self.cats = QListWidget()
        self.cats.setMinimumHeight(140)
        self.cats.itemChanged.connect(self._on_cat)
        f.addWidget(self.cats, 2)
        f.addWidget(section_label("ON BY ITSELF (AUTOMATIC) WHILE"))
        wh = QHBoxLayout()
        self.when = QComboBox()
        self.when.addItem("one of these programs has a window open", "running")
        self.when.addItem("one of these programs is the window in front", "front")
        self.when.activated.connect(self._on_when)
        wh.addWidget(self.when, 1)
        f.addLayout(wh)
        self.apps = QListWidget()
        self.apps.setMinimumHeight(60)
        f.addWidget(self.apps, 1)
        ah = QHBoxLayout()
        self.btn_pick = QPushButton("Add from the open windows…")
        self.btn_pick.setToolTip("Add the program of one of the windows open now")
        icons.set_icon(self.btn_pick, "window", size=14)
        self.btn_pick.clicked.connect(self._pick_app)
        ah.addWidget(self.btn_pick)
        ah.addStretch(1)
        self.btn_rm_app = QPushButton("Remove")
        self.btn_rm_app.setToolTip("Take the program picked in the list off this profile")
        self.btn_rm_app.clicked.connect(self._remove_app)
        ah.addWidget(self.btn_rm_app)
        f.addLayout(ah)
        th = QHBoxLayout()
        self.app_text = QLineEdit()
        self.app_text.setPlaceholderText("or type a program's name: something.exe")
        self.app_text.returnPressed.connect(self._type_app)
        th.addWidget(self.app_text, 1)
        self.btn_add_app = QPushButton("Add")
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
        p = profiles.new_profile(f"Profile {len(self.profiles) + 1}")
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
        p.name = profiles.clean_name(text) or "Profile"
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
            menu.addAction("No windows open").setEnabled(False)
        menu.exec(self.btn_pick.mapToGlobal(self.btn_pick.rect().bottomLeft()))
