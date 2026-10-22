"""`jarviscore serve --role NAME`: run one agent from `jarviscore.yaml`.

This is the single entry point used by `jarviscore dev`, containers and CI. The command
resolves the agent's environment from the project files, then replaces itself with a
fresh interpreter running `run_agent`, because framework settings are read once at
import time and must see the final environment.
"""

import asyncio
import importlib.util
import inspect
import os
import signal
import sys
from pathlib import Path

import typer

from jarviscore.project import ProjectError, build_env, load_project

RUNNER_MODULE = "jarviscore.cli.serve"
ORPHAN_STOP_TIMEOUT = 20.0


def serve_command(
    role: str = typer.Option(..., "--role", "-r", help="Agent name from jarviscore.yaml"),
    destination: str = typer.Option(None, "--destination", "-d", help="Environment overlay, e.g. prod"),
    replica: int = typer.Option(1, "--replica", min=1, help="Replica number, used in the node name"),
) -> None:
    """Run one agent from jarviscore.yaml."""
    try:
        loaded = load_project(destination=destination)
    except ProjectError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(2) from None

    project = loaded.project
    if role not in project.agents:
        typer.echo(f"Unknown agent {role!r}. Defined agents: {', '.join(project.agents)}", err=True)
        raise typer.Exit(2)

    agent_file = loaded.root / project.agents[role].path
    if not agent_file.is_file():
        typer.echo(f"agents.{role}.path: {project.agents[role].path} does not exist", err=True)
        raise typer.Exit(2)

    env = build_env(loaded, role)
    env["JARVISCORE_NODE_NAME"] = f"{project.service}-{role}-{replica}"
    # Explicit process env (from dev, compose, CI) wins over the project files.
    env.update(os.environ)

    os.chdir(loaded.root)
    argv = [sys.executable, "-m", RUNNER_MODULE, str(loaded.root), str(agent_file)]
    os.execve(sys.executable, argv, env)


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


async def run_agent(agent) -> None:
    from jarviscore import Mesh

    mesh = Mesh()
    mesh.add(agent)

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)

    await mesh.start()
    loops = asyncio.create_task(mesh.run_forever())
    stopper = asyncio.create_task(stop.wait())
    orphan_watch = asyncio.create_task(_stop_when_orphaned(stop))
    try:
        done, _ = await asyncio.wait({loops, stopper}, return_when=asyncio.FIRST_COMPLETED)
        if loops in done and loops.exception() is None and not stop.is_set():
            # No run() loop (workflow-driven agent): stay up until signalled.
            await stopper
    finally:
        orphaned = orphan_watch.done() and not orphan_watch.cancelled() and orphan_watch.result()
        for task in (loops, stopper, orphan_watch):
            task.cancel()
        await asyncio.gather(loops, stopper, orphan_watch, return_exceptions=True)
        if orphaned:
            # Nobody is left to kill us if shutdown hangs on peers that are also going away.
            try:
                await asyncio.wait_for(mesh.stop(), ORPHAN_STOP_TIMEOUT)
            except asyncio.TimeoutError:
                os._exit(0)
        else:
            await mesh.stop()
    if loops.done() and not loops.cancelled() and loops.exception():
        raise loops.exception()


async def _stop_when_orphaned(stop: asyncio.Event, interval: float = 1.0) -> bool:
    """Under `jarviscore dev`, shut down if dev dies without stopping us (e.g. kill -9)."""
    expected = os.environ.get("JARVISCORE_DEV_PARENT_PID")
    if not expected or not expected.isdigit():
        return False
    while not stop.is_set():
        if os.getppid() != int(expected):
            print("jarviscore dev is gone; stopping agent", file=sys.stderr, flush=True)
            stop.set()
            return True
        await asyncio.sleep(interval)
    return False


def _runner_main(argv: list) -> int:
    root, agent_file = Path(argv[0]), Path(argv[1])
    try:
        agent = resolve_agent(load_agent_module(root, agent_file))
    except AgentResolutionError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    asyncio.run(run_agent(agent))
    return 0


if __name__ == "__main__":
    sys.exit(_runner_main(sys.argv[1:]))
