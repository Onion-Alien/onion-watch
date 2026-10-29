"""One trigger's card on the triggers page (TriggerRow): its header (pictures, name,
what it does, the live match, the sounds) and, opened, everything about it."""
from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QEvent, QPoint, QRect, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QFontMetrics, QIcon, QImage, QPixmap
from PySide6.QtWidgets import (QApplication, QCheckBox, QDialog, QDoubleSpinBox, QFrame,
                               QGridLayout, QHBoxLayout, QLabel, QLineEdit, QMenu, QPushButton,
                               QSizePolicy, QVBoxLayout, QWidget)

from onionwatch.engine import profiles, screenwatch
from onionwatch.engine.screenwatch import (INTERVALS_MS, MAX_PICTURES, MAX_SOUNDS, Monitor, Trigger,
                                           WindowRef)
from onionwatch.i18n import _
from onionwatch.ui.kit import icons, theme
from onionwatch.ui.kit.panel import dialog_layout, hint_label
from onionwatch.ui.kit.wheelguard import no_wheel
from onionwatch.ui.triggers.cardkit import (DEFAULT, PICK_WINDOW, PLACES, STRIP_THUMBS, ElideLabel,
                                            FitDoubleSpin, FitSpin, FlowBox, Pair, Plate,
                                            ShrinkButton, Strip, Switch, TuneGrid, WideCombo,
                                            align_control, capital, card_css, control_height,
                                            divider, fill_sources, interval_label, labelled,
                                            mid_sentence, pictures, rule_hint, swatch)
from onionwatch.ui.triggers.chances import LiveLabel, goes_below
from onionwatch.ui.triggers.pictures import PICTURE_EXTS, THUMB, set_web
from onionwatch.ui.triggers.soundmenu import Groups, SoundBox
from onionwatch.ui.triggers.windowpicker import places_label

ADD = "__add__"         # the sound list's "+ Add sound" entry (its resting state)
FILE = "__file__"       # ...its "Choose a sound file" entry
NEW_CATEGORY = "__new_category__"   # a card's Category list's "New category" entry
POLL_MS = 150           # how often the live match numbers refresh
# an open card's pictures on a card BIG_CARD px wide or wider: what it looks for, big
THUMB_BIG = QSize(176, 96)
BIG_CARD = 700
CHIP_CHARS = 24         # a sound chip's name is cut to this many characters
PICKS = (("random", _("Play one at random")), ("order", _("Play them in turn")),
         ("all", _("Play all at once")))
MODES = (("appear", _("The picture shows up")), ("vanish", _("The picture goes away")),
         ("change", _("Something changes in an area")),
         ("still", _("An area stops changing")), ("colour", _("A bar runs low")))
LEVELS = {"change": 0.05, "still": 0.01, "colour": 0.30}   # a new mode's starting level
# what stops a ringing trigger by itself (Trigger.stop): its words on the card, on
# its state line and in the alert, and a tooltip
UNTILS = {
    "moves": (_("until the game moves"), _("keeps playing until the game moves"),
              _("Ringing until the game moves."),
              _("Stops once anything moves where it looks (you're back and playing), or "
                "when it goes away. It waits for the screen to settle first, so a fade-in "
                "doesn't stop it. A bar: once it's back over its line.")),
    "focus": (_("until I switch to the game"),
              _("keeps playing until you switch to the game"),
              _("Ringing until you switch to it."),
              _("Stops when you alt-tab back to its window. Watching a whole screen: when "
                "you switch to any other window.")),
    "gone": (_("until it's gone"), _("keeps playing until it's gone"),
             _("Ringing until it's gone."),
             _("Stops when the picture goes away (or the bar is back, or the area settles).")),
    "input": (_("until I touch mouse or keys"),
              _("keeps playing until you touch the mouse or keyboard"),
              _("Ringing until you touch the mouse or keyboard."),
              _("Stops as soon as you move the mouse or press a key, anywhere.")),
    "manual": (_("until I click Stop"), _("keeps playing until you click Stop"),
               _("Ringing until you stop it."),
               _("Only the Stop button on the red bar (or the tray icon) stops it.")),
}
TILE_THUMB = QSize(60, 36)  # a closed card's (a tile's) one thumbnail
PAD_THUMB = QSize(124, 64)  # ...and a pad's (the Pads view), over its name


def trigger_ready(t: Trigger) -> bool:
    """It has what it needs to be watched for (sounds aside): pictures, or for a
    colour trigger the bar and its colour."""
    if t.uses_pictures:
        return bool(t.images)
    if t.mode == "colour":
        return bool(t.colour) and t.region is not None
    return True


class TriggerRow(QFrame):
    """One trigger's card: a header (pictures, name, what it does, the live match,
    on / off) that opens to three parts: what to watch for, what happens then, and
    the fine-tuning, folded away behind a line summing it up. Closed, it's a tile in
    its category's grid: the same header, small (a picture, the name over how it's
    doing and what it plays, the switch); open, it's the whole width."""
    btn_close: QPushButton     # an open editor's ✕ (_open_editor), not a tile's
    changed = Signal(object)             # row: a setting changed
    pictures_wanted = Signal(object)     # row: "+ Add pictures…" (files)
    paste_wanted = Signal(object)        # row: "Paste picture"
    cut_wanted = Signal(object)          # row: "Cut from window"
    picture_view = Signal(object, int)   # row, index: a thumbnail was clicked: show it big
    picture_swap = Signal(object, int)   # row, index: swap that picture for another file
    picture_removed = Signal(object, int)  # row, index
    sound_file_wanted = Signal(object)   # row: "Choose a sound file"
    window_wanted = Signal(object)       # row: "Pick windows"
    retarget_wanted = Signal(object)     # WindowRef: "Change window" on a window not open
    area_wanted = Signal(object)         # row: "Area…"
    duplicate = Signal(object)           # row: "Duplicate"
    category_wanted = Signal(object, str)  # row, category: moved there (NEW_CATEGORY: ask)
    hear = Signal(str)                   # a sound chip was clicked: play that sound id
    test = Signal(object)
    remove = Signal(object)
    files_dropped = Signal(object, list)   # row, picture files dropped on it
    picture_dropped = Signal(object, object)  # row, a picture (QImage) dropped on it

    def __init__(self, t: Trigger, sounds: list[tuple[str, str]],
                 screens: list[Monitor] = (), open_: bool = False,
                 parent: QWidget | None = None):
        super().__init__(parent)
        if parent is not None:      # until it's laid out, the size a card made on its
            self.resize(640, 480)   # own starts at: not "too narrow" (_fit_narrow)
        self.setObjectName("card")
        self.t = t
        self.advanced = False
        self.watching = False
        self.cooldown_until = 0.0
        self.sound_details = lambda _sid: _("Volume / hotkey: sound settings")
        self.missing: list[str] = []    # its sounds that are no longer in the library
        self.fallback = False           # its own screen isn't there: the default is watched
        self.note: tuple[str, str] | None = None   # (text, tone) from watching: not open…
        self.waiting: WindowRef | None = None       # the window the note waits for
        self._screens = 0               # how many screens there are
        self._mons: list[Monitor] = []
        self._sounds: list[tuple[str, str]] = []   # the sounds as last given
        # () -> the host's categories, for the + menu (the panel sets it)
        self.sound_groups: Callable[[], Groups] = list
        self._narrow = False            # too narrow for the header's thumbnail
        self._big = False               # open and wide: its pictures big (THUMB_BIG)
        self._press: QPoint | None = None   # where a press on the header began (a drag?)
        # with the list beside an editor: opening the card shows it there instead
        self.on_open = None
        self.pinned = False             # it's that editor: always open, not dragged
        self.selected = False           # it's the one the editor is showing
        self.setAcceptDrops(True)           # picture files dropped on it are added
        v = QVBoxLayout(self)
        v.setContentsMargins(10, 8, 10, 8)
        v.setSpacing(6)

        # the header, always shown: its pictures (and a + to add more), name, what it
        # does (or what's wrong), the live match, on / off, and open / close. Click it
        # to open the rest, drag it to move it. Laid out by _arrange: on one line while
        # open; closed, a small thumbnail and the switches over the name and the rest
        self.top = top = QGridLayout()
        top.setHorizontalSpacing(8)
        top.setVerticalSpacing(2)
        self.strip = Strip()
        self.strip.setToolTip(_("The pictures to look for: any of them showing up plays the "
                                "sound. Click one to see it big."))
        self.strip.picture_clicked.connect(lambda i: self.picture_view.emit(self, i))
        self.strip.picture_removed.connect(lambda i: self.picture_removed.emit(self, i))
        self.strip.add_wanted.connect(self._show_add_menu)
        self.btn_add_pic = QPushButton("+")
        # an outlined slot after the pictures (open), or where the first one goes
        self.btn_add_pic.setObjectName("addpic")
        self.btn_add_pic.setAccessibleName(_("Add a picture"))
        self.btn_add_pic.setToolTip(_("Add a picture: cut it from the window, pick files or "
                                      "paste the one you copied. You can also drop picture files "
                                      "on the card."))
        self.btn_add_pic.setCursor(Qt.PointingHandCursor)
        self.btn_add_pic.clicked.connect(self._show_add_menu)
        # the header's pieces belong to the card from the start: _arrange moves them
        # between layouts, and a piece shown while it had no parent flashed up on the
        # desktop as a little blank window of its own (and lagged the app)
        self.pics = QWidget(self)       # the strip and its +, side by side
        self.pics.setObjectName("labelled")
        pics = QHBoxLayout(self.pics)
        pics.setContentsMargins(0, 0, 0, 0)
        pics.setSpacing(4)
        pics.addWidget(self.strip)
        pics.addWidget(self.btn_add_pic)
        self.badge = Plate(self)          # instead of the strip, for a trigger without pictures
        self.badge.setObjectName("iconlabel")
        self.badge.setAlignment(Qt.AlignCenter)
        self.names = QWidget(self)        # under the name: what it does (or what's wrong)...
        self.names.setObjectName("labelled")      # see-through, like labelled()'s boxes
        names = QVBoxLayout(self.names)
        names.setContentsMargins(0, 0, 0, 0)
        names.setSpacing(2)
        self.name = QLineEdit(t.name)
        # a title until you click it (styled by CARD_CSS)
        self.name.setObjectName("cardname")
        self.name.setToolTip(_("Click to rename it"))
        self.name.setMinimumWidth(50)
        self.name.setPlaceholderText(_("Name, e.g. Rare spawn"))
        self.name.setMaxLength(60)
        self.name.setCursorPosition(0)          # a long name shows its start, not its end
        self.setProperty("interactive", True)
        self.setProperty("hovered", False)
        self.setStyleSheet(card_css())
        self.name.editingFinished.connect(self._on_name)
        self.name.editingFinished.connect(lambda: self.name.setCursorPosition(0))
        # as wide as the name, not the whole card: the hover / editing box hugs it
        self.name.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Policy.Fixed)   # up to that
        self.name.textChanged.connect(self._fit_name)
        self._fit_name()
        self.name_line = QWidget(self)    # the name takes what it needs, the rest is empty
        self.name_line.setObjectName("labelled")
        line = QHBoxLayout(self.name_line)
        line.setContentsMargins(0, 0, 0, 0)
        line.setSpacing(0)
        line.addWidget(self.name, 100)
        # a closed card's name is just read (a click anywhere on the card opens it)
        self.title = ElideLabel()
        self.title.setObjectName("cardtitle")
        self.title.setContentsMargins(6, 0, 0, 0)
        self.title.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.title.set_elide(True)
        self.name.textChanged.connect(self._show_title)
        self._show_title()
        line.addWidget(self.title, 100)
        line.addStretch(1)
        self.state = ElideLabel()
        self.state.setObjectName("hint")
        self.state.set_elide(True)      # one line: the whole of it is its tooltip
        self.state.setIndent(0)
        self.state.setContentsMargins(6, 0, 0, 0)  # title's border, padding and text inset
        self.state.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        # on "Waiting for <game> to open": point everything that looked in that
        # window at another one (the game's program was renamed, a new launcher...)
        self.btn_retarget = QPushButton(_("Change window"))
        self.btn_retarget.setObjectName("small")
        self.btn_retarget.setToolTip(
            _("Pick the window to look in instead. Every trigger, the default Look in and the "
              "profiles that used this window (or its program) move to the new one."))
        self.btn_retarget.clicked.connect(
            lambda: self.waiting is not None and self.retarget_wanted.emit(self.waiting))
        self.btn_retarget.setVisible(False)
        state_line = QHBoxLayout()
        state_line.setSpacing(6)
        state_line.addWidget(self.state, 1)
        state_line.addWidget(self.btn_retarget)
        names.addLayout(state_line)
        self.sound_summary = ElideLabel()
        self.sound_summary.setObjectName("muted")
        self.sound_summary.setContentsMargins(6, 0, 0, 0)
        self.sound_summary.setWordWrap(True)
        self.sound_summary.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        names.addWidget(self.sound_summary)
        self.details = QLabel(self)
        self.details.setContentsMargins(6, 0, 0, 0)
        self.details.setObjectName("hint")
        self.details.setWordWrap(True)
        self.details.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.details.setParent(self)    # under a closed card's header (_arrange)
        self.details.hide()
        # what it's doing right now: a coloured dot and a word, or the live match
        self.live = LiveLabel(self)
        self.live.setTextFormat(Qt.RichText)
        self.live.setIndent(0)
        self.live.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self._live_shown = ""
        self._live_room: QSize | None = None    # a score's size (_fit_live)
        self._live_score = False            # it's showing a score
        self._score: float | None = None    # the score shown (show_score)
        self.chk_on = Switch(self)
        self.chk_on.setToolTip(_("Watch for this trigger (switch it off to keep it but pause it)"))
        self.chk_on.setChecked(t.enabled)
        self.chk_on.toggled.connect(self._on_enabled)
        self.btn_open = QPushButton(self)
        self.btn_open.setObjectName("fold")
        self.btn_open.setCheckable(True)
        self.btn_open.setFixedSize(28, 28)
        self.btn_open.setAccessibleName(_("Edit trigger"))
        self.btn_open.toggled.connect(self.set_open)
        self._tile: bool | None = None      # how the header is laid out now (_arrange)
        self.pad = False                    # closed, it's a pad: the picture over the name
        self._said: bool | None = None      # a tile's line is saying what's wrong
        v.addLayout(top)

        self.body = QWidget()
        sp = self.body.sizePolicy()
        sp.setHeightForWidth(True)          # its rows wrap: taller when narrower
        self.body.setSizePolicy(sp)
        bv = QVBoxLayout(self.body)
        bv.setContentsMargins(0, 0, 0, 2)     # the card's 8 at the bottom: 10, as at its sides
        bv.setSpacing(10)    # room between the editor's rows: at 4 they looked packed
        v.addWidget(self.body)
        v.addStretch(1)     # a tile taller than it needs (its line's tallest): space below
        # the editor under the header is made the first time the card opens
        # (_build_body): a closed tile is just its header, and most never open
        self._built = False
        self._categories: list[str] | None = None   # set_categories, kept till then
        self._default_ms: int | None = None          # set_default_interval, likewise
        self.default_place = ""         # where "Default" looks (set_default_place)

        self._flash = QTimer(self)
        self._flash.setSingleShot(True)
        self._flash.timeout.connect(self._update_state)
        self._show_mode()
        self.set_sounds(sounds)
        self.set_screens(list(screens))
        if not open_:   # its pictures made once, at the size they're shown (_arrange)
            self.strip.set_look(TILE_THUMB, 1)
        self.refresh_pictures()
        self._update_state()
        self.show_score(None)
        self.btn_open.setChecked(open_)
        self.set_open(open_)

    # the editor's widgets, made by _build_body: asking a closed card for one makes it
    EDITOR = frozenset({
        "mode", "where", "where_box", "_watch_row", "sounds_box", "sounds_row",
        "lbl_play", "chips", "sound", "pick", "btn_test", "btn_tune", "rules_box",
        "rule_chips", "btn_dup", "btn_del", "tune", "rules_dlg", "_tune_row", "btn_area",
        "interval", "chk_size", "chk_ring", "until", "ring_box", "delay", "cooldown", "hold",
        "lbl_hold", "hold_box", "threshold", "below", "lbl_number", "match_box", "_in",
        "chk_quiet", "chk_hold", "chk_delay", "chk_cooldown", "chk_region", "cb_category",
        "area_note"})

    def __getattr__(self, name: str):
        # (only for what isn't there: a closed card's editor, made now)
        if name in TriggerRow.EDITOR and self.__dict__.get("_built") is False:
            self._build_body()
            return getattr(self, name)
        raise AttributeError(f"{type(self).__name__!r} object has no attribute {name!r}")

    @property
    def built(self) -> bool:
        """Its editor has been made (it was opened, or something needed it)."""
        return self._built

    def _build_body(self):
        """Make the editor: the trigger as a sentence ("When [the picture shows up] in
        [the game] / play [Ready] [Chime] [+] / [ ] Keep playing [until …]"), the rules
        it has on as chips with a Rules button, the rules themselves (folded away), and
        Test, its category, Duplicate and Delete at the bottom."""
        if self._built:
            return
        self._built = True
        t = self.t
        bv = self.body.layout()
        assert bv is not None       # (made above)
        bv.addWidget(divider())
        bv.addSpacing(2)

        def word(text: str) -> QLabel:
            """A word of the sentence between its controls, centred on them."""
            lab = QLabel(text)
            lab.setObjectName("sentenceword")
            lab.setAlignment(Qt.AlignVCenter)
            lab.setFixedHeight(control_height(lab))
            return lab
        # "When [it shows up] in [the game]": what sets it off and where (a bar's level,
        # the area that changes, how long nothing moves join this line: _place)
        sentence = FlowBox(gap=8)
        row = sentence.flow
        self.mode = WideCombo(min_width=120)
        for key, label in MODES:
            self.mode.addItem(mid_sentence(label), key)
        self.mode.setCurrentIndex(max(self.mode.findData(t.mode), 0))
        self.mode.setToolTip(
            _("What sets it off:\n• it shows up: one of its pictures appears\n• it goes away: "
              "its picture disappears (a buff running out, a bobber)\n• the area changes: "
              "anything moves in its area (a chat line, the minimap)\n• the area stops changing: "
              "nothing moves for a while (stuck, idle, disconnected)\n• a bar runs low: less of "
              "its area is one colour (a health bar)"))
        no_wheel(self.mode)
        self.mode.activated.connect(self._on_mode)
        self.mode.setProperty("token", "accent")    # (CARD_CSS)
        self.where = WideCombo(min_width=120)
        self.where.setToolTip(_("Where to look: game windows (watched even while other windows "
                                "cover them, but not while they're minimized) or whole screens. "
                                "“Pick windows” can tick several, or every copy of a game. "
                                "“Default” is the Look in on the bottom bar."))
        no_wheel(self.where)
        self.where.activated.connect(self._on_where)
        self.where_box = self.where
        self.where.setProperty("token", "accent")   # every choice of the sentence alike
        row.addWidget(word(capital(_("when"))))
        row.addWidget(self.mode)
        row.addWidget(word(_("in")))
        row.addWidget(self.where)
        self._watch_row = row
        bv.addWidget(sentence)
        # an area trigger's weak spots, said plainly under the sentence (_show_mode_body)
        self.area_note = hint_label("")
        self.area_note.hide()
        bv.addWidget(self.area_note)
        # "play [Ready ✕] [Chime ✕] [+] [one at random]"
        self.sounds_box = FlowBox(gap=8)
        self.sounds_row = self.sounds_box.flow
        self.lbl_play = word(capital(_("play")))
        self.chips: list[QFrame] = []
        self.sound = SoundBox(FILE)     # a square +: opens a menu with search, categories
        self.sound.groups = lambda: self.sound_groups()
        self.sound.taken = lambda: set(self.t.sounds)
        self.sound.setObjectName("addsound")
        self.sound.setAccessibleName(_("+ Add sound"))
        self.sound.setProperty("token", "true")
        self.sound.setToolTip(_("Add a sound to play: a built-in alert, or a sound file of yours"))
        no_wheel(self.sound)
        self.sound.activated.connect(self._on_sound)
        self.sound.picked.connect(self._add_sound)
        self.pick = WideCombo(self)    # (shown before it's in the row: no flash)
        for key, label in PICKS:
            self.pick.addItem(label, key)
        self.pick.setCurrentIndex(max(self.pick.findData(t.pick), 0))
        self.pick.setToolTip(_("With several sounds: play one at random (each once before any "
                               "repeats), take them in turn, or play them all at once"))
        no_wheel(self.pick)
        self.pick.currentIndexChanged.connect(self._on_pick)
        self.pick.setProperty("token", "accent")
        bv.addWidget(self.sounds_box)
        # "[ ] Keep playing [until I switch to the game]"
        self.chk_ring = QCheckBox(_("Keep playing"))
        self.chk_ring.setObjectName("sentencecheck")
        self.chk_ring.setToolTip(_("Keep playing the sound over and over — for when you're away "
                                   "from the keyboard. The Stop button on the red bar always "
                                   "stops it; pick what else does next to it."))
        self.chk_ring.setChecked(t.ring)
        self.chk_ring.toggled.connect(self._on_ring)
        self.until = WideCombo(self)   # (shown before it's in its Pair: no flash)
        for key, (label, *_rest) in UNTILS.items():
            self.until.addItem(label, key)
            self.until.setItemData(self.until.count() - 1, UNTILS[key][3], Qt.ToolTipRole)
        self.until.setCurrentIndex(max(self.until.findData(t.stop), 0))
        self.until.setToolTip(_("What stops the ringing by itself"))
        self.until.setVisible(t.ring)
        self.until.setProperty("token", "accent")
        no_wheel(self.until)
        self.until.currentIndexChanged.connect(self._on_until)
        self.ring_box = Pair(self.chk_ring, self.until)
        self.ring_box.setMinimumHeight(control_height(self.until))
        bv.addWidget(self.ring_box)

        # the rules it has on, each a chip (✕ takes it off), then Rules: open them all
        self.btn_tune = ShrinkButton(_("Extra settings"))
        self.btn_tune.setObjectName("small")
        self.btn_tune.setToolTip(_("How long it must last, a wait before playing, a rest "
                                   "after, where in the window, how alike, how often"))
        icons.set_icon(self.btn_tune, "setup", size=14)
        self.btn_tune.clicked.connect(self.show_rules)
        self.rules_box = FlowBox(gap=8)
        self.rule_chips: list[QFrame] = []
        self._rules_shown: list[tuple[str, str]] | None = None
        bv.addWidget(self.rules_box)

        # the rules: three groups, a tick box (or label) and its number or button each
        # the extra settings: a pop-up of their own, so the card stays short
        self.rules_dlg = dlg = QDialog(self)
        dlg.setObjectName("rulesdialog")    # (CARD_CSS: a background of its own)
        dlg.setWindowTitle(_("Extra settings"))
        dlg.setMinimumWidth(560)            # (the list's width isn't asked for: Ignored)
        dv = dialog_layout(dlg, _("Extra settings"), _(
            "Each one is off until you tick it. The ones you change show on the card; their ✕ "
            "puts them back."))
        self.tune = TuneGrid()
        self.tune.max_cols = 1      # one column: a list to read down
        self._tune_row = self.tune
        self.btn_area = QPushButton(self.tune)
        self.btn_area.setObjectName("small")
        self.btn_area.clicked.connect(lambda: self.area_wanted.emit(self))
        self.chk_region = QCheckBox(_("Only look in part of the window"))
        self.chk_region.setToolTip(_("Look in only part of each window: drag a box around it. "
                                     "Fewer false alarms, quicker checks."))
        self.chk_region.toggled.connect(self._on_region)
        self.interval = WideCombo(min_width=100)
        self.interval.addItem(_("Default"), 0)       # its text: set_default_interval
        for ms in sorted(set(INTERVALS_MS) | {t.interval_ms} - {0}):
            self.interval.addItem(interval_label(ms), ms)
        self.interval.setCurrentIndex(max(0, self.interval.findData(t.interval_ms)))
        self.interval.setToolTip(_("How often this trigger is checked. Default is the speed set "
                                   "under ⚙ (Watching settings, on the bottom bar), for every "
                                   "trigger left on Default. Watching keeps to its share of your "
                                   "processor, so with a lot on it may check less often."))
        no_wheel(self.interval)
        self.interval.currentIndexChanged.connect(self._on_interval)
        self.chk_size = QCheckBox(_("Find it at any size"))
        self.chk_size.setToolTip(
            _("Find the pictures even when the game shows them bigger or smaller than when they "
              "were cut: cut in fullscreen, played in a window, or another UI scale.\nUntick it "
              "if a picture only ever shows at one size and it goes off by mistake."))
        self.chk_size.setChecked(t.any_size)
        self.chk_size.toggled.connect(self._on_size)
        self.threshold = FitSpin()
        self.threshold.setObjectName("stepper")   # arrows like the other numbers
        self.threshold.setSuffix(" %")
        self.below = WideCombo(min_width=70)
        self.below.addItem("below", True)
        self.below.addItem("above", False)
        self.below.setCurrentIndex(0 if t.below else 1)
        self.below.setToolTip(_("Go off when less of the area is the colour (a bar running low), "
                                "or when more of it is"))
        no_wheel(self.below)
        self.below.currentIndexChanged.connect(self._on_below)
        self.lbl_number = QLabel()
        self.match_box = match = labelled("", self.threshold, in_card=True)
        match.layout().insertWidget(0, self.lbl_number)
        match.layout().insertWidget(1, self.below)
        self.delay = FitDoubleSpin()
        self.delay.setRange(0.0, 60.0)
        self.delay.setDecimals(1)
        self.delay.setSingleStep(0.5)
        self.delay.setSuffix(" s")
        self.delay.setValue(t.delay)
        self.delay.setToolTip(_("How long after it goes off to play the sound (0 = straight away)"))
        self.chk_delay = QCheckBox(_("Wait before playing"))
        self.chk_delay.setToolTip(self.delay.toolTip())
        self.cooldown = FitDoubleSpin()
        self.cooldown.setRange(0.0, 600.0)
        self.cooldown.setDecimals(0)
        self.cooldown.setSingleStep(1.0)
        self.cooldown.setSuffix(" s")
        self.cooldown.setValue(t.cooldown)
        self.cooldown.setToolTip(_("After playing, ignore this trigger for this long. It also "
                                   "has to stop before it can play again."))
        self.chk_cooldown = QCheckBox(_("Rest after playing"))
        self.chk_cooldown.setToolTip(self.cooldown.toolTip())
        self.hold = FitDoubleSpin()
        self.hold.setRange(0.0, screenwatch.MAX_HOLD)
        self.hold.setDecimals(1)
        self.hold.setSingleStep(0.5)
        self.hold.setSuffix(" s")
        self.hold.setValue(t.hold)
        self.lbl_hold = QLabel()
        self.hold_box = hold = labelled("", self.hold, in_card=True)
        hold.layout().insertWidget(0, self.lbl_hold)
        self.chk_hold = QCheckBox(_("Only if it lasts"))
        # box -> where it is now: the rules, or up in the sentence
        self._in: dict = {match: self.tune, hold: self.tune, self.btn_area: self.tune}
        self.chk_quiet = QCheckBox(_("Stay quiet while I'm in that window"))
        self.chk_quiet.setToolTip(_("Stay quiet while the window it went off in is the one "
                                    "you're using: you can see it yourself"))
        self.chk_quiet.setChecked(t.unfocused)
        self.chk_quiet.toggled.connect(self._on_quiet)
        self.tune.add_group([
            (self.chk_hold, hold, None),
            (None, rule_hint(_("Ignores things that only flash past"), hold), None),
            (self.chk_delay, self.delay, None),
            (self.chk_cooldown, self.cooldown, None),
            (None, rule_hint(_("So it doesn't go off again and again"), self.cooldown), None),
            (None, self.chk_quiet, None),
            (None, rule_hint(_("You can already see it"), self.chk_quiet), None)],
            _("When it plays"))
        self.tune.add_group([
            (None, match, self.lbl_number),
            (None, rule_hint(_("Lower it if it's missed, raise it if it goes off by mistake"),
                             match), None),
            (self.chk_region, self.btn_area, None),
            (None, rule_hint(_("Fewer false alarms, and quicker"), self.btn_area), None),
            (None, self.chk_size, None)], _("Where it looks"))
        self.tune.add_group([(QLabel(_("Check every")), self.interval, None)],
                            _("How often it looks"))
        dv.addWidget(self.tune)
        # never stretched: room to spare goes above Done, not between the rows (a
        # heading would drift down from its rules)
        self.tune.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Policy.Maximum)
        dv.addStretch(1)
        dv.addSpacing(6)
        done = QPushButton(_("Done"))
        done.setObjectName("primary")
        done.clicked.connect(dlg.accept)
        foot_r = QHBoxLayout()
        foot_r.addStretch(1)
        foot_r.addWidget(done)
        dv.addLayout(foot_r)
        for check, spin in ((self.chk_hold, self.hold), (self.chk_delay, self.delay),
                            (self.chk_cooldown, self.cooldown)):
            check.toggled.connect(lambda on, s=spin: self._on_rule_check(s, on))

        # the bottom line: Test, then (quiet, at the far end) its category, Duplicate
        # and Delete in words, not behind a ⋯ nobody could read
        foot = QHBoxLayout()
        foot.setSpacing(8)
        self.btn_test = QPushButton(_("Test"), self)
        self.btn_test.setObjectName("primary")     # the card's one main button
        icons.set_icon(self.btn_test, "play", size=14)
        self.btn_test.clicked.connect(lambda: self.test.emit(self))
        foot.addWidget(self.btn_test)
        foot.addStretch(1)
        folder = QLabel()
        folder.setPixmap(icons.icon("folder", "muted").pixmap(15, 15))
        folder.setToolTip(_("Category"))
        foot.addWidget(folder)
        self.cb_category = WideCombo(min_width=120)
        self.cb_category.setToolTip(_("The category this trigger is in: a whole category can be "
                                      "switched on or off at once"))
        no_wheel(self.cb_category)
        self.cb_category.activated.connect(self._on_category)
        foot.addWidget(self.cb_category)
        self.btn_dup = ShrinkButton(_("Duplicate"))  # (just its icon when short of room)
        self.btn_dup.setObjectName("small")
        self.btn_dup.setProperty("quiet", True)
        icons.set_icon(self.btn_dup, "copy", size=14)
        self.btn_dup.setToolTip(_("Make a copy of this trigger (pictures, sounds and all)"))
        self.btn_dup.clicked.connect(lambda: self.duplicate.emit(self))
        foot.addWidget(self.btn_dup)
        self.btn_del = ShrinkButton(_("Delete"))
        self.btn_del.setObjectName("small")
        self.btn_del.setProperty("quiet", True)
        icons.set_icon(self.btn_del, "trash", size=14)
        self.btn_del.setToolTip(_("Delete this trigger (Recently deleted keeps it a while)"))
        self.btn_del.clicked.connect(lambda: self.remove.emit(self))
        foot.addWidget(self.btn_del)
        bv.addSpacing(2)
        bv.addLayout(foot)
        for w in (self.delay, self.cooldown, self.hold, self.threshold):
            no_wheel(w)
            w.valueChanged.connect(self._on_numbers)
        self._show_mode_body()
        self._fill_sounds()
        fill_sources(self.where, self._mons, t.sources, self._default_label(),
                     _("Pick windows"))
        if self._categories is not None:
            self.set_categories(self._categories)
        if self._default_ms is not None:
            self.set_default_interval(self._default_ms)
        self._sync_rules()
        self._set_tune_text()
        for control in (self.mode, self.where, self.btn_area, self.interval, self.sound,
                        self.pick, self.until, self.btn_test, self.btn_tune, self.btn_dup,
                        self.btn_del, self.delay,
                        self.cooldown, self.hold, self.threshold, self.below, self.cb_category):
            align_control(control, in_card=True)
        self.sound.setFixedWidth(self.sound.height())     # square, like the +
        self.tune.relayout()        # (the controls' sizes are their real ones now)

    def _show_title(self, _text: str = ""):
        self.title.setText(self.name.text().strip() or _("No name"))

    def _fit_name(self, _text: str = ""):
        """The name box as wide as its text (or the hint while it's empty), plus room
        to type, never wider than the card lets it be."""
        self.name.ensurePolished()      # its style sheet's 11 pt bold, not the default
        fm = QFontMetrics(self.name.font())
        text = self.name.text() or self.name.placeholderText()
        self.name.setMaximumWidth(fm.horizontalAdvance(text) + 32)

    # ------------------------------------------------------------------ open / closed
    @property
    def is_open(self) -> bool:
        return not self.body.isHidden()

    def set_open(self, on: bool):
        """Show the whole card, or just its header (or, beside the editor, show it
        there and stay a tile)."""
        if on and self.on_open is not None:
            self.on_open(self)
            on = False
        if self.pinned:
            on = True
        if on:
            self._build_body()
        self.body.setVisible(on)
        self._arrange(not on)
        if self.btn_open.isChecked() != on:
            self.btn_open.blockSignals(True)
            self.btn_open.setChecked(on)
            self.btn_open.blockSignals(False)
        icons.set_icon(self.btn_open, "fold_open" if on else "fold", "muted", "muted", size=16)
        self.btn_open.setToolTip(_("Close this trigger") if on else _("Open this trigger to change "
                                                                   "it"))

    def set_pad(self, on: bool):
        """Closed, a pad (the Pads view: the picture over the name, how it's doing and
        the switch) or a tile (all on one line)."""
        if on != self.pad:
            self.pad = on
            self._tile = None
            self._arrange(not self.is_open)

    def _thumb_size(self) -> QSize:
        if not self._tile:
            return THUMB_BIG if self._big else THUMB
        return PAD_THUMB if self.pad else TILE_THUMB

    def _arrange(self, tile: bool):
        """The header as a tile's (a small picture, the name over one line: how it's
        doing and what it plays, or what's wrong; the switch), a pad's (the picture
        over the name, and how it's doing beside the switch) or the open card's (the
        whole width: its pictures, the name to type in over what it does and plays,
        the live state and the switch)."""
        if tile == self._tile:
            return
        self._tile = tile
        top = self.top
        for widget in (self.pics, self.badge, self.name_line, self.names, self.live,
                       self.details, self.chk_on, self.btn_open):
            top.removeWidget(widget)
        for col in range(5):
            top.setColumnStretch(col, 0)
        size = self._thumb_size()
        self.strip.set_look(size, 1 if tile else STRIP_THUMBS)
        self.badge.setFixedSize(size + QSize(8, 8))
        self.btn_open.setFixedSize(20 if tile else 28, 28)
        middle = Qt.AlignmentFlag.AlignVCenter
        pad = tile and self.pad
        if pad:
            top.addWidget(self.pics, 0, 0, 1, 2, Qt.AlignHCenter)
            top.addWidget(self.badge, 0, 0, 1, 2, Qt.AlignHCenter)
        else:
            top.addWidget(self.pics, 0, 0, 2, 1, Qt.AlignLeft | middle)
            top.addWidget(self.badge, 0, 0, 2, 1, Qt.AlignLeft | middle)
        # (a pad has no arrow: a click opens it)
        self.btn_open.setVisible(not pad and self.on_open is None and not self.pinned)
        if pad:
            top.addWidget(self.name_line, 1, 0, 1, 2)
            top.addWidget(self.live, 2, 0, Qt.AlignLeft | middle)
            top.addWidget(self.names, 2, 0, Qt.AlignLeft | middle)    # (_fit_lines)
            top.addWidget(self.chk_on, 2, 1, Qt.AlignRight | middle)
            top.addWidget(self.details, 3, 0, 1, 2)
            top.setColumnStretch(0, 1)
            self.setCursor(Qt.PointingHandCursor)
            self.setToolTip(_("Click to open it, drag to move it"))
        elif tile:
            top.addWidget(self.name_line, 0, 1, 1, 2, Qt.AlignBottom)
            top.addWidget(self.live, 1, 1, Qt.AlignLeft | Qt.AlignTop)
            top.addWidget(self.names, 1, 2, Qt.AlignTop)    # (_fit_lines moves it)
            top.addWidget(self.chk_on, 0, 3, 2, 1, middle)
            top.addWidget(self.btn_open, 0, 4, 2, 1, middle)
            top.addWidget(self.details, 2, 1, 1, 2)     # under the name, like its line
            top.setColumnStretch(2, 1)
            self.setCursor(Qt.PointingHandCursor)
            self.setToolTip(_("Click to open it, drag to move it"))
        else:
            top.addWidget(self.name_line, 0, 1, Qt.AlignmentFlag.AlignBottom)
            top.addWidget(self.names, 1, 1, Qt.AlignTop)
            top.addWidget(self.live, 0, 2, 2, 1, middle)
            top.addWidget(self.chk_on, 0, 3, 2, 1, middle)
            top.addWidget(self.btn_open, 0, 4, 2, 1, middle)
            top.setColumnStretch(1, 1)
            self.unsetCursor()
            self.setToolTip("")
        self.title.setVisible(tile)
        self.name.setVisible(not tile)
        self.live.setAlignment((Qt.AlignmentFlag.AlignLeft if tile
                                else Qt.AlignmentFlag.AlignRight) | middle)
        self.live.setContentsMargins(6 if tile else 0, 0, 0, 0)
        self._live_room = None          # sized again for its margins
        self._fit_live()
        self.details.setVisible(tile and self.advanced)
        self._fit_text()
        self._said = None
        self._fit_lines()
        self._narrow = None             # re-decided for the new layout
        self._fit_narrow()
        self._show_thumb()
        self.updateGeometry()

    def _fit_text(self):
        """A closed card keeps its name and its line to one line each, cut short with
        an …; with Show more info on it's as tall as it takes to read all of them."""
        whole = bool(self._tile) and self.advanced
        self.title.set_elide(not whole)
        self.state.set_elide(not whole)
        self.sound_summary.set_elide(bool(self._tile) and not whole)

    def _fit_lines(self):
        """A tile has one line under its name: what's wrong (or a note, or a flash)
        when there's something to say, else how it's doing and what it plays. Open,
        all of them."""
        say = bool(self.state.property("tone")) or self.btn_retarget.isVisibleTo(self)
        pad = bool(self._tile) and self.pad
        # open, the sentence says what it does and plays: only what's wrong is said here
        self.state.setVisible(say)
        # a pad: what's wrong, else how it's doing, beside its switch (no sounds line)
        self.sound_summary.setVisible(bool(self._tile) and not (say or pad))
        self.names.setVisible((not pad or say) and (bool(self._tile) or say))
        self.live.setVisible(not self._tile or not say)
        if not self._tile:      # the name in the middle of the header, or over what's wrong
            self.top.removeWidget(self.name_line)
            align = Qt.AlignmentFlag.AlignBottom if say else Qt.AlignmentFlag.AlignVCenter
            self.top.addWidget(self.name_line, 0, 1, 1 if say else 2, 1, align)
        if pad:
            self._said = say
        elif self._tile and say != self._said:    # under the name, where the state was
            self._said = say
            self.top.removeWidget(self.names)
            self.top.addWidget(self.names, 1, 1 if say else 2, 1, 2 if say else 1,
                               Qt.AlignTop)

    NARROW = 440        # px: below this the header's thumbnails go, for the rest to fit

    def changeEvent(self, ev):
        super().changeEvent(ev)
        if ev.type() in (QEvent.StyleChange, QEvent.FontChange):   # a theme was applied
            self._fit_name()
            if hasattr(self, "live"):   # (not yet while it's being made)
                self._live_shown = ""   # the dot's colour is the theme's
                self._live_room = None  # ...and its font
                self.show_score(self._score)    # (the score it had: a restyle isn't news)

    def showEvent(self, ev):
        super().showEvent(ev)
        self._fit_name()          # polished by now: the host's fonts are in

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self._fit_narrow()

    def _fit_narrow(self):
        narrow = not self._tile and self.width() < self.NARROW
        big = not self._tile and self.width() >= BIG_CARD
        if big != self._big:
            self._big = big
            self.name.setProperty("big", big)
            self.name.style().unpolish(self.name)
            self.name.style().polish(self.name)
            self._fit_name()
            size = self._thumb_size()
            self.strip.set_look(size, STRIP_THUMBS)
            self.badge.setFixedSize(size + QSize(8, 8))
            self._narrow = None
        if narrow != self._narrow:
            self._narrow = narrow
            self._show_thumb()

    def _show_thumb(self):
        """The header's pictures (or the badge of a trigger without), unless the card
        is too narrow for them."""
        pics = self.t.uses_pictures
        self.pics.setVisible(pics and not self._narrow)
        self.badge.setVisible(not pics and not self._narrow)
        # the +: with no picture yet it's the slot the first one goes in; after that
        # it follows the open card's pictures, and is on a closed card's thumbnail
        some = bool(self.t.images)
        size = self._thumb_size()
        self.strip.setVisible(some)
        self.btn_add_pic.setVisible(not some or not self._tile)
        self.btn_add_pic.setFixedSize(28 if some else size.width() + 8, size.height() + 8)

    # ------------------------------------------------------------------ click, drag, drop
    MIME = "application/x-onionwatch-trigger"   # a card being dragged: its trigger's id

    def _on_header(self, pos) -> bool:
        return not self.pinned and (not self.is_open or pos.y() < self.body.y())

    def mousePressEvent(self, ev):
        """A press on the header (not on one of its controls): a click opens or closes
        the card, a drag moves it (to another place, or another category)."""
        if ev.button() == Qt.LeftButton and self._on_header(ev.position()):
            self._press = ev.position().toPoint()
            ev.accept()
            return
        self._press = None
        super().mousePressEvent(ev)

    def mouseMoveEvent(self, ev):
        if (self._press is not None and ev.buttons() & Qt.LeftButton
                and (ev.position().toPoint() - self._press).manhattanLength()
                >= QApplication.startDragDistance()):
            self._press = None
            self.drag()
            return
        super().mouseMoveEvent(ev)

    def mouseReleaseEvent(self, ev):
        if ev.button() == Qt.LeftButton and self._press is not None:
            self._press = None
            self.set_open(not self.is_open)
            ev.accept()
            return
        super().mouseReleaseEvent(ev)

    def drag(self):
        """Pick the card up: the category it's dropped on puts it there (categories)."""
        from PySide6.QtCore import QMimeData
        from PySide6.QtGui import QDrag, QPainter
        mime = QMimeData()
        mime.setData(self.MIME, self.t.id.encode())
        d = QDrag(self)
        d.setMimeData(mime)
        shot = self.grab(QRect(0, 0, self.width(), self.body.y() if self.is_open
                               else self.height()))
        if shot.width() > 320:
            shot = shot.scaledToWidth(320, Qt.SmoothTransformation)
        faded = QPixmap(shot.size())
        faded.fill(Qt.transparent)
        p = QPainter(faded)
        p.setOpacity(0.8)
        p.drawPixmap(0, 0, shot)
        p.end()
        d.setPixmap(faded)
        d.setHotSpot(QPoint(min(24, faded.width() // 2), min(24, faded.height() // 2)))
        d.exec(Qt.MoveAction)

    @staticmethod
    def picture_files(mime) -> list[str]:
        """The picture files in a drag (by their extension), if any."""
        exts = {e[1:] for e in PICTURE_EXTS.split()}
        return [u.toLocalFile() for u in mime.urls()
                if u.isLocalFile() and Path(u.toLocalFile()).suffix.lower() in exts]

    @staticmethod
    def dropped_picture(mime) -> QImage | None:
        """A picture itself in a drag (one dragged from a browser), if there is one."""
        if not mime.hasImage():
            return None
        img = QImage(mime.imageData())
        if img.isNull():
            return None
        set_web(img)
        return img

    def dragEnterEvent(self, ev):
        mime = ev.mimeData()
        if self.t.uses_pictures and (self.picture_files(mime) or mime.hasImage()):
            ev.acceptProposedAction()
            self.setStyleSheet(card_css("QFrame#card { border-color:palette(highlight); }"))
        else:
            ev.ignore()             # a card being moved: the category takes it

    def _unmark(self):
        self.setStyleSheet(card_css())

    def _hover(self, on: bool):
        if self.property("interactive") and self.property("hovered") != on:
            self.setProperty("hovered", on)
            self.style().unpolish(self)
            self.style().polish(self)
            self.update()

    def enterEvent(self, ev):
        self._hover(True)
        super().enterEvent(ev)

    def leaveEvent(self, ev):
        self._hover(False)
        super().leaveEvent(ev)

    def set_selected(self, on: bool):
        """Mark it as the one the editor beside the list is showing."""
        if on != self.selected:
            self.selected = on
            self.setProperty("selected", on)
            # Only the frame's border changes. Replacing its sheet also restyles
            # every child, including a previously opened tile's hidden editor.
            self.style().unpolish(self)
            self.style().polish(self)
            self.update()

    def dragLeaveEvent(self, ev):
        self._unmark()
        super().dragLeaveEvent(ev)

    def dropEvent(self, ev):
        self._unmark()
        files = self.picture_files(ev.mimeData())
        if files:
            ev.acceptProposedAction()
            self.files_dropped.emit(self, files)
        elif (img := self.dropped_picture(ev.mimeData())) is not None:
            ev.acceptProposedAction()
            self.picture_dropped.emit(self, img)

    def _add_menu(self) -> QMenu:
        """The header's +: the ways to add a picture."""
        menu = QMenu(self)
        menu.addAction(icons.icon("crop"), _("Cut from window"),
                       lambda: self.cut_wanted.emit(self))
        menu.addAction(icons.icon("plus"), _("Picture files"),
                       lambda: self.pictures_wanted.emit(self))
        paste = menu.addAction(icons.icon("image"), _("Paste the copied picture"),
                               lambda: self.paste_wanted.emit(self))
        paste.setEnabled(not QApplication.clipboard().image().isNull())
        return menu

    def _show_add_menu(self):
        b = self.btn_add_pic if self.btn_add_pic.isVisible() else self.strip
        self._add_menu().exec(b.mapToGlobal(QPoint(0, b.height())))

    def show_rules(self):
        """Extra settings: in a pop-up over the card (not waited on: what's ticked shows
        on the card at once)."""
        dlg = self.rules_dlg
        # the card's child, so it takes the card's sheet and not the app's dialog fill:
        # the theme's panel colour, read as it opens (palette(window) is the system's,
        # light under a dark theme; and on "bg" the number boxes, "field", vanish)
        dlg.setStyleSheet(
            f"QDialog#rulesdialog {{ background: {theme.T.get('panel', '#202020')}; }}")
        self.tune.relayout()
        dlg.adjustSize()
        # adjustSize sizes the hint for a narrower width (two lines): as tall as it needs
        # at the width it got, or the slack spreads out between the rows
        lay = dlg.layout()
        if lay is not None and lay.hasHeightForWidth():
            dlg.resize(dlg.width(), lay.totalHeightForWidth(dlg.width()))
        dlg.open()

    def _rules(self) -> list[tuple[str, str]]:
        """The rules it has that aren't how a new trigger comes, as (rule, words):
        ("match", "Match 90 %"), ("size", "Exact size only")... Not what the sentence
        already says (a bar's level, how long nothing moves), nor its category (the
        section it's in, and the list at the bottom)."""
        t, d = self.t, Trigger(id="")
        rules = []
        if t.uses_pictures:     # (otherwise the level is in the sentence)
            if round(t.number * 100) != round(d.threshold * 100):
                rules.append(("match", _("Match {n} %", n=round(t.number * 100))))
            if not t.any_size:
                rules.append(("size", _("exact size only")))
        if t.hold and t.mode != "still":
            rules.append(("hold", _("only if it lasts {s:g} s", s=t.hold)))
        if t.delay:
            rules.append(("delay", _("wait {s:g} s before playing", s=t.delay)))
        if t.cooldown != d.cooldown:
            rules.append(("cooldown", _("rest {s:g} s after playing", s=t.cooldown)
                          if t.cooldown else _("no rest after playing")))
        if t.uses_pictures and t.region is not None:
            rules.append(("region", _("part of the window")))
        if t.unfocused:
            rules.append(("quiet", _("quiet while you're in the window")))
        if t.interval_ms:
            rules.append(("interval", _("checks every {ms} ms", ms=t.interval_ms)))
        return [(key, capital(text)) for key, text in rules]

    def _tune_summary(self) -> str:
        """The rules it has on, in a line: "Match 90 % · Exact size only"."""
        return " · ".join(text for _key, text in self._rules())

    def _set_tune_text(self):
        """The rules it has on as chips (a ✕ each to take it off), then Rules."""
        rules = self._rules()
        if rules == self._rules_shown:      # (asked on every change of state)
            return
        self._rules_shown = rules
        flow = self.rules_box.flow
        while flow.count():
            flow.takeAt(0)
        old, self.rule_chips = self.rule_chips, []
        for key, text in rules:
            chip = QFrame()
            chip.setObjectName("chip")
            chip.setProperty("rule", key)
            chip.setProperty("pill", True)
            chip.setFixedHeight(control_height(chip))
            h = QHBoxLayout(chip)
            h.setContentsMargins(4, 0, 2, 0)
            h.setSpacing(2)
            name = QLabel(text)
            name.setObjectName("rulename")
            h.addWidget(name)
            x = QPushButton("✕")
            x.setObjectName("chipstop")
            x.setFixedSize(22, 22)
            x.setToolTip(_("Put this back to normal"))
            x.clicked.connect(lambda __=False, k=key: self._drop_rule(k))
            h.addWidget(x)
            self.rule_chips.append(chip)
            flow.addWidget(chip)
        flow.addWidget(self.btn_tune)
        flow.invalidate()
        self.rules_box._fit()
        for chip in old:
            chip.setParent(None)        # (see _fill_sounds)
            chip.deleteLater()

    def _drop_rule(self, key: str):
        """A rule chip's ✕: back to how a new trigger has it."""
        d = Trigger(id="")
        if key == "match":
            self.threshold.setValue(round(d.threshold * 100))
        elif key == "size":
            self.chk_size.setChecked(True)
        elif key == "hold":
            self.chk_hold.setChecked(False)
        elif key == "delay":
            self.chk_delay.setChecked(False)
        elif key == "cooldown":
            self.cooldown.setValue(d.cooldown)
        elif key == "region":
            self.chk_region.setChecked(False)
        elif key == "quiet":
            self.chk_quiet.setChecked(False)
        elif key == "interval":
            self.interval.setCurrentIndex(0)

    def _on_rule_check(self, spin: QDoubleSpinBox, on: bool):
        """A number rule's tick box: on, its number (1 s, or a new trigger's rest);
        off, 0 (no wait, no rest)."""
        if on and not spin.value():
            spin.setValue(Trigger(id="").cooldown if spin is self.cooldown else 1.0)
        elif not on:
            spin.setValue(0.0)
        self._sync_rules()

    def _on_region(self, on: bool):
        """"Only look in part of the window": drag the box (the area dialog), or back
        to the whole window."""
        t = self.t
        if on and t.region is None:
            self.area_wanted.emit(self)     # (cancelled: _label_area unticks it again)
            self._label_area()
        elif not on and t.region is not None and t.uses_pictures:
            t.region = None
            self._label_area()
            self._update_state()
            self.changed.emit(self)

    def _sync_rules(self):
        """The rules' tick boxes as their numbers say, each number only to be changed
        while its box is ticked."""
        if not self._built:
            return
        for check, spin in ((self.chk_hold, self.hold), (self.chk_delay, self.delay),
                            (self.chk_cooldown, self.cooldown)):
            check.blockSignals(True)
            check.setChecked(spin.value() > 0)
            check.blockSignals(False)
            spin.setEnabled(spin.value() > 0 or spin is self.hold and self.t.mode == "still")

    # ------------------------------------------------------------------ view
    def _place(self, box: QWidget, main: bool):
        """Put a setting in the "When … in …" line (`main`: it's what the trigger is
        about, a bar's level) or under More options."""
        want = self._watch_row if main else self.tune
        if self._in[box] is not want:
            self._in[box].removeWidget(box)
            want.addWidget(box)
            self._in[box] = want
            box.show()

    def _show_mode(self):
        """Show the controls the trigger's mode uses, labelled for it."""
        t = self.t
        pics = t.uses_pictures
        self._show_thumb()
        if not pics:
            self.badge.setPixmap(icons.pixmap(
                {"change": "live", "still": "pause", "colour": "palette"}.get(t.mode, "triggers"),
                28, theme.T.get("muted", "#888888")))
        self.live.setToolTip(_("Right now: how well it matches (the best of its pictures)")
                             if pics else _("Right now, in the place closest to going off"))
        if self._built:
            self._show_mode_body()

    def _show_mode_body(self):
        """The editor's part of _show_mode."""
        t = self.t
        pics = t.uses_pictures
        self._place(self.match_box, not pics)          # a bar's level, how much changes
        self._place(self.hold_box, t.mode == "still")  # how long nothing may move
        self._place(self.btn_area, not pics)           # the bar, the area that changes
        self.chk_size.setVisible(pics)
        self.below.setVisible(t.mode == "colour")
        # the box is kept as a share of the window, so it follows the window when it's
        # moved or resized; a whole screen, a HUD pinned to a corner, or a game that stops
        # drawing while you're away can still fool it
        note = {"change": _("Works best on the game's own window, not a whole screen. If you "
                            "resize the game, check the box still covers the right part."),
                "still": _("Works best on the game's own window, not a whole screen. Some "
                           "games stop drawing while you're alt-tabbed, which looks like "
                           "nothing moving and can set it off.")}.get(t.mode, "")
        self.area_note.setText(note)
        self.area_note.setVisible(bool(note))
        self.threshold.blockSignals(True)
        if pics:
            self.threshold.setRange(30, 99)
            self.threshold.setValue(round(t.threshold * 100))
        else:
            self.threshold.setRange(1, 99)
            self.threshold.setValue(round(t.level * 100))
        self.threshold.blockSignals(False)
        self.lbl_number.setText({"appear": _("Match"), "vanish": _("Match"),
                                 "change": _("Amount of change"),
                                 "still": _("Still if under"),
                                 "colour": _("Colour")}[t.mode])
        self.threshold.setToolTip({
            "appear": _("How alike the picture must be to count. Lower it if the picture is "
                        "missed, raise it if it plays by mistake — the live number helps."),
            "vanish": _("How alike the picture must be to count as there; it's gone once it "
                        "drops below this."),
            "change": _("How much of the area must change at once to count. Raise it if small "
                        "animations set it off."),
            "still": _("Anything moving less than this much of the area counts as nothing "
                       "happening."),
            "colour": _("How much of the area is the colour, as a share: a bar that's full "
                        "reads about 100 %, half empty about 50 %."),
        }[t.mode])
        # (in the rules, its tick box says it)
        self.lbl_hold.setText(_("Still for") if t.mode == "still" else "")
        self.lbl_hold.setVisible(t.mode == "still")
        for lab in (self.lbl_number, self.lbl_hold):     # (the grid sizes them again)
            lab.setMinimumWidth(0)
            lab.setMaximumWidth(16777215)
        self.hold.setToolTip(
            _("How long nothing may change before it plays") if t.mode == "still" else
            _("It only counts once it has gone on this long, so a flicker or a loading screen "
              "doesn't set it off (0 = at once)"))
        self._label_area()
        self.tune.relayout()

    def _label_area(self):
        if not self._built:
            return
        t = self.t
        colour = t.mode == "colour"
        if colour:
            self.btn_area.setText(_("Bar and colour") if t.region is None or not t.colour
                                  else _("Bar: set"))
            self.btn_area.setIcon(swatch(t.colour) if t.colour else QIcon())
            self.btn_area.setToolTip(_("Drag a box around the bar to measure and check its colour"))
        elif t.uses_pictures:     # in the rules, after "Only look in part of the window"
            self.btn_area.setText(_("Drag a box") if t.region is None else _("Change the box"))
            self.btn_area.setIcon(QIcon())
            self.btn_area.setToolTip(_("Look in only part of each window: drag a box around it. "
                                       "Fewer false alarms, quicker checks."))
        else:                     # in the sentence: the area that changes
            self.btn_area.setText(_("Whole window") if t.region is None
                                  else _("Part of the window"))
            self.btn_area.setIcon(QIcon())
            self.btn_area.setToolTip(_("Look in only part of each window: drag a box around it. "
                                       "Fewer false alarms, quicker checks."))
        self.chk_region.blockSignals(True)
        self.chk_region.setChecked(t.region is not None)
        self.chk_region.blockSignals(False)
        self._sync_rules()

    def set_sounds(self, sounds: list[tuple[str, str]]):
        """The sounds on offer: fill the "+ Add sound" list and redraw the chips (once
        the editor is made: a closed tile only names them)."""
        self._sounds = list(sounds)
        names = dict(sounds)
        self.missing = [sid for sid in self.t.sounds if sid not in names]
        if self._built:
            self._fill_sounds()
        self._update_state()

    def _fill_sounds(self):
        sounds = self._sounds
        cb = self.sound
        cb.blockSignals(True)
        cb.clear()
        cb.addItem(icons.icon("plus"), "", ADD)     # what the closed box shows
        cb.addItem(icons.icon("folder"), _("Choose a sound file"), FILE)
        cb.set_sounds(sounds)                       # its menu's list, not items
        cb.setCurrentIndex(0)
        cb.view().setRowHidden(0, True)                # ...but not a choice in the list
        cb.blockSignals(False)
        names = dict(sounds)
        old, self.chips = self.chips, []
        for sid in self.t.sounds:
            self.chips.append(self._chip(names.get(sid, _("Removed sound")), sid,
                                         warn=sid not in names))
        self.pick.setVisible(len(self.t.sounds) > 1)
        self._layout_sounds()
        for chip in old:
            # off the card now: a chip waiting for the event loop to delete it is still
            # a child of the card, and one never laid out paints its frame at Qt's
            # default size over the card
            chip.setParent(None)
            chip.deleteLater()

    def _layout_sounds(self):
        """Put the sounds row's widgets back in order (the Flow layout has no insert)."""
        while self.sounds_row.count():
            self.sounds_row.takeAt(0)
        for w in (self.lbl_play, *self.chips, self.sound, self.pick):
            self.sounds_row.addWidget(w)
        self.sounds_row.invalidate()
        self.sounds_box._fit()

    def _chip(self, text: str, sid: str, warn: bool = False) -> QFrame:
        """A sound the trigger plays: its name (click to hear it) and a ✕."""
        chip = QFrame()
        chip.setObjectName("chip")
        chip.setProperty("token", "true")      # like the sentence's other choices
        chip.setFixedHeight(control_height(chip))
        h = QHBoxLayout(chip)
        h.setContentsMargins(6, 0, 4, 0)
        h.setSpacing(2)
        name = QPushButton(text if len(text) <= CHIP_CHARS else text[:CHIP_CHARS - 1] + "…")
        name.setObjectName("chipname")
        icons.set_icon(name, "volume", size=14)
        if warn:
            name.setToolTip(_("This sound file is gone — pick another"))
            name.setStyleSheet(f"color:{theme.status('warn')};")
        else:
            name.setToolTip(_("{text} — click to hear it", text=text))
            name.clicked.connect(lambda __=False, s=sid: self.hear.emit(s))
        h.addWidget(name)
        x = QPushButton("✕")
        x.setObjectName("chipstop")
        x.setFixedSize(22, 22)
        x.setToolTip(_("Take this sound off the trigger"))
        x.clicked.connect(lambda __=False, s=sid: self._remove_sound(s))
        h.addWidget(x)
        return chip

    def set_screens(self, mons: list[Monitor]):
        """Fill the "Look in" list with the screens there are now."""
        t = self.t
        self._mons = list(mons)
        self._screens = len(mons)
        if self._built:
            fill_sources(self.where, mons, t.sources, self._default_label(),
                         _("Pick windows"))
        self.fallback = any(not 0 <= m < len(mons) for m in t.screens)
        self._update_state()

    def refresh_pictures(self):
        """Redraw the strip after the trigger's pictures changed."""
        t = self.t
        self.strip.set_paths(t.images)
        room = len(t.images) < MAX_PICTURES
        self.btn_add_pic.setEnabled(room)
        self.strip.set_can_add(room)
        self._show_thumb()
        self._update_state()

    def show_score(self, score: float | None):
        """The live state, a coloured dot and a word: Off, Waiting, Cooldown, Ready,
        Watching, or while watching how well it matches (bold once it would go off)."""
        self._score = score
        T = theme.T
        muted, accent = T.get("muted", "#888888"), T.get("accent", "#1fb6a6")
        bold, meter = False, None
        if not self.t.enabled:
            word, dot = _("Off"), T.get("off", muted)
        elif self.note:
            word, dot = _("Waiting"), theme.status("warn")
        elif self.watching and time.monotonic() < self.cooldown_until:
            word, dot = _("Cooldown"), theme.status("warn")
        elif not trigger_ready(self.t) or not self.t.sounds:
            word, dot = _("Not set up"), muted    # as Chances says: nothing to watch yet
        elif score is None:
            word, dot = (_("Watching"), accent) if self.watching else (_("Ready"), muted)
        else:
            bold = screenwatch.verdict(self.t.mode, score, self.t.number, self.t.below) is True
            word = f"{max(0, round(score * 100))}%"
            dot = theme.status("ok") if bold else accent
            meter = (score, self.t.number, bold, goes_below(self.t))
        self.live.set_meter(meter)
        text = (f'<span style="color:{dot}">●</span>&nbsp;'
                + (f"<b>{word}</b>" if bold else word))
        if text != self._live_shown:        # every POLL_MS on every card: only on a change
            self._live_shown = text
            self.live.setText(text)
            self._live_score = len(word) <= 4 and word.endswith("%")    # 0% to 100%
            self._fit_live()

    def _fit_live(self):
        """The live state's label as big as its text, but a score always as big as
        the widest one ("100%", bold): a label that can't change size doesn't ask for
        a new layout, so a score changing every check never moves the card's other
        parts, or makes the page lay all its cards out again."""
        live = self.live
        if self._live_score:
            if self._live_room is None:     # (again after a theme or the margins change)
                self._live_room = live.meter_size()
            size = self._live_room
        else:
            size = live.sizeHint()
        if live.minimumSize() != size or live.maximumSize() != size:
            live.setFixedSize(size)

    def set_note(self, note: tuple[str, str] | None, waiting: WindowRef | None = None):
        """What watching says about this trigger's window or screen (not open,
        minimized, black), or None; `waiting`: the window it says isn't open."""
        if note != self.note or waiting != self.waiting:
            self.note = note
            self.waiting = waiting
            if not self._flash.isActive():
                self._update_state()

    def flash(self, text: str, ms: int = 2500, tone: str = "ok"):
        self.state.setText(text)
        theme.set_tone(self.state, tone)
        self._fit_lines()
        self._flash.start(ms)

    def _what(self) -> str:
        """When it plays, in words: "as soon as it shows up"…"""
        t = self.t
        n = round(t.number * 100)
        return {
            "appear": _("{s:g} s after it shows up", s=t.delay) if t.delay
            else _("as soon as it shows up"),
            "vanish": _("when its picture goes away"),
            "change": _("when something changes in its area"),
            "still": _("when nothing has moved for {s:g} s", s=t.hold),
            "colour": _("when the colour is below {n}% of the bar", n=n) if t.below
            else _("when the colour is above {n}% of the bar", n=n),
        }[t.mode]

    def _update_state(self):
        t = self.t
        n = len(t.sounds)
        retarget = False
        if t.uses_pictures and not t.images:
            text, tone = _("No picture yet — click + to add one"), "warn"
        elif t.mode == "colour" and (not t.colour or t.region is None):
            text, tone = _("Pick the bar to measure — Bar and colour"), "warn"
        elif not n:
            text, tone = _("Pick the sound to play"), "warn"
        elif len(self.missing) == n:
            text, tone = (_("Its sound file is gone — pick another") if n == 1 else
                          _("Its sound files are gone — pick others")), "warn"
        elif self.fallback:
            text = (_("Screen {n} isn't plugged in, so it's looked for on the screen picked "
                      "below", n=t.monitor + 1) if self._screens > 1 else
                    _("Screen {n} isn't plugged in, so it's looked for on the main screen",
                      n=t.monitor + 1))
            tone = "warn"
        elif self.note is not None:
            text, tone = self.note
            retarget = self.waiting is not None
        else:
            # when, then what it does, each a whole phrase of its own (no English
            # glued into another language's sentence)
            parts = [capital(self._what())]
            if t.ring:
                parts.append(UNTILS[t.stop][1])
            elif n <= 1:
                parts.append(_("plays its sound once"))
            if n > 1:
                parts.append({"random": _("one of its {n} sounds at random", n=n),
                              "order": _("its {n} sounds in turn", n=n),
                              "all": _("all {n} sounds at once", n=n)}[t.pick])
            text = " · ".join(parts)
            if len(t.sources) > 1 or any(isinstance(s, WindowRef) and s.every
                                         for s in t.sources):
                place = places_label(t.sources) if len(t.sources) > 1 else t.sources[0].label
                text += _(", in {place}", place=place)
            tone = ""
        self.state.setText(text)
        theme.set_tone(self.state, tone)
        self.btn_retarget.setVisible(retarget)
        self._fit_lines()
        if self._built:
            self._set_tune_text()
        sounds = dict(self._sounds)
        self.sound_summary.setText("♪ " + (", ".join(sounds.get(s, _("Removed sound"))
                                                    for s in t.sounds) or _("Choose a sound")))
        where = places_label(t.sources) if t.sources else _("Default window / screen")
        interval = f"{t.interval_ms} ms" if t.interval_ms else _("default")
        self.details.setText(
            _("Look in: {where}\n{mode} · check every {interval}\nCooldown: {cooldown:g} s · "
              "{size}\nArea: {area} · {pictures}\n",
              where=where, mode=dict(MODES)[t.mode], interval=interval, cooldown=t.cooldown,
              size=_("Any size") if t.any_size else _("Original size"),
              area=_("custom") if t.region else _("whole view"),
              pictures=pictures(len(t.images)))
            + "\n".join(self.sound_details(sid) for sid in t.sounds))
        self.details.setVisible(self.advanced and bool(self._tile))

    def set_advanced(self, on: bool):
        self.advanced = on
        self.details.setVisible(on and bool(self._tile))
        self._fit_text()
        self.updateGeometry()

    # ------------------------------------------------------------------ edits
    def _on_interval(self, _index):
        self.t.interval_ms = self.interval.currentData()
        self._update_state()
        self.changed.emit(self)

    def _default_label(self) -> str:
        """The Look in list's first choice: the bottom bar's, by name."""
        return (_("Default ({place})", place=self.default_place) if self.default_place
                else _("Default"))

    def set_default_place(self, place: str):
        """Say where "Default" looks now (the Look in on the bottom bar)."""
        self.default_place = place
        if self._built and self.where.count() and self.where.itemData(0) == DEFAULT:
            self.where.setItemText(0, self._default_label())

    def set_default_interval(self, ms: int):
        """Say what "Default" is now (the speed picked under ⚙)."""
        self._default_ms = ms
        if self._built:
            self.interval.setItemText(0, _("Default ({ms} ms)", ms=ms))

    def _on_name(self):
        name = self.name.text().strip() or _("Trigger")
        if name != self.t.name:
            self.t.name = name
            self.changed.emit(self)

    def set_categories(self, names: list[str]):
        """The categories it can be put in (onionwatch.engine.profiles), its own picked."""
        self._categories = list(names)
        if not self._built:
            return
        cb = self.cb_category
        cb.blockSignals(True)
        cb.clear()
        for n in names if self.t.category in names else [*names, self.t.category]:
            cb.addItem(profiles.label(n), n)
        cb.insertSeparator(cb.count())
        cb.addItem(_("New category"), NEW_CATEGORY)
        cb.setCurrentIndex(max(0, cb.findData(self.t.category)))
        cb.blockSignals(False)

    def _on_category(self, _i: int):
        want = self.cb_category.currentData()
        self.cb_category.setCurrentIndex(max(0, self.cb_category.findData(self.t.category)))
        if want is not None and want != self.t.category:
            self.category_wanted.emit(self, want)

    def _on_enabled(self, on: bool):
        self.t.enabled = on
        self.show_score(None)   # "Off" (or back to Ready) now, not on the next check
        self.changed.emit(self)

    def _on_ring(self, on: bool):
        self.t.ring = on
        self.until.setVisible(on)
        self._update_state()
        self.changed.emit(self)

    def _on_until(self, _i: int):
        self.t.stop = self.until.currentData()
        self._update_state()
        self.changed.emit(self)

    def _on_quiet(self, on: bool):
        self.t.unfocused = on
        self._update_state()
        self.changed.emit(self)

    def _on_size(self, on: bool):
        self.t.any_size = on
        self._update_state()
        self.changed.emit(self)

    def _on_mode(self, i: int):
        key = self.mode.itemData(i)
        t = self.t
        if key not in screenwatch.MODES or key == t.mode:
            return
        t.mode = key
        if key in LEVELS:
            t.level = LEVELS[key]
        if key == "still" and t.hold < 1:
            t.hold = 10.0
        elif t.hold == 10.0:
            t.hold = 0.0            # the "still" default, not a wait the user picked
        self.hold.blockSignals(True)
        self.hold.setValue(t.hold)
        self.hold.blockSignals(False)
        self._show_mode()
        self._update_state()
        self.changed.emit(self)
        if key == "colour" and (not t.colour or t.region is None):
            self.area_wanted.emit(self)     # nothing to measure yet: pick the bar

    def _on_below(self, i: int):
        below = bool(self.below.itemData(i))
        if below != self.t.below:
            self.t.below = below
            self._update_state()
            self.changed.emit(self)

    def _on_sound(self, i: int):
        """An item of the "+ Add sound" box was picked (only FILE is one)."""
        self._add_sound(self.sound.itemData(i))

    def _add_sound(self, sid):
        """A sound of the "+ Add sound" menu was picked: add it to the trigger."""
        self.sound.blockSignals(True)
        self.sound.setCurrentIndex(0)
        self.sound.blockSignals(False)
        if sid == FILE:
            self.sound_file_wanted.emit(self)
            return
        if not sid or sid == ADD or sid in self.t.sounds:
            return
        if len(self.t.sounds) >= MAX_SOUNDS:
            self.flash(_("A trigger can play up to {n} sounds", n=MAX_SOUNDS), 4000, "warn")
            return
        self.t.sounds.append(sid)
        self.set_sounds(self._sounds)
        self.changed.emit(self)

    def _remove_sound(self, sid: str):
        if sid not in self.t.sounds:
            return
        self.t.sounds.remove(sid)
        self.set_sounds(self._sounds)
        self.changed.emit(self)

    def _on_pick(self, i: int):
        key = self.pick.itemData(i)
        if key in screenwatch.PICKS and key != self.t.pick:
            self.t.pick = key
            self._update_state()
            self.changed.emit(self)

    def _on_where(self, i: int):
        data = self.where.itemData(i)
        t = self.t
        if data == PICK_WINDOW:
            self.set_screens(self._mons)       # back to the current choice until one is picked
            self.window_wanted.emit(self)
            return
        if data == PLACES:
            return
        places = [data] if isinstance(data, int) and not isinstance(data, bool) else []
        if places == t.sources:
            return
        t.sources = places
        self.note = self.waiting = None
        self.set_screens(self._mons)
        self.changed.emit(self)

    def set_places(self, places: list):
        """Look in these windows and screens from now on."""
        self.t.sources = list(places)
        self.note = self.waiting = None
        self.set_screens(self._mons)
        self.changed.emit(self)

    def _on_numbers(self, _v=None):
        t = self.t
        t.delay = round(self.delay.value(), 1)
        t.cooldown = float(self.cooldown.value())
        t.hold = round(self.hold.value(), 1)
        if t.uses_pictures:
            t.threshold = self.threshold.value() / 100
        else:
            t.level = self.threshold.value() / 100
        self._sync_rules()
        self._update_state()
        self.changed.emit(self)
