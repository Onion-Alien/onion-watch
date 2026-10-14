"""The style kit (onionwatch/style): an exact copy of Onion Board's soundboard/style, made
by scripts/sync_style.py. Never edited here; it follows Onion Watch's theme on its
own and Onion Board's inside the board."""
import ast
import json
import sys
import types
from pathlib import Path

from onionwatch import kit, theme
from onionwatch.style import KIT_VERSION, bunnyfit, palettes

STYLE = Path(__file__).resolve().parent.parent / "onionwatch" / "style"


def test_the_copy_is_exactly_what_was_synced():
    sys.path.insert(0, str(STYLE.parent.parent / "scripts"))
    try:
        from sync_style import digest
    finally:
        sys.path.pop(0)
    stamp = json.loads((STYLE / "SOURCE.json").read_text(encoding="utf-8"))
    assert stamp["from"] == "Onion Board" and len(stamp["commit"]) == 40
    assert sorted(p.name for p in STYLE.glob("*.py")) == sorted(stamp["files"])
    for name, want in stamp["files"].items():
        assert digest((STYLE / name).read_bytes()) == want, (
            f"onionwatch/style/{name} was edited here: change it in Onion Board and run "
            "scripts/sync_style.py")


def test_kit_imports_nothing_from_the_app():
    allowed = set(sys.stdlib_module_names) | {"PySide6", "__future__"}
    for path in STYLE.glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and not node.level:
                names = [node.module]
            else:
                continue
            for name in names:
                assert name.split(".")[0] in allowed, f"{path.name} imports {name}"


def test_every_board_theme_plus_hoot():
    assert list(theme.THEMES)[0] == "Hoot"
    assert set(theme.THEMES) == {"Hoot", *palettes.THEMES}
    grouped = [n for _, names in theme.GROUPS for n in names]
    assert sorted(grouped) == sorted(theme.THEMES)
    assert theme.THEMES["Dark"] == palettes.THEMES["Dark"]   # Onion Board's own colours
    assert "accent_link" in theme.THEMES["Hoot"]   # finished like the others


def test_hoot_wears_the_theme_outfit_on_his_own():
    try:
        theme.set_current("Royal")
        assert bunnyfit.outfit() == bunnyfit.OUTFITS["Royal"]
        theme.set_current("Hoot")
        assert bunnyfit.outfit() == ()   # his own theme: just him
    finally:
        theme.set_current(theme.DEFAULT)


class _Host:
    def __init__(self, name=None, kit_pkg=None):
        self._name, self._kit = name, kit_pkg
        if name is not None:
            self.style = lambda: {"theme": self._name, "live_color": "", "textures": False}
        if kit_pkg is not None:
            self.kit = lambda: self._kit

    def palette(self):
        return dict(palettes.THEMES["Lava"])


def test_inside_the_board_he_follows_its_theme():
    try:
        theme.follow_host(_Host("Lava"))
        assert theme.current_name == "Lava" and theme.T["bg"] == palettes.THEMES["Lava"]["bg"]
        assert bunnyfit.outfit() == bunnyfit.OUTFITS.get("Lava", ())
        theme.follow_host(_Host())   # an older board: colours only, no outfit
        assert theme.current_name == theme.DEFAULT
        assert theme.T["bg"] == palettes.THEMES["Lava"]["bg"]
    finally:
        theme.set_current(theme.DEFAULT)


def test_the_board_kit_draws_him_when_it_is_as_new():
    board = types.ModuleType("boardkit")
    try:
        board.KIT_VERSION = KIT_VERSION
        kit.use_host(_Host(kit_pkg=board))
        assert kit.name() == "boardkit"
        board.KIT_VERSION = KIT_VERSION - 1   # an older board: our own copy
        kit.use_host(_Host(kit_pkg=board))
        assert kit.name() == "onionwatch.style"
        kit.use_host(_Host())                 # a board without kit()
        assert kit.owl().__name__ == "onionwatch.style.owl"
    finally:
        kit.use_own()
