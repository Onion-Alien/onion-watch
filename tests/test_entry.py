"""Importing `onionwatch.__main__` (Onion Board loads every file of the add-on up
front) must not start the app: only `python -m onionwatch` does."""
import importlib
import sys

from onionwatch.core import app


def test_importing_the_python_m_start_file_does_not_start_the_app(monkeypatch):
    started = []
    monkeypatch.setattr(app, "main", lambda *a, **k: started.append(True))
    monkeypatch.delitem(sys.modules, "onionwatch.__main__", raising=False)
    importlib.import_module("onionwatch.__main__")
    assert started == []
