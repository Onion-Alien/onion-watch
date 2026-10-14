"""Which style kit draws Hoot: Onion Watch's own copy (onionwatch/style), or, inside
Onion Board, the board's (its optional host.kit()) when that's at least as new
(KIT_VERSION). The board's kit paints in the board's theme and outfits, so Hoot in the
Triggers tab matches Bun even when this add-on is older than the board.
"""
from __future__ import annotations

import importlib

from onionwatch import style as _own
from onionwatch.style import owl as _own_owl   # (a plain import: the module build packs it)

_kit = _own


def use_host(host) -> None:
    """Draw with `host`'s kit if it has one at least as new as ours, else our own."""
    global _kit
    try:
        theirs = host.kit() if hasattr(host, "kit") else None
    except Exception:  # noqa: BLE001 - a host's bug mustn't stop the tab
        theirs = None
    ok = theirs is not None and getattr(theirs, "KIT_VERSION", 0) >= _own.KIT_VERSION
    _kit = theirs if ok else _own


def use_own() -> None:
    global _kit
    _kit = _own


def name() -> str:
    """The kit in use's package name ("onionwatch.style" or the board's)."""
    return _kit.__name__


def owl():
    """The owl module of the kit in use (OwlWidget, draw_owl, owl_image)."""
    if _kit is _own:
        return _own_owl
    return importlib.import_module(f"{_kit.__name__}.owl")
