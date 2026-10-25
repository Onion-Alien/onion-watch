"""The triggers page: play a sound when a picture shows up in a game — a rare
spawn's name plate, a queue-ready banner, "YOU DIED". Each trigger is a card: the
pictures to look for (cut from the watched window, files, or pasted after
Win+Shift+S; any of them showing up counts), the sounds to play and which of them
(one at random, in turn, or all at once), once or ringing until it's stopped, how
long to wait before playing, how soon it may play again, how close a match must
be, with the live match next to it so the number is easy to set, and where to
look: a window (watched even while other windows cover it) or a screen — "Same as
below" being the one picked at the bottom of the page.

The watching itself (capture and matching on a worker thread) is
onionwatch.engine.screenwatch, windows are onionwatch.engine.windows. Everything else comes from
the host (onionwatch.host: the Onion Watch app, or Onion Board): the saved triggers
(host.screen), the sounds and playing them, and the folder the pictures are kept
in (host.data_dir / "triggers").
"""
from __future__ import annotations

import dataclasses
import logging
import math
import time
import uuid
from collections import deque
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PySide6.QtCore import QEvent, QPoint, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QImage, QKeySequence, QShortcut
from PySide6.QtWidgets import (QApplication, QBoxLayout, QCheckBox, QFileDialog, QFrame,
                               QHBoxLayout, QLabel, QLineEdit, QMenu, QMessageBox, QPushButton,
                               QScrollArea, QSizePolicy, QSplitter, QVBoxLayout, QWidget)

from onionwatch.audio.shuffle import ShuffleBag
from onionwatch.core import usage
from onionwatch.engine import cutout, profiles, screenwatch, windows
from onionwatch.engine.screenwatch import (INTERVALS_MS, MAX_PICTURES, MAX_SOUNDS, Monitor, Picture,
                                           Trigger, Watched, WindowRef)
from onionwatch.i18n import _, ngettext
from onionwatch.ui.kit import icons, kit, theme
from onionwatch.ui.kit.panel import UndoBar, card, hint_label
from onionwatch.ui.kit.wheelguard import no_wheel
from onionwatch.ui.settings.watching import share_label
from onionwatch.ui.triggers.card import (LEVELS, NEW_CATEGORY, POLL_MS, UNTILS, TriggerRow,
                                         trigger_ready)
from onionwatch.ui.triggers.bincontrol import KEEP_DAYS, BinControl
from onionwatch.ui.triggers.cardkit import (PICK_WINDOW, BarFlow, ElidedLabel, WideCombo,
                                            align_control, card_css, fill_sources, labelled,
                                            pictures, retarget, retargeted, source_label, triggers)
from onionwatch.ui.triggers.categories import (MAX_PER_ROW, PAD, CategoriesDialog, CategorySection,
                                               counts_text)
from onionwatch.ui.triggers.controller import MAX_TRIGGERS, needs_part
from onionwatch.ui.triggers.history import THUMB as LOG_THUMB, HistoryDialog
from onionwatch.ui.triggers.pictures import (copied_picture, cut_size, delete_picture,
                                             fit_web, flatness, hit_image, is_web, picture_file,
                                             picture_filter, picture_name, picture_of, picture_rgb,
                                             picture_tint, pictures_dir, save_picture, set_cut_size,
                                             set_web, with_alpha)
from onionwatch.ui.triggers.packcontrol import PackControl
from onionwatch.ui.triggers.profilecontrol import ProfileControl
from onionwatch.ui.triggers.windowpicker import places_label

log = logging.getLogger(__name__)


# Versions before categories load only the first 50 of Config.screen["triggers"] and
# save just those back. So only the first OLD_TRIGGERS are kept there and the rest
# under "more_triggers", which those versions never read or write: opening the same
# settings in one of them (an older Onion Board add-on, say) can't lose any
OLD_TRIGGERS = 50
SEARCH_MIN = 200        # px: the search box never gets narrower (it was squeezed to "Sea…")
SEARCH_ROOM = 260       # px it keeps before the view's controls go to a line of their own
LIST_VIEW = -1          # the View list's "List and editor"
PADS_VIEW = -2          # ...and its "Pads"
PADS_SHARE = 0.3        # how much of the width the pads keep beside an editor at first
SPLIT_MIN = 760         # px: from this wide, the list on the left and one trigger's editor
LIST_WIDTH = 300        # ...on the right; the list is this wide
# the empty list's card: padding above and below, gap between Hoot and the text (px);
# tight when roomy would need a scroll bar (_fit_empty_card)
EMPTY_ROOMY = (24, 24, 10)
EMPTY_TIGHT = (8, 12, 6)
MAX_SIDE = 8192         # bigger pictures are refused (kept pixel for pixel, never resized)
INPUT_POLL_MS = 100     # how often an "input" ring checks for the mouse or keyboard


GUESS_PLAYING_S = 8     # a sound counts as playing this long when the host can't say
HISTORY = 50            # alerts kept in the history (in memory only)
BUILD_NOW = 8           # an opened category's cards made at once (the first ones, on
BUILD_STEP_MS = 40      # ...screen); the rest this long at a time, so the window never
                        # ...freezes, however many there are (a card takes ~20-30 ms)
SCREEN_LEARN_MS = 1300  # a screen cut's frames for the cut-out: grabbed this long after
HEAVY_GAP = 0.5         # s: checks spaced out further than this (to keep to the share of
HEAVY_FOR = 5.0         # ...the processor picked) for this long: say too many pictures are on


@dataclass
class Alert:
    """Something that went off, for the history: when, which trigger, where, how
    strongly, and what the watched window looked like then (the check's own small
    copy, the box around what set it off drawn on it, kept at the size the Log shows
    it: 50 of them stay in memory)."""
    when: float
    name: str
    place: str
    score: float
    mode: str
    picture: QImage

    @classmethod
    def of(cls, t: Trigger, hit: screenwatch.Hit, place: str) -> Alert:
        img = hit_image(hit)
        if img.width() > LOG_THUMB.width() or img.height() > LOG_THUMB.height():
            # what the Log's thumbnail would make of it anyway (windowpicker.thumbnail)
            img = img.scaled(LOG_THUMB, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        return cls(time.time(), t.name, place, hit.score, t.mode, img)


def _row_width(widgets: list[QWidget], gap: int = 8, least: bool = True) -> int:
    """The width the shown `widgets` need side by side, `gap` px apart: the least
    they can do with, or (`least` False) what they'd like."""
    shown = [w for w in widgets if not w.isHidden()]
    return (sum(max(w.minimumWidth(),
                    (w.minimumSizeHint() if least else w.sizeHint()).width())
                for w in shown)
            + gap * max(0, len(shown) - 1))


class TriggersTab(QWidget):
    """The list of triggers, the on / off switch and the watcher behind them.
    `host` (onionwatch.host.Host) keeps the settings and has the sounds."""
    active_changed = Signal(bool)       # watching or not
    fired = Signal(object)              # a Trigger just went off (its sound started)
    trigger_added = Signal()            # a new trigger was made (not one brought back)
    ringing_changed = Signal()          # a sound started or stopped ringing
    history_changed = Signal()          # something went off (TriggersTab.history)
    playing_changed = Signal()          # a trigger's sound started, or was stopped
    _fired = Signal(str, object)        # from the watcher thread: trigger id, Hit
    _quieted = Signal(str)              # ...a ringing trigger's stop happened (Quieter)

    def __init__(self, host, parent=None):
        super().__init__(parent)
        self.host = host
        self.binctl = BinControl(self)        # Recently deleted
        self.packctl = PackControl(self)      # saving / loading packs
        self.profilectl = ProfileControl(self)   # the Profile list
        s = host.screen
        self.triggers: list[Trigger] = []
        saved = [d for k in ("triggers", "more_triggers")
                 for d in (s.get(k) if isinstance(s.get(k), list) else [])]
        # each trigger's category, kept apart too: an older version saves its
        # triggers back without one (see _store)
        cats = s.get("trigger_categories") if isinstance(s.get("trigger_categories"),
                                                          dict) else {}
        for d in saved:
            t = Trigger.from_raw(d)
            if (t is not None and len(self.triggers) < MAX_TRIGGERS
                    and all(x.id != t.id for x in self.triggers)):
                t.pending = ""      # an older Onion Board's sound import, long over
                if "category" not in d:
                    t.category = profiles.clean_name(cats.get(t.id, ""))
                self.triggers.append(t)
        self.rows: dict[str, TriggerRow] = {}   # the cards made so far (open categories')
        self.cooldowns: dict[str, float] = {}   # trigger id -> its cooldown's end (monotonic)
        # the categories and profiles (onionwatch.engine.profiles), and the categories on now
        self.groups = profiles.Groups.load(s, [t.category for t in self.triggers])
        self.groups.ensure(profiles.UNCATEGORISED)
        self.apps = profiles.AppWatch()
        self._active = self.groups.active()
        self.sections: dict[str, CategorySection] = {}
        self._lister = windows.list_windows     # the open windows, and the one in front
        self._front = windows.foreground        # (tests stand in for them)
        self._last_category = ""    # where a new trigger goes: the category last opened
        self._heavy_since: float | None = None  # checks spaced out past HEAVY_GAP since
        self._gap_shown = ""        # the check gap as the counts line last said it
        self._mons: list[Monitor] = []      # the screens as last listed
        self._fell_back: frozenset[str] = frozenset()   # watcher.fell_back as last seen
        self._gray: dict[str, tuple[float, Picture]] = {}   # picture path -> (mtime, picture)
        self._cuts: dict[str, tuple[int, int] | None] = {}  # ...-> the size it was cut from
        self._wide: dict[str, bool] = {}                    # ...-> not cut from the game
        self._web_added = 0             # pictures from the web the last _add_pictures took
        self._tints: dict[str, np.ndarray | None] = {}      # ...-> its colours in brief
        self._colours: dict[str, np.ndarray | None] = {}    # ...-> its colours (RGB)
        self._gen = 0                   # bumped to drop sounds still waiting to play
        self._bag = ShuffleBag()        # "Random": each trigger's sounds, each once per round
        self._order: dict[str, int] = {}   # "In order": each trigger's next sound
        self.watcher = screenwatch.Watcher(self._fired.emit, hits=True,
                                           on_quiet=self._quieted.emit)
        self._fired.connect(self._on_fired)
        self._quieted.connect(self._stop_by_itself)
        # "input" rings: trigger id -> when it started ringing (time.monotonic)
        self._input_waits: dict[str, float] = {}
        self._played: dict[str, set[str]] = {}       # trigger id -> sounds it played (tagged)
        self._ring_sounds: dict[str, list[str]] = {}  # ...-> what its ring is playing
        self._sounds_shown: list | None = None  # the host's sounds the cards last got
        self._ring_how: dict[str, str] = {}           # ...-> what stops that ring (Trigger.stop)
        self._live: dict[str, float] = {}             # ...-> when it went off, while it plays
        self.pages = None               # the Triggers / Log pages it's shown in (ui.pages)
        self._input_poll = QTimer(self)
        self._input_poll.timeout.connect(self._check_input)
        self._hits: dict[str, screenwatch.Hit] = {}     # each trigger's latest, for alerts
        # what went off lately, newest last (kept in memory only, never saved)
        self.history: deque[Alert] = deque(maxlen=HISTORY)
        interval = s.get("interval_ms", screenwatch.DEFAULT_INTERVAL_MS)
        if interval not in INTERVALS_MS:
            interval = screenwatch.DEFAULT_INTERVAL_MS
        self.watcher.interval = interval / 1000
        share = s.get("cpu_share", screenwatch.CPU_SHARE)
        self.watcher.cpu_share = (share if share in screenwatch.CPU_SHARES
                                  else screenwatch.CPU_SHARE)
        most = s.get("max_detect", "off")
        self.watcher.max_detect = most if most in screenwatch.MAX_DETECTS else "off"
        self.watcher.color_hits = s.get("color_log") is not False
        self.watcher.default = self._saved_default()

        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(12)
        # what Watch does and needs (also said in the empty tab: _fit_empty)
        self.about = _("Pick the game window, cut out the thing to watch for — a rare "
                       "spawn's name, a “queue ready” banner, a message — and choose the "
                       "sound. Onion Watch keeps looking at that window while you're "
                       "alt-tabbed into another game or away from the keyboard, and plays "
                       "the sound (or rings until you're back) the moment it appears. It "
                       "only looks: it never clicks, types or touches the game.")
        head, hv = card(_("Play a sound when something shows up in your game"), self.about)
        hv.itemAt(0).widget().setWordWrap(True)
        self.hint = hv.itemAt(1).widget()
        self.warn = hint_label("")
        theme.set_tone(self.warn, "warn")
        self.warn.setVisible(False)
        # no banner: the explanation is behind an ⓘ (the host's own, by Onion Board's
        # tabs, or one in the button row here); only the warning shows, when there is one
        self.info = (hv.itemAt(0).widget().text(), self.hint.text())
        tab_info = getattr(host, "tab_info", None)
        if callable(tab_info):
            tab_info(*self.info)
        v.addWidget(self.warn)
        head.hide()
        v.addWidget(head)
        # "Deleted X · Undo" floats over the top of the tab: not in the layout, so
        # showing it never pushes the list down
        self.undo_bar = UndoBar(parent=self)

        # the profile in charge and how much is on: there once there are categories
        # or profiles (a plain list of triggers looks as it always did)
        self.groupbar = QWidget()
        gb = QHBoxLayout(self.groupbar)
        gb.setContentsMargins(4, 0, 4, 0)
        gb.setSpacing(4)
        self.cb_profile = WideCombo(min_width=150)
        self.cb_profile.setMaximumWidth(240)
        self.cb_profile.setToolTip(_("Which categories are on: your own switches (Manual), a "
                                     "profile's, or Automatic: the profile of the program that's "
                                     "open"))
        no_wheel(self.cb_profile)
        self.cb_profile.activated.connect(self.profilectl._on_profile)
        gb.addWidget(labelled(_("Profile"), self.cb_profile), 0, Qt.AlignmentFlag.AlignLeft)
        self.btn_categories = QPushButton()
        self.btn_categories.setAccessibleName(_("Categories"))
        self.btn_categories.setToolTip(_("Categories: give each one its own colours and a picture"))
        icons.set_icon(self.btn_categories, "palette")
        self.btn_categories.clicked.connect(lambda: self.edit_categories())
        align_control(self.btn_categories)
        gb.addWidget(self.btn_categories)
        self.lbl_counts = ElidedLabel()     # cut short rather than widen a narrow window
        self.lbl_counts.setObjectName("hint")
        self.lbl_counts.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        # one line over the list: the search box, always there, then (once there are
        # categories or profiles) the category to search and the profile in charge
        self.search_bar = QWidget()
        bar_layout = QVBoxLayout(self.search_bar)
        bar_layout.setContentsMargins(0, 0, 0, 0)
        bar_layout.setSpacing(8)
        self.search_line = QWidget()
        search_layout = QBoxLayout(QBoxLayout.LeftToRight, self.search_line)
        search_layout.setContentsMargins(0, 0, 0, 0)
        search_layout.setSpacing(8)
        bar_layout.addWidget(self.search_line)
        self.search_text = QLineEdit()
        self.search_text.setPlaceholderText(_("Search triggers"))
        self.search_text.setAccessibleName(_("Search triggers"))
        self.search_text.setToolTip(_("Find a trigger by name, category, window or sound "
                                      "(Ctrl+F). Esc clears it."))
        self.search_text.setClearButtonEnabled(True)
        self._search_icon = self.search_text.addAction(icons.icon("search", "muted"),
                                                       QLineEdit.LeadingPosition)
        align_control(self.search_text)
        self.search_text.setMinimumWidth(SEARCH_MIN)
        # + New trigger, right where the list starts: "What should it watch for?"
        self.btn_new = QPushButton(_("New trigger"))
        self.btn_new.setObjectName("newtrigger")
        # (lit up by its own colours, _update_new_trigger_glow: a drop shadow on it left
        # the bottom bar unpainted in Onion Board until something else redrew the window)
        self.btn_new.setToolTip(_("Make a new trigger: pick what it watches for (a picture, a "
                                  "bar, a chat line...), then cut it from the game"))
        icons.set_icon(self.btn_new, "plus")
        self.btn_new.clicked.connect(self.new_trigger)
        align_control(self.btn_new)
        search_layout.addWidget(self.btn_new)
        search_layout.addWidget(self.search_text, 3)
        self.search_scope = WideCombo(min_width=140)
        self.search_scope.setAccessibleName(_("Search category"))
        no_wheel(self.search_scope)
        align_control(self.search_scope)
        search_layout.addWidget(self.search_scope)
        self.btn_clear_search = QPushButton(_("Clear"))
        self.btn_clear_search.setToolTip(_("Show every trigger again (Esc)"))
        align_control(self.btn_clear_search)
        search_layout.addWidget(self.btn_clear_search)
        self.search_summary = hint_label("")
        self.search_summary.setWordWrap(False)
        search_layout.addWidget(self.search_summary)
        search_layout.addWidget(self.lbl_counts, 4)
        search_layout.addStretch(1)
        # how the cards look, and the profile: at the end of the line while the search
        # box keeps its room there, else on a line of their own under it (_fit_top)
        self.view_bar = QWidget()
        view_layout = QBoxLayout(QBoxLayout.LeftToRight, self.view_bar)
        view_layout.setContentsMargins(0, 0, 0, 0)
        view_layout.setSpacing(8)
        search_layout.addWidget(self.view_bar)
        self.cb_per_row = WideCombo(min_width=110)
        self.cb_per_row.setAccessibleName(_("View"))
        self.cb_per_row.setToolTip(_("List and editor: the triggers in a list, the one you pick "
                                     "beside it (in a window wide enough). Or cards side by side "
                                     "that open where they are: as many as fit at their usual "
                                     "size (Auto), or a number of your own."))
        self.cb_per_row.addItem(_("List and editor"), LIST_VIEW)
        self.cb_per_row.addItem(_("Pads"), PADS_VIEW)
        self.cb_per_row.addItem(_("Auto per row"), 0)
        for k in range(1, MAX_PER_ROW + 1):
            self.cb_per_row.addItem(_("{k} per row", k=k), k)
        per_row = host.screen.get("cards_per_row")
        self.per_row = per_row if type(per_row) is int and 0 < per_row <= MAX_PER_ROW else 0
        # (a key of its own: an older version reads cards_per_row, and knows no list;
        # one that knows no pads reads "pads" as the list)
        self.list_view = host.screen.get("view") != "cards"
        self.pads = host.screen.get("view") == "pads"   # (the pads beside the editor)
        self.cb_per_row.setCurrentIndex(self.cb_per_row.findData(self._view_data()))
        no_wheel(self.cb_per_row)
        align_control(self.cb_per_row)
        self.cb_per_row.activated.connect(self._on_view)
        view_layout.addWidget(self.cb_per_row)
        self.chk_advanced = QCheckBox(_("Show more info"))
        self.chk_advanced.setToolTip(_("Closed cards show more: every name in full, and each "
                                       "trigger's settings"))
        self.chk_advanced.setChecked(host.screen.get("advanced_cards") is True)
        self.chk_advanced.toggled.connect(self._on_advanced)
        view_layout.addWidget(self.chk_advanced)
        view_layout.addWidget(self.groupbar)
        # side by side only sets no minimum: below 600 px resizeEvent stacks it instead
        self.search_bar.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        v.addWidget(self.search_bar)
        self._search_ids: set[str] | None = None
        self.search_text.textChanged.connect(self._apply_search)
        self.search_scope.currentIndexChanged.connect(self._apply_search)
        self.btn_clear_search.clicked.connect(self.clear_search)
        self.find_shortcut = QShortcut(QKeySequence.Find, self)
        self.find_shortcut.activated.connect(self.show_search)
        self.close_search_shortcut = QShortcut(QKeySequence("Escape"), self.search_bar)
        self.close_search_shortcut.setContext(Qt.WidgetWithChildrenShortcut)
        self.close_search_shortcut.activated.connect(self.clear_search)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.list = QWidget()
        self.list_layout = QVBoxLayout(self.list)
        self.list_layout.setContentsMargins(0, 0, 0, 0)
        self.list_layout.setSpacing(10)
        self.empty, ev = card()
        ev.setContentsMargins(16, EMPTY_ROOMY[0], 16, EMPTY_ROOMY[1])
        ev.setSpacing(EMPTY_ROOMY[2])
        self.hoot = kit.owl().OwlWidget(108)   # waiting (sadly) for something to watch
        ev.addWidget(self.hoot, 0, Qt.AlignmentFlag.AlignHCenter)
        hint = hint_label(_("No triggers yet. Click + New trigger above, pick what it should "
                            "watch for, and Hoot walks you through the rest."))
        hint.setAlignment(Qt.AlignCenter)
        ev.addWidget(hint)
        # what Watch needs, said where it's empty (not only behind the tab's ⓘ): here
        # when the list is the whole width, in the editor's box when it's beside it
        self.empty_about = hint_label(self.about)
        self.empty_about.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ev.addWidget(self.empty_about)
        self.list_layout.addWidget(self.empty)
        self.no_results = hint_label(_("No matching triggers. Try another search or clear "
                                       "filters."))
        self.no_results.setAlignment(Qt.AlignCenter)
        self.no_results.hide()
        v.addWidget(self.no_results)
        self.list_layout.addStretch(1)
        self.scroll.setWidget(self.list)
        # (resized: _fit_empty_card; pyright takes self.scroll for QWidget.scroll())
        self.scroll.installEventFilter(self)  # pyright: ignore[reportAttributeAccessIssue]
        # the cards keep a gap from the scroll bar instead of running up against it
        self.scroll.verticalScrollBar().rangeChanged.connect(
            lambda _lo, hi: self.list_layout.setContentsMargins(0, 0, 10 if hi else 0, 0))
        # a wide window: the list on the left, the trigger picked in it on the right
        # (_set_split). Narrower, the list is the whole width and a card opens in it
        self.body = QWidget()
        bh = QHBoxLayout(self.body)
        bh.setContentsMargins(0, 0, 0, 0)
        bh.setSpacing(0)
        # the list and the editor side by side, the gap between them a handle: in the
        # Pads view it's dragged to share the width out (kept as "pads_split")
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setHandleWidth(10)
        self.splitter.setStyleSheet(
            "QSplitter { background: transparent; }"
            "QSplitter::handle { background: transparent; }"
            "QSplitter::handle:enabled:hover { background: palette(mid); margin: 0 3px;"
            " border-radius: 2px; }")
        self.splitter.splitterMoved.connect(self._on_split_moved)
        bh.addWidget(self.splitter, 1)
        # (pyright takes self.scroll for QWidget.scroll(), the method it shadows)
        self.splitter.addWidget(self.scroll)  # pyright: ignore[reportArgumentType]
        self.editor_scroll = QScrollArea()
        self.editor_scroll.setWidgetResizable(True)
        self.editor_scroll.setFrameShape(QFrame.NoFrame)
        self.editor_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.editor_pane = QWidget()
        ep = QVBoxLayout(self.editor_pane)
        ep.setContentsMargins(0, 0, 0, 0)
        ep.setSpacing(8)
        # nothing picked: match the empty list's card, with the hint in its middle
        self.editor_empty, ee = card()
        ee.setContentsMargins(32, 24, 32, 24)
        ee.setSpacing(10)
        ee.addStretch(1)
        mark = QLabel()
        icons.set_label_icon(mark, "triggers", size=40)
        ee.addWidget(mark, 0, Qt.AlignmentFlag.AlignHCenter)
        self.editor_hint = hint_label("")     # (_fit_empty: what it says)
        self.editor_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ee.addWidget(self.editor_hint)
        ee.addStretch(1)
        ep.addWidget(self.editor_empty, 1)
        ep.addStretch(0)        # under a picked trigger: the gap (_empty_shown)
        self.editor_scroll.setWidget(self.editor_pane)
        self.editor_scroll.hide()
        self._fit_empty()
        self.splitter.addWidget(self.editor_scroll)
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.handle(1).setEnabled(False)   # only the Pads view drags it
        self._split_save = QTimer(self)     # the handle's place, saved once it stops
        self._split_save.setSingleShot(True)
        self._split_save.setInterval(400)
        self._split_save.timeout.connect(self.host.save)
        self.editor: TriggerRow | None = None   # the trigger shown on the right
        self._editor_cache: dict[str, tuple[object, TriggerRow]] = {}
        self._editor_snapshot: object = None
        self.split = False
        v.addWidget(self.body, 1)

        f = QFrame()
        f.setObjectName("transport")
        self.toolbar = f
        # roomier buttons than elsewhere: the bar's few big actions read as buttons, not a
        # packed strip (only padding: their colours stay the theme's)
        f.setStyleSheet("QPushButton { padding: 8px 16px; } "
                        "QPushButton#live { font-weight: 700; }")
        h = BarFlow(f, gap=18)   # room between them: at 10 the bar looked packed
        # its first button in line with the cards' pictures above it (a card's margin
        # and the strip's own two pixels)
        h.setContentsMargins(12, 10, 12, 10)
        self.btn_watch = QPushButton()
        self.btn_watch.setObjectName("live")
        self.btn_watch.setCheckable(True)
        self.btn_watch.setToolTip(_("Watch for the pictures above"))
        icons.set_icon(self.btn_watch, "triggers", checked_color="#ffffff")
        self.btn_watch.toggled.connect(self.set_watching)
        h.addWidget(self.btn_watch)
        self.hoot.clicked.connect(lambda: self.btn_new.setFocus(Qt.OtherFocusReason))
        icons.gap_follows_compact(self.btn_watch)   # (fit_parts)
        self.btn_more = QPushButton(_("More"))
        self.btn_more.setToolTip(_("What went off lately, saving or loading triggers, and "
                                   "recently deleted ones"))
        icons.set_icon(self.btn_more, "history")
        menu = QMenu(self.btn_more)
        menu.addAction(_("What went off"), self.show_history)
        menu.addSeparator()
        menu.addAction(_("New category"), self.new_category)
        self.act_categories = menu.addAction(icons.icon("palette"), _("Categories"),
                                             lambda: self.edit_categories())
        menu.addAction(_("Profiles"), self.profilectl.edit_profiles)
        menu.addSeparator()
        self.act_export = menu.addAction(_("Save triggers to a file"), self.packctl.export_triggers)
        menu.addAction(_("Load triggers from a file"), self.packctl.import_triggers)
        menu.addSeparator()
        self.act_bin = menu.addAction(icons.icon("trash"), _("Recently deleted"),
                                      self.binctl.show_deleted)

        def about_to_show():
            self.act_export.setEnabled(bool(self.triggers))
            self.act_categories.setEnabled(self._named_categories())
            n = len(self.binctl._bin())
            self.act_bin.setText(_("Recently deleted ({n})", n=n) if n else _("Recently deleted"))
        menu.aboutToShow.connect(about_to_show)
        self.btn_more.setMenu(menu)
        h.addWidget(self.btn_more)
        self.cb_where = WideCombo(min_width=140)
        # as wide as "Screen 1: 1920×1080" when there's room (at 150 it always read
        # "Screen 1: 1…"); a long window title stays in the popup and the tooltip
        self.cb_where.setMaximumWidth(260)
        self.cb_where.setToolTip(_("Where triggers set to “Default” look: your game's "
                                   "window, or a whole screen"))
        self.cb_where.activated.connect(self._on_where)
        no_wheel(self.cb_where)
        # beside the buttons when there's room (the list gives way first), on a line of
        # its own when not. How often triggers on "Default" are checked is under ⚙
        # (set_default_interval): each card has its own "Check every" too
        self.look = labelled(_("Look in"), self.cb_where)
        h.addWidget(self.look)
        # the watching settings (check speed, processor use), then last the ⓘ and the
        # bin (only while it holds something)
        self.btn_settings = QPushButton()
        self.btn_settings.setFixedWidth(34)
        self.btn_settings.setToolTip(_("Watching settings: how often triggers on Default are "
                                       "checked, and how much of your processor it may use"))
        self.btn_settings.setAccessibleName(_("Watching settings"))
        icons.set_icon(self.btn_settings, "chip")   # not a gear: that's the app's Settings
        self.btn_settings.clicked.connect(self.show_watching)
        h.addWidget(self.btn_settings)
        if not callable(getattr(host, "tab_info", None)):
            self.btn_info = QPushButton(_("Help"))
            self.btn_info.setObjectName("small")
            self.btn_info.setCursor(Qt.CursorShape.PointingHandCursor)
            self.btn_info.clicked.connect(
                lambda: QMessageBox.information(self, *self.info))
            self.btn_info.setParent(self)
            self.btn_info.hide()
            menu.addSeparator()
            menu.addAction(_("Help"), self.btn_info.click)
        self.btn_bin = QPushButton()     # the bin's icon and count (_label_bin)
        icons.set_icon(self.btn_bin, "trash")
        self.btn_bin.clicked.connect(self.binctl.show_deleted)
        h.addWidget(self.btn_bin)
        for control in (self.btn_watch, self.btn_more,
                        self.cb_where, self.btn_settings, self.btn_bin):
            align_control(control)
        if hasattr(self, "btn_info"):
            align_control(self.btn_info)
        v.addWidget(f)

        ok, why = screenwatch.supported()
        if not ok:
            self.warn.setText(why)
            self.warn.setVisible(True)
            self.btn_watch.setEnabled(False)
        self._fill_sources()
        self._layout_sections()
        self.profilectl._fill_profiles()
        self.profilectl._update_app_timer()
        self.binctl._prune_bin()
        self.binctl._label_bin()
        self.poll = QTimer(self)
        self.poll.timeout.connect(self._poll)
        self._label_watch()
        if ok and s.get("on") and self.triggers:
            self.btn_watch.setChecked(True)    # it was on when the app last closed

    # ------------------------------------------------------------------ search
    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit_top()
        was = self.split
        self._set_split(self.list_view and self.width() >= SPLIT_MIN)
        self._label_view()
        if was and self.split:
            self._fit_split(resized=True)

    # ------------------------------------------------------------------ list and editor
    def _set_split(self, on: bool):
        """The list on the left and the picked trigger's editor on the right (a wide
        window), or the list alone with cards opening in it."""
        if on == self.split:
            return
        self.split = on
        self._fit_split()
        self._fit_top()     # (the line over it in the same two columns)
        picked = self.editor.t.id if self.editor is not None else None
        for row in self.rows.values():
            row.on_open = self._select if on else None
            # a click picks it; the editor never folds (a pad has no arrow at all)
            row.btn_open.setVisible(not on and not row.pad)
            if on and row.is_open:
                picked = picked or row.t.id
                row.set_open(False)
        if on:
            if picked is None and self.triggers and not self.pads:
                picked = self.triggers[0].id    # (the pads stay whole until one's picked)
            if picked in self.rows:
                self._select(self.rows[picked])
        else:
            self._drop_editor()
            if picked in self.rows:
                self.rows[picked].set_open(True)

    def _fit_split(self, resized: bool = False):
        """The list and the editor's shares of the width: the list LIST_WIDTH wide
        beside the editor; the pads as wide as the handle was left (PADS_SHARE at
        first), or the whole width with no trigger picked; the list alone, all of it."""
        on, pads = self.split, self.split and self.pads
        shown = on and (not pads or self.editor is not None)
        was = not self.editor_scroll.isHidden()
        fixed = on and not pads
        self.scroll.setMaximumWidth(LIST_WIDTH if fixed else 16777215)
        self.scroll.setMinimumWidth(LIST_WIDTH if fixed else PAD + 20 if pads else 0)
        self.editor_scroll.setVisible(shown)
        self.splitter.handle(1).setEnabled(pads and shown)
        self.splitter.handle(1).setCursor(Qt.CursorShape.SplitHCursor if pads and shown
                                          else Qt.CursorShape.ArrowCursor)
        if self.editor is not None:
            self.editor.btn_close.setVisible(pads and shown)
        # (the page's width: the splitter's own is still the old one in a resize)
        lay = self.layout()
        assert lay is not None
        m = lay.contentsMargins()
        total = max(1, self.width() - m.left() - m.right() - self.splitter.handleWidth())
        if fixed:   # (the handle may have been left anywhere by the Pads view)
            self.splitter.setSizes([LIST_WIDTH, max(1, total - LIST_WIDTH)])
        elif pads and shown and (resized or not was):   # (its share kept as it grows)
            share = self.host.screen.get("pads_split")
            share = share if type(share) is float and 0.1 <= share <= 0.9 else PADS_SHARE
            self.splitter.setSizes([round(total * share), total - round(total * share)])
        self._fit_empty()

    def _fit_empty(self):
        """The nothing-here boxes never say the same thing twice: with no triggers the
        list's box says how to start, and what Watch needs is in the editor's box beside
        it (or under the list's, with no editor shown); with triggers, the editor's box
        says to pick one."""
        none = not self.triggers
        self.editor_hint.setText(
            self.about if none else
            _("Pick a trigger on the left to change it, or click + New trigger to make one."))
        self.empty_about.setVisible(self.editor_scroll.isHidden())
        self._fit_empty_card()

    def eventFilter(self, obj, event):
        if obj is self.scroll and event.type() == QEvent.Type.Resize:
            self._fit_empty_card()
        return super().eventFilter(obj, event)

    def _fit_empty_card(self):
        """The empty list's card keeps its roomy padding unless that would need a
        scroll bar (a short, narrow window): then its padding and gaps tighten so Hoot
        and both paragraphs still fit. Measured at the list's full width, as it is
        with no scroll bar, so taking the bar away can't flip it back."""
        lay = self.empty.layout()
        assert lay is not None
        items = (lay.itemAt(i) for i in range(lay.count()))
        gaps = sum(1 for it in items if it is not None and (w := it.widget()) is not None
                   and not w.isHidden()) - 1
        m = lay.contentsMargins()
        scroll: QScrollArea = self.scroll  # pyright: ignore[reportAssignmentType]
        width = scroll.width()
        if width <= 0 or gaps < 0:
            return
        top, bottom, spacing = EMPTY_ROOMY
        roomy = (lay.totalHeightForWidth(width) - m.top() - m.bottom()
                 - gaps * lay.spacing() + top + bottom + gaps * spacing)
        if roomy > scroll.height():
            top, bottom, spacing = EMPTY_TIGHT
        if (m.top(), m.bottom(), lay.spacing()) != (top, bottom, spacing):
            lay.setContentsMargins(m.left(), top, m.right(), bottom)
            lay.setSpacing(spacing)

    def _on_split_moved(self, _pos: int, _index: int):
        """The handle was dragged (the Pads view): keep the pads' share for next time."""
        a, b = self.splitter.sizes()
        if self.pads and a + b > 0:
            self.host.screen["pads_split"] = round(a / (a + b), 3)
            self._split_save.start()

    def _select(self, row: TriggerRow):
        """Show `row`'s trigger in the editor on the right."""
        t = row.t
        if self.editor is not None and self.editor.t is t:
            return
        sounds = list(self.host.sounds())
        snapshot = (t.to_raw(), sounds, list(self._mons), self.groups.names(),
                    self.default_interval, self.watcher.default, dict(theme.T))
        self._drop_editor(keep=True)
        cached = self._editor_cache.pop(t.id, None)
        if cached is not None and cached[0] == snapshot and cached[1].t is t:
            ed = cached[1]
        else:
            if cached is not None:
                cached[1].deleteLater()
            ed = self._make_editor(t, sounds)
        self._editor_snapshot = snapshot
        ed.watching = row.watching
        ed.cooldown_until = row.cooldown_until
        ed.note, ed.waiting = row.note, row.waiting
        ed._update_state()
        ed.show_score(row._score)
        self.editor = ed
        self.editor_pane.layout().insertWidget(0, ed)
        ed.show()
        self._empty_shown(False)
        for r in self.rows.values():
            r.set_selected(r.t is t)
        self._fit_split()
        self.playing_now()     # a cached Test button may have said Stop when hidden

    def _make_editor(self, t: Trigger, sounds: list[tuple[str, str]]) -> TriggerRow:
        ed = TriggerRow(t, sounds, self._mons, open_=True,
                        parent=self.editor_pane)
        ed.pinned = True
        ed.btn_open.hide()
        ed.setProperty("interactive", False)   # the editor isn't a tile to pick
        self._wire(ed)
        ed.set_categories(self.groups.names())
        ed.set_default_interval(self.default_interval)
        ed.set_default_place(places_label([self.watcher.default]))
        ed.set_open(True)
        # its ✕, shown in the Pads view (_fit_split): the pads back across the width
        ed.btn_close = QPushButton(ed)
        ed.btn_close.setObjectName("fold")
        ed.btn_close.setFixedSize(28, 28)
        ed.btn_close.setAccessibleName(_("Close this trigger"))
        ed.btn_close.setToolTip(_("Close this trigger"))
        icons.set_icon(ed.btn_close, "close", "muted", "muted", size=16)
        ed.btn_close.clicked.connect(self._drop_editor)
        ed.btn_close.hide()
        ed.top.addWidget(ed.btn_close, 0, 5, 2, 1, Qt.AlignmentFlag.AlignVCenter)
        return ed

    def _clear_editor_cache(self):
        for _snapshot, ed in self._editor_cache.values():
            ed.deleteLater()
        self._editor_cache.clear()

    def _drop_editor(self, keep: bool = False):
        ed, self.editor = self.editor, None
        if ed is not None:
            self.editor_pane.layout().removeWidget(ed)
            ed.hide()
            if keep:
                self._editor_cache[ed.t.id] = (self._editor_snapshot, ed)
                # Bound the hidden widget trees even when browsing hundreds of triggers.
                while len(self._editor_cache) > 3:
                    _snapshot, old = self._editor_cache.pop(next(iter(self._editor_cache)))
                    old.deleteLater()
            else:
                ed.deleteLater()
        if keep:
            return
        self._clear_editor_cache()
        for r in self.rows.values():
            r.set_selected(False)
        self._empty_shown(True)
        self._fit_split()       # (the Pads view: the pads the whole width again)

    def _empty_shown(self, on: bool):
        """The nothing-picked box, filling the pane; or the gap under a picked trigger."""
        ep = self.editor_pane.layout()
        ep.setStretch(ep.count() - 1, 0 if on else 1)
        self.editor_empty.setVisible(on)

    def _cards(self) -> list[TriggerRow]:
        """Every card made: the list's, and the editor."""
        return [*self.rows.values(), *([self.editor] if self.editor is not None else [])]

    def _views(self, tid: str) -> list[TriggerRow]:
        """The cards showing trigger `tid`: its one in the list, and the editor."""
        return [r for r in (self.rows.get(tid), self.editor)
                if r is not None and r.t.id == tid]

    def _sync_views(self):
        """After an edit, the list's card and the editor show the same trigger: the
        one that wasn't edited catches up."""
        ed = self.editor
        if ed is None:
            return
        tile = self.rows.get(ed.t.id)
        t = ed.t
        for r in (tile, ed):
            if r is None:
                continue
            if r.name.text() != t.name and not r.name.hasFocus():
                r.name.setText(t.name)
            if r.chk_on.isChecked() != t.enabled:
                r.chk_on.blockSignals(True)
                r.chk_on.setChecked(t.enabled)
                r.chk_on.blockSignals(False)
                r.show_score(None)
            r.refresh_pictures()
        if ed.cb_category.currentData() != t.category:     # moved by its tile, a drag...
            ed.set_categories(self.groups.names())
        if tile is not None:
            tile.set_sounds(self.host.sounds())
            tile._show_mode()
            tile._update_state()

    def _fit_top(self):
        """The line over the list: stacked in a narrow window, and only the parts
        there's a use for (the category to search and the profile once there are
        categories, Clear and the count while searching, else what's on)."""
        width = self.width()
        stacked = width < 600
        self.search_line.layout().setDirection(
            QBoxLayout.TopToBottom if stacked else QBoxLayout.LeftToRight)
        self.search_text.setMaximumWidth(16777215 if stacked else 360)
        grouped = self._grouped()
        active = self._search_ids is not None
        self.search_scope.setVisible(grouped)
        self.btn_clear_search.setVisible(active)
        self.search_summary.setVisible(active)
        self.lbl_counts.setVisible(grouped and not active and not stacked)
        self.groupbar.setVisible(grouped)
        self.btn_categories.setEnabled(self._named_categories())
        # the view's controls share the search's line only while they, the search box
        # (SEARCH_ROOM) and the counts' first part fit there at their usual widths (a
        # layout short of room squeezes the search box first); else they go under it,
        # one above the other when even a line of their own is too narrow for them
        line = [self.search_scope, self.btn_clear_search, self.search_summary]
        view = [self.cb_per_row, self.chk_advanced, self.groupbar]
        counts = 0 if self.lbl_counts.isHidden() else self.lbl_counts.least_width() + 8
        wanted = SEARCH_ROOM + 8 + counts + _row_width(line + view, least=False)
        one_line = not stacked and width >= wanted
        self.view_bar.layout().setDirection(
            QBoxLayout.TopToBottom if stacked or width < _row_width(view)
            else QBoxLayout.LeftToRight)
        self.search_text.setMinimumWidth(SEARCH_ROOM if one_line else SEARCH_MIN)
        target = self.search_line.layout() if one_line else self.search_bar.layout()
        assert target is not None
        if self.view_bar.parentWidget() is not target.parentWidget():
            self.view_bar.parentWidget().layout().removeWidget(self.view_bar)
            target.addWidget(self.view_bar)
        target.setAlignment(self.view_bar,
                            Qt.Alignment() if stacked else Qt.AlignmentFlag.AlignLeft)
        # beside the editor, the line in the list's and the editor's columns: New trigger
        # as wide as the list, the search box from where the editor starts. Only while
        # the search box keeps its room (with categories, a search or a profile on the
        # line too, New trigger stays its own width)
        gap = self.splitter.handleWidth()
        rest = (_row_width(line, least=False) + counts
                + (_row_width(view, least=False) + 8 if one_line else 0))
        columns = (self.split and not self.pads and not stacked
                   and width - LIST_WIDTH - gap - rest - 8 >= SEARCH_ROOM)
        self.btn_new.setMinimumWidth(LIST_WIDTH if columns else 0)
        self.btn_new.setMaximumWidth(LIST_WIDTH if columns else 16777215)
        self.search_line.layout().setSpacing(gap if columns else 8)

    def _on_view(self, i: int):
        n = self.cb_per_row.itemData(i)
        if n in (LIST_VIEW, PADS_VIEW):
            self.set_list_view(True, pads=n == PADS_VIEW)
        else:
            self.set_list_view(False)
            self.set_per_row(n)

    def _view_data(self):
        """The View list's entry for the view in use."""
        return (PADS_VIEW if self.list_view and self.pads else LIST_VIEW if self.list_view
                else self.per_row)

    def set_list_view(self, on: bool, pads: bool = False):
        """The list beside an editor (`pads`: pads, as many to a line as fit, beside
        it), or cards that open where they are; kept for the next start."""
        pads = on and pads
        if pads != self.pads and self.split:
            self._set_split(False)      # (laid out again for the other kind below)
        self.list_view = on
        self.pads = pads
        self.host.screen["view"] = "pads" if pads else "list" if on else "cards"
        self.host.save()
        want = self.cb_per_row.findData(self._view_data())
        if self.cb_per_row.currentIndex() != want:
            self.cb_per_row.setCurrentIndex(want)
        self._show_pads()
        self._set_split(on and self.width() >= SPLIT_MIN)
        self._label_view()

    def _label_view(self):
        """The View box says what's on screen: "List and editor" picked in a window too
        narrow for the two columns shows cards that open where they are, so it says so
        (back to "List and editor" once the window's wide enough again)."""
        i = self.cb_per_row.findData(LIST_VIEW)
        if i < 0:
            return
        narrow = self.list_view and not self.pads and self.width() < SPLIT_MIN
        text = _("Cards (too narrow)") if narrow else _("List and editor")
        if self.cb_per_row.itemText(i) != text:
            self.cb_per_row.setItemText(i, text)

    def _show_pads(self):
        """Every card and category grid as pads (the Pads view) or as tiles."""
        for sec in self.sections.values():
            sec.body_layout.set_pads(self.pads)
        for row in self.rows.values():
            row.set_pad(self.pads)
        for sec in self.sections.values():
            sec.body._fit()

    def set_per_row(self, n: int):
        """`n` closed cards to a line (0: as many as fit), kept for the next start."""
        self.per_row = n if 0 < n <= MAX_PER_ROW else 0
        self.host.screen["cards_per_row"] = self.per_row
        self.host.save()
        want = self.cb_per_row.findData(self._view_data())
        if self.cb_per_row.currentIndex() != want:
            self.cb_per_row.setCurrentIndex(want)
        for sec in self.sections.values():
            sec.body_layout.set_per_row(self.per_row)
            sec.body._fit()

    def show_search(self, category: str | None = None):
        """Put the cursor in the search box (Ctrl+F), to search `category` if given."""
        if category is not None:
            self.search_scope.setCurrentIndex(max(0, self.search_scope.findData(category)))
        self.search_text.setFocus()
        self.search_text.selectAll()

    def clear_search(self):
        self.search_text.blockSignals(True)
        self.search_scope.blockSignals(True)
        self.search_text.clear()
        self.search_scope.setCurrentIndex(0)
        self.search_text.blockSignals(False)
        self.search_scope.blockSignals(False)
        self._apply_search()

    def _search_categories(self):
        scope = self.search_scope.currentData()
        self.search_scope.blockSignals(True)
        self.search_scope.clear()
        self.search_scope.addItem(_("All categories"), None)
        for name in self.groups.names():
            self.search_scope.addItem(profiles.label(name), name)
        self.search_scope.setCurrentIndex(max(0, self.search_scope.findData(scope)))
        self.search_scope.blockSignals(False)

    def _apply_search(self, *__):
        """Filter model data, including unbuilt/folded cards, without changing watching."""
        words = self.search_text.text().casefold().split()
        scope = self.search_scope.currentData()
        active = bool(words) or scope is not None
        was_active = self._search_ids is not None
        sounds = dict(self.host.sounds())
        self._search_ids = set() if active else None
        if active:
            for t in self.triggers:
                text = " ".join([t.name, profiles.label(t.category),
                                 *[f"{s.label} {s.exe}"
                                   for s in (t.sources or [self.watcher.default])
                                   if isinstance(s, WindowRef)],
                                 *[sounds.get(s, s) for s in t.sounds]]).casefold()
                if (scope is None or t.category == scope) and all(w in text for w in words):
                    self._search_ids.add(t.id)
        for name, sec in self.sections.items():
            matches = any(t.category == name and self._matches_search(t) for t in self.triggers)
            sec.setVisible(matches if active else True)
            sec.set_open(matches if active else self.groups.find(name).open)
            if sec.is_open and (active or was_active):
                self._build(sec)
        # a card shown in a shown grid lays the whole grid out there and then, so with
        # hundreds of cards to show, clearing a search took a quarter of a second. A
        # grid with several to show hides while they're shown: shown again, it's laid
        # out once
        change = [(row, self._matches_search(row.t)) for row in self.rows.values()]
        change = [(row, on) for row, on in change if row.isHidden() == on]
        showing: dict[QWidget, int] = {}
        for row, on in change:
            body = row.parentWidget()
            if on and body is not None and not body.isHidden():
                showing[body] = showing.get(body, 0) + 1
        focus = QApplication.focusWidget()      # (hidden, it would lose the cursor)
        bodies = [body for body, n in showing.items()
                  if n > 1 and not (focus and body.isAncestorOf(focus))]
        for body in bodies:
            body.hide()
        for row, on in change:
            row.setVisible(on)
        for body in bodies:
            body.show()
        self.no_results.setVisible(active and not self._search_ids)
        self.empty.setVisible(not self.triggers and not active)
        self._fit_empty()
        self.search_summary.setText(
            _("{n} of {n2}", n=len(self._search_ids), n2=len(self.triggers)) if active else "")
        self.search_summary.setToolTip(_("Matching triggers; watching is unchanged"))
        self._fit_top()

    def _matches_search(self, trigger: Trigger) -> bool:
        return self._search_ids is None or trigger.id in self._search_ids

    # ------------------------------------------------------------------ the default
    def _saved_default(self) -> int | WindowRef:
        s = self.host.screen
        ref = WindowRef.from_raw(s.get("window"))
        if ref is not None:
            return ref
        mon = s.get("monitor", 0)
        return mon if isinstance(mon, int) and not isinstance(mon, bool) else 0

    def set_default(self, src: int | WindowRef):
        """Where triggers without their own window / screen look."""
        self._put_default(src)
        self.host.save()
        self._fill_sources()

    def _put_default(self, src: int | WindowRef):
        self.watcher.set_default(src)
        if isinstance(src, WindowRef):
            self.host.screen["window"] = src.to_raw()
        else:
            self.host.screen["window"] = None
            self.host.screen["monitor"] = src

    def _on_where(self, i: int):
        data = self.cb_where.itemData(i)
        if data == PICK_WINDOW:
            self._fill_sources()            # back to the current choice until one is picked
            ref = self.pick_window(self.watcher.default
                                   if isinstance(self.watcher.default, WindowRef) else None)
            if ref is not None:
                self.set_default(ref)
        elif isinstance(data, int) and not isinstance(data, bool):
            self.set_default(data)

    def pick_window(self, current: WindowRef | None = None, heading: str = ""
                    ) -> WindowRef | None:
        from onionwatch.ui.triggers.windowpicker import WindowPicker
        dlg = WindowPicker(self, current, heading=heading)
        return dlg.chosen if dlg.exec() else None

    def pick_places(self, current: list) -> list | None:
        """The windows and screens a trigger looks in, picked in a list (None:
        cancelled)."""
        from onionwatch.ui.triggers.windowpicker import WindowPicker
        dlg = WindowPicker(self, current, multi=True)
        return dlg.places if dlg.exec() else None

    def _pick_for(self, row: TriggerRow):
        usage.used("pick-windows")
        places = self.pick_places(row.t.sources)
        if places:
            row.set_places(places)

    def change_window(self, old: WindowRef) -> bool:
        """"Change window" on a card waiting for `old`: pick another window, and
        everything that looked in `old` looks in it instead (retarget_window)."""
        new = self.pick_window(old)
        if new is None or new == old:
            return False
        return self.retarget_window(old, new)

    def retarget_window(self, old: WindowRef, new: WindowRef) -> bool:
        """Swap the window `old` for `new` everywhere at once: the default Look in,
        every trigger's places (copies and "every copy" ones too, see retarget), and
        `old`'s program for `new`'s in the profiles. Saved once, with an Undo bar.
        False if nothing used `old`."""
        before_default = self.watcher.default
        before_sources = {t.id: list(t.sources) for t in self.triggers}
        before_apps = {p.id: list(p.apps) for p in self.groups.profiles}
        default = retarget(before_default, old, new)
        moved = []
        for t in self.triggers:
            places = retargeted(t.sources, old, new)
            if places != t.sources:
                t.sources = places
                moved.append(t)
        apps = bool(old.exe and new.exe) and self.groups.replace_app(old.exe, new.exe)
        if default == before_default and not moved and not apps:
            return False
        ids = {t.id for t in moved}
        before_sources = {k: v for k, v in before_sources.items() if k in ids}
        before_apps = {p.id: before_apps[p.id] for p in self.groups.profiles
                       if p.id in before_apps and p.apps != before_apps[p.id]}
        if default != before_default:
            self._put_default(default)

        def refresh():
            for t in self.triggers:
                row = self.rows.get(t.id)
                if row is not None and t.id in ids:
                    row.note = row.waiting = None
                    row.set_screens(self._mons)
            self._fill_sources()
            self.profilectl._update_app_timer()
            self._store()
        refresh()

        def undo():
            if self.watcher.default == default:
                self._put_default(before_default)
            for t in self.triggers:
                if t.id in ids:
                    t.sources = before_sources[t.id]
            for p in self.groups.profiles:
                if p.id in before_apps:
                    p.apps = before_apps[p.id]
            refresh()
        what = [triggers(len(moved))] if moved else []
        if default != before_default:
            what.append(_("the default Look in"))
        if apps:
            what.append(_("profiles"))
        self.undo_bar.show_for(_("Moved {what} to {place}", what=", ".join(what),
                                 place=new.label), undo,
                               tip=_("Look in {place} again", place=old.label))
        return True

    # ------------------------------------------------------------------ watching
    @property
    def pictures(self) -> Path:
        """The folder the trigger pictures are kept in."""
        return pictures_dir(self.host)

    def showEvent(self, ev):
        super().showEvent(ev)
        self.sounds_changed()     # the host's sounds may have been renamed meanwhile
        self._fill_sources()      # ...and screens plugged in or out
        if self.poll.isActive() and self._on_screen():
            self._show_poll()     # what watching found while it was hidden

    def is_active(self) -> bool:
        return self.btn_watch.isChecked()

    def set_watching(self, on: bool, remember: bool = True):
        """Start / stop watching. `remember`: keep it as the setting for next launch
        (not when watching stopped by itself: it's tried again then)."""
        if self.btn_watch.isChecked() != on:
            self.btn_watch.blockSignals(True)
            self.btn_watch.setChecked(on)
            self.btn_watch.blockSignals(False)
        if on:
            usage.used("watching")
            self._fill_sources()
            self._sync()
            self.watcher.start()
            self.poll.start(POLL_MS)
        else:
            self.watcher.stop()
            self.poll.stop()
            self.cancel_pending()
            if remember and self.host.ringing():
                self.stop_ringing()     # you switched it off: you're here
            for row in self._cards():
                row.watching = False    # else the card keeps saying "Watching"
                row.show_score(None)
                row.set_note(None)
        if remember:
            self.host.screen["on"] = on
            self.host.save()
        self._label_watch()
        self._show_warning()
        self.active_changed.emit(on)

    def _label_watch(self):
        text = _("Watching") if self.is_active() else _("Start watching")
        self.btn_watch.setProperty("full_text", text)   # a host that shows it icon only
        if not self.btn_watch.property("compact"):       # reads it back when there's room
            self.btn_watch.setText(text)
            icons.text_gap(self.btn_watch)   # it had no words when its icon was set

    def fit_parts(self) -> dict[str, QWidget]:
        """What a host may hide, or show as an icon only, when its window gets small:
        "hint" (the explanation at the top) and the "watch" button (icon only). New
        triggers are made with + New trigger now, and the check speed is under ⚙: a host
        asking for "cut", "add", "paste" or "interval_label" gets nothing, and leaves it be."""
        return {"hint": self.hint, "watch": self.btn_watch}

    def cancel_pending(self):
        """Drop sounds that are still waiting out their delay (switched off, Stop all)."""
        self._gen += 1

    def stop_ringing(self):
        for tag in self.host.ringing():
            self.host.stop_tag(tag)
        self._forget_ring()
        self.ringing_changed.emit()

    def _watch_ring(self, t: Trigger):
        """`t` just started ringing: watch for what stops it by itself (Trigger.stop)."""
        self._forget_ring(t.id)
        self._ring_how[t.id] = t.stop
        hit = self._hits.get(t.id)
        if t.stop == "input":
            self._input_waits[t.id] = time.monotonic()
            self._input_poll.start(INPUT_POLL_MS)
        elif hit is not None:
            self.watcher.quiet_on(t.id, hit.source, t.stop)

    def _forget_ring(self, tid: str | None = None):
        """Stop watching for what stops trigger `tid`'s ringing (None: every one's)."""
        self.watcher.quiet_off(tid)
        if tid is None:
            self._input_waits.clear()
        else:
            self._input_waits.pop(tid, None)
        if not self._input_waits:
            self._input_poll.stop()

    def _check_input(self):
        """The "input" rings: stop each once the mouse or keyboard has been touched
        since it began (after the first STOP_LEAST seconds, so it's heard)."""
        idle = windows.idle_seconds()
        if idle is None:
            return
        now = time.monotonic()
        for tid, since in list(self._input_waits.items()):
            if idle < now - since - screenwatch.STOP_LEAST:
                self._stop_by_itself(tid)

    def _stop_by_itself(self, tid: str):
        """What stops trigger `tid`'s ringing happened: stop it."""
        self._forget_ring(tid)
        if tid not in self.host.ringing():
            return
        self.host.stop_tag(tid)
        t = next((t for t in self.triggers if t.id == tid), None)
        log.info("trigger %r stopped ringing by itself", t.name if t else tid)
        for row in self._views(tid):
            row.flash(_("Stopped ringing — you're back"), 4000)
        self.ringing_changed.emit()

    def retheme(self):
        """The theme changed (onionwatch.ui.kit.theme.T has the new colours): redraw what
        was coloured by hand."""
        icons.retheme()
        self._update_new_trigger_glow()
        self._search_icon.setIcon(icons.icon("search", "muted"))
        self.undo_bar.restyle()
        for sec in self.sections.values():
            sec.retheme()             # category tabs fade into the new panel colour
        self.sounds_changed(force=True)   # the chips of sounds that are gone
        self._clear_editor_cache()      # hidden editors keep the old theme's colours
        for row in self._cards():
            row.setStyleSheet(card_css())   # its colours are the theme's, written in
            row._show_mode()           # the badge of a trigger without pictures
            row.show_score(self.watcher.scores.get(row.t.id) if self.is_active() else None)

    def shutdown(self):
        self._clear_editor_cache()
        self._input_poll.stop()
        self.poll.stop()
        self.watcher.stop()
        self.cancel_pending()

    def _sync(self):
        """Hand the watcher the triggers that can fire, pictures loaded and grey."""
        items = []
        for t in self.triggers:
            if not (self.is_on(t) and self.ready(t) and self._playable(t)):
                continue
            got = [(p, path) for path in (t.images if t.uses_pictures else [])
                   if (p := self._picture(path)) is not None]
            if got or not t.uses_pictures:
                items.append(Watched(t.id, [p for p, _path in got], t.number, t.cooldown,
                                     sources=list(t.sources), mode=t.mode, below=t.below,
                                     colour=t.rgb, region=t.region, hold=t.hold,
                                     unfocused=t.unfocused, any_size=t.any_size,
                                     interval_ms=t.interval_ms,
                                     cuts=[self._cuts.get(path) for _p, path in got],
                                     wide=[self._wide.get(path, False) for _p, path in got],
                                     tints=[self._tints.get(path) for _p, path in got],
                                     colours=[self._colours.get(path) for _p, path in got]))
        self.watcher.set_items(items)

    ready = staticmethod(trigger_ready)

    def _picture(self, path: str) -> Picture | None:
        try:
            mtime = Path(path).stat().st_mtime
        except OSError:
            return None
        got = self._gray.get(path)
        if got is not None and got[0] == mtime:
            return got[1]
        img = QImage(path)
        pic = picture_of(img)
        if pic is not None:
            self._gray[path] = (mtime, pic)
            self._cuts[path] = cut_size(img)
            self._wide[path] = is_web(img)
            self._tints[path] = picture_tint(img)
            self._colours[path] = picture_rgb(img)
        return pic

    def _playable(self, t: Trigger) -> list[str]:
        """The trigger's sounds that are still in the library, in its order."""
        have = {sid for sid, _name in self.host.sounds()}
        return [sid for sid in t.sounds if sid in have]

    def _on_fired(self, tid: str, hit: screenwatch.Hit | None = None):
        t = next((t for t in self.triggers if t.id == tid), None)
        if t is None or not self.is_active() or not self._playable(t):
            return
        self.cooldowns[tid] = time.monotonic() + t.cooldown
        for row in self._views(tid):
            row.cooldown_until = time.monotonic() + t.cooldown
        if hit is not None:
            # where it went off is all that's needed later (_watch_ring, _in): not the
            # picture of the window, which the history keeps small
            self._hits[tid] = dataclasses.replace(hit, frame=None)
            self.history.append(Alert.of(t, hit, self.place_name(hit.source)))
            self.history_changed.emit()
        gen = self._gen
        if t.delay > 0:
            for row in self._views(tid):
                place = self._in(tid)
                row.flash(_("Seen in {place}! Playing in {s:g} s…", place=place, s=t.delay)
                          if place else _("Seen! Playing in {s:g} s…", s=t.delay),
                          int(t.delay * 1000) + 1500)
            QTimer.singleShot(int(t.delay * 1000), self, lambda: self._fire(tid, gen))
        else:
            self._fire(tid, gen)

    def _fire(self, tid: str, gen: int):
        t = next((t for t in self.triggers if t.id == tid), None)
        if gen != self._gen or t is None or not self.is_on(t):
            return
        if self._play_trigger(t):
            log.info("trigger %r matched", t.name)
            for row in self._views(tid):
                place = self._in(tid)
                if place:
                    text = (_("Ringing in {place}!", place=place) if t.ring
                            else _("Played in {place}!", place=place))
                else:
                    text = _("Ringing!") if t.ring else _("Played!")
                row.flash(text, 4000)
            if t.ring:
                self._watch_ring(t)
            self._live[t.id] = time.monotonic()
            self.playing_changed.emit()
            usage.used("went-off")
            self.fired.emit(t)

    def place_name(self, place) -> str:
        """A window or screen as the alerts name it: "Game (copy 2)", "screen 2"."""
        return source_label(place, self._mons)

    def _in(self, tid: str) -> str:
        """"Game (copy 2)" for a trigger looking in more than one place (else ""):
        which one it went off in."""
        hit = self._hits.get(tid)
        places = self.watcher.where.get(tid, ())
        if hit is None or len(places) < 2:
            return ""
        return self.place_name(hit.source)

    def alert_text(self, t: Trigger) -> str:
        """The words of a notification for `t` going off: what happened and where."""
        where = self._in(t.id)
        what = {"appear": _("It just showed up"), "vanish": _("It went away"),
                "change": _("Something changed"), "still": _("Nothing has moved for a while"),
                "colour": _("The bar ran low") if t.below else _("The bar filled up")}[t.mode]
        what = _("{what} in {place}.", what=what, place=where) if where else what + "."
        return what + (" " + UNTILS[t.stop][2] if t.ring else "")

    def _play_trigger(self, t: Trigger, test: bool = False) -> list[str]:
        """Play the trigger's sound(s) the way its Play setting says: one at random
        (a shuffle bag: each once before any repeats, never twice running), the next
        in turn, or all of them; ringing (over and over) when it's set to, except for a
        test. Sounds no longer in the library are skipped; when none of the chosen
        ones will play (a file gone or undecodable), the host's default sound
        does. Returns what played."""
        pool = self._playable(t)
        if not pool:
            return []
        if t.pick == "all":
            chosen = pool
        elif t.pick == "order":
            n, i = len(t.sounds), self._order.get(t.id, 0)
            chosen = []
            for __ in range(n):
                sid, i = t.sounds[i % n], i + 1
                if sid in pool:
                    chosen = [sid]
                    break
            self._order[t.id] = i % n
        else:
            chosen = [self._bag.next(t.id, pool)]
        ring = t.ring and not test
        if ring:
            self.host.stop_tag(t.id)        # one ring per trigger, not a pile of them

        def play(sid: str) -> bool:
            if ring:
                return self.host.play(sid, loop=True, tag=t.id)
            tag = self._shot_tag(t.id, sid)
            self.host.stop_tag(tag)         # pressed again: from the start, not twice
            if not self.host.play(sid, tag=tag):
                return False
            self._played.setdefault(t.id, set()).add(sid)
            return True
        played = [sid for sid in chosen if play(sid)]
        fallback = self.host.default_sound
        if not played and fallback and fallback not in chosen:
            # its sound file is gone or won't decode: an alarm that makes no sound is
            # worse than the wrong one, so the default alert plays instead
            log.warning("trigger %r: its sound couldn't be played, playing the default "
                        "alert instead", t.name)
            if play(fallback):
                played = [fallback]
        if ring and played:
            self._ring_sounds[t.id] = played
            self.ringing_changed.emit()
        return played

    def _poll(self):
        w = self.watcher
        if not w.running and self.is_active():
            # the thread died (_show_warning says why): stop, but leave the setting on
            self.set_watching(False, remember=False)
            return
        if w.fell_back != self._fell_back:
            # a trigger's own screen went away (or came back) while watching
            self._fell_back = w.fell_back
            self._fill_sources()
        heavy = w.gap > HEAVY_GAP and w.gap > w.interval * 1.05
        if not heavy:
            self._heavy_since = None
        elif self._heavy_since is None:
            self._heavy_since = time.monotonic()
        # the rest is only for the eye: nothing while the tab is hidden or its window
        # minimised (showEvent catches up, and so does the next check after a restore)
        if self._on_screen():
            self._show_poll()

    def _on_screen(self) -> bool:
        return self.isVisible() and not self.window().isMinimized()

    def _show_poll(self):
        """What watching says on each card (notes, live scores) and at the bottom."""
        w = self.watcher
        for row in self._cards():
            row.set_note(*self._first_note(w.where.get(row.t.id, ())))
        if self._gap_text() != self._gap_shown:
            self._refresh_counts()
        for row in self._cards():
            row.watching = w.running and self.is_on(row.t)
            row.show_score(w.scores.get(row.t.id))
        self._show_warning()

    def _first_note(self, places) -> tuple[tuple[str, str] | None, WindowRef | None]:
        """What to say on a card about the places it's looked in: the first problem,
        and the window it's about when that one isn't open (for "Change window")."""
        for src in places:
            note = self._note(src)
            if note is not None:
                waiting = src if isinstance(src, WindowRef) and src in self.watcher.failed \
                    else None
                return note, waiting
        return None, None

    def _note(self, src) -> tuple[str, str] | None:
        """What to say on a card about the window / screen it's looked for in."""
        w = self.watcher
        if src is None:
            return None
        name = source_label(src, self._mons)
        if src in w.failed:
            if isinstance(src, WindowRef):
                return _("Waiting for {name} to open", name=name), "warn"
            return _("Screen {n} can't be captured — waiting for it", n=src + 1), "warn"
        if src in w.minimized:
            return _("{name} is minimized, so it can't be seen — restore it (covering it "
                     "with other windows is fine)", name=name), "warn"
        if src in w.unseen:
            if isinstance(src, WindowRef):
                return _("{name} can't be captured: nothing comes out of it. Pick its "
                         "screen under Look in instead.", name=name), "warn"
            return _("Screen {n} gives no picture — waiting for one", n=src + 1), "warn"
        if src in w.blacked:
            if isinstance(src, WindowRef):
                return _("{name} comes out black. Some games can only be seen on the "
                         "screen: pick its screen under Look in instead.", name=name), "warn"
            return _("The screen looks all black. If the game is in exclusive fullscreen, "
                     "set it to Borderless or Windowed."), "warn"
        return None

    def _show_warning(self):
        w, why = self.watcher, ""
        ok, unsupported = screenwatch.supported()
        if not ok:
            why = unsupported
        elif w.error:
            why = _("Watching stopped: {error}", error=w.error)
        elif self.is_active() and w.lost:
            why = _("Waiting for the screen to come back. A game switching to or from "
                    "fullscreen does this for a moment.")
        elif self.is_active() and not w.scores and not w.failed and not any(
                self.is_on(t) and self.ready(t) and t.sounds for t in self.triggers):
            if any(t.enabled and self.ready(t) and t.sounds for t in self.triggers):
                why = _("Nothing to watch for: the triggers that could go off are all in "
                        "categories that are off now.")
            else:
                why = _("Nothing to watch for yet: each trigger needs a sound, and a "
                        "picture (or its bar) to look for.")
        elif (self.is_active() and self._heavy_since is not None
              and time.monotonic() - self._heavy_since >= HEAVY_FOR):
            n = self._counts()[2]
            why = ngettext("Each trigger is checked only every {s:.1f} s: {n} picture is on, "
                           "more than this computer looks for in {share} of its processor. "
                           "Let it use more under ⚙, switch off a category, or give triggers "
                           "an Area to look in, to check more often.",
                           "Each trigger is checked only every {s:.1f} s: {n} pictures are on, "
                           "more than this computer looks for in {share} of its processor. "
                           "Let it use more under ⚙, switch off a category, or give triggers "
                           "an Area to look in, to check more often.",
                           n, s=w.gap, share=share_label(w.cpu_share))
        self.warn.setText(why)
        self.warn.setVisible(bool(why))

    @property
    def default_interval(self) -> int:
        """How often (ms) triggers left on "Default" are checked."""
        return round(self.watcher.interval * 1000)

    def set_default_interval(self, ms: int):
        """The check speed of triggers on "Default" (Watching settings), kept, and
        shown on every card's "Check every"."""
        if ms not in INTERVALS_MS:
            return
        self.watcher.interval = ms / 1000
        self.host.screen["interval_ms"] = ms
        self.host.save()
        for row in self._cards():
            row.set_default_interval(ms)

    def _on_advanced(self, on: bool):
        self.host.screen["advanced_cards"] = on
        self.host.save()
        for row in self.rows.values():
            row.set_advanced(on)

    def _fill_sources(self):
        """List the screens again: the "Look in" at the bottom (the default) and each
        card's own. A change while watching is passed on to the watcher."""
        mons = screenwatch.monitors()
        d = self.watcher.default
        fill_sources(self.cb_where, mons, [d])
        place = places_label([d])
        for row in self._cards():
            row.set_default_place(place)
            row.set_screens(mons)
        if mons != self._mons and self.watcher.running:
            self.watcher.rescan()
        self._mons = mons

    # ------------------------------------------------------------------ categories
    # Triggers sit in categories (Trigger.category, onionwatch.engine.profiles), each a
    # section of the list. A section's cards are only made once it's opened, so a
    # library of hundreds opens at once, and a trigger is watched for only while
    # it's on and so is its category (is_on): one that's off costs nothing.
    def is_on(self, t: Trigger) -> bool:
        """It's switched on, and so is its category (by hand or by a profile)."""
        return t.enabled and t.category in self._active

    def _grouped(self) -> bool:
        """There's more than the one category, or a profile: show the sections'
        headers and the Profile line."""
        return len(self.groups.categories) > 1 or bool(self.groups.profiles)

    def _shown_categories(self) -> list[str]:
        """The categories with a section: all of them, but Uncategorised only while
        a trigger is in it or it's the only one."""
        have = {t.category for t in self.triggers}
        names = self.groups.names()
        return [n for n in names if n or n in have or len(names) == 1]

    def _new_category(self) -> str:
        """The category a new trigger goes in: the one last opened, if it's still there."""
        return self._last_category if self.groups.find(self._last_category) else ""

    def _section_of(self, t: Trigger) -> CategorySection:
        self.groups.ensure(t.category)
        if t.category not in self.sections:
            self._layout_sections()
        return self.sections[t.category]

    def _make_section(self, name: str) -> CategorySection:
        sec = CategorySection(name)
        sec.fold_toggled.connect(self._on_fold)
        sec.switched.connect(self._on_switch)
        sec.menu_wanted.connect(self._category_menu)
        sec.add_wanted.connect(self._category_add_menu)
        sec.search_wanted.connect(self.show_search)
        sec.body_layout.set_per_row(self.per_row)
        sec.body_layout.set_pads(self.pads)
        sec.card_dropped.connect(self.reorder)
        sec.drag_at.connect(self._scroll_for_drag)
        sec.set_look(self.groups.find(name), self.host.data_dir)
        self.sections[name] = sec
        return sec

    def _named_categories(self) -> bool:
        """There's a category of the user's own (the Categories window has a use)."""
        return any(n != profiles.UNCATEGORISED for n in self.groups.names())

    def edit_categories(self, start: str = ""):
        """The Categories window: each category's colours and picture."""
        if not start:
            start = next((n for n in self.groups.names() if n != profiles.UNCATEGORISED),
                         "")
        dlg = CategoriesDialog(self, self.groups.categories, self.host.data_dir, start)
        if dlg.exec():
            self.set_category_looks(dlg.result)

    def set_category_looks(self, looks: dict):
        """Give categories their looks (name -> Category.full_look(); a category
        left out keeps its own) and show them."""
        for c in self.groups.categories:
            if c.name in looks:
                c.set_full_look(looks[c.name])
        for name, sec in self.sections.items():
            sec.set_look(self.groups.find(name), self.host.data_dir)
        self._save_groups()

    def reorder(self, tid: str, category: str, before: str | None = None):
        """A card was dragged: put its trigger in `category`, just before trigger
        `before` (None: after the category's last). The list's order is what's saved,
        so it's kept, also by older versions."""
        t = next((x for x in self.triggers if x.id == tid), None)
        if t is None or before == tid:
            return
        cat = profiles.clean_name(category)
        rest = [x for x in self.triggers if x is not t]
        at = next((i for i, x in enumerate(rest) if x.id == before and x.category == cat),
                  None)
        if at is None:      # after the category's last, or at the end
            at = max((i + 1 for i, x in enumerate(rest) if x.category == cat),
                     default=len(rest))
        if rest[:at] + [t] + rest[at:] == self.triggers and t.category == cat:
            return          # dropped where it already was
        self.triggers[:] = rest[:at] + [t] + rest[at:]
        if t.category != cat:
            self.move_trigger(t, cat)       # places its card, and saves
            return
        sec = self.sections.get(cat)
        if sec is not None and t.id in self.rows:
            self._place_row(t, sec)
        self._store()

    def _scroll_for_drag(self, at: QPoint):
        """A card dragged near the top or bottom of the list scrolls it."""
        vp = self.scroll.viewport()
        y = vp.mapFromGlobal(at).y()
        bar = self.scroll.verticalScrollBar()
        edge = 40
        if y < edge:
            bar.setValue(bar.value() - (edge - y))
        elif y > vp.height() - edge:
            bar.setValue(bar.value() + (y - vp.height() + edge))

    def _drop_section(self, name: str):
        sec = self.sections.pop(name, None)
        if sec is None:
            return
        for tid in [tid for tid, r in self.rows.items() if r.parentWidget() is sec.body]:
            self._drop_row(tid)
        self.list_layout.removeWidget(sec)
        sec.setParent(None)
        sec.deleteLater()

    def _layout_sections(self):
        """Make, order and label the sections, and make the open ones' cards."""
        names = self._shown_categories()
        for n in list(self.sections):
            if n not in names:
                self._drop_section(n)
        lone = len(names) == 1
        for i, n in enumerate(names):
            sec = self.sections.get(n) or self._make_section(n)
            if self.list_layout.indexOf(sec) != i + 1:
                self.list_layout.removeWidget(sec)
                self.list_layout.insertWidget(i + 1, sec)     # after the "no triggers" note
            sec.set_header_visible(not lone)
            c = self.groups.find(n)
            if lone:
                c.open = True       # and still open once a second category comes along
            sec.set_open(c.open)
            if c.open:
                self._build(sec)
        self.empty.setVisible(not self.triggers)
        self._fit_empty()
        self._refresh_switches()
        self._refresh_counts()

        self._search_categories()
        self._apply_search()

    def _set_open(self, sec: CategorySection, on: bool):
        c = self.groups.ensure(sec.name)
        c.open = on
        sec.set_open(on)
        if on:
            self._last_category = sec.name
            self._build(sec)

    def _on_fold(self, name: str, on: bool):
        sec = self.sections.get(name)
        if sec is None:
            return
        if self._search_ids is not None:
            return   # search temporarily opens categories; never persist those folds
        self._set_open(sec, on)
        self.groups.save(self.host.screen)
        self.host.save()

    def _build(self, sec: CategorySection, need: Trigger | None = None):
        """Make the cards of `sec`'s triggers: BUILD_NOW now (and `need`), the rest
        a few at a time after (_build_more)."""
        todo = [t for t in self.triggers if t.category == sec.name and t.id not in self.rows
                and self._matches_search(t)]
        if sec.built and not todo:
            return
        sec.built = True
        one = len(self.triggers) == 1
        for t in todo[:BUILD_NOW]:
            self._place_row(t, sec, open_=one)
        if need is not None and need.id not in self.rows:
            self._place_row(need, sec, open_=True)
        if len(todo) > BUILD_NOW:
            QTimer.singleShot(0, self, lambda: self._build_more(sec))
        self._refresh_counts()

    def _build_more(self, sec: CategorySection):
        if self.sections.get(sec.name) is not sec or not sec.is_open:
            sec.built = False           # gone or folded meanwhile: the rest when reopened
            return
        todo = [t for t in self.triggers if t.category == sec.name and t.id not in self.rows
                and self._matches_search(t)]
        until = time.perf_counter() + BUILD_STEP_MS / 1000
        made = 0
        for t in todo:
            if made and time.perf_counter() > until:
                break
            self._place_row(t, sec)
            made += 1
        if len(todo) > made:
            QTimer.singleShot(0, self, lambda: self._build_more(sec))

    def _counts(self) -> tuple[int, int, int]:
        """(triggers, on, pictures on) over the whole list."""
        on = [t for t in self.triggers if self.is_on(t)]
        return (len(self.triggers), len(on),
                sum(len(t.images) for t in on if t.uses_pictures))

    @needs_part()
    def show_watching(self):
        if self.pages is not None and self.pages.settings is not None:
            self.pages.show_settings()      # inside Onion Board: on its Settings tab
            return
        from onionwatch.ui.settings.watching import WatchingDialog
        WatchingDialog(self, self).exec()

    def set_cpu_share(self, share: float):
        """How much of the processor watching may use (screenwatch.CPU_SHARES), kept."""
        self.watcher.cpu_share = share
        self.host.screen["cpu_share"] = share
        self.host.save()

    def set_max_detect(self, how: str):
        """"Max detection" (screenwatch.MAX_DETECTS), kept in a key of its own: the
        processor share stays as picked, for when it's off (and older versions)."""
        self.watcher.max_detect = how
        self.host.screen["max_detect"] = how
        self.host.save()

    def set_color_log(self, on: bool):
        """The Log's pictures in colour (on) or grey, kept as "color_log"."""
        self.watcher.color_hits = on
        self.host.screen["color_log"] = on
        self.host.save()

    def set_show_chances(self, on: bool):
        """The Chances button on the Playing now bar, shown or not ("show_chances")."""
        self.host.screen["show_chances"] = on
        self.host.save()
        if self.pages is not None:
            self.pages.playing.show_chances_button()

    def watching_text(self) -> str:
        """How often each trigger is checked now, for the Watching dialog."""
        pics = pictures(self._counts()[2])
        if not self.is_active() or not self.watcher.running:
            return _("Not watching right now ({pictures} on).", pictures=pics)
        w = self.watcher
        if w.heavy:
            text = _("Each trigger is checked every {s:.2f} s (max detection is on), with "
                     "{pictures} on.", s=w.gap, pictures=pics)
        elif w.gap > w.interval * 1.05:
            text = _("Each trigger is checked every {s:.2f} s (the most it can in that share), "
                     "with {pictures} on.", s=w.gap, pictures=pics)
        else:
            text = _("Each trigger is checked every {s:.2f} s, with {pictures} on.",
                     s=w.gap, pictures=pics)
        if any(t.interval_ms for t in self.triggers if self.is_on(t)):
            text = _("Watching ticks every {s:.2f} s, with {pictures} on. Each trigger follows "
                     "its own interval (or the default); the shared processor limit can make "
                     "checks slower.", s=w.gap, pictures=pics)
        if w.cpu_used is not None:
            text += "\n" + _("Watching is using about {share:.2f} % of your processor "
                             "({core:.0f} % of one core).", share=w.cpu_used * 100,
                             core=w.cpu_used * screenwatch.CORES * 100)
        return text

    def _gap_text(self) -> str:
        if not self.is_active() or not self.watcher.running:
            return ""
        if any(t.interval_ms for t in self.triggers if self.is_on(t)):
            return _("watching tick {s:.2f} s · individual intervals", s=self.watcher.gap)
        return _("each checked every {s:.1f} s", s=self.watcher.gap)

    def _update_new_trigger_glow(self):
        """Point to the first action only while the whole library is empty: an accent
        border and a faint accent fill. Never a QGraphicsEffect: one on this button
        stopped Onion Board painting the bottom bar of an empty library."""
        empty = not self.triggers
        self.btn_new.setProperty("glow", empty)
        if empty:
            a = QColor(theme.T.get("accent", theme.THEMES[theme.DEFAULT]["accent"]))
            rgb = f"{a.red()}, {a.green()}, {a.blue()}"
            self.btn_new.setStyleSheet(
                f"QPushButton#newtrigger {{ border-color:rgba({rgb}, 150); "
                f"background-color:rgba({rgb}, 40); }}"
                f"QPushButton#newtrigger:hover {{ background-color:rgba({rgb}, 70); }}"
                f"QPushButton#newtrigger:focus {{ border-color:{a.name()}; }}")
        else:
            self.btn_new.setStyleSheet("")

    def _refresh_counts(self):
        """The numbers on the sections' headers and the Profile line."""
        self._update_new_trigger_glow()
        per: dict[str, list[int]] = {}
        for t in self.triggers:
            n = per.setdefault(t.category, [0, 0, 0])
            n[0] += 1
            if t.enabled:
                n[1] += 1
                if t.uses_pictures:
                    n[2] += len(t.images)
        for name, sec in self.sections.items():
            n, on, pics = per.get(name, (0, 0, 0))
            cat_on = name in self._active
            sec.set_counts(counts_text(n, on, pics, cat_on), "" if cat_on else "warn")
            sec.empty.setVisible(not n and not sec.header.isHidden())
        total, on, pics = self._counts()
        parts = [ngettext("{on} of {n} trigger on", "{on} of {n} triggers on", total, on=on),
                 pictures(pics)]
        self._gap_shown = self._gap_text()
        if self._gap_shown:
            parts.append(self._gap_shown)
        state = self.profilectl._profile_state()
        self.lbl_counts.setText(" · ".join(parts) + (f"  —  {state}" if state else ""))
        self.lbl_counts.setToolTip(
            _("Triggers on, and the pictures they look for. Each picture on takes a share of the "
              "processor watching keeps to (⚙): with too many, each is checked less often. Turn "
              "off what you don't need now, or give triggers an Area."))

    def _refresh_switches(self):
        """Each section's switch: is it on now, and who says so."""
        ps = self.groups.in_charge(self.apps.matched)
        if not ps:
            tip = _("Switch the whole category on or off. Its triggers keep their own "
                    "switches, so turning it back on brings back just the ones that were on.")
        elif len(ps) == 1:
            tip = _("On or off as the profile “{name}” says: switching it changes "
                    "that profile.", name=ps[0].name)
        else:
            tip = _("On or off as the profiles {names} say (Automatic). "
                    "Change them under More → Profiles.", names=", ".join(p.name for p in ps))
        for name, sec in self.sections.items():
            sec.set_switch(name in self._active, tip)

    def _apply_active(self, force: bool = False) -> bool:
        """Work out which categories are on again; hand the watcher what changed."""
        active = self.groups.active(self.apps.matched)
        changed = active != self._active
        self._active = active
        if changed or force:
            if self.is_active():
                self._sync()
            self._refresh_switches()
            self._refresh_counts()
            self._show_warning()
        return changed

    def _on_switch(self, name: str, on: bool):
        """A category's switch was clicked."""
        if not self.groups.set_on(name, on, self.apps.matched):
            names = ", ".join(p.name for p in self.groups.in_charge(self.apps.matched))
            QMessageBox.information(self, _("Set by profiles"),
                                    _("The profiles {names} say which categories are on now "
                                      "(Profile is Automatic). Change them under More → "
                                      "Profiles.", names=names))
            self._refresh_switches()
            return
        self._save_groups()
        self._apply_active(force=True)
        if name not in self._active:        # you switched it off: its rings stop too
            for t in self.triggers:
                if t.category == name:
                    self._silence(t.id, ring=True)

    def _save_groups(self):
        self.groups.save(self.host.screen)
        self.host.save()

    def new_category(self, name: str | None = None) -> str | None:
        """Make a category (asked for when `name` isn't given): its name, or None."""
        if name is None:
            from PySide6.QtWidgets import QInputDialog
            name, ok = QInputDialog.getText(self, _("New category"), _("Name of the category:"))
            if not ok:
                return None
        name = profiles.clean_name(name)
        if not name:
            return None
        if self.groups.find(name) is None:
            if len(self.groups.categories) >= profiles.MAX_CATEGORIES:
                QMessageBox.information(self, _("Too many categories"),
                                        _("You can have up to {max_categories}.",
                                          max_categories=profiles.MAX_CATEGORIES))
                return None
            self.groups.ensure(name).open = True
        self._last_category = name
        self._categories_changed()
        return name

    def _categories_changed(self):
        """Categories were added, renamed, removed or moved: the sections, the cards'
        Category lists and the profiles follow."""
        self._layout_sections()
        names = self.groups.names()
        for row in self._cards():
            row.set_categories(names)
        self._apply_active(force=True)
        self._save_groups()

    def _move_to(self, row: TriggerRow, name: str):
        """A card's Category was changed."""
        if name == NEW_CATEGORY:
            name = self.new_category()
            if name is None:
                return
        self.move_trigger(row.t, name)

    def move_trigger(self, t: Trigger, name: str):
        """Put `t` in category `name` (made if need be). Its card moves there, if
        that category is open."""
        self._drop_row(t.id)
        t.category = profiles.clean_name(name)
        self.groups.ensure(t.category)
        self._last_category = t.category
        self._layout_sections()
        sec = self.sections.get(t.category)
        if sec is not None and sec.is_open and sec.built:
            row = self._place_row(t, sec)
            row.flash(_("Moved to {category}", category=profiles.label(t.category)))
        self._store()

    def rename_category(self, old: str, new: str) -> bool:
        new = profiles.clean_name(new)
        if old == profiles.UNCATEGORISED or not new or new == old:
            return False
        was_open = self.groups.find(old).open if self.groups.find(old) else False
        if not self.groups.rename(old, new):
            return False
        for t in self.triggers:
            if t.category == old:
                t.category = new
        self._drop_section(old)
        self._drop_section(new)
        self.groups.find(new).open = self.groups.find(new).open or was_open
        if self._last_category == old:
            self._last_category = new
        self._categories_changed()
        self._store()
        return True

    def set_category_triggers(self, name: str, on: bool):
        """Switch every trigger in a category on (or off), each one's own switch."""
        for t in self.triggers:
            if t.category != name or t.enabled == on:
                continue
            t.enabled = on
            for row in self._views(t.id):   # its card in the list, and the editor
                row.chk_on.blockSignals(True)
                row.chk_on.setChecked(on)
                row.chk_on.blockSignals(False)
                row._update_state()
                row.show_score(None)
            if not on:
                self._silence(t.id, ring=True)
        self._store()

    def move_category(self, name: str, step: int):
        self.groups.move(name, step)
        self._categories_changed()

    def delete_category(self, name: str, ask: bool = True) -> bool:
        """Take a category away: its triggers go to Uncategorised (nothing is
        deleted), with an Undo bar."""
        if name == profiles.UNCATEGORISED or self.groups.find(name) is None:
            return False
        moved = [t for t in self.triggers if t.category == name]
        if ask:
            box = QMessageBox(QMessageBox.Question, _("Delete category"),
                              _("Delete the category “{name}”?", name=name) + "\n\n"
                              + (ngettext("Its {n} trigger moves to {uncategorised}: none is "
                                          "deleted.",
                                          "Its {n} triggers move to {uncategorised}: none is "
                                          "deleted.", len(moved),
                                          uncategorised=profiles.label(profiles.UNCATEGORISED))
                                 if moved else _("It's empty.")),
                              QMessageBox.Yes | QMessageBox.Cancel, self)
            box.button(QMessageBox.Yes).setText(_("Delete"))
            box.setDefaultButton(QMessageBox.Cancel)
            if box.exec() != QMessageBox.Yes:
                return False
        before: dict = {}
        self.groups.save(before)
        self.groups.remove(name)
        for t in moved:
            t.category = profiles.UNCATEGORISED
            self._drop_row(t.id)
        self._drop_section(name)
        if self.groups.mode and self.groups.mode != profiles.AUTO \
                and self.groups.profile(self.groups.mode) is None:
            self.groups.mode = ""
        self._categories_changed()
        self._store()
        ids = {t.id for t in moved}

        def undo():
            self.groups = profiles.Groups.load(before, [t.category for t in self.triggers])
            self.groups.ensure(profiles.UNCATEGORISED)
            for t in self.triggers:
                if t.id in ids:
                    self._drop_row(t.id)
                    t.category = name
            self._drop_section(profiles.UNCATEGORISED)
            self._categories_changed()
            self.profilectl._fill_profiles()
            self._store()
        self.undo_bar.show_for(_("Deleted the category “{name}”", name=name), undo,
                               tip=_("Put it back, its triggers and all"))
        return True

    def export_category(self, name: str):
        ts = [t for t in self.triggers if t.category == name]
        if ts:
            self.packctl.export_triggers(ts, profiles.label(name))

    def add_in_category(self, name: str, make):
        """Make a new trigger (`make`: add_from_cut and co.) in this category: it's
        opened first, so the new one goes in it and shows."""
        sec = self.sections.get(name)
        if sec is not None and not sec.btn_fold.isChecked():
            sec.btn_fold.setChecked(True)      # opens it (and makes it the last opened)
        self._last_category = name
        make()

    def _fill_new_here(self, menu: QMenu, name: str):
        """The ways to make a trigger, each putting it in this category."""
        menu.addAction(icons.icon("crop"), _("Cut it from the window"),
                       lambda: self.add_in_category(name, self.add_from_cut))
        menu.addAction(icons.icon("plus"), _("From a picture file"),
                       lambda: self.add_in_category(name, self.add_from_file))
        a = menu.addAction(icons.icon("image"), _("Paste the copied picture"),
                           lambda: self.add_in_category(name, self.add_from_clipboard))
        a.setEnabled(not QApplication.clipboard().image().isNull())
        menu.addAction(_("Without a picture"),
                       lambda: self.add_in_category(name, self.add_area_trigger))

    def _pop_menu(self, menu: QMenu, under: QWidget):
        """Show a menu under a button (tests swap this for one that doesn't wait)."""
        menu.exec(under.mapToGlobal(under.rect().bottomLeft()))

    def _category_add_menu(self, name: str):
        """A section's + button: the ways to make a new trigger in it."""
        sec = self.sections.get(name)
        if sec is None:
            return
        menu = QMenu(sec.btn_add)
        self._fill_new_here(menu, name)
        self._pop_menu(menu, sec.btn_add)

    def _category_menu(self, name: str):
        """A section's ⋯ menu."""
        sec = self.sections.get(name)
        if sec is None:
            return
        menu = QMenu(sec.btn_menu)
        named = name != profiles.UNCATEGORISED
        n = sum(t.category == name for t in self.triggers)
        self._fill_new_here(menu.addMenu(icons.icon("plus"), _("New trigger here")), name)
        menu.addSeparator()
        if named:
            menu.addAction(_("Rename"), lambda: self._ask_rename(name))
        menu.addAction(icons.icon("palette"), _("Colours and picture"),
                       lambda: self.edit_categories(name))
        menu.addAction(icons.icon("search"), _("Search this category"),
                       lambda: self.show_search(name))
        a = menu.addAction(_("Turn all its triggers on"),
                           lambda: self.set_category_triggers(name, True))
        a.setEnabled(n > 0)
        a = menu.addAction(_("Turn all its triggers off"),
                           lambda: self.set_category_triggers(name, False))
        a.setEnabled(n > 0)
        menu.addSeparator()
        i = self.groups.names().index(name) if self.groups.find(name) else 0
        menu.addAction(_("Move up"), lambda: self.move_category(name, -1)).setEnabled(i > 0)
        menu.addAction(_("Move down"), lambda: self.move_category(name, 1)).setEnabled(
            i < len(self.groups.categories) - 1)
        menu.addSeparator()
        menu.addAction(_("Save to a file"), lambda: self.export_category(name)).setEnabled(n > 0)
        if named:
            menu.addAction(icons.icon("trash"), _("Delete category"),
                           lambda: self.delete_category(name))
        self._pop_menu(menu, sec.btn_menu)

    def _ask_rename(self, name: str):
        from PySide6.QtWidgets import QInputDialog
        new, ok = QInputDialog.getText(self, _("Rename category"), _("New name:"), text=name)
        if ok:
            self.rename_category(name, new)

    # ------------------------------------------------------------------ the list
    def sound_groups(self) -> list[tuple[str, list[str]]]:
        """The host's sound categories, (name, sound ids) in its order, for the Play +
        menu. Optional: a host without sound_categories() (an older board, the app's
        own) has none, and the menu shows no category list."""
        fn = getattr(self.host, "sound_categories", None)
        if fn is None:
            return []
        try:
            return [(str(name), list(ids)) for name, ids in fn()]
        except Exception:  # noqa: BLE001 - a host's bug mustn't stop the tab
            log.exception("the host's sound categories")
            return []

    def sounds_changed(self, force: bool = False):
        """The host's sounds may have changed: give the cards the new list. Only when
        it did (or `force`: a trigger's own sounds or the theme changed), since every
        tab show and board pad move lands here, and remaking every card's list and
        chips is slow with many triggers."""
        sounds = list(self.host.sounds())
        if force or sounds != self._sounds_shown:
            self._sounds_shown = sounds
            for row in self._cards():
                row.set_sounds(sounds)
        # a sound taken off the board (or the app) stops wherever a trigger played it
        have = {sid for sid, _name in sounds}
        for tid in list(self._played):
            self._silence(tid, [s for s in self._played[tid] if s not in have])
        for tid, ringing in list(self._ring_sounds.items()):
            if tid in self.host.ringing() and not set(ringing) & have:
                self._silence(tid, [], ring=True)

    def _add_row(self, t: Trigger, at: int | None = None, open_: bool = True) -> TriggerRow:
        """The card of `t` (already in self.triggers), made if it isn't yet, in its
        category, which is opened to show it. `at` is past: a card goes where its
        trigger is in self.triggers."""
        if self._search_ids is not None:
            self.clear_search()   # the newly added/restored card must be visible to edit
        sec = self._section_of(t)
        if not sec.is_open:
            self._set_open(sec, True)
        self._build(sec, need=t)
        row = self.rows.get(t.id) or self._place_row(t, sec, open_)
        if open_ and self.split:        # (its card may have been made closed, with others)
            self._select(row)
        return row

    def _make_row(self, t: Trigger, open_: bool, parent: QWidget | None = None) -> TriggerRow:
        """A card for `t`, opened unless `open_` is false (the cards made for the
        list at start, when there's more than one). Made in `parent` (where it goes):
        moved there afterwards, its every widget would be styled all over again."""
        split = self.split
        row = TriggerRow(t, self.host.sounds(), self._mons, open_=open_ and not split,
                         parent=parent)
        self._wire(row)
        row.set_advanced(self.chk_advanced.isChecked())
        row.set_categories(self.groups.names())
        row.set_default_interval(self.default_interval)
        row.set_default_place(places_label([self.watcher.default]))
        row.set_pad(self.pads)
        self.rows[t.id] = row
        if split:
            row.on_open = self._select
            row.btn_open.hide()
            if open_:
                self._select(row)
            elif self.editor is not None and self.editor.t is t:
                row.set_selected(True)      # made again (moved, found by a search...)
        return row

    def _wire(self, row: TriggerRow):
        """Connect a card (the list's, or the editor) to the tab."""
        row.sound_details = getattr(self.host, "sound_details", row.sound_details)
        row.sound_groups = self.sound_groups
        row._update_state()
        row.files_dropped.connect(self._add_dropped_files)
        row.picture_dropped.connect(self._add_dropped_picture)
        row.category_wanted.connect(self._move_to)
        row.changed.connect(self._row_changed)
        row.pictures_wanted.connect(self._add_picture_files)
        row.paste_wanted.connect(self._paste_picture)
        row.cut_wanted.connect(self._cut_picture)
        row.picture_view.connect(self._view_picture)
        row.picture_swap.connect(self._change_picture)
        row.picture_removed.connect(self._remove_picture)
        row.sound_file_wanted.connect(self._choose_sound_file)
        row.window_wanted.connect(self._pick_for)
        row.retarget_wanted.connect(self.change_window)
        row.area_wanted.connect(self._pick_area)
        row.duplicate.connect(self._duplicate)
        row.hear.connect(lambda sid, r=row: self._hear(r.t, sid))
        row.test.connect(lambda r: self.test_trigger(r.t, r))
        row.remove.connect(self.ask_remove)

    def _place_row(self, t: Trigger, sec: CategorySection, open_: bool = False) -> TriggerRow:
        """Put `t`'s card (made if need be) in `sec` where it is in self.triggers."""
        row = self.rows.get(t.id) or self._make_row(t, open_, sec.body)
        old = row.parentWidget()
        if old is not None and old.layout() is not None:
            old.layout().removeWidget(row)
        before = 0
        for x in self.triggers:
            if x is t:
                break
            r = self.rows.get(x.id)
            if x.category == t.category and r is not None and r.parentWidget() is sec.body:
                before += 1
        sec.body_layout.insertWidget(before + 1, row)      # after its "empty" note
        row.setVisible(self._matches_search(t))
        sec.empty.setVisible(False)
        self.empty.setVisible(False)
        self._fit_empty()
        return row

    def _drop_row(self, tid: str):
        """Throw a trigger's card away (the trigger stays)."""
        row = self.rows.pop(tid, None)
        if row is None:
            return
        parent = row.parentWidget()
        if parent is not None and parent.layout() is not None:
            parent.layout().removeWidget(row)
        row.setParent(None)   # gone from the list now, not when the event loop gets to it
        row.deleteLater()

    def _row_changed(self, row: TriggerRow):
        """A card was edited: save, and silence what it no longer plays. A sound
        taken off it stops (its preview, its test, its ring); a trigger switched off
        stops all of them; Ring unticked stops the ring; a new "until" applies to
        the ring going now."""
        t = row.t
        self._silence(t.id, [sid for sid in self._played.get(t.id, ()) if sid not in t.sounds])
        if t.id in self.host.ringing():
            gone = not set(self._ring_sounds.get(t.id, ())) & set(t.sounds) \
                and self.host.default_sound not in self._ring_sounds.get(t.id, ())
            if not (t.enabled and t.ring) or gone:
                self._silence(t.id, [], ring=True)
            elif self._ring_how.get(t.id) != t.stop:
                self._watch_ring(t)
        if not t.enabled:
            self._silence(t.id, ring=True)
        self._store()

    # Every sound a trigger plays is tagged, so it can be stopped again: a ring with
    # the trigger's id (what the alarm bar asks the host about), anything else with
    # the trigger and the sound, and a preview of a sound on its card with "hear:"
    # in front (a host plays that to you alone, not into a call).
    @staticmethod
    def _shot_tag(tid: str, sid: str) -> str:
        return f"{tid}/{sid}"

    @staticmethod
    def _hear_tag(tid: str, sid: str) -> str:
        return f"hear:{tid}/{sid}"

    def _hear(self, t: Trigger, sid: str):
        """A sound on `t`'s card was clicked: play it to check it (again from the
        start if it's still going)."""
        tag = self._hear_tag(t.id, sid)
        self.host.stop_tag(tag)
        if self.host.play(sid, tag=tag):
            self._played.setdefault(t.id, set()).add(sid)

    def _silence(self, tid: str, sids=None, ring: bool = False):
        """Stop what trigger `tid` played: the sounds `sids` (None: all it played,
        previews and tests too), and with `ring` its ring."""
        played = self._played.get(tid, set())
        for sid in list(played if sids is None else sids):
            self.host.stop_tag(self._shot_tag(tid, sid))
            self.host.stop_tag(self._hear_tag(tid, sid))
            played.discard(sid)
        if ring and tid in self.host.ringing():
            self.host.stop_tag(tid)
            self._forget_ring(tid)
            self.ringing_changed.emit()

    def _store(self):
        self._clear_editor_cache()
        raws = [t.to_raw() for t in self.triggers]
        self.host.screen["triggers"] = raws[:OLD_TRIGGERS]      # (see OLD_TRIGGERS)
        self.host.screen["more_triggers"] = raws[OLD_TRIGGERS:]
        # older versions drop a field they don't know when they save a trigger: its
        # category is kept here as well, where they never look
        self.host.screen["trigger_categories"] = {t.id: t.category for t in self.triggers
                                                  if t.category}
        self.groups.save(self.host.screen)
        self.host.save()
        self._sync_views()
        self._refresh_counts()
        if self._search_ids is not None:
            self._apply_search()
        if self.is_active():
            self._sync()
        self._show_warning()

    def _new(self, img: QImage | list[QImage], name: str, notes: list[str] = (),
             sources: list | None = None, mode: str = "appear") -> Trigger | None:
        """A new trigger from a picture (or several), playing the default alert until
        another sound is picked; None when no picture could be used. `notes`: see
        _add_pictures; `sources`: where it looks (the default place without);
        `mode`: it showing up, or going away."""
        if len(self.triggers) >= MAX_TRIGGERS:
            QMessageBox.information(self, _("Too many triggers"),
                                    _("You can have up to {max_triggers} triggers.",
                                      max_triggers=MAX_TRIGGERS))
            return None
        t = Trigger(id=uuid.uuid4().hex[:12], name=name[:60] or _("Trigger"),
                    sounds=[self.host.default_sound] if self.host.default_sound else [],
                    sources=list(sources or []), mode=mode, category=self._new_category())
        if not self._add_pictures(t, [img] if isinstance(img, QImage) else list(img),
                                  notes=notes):
            return None
        self.triggers.append(t)
        row = self._add_row(t)
        if self._web_added:
            self._web_tip(row)
        self._store()
        self.trigger_added.emit()
        QTimer.singleShot(0, row, lambda: self.scroll.ensureWidgetVisible(row))
        row.name.setFocus()
        row.name.selectAll()
        return t

    def _check_picture(self, img: QImage) -> tuple[Picture | None, tuple[str, str]]:
        """Whether a picture can be looked for: (its grey and mask, ()) or (None,
        (why not, in detail))."""
        if img.isNull():
            return None, (_("Not a picture"), _("That picture couldn't be read."))
        if min(img.width(), img.height()) < 6:
            return None, (_("Picture too small"),
                          _("Cut a bigger piece: at least 6 pixels each way."))
        if max(img.width(), img.height()) > MAX_SIDE:
            return None, (_("Picture too big"), _("Cut a smaller piece: at most "
                                                  "{n} pixels each way.", n=MAX_SIDE))
        pic = picture_of(img)
        if pic is None or flatness(*pic) < screenwatch.FLAT_STD:
            return None, (_("Picture is one plain colour"),
                          _("There's nothing in it to recognise. Cut a piece with some detail, "
                            "like the words or an icon. (Transparent parts don't count.)"))
        return pic, ()

    def _add_pictures(self, t: Trigger, imgs: list[QImage], names: list[str] = (),
                      at: int | None = None, notes: list[str] = ()) -> int:
        """Add pictures to a trigger (`at`: replace that one instead). Each is checked
        before it's saved, so a refused picture never replaces or joins the others;
        what was refused, and what may not be found (`notes`: more of that, from how
        a cut did while it was cut), is said once for the lot.
        Returns how many were added."""
        refused: list[tuple[str, str, str]] = []      # (name, title, text)
        extra, notes = list(notes), []                # notes: (name, note)
        added = left_out = 0
        # a pasted or loaded picture doesn't say what it was cut from: most likely
        # what the trigger watches, as it is now
        here = self._source_size(t.source if t.source is not None else self.watcher.default)
        web = 0
        for i, img in enumerate(imgs):
            if not img.isNull() and is_web(img):
                img = fit_web(img, here)
            if not img.isNull() and cut_size(img) is None:
                set_cut_size(img, here)
            name = names[i] if i < len(names) else _("Picture {n}", n=len(t.images) + 1)
            if at is None and len(t.images) >= MAX_PICTURES:
                left_out = len(imgs) - i
                break
            pic, why = self._check_picture(img)
            if pic is None:
                refused.append((name, *why))
                continue
            try:
                path = save_picture(img, picture_name(t, self.pictures), self.pictures)
            except OSError as e:
                refused.append((name, _("Couldn't keep the picture"), str(e)))
                continue
            if at is not None and 0 <= at < len(t.images):
                old, t.images[at] = t.images[at], path
                delete_picture(old, self.pictures)
                self._gray.pop(old, None)
                self._cuts.pop(old, None)
                self._wide.pop(old, None)
                at = None                   # a second picture would only be added
            else:
                t.images.append(path)
            added += 1
            web += is_web(img)
            for note in self._picture_notes(pic, t, is_web(img)) + extra:
                notes.append((name, note))
        self._web_added = web
        row = self.rows.get(t.id)
        if row is not None:
            row.refresh_pictures()
            if web:
                self._web_tip(row)
            if left_out:
                row.flash(ngettext("A trigger can look for up to {max} pictures — {n} "
                                   "picture not added",
                                   "A trigger can look for up to {max} pictures — {n} "
                                   "pictures not added", left_out, max=MAX_PICTURES),
                          4000, "warn")
        self._say(refused, _("Some pictures couldn't be used"))
        self._say([(n, _("This picture may not be found"), note) for n, note in notes],
                  _("Some pictures may not be found"))
        return added

    @staticmethod
    def _web_tip(row: TriggerRow):
        """Said on the card when a picture not cut from the game is added (once the
        card's been redrawn for it: that sets its line back)."""
        text = _("From the web: looked for at every size. Never found? Cut it from the game.")
        QTimer.singleShot(0, row, lambda: row.flash(text, 9000, "warn"))

    def _say(self, items: list[tuple[str, str, str]], title: str):
        """One warning for a list of (picture name, title, text): the picture's own
        title when there's only one, `title` with the names when there are more."""
        if len(items) == 1:
            QMessageBox.warning(self, items[0][1], items[0][2])
        elif items:
            QMessageBox.warning(self, title, "\n\n".join(f"{n}: {text}" for n, _t, text in items))

    def _source_size(self, src) -> tuple[int, int] | None:
        """The size in pixels of a window / screen being watched; None if unknown."""
        if isinstance(src, WindowRef):
            info = windows.find(src)
            return (info.width, info.height) if info is not None and info.width else None
        mons = screenwatch.monitors()
        if not mons:
            return None
        mon = mons[src] if isinstance(src, int) and 0 <= src < len(mons) else mons[0]
        return mon.width, mon.height

    def _picture_notes(self, pic: Picture, t: Trigger, web: bool = False) -> list[str]:
        """What may stop a picture being found where it's watched (it's kept anyway:
        it may be meant for a window that isn't open yet)."""
        src = t.source if t.source is not None else self.watcher.default
        size = self._source_size(src)
        if size is None:
            return []
        sw, sh = size
        what = "window" if isinstance(src, WindowRef) else "screen"
        gray, mask = pic
        h, w = gray.shape
        notes = []
        smallest = (screenwatch.WIDE_SIZES[0] if web else
                    screenwatch.SIZES[0] if t.any_size else 1.0)
        if w * smallest > sw or h * smallest > sh:
            notes.append(
                _("It's bigger than the window being watched ({w}×{h}), so it can't be found "
                  "there. Cut it from that window at the size it's shown.", w=sw, h=sh)
                if what == "window" else
                _("It's bigger than the screen being watched ({w}×{h}), so it can't be found "
                  "there. Cut it from that screen at the size it's shown.", w=sw, h=sh))
            return notes
        top = screenwatch.work_scale(sw, [1])     # the most detail a check keeps
        need = math.ceil(screenwatch.MIN_SIDE / top)
        if min(w, h) < need:
            notes.append(
                _("It's very small for a {w}-pixel-wide window, so it may be missed or match "
                  "the wrong thing. A bigger piece (at least {n} pixels each way) works "
                  "better.", w=sw, n=need) if what == "window" else
                _("It's very small for a {w}-pixel-wide screen, so it may be missed or match "
                  "the wrong thing. A bigger piece (at least {n} pixels each way) works "
                  "better.", w=sw, n=need))
        scale = screenwatch.work_scale(sw, [min(w, h)])
        if mask is not None and int(screenwatch.shrink_mask(mask, scale).sum()) < \
                screenwatch.MASK_MIN:
            notes.append(_("Most of it is see-through and what's left is thin, so there's "
                           "almost nothing to compare once it's scaled down for checking. "
                           "Keep more of the background around it, or use a picture "
                           "without transparency."))
        return notes

    # ------------------------------------------------------------------ cutting
    def capture(self, src) -> tuple[QImage | None, str]:
        """A full-size picture of a window or screen to cut from: (image, its name),
        or (None, why not)."""
        from onionwatch.ui.triggers.windowpicker import bgra_image
        px, where, _again = self._grab(src)
        return (None if px is None else bgra_image(px)), where

    def _grab(self, src) -> tuple[np.ndarray | None, str, object]:
        """capture() as pixels: (BGRA, its name, how to grab it again: a function
        for a window, the Monitor for a screen) or (None, why not, None)."""
        if isinstance(src, WindowRef):
            info = windows.find(src)
            if info is None:
                return None, _("{name} isn't open. Start it, then try again.",
                               name=src.label), None
            if info.minimized:
                return None, _("{name} is minimized. Restore it, then try again.",
                               name=src.label), None
            px = windows.snapshot(info.hwnd)
            if px is None:
                return None, _("{name} couldn't be copied.", name=src.label), None
            return px, src.label, lambda: windows.snapshot(info.hwnd)
        mons = screenwatch.monitors()
        if not mons:
            return None, _("No screen was found."), None
        mon = mons[src] if isinstance(src, int) and 0 <= src < len(mons) else mons[0]
        win = self.window()
        # take our own window out of the way first: it's probably on that screen
        was = win.windowOpacity()
        win.setWindowOpacity(0.0)
        QApplication.processEvents()
        from PySide6.QtCore import QThread
        QThread.msleep(200)
        try:
            px = windows.screen_snapshot(mon.left, mon.top, mon.width, mon.height)
        finally:
            win.setWindowOpacity(was)
        if px is None:
            return None, _("The screen couldn't be copied."), None
        return px, source_label(src, mons), mon

    @needs_part(fallback=(None, [], ""))
    def _cut(self, src, threshold: float = Trigger.threshold, heading: str = ""
             ) -> tuple[QImage | None, list[str], str]:
        """Cut a picture from a window or screen: (the piece or None, what's worth
        warning about it, a line to flash when it was made a cut-out). While a
        window's cut dialog is open the window keeps being grabbed (a screen, for a
        moment after it): scenery moving behind the thing is learned and left out
        (cutout.py), and a piece that may be missed or go off by mistake is said."""
        from onionwatch.ui.triggers.windowpicker import bgra_image
        px, where, again = self._grab(src)
        if px is None:
            info = windows.find(src) if isinstance(src, WindowRef) else None
            if info is not None and info.minimized:
                where += "\n\n" + fullscreen_hint()
            QMessageBox.information(self, _("Can't cut a picture"), where)
            return None, [], ""
        if float(px[..., :3].max()) < 8:
            QMessageBox.information(self, _("It comes out black"),
                                    _("{where} comes out black, so there's nothing to cut. Some "
                                      "games can only be seen on the screen: pick its screen "
                                      "under Look in instead.", where=where)
                                    + "\n\n" + fullscreen_hint())
            return None, [], ""
        img = bgra_image(px)
        from onionwatch.ui.triggers.snip import SnipDialog
        rec = cutout.Recorder(px, again if callable(again) else None)
        if callable(again):
            rec.start()
        dlg = SnipDialog(img, where, self, heading=heading)
        if not dlg.exec() or dlg.piece is None:
            rec.stop()
            return None, [], ""
        piece = dlg.piece
        s = dlg.view.selection
        rect = (s.x(), s.y(), piece.width(), piece.height())
        if isinstance(again, Monitor):
            rec.stop()
            self._grab_screen_after(rec, again, rect)
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            keep, plain, cut = cutout.learn(rec, rect)
        except Exception:       # learning is a bonus: the plain cut still works
            log.exception("learning the cut's background failed")
            keep, plain, cut = None, None, None
        finally:
            QApplication.restoreOverrideCursor()
        flash = ""
        if keep is not None:
            piece = with_alpha(piece, keep)
            flash = _("Learned the background: {share:.0%} of the picture is scenery and "
                      "left out", share=1 - float(keep.mean()))
        set_cut_size(piece, (img.width(), img.height()))
        kept = cut if keep is not None else plain
        what = "window" if isinstance(src, WindowRef) else "screen"
        return piece, ([] if kept is None else cutout.notes(kept, threshold, what)), flash

    def _grab_screen_after(self, rec: cutout.Recorder, mon: Monitor,
                           rect: tuple[int, int, int, int]):
        """A screen's frames for the cut-out: grabbed for SCREEN_LEARN_MS once the
        cut dialog has closed (it covered the screen while open), our window hidden
        only when it's over the piece."""
        from PySide6.QtCore import QElapsedTimer, QThread
        win = self.window()
        g = win.frameGeometry()
        dpr = win.devicePixelRatioF() or 1.0
        x, y, w, h = rect
        over = (g.left() * dpr < mon.left + x + w and g.right() * dpr > mon.left + x
                and g.top() * dpr < mon.top + y + h and g.bottom() * dpr > mon.top + y)
        was = win.windowOpacity()
        if over:
            win.setWindowOpacity(0.0)
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            QApplication.processEvents()
            QThread.msleep(150)
            rec.restart(lambda: windows.screen_snapshot(mon.left, mon.top, mon.width,
                                                        mon.height))
            clock = QElapsedTimer()
            clock.start()
            while clock.elapsed() < SCREEN_LEARN_MS:
                QApplication.processEvents()
                QThread.msleep(20)
        finally:
            QApplication.restoreOverrideCursor()
            if over:
                win.setWindowOpacity(was)

    def add_from_cut(self) -> Trigger | None:
        usage.used("cut-from-window")
        piece, notes, flash = self._cut(self.watcher.default)
        if piece is None:
            return None
        t = self._new(piece, _("Trigger {n}", n=len(self.triggers) + 1), notes)
        if t is not None and flash and t.id in self.rows:
            self.rows[t.id].flash(flash, 5000)
        return t

    def _cut_picture(self, row: TriggerRow):
        usage.used("cut-from-window")
        src = row.t.source if row.t.source is not None else self.watcher.default
        piece, notes, flash = self._cut(src, row.t.threshold)
        if piece is not None and self._add_pictures(row.t, [piece], notes=notes):
            self._store()
            if flash:
                row.flash(flash, 5000)

    # ------------------------------------------------------------------ files
    def add_from_file(self):
        usage.used("picture-file")
        path, __ = QFileDialog.getOpenFileName(self, _("Picture to look for"), str(Path.home()),
                                              picture_filter())
        if path:
            self._new(picture_file(path), Path(path).stem)

    def add_from_clipboard(self):
        usage.used("paste-picture")
        img = copied_picture()
        if img.isNull():
            QMessageBox.information(self, _("No picture copied"),
                                    _("Copy a picture first: press Win+Shift+S, drag around the "
                                      "thing to look for, then click Paste."))
            return
        self._new(img, _("Trigger {n}", n=len(self.triggers) + 1))

    def _add_picture_files(self, row: TriggerRow):
        """The card's "+ Add pictures…": any number of files onto this trigger."""
        usage.used("picture-file")
        paths, __ = QFileDialog.getOpenFileNames(self, _("Pictures to look for"),
                                                str(Path.home()), picture_filter())
        if paths and self._add_pictures(row.t, [picture_file(p) for p in paths],
                                        [Path(p).name for p in paths]):
            self._store()

    def _add_dropped_files(self, row: TriggerRow, paths: list[str]):
        """Picture files dropped on a card: onto its trigger."""
        usage.used("picture-file")
        if paths and self._add_pictures(row.t, [picture_file(p) for p in paths],
                                        [Path(p).name for p in paths]):
            self._store()

    def _add_dropped_picture(self, row: TriggerRow, img: QImage):
        """A picture dragged from a browser and dropped on a card: onto its trigger."""
        if self._add_pictures(row.t, [img]):
            self._store()

    def _paste_picture(self, row: TriggerRow):
        """The card's "Paste picture": the copied picture onto this trigger."""
        usage.used("paste-picture")
        img = copied_picture()
        if img.isNull():
            QMessageBox.information(self, _("No picture copied"),
                                    _("Copy a picture first: press Win+Shift+S, drag around the "
                                      "thing to look for, then click “Paste the copied picture”."))
            return
        if self._add_pictures(row.t, [img]):
            self._store()

    @needs_part()
    def _view_picture(self, row: TriggerRow, index: int = 0):
        """A thumbnail was clicked: its picture big, with the trigger's others."""
        from onionwatch.ui.triggers.viewer import PictureViewer
        t = row.t
        viewers = getattr(self, "_picture_viewers", None)
        if viewers is None:
            viewers = self._picture_viewers = {}
        if t.id in viewers:
            viewers[t.id].go(index)
            viewers[t.id].raise_()
            viewers[t.id].activateWindow()
            return

        def made_from(img: QImage) -> str:
            if is_web(img):
                return _("not cut from the game: looked for at any size")
            size = cut_size(img)
            return _("cut from a {w}×{h} view", w=size[0], h=size[1]) if size else ""

        def swap(i: int):
            r = self.rows.get(t.id)
            if r is not None:
                self._change_picture(r, i)

        def remove(i: int):
            r = self.rows.get(t.id)
            if r is not None:
                self._remove_picture(r, i)

        viewer = PictureViewer(_("Pictures of “{name}”", name=t.name), lambda: t.images, index,
                               swap,
                               remove, made_from, self)
        viewers[t.id] = viewer
        viewer.setAttribute(Qt.WA_DeleteOnClose)
        viewer.finished.connect(lambda _result: viewers.pop(t.id, None))
        viewer.open()

    def _change_picture(self, row: TriggerRow, index: int = 0):
        """Swap one of the trigger's pictures for a file."""
        path, __ = QFileDialog.getOpenFileName(self, _("Picture to look for"), str(Path.home()),
                                              picture_filter())
        if path and self._add_pictures(row.t, [picture_file(path)], [Path(path).name],
                                       at=index):
            self._store()

    def _remove_picture(self, row: TriggerRow, index: int):
        """Take a picture off a trigger. Its file stays until the Undo bar goes."""
        t = row.t
        if not 0 <= index < len(t.images):
            return
        path = t.images.pop(index)
        row.refresh_pictures()
        self._store()

        def undo():
            r = self.rows.get(t.id)
            if r is None or len(t.images) >= MAX_PICTURES or path in t.images:
                done()
                return
            t.images.insert(min(index, len(t.images)), path)
            r.refresh_pictures()
            self._store()

        def done():
            if not self.binctl._picture_used(path):
                delete_picture(path, self.pictures)
                self._gray.pop(path, None)
        self.undo_bar.show_for(_("Removed a picture from “{name}”", name=t.name), undo, done)

    def _choose_sound_file(self, row: TriggerRow):
        exts = " ".join(f"*{e}" for e in sorted(self.host.audio_exts))
        path, __ = QFileDialog.getOpenFileName(self, _("Sound to play"), str(Path.home()),
                                              _("Audio") + f" ({exts});;" + _("All files") + " (*)")
        if not path:
            return
        tid = row.t.id
        row.flash(_("Adding the sound…"), 60_000)
        try:
            self.host.add_sound(path, lambda sid: self._sound_added(tid, sid))
        except OSError as e:
            row.flash("", 0)
            QMessageBox.warning(self, _("Can't use that sound"), str(e))

    def _sound_added(self, tid: str, sid: str | None):
        """A sound file picked on a card has been added to the host (sid), or couldn't
        be (None): put it on that trigger, if it's still there."""
        t = next((t for t in self.triggers if t.id == tid), None)
        row = self.rows.get(tid)
        if row is not None:
            row.flash("", 0)
        if t is not None and sid and sid not in t.sounds and len(t.sounds) < MAX_SOUNDS:
            t.sounds.append(sid)
        self.sounds_changed(force=True)
        if t is not None and sid:
            self._store()
        elif row is not None and not sid:
            row.flash(_("That sound couldn't be added"), 4000, "warn")

    def ask_remove(self, row: TriggerRow):
        """The card's delete button: ask first, then delete (to Recently deleted)."""
        box = QMessageBox(QMessageBox.Question, _("Delete trigger"),
                          _("Delete the trigger “{name}”?\n\nIt goes to Recently deleted, where "
                            "you can bring it back for {keep_days} days.",
                            name=row.t.name, keep_days=KEEP_DAYS),
                          QMessageBox.Yes | QMessageBox.Cancel, self)
        box.button(QMessageBox.Yes).setText(_("Delete"))
        box.setDefaultButton(QMessageBox.Cancel)
        if box.exec() == QMessageBox.Yes:
            self._remove(row)

    def _remove(self, row: TriggerRow):
        """Delete a trigger: it goes to Recently deleted (pictures and all), with an
        Undo bar for the next few seconds."""
        t = row.t
        index = next((i for i, x in enumerate(self.triggers) if x.id == t.id), 0)
        entry = {"id": uuid.uuid4().hex[:12], "when": time.time(), "index": index,
                 "trigger": t.to_raw()}
        self.host.screen["deleted"] = self.binctl._bin() + [entry]
        self.triggers = [x for x in self.triggers if x.id != t.id]
        self._bag.forget(t.id)
        self._order.pop(t.id, None)
        self.host.stop_tag(t.id)
        self._silence(t.id, ring=True)
        self._forget_ring(t.id)
        for d in (self._played, self._ring_sounds, self._ring_how):
            d.pop(t.id, None)
        self._drop_row(t.id)
        if self.editor is not None and self.editor.t.id == t.id:
            self._drop_editor()         # the editor moves on to the next one
            nxt = self.triggers[min(index, len(self.triggers) - 1)] if self.triggers else None
            if nxt is not None and nxt.id in self.rows:
                self._select(self.rows[nxt.id])
        for path in t.images:
            self._gray.pop(path, None)   # the file stays, in the bin
        self._layout_sections()
        self.binctl._prune_bin()
        self._store()
        self.ringing_changed.emit()
        if not self.triggers and self.is_active():
            self.set_watching(False)
        self.binctl._label_bin()
        self.undo_bar.show_for(_("Deleted “{name}”", name=t.name),
                               lambda: self.binctl.restore_deleted(entry["id"]),
                               tip=_("Put it back, exactly as it was. Later: Recently "
                                     "deleted (kept {n} days)", n=KEEP_DAYS))

    # ------------------------------------------------------------------ areas, copies
    @needs_part()
    def _ask_area(self, img: QImage, where: str, t: Trigger, heading: str = ""
                  ) -> tuple | None:
        """Drag the part of `img` (the window, or a picture of it) to look in, and for a
        colour trigger check its colour: (region, colour), or None if cancelled."""
        from onionwatch.ui.triggers.snip import AreaDialog
        dlg = AreaDialog(img, where, t.region, t.colour if t.mode == "colour" else None, self,
                         heading=heading)
        if not dlg.exec():
            return None
        return dlg.region, dlg.colour

    def _pick_area(self, row: TriggerRow, heading: str = ""):
        """The card's "Area…" / "Bar and colour": drag the part of the window to look
        in (and for a colour trigger, check its colour)."""
        t = row.t
        src = t.source if t.source is not None else self.watcher.default
        img, where = self.capture(src)
        if img is None:
            QMessageBox.information(self, _("Can't show the window"), where)
            return
        area = self._ask_area(img, where, t, heading)
        if area is not None:
            self._set_area(t, *area)

    def _set_area(self, t: Trigger, region, colour: str):
        """`t` looks in `region` (and for a colour trigger, measures `colour`)."""
        t.region = region
        if t.mode == "colour":
            t.colour = colour
        row = self._card_of(t)
        for one in {row, self.rows.get(t.id)} - {None}:    # the editor and its tile
            one._label_area()
            one._update_state()
            one.show_score(one._score)    # "Not set up" until now: say it's ready
        self._store()

    def _duplicate(self, row: TriggerRow):
        """A copy of the trigger (its pictures copied too), just below it."""
        usage.used("duplicate")
        if len(self.triggers) >= MAX_TRIGGERS:
            QMessageBox.information(self, _("Too many triggers"),
                                    _("You can have up to {max_triggers} triggers.",
                                      max_triggers=MAX_TRIGGERS))
            return
        t = row.t.copy(uuid.uuid4().hex[:12])
        t.name = row.t.name[:53] + " (copy)"
        t.images = []
        for path in row.t.images:
            img = QImage(path)
            if img.isNull():
                continue
            try:
                t.images.append(save_picture(img, picture_name(t, self.pictures), self.pictures))
            except OSError:
                log.warning("couldn't copy the picture %s", path, exc_info=True)
        self._insert(t, after=row.t)

    def _insert(self, t: Trigger, after: Trigger | None = None) -> TriggerRow:
        """Add a finished trigger to the list (after `after`, else at the end)."""
        i = self.triggers.index(after) + 1 if after in self.triggers else len(self.triggers)
        self.triggers.insert(i, t)
        row = self._add_row(t)
        self._store()
        self.trigger_added.emit()
        QTimer.singleShot(0, row, lambda: self.scroll.ensureWidgetVisible(row))
        return row

    @needs_part()
    def new_trigger(self):
        """+ New trigger: what it watches for and where its picture comes from
        (WhatPicker); then which window to watch; then the picture cut, or the box
        dragged round the bar or the area on the picture of the game. The new card
        opens."""
        from onionwatch.ui.triggers.whatpick import CUT, FILE, PASTE, PICTURE_KINDS, WhatPicker
        dlg = WhatPicker(self, can_paste=not copied_picture().isNull())
        if not dlg.exec() or dlg.picked is None:
            return
        what = dlg.picked
        here = self.watcher.default if isinstance(self.watcher.default, WindowRef) else None
        name = _("Trigger {n}", n=len(self.triggers) + 1)
        if what in PICTURE_KINDS and dlg.source in (PASTE, FILE):
            # the picture's in hand: step 3, the window to look for it in
            src = self.pick_window(here, heading=_("Step 3: which window should it watch?"))
            if src is None:
                return
            if dlg.source == PASTE:
                imgs = [copied_picture()]
            elif dlg.paths:
                imgs = [picture_file(path) for path in dlg.paths]
                name = Path(dlg.paths[0]).stem
            else:
                imgs = [dlg.image] if dlg.image is not None else []
                for img in imgs:
                    set_web(img)        # dragged out of a browser: its size is anyone's guess
            if imgs and not all(img.isNull() for img in imgs):
                self._new(imgs, name, sources=[src], mode=what)
            return
        if what in PICTURE_KINDS and dlg.source == CUT:
            src = self.pick_window(here, heading=_("Step 3: which window is it in?"))
            if src is None:
                return
            piece, notes, flash = self._cut(src, heading=_("Step 4: drag a box round the "
                                                           "thing to watch for"))
            if piece is None:
                return
            t = self._new(piece, name, notes, sources=[src], mode=what)
            if t is not None and flash and t.id in self.rows:
                self.rows[t.id].flash(flash, 5000)
            return
        # a bar, a chat line, everything still: step 2 gave a picture of the game (a
        # screenshot, or the game as it is now); step 3 the game's window, step 4 the
        # box round the bar or the part to watch on that picture
        shot = None
        if dlg.source == PASTE:
            shot = copied_picture()
        elif dlg.source == FILE:
            shot = picture_file(dlg.paths[0]) if dlg.paths else dlg.image
        if shot is not None and shot.isNull():
            return
        src = self.pick_window(here, heading=_("Step 3: which window is the game in?"))
        if src is None:
            return
        if shot is None:
            shot, where = self.capture(src)
            if shot is None:
                info = windows.find(src)
                if info is not None and info.minimized:
                    where += "\n\n" + fullscreen_hint()
                QMessageBox.information(self, _("Can't show the window"), where)
                return
        else:
            where = src.label
        draft = Trigger(id="", mode=what)   # (a colour one: the box picks its colour)
        area = self._ask_area(shot, where, draft, heading=(
            _("Step 4: drag a box round the bar") if what == "colour" else
            _("Step 4: drag a box round the chat") if what == "change" else
            _("Step 4: drag a box round the part to watch, or pick All of it")))
        if area is None:
            return
        t = self.add_area_trigger(what, [src])
        if t is not None:
            self._set_area(t, *area)

    def _card_of(self, t: Trigger) -> TriggerRow:
        """The card showing `t` for editing: the editor beside the list, or its own."""
        return self.editor if self.editor is not None and self.editor.t is t else self.rows[t.id]

    def add_area_trigger(self, mode: str = "still", sources: list | None = None
                         ) -> Trigger | None:
        """A new trigger that watches an area rather than looking for a picture: by
        default "the area stops changing" (a game stuck or idle) in the default place;
        the card picks another kind."""
        usage.used("area-trigger")
        if len(self.triggers) >= MAX_TRIGGERS:
            QMessageBox.information(self, _("Too many triggers"),
                                    _("You can have up to {max_triggers} triggers.",
                                      max_triggers=MAX_TRIGGERS))
            return
        t = Trigger(id=uuid.uuid4().hex[:12], name=_("Trigger {n}", n=len(self.triggers) + 1),
                    sounds=[self.host.default_sound] if self.host.default_sound else [],
                    mode=mode, level=LEVELS[mode], hold=10.0 if mode == "still" else 0.0,
                    sources=list(sources or []), category=self._new_category())
        row = self._insert(t)
        row.name.setFocus()
        row.name.selectAll()
        return t

    def show_history(self):
        usage.used("history")
        if self.pages is not None:
            self.pages.show_log()
        else:
            HistoryDialog(self, self).exec()

    # ------------------------------------------------------------------ playing now
    def playing_now(self) -> list[tuple[Trigger, bool]]:
        """The triggers whose sound is still going, oldest first, each with whether
        it rings. A host that can say which sounds are playing (Host.playing) says
        when one ends; with one that can't, a one-shot counts as playing for
        GUESS_PLAYING_S after it went off."""
        ringing = set(self.host.ringing())
        tags = None
        playing = getattr(self.host, "playing", None)
        if callable(playing):
            try:
                tags = set(playing())
            except Exception:  # noqa: BLE001 - a host's bug mustn't break the bar
                log.warning("the host couldn't say what's playing", exc_info=True)
        out, now = [], time.monotonic()
        for tid, since in list(self._live.items()):
            t = next((x for x in self.triggers if x.id == tid), None)
            ring = tid in ringing
            if t is not None and (ring or (
                    any(tag.startswith(tid + "/") for tag in tags) if tags is not None
                    else now - since < GUESS_PLAYING_S)):
                out.append((t, ring))
            else:
                del self._live[tid]
        self._show_tests({t.id for t, __ in out})
        return out

    def test_trigger(self, t: Trigger, row: TriggerRow | None = None):
        """A card's Test (`row`: that card): play it as it would go off, shown in
        Playing now like any other; pressed again while it plays (it says Stop then),
        stop it. With no sound it could play, open the card's sound list instead."""
        usage.used("test")
        if any(x.id == t.id for x, __ in self.playing_now()):
            self.stop_trigger(t.id)
            return
        if not self._playable(t):
            # rather than do nothing (its line already says "Pick the sound to play")
            if row is not None and row.built:
                row.sound.setFocus()
                row.sound.showPopup()
            return
        if self._play_trigger(t, test=True):
            self._live[t.id] = time.monotonic()
            self.playing_changed.emit()

    def _show_tests(self, live: set[str]):
        """Each card's Test says Stop while its trigger plays."""
        for row in [*self.rows.values(), self.editor]:
            if row is None or not row.built:   # a closed card's editor isn't made yet
                continue
            on = row.t.id in live
            if row.btn_test.property("stops") != on:
                row.btn_test.setProperty("stops", on)
                row.btn_test.setText(_("Stop") if on else _("Test"))
                icons.set_icon(row.btn_test, "stop" if on else "play", size=14)

    def stop_trigger(self, tid: str):
        """Stop what trigger `tid` is playing now, its ring too (Playing now's Stop)."""
        self._silence(tid, ring=True)
        if self._live.pop(tid, None) is not None:
            t = next((x for x in self.triggers if x.id == tid), None)
            log.info("trigger %r stopped by hand", t.name if t else tid)
        for row in self._views(tid):
            row.flash(_("Stopped"), 2500)
        self.playing_changed.emit()

    def stop_all_playing(self):
        """Stop every trigger's sound, and drop any still waiting out its wait."""
        self.cancel_pending()
        for tid in list(self._live):
            self._silence(tid, ring=True)
        self._live.clear()
        self.stop_ringing()
        self.playing_changed.emit()


def fullscreen_hint() -> str:
    """Said when a game's window can't be cut from (minimized, or black): a game in
    exclusive fullscreen minimizes as soon as you switch to this app."""
    return _("A game in exclusive fullscreen hides itself when you switch away. Take a "
             "screenshot in the game (Print Screen) and paste it instead.")
