"""`jarviscore dev`: run every agent in jarviscore.yaml locally with live reload.

Each agent replica runs the `jarviscore serve` runner (same environment, started
directly) on its own free ports; the first one is the SWIM seed the others join.
Redis is reused if one is already configured or running, otherwise started in Docker
(or with a local redis-server) for the session.
"""

from __future__ import annotations

import hashlib
import json
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
from typing import TYPE_CHECKING, Annotated

import typer

from jarviscore.project._names import SECRET_REF_PREFIX

from ._python import InterpreterError, ensure_jarviscore, install_hint, project_python
from .serve import PARENT_PID_ENV, POLL_INTERVAL_ENV, agent_env, runner_argv

if TYPE_CHECKING:
    from jarviscore.project import LoadedProject

ZMQ_PORT_OFFSET = 1000
DEFAULT_REDIS = "redis://localhost:6379/0"
REDIS_IMAGE = "redis:7-alpine"
STOP_TIMEOUT = 15.0
SEED_BIND_TIMEOUT = 20.0
DOCKER_TIMEOUT = 15
# `docker run` may pull the image on first use.
DOCKER_PULL_TIMEOUT = 300
DOCKER_STOP_GRACE = 5
COLORS = ("36", "35", "33", "32", "34", "31")
# Agents under dev pick up tasks quickly; deployed agents keep the 2s default.
DEV_POLL_INTERVAL = "0.25"
NO_REDIS_HINT = (
    "Start Redis with one of:\n"
    "  docker run -d -p 6379:6379 redis:7-alpine\n"
    "  redis-server   (install: brew install redis, or apt install redis-server)\n"
    "or point at an existing one with REDIS_URL in .env (or --redis URL)"
)


class DevError(Exception):
    pass


# ── Redis ────────────────────────────────────────────────────────────────

@dataclass
class RedisHandle:
    url: str
    source: str
    cleanup: Callable[[], None] = lambda: None
    # Immediate, best-effort stop for a second Ctrl-C (no waiting).
    kill: Callable[[], None] = lambda: None


def _note(text: str) -> None:
    print(text, file=sys.stderr, flush=True)


def _redact(url: str) -> str:
    from jarviscore.project.checks.redis import redact

    return redact(url)


def redis_reachable(url: str, timeout: float = 0.5) -> bool:
    try:
        import redis
    except ImportError as exc:
        raise DevError(
            f"jarviscore dev needs the redis package. Install it with: {install_hint('redis')}"
        ) from exc
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
    from jarviscore.project.checks.production import available_values

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
            raise DevError(
                f"Redis from {source} is not reachable at {_redact(url)}. Start that Redis or "
                f"fix the URL; without {source}, jarviscore dev starts a local Redis for you.")
        return RedisHandle(url, source)

    if reachable(DEFAULT_REDIS):
        return RedisHandle(DEFAULT_REDIS, "already running on localhost:6379")
    failures: list[str] = []
    if which("docker"):
        try:
            return _docker_redis(loaded, reachable)
        except DevError as exc:
            failures.append(str(exc))
    if which("redis-server"):
        if failures:
            _note("Trying a local redis-server instead…")
        try:
            return _local_redis_server(loaded, reachable)
        except DevError as exc:
            failures.append(str(exc))
    raise DevError("\n".join([*failures, "No Redis available. " + NO_REDIS_HINT]))


def docker_redis_name(loaded: LoadedProject) -> str:
    # Path hash keeps two checkouts with the same service name apart.
    digest = hashlib.sha1(str(loaded.root.resolve()).encode()).hexdigest()[:6]
    return f"jarviscore-dev-{loaded.project.service}-{digest}-redis"


def _docker_redis(loaded: LoadedProject, reachable) -> RedisHandle:
    name = docker_redis_name(loaded)

    def docker(*args: str, check: bool = True, timeout: float | None = None) -> subprocess.CompletedProcess:
        return subprocess.run(["docker", *args], capture_output=True, text=True, check=check,
                              timeout=timeout)

    try:
        state = docker("inspect", "-f", "{{.State.Running}}", name, check=False,
                       timeout=DOCKER_TIMEOUT)
        if state.returncode != 0:
            _note(f"Starting Redis in Docker (first run pulls {REDIS_IMAGE})…")
            docker("run", "-d", "--name", name, "--label", "jarviscore.dev=1",
                   "-p", "127.0.0.1::6379", "-v", f"{name}-data:/data",
                   REDIS_IMAGE, "redis-server", "--appendonly", "yes",
                   timeout=DOCKER_PULL_TIMEOUT)
        elif state.stdout.strip() != "true":
            _note(f"Starting Redis container {name}…")
            docker("start", name, timeout=DOCKER_TIMEOUT)
        port = docker(
            "port", name, "6379/tcp", timeout=DOCKER_TIMEOUT).stdout.strip().splitlines()[0].rsplit(":", 1)[1]
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, IndexError) as exc:
        detail = getattr(exc, "stderr", "") or str(exc)
        raise DevError(
            f"Could not start Redis in Docker ({detail.strip()}). Is Docker running?") from None

    url = f"redis://127.0.0.1:{port}/0"
    _wait_for(lambda: reachable(url), 20,
              f"Redis container {name} did not become ready")

    def stop() -> None:
        try:
            docker("stop", "-t", str(DOCKER_STOP_GRACE), name, check=False,
                   timeout=DOCKER_STOP_GRACE + DOCKER_TIMEOUT)
        except (subprocess.SubprocessError, OSError):
            _note(f"⚠ could not stop {name}; stop it with: docker stop {name}")

    return RedisHandle(url, f"docker container {name}", stop)


def _local_redis_server(loaded: LoadedProject, reachable) -> RedisHandle:
    data = loaded.root / ".jarviscore" / "dev" / "redis"
    data.mkdir(parents=True, exist_ok=True)
    port = _free_port()
    try:
        proc = subprocess.Popen(
            ["redis-server", "--port", str(port), "--bind", "127.0.0.1", "--dir", str(data),
             "--appendonly", "yes"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
        )
    except OSError as exc:
        raise DevError(f"Could not run redis-server ({exc})") from None
    url = f"redis://127.0.0.1:{port}/0"
    try:
        _wait_for(lambda: reachable(url), 10, "redis-server did not start")
    except DevError:
        proc.kill()
        raise

    def stop() -> None:
        proc.terminate()
        try:
            proc.wait(5)
        except subprocess.TimeoutExpired:
            proc.kill()

    return RedisHandle(url, f"redis-server (data in {data.relative_to(loaded.root)})", stop,
                       proc.kill)


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
               allocate: Callable[[set[int]], int] = allocate_peer_port,
               taken: set[int] | None = None) -> list[Peer]:
    taken = set() if taken is None else taken
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
                PARENT_PID_ENV: str(os.getpid()),
            }
            if POLL_INTERVAL_ENV not in os.environ:
                env[POLL_INTERVAL_ENV] = DEV_POLL_INTERVAL
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
    python: str = field(default_factory=lambda: sys.executable)
    peers: list[Peer] = field(default_factory=list)
    # Every port handed out this session; a stopped peer's port may not be released yet.
    used_ports: set[int] = field(default_factory=set)
    # Set on Ctrl-C/SIGTERM so a slow start-up stops early.
    stopping: threading.Event = field(default_factory=threading.Event)
    _print_lock: threading.Lock = field(default_factory=threading.Lock)

    def say(self, text: str) -> None:
        # Flush every line: piped output (CI, `| tee`) should stream, not arrive in blocks.
        with self._print_lock:
            print(text, flush=True)

    def warn(self, text: str) -> None:
        with self._print_lock:
            print(text, file=sys.stderr, flush=True)

    def start_all(self) -> None:
        self.peers = plan_peers(self.loaded, self.roles, self.redis.url, taken=self.used_ports)
        for index, peer in enumerate(self.peers):
            if self.stopping.is_set():
                break
            self._start(peer)
            if index == 0 and len(self.peers) > 1:
                self._wait_until_bound(peer)

    def _wait_until_bound(self, peer: Peer) -> None:
        # Let the seed bind before others try to join it.
        port = peer.port + ZMQ_PORT_OFFSET
        _wait_for(lambda: (_listening(port) or peer.proc.poll() is not None
                           or self.stopping.is_set()),
                  SEED_BIND_TIMEOUT, None)
        if peer.proc.poll() is None and not self.stopping.is_set() and not _listening(port):
            self.warn(
                f"! {peer.label} did not open its mesh port {port} within "
                f"{SEED_BIND_TIMEOUT:.0f}s; the other agents may not find it. If its log "
                "mentions swim or zmq, install the p2p extra into the project "
                "(\"jarviscore-framework[p2p,redis]\" in pyproject.toml).")

    def _start(self, peer: Peer) -> None:
        # The same environment `jarviscore serve` would build, without a second
        # interpreter start just to compute it; peer.env (ports, seed) wins.
        env = agent_env(self.loaded, peer.role, peer.replica, {**os.environ, **peer.env})
        agent_file = self.loaded.root / self.loaded.project.agents[peer.role].path
        peer.stopping = False
        try:
            peer.proc = subprocess.Popen(
                runner_argv(self.python, self.loaded.root, agent_file),
                cwd=self.loaded.root, env=env,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1,
                start_new_session=True,
            )
        except OSError as exc:
            raise DevError(f"Could not start {peer.label} with {self.python}: {exc}") from None
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
        seed = self._seed_peer()
        # Peers hang in shutdown if the seed disappears under them, so the seed goes last.
        self._terminate([p for p in targets if p is not seed])
        self._terminate([p for p in targets if p is seed])

    def _seed_peer(self) -> Peer | None:
        """The peer most others joined through."""
        joined = [p.env.get("JARVISCORE_SEED_NODES") for p in self.peers]
        by_address = {f"127.0.0.1:{p.port}": p for p in self.peers}
        counts = {a: joined.count(a) for a in by_address if a in joined}
        if counts:
            return by_address[max(counts, key=counts.get)]
        return self.peers[0] if self.peers else None

    def _terminate(self, targets: list[Peer]) -> None:
        for peer in targets:
            peer.stopping = True
            peer.proc.send_signal(signal.SIGTERM)
        deadline = time.time() + STOP_TIMEOUT
        for peer in targets:
            try:
                peer.proc.wait(max(0.1, deadline - time.time()))
            except subprocess.TimeoutExpired:
                self.warn(
                    f"⚠ {peer.label} did not stop within {STOP_TIMEOUT:.0f}s, killing it")
                peer.proc.kill()
                peer.proc.wait()

    def kill_all(self) -> None:
        """Second Ctrl-C: SIGKILL every agent (and anything it started) without waiting."""
        for peer in self.peers:
            peer.stopping = True
            if peer.proc and peer.proc.poll() is None:
                try:
                    # Each agent leads its own session (start_new_session), so pgid == pid.
                    os.killpg(peer.proc.pid, signal.SIGKILL)
                except OSError:
                    try:
                        peer.proc.kill()
                    except OSError:
                        pass

    def restart(self, roles: set[str]) -> None:
        targets = [p for p in self.peers if p.role in roles]
        self.say(f"↻ restarting {', '.join(sorted(roles))}")
        self.stop(targets)
        survivors = [p for p in self.peers if p not in targets and p.proc and p.proc.poll() is None]
        seed = f"127.0.0.1:{survivors[0].port}" if survivors else None
        for peer in targets:
            peer.port = allocate_peer_port(self.used_ports)
            peer.env["JARVISCORE_BIND_PORT"] = str(peer.port)
            if seed:
                peer.env["JARVISCORE_SEED_NODES"] = seed
            else:
                peer.env.pop("JARVISCORE_SEED_NODES", None)
                seed = f"127.0.0.1:{peer.port}"
            self._start(peer)
            if not survivors and peer is targets[0] and len(targets) > 1:
                self._wait_until_bound(peer)
            self.say(f"  {peer.label:<14} port {peer.port}")

    def reload_project(self) -> None:
        from jarviscore.project import ProjectError, load_project

        try:
            loaded = load_project(self.loaded.root, self.loaded.destination)
        except ProjectError as exc:
            self.warn(
                f"✗ jarviscore.yaml is invalid, keeping the running agents:\n{exc}")
            return
        self.say("↻ jarviscore.yaml changed, restarting all agents")
        self.stop()
        self.loaded = loaded
        self.roles = [r for r in self.roles if r in loaded.project.agents] or list(
            loaded.project.agents)
        self.start_all()
        for peer in self.peers:
            self.say(f"  {peer.label:<14} port {peer.port}")


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


def _make_watch_filter():
    import watchfiles

    class _DevFilter(watchfiles.DefaultFilter):
        def __call__(self, change, path: str) -> bool:
            return super().__call__(change, path) and _watch_filter(change, path)

    return _DevFilter()


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
    sync: bool = typer.Option(
        True, "--sync/--no-sync",
        help="Create .venv from pyproject.toml on first run (uv sync, else venv + pip). "
             "Also disabled by JARVISCORE_DEV_NO_SYNC=1"),
) -> None:
    """Run all agents locally with Redis and live reload."""
    raise typer.Exit(run_dev(roles or [], destination, redis_url, reload, sync=sync))


def use_color(stream=None, environ=None) -> bool:
    """ANSI colour only on a terminal, and never with NO_COLOR set or TERM=dumb."""
    stream = sys.stdout if stream is None else stream
    environ = os.environ if environ is None else environ
    if environ.get("NO_COLOR") or environ.get("TERM") == "dumb":
        return False
    return stream.isatty()


def _fail(exc: Exception) -> None:
    print(f"✗ {exc}", file=sys.stderr, flush=True)


def run_dev(roles: list[str], destination: str | None, redis_url: str | None,
            reload: bool, sync: bool = True) -> int:
    """Exit codes: 0 stopped normally, 1 runtime failure, 2 bad project/arguments,
    128+N stopped by signal N (130 for Ctrl-C)."""
    from jarviscore.project import ProjectError, load_project

    try:
        loaded = load_project(destination=destination)
        selected = _select_roles(loaded, roles)
        acquire_session(loaded)
    except (ProjectError, DevError) as exc:
        _fail(exc)
        return 2
    except KeyboardInterrupt:
        return 130

    try:
        _provision_env(loaded, sync)
        python = _agent_python(loaded)
        if reload:
            _require("watchfiles")
        redis = resolve_redis(loaded, dict(os.environ), redis_url)
    except DevError as exc:
        release_session(loaded)
        _fail(exc)
        return 1
    except KeyboardInterrupt as exc:
        release_session(loaded)
        print("\nInterrupted.", file=sys.stderr, flush=True)
        return 128 + getattr(exc, "signum", signal.SIGINT)

    session = DevSession(loaded, selected, redis, color=use_color(), python=python)
    stop_event = session.stopping
    received: list[int] = []

    def on_signal(signum, _frame) -> None:
        if received:
            # Second signal: do not wait for graceful shutdown.
            session.kill_all()
            redis.kill()
            release_session(loaded)
            os.write(2, b"\nKilled agents.\n")
            os._exit(128 + received[0])
        received.append(signum)
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, on_signal)

    failed = False
    try:
        session.start_all()
        if not stop_event.is_set():
            write_session_file(loaded, redis.url)
            _banner(session, reload)
        if reload and not stop_event.is_set():
            import watchfiles

            for changes in watchfiles.watch(loaded.root, watch_filter=_make_watch_filter(),
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
        failed = True
        session.warn(f"✗ {exc}")
    finally:
        session.say("Stopping agents… (Ctrl-C again to kill them now)")
        release_session(loaded)
        session.stop()
        redis.cleanup()
        session.say("Stopped.")
    if received:
        return 128 + received[0]
    return 1 if failed else 0


def _provision_env(loaded: LoadedProject, sync: bool) -> None:
    """First run: create the project's .venv so agents get its dependencies (p2p, redis)."""
    from ._provision import ProvisionError, provision, should_provision

    if not should_provision(loaded.root, sync=sync):
        return
    try:
        provision(loaded.root)
    except ProvisionError as exc:
        raise DevError(str(exc)) from None


def _agent_python(loaded: LoadedProject) -> str:
    python, note = project_python(loaded.root)
    if note:
        _note(note)
    try:
        ensure_jarviscore(python, loaded.root)
    except InterpreterError as exc:
        raise DevError(str(exc)) from None
    return python


def _require(module: str) -> None:
    import importlib.util

    if importlib.util.find_spec(module) is None:
        raise DevError(f"jarviscore dev needs the {module} package. Install it with: "
                       f"{install_hint(module)}")


def session_file(loaded: LoadedProject) -> Path:
    return loaded.root / ".jarviscore" / "dev" / "session.json"


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def acquire_session(loaded: LoadedProject) -> None:
    """Claim the project for this process; one `jarviscore dev` per project at a time."""
    path = session_file(loaded)
    path.parent.mkdir(parents=True, exist_ok=True)
    for _ in range(2):
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            try:
                owner = int(json.loads(path.read_text()).get("pid", 0))
            except (OSError, ValueError, TypeError, AttributeError):
                owner = 0
            if owner and owner != os.getpid() and _pid_alive(owner):
                raise DevError(
                    f"jarviscore dev is already running for this project (pid {owner}). "
                    "Stop it first, or send tasks to it with `jarviscore run`."
                ) from None
            path.unlink(missing_ok=True)
            continue
        with os.fdopen(fd, "w") as f:
            json.dump({"pid": os.getpid(), "redis_url": None,
                       "environment": loaded.environment}, f)
        return
    raise DevError(f"Could not claim {path}; another jarviscore dev may be starting")


def release_session(loaded: LoadedProject) -> None:
    path = session_file(loaded)
    try:
        owner = json.loads(path.read_text()).get("pid")
    except (OSError, ValueError, AttributeError):
        return
    if owner == os.getpid():
        path.unlink(missing_ok=True)


def write_session_file(loaded: LoadedProject, redis_url: str) -> None:
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
             f"  python  {session.python}",
             f"  redis   {session.redis.source}"]
    for peer in session.peers:
        lines.append(f"  {peer.label:<14} port {peer.port}")
    lines.append(
        f"  reload  {'on: edit a file to restart its agent' if reload else 'off'}")
    lines.append("  Ctrl-C to stop\n")
    session.say("\n".join(lines))


if __name__ == "__main__":
    from jarviscore.cli.app import main

    main(["dev", *sys.argv[1:]])
