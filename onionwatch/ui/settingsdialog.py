"""Settings, laid out like Onion Board's: a list of categories on the left, a page of
cards for each on the right, Done at the bottom. Audio (where the alerts play,
how loud), Alerts (a Windows notification too, closing to the tray), Appearance (the
language and the colour theme), Updates and privacy (the daily update check, the
anonymous usage count) and About (the version, Send feedback / Report a problem).
Every change applies straight away, but a new language only shows once Onion Watch
restarts (Restart now)."""
from __future__ import annotations

import os
import threading
import webbrowser

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QFrame, QGridLayout,
                               QHBoxLayout, QLabel, QLayout, QListWidget, QListWidgetItem,
                               QPushButton, QScrollArea, QSlider, QStackedWidget,
                               QVBoxLayout, QWidget)

from onionwatch import __version__, feedback, i18n, theme
from onionwatch.sounds import DEFAULT_SOUND
from onionwatch.ui import fit, icons
from onionwatch.ui.panel import hint_label
from onionwatch.wheelguard import no_wheel
from onionwatch.i18n import _


def group_label(group: str) -> str:
    """A theme group's name (theme.GROUPS) in the current language."""
    return {"Classic": _("Classic"), "Colourful": _("Colourful"), "Wild": _("Wild"),
            "Meme": _("Meme")}.get(group, group)


class ThemeCard(QPushButton):
    """A clickable mini-preview of a theme (the same as Onion Board's)."""

    def __init__(self, name: str):
        super().__init__()
        self.name = name
        self.setObjectName("themecard")
        self.setCheckable(True)
        self.setFixedSize(QSize(150, 112))
        self.setCursor(Qt.PointingHandCursor)
        self.setAccessibleName(name)

    def paintEvent(self, e):
        super().paintEvent(e)   # frame + checked border from the stylesheet
        t = theme.THEMES[self.name]
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(8, 8, -8, -30)
        win = QPainterPath()
        win.addRoundedRect(r, 8, 8)
        p.fillPath(win, QColor(t["bg"]))
        # side panel, cards and a slider, in the theme's own colours
        p.setPen(Qt.NoPen)
        tex = t.get("texture")
        if tex:
            tile = theme.texture_image(tex, t["panel"], 6 if tex == "carbon" else None)
            p.setBrush(QBrush(QPixmap.fromImage(tile)))
        else:
            p.setBrush(QColor(t["panel"]))
        p.drawRoundedRect(QRectF(r.right() - 44, r.top() + 6, 38, r.height() - 12), 5, 5)
        for i, col in enumerate(("#7c5cff", "#ff5c8a", "#1fb6ff", "#13ce66")):
            x = r.left() + 7 + (i % 2) * 44
            y = r.top() + 7 + (i // 2) * 34
            p.setBrush(QColor(t["card"]))
            p.drawRoundedRect(QRectF(x, y, 40, 28), 5, 5)
            p.setBrush(QColor(col))
            p.drawRoundedRect(QRectF(x + 5, y + 5, 10, 3), 1.5, 1.5)
        p.setBrush(QColor(t["groove"]))
        p.drawRoundedRect(QRectF(r.right() - 39, r.top() + 20, 28, 3), 1.5, 1.5)
        p.setBrush(QColor(t["accent"]))
        p.drawRoundedRect(QRectF(r.right() - 39, r.top() + 20, 17, 3), 1.5, 1.5)
        theme.paint_logo(p, QRectF(r.right() - 36, r.bottom() - 30, 22, 22),
                         t["accent"], t["accent2"])
        # name, in the theme's own font
        p.setPen(QColor(theme.T["text"]))
        f = QFont(self.font())
        f.setFamily(t.get("font", theme.FONT))
        f.setBold(True)
        p.setFont(f)
        p.drawText(QRectF(10, self.height() - 28, self.width() - 20, 22),
                   Qt.AlignLeft | Qt.AlignVCenter, self.name)
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
        self._reflow(max(1, min(len(self.cards), (self.width() + 12) // 162)))

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
        w, v = self._page()
        v.addWidget(self._language_card())
        self.theme_cards: list[ThemeCard] = []
        for group, names in theme.GROUPS:
            card, cv = self._card(group_label(group))
            cards = []
            for name in names:
                c = ThemeCard(name)
                c.setChecked(name == theme.current_name)
                c.clicked.connect(lambda __=False, n=name: self._pick_theme(n))
                cards.append(c)
                self.theme_cards.append(c)
            cv.addWidget(ThemeGrid(cards))
            v.addWidget(card)
        v.addStretch(1)
        return w

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
        for c in self.theme_cards:
            c.setChecked(c.name == name)
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
