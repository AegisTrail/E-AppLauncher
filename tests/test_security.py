"""Security-focused tests: subprocess safety, path handling, deletion scope,
desktop parsing, extraction, truncation, corruption quarantine.
All deterministic: subprocesses and tools are mocked, never executed.
"""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from e_app_launcher import desktop as dm
from e_app_launcher.config import ConfigStore
from e_app_launcher.index import AppImageIndex
from e_app_launcher.launcher import AppLauncher
from e_app_launcher.models import AppImageEntry

SOURCES = list((Path(__file__).parent.parent / "e_app_launcher").glob("*.py"))


def test_no_shell_true_anywhere():
    """Every subprocess call must use argv lists, never shell=True."""
    assert SOURCES, "source dir missing"
    for src in SOURCES:
        text = src.read_text(encoding="utf-8")
        assert "shell=True" not in text, f"{src.name} uses shell=True"


def make_entry(path: Path, **kw) -> AppImageEntry:
    kw.setdefault("executable", True)
    return AppImageEntry(name=path.name, path=str(path), size=100, mtime=0, **kw)


# --- launch argv integrity -------------------------------------------------


def test_launch_argv_is_list_and_injection_stays_single_arg(tmp_path: Path):
    p = tmp_path / "App.AppImage"
    p.write_text("hi")
    p.chmod(0o755)
    launcher = AppLauncher()
    evil = ["; rm -rf /", "--appimage-extract", "$(touch /tmp/x)"]
    with patch("subprocess.Popen") as mock_popen:
        launcher.launch(make_entry(p), extra_args=evil)
        cmd, kwargs = mock_popen.call_args[0][0], mock_popen.call_args[1]
    assert cmd[0] == str(p)
    assert cmd[1:] == evil  # NOT split, NOT interpreted
    assert len(cmd) == 4
    assert "shell" not in kwargs
    assert kwargs["stdin"] is not None  # DEVNULL: no interactive stdin
    assert kwargs["start_new_session"] is True


def test_launch_by_name_first_match_wins_and_only_one_launch(tmp_path: Path):
    a = tmp_path / "Dup-one.AppImage"
    b = tmp_path / "Dup-two.AppImage"
    a.write_text("hi")
    b.write_text("hi")
    entries = [make_entry(a), make_entry(b)]
    launcher = AppLauncher()
    with patch.object(launcher, "launch", return_value=None) as mock_launch:
        result = launcher.launch_by_name(entries, "dup")
        assert result.path == str(a)
        mock_launch.assert_called_once()


# --- desktop filename sanitization ------------------------------------------


def test_desktop_filename_never_escapes_dir():
    for raw in ["a/b.AppImage", "../../evil.AppImage", ".. .. .AppImage", "a b c.AppImage"]:
        name = dm._desktop_filename(Path(f"/tmp/{raw}"))
        assert "/" not in name
        assert "\\" not in name
        assert name.startswith("e-applauncher-")
        assert name.endswith(".desktop")


def test_desktop_filename_all_dots_stem():
    name = dm._desktop_filename(Path("/tmp/....AppImage"))
    assert "/" not in name and name.endswith(".desktop")


def test_integrate_rejects_wrong_suffix_and_missing(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(dm, "DESKTOP_DIR", tmp_path / "apps")
    monkeypatch.setattr(dm, "ICON_DIR", tmp_path / "icons")
    txt = tmp_path / "evil.txt"
    txt.write_text("hi")
    try:
        dm.integrate(txt)
        raise AssertionError("should raise ValueError")
    except ValueError:
        pass
    try:
        dm.integrate(tmp_path / "Missing.AppImage")
        raise AssertionError("should raise FileNotFoundError")
    except FileNotFoundError:
        pass


def test_remove_integration_leaves_foreign_files(tmp_path: Path, monkeypatch):
    desk, icons = tmp_path / "apps", tmp_path / "icons"
    desk.mkdir()
    monkeypatch.setattr(dm, "DESKTOP_DIR", desk)
    monkeypatch.setattr(dm, "ICON_DIR", icons)
    foreign = desk / "someone-else.desktop"
    foreign.write_text("[Desktop Entry]\n")
    app = tmp_path / "Real.AppImage"
    app.write_text("hi")
    assert dm.remove_integration(app) is False
    assert foreign.exists()  # untouched


# --- desktop file parsing ----------------------------------------------------


def test_transform_removes_tryexec_keeps_exec_token():
    content = "[Desktop Entry]\nName=X\nExec=AppRun --opt %U\nTryExec=evil\nIcon=x\nType=Application\n"
    out = dm._transform_desktop(content, Path("/apps/X.AppImage"))
    assert "TryExec" not in out
    assert "Exec=/apps/X.AppImage %U" in out
    assert "X-AppImage-Path=/apps/X.AppImage" in out
    assert "X-AppImage-Integrator=e-applauncher" in out


def test_transform_exec_without_placeholder_gets_none():
    out = dm._transform_desktop("[Desktop Entry]\nName=X\nExec=AppRun\n", Path("/a/X.AppImage"))
    assert "Exec=/a/X.AppImage" in out


def test_transform_corrupt_or_bare_falls_back_to_minimal():
    for bad in ["not ini at all [[[", "[Other]\nFoo=bar\n", ""]:
        out = dm._transform_desktop(bad, Path("/a/X.AppImage"))
        assert "Type=Application" in out
        assert "Exec=/a/X.AppImage" in out


# --- extraction --------------------------------------------------------------


def test_extract_appimage_run_raises_means_false(tmp_path: Path):
    app = tmp_path / "X.AppImage"
    app.write_text("hi")
    with patch("subprocess.run", side_effect=OSError("nope")):
        assert dm._extract_appimage(app, tmp_path / "dest") is False


def test_extract_appimage_bad_returncode_means_false(tmp_path: Path):
    app = tmp_path / "X.AppImage"
    app.write_text("hi")
    with (
        patch("subprocess.run") as mock_run,
        patch("shutil.which", return_value=None),
    ):
        mock_run.return_value.returncode = 1
        assert dm._extract_appimage(app, tmp_path / "dest") is False


def test_extract_falls_back_to_unsquashfs(tmp_path: Path):
    app = tmp_path / "X.AppImage"
    app.write_text("hi")
    dest = tmp_path / "dest"
    dest.mkdir()
    (dest / "seed.txt").write_text("already here")  # any(iterdir()) is True
    calls = []

    def fake_run(argv, **kw):
        calls.append(argv[0])
        m = MagicMock()
        m.returncode = 1 if argv[0] == str(app) else 0
        return m

    def fake_which(tool):
        return "/usr/bin/unsquashfs" if tool == "unsquashfs" else None

    with patch("subprocess.run", side_effect=fake_run), patch("shutil.which", side_effect=fake_which):
        assert dm._extract_appimage(app, dest) is True
    assert calls[0] == str(app)
    assert calls[1] == "unsquashfs"


# --- update output truncation -------------------------------------------------


def test_update_info_output_is_truncated(tmp_path: Path):
    p = tmp_path / "App.AppImage"
    p.write_text("hi")
    p.chmod(0o755)
    entry = AppImageEntry(name="App.AppImage", path=str(p), executable=True)
    big = "UPDATEINFORMATION " + "x" * 2000
    with patch("subprocess.run") as mock_run:
        mock_run.return_value.stdout = big
        mock_run.return_value.stderr = ""
        from e_app_launcher.updates import check_update_info

        result = check_update_info(entry)
    assert result is not None
    assert len(result["output"]) <= 500


def test_update_hint_is_truncated(tmp_path: Path):
    p = tmp_path / "App.AppImage"
    p.write_text("hi")
    p.chmod(0o755)
    entry = AppImageEntry(name="App.AppImage", path=str(p), executable=True)
    long_line = "zsync-url: " + "y" * 1000
    with patch("subprocess.run") as mock_run:
        first = MagicMock()
        first.stdout = "nothing"
        first.stderr = ""
        second = MagicMock()
        second.returncode = 0
        second.stdout = long_line
        mock_run.side_effect = [first, second]
        from e_app_launcher.updates import check_update_info

        result = check_update_info(entry)
    assert result is not None
    assert len(result["hint"]) <= 200


# --- corruption quarantine -----------------------------------------------------


def test_config_quarantine_keeps_existing_backup(tmp_path: Path):
    p = tmp_path / "config.json"
    backup = tmp_path / "config.json.corrupted"
    backup.write_text("original-backup")
    p.write_text("{bad json")
    cfg = ConfigStore(p)
    assert cfg.load() == {}
    assert backup.read_text() == "original-backup"  # not overwritten


def test_index_quarantine_keeps_existing_backup(tmp_path: Path):
    idx_path = tmp_path / "index.json"
    backup = tmp_path / "index.json.corrupted"
    backup.write_text("original-backup")
    idx_path.write_text("{bad json")
    idx = AppImageIndex(idx_path)
    assert idx.load() == (None, [])
    assert backup.read_text() == "original-backup"


def test_index_load_skips_garbage_items(tmp_path: Path):
    idx_path = tmp_path / "index.json"
    payload = {
        "directory": str(tmp_path),
        "version": 2,
        "apps": [
            {"name": "Good.AppImage", "path": "/tmp/Good.AppImage", "executable": True},
            {"name": "Bad.AppImage", "path": "/tmp/Bad.AppImage", "size": "not-a-number"},
            "just-a-string",
            None,
        ],
    }
    idx_path.write_text(json.dumps(payload))
    idx = AppImageIndex(idx_path)
    _, entries = idx.load()
    assert [e.name for e in entries] == ["Good.AppImage"]


def test_config_wrong_types_do_not_crash(tmp_path: Path):
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"directories": "a-string-not-list", "directory": None}))
    cfg = ConfigStore(p)
    assert cfg.get_directory() is None
    p.write_text(json.dumps({"directories": [None, ""]}))
    assert cfg.get_directories() == []


# --- scan side-effect scope -----------------------------------------------------


def test_scan_chmod_only_touches_appimages(tmp_path: Path):
    idx = AppImageIndex(tmp_path / "index.json")
    d = tmp_path / "apps"
    d.mkdir()
    target = d / "A.AppImage"
    target.write_text("hi")
    target.chmod(0o644)
    other = d / "notes.txt"
    other.write_text("hi")
    other.chmod(0o644)
    idx.scan(d)
    import stat

    assert target.stat().st_mode & stat.S_IXUSR
    assert not (other.stat().st_mode & stat.S_IXUSR)  # untouched
