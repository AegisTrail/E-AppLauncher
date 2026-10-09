from __future__ import annotations

import configparser
import shutil
import subprocess
import tempfile
from pathlib import Path

from .paths import DESKTOP_DIR, ICON_DIR


def _desktop_filename(appimage: Path) -> str:
    name = appimage.stem.replace(" ", "_")

    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in name)
    return f"e-applauncher-{safe}.desktop"


def _icon_filename(appimage: Path) -> Path | None:
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in appimage.stem)
    return ICON_DIR / f"{safe}.png"


def is_integrated(appimage: Path) -> bool:
    desktop = DESKTOP_DIR / _desktop_filename(appimage)
    return desktop.exists()


def integrate(appimage: Path, prompt: bool = False) -> Path | None:
    """Extract desktop file and icon from AppImage and create integration.
    Returns path to desktop file or None.
    """
    appimage = appimage.expanduser().resolve()
    if not appimage.is_file():
        raise FileNotFoundError(f"AppImage not found: {appimage}")
    if appimage.suffix.lower() != ".appimage":
        raise ValueError(f"Not an AppImage: {appimage}")

    desktop_path = DESKTOP_DIR / _desktop_filename(appimage)
    DESKTOP_DIR.mkdir(parents=True, exist_ok=True)
    ICON_DIR.mkdir(parents=True, exist_ok=True)

    desktop_content = None
    icon_src = None
    extracted_icon_dest = None

    with tempfile.TemporaryDirectory(prefix="e-applauncher-extract-") as tmp:
        tmp_path = Path(tmp)

        extracted = _extract_appimage(appimage, tmp_path)
        if extracted:
            desktops = list(tmp_path.rglob("*.desktop"))

            chosen = None
            for d in desktops:
                if d.name.startswith("."):
                    continue
                chosen = d
                break
            if chosen:
                try:
                    text = chosen.read_text(encoding="utf-8", errors="ignore")
                    desktop_content = _transform_desktop(text, appimage)
                except OSError:
                    pass

            icons = list(tmp_path.rglob("*.png")) + list(tmp_path.rglob("*.svg"))
            if icons:
                icons.sort(key=lambda p: p.stat().st_size if p.exists() else 0, reverse=True)
                icon_src = icons[0]

            if icon_src and icon_src.exists():
                dest = _icon_filename(appimage)
                try:
                    shutil.copy2(icon_src, dest)
                    extracted_icon_dest = dest
                except OSError:
                    pass

    if desktop_content is None:
        icon_name = ""
        if extracted_icon_dest:
            icon_name = extracted_icon_dest.stem
        desktop_content = _generate_minimal_desktop(appimage, icon_name)

    if extracted_icon_dest and "Icon=" in desktop_content:
        icon_name = extracted_icon_dest.stem

        lines = []
        for line in desktop_content.splitlines():
            if line.startswith("Icon="):
                lines.append(f"Icon={icon_name}")
            else:
                lines.append(line)
        desktop_content = "\n".join(lines) + "\n"

    desktop_path.write_text(desktop_content, encoding="utf-8")

    try:
        desktop_path.chmod(0o755)
    except OSError:
        pass

    try:
        subprocess.run(
            ["update-desktop-database", str(DESKTOP_DIR)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5,
        )
    except Exception:
        pass
    try:
        subprocess.run(
            ["gtk-update-icon-cache", "-f", "-t", str(ICON_DIR.parent)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5,
        )
    except Exception:
        pass

    return desktop_path


def remove_integration(appimage: Path) -> bool:
    appimage = appimage.expanduser().resolve()
    desktop = DESKTOP_DIR / _desktop_filename(appimage)
    removed = False
    if desktop.exists():
        try:
            desktop.unlink()
            removed = True
        except OSError:
            pass
    icon = _icon_filename(appimage)
    if icon and icon.exists():
        try:
            icon.unlink()
            removed = True
        except OSError:
            pass
    if removed:
        try:
            subprocess.run(
                ["update-desktop-database", str(DESKTOP_DIR)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5,
            )
        except Exception:
            pass
    return removed


def integrate_all(entries, overwrite: bool = False) -> int:
    count = 0
    for e in entries:
        p = Path(e.path)
        dest = DESKTOP_DIR / _desktop_filename(p)
        if dest.exists() and not overwrite:
            continue
        try:
            integrate(p)
            count += 1
        except Exception:
            continue
    return count


def _extract_appimage(appimage: Path, dest: Path) -> bool:
    """Try multiple extraction methods. Returns True if extracted."""

    try:
        result = subprocess.run(
            [str(appimage), "--appimage-extract"],
            cwd=str(dest),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=30,
        )
        if result.returncode == 0 and any(dest.iterdir()):
            squash = dest / "squashfs-root"
            if squash.exists():
                for item in squash.iterdir():
                    try:
                        shutil.move(str(item), str(dest / item.name))
                    except OSError:
                        pass
                try:
                    squash.rmdir()
                except OSError:
                    pass
            return True
    except Exception:
        pass

    for tool in ["unsquashfs", "7z"]:
        if shutil.which(tool) is None:
            continue
        try:
            if tool == "unsquashfs":
                result = subprocess.run(
                    [tool, "-d", str(dest), str(appimage)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=30,
                )
            else:
                result = subprocess.run(
                    [tool, "x", str(appimage), f"-o{dest}"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=30,
                )
            if result.returncode == 0 and any(dest.iterdir()):
                return True
        except Exception:
            continue
    return False


def _transform_desktop(content: str, appimage: Path) -> str:
    """Transform extracted desktop file to point to AppImage path."""
    parser = configparser.ConfigParser(interpolation=None)
    parser.optionxform = str
    try:
        parser.read_string(content)
    except Exception:
        return _generate_minimal_desktop(appimage, "")

    if "Desktop Entry" not in parser:
        return _generate_minimal_desktop(appimage, "")

    entry = parser["Desktop Entry"]

    orig_exec = entry.get("Exec", "AppRun")

    args = ""
    for token in ["%F", "%U", "%f", "%u", "%D", "%N"]:
        if token in orig_exec:
            args = token
            break
    new_exec = f"{appimage} {args}".strip()
    entry["Exec"] = new_exec

    if "TryExec" in entry:
        del entry["TryExec"]

    entry["Path"] = str(appimage.parent)

    if "Type" not in entry:
        entry["Type"] = "Application"
    if "Name" not in entry:
        entry["Name"] = appimage.stem
    entry["X-AppImage-Path"] = str(appimage)
    entry["X-AppImage-Integrator"] = "e-applauncher"

    from io import StringIO

    out = StringIO()
    parser.write(out, space_around_delimiters=False)
    text = out.getvalue()

    return text


def _generate_minimal_desktop(appimage: Path, icon_name: str) -> str:
    name = appimage.stem
    icon_line = f"Icon={icon_name}" if icon_name else "Icon=application-x-executable"
    return f"""[Desktop Entry]
Type=Application
Name={name}
Comment=AppImage: {name}
Exec={appimage} %F
{icon_line}
Categories=Utility;
Terminal=false
X-AppImage-Path={appimage}
X-AppImage-Integrator=e-applauncher
"""
