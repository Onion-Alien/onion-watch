"""A trigger whose picture never left the screen still goes off again when you ask
for it: by starting to watch again, or by changing what the trigger looks for."""
import time

from test_modes import GAME1, banner, run_until, scene, showing, watcher, ws  # noqa: F401

from onionwatch.engine.screenwatch import Gate, Watched


PICTURE = (banner(), None)


def _item(**kw):
    kw = {"sources": [GAME1], **kw}
    threshold = kw.pop("threshold", 0.8)
    cooldown = kw.pop("cooldown", 0.0)
    return Watched("t", [PICTURE], threshold, cooldown, **kw)


def _fired_once(ws, fired, **item):  # noqa: F811
    ws.open = {GAME1: showing(scene(1))}
    w = watcher(ws, fired)
    w.set_items([_item(**item)])
    w.start()
    assert run_until(lambda: len(fired) == 1)
    if not item.get("replay"):
        time.sleep(0.1)
        assert len(fired) == 1              # it stays up: once, as before
    return w


def test_stopping_and_starting_again_goes_off_again(ws):  # noqa: F811
    fired = []
    w = _fired_once(ws, fired)
    try:
        w.stop()
        w.start()
        assert run_until(lambda: len(fired) == 2)
    finally:
        w.stop()


def test_changing_the_match_goes_off_again(ws):  # noqa: F811
    fired = []
    w = _fired_once(ws, fired)
    try:
        w.set_items([_item(threshold=0.7)])
        assert run_until(lambda: len(fired) == 2)
    finally:
        w.stop()


def test_saving_the_trigger_unchanged_does_not_go_off_again(ws):  # noqa: F811
    fired = []
    w = _fired_once(ws, fired)
    try:
        w.set_items([_item()])
        time.sleep(0.15)
        assert len(fired) == 1
    finally:
        w.stop()


def test_the_rest_still_holds_then_it_goes_off(ws):  # noqa: F811
    fired = []
    w = _fired_once(ws, fired, cooldown=1.0)
    try:
        w.set_items([_item(threshold=0.7, cooldown=1.0)])
        time.sleep(0.2)
        assert len(fired) == 1              # still resting
        assert run_until(lambda: len(fired) == 2)
        time.sleep(1.2)
        assert len(fired) == 2              # it stayed up: once more, not over and over
    finally:
        w.stop()


def test_goes_away_trigger_restarted_waits_to_see_it_first(ws):  # noqa: F811
    fired = []
    ws.open = {GAME1: showing(scene(1))}
    w = watcher(ws, fired)
    w.set_items([_item(mode="vanish")])
    w.start()
    try:
        assert run_until(lambda: w.scores.get("t", 0) > 0.9)
        w.stop()
        ws.open[GAME1] = scene(1)           # gone while nobody was watching
        w.start()
        time.sleep(0.15)
        assert not fired                    # it wasn't seen go, so it can't say it went
        ws.open[GAME1] = showing(scene(1))
        assert run_until(lambda: w.scores.get("t", 0) > 0.9)
        ws.open[GAME1] = scene(1)
        assert run_until(lambda: len(fired) == 1)
    finally:
        w.stop()

def test_a_picture_that_stays_up_replays_after_each_rest(ws):  # noqa: F811
    fired = []
    w = _fired_once(ws, fired, cooldown=0.4, replay=True)
    try:
        assert run_until(lambda: len(fired) == 3)
        ws.open[GAME1] = scene(1)           # gone: quiet
        time.sleep(0.1)
        n = len(fired)
        time.sleep(0.6)
        assert len(fired) == n
    finally:
        w.stop()


def test_no_rest_or_no_replay_plays_once(ws):  # noqa: F811
    fired = []
    w = _fired_once(ws, fired, cooldown=0.0, replay=True)
    try:
        time.sleep(0.3)
        assert len(fired) == 1
    finally:
        w.stop()
    fired.clear()
    w = _fired_once(ws, fired, cooldown=0.1, replay=False)
    try:
        time.sleep(0.4)
        assert len(fired) == 1
    finally:
        w.stop()


def test_a_hit_says_whether_the_picture_ever_left(ws):  # noqa: F811
    fired = []
    w = _fired_once(ws, fired, cooldown=0.1, replay=True)
    try:
        assert run_until(lambda: len(fired) >= 2)
        assert not fired[0][1].replay               # new
        assert fired[1][1].replay                   # it never left
        ws.open[GAME1] = scene(1)
        assert run_until(lambda: w.scores.get("t", 1) < 0.5)
        n = len(fired)
        ws.open[GAME1] = showing(scene(1))
        assert run_until(lambda: len(fired) > n)
        assert not fired[n][1].replay               # gone and back: new again
        w.stop()
        n = len(fired)
        w.start()
        assert run_until(lambda: len(fired) > n)
        assert not fired[n][1].replay               # started watching again: new too
    finally:
        w.stop()


def test_a_replay_that_was_not_played_does_not_hold_up_something_new():
    g = Gate()
    assert g.step(True, 0.0, 3.0, again=True)            # plays
    assert not g.step(True, 2.9, 3.0, again=True)        # resting
    assert g.step(True, 3.0, 3.0, again=True)            # a replay...
    g.skipped()                                          # ...the sound hadn't ended
    assert not g.step(True, 3.1, 3.0, again=True)        # the next replay still waits
    g.step(False, 3.5, 3.0, again=True)                  # gone
    assert g.step(True, 4.0, 3.0, again=True)            # back: 4 s since it was last heard


def test_a_replay_that_played_still_rests():
    g = Gate()
    assert g.step(True, 0.0, 3.0, again=True)
    assert g.step(True, 3.0, 3.0, again=True)            # a replay, and it played
    g.step(False, 3.5, 3.0, again=True)                  # gone
    assert not g.step(True, 4.0, 3.0, again=True)        # back, but only 1 s after it played
    assert g.step(True, 6.0, 3.0, again=True)
