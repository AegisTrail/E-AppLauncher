from __future__ import annotations

import argparse
from pathlib import Path

from .paths import APP_VERSION


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="e-applauncher",
        description="E-AppLauncher - AppImage launcher for Linux",
        epilog="Examples: e-applauncher --dir ~/AppImages --list; e-applauncher --launch MyApp.AppImage -- --help",
    )
    parser.add_argument(
        "--dir",
        type=Path,
        dest="dir",
        help="Directory to scan for AppImage files. Saves as the current default directory. Can be used multiple times.",
        action="append",
    )
    parser.add_argument(
        "--recursive",
        action="store_true",
        help="Recursively scan subdirectories for AppImages.",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List indexed AppImages and exit.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="With --list, output JSON instead of table.",
    )
    parser.add_argument(
        "--launch",
        metavar="NAME",
        help="Launch a specific AppImage by file name and exit. Supports partial match.",
    )
    parser.add_argument(
        "--rescan",
        action="store_true",
        help="Rescan the saved directory before listing, launching, or opening the TUI.",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Verbose output.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {APP_VERSION}",
    )
    parser.add_argument(
        "--config",
        action="store_true",
        help="Show current config (directories, index path) and exit.",
    )
    parser.add_argument(
        "--forget",
        action="store_true",
        help="Clear saved directory config and exit.",
    )
    parser.add_argument(
        "--integrate",
        nargs="?",
        const="all",
        metavar="NAME",
        help="Create desktop integration for AppImage (or all with --integrate without arg).",
    )
    parser.add_argument(
        "--remove-integration",
        nargs="?",
        const="all",
        metavar="NAME",
        help="Remove desktop integration for AppImage (or all).",
    )
    parser.add_argument(
        "--no-integrate",
        action="store_true",
        help="Do not auto-integrate (reserved for future).",
    )
    parser.add_argument(
        "--watch",
        action="store_true",
        help="Watch directory for changes and keep TUI updated (requires watchdog or polling).",
    )
    parser.add_argument(
        "--check-updates",
        action="store_true",
        help="Check for AppImage updates (if update info available) and exit.",
    )
    parser.add_argument(
        "extra_args",
        nargs=argparse.REMAINDER,
        help="Extra args to pass to AppImage when using --launch. Use -- before args.",
    )
    return parser
