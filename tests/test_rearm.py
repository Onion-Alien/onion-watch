"""A trigger whose picture never left the screen still goes off again when you ask
for it: by starting to watch again, or by changing what the trigger looks for."""
import time

from test_modes import GAME1, banner, run_until, scene, showing, watcher, ws  # noqa: F401

from onionwatch.engine.screenwatch import Watched


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
    time.sleep(0.1)
    assert len(fired) == 1                  # it stays up: once, as before
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
