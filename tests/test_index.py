import json
import stat
from pathlib import Path

import pytest

from e_app_launcher.index import AppImageIndex


def create_appimage(path: Path, executable: bool = False):
    path.write_text("#!/bin/sh\necho hi\n")
    if not executable:
        path.chmod(0o644)
    else:
        path.chmod(0o755)


def test_scan_basic(tmp_path: Path):
    idx = AppImageIndex(tmp_path / "index.json")
    appdir = tmp_path / "apps"
    appdir.mkdir()
    create_appimage(appdir / "Foo.AppImage")
    create_appimage(appdir / "bar.appimage")
    (appdir / "not.txt").write_text("hi")
    (appdir / "sub").mkdir()
    create_appimage(appdir / "sub" / "Sub.AppImage")

    entries = idx.scan(appdir)
    # Non-recursive should find 2 only
    assert len(entries) == 2
    names = {e.name for e in entries}
    assert "Foo.AppImage" in names
    assert "bar.appimage" in names
    # Should make executable
    for e in entries:
        assert Path(e.path).stat().st_mode & stat.S_IXUSR
        assert e.executable is True
        assert e.size > 0
        assert e.mtime > 0

    # Verify index saved
    data = json.loads((tmp_path / "index.json").read_text())
    assert data["directory"] == str(appdir.resolve())
    assert len(data["apps"]) == 2


def test_scan_recursive(tmp_path: Path):
    idx = AppImageIndex(tmp_path / "index.json")
    appdir = tmp_path / "apps"
    appdir.mkdir()
    sub = appdir / "sub"
    sub.mkdir()
    create_appimage(appdir / "Top.AppImage")
    create_appimage(sub / "Nested.AppImage")
    entries = idx.scan(appdir, recursive=True)
    assert len(entries) == 2
    assert any(e.name == "Nested.AppImage" for e in entries)


def test_scan_case_insensitive(tmp_path: Path):
    idx = AppImageIndex(tmp_path / "index.json")
    appdir = tmp_path / "apps"
    appdir.mkdir()
    create_appimage(appdir / "UPPER.APPIMAGE")
    create_appimage(appdir / "lower.appImage")
    entries = idx.scan(appdir)
    assert len(entries) == 2


def test_scan_symlink(tmp_path: Path):
    idx = AppImageIndex(tmp_path / "index.json")
    appdir = tmp_path / "apps"
    appdir.mkdir()
    real = appdir / "Real.AppImage"
    create_appimage(real)
    link = appdir / "Link.AppImage"
    try:
        link.symlink_to(real)
    except OSError:
        pytest.skip("symlink not supported")
    # Without follow_symlinks, should still find both but deduplicate by resolved path
    entries = idx.scan(appdir, follow_symlinks=False)
    # Depends on dedup logic: both resolve to same file, so 1 entry
    # Our code deduplicates by resolved path, so should be 1
    assert len(entries) == 1


def test_scan_multi_dir(tmp_path: Path):
    idx = AppImageIndex(tmp_path / "index.json")
    d1 = tmp_path / "a"
    d2 = tmp_path / "b"
    d1.mkdir()
    d2.mkdir()
    create_appimage(d1 / "A.AppImage")
    create_appimage(d2 / "B.AppImage")
    entries = idx.scan([d1, d2])
    assert len(entries) == 2


def test_load_corrupted(tmp_path: Path):
    idx = AppImageIndex(tmp_path / "index.json")
    (tmp_path / "index.json").write_text("bad json", encoding="utf-8")
    dirs, entries = idx.load_with_dirs()
    assert entries == []
    # Should backup
    assert (tmp_path / "index.json.corrupted").exists() or not (tmp_path / "index.json").exists()


def test_load_missing(tmp_path: Path):
    idx = AppImageIndex(tmp_path / "missing.json")
    d, e = idx.load()
    assert e == []
    assert d is None


def test_is_stale(tmp_path: Path):
    idx = AppImageIndex(tmp_path / "index.json")
    appdir = tmp_path / "apps"
    appdir.mkdir()
    create_appimage(appdir / "A.AppImage")
    entries = idx.scan(appdir)
    assert idx.is_stale([appdir], entries) is False
    # Add file -> stale
    create_appimage(appdir / "B.AppImage")
    assert idx.is_stale([appdir], entries) is True
    # Remove cached file -> stale
    (appdir / "A.AppImage").unlink()
    assert idx.is_stale([appdir], entries) is True


def test_save_and_load_roundtrip(tmp_path: Path):
    idx = AppImageIndex(tmp_path / "index.json")
    appdir = tmp_path / "apps"
    appdir.mkdir()
    create_appimage(appdir / "Foo.AppImage")
    entries = idx.scan(appdir)
    # Modify entry with display_name
    entries[0].display_name = "Foo App"
    idx.save(appdir, entries)
    _, loaded = idx.load()
    assert loaded[0].display_name == "Foo App"
    assert loaded[0].path == entries[0].path


def test_scan_missing_dir_raises(tmp_path: Path):
    idx = AppImageIndex(tmp_path / "index.json")
    with pytest.raises(FileNotFoundError):
        idx.scan(tmp_path / "nope")


def test_scan_not_a_dir_raises(tmp_path: Path):
    idx = AppImageIndex(tmp_path / "index.json")
    f = tmp_path / "file.txt"
    f.write_text("hi")
    with pytest.raises(NotADirectoryError):
        idx.scan(f)


def test_scan_broken_symlink_skipped(tmp_path: Path):
    idx = AppImageIndex(tmp_path / "index.json")
    appdir = tmp_path / "apps"
    appdir.mkdir()
    create_appimage(appdir / "Real.AppImage")
    link = appdir / "Ghost.AppImage"
    try:
        link.symlink_to(appdir / "Missing.AppImage")
    except OSError:
        pytest.skip("symlink not supported")
    entries = idx.scan(appdir)
    assert {e.name for e in entries} == {"Real.AppImage"}


def test_scan_duplicate_names_in_different_dirs_kept(tmp_path: Path):
    idx = AppImageIndex(tmp_path / "index.json")
    d1, d2 = tmp_path / "a", tmp_path / "b"
    d1.mkdir()
    d2.mkdir()
    create_appimage(d1 / "Dup.AppImage")
    create_appimage(d2 / "Dup.AppImage")
    entries = idx.scan([d1, d2])
    assert len(entries) == 2
    assert entries[0].path != entries[1].path


def test_scan_unwritable_symlink_keeps_target_exec_bit(tmp_path: Path):
    from unittest.mock import patch

    idx = AppImageIndex(tmp_path / "index.json")
    d = tmp_path / "apps"
    d.mkdir()
    real = d / "Real.AppImage"
    create_appimage(real)  # 644: forces the auto-chmod path
    link = d / "Link.AppImage"
    try:
        link.symlink_to(real)
    except OSError:
        pytest.skip("symlink not supported")
    real_chmod = Path.chmod

    def flaky_chmod(self, mode, *args, **kwargs):
        if self.is_symlink():
            raise OSError("read-only link")
        return real_chmod(self, mode, *args, **kwargs)

    with patch.object(Path, "chmod", flaky_chmod):
        entries = idx.scan(d)
    # Link sorts first and dedups the target; its own chmod failed quietly.
    assert len(entries) == 1
    assert entries[0].executable is True


def test_scan_follow_symlinks_includes_link(tmp_path: Path):
    idx = AppImageIndex(tmp_path / "index.json")
    appdir = tmp_path / "apps"
    appdir.mkdir()
    real = appdir / "Real.AppImage"
    create_appimage(real, executable=True)
    link = appdir / "Link.AppImage"
    try:
        link.symlink_to(real)
    except OSError:
        pytest.skip("symlink not supported")
    entries = idx.scan(appdir, follow_symlinks=True)
    # Same target dedups to one entry
    assert len(entries) == 1


def test_scan_iterdir_permission_error_propagates(tmp_path: Path):
    from unittest.mock import patch

    idx = AppImageIndex(tmp_path / "index.json")
    d = tmp_path / "apps"
    d.mkdir()
    with patch.object(Path, "iterdir", side_effect=PermissionError("denied")), pytest.raises(PermissionError):
        idx.scan(d)


def test_init_mkdir_error_swallowed(tmp_path: Path):
    from unittest.mock import patch

    with patch.object(Path, "mkdir", side_effect=OSError("ro")):
        AppImageIndex(tmp_path / "index.json")  # must not raise


def test_scan_unresolvable_symlink_skipped(tmp_path: Path):
    from unittest.mock import patch

    idx = AppImageIndex(tmp_path / "index.json")
    d = tmp_path / "apps"
    d.mkdir()
    create_appimage(d / "Real.AppImage")
    link = d / "Link.AppImage"
    try:
        link.symlink_to(d / "Real.AppImage")
    except OSError:
        pytest.skip("symlink not supported")
    real_resolve = Path.resolve

    def flaky_resolve(self, *args, **kwargs):
        if self.name == "Link.AppImage":
            raise OSError("racy fs")
        return real_resolve(self, *args, **kwargs)

    with patch.object(Path, "resolve", flaky_resolve):
        entries = idx.scan(d)
    assert {e.name for e in entries} == {"Real.AppImage"}


def test_scan_access_error_falls_back_to_chmod(tmp_path: Path):
    import os
    from unittest.mock import patch

    idx = AppImageIndex(tmp_path / "index.json")
    d = tmp_path / "apps"
    d.mkdir()
    create_appimage(d / "A.AppImage")
    with patch("os.access", side_effect=OSError("denied")):
        entries = idx.scan(d)
    assert entries[0].executable is True
    import stat as statmod

    assert (d / "A.AppImage").stat().st_mode & statmod.S_IXUSR


def test_scan_unwritable_target_marks_not_executable(tmp_path: Path):
    from unittest.mock import patch

    idx = AppImageIndex(tmp_path / "index.json")
    d = tmp_path / "apps"
    d.mkdir()
    create_appimage(d / "A.AppImage")
    with patch.object(Path, "chmod", side_effect=OSError("ro")):
        entries = idx.scan(d)
    assert entries[0].executable is False


def test_scan_stat_race_gives_zero_size(tmp_path: Path):
    idx = AppImageIndex(tmp_path / "index.json")
    d = tmp_path / "apps"
    d.mkdir()
    create_appimage(d / "A.AppImage", executable=True)
    real_stat = Path.stat
    calls = {"n": 0}

    def flaky_stat(self, *args, **kwargs):
        # is_symlink/is_file/resolve stats succeed (calls 1-3); only the
        # size stat races (call 4). pathlib routes all of these through
        # Path.stat, verified empirically.
        if self.suffix.lower() == ".appimage":
            calls["n"] += 1
            if calls["n"] >= 4:
                raise OSError("racy")
        return real_stat(self, *args, **kwargs)

    from unittest.mock import patch

    with patch.object(Path, "stat", flaky_stat), patch("os.access", return_value=True):
        entries = idx.scan(d)
    assert calls["n"] >= 4
    assert entries[0].size == 0
    assert entries[0].mtime == 0.0


def test_scan_entry_construction_error_skips_file(tmp_path: Path):
    from unittest.mock import patch

    import e_app_launcher.index as indexmod

    idx = AppImageIndex(tmp_path / "index.json")
    d = tmp_path / "apps"
    d.mkdir()
    create_appimage(d / "A.AppImage")
    with patch.object(indexmod, "AppImageEntry", side_effect=OSError("bad row")):
        assert idx.scan(d) == []


def test_is_stale_missing_but_same_name_is_stale(tmp_path: Path):
    from unittest.mock import patch

    idx = AppImageIndex(tmp_path / "index.json")
    d = tmp_path / "apps"
    d.mkdir()
    create_appimage(d / "A.AppImage")
    entries = idx.scan(d)
    # Disk still shows the name, but every cached path is gone.
    with patch.object(Path, "exists", return_value=False):
        assert idx.is_stale([d], entries) is True


def test_is_stale_missing_dir_counts_as_empty(tmp_path: Path):
    idx = AppImageIndex(tmp_path / "index.json")
    assert idx.is_stale([tmp_path / "nope"], []) is False


def test_save_multi_dir_payload(tmp_path: Path):
    import json as jsonlib

    idx = AppImageIndex(tmp_path / "index.json")
    d1, d2 = tmp_path / "a", tmp_path / "b"
    d1.mkdir()
    d2.mkdir()
    create_appimage(d1 / "A.AppImage")
    entries = idx.scan([d1, d2])
    payload = jsonlib.loads((tmp_path / "index.json").read_text())
    assert payload["version"] == 2
    assert {d1.resolve(), d2.resolve()} == {Path(p).resolve() for p in payload["directories"]}
    assert len(entries) == 1
    dirs, loaded = idx.load_with_dirs()
    assert [d.resolve() for d in dirs] == [d1.resolve(), d2.resolve()]
    assert [e.name for e in loaded] == ["A.AppImage"]


def test_load_with_dirs_prefers_directories_list(tmp_path: Path):
    idx = AppImageIndex(tmp_path / "index.json")
    d = tmp_path / "apps"
    d.mkdir()
    create_appimage(d / "A.AppImage")
    entries = idx.scan(d)
    dirs, loaded = idx.load_with_dirs()
    assert dirs == [d.resolve()]
    assert [e.name for e in loaded] == [e.name for e in entries]


def test_version_migration_triggers_rescan(tmp_path: Path):
    from unittest.mock import patch

    from e_app_launcher.app import _load_entries

    idx = AppImageIndex(tmp_path / "index.json")
    d = tmp_path / "apps"
    d.mkdir()
    create_appimage(d / "A.AppImage")
    entries = idx.scan(d)
    # Downgrade payload version -> next load must rescan
    import json as jsonlib

    payload = jsonlib.loads((tmp_path / "index.json").read_text())
    payload["version"] = 1
    (tmp_path / "index.json").write_text(jsonlib.dumps(payload))
    sentinel = [entries[0]]
    with patch.object(idx, "scan", return_value=sentinel) as mock_scan:
        assert _load_entries(idx, [d], should_scan=False) is sentinel
        mock_scan.assert_called_once()


def test_is_stale_misses_recursive_subdir_change(tmp_path: Path):
    # Known limitation: is_stale only looks at top-level names.
    idx = AppImageIndex(tmp_path / "index.json")
    d = tmp_path / "apps"
    sub = d / "sub"
    sub.mkdir(parents=True)
    create_appimage(d / "A.AppImage")
    entries = idx.scan(d, recursive=True)
    create_appimage(sub / "New.AppImage")
    assert idx.is_stale([d], entries) is False


def test_scan_marks_not_integrated_when_check_raises(tmp_path: Path):
    from unittest.mock import patch

    import e_app_launcher.desktop as dm

    idx = AppImageIndex(tmp_path / "index.json")
    d = tmp_path / "apps"
    d.mkdir()
    create_appimage(d / "A.AppImage")
    with patch.object(dm, "is_integrated", side_effect=RuntimeError("db gone")):
        entries = idx.scan(d)
    assert entries[0].desktop_integrated is False


def test_load_empty_and_whitespace(tmp_path: Path):
    idx = AppImageIndex(tmp_path / "index.json")
    (tmp_path / "index.json").write_text("")
    assert idx.load() == (None, [])
    assert idx.load_with_dirs() == ([], [])
    (tmp_path / "index.json").write_text("  \n ")
    assert idx.load() == (None, [])
    assert idx.load_with_dirs() == ([], [])


def test_load_with_dirs_falls_back_to_single_directory(tmp_path: Path):
    import json as jsonlib

    idx = AppImageIndex(tmp_path / "index.json")
    d = tmp_path / "apps"
    d.mkdir()
    (tmp_path / "index.json").write_text(jsonlib.dumps({"directory": str(d), "apps": []}))
    dirs, entries = idx.load_with_dirs()
    assert dirs == [d]
    assert entries == []


def test_load_rename_failure_still_returns_empty(tmp_path: Path):
    from unittest.mock import patch

    (tmp_path / "index.json").write_text("{bad")
    idx = AppImageIndex(tmp_path / "index.json")
    with patch.object(Path, "rename", side_effect=OSError("ro")):
        assert idx.load() == (None, [])


def test_is_stale_iterdir_error_means_stale(tmp_path: Path):
    from unittest.mock import patch

    idx = AppImageIndex(tmp_path / "index.json")
    d = tmp_path / "apps"
    d.mkdir()
    create_appimage(d / "A.AppImage")
    entries = idx.scan(d)
    with patch.object(Path, "iterdir", side_effect=OSError("denied")):
        assert idx.is_stale([d], entries) is True
