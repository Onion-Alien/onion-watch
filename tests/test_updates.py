"""The update check and download (onionwatch.updates), with GitHub faked."""
import hashlib
import io

import pytest

from onionwatch import settings, updates

SHA = "a" * 64
DL = updates.DOWNLOADS + "v9.9.9/"


def release(**kw):
    data = {"tag_name": "v9.9.9", "html_url": f"https://github.com/{updates.REPO}/releases/tag/v9.9.9",
            "body": "**New:** things.\n\n⬇ Download it\n\nMore.",
            "assets": [{"name": updates.ASSET, "browser_download_url": DL + updates.ASSET,
                        "digest": "sha256:" + SHA, "size": 10}]}
    data.update(kw)
    return data


def test_versions():
    assert updates.parse_version("v0.10.2") == (0, 10, 2)
    assert updates.newer("0.10.0", "0.9.9") and not updates.newer("0.7.2", "0.7.2")


def test_latest_reads_the_release(monkeypatch):
    monkeypatch.setattr(updates, "_get", lambda url: release())
    rel = updates.latest()
    assert (rel.version, rel.asset_url, rel.sha256) == ("9.9.9", DL + updates.ASSET, SHA)
    assert rel.notes == "New: things.\n\nMore."


def test_update_asset_preferred_and_strangers_refused(monkeypatch):
    data = release()
    data["assets"].append({"name": updates.UPDATE_ASSET, "digest": "sha256:" + "b" * 64,
                           "browser_download_url": DL + updates.UPDATE_ASSET})
    assert updates._installer(data)[0].endswith(updates.UPDATE_ASSET)
    data = release(assets=[{"name": updates.ASSET, "digest": "sha256:" + SHA,
                            "browser_download_url": "https://example.com/x.exe"}])
    assert updates._installer(data) == ("", "", 0)
    data = release(html_url="https://example.com/evil")
    monkeypatch.setattr(updates, "_get", lambda url: data)
    assert updates.latest().url == updates.RELEASES


def test_check_daily_skip_and_switch(monkeypatch):
    calls = []
    monkeypatch.setattr(updates, "_get", lambda url: calls.append(url) or release())
    c = settings.Config()
    assert updates.check(c).version == "9.9.9"
    assert updates.check(c) is None and len(calls) == 1          # once a day
    c.update_checked, c.update_skip = 0.0, "9.9.9"
    assert updates.check(c) is None                              # skipped...
    assert updates.check(c, force=True).version == "9.9.9"       # ...but Check now says
    c.update_checked, c.update_check = 0.0, False
    n = len(calls)
    assert updates.check(c) is None and len(calls) == n          # switched off: no ask


def test_check_quiet_offline_but_forced_raises(monkeypatch):
    def boom(url):
        raise OSError("offline")
    monkeypatch.setattr(updates, "_get", boom)
    assert updates.check(settings.Config()) is None
    with pytest.raises(OSError):
        updates.check(settings.Config(), force=True)


class FakeResponse(io.BytesIO):
    def __init__(self, data, url="https://objects.example/x"):
        super().__init__(data)
        self.headers = {"Content-Length": str(len(data))}
        self._url = url

    def geturl(self):
        return self._url

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


def test_download_checks_the_sha(monkeypatch, tmp_path):
    monkeypatch.setattr(updates, "UPDATES_DIR", tmp_path)
    data = b"installer bytes"
    good = hashlib.sha256(data).hexdigest()
    monkeypatch.setattr(updates.urllib.request, "urlopen", lambda req, timeout: FakeResponse(data))
    rel = updates.Release("9.9.9", "", "", DL + updates.ASSET, good)
    seen = []
    path = updates.download(rel, lambda d, t: seen.append((d, t)))
    assert path.read_bytes() == data and seen[-1] == (len(data), len(data))
    bad = updates.Release("9.9.8", "", "", DL + updates.ASSET, SHA)
    with pytest.raises(updates.UpdateError, match="checksum"):
        updates.download(bad)
    assert not list(tmp_path.glob("*9.9.8*"))                    # no half file left
    with pytest.raises(updates.UpdateError):
        updates.download(updates.Release("9.9.7", "", "", "https://example.com/x.exe", good))


def test_installer_env_drops_the_frozen_apps_paths(tmp_path):
    bundle = str(tmp_path / "_internal")
    env = updates.installer_env({"_PYI_X": "1", "PATH": rf"{bundle};C:\Windows",
                                 "QT_PLUGIN_PATH": bundle + r"\plugins"}, bundle)
    assert env["PATH"] == r"C:\Windows" and "_PYI_X" not in env
    assert "QT_PLUGIN_PATH" not in env and env["PYINSTALLER_RESET_ENVIRONMENT"] == "1"
