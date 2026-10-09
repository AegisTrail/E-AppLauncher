from __future__ import annotations

import json
from pathlib import Path

from .paths import CONFIG_PATH, CONFIG_PATH_XDG, DATA_DIR


class ConfigStore:
    """Handles config with XDG compliance, multi-dir, and corruption safety."""

    def __init__(self, config_path: Path | None = None) -> None:
        if config_path is not None:
            self.config_path = config_path
            self._alt_path = None
        else:
            self.config_path = CONFIG_PATH
            self._alt_path = CONFIG_PATH_XDG

        try:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        if self._alt_path is not None:
            try:
                self._alt_path.parent.mkdir(parents=True, exist_ok=True)
            except OSError:
                pass

    def _resolve_path(self) -> Path:
        """Return existing config path, or default."""
        if self.config_path.exists():
            return self.config_path
        if self._alt_path is not None and self._alt_path.exists():
            return self._alt_path
        return self.config_path

    def load(self) -> dict:
        path = self._resolve_path()
        if not path.exists():
            return {}
        try:
            text = path.read_text(encoding="utf-8")
            if not text.strip():
                return {}
            return json.loads(text)
        except (json.JSONDecodeError, OSError, UnicodeDecodeError):
            try:
                backup = path.with_suffix(".json.corrupted")
                if not backup.exists():
                    path.rename(backup)
            except OSError:
                pass
            return {}

    def save(self, data: dict) -> None:
        path = self.config_path
        path.parent.mkdir(parents=True, exist_ok=True)

        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        tmp.replace(path)

    def save_directory(self, directory: Path) -> None:
        data = self.load()
        data["directory"] = str(directory.expanduser().resolve())

        dirs = data.get("directories")
        if dirs is None:
            data["directories"] = [data["directory"]]
        self.save(data)

    def save_directories(self, directories: list[Path]) -> None:
        resolved = [str(p.expanduser().resolve()) for p in directories]
        data = self.load()
        data["directories"] = resolved

        if resolved:
            data["directory"] = resolved[0]
        self.save(data)

    def get_directory(self) -> Path | None:
        data = self.load()
        directory = data.get("directory")
        if directory:
            return Path(directory)
        dirs = data.get("directories")
        if dirs and isinstance(dirs, list) and dirs[0]:
            return Path(dirs[0])
        return None

    def get_directories(self) -> list[Path]:
        data = self.load()
        dirs = data.get("directories")
        if dirs and isinstance(dirs, list):
            return [Path(d) for d in dirs if d]
        single = data.get("directory")
        if single:
            return [Path(single)]

        candidates = [Path.home() / "AppImages", Path.home() / "Applications"]
        existing = [p for p in candidates if p.is_dir()]
        return existing

    def add_directory(self, directory: Path) -> None:
        dirs = self.get_directories()
        resolved = directory.expanduser().resolve()
        if resolved not in [d.expanduser().resolve() for d in dirs]:
            dirs.append(resolved)
            self.save_directories(dirs)

    def remove_directory(self, directory: Path) -> bool:
        dirs = self.get_directories()
        resolved = directory.expanduser().resolve()
        new_dirs = [d for d in dirs if d.expanduser().resolve() != resolved]
        if len(new_dirs) != len(dirs):
            self.save_directories(new_dirs)
            return True
        return False

    def clear(self) -> None:
        path = self._resolve_path()
        try:
            if path.exists():
                path.unlink()
        except OSError:
            pass

    def get(self, key: str, default=None):
        return self.load().get(key, default)

    def set(self, key: str, value) -> None:
        data = self.load()
        data[key] = value
        self.save(data)
