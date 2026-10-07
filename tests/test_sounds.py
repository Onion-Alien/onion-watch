"""The alert sounds and the player: the built-ins are made in code and aren't
silent, a sound file is copied in and decoded at 48 kHz stereo, and the player
plays once or rings until stopped (through a stand-in stream: nothing is heard)."""
import time

import numpy as np
import pytest
import soundfile as sf
from conftest import SilentOutputStream

from onionwatch import sounds
from onionwatch.player import GAP_S, Player, Voice
from onionwatch.sounds import BUILTINS, RATE, Library


def test_every_built_in_sound_is_stereo_and_audible_but_not_clipping():
    lib = Library([])
    for sid in BUILTINS:
        data = lib.load(sid)
        assert data.dtype == np.float32 and data.ndim == 2 and data.shape[1] == 2
        assert 0.3 < float(np.abs(data).max()) <= 0.71, sid
        assert 0.1 < len(data) / RATE < 5, sid


def test_a_sound_file_is_copied_in_and_resampled(app_dir, tmp_path):
    src = tmp_path / "in" / "Ding.wav"
    src.parent.mkdir()
    t = np.arange(22050) / 22050
    sf.write(src, (0.5 * np.sin(2 * np.pi * 440 * t)).astype(np.float32), 22050)
    saved = []
    lib = Library([], lambda: saved.append(1))
    sid = lib.add_file(src)
    assert saved and (sid, "Ding") in lib.listing()
    src.unlink()                                   # the original can go: it was copied
    data = lib.load(sid)
    assert data.shape == (RATE, 2)                 # one second at 48 kHz, stereo
    assert abs(float(np.abs(data).max()) - 0.5) < 0.02
    lib.remove(sid)
    assert sid not in lib.ids() and not (sounds.sounds_dir() / f"{sid}.wav").exists()


def test_a_file_that_is_not_a_sound_is_refused(app_dir, tmp_path):
    bad = tmp_path / "notes.wav"
    bad.write_text("not audio")
    with pytest.raises(OSError):
        Library([]).add_file(bad)


def test_a_library_drops_broken_entries():
    entries = [{"id": "a", "name": "A", "path": "x.wav"}, {"id": 3}, "junk"]
    lib = Library(entries)
    assert entries == [{"id": "a", "name": "A", "path": "x.wav"}]
    assert lib.name("a") == "A" and lib.name("gone") == "Removed sound"


def test_a_voice_plays_once_or_rings_with_a_gap():
    data = np.ones((100, 2), np.float32)
    once = Voice(data, loop=False)
    out = np.zeros((250, 2), np.float32)
    once.mix(out, 0.5)
    assert out[:100].min() == 0.5 and out[100:].max() == 0 and once.done
    ring = Voice(data, loop=True)
    gap = int(GAP_S * RATE)
    out = np.zeros((100 + gap + 50, 2), np.float32)
    ring.mix(out, 1.0)
    assert out[:100].min() == 1 and out[100:100 + gap].max() == 0 and out[-50:].min() == 1
    assert not ring.done


def test_the_player_rings_until_stopped():
    SilentOutputStream.opened.clear()
    p = Player()
    tone = np.full((480, 2), 0.25, np.float32)
    assert p.play(tone, loop=True, tag="t1")
    stream = SilentOutputStream.opened[-1]
    end = time.monotonic() + 3
    while stream.peak < 0.2 and time.monotonic() < end:
        time.sleep(0.01)
    assert stream.peak == pytest.approx(0.25 * p.volume, abs=1e-6)
    assert p.ringing == ["t1"]
    p.stop_tag("t1")
    assert p.ringing == []
    p.play(tone, loop=True, tag="a")
    p.play(tone, loop=False, tag="b")
    assert p.ringing == ["a"]
    p.stop_all()
    assert p.ringing == []
    p.close()


def test_the_player_opens_its_output_again_after_the_device_goes():
    """Headphones unplugged: the stream stops by itself. The next alarm must open a
    new one, not ring into the dead one."""
    SilentOutputStream.opened.clear()
    p = Player()
    tone = np.full((480, 2), 0.25, np.float32)
    assert p.play(tone, tag="a")
    first = SilentOutputStream.opened[-1]
    assert p.play(tone, tag="b") and SilentOutputStream.opened[-1] is first   # kept
    first.stop()                                   # the device went away
    assert p.play(tone, tag="c")
    assert SilentOutputStream.opened[-1] is not first and SilentOutputStream.opened[-1].active
    p.close()


def _wait(cond, timeout=3.0):
    end = time.monotonic() + timeout
    while not cond() and time.monotonic() < end:
        time.sleep(0.01)
    return cond()


def test_the_player_closes_its_output_after_a_while_of_silence_and_opens_it_again():
    """An open stream runs its callback a hundred times a second, sound or not: it's
    closed once nothing has played for idle_close_s, and the next alert opens it
    again and is heard."""
    SilentOutputStream.opened.clear()
    p = Player()
    p.idle_close_s = 0.3
    tone = np.full((480, 2), 0.25, np.float32)          # 10 ms
    assert p.play(tone, tag="a")
    first = SilentOutputStream.opened[-1]
    assert _wait(lambda: p._stream is None)
    assert not first.active
    blocks = first.blocks
    time.sleep(0.1)
    assert first.blocks == blocks                       # no callbacks once closed
    assert p.play(tone, tag="b")                        # the next alert
    second = SilentOutputStream.opened[-1]
    assert second is not first and second.active
    assert _wait(lambda: second.peak > 0.1)             # ...is heard
    p.close()


def test_a_ringing_sound_keeps_the_output_open():
    SilentOutputStream.opened.clear()
    p = Player()
    p.idle_close_s = 0.15
    assert p.play(np.full((480, 2), 0.25, np.float32), loop=True, tag="r")
    stream = SilentOutputStream.opened[-1]
    time.sleep(0.6)
    assert p._stream is stream and stream.active and p.ringing == ["r"]
    p.stop_all()
    assert _wait(lambda: p._stream is None)             # silent from then on: closed
    p.close()


def test_decoded_sounds_kept_are_bounded_and_the_latest_played_stay(app_dir, tmp_path,
                                                                    monkeypatch):
    monkeypatch.setattr(sounds, "CACHE_MB", 1.2)        # ~3.3 s of 48 kHz stereo
    lib = Library([])
    ids = []
    for i in range(4):                                  # 1 s each: 0.37 MB decoded
        src = tmp_path / f"s{i}.wav"
        sf.write(src, np.full((RATE, 2), 0.1 * (i + 1), np.float32), RATE)
        ids.append(lib.add_file(src))
    for sid in ids[:3]:
        lib.load(sid)
    lib.load(ids[0])                                    # played again: kept
    lib.load(ids[3])                                    # no room for four: the oldest goes
    assert list(lib._cache) == [ids[2], ids[0], ids[3]]
    assert sum(a.nbytes for a in lib._cache.values()) <= 1.2 * 2 ** 20
    again = lib.load(ids[1])                            # decoded again when wanted
    assert again is not None and float(again[0, 0]) == pytest.approx(0.2)


@pytest.mark.parametrize("rate", [22050, 44100, 96000])
def test_resampling_gives_what_scipy_did(tmp_path, rate):
    # decode() resamples with soxr now; it should give what scipy's resample_poly gave,
    # sample for sample, but for the two filters' slightly different edges
    signal = pytest.importorskip("scipy.signal")
    t = np.arange(rate) / rate
    tone = np.stack([0.4 * np.sin(2 * np.pi * 440 * t) + 0.1 * np.sin(2 * np.pi * 3000 * t),
                     0.3 * np.sin(2 * np.pi * 660 * t)], axis=1).astype(np.float32)
    src = tmp_path / f"tone{rate}.wav"
    sf.write(src, tone, rate, subtype="FLOAT")
    got = sounds.decode(src)
    g = np.gcd(rate, RATE)
    want = signal.resample_poly(tone, RATE // g, rate // g, axis=0).astype(np.float32)
    assert got.dtype == np.float32 and got.flags.c_contiguous
    assert got.shape == want.shape == (RATE, 2)
    edge = RATE // 50
    np.testing.assert_allclose(got[edge:-edge], want[edge:-edge], rtol=0, atol=1e-3)
