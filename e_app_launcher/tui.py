from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from rich.console import Console, Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from .launcher import AppLauncher
from .models import AppImageEntry

try:
    from textual.app import App, ComposeResult
    from textual.binding import Binding
    from textual.containers import Center, Horizontal, Middle, Vertical
    from textual.screen import ModalScreen
    from textual.suggester import Suggester
    from textual.widgets import Button, DataTable, Input, Static

    HAS_TEXTUAL = True
except ImportError:
    HAS_TEXTUAL = False


class RichTUI:
    def __init__(
        self,
        entries: list[AppImageEntry],
        directory: Path | list[Path],
        launcher: AppLauncher,
        console: Console | None = None,
        recursive: bool = False,
        watch: bool = False,
    ) -> None:
        self.entries = entries
        self.directory = directory if isinstance(directory, list) else [directory]
        self.primary_dir = self.directory[0] if self.directory else Path.cwd()
        self.launcher = launcher
        self.console = console or Console()
        self.selected = 0
        self.filter_text = ""
        self.sort_mode = "name"
        self._watch = watch
        self.launched_entry: AppImageEntry | None = None

    def _filtered_sorted(self) -> list[AppImageEntry]:
        filtered = self.entries
        if self.filter_text:
            q = self.filter_text.casefold()
            filtered = [
                e
                for e in self.entries
                if q in e.name.casefold()
                or q in e.effective_display_name().casefold()
                or q in e.comment.casefold()
                or q in e.path.casefold()
            ]
        if self.sort_mode == "name":
            return sorted(filtered, key=lambda e: e.name.lower())
        elif self.sort_mode == "size":
            return sorted(filtered, key=lambda e: e.size, reverse=True)
        elif self.sort_mode == "mtime":
            return sorted(filtered, key=lambda e: e.mtime, reverse=True)
        return filtered

    def run(self) -> AppImageEntry | None:
        if HAS_TEXTUAL and sys.stdin.isatty() and sys.stdout.isatty():
            try:
                app = TextualTUI(
                    entries=self.entries,
                    directory=self.directory,
                    launcher=self.launcher,
                    sort_mode=self.sort_mode,
                )
                result = app.run()
                if isinstance(result, AppImageEntry):
                    self.launched_entry = result
                    self.console.print(f"Launching {result.name}")
                    return result
                if app.launched_entry is not None:
                    self.launched_entry = app.launched_entry
                    self.console.print(f"Launching {app.launched_entry.name}")
                    return app.launched_entry
                return None
            except Exception as e:
                self.console.print(f"[yellow]Textual TUI failed ({e}), falling back to Rich[/yellow]")
        return self._run_rich()

    def _run_rich(self) -> AppImageEntry | None:
        import termios
        import tty

        if not sys.stdin.isatty() or not sys.stdout.isatty():
            raise SystemExit("The TUI requires an interactive terminal. Use --list or --launch.")

        if not self.entries:
            self.console.print(
                Panel(
                    f"No AppImages found in [bold]{', '.join(str(d) for d in self.directory)}[/bold].\nUse --dir PATH to scan a folder first.",
                    title="E-AppLauncher",
                    border_style="yellow",
                )
            )
            return None

        watcher = None
        if self._watch:
            try:
                from .index import AppImageIndex
                from .watcher import create_watcher

                def on_change():
                    idx = AppImageIndex()
                    try:
                        self.entries = idx.scan(self.directory[0] if len(self.directory) == 1 else self.directory)
                    except Exception:
                        pass

                watcher = create_watcher(self.directory, on_change)
            except Exception:
                pass

        self._enable_alt_screen()
        old_settings = termios.tcgetattr(sys.stdin.fileno())
        launched = None
        try:
            tty.setcbreak(sys.stdin.fileno())
            status = ""
            while True:
                filtered = self._filtered_sorted()
                if not filtered:
                    self._render(filtered, status="No matches for filter: " + self.filter_text)
                else:
                    if self.selected >= len(filtered):
                        self.selected = 0
                    self._render(filtered, status=status)
                status = ""
                key = self._read_key()
                if key in {"q", "\x03", "\x1b"}:
                    break
                if key == "up":
                    self.selected = (self.selected - 1) % max(1, len(filtered))
                elif key == "down":
                    self.selected = (self.selected + 1) % max(1, len(filtered))
                elif key == "enter":
                    if filtered:
                        entry = filtered[self.selected]
                        try:
                            self.launcher.validate_entry(entry)
                            self.launcher.launch(entry)
                            launched = entry
                            self.launched_entry = entry
                            break
                        except Exception as e:
                            status = f"[red]Launch failed: {e}[/red]"
                elif key == "r":
                    from .index import AppImageIndex

                    idx = AppImageIndex()
                    try:
                        self.entries = idx.scan(self.directory[0] if len(self.directory) == 1 else self.directory)
                        status = f"Rescanned, found {len(self.entries)} apps"
                        self.selected = 0
                    except Exception as e:
                        status = f"Rescan failed: {e}"
                elif key == "s":
                    modes = ["name", "size", "mtime"]
                    idx = modes.index(self.sort_mode)
                    self.sort_mode = modes[(idx + 1) % len(modes)]
                    status = f"Sort: {self.sort_mode}"
                elif key == "o":
                    try:
                        folder = str(self.primary_dir)
                        subprocess.Popen(
                            ["xdg-open", folder],
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                        )
                        status = f"Opened {folder}"
                    except Exception as e:
                        status = f"Failed to open: {e}"
                elif key == "d":
                    status = "Press 'y' to delete, not implemented in Rich fallback, use CLI"
                elif key == "/":
                    self.console.print("[dim]Filter: (type and Enter, empty to clear)[/dim]")
                    termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, old_settings)
                    try:
                        text = input("Filter: ")
                        self.filter_text = text.strip()
                        self.selected = 0
                    except EOFError:
                        pass
                    tty.setcbreak(sys.stdin.fileno())
                elif key == "?":
                    status = "Help: Up/Down move, Enter launch, / search, s sort, r rescan, o open folder, q quit"
                elif key == "y":
                    if filtered:
                        entry = filtered[self.selected]
                        try:
                            if shutil.which("wl-copy"):
                                subprocess.run(["wl-copy"], input=entry.path.encode(), timeout=2)
                                status = f"Copied {entry.path} to clipboard"
                            elif shutil.which("xclip"):
                                subprocess.run(
                                    ["xclip", "-selection", "clipboard"],
                                    input=entry.path.encode(),
                                    timeout=2,
                                )
                                status = f"Copied {entry.path} to clipboard"
                            else:
                                status = f"Path: {entry.path}"
                        except Exception as e:
                            status = f"Copy failed: {e}"
        finally:
            termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, old_settings)
            self._disable_alt_screen()
            if watcher:
                try:
                    watcher.stop()
                except Exception:
                    pass
            if launched is not None:
                self.console.print(f"Launching {launched.name}")
        return launched

    def _render(self, entries: list[AppImageEntry], status: str | None = None) -> None:
        table = Table(expand=True, show_header=True, header_style="bold #89b4fa")
        table.add_column(" ", width=2)
        table.add_column("AppImage", style="bold", no_wrap=False)
        table.add_column("Size", justify="right", width=10)
        table.add_column("Path", overflow="fold")

        for index, entry in enumerate(entries):
            marker = Text("▸" if index == self.selected else " ", style="bold #89b4fa")
            name = Text(entry.effective_display_name(), style="bold white" if index == self.selected else "")
            size_str = self._human_size(entry.size)
            size = Text(size_str, style="white" if index == self.selected else "dim")
            path = Text(entry.path, style="white" if index == self.selected else "dim")
            row_style = "on #313244" if index == self.selected else ""
            table.add_row(marker, name, size, path, style=row_style)

        detail = ""
        if entries and 0 <= self.selected < len(entries):
            e = entries[self.selected]
            integration = "yes" if e.desktop_integrated else "no"
            detail = Text(
                f"Name: {e.name} | Size: {self._human_size(e.size)} | Integrated: {integration} | Exec: {'yes' if e.executable else 'no'}",
                style="dim",
            )
            if e.comment:
                detail = Text(f"{detail.plain} | {e.comment}", style="dim")

        status_text = Text(status, style="bold #a6e3a1") if status else Text("")
        help_text = Text(
            "Up/Down move  Enter launch  / search  s sort  r rescan  o open  y copy  ? help  q quit",
            style="dim",
        )
        filter_text = Text(
            f"Filter: {self.filter_text or 'none'} | Sort: {self.sort_mode} | {len(entries)}/{len(self.entries)}",
            style="bold #89b4fa",
        )
        content = [filter_text, table]
        if detail:
            content.append(detail)
        content.append(help_text)
        if status:
            content.append(status_text)

        self.console.clear()
        title = f"E-AppLauncher | {self.primary_dir}"
        if len(self.directory) > 1:
            title += f" (+{len(self.directory) - 1} more)"
        self.console.print(
            Panel(
                Group(
                    Text(f"Directories: {', '.join(str(d) for d in self.directory)}", style="bold #cdd6f4"),
                    *content,
                ),
                title=title,
                border_style="#89b4fa",
                padding=(1, 2),
            )
        )

    def _human_size(self, size: int) -> str:
        if size < 1024:
            return f"{size} B"
        elif size < 1024 * 1024:
            return f"{size / 1024:.1f}K"
        elif size < 1024 * 1024 * 1024:
            return f"{size / 1024 / 1024:.1f}M"
        else:
            return f"{size / 1024 / 1024 / 1024:.2f}G"

    def _read_key(self) -> str:
        char = os.read(sys.stdin.fileno(), 1).decode(errors="ignore")
        if char == "\x1b":
            next_chars = self._read_escape_sequence()
            if not next_chars:
                return "\x1b"
            if next_chars.endswith(("[A", "OA")):
                return "up"
            if next_chars.endswith(("[B", "OB")):
                return "down"
            return "ignore"
        if char == "\r" or char == "\n":
            return "enter"
        return char

    def _read_escape_sequence(self) -> str:
        from select import select

        data = ""
        while len(data) < 8:
            ready, _, _ = select([sys.stdin], [], [], 0.2 if not data else 0.03)
            if not ready:
                break
            data += os.read(sys.stdin.fileno(), 1).decode(errors="ignore")
            if data.endswith(("[A", "[B", "OA", "OB")):
                break
        return data

    def _enable_alt_screen(self) -> None:
        sys.stdout.write("\x1b[?1049h")
        sys.stdout.flush()

    def _disable_alt_screen(self) -> None:
        sys.stdout.write("\x1b[?1049l")
        sys.stdout.flush()


if HAS_TEXTUAL:

    class TextualTUI(App):
        TITLE = "⬢ E-AppLauncher"
        SUB_TITLE = "AppImage Launcher"

        CSS = """
        Screen {
            background: #11111b;
            padding: 1 1;
        }
        #topbar {
            height: 3;
            background: #1e1e2e;
            border: round #45475a;
            padding: 0 1;
            layout: horizontal;
        }
        #brand {
            width: auto;
            content-align: left middle;
            color: #89b4fa;
            text-style: bold;
            padding: 0 1 0 0;
        }
        #dirs {
            width: 1fr;
            content-align: left middle;
            color: #7f849c;
            padding: 0 1;
        }
        #stats {
            width: auto;
            content-align: right middle;
            color: #11111b;
            background: #89b4fa;
            text-style: bold;
            padding: 0 1;
            margin: 1 0 1 1;
        }
        #count {
            width: auto;
            height: 1;
            content-align: center middle;
            color: #a6adc8;
            background: #1e1e2e;
            border: round #45475a;
            padding: 0 1;
            margin: 1 0 1 1;
            text-style: bold;
        }
        #search-card {
            width: 64;
            height: auto;
            background: #1e1e2e;
            border: round #89b4fa;
            padding: 1 2;
        }
        #search-title {
            content-align: left middle;
            color: #89b4fa;
            text-style: bold;
            height: 2;
        }
        #search-box {
            height: 3;
            border: round #45475a;
            background: #181825;
            color: #cdd6f4;
            padding: 0 1;
        }
        #search-box:focus {
            border: round #89b4fa;
            background: #1e1e2e;
        }
        #search-hint {
            height: 2;
            content-align: center middle;
            color: #7f849c;
        }
        #main {
            height: 1fr;
            layout: horizontal;
            margin: 1 0;
        }
        #list-pane {
            width: 60%;
            height: 100%;
            background: #1e1e2e;
            border: round #45475a;
            padding: 0 1;
        }
        #detail-pane {
            width: 40%;
            height: 100%;
            background: #1e1e2e;
            border: round #89b4fa;
            padding: 0 1;
            margin-left: 1;
        }
        .pane-title {
            height: 2;
            content-align: left middle;
            color: #7f849c;
            text-style: bold;
            padding: 0 0;
        }
        #table {
            height: 1fr;
            background: #1e1e2e;
            color: #cdd6f4;
        }
        DataTable {
            background: #1e1e2e;
            border: none;
            padding: 0 0;
        }
        DataTable > .datatable--header {
            background: #1e1e2e;
            color: #89b4fa;
            text-style: bold;
        }
        DataTable > .datatable--cursor {
            background: #313244;
            color: #ffffff;
            text-style: bold;
        }
        DataTable > .datatable--hover {
            background: #26263a;
        }
        DataTable > .datatable--zebra-stripe {
            background: #1a1a28;
        }
        #detail {
            height: 1fr;
            background: #1e1e2e;
            color: #cdd6f4;
            padding: 0 1 1 1;
        }
        #footer {
            height: 3;
            background: #1e1e2e;
            border: round #45475a;
            layout: horizontal;
            padding: 0 1;
        }
        #footer-left {
            width: 1fr;
            content-align: left middle;
            color: #7f849c;
        }
        #footer-right {
            width: auto;
            content-align: right middle;
            color: #89b4fa;
            text-style: bold;
            padding-left: 2;
        }
        #help-card {
            width: 64;
            height: auto;
            background: #1e1e2e;
            border: round #89b4fa;
            padding: 1 2;
        }
        #help-title {
            content-align: left middle;
            color: #89b4fa;
            text-style: bold;
            height: 2;
        }
        #help-body {
            color: #cdd6f4;
            height: auto;
            padding: 0 0 1 0;
        }
        #confirm-card {
            width: 56;
            height: auto;
            background: #1e1e2e;
            border: round #f38ba8;
            padding: 1 2;
        }
        #confirm-msg {
            color: #cdd6f4;
            text-align: center;
            height: auto;
            padding: 0 0 1 0;
        }
        #confirm-detail {
            color: #7f849c;
            text-align: center;
            height: auto;
            padding: 0 0 1 0;
        }
        #confirm-buttons {
            height: 3;
            layout: horizontal;
            align: center middle;
        }
        Button {
            margin: 0 1;
        }
        """

        BINDINGS = [
            Binding("q", "quit", "Quit", show=False),
            Binding("escape", "escape_key", "Esc", show=False),
            Binding("/", "search", "Filter", show=False),
            Binding("s", "sort", "Sort", show=False),
            Binding("?", "help", "Help", show=False),
            Binding("r", "rescan", "Rescan", show=False),
            Binding("o", "open_folder", "Open", show=False),
            Binding("d", "delete", "Delete", show=False),
            Binding("y", "copy_path", "Copy", show=False),
            Binding("i", "integrate", "Integrate", show=False),
            Binding("j", "cursor_down", "Down", show=False),
            Binding("k", "cursor_up", "Up", show=False),
            Binding("g", "cursor_top", "Top", show=False),
            Binding("G", "cursor_bottom", "Bottom", show=False),
            Binding("enter", "launch", "Launch", show=False),
        ]

        def __init__(
            self,
            entries: list[AppImageEntry],
            directory: Path | list[Path],
            launcher: AppLauncher,
            sort_mode: str = "name",
        ) -> None:
            super().__init__()
            self.entries = entries
            self.directory = directory if isinstance(directory, list) else [directory]
            self.primary_dir = self.directory[0] if self.directory else Path.cwd()
            self.launcher = launcher
            self.sort_mode = sort_mode
            self.filter_text = ""
            self._filtered: list[AppImageEntry] = []
            self._watcher = None
            self.launched_entry: AppImageEntry | None = None

        SORT_LABELS = {"name": "Name A-Z", "size": "Size ↓", "mtime": "Recent ↓"}

        def compose(self) -> ComposeResult:
            with Horizontal(id="topbar"):
                yield Static("⬢ E-AppLauncher", id="brand")
                yield Static("", id="dirs")
                yield Static("", id="count")
                yield Static("", id="stats")
            with Horizontal(id="main"):
                with Vertical(id="list-pane"):
                    yield Static("", id="list-title", classes="pane-title")
                    yield DataTable(id="table")
                with Vertical(id="detail-pane"):
                    yield Static("─ DETAILS", id="detail-title", classes="pane-title")
                    yield Static("Select an AppImage to see details", id="detail")
            with Horizontal(id="footer"):
                yield Static("", id="footer-left")
                yield Static("", id="footer-right")

        def on_mount(self) -> None:
            table = self.query_one("#table", DataTable)
            table.cursor_type = "row"
            table.zebra_stripes = False
            table.show_header = True
            table.add_column("", width=2)
            table.add_column("Application")
            table.add_column("Size", width=9)
            table.add_column("Status", width=13)
            self._update_all()
            table.focus()
            try:
                from .watcher import create_watcher

                def on_change():
                    self.call_from_thread(self._rescan_silent)

                self._watcher = create_watcher(self.directory, on_change)
            except Exception:
                pass

        def on_unmount(self) -> None:
            if self._watcher:
                try:
                    self._watcher.stop()
                except Exception:
                    pass

        def _filtered_sorted(self) -> list[AppImageEntry]:
            filtered = self.entries
            if self.filter_text:
                q = self.filter_text.casefold()
                filtered = [
                    e
                    for e in self.entries
                    if q in e.name.casefold()
                    or q in e.effective_display_name().casefold()
                    or q in e.comment.casefold()
                    or q in e.path.casefold()
                ]
            if self.sort_mode == "name":
                return sorted(filtered, key=lambda e: e.name.lower())
            elif self.sort_mode == "size":
                return sorted(filtered, key=lambda e: e.size, reverse=True)
            elif self.sort_mode == "mtime":
                return sorted(filtered, key=lambda e: e.mtime, reverse=True)
            return filtered

        def _update_all(self) -> None:
            self._update_table(restore_cursor=True)
            self._update_topbar()
            self._update_count()
            self._update_footer_left()

        def _update_table(self, restore_cursor: bool = False) -> None:
            try:
                table = self.query_one("#table", DataTable)
            except Exception:
                return
            prev_path: str | None = None
            try:
                idx0 = table.cursor_row
                if idx0 is not None and self._filtered and 0 <= idx0 < len(self._filtered):
                    prev_path = self._filtered[idx0].path
            except Exception:
                pass
            table.clear()
            self._filtered = self._filtered_sorted()
            for e in self._filtered:
                size = self._human_size(e.size)
                if e.desktop_integrated:
                    status = Text("● integrated", style="bold #a6e3a1")
                else:
                    status = Text("○ local", style="#7f849c")
                name = Text(self._short_name(e.effective_display_name(), 70), style="bold #ffffff")
                table.add_row(Text(""), name, Text(size, style="#cdd6f4"), status, key=e.path)
            if not self._filtered:
                if self.filter_text:
                    table.add_row("", Text(f"No matches for '{self.filter_text}'", style="italic #7f849c"), "", "")
                else:
                    table.add_row("", Text("No AppImages found - press r to rescan", style="italic #7f849c"), "", "")
            elif restore_cursor and prev_path:
                try:
                    for row_idx, e in enumerate(self._filtered):
                        if e.path == prev_path:
                            table.move_cursor(row=row_idx)
                            break
                except Exception:
                    pass
            self._refresh_markers()
            self._update_detail()
            self._update_footer_right()
            self._update_count()
            self._update_topbar()
            self._update_list_title()
            self.sub_title = (
                f"{len(self._filtered)}/{len(self.entries)} • {self.SORT_LABELS.get(self.sort_mode, self.sort_mode)}"
            )

        def _refresh_markers(self) -> None:
            # Slim selection gutter: "->" on the cursor row, blank elsewhere.
            try:
                table = self.query_one("#table", DataTable)
                cursor = table.cursor_row
            except Exception:
                return
            try:
                from textual.coordinate import Coordinate

                for idx in range(table.row_count):
                    marker = Text("->", style="bold #89b4fa") if idx == cursor else Text("")
                    table.update_cell_at(Coordinate(idx, 0), marker)
            except Exception:
                pass

        def _short_name(self, name: str, limit: int = 70) -> str:
            # Keep full AppImage names visible; only hard-truncate absurdly long ones.
            # The Location column was dropped so the name gets (almost) the full table width.
            if len(name) <= limit:
                return name
            return name[: max(0, limit - 1)] + "…"

        def _short_path(self, path: str, limit: int = 42) -> str:
            home = str(Path.home())
            display = path.replace(home, "~") if path.startswith(home) else path
            # Prefer keeping the filename (tail) visible - most useful for disambiguation.
            if len(display) > limit:
                return "…" + display[-(limit - 1) :]
            return display

        def _human_size(self, size: int) -> str:
            if size < 1024:
                return f"{size} B"
            elif size < 1024 * 1024:
                return f"{size / 1024:.1f}K"
            elif size < 1024 * 1024 * 1024:
                return f"{size / 1024 / 1024:.1f}M"
            else:
                return f"{size / 1024 / 1024 / 1024:.2f}G"

        def _current_entry(self) -> AppImageEntry | None:
            try:
                table = self.query_one("#table", DataTable)
                idx = table.cursor_row
            except Exception:
                return None
            if idx is None or not self._filtered or idx >= len(self._filtered):
                return None
            return self._filtered[idx]

        def _library_stats(self) -> tuple[int, int, int]:
            """Aggregate over the full library: (total_bytes, integrated_count, local_count)."""
            total = sum(e.size for e in self.entries)
            integrated = sum(1 for e in self.entries if e.desktop_integrated)
            return total, integrated, len(self.entries) - integrated

        def _completion_names(self) -> list[str]:
            """Candidate names for search autocomplete, alphabetical and deduplicated."""
            return sorted(
                {e.effective_display_name() for e in self.entries},
                key=str.lower,
            )

        def _topbar_segments(self) -> list[tuple[str, str]]:
            """(text, style) segments for the topbar library summary. Single source of truth."""
            if len(self.directory) == 1:
                home = str(Path.home())
                d = str(self.directory[0])
                d_short = d.replace(home, "~") if d.startswith(home) else d
            else:
                d_short = f"{len(self.directory)} folders"
            total, integrated, local = self._library_stats()
            return [
                (f"󰉋  {d_short}  ", "#7f849c"),
                (f"{self._human_size(total)} total", "bold #cdd6f4"),
                ("  ·  ", "#7f849c"),
                (f"● {integrated} integrated", "bold #a6e3a1"),
                ("  ·  ", "#7f849c"),
                (f"○ {local} local", "#7f849c"),
            ]

        def _topbar_dirs_text(self) -> str:
            """Plain-text topbar summary (folder · disk usage · integration counts)."""
            return "".join(seg for seg, _ in self._topbar_segments())

        def _stats_text(self) -> str:
            """Text for the topbar sort pill (totals live in #count)."""
            sort_label = self.SORT_LABELS.get(self.sort_mode, self.sort_mode)
            return f" ⇅ {sort_label} "

        def _update_topbar(self) -> None:
            try:
                dirs_w = self.query_one("#dirs", Static)
                stats_w = self.query_one("#stats", Static)
            except Exception:
                return
            text = Text()
            for seg, style in self._topbar_segments():
                text.append(seg, style=style)
            dirs_w.update(text)
            stats_w.update(self._stats_text())

        def _update_count(self) -> None:
            try:
                c = self.query_one("#count", Static)
            except Exception:
                return
            if self.filter_text:
                c.update(f"⌕ {len(self._filtered)}/{len(self.entries)}")
            else:
                c.update(f"{len(self.entries)} apps")

        def _update_list_title(self) -> None:
            try:
                t = self.query_one("#list-title", Static)
            except Exception:
                return
            sort_label = self.SORT_LABELS.get(self.sort_mode, self.sort_mode)
            t.update(Text(f"─ APPLICATIONS  ({len(self._filtered)})   ·   ⇅ {sort_label}", style="bold #7f849c"))

        def _update_detail(self) -> None:
            try:
                detail = self.query_one("#detail", Static)
            except Exception:
                return
            e = self._current_entry()
            if e is None:
                if self.filter_text:
                    detail.update(
                        Text.from_markup(
                            f"[bold #cdd6f4]No results[/]\n\n[dim]No match for '{self.filter_text}'.[/dim]\n\n[dim]Press Esc to clear the filter.[/dim]"
                        )
                    )
                else:
                    detail.update(
                        Text.from_markup(
                            "[bold #cdd6f4]No selection[/]\n\n[dim]Select an AppImage from the list to view details.[/dim]"
                        )
                    )
                return
            title = e.effective_display_name()
            if len(title) > 44:
                title = title[:43] + "…"
            size_s = self._human_size(e.size)
            if e.desktop_integrated:
                integ_badge = "[black on #a6e3a1] ● INTEGRATED [/]"
            else:
                integ_badge = "[#7f849c on #313244] ○ LOCAL [/]"
            exec_badge = "[black on #89b4fa] ✓ EXEC [/]" if e.executable else "[black on #f38ba8] ✕ NOEXEC [/]"
            home = str(Path.home())
            loc_full = e.path.replace(home, "~") if e.path.startswith(home) else e.path
            parent = str(Path(loc_full).parent)
            lines = [
                f"[bold #ffffff]{title}[/]",
            ]
            if e.display_name and e.display_name != e.name:
                lines.append(f"[italic #7f849c]{e.name}[/]")
            lines.append("")
            lines.append(f"[#89b4fa]{size_s}[/]  {integ_badge}  {exec_badge}")
            lines.append("")
            lines.append("[#45475a]──────────────────────────────[/#45475a]")
            lines.append(f"[#7f849c]Location  [/#7f849c][#cdd6f4]{parent}[/]")
            lines.append(f"[#7f849c]File      [/#7f849c][#cdd6f4]{e.name}[/]")
            lines.append(f"[#7f849c]Modified  [/#7f849c][#cdd6f4]{self._format_mtime(e.mtime)}[/]")
            if e.version:
                lines.append(f"[#7f849c]Version   [/#7f849c][#cdd6f4]{e.version}[/]")
            if e.categories:
                lines.append(f"[#7f849c]Category  [/#7f849c][#cdd6f4]{e.categories}[/]")
            if e.comment:
                comment = e.comment if len(e.comment) <= 140 else e.comment[:139] + "…"
                lines.append(f"[#7f849c]About     [/#7f849c][italic #a6adc8]{comment}[/]")
            detail.update(Text.from_markup("\n".join(lines)))

        def _update_footer_left(self) -> None:
            try:
                left = self.query_one("#footer-left", Static)
            except Exception:
                return
            left.update(
                Text.from_markup(
                    "[bold black on #89b4fa] q [/][bold #89b4fa] quit [/]  "
                    "[bold black on #74c7ec] / [/][bold #74c7ec] search [/]  "
                    "[bold black on #cba6f7] s [/][bold #cba6f7] sort [/]  "
                    "[bold black on #a6e3a1] r [/][bold #a6e3a1] rescan [/]  "
                    "[bold black on #fab387] o [/][bold #fab387] open [/]  "
                    "[bold black on #f9e2af] y [/][bold #f9e2af] copy [/]  "
                    "[bold white on #f38ba8] d [/][bold #f38ba8] delete [/]  "
                    "[bold black on #94e2d5] i [/][bold #94e2d5] integrate [/]  "
                    "[bold black on #bac2de] ? [/][bold #bac2de] help [/]"
                )
            )

        def _update_footer_right(self) -> None:
            try:
                right = self.query_one("#footer-right", Static)
            except Exception:
                return
            e = self._current_entry()
            if e is None:
                if self.filter_text:
                    right.update(Text("Esc to clear search", style="bold #f9e2af"))
                else:
                    right.update(Text("↑↓ navigate", style="#7f849c"))
                return
            name = self._short_name(e.effective_display_name(), 40)
            right.update(Text.from_markup(f"[bold #a6e3a1]⏎ Launch[/] [bold #ffffff]{name}[/]"))

        def _update_footer(self) -> None:
            self._update_footer_left()
            self._update_footer_right()

        def _format_mtime(self, mtime: float) -> str:
            import datetime

            try:
                dt = datetime.datetime.fromtimestamp(mtime)
                return dt.strftime("%b %d, %Y %H:%M")
            except Exception:
                return "-"

        def _launch_entry(self, e: AppImageEntry | None) -> None:
            if e is None:
                return
            try:
                self.launcher.validate_entry(e)
                self.launcher.launch(e)
                self.launched_entry = e
                self.exit(e)
            except Exception as ex:
                self.notify(f"Launch failed: {ex}", severity="error")

        def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
            idx = event.cursor_row
            if idx is None or idx >= len(self._filtered):
                return
            self._launch_entry(self._filtered[idx])

        def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
            self._refresh_markers()
            self._update_detail()
            self._update_footer_right()

        def _close_search(self, value: str) -> None:
            """Apply a search query from the popup, close it, and refocus the table."""
            self.filter_text = value.strip()
            try:
                modal_open = isinstance(self.screen, SearchScreen)
            except Exception:
                modal_open = False
            if modal_open:
                self.pop_screen()
            self._update_table()
            try:
                self.query_one("#table", DataTable).focus()
            except Exception:
                pass

        def on_key(self, event) -> None:
            # The search popup owns every keystroke while it is open.
            if isinstance(self.screen, SearchScreen):
                return
            # Global j/k navigation when table is focused (vim-style).
            if event.key in ("j", "k"):
                try:
                    table = self.query_one("#table", DataTable)
                except Exception:
                    return
                if event.key == "j":
                    table.action_cursor_down()
                else:
                    table.action_cursor_up()
                event.prevent_default()

        def action_escape_key(self) -> None:
            if isinstance(self.screen, SearchScreen):
                # The popup handles Escape itself (clear + close).
                return
            # Quit from anywhere else.
            self.exit(None)

        def action_search(self) -> None:
            try:
                if isinstance(self.screen, SearchScreen):
                    self.screen.query_one("#search-box", Input).focus()
                    return
            except Exception:
                pass
            self.push_screen(SearchScreen(self.filter_text))

        def action_launch(self) -> None:
            if isinstance(self.screen, SearchScreen):
                return
            self._launch_entry(self._current_entry())

        def action_cursor_down(self) -> None:
            try:
                table = self.query_one("#table", DataTable)
                table.focus()
                table.action_cursor_down()
            except Exception:
                pass

        def action_cursor_up(self) -> None:
            try:
                table = self.query_one("#table", DataTable)
                table.focus()
                table.action_cursor_up()
            except Exception:
                pass

        def action_cursor_top(self) -> None:
            try:
                table = self.query_one("#table", DataTable)
                table.focus()
                table.move_cursor(row=0)
            except Exception:
                pass

        def action_cursor_bottom(self) -> None:
            try:
                table = self.query_one("#table", DataTable)
                table.focus()
                if self._filtered:
                    table.move_cursor(row=len(self._filtered) - 1)
            except Exception:
                pass

        def action_sort(self) -> None:
            modes = ["name", "size", "mtime"]
            idx = modes.index(self.sort_mode)
            self.sort_mode = modes[(idx + 1) % len(modes)]
            label = self.SORT_LABELS.get(self.sort_mode, self.sort_mode)
            self.notify(f"Sort: {label}")
            self._update_table()

        def action_rescan(self) -> None:
            self._rescan_silent()
            self.notify(f"Rescanned, found {len(self.entries)} apps")

        def _rescan_silent(self) -> None:
            from .index import AppImageIndex

            idx = AppImageIndex()
            try:
                if len(self.directory) == 1:
                    self.entries = idx.scan(self.directory[0])
                else:
                    self.entries = idx.scan(self.directory)
                self._update_table()
            except Exception as e:
                self.notify(f"Rescan failed: {e}", severity="error")

        def action_open_folder(self) -> None:
            try:
                subprocess.Popen(
                    ["xdg-open", str(self.primary_dir)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                self.notify(f"Opened {self.primary_dir}")
            except Exception as e:
                self.notify(f"Failed to open: {e}", severity="error")

        def action_copy_path(self) -> None:
            e = self._current_entry()
            if e is None:
                return
            # Copies the selected AppImage's FULL file path to the system clipboard
            # (Wayland: wl-copy, X11: xclip/xsel). Paste with Ctrl+V / Ctrl+Shift+V.
            try:
                if shutil.which("wl-copy"):
                    subprocess.run(["wl-copy"], input=e.path.encode(), timeout=2)
                    self.notify(f"Copied to clipboard (wl-copy): {e.path}")
                elif shutil.which("xclip"):
                    subprocess.run(["xclip", "-selection", "clipboard"], input=e.path.encode(), timeout=2)
                    self.notify(f"Copied to clipboard (xclip): {e.path}")
                elif shutil.which("xsel"):
                    subprocess.run(["xsel", "--clipboard", "--input"], input=e.path.encode(), timeout=2)
                    self.notify(f"Copied to clipboard (xsel): {e.path}")
                else:
                    self.notify(
                        f"No clipboard tool found - path is: {e.path} (install wl-copy/xclip)", severity="warning"
                    )
            except Exception as e2:
                self.notify(f"Copy failed: {e2}", severity="error")

        def action_delete(self) -> None:
            e = self._current_entry()
            if e is None:
                return

            def do_delete():
                p = Path(e.path)
                try:
                    if shutil.which("gio"):
                        result = subprocess.run(["gio", "trash", str(p)], timeout=5)
                        if result.returncode != 0:
                            # Trash unsupported/failed (e.g. system mounts): fall back
                            # to a permanent delete instead of silently keeping the file.
                            p.unlink()
                    else:
                        p.unlink()
                    self.notify(f"Deleted {e.name}")
                    self.entries = [x for x in self.entries if x.path != e.path]
                    try:
                        from .desktop import remove_integration

                        remove_integration(p)
                    except Exception:
                        pass
                    self._update_table()
                except Exception as ex:
                    self.notify(f"Delete failed: {ex}", severity="error")

            self.push_screen(ConfirmScreen(f"Move '{e.effective_display_name()}' to trash?", f"{e.path}", do_delete))

        def action_integrate(self) -> None:
            # Toggle desktop integration: install the .desktop entry + icon,
            # or remove them again when already integrated.
            e = self._current_entry()
            if e is None:
                return
            try:
                if e.desktop_integrated:
                    from .desktop import remove_integration

                    removed = remove_integration(Path(e.path))
                    e.desktop_integrated = False
                    if removed:
                        self.notify(f"Removed desktop integration for {e.name}")
                    else:
                        self.notify(f"No integration found for {e.name} - marked as local")
                    self._update_table()
                    return
                from .desktop import integrate

                dest = integrate(Path(e.path))
                self.notify(f"Integrated {e.name} -> {dest}")
                e.desktop_integrated = True
                self._update_table()
            except Exception as ex:
                self.notify(f"Integration failed: {ex}", severity="error")

        def action_help(self) -> None:
            self.push_screen(HelpScreen())

    class EntrySuggester(Suggester):
        """Complete the search box from app names in the current library.

        The candidate provider is called on every keystroke (no cache) so a
        rescan is always reflected. Matching is case insensitive; the first
        name in alphabetical order that starts with the query wins.
        """

        def __init__(self, candidates) -> None:
            super().__init__(use_cache=False, case_sensitive=False)
            self._candidates = candidates

        async def get_suggestion(self, value: str) -> str | None:
            if not value:
                return None
            for name in self._candidates():
                folded = name.casefold()
                if folded.startswith(value) and len(folded) > len(value):
                    return name
            return None

    class SearchScreen(ModalScreen):
        """Search popup: opened with `/`, closed with Enter (apply) or Esc (clear)."""

        def __init__(self, initial: str = "") -> None:
            super().__init__()
            self._initial = initial

        def compose(self) -> ComposeResult:
            with Center(), Middle(), Vertical(id="search-card"):
                yield Static("⌕  Search applications", id="search-title")
                yield Input(
                    value=self._initial,
                    placeholder="Type to narrow the list…",
                    id="search-box",
                    suggester=EntrySuggester(self.app._completion_names),
                )
                yield Static("Enter applies  ·  → completes  ·  Esc clears and closes", id="search-hint")

        def on_mount(self) -> None:
            self.query_one("#search-box", Input).focus()

        def on_input_submitted(self, event: Input.Submitted) -> None:
            if event.input.id == "search-box":
                event.prevent_default()
                event.stop()
                self.app._close_search(event.value)

        def on_key(self, event) -> None:
            if event.key == "escape":
                event.prevent_default()
                event.stop()
                self.app._close_search("")

    class HelpScreen(ModalScreen):
        def compose(self) -> ComposeResult:
            with Center(), Vertical(id="help-card"):
                yield Static("󰋖  Keyboard shortcuts", id="help-title")
                yield Static(
                    Text.from_markup(
                        "[bold #ffffff]Navigate[/]\n"
                        "  [bold black on #bac2de] ↑↓ [/] / [bold black on #bac2de] j k [/]  move selection\n"
                        "  [bold black on #bac2de] g [/] / [bold black on #bac2de] G [/]  jump to top / bottom\n"
                        "  [bold black on #a6e3a1] ⏎ [/]  launch selected app\n"
                        "  [bold black on #89b4fa] q [/] / [bold black on #bac2de] Esc [/]  quit\n\n"
                        "[bold #ffffff]Search & view[/]\n"
                        "  [bold black on #74c7ec] / [/]  open search popup\n"
                        "  [bold black on #bac2de] Esc [/]  clear + close search, or quit\n"
                        "  [bold black on #cba6f7] s [/]  cycle sort: Name → Size → Recent\n"
                        "  [bold black on #a6e3a1] r [/]  rescan folders\n\n"
                        "[bold #ffffff]Actions[/]\n"
                        "  [bold black on #fab387] o [/]  open folder in file manager\n"
                        "  [bold black on #f9e2af] y [/]  copy full file path to system clipboard\n"
                        "  [bold black on #94e2d5] i [/]  install or remove desktop integration\n"
                        "  [bold white on #f38ba8] d [/]  move to trash (with confirm)\n"
                    ),
                    id="help-body",
                )
                with Center():
                    yield Button("Close  (Esc)", variant="primary", id="close")

        def on_button_pressed(self, event: Button.Pressed) -> None:
            self.dismiss()

        def on_key(self, event) -> None:
            if event.key in ("escape", "q", "?"):
                self.dismiss()

    class ConfirmScreen(ModalScreen):
        def __init__(self, message: str, detail: str = "", on_confirm=None):
            super().__init__()
            self.message = message
            self.detail = detail
            self.on_confirm = on_confirm

        def compose(self) -> ComposeResult:
            with Center(), Vertical(id="confirm-card"):
                yield Static("⚠  Confirm delete", id="help-title")
                yield Static(Text(self.message, style="bold #ffffff"), id="confirm-msg")
                if self.detail:
                    yield Static(Text(self.detail, style="#7f849c"), id="confirm-detail")
                with Horizontal(id="confirm-buttons"):
                    yield Button("Cancel (Esc)", variant="default", id="cancel")
                    yield Button("Move to trash", variant="error", id="confirm")

        def on_button_pressed(self, event: Button.Pressed) -> None:
            if event.button.id == "confirm":
                self.dismiss()
                if self.on_confirm:
                    self.on_confirm()
            else:
                self.dismiss()

        def on_key(self, event) -> None:
            if event.key == "escape":
                self.dismiss()

else:
    TextualTUI = RichTUI
