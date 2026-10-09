from __future__ import annotations

import json
from pathlib import Path

from rich.console import Console

from .cli import build_parser
from .config import ConfigStore
from .index import AppImageIndex
from .launcher import AppLauncher, LaunchError
from .models import AppImageEntry
from .paths import APP_VERSION, DATA_DIR, INDEX_PATH
from .tui import RichTUI


def main() -> None:
    console = Console()
    parser = build_parser()
    args, unknown = parser.parse_known_args()

    extra_args = []
    if args.extra_args:
        extra = args.extra_args
        if extra and extra[0] == "--":
            extra = extra[1:]
        extra_args = extra

    if unknown:
        extra_args.extend(unknown)

    try:
        config = ConfigStore()
        index = AppImageIndex()
        launcher = AppLauncher()

        if args.config:
            _handle_config(console, config, index)
            return
        if args.forget:
            config.clear()

            try:
                if INDEX_PATH.exists():
                    INDEX_PATH.unlink()
            except OSError:
                pass
            console.print("[green]Cleared saved directory and index.[/green]")
            return

        directories = _resolve_directories(args.dir, config, args.recursive)

        if args.check_updates:
            entries = _load_entries(index, directories, args.rescan or args.dir is not None, recursive=args.recursive)
            _handle_check_updates(console, entries)
            return

        if args.integrate is not None:
            entries = _load_entries(index, directories, args.rescan or args.dir is not None, recursive=args.recursive)
            _handle_integrate(console, entries, args.integrate)
            return
        if args.remove_integration is not None:
            entries = _load_entries(index, directories, args.rescan or args.dir is not None, recursive=args.recursive)
            _handle_remove_integration(console, entries, args.remove_integration)
            return

        entries = _load_entries(index, directories, args.rescan or args.dir is not None, recursive=args.recursive)

        if args.verbose:
            console.print(f"[dim]Directories: {', '.join(str(d) for d in directories)}[/dim]")
            console.print(f"[dim]Found {len(entries)} AppImages[/dim]")
            ok, msg = launcher.check_fuse()
            if not ok:
                console.print(f"[yellow]Warning: {msg}[/yellow]")

        if args.list:
            _handle_list(console, entries, directories, args.json)
            return

        if args.launch:
            try:
                entry = launcher.launch_by_name(entries, args.launch, extra_args=extra_args if extra_args else None)
                console.print(f"Launching {entry.name}")
            except LaunchError as e:
                console.print(f"[bold red]Launch error:[/bold red] {e}")
                raise SystemExit(1) from e
            return

        primary = directories[0] if len(directories) == 1 else directories

        tui = RichTUI(
            entries=entries,
            directory=primary,
            launcher=launcher,
            console=console,
            watch=args.watch,
        )

        if args.recursive:
            tui._recursive = True

        tui.run()

    except (FileNotFoundError, NotADirectoryError) as error:
        console.print(f"[bold red]Error:[/bold red] {error}")
        raise SystemExit(1) from error
    except PermissionError as error:
        console.print(f"[bold red]Permission error:[/bold red] {error}")
        raise SystemExit(1) from error
    except LaunchError as error:
        console.print(f"[bold red]Launch failed:[/bold red] {error}")
        raise SystemExit(1) from error


def _resolve_directories(
    cli_directories: list[Path] | None, config: ConfigStore, recursive: bool = False
) -> list[Path]:
    if cli_directories:
        dirs = [d.expanduser().resolve() for d in cli_directories]

        for d in dirs:
            if not d.exists():
                raise FileNotFoundError(f"Directory does not exist: {d}")
            if not d.is_dir():
                raise NotADirectoryError(f"Not a directory: {d}")
        config.save_directories(dirs)
        return dirs

    saved = config.get_directories()
    if saved:
        existing = [d.expanduser().resolve() for d in saved if d.expanduser().exists()]
        if existing:
            return existing

        return [d.expanduser().resolve() for d in saved]

    raise SystemExit("No AppImage directory configured. Use --dir PATH. Tried ~/AppImages and ~/Applications.")


def _load_entries(
    index: AppImageIndex,
    directories: list[Path],
    should_scan: bool,
    recursive: bool = False,
) -> list[AppImageEntry]:
    if should_scan:
        return index.scan(directories, recursive=recursive)

    indexed_dirs, entries = index.load_with_dirs()

    def norm(p: Path) -> Path:
        return p.expanduser().resolve()

    if indexed_dirs and entries:
        cached_set = {norm(d) for d in indexed_dirs}
        req_set = {norm(d) for d in directories}
        if cached_set == req_set:
            needs_migration = any(e.size == 0 or e.mtime == 0 for e in entries)

            if not needs_migration:
                try:
                    raw = json.loads(index.index_path.read_text(encoding="utf-8"))
                    if raw.get("version") != 2:
                        needs_migration = True
                except Exception:
                    needs_migration = True
            if needs_migration:
                return index.scan(directories, recursive=recursive)

            try:
                if hasattr(index, "is_stale") and not index.is_stale(directories, entries):
                    if all(Path(e.path).exists() for e in entries):
                        return entries
                else:
                    if index.is_stale(directories, entries):
                        return index.scan(directories, recursive=recursive)

                    if all(Path(e.path).exists() for e in entries):
                        return entries
            except OSError:
                pass

            try:
                disk_names = set()
                for d in directories:
                    d = norm(d)
                    if not d.is_dir():
                        continue

                    iterator = d.rglob("*") if recursive else d.iterdir()
                    for p in iterator:
                        if p.is_file() and p.suffix.lower() == ".appimage":
                            disk_names.add(p.name.lower())
                cached_names = {e.name.lower() for e in entries}
                if disk_names == cached_names and all(Path(e.path).exists() for e in entries):
                    return entries
            except OSError:
                pass

        return index.scan(directories, recursive=recursive)

    return index.scan(directories, recursive=recursive)


def _handle_list(console: Console, entries: list[AppImageEntry], directories: list[Path], as_json: bool) -> None:
    if as_json:
        data = {
            "directories": [str(d) for d in directories],
            "apps": [e.to_dict() for e in entries],
            "count": len(entries),
        }
        console.print_json(data=data)
        return
    if not entries:
        console.print(f"No AppImages found in [bold]{', '.join(str(d) for d in directories)}[/bold].")
        return
    from rich.table import Table

    table = Table(
        title=f"AppImages in {', '.join(str(d) for d in directories)}",
        show_header=True,
        header_style="bold cyan",
    )
    table.add_column("Name", style="bold")
    table.add_column("Size", justify="right")
    table.add_column("Integrated", justify="center")
    table.add_column("Path", overflow="fold")
    for e in entries:
        size = _human_size(e.size)
        integ = "✓" if e.desktop_integrated else "○"
        table.add_row(e.name, size, integ, e.path)
    console.print(table)
    console.print(f"[dim]Total: {len(entries)} AppImages[/dim]")


def _handle_config(console: Console, config: ConfigStore, index: AppImageIndex) -> None:
    data = config.load()
    dirs = config.get_directories()
    idx_dirs, entries = index.load_with_dirs()
    console.print(f"[bold]Config path:[/bold] {config.config_path} (alt: {config._alt_path})")
    console.print(f"[bold]Index path:[/bold] {index.index_path}")
    console.print(f"[bold]Data dir:[/bold] {DATA_DIR}")
    console.print(f"[bold]Saved directories:[/bold] {', '.join(str(d) for d in dirs) if dirs else 'none'}")
    console.print(f"[bold]Indexed directories:[/bold] {', '.join(str(d) for d in idx_dirs) if idx_dirs else 'none'}")
    console.print(f"[bold]Indexed apps:[/bold] {len(entries)}")
    console.print(f"[bold]Version:[/bold] {APP_VERSION}")
    if data:
        console.print_json(data=data)

    import os

    console.print(f"[dim]XDG_DATA_HOME={os.getenv('XDG_DATA_HOME', '(default)')}[/dim]")
    console.print(f"[dim]XDG_CONFIG_HOME={os.getenv('XDG_CONFIG_HOME', '(default)')}[/dim]")


def _handle_integrate(console: Console, entries: list[AppImageEntry], target: str) -> None:
    from .desktop import integrate, integrate_all

    if target == "all":
        count = integrate_all(entries)
        console.print(f"[green]Integrated {count} AppImages to desktop menu.[/green]")
        console.print("[dim]Desktop files in ~/.local/share/applications, run update-desktop-database if needed.[/dim]")
        return

    for e in entries:
        if e.name.casefold() == target.casefold() or target.casefold() in e.name.casefold():
            try:
                dest = integrate(Path(e.path))
                console.print(f"[green]Integrated {e.name} -> {dest}[/green]")
                return
            except Exception as ex:
                console.print(f"[red]Failed to integrate {e.name}: {ex}[/red]")
                raise SystemExit(1) from ex
    console.print(f"[red]No AppImage matching '{target}' found[/red]")
    raise SystemExit(1)


def _handle_remove_integration(console: Console, entries: list[AppImageEntry], target: str) -> None:
    from .desktop import remove_integration

    if target == "all":
        count = 0
        for e in entries:
            if remove_integration(Path(e.path)):
                count += 1

        from .paths import DESKTOP_DIR

        for p in DESKTOP_DIR.glob("e-applauncher-*.desktop"):
            try:
                p.unlink()
                count += 1
            except OSError:
                pass
        console.print(f"[green]Removed {count} integrations.[/green]")
        return
    for e in entries:
        if e.name.casefold() == target.casefold() or target.casefold() in e.name.casefold():
            if remove_integration(Path(e.path)):
                console.print(f"[green]Removed integration for {e.name}[/green]")
            else:
                console.print(f"[yellow]No integration found for {e.name}[/yellow]")
            return

    p = Path(target).expanduser()
    if p.exists():
        if remove_integration(p):
            console.print(f"[green]Removed integration for {p}[/green]")
            return
    console.print(f"[red]No AppImage matching '{target}' found[/red]")
    raise SystemExit(1)


def _handle_check_updates(console: Console, entries: list[AppImageEntry]) -> None:
    from .updates import check_all

    console.print("[bold]Checking for updates...[/bold]")
    results = check_all(entries)
    has_updates = False
    for entry, info in results:
        if info.get("has_update_info"):
            has_updates = True
            console.print(f"[yellow]• {entry.name}: has update info[/yellow] {info.get('hint', '')}")
        else:
            console.print(f"[dim]• {entry.name}: no update info[/dim]")
    if not has_updates:
        console.print("[dim]No AppImages with embedded update information found.[/dim]")
        console.print("[dim]Tip: AppImages built with appimage-builder and zsync will show here.[/dim]")


def _human_size(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    elif size < 1024 * 1024:
        return f"{size / 1024:.1f}K"
    elif size < 1024 * 1024 * 1024:
        return f"{size / 1024 / 1024:.1f}M"
    else:
        return f"{size / 1024 / 1024 / 1024:.2f}G"
