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
