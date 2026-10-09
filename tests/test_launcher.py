from pathlib import Path
from unittest.mock import patch

import pytest

from e_app_launcher.launcher import AppLauncher
from e_app_launcher.models import AppImageEntry


def make_entry(path: Path) -> AppImageEntry:
    return AppImageEntry(name=path.name, path=str(path), executable=True, size=100, mtime=0)


def test_validate_exists(tmp_path: Path):
    p = tmp_path / "App.AppImage"
    p.write_text("hi")
    p.chmod(0o755)
    launcher = AppLauncher()
    e = make_entry(p)
    launcher.validate_entry(e)  # should not raise


def test_validate_missing(tmp_path: Path):
    launcher = AppLauncher()
    e = AppImageEntry(name="Missing.AppImage", path=str(tmp_path / "Missing.AppImage"), executable=True)
    with pytest.raises(FileNotFoundError):
        launcher.validate_entry(e)


def test_validate_not_executable(tmp_path: Path):
    p = tmp_path / "App.AppImage"
    p.write_text("hi")
    p.chmod(0o644)
    # os.access may still return True for root; mock it
    launcher = AppLauncher()
    e = make_entry(p)
    with patch("os.access", return_value=False), pytest.raises(PermissionError):
        launcher.validate_entry(e)


def test_launch_by_name_exact(tmp_path: Path):
    p1 = tmp_path / "Foo.AppImage"
    p2 = tmp_path / "Bar.AppImage"
    p1.write_text("hi")
    p2.write_text("hi")
    entries = [make_entry(p1), make_entry(p2)]
    launcher = AppLauncher()
    with patch.object(launcher, "launch", return_value=None) as mock_launch:
        result = launcher.launch_by_name(entries, "Foo.AppImage")
        assert result.name == "Foo.AppImage"
        mock_launch.assert_called_once()


def test_launch_by_name_casefold(tmp_path: Path):
    p = tmp_path / "Foo.AppImage"
    p.write_text("hi")
    entries = [make_entry(p)]
    launcher = AppLauncher()
    with patch.object(launcher, "launch", return_value=None):
        result = launcher.launch_by_name(entries, "foo.appimage")
        assert result.name == "Foo.AppImage"


def test_launch_by_name_fuzzy(tmp_path: Path):
    p = tmp_path / "MyCoolApp-1.2.AppImage"
    p.write_text("hi")
    entries = [make_entry(p)]
    launcher = AppLauncher()
    with patch.object(launcher, "launch", return_value=None):
        result = launcher.launch_by_name(entries, "coolapp")
        assert result.name == "MyCoolApp-1.2.AppImage"


def test_launch_by_name_not_found(tmp_path: Path):
    launcher = AppLauncher()
    with pytest.raises(FileNotFoundError):
        launcher.launch_by_name([], "Missing.AppImage")


def test_check_fuse(monkeypatch):
    launcher = AppLauncher()
    monkeypatch.setattr("shutil.which", lambda x: "/usr/bin/fusermount" if "fusermount" in x else None)
    # Mock /dev/fuse exists

    orig_exists = Path.exists

    def fake_exists(self):
        if str(self) == "/dev/fuse":
            return True
        return orig_exists(self)

    monkeypatch.setattr(Path, "exists", fake_exists)
    ok, msg = launcher.check_fuse()
    assert ok is True


def test_launch_with_extra_args(tmp_path: Path):
    p = tmp_path / "App.AppImage"
    p.write_text("#!/bin/sh\necho hi\n")
    p.chmod(0o755)
    launcher = AppLauncher()
    e = make_entry(p)
    with patch("subprocess.Popen") as mock_popen:
        launcher.launch(e, extra_args=["--help"])
        args = mock_popen.call_args[0][0]
        assert args[0] == str(p)
        assert "--help" in args


def test_get_launch_command(tmp_path: Path):
    launcher = AppLauncher()
    e = AppImageEntry(name="A", path="/tmp/A.AppImage", executable=True)
    assert launcher.get_launch_command(e) == ["/tmp/A.AppImage"]
    assert launcher.get_launch_command(e, ["--help"]) == ["/tmp/A.AppImage", "--help"]
    assert launcher.get_launch_command(e, None) == ["/tmp/A.AppImage"]


def test_launch_dry_run_validates_but_does_not_spawn(tmp_path: Path):
    p = tmp_path / "App.AppImage"
    p.write_text("hi")
    p.chmod(0o755)
    launcher = AppLauncher()
    with patch("subprocess.Popen") as mock_popen:
        assert launcher.launch(make_entry(p), dry_run=True) is None
        mock_popen.assert_not_called()


def test_launch_dry_run_still_validates(tmp_path: Path):
    launcher = AppLauncher()
    e = AppImageEntry(name="Missing.AppImage", path=str(tmp_path / "Missing.AppImage"), executable=True)
    with pytest.raises(FileNotFoundError):
        launcher.launch(e, dry_run=True)


def test_launch_oserror_mentions_fuse_when_missing(tmp_path: Path, monkeypatch):
    p = tmp_path / "App.AppImage"
    p.write_text("hi")
    p.chmod(0o755)
    launcher = AppLauncher()
    monkeypatch.setattr("shutil.which", lambda _: None)

    orig_exists = Path.exists

    def fake_exists(self):
        if str(self) == "/dev/fuse":
            return False
        return orig_exists(self)

    monkeypatch.setattr(Path, "exists", fake_exists)
    from e_app_launcher.launcher import LaunchError

    with patch("subprocess.Popen", side_effect=OSError("boom")), pytest.raises(LaunchError) as exc:
        launcher.launch(make_entry(p))
    assert "FUSE" in str(exc.value) or "fuse" in str(exc.value).lower()


def test_launch_oserror_plain_when_fuse_ok(tmp_path: Path, monkeypatch):
    p = tmp_path / "App.AppImage"
    p.write_text("hi")
    p.chmod(0o755)
    launcher = AppLauncher()
    monkeypatch.setattr("shutil.which", lambda x: "/usr/bin/fusermount" if "fusermount" in x else None)
    orig_exists = Path.exists

    def fake_exists(self):
        if str(self) == "/dev/fuse":
            return True
        return orig_exists(self)

    monkeypatch.setattr(Path, "exists", fake_exists)
    from e_app_launcher.launcher import LaunchError

    with patch("subprocess.Popen", side_effect=OSError("boom")), pytest.raises(LaunchError) as exc:
        launcher.launch(make_entry(p))
    assert "Failed to launch App.AppImage: boom" in str(exc.value)


def test_validate_directory_is_not_a_file(tmp_path: Path):
    launcher = AppLauncher()
    e = make_entry(tmp_path)  # a directory, not a file
    with pytest.raises(FileNotFoundError):
        launcher.validate_entry(e)


def test_launch_by_name_display_name_fallback(tmp_path: Path):
    p = tmp_path / "Zqx9.AppImage"
    p.write_text("hi")
    e = make_entry(p)
    e.display_name = "Cool Editor"
    launcher = AppLauncher()
    with patch.object(launcher, "launch", return_value=None):
        assert launcher.launch_by_name([e], "cool editor").path == str(p)


def test_check_fuse_missing_fusermount_message(monkeypatch):
    launcher = AppLauncher()
    monkeypatch.setattr("shutil.which", lambda _: None)
    orig_exists = Path.exists

    def fake_exists(self):
        if str(self) == "/dev/fuse":
            return True
        return orig_exists(self)

    monkeypatch.setattr(Path, "exists", fake_exists)
    ok, msg = launcher.check_fuse()
    assert ok is False
    assert "fusermount" in msg


def test_check_fuse_no_dev_fuse_message(monkeypatch):
    launcher = AppLauncher()
    monkeypatch.setattr("shutil.which", lambda _: "/usr/bin/fusermount")
    orig_exists = Path.exists

    def fake_exists(self):
        if str(self) == "/dev/fuse":
            return False
        return orig_exists(self)

    monkeypatch.setattr(Path, "exists", fake_exists)
    ok, msg = launcher.check_fuse()
    assert ok is False
    assert "/dev/fuse" in msg
