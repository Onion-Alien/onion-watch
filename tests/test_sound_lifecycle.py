"""Nothing a trigger plays outlives what started it: a sound checked on its card
stops when it's taken off the card, a test stops when the trigger is deleted, a
ring stops when Ring is unticked, the trigger switched off, its sound removed or
watching switched off. Clicking a sound again starts it over, not on top. The
real player, on a silent output."""
import pytest
import test_ui
from test_ui import as_qimage, banner

fake_screen, tab = test_ui.fake_screen, test_ui.tab   # the same stand-ins

ALARM, BELL = "builtin:alarm", "builtin:bell"


def playing(tab) -> list[str]:
    return sorted(v.tag for v in tab.host.player._voices if not v.done)


@pytest.fixture
def card(tab):
    tab._new(_banner(), "Queue")
    row = next(iter(tab.rows.values()))
    row.t.sounds = [ALARM, BELL]
    row.set_sounds(tab.host.sounds())
    return row


def _banner():
    return as_qimage(banner())


def test_a_sound_checked_on_a_card_stops_when_it_is_taken_off(tab, card):
    tid = card.t.id
    card.hear.emit(ALARM)
    card.hear.emit(BELL)
    assert playing(tab) == [f"hear:{tid}/{ALARM}", f"hear:{tid}/{BELL}"]
    card._remove_sound(ALARM)
    assert playing(tab) == [f"hear:{tid}/{BELL}"]          # only that one stops


def test_clicking_a_sound_again_starts_it_over(tab, card):
    card.hear.emit(ALARM)
    card.hear.emit(ALARM)
    assert len(playing(tab)) == 1


def test_a_test_stops_when_the_trigger_is_deleted(tab, card):
    card.t.pick = "all"
    card.btn_test.click()
    card.btn_test.click()                                  # again: over, not on top
    assert playing(tab) == [f"{card.t.id}/{ALARM}", f"{card.t.id}/{BELL}"]
    tab._remove(card)
    assert playing(tab) == []


def ring(tab, card):
    card.chk_ring.setChecked(True)
    card.until.setCurrentIndex(card.until.findData("manual"))
    tab._fire(card.t.id, tab._gen)
    assert tab.host.ringing() == [card.t.id]


def test_unticking_ring_stops_the_ring(tab, card):
    ring(tab, card)
    card.chk_ring.setChecked(False)
    assert tab.host.ringing() == []


def test_switching_a_trigger_off_stops_it(tab, card):
    ring(tab, card)
    card.hear.emit(BELL)
    card._on_enabled(False)
    assert tab.host.ringing() == [] and playing(tab) == []


def test_taking_the_ringing_sound_off_stops_the_ring(tab, card):
    ring(tab, card)
    rung = tab._ring_sounds[card.t.id]
    for sid in rung:
        card._remove_sound(sid)
    assert tab.host.ringing() == []


def test_a_new_until_applies_to_the_ring_going_now(tab, card):
    ring(tab, card)
    from onionwatch import screenwatch as sw
    tab._hits[card.t.id] = sw.Hit(0, (0, 0, 1, 1), 0.9)
    card.until.setCurrentIndex(card.until.findData("gone"))
    assert tab.host.ringing() == [card.t.id]               # still ringing...
    assert tab.watcher._quiet[card.t.id].how == "gone"     # ...until it's gone


def test_switching_watching_off_stops_the_ring(tab, card):
    tab.set_watching(True)
    ring(tab, card)
    tab.set_watching(False)
    assert tab.host.ringing() == []


def test_a_sound_gone_from_the_library_stops(tab, card, monkeypatch):
    card.hear.emit(BELL)
    sounds = [s for s in tab.host.sounds() if s[0] != BELL]
    monkeypatch.setattr(tab.host, "sounds", lambda: sounds)
    tab.sounds_changed()
    assert playing(tab) == []
