from pathlib import Path
from unittest.mock import MagicMock

import pytest

from e_app_launcher import tui as tui_module
from e_app_launcher.models import AppImageEntry
from e_app_launcher.tui import RichTUI

TextualTUI = tui_module.TextualTUI

needs_textual = pytest.mark.skipif(not tui_module.HAS_TEXTUAL, reason="textual not installed")


def make_textual(entries, directory=Path("/tmp"), sort_mode="name"):
    app = TextualTUI(entries=list(entries), directory=directory, launcher=MagicMock(), sort_mode=sort_mode)
    app._filtered = list(entries)
    return app


def make_entry(name, path="/tmp/foo"):
    return AppImageEntry(name=name, path=f"{path}/{name}", executable=True, size=1000, mtime=1000)


def test_filtered_sorted_name():
    tui = RichTUI(entries=[], directory=Path("/tmp"), launcher=MagicMock())
    tui.entries = [make_entry("Z.AppImage"), make_entry("A.AppImage"), make_entry("M.AppImage")]
    tui.sort_mode = "name"
    tui.filter_text = ""
    result = tui._filtered_sorted()
    assert [r.name for r in result] == ["A.AppImage", "M.AppImage", "Z.AppImage"]


def test_filtered_sorted_size():
    tui = RichTUI(entries=[], directory=Path("/tmp"), launcher=MagicMock())
    tui.entries = [
        AppImageEntry(name="A.AppImage", path="/tmp/A", executable=True, size=100, mtime=0),
        AppImageEntry(name="B.AppImage", path="/tmp/B", executable=True, size=300, mtime=0),
        AppImageEntry(name="C.AppImage", path="/tmp/C", executable=True, size=200, mtime=0),
    ]
    tui.sort_mode = "size"
    result = tui._filtered_sorted()
    assert result[0].name == "B.AppImage"


def test_filter():
    tui = RichTUI(entries=[], directory=Path("/tmp"), launcher=MagicMock())
    # Use distinct paths without 'foo' to test name filtering only
    tui.entries = [
        AppImageEntry(name="Foo.AppImage", path="/tmp/a/Foo.AppImage", executable=True, size=1000, mtime=1000),
        AppImageEntry(name="Bar.AppImage", path="/tmp/a/Bar.AppImage", executable=True, size=1000, mtime=1000),
        AppImageEntry(
            name="FooBar.AppImage",
            path="/tmp/a/FooBar.AppImage",
            executable=True,
            size=1000,
            mtime=1000,
        ),
    ]
    tui.filter_text = "foo"
    result = tui._filtered_sorted()
    assert len(result) == 2
    assert all("foo" in r.name.lower() for r in result)


def test_filter_comment():
    tui = RichTUI(entries=[], directory=Path("/tmp"), launcher=MagicMock())
    e = AppImageEntry(name="A.AppImage", path="/tmp/A", executable=True, comment="My Comment")
    tui.entries = [e]
    tui.filter_text = "my comment"
    result = tui._filtered_sorted()
    assert len(result) == 1


def test_human_size():
    tui = RichTUI(entries=[], directory=Path("/tmp"), launcher=MagicMock())
    assert tui._human_size(500) == "500 B"
    assert tui._human_size(2048) == "2.0K"
    assert "M" in tui._human_size(2 * 1024 * 1024)
    assert "G" in tui._human_size(2 * 1024 * 1024 * 1024)


def test_multi_dir():
    tui = RichTUI(entries=[], directory=[Path("/tmp/a"), Path("/tmp/b")], launcher=MagicMock())
    assert tui.directory == [Path("/tmp/a"), Path("/tmp/b")]
    assert tui.primary_dir == Path("/tmp/a")


class FakeTTY:
    """Minimal tty stand-in: isatty() plus a writable buffer."""

    def __init__(self, tty: bool):
        import io

        self._tty = tty
        self.buf = io.StringIO()

    def isatty(self):
        return self._tty

    def write(self, text):
        return self.buf.write(text)

    def flush(self):
        pass

    def fileno(self):
        return 0


def test_run_non_tty_raises_system_exit(monkeypatch):
    import sys

    from e_app_launcher.tui import RichTUI

    monkeypatch.setattr(sys, "stdin", FakeTTY(False))
    monkeypatch.setattr(sys, "stdout", FakeTTY(False))
    tui = RichTUI(entries=[], directory=Path("/tmp"), launcher=MagicMock())
    with pytest.raises(SystemExit, match="interactive terminal"):
        tui.run()


def test_run_textual_error_falls_back_to_rich(monkeypatch):
    import sys

    import e_app_launcher.tui as tuimod

    monkeypatch.setattr(sys, "stdin", FakeTTY(True))
    monkeypatch.setattr(sys, "stdout", FakeTTY(True))

    class BrokenApp:
        def __init__(self, *a, **k):
            pass

        def run(self):
            raise RuntimeError("textual exploded")

    monkeypatch.setattr(tuimod, "TextualTUI", BrokenApp)
    tui = tuimod.RichTUI(entries=[], directory=Path("/tmp"), launcher=MagicMock())
    monkeypatch.setattr(tuimod.RichTUI, "_run_rich", lambda self: "fallback-ok")
    assert tui.run() == "fallback-ok"


def test_run_textual_clean_exit_returns_none(monkeypatch):
    import sys

    import e_app_launcher.tui as tuimod

    monkeypatch.setattr(sys, "stdin", FakeTTY(True))
    monkeypatch.setattr(sys, "stdout", FakeTTY(True))

    class CleanApp:
        def __init__(self, *a, **k):
            self.launched_entry = None

        def run(self):
            return None  # user quit without launching

    monkeypatch.setattr(tuimod, "TextualTUI", CleanApp)
    tui = tuimod.RichTUI(entries=[], directory=Path("/tmp"), launcher=MagicMock())
    assert tui.run() is None


def test_rich_filtered_sorted_unknown_mode_passes_through():
    tui = RichTUI(entries=[], directory=Path("/tmp"), launcher=MagicMock())
    tui.entries = [make_entry("B.AppImage"), make_entry("A.AppImage")]
    tui.sort_mode = "bogus"
    assert [r.name for r in tui._filtered_sorted()] == ["B.AppImage", "A.AppImage"]


def test_rich_watch_callback_error_keeps_entries(tmp_path: Path, monkeypatch):
    import e_app_launcher.index as indexmod
    import e_app_launcher.watcher as watchmod
    from e_app_launcher.models import AppImageEntry

    d = tmp_path / "apps"
    d.mkdir()
    before = [AppImageEntry(name="O.AppImage", path=str(d / "O.AppImage"), executable=True)]
    captured = {}

    def fake_create(dirs, cb):
        from unittest.mock import MagicMock

        captured["cb"] = cb
        return MagicMock()

    class ExplodingIndex:
        def __init__(self, *a, **k):
            pass

        def scan(self, *a, **k):
            raise OSError("denied")

    # Patch before _run_rich: the watch callback binds AppImageIndex eagerly.
    monkeypatch.setattr(indexmod, "AppImageIndex", ExplodingIndex)
    monkeypatch.setattr(watchmod, "create_watcher", fake_create)
    tui = _rich_tui(tmp_path, watch=True)
    tui.entries = list(before)
    with _patch_tty(monkeypatch):
        monkeypatch.setattr(tui, "_read_key", lambda: "q")
        tui._run_rich()
        captured["cb"]()  # scan blows up: entries untouched, no crash
        assert tui.entries == before


def test_rich_watch_callback_rescans(tmp_path: Path, monkeypatch):
    import e_app_launcher.index as indexmod
    import e_app_launcher.watcher as watchmod
    from e_app_launcher.models import AppImageEntry

    d = tmp_path / "apps"
    d.mkdir()
    fresh = [AppImageEntry(name="N.AppImage", path=str(d / "N.AppImage"), executable=True)]
    captured = {}

    class FakeIndex:
        def __init__(self, *a, **k):
            pass

        def scan(self, *a, **k):
            return fresh

    monkeypatch.setattr(indexmod, "AppImageIndex", FakeIndex)

    def fake_create(dirs, cb):
        captured["cb"] = cb
        return MagicMock()

    monkeypatch.setattr(watchmod, "create_watcher", fake_create)
    tui = _rich_tui(tmp_path, watch=True)
    with _patch_tty(monkeypatch):
        monkeypatch.setattr(tui, "_read_key", lambda: "q")
        tui._run_rich()
        captured["cb"]()  # watcher thread would call this on fs change
        assert tui.entries is fresh


def test_no_textual_install_aliases_rich():
    # Environment-dependent import fallback: without textual, TextualTUI is RichTUI.
    import builtins
    import importlib

    import e_app_launcher.tui as tm

    real_import = builtins.__import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if isinstance(name, str) and name.split(".")[0] == "textual":
            raise ImportError("no textual here")
        return real_import(name, globals, locals, fromlist, level)

    builtins.__import__ = fake_import
    try:
        importlib.reload(tm)
        assert tm.HAS_TEXTUAL is False
        assert tm.TextualTUI is tm.RichTUI
    finally:
        builtins.__import__ = real_import
        importlib.reload(tm)
    assert tm.HAS_TEXTUAL is True


def test_run_without_textual_calls_rich(monkeypatch):
    import e_app_launcher.tui as tuimod

    monkeypatch.setattr(tuimod, "HAS_TEXTUAL", False)
    tui = tuimod.RichTUI(entries=[], directory=Path("/tmp"), launcher=MagicMock())
    monkeypatch.setattr(tuimod.RichTUI, "_run_rich", lambda self: "rich-ok")
    assert tui.run() == "rich-ok"


@needs_textual
def test_launch_entry_success_sets_launched_and_exits():
    entries = [make_entry("A.AppImage")]
    launcher = MagicMock()
    app = make_textual(entries)
    app.launcher = launcher
    exited = {}
    app.exit = lambda result: exited.setdefault("result", result)
    app._launch_entry(entries[0])
    launcher.validate_entry.assert_called_once_with(entries[0])
    launcher.launch.assert_called_once_with(entries[0])
    assert app.launched_entry is entries[0]
    assert exited["result"] is entries[0]


@needs_textual
def test_launch_entry_none_is_noop():
    app = make_textual([])
    app.launcher = MagicMock()
    app.exit = MagicMock()
    app._launch_entry(None)
    app.launcher.launch.assert_not_called()
    app.exit.assert_not_called()


@needs_textual
def test_library_stats_empty():
    app = make_textual([])
    assert app._library_stats() == (0, 0, 0)


@needs_textual
def test_library_stats_sums_sizes_and_counts():
    entries = [
        AppImageEntry(name="A.AppImage", path="/tmp/A", executable=True, size=100, mtime=0),
        AppImageEntry(name="B.AppImage", path="/tmp/B", executable=True, size=200, mtime=0, desktop_integrated=True),
        AppImageEntry(name="C.AppImage", path="/tmp/C", executable=True, size=300, mtime=0, desktop_integrated=True),
    ]
    app = make_textual(entries)
    assert app._library_stats() == (600, 2, 1)


@needs_textual
def test_library_stats_all_local():
    entries = [make_entry(f"App{i}.AppImage") for i in range(4)]
    app = make_textual(entries)
    total, integrated, local = app._library_stats()
    assert total == 4000
    assert integrated == 0
    assert local == 4


@needs_textual
def test_library_stats_zero_size_entries_still_count():
    entries = [
        AppImageEntry(name="A.AppImage", path="/tmp/A", executable=True, size=0, mtime=0),
        AppImageEntry(name="B.AppImage", path="/tmp/B", executable=True, size=0, mtime=0, desktop_integrated=True),
    ]
    assert make_textual(entries)._library_stats() == (0, 1, 1)


@needs_textual
def test_topbar_single_dir_shows_folder_total_and_counts():
    mb = 1024 * 1024
    entries = [
        AppImageEntry(
            name="Big.AppImage",
            path="/tmp/AppImages/Big.AppImage",
            executable=True,
            size=200 * mb,
            mtime=0,
            desktop_integrated=True,
        ),
        AppImageEntry(
            name="Small.AppImage", path="/tmp/AppImages/Small.AppImage", executable=True, size=100 * mb, mtime=0
        ),
    ]
    app = make_textual(entries, directory=Path("/tmp/AppImages"))
    text = app._topbar_dirs_text()
    assert "/tmp/AppImages" in text
    assert "300.0M total" in text
    assert "● 1 integrated" in text
    assert "○ 1 local" in text


@needs_textual
def test_topbar_home_directory_shortened():
    app = make_textual([], directory=Path.home() / "AppImages")
    text = app._topbar_dirs_text()
    assert "~" in text
    assert str(Path.home()) not in text


@needs_textual
def test_topbar_multi_dir_shows_folder_count():
    app = make_textual([], directory=[Path("/tmp/a"), Path("/tmp/b"), Path("/tmp/c")])
    text = app._topbar_dirs_text()
    assert "3 folders" in text
    assert "0 B total" in text
    assert "● 0 integrated" in text
    assert "○ 0 local" in text


@needs_textual
def test_topbar_segments_join_to_plain_text_with_color_contract():
    app = make_textual([make_entry("A.AppImage")])
    segments = app._topbar_segments()
    assert app._topbar_dirs_text() == "".join(seg for seg, _ in segments)
    by_text = dict(segments)
    assert "a6e3a1" in by_text["● 0 integrated"]
    assert by_text["○ 1 local"] == "#7f849c"
    assert "cdd6f4" in by_text["1000 B total"]


@needs_textual
def test_stats_text_is_sort_only_counts_live_in_count_badge():
    entries = [make_entry("A.AppImage"), make_entry("B.AppImage"), make_entry("C.AppImage")]
    app = make_textual(entries)
    assert app._stats_text() == " ⇅ Name A-Z "
    app._filtered = entries[:1]
    assert app._stats_text() == " ⇅ Name A-Z "


@needs_textual
@pytest.mark.parametrize(
    ("sort_mode", "label"),
    [("name", "Name A-Z"), ("size", "Size ↓"), ("mtime", "Recent ↓"), ("custom", "custom")],
)
def test_stats_text_sort_labels(sort_mode, label):
    app = make_textual([], sort_mode=sort_mode)
    assert app._stats_text() == f" ⇅ {label} "


@needs_textual
def test_close_search_applies_and_is_unmounted_safe():
    entries = [make_entry("B.AppImage"), make_entry("A.AppImage")]
    app = make_textual(entries)
    # Unmounted: no modal to pop, no widgets to focus - must not raise.
    app._close_search("b.app")
    assert app.filter_text == "b.app"
    app._close_search("  ")
    assert app.filter_text == ""


@needs_textual
def test_update_topbar_unmounted_does_not_crash():
    # Widgets don't exist before mount; the updater must swallow that quietly.
    app = make_textual([make_entry("A.AppImage")])
    app._update_topbar()


# --- Rich fallback (non-Textual) behavior ---


def _rich_tui(tmp_path: Path, names=("A.AppImage",), **kw):
    from e_app_launcher.models import AppImageEntry as Entry

    entries = []
    for name in names:
        p = tmp_path / name
        p.write_text("hi")
        p.chmod(0o755)
        entries.append(Entry(name=name, path=str(p), executable=True, size=1000, mtime=1000))
    return RichTUI(entries=entries, directory=tmp_path, launcher=MagicMock(), **kw)


def _patch_tty(monkeypatch):
    import sys
    import termios
    from unittest.mock import patch

    monkeypatch.setattr(sys, "stdin", FakeTTY(True))
    monkeypatch.setattr(sys, "stdout", FakeTTY(True))
    monkeypatch.setattr(termios, "tcgetattr", lambda fd: ["s"])
    monkeypatch.setattr(termios, "tcsetattr", lambda *a, **k: None)
    return patch("tty.setcbreak", lambda fd: None)


def test_rich_render_smoke_and_empty_filter(tmp_path: Path, capsys):
    from rich.console import Console

    tui = _rich_tui(tmp_path, names=("A.AppImage", "B.AppImage"))
    tui.console = Console(record=True, width=100)
    tui._render(tui._filtered_sorted())
    tui.filter_text = "zzz-no-match"
    tui._render(tui._filtered_sorted(), status="No matches for filter: zzz")


def test_rich_read_key_variants(monkeypatch):
    import sys
    from unittest.mock import patch

    from e_app_launcher.tui import RichTUI as RT

    monkeypatch.setattr(sys, "stdin", FakeTTY(True))
    tui = RT(entries=[], directory=Path("/tmp"), launcher=MagicMock())
    with patch("os.read", return_value=b"q"):
        assert tui._read_key() == "q"
    with patch("os.read", return_value=b"\r"):
        assert tui._read_key() == "enter"
    with patch("os.read", return_value=b"\x1b"):
        with patch.object(RT, "_read_escape_sequence", return_value="[A"):
            assert tui._read_key() == "up"
        with patch.object(RT, "_read_escape_sequence", return_value=""):
            assert tui._read_key() == "\x1b"


def test_rich_alt_screen_codes(capsys):
    tui = RichTUI(entries=[], directory=Path("/tmp"), launcher=MagicMock())
    tui._enable_alt_screen()
    tui._disable_alt_screen()
    out = capsys.readouterr().out
    assert "\x1b[?1049h" in out and "\x1b[?1049l" in out


def test_rich_empty_library_panel(tmp_path: Path, monkeypatch):
    import io

    from rich.console import Console

    buf = io.StringIO()
    tui = _rich_tui(tmp_path, names=())
    tui.console = Console(file=buf, width=100)
    with _patch_tty(monkeypatch):
        assert tui._run_rich() is None
    assert "No AppImages found" in buf.getvalue()


def test_rich_enter_launches_and_quits(tmp_path: Path, monkeypatch):
    tui = _rich_tui(tmp_path)
    with _patch_tty(monkeypatch):
        monkeypatch.setattr(tui, "_read_key", lambda: "enter")
        result = tui._run_rich()
    assert result is not None and result.name == "A.AppImage"
    assert tui.launched_entry is not None
    tui.launcher.validate_entry.assert_called_once()
    tui.launcher.launch.assert_called_once()


def test_rich_key_loop_sort_rescan_open_copy_help_delete_quit(tmp_path: Path, monkeypatch):
    from unittest.mock import patch

    import e_app_launcher.index as indexmod

    tui = _rich_tui(tmp_path)
    keys = iter(["s", "r", "o", "y", "d", "/", "?", "q"])
    with _patch_tty(monkeypatch):
        monkeypatch.setattr(tui, "_read_key", lambda: next(keys))
        with (
            patch.object(indexmod.AppImageIndex, "scan", return_value=tui.entries) as mock_scan,
            patch("subprocess.Popen") as mock_popen,
            patch("shutil.which", return_value=None),
            patch("builtins.input", return_value=""),
        ):
            assert tui._run_rich() is None
    assert tui.sort_mode == "size"  # cycled once by 's'
    mock_scan.assert_called_once()  # 'r' rescanned
    mock_popen.assert_called_once()  # 'o' opened folder (args: xdg-open dir)
    assert mock_popen.call_args[0][0][0] == "xdg-open"


def test_rich_launch_failure_sets_status_and_continues(tmp_path: Path, monkeypatch):
    tui = _rich_tui(tmp_path)
    tui.launcher.launch.side_effect = RuntimeError("boom")
    keys = iter(["enter", "q"])
    with _patch_tty(monkeypatch):
        monkeypatch.setattr(tui, "_read_key", lambda: next(keys))
        assert tui._run_rich() is None  # failed launch does not exit


def test_rich_filtered_sorted_mtime():
    from e_app_launcher.models import AppImageEntry

    tui = RichTUI(entries=[], directory=Path("/tmp"), launcher=MagicMock())
    tui.entries = [
        AppImageEntry(name="Old.AppImage", path="/tmp/Old", executable=True, size=1, mtime=10),
        AppImageEntry(name="New.AppImage", path="/tmp/New", executable=True, size=1, mtime=99),
    ]
    tui.sort_mode = "mtime"
    assert [r.name for r in tui._filtered_sorted()] == ["New.AppImage", "Old.AppImage"]


def test_run_maps_textual_result_to_launched(monkeypatch):
    import sys

    import e_app_launcher.tui as tuimod
    from e_app_launcher.models import AppImageEntry

    monkeypatch.setattr(sys, "stdin", FakeTTY(True))
    monkeypatch.setattr(sys, "stdout", FakeTTY(True))
    entry = AppImageEntry(name="A.AppImage", path="/tmp/A", executable=True)

    class DirectApp:
        def __init__(self, *a, **k):
            self.launched_entry = None

        def run(self):
            return entry  # Textual App.exit(entry) returns the entry itself

    monkeypatch.setattr(tuimod, "TextualTUI", DirectApp)
    tui = tuimod.RichTUI(entries=[entry], directory=Path("/tmp"), launcher=MagicMock())
    assert tui.run() is entry
    assert tui.launched_entry is entry


def test_run_uses_app_launched_entry_fallback(monkeypatch):
    import sys

    import e_app_launcher.tui as tuimod
    from e_app_launcher.models import AppImageEntry

    monkeypatch.setattr(sys, "stdin", FakeTTY(True))
    monkeypatch.setattr(sys, "stdout", FakeTTY(True))
    entry = AppImageEntry(name="A.AppImage", path="/tmp/A", executable=True)

    class IndirectApp:
        def __init__(self, *a, **k):
            self.launched_entry = entry

        def run(self):
            return None

    monkeypatch.setattr(tuimod, "TextualTUI", IndirectApp)
    tui = tuimod.RichTUI(entries=[entry], directory=Path("/tmp"), launcher=MagicMock())
    assert tui.run() is entry


def test_rich_read_escape_sequence_empty_and_full(monkeypatch):
    import sys
    from unittest.mock import patch

    import e_app_launcher.tui as tuimod

    monkeypatch.setattr(sys, "stdin", FakeTTY(True))
    tui = tuimod.RichTUI(entries=[], directory=Path("/tmp"), launcher=MagicMock())
    with patch("select.select", return_value=([], [], [])):
        assert tui._read_escape_sequence() == ""
    reads = iter([b"[", b"A"])
    with (
        patch("select.select", return_value=([1], [], [])),
        patch("os.read", side_effect=lambda fd, n: next(reads)),
    ):
        assert tui._read_escape_sequence() == "[A"


def test_rich_key_failures_do_not_crash(tmp_path: Path, monkeypatch, capsys):
    from unittest.mock import patch

    import e_app_launcher.index as indexmod

    tui = _rich_tui(tmp_path)
    keys = iter(["r", "o", "q"])
    with _patch_tty(monkeypatch):
        monkeypatch.setattr(tui, "_read_key", lambda: next(keys))
        with (
            patch.object(indexmod.AppImageIndex, "scan", side_effect=OSError("denied")),
            patch("subprocess.Popen", side_effect=OSError("no xdg")),
        ):
            assert tui._run_rich() is None  # rescan/open failures -> status, then quit


def test_rich_filter_eof_keeps_old_filter(tmp_path: Path, monkeypatch):
    from unittest.mock import patch

    tui = _rich_tui(tmp_path)
    tui.filter_text = "keep"
    keys = iter(["/", "q"])
    with _patch_tty(monkeypatch):
        monkeypatch.setattr(tui, "_read_key", lambda: next(keys))
        with patch("builtins.input", side_effect=EOFError):
            tui._run_rich()
    assert tui.filter_text == "keep"


def test_rich_copy_variants_and_failure(tmp_path: Path, monkeypatch):
    from unittest.mock import patch

    tui = _rich_tui(tmp_path)
    with _patch_tty(monkeypatch):
        # xclip present
        monkeypatch.setattr(tui, "_read_key", lambda: "q")
        monkeypatch.setattr("shutil.which", lambda n: "/usr/bin/xclip" if n == "xclip" else None)
        with patch("subprocess.run") as mock_run:
            # drive the 'y' branch directly through the loop
            keys = iter(["y", "q"])
            monkeypatch.setattr(tui, "_read_key", lambda: next(keys))
            tui._run_rich()
            mock_run.assert_called_once()
            assert mock_run.call_args[0][0][0] == "xclip"
        # clipboard tool explodes -> status, no crash
        keys = iter(["y", "q"])
        monkeypatch.setattr(tui, "_read_key", lambda: next(keys))
        with patch("subprocess.run", side_effect=OSError("no clipboard")):
            tui._run_rich()


def test_rich_cursor_up_down_and_launch_second(tmp_path: Path, monkeypatch):
    tui = _rich_tui(tmp_path, names=("A.AppImage", "B.AppImage"))
    keys = iter(["up", "down", "down", "enter"])
    with _patch_tty(monkeypatch):
        monkeypatch.setattr(tui, "_read_key", lambda: next(keys))
        result = tui._run_rich()
    assert result is not None and result.name == "B.AppImage"


def test_rich_render_with_comment_and_status(tmp_path: Path):
    import io

    from rich.console import Console

    from e_app_launcher.models import AppImageEntry

    e = AppImageEntry(name="C.AppImage", path="/tmp/C", executable=True, size=10, mtime=0, comment="hello")
    tui = RichTUI(entries=[e], directory=Path("/tmp"), launcher=MagicMock())
    tui.console = Console(file=io.StringIO(), width=100)
    tui._render([e], status="all good")


def test_rich_watcher_create_failure_continues(tmp_path: Path, monkeypatch):
    import e_app_launcher.watcher as watchmod

    tui = _rich_tui(tmp_path, watch=True)
    with _patch_tty(monkeypatch):
        monkeypatch.setattr(watchmod, "create_watcher", MagicMock(side_effect=OSError("no watch")))
        monkeypatch.setattr(tui, "_read_key", lambda: "q")
        assert tui._run_rich() is None


def test_rich_no_match_render_and_selected_clamp(tmp_path: Path, monkeypatch, capsys):
    import io

    from rich.console import Console

    tui = _rich_tui(tmp_path, names=("A.AppImage",))
    tui.console = Console(file=io.StringIO(), width=100)
    tui.filter_text = "zzz"
    with _patch_tty(monkeypatch):
        monkeypatch.setattr(tui, "_read_key", lambda: "q")
        assert tui._run_rich() is None  # empty match renders the no-match row
    # Out-of-range selection is clamped when there IS something to select.
    tui.filter_text = ""
    tui.selected = 9
    with _patch_tty(monkeypatch):
        monkeypatch.setattr(tui, "_read_key", lambda: "q")
        tui._run_rich()
    assert tui.selected == 0


def test_rich_wl_copy_success_and_delete_status(tmp_path: Path, monkeypatch):
    from unittest.mock import patch

    tui = _rich_tui(tmp_path)
    keys = iter(["y", "d", "q"])
    with _patch_tty(monkeypatch):
        monkeypatch.setattr(tui, "_read_key", lambda: next(keys))
        monkeypatch.setattr("shutil.which", lambda n: "/usr/bin/wl-copy" if n == "wl-copy" else None)
        with patch("subprocess.run") as mock_run:
            tui._run_rich()
            mock_run.assert_called_once()
            assert mock_run.call_args[0][0] == ["wl-copy"]


def test_rich_watcher_stop_failure_swallowed(tmp_path: Path, monkeypatch):
    import e_app_launcher.watcher as watchmod

    tui = _rich_tui(tmp_path, watch=True)
    fake = MagicMock()
    fake.stop.side_effect = OSError("stuck")
    with _patch_tty(monkeypatch):
        monkeypatch.setattr(watchmod, "create_watcher", lambda dirs, cb: fake)
        monkeypatch.setattr(tui, "_read_key", lambda: "q")
        tui._run_rich()  # stop() raising must not propagate


def test_rich_render_multi_dir_title(tmp_path: Path):
    import io

    from rich.console import Console

    buf = io.StringIO()
    tui = RichTUI(entries=[], directory=[Path("/a"), Path("/b"), Path("/c")], launcher=MagicMock())
    tui.console = Console(file=buf, width=100)
    tui._render([], status="hi")
    assert "+2 more" in buf.getvalue()


def test_rich_read_key_down_and_ignore(monkeypatch):
    import sys
    from unittest.mock import patch

    from e_app_launcher.tui import RichTUI as RT

    monkeypatch.setattr(sys, "stdin", FakeTTY(True))
    tui = RT(entries=[], directory=Path("/tmp"), launcher=MagicMock())
    with patch("os.read", return_value=b"\x1b"):
        with patch.object(RT, "_read_escape_sequence", return_value="[B"):
            assert tui._read_key() == "down"
        with patch.object(RT, "_read_escape_sequence", return_value="xyz"):
            assert tui._read_key() == "ignore"


def test_rich_watch_starts_and_stops(tmp_path: Path, monkeypatch):
    import e_app_launcher.watcher as watchmod

    tui = _rich_tui(tmp_path, watch=True)
    stopped = []
    fake = MagicMock()
    fake.stop.side_effect = lambda: stopped.append(1)
    with _patch_tty(monkeypatch):
        monkeypatch.setattr(watchmod, "create_watcher", lambda dirs, cb: fake)
        monkeypatch.setattr(tui, "_read_key", lambda: "q")
        tui._run_rich()
    assert stopped == [1]


# --- headless Textual pilot tests (no display needed) ---


def _pilot_entries(tmp_path: Path, names=("A.AppImage", "B.AppImage")):
    from e_app_launcher.models import AppImageEntry as Entry

    entries = []
    for name in names:
        p = tmp_path / name
        p.write_text("hi")
        p.chmod(0o755)
        entries.append(Entry(name=name, path=str(p), executable=True, size=1000, mtime=1000))
    return entries


@needs_textual
def test_pilot_sort_cycles_through_modes(tmp_path: Path):
    import asyncio

    entries = _pilot_entries(tmp_path)
    app = make_textual(entries)
    notes = []
    app.notify = lambda msg, *a, **k: notes.append(msg)

    async def main():
        async with app.run_test(size=(120, 30)) as pilot:
            await pilot.pause()
            assert app.sort_mode == "name"
            await pilot.press("s")
            await pilot.pause()
            assert app.sort_mode == "size"
            await pilot.press("s")
            await pilot.pause()
            assert app.sort_mode == "mtime"

    asyncio.run(main())
    assert any("Sort" in m for m in notes)


@needs_textual
def test_pilot_copy_without_tools_warns_with_path(tmp_path: Path, monkeypatch):
    import asyncio

    entries = _pilot_entries(tmp_path, names=("Only.AppImage",))
    app = make_textual(entries)
    notes = []
    app.notify = lambda msg, *a, **k: notes.append((msg, k.get("severity", "info")))
    monkeypatch.setattr("shutil.which", lambda _: None)

    async def main():
        async with app.run_test(size=(120, 30)) as pilot:
            await pilot.pause()
            await pilot.press("y")
            await pilot.pause()

    asyncio.run(main())
    assert any("Only.AppImage" in m for m, _ in notes), notes
    assert any(sev == "warning" for _, sev in notes)


@needs_textual
def test_pilot_copy_uses_wl_copy(tmp_path: Path, monkeypatch):
    import asyncio
    from unittest.mock import patch

    entries = _pilot_entries(tmp_path, names=("Only.AppImage",))
    app = make_textual(entries)
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/wl-copy" if name == "wl-copy" else None)

    async def main():
        async with app.run_test(size=(120, 30)) as pilot:
            await pilot.pause()
            with patch("subprocess.run") as mock_run:
                await pilot.press("y")
                await pilot.pause()
                mock_run.assert_called_once()
                assert mock_run.call_args[0][0] == ["wl-copy"]
                assert b"Only.AppImage" in mock_run.call_args[1]["input"]

    asyncio.run(main())


@needs_textual
def test_pilot_integrate_toggles_integration(tmp_path: Path, monkeypatch):
    import asyncio

    import e_app_launcher.desktop as dm

    entries = _pilot_entries(tmp_path, names=("S.AppImage",))
    app = make_textual(entries)
    monkeypatch.setattr(dm, "integrate", lambda p: tmp_path / "x.desktop")
    monkeypatch.setattr(dm, "remove_integration", lambda p: True)

    async def main():
        async with app.run_test(size=(120, 30)) as pilot:
            await pilot.pause()
            assert entries[0].desktop_integrated is False
            await pilot.press("i")
            await pilot.pause()
            assert entries[0].desktop_integrated is True
            await pilot.press("i")
            await pilot.pause()
            assert entries[0].desktop_integrated is False

    asyncio.run(main())


@needs_textual
def test_pilot_delete_confirm_regression_and_cancel(tmp_path: Path):
    # Regression: two widgets shared id 'confirm-msg' -> MountError on 'd'.
    import asyncio

    entries = _pilot_entries(tmp_path, names=("Gone.AppImage",))
    app = make_textual(entries)

    async def main():
        async with app.run_test(size=(120, 30)) as pilot:
            await pilot.pause()
            await pilot.press("d")
            await pilot.pause()
            assert type(app.screen).__name__ == "ConfirmScreen"
            await pilot.press("escape")
            await pilot.pause()
            assert "Confirm" not in type(app.screen).__name__

    asyncio.run(main())
    assert (tmp_path / "Gone.AppImage").exists()  # cancelled: file kept


@needs_textual
def test_pilot_delete_confirm_deletes_file(tmp_path: Path):
    import asyncio

    entries = _pilot_entries(tmp_path, names=("Gone.AppImage",))
    app = make_textual(entries)

    async def main():
        async with app.run_test(size=(120, 30)) as pilot:
            await pilot.pause()
            await pilot.press("d")
            await pilot.pause()
            await pilot.click("#confirm")
            await pilot.pause()

    asyncio.run(main())
    assert not (tmp_path / "Gone.AppImage").exists()
    assert app.entries == []


@needs_textual
def test_pilot_delete_with_working_gio_keeps_file_but_drops_entry(tmp_path: Path, monkeypatch):
    # gio trash succeeding means: entry removed from library, file left to trash.
    import asyncio
    from unittest.mock import MagicMock

    entries = _pilot_entries(tmp_path, names=("Gone.AppImage",))
    app = make_textual(entries)
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/gio" if name == "gio" else None)

    async def main():
        async with app.run_test(size=(120, 30)) as pilot:
            await pilot.pause()
            from unittest.mock import patch

            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0)
                await pilot.press("d")
                await pilot.pause()
                await pilot.click("#confirm")
                await pilot.pause()
                mock_run.assert_called_once()
                assert mock_run.call_args[0][0][:2] == ["gio", "trash"]

    asyncio.run(main())
    assert (tmp_path / "Gone.AppImage").exists()  # trashed, not unlinked
    assert app.entries == []


@needs_textual
def test_pilot_markup_in_filename_is_safe(tmp_path: Path):
    import asyncio

    entries = _pilot_entries(tmp_path, names=("Evil [bold red]hack[X]Y.AppImage", "Plain.AppImage"))
    app = make_textual(entries)

    async def main():
        async with app.run_test(size=(120, 30)) as pilot:
            await pilot.pause()
            assert app.query_one("#table").row_count == 2
            await pilot.press("j")
            await pilot.pause()
            await pilot.press("s")
            await pilot.pause()

    asyncio.run(main())


@needs_textual
def test_pilot_help_opens_and_closes(tmp_path: Path):
    import asyncio

    app = make_textual(_pilot_entries(tmp_path))

    async def main():
        async with app.run_test(size=(120, 30)) as pilot:
            await pilot.pause()
            await pilot.press("?")
            await pilot.pause()
            assert type(app.screen).__name__ == "HelpScreen"
            await pilot.press("escape")
            await pilot.pause()
            assert "Help" not in type(app.screen).__name__

    asyncio.run(main())


@needs_textual
def test_textual_format_mtime_invalid():
    app = make_textual([])
    assert app._format_mtime(float("inf")) == "-"
    assert app._format_mtime(float("nan")) == "-"


@needs_textual
def test_pilot_enter_launches_selected(tmp_path: Path):
    import asyncio
    from unittest.mock import MagicMock

    entries = _pilot_entries(tmp_path, names=("Run.AppImage",))
    launcher = MagicMock()
    app = TextualTUI(entries=entries, directory=tmp_path, launcher=launcher)
    app._filtered = list(entries)
    exited = {}

    async def main():
        async with app.run_test(size=(120, 30)) as pilot:
            await pilot.pause()
            app.exit = lambda result: exited.setdefault("result", result)
            await pilot.press("enter")
            await pilot.pause()

    asyncio.run(main())
    launcher.validate_entry.assert_called_once()
    launcher.launch.assert_called_once()
    assert exited["result"].name == "Run.AppImage"
    assert app.launched_entry.name == "Run.AppImage"


@needs_textual
def test_pilot_action_failures_notify_error(tmp_path: Path, monkeypatch):
    import asyncio
    from unittest.mock import patch

    import e_app_launcher.index as indexmod

    entries = _pilot_entries(tmp_path, names=("F.AppImage",))
    app = make_textual(entries)
    notes = []
    app.notify = lambda msg, *a, **k: notes.append((msg, k.get("severity", "info")))
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/wl-copy" if name == "wl-copy" else None)

    async def main():
        async with app.run_test(size=(120, 30)) as pilot:
            await pilot.pause()
            with (
                patch.object(indexmod.AppImageIndex, "scan", side_effect=OSError("denied")),
                patch("subprocess.Popen", side_effect=OSError("no xdg")),
                patch("subprocess.run", side_effect=OSError("no clipboard")),
            ):
                await pilot.press("r")
                await pilot.pause()
                await pilot.press("o")
                await pilot.pause()
                await pilot.press("y")
                await pilot.pause()

    asyncio.run(main())
    assert len([1 for _, sev in notes if sev == "error"]) == 3, notes


@needs_textual
def test_pilot_help_dismisses_with_button(tmp_path: Path):
    import asyncio

    app = make_textual(_pilot_entries(tmp_path))

    async def main():
        async with app.run_test(size=(120, 30)) as pilot:
            await pilot.pause()
            await pilot.press("?")
            await pilot.pause()
            assert type(app.screen).__name__ == "HelpScreen"
            await pilot.click("#close")
            await pilot.pause()
            assert "Help" not in type(app.screen).__name__

    asyncio.run(main())


@needs_textual
def test_pilot_help_dismisses_with_escape(tmp_path: Path):
    import asyncio

    app = make_textual(_pilot_entries(tmp_path))

    async def main():
        async with app.run_test(size=(120, 30)) as pilot:
            await pilot.pause()
            await pilot.press("?")
            await pilot.pause()
            assert type(app.screen).__name__ == "HelpScreen"
            await pilot.press("escape")
            await pilot.pause()
            assert "Help" not in type(app.screen).__name__

    asyncio.run(main())


@needs_textual
def test_pilot_cursor_keys_and_escape_clear(tmp_path: Path):
    import asyncio

    app = make_textual(_pilot_entries(tmp_path, names=("A.AppImage", "B.AppImage", "C.AppImage")))

    async def main():
        async with app.run_test(size=(120, 30)) as pilot:
            await pilot.pause()
            table = app.query_one("#table")
            await pilot.press("j")
            await pilot.pause()
            assert table.cursor_row == 1
            await pilot.press("G")
            await pilot.pause()
            assert table.cursor_row == 2
            await pilot.press("g")
            await pilot.pause()
            assert table.cursor_row == 0
            # Open search popup, Esc clears (back on main screen afterwards)
            await pilot.press("/")
            await pilot.pause()
            assert type(app.screen).__name__ == "SearchScreen"
            search = app.screen.query_one("#search-box")
            search.value = "zzz-no-match"
            await pilot.pause()
            await pilot.press("escape")
            await pilot.pause()
            assert "Search" not in type(app.screen).__name__
            assert app.filter_text == ""

    asyncio.run(main())


@needs_textual
def test_completion_names_sorted_deduped_display_first():
    from e_app_launcher.models import AppImageEntry

    entries = [
        AppImageEntry(name="Z.AppImage", path="/tmp/Z", executable=True, display_name="Zebra"),
        AppImageEntry(name="A.AppImage", path="/tmp/A", executable=True),
        AppImageEntry(name="A.AppImage", path="/tmp/A2", executable=True),
    ]
    assert make_textual(entries)._completion_names() == ["A.AppImage", "Zebra"]
    assert make_textual([])._completion_names() == []


@needs_textual
def test_entry_suggester_matches():
    import asyncio

    from e_app_launcher.tui import EntrySuggester

    async def run():
        # Note: Textual casefolds the query before calling get_suggestion,
        # so values here are already lowercase (case-insensitivity of the
        # query itself is covered by the pilot test below).
        s = EntrySuggester(lambda: ["Joplin-3.7.21.appimage", "Remix-IDE.appimage"])
        assert await s.get_suggestion("") is None
        assert await s.get_suggestion("zzz") is None
        assert await s.get_suggestion("jopl") == "Joplin-3.7.21.appimage"
        assert await s.get_suggestion("joplin-3.7.21.appimage") is None  # already complete
        assert await s.get_suggestion("r") == "Remix-IDE.appimage"
        empty = EntrySuggester(lambda: [])
        assert await empty.get_suggestion("a") is None

    asyncio.run(run())


@needs_textual
def test_pilot_search_popup_applies_on_enter(tmp_path: Path):
    import asyncio
    from unittest.mock import MagicMock

    entries = _pilot_entries(tmp_path, names=("Alpha.AppImage", "Beta.AppImage"))
    launcher = MagicMock()
    app = TextualTUI(entries=entries, directory=tmp_path, launcher=launcher)
    app._filtered = list(entries)

    async def main():
        async with app.run_test(size=(120, 30)) as pilot:
            await pilot.pause()
            await pilot.press("/")
            await pilot.pause()
            assert type(app.screen).__name__ == "SearchScreen"
            box = app.screen.query_one("#search-box")
            box.value = "alpha"
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            assert "Search" not in type(app.screen).__name__
            assert app.filter_text == "alpha"
            assert [e.name for e in app._filtered] == ["Alpha.AppImage"]

    asyncio.run(main())
    # Enter in the popup applies the query - it must NOT launch anything.
    launcher.launch.assert_not_called()


@needs_textual
def test_pilot_search_popup_does_not_stack(tmp_path: Path):
    import asyncio

    app = make_textual(_pilot_entries(tmp_path))

    async def main():
        async with app.run_test(size=(120, 30)) as pilot:
            await pilot.pause()
            await pilot.press("/")
            await pilot.pause()
            first = app.screen
            assert type(first).__name__ == "SearchScreen"
            await pilot.press("/")
            await pilot.pause()
            # Still the same popup, focused back on its input.
            assert app.screen is first

    asyncio.run(main())


@needs_textual
def test_pilot_search_popup_is_vertically_centered(tmp_path: Path):
    import asyncio

    app = make_textual(_pilot_entries(tmp_path))

    async def main():
        async with app.run_test(size=(140, 40)) as pilot:
            await pilot.pause()
            await pilot.press("/")
            await pilot.pause()
            card = app.screen.query_one("#search-card")
            reg = card.region
            scr_h = app.screen.size.height
            top, bottom = reg.y, scr_h - (reg.y + reg.height)
            assert reg.height < scr_h // 2
            assert abs(top - bottom) <= 2, (top, bottom, scr_h)

    asyncio.run(main())


@needs_textual
def test_pilot_modal_key_guards(tmp_path: Path):
    import asyncio
    from unittest.mock import MagicMock

    app = make_textual(_pilot_entries(tmp_path))

    async def main():
        async with app.run_test(size=(120, 30)) as pilot:
            await pilot.pause()
            await pilot.press("/")
            await pilot.pause()
            box = app.screen.query_one("#search-box")
            # App-level j/k navigation must not hijack typing in the popup.
            app.on_key(MagicMock(key="j"))
            assert box.value == ""
            box.value = "x"
            # Launch/search actions are inert while the popup is open.
            app.action_launch()
            app.action_search()
            assert type(app.screen).__name__ == "SearchScreen"
            app.launcher.launch.assert_not_called()
            # App-level j/k handling cannot see the table behind a modal.
            from textual.widgets import Input as TextualInput

            app.on_key(MagicMock(key="j"))
            assert box.value == "x"
            # A failing focus is swallowed, popup stays put.
            from unittest.mock import patch

            with patch.object(TextualInput, "focus", side_effect=RuntimeError("no focus")):
                app.action_search()
            assert type(app.screen).__name__ == "SearchScreen"
            await pilot.press("escape")
            await pilot.pause()

    asyncio.run(main())


@needs_textual
def test_pilot_watcher_wiring_and_unmount(tmp_path: Path, monkeypatch):
    import asyncio
    from unittest.mock import MagicMock

    import e_app_launcher.index as indexmod
    import e_app_launcher.watcher as watchmod
    from e_app_launcher.models import AppImageEntry

    d = tmp_path / "apps"
    d.mkdir()
    rescanned = AppImageEntry(name="B.AppImage", path=str(d / "B.AppImage"), executable=True)
    app = TextualTUI(entries=[], directory=d, launcher=MagicMock())
    app._filtered = []
    captured = {}

    def fake_create(dirs, cb):
        captured["cb"] = cb
        return MagicMock()

    class FakeIndex:
        def __init__(self, *a, **k):
            pass

        def scan(self, *a, **k):
            return [rescanned]

    monkeypatch.setattr(watchmod, "create_watcher", fake_create)
    monkeypatch.setattr(indexmod, "AppImageIndex", FakeIndex)

    async def main():
        async with app.run_test(size=(120, 30)) as pilot:
            await pilot.pause()
            # call_from_thread requires a non-app thread, like the real watcher.
            # It blocks until the app loop processes the callback, so the
            # thread must run concurrently with pilot pauses (join first = deadlock).
            import threading

            t = threading.Thread(target=captured["cb"], daemon=True)
            t.start()
            await pilot.pause()
            await pilot.pause()
            t.join(timeout=10)
            assert not t.is_alive()
            assert [e.name for e in app.entries] == ["B.AppImage"]
            # Unmount must tolerate a failing watcher stop.
            app._watcher = MagicMock(stop=MagicMock(side_effect=OSError("stuck")))
            app.on_unmount()

    asyncio.run(main())


@needs_textual
def test_pilot_mount_survives_watcher_create_failure(tmp_path: Path, monkeypatch):
    import asyncio
    from unittest.mock import MagicMock

    import e_app_launcher.watcher as watchmod

    app = make_textual(_pilot_entries(tmp_path))
    monkeypatch.setattr(watchmod, "create_watcher", MagicMock(side_effect=OSError("no watch")))

    async def main():
        async with app.run_test(size=(120, 30)) as pilot:
            await pilot.pause()
            assert app.query_one("#table").row_count == 2

    asyncio.run(main())


@needs_textual
def test_pilot_rescan_open_success_and_failure(tmp_path: Path, monkeypatch):
    import asyncio
    from unittest.mock import MagicMock, patch

    import e_app_launcher.index as indexmod
    from e_app_launcher.models import AppImageEntry

    d1, d2 = tmp_path / "a", tmp_path / "b"
    d1.mkdir()
    d2.mkdir()
    app = make_textual(_pilot_entries(d1))
    app.directory = [d1]
    app.primary_dir = d1
    notes = []
    app.notify = lambda msg, *a, **k: notes.append((msg, k.get("severity", "info")))
    rescanned = AppImageEntry(name="New.AppImage", path=str(d2 / "New.AppImage"), executable=True)

    class FakeIndex:
        def __init__(self, *a, **k):
            pass

        def scan(self, *a, **k):
            return [rescanned]

    monkeypatch.setattr(indexmod, "AppImageIndex", FakeIndex)

    async def main():
        async with app.run_test(size=(140, 40)) as pilot:
            await pilot.pause()
            await pilot.press("r")  # single-dir rescan branch
            await pilot.pause()
            assert [e.name for e in app.entries] == ["New.AppImage"]
            app.directory = [d1, d2]
            await pilot.press("r")  # multi-dir rescan branch
            await pilot.pause()
            assert [e.name for e in app.entries] == ["New.AppImage"]
            with patch.object(FakeIndex, "scan", side_effect=OSError("denied")):
                await pilot.press("r")
                await pilot.pause()
            with patch("subprocess.Popen") as mock_popen:
                await pilot.press("o")
                await pilot.pause()
                mock_popen.assert_called_once()
            with patch("subprocess.Popen", side_effect=OSError("no xdg")):
                await pilot.press("o")
                await pilot.pause()

    asyncio.run(main())
    assert any("Rescanned" in m for m, _ in notes)
    assert any("Opened" in m for m, _ in notes)
    assert [s for _, s in notes].count("error") == 2


@needs_textual
def test_pilot_copy_xclip_xsel_and_no_entry(tmp_path: Path, monkeypatch):
    import asyncio
    from unittest.mock import patch

    app = make_textual(_pilot_entries(tmp_path, names=("A.AppImage", "B.AppImage")))

    async def main():
        async with app.run_test(size=(140, 40)) as pilot:
            await pilot.pause()
            monkeypatch.setattr("shutil.which", lambda n: "/usr/bin/xclip" if n == "xclip" else None)
            with patch("subprocess.run") as mock_run:
                await pilot.press("y")
                await pilot.pause()
                assert mock_run.call_args[0][0][0] == "xclip"
            monkeypatch.setattr("shutil.which", lambda n: "/usr/bin/xsel" if n == "xsel" else None)
            with patch("subprocess.run") as mock_run:
                await pilot.press("y")
                await pilot.pause()
                assert mock_run.call_args[0][0][0] == "xsel"
            # Nothing selected (filter matches nothing): no crash, no modal.
            await pilot.press("/")
            await pilot.pause()
            app.screen.query_one("#search-box").value = "zzz-no-match"
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            await pilot.press("y")
            await pilot.pause()
            await pilot.press("d")
            await pilot.pause()
            await pilot.press("i")
            await pilot.pause()
            assert "Confirm" not in type(app.screen).__name__

    asyncio.run(main())


@needs_textual
def test_pilot_delete_failure_and_remove_error_paths(tmp_path: Path, monkeypatch):
    import asyncio

    import e_app_launcher.desktop as dm

    app = make_textual(_pilot_entries(tmp_path, names=("Gone.AppImage",)))
    notes = []
    app.notify = lambda msg, *a, **k: notes.append((msg, k.get("severity", "info")))
    monkeypatch.setattr("shutil.which", lambda _: None)

    async def main():
        async with app.run_test(size=(140, 40)) as pilot:
            await pilot.pause()
            from unittest.mock import patch

            with patch.object(Path, "unlink", side_effect=OSError("ro")):
                await pilot.press("d")
                await pilot.pause()
                await pilot.click("#confirm")
                await pilot.pause()
            # Unlink works but desktop removal explodes: entry still dropped.
            with patch.object(dm, "remove_integration", side_effect=RuntimeError("db gone")):
                await pilot.press("d")
                await pilot.pause()
                await pilot.click("#confirm")
                await pilot.pause()

    asyncio.run(main())
    assert any("Delete failed" in m for m, _ in notes)
    assert any("Deleted Gone.AppImage" in m for m, _ in notes)
    assert app.entries == []


@needs_textual
def test_pilot_integrate_remove_missing_and_integrate_failure(tmp_path: Path, monkeypatch):
    import asyncio

    import e_app_launcher.desktop as dm
    from e_app_launcher.models import AppImageEntry

    synced = AppImageEntry(
        name="S.AppImage", path=str(tmp_path / "S.AppImage"), executable=True, desktop_integrated=True
    )
    local = AppImageEntry(name="L.AppImage", path=str(tmp_path / "L.AppImage"), executable=True)
    for p in (tmp_path / "S.AppImage", tmp_path / "L.AppImage"):
        p.write_text("hi")
        p.chmod(0o755)
    app = TextualTUI(entries=[synced, local], directory=tmp_path, launcher=MagicMock())
    app._filtered = [synced, local]
    notes = []
    app.notify = lambda msg, *a, **k: notes.append(msg)
    monkeypatch.setattr(dm, "remove_integration", lambda p: False)
    monkeypatch.setattr(dm, "integrate", lambda p: (_ for _ in ()).throw(RuntimeError("extract boom")))

    async def main():
        async with app.run_test(size=(140, 40)) as pilot:
            await pilot.pause()
            await pilot.press("i")  # synced entry, nothing to remove
            await pilot.pause()
            assert synced.desktop_integrated is False
            await pilot.press("j")
            await pilot.pause()
            await pilot.press("i")  # local entry, integration explodes
            await pilot.pause()
            assert local.desktop_integrated is False

    asyncio.run(main())
    assert any("marked as local" in m for m in notes)
    assert any("Integration failed" in m for m in notes)


@needs_textual
def test_pilot_launch_failure_notifies(tmp_path: Path):
    import asyncio
    from unittest.mock import MagicMock

    launcher = MagicMock()
    launcher.validate_entry.side_effect = PermissionError("not executable")
    app = TextualTUI(entries=_pilot_entries(tmp_path, names=("A.AppImage",)), directory=tmp_path, launcher=launcher)
    app._filtered = list(app.entries)
    notes = []
    app.notify = lambda msg, *a, **k: notes.append((msg, k.get("severity", "info")))

    async def main():
        async with app.run_test(size=(120, 30)) as pilot:
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()

    asyncio.run(main())
    assert any("Launch failed" in m for m, _ in notes)
    assert [s for _, s in notes if s == "error"]


@needs_textual
def test_pilot_detail_rich_and_empty_states(tmp_path: Path):
    import asyncio
    from unittest.mock import MagicMock

    from e_app_launcher.models import AppImageEntry

    rich_entry = AppImageEntry(
        name="a-very-long-application-name-that-keeps-going.AppImage",
        path="/tmp/a-very-long-application-name-that-keeps-going.AppImage",
        executable=True,
        size=10,
        mtime=1000,
        display_name="A Much Longer Human Display Name That Exceeds Limits",
        comment="c" * 200,
        categories="Audio",
        version="9.9",
    )
    app = TextualTUI(entries=[rich_entry], directory=Path("/tmp"), launcher=MagicMock())
    app._filtered = [rich_entry]

    async def main():
        async with app.run_test(size=(140, 40)) as pilot:
            await pilot.pause()  # rich entry renders without crashing

    asyncio.run(main())

    empty = TextualTUI(entries=[], directory=Path("/tmp"), launcher=MagicMock())
    empty._filtered = []

    async def main2():
        async with empty.run_test(size=(140, 40)) as pilot:
            await pilot.pause()  # "No selection" detail

    asyncio.run(main2())

    nomatch = make_textual(_pilot_entries(tmp_path))

    async def main3():
        async with nomatch.run_test(size=(140, 40)) as pilot:
            await pilot.pause()
            await pilot.press("/")
            await pilot.pause()
            nomatch.screen.query_one("#search-box").value = "zzz-no-match"
            await pilot.pause()
            await pilot.press("enter")  # applies: empty table, "No results" detail
            await pilot.pause()
            assert nomatch._filtered == []

    asyncio.run(main3())


@needs_textual
def test_pilot_delete_cancel_keeps_file(tmp_path: Path):
    import asyncio

    app = make_textual(_pilot_entries(tmp_path, names=("Keep.AppImage",)))

    async def main():
        async with app.run_test(size=(120, 30)) as pilot:
            await pilot.pause()
            await pilot.press("d")
            await pilot.pause()
            await pilot.click("#cancel")
            await pilot.pause()
            assert "Confirm" not in type(app.screen).__name__

    asyncio.run(main())
    assert (tmp_path / "Keep.AppImage").exists()
    assert len(app.entries) == 1


@needs_textual
def test_pilot_confirm_modal_key_fallbacks(tmp_path: Path):
    # With a modal open, the table is unreachable so app-level j/k handling
    # bails out quietly (and the key bindings hit the same wall).
    import asyncio

    app = make_textual(_pilot_entries(tmp_path, names=("A.AppImage", "B.AppImage", "C.AppImage")))

    async def main():
        async with app.run_test(size=(140, 40)) as pilot:
            await pilot.pause()
            table = app.query_one("#table")
            assert table.cursor_row == 0
            await pilot.press("d")
            await pilot.pause()
            assert type(app.screen).__name__ == "ConfirmScreen"
            for key in ("j", "k", "g", "G"):
                await pilot.press(key)
                await pilot.pause()
            assert table.cursor_row == 0  # nothing moved behind the modal
            # Direct call: a failing table query bails out quietly.
            from unittest.mock import MagicMock, patch

            with patch.object(type(app), "query_one", side_effect=Exception("gone")):
                app.on_key(MagicMock(key="j"))
            await pilot.press("escape")
            await pilot.pause()
            assert "Confirm" not in type(app.screen).__name__

    asyncio.run(main())


@needs_textual
def test_pilot_cursor_actions_drive_table(tmp_path: Path):
    import asyncio

    app = make_textual(_pilot_entries(tmp_path, names=("A.AppImage", "B.AppImage", "C.AppImage")))

    async def main():
        async with app.run_test(size=(140, 40)) as pilot:
            await pilot.pause()
            table = app.query_one("#table")
            app.action_cursor_down()
            assert table.cursor_row == 1
            app.action_cursor_up()
            assert table.cursor_row == 0
            app.action_cursor_bottom()
            assert table.cursor_row == 2
            app.action_cursor_top()
            assert table.cursor_row == 0

    asyncio.run(main())


@needs_textual
def test_pilot_action_escape_and_launch_direct(tmp_path: Path):
    import asyncio

    app = make_textual(_pilot_entries(tmp_path, names=("A.AppImage",)))
    exited = {}
    app.exit = lambda result: exited.setdefault("result", result)

    async def main():
        async with app.run_test(size=(120, 30)) as pilot:
            await pilot.pause()
            await pilot.press("/")
            await pilot.pause()
            app.action_escape_key()  # modal open: inert, popup owns Escape
            assert type(app.screen).__name__ == "SearchScreen"
            await pilot.press("escape")
            await pilot.pause()
            app.action_launch()  # main screen: launches selection
            assert exited["result"].name == "A.AppImage"

    asyncio.run(main())
    app.launcher.launch.assert_called_once()


@needs_textual
def test_pilot_table_failure_tolerance(tmp_path: Path):
    import asyncio
    from unittest.mock import PropertyMock, patch

    from textual.widgets import DataTable

    app = make_textual(_pilot_entries(tmp_path, names=("A.AppImage", "B.AppImage")))

    async def main():
        async with app.run_test(size=(140, 40)) as pilot:
            await pilot.pause()
            await pilot.press("j")
            await pilot.pause()
            with patch.object(DataTable, "move_cursor", side_effect=RuntimeError("stuck")):
                app._update_table(restore_cursor=True)  # restore path swallows it
            with patch.object(DataTable, "update_cell_at", side_effect=RuntimeError("stuck")):
                app._refresh_markers()  # marker loop swallows it
            with patch.object(DataTable, "cursor_row", new_callable=PropertyMock) as mock_cursor:
                mock_cursor.side_effect = RuntimeError("no cursor")
                app._update_table(restore_cursor=True)  # prev-path probe swallows it
            assert app.query_one("#table").row_count == 2

    asyncio.run(main())


@needs_textual
def test_pilot_search_autocomplete_accepts_with_right(tmp_path: Path):
    import asyncio
    from unittest.mock import MagicMock

    entries = _pilot_entries(tmp_path, names=("Joplin-3.7.21.appimage", "Remix-IDE-1.3.6.appimage"))
    launcher = MagicMock()
    app = TextualTUI(entries=entries, directory=tmp_path, launcher=launcher)
    app._filtered = list(entries)

    async def main():
        async with app.run_test(size=(140, 40)) as pilot:
            await pilot.pause()
            await pilot.press("/")
            await pilot.pause()
            box = app.screen.query_one("#search-box")
            box.value = "JOPL"  # uppercase: matching is case insensitive
            await pilot.pause()
            await pilot.pause()
            await pilot.press("right")  # accept the dimmed completion
            await pilot.pause()
            assert box.value == "Joplin-3.7.21.appimage"
            await pilot.press("enter")
            await pilot.pause()
            assert [e.name for e in app._filtered] == ["Joplin-3.7.21.appimage"]

    asyncio.run(main())
    launcher.launch.assert_not_called()


@needs_textual
def test_update_helpers_unmounted_are_silent():
    app = make_textual([make_entry("A.AppImage")])
    app._update_count()
    app._update_list_title()
    app._update_footer()
    app._update_detail()
    app._refresh_markers()
    assert app._current_entry() is None
    app.action_cursor_down()
    app.action_cursor_up()
    app.action_cursor_top()
    app.action_cursor_bottom()


@needs_textual
def test_pure_helpers_edge_cases():
    app = make_textual([])
    app.sort_mode = "bogus"
    entries = [make_entry("B.AppImage"), make_entry("A.AppImage")]
    app.entries = entries
    assert app._filtered_sorted() is app.entries  # unknown mode: unsorted passthrough
    assert app._short_name("x" * 100).endswith("…")
    assert app._short_name("short.AppImage") == "short.AppImage"
    assert app._human_size(3 * 1024**3) == "3.00G"
    long_path = str(Path.home() / ("d" * 100) / ("f" * 50 + ".AppImage"))
    assert app._short_path(long_path).startswith("…")
    assert app._short_path("/tmp/x.AppImage") == "/tmp/x.AppImage"


@needs_textual
def test_row_selected_guard_ignores_bad_rows():
    launcher = MagicMock()
    app = make_textual([])
    app.launcher = launcher
    app.exit = MagicMock()
    app.on_data_table_row_selected(MagicMock(cursor_row=None))
    app.on_data_table_row_selected(MagicMock(cursor_row=99))
    launcher.launch.assert_not_called()
    app.exit.assert_not_called()


@needs_textual
def test_pilot_count_badge_moves_with_filter(tmp_path: Path):
    import asyncio

    app = make_textual(_pilot_entries(tmp_path, names=("A.AppImage", "B.AppImage")))

    async def main():
        async with app.run_test(size=(140, 40)) as pilot:
            await pilot.pause()
            from textual.css.query import NoMatches

            # Count badge lives in the topbar now; the search row is gone.
            topbar = app.query_one("#topbar")
            assert topbar.query_one("#count") is not None
            assert topbar.query_one("#stats") is not None
            with pytest.raises(NoMatches):
                app.query_one("#search-row")
            await pilot.press("/")
            await pilot.pause()
            app.screen.query_one("#search-box").value = "zzz-no-match"
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            assert app.filter_text == "zzz-no-match"
            assert app._filtered == []

    asyncio.run(main())
