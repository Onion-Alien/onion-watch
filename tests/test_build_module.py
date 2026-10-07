"""The Onion Board add-on zip (scripts/build_module.py): it holds only what the
board's Triggers tab needs, imports nothing Onion Board doesn't ship, is the same
bytes every build, and the package unzipped from it runs on its own the way the
board loads it (in a separate Python, so this one's onionwatch isn't disturbed)."""
import json
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import build_module  # noqa: E402

from onionwatch import __version__  # noqa: E402
from onionwatch.host import API_VERSION  # noqa: E402


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    return build_module.build(tmp_path_factory.mktemp("module"))


def test_it_holds_the_page_and_engine_but_not_the_app(built):
    with zipfile.ZipFile(built) as z:
        names = set(z.namelist())
    top = "onion-watch/onionwatch/"
    for want in ("board.py", "host.py", "screenwatch.py", "windows.py", "ui/triggerspanel.py",
                 "ui/windowpicker.py", "ui/snip.py", "ui/alarmbar.py", "theme.py",
                 "ui/viewer.py", "ui/deleted.py", "ui/watching.py"):  # opened only when asked
        assert top + want in names, want
    for app_only in ("app.py", "apphost.py", "player.py", "sounds.py", "settings.py",
                     "singleinstance.py", "ui/mainwindow.py", "ui/settingsdialog.py"):
        assert top + app_only not in names, app_only
    assert {"onion-watch/module.json", "onion-watch/LICENSE"} <= names
    assert all(n.startswith("onion-watch/") and ".." not in n for n in names)


def test_its_module_json_says_what_the_board_checks(built):
    with zipfile.ZipFile(built) as z:
        m = json.loads(z.read("onion-watch/module.json"))
    assert m["id"] == "onion-watch" and m["kind"] == "triggers"
    assert m["version"] == __version__ and m["api_version"] == API_VERSION
    assert (m["package"], m["entry"]) == ("onionwatch", "onionwatch.board")
    assert set(m["imports"]) == {"numpy", "PySide6.QtCore", "PySide6.QtGui", "PySide6.QtWidgets"}


def test_it_imports_only_what_onion_board_ships():
    _files, outside = build_module.closure()
    assert build_module.not_allowed(outside) == []
    # sounddevice would be refused (the board ships it, but the module mustn't need it)
    assert build_module.not_allowed(outside | {"sounddevice", "requests"}) == [
        "requests", "sounddevice"]
    # nor scipy as a must: only scipy.fft, and only tried, with a fallback
    assert build_module.not_allowed(outside | {"scipy.fft"}) == ["scipy.fft"]


def test_scipy_fft_is_only_tried_so_the_module_loads_without_it(built):
    files, _outside = build_module.closure()
    assert build_module.tried(files) == {"scipy.fft"} == build_module.OPTIONAL
    with zipfile.ZipFile(built) as z:
        m = json.loads(z.read("onion-watch/module.json"))
    assert not any(i.startswith("scipy") for i in m["imports"])


def test_an_optional_import_needs_a_fallback(tmp_path):
    src = tmp_path / "m.py"
    src.write_text("try:\n    import scipy.fft\nexcept ImportError:\n    pass\n"
                   "import scipy.signal\n", encoding="utf-8")
    assert build_module._imports(src, "m") == {"scipy.signal"}
    assert build_module._imports(src, "m", optional=True) == {"scipy.fft"}


def test_the_same_source_builds_the_same_bytes(built, tmp_path):
    again = build_module.build(tmp_path)
    assert again.read_bytes() == built.read_bytes()


def test_the_unzipped_package_runs_on_a_board_like_host(built, tmp_path):
    with zipfile.ZipFile(built) as z:
        z.extractall(tmp_path)
    folder = tmp_path / "onion-watch"
    script = f"""
import importlib, importlib.util, os, sys
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, {str(ROOT / "tests")!r})     # the stand-in host only
folder = {str(folder)!r}
spec = importlib.util.spec_from_file_location(
    "onionwatch", os.path.join(folder, "onionwatch", "__init__.py"),
    submodule_search_locations=[os.path.join(folder, "onionwatch")])
pkg = importlib.util.module_from_spec(spec)
sys.modules["onionwatch"] = pkg
spec.loader.exec_module(pkg)
from PySide6.QtWidgets import QApplication
app = QApplication([])
board = importlib.import_module("onionwatch.board")
from fakehost import FakeHost
from pathlib import Path
tab = board.create(FakeHost(Path({str(tmp_path / "data")!r})))
assert all(m.__file__.startswith(folder) for n, m in sys.modules.items()
           if n.startswith("onionwatch") and getattr(m, "__file__", None))
assert "onionwatch.player" not in sys.modules and "sounddevice" not in sys.modules
tab.shutdown()
print("loaded", tab.version)
"""
    r = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True,
                       timeout=120, cwd=tmp_path)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == f"loaded {__version__}"
