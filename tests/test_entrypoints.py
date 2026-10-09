"""Package entry points: __main__ and root main.py delegate to app.main."""

import runpy
from pathlib import Path


def test_dunder_main_calls_app_main(monkeypatch):
    calls = []
    monkeypatch.setattr("e_app_launcher.app.main", lambda: calls.append(1))
    runpy.run_module("e_app_launcher.__main__", run_name="__main__")
    assert calls == [1]


def test_root_main_py_calls_app_main(monkeypatch):
    calls = []
    monkeypatch.setattr("e_app_launcher.app.main", lambda: calls.append(1))
    root = Path(__file__).parent.parent / "main.py"
    runpy.run_path(str(root), run_name="__main__")
    assert calls == [1]
