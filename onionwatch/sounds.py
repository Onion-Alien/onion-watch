"""The sounds a trigger can play: a few alert sounds made in code (no audio files
ship with the app), plus sound files the user adds, which are copied into
%APPDATA%\\OnionWatch\\sounds so moving or deleting the original doesn't break a
trigger.

Everything is decoded to float32 stereo at RATE and kept in memory once loaded,
so a trigger fires with no disk access: up to CACHE_MB of them, the sounds played
longest ago making room (a long file is up to ~46 MB decoded).
"""
from __future__ import annotations

import logging
import math
import shutil
import uuid
from pathlib import Path

import numpy as np

from onionwatch import settings
from onionwatch.i18n import _

log = logging.getLogger(__name__)

RATE = 48000
AUDIO_EXTS = {".wav", ".mp3", ".ogg", ".flac", ".aiff", ".aif", ".opus"}
MAX_SECONDS = 120           # longer files are cut to this (an alarm, not a playlist)
CACHE_MB = 64               # decoded sounds kept in memory (Library.load), at most
BUILTIN_PREFIX = "builtin:"


# --------------------------------------------------------------------------- built-ins

def _t(seconds: float) -> np.ndarray:
    return np.arange(int(seconds * RATE), dtype=np.float64) / RATE


def _env(n: int, attack: float = 0.005, decay: float = 6.0) -> np.ndarray:
    t = np.arange(n) / RATE
    return np.minimum(t / attack, 1.0) * np.exp(-decay * t)


def _note(freq: float, seconds: float, decay: float = 6.0, partials=((1, 1.0),)) -> np.ndarray:
    t = _t(seconds)
    y = sum(a * np.sin(2 * math.pi * freq * k * t) for k, a in partials)
    return y * _env(len(t), decay=decay)


def _place(total: float, parts: list[tuple[float, np.ndarray]]) -> np.ndarray:
    out = np.zeros(int(total * RATE))
    for at, y in parts:
        i = int(at * RATE)
        n = min(len(y), len(out) - i)
        out[i:i + n] += y[:n]
    return out


def _chime() -> np.ndarray:
    bell = ((1, 1.0), (2, 0.35), (3, 0.12))
    return _place(1.4, [(0.0, _note(1318.5, 1.2, 4.0, bell)),     # E6
                        (0.16, _note(1760.0, 1.2, 3.5, bell))])   # A6


def _ping() -> np.ndarray:
    return _note(1975.5, 0.6, 9.0, ((1, 1.0), (2.76, 0.2)))


def _alarm() -> np.ndarray:
    """Three pairs of hard beeps: hard to sleep through."""
    t = _t(0.12)
    beep = np.sign(np.sin(2 * math.pi * 988 * t)) * 0.5 + np.sin(2 * math.pi * 1976 * t) * 0.3
    beep *= np.minimum(1.0, np.minimum(t, t[-1] - t) / 0.004)
    parts = []
    for i in range(3):
        parts += [(i * 0.5, beep), (i * 0.5 + 0.17, beep)]
    return _place(1.5, parts)


def _bell() -> np.ndarray:
    """A small church-like bell: inharmonic partials with a long ring."""
    partials = ((0.5, 0.5), (1.0, 1.0), (1.19, 0.6), (1.56, 0.4), (2.0, 0.35), (2.51, 0.25),
                (3.01, 0.15))
    return _note(660.0, 2.5, 1.8, partials)


def _rising() -> np.ndarray:
    """A quick three-note rising arpeggio: "something's ready"."""
    tone = ((1, 1.0), (2, 0.25))
    return _place(0.9, [(0.0, _note(784.0, 0.5, 8.0, tone)),       # G5
                        (0.1, _note(987.8, 0.5, 8.0, tone)),       # B5
                        (0.2, _note(1174.7, 0.7, 5.0, tone))])     # D6


BUILTINS: dict[str, tuple[str, object]] = {
    "builtin:chime": (_("Chime"), _chime),
    "builtin:ping": (_("Ping"), _ping),
    "builtin:rising": (_("Ready"), _rising),
    "builtin:bell": (_("Bell"), _bell),
    "builtin:alarm": (_("Alarm"), _alarm),
}
DEFAULT_SOUND = "builtin:chime"


def _stereo(mono: np.ndarray, peak: float = 0.7) -> np.ndarray:
    m = float(np.abs(mono).max()) or 1.0
    y = (mono * (peak / m)).astype(np.float32)
    return np.column_stack([y, y])


# --------------------------------------------------------------------------- files

def sounds_dir() -> Path:
    return settings.APP_DIR / "sounds"


def decode(path: str | Path) -> np.ndarray:
    """A sound file as float32 stereo at RATE (at most MAX_SECONDS). OSError if it
    can't be read."""
    import soundfile as sf
    try:
        data, rate = sf.read(str(path), dtype="float32", always_2d=True,
                             frames=-1)
    except Exception as e:  # noqa: BLE001 - libsndfile raises its own types
        raise OSError(_("{name} couldn't be read as a sound ({error})",
                       name=Path(path).name, error=e)) from e
    if data.size == 0:
        raise OSError(_("{name} has no sound in it", name=Path(path).name))
    data = data[: int(MAX_SECONDS * rate)]
    if data.shape[1] == 1:
        data = np.repeat(data, 2, axis=1)
    elif data.shape[1] > 2:
        data = data[:, :2]
    if rate != RATE:
        import soxr
        data = soxr.resample(data, rate, RATE, quality="VHQ")
    return np.ascontiguousarray(data, dtype=np.float32)


class Library:
    """The sounds on offer: the built-ins, then the added files (Config.sounds, which
    this edits in place). `cb_save()` is called after a change."""

    def __init__(self, entries: list, save_cb=None):
        self.entries = entries
        self._save = save_cb or (lambda: None)
        self._cache: dict[str, np.ndarray] = {}     # the one played longest ago first
        clean = [e for e in entries if isinstance(e, dict) and isinstance(e.get("id"), str)
                 and isinstance(e.get("name"), str) and isinstance(e.get("path"), str)]
        entries[:] = clean

    def listing(self) -> list[tuple[str, str]]:
        """(id, name) of every sound: built-ins first."""
        return ([(sid, name) for sid, (name, _f) in BUILTINS.items()]
                + [(e["id"], e["name"]) for e in self.entries])

    def ids(self) -> set[str]:
        return set(BUILTINS) | {e["id"] for e in self.entries}

    def name(self, sid: str) -> str:
        if sid in BUILTINS:
            return BUILTINS[sid][0]
        return next((e["name"] for e in self.entries if e["id"] == sid),
                    _("Removed sound"))

    def add_file(self, path: str | Path) -> str:
        """Copy a sound file in and list it; returns its id. A file already added (the
        same name and size) gives the id it already has. OSError if it can't be read."""
        src = Path(path)
        decode(src)                                  # refuse it now if it can't be played
        size = src.stat().st_size
        for e in self.entries:
            p = Path(e["path"])
            if e["name"] == src.stem and p.exists() and p.stat().st_size == size:
                return e["id"]
        sid = uuid.uuid4().hex[:12]
        folder = sounds_dir()
        folder.mkdir(parents=True, exist_ok=True)
        dest = folder / f"{sid}{src.suffix.lower()}"
        shutil.copyfile(src, dest)
        self.entries.append({"id": sid, "name": src.stem[:60], "path": str(dest)})
        self._save()
        return sid

    def remove(self, sid: str):
        e = next((e for e in self.entries if e["id"] == sid), None)
        if e is None:
            return
        self.entries.remove(e)
        self._cache.pop(sid, None)
        p = Path(e["path"])
        if p.parent == sounds_dir():
            p.unlink(missing_ok=True)
        self._save()

    def load(self, sid: str) -> np.ndarray | None:
        """The sound's samples (float32 stereo at RATE), or None if it's gone."""
        data = self._cache.pop(sid, None)
        if data is not None:
            self._cache[sid] = data             # played now: the last to make room
            return data
        if sid in BUILTINS:
            data = _stereo(BUILTINS[sid][1]())
        else:
            e = next((e for e in self.entries if e["id"] == sid), None)
            if e is None:
                return None
            try:
                data = decode(e["path"])
            except OSError:
                log.warning("sound %s couldn't be loaded", e["name"], exc_info=True)
                return None
        self._cache[sid] = data
        room = CACHE_MB * 2 ** 20
        while len(self._cache) > 1 and sum(a.nbytes for a in self._cache.values()) > room:
            del self._cache[next(iter(self._cache))]
        return data
