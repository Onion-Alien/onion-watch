"""Trigger packs: triggers saved to a .zip to share or move to another PC, and read
back. A pack holds `triggers.json` and each trigger's pictures (PNGs); sounds go by
name (a sound file of yours isn't packed), so a pack from someone else plays the
sound of the same name when you have one, else the default alert.

    triggers.json   {"format": FORMAT, "version": 1, "app": "Onion Watch x.y.z",
                     "triggers": [Trigger.to_raw() with "images" as "pictures/<n>.png"
                                  and "sound_names" beside "sounds"],
                     "categories": {name: Category.full_look() with its picture
                                    and banner as "categories/<n>.png"}}
    pictures/       the PNGs
    categories/     the categories' pictures and banners

Each trigger keeps its category (Trigger.category), so a pack of a whole library
loads back sorted the way it was, each category with its colours, picture and
banner (an older version reads the triggers and skips "categories").

Reading checks everything: only these names are read, sizes are capped, and the
triggers go through Trigger.from_raw like a config does.
"""
from __future__ import annotations

import json
import zipfile
from pathlib import Path

from onionwatch import __version__, profiles
from onionwatch.screenwatch import MAX_PICTURES, Trigger

FORMAT = "onion-watch-triggers"
MAX_PACK_TRIGGERS = 500
MAX_JSON = 4 * 1024 * 1024          # bytes
MAX_PICTURE = 32 * 1024 * 1024      # bytes, one picture
MAX_TOTAL = 256 * 1024 * 1024       # bytes, all of them


class PackError(OSError):
    """The file isn't a trigger pack this version can read (the message says why)."""


def write_pack(path: str | Path, triggers: list[Trigger],
               sound_names: dict[str, str], categories=(), pictures_dir=None) -> int:
    """Save `triggers` (their pictures read from disk) as a pack; returns how many
    pictures went in. `sound_names` names the sound ids (the host's sounds).
    `categories` (profiles.Category) go in with their looks, their picture and
    banner files read from `pictures_dir`."""
    out = []
    n = 0
    cats = {}
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        k = 0
        for c in categories:
            look = c.full_look()
            if not look:
                continue
            for d, key in ((look, "image"), (look.get("banner"), "image")):
                if not isinstance(d, dict) or not d.get(key):
                    continue
                try:
                    data = (Path(pictures_dir) / d[key]).read_bytes()
                except (OSError, TypeError):
                    d[key] = ""
                    continue
                d[key] = f"categories/{k}.png"
                z.writestr(d[key], data)
                k += 1
            if isinstance(look.get("banner"), dict) and not look["banner"]["image"]:
                del look["banner"]
            cats[c.name] = look
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
             "triggers": out, "categories": cats}, indent=1))
    return n


def read_categories(path: str | Path) -> dict[str, tuple[dict, bytes, bytes]]:
    """The categories' looks in a pack: name -> (Category.full_look() without its
    file names, its picture's bytes, its banner's bytes; b"" for none). {} for a
    pack without them (an older one) or one that can't be read: its triggers still
    load (read_pack says why if not)."""
    try:
        with zipfile.ZipFile(path) as z:
            info = z.getinfo("triggers.json")
            if info.file_size > MAX_JSON:
                return {}
            d = json.loads(z.read(info).decode("utf-8-sig"))
            cats = d.get("categories") if isinstance(d, dict) else None
            if not isinstance(cats, dict):
                return {}
            names = {i.filename: i for i in z.infolist()}

            def read(name) -> bytes:
                i = names.get(name) if isinstance(name, str) else None
                if (i is None or not name.startswith("categories/") or "/" in name[11:]
                        or i.file_size > MAX_PICTURE):
                    return b""
                return z.read(i)
            out = {}
            for name, look in list(cats.items())[:profiles.MAX_CATEGORIES]:
                if not isinstance(name, str) or profiles.clean_name(name) != name \
                        or not isinstance(look, dict):
                    continue
                banner = look.get("banner") if isinstance(look.get("banner"), dict) else {}
                pic, wide = read(look.get("image")), read(banner.get("image"))
                c = profiles.Category(name)
                c.set_full_look({**look, "image": "", "banner": {**banner, "image": ""}})
                clean = c.full_look()
                if wide:
                    clean["banner"] = {"x": c.banner_x, "y": c.banner_y,
                                       "height": c.banner_height}
                out[name] = (clean, pic, wide)
            return out
    except Exception:  # noqa: BLE001 - a damaged zip fails in many ways; the triggers decide
        return {}


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
