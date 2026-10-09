from pathlib import Path
from unittest.mock import patch

from e_app_launcher.models import AppImageEntry
from e_app_launcher.updates import check_update_info


def test_check_update_no_file(tmp_path: Path):
    e = AppImageEntry(name="A", path=str(tmp_path / "Missing.AppImage"), executable=True)
    assert check_update_info(e) is None


def test_check_update_no_info(tmp_path: Path):
    p = tmp_path / "App.AppImage"
    p.write_text("#!/bin/sh\necho hi\n")
    p.chmod(0o755)
    e = AppImageEntry(name="App.AppImage", path=str(p), executable=True)
    with patch("subprocess.run") as mock_run:
        mock_run.return_value.stdout = "no update here"
        mock_run.return_value.stderr = ""
        mock_run.return_value.returncode = 0
        result = check_update_info(e)
        assert result is not None
        assert result["has_update_info"] is False


def _entry_for(path: Path) -> AppImageEntry:
    return AppImageEntry(name=path.name, path=str(path), executable=True)


def test_has_update_via_appimage_help_stdout(tmp_path: Path):
    from unittest.mock import MagicMock

    p = tmp_path / "App.AppImage"
    p.write_text("hi")
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(stdout="UpdateInformation: zsync|...", stderr="", returncode=0)
        result = check_update_info(_entry_for(p))
    assert result is not None
    assert result["has_update_info"] is True
    assert "output" in result


def test_has_update_via_stderr_only(tmp_path: Path):
    from unittest.mock import MagicMock

    p = tmp_path / "App.AppImage"
    p.write_text("hi")
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(stdout="", stderr="AppImageUpdate available", returncode=0)
        result = check_update_info(_entry_for(p))
    assert result is not None
    assert result["has_update_info"] is True


def test_has_update_via_zsync_strings(tmp_path: Path):
    from unittest.mock import MagicMock

    p = tmp_path / "App.AppImage"
    p.write_text("hi")
    with patch("subprocess.run") as mock_run:
        mock_run.side_effect = [
            MagicMock(stdout="plain help", stderr="", returncode=0),
            MagicMock(stdout="https://example.com/app.zsync\nnoise", stderr="", returncode=0),
        ]
        result = check_update_info(_entry_for(p))
    assert result is not None
    assert result["has_update_info"] is True
    assert "zsync" in result["hint"]


def test_has_update_via_github_update_line(tmp_path: Path):
    from unittest.mock import MagicMock

    p = tmp_path / "App.AppImage"
    p.write_text("hi")
    with patch("subprocess.run") as mock_run:
        mock_run.side_effect = [
            MagicMock(stdout="plain", stderr="", returncode=0),
            MagicMock(stdout="https://github.com/x/y update channel", stderr="", returncode=0),
        ]
        result = check_update_info(_entry_for(p))
    assert result is not None
    assert result["has_update_info"] is True


def test_github_without_update_word_is_no_info(tmp_path: Path):
    from unittest.mock import MagicMock

    p = tmp_path / "App.AppImage"
    p.write_text("hi")
    with patch("subprocess.run") as mock_run:
        mock_run.side_effect = [
            MagicMock(stdout="plain", stderr="", returncode=0),
            MagicMock(stdout="https://github.com/x/y readme", stderr="", returncode=0),
        ]
        result = check_update_info(_entry_for(p))
    assert result is not None
    assert result["has_update_info"] is False


def test_strings_nonzero_returncode_is_no_info(tmp_path: Path):
    from unittest.mock import MagicMock

    p = tmp_path / "App.AppImage"
    p.write_text("hi")
    with patch("subprocess.run") as mock_run:
        mock_run.side_effect = [
            MagicMock(stdout="plain", stderr="", returncode=0),
            MagicMock(stdout="zsync", stderr="", returncode=1),
        ]
        result = check_update_info(_entry_for(p))
    assert result is not None
    assert result["has_update_info"] is False


def test_run_errors_yield_no_info_not_crash(tmp_path: Path):
    p = tmp_path / "App.AppImage"
    p.write_text("hi")
    with patch("subprocess.run", side_effect=OSError("timeout")):
        result = check_update_info(_entry_for(p))
    assert result is not None
    assert result["has_update_info"] is False


def test_check_all_skips_missing_and_aggregates(tmp_path: Path):
    from unittest.mock import MagicMock

    from e_app_launcher.updates import check_all

    good = tmp_path / "Good.AppImage"
    good.write_text("hi")
    missing = AppImageEntry(name="Missing.AppImage", path=str(tmp_path / "Missing.AppImage"), executable=True)
    present = _entry_for(good)
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(stdout="nothing", stderr="", returncode=0)
        results = check_all([missing, present])
    assert len(results) == 1
    assert results[0][0].name == "Good.AppImage"
