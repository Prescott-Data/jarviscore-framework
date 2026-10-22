"""`jarviscore run AGENT "task"`: send one task to a running mesh and print the result.

The task is submitted as a one-step workflow through Redis; the running agent's
distributed worker claims and executes it. Use it against `jarviscore dev` or any
deployment whose Redis you can reach.
"""

from __future__ import annotations

import json
import os
import sys
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar

import typer

from jarviscore.project._names import SECRET_REF_PREFIX

if TYPE_CHECKING:
    from jarviscore.project import LoadedProject

# The CLI waits on one step: poll fast at first, then back off (the default is 2s flat).
RESULT_POLL = {"remote_step_poll_interval": 0.1, "remote_step_poll_max_interval": 1.0}


class RunError(Exception):
    pass


def resolve_run_redis(loaded: LoadedProject, environ: dict[str, str], explicit: str | None) -> tuple[str, str]:
    from jarviscore.project.checks.production import available_values

    from .dev import session_file

    if explicit:
        return explicit, "--redis"
    session = _live_session(session_file(loaded))
    if session:
        return session["redis_url"], "jarviscore dev session"
    values = available_values(loaded.root, environ)
    accessory = loaded.project.accessories["redis"]
    if accessory.external:
        url = accessory.url or ""
        if url.startswith(SECRET_REF_PREFIX):
            url = values.get(url[len(SECRET_REF_PREFIX):], "")
        if url:
            return url, "accessories.redis.url"
    if values.get("REDIS_URL"):
        return values["REDIS_URL"], "REDIS_URL"
    raise RunError("No running mesh found. Start your agents with `jarviscore dev` in another terminal, "
                   "or pass --redis URL.")


def _live_session(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text())
        os.kill(int(data["pid"]), 0)
    except (OSError, ValueError, KeyError, TypeError):
        return None
    # dev claims the file before Redis is up; no URL means it is still starting.
    return data if data.get("redis_url") else None


def agent_role(loaded: LoadedProject, name: str) -> str:
    """The role the agent registers in the mesh, which can differ from its yaml name."""
    from .serve import AgentResolutionError, load_agent_module, resolve_agent

    agents = loaded.project.agents
    if name not in agents:
        raise RunError(
            f"Unknown agent {name!r}. Defined agents: {', '.join(agents)}")
    path = loaded.root / agents[name].path
    if not path.is_file():
        raise RunError(
            f"agents.{name}.path: {agents[name].path} does not exist")
    try:
        agent = resolve_agent(load_agent_module(loaded.root, path))
    except AgentResolutionError as exc:
        raise RunError(str(exc)) from None
    return agent.role


async def submit(redis_url: str, role: str, task: str, timeout: float) -> dict:
    from jarviscore import Mesh
    from jarviscore.profiles import CustomAgent

    class CliClient(CustomAgent):
        # A mesh needs one agent; this role matches no step, so it never claims work.
        role = "jarviscore_cli_client"
        capabilities: ClassVar[list[str]] = ["jarviscore_cli_client"]

        async def on_peer_request(self, msg):
            return None

    mesh = Mesh(config={"redis_url": _with_timeouts(redis_url), "p2p_enabled": False,
                        **RESULT_POLL})
    mesh.add(CliClient, agent_id=f"jarviscore-cli-{uuid.uuid4().hex[:8]}")
    await mesh.start()
    try:
        if "redis" not in mesh.capabilities:
            raise RunError(
                f"Could not connect to Redis at {_redact(redis_url)}")
        workflow_id = f"run-{role}-{uuid.uuid4().hex[:8]}"
        results = await mesh.workflow(workflow_id, [{"agent": role, "task": task}], timeout_per_step=timeout)
        result = {"workflow_id": workflow_id, **results[0]}
        if result.get("status") != "success":
            # The engine only reports "remote failure"; the peer stored the real error.
            saved = mesh._redis_store.get_step_output(
                workflow_id, result.get("step_id", "step0")) or {}
            stored = saved.get("output", saved)
            if isinstance(stored, dict) and stored.get("error"):
                result["error"] = stored["error"]
        return result
    finally:
        await mesh.stop()


def _with_timeouts(url: str, seconds: float = 3) -> str:
    """Add redis-py socket timeouts to the URL unless it already sets them."""
    from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query.setdefault("socket_connect_timeout", str(seconds))
    query.setdefault("socket_timeout", str(seconds))
    return urlunsplit(parts._replace(query=urlencode(query)))


def _redact(url: str) -> str:
    from jarviscore.project.checks.redis import redact

    return redact(url)


def run_command(
    agent: str = typer.Argument(..., help="Agent name from jarviscore.yaml"),
    task: str = typer.Argument(..., help="The task to send"),
    timeout: float = typer.Option(
        300, "--timeout", min=1, help="Seconds to wait for the result"),
    destination: str = typer.Option(
        None, "--destination", "-d", help="Environment overlay"),
    redis_url: str = typer.Option(
        None, "--redis", help="Redis of the mesh to send the task to"),
    as_json: bool = typer.Option(
        False, "--json", help="Print the full result as JSON"),
) -> None:
    """Send one task to a running agent and print the result."""
    import asyncio

    from jarviscore.project import ProjectError, load_project

    try:
        loaded = load_project(destination=destination)
        role = agent_role(loaded, agent)
        url, source = resolve_run_redis(loaded, dict(os.environ), redis_url)
    except (ProjectError, RunError) as exc:
        typer.echo(f"✗ {exc}", err=True)
        raise typer.Exit(2) from None

    if not as_json:
        typer.echo(
            f"→ {agent} (role {role}) via {source}, waiting up to {timeout:.0f}s…", err=True)
    try:
        result = asyncio.run(submit(url, role, task, timeout))
    except RunError as exc:
        typer.echo(f"✗ {exc}", err=True)
        raise typer.Exit(2) from None

    ok = result.get("status") == "success"
    if as_json:
        typer.echo(json.dumps(result, indent=2, default=str))
    elif ok:
        output = result.get("output")
        typer.echo(output if isinstance(output, str)
                   else json.dumps(output, indent=2, default=str))
    else:
        typer.echo(
            f"✗ {result.get('error') or result.get('status')}", err=True)
    raise typer.Exit(0 if ok else 1)


if __name__ == "__main__":
    from jarviscore.cli.app import main

    main(["run", *sys.argv[1:]])
