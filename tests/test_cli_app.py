"""The Typer app must route every legacy command to its original parser unchanged."""

import subprocess
import sys

import pytest
from typer.testing import CliRunner

from jarviscore.cli.app import _LEGACY_COMMANDS, app, main

runner = CliRunner()


@pytest.fixture
def captured(monkeypatch):
    """Replace each legacy entry point with a stub that records the argv it saw."""
    from importlib import import_module

    calls = {}
    for name, module, func, _ in _LEGACY_COMMANDS:
        def stub(name=name):
            calls[name] = list(sys.argv[1:])
        monkeypatch.setattr(import_module(
            f"jarviscore.cli.{module}"), func, stub)
    return calls


def test_help_lists_every_legacy_command():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for name, *_ in _LEGACY_COMMANDS:
        assert name in result.output


@pytest.mark.parametrize("name", [c[0] for c in _LEGACY_COMMANDS])
def test_legacy_command_receives_args_untouched(captured, name):
    args = ["sub", "--flag", "value", "-x", "--", "--literal"]
    main([name, *args])
    assert captured[name] == args


def test_legacy_command_via_app_still_routes(captured):
    result = runner.invoke(app, ["inspect", "run-1", "--errors"])
    assert result.exit_code == 0, result.output
    assert captured["inspect"] == ["run-1", "--errors"]


def test_legacy_help_is_the_original_argparse_help():
    result = runner.invoke(app, ["check", "--help"])
    assert result.exit_code == 0
    assert "--validate-llm" in result.output


def test_legacy_exit_code_is_preserved(monkeypatch):
    from jarviscore.cli import inspect as inspect_cli

    def fail():
        sys.exit(3)

    monkeypatch.setattr(inspect_cli, "main", fail)
    with pytest.raises(SystemExit) as exc:
        main(["inspect"])
    assert exc.value.code == 3


def test_unknown_command_is_a_usage_error_with_a_suggestion(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["no-such-command"])
    assert exc.value.code == 2
    captured = capsys.readouterr()
    assert "Unknown command: no-such-command" in captured.err
    assert "Did you mean" not in captured.err
    assert captured.out == "", "must not dump the full help"

    with pytest.raises(SystemExit) as exc:
        main(["serv"])
    assert exc.value.code == 2
    assert "Did you mean 'serve'?" in capsys.readouterr().err


def test_version_flag(capsys):
    from importlib.metadata import version

    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert capsys.readouterr().out.strip() == f"jarviscore {version('jarviscore-framework')}"


@pytest.mark.parametrize("args", [["-h"], ["dev", "-h"], ["run", "-h"], ["serve", "-h"]])
def test_short_help_everywhere(args):
    out = subprocess.run([sys.executable, "-m", "jarviscore.cli", *args],
                         capture_output=True, text=True, check=False)
    assert out.returncode == 0, out.stderr
    assert out.stdout.startswith("Usage: jarviscore")
    assert "\x1b[" not in out.stdout and "─" not in out.stdout, "help must be plain text"


def test_no_args_shows_help_and_exits_1_like_before(capsys):
    with pytest.raises(SystemExit) as exc:
        main([])
    assert exc.value.code == 1
    out = capsys.readouterr().out
    assert "check" in out and "inspect" in out


def test_console_entry_point_and_module_invocation():
    out = subprocess.run(
        [sys.executable, "-m", "jarviscore.cli", "check", "--help"],
        capture_output=True, text=True, check=False,
    )
    assert out.returncode == 0 and "--validate-llm" in out.stdout

    direct = subprocess.run(
        [sys.executable, "-m", "jarviscore.cli.check", "--help"],
        capture_output=True, text=True, check=False,
    )
    assert direct.returncode == 0 and "--validate-llm" in direct.stdout
