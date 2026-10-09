"""Unit tests for AppImageEntry: display names and (de)serialization."""

import pytest

from e_app_launcher.models import AppImageEntry


def test_effective_display_name_prefers_display():
    e = AppImageEntry(name="foo.AppImage", path="/tmp/foo.AppImage", executable=True, display_name="Foo App")
    assert e.effective_display_name() == "Foo App"


def test_effective_display_name_falls_back_to_name():
    e = AppImageEntry(name="foo.AppImage", path="/tmp/foo.AppImage", executable=True)
    assert e.effective_display_name() == "foo.AppImage"


def test_to_from_dict_roundtrip():
    e = AppImageEntry(
        name="A.AppImage",
        path="/tmp/A.AppImage",
        executable=True,
        size=123,
        mtime=456.0,
        display_name="A",
        comment="c",
        categories="Utility",
        icon="a",
        version="1.0",
        desktop_integrated=True,
    )
    assert AppImageEntry.from_dict(e.to_dict()) == e


def test_from_dict_defaults():
    e = AppImageEntry.from_dict({"name": "A", "path": "/tmp/A"})
    assert e.executable is False
    assert e.size == 0
    assert e.mtime == 0.0
    assert e.desktop_integrated is False
    assert e.effective_display_name() == "A"


def test_from_dict_casts_types():
    e = AppImageEntry.from_dict({"name": "A", "path": "/tmp/A", "size": "10", "mtime": "5", "executable": 1})
    assert e.size == 10
    assert e.mtime == 5.0
    assert e.executable is True


def test_from_dict_garbage_raises():
    # Callers (index load) must skip such items instead of crashing.
    with pytest.raises((ValueError, TypeError)):
        AppImageEntry.from_dict({"name": "A", "path": "/tmp/A", "size": "not-a-number"})
