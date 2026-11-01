"""The build's trim (scripts/buildtools/prune_build.py): PortAudio's ASIO builds (made with
Steinberg's ASIO SDK, which isn't open source) and its builds for other systems never
ship; the plain x64 one, which sounddevice loads here, stays."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts" / "buildtools"))
import prune_build  # noqa: E402


def test_only_the_plain_x64_portaudio_stays(tmp_path):
    (tmp_path / "_internal" / "PySide6").mkdir(parents=True)
    pa = tmp_path / prune_build.PORTAUDIO
    pa.mkdir(parents=True)
    names = ["libportaudio64bit.dll", *prune_build.DROP_PORTAUDIO]
    for n in names:
        (pa / n).write_bytes(b"")
    drop, problems = prune_build.plan(tmp_path, lambda p: [])
    assert not problems
    dropped = {p.name for p in drop if p.parent == pa}
    assert dropped == set(names) - {"libportaudio64bit.dll"}
    assert "libportaudio64bit-asio.dll" in dropped
