"""A board with thousands of sounds: the trigger cards take its new list without
freezing the window. Every card's "+ Add sound" box got every sound as an item, refilled
item by item on each change of the board's sounds, and inside Onion Board each item
also had the box measured again: seconds to minutes of a frozen window."""
import time

import test_board
from test_ui import as_qimage, banner

tab = test_board.tab      # the tab Onion Board gets, on a stand-in board
SOUNDS = 3000
CARDS = 20


def test_thousands_of_sounds_reach_every_card_quickly(tab):
    panel = tab.panel
    for _i in range(CARDS):
        panel._new(as_qimage(banner()), "Queue")
    rows = list(panel.rows.values())
    for row in rows:
        row._build_body()            # every editor made, as with every card opened
    tab.host.board = [(f"s{i}", f"A sound with a longish name {i}") for i in range(SOUNDS)]
    start = time.perf_counter()
    panel.sounds_changed()
    took = time.perf_counter() - start
    for row in rows:
        assert row.sound.count() == 2          # the + and "Choose a sound file", no more
        assert len(row.sound.sounds()) == SOUNDS
    assert took < 0.5, f"{CARDS} cards took {took:.2f} s to take {SOUNDS} sounds"


def test_a_sound_picked_from_the_menu_is_added(tab):
    tab.panel._new(as_qimage(banner()), "Queue")
    row = next(iter(tab.panel.rows.values()))
    row.sound.showPopup()
    menu = row.sound.menu
    assert menu is not None and [sid for sid, _n in menu.sounds] == ["s1", "s2"]
    menu._pick("s2")
    assert "s2" in row.t.sounds and row.sound.currentIndex() == 0
