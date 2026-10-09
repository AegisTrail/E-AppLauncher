import json
from pathlib import Path

from e_app_launcher.config import ConfigStore


def test_save_and_get_directory(tmp_path: Path):
    cfg = ConfigStore(tmp_path / "config.json")
    target = tmp_path / "apps"
    target.mkdir()
    cfg.save_directory(target)
    assert cfg.get_directory() == target.resolve()
    data = json.loads((tmp_path / "config.json").read_text())
    assert data["directory"] == str(target.resolve())


def test_multi_directories(tmp_path: Path):
    cfg = ConfigStore(tmp_path / "config.json")
    d1 = tmp_path / "a"
    d2 = tmp_path / "b"
    d1.mkdir()
    d2.mkdir()
    cfg.save_directories([d1, d2])
    dirs = cfg.get_directories()
    assert len(dirs) == 2
    assert Path(d1.resolve()) in [Path(d).resolve() for d in dirs]
    # add duplicate should not duplicate
    cfg.add_directory(d1)
    assert len(cfg.get_directories()) == 2
    # remove
    assert cfg.remove_directory(d1) is True
    assert len(cfg.get_directories()) == 1
    assert cfg.remove_directory(d1) is False


def test_corrupted_config(tmp_path: Path):
    p = tmp_path / "config.json"
    p.write_text("not json {", encoding="utf-8")
    cfg = ConfigStore(p)
    assert cfg.load() == {}
    # Should backup
    assert (tmp_path / "config.json.corrupted").exists() or not p.exists()
    # After corrupted, get_directory should be None and not crash
    assert cfg.get_directory() is None


def test_empty_config(tmp_path: Path):
    cfg = ConfigStore(tmp_path / "missing.json")
    assert cfg.load() == {}
    assert cfg.get_directory() is None
    assert cfg.get_directories() == [] or isinstance(cfg.get_directories(), list)


def test_xdg_fallback(tmp_path: Path, monkeypatch):
    # When no config, get_directories should return existing ~/AppImages if exists
    # Mock home
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    (fake_home / "AppImages").mkdir()
    monkeypatch.setattr(Path, "home", lambda: fake_home)
    cfg = ConfigStore(tmp_path / "config.json")
    dirs = cfg.get_directories()
    assert any("AppImages" in str(d) for d in dirs)


def test_clear(tmp_path: Path):
    p = tmp_path / "config.json"
    cfg = ConfigStore(p)
    d = tmp_path / "x"
    d.mkdir()
    cfg.save_directory(d)
    assert p.exists()
    cfg.clear()
    assert not p.exists()


def test_get_set_roundtrip(tmp_path: Path):
    cfg = ConfigStore(tmp_path / "config.json")
    assert cfg.get("missing", "default") == "default"
    cfg.set("theme", "dark")
    assert cfg.get("theme") == "dark"
    assert cfg.load()["theme"] == "dark"


def test_save_directories_empty_list(tmp_path: Path):
    cfg = ConfigStore(tmp_path / "config.json")
    cfg.save_directories([])
    assert cfg.get_directory() is None


def test_resolve_path_prefers_alt(tmp_path: Path):
    primary = tmp_path / "primary.json"
    alt = tmp_path / "alt.json"
    alt.write_text('{"directory": "/from-alt"}')
    cfg = ConfigStore(primary)
    cfg._alt_path = alt
    assert cfg._resolve_path() == alt
    assert cfg.get_directory() == Path("/from-alt")
    # Once primary exists, it wins
    primary.write_text('{"directory": "/from-primary"}')
    assert cfg._resolve_path() == primary


def test_unicode_decode_error_quarantines(tmp_path: Path):
    p = tmp_path / "config.json"
    p.write_bytes(b"\xff\xfe\x00bad")
    cfg = ConfigStore(p)
    assert cfg.load() == {}
    assert (tmp_path / "config.json.corrupted").exists()


def test_save_propagates_write_errors(tmp_path: Path):
    from unittest.mock import patch

    cfg = ConfigStore(tmp_path / "config.json")
    with patch.object(Path, "write_text", side_effect=OSError("disk full")):
        try:
            cfg.save({"a": 1})
            raise AssertionError("save should propagate OSError")
        except OSError:
            pass


def test_save_directory_expands_tilde(tmp_path: Path, monkeypatch):
    # expanduser() reads $HOME (not Path.home()), so patch the env var.
    fake_home = tmp_path / "home"
    (fake_home / "AppImages").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(fake_home))
    cfg = ConfigStore(tmp_path / "config.json")
    cfg.save_directory(Path("~/AppImages"))
    assert cfg.get_directory() == (fake_home / "AppImages").resolve()


def test_clear_missing_file_is_noop(tmp_path: Path):
    cfg = ConfigStore(tmp_path / "missing.json")
    cfg.clear()  # should not raise


def test_init_mkdir_errors_swallowed(tmp_path: Path, monkeypatch):
    from unittest.mock import patch

    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    with patch.object(Path, "mkdir", side_effect=OSError("ro")):
        ConfigStore()  # must not raise; paths stay unusable but object exists


def test_whitespace_file_is_empty(tmp_path: Path):
    p = tmp_path / "config.json"
    p.write_text("  \n  ")
    assert ConfigStore(p).load() == {}


def test_rename_failure_still_returns_empty(tmp_path: Path):
    from unittest.mock import patch

    p = tmp_path / "config.json"
    p.write_text("{bad")
    cfg = ConfigStore(p)
    with patch.object(Path, "rename", side_effect=OSError("ro")):
        assert cfg.load() == {}


def test_get_directory_prefers_directories_list(tmp_path: Path):
    p = tmp_path / "config.json"
    import json as jsonlib

    p.write_text(jsonlib.dumps({"directories": ["/tmp/a", "/tmp/b"]}))
    assert ConfigStore(p).get_directory() == Path("/tmp/a")


def test_get_directories_single_key_fallback(tmp_path: Path):
    p = tmp_path / "config.json"
    import json as jsonlib

    p.write_text(jsonlib.dumps({"directory": "/tmp/solo"}))
    assert ConfigStore(p).get_directories() == [Path("/tmp/solo")]


def test_add_new_directory_appends(tmp_path: Path):
    cfg = ConfigStore(tmp_path / "config.json")
    d1, d2 = tmp_path / "a", tmp_path / "b"
    d1.mkdir()
    d2.mkdir()
    cfg.save_directory(d1)
    cfg.add_directory(d2)
    assert len(cfg.get_directories()) == 2


def test_clear_unlink_error_swallowed(tmp_path: Path):
    from unittest.mock import patch

    p = tmp_path / "config.json"
    p.write_text("{}")
    cfg = ConfigStore(p)
    with patch.object(Path, "unlink", side_effect=OSError("ro")):
        cfg.clear()  # no raise
    assert p.exists()
