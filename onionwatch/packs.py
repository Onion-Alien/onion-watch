"""Trigger packs: triggers saved to a .zip to share or move to another PC, and read
back. A pack holds `triggers.json` and each trigger's pictures (PNGs); sounds go by
name (a sound file of yours isn't packed), so a pack from someone else plays the
sound of the same name when you have one, else the default alert.

    triggers.json   {"format": FORMAT, "version": 1, "app": "Onion Watch x.y.z",
                     "triggers": [Trigger.to_raw() with "images" as "pictures/<n>.png"
                                  and "sound_names" beside "sounds"]}
    pictures/       the PNGs

Each trigger keeps its category (Trigger.category), so a pack of a whole library
loads back sorted the way it was.

Reading checks everything: only these names are read, sizes are capped, and the
triggers go through Trigger.from_raw like a config does.
"""
from __future__ import annotations

import json
import zipfile
from pathlib import Path

from onionwatch import __version__
from onionwatch.screenwatch import MAX_PICTURES, Trigger

FORMAT = "onion-watch-triggers"
MAX_PACK_TRIGGERS = 500
MAX_JSON = 4 * 1024 * 1024          # bytes
MAX_PICTURE = 32 * 1024 * 1024      # bytes, one picture
MAX_TOTAL = 256 * 1024 * 1024       # bytes, all of them


class PackError(OSError):
    """The file isn't a trigger pack this version can read (the message says why)."""


def write_pack(path: str | Path, triggers: list[Trigger],
               sound_names: dict[str, str]) -> int:
    """Save `triggers` (their pictures read from disk) as a pack; returns how many
    pictures went in. `sound_names` names the sound ids (the host's sounds)."""
    out = []
    n = 0
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for t in triggers[:MAX_PACK_TRIGGERS]:
            raw = t.to_raw()
            pics = []
            for img in t.images:
                try:
                    data = Path(img).read_bytes()
                except OSError:
                    continue            # a picture that's gone: left out
                name = f"pictures/{n}.png"
                z.writestr(name, data)
                pics.append(name)
                n += 1
            raw["images"], raw["image"] = pics, pics[0] if pics else ""
            raw["sound_names"] = [sound_names.get(sid, "") for sid in t.sounds]
            raw["pending"] = ""
            out.append(raw)
        z.writestr("triggers.json", json.dumps(
            {"format": FORMAT, "version": 1, "app": f"Onion Watch {__version__}",
             "triggers": out}, indent=1))
    return n


def read_pack(path: str | Path) -> list[tuple[Trigger, list[bytes], list[tuple[str, str]]]]:
    """The triggers in a pack: (trigger, its pictures' PNG bytes, its sounds as (id, name)),
    each trigger with its saved ids for sounds and a placeholder for pictures (the
    caller gives it a new id and keeps the pictures). PackError if it can't be read."""
    try:
        return _read_pack(path)
    except PackError:
        raise
    except Exception as e:  # noqa: BLE001 - a damaged zip fails in many ways (CRC, zlib, encrypted, recursion)
        raise PackError(f"it's damaged ({e or type(e).__name__})") from e


def _read_pack(path):
    try:
        z = zipfile.ZipFile(path)
    except (OSError, zipfile.BadZipFile) as e:
        raise PackError(f"it isn't a trigger pack ({e})") from e
    with z:
        try:
            info = z.getinfo("triggers.json")
        except KeyError as e:
            raise PackError("it isn't a trigger pack (no triggers.json)") from e
        if info.file_size > MAX_JSON:
            raise PackError("its triggers.json is too big")
        try:
            d = json.loads(z.read(info).decode("utf-8-sig"))
        except (ValueError, UnicodeDecodeError) as e:
            raise PackError(f"its triggers.json can't be read ({e})") from e
        if not isinstance(d, dict) or d.get("format") != FORMAT:
            raise PackError("it isn't an Onion Watch trigger pack")
        raws = d.get("triggers")
        if not isinstance(raws, list):
            raise PackError("it has no triggers")
        names = {i.filename: i for i in z.infolist()}
        total = 0
        found = []
        for raw in raws[:MAX_PACK_TRIGGERS]:
            if not isinstance(raw, dict):
                continue
            t = Trigger.from_raw({**raw, "id": "imported"})
            if t is None:
                continue
            pics = []
            for name in t.images[:MAX_PICTURES]:
                i = names.get(name)
                if (i is None or not name.startswith("pictures/") or "/" in name[9:]
                        or i.file_size > MAX_PICTURE or total + i.file_size > MAX_TOTAL):
                    continue
                total += i.file_size
                pics.append(z.read(i))
            sids, sn = raw.get("sounds"), raw.get("sound_names")
            pairs = list(zip(sids, sn)) if isinstance(sids, list) and isinstance(sn, list) \
                else []
            found.append((t, pics, [(a, b) for a, b in pairs
                                    if isinstance(a, str) and isinstance(b, str)]))
        return found
