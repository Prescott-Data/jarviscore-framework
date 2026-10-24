"""Legacy argparse commands, shared by `__main__` (fast path) and the Typer app.

Kept dependency-free so dispatch never pays for importing Typer.
"""

import sys
from importlib import import_module

# (command, module, entry function, help)
LEGACY_COMMANDS = [
    ("init", "scaffold", "main",
     "Create a project: init NAME [--template minimal|support|research|pipeline]"),
    ("check", "check", "main", "Health check and validation"),
    ("smoketest", "smoketest", "main", "Quick smoke test"),
    ("nexus", "nexus", "main", "Manage Nexus auth (init, register, status, list, test)"),
    ("memory", "memory", "run", "Manage Athena MemOS (init, status, context, search)"),
    ("atom", "atom", "main", "Validate, test, and list integration atoms"),
    ("inspect", "inspect", "main", "Read recorded traces: what did my agents do?"),
    ("human", "human", "main", "Join the mesh as a person (join, inbox, answer)"),
    ("room", "room", "main", "Work together on a shared workspace (ask, diff, accept, watch)"),
]

LEGACY_BY_NAME = {spec[0]: spec for spec in LEGACY_COMMANDS}


def run_legacy(name: str, args: list) -> None:
    _, module, func, _ = LEGACY_BY_NAME[name]
    sys.argv = [sys.argv[0], *args]
    getattr(import_module(f"jarviscore.cli.{module}"), func)()
