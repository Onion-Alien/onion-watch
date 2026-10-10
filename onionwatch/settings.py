"""Where Onion Watch keeps its things, and its settings file.

Everything lives in %APPDATA%\\OnionWatch (ONIONWATCH_HOME overrides it, for tests
and a portable copy): config.json, the log, the trigger pictures (triggers\\) and
the sound files picked for them (sounds\\). config.json is written beside itself
first and swapped in, so a crash mid-save never leaves half a file.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

log = logging.getLogger(__name__)

APP_DIR = Path(os.environ.get("ONIONWATCH_HOME")
               or Path(os.environ.get("APPDATA", Path.home())) / "OnionWatch")
CONFIG = "config.json"


def _keep_aside(path: Path):
    """A config.json that can't be used is renamed to config.json.bad (replacing an
    older one) before the defaults are saved over it, so the settings in it can
    still be got back by hand."""
    bad = path.with_name(path.name + ".bad")
    try:
        os.replace(path, bad)
    except OSError:
        log.warning("%s is damaged and couldn't be kept aside: starting from defaults",
                    path.name, exc_info=True)
        return
    log.warning("%s is damaged: kept as %s, starting from defaults", path.name, bad.name)


@dataclass
class Config:
    theme: str = "Hoot"
    # the triggers and how they're watched: on, interval_ms, monitor / window (the
    # default for triggers that don't pick their own), triggers (screenwatch.Trigger)
    screen: dict = field(default_factory=dict)
    sounds: list = field(default_factory=list)   # the sound files added: [{id, name, path}]
    device: str = ""            # output device name; "" = Windows' default
    volume: float = 0.8         # 0..1
    notify: bool = True         # a Windows notification when a trigger goes off
    tray: bool = True           # closing the window keeps watching from the tray
    geometry: str = ""          # the window's size and place (Qt's saveGeometry, hex)
    # new versions (onionwatch.updates): ask GitHub once a day; when it last did; a
    # version the user said to skip
    update_check: bool = True
    update_checked: float = 0.0
    update_skip: str = ""
    # the anonymous usage count (onionwatch.usage): its switch, this PC's random ID
    # (made on the first send), when the last daily one went, and the installer's
    # "Where did you hear about Onion Watch?" (sent once, with the first-start count)
    usage_count: bool = True
    stats_id: str = ""
    stats_sent: float = 0.0
    stats_heard: str = ""
    # ...and the daily count's picture of how it's used: when this install started
    # (age/), the first steps sent, features used and triggers gone off since the last
    # one, and problems not sent yet
    stats_started: float = 0.0
    stats_steps: list = field(default_factory=list)
    stats_used: list = field(default_factory=list)
    stats_fired: int = 0
    stats_problems: list = field(default_factory=list)
    # Settings → Look → Language: a catalog's code ("de", "pt-BR"…), or "" for Windows'
    # own. Read on its own by i18n.startup() before anything else, as the app starts
    language: str = ""

    @classmethod
    def load(cls, folder: Path | None = None) -> Config:
        path = (folder or APP_DIR) / CONFIG
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return cls()
        except ValueError:          # damaged: not JSON, or not UTF-8
            _keep_aside(path)
            return cls()
        except OSError:             # locked or unreadable for now: left where it is
            log.warning("config.json couldn't be read: starting from defaults", exc_info=True)
            return cls()
        cfg = cls()
        if not isinstance(raw, dict):
            _keep_aside(path)
            return cfg
        # settings a newer version wrote that this one doesn't know: kept, and saved
        # back as they were, so opening the same settings here loses nothing
        known = {f.name for f in fields(cls)}
        cfg._unknown = {k: v for k, v in raw.items() if k not in known}
        for f in fields(cls):
            if f.name not in raw:
                continue
            v, default = raw[f.name], getattr(cfg, f.name)
            if isinstance(default, bool):
                ok = isinstance(v, bool)
            elif isinstance(default, float):
                ok = isinstance(v, (int, float)) and not isinstance(v, bool)
            else:
                ok = isinstance(v, type(default))
            if ok:
                setattr(cfg, f.name, float(v) if isinstance(default, float) else v)
        cfg.volume = min(max(cfg.volume, 0.0), 1.0)
        # settings from before the usage count: they installed an app that sent
        # nothing, so it starts switched off for them (new installs: on, unless the
        # installer's Count me in box was unticked)
        if "usage_count" not in raw:
            cfg.usage_count = False
        return cfg

    def save(self, folder: Path | None = None):
        folder = folder or APP_DIR
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / CONFIG
        tmp = folder / (CONFIG + ".saving")
        data = {**getattr(self, "_unknown", {}), **asdict(self)}
        tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, path)
