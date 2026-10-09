"""Parser-level tests: every flag, defaults, combos and edge cases."""

import pytest

from e_app_launcher.cli import build_parser


def parse(*argv):
    return build_parser().parse_args(list(argv))


def test_defaults():
    args = parse()
    assert args.dir is None
    assert args.recursive is False
    assert args.list is False
    assert args.json is False
    assert args.launch is None
    assert args.rescan is False
    assert args.verbose is False
    assert args.config is False
    assert args.forget is False
    assert args.integrate is None
    assert args.remove_integration is None
    assert args.no_integrate is False
    assert args.watch is False
    assert args.check_updates is False
    assert args.extra_args == []


def test_dir_single_and_multi(tmp_path):
    args = parse("--dir", str(tmp_path))
    assert len(args.dir) == 1
    args = parse("--dir", "/a", "--dir", "/b")
    assert len(args.dir) == 2


def test_dir_tilde_kept_as_path():
    args = parse("--dir", "~/AppImages")
    assert str(args.dir[0]) == "~/AppImages"


def test_recursive_list_json_flags():
    args = parse("--recursive", "--list", "--json")
    assert args.recursive and args.list and args.json


def test_launch_with_value():
    args = parse("--launch", "Joplin")
    assert args.launch == "Joplin"


def test_launch_requires_value():
    with pytest.raises(SystemExit):
        parse("--launch")


def test_rescan_verbose_short_flag():
    assert parse("--rescan").rescan is True
    assert parse("--verbose").verbose is True
    assert parse("-v").verbose is True


def test_version_exits(capfd):
    with pytest.raises(SystemExit) as exc:
        parse("--version")
    assert exc.value.code == 0
    out = capfd.readouterr().out
    assert "e-applauncher" in out


def test_config_forget_watch_check_updates():
    args = parse("--config")
    assert args.config is True
    args = parse("--forget")
    assert args.forget is True
    args = parse("--watch")
    assert args.watch is True
    args = parse("--check-updates")
    assert args.check_updates is True


def test_integrate_bare_means_all():
    assert parse("--integrate").integrate == "all"
    assert parse("--integrate", "Foo.AppImage").integrate == "Foo.AppImage"
    assert parse("--remove-integration").remove_integration == "all"
    assert parse("--remove-integration", "Foo").remove_integration == "Foo"


def test_no_integrate_reserved_noop():
    assert parse("--no-integrate").no_integrate is True


def test_extra_args_after_double_dash():
    args = parse("--launch", "Foo", "--", "--help", "-v")
    assert args.launch == "Foo"
    assert args.extra_args == ["--", "--help", "-v"]


def test_unknown_flags_land_in_extra_via_known_args():
    # main() uses parse_known_args: unknown flags flow to the AppImage as extra_args.
    parser = build_parser()
    args, unknown = parser.parse_known_args(["--launch", "Foo", "--unknown-flag", "x"])
    assert args.launch == "Foo"
    assert unknown == ["--unknown-flag"]  # unknown optionals land here...
    assert args.extra_args == ["x"]  # ...bare words land in REMAINDER; main() forwards both


def test_json_without_list_parses():
    # --json alone is accepted by the parser; app.py ignores it without --list.
    args = parse("--json")
    assert args.json is True
    assert args.list is False


def test_prog_name():
    assert build_parser().prog == "e-applauncher"
