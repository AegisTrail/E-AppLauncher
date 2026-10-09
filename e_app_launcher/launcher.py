from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from .models import AppImageEntry


class LaunchError(RuntimeError):
    pass


class AppLauncher:
    def check_fuse(self) -> tuple[bool, str]:
        """Check if FUSE is available for AppImages."""

        has_fusermount = shutil.which("fusermount") is not None or shutil.which("fusermount3") is not None
        has_fuse = Path("/dev/fuse").exists()
        if has_fusermount and has_fuse:
            return True, "FUSE available"

        if not has_fuse:
            return (
                False,
                "FUSE not available: /dev/fuse missing. Install libfuse2 or fuse3. AppImages may fail to launch.",
            )
        if not has_fusermount:
            return False, "fusermount not found. Install fuse."
        return True, "FUSE available"  # pragma: no cover - unreachable, kept as a safety net

    def validate_entry(self, entry: AppImageEntry) -> None:
        path = Path(entry.path)
        if not path.exists():
            raise FileNotFoundError(f"AppImage no longer exists: {entry.path}")
        if not path.is_file():
            raise FileNotFoundError(f"Not a file: {entry.path}")

        if not os.access(path, os.X_OK):
            raise PermissionError(f"AppImage not executable: {entry.path}. Run chmod +x or rescan.")

    def launch(
        self,
        entry: AppImageEntry,
        extra_args: list[str] | None = None,
        dry_run: bool = False,
    ) -> subprocess.Popen[bytes] | None:
        self.validate_entry(entry)
        cmd = [entry.path]
        if extra_args:
            cmd.extend(extra_args)
        if dry_run:
            return None
        try:
            return subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                start_new_session=True,
            )
        except OSError as e:
            ok, msg = self.check_fuse()
            if not ok:
                raise LaunchError(f"Failed to launch {entry.name}: {e}. {msg}") from e
            raise LaunchError(f"Failed to launch {entry.name}: {e}") from e

    def launch_by_name(
        self, entries: list[AppImageEntry], name: str, extra_args: list[str] | None = None
    ) -> AppImageEntry:
        target_name = name.casefold()

        for entry in entries:
            if entry.name.casefold() == target_name:
                self.launch(entry, extra_args=extra_args)
                return entry

        for entry in entries:
            if target_name in entry.name.casefold():
                self.launch(entry, extra_args=extra_args)
                return entry

        for entry in entries:
            if target_name in entry.effective_display_name().casefold():
                self.launch(entry, extra_args=extra_args)
                return entry
        raise FileNotFoundError(f"No AppImage named '{name}' found in index")

    def get_launch_command(self, entry: AppImageEntry, extra_args: list[str] | None = None) -> list[str]:
        cmd = [entry.path]
        if extra_args:
            cmd.extend(extra_args)
        return cmd
