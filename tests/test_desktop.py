from pathlib import Path

import pytest

from e_app_launcher.desktop import (
    _desktop_filename,
    _generate_minimal_desktop,
    integrate,
    is_integrated,
    remove_integration,
)


def test_desktop_filename():
    p = Path("/tmp/My App-1.2.AppImage")
    name = _desktop_filename(p)
    assert name.startswith("e-applauncher-")
    assert name.endswith(".desktop")
    assert " " not in name


def test_generate_minimal():
    p = Path("/home/user/AppImages/Foo.AppImage")
    text = _generate_minimal_desktop(p, "foo")
    assert "Name=Foo" in text
    assert f"Exec={p}" in text
    assert "Icon=foo" in text
    assert "Type=Application" in text


def test_integrate_and_remove(tmp_path: Path, monkeypatch):
    # Override DESKTOP_DIR and ICON_DIR to tmp
    import e_app_launcher.desktop as dm
    import e_app_launcher.paths as paths

    desktop_dir = tmp_path / "applications"
    icon_dir = tmp_path / "icons"
    monkeypatch.setattr(dm, "DESKTOP_DIR", desktop_dir)
    monkeypatch.setattr(dm, "ICON_DIR", icon_dir)
    monkeypatch.setattr(paths, "DESKTOP_DIR", desktop_dir)
    # Also need to patch is_integrated check
    app = tmp_path / "Test.AppImage"
    app.write_text("#!/bin/sh\necho hi\n")
    app.chmod(0o755)

    # Integrate should create desktop file
    dest = integrate(app)
    assert dest.exists()
    assert dest.read_text().count("Exec=") >= 1
    # Check is_integrated
    # Need to monkeypatch is_integrated's DESKTOP_DIR too

    # Re-evaluate is_integrated with patched dir
    assert dest.exists()
    # Manually check
    assert (desktop_dir / dest.name).exists()

    # Remove
    assert remove_integration(app) is True
    assert not dest.exists()
    assert remove_integration(app) is False  # second time no file


def test_is_integrated_false(tmp_path: Path, monkeypatch):
    import e_app_launcher.desktop as dm

    monkeypatch.setattr(dm, "DESKTOP_DIR", tmp_path / "nope")
    assert is_integrated(Path("/tmp/Nonexistent.AppImage")) is False


def test_integrate_not_appimage(tmp_path: Path, monkeypatch):
    import e_app_launcher.desktop as dm

    monkeypatch.setattr(dm, "DESKTOP_DIR", tmp_path / "applications")
    monkeypatch.setattr(dm, "ICON_DIR", tmp_path / "icons")
    p = tmp_path / "not.txt"
    p.write_text("hi")
    with pytest.raises(ValueError):
        integrate(p)


def test_transform_desktop(tmp_path: Path):
    from e_app_launcher.desktop import _transform_desktop

    app = Path("/tmp/Foo.AppImage")
    content = """[Desktop Entry]
Name=Foo
Exec=AppRun %F
Icon=foo
Type=Application
"""
    result = _transform_desktop(content, app)
    assert str(app) in result
    assert "X-AppImage-Path" in result


def test_integrate_all_skips_existing_without_overwrite(tmp_path: Path, monkeypatch):
    from unittest.mock import patch

    import e_app_launcher.desktop as dm
    from e_app_launcher.models import AppImageEntry

    desk, icons = tmp_path / "applications", tmp_path / "icons"
    monkeypatch.setattr(dm, "DESKTOP_DIR", desk)
    monkeypatch.setattr(dm, "ICON_DIR", icons)
    apps = []
    for name in ("A.AppImage", "B.AppImage"):
        p = tmp_path / name
        p.write_text("hi")
        p.chmod(0o755)
        apps.append(AppImageEntry(name=name, path=str(p), executable=True))
    pre = desk / dm._desktop_filename(tmp_path / "A.AppImage")
    with patch("shutil.which", return_value=None):
        count = dm.integrate_all(apps)
        assert count == 2
        # Second run: both exist -> skipped
        assert dm.integrate_all(apps) == 0
        # Overwrite forces redo
        assert dm.integrate_all(apps, overwrite=True) == 2
    assert pre.exists()


def test_extract_appimage_empty_dest_is_false(tmp_path: Path):
    from unittest.mock import MagicMock, patch

    import e_app_launcher.desktop as dm

    app = tmp_path / "X.AppImage"
    app.write_text("hi")
    dest = tmp_path / "dest"
    dest.mkdir()
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        # returncode ok but nothing extracted -> False
        assert dm._extract_appimage(app, dest) is False


def test_transform_exec_token_priority():
    from e_app_launcher.desktop import _transform_desktop

    # %F wins over %u regardless of position (token list order).
    out = _transform_desktop("[Desktop Entry]\nName=X\nExec=AppRun %u %F\n", Path("/a/X.AppImage"))
    assert "Exec=/a/X.AppImage %F" in out


def test_transform_preserves_other_keys():
    from e_app_launcher.desktop import _transform_desktop

    content = "[Desktop Entry]\nName=X\nExec=AppRun\nCategories=Audio;\nStartupWMClass=x\n"
    out = _transform_desktop(content, Path("/a/X.AppImage"))
    assert "Categories=Audio;" in out
    assert "StartupWMClass=x" in out
    assert "Path=/a" in out


def test_integrate_survives_chmod_failure(tmp_path: Path, monkeypatch):
    from unittest.mock import patch

    import e_app_launcher.desktop as dm

    monkeypatch.setattr(dm, "DESKTOP_DIR", tmp_path / "applications")
    monkeypatch.setattr(dm, "ICON_DIR", tmp_path / "icons")
    app = tmp_path / "C.AppImage"
    app.write_text("hi")
    app.chmod(0o755)
    with (
        patch("shutil.which", return_value=None),
        patch.object(Path, "chmod", side_effect=OSError("ro")),
    ):
        dest = dm.integrate(app)
    assert dest.exists()


def test_icon_filename_scoped_to_icon_dir():
    from e_app_launcher.desktop import _icon_filename

    dest = _icon_filename(Path("/tmp/a/b.AppImage"))
    assert dest is not None
    assert dest.suffix == ".png"
    assert dest.parent.name == "apps"


def test_integrate_with_extracted_desktop_and_icon(tmp_path: Path, monkeypatch):
    """Happy path: extraction yields a .desktop + icon; both get installed."""
    from unittest.mock import patch

    import e_app_launcher.desktop as dm

    desk, icons = tmp_path / "applications", tmp_path / "icons"
    monkeypatch.setattr(dm, "DESKTOP_DIR", desk)
    monkeypatch.setattr(dm, "ICON_DIR", icons)
    app = tmp_path / "Cool.AppImage"
    app.write_text("hi")
    app.chmod(0o755)

    def fake_extract(appimage, dest):
        (dest / "cool.desktop").write_text(
            "[Desktop Entry]\nName=Cool\nExec=AppRun %F\nIcon=coolicon\nType=Application\n"
        )
        (dest / "coolicon.png").write_bytes(b"\x89PNG-fake")
        return True

    with (
        patch.object(dm, "_extract_appimage", side_effect=fake_extract),
        patch("shutil.which", return_value=None),
        patch("subprocess.run"),
    ):
        dest = dm.integrate(app)
    text = dest.read_text()
    assert f"Exec={app.resolve()} %F" in text
    assert "TryExec" not in text
    installed_icons = list(icons.rglob("*.png"))
    assert len(installed_icons) == 1
    assert "Icon=Cool" in text  # rewritten to installed icon stem
    assert dm.is_integrated(app) is True


def test_extract_flattens_squashfs_root(tmp_path: Path):
    from unittest.mock import MagicMock, patch

    import e_app_launcher.desktop as dm

    app = tmp_path / "X.AppImage"
    app.write_text("hi")
    dest = tmp_path / "dest"
    dest.mkdir()

    def fake_run(argv, **kw):
        squash = dest / "squashfs-root"
        squash.mkdir(exist_ok=True)
        (squash / "app.desktop").write_text("[Desktop Entry]\n")
        return MagicMock(returncode=0)

    with patch("subprocess.run", side_effect=fake_run):
        assert dm._extract_appimage(app, dest) is True
    assert (dest / "app.desktop").exists()
    assert not (dest / "squashfs-root").exists()


def test_transform_adds_missing_type_and_name():
    from e_app_launcher.desktop import _transform_desktop

    out = _transform_desktop("[Desktop Entry]\nExec=AppRun\n", Path("/a/B.AppImage"))
    assert "Type=Application" in out
    assert "Name=B" in out


def test_integrate_dotfile_desktop_ignored(tmp_path: Path, monkeypatch):
    from unittest.mock import patch

    import e_app_launcher.desktop as dm

    monkeypatch.setattr(dm, "DESKTOP_DIR", tmp_path / "applications")
    monkeypatch.setattr(dm, "ICON_DIR", tmp_path / "icons")
    app = tmp_path / "D.AppImage"
    app.write_text("hi")
    app.chmod(0o755)

    def fake_extract(appimage, dest):
        (dest / ".hidden.desktop").write_text("[Desktop Entry]\nName=Hidden\n")
        return True

    with (
        patch.object(dm, "_extract_appimage", side_effect=fake_extract),
        patch("shutil.which", return_value=None),
        patch("subprocess.run"),
    ):
        dest = dm.integrate(app)
    assert "application-x-executable" in dest.read_text()  # minimal fallback, no icon


def test_integrate_desktop_read_failure_falls_back(tmp_path: Path, monkeypatch):
    from unittest.mock import patch

    import e_app_launcher.desktop as dm

    monkeypatch.setattr(dm, "DESKTOP_DIR", tmp_path / "applications")
    monkeypatch.setattr(dm, "ICON_DIR", tmp_path / "icons")
    app = tmp_path / "R.AppImage"
    app.write_text("hi")
    app.chmod(0o755)

    real_read = Path.read_text

    def flaky_read(self, *a, **k):
        if self.name == "r.desktop":
            raise OSError("unreadable")
        return real_read(self, *a, **k)

    def fake_extract(appimage, dest):
        (dest / "r.desktop").write_text("[Desktop Entry]\nName=R\n")
        return True

    with (
        patch.object(dm, "_extract_appimage", side_effect=fake_extract),
        patch("shutil.which", return_value=None),
        patch("subprocess.run"),
        patch.object(Path, "read_text", flaky_read),
    ):
        dest = dm.integrate(app)
    assert "Type=Application" in dest.read_text()


def test_integrate_icon_copy_failure_still_integrates(tmp_path: Path, monkeypatch):
    from unittest.mock import patch

    import e_app_launcher.desktop as dm

    monkeypatch.setattr(dm, "DESKTOP_DIR", tmp_path / "applications")
    monkeypatch.setattr(dm, "ICON_DIR", tmp_path / "icons")
    app = tmp_path / "I.AppImage"
    app.write_text("hi")
    app.chmod(0o755)

    def fake_extract(appimage, dest):
        (dest / "i.desktop").write_text("[Desktop Entry]\nName=I\nExec=AppRun\n")
        (dest / "i.png").write_bytes(b"fake")
        return True

    with (
        patch.object(dm, "_extract_appimage", side_effect=fake_extract),
        patch("shutil.which", return_value=None),
        patch("subprocess.run"),
        patch("shutil.copy2", side_effect=OSError("ro")),
    ):
        dest = dm.integrate(app)
    assert dest.exists()


def test_integrate_survives_cache_tool_failures(tmp_path: Path, monkeypatch):
    from unittest.mock import patch

    import e_app_launcher.desktop as dm

    monkeypatch.setattr(dm, "DESKTOP_DIR", tmp_path / "applications")
    monkeypatch.setattr(dm, "ICON_DIR", tmp_path / "icons")
    app = tmp_path / "T.AppImage"
    app.write_text("hi")
    app.chmod(0o755)
    with (
        patch("shutil.which", return_value=None),
        patch("subprocess.run", side_effect=Exception("no tools")),
    ):
        assert dm.integrate(app).exists()


def test_remove_integration_unlink_errors_swallowed(tmp_path: Path, monkeypatch):
    from unittest.mock import patch

    import e_app_launcher.desktop as dm

    monkeypatch.setattr(dm, "DESKTOP_DIR", tmp_path / "applications")
    monkeypatch.setattr(dm, "ICON_DIR", tmp_path / "icons")
    app = tmp_path / "U.AppImage"
    app.write_text("hi")
    app.chmod(0o755)
    with (
        patch("shutil.which", return_value=None),
        patch("subprocess.run"),
    ):
        dm.integrate(app)
    with patch.object(Path, "unlink", side_effect=OSError("ro")):
        assert dm.remove_integration(app) is False  # nothing removed, no crash


def test_extract_move_and_rmdir_errors_swallowed(tmp_path: Path):
    from unittest.mock import MagicMock, patch

    import e_app_launcher.desktop as dm

    app = tmp_path / "X.AppImage"
    app.write_text("hi")
    dest = tmp_path / "dest"
    dest.mkdir()

    def fake_run(argv, **kw):
        squash = dest / "squashfs-root"
        squash.mkdir(exist_ok=True)
        (squash / "app.desktop").write_text("[Desktop Entry]\n")
        return MagicMock(returncode=0)

    with (
        patch("subprocess.run", side_effect=fake_run),
        patch("shutil.move", side_effect=OSError("busy")),
        patch.object(Path, "rmdir", side_effect=OSError("busy")),
    ):
        assert dm._extract_appimage(app, dest) is True


def test_integrate_icon_only_extraction_uses_minimal_desktop(tmp_path: Path, monkeypatch):
    from unittest.mock import patch

    import e_app_launcher.desktop as dm

    monkeypatch.setattr(dm, "DESKTOP_DIR", tmp_path / "applications")
    monkeypatch.setattr(dm, "ICON_DIR", tmp_path / "icons")
    app = tmp_path / "O.AppImage"
    app.write_text("hi")
    app.chmod(0o755)

    def fake_extract(appimage, dest):
        (dest / "icon.png").write_bytes(b"fake")
        return True

    with (
        patch.object(dm, "_extract_appimage", side_effect=fake_extract),
        patch("shutil.which", return_value=None),
        patch("subprocess.run"),
    ):
        dest = dm.integrate(app)
    text = dest.read_text()
    assert "Type=Application" in text
    assert "Icon=O\n" in text  # icon stem, no extracted desktop to rewrite


def test_remove_then_update_db_failure_swallowed(tmp_path: Path, monkeypatch):
    from unittest.mock import patch

    import e_app_launcher.desktop as dm

    desk, icons = tmp_path / "applications", tmp_path / "icons"
    monkeypatch.setattr(dm, "DESKTOP_DIR", desk)
    monkeypatch.setattr(dm, "ICON_DIR", icons)
    app = tmp_path / "O2.AppImage"
    app.write_text("hi")
    app.chmod(0o755)

    def fake_extract(appimage, dest):
        (dest / "icon.png").write_bytes(b"fake")
        return True

    with (
        patch.object(dm, "_extract_appimage", side_effect=fake_extract),
        patch("shutil.which", return_value=None),
        patch("subprocess.run"),
    ):
        dm.integrate(app)
    assert (icons / "O2.png").exists()
    with patch("subprocess.run", side_effect=Exception("no db tools")):
        assert dm.remove_integration(app) is True
    assert not (desk / dm._desktop_filename(app)).exists()
    assert not (icons / "O2.png").exists()


def test_remove_icon_unlink_error_keeps_going(tmp_path: Path, monkeypatch):
    from unittest.mock import patch

    import e_app_launcher.desktop as dm

    desk, icons = tmp_path / "applications", tmp_path / "icons"
    monkeypatch.setattr(dm, "DESKTOP_DIR", desk)
    monkeypatch.setattr(dm, "ICON_DIR", icons)
    app = tmp_path / "P.AppImage"
    app.write_text("hi")
    app.chmod(0o755)

    def fake_extract(appimage, dest):
        (dest / "icon.png").write_bytes(b"fake")
        return True

    real_unlink = Path.unlink

    def flaky_unlink(self, *args, **kwargs):
        if self.suffix == ".png":
            raise OSError("read-only icon")
        return real_unlink(self, *args, **kwargs)

    with (
        patch.object(dm, "_extract_appimage", side_effect=fake_extract),
        patch("shutil.which", return_value=None),
        patch("subprocess.run"),
    ):
        dm.integrate(app)
    assert (icons / "P.png").exists()
    with (
        patch.object(Path, "unlink", flaky_unlink),
        patch("subprocess.run"),
    ):
        assert dm.remove_integration(app) is True
    assert not (desk / dm._desktop_filename(app)).exists()
    assert (icons / "P.png").exists()  # icon removal failed, desktop still removed


def test_integrate_all_counts_only_new(tmp_path: Path, monkeypatch):
    from unittest.mock import patch

    import e_app_launcher.desktop as dm
    from e_app_launcher.models import AppImageEntry

    monkeypatch.setattr(dm, "DESKTOP_DIR", tmp_path / "applications")
    monkeypatch.setattr(dm, "ICON_DIR", tmp_path / "icons")
    p = tmp_path / "N.AppImage"
    p.write_text("hi")
    p.chmod(0o755)
    entries = [AppImageEntry(name="N.AppImage", path=str(p), executable=True)]
    with (
        patch("shutil.which", return_value=None),
        patch("subprocess.run"),
    ):
        assert dm.integrate_all(entries) == 1
        assert dm.integrate_all(entries) == 0  # now exists: skipped


def test_integrate_all_skips_broken_entries(tmp_path: Path, monkeypatch):
    from unittest.mock import patch

    import e_app_launcher.desktop as dm
    from e_app_launcher.models import AppImageEntry

    monkeypatch.setattr(dm, "DESKTOP_DIR", tmp_path / "applications")
    monkeypatch.setattr(dm, "ICON_DIR", tmp_path / "icons")
    p = tmp_path / "G.AppImage"
    p.write_text("hi")
    p.chmod(0o755)
    entries = [
        AppImageEntry(name="G.AppImage", path=str(p), executable=True),
        AppImageEntry(name="Missing.AppImage", path=str(tmp_path / "Missing.AppImage"), executable=True),
    ]
    with (
        patch("shutil.which", return_value=None),
        patch("subprocess.run"),
    ):
        assert dm.integrate_all(entries) == 1
