"""Watching stays quiet: no capture path may use Windows.Graphics.Capture, the API
that draws the yellow "being recorded" border around what it copies. Onion Watch
copies with Desktop Duplication, GDI blits and PrintWindow, which show nothing."""
import re
from pathlib import Path

PKG = Path(__file__).resolve().parent.parent / "onionwatch"

# names only the border-drawing capture API (or a wrapper of it) would bring in
LOUD = re.compile(r"Graphics\.Capture|GraphicsCapture|winrt|windows_capture|"
                  r"IsBorderRequired|Direct3D11CaptureFramePool|CreateForMonitor",
                  re.IGNORECASE)


def test_no_capture_path_draws_a_border():
    found = [f"{p.relative_to(PKG.parent)}:{n}: {line.strip()}"
             for p in sorted(PKG.rglob("*.py"))
             for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1)
             if LOUD.search(line)]
    assert not found, "border-drawing capture API in use:\n" + "\n".join(found)
