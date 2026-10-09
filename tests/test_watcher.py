import time
from pathlib import Path

import pytest

from e_app_launcher.watcher import PollingWatcher


def test_polling_watcher_detects(tmp_path: Path):
    d = tmp_path / "apps"
    d.mkdir()
    (d / "A.AppImage").write_text("hi")
    called = []

    def cb():
        called.append(1)

    w = PollingWatcher([d], cb, interval=0.1)
    w.start()
    time.sleep(0.2)
    # Create new file
    (d / "B.AppImage").write_text("hi")
    time.sleep(0.5)
    w.stop()
    assert len(called) >= 1


def test_polling_watcher_no_change(tmp_path: Path):
    d = tmp_path / "apps"
    d.mkdir()
    called = []

    def cb():
        called.append(1)

    w = PollingWatcher([d], cb, interval=0.1)
    w.start()
    time.sleep(0.3)
    w.stop()
    assert len(called) == 0


def test_snapshot_ignores_non_appimage_and_missing_dir(tmp_path: Path):
    d = tmp_path / "apps"
    d.mkdir()
    (d / "notes.txt").write_text("hi")
    w = PollingWatcher([d, tmp_path / "nope"], lambda: None, interval=60)
    assert w._take_snapshot() == {}
    (d / "A.AppImage").write_text("hi")
    snap = w._take_snapshot()
    assert len(snap) == 1


def test_polling_watcher_detects_deletion(tmp_path: Path):
    d = tmp_path / "apps"
    d.mkdir()
    (d / "A.AppImage").write_text("hi")
    called = []

    def cb():
        called.append(1)

    w = PollingWatcher([d], cb, interval=0.05)
    w.start()
    time.sleep(0.15)
    (d / "A.AppImage").unlink()
    time.sleep(0.4)
    w.stop()
    assert len(called) >= 1


def test_watcher_stop_idempotent_and_double_start(tmp_path: Path):
    d = tmp_path / "apps"
    d.mkdir()
    w = PollingWatcher([d], lambda: None, interval=60)
    w.stop()  # never started: no crash
    w.start()
    first = w._thread
    w.start()  # already alive: keeps same thread
    assert w._thread is first
    w.stop()
    w.stop()  # second stop: no crash


def test_callback_exception_does_not_kill_watcher(tmp_path: Path):
    d = tmp_path / "apps"
    d.mkdir()
    (d / "A.AppImage").write_text("hi")
    calls = []

    def cb():
        calls.append(1)
        raise RuntimeError("boom")

    w = PollingWatcher([d], cb, interval=0.05)
    w.start()
    time.sleep(0.15)
    (d / "B.AppImage").write_text("hi")
    time.sleep(0.4)
    w.stop()
    assert len(calls) >= 1  # callback ran; watcher survived its exception


def test_create_watcher_schedule_error_skips_dir(tmp_path: Path):
    watchdog = pytest.importorskip("watchdog")
    from unittest.mock import patch

    from watchdog.observers import Observer

    import e_app_launcher.watcher as watchmod

    d = tmp_path / "apps"
    d.mkdir()
    with patch.object(Observer, "schedule", side_effect=OSError("denied")):
        w = watchmod.create_watcher([d], lambda: None)
    try:
        w.stop()
    except Exception:
        pass


def test_create_watcher_falls_back_without_watchdog(tmp_path: Path, monkeypatch):
    import sys

    from e_app_launcher.watcher import PollingWatcher, create_watcher

    d = tmp_path / "apps"
    d.mkdir()
    monkeypatch.setitem(sys.modules, "watchdog.events", None)
    monkeypatch.setitem(sys.modules, "watchdog.observers", None)
    w = create_watcher([d], lambda: None, interval=60)
    try:
        assert isinstance(w, PollingWatcher)
    finally:
        w.stop()


def test_create_watcher_returns_stoppable(tmp_path: Path):
    from e_app_launcher.watcher import create_watcher

    d = tmp_path / "apps"
    d.mkdir()
    w = create_watcher([d], lambda: None, interval=60)
    assert hasattr(w, "stop")
    assert hasattr(w, "start")
    w.start()  # wrapper start is a documented noop
    w.stop()


def test_snapshot_stat_error_records_zero(tmp_path: Path):
    from unittest.mock import patch

    from e_app_launcher.watcher import PollingWatcher

    d = tmp_path / "apps"
    d.mkdir()
    (d / "A.AppImage").write_text("hi")
    with (
        patch.object(Path, "is_file", return_value=True),
        patch.object(Path, "stat", side_effect=OSError("racy")),
    ):
        snap = PollingWatcher([d], lambda: None, interval=60)._take_snapshot()
    assert list(snap.values()) == [0]


def test_watchdog_handler_debounce_filters_and_swallows(tmp_path: Path):
    pytest.importorskip("watchdog")
    import time
    from unittest.mock import MagicMock, patch

    import e_app_launcher.watcher as watchmod

    d = tmp_path / "apps"
    d.mkdir()
    captured = {}
    from watchdog.observers import Observer

    orig_schedule = Observer.schedule

    def fake_schedule(self, handler, path, **kw):
        captured["handler"] = handler
        return orig_schedule(self, handler, path, **kw)

    calls = []
    with patch.object(Observer, "schedule", fake_schedule):
        w = watchmod.create_watcher([d], lambda: calls.append(1))
    try:
        handler = captured["handler"]

        def event(src="", dest="", is_dir=False):
            e = MagicMock()
            e.src_path = src
            e.dest_path = dest
            e.is_directory = is_dir
            return e

        handler.on_any_event(event(src=str(d / "A.AppImage")))
        assert calls == [1]
        handler.on_any_event(event(src=str(d / "B.AppImage")))
        assert calls == [1]  # debounced within 1s
        handler._last = time.time() - 2
        handler.on_any_event(event(src=str(d / "notes.txt")))
        assert calls == [1]  # non-AppImage file ignored
        handler._last = time.time() - 2
        handler.on_any_event(event(src=str(d), is_dir=True))
        assert calls == [1, 1]  # directory events always fire
    finally:
        w.stop()


def test_watchdog_handler_callback_error_swallowed(tmp_path: Path):
    pytest.importorskip("watchdog")
    from unittest.mock import patch

    from watchdog.observers import Observer

    import e_app_launcher.watcher as watchmod

    d = tmp_path / "apps"
    d.mkdir()
    captured = {}
    orig_schedule = Observer.schedule

    def fake_schedule(self, handler, path, **kw):
        captured["handler"] = handler
        return orig_schedule(self, handler, path, **kw)

    def bad_cb():
        raise RuntimeError("boom")

    with patch.object(Observer, "schedule", fake_schedule):
        w = watchmod.create_watcher([d], bad_cb)
    try:
        from unittest.mock import MagicMock

        e = MagicMock()
        e.src_path = str(d / "A.AppImage")
        e.dest_path = ""
        e.is_directory = False
        captured["handler"].on_any_event(e)  # must not raise
    finally:
        w.stop()
