"""Build Onion Watch as an Onion Board add-on module: dist/OnionWatch-module.zip.

    onion-watch/
        module.json     id, name, version, kind "triggers", api_version, package,
                        entry, and the third-party modules it imports
        onionwatch/     only what onionwatch.board needs (followed through every
                        import, also the ones made inside functions): the engine
                        and the triggers page, not the app, its tray or its player
        LICENSE

Onion Board unzips it into %APPDATA%\\OnionBoard\\modules\\onion-watch and loads the
package from there. The built app has no pip, so the module may only import what
Onion Board ships: the standard library, numpy and PySide6's QtCore / QtGui /
QtWidgets (ALLOWED_*). Anything else fails the build. It may also try scipy.fft
(OPTIONAL: Onion Board ships it, for speed) inside a `try` that falls back when the
import fails; module.json doesn't list it, so a host without it still loads the
module.

The zip is the same byte for byte for the same source (fixed file times, sorted
entries), so its SHA-256 only changes when the code does.

Usage: python scripts/build_module.py [--out DIR]   (prints the zip's path and SHA-256)
The zip is attached to the GitHub release as is (see README → Onion Board add-on).
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import importlib.util
import io
import json
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PACKAGE = "onionwatch"
ENTRY = "onionwatch.board"
MODULE_ID = "onion-watch"
ZIP_NAME = "OnionWatch-module.zip"
# what Onion Board's build ships besides the standard library: these packages
# (any part of them), and these modules
ALLOWED_PACKAGES = {"numpy"}
ALLOWED_MODULES = {"PySide6", "PySide6.QtCore", "PySide6.QtGui", "PySide6.QtWidgets"}
# tried, with a fallback when they're missing (see _optional)
OPTIONAL = {"scipy.fft"}
DESCRIPTION = ("Plays a sound when something shows up in a game — a rare spawn, a queue "
               "pop, YOU DIED — watching the game's own window, even while other windows "
               "cover it.")
FIXED_TIME = (2026, 1, 1, 0, 0, 0)


def _optional(tree: ast.AST) -> set[int]:
    """The import statements (their ids) inside a `try` that catches ImportError:
    the code runs without what they import."""
    def catches(h: ast.ExceptHandler) -> bool:
        names = h.type.elts if isinstance(h.type, ast.Tuple) else [h.type]
        return any(isinstance(n, ast.Name) and n.id in ("ImportError", "ModuleNotFoundError")
                   for n in names)
    out: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Try) and any(catches(h) for h in node.handlers):
            out.update(id(sub) for stmt in node.body for sub in ast.walk(stmt)
                       if isinstance(sub, (ast.Import, ast.ImportFrom)))
    return out


def _imports(path: Path, modname: str, optional: bool = False) -> set[str]:
    """Every module `path` imports, anywhere in it, as absolute names: the ones it
    needs, or with `optional` the ones it only tries (see _optional)."""
    tree = ast.parse(path.read_text(encoding="utf-8"), str(path))
    pkg = modname if path.name == "__init__.py" else modname.rpartition(".")[0]
    tried = _optional(tree)
    found: set[str] = set()
    for node in ast.walk(tree):
        if (id(node) in tried) != optional:
            continue
        if isinstance(node, ast.Import):
            found.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                parts = pkg.split(".")
                base = ".".join(parts[:len(parts) - node.level + 1] + ([base] if base else []))
            if base == "__future__":
                continue
            found.add(base)
            # "from onionwatch import theme": theme may itself be a module
            found.update(f"{base}.{a.name}" for a in node.names)
    return found


def _file_of(modname: str) -> Path | None:
    """The source file of a module inside the package, or None if it isn't one."""
    rel = ROOT.joinpath(*modname.split("."))
    if rel.with_suffix(".py").is_file():
        return rel.with_suffix(".py")
    if (rel / "__init__.py").is_file():
        return rel / "__init__.py"
    return None


def closure(entry: str = ENTRY) -> tuple[dict[str, Path], set[str]]:
    """The package's modules `entry` needs, followed through every import:
    ({module name: its file}, the modules it imports from outside the package)."""
    files: dict[str, Path] = {}
    outside: set[str] = set()
    todo = [PACKAGE, entry]
    while todo:
        name = todo.pop()
        if name in files:
            continue
        path = _file_of(name)
        if path is None:
            if not (name == PACKAGE or name.startswith(PACKAGE + ".")):
                outside.add(name)
            continue          # "from onionwatch import __version__": not a module
        files[name] = path
        # a submodule needs its package's __init__ too
        parent = name.rpartition(".")[0]
        if parent:
            todo.append(parent)
        todo.extend(_imports(path, name))
    return files, outside


def _is_module(name: str) -> bool:
    """Is `name` a module (not a name inside one, like PySide6.QtCore.Qt)?"""
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):     # its parent isn't a package
        return False


def third_party(outside: set[str]) -> list[str]:
    """The modules from outside the standard library it imports (module.json lists
    them so Onion Board can check it has them before loading the module)."""
    stdlib = set(sys.stdlib_module_names)

    def module_or_missing(n: str) -> bool:
        # a name inside a module (PySide6.QtCore.Qt) isn't one; a module that
        # can't be found at all still counts, so an import of it is refused
        parent = n.rpartition(".")[0]
        return _is_module(n) or not (parent and _is_module(parent))
    return sorted(n for n in outside if n.split(".")[0] not in stdlib and module_or_missing(n))


def not_allowed(outside: set[str]) -> list[str]:
    """The modules it imports that Onion Board doesn't ship."""
    return [n for n in third_party(outside)
            if n.split(".")[0] not in ALLOWED_PACKAGES and n not in ALLOWED_MODULES]


def manifest(outside: set[str]) -> dict:
    sys.path.insert(0, str(ROOT))
    from onionwatch import __version__
    from onionwatch.host import API_VERSION
    return {"id": MODULE_ID, "name": "Onion Watch", "version": __version__,
            "description": DESCRIPTION, "kind": "triggers", "api_version": API_VERSION,
            "package": PACKAGE, "entry": ENTRY, "imports": third_party(outside),
            "homepage": "https://github.com/Onion-Alien/onion-watch"}


def _add(z: zipfile.ZipFile, name: str, data: bytes):
    info = zipfile.ZipInfo(name, FIXED_TIME)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o644 << 16
    z.writestr(info, data)


def tried(files: dict[str, Path]) -> set[str]:
    """The modules from outside the package the module only tries to import."""
    names = set().union(*(_imports(p, m, optional=True) for m, p in files.items()))
    return {n for n in names if _file_of(n) is None and n.split(".")[0] != PACKAGE}


def build(out: Path) -> Path:
    files, outside = closure()
    bad = not_allowed(outside) + sorted(tried(files) - OPTIONAL)
    if bad:
        raise SystemExit("the module imports what Onion Board doesn't ship: " + ", ".join(bad))
    entries = {f"{MODULE_ID}/module.json":
               (json.dumps(manifest(outside), indent=1, ensure_ascii=False) + "\n").encode(),
               f"{MODULE_ID}/LICENSE": (ROOT / "LICENSE").read_bytes()}
    for path in files.values():
        rel = path.relative_to(ROOT).as_posix()
        entries[f"{MODULE_ID}/{rel}"] = path.read_bytes()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name in sorted(entries):
            _add(z, name, entries[name])
    out.mkdir(parents=True, exist_ok=True)
    dest = out / ZIP_NAME
    dest.write_bytes(buf.getvalue())
    return dest


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", type=Path, default=ROOT / "dist")
    args = ap.parse_args(argv)
    dest = build(args.out)
    sha = hashlib.sha256(dest.read_bytes()).hexdigest()
    with zipfile.ZipFile(dest) as z:
        names = z.namelist()
    print(f"{dest} ({dest.stat().st_size // 1024} KB, {len(names)} files)")
    print(f"SHA-256: {sha}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
