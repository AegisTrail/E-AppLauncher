from __future__ import annotations

import threading
import time
from pathlib import Path


class PollingWatcher:
    """Simple polling watcher. Calls callback when directory changes."""

    def __init__(self, directories: list[Path], callback, interval: float = 2.0):
        self.directories = [d.expanduser().resolve() for d in directories]
        self.callback = callback
        self.interval = interval
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._snapshot = self._take_snapshot()

    def _take_snapshot(self) -> dict[str, float]:
        snap: dict[str, float] = {}
        for d in self.directories:
            try:
                for p in d.iterdir():
                    if p.is_file() and p.suffix.lower() == ".appimage":
                        try:
                            snap[str(p.resolve())] = p.stat().st_mtime
                        except OSError:
                            snap[str(p.resolve())] = 0

            except OSError:
                continue
        return snap

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=1)

    def _loop(self) -> None:
        while not self._stop.is_set():
            time.sleep(self.interval)
            new_snap = self._take_snapshot()
            if new_snap != self._snapshot:
                self._snapshot = new_snap
                try:
                    self.callback()
                except Exception:
                    pass


def create_watcher(directories: list[Path], callback, interval: float = 2.0):
    """Try watchdog, fall back to polling."""
    try:
        from watchdog.events import FileSystemEventHandler
        from watchdog.observers import Observer

        class Handler(FileSystemEventHandler):
            def __init__(self, cb):
                self.cb = cb
                self._last = 0

            def on_any_event(self, event):

                now = time.time()
                if now - self._last < 1.0:
                    return
                self._last = now

                src = getattr(event, "src_path", "")
                dest = getattr(event, "dest_path", "")
                if src.lower().endswith(".appimage") or dest.lower().endswith(".appimage") or event.is_directory:
                    try:
                        self.cb()
                    except Exception:
                        pass

        observer = Observer()
        handler = Handler(callback)
        for d in directories:
            try:
                d_resolved = d.expanduser().resolve()
                if d_resolved.is_dir():
                    observer.schedule(handler, str(d_resolved), recursive=False)
            except OSError:
                continue
        observer.start()

        class WatchdogWrapper:
            def stop(self):
                observer.stop()
                observer.join(timeout=1)

            def start(self):
                pass

        return WatchdogWrapper()
    except ImportError:
        w = PollingWatcher(directories, callback, interval=interval)
        w.start()
        return w
