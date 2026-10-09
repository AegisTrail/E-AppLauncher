from __future__ import annotations

import subprocess
from pathlib import Path

from .models import AppImageEntry


def check_update_info(entry: AppImageEntry) -> dict | None:
    """Try to get update info from AppImage.
    Checks for embedded update information via --appimage-help or AppImageUpdate.
    Returns dict with info or None.
    """
    path = Path(entry.path)
    if not path.exists():
        return None

    try:
        result = subprocess.run(
            [str(path), "--appimage-help"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        output = (result.stdout or "") + (result.stderr or "")

        if "updateinformation" in output.lower() or "appimageupdate" in output.lower():
            return {"has_update_info": True, "output": output.strip()[:500]}
    except Exception:
        pass

    try:
        result = subprocess.run(
            ["strings", str(path)],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            text = result.stdout

            for line in text.splitlines():
                if "zsync" in line.lower() or "github.com" in line and "update" in line.lower():
                    return {"has_update_info": True, "hint": line.strip()[:200]}
    except Exception:
        pass

    return {"has_update_info": False}


def check_all(entries: list[AppImageEntry]) -> list[tuple[AppImageEntry, dict]]:
    results = []
    for e in entries:
        info = check_update_info(e)
        if info:
            results.append((e, info))
    return results
