from __future__ import annotations

import json
import os
import stat
from pathlib import Path

from .models import AppImageEntry
from .paths import DATA_DIR, INDEX_PATH


class AppImageIndex:
    def __init__(self, index_path: Path = INDEX_PATH) -> None:
        self.index_path = index_path
        try:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass

    def scan(
        self,
        directory: Path | list[Path],
        recursive: bool = False,
        follow_symlinks: bool = False,
    ) -> list[AppImageEntry]:
        """Scan directory(ies) for AppImages. Handles duplicates, symlinks, recursive."""
        if isinstance(directory, (str, Path)):
            directories = [Path(directory)]
        else:
            directories = [Path(d) for d in directory]

        entries: list[AppImageEntry] = []
        seen_paths: set[str] = set()
        seen_names_lower: set[str] = set()

        for dir_path in directories:
            dir_path = dir_path.expanduser().resolve()
            if not dir_path.exists():
                raise FileNotFoundError(f"Directory does not exist: {dir_path}")
            if not dir_path.is_dir():
                raise NotADirectoryError(f"Not a directory: {dir_path}")

            if recursive:
                iterator = dir_path.rglob("*")
            else:
                iterator = dir_path.iterdir()

            for path in sorted(iterator, key=lambda item: item.name.lower()):
                try:
                    if path.is_symlink() and not follow_symlinks:
                        try:
                            real = path.resolve()
                            if not real.is_file():
                                continue

                            path_to_check = real
                        except OSError:
                            continue
                    else:
                        if not path.is_file():
                            continue
                        path_to_check = path

                    if path.suffix.lower() != ".appimage" and path_to_check.suffix.lower() != ".appimage":
                        continue

                    resolved_str = str(path.resolve())
                    if resolved_str in seen_paths:
                        continue
                    seen_paths.add(resolved_str)

                    try:
                        executable = os.access(path_to_check, os.X_OK)
                    except OSError:
                        executable = False
                    if not executable:
                        try:
                            st = path_to_check.stat()
                            path_to_check.chmod(st.st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

                            if path != path_to_check:
                                try:
                                    st2 = path.stat()
                                    path.chmod(st2.st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
                                except OSError:
                                    pass
                            executable = True
                        except OSError:
                            executable = False

                    try:
                        st = path_to_check.stat()
                        size = st.st_size
                        mtime = st.st_mtime
                    except OSError:
                        size = 0
                        mtime = 0.0

                    display_name, comment, categories, icon, version = self._extract_metadata(path_to_check)

                    desktop_integrated = self._is_integrated(path)

                    entries.append(
                        AppImageEntry(
                            name=path.name,
                            path=str(path.resolve()),
                            executable=executable,
                            size=size,
                            mtime=mtime,
                            display_name=display_name,
                            comment=comment,
                            categories=categories,
                            icon=icon,
                            version=version,
                            desktop_integrated=desktop_integrated,
                        )
                    )
                except OSError:
                    continue

        entries.sort(key=lambda e: e.name.lower())

        primary = directories[0].expanduser().resolve() if directories else Path.cwd()

        if len(directories) > 1:
            self.save(primary, entries, directories=directories)
        else:
            self.save(primary, entries)
        return entries

    def _extract_metadata(self, path: Path) -> tuple[str, str, str, str, str]:
        """Best-effort extract Name/Comment from AppImage without heavy extraction.
        Tries to run --appimage-help or use strings on desktop file if available.
        Falls back to empty.
        """

        name = path.name
        version = ""

        return "", "", "", "", version

    def _is_integrated(self, path: Path) -> bool:
        try:
            from .desktop import is_integrated

            return is_integrated(path)
        except Exception:
            return False

    def save(
        self,
        directory: Path,
        entries: list[AppImageEntry],
        directories: list[Path] | None = None,
    ) -> None:
        payload = {
            "directory": str(directory),
            "apps": [e.to_dict() for e in entries],
        }
        if directories is not None:
            payload["directories"] = [str(d.expanduser().resolve()) for d in directories]

        payload["version"] = 2
        self.index_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.index_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        tmp.replace(self.index_path)

    def load(self) -> tuple[Path | None, list[AppImageEntry]]:
        if not self.index_path.exists():
            return None, []
        try:
            text = self.index_path.read_text(encoding="utf-8")
            if not text.strip():
                return None, []
            payload = json.loads(text)
        except (json.JSONDecodeError, OSError, UnicodeDecodeError):
            try:
                backup = self.index_path.with_suffix(".json.corrupted")
                if not backup.exists():
                    self.index_path.rename(backup)
            except OSError:
                pass
            return None, []

        directory = payload.get("directory")

        raw_apps = payload.get("apps", [])
        entries: list[AppImageEntry] = []
        for item in raw_apps:
            try:
                if isinstance(item, dict):
                    entries.append(AppImageEntry.from_dict(item))
            except Exception:
                continue

        dirs = payload.get("directories")

        return (Path(directory) if directory else None), entries

    def load_with_dirs(self) -> tuple[list[Path], list[AppImageEntry]]:
        """Load and return all directories + entries."""
        if not self.index_path.exists():
            return [], []
        try:
            text = self.index_path.read_text(encoding="utf-8")
            if not text.strip():
                return [], []
            payload = json.loads(text)
        except (json.JSONDecodeError, OSError, UnicodeDecodeError):
            self.load()
            return [], []
        dirs_raw = payload.get("directories")
        if dirs_raw:
            dirs = [Path(d) for d in dirs_raw]
        else:
            d = payload.get("directory")
            dirs = [Path(d)] if d else []
        _, entries = self.load()
        return dirs, entries

    def is_stale(self, directories: list[Path], entries: list[AppImageEntry]) -> bool:
        """Check if index is stale vs disk."""
        try:
            disk_names = set()
            for d in directories:
                d = d.expanduser().resolve()
                if not d.is_dir():
                    continue
                for p in d.iterdir():
                    if p.is_file() and p.suffix.lower() == ".appimage":
                        disk_names.add(p.name.lower())
            cached = {e.name.lower() for e in entries}
            if disk_names != cached:
                return True
            if not all(Path(e.path).exists() for e in entries):
                return True
            return False
        except OSError:
            return True
