"""
Typer application for the `jarviscore` command
"""

import sys
from importlib import import_module

import typer

app = typer.Typer(
    name="jarviscore",
    help="JarvisCore: build, run and deploy agent meshes.",
    no_args_is_help=True,
    add_completion=False,
)

# (command, module, entry function, help)
_LEGACY_COMMANDS = [
    ("init", "scaffold", "main",
     "Create a project: init NAME [--template minimal|support|research|pipeline]"),
    ("check", "check", "main", "Health check and validation"),
    ("smoketest", "smoketest", "main", "Quick smoke test"),
    ("nexus", "nexus", "main", "Manage Nexus auth (init, register, status, list, test)"),
    ("memory", "memory", "run", "Manage Athena MemOS (init, status, context, search)"),
    ("atom", "atom", "main", "Validate, test, and list integration atoms"),
    ("inspect", "inspect", "main", "Read recorded traces: what did my agents do?"),
]


def _run_legacy(name: str, args: list) -> None:
    _, module, func, _ = _LEGACY_BY_NAME[name]
    sys.argv = [sys.argv[0], *args]
    getattr(import_module(f"jarviscore.cli.{module}"), func)()


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


_LEGACY_BY_NAME = {spec[0]: spec for spec in _LEGACY_COMMANDS}
for _name, _, _, _help in _LEGACY_COMMANDS:
    _register_legacy(_name, _help)


def _register_commands() -> None:
    from .dev import dev_command
    from .serve import serve_command

    app.command("dev", help="Run all agents locally with Redis and live reload.")(
        dev_command)
    app.command("serve", help="Run one agent from jarviscore.yaml.")(
        serve_command)


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
