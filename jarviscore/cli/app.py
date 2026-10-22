"""
Typer application for the `jarviscore` command
"""

import sys
from importlib import import_module

import typer
from typer.core import TyperGroup

from ._commands import LEGACY_BY_NAME as _LEGACY_BY_NAME
from ._commands import LEGACY_COMMANDS as _LEGACY_COMMANDS
from ._commands import run_legacy as _run_legacy

# (command, module, entry function, help); the module loads only when the command runs.
_LAZY_COMMANDS = [
    ("dev", "dev", "dev_command", "Run all agents locally with Redis and live reload."),
    ("run", "run", "run_command", "Send one task to a running agent and print the result."),
    ("serve", "serve", "serve_command", "Run one agent from jarviscore.yaml."),
]
_LAZY_BY_NAME = {spec[0]: spec for spec in _LAZY_COMMANDS}


class _LazyGroup(TyperGroup):
    """Lists placeholder commands for help; swaps in the real one when it is invoked."""

    def resolve_command(self, ctx, args):
        if args and args[0] in _LAZY_BY_NAME:
            self.commands[args[0]] = _load_command(args[0])
        return super().resolve_command(ctx, args)


def _load_command(name: str):
    _, module, func, help_text = _LAZY_BY_NAME[name]
    sub = typer.Typer(add_completion=False)
    sub.command(name, help=help_text)(getattr(import_module(f"jarviscore.cli.{module}"), func))
    return typer.main.get_command(sub)


app = typer.Typer(
    name="jarviscore",
    help='''
        JarvisCore cli is a tool for managing and interacting with the JarvisCore runtime, where AI agents operate as a fleet of equal peers.
        Operations include project setup, agent infrastructure management, and operational inspection of running agents.
    ''',
    no_args_is_help=True,
    add_completion=False,
    cls=_LazyGroup,
)


def _register_legacy(name: str, help_text: str) -> None:
    # Only reached when `app` is invoked directly; `main` dispatches before Click parses.
    @app.command(
        name,
        help=help_text,
        add_help_option=False,
        context_settings={"allow_extra_args": True,
                          "ignore_unknown_options": True},
    )
    def _command(ctx: typer.Context) -> None:
        _run_legacy(name, ctx.args)


for _name, _, _, _help in _LEGACY_COMMANDS:
    _register_legacy(_name, _help)


def _register_commands() -> None:
    for name, _, _, help_text in _LAZY_COMMANDS:
        # Placeholder: _LazyGroup.resolve_command replaces it before it can run.
        app.command(name, help=help_text)(lambda: None)


_register_commands()


def main(argv: list | None = None) -> None:
    argv = sys.argv[1:] if argv is None else list(argv)
    # Legacy commands get raw argv (including a bare `--`)
    if argv and argv[0] in _LEGACY_BY_NAME:
        _run_legacy(argv[0], argv[1:])
        return
    command = typer.main.get_command(app)
    if not argv or (not argv[0].startswith("-") and argv[0] not in command.commands):
        if argv:
            print(f"Unknown command: {argv[0]}\n", file=sys.stderr)
        command.main(args=["--help"], prog_name="jarviscore",
                     standalone_mode=False)
        sys.exit(1)
    app(args=argv, prog_name="jarviscore")
