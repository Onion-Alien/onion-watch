"""Copy Onion Board's style kit (soundboard/style: the themes' colours and textures, Bun's
outfits, Hoot) into onionwatch/style, exactly, and stamp where it came from.

The kit's only real copy is Onion Board's. Never edit onionwatch/style by hand:
change it in Onion Board, then run this (tests/test_style_kit.py fails on a copy that
doesn't match its stamp).

    python scripts/sync_style.py --board ..\\soundboard\\code          # its origin/main
    python scripts/sync_style.py --board <checkout> --ref <branch or commit>

It reads the files from git (`git show <ref>:soundboard/style/...`), never the
checkout's working tree, which may be on an old branch.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEST = ROOT / "onionwatch" / "style"
STAMP = DEST / "SOURCE.json"
KIT = "soundboard/style"


def digest(data: bytes) -> str:
    """A file's fingerprint, the same whatever line endings git checked it out with."""
    return hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest()


def _git(board: Path, *args: str) -> bytes:
    return subprocess.run(["git", "-C", str(board), *args], check=True,
                          capture_output=True, timeout=60).stdout


def sync(board: Path, ref: str) -> dict:
    commit = _git(board, "rev-parse", f"{ref}^{{commit}}").decode().strip()
    names = [n for n in _git(board, "ls-tree", "--name-only", commit, f"{KIT}/")
             .decode().split() if n.endswith(".py")]
    if not names:
        raise SystemExit(f"no {KIT}/ at {ref} in {board}")
    DEST.mkdir(exist_ok=True)
    for old in DEST.glob("*.py"):
        old.unlink()
    files = {}
    for name in names:
        data = _git(board, "show", f"{commit}:{name}").replace(b"\r\n", b"\n")
        (DEST / Path(name).name).write_bytes(data)
        files[Path(name).name] = digest(data)
    stamp = {"from": "Onion Board", "path": KIT, "commit": commit, "files": files}
    STAMP.write_text(json.dumps(stamp, indent=2) + "\n", encoding="utf-8")
    return stamp


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--board", type=Path, required=True, help="an Onion Board git checkout")
    ap.add_argument("--ref", default="origin/main", help="branch or commit (origin/main)")
    a = ap.parse_args(argv)
    stamp = sync(a.board, a.ref)
    print(f"copied {len(stamp['files'])} files from Onion Board {stamp['commit'][:10]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
