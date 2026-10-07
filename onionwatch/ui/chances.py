"""Live chances: how sure watching is, right now, that each trigger's picture (or
change, or colour) is on screen.

`LiveLabel` shows the little bar a card shows while watching: how well it matches, filled
up to the score, with a tick where the trigger goes off. `ChancesDialog` is the
same for every trigger at once, opened from the Chances button on the Playing now
bar (pages.PlayingBar). The button is optional: Watching settings → "Chances
button", kept as "show_chances" in the host's screen settings."""
from __future__ import annotations

import time

from PySide6.QtCore import QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QFrame, QHBoxLayout, QLabel,
                               QPushButton, QScrollArea, QVBoxLayout, QWidget)

from onionwatch import screenwatch, theme
from onionwatch.ui import fit, icons
from onionwatch.i18n import _

POLL_MS = 150           # as often as the cards' scores refresh
THUMB = QSize(64, 40)
NAME_W = 170            # the names' column, so every bar starts in line
SHOW_KEY = "show_chances"   # host.screen: the Chances button on the Playing now bar

# the modes that go off when the score drops below the line, not above it
BELOW = ("vanish", "still")

WHAT = {"appear": _("Shows up"), "vanish": _("Goes away"), "change": _("Changes"),
        "still": _("Stays still"), "colour": _("Colour")}


def goes_below(t) -> bool:
    """It goes off when its score drops under the line (else when it climbs over)."""
    return t.mode in BELOW or (t.mode == "colour" and t.below)


def closeness(t, score: float) -> float:
    """How far past its line the trigger is (positive: it would go off)."""
    return t.number - score if goes_below(t) else score - t.number


def show_button(host) -> bool:
    return host.screen.get(SHOW_KEY, True) is not False


def _mix(a: str, b: str, k: float) -> QColor:
    ca, cb = QColor(a), QColor(b)
    return QColor(round(ca.red() + (cb.red() - ca.red()) * k),
                  round(ca.green() + (cb.green() - ca.green()) * k),
                  round(ca.blue() + (cb.blue() - ca.blue()) * k))


def paint_meter(p: QPainter, rect: QRectF, score: float, level: float, hot: bool,
                below: bool = False):
    """A rounded bar filled to `score` (0..1) with a tick at `level`. `hot`: it would
    go off now (the fill turns the theme's "ok" colour). `below`: it goes off under
    the line, so the part under the tick is the side that counts."""
    T = theme.T
    score = max(0.0, min(1.0, score))
    level = max(0.0, min(1.0, level))
    r = rect.height() / 2
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(T.get("inset", "#1b1d26")))
    p.drawRoundedRect(rect, r, r)
    accent = T.get("accent", "#1fb6a6")
    if hot:
        fill = QColor(theme.status("ok"))
    else:   # the nearer the line, the brighter
        near = 1 - min(1.0, abs(score - level) / max(level, 0.2))
        fill = _mix(T.get("off", "#4a5068"), accent, 0.45 + 0.55 * near)
    if score > 0:
        w = max(rect.height(), rect.width() * score)
        clip = QPainterPath()
        clip.addRoundedRect(rect, r, r)
        p.save()
        p.setClipPath(clip)
        p.setBrush(fill)
        p.drawRoundedRect(QRectF(rect.x(), rect.y(), w, rect.height()), r, r)
        p.restore()
    x = rect.x() + rect.width() * level
    p.setBrush(QColor(T.get("text_hi", "#ffffff")))
    p.drawRoundedRect(QRectF(x - 1, rect.y() - 2, 2, rect.height() + 4), 1, 1)


class LiveLabel(QLabel):
    """A card's live state: a coloured dot and a word as rich text, or while
    watching the score as a small bar with the trigger's line and the number
    (`set_meter`). The text is kept either way (what it says, for tests and
    screen readers)."""

    BAR_W = 46

    def __init__(self, parent=None):
        super().__init__(parent)
        self.meter: tuple[float, float, bool, bool] | None = None

    def set_meter(self, meter: tuple[float, float, bool, bool] | None):
        """(score, level, hot, below), or None for the dot and word."""
        if meter != self.meter:
            self.meter = meter
            self.update()

    def _font(self) -> QFont:
        f = QFont(self.font())
        f.setBold(True)
        return f

    def meter_size(self) -> QSize:
        fm = QFontMetrics(self._font())
        m = self.contentsMargins()
        return QSize(m.left() + self.BAR_W + 6 + fm.horizontalAdvance("100%") + 2,
                     max(18, fm.height() + 2))

    def paintEvent(self, e):
        if self.meter is None:
            return super().paintEvent(e)
        score, level, hot, below = self.meter
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        h, x0 = self.height(), self.contentsMargins().left()
        paint_meter(p, QRectF(x0 + 1, h / 2 - 3.5, self.BAR_W, 7), score, level, hot, below)
        p.setFont(self._font())
        p.setPen(QColor(theme.status("ok") if hot else theme.T.get("text", "#e6e8f0")))
        p.drawText(QRectF(x0 + self.BAR_W + 6, 0, self.width() - x0 - self.BAR_W - 6, h),
                   Qt.AlignRight | Qt.AlignVCenter, f"{max(0, round(score * 100))}%")
        p.end()


class ChanceRow(QFrame):
    """One trigger in the Chances window: picture, name, its bar and its state."""

    def __init__(self, t, parent=None):
        super().__init__(parent)
        self.setObjectName("chancerow")
        self.tid = t.id
        h = QHBoxLayout(self)
        h.setContentsMargins(8, 6, 10, 6)
        h.setSpacing(10)
        self.thumb = QLabel()
        self.thumb.setFixedSize(THUMB)
        self.thumb.setAlignment(Qt.AlignCenter)
        h.addWidget(self.thumb)
        box = QWidget()
        box.setFixedWidth(NAME_W)
        box.setStyleSheet("background:transparent;")
        names = QVBoxLayout(box)
        names.setContentsMargins(0, 0, 0, 0)
        names.setSpacing(0)
        self.name = QLabel()
        self.name.setStyleSheet("font-weight:600; background:transparent;")
        self.sub = QLabel()
        self.sub.setObjectName("muted")
        self.sub.setStyleSheet("font-size:8pt; background:transparent;")
        names.addWidget(self.name)
        names.addWidget(self.sub)
        h.addWidget(box)
        self.bar = _Bar()
        h.addWidget(self.bar, 1)
        self.word = QLabel()
        # as wide as the longest state word (a translation can be longer), the same on
        # every row so the bars end in line
        bold = QFont(self.word.font())
        bold.setBold(True)
        fm = QFontMetrics(bold)
        self.word.setFixedWidth(max(96, 8 + max(fm.horizontalAdvance(w) for w in (
            _("Off"), _("Not set up"), _("Playing"), _("Ready"), _("Waiting"),
            _("Cooldown"), _("Watching"), "100%"))))
        self.word.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.word.setTextFormat(Qt.RichText)
        self.word.setStyleSheet("background:transparent;")
        h.addWidget(self.word)
        self._look = None
        self._word = None

    def show_trigger(self, t, category: str):
        look = (t.name, category, t.mode, tuple(t.images[:1]), t.colour)
        if look == self._look:
            return
        self._look = look
        fm = self.name.fontMetrics()
        self.name.setText(fm.elidedText(t.name, Qt.ElideRight, NAME_W - 16))
        self.name.setToolTip(t.name)
        self.sub.setText(" · ".join(x for x in (WHAT.get(t.mode, ""), category) if x))
        self.thumb.setPixmap(_thumb(t))

    def show_state(self, word: str, tone: str, score: float | None, level: float,
                   hot: bool, below: bool):
        self.bar.set(score, level, hot, below)
        colour = {"ok": theme.status("ok"), "warn": theme.status("warn"),
                  "accent": theme.T.get("accent", "#1fb6a6")}.get(
                      tone, theme.T.get("muted", "#888888"))
        text = f'<span style="color:{colour}; font-weight:{700 if tone else 400}">{word}</span>'
        if text != self._word:
            self._word = text
            self.word.setText(text)


class _Bar(QWidget):
    """The Chances window's wide bar (empty and dim with no score)."""

    def __init__(self):
        super().__init__()
        self.score: float | None = None
        self.level, self.hot, self.below = 0.5, False, False
        self.setMinimumWidth(120)
        self.setFixedHeight(22)

    def set(self, score, level, hot, below):
        if (score, level, hot, below) != (self.score, self.level, self.hot, self.below):
            self.score, self.level, self.hot, self.below = score, level, hot, below
            self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(1, self.height() / 2 - 5, self.width() - 2, 10)
        if self.score is None:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(theme.T.get("inset", "#1b1d26")))
            p.drawRoundedRect(rect, 5, 5)
            p.setBrush(QColor(theme.T.get("faint", "#6b7189")))
            x = rect.x() + rect.width() * self.level
            p.drawRoundedRect(QRectF(x - 1, rect.y() - 2, 2, rect.height() + 4), 1, 1)
        else:
            paint_meter(p, rect, self.score, self.level, self.hot, self.below)
        p.end()


def _thumb(t) -> QPixmap:
    from onionwatch.ui.triggerspanel import thumb_pixmap
    pm = thumb_pixmap(t.images[0], THUMB) if t.images else QPixmap()
    if not pm.isNull():
        return pm
    out = QPixmap(THUMB)
    out.fill(Qt.transparent)
    p = QPainter(out)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(t.colour if t.mode == "colour" and t.colour
                      else theme.T.get("badge", "#343849")))
    p.drawRoundedRect(QRectF(2, 2, THUMB.width() - 4, THUMB.height() - 4), 8, 8)
    if not (t.mode == "colour" and t.colour):
        icon = icons.pixmap("image" if t.uses_pictures else "gauge", 20,
                            theme.T.get("badge_text", "#d6d9e6"))
        p.drawPixmap((THUMB.width() - 20) // 2, (THUMB.height() - 20) // 2, icon)
    p.end()
    return out


class ChancesDialog(QDialog):
    """Every trigger's chance right now, closest to going off first. Follows
    `panel` (a TriggersTab) every POLL_MS while it's open."""

    SORTS = [_("Closest to going off"), _("List order"), _("Name")]

    def __init__(self, panel, parent=None):
        super().__init__(parent)
        fit.watch(self)          # grows to fit its (translated) text
        self.panel = panel
        self.setWindowTitle(_("Live chances"))
        self.setMinimumSize(460, 420)
        self.resize(560, 560)
        v = QVBoxLayout(self)
        v.setContentsMargins(16, 14, 16, 12)
        v.setSpacing(10)
        head = QHBoxLayout()
        head.setSpacing(10)
        badge = QLabel()
        badge.setPixmap(icons.pixmap("gauge", 28, theme.T.get("accent", "#1fb6a6")))
        head.addWidget(badge)
        words = QVBoxLayout()
        words.setSpacing(0)
        title = QLabel(_("Live chances"))
        title.setStyleSheet("font-size:14pt; font-weight:700; background:transparent;")
        sub = QLabel(_("How sure Onion Watch is, right now, that each trigger's picture is on "
                       "screen. The tick on each bar is where it goes off."))
        sub.setObjectName("muted")
        sub.setWordWrap(True)
        words.addWidget(title)
        words.addWidget(sub)
        head.addLayout(words, 1)
        v.addLayout(head)

        stats = QHBoxLayout()
        stats.setSpacing(8)
        self.stat_on = self._stat()
        self.stat_near = self._stat()
        self.stat_hot = self._stat()
        for s in (self.stat_on, self.stat_near, self.stat_hot):
            stats.addWidget(s, 1)
        v.addLayout(stats)

        tools = QHBoxLayout()
        tools.addWidget(QLabel(_("Sort:")))
        self.sort = QComboBox()
        self.sort.addItems(self.SORTS)
        self.sort.setAccessibleName(_("Sort the triggers"))
        self.sort.currentIndexChanged.connect(lambda _i: self.refresh(force=True))
        tools.addWidget(self.sort)
        tools.addStretch(1)
        self.show_off = QCheckBox(_("Show ones that are off"))
        self.show_off.toggled.connect(lambda _on: self.refresh(force=True))
        tools.addWidget(self.show_off)
        v.addLayout(tools)

        self.empty = QLabel()
        self.empty.setObjectName("muted")
        self.empty.setAlignment(Qt.AlignCenter)
        self.empty.setWordWrap(True)
        self.empty.setMinimumHeight(120)
        v.addWidget(self.empty)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.list = QWidget()
        self.list.setObjectName("chancelist")
        self.rows_box = QVBoxLayout(self.list)
        self.rows_box.setContentsMargins(0, 0, 0, 0)
        self.rows_box.setSpacing(6)
        self.rows_box.addStretch(1)
        self.scroll.setWidget(self.list)
        v.addWidget(self.scroll, 1)

        foot = QHBoxLayout()
        self.foot = QLabel()
        self.foot.setObjectName("muted")
        self.foot.setWordWrap(True)     # a translation can be longer than the room
        foot.addWidget(self.foot, 1)
        close = QPushButton(_("Close"))
        close.clicked.connect(self.accept)
        foot.addWidget(close)
        v.addLayout(foot)
        self._restyle()
        # never narrower than its contents: the tools line and a trigger's row (both as
        # long as the language makes them), with room for the list's scroll bar
        probe = ChanceRow(type("T", (), {"id": ""})())
        row = probe.minimumSizeHint().width() + self.scroll.verticalScrollBar().sizeHint().width()
        probe.deleteLater()
        m = v.contentsMargins()
        self.setMinimumWidth(max(460, v.minimumSize().width(), row + m.left() + m.right()))

        self.rows: dict[str, ChanceRow] = {}
        self._order: list[str] = []
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh)
        self._timer.start(POLL_MS)
        self.refresh(force=True)

    def _stat(self) -> QLabel:
        s = QLabel()
        s.setObjectName("chancestat")
        s.setTextFormat(Qt.RichText)
        s.setAlignment(Qt.AlignCenter)
        return s

    def _restyle(self):
        T = theme.T
        self.setStyleSheet(
            f"QFrame#chancerow {{ background:{T.get('card', '#232633')}; border-radius:10px; }}"
            f"QLabel#chancestat {{ background:{T.get('card', '#232633')}; border-radius:10px;"
            f" padding:6px; }}"
            f"QWidget#chancelist {{ background:transparent; }}")

    def _states(self):
        """(trigger, word, tone, score, level, hot, below) for each trigger shown."""
        panel, w = self.panel, self.panel.watcher
        active = panel.is_active() and w.running
        playing = {t.id for t, _ring in panel.playing_now()}
        cool = getattr(panel, "cooldowns", {})
        now = time.monotonic()
        out = []
        for t in panel.triggers:
            on = panel.is_on(t)
            if not on and not self.show_off.isChecked():
                continue
            score = w.scores.get(t.id) if active and on else None
            below = goes_below(t)
            hot = score is not None and screenwatch.verdict(
                t.mode, score, t.number, t.below) is True
            if not on:
                word, tone = _("Off"), ""
            elif not panel.ready(t) or not t.sounds:
                word, tone = _("Not set up"), ""
            elif t.id in playing:
                word, tone = _("Playing"), "ok"
            elif not active:
                word, tone = _("Ready"), ""
            elif panel._first_note(w.where.get(t.id, ()))[0] is not None:
                word, tone = _("Waiting"), "warn"
            elif cool.get(t.id, 0) > now:
                word, tone = _("Cooldown"), "warn"
            elif score is None:
                word, tone = _("Watching"), "accent"
            else:
                word = f"{max(0, round(score * 100))}%"
                tone = "ok" if hot else "accent"
            out.append((t, word, tone, score, t.number, hot, below))
        return out

    def refresh(self, force: bool = False):
        if not self.isVisible() and not force:
            return
        states = self._states()
        sort = self.sort.currentIndex()
        if sort == 0:
            states.sort(key=lambda s: (s[3] is None, -closeness(s[0], s[3])
                                       if s[3] is not None else 0))
        elif sort == 2:
            states.sort(key=lambda s: s[0].name.lower())
        order = [s[0].id for s in states]
        cats = {}
        for t, word, tone, score, level, hot, below in states:
            row = self.rows.get(t.id)
            if row is None:
                row = self.rows[t.id] = ChanceRow(t)
            if t.category not in cats:
                cats[t.category] = t.category or ""
            row.show_trigger(t, cats[t.category])
            row.show_state(word, tone, score, level, hot, below)
        for tid in list(self.rows):
            if tid not in order:
                row = self.rows.pop(tid)
                row.setParent(None)
                row.deleteLater()
        if order != self._order or force:
            self._order = order
            box = self.rows_box
            while box.count():
                box.takeAt(0)
            for tid in order:
                box.addWidget(self.rows[tid])
                self.rows[tid].show()
            box.addStretch(1)
        self._stats(states)

    def _stats(self, states):
        panel = self.panel
        active = panel.is_active() and panel.watcher.running
        scored = [s for s in states if s[3] is not None]
        near = sum(1 for s in scored if not s[5] and closeness(s[0], s[3]) > -0.1)
        hot = sum(1 for s in scored if s[5])
        T = theme.T
        muted = T.get("muted", "#888888")

        def stat(n, what, colour):
            return (f'<span style="font-size:15pt; font-weight:700; color:{colour}">{n}</span>'
                    f'<br><span style="color:{muted}; font-size:8pt">{what}</span>')
        self.stat_on.setText(stat(len(scored) if active else 0, _("being checked"),
                                  T.get("text", "#e6e8f0")))
        self.stat_near.setText(stat(near, _("close to the line"), theme.status("warn")))
        self.stat_hot.setText(stat(hot, _("over the line now"), theme.status("ok")))
        if not panel.triggers:
            self.empty.setText(_("No triggers yet. Add one on the Triggers page."))
        elif not states:
            self.empty.setText(_("Every trigger is off. Tick “Show ones that are off” to see "
                                 "them anyway."))
        else:
            self.empty.setText("")
        self.empty.setVisible(bool(self.empty.text()))
        self.scroll.setVisible(bool(states))
        self.foot.setText(_("Watching: live, several times a second.") if active else
                          _("Not watching right now: switch watching on to see the chances move."))
