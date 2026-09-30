"""What the triggers panel needs from the program it runs in, and nothing more.

Two programs host the panel: the Onion Watch app (onionwatch.apphost) and Onion
Board, which loads it as an add-on module (onionwatch.board, packed by
scripts/build_module.py). The panel talks to its host only through `Host`; the
engine (screenwatch, windows) knows nothing about hosts at all.

API_VERSION goes up whenever this interface changes in a way the other side can't
follow. A module carries it as "api_version" in module.json: Onion Board checks it
before loading the module, and onionwatch.board.create() checks the host's in turn,
so a mismatch is refused with a message instead of a crash.
"""
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Protocol

API_VERSION = 1


class Host(Protocol):
    api_version: int          # the API_VERSION the host was written for
    name: str                 # "Onion Watch", "Onion Board": for words on screen
    # the triggers and how they're watched, as saved: on, interval_ms, monitor /
    # window (the default), triggers (screenwatch.Trigger.to_raw). Edited in place.
    screen: dict
    data_dir: Path            # the trigger pictures are kept in data_dir / "triggers"
    default_sound: str        # a new trigger's sound ("" = none until one is picked)
    audio_exts: frozenset[str]   # the sound files "Choose a sound file…" offers (".mp3"…)

    def save(self) -> None:
        """`screen` changed: save it (soon; the host may wait to gather changes)."""

    def sounds(self) -> list[tuple[str, str]]:
        """The sounds a trigger can play: (id, name), in the order to list them."""

    def add_sound(self, path: str, done: Callable[[str | None], None]) -> None:
        """Add a sound file to the host's sounds. `done(id)` once it's in sounds(),
        straight away or later (Onion Board adds files in the background);
        `done(None)` if it couldn't be added after all. OSError: refused now, with
        the reason as its message."""

    def play(self, sid: str, loop: bool = False, tag: str = "") -> bool:
        """Play a sound. `loop`: over and over until stop_tag(tag) (a ringing
        trigger). `tag` is the trigger that played it. False if it couldn't play."""

    def stop_tag(self, tag: str) -> None:
        """Stop the sounds played with `tag`."""

    def ringing(self) -> list[str]:
        """The tags of the looping sounds playing now."""

    def palette(self) -> dict[str, str]:
        """The host's theme colours now (onionwatch.theme.THEMES' keys)."""

    def notify(self, title: str, body: str) -> None:
        """A desktop notification, if the host has a way to show one (else nothing)."""


def missing(host) -> list[str]:
    """What a host lacks of `Host` (empty when it has it all)."""
    names = [n for n in Host.__annotations__] + [
        n for n, v in vars(Host).items() if callable(v) and not n.startswith("_")]
    return [n for n in names if not hasattr(host, n)]
