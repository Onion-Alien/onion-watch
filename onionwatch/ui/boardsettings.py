"""The Settings tab, inside Onion Board only (TriggerPages' third tab): Onion Watch
has no settings window of its own there. At the top what it is (the version, that
it's an add-on of the board) with Send feedback, Report a problem, What's new and its
GitHub page; then the Watching cards (watching.WatchingBody); last *Remove Onion
Watch…*.

The remove item is the board's: it puts it last in the menu of the add-on's
`btn_more` (board.BoardPanel hands it a menu of its own, never shown). Its button
here triggers that action, so the board asks, uninstalls and puts Hoot back as
before; a board that added nothing (a bundled add-on, an older board) shows no
Remove card."""
from __future__ import annotations

import webbrowser

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QMenu, QPushButton, QScrollArea,
                               QVBoxLayout, QWidget)

from onionwatch import REPO, __version__, theme
from onionwatch.core import feedback
from onionwatch.i18n import _
from onionwatch.ui import icons
from onionwatch.ui.panel import Flow, card, hint_label
from onionwatch.ui.watching import WatchingBody

OWL_PX = 48
ONE_COLUMN_BELOW = 640   # px of page: narrower, the Watching cards go in one column
PAGE_URL = f"https://github.com/{REPO}"
NOTES_URL = f"https://github.com/{REPO}/releases"


class BoardSettings(QScrollArea):
    """Follows `panel` (a TriggersTab). `board_menu`: the menu the board adds
    "Remove Onion Watch…" to."""

    def __init__(self, panel, board_menu: QMenu, parent=None):
        super().__init__(parent)
        self.panel = panel
        self.board_menu = board_menu
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setStyleSheet("QScrollArea { background: transparent; }")
        self.viewport().setAutoFillBackground(False)
        body = QWidget()
        body.setObjectName("boardsettings")
        body.setStyleSheet("QWidget#boardsettings { background: transparent; }")
        v = QVBoxLayout(body)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(10)

        box, bv = card()
        top = QHBoxLayout()
        top.setSpacing(14)
        self.owl = QLabel()
        self.owl.setFixedSize(OWL_PX, OWL_PX)
        self.owl.setScaledContents(True)
        top.addWidget(self.owl, 0, Qt.AlignmentFlag.AlignTop)
        words = QVBoxLayout()
        words.setSpacing(4)
        self.title = QLabel("Onion Watch")
        self.title.setStyleSheet("font-size: 15px; font-weight: 700; background: transparent;")
        self.title.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        words.addWidget(self.title)
        words.addWidget(hint_label(_("An add-on for Onion Board: it plays the board's sounds, "
                                     "and the board keeps its triggers and settings.")))
        words.addWidget(hint_label(_("Onion Watch {version} — it only looks at the screen and "
                                     "plays sounds; it never clicks, types or reads a game's "
                                     "memory.", version=__version__)))
        top.addLayout(words, 1)
        bv.addLayout(top)
        links = QWidget()
        links.setObjectName("settingslinks")
        links.setStyleSheet("QWidget#settingslinks { background: transparent; }")
        row = Flow(links, gap=8)        # onto two lines in a narrow window
        self.btn_feedback = self._link(_("Send feedback"), "edit",
                                       _("Opens a short form in your browser (no account)"),
                                       feedback.feedback_url(__version__))
        self.btn_problem = self._link(_("Report a problem"), "warn",
                                      _("Opens a new issue on GitHub in your browser"),
                                      feedback.problem_url(__version__))
        self.btn_notes = self._link(_("What's new"), "star",
                                    _("Opens the list of Onion Watch's versions and what each "
                                      "changed, on GitHub in your browser"), NOTES_URL)
        self.btn_page = self._link("GitHub", "forward",
                                   _("Opens Onion Watch's page on GitHub in your browser"),
                                   PAGE_URL)
        for b in (self.btn_feedback, self.btn_problem, self.btn_notes, self.btn_page):
            row.addWidget(b)
        bv.addWidget(links)
        v.addWidget(box)

        self.watching = WatchingBody(panel)
        v.addWidget(self.watching)

        self.remove_card, rv = card()
        line = QHBoxLayout()
        line.setSpacing(12)
        line.addWidget(hint_label(_("Uninstall the add-on from Onion Board. Your triggers are "
                                    "kept, for when you get it again.")), 1)
        self.btn_remove = QPushButton()
        icons.set_icon(self.btn_remove, "trash", "danger_text")
        self.btn_remove.clicked.connect(self._remove)
        line.addWidget(self.btn_remove)
        rv.addLayout(line)
        v.addWidget(self.remove_card)
        v.addStretch(1)
        self.setWidget(body)
        # room for the scroll bar while there is one, so it never covers the cards; none
        # without one, so the cards line up with the bars under them
        bar = self.verticalScrollBar()
        bar.rangeChanged.connect(
            lambda _lo, hi: v.setContentsMargins(0, 0, bar.sizeHint().width() + 6 if hi else 0, 0))
        self.retheme()
        self._find_remove()

    def _link(self, text: str, icon: str, tip: str, url: str) -> QPushButton:
        b = QPushButton(text)
        icons.set_icon(b, icon)
        b.setToolTip(tip)
        b.clicked.connect(lambda: webbrowser.open(url))
        return b

    def remove_action(self) -> QAction | None:
        """The board's "Remove Onion Watch…" (the last item it added), if any."""
        acts = [a for a in self.board_menu.actions() if not a.isSeparator()]
        return acts[-1] if acts else None

    def _find_remove(self):
        act = self.remove_action()
        self.remove_card.setVisible(act is not None)
        if act is not None:
            self.btn_remove.setText(act.text())
            self.btn_remove.setToolTip(act.toolTip() if act.toolTip() != act.text() else "")

    def _remove(self):
        act = self.remove_action()
        if act is not None:
            act.trigger()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.watching.set_one_column(self.viewport().width() < ONE_COLUMN_BELOW)

    def showEvent(self, e):
        super().showEvent(e)
        self._find_remove()      # the board adds it after the tab is made

    def retheme(self):
        self.owl.setPixmap(theme.themed_logo(OWL_PX * 2))
