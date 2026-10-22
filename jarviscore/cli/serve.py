"""`jarviscore serve --role NAME`: run one agent from `jarviscore.yaml`.

This is the entry point used by containers and CI. The command resolves the agent's
environment from the project files, then replaces itself with a fresh interpreter
running `run_agent` (`python -m jarviscore.cli.serve ROOT AGENT_FILE`), because framework
settings are read once at import time and must see the final environment.
`jarviscore dev` builds the same environment and starts that runner directly.

The runner path imports neither Typer nor the project schema; the Typer command is
built on first access (`serve_command`, PEP 562).
"""

from __future__ import annotations

import importlib.util
import inspect
import os
import signal
import sys
import threading
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import asyncio

RUNNER_MODULE = "jarviscore.cli.serve"
RUNNER_USAGE = (
    "usage: python -m jarviscore.cli.serve PROJECT_ROOT AGENT_FILE\n"
    "Internal agent runner. To run an agent use: jarviscore serve --role NAME"
)
ORPHAN_STOP_TIMEOUT = 10.0
PARENT_PID_ENV = "JARVISCORE_DEV_PARENT_PID"
# Read only by the runner; `jarviscore dev` sets it so tasks are claimed promptly.
POLL_INTERVAL_ENV = "JARVISCORE_DISTRIBUTED_POLL_INTERVAL"


class ServeError(Exception):
    pass


def agent_env(loaded, role: str, replica: int, environ: dict[str, str]) -> dict[str, str]:
    """The runner's environment: project files, then `environ` (explicit env wins)."""
    from jarviscore.project import build_env

    env = build_env(loaded, role)
    env["JARVISCORE_NODE_NAME"] = f"{loaded.project.service}-{role}-{replica}"
    env.update(environ)
    return env


def agent_path(loaded, role: str) -> Path:
    project = loaded.project
    if role not in project.agents:
        raise ServeError(f"Unknown agent {role!r}. Defined agents: {', '.join(project.agents)}")
    agent_file = loaded.root / project.agents[role].path
    if not agent_file.is_file():
        raise ServeError(f"agents.{role}.path: {project.agents[role].path} does not exist")
    return agent_file


def runner_argv(python: str, root: Path, agent_file: Path) -> list[str]:
    return [python, "-m", RUNNER_MODULE, str(root), str(agent_file)]


def serve(role: str, destination: str | None, replica: int) -> int:
    """Resolve and exec the runner; returns an exit code only on failure."""
    from jarviscore.project import ProjectError, load_project

    from ._python import InterpreterError, ensure_jarviscore, project_python

    try:
        loaded = load_project(destination=destination)
        agent_file = agent_path(loaded, role)
    except (ProjectError, ServeError) as exc:
        print(str(exc), file=sys.stderr)
        return 2

    python, note = project_python(loaded.root)
    if note:
        print(note, file=sys.stderr)
    try:
        ensure_jarviscore(python, loaded.root)
    except InterpreterError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    # Explicit process env (from compose, CI) wins over the project files.
    env = agent_env(loaded, role, replica, dict(os.environ))
    os.chdir(loaded.root)
    sys.stdout.flush()
    sys.stderr.flush()
    os.execve(python, runner_argv(python, loaded.root, agent_file), env)
    return 0  # unreachable unless execve is stubbed


def _build_serve_command():
    import typer

    def serve_command(
        role: str = typer.Option(..., "--role", "-r", help="Agent name from jarviscore.yaml"),
        destination: str = typer.Option(None, "--destination", "-d", help="Environment overlay, e.g. prod"),
        replica: int = typer.Option(1, "--replica", min=1, help="Replica number, used in the node name"),
    ) -> None:
        """Run one agent from jarviscore.yaml."""
        code = serve(role, destination, replica)
        if code:
            raise typer.Exit(code)

    return serve_command


def __getattr__(name: str):
    if name == "serve_command":
        command = _build_serve_command()
        globals()[name] = command
        return command
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


class AgentResolutionError(Exception):
    pass


def resolve_agent(module):
    """`agent = ...` in the module wins; otherwise the single Agent subclass it defines."""
    from jarviscore import Agent

    explicit = getattr(module, "agent", None)
    if explicit is not None:
        if isinstance(explicit, Agent) or (inspect.isclass(explicit) and issubclass(explicit, Agent)):
            return explicit
        raise AgentResolutionError(
            f"`agent` in {module.__file__} must be an Agent subclass or instance, got {type(explicit).__name__}"
        )

    defined = [
        obj for obj in vars(module).values()
        if inspect.isclass(obj)
        and issubclass(obj, Agent)
        and obj.__module__ == module.__name__
        and not inspect.isabstract(obj)
        and getattr(obj, "role", None)
    ]
    if len(defined) == 1:
        return defined[0]
    if not defined:
        raise AgentResolutionError(
            f"No agent found in {module.__file__}. Define an Agent subclass with `role` and "
            f"`capabilities`, or set `agent = MyAgent()` at module level."
        )
    names = ", ".join(sorted(cls.__name__ for cls in defined))
    raise AgentResolutionError(
        f"{module.__file__} defines several agents ({names}). Pick one with `agent = <Name>` at module level."
    )


def load_agent_module(root: Path, agent_file: Path):
    # Project root on sys.path so agent files can import shared project modules.
    sys.path.insert(0, str(root))
    name = f"jarviscore_agent_{agent_file.stem}"
    spec = importlib.util.spec_from_file_location(name, agent_file)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def has_run_loop(agent) -> bool:
    """True when the agent (class or instance) overrides Agent.run() with its own loop."""
    from jarviscore import Agent

    cls = agent if inspect.isclass(agent) else type(agent)
    return getattr(cls, "run", Agent.run) is not Agent.run


async def run_agent(agent) -> None:
    import asyncio

    from jarviscore import Mesh

    config = {}
    poll = os.environ.get(POLL_INTERVAL_ENV, "")
    try:
        if float(poll) > 0:
            config["distributed_poll_interval"] = float(poll)
    except ValueError:
        pass
    mesh = Mesh(config=config) if config else Mesh()
    mesh.add(agent)

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)

    # Watch from the start: dev may die while this agent is still starting up.
    orphan_watch = asyncio.create_task(_stop_when_orphaned(stop))
    await mesh.start()
    if has_run_loop(agent):
        loops = asyncio.create_task(mesh.run_forever())
    else:
        # Task-driven agent (e.g. AutoAgent): its run() is the no-op default, and
        # run_forever() would see it return and stop the mesh (SWIM, ZMQ, task polling)
        # while this process stays up. Keep the mesh serving until signalled instead.
        loops = asyncio.create_task(stop.wait())
    stopper = asyncio.create_task(stop.wait())
    try:
        done, _ = await asyncio.wait({loops, stopper}, return_when=asyncio.FIRST_COMPLETED)
        if loops in done and loops.exception() is None and not stop.is_set():
            # No run() loop (workflow-driven agent): stay up until signalled.
            await stopper
    finally:
        for task in (loops, stopper, orphan_watch):
            task.cancel()
        await asyncio.gather(loops, stopper, orphan_watch, return_exceptions=True)
        await mesh.stop()
    if loops.done() and not loops.cancelled() and loops.exception():
        raise loops.exception()


async def _stop_when_orphaned(stop: asyncio.Event, interval: float = 1.0) -> bool:
    """Under `jarviscore dev`, shut down if dev dies without stopping us (e.g. kill -9)."""
    import asyncio

    expected = os.environ.get(PARENT_PID_ENV)
    if not expected or not expected.isdigit():
        return False
    while not stop.is_set():
        if os.getppid() != int(expected):
            _detach_output()
            _arm_exit_watchdog(ORPHAN_STOP_TIMEOUT)
            stop.set()
            return True
        await asyncio.sleep(interval)
    return False


def _arm_exit_watchdog(seconds: float) -> None:
    """Nobody is left to kill us if shutdown hangs on peers that are also going away.

    A thread, not the event loop: a stuck `mesh.stop()` (or a cancellation it swallows)
    would block a loop-based timeout, and non-daemon threads can block interpreter exit.
    """
    timer = threading.Timer(seconds, os._exit, args=(0,))
    timer.daemon = True
    timer.start()


def _detach_output() -> None:
    """dev read our output through a pipe; with dev gone every write would raise
    BrokenPipeError, so point stdout/stderr at /dev/null before shutting down."""
    try:
        devnull = os.open(os.devnull, os.O_WRONLY)
        for stream in (sys.stdout, sys.stderr):
            try:
                stream.flush()
            except (OSError, ValueError):
                pass
            os.dup2(devnull, stream.fileno())
        os.close(devnull)
    except (OSError, ValueError):
        pass


def _runner_main(argv: list) -> int:
    if len(argv) != 2 or any(a.startswith("-") for a in argv):
        print(RUNNER_USAGE, file=sys.stderr)
        return 2
    root, agent_file = Path(argv[0]), Path(argv[1])
    if not root.is_dir() or not agent_file.is_file():
        print(f"{agent_file if root.is_dir() else root} does not exist\n{RUNNER_USAGE}",
              file=sys.stderr)
        return 2
    try:
        agent = resolve_agent(load_agent_module(root, agent_file))
    except AgentResolutionError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    import asyncio

    asyncio.run(run_agent(agent))
    return 0


if __name__ == "__main__":
    sys.exit(_runner_main(sys.argv[1:]))
