import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from e_app_launcher.app import _load_entries, _resolve_directories
from e_app_launcher.config import ConfigStore
from e_app_launcher.index import AppImageIndex


def test_resolve_directories_cli(tmp_path: Path):
    cfg = ConfigStore(tmp_path / "config.json")
    d = tmp_path / "apps"
    d.mkdir()
    result = _resolve_directories([d], cfg)
    assert result[0] == d.resolve()
    # Saved
    assert cfg.get_directory() == d.resolve()


def test_resolve_directories_saved(tmp_path: Path):
    cfg = ConfigStore(tmp_path / "config.json")
    d = tmp_path / "apps"
    d.mkdir()
    cfg.save_directory(d)
    result = _resolve_directories(None, cfg)
    assert result[0] == d.resolve()


def test_resolve_directories_no_config(tmp_path: Path, monkeypatch):
    # Ensure no fallback dirs exist
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: fake_home)
    cfg = ConfigStore(tmp_path / "config.json")
    with pytest.raises(SystemExit, match="No AppImage"):
        _resolve_directories(None, cfg)


def test_load_entries_scan_flag(tmp_path: Path):
    idx = AppImageIndex(tmp_path / "index.json")
    d = tmp_path / "apps"
    d.mkdir()
    (d / "A.AppImage").write_text("hi")
    (d / "A.AppImage").chmod(0o755)
    entries = _load_entries(idx, [d], should_scan=True)
    assert len(entries) == 1


def test_load_entries_cache_hit(tmp_path: Path):
    idx = AppImageIndex(tmp_path / "index.json")
    d = tmp_path / "apps"
    d.mkdir()
    p = d / "A.AppImage"
    p.write_text("hi")
    p.chmod(0o755)
    first = idx.scan(d)
    # Second load should hit cache (no rescan)
    with patch.object(idx, "scan") as mock_scan:
        entries = _load_entries(idx, [d], should_scan=False)
        mock_scan.assert_not_called()
        assert len(entries) == 1


def test_load_entries_stale_detect(tmp_path: Path):
    idx = AppImageIndex(tmp_path / "index.json")
    d = tmp_path / "apps"
    d.mkdir()
    (d / "A.AppImage").write_text("hi")
    (d / "A.AppImage").chmod(0o755)
    idx.scan(d)
    # Add new file -> should rescan
    (d / "B.AppImage").write_text("hi")
    (d / "B.AppImage").chmod(0o755)
    entries = _load_entries(idx, [d], should_scan=False)
    assert len(entries) == 2
    assert {e.name for e in entries} == {"A.AppImage", "B.AppImage"}


def test_load_entries_removed_file(tmp_path: Path):
    idx = AppImageIndex(tmp_path / "index.json")
    d = tmp_path / "apps"
    d.mkdir()
    p = d / "A.AppImage"
    p.write_text("hi")
    p.chmod(0o755)
    idx.scan(d)
    p.unlink()
    entries = _load_entries(idx, [d], should_scan=False)
    assert len(entries) == 0


def test_cli_list_json(tmp_path: Path, capsys):

    d = tmp_path / "apps"
    d.mkdir()
    (d / "X.AppImage").write_text("hi")
    (d / "X.AppImage").chmod(0o755)
    cfg_path = tmp_path / "config.json"
    idx_path = tmp_path / "index.json"
    # Need to patch paths
    with (
        patch("e_app_launcher.app.ConfigStore") as MockCfg,
        patch("e_app_launcher.app.AppImageIndex") as MockIdx,
    ):
        # Use real instances but patched paths
        real_cfg = ConfigStore(cfg_path)
        real_cfg.save_directory(d)
        real_idx = AppImageIndex(idx_path)
        MockCfg.return_value = real_cfg
        MockIdx.return_value = real_idx
        sys.argv = ["e-applauncher", "--list", "--json"]
        # Need to ensure _resolve_directories finds our tmp dir
        # Instead directly test _handle_list
        from rich.console import Console

        from e_app_launcher.app import _handle_list

        console = Console(record=True)
        entries = real_idx.scan(d)
        _handle_list(console, entries, [d], as_json=True)
        # Should not crash


def test_handle_config(tmp_path: Path):
    from rich.console import Console

    from e_app_launcher.app import _handle_config

    cfg = ConfigStore(tmp_path / "config.json")
    idx = AppImageIndex(tmp_path / "index.json")
    console = Console(record=True)
    _handle_config(console, cfg, idx)  # should not crash


def test_recursive_flag(tmp_path: Path):
    idx = AppImageIndex(tmp_path / "index.json")
    d = tmp_path / "apps"
    d.mkdir()
    sub = d / "sub"
    sub.mkdir()
    (sub / "Nested.AppImage").write_text("hi")
    (sub / "Nested.AppImage").chmod(0o755)
    # Without recursive, 0
    entries = _load_entries(idx, [d], should_scan=True, recursive=False)
    assert len(entries) == 0
    # With recursive, 1
    entries = _load_entries(idx, [d], should_scan=True, recursive=True)
    assert len(entries) == 1


# --- main() end-to-end (patched constructors, real tmp instances) ---


def _setup_main(monkeypatch, tmp_path: Path, with_app: bool = True):
    """Patch app constructors to use tmp paths. Returns (real_cfg, real_idx, d)."""
    from e_app_launcher import app as appmod

    d = tmp_path / "apps"
    d.mkdir(exist_ok=True)
    if with_app:
        (d / "A.AppImage").write_text("#!/bin/sh\necho hi\n")
        (d / "A.AppImage").chmod(0o755)
    real_cfg = ConfigStore(tmp_path / "config.json")
    real_idx = AppImageIndex(tmp_path / "index.json")
    monkeypatch.setattr(appmod, "ConfigStore", lambda *a, **k: real_cfg)
    monkeypatch.setattr(appmod, "AppImageIndex", lambda *a, **k: real_idx)
    return real_cfg, real_idx, d


def test_main_list_table(tmp_path: Path, monkeypatch, capsys):
    from e_app_launcher.app import main

    _, _, d = _setup_main(monkeypatch, tmp_path)
    monkeypatch.setattr(sys, "argv", ["e-applauncher", "--dir", str(d), "--list"])
    main()
    out = capsys.readouterr().out
    assert "A.AppImage" in out
    assert "Total: 1 AppImages" in out


def test_main_list_json_content(tmp_path: Path, monkeypatch, capsys):
    import json as jsonlib

    from e_app_launcher.app import main

    _, _, d = _setup_main(monkeypatch, tmp_path)
    monkeypatch.setattr(sys, "argv", ["e-applauncher", "--dir", str(d), "--list", "--json"])
    main()
    out = capsys.readouterr().out
    payload = jsonlib.loads(out[out.index("{") :])
    assert payload["count"] == 1
    assert payload["apps"][0]["name"] == "A.AppImage"
    assert payload["directories"] == [str(d.resolve())]


def test_main_list_empty(tmp_path: Path, monkeypatch, capsys):
    from e_app_launcher.app import main

    _, _, d = _setup_main(monkeypatch, tmp_path, with_app=False)
    monkeypatch.setattr(sys, "argv", ["e-applauncher", "--dir", str(d), "--list"])
    main()
    assert "No AppImages found" in capsys.readouterr().out


def test_main_launch_ok_and_extra_args(tmp_path: Path, monkeypatch, capsys):
    from e_app_launcher import app as appmod
    from e_app_launcher.app import main

    _, _, d = _setup_main(monkeypatch, tmp_path)
    seen = {}

    class FakeLauncher:
        def check_fuse(self):
            return True, "ok"

        def launch_by_name(self, entries, name, extra_args=None):
            seen["extra"] = extra_args
            return entries[0]

    monkeypatch.setattr(appmod, "AppLauncher", lambda *a, **k: FakeLauncher())
    monkeypatch.setattr(sys, "argv", ["e-applauncher", "--dir", str(d), "--launch", "a.appimage", "--", "--help"])
    main()
    assert "Launching" in capsys.readouterr().out
    assert seen["extra"] == ["--help"]


def test_main_launch_unknown_app_exits_1(tmp_path: Path, monkeypatch):
    from e_app_launcher import app as appmod
    from e_app_launcher.app import main
    from e_app_launcher.launcher import LaunchError

    _, _, d = _setup_main(monkeypatch, tmp_path)

    class FakeLauncher:
        def check_fuse(self):
            return True, "ok"

        def launch_by_name(self, entries, name, extra_args=None):
            raise LaunchError("nope")

    monkeypatch.setattr(appmod, "AppLauncher", lambda *a, **k: FakeLauncher())
    monkeypatch.setattr(sys, "argv", ["e-applauncher", "--dir", str(d), "--launch", "Missing"])
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 1


def test_main_forget_removes_only_own_files(tmp_path: Path, monkeypatch, capsys):
    from e_app_launcher import app as appmod
    from e_app_launcher.app import INDEX_PATH, main

    real_cfg, real_idx, d = _setup_main(monkeypatch, tmp_path)
    real_cfg.save_directory(d)
    real_idx.scan(d)
    keeper = tmp_path / "keep.txt"
    keeper.write_text("do not delete")
    monkeypatch.setattr(appmod, "INDEX_PATH", tmp_path / "index.json")
    monkeypatch.setattr(sys, "argv", ["e-applauncher", "--forget"])
    main()
    assert "Cleared" in capsys.readouterr().out
    assert not (tmp_path / "config.json").exists()
    assert not (tmp_path / "index.json").exists()
    assert keeper.exists()
    assert INDEX_PATH is not None  # import sanity


def test_main_integrate_all_and_match(tmp_path: Path, monkeypatch, capsys):
    import e_app_launcher.desktop as dm
    from e_app_launcher.app import main

    _, _, d = _setup_main(monkeypatch, tmp_path)
    monkeypatch.setattr(dm, "DESKTOP_DIR", tmp_path / "applications")
    monkeypatch.setattr(dm, "ICON_DIR", tmp_path / "icons")
    monkeypatch.setattr(sys, "argv", ["e-applauncher", "--dir", str(d), "--integrate"])
    main()
    assert "Integrated 1 AppImages" in capsys.readouterr().out
    monkeypatch.setattr(sys, "argv", ["e-applauncher", "--dir", str(d), "--integrate", "a.app"])
    main()
    assert "Integrated A.AppImage" in capsys.readouterr().out


def test_main_integrate_no_match_exits_1(tmp_path: Path, monkeypatch):
    from e_app_launcher.app import main

    _, _, d = _setup_main(monkeypatch, tmp_path)
    monkeypatch.setattr(sys, "argv", ["e-applauncher", "--dir", str(d), "--integrate", "Nope"])
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 1


def test_main_remove_integration_all_scoped_glob(tmp_path: Path, monkeypatch, capsys):
    import e_app_launcher.desktop as dm
    from e_app_launcher import app as appmod
    from e_app_launcher.app import main

    _, _, d = _setup_main(monkeypatch, tmp_path)
    import e_app_launcher.paths as paths

    desk = tmp_path / "applications"
    desk.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(dm, "DESKTOP_DIR", desk)
    monkeypatch.setattr(dm, "ICON_DIR", tmp_path / "icons")
    monkeypatch.setattr(paths, "DESKTOP_DIR", desk)
    foreign = desk / "other-app.desktop"
    stale = desk / "e-applauncher-stale.desktop"
    foreign.write_text("[Desktop Entry]\nName=Foreign\n")
    stale.write_text("[Desktop Entry]\nName=Stale\n")
    monkeypatch.setattr(sys, "argv", ["e-applauncher", "--dir", str(d), "--remove-integration"])
    main()
    assert "Removed" in capsys.readouterr().out
    assert foreign.exists()  # glob must not touch foreign files
    assert not stale.exists()  # prefixed stale file cleaned


def test_main_remove_integration_no_match_exits_1(tmp_path: Path, monkeypatch):
    from e_app_launcher.app import main

    _, _, d = _setup_main(monkeypatch, tmp_path)
    monkeypatch.setattr(sys, "argv", ["e-applauncher", "--dir", str(d), "--remove-integration", "Nope"])
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 1


def test_main_check_updates(tmp_path: Path, monkeypatch, capsys):
    import e_app_launcher.updates as updates
    from e_app_launcher.app import main

    _, _, d = _setup_main(monkeypatch, tmp_path)
    monkeypatch.setattr(
        updates,
        "check_all",
        lambda entries: [(e, {"has_update_info": False}) for e in entries],
    )
    monkeypatch.setattr(sys, "argv", ["e-applauncher", "--dir", str(d), "--check-updates"])
    main()
    out = capsys.readouterr().out
    assert "Checking for updates" in out
    assert "no update info" in out


def test_main_verbose_warns_without_fuse(tmp_path: Path, monkeypatch, capsys):
    from e_app_launcher import app as appmod
    from e_app_launcher.app import main

    _, _, d = _setup_main(monkeypatch, tmp_path)

    class FakeLauncher:
        def check_fuse(self):
            return False, "no fuse here"

    monkeypatch.setattr(appmod, "AppLauncher", lambda *a, **k: FakeLauncher())
    monkeypatch.setattr(sys, "argv", ["e-applauncher", "--dir", str(d), "--verbose", "--list"])
    main()
    assert "Warning: no fuse here" in capsys.readouterr().out


def test_main_missing_dir_exits_1(tmp_path: Path, monkeypatch):
    from e_app_launcher.app import main

    _setup_main(monkeypatch, tmp_path, with_app=False)
    monkeypatch.setattr(sys, "argv", ["e-applauncher", "--dir", str(tmp_path / "nope"), "--list"])
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 1


def test_main_not_a_dir_exits_1(tmp_path: Path, monkeypatch):
    from e_app_launcher.app import main

    _setup_main(monkeypatch, tmp_path, with_app=False)
    f = tmp_path / "file.txt"
    f.write_text("hi")
    monkeypatch.setattr(sys, "argv", ["e-applauncher", "--dir", str(f), "--list"])
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 1


def test_main_no_configured_dir_exits(tmp_path: Path, monkeypatch):
    from e_app_launcher import app as appmod
    from e_app_launcher.app import main

    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: fake_home)
    real_cfg = ConfigStore(tmp_path / "config.json")
    real_idx = AppImageIndex(tmp_path / "index.json")
    monkeypatch.setattr(appmod, "ConfigStore", lambda *a, **k: real_cfg)
    monkeypatch.setattr(appmod, "AppImageIndex", lambda *a, **k: real_idx)
    monkeypatch.setattr(sys, "argv", ["e-applauncher", "--list"])
    with pytest.raises(SystemExit):
        main()


def test_main_tui_branch_passes_watch_flag(tmp_path: Path, monkeypatch):
    from e_app_launcher import app as appmod
    from e_app_launcher.app import main

    _, _, d = _setup_main(monkeypatch, tmp_path)
    real_cfg = ConfigStore(tmp_path / "config.json")
    real_cfg.save_directory(d)
    seen = {}
    real_idx = AppImageIndex(tmp_path / "index.json")
    monkeypatch.setattr(appmod, "ConfigStore", lambda *a, **k: real_cfg)
    monkeypatch.setattr(appmod, "AppImageIndex", lambda *a, **k: real_idx)

    class FakeTUI:
        def __init__(self, entries, directory, launcher, console, watch):
            seen["watch"] = watch

        def run(self):
            seen["ran"] = True

    monkeypatch.setattr(appmod, "RichTUI", FakeTUI)
    monkeypatch.setattr(sys, "argv", ["e-applauncher", "--watch"])
    main()
    assert seen == {"watch": True, "ran": True}


def test_main_config_flag(tmp_path: Path, monkeypatch, capsys):
    from e_app_launcher.app import main

    _setup_main(monkeypatch, tmp_path, with_app=False)
    monkeypatch.setattr(sys, "argv", ["e-applauncher", "--config"])
    main()
    out = capsys.readouterr().out
    assert "Config path:" in out
    assert "Version:" in out


def test_main_unknown_flags_forwarded_to_launch(tmp_path: Path, monkeypatch, capsys):
    from e_app_launcher import app as appmod
    from e_app_launcher.app import main

    _, _, d = _setup_main(monkeypatch, tmp_path)
    seen = {}

    class FakeLauncher:
        def check_fuse(self):
            return True, "ok"

        def launch_by_name(self, entries, name, extra_args=None):
            seen["extra"] = extra_args
            return entries[0]

    monkeypatch.setattr(appmod, "AppLauncher", lambda *a, **k: FakeLauncher())
    monkeypatch.setattr(sys, "argv", ["e-applauncher", "--dir", str(d), "--launch", "A", "--mystery-flag"])
    main()
    assert seen["extra"] == ["--mystery-flag"]
    assert "Launching" in capsys.readouterr().out


def test_main_recursive_tui_sets_flag(tmp_path: Path, monkeypatch):
    from e_app_launcher import app as appmod
    from e_app_launcher.app import main

    _, _, d = _setup_main(monkeypatch, tmp_path)
    real_cfg = ConfigStore(tmp_path / "config.json")
    real_cfg.save_directory(d)
    real_idx = AppImageIndex(tmp_path / "index.json")
    monkeypatch.setattr(appmod, "ConfigStore", lambda *a, **k: real_cfg)
    monkeypatch.setattr(appmod, "AppImageIndex", lambda *a, **k: real_idx)
    seen = {}

    class FakeTUI:
        def __init__(self, *a, **k):
            seen["tui"] = self

        def run(self):
            seen["ran"] = True

    monkeypatch.setattr(appmod, "RichTUI", FakeTUI)
    monkeypatch.setattr(sys, "argv", ["e-applauncher", "--recursive"])
    main()
    assert seen["ran"] is True
    assert getattr(seen["tui"], "_recursive", False) is True


def test_main_tui_launch_error_exits_1(tmp_path: Path, monkeypatch):
    from e_app_launcher import app as appmod
    from e_app_launcher.app import main
    from e_app_launcher.launcher import LaunchError

    _, _, d = _setup_main(monkeypatch, tmp_path)
    real_cfg = ConfigStore(tmp_path / "config.json")
    real_cfg.save_directory(d)
    real_idx = AppImageIndex(tmp_path / "index.json")
    monkeypatch.setattr(appmod, "ConfigStore", lambda *a, **k: real_cfg)
    monkeypatch.setattr(appmod, "AppImageIndex", lambda *a, **k: real_idx)

    class BoomTUI:
        def __init__(self, *a, **k):
            pass

        def run(self):
            raise LaunchError("tui boom")

    monkeypatch.setattr(appmod, "RichTUI", BoomTUI)
    monkeypatch.setattr(sys, "argv", ["e-applauncher"])
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 1


def test_main_scan_permission_error_exits_1(tmp_path: Path, monkeypatch):
    from unittest.mock import patch

    from e_app_launcher import app as appmod
    from e_app_launcher.app import main

    real_cfg, real_idx, d = _setup_main(monkeypatch, tmp_path)
    real_cfg.save_directory(d)
    monkeypatch.setattr(appmod, "ConfigStore", lambda *a, **k: real_cfg)
    monkeypatch.setattr(appmod, "AppImageIndex", lambda *a, **k: real_idx)
    monkeypatch.setattr(sys, "argv", ["e-applauncher", "--list"])
    with (
        patch.object(AppImageIndex, "scan", side_effect=PermissionError("denied")),
        pytest.raises(SystemExit) as exc,
    ):
        main()
    assert exc.value.code == 1


def test_main_integrate_failure_exits_1(tmp_path: Path, monkeypatch):
    import e_app_launcher.desktop as dm
    from e_app_launcher.app import main

    _, _, d = _setup_main(monkeypatch, tmp_path)
    monkeypatch.setattr(dm, "integrate", lambda p: (_ for _ in ()).throw(RuntimeError("extract boom")))
    monkeypatch.setattr(sys, "argv", ["e-applauncher", "--dir", str(d), "--integrate", "A.App"])
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 1


def test_main_remove_integration_by_existing_path(tmp_path: Path, monkeypatch, capsys):
    from unittest.mock import patch

    import e_app_launcher.desktop as dm
    from e_app_launcher.app import main

    _, _, d = _setup_main(monkeypatch, tmp_path)
    monkeypatch.setattr(dm, "DESKTOP_DIR", tmp_path / "applications")
    monkeypatch.setattr(dm, "ICON_DIR", tmp_path / "icons")
    target = tmp_path / "other.AppImage"
    target.write_text("hi")
    target.chmod(0o755)
    with (
        patch("shutil.which", return_value=None),
        patch("subprocess.run"),
    ):
        dm.integrate(target)  # real integration first
    assert dm.is_integrated(target) is True
    monkeypatch.setattr(sys, "argv", ["e-applauncher", "--dir", str(d), "--remove-integration", str(target)])
    main()
    assert "Removed integration for" in capsys.readouterr().out
    assert dm.is_integrated(target) is False


def test_main_check_updates_with_update_info(tmp_path: Path, monkeypatch, capsys):
    import e_app_launcher.updates as updates
    from e_app_launcher.app import main

    _, _, d = _setup_main(monkeypatch, tmp_path)
    monkeypatch.setattr(
        updates,
        "check_all",
        lambda entries: [(e, {"has_update_info": True, "hint": "zsync"}) for e in entries],
    )
    monkeypatch.setattr(sys, "argv", ["e-applauncher", "--dir", str(d), "--check-updates"])
    main()
    assert "has update info" in capsys.readouterr().out


def test_main_forget_index_unlink_error_swallowed(tmp_path: Path, monkeypatch, capsys):
    from unittest.mock import patch

    from e_app_launcher import app as appmod
    from e_app_launcher.app import main

    real_cfg, _, d = _setup_main(monkeypatch, tmp_path, with_app=False)
    real_cfg.save_directory(d)
    (tmp_path / "index.json").write_text("{}")
    monkeypatch.setattr(appmod, "INDEX_PATH", tmp_path / "index.json")
    with patch.object(Path, "unlink", side_effect=OSError("ro")):
        main_args = ["e-applauncher", "--forget"]
        monkeypatch.setattr(sys, "argv", main_args)
        main()  # OSError swallowed, still reports cleared
    assert "Cleared" in capsys.readouterr().out


def test_resolve_returns_saved_even_if_missing(tmp_path: Path):
    cfg = ConfigStore(tmp_path / "config.json")
    d = tmp_path / "gone"
    cfg.save_directories([d])
    assert d.exists() is False
    assert _resolve_directories(None, cfg) == [d.resolve()]


def test_handle_config_prints_saved_data(tmp_path: Path, capsys):
    from rich.console import Console

    from e_app_launcher.app import _handle_config

    cfg = ConfigStore(tmp_path / "config.json")
    cfg.set("custom", "value")
    idx = AppImageIndex(tmp_path / "index.json")
    _handle_config(Console(record=True), cfg, idx)
    assert "value" in capsys.readouterr().out


def test_handle_remove_integration_name_branches(tmp_path: Path, monkeypatch, capsys):
    from unittest.mock import patch

    from rich.console import Console

    import e_app_launcher.desktop as dm
    from e_app_launcher.app import _handle_remove_integration
    from e_app_launcher.models import AppImageEntry

    desk = tmp_path / "applications"
    monkeypatch.setattr(dm, "DESKTOP_DIR", desk)
    monkeypatch.setattr(dm, "ICON_DIR", tmp_path / "icons")
    p = tmp_path / "A.AppImage"
    p.write_text("hi")
    p.chmod(0o755)
    entries = [AppImageEntry(name="A.AppImage", path=str(p), executable=True)]
    console = Console(record=True)
    with (
        patch("shutil.which", return_value=None),
        patch("subprocess.run"),
    ):
        dm.integrate(p)
        _handle_remove_integration(console, entries, "a.app")
        assert "Removed integration for A.AppImage" in capsys.readouterr().out
        _handle_remove_integration(console, entries, "a.app")
        assert "No integration found for A.AppImage" in capsys.readouterr().out


def test_load_entries_fresh_cache_returns_cached(tmp_path: Path):
    from unittest.mock import patch

    idx = AppImageIndex(tmp_path / "index.json")
    d = tmp_path / "apps"
    d.mkdir()
    (d / "A.AppImage").write_text("hi")
    (d / "A.AppImage").chmod(0o755)
    cached = idx.scan(d)
    with patch.object(idx, "scan") as mock_scan:
        entries = _load_entries(idx, [d], should_scan=False)
        mock_scan.assert_not_called()
        assert [e.name for e in entries] == [e.name for e in cached]


def test_load_entries_version_read_error_migrates(tmp_path: Path):
    from unittest.mock import patch

    idx = AppImageIndex(tmp_path / "index.json")
    d = tmp_path / "apps"
    d.mkdir()
    (d / "A.AppImage").write_text("hi")
    (d / "A.AppImage").chmod(0o755)
    entries = idx.scan(d)
    payload = (tmp_path / "index.json").read_text()
    reads = iter([payload, payload, OSError("denied")])

    def flaky_read_text(self, *a, **k):
        nxt = next(reads)
        if isinstance(nxt, Exception):
            raise nxt
        return nxt

    sentinel = entries
    with (
        patch.object(Path, "read_text", flaky_read_text),
        patch.object(idx, "scan", return_value=sentinel) as mock_scan,
    ):
        assert _load_entries(idx, [d], should_scan=False) is sentinel
        mock_scan.assert_called_once()


def test_load_entries_second_stale_check_disagrees(tmp_path: Path):
    from unittest.mock import patch

    idx = AppImageIndex(tmp_path / "index.json")
    d = tmp_path / "apps"
    d.mkdir()
    (d / "A.AppImage").write_text("hi")
    (d / "A.AppImage").chmod(0o755)
    entries = idx.scan(d)
    with patch.object(idx, "is_stale", side_effect=[True, False]) as mock_stale:
        result = _load_entries(idx, [d], should_scan=False)
        assert [e.name for e in result] == ["A.AppImage"]
        assert mock_stale.call_count == 2


def test_load_entries_stale_checker_raises_falls_through(tmp_path: Path):
    from unittest.mock import patch

    idx = AppImageIndex(tmp_path / "index.json")
    d = tmp_path / "apps"
    d.mkdir()
    (d / "A.AppImage").write_text("hi")
    (d / "A.AppImage").chmod(0o755)
    entries = idx.scan(d)
    with (
        patch.object(idx, "is_stale", side_effect=OSError("racy")),
        patch.object(idx, "scan") as mock_scan,
    ):
        result = _load_entries(idx, [d], should_scan=False)
        mock_scan.assert_not_called()
        assert [e.name for e in result] == [e.name for e in entries]


def test_load_entries_disk_walk_fails_rescans(tmp_path: Path):
    from unittest.mock import patch

    idx = AppImageIndex(tmp_path / "index.json")
    d = tmp_path / "apps"
    d.mkdir()
    (d / "A.AppImage").write_text("hi")
    (d / "A.AppImage").chmod(0o755)
    entries = idx.scan(d)
    with (
        patch.object(idx, "is_stale", side_effect=OSError("racy")),
        patch.object(Path, "iterdir", side_effect=OSError("denied")),
        patch.object(idx, "scan", return_value=entries) as mock_scan,
    ):
        assert _load_entries(idx, [d], should_scan=False) is entries
        mock_scan.assert_called_once()


def test_main_remove_integration_all_counts_entries(tmp_path: Path, monkeypatch, capsys):
    from unittest.mock import patch

    import e_app_launcher.desktop as dm
    import e_app_launcher.paths as paths
    from e_app_launcher.app import main

    _, _, d = _setup_main(monkeypatch, tmp_path)
    desk = tmp_path / "applications"
    monkeypatch.setattr(dm, "DESKTOP_DIR", desk)
    monkeypatch.setattr(dm, "ICON_DIR", tmp_path / "icons")
    monkeypatch.setattr(paths, "DESKTOP_DIR", desk)
    with (
        patch("shutil.which", return_value=None),
        patch("subprocess.run"),
    ):
        dm.integrate(d / "A.AppImage")
    monkeypatch.setattr(sys, "argv", ["e-app-launcher", "--dir", str(d), "--remove-integration"])
    main()
    assert "Removed 1 integrations." in capsys.readouterr().out


def test_main_remove_integration_glob_error_swallowed(tmp_path: Path, monkeypatch, capsys):
    from unittest.mock import patch

    import e_app_launcher.desktop as dm
    import e_app_launcher.paths as paths
    from e_app_launcher.app import main

    _, _, d = _setup_main(monkeypatch, tmp_path)
    desk = tmp_path / "applications"
    desk.mkdir(parents=True, exist_ok=True)
    (desk / "e-applauncher-stale.desktop").write_text("[Desktop Entry]\n")
    monkeypatch.setattr(dm, "DESKTOP_DIR", desk)
    monkeypatch.setattr(dm, "ICON_DIR", tmp_path / "icons")
    monkeypatch.setattr(paths, "DESKTOP_DIR", desk)
    with patch.object(Path, "unlink", side_effect=OSError("ro")):
        monkeypatch.setattr(sys, "argv", ["e-app-launcher", "--dir", str(d), "--remove-integration"])
        main()  # unlink failures are swallowed, count stays 0
    assert "Removed 0 integrations." in capsys.readouterr().out


def test_load_entries_skips_non_directories_in_walk(tmp_path: Path):
    from unittest.mock import patch

    from e_app_launcher.models import AppImageEntry

    idx = AppImageIndex(tmp_path / "index.json")
    d = tmp_path / "apps"
    d.mkdir()
    (d / "A.AppImage").write_text("hi")
    (d / "A.AppImage").chmod(0o755)
    stray = tmp_path / "file.txt"
    stray.write_text("hi")
    real = AppImageEntry(name="A.AppImage", path=str(d / "A.AppImage"), executable=True, size=10, mtime=10)
    ghost = AppImageEntry(
        name="X.AppImage", path=str(tmp_path / "gone" / "X.AppImage"), executable=True, size=10, mtime=10
    )
    idx.save(d, [real, ghost], directories=[d, stray])
    sentinel = [real]
    with (
        patch.object(idx, "is_stale", return_value=False),
        patch.object(idx, "scan", return_value=sentinel) as mock_scan,
    ):
        # is_stale says fresh but a cached path is gone -> manual walk runs,
        # skips the non-directory, finds a name mismatch -> rescan.
        assert _load_entries(idx, [d, stray], should_scan=False) is sentinel
        mock_scan.assert_called_once()


def test_handle_remove_integration_all_empty(tmp_path: Path, monkeypatch, capsys):
    from rich.console import Console

    import e_app_launcher.desktop as dm
    import e_app_launcher.paths as paths
    from e_app_launcher.app import _handle_remove_integration

    desk = tmp_path / "applications"
    desk.mkdir(parents=True)
    # Scope BOTH the removal helper and the stale-file glob to tmp: the glob
    # would otherwise touch the real ~/.local/share/applications.
    monkeypatch.setattr(dm, "DESKTOP_DIR", desk)
    monkeypatch.setattr(paths, "DESKTOP_DIR", desk)
    _handle_remove_integration(Console(record=True), [], "all")
    assert "Removed 0 integrations." in capsys.readouterr().out


def test_handle_list_table_and_empty(tmp_path: Path, capsys):
    from rich.console import Console

    from e_app_launcher.app import _handle_list, _human_size

    d = tmp_path / "apps"
    d.mkdir()
    console = Console(record=True)
    _handle_list(console, [], [d], as_json=False)
    assert "No AppImages found" in capsys.readouterr().out
    assert _human_size(0) == "0 B"
    assert _human_size(1023) == "1023 B"
    assert _human_size(1024) == "1.0K"
    assert _human_size(1024 * 1024) == "1.0M"
    assert _human_size(1024 * 1024 * 1024) == "1.00G"
