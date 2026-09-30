"""Plays the alert sounds on the speakers or headphones picked in Settings.

One output stream, opened the first time something plays and kept open, mixes
every sound that's playing. The audio callback never waits on anything: the UI
thread hands it a new tuple of voices (swapping the reference is atomic), and each
voice's position is only ever moved by the callback. A ringing voice (`loop`) plays
over and over until stop() or stop_all().
"""
from __future__ import annotations

import logging
import threading

import numpy as np

from onionwatch.sounds import RATE

log = logging.getLogger(__name__)

GAP_S = 0.6       # silence between repeats of a ringing sound


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
            return True
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
        s, self._stream = self._stream, None
        if s is not None:
            try:
                s.stop()
                s.close()
            except Exception:  # noqa: BLE001
                log.debug("closing the output stream failed", exc_info=True)

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
    def ringing(self) -> list[str]:
        """The tags of the sounds ringing (looping) now."""
        return [v.tag for v in self._voices if v.loop and not v.done]

    def close(self):
        self.stop_all()
        self._close()
