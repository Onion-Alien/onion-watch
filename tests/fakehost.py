"""A host for the triggers panel that is nothing but onionwatch.host.Host: what
Onion Board looks like from the panel's side. It records what the panel asks of
it and never makes a sound."""
from __future__ import annotations

from pathlib import Path

from onionwatch.host import API_VERSION


class FakeHost:
    api_version = API_VERSION
    name = "Test Board"
    default_sound = ""
    audio_exts = frozenset({".wav", ".mp3", ".m4a"})

    def __init__(self, data_dir: Path, screen: dict | None = None):
        self.data_dir = data_dir
        self.screen = screen if screen is not None else {}
        self.board = [("s1", "Airhorn"), ("s2", "Bruh")]
        self.saves = 0
        self.played: list[tuple[str, bool, str]] = []    # (id, loop, tag)
        self.looping: list[tuple[str, str]] = []          # (id, tag) ringing now
        self.adding: list[tuple[str, object]] = []        # (path, done) not finished yet
        self.refuse = ""                                  # add_sound raises this
        self.notes: list[tuple[str, str]] = []
        self.colours = {"accent": "#123456"}

    def save(self):
        self.saves += 1

    def sounds(self):
        return list(self.board)

    def add_sound(self, path, done):
        if self.refuse:
            raise OSError(self.refuse)
        self.adding.append((path, done))       # the board adds files in the background

    def finish_adding(self, sid: str | None, name: str = "New sound"):
        path, done = self.adding.pop(0)
        if sid:
            self.board.append((sid, name))
        done(sid)

    def play(self, sid, loop=False, tag=""):
        if sid not in dict(self.board):
            return False
        self.played.append((sid, loop, tag))
        if loop:
            self.looping.append((sid, tag))
        return True

    def stop_tag(self, tag):
        self.looping = [(s, t) for s, t in self.looping if t != tag]

    def ringing(self):
        return [t for _s, t in self.looping]

    def palette(self):
        return dict(self.colours)

    def notify(self, title, body):
        self.notes.append((title, body))
