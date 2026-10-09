from __future__ import annotations

import os
from pathlib import Path

APP_NAME = "e-applauncher"


def _xdg_data_home() -> Path:
    xdg = os.getenv("XDG_DATA_HOME")
    if xdg:
        return Path(xdg).expanduser()
    return Path.home() / ".local" / "share"


def _xdg_config_home() -> Path:
    xdg = os.getenv("XDG_CONFIG_HOME")
    if xdg:
        return Path(xdg).expanduser()
    return Path.home() / ".config"


DATA_DIR = _xdg_data_home() / APP_NAME
CONFIG_DIR = _xdg_config_home() / APP_NAME
CONFIG_PATH = DATA_DIR / "config.json"

CONFIG_PATH_XDG = CONFIG_DIR / "config.json"
INDEX_PATH = DATA_DIR / "index.json"


DESKTOP_DIR = _xdg_data_home() / "applications"
ICON_DIR = _xdg_data_home() / "icons" / "hicolor" / "256x256" / "apps"

APP_VERSION = "0.2.0"
