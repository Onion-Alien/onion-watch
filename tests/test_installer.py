"""The installer script (installer/OnionWatch.iss), read as text since Inno Setup only
runs on a build PC: uninstalling offers to delete the app's data without ever doing
it by surprise."""
import re
from pathlib import Path

ISS = Path(__file__).resolve().parent.parent / "installer" / "OnionWatch.iss"


def test_uninstall_offers_to_delete_data_safely():
    text = ISS.read_text("utf-8")
    assert not re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", text), "a control character"
    body = text.split("procedure OfferToDeleteData;", 1)[1].split("\nend;", 1)[0]
    assert "{userappdata}\\OnionWatch" in body
    assert "UninstallSilent" in body              # a silent uninstall keeps the data
    assert "MB_DEFBUTTON2" in body                # No is the default
    assert "SendToRecycleBin" in body             # Yes recycles, it doesn't erase
    assert "{sys}\\WindowsPowerShell\\v1.0\\powershell.exe" in body
    assert "SW_HIDE" in body
    assert "usPostUninstall then\n    OfferToDeleteData" in text.replace("\r\n", "\n")
