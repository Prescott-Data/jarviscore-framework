"""`jarviscore dev`: run every agent in jarviscore.yaml locally with live reload.

Each agent replica is a `jarviscore serve` process on its own free ports; the first one
is the SWIM seed the others join. Redis is reused if one is already configured or
running, otherwise started in Docker (or with a local redis-server) for the session.
"""

import os
import random
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated

import typer

from jarviscore.project import LoadedProject, ProjectError, load_project
from jarviscore.project.checks.production import available_values
from jarviscore.project.schema import SECRET_REF_PREFIX

ZMQ_PORT_OFFSET = 1000
DEFAULT_REDIS = "redis://localhost:6379/0"
REDIS_IMAGE = "redis:7-alpine"
STOP_TIMEOUT = 15.0
COLORS = ("36", "35", "33", "32", "34", "31")


class DevError(Exception):
    pass


# ── Redis ────────────────────────────────────────────────────────────────

@dataclass
class RedisHandle:
    url: str
    source: str
    cleanup: Callable[[], None] = lambda: None


def redis_reachable(url: str, timeout: float = 0.5) -> bool:
    try:
        import redis
    except ImportError as exc:
        raise DevError(
            'jarviscore dev needs Redis support: pip install "jarviscore-framework[redis]"') from exc
    try:
        return bool(redis.Redis.from_url(url, socket_timeout=timeout, socket_connect_timeout=timeout).ping())
    except Exception:  # noqa: BLE001 - any failure means "not usable"
        return False


def resolve_redis(
    loaded: LoadedProject,
    environ: dict[str, str],
    explicit: str | None = None,
    *,
    reachable: Callable[[str], bool] = redis_reachable,
    which: Callable[[str], str | None] = shutil.which,
) -> RedisHandle:
    values = available_values(loaded.root, environ)
    accessory = loaded.project.accessories["redis"]

    candidates: list[tuple[str, str]] = []
    if explicit:
        candidates.append((explicit, "--redis"))
    elif accessory.external:
        url = accessory.url or ""
        if url.startswith(SECRET_REF_PREFIX):
            name = url[len(SECRET_REF_PREFIX):]
            if name not in values:
                raise DevError(
                    f"accessories.redis.url needs {name}; set it in .env or your shell")
            url = values[name]
        candidates.append((url, "accessories.redis.url"))
    elif values.get("REDIS_URL"):
        candidates.append((values["REDIS_URL"], "REDIS_URL"))

    for url, source in candidates:
        if not reachable(url):
            raise DevError(f"Redis from {source} is not reachable")
        return RedisHandle(url, source)

    if reachable(DEFAULT_REDIS):
        return RedisHandle(DEFAULT_REDIS, "already running on localhost:6379")
    if which("docker"):
        return _docker_redis(loaded, reachable)
    if which("redis-server"):
        return _local_redis_server(loaded, reachable)
    raise DevError(
        "No Redis available. Start one of:\n"
        "  docker run -d -p 6379:6379 redis:7-alpine\n"
        "  brew install redis && brew services start redis\n"
        "or point at an existing one with REDIS_URL in .env"
    )


def _docker_redis(loaded: LoadedProject, reachable) -> RedisHandle:
    name = f"jarviscore-dev-{loaded.project.service}-redis"

    def docker(*args: str, check: bool = True) -> subprocess.CompletedProcess:
        return subprocess.run(["docker", *args], capture_output=True, text=True, check=check)

    state = docker("inspect", "-f", "{{.State.Running}}", name, check=False)
    try:
        if state.returncode != 0:
            docker("run", "-d", "--name", name, "--label", "jarviscore.dev=1",
                   "-p", "127.0.0.1::6379", "-v", f"{name}-data:/data",
                   REDIS_IMAGE, "redis-server", "--appendonly", "yes")
        elif state.stdout.strip() != "true":
            docker("start", name)
        port = docker(
            "port", name, "6379/tcp").stdout.strip().splitlines()[0].rsplit(":", 1)[1]
    except (subprocess.CalledProcessError, IndexError) as exc:
        detail = getattr(exc, "stderr", "") or str(exc)
        raise DevError(
            f"Could not start Redis in Docker ({detail.strip()}). Is Docker running?") from None

    url = f"redis://127.0.0.1:{port}/0"
    _wait_for(lambda: reachable(url), 20,
              f"Redis container {name} did not become ready")
    return RedisHandle(url, f"docker container {name}", lambda: docker("stop", name, check=False))


def _local_redis_server(loaded: LoadedProject, reachable) -> RedisHandle:
    data = loaded.root / ".jarviscore" / "dev" / "redis"
    data.mkdir(parents=True, exist_ok=True)
    port = _free_port()
    proc = subprocess.Popen(
        ["redis-server", "--port", str(port), "--bind", "127.0.0.1", "--dir", str(data),
         "--appendonly", "yes"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
    )
    url = f"redis://127.0.0.1:{port}/0"
    _wait_for(lambda: reachable(url), 10, "redis-server did not start")

    def stop() -> None:
        proc.terminate()
        try:
            proc.wait(5)
        except subprocess.TimeoutExpired:
            proc.kill()

    return RedisHandle(url, f"redis-server (data in {data.relative_to(loaded.root)})", stop)


# ── Peers ────────────────────────────────────────────────────────────────

def _port_free(port: int) -> bool:
    for kind in (socket.SOCK_STREAM, socket.SOCK_DGRAM):
        with socket.socket(socket.AF_INET, kind) as s:
            try:
                s.bind(("127.0.0.1", port))
            except OSError:
                return False
    return True


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def allocate_peer_port(taken: set[int]) -> int:
    """A port free for SWIM (UDP+TCP) whose ZMQ partner (port + offset) is free too."""
    for _ in range(500):
        port = random.randint(20000, 40000)
        pair = {port, port + ZMQ_PORT_OFFSET}
        if pair & taken:
            continue
        if _port_free(port) and _port_free(port + ZMQ_PORT_OFFSET):
            taken |= pair
            return port
    raise DevError("Could not find free ports for the agents")


@dataclass
class Peer:
    role: str
    replica: int
    port: int
    env: dict[str, str]
    color: str
    proc: subprocess.Popen | None = None
    stopping: bool = False

    @property
    def label(self) -> str:
        return f"{self.role}-{self.replica}"


def plan_peers(loaded: LoadedProject, roles: list[str], redis_url: str,
               allocate: Callable[[set[int]], int] = allocate_peer_port) -> list[Peer]:
    taken: set[int] = set()
    peers: list[Peer] = []
    seed: str | None = None
    for i, role in enumerate(roles):
        for replica in range(1, loaded.project.agents[role].replicas + 1):
            port = allocate(taken)
            env = {
                "REDIS_URL": redis_url,
                "P2P_ENABLED": "true",
                "JARVISCORE_BIND_HOST": "127.0.0.1",
                "JARVISCORE_BIND_PORT": str(port),
                "PYTHONUNBUFFERED": "1",
            }
            if seed:
                env["JARVISCORE_SEED_NODES"] = seed
            else:
                seed = f"127.0.0.1:{port}"
            peers.append(Peer(role, replica, port,
                         env, COLORS[i % len(COLORS)]))
    return peers


@dataclass
class DevSession:
    loaded: LoadedProject
    roles: list[str]
    redis: RedisHandle
    color: bool = True
    peers: list[Peer] = field(default_factory=list)
    _print_lock: threading.Lock = field(default_factory=threading.Lock)

    def say(self, text: str) -> None:
        with self._print_lock:
            print(text, flush=True)

    def start_all(self) -> None:
        self.peers = plan_peers(self.loaded, self.roles, self.redis.url)
        for index, peer in enumerate(self.peers):
            self._start(peer)
            if index == 0 and len(self.peers) > 1:
                # Let the seed bind before others try to join it.
                _wait_for(lambda p=peer: _listening(p.port + ZMQ_PORT_OFFSET) or p.proc.poll() is not None,
                          20, None)

    def _start(self, peer: Peer) -> None:
        cmd = [sys.executable, "-m", "jarviscore.cli", "serve", "--role", peer.role,
               "--replica", str(peer.replica)]
        if self.loaded.destination:
            cmd += ["-d", self.loaded.destination]
        peer.stopping = False
        peer.proc = subprocess.Popen(
            cmd, cwd=self.loaded.root, env={**os.environ, **peer.env},
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1,
            start_new_session=True,
        )
        threading.Thread(target=self._pump, args=(
            peer, peer.proc), daemon=True).start()

    def _pump(self, peer: Peer, proc: subprocess.Popen) -> None:
        prefix = f"\033[{peer.color}m{peer.label:>14} |\033[0m" if self.color else f"{peer.label:>14} |"
        for line in proc.stdout:
            self.say(f"{prefix} {line.rstrip()}")
        code = proc.wait()
        if not peer.stopping and proc is peer.proc:
            self.say(
                f"{prefix} exited with code {code} (save a file to restart it)")

    def stop(self, peers: list[Peer] | None = None) -> None:
        targets = [p for p in (
            peers if peers is not None else self.peers) if p.proc and p.proc.poll() is None]
        seed = self.peers[0] if self.peers else None
        # Peers hang in shutdown if the seed disappears under them, so the seed goes last.
        self._terminate([p for p in targets if p is not seed])
        self._terminate([p for p in targets if p is seed])

    def _terminate(self, targets: list[Peer]) -> None:
        for peer in targets:
            peer.stopping = True
            peer.proc.send_signal(signal.SIGTERM)
        deadline = time.time() + STOP_TIMEOUT
        for peer in targets:
            try:
                peer.proc.wait(max(0.1, deadline - time.time()))
            except subprocess.TimeoutExpired:
                self.say(
                    f"⚠ {peer.label} did not stop within {STOP_TIMEOUT:.0f}s, killing it")
                peer.proc.kill()
                peer.proc.wait()

    def restart(self, roles: set[str]) -> None:
        targets = [p for p in self.peers if p.role in roles]
        self.say(f"↻ restarting {', '.join(sorted(roles))}")
        self.stop(targets)
        for peer in targets:
            self._start(peer)

    def reload_project(self) -> None:
        try:
            loaded = load_project(self.loaded.root, self.loaded.destination)
        except ProjectError as exc:
            self.say(
                f"✗ jarviscore.yaml is invalid, keeping the running agents:\n{exc}")
            return
        self.say("↻ jarviscore.yaml changed, restarting all agents")
        self.stop()
        self.loaded = loaded
        self.roles = [r for r in self.roles if r in loaded.project.agents] or list(
            loaded.project.agents)
        self.start_all()


def roles_to_restart(changed: set[str], loaded: LoadedProject, roles: list[str]) -> set[str] | None:
    """None means jarviscore.yaml changed; otherwise the roles affected by the edits."""
    root = loaded.root.resolve()
    files = {Path(p).resolve() for p in changed}
    project_files = {f.resolve() for f in loaded.files}
    if files & project_files:
        return None
    by_path = {
        (root / loaded.project.agents[r].path).resolve(): r for r in roles}
    affected: set[str] = set()
    for path in files:
        if path in by_path:
            affected.add(by_path[path])
        elif path.suffix == ".py":
            # A shared module could be imported by any agent.
            return set(roles)
    return affected


def _watch_filter(change, path: str) -> bool:
    parts = Path(path).parts
    if ".jarviscore" in parts or "tests" in parts:
        return False
    return path.endswith((".py", ".yaml"))


def _listening(port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(0.2)
        return s.connect_ex(("127.0.0.1", port)) == 0


def _wait_for(predicate: Callable[[], bool], timeout: float, error: str | None) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return
        time.sleep(0.2)
    if error:
        raise DevError(error)


# ── Command ──────────────────────────────────────────────────────────────

def dev_command(
    roles: Annotated[
        list[str] | None, typer.Argument(
            help="Agents to run (default: all in jarviscore.yaml)")
    ] = None,
    destination: str = typer.Option(
        None, "--destination", "-d", help="Environment overlay to use"),
    redis_url: str = typer.Option(
        None, "--redis", help="Use this Redis instead of finding or starting one"),
    reload: bool = typer.Option(
        True, "--reload/--no-reload", help="Restart agents when their files change"),
) -> None:
    """Run all agents locally with Redis and live reload."""
    try:
        loaded = load_project(destination=destination)
        selected = _select_roles(loaded, roles or [])
        redis = resolve_redis(loaded, dict(os.environ), redis_url)
    except (ProjectError, DevError) as exc:
        typer.echo(f"✗ {exc}", err=True)
        raise typer.Exit(2) from None

    session = DevSession(loaded, selected, redis, color=sys.stdout.isatty())
    stop_event = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop_event.set())

    try:
        session.start_all()
        write_session_file(loaded, redis.url)
        _banner(session, reload)
        if reload:
            import watchfiles

            for changes in watchfiles.watch(loaded.root, watch_filter=_watch_filter,
                                            stop_event=stop_event, raise_interrupt=False):
                affected = roles_to_restart(
                    {p for _, p in changes}, session.loaded, session.roles)
                if affected is None:
                    session.reload_project()
                elif affected:
                    session.restart(affected)
        else:
            stop_event.wait()
    except DevError as exc:
        session.say(f"✗ {exc}")
    finally:
        session.say("Stopping agents…")
        session_file(loaded).unlink(missing_ok=True)
        session.stop()
        redis.cleanup()
        session.say("Stopped.")


def session_file(loaded: LoadedProject) -> Path:
    return loaded.root / ".jarviscore" / "dev" / "session.json"


def write_session_file(loaded: LoadedProject, redis_url: str) -> None:
    import json

    path = session_file(loaded)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"pid": os.getpid(), "redis_url": redis_url,
                                "environment": loaded.environment}))
    path.chmod(0o600)


def _select_roles(loaded: LoadedProject, requested: list[str]) -> list[str]:
    agents = loaded.project.agents
    unknown = [r for r in requested if r not in agents]
    if unknown:
        raise DevError(
            f"Unknown agent(s) {', '.join(unknown)}. Defined: {', '.join(agents)}")
    selected = requested or list(agents)
    missing = [f"{r}: {agents[r].path}" for r in selected if not (
        loaded.root / agents[r].path).is_file()]
    if missing:
        raise DevError("Agent file(s) not found: " + "; ".join(missing))
    return selected


def _banner(session: DevSession, reload: bool) -> None:
    project = session.loaded.project
    lines = [f"\njarviscore dev: {project.service} ({session.loaded.environment})",
             f"  redis   {session.redis.source}"]
    for peer in session.peers:
        lines.append(f"  {peer.label:<14} port {peer.port}")
    lines.append(
        f"  reload  {'on: edit a file to restart its agent' if reload else 'off'}")
    lines.append("  Ctrl-C to stop\n")
    session.say("\n".join(lines))
