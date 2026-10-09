from pathlib import Path

import e_app_launcher.paths as paths


def test_xdg_data_home(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    # Reimport to test function
    from e_app_launcher.paths import _xdg_data_home

    assert _xdg_data_home() == tmp_path / "data"


def test_xdg_config_home(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    from e_app_launcher.paths import _xdg_config_home

    assert _xdg_config_home() == tmp_path / "config"


def test_default_paths(monkeypatch):
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    from e_app_launcher.paths import _xdg_config_home, _xdg_data_home

    assert _xdg_data_home() == Path.home() / ".local" / "share"
    assert _xdg_config_home() == Path.home() / ".config"


def test_version_exists():
    assert paths.APP_VERSION
    assert isinstance(paths.APP_VERSION, str)


def test_xdg_empty_string_falls_back(monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", "")
    monkeypatch.setenv("XDG_CONFIG_HOME", "")
    from e_app_launcher.paths import _xdg_config_home, _xdg_data_home

    assert _xdg_data_home() == Path.home() / ".local" / "share"
    assert _xdg_config_home() == Path.home() / ".config"


def test_xdg_tilde_expanded(monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", "~/custom-data")
    from e_app_launcher.paths import _xdg_data_home

    assert _xdg_data_home() == Path.home() / "custom-data"
    assert "~" not in str(_xdg_data_home())


def test_xdg_relative_kept_as_given(monkeypatch):
    # No resolve(): relative values are kept verbatim (callers must handle).
    monkeypatch.setenv("XDG_DATA_HOME", "relative/dir")
    from e_app_launcher.paths import _xdg_data_home

    assert _xdg_data_home() == Path("relative/dir")


def test_constants_layout():
    assert str(paths.CONFIG_PATH).endswith("e-applauncher/config.json")
    assert str(paths.CONFIG_PATH_XDG).endswith("e-applauncher/config.json")
    assert str(paths.INDEX_PATH).endswith("e-applauncher/index.json")
    assert str(paths.DESKTOP_DIR).endswith("applications")
    assert str(paths.ICON_DIR).endswith("icons/hicolor/256x256/apps")
    assert paths.DATA_DIR.name == "e-applauncher"
