"""The Onion Watch app as the triggers panel's host (onionwatch.host.Host): its
own settings file, sound library and player."""
from __future__ import annotations

from collections.abc import Callable

from onionwatch import settings, theme
from onionwatch.host import API_VERSION
from onionwatch.player import Player
from onionwatch.settings import Config
from onionwatch.sounds import AUDIO_EXTS, DEFAULT_SOUND, Library


class AppHost:
    api_version = API_VERSION
    name = "Onion Watch"
    default_sound = DEFAULT_SOUND
    audio_exts = frozenset(AUDIO_EXTS)

    def __init__(self, cfg: Config, save_cb: Callable[[], None], library: Library,
                 player: Player, notify: Callable[[str, str], None] | None = None):
        self.cfg, self._save, self.library, self.player = cfg, save_cb, library, player
        self._notify = notify
        if not isinstance(cfg.screen, dict):
            cfg.screen = {}

    @property
    def screen(self) -> dict:
        return self.cfg.screen

    @property
    def data_dir(self):
        return settings.APP_DIR     # read when used: tests point it elsewhere

    def save(self):
        self._save()

    def sounds(self) -> list[tuple[str, str]]:
        return self.library.listing()

    def sound_details(self, sid: str) -> str:
        """Optional card detail; older hosts can keep providing names alone."""
        return f"Volume: {self.cfg.volume:.0%} · Hotkey: none"

    def add_sound(self, path: str, done: Callable[[str | None], None]) -> None:
        done(self.library.add_file(path))    # OSError: it can't be read as a sound

    def play(self, sid: str, loop: bool = False, tag: str = "") -> bool:
        return self.player.play(self.library.load(sid), loop=loop, tag=tag)

    def stop_tag(self, tag: str):
        self.player.stop_tag(tag)

    def ringing(self) -> list[str]:
        return self.player.ringing

    def playing(self) -> list[str]:
        return self.player.playing

    def palette(self) -> dict[str, str]:
        return dict(theme.T)

    def notify(self, title: str, body: str):
        if self._notify is not None:
            self._notify(title, body)
