"""Plays the alert sounds on the speakers or headphones picked in Settings.

One output stream, opened the first time something plays, mixes every sound
that's playing. It's closed again once nothing has played for IDLE_CLOSE_S (an
open stream runs its callback a hundred times a second, silence or not) and opened
anew by the next sound. The audio callback never waits on anything: the UI
thread hands it a new tuple of voices (swapping the reference is atomic), and each
voice's position is only ever moved by the callback. A ringing voice (`loop`) plays
over and over until stop() or stop_all().
"""
from __future__ import annotations

import logging
import threading
import time

import numpy as np

from onionwatch.sounds import RATE

log = logging.getLogger(__name__)

GAP_S = 0.6       # silence between repeats of a ringing sound
IDLE_CLOSE_S = 30.0   # the output stream is closed after this long with nothing playing


class Voice:
    def __init__(self, data: np.ndarray, loop: bool, tag: str = ""):
        self.data = data
        self.loop = loop
        self.tag = tag              # which trigger started it (stop_tag)
        self.pos = 0
        self.gap = int(GAP_S * RATE) if loop else 0
        self.done = False

    def mix(self, out: np.ndarray, gain: float):
        n, frames = len(self.data), out.shape[0]
        i = 0
        while i < frames and not self.done:
            if self.pos < n:
                take = min(frames - i, n - self.pos)
                out[i:i + take] += self.data[self.pos:self.pos + take] * gain
                self.pos += take
                i += take
            elif self.loop:
                wait = min(frames - i, n + self.gap - self.pos)
                self.pos += wait
                i += wait
                if self.pos >= n + self.gap:
                    self.pos = 0
            else:
                self.done = True


class Player:
    def __init__(self, device: str = "", volume: float = 0.8):
        self.device = device
        self.volume = volume
        self._voices: tuple[Voice, ...] = ()
        self._stream = None
        self._lock = threading.Lock()      # the UI side only: the callback never takes it
        self.error = ""
        self.idle_close_s = IDLE_CLOSE_S
        self._idle: threading.Timer | None = None   # looks in now and then (_idle_check)
        self._busy_at = 0.0                # when something was last seen playing

    # ------------------------------------------------------------------ devices
    @staticmethod
    def devices() -> list[str]:
        """Output device names (Windows' own list, one entry per device)."""
        try:
            import sounddevice as sd
            apis = sd.query_hostapis()
            wasapi = next((i for i, a in enumerate(apis) if "WASAPI" in a["name"]), None)
            names = []
            for d in sd.query_devices():
                if d["max_output_channels"] > 0 and (wasapi is None or d["hostapi"] == wasapi):
                    if d["name"] not in names:
                        names.append(d["name"])
            return names
        except Exception:  # noqa: BLE001 - no audio at all shouldn't stop the app
            log.warning("listing output devices failed", exc_info=True)
            return []

    def set_device(self, name: str):
        if name != self.device:
            self.device = name
            with self._lock:
                self._close()

    def _device_index(self):
        if not self.device:
            return None
        import sounddevice as sd
        for i, d in enumerate(sd.query_devices()):
            if d["name"] == self.device and d["max_output_channels"] > 0:
                return i
        return None

    # ------------------------------------------------------------------ playing
    def _open(self) -> bool:
        if self._stream is not None:
            try:
                if self._stream.active:
                    return True
            except Exception:  # noqa: BLE001 - a stream whose device is gone
                pass
            # the device went away (headphones unplugged, a driver reset): the stream
            # stopped by itself, so open it again rather than ring into nothing
            log.info("the output stream stopped; opening it again")
            self._close()
        import sounddevice as sd
        for dev in ((self._device_index(), None) if self.device else (None,)):
            try:
                self._stream = sd.OutputStream(samplerate=RATE, channels=2, dtype="float32",
                                               device=dev, callback=self._callback)
                self._stream.start()
                self.error = ""
                return True
            except Exception as e:  # noqa: BLE001
                log.warning("opening output device %r failed: %s", dev, e)
                self.error = str(e)
                self._stream = None
        return False

    def _close(self):
        if self._idle is not None:
            self._idle.cancel()
            self._idle = None
        s, self._stream = self._stream, None
        if s is not None:
            try:
                s.stop()
                s.close()
            except Exception:  # noqa: BLE001
                log.debug("closing the output stream failed", exc_info=True)

    def _arm_idle(self):
        """Look again in a while whether the stream can be closed (the lock held)."""
        if self._idle is None and self._stream is not None:
            t = threading.Timer(max(0.01, self.idle_close_s / 3), self._idle_check)
            t.daemon = True
            self._idle = t
            t.start()

    def _idle_check(self):
        """On the timer's thread: close the stream once nothing has played for
        idle_close_s (a ringing sound plays until stopped, so keeps it open)."""
        with self._lock:
            self._idle = None
            if self._stream is None:
                return
            now = time.monotonic()
            if any(not v.done for v in self._voices):
                self._busy_at = now
            elif now - self._busy_at >= self.idle_close_s:
                log.debug("nothing played for %.0f s: closing the output stream",
                          now - self._busy_at)
                self._voices = ()
                self._close()
                return
            self._arm_idle()

    def _callback(self, out, frames, _time, _status):
        out.fill(0)
        gain = self.volume
        for v in self._voices:
            if not v.done:
                v.mix(out, gain)
        np.clip(out, -1.0, 1.0, out=out)

    def play(self, data: np.ndarray | None, loop: bool = False, tag: str = "") -> bool:
        """Start a sound (float32 stereo at RATE). False when there's no output."""
        if data is None or not len(data):
            return False
        with self._lock:
            if not self._open():
                return False
            self._voices = tuple(v for v in self._voices if not v.done) + (Voice(data, loop, tag),)
            self._busy_at = time.monotonic()
            self._arm_idle()
        return True

    def stop_tag(self, tag: str):
        """Stop the sounds a trigger started."""
        with self._lock:
            for v in self._voices:
                if v.tag == tag:
                    v.done = True
            self._voices = tuple(v for v in self._voices if not v.done)

    def stop_all(self):
        with self._lock:
            for v in self._voices:
                v.done = True
            self._voices = ()

    @property
    def playing(self) -> list[str]:
        """The tags of every sound playing now."""
        return [v.tag for v in self._voices if not v.done]

    @property
    def ringing(self) -> list[str]:
        """The tags of the sounds ringing (looping) now."""
        return [v.tag for v in self._voices if v.loop and not v.done]

    def close(self):
        self.stop_all()
        with self._lock:
            self._close()
