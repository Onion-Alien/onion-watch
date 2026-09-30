"""Write build/version_info.txt, the Windows version details PyInstaller stamps on
OnionWatch.exe (Properties -> Details: product, description, version, copyright).
An exe without them looks like throwaway malware to machine-learning virus scanners,
so build.ps1 always passes this with --version-file.

    python scripts/make_version_info.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from onionwatch import __version__  # noqa: E402

TEMPLATE = """\
VSVersionInfo(
  ffi=FixedFileInfo(filevers={t}, prodvers={t}, mask=0x3f, flags=0x0, OS=0x40004,
                    fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040904B0', [
      StringStruct('CompanyName', 'Onion Watch'),
      StringStruct('FileDescription', 'Onion Watch'),
      StringStruct('FileVersion', '{v}'),
      StringStruct('InternalName', 'OnionWatch'),
      StringStruct('LegalCopyright', 'Copyright (C) Onion Watch contributors'),
      StringStruct('OriginalFilename', 'OnionWatch.exe'),
      StringStruct('ProductName', 'Onion Watch'),
      StringStruct('ProductVersion', '{v}'),
      StringStruct('Comments', 'https://github.com/Onion-Alien/onion-watch')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""


def main() -> int:
    parts = [int(x) for x in __version__.split(".")] + [0]
    out = ROOT / "build" / "version_info.txt"
    out.parent.mkdir(exist_ok=True)
    out.write_text(TEMPLATE.format(t=tuple(parts[:4]), v=__version__), encoding="utf-8")
    print(f"wrote {out.relative_to(ROOT)} ({__version__})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
