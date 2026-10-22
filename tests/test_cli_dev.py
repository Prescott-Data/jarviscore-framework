import json
import os
import signal
import socket
import subprocess
import sys
import textwrap
import threading
import time

import pytest

from jarviscore.cli import dev
from jarviscore.cli.dev import (
    DevError,
    _select_roles,
    allocate_peer_port,
    plan_peers,
    resolve_redis,
    roles_to_restart,
)
from jarviscore.project import load_project

YAML = """
service: demo
agents:
  triage:    { path: agents/triage.py }
  responder: { path: agents/responder.py, replicas: 2 }
"""

AGENT = '''
import os
from pathlib import Path
from jarviscore.profiles import CustomAgent

LOG = Path(os.environ["MARKER_DIR"]) / "{role}.log"


class {cls}(CustomAgent):
    role = "{role}"
    capabilities = ["{role}"]

    async def setup(self):
        await super().setup()
        with LOG.open("a") as f:
            f.write("up " + os.environ["JARVISCORE_NODE_NAME"] + " seed=" + os.environ.get("JARVISCORE_SEED_NODES", "") + "\\n")

    async def teardown(self):
        with LOG.open("a") as f:
            f.write("down " + os.environ["JARVISCORE_NODE_NAME"] + "\\n")
        await super().teardown()

    async def on_peer_request(self, msg):
        return {{}}
'''


@pytest.fixture
def project(tmp_path):
    (tmp_path / "agents").mkdir()
    (tmp_path / "jarviscore.yaml").write_text(textwrap.dedent(YAML))
    (tmp_path / "agents" / "triage.py").write_text(AGENT.format(role="triage", cls="Triage"))
    (tmp_path / "agents" / "responder.py").write_text(AGENT.format(role="responder", cls="Responder"))
    (tmp_path / "agents" / "shared.py").write_text("X = 1\n")
    return tmp_path


# ── Redis resolution ──────────────────────────────────────────────────────

def no_tools(_):
    return None


def test_explicit_redis_wins(project):
    handle = resolve_redis(load_project(project), {"REDIS_URL": "redis://other"}, "redis://mine",
                           reachable=lambda u: True, which=no_tools)
    assert (handle.url, handle.source) == ("redis://mine", "--redis")


def test_explicit_unreachable_is_an_error(project):
    with pytest.raises(DevError, match="--redis is not reachable"):
        resolve_redis(load_project(project), {}, "redis://dead", reachable=lambda u: False, which=no_tools)


def test_redis_url_from_dotenv(project):
    (project / ".env").write_text("REDIS_URL=redis://from-dotenv:6379\n")
    handle = resolve_redis(load_project(project), {}, reachable=lambda u: True, which=no_tools)
    assert handle.url == "redis://from-dotenv:6379" and handle.source == "REDIS_URL"


def test_external_accessory_secret(project):
    (project / "jarviscore.yaml").write_text(YAML + 'accessories:\n  redis: { url: "secret:SHARED_REDIS" }\n')
    with pytest.raises(DevError, match="needs SHARED_REDIS"):
        resolve_redis(load_project(project), {}, reachable=lambda u: True, which=no_tools)
    handle = resolve_redis(load_project(project), {"SHARED_REDIS": "rediss://x:6380"},
                           reachable=lambda u: True, which=no_tools)
    assert handle.url == "rediss://x:6380"


def test_reuses_local_redis(project):
    handle = resolve_redis(load_project(project), {}, reachable=lambda u: u == dev.DEFAULT_REDIS,
                           which=no_tools)
    assert handle.url == dev.DEFAULT_REDIS and "already running" in handle.source


def test_starts_redis_in_docker_and_stops_it(project, monkeypatch):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd[1:])
        out = {"inspect": "", "port": "127.0.0.1:55123\n"}.get(cmd[1], "")
        return subprocess.CompletedProcess(cmd, 1 if cmd[1] == "inspect" else 0, out, "No such object")

    monkeypatch.setattr(dev.subprocess, "run", fake_run)
    handle = resolve_redis(load_project(project), {}, reachable=lambda u: u != dev.DEFAULT_REDIS,
                           which=lambda tool: "/usr/bin/docker" if tool == "docker" else None)
    assert handle.url == "redis://127.0.0.1:55123/0"
    name = dev.docker_redis_name(load_project(project))
    run = next(c for c in calls if c[0] == "run")
    assert name in run and "--appendonly" in run and f"{name}-data:/data" in run
    handle.cleanup()
    assert calls[-1] == ["stop", name]


def test_docker_redis_name_is_scoped_to_the_project_path(tmp_path):
    for d in ("a", "b"):
        (tmp_path / d).mkdir()
        (tmp_path / d / "jarviscore.yaml").write_text(textwrap.dedent(YAML))
    a, b = (dev.docker_redis_name(load_project(tmp_path / d)) for d in ("a", "b"))
    assert a != b and a.startswith("jarviscore-dev-demo-") and a.endswith("-redis")
    assert a == dev.docker_redis_name(load_project(tmp_path / "a"))


def test_no_redis_anywhere_explains_options(project):
    with pytest.raises(DevError, match="docker run"):
        resolve_redis(load_project(project), {}, reachable=lambda u: False, which=no_tools)


# ── Planning and reload targeting ─────────────────────────────────────────

def test_plan_peers_seed_and_replicas(project):
    ports = iter([30001, 30002, 30003])
    peers = plan_peers(load_project(project), ["triage", "responder"], "redis://r",
                       allocate=lambda taken: next(ports))
    assert [p.label for p in peers] == ["triage-1", "responder-1", "responder-2"]
    assert "JARVISCORE_SEED_NODES" not in peers[0].env
    assert {p.env["JARVISCORE_SEED_NODES"] for p in peers[1:]} == {"127.0.0.1:30001"}
    assert all(p.env["REDIS_URL"] == "redis://r" for p in peers)


def test_allocated_ports_are_free_and_distinct():
    taken: set[int] = set()
    a, b = allocate_peer_port(taken), allocate_peer_port(taken)
    assert a != b and {a, a + 1000, b, b + 1000} <= taken


class _FakeProc:
    def poll(self):
        return None

    def send_signal(self, sig):
        pass

    def wait(self, timeout=None):
        return 0


def _session(project, roles=("triage", "responder")):
    session = dev.DevSession(load_project(project), list(roles), dev.RedisHandle("redis://r", "test"))
    session.peers = plan_peers(session.loaded, session.roles, "redis://r", taken=session.used_ports)
    session._start = lambda peer: setattr(peer, "proc", _FakeProc())
    session.say = lambda text: None
    for peer in session.peers:
        session._start(peer)
    return session


def test_restart_moves_agent_to_fresh_ports_and_rejoins_a_survivor(project):
    session = _session(project)
    triage = session.peers[0]
    old_ports = {p.port for p in session.peers}
    session.restart({"triage"})
    assert triage.port not in old_ports
    assert triage.env["JARVISCORE_BIND_PORT"] == str(triage.port)
    survivors = {f"127.0.0.1:{p.port}" for p in session.peers if p.role == "responder"}
    assert triage.env["JARVISCORE_SEED_NODES"] in survivors
    assert session._seed_peer() is not triage


def test_restarting_every_agent_elects_a_new_seed(project):
    session = _session(project)
    old_ports = {p.port for p in session.peers}
    session.restart({"triage", "responder"})
    new_seed, *others = session.peers
    assert not ({p.port for p in session.peers} & old_ports)
    assert "JARVISCORE_SEED_NODES" not in new_seed.env
    assert {p.env["JARVISCORE_SEED_NODES"] for p in others} == {f"127.0.0.1:{new_seed.port}"}
    assert session._seed_peer() is new_seed


def test_peers_know_the_dev_pid(project):
    peers = plan_peers(load_project(project), ["triage"], "redis://r", allocate=lambda t: 30001)
    assert peers[0].env[dev.PARENT_PID_ENV] == str(os.getpid())


# -- One dev session per project ------------------------------------------

def test_session_lock_refuses_a_live_owner(project):
    loaded = load_project(project)
    other = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        path = dev.session_file(loaded)
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({"pid": other.pid, "redis_url": "redis://x"}))
        with pytest.raises(DevError, match=rf"already running for this project \(pid {other.pid}\)"):
            dev.acquire_session(loaded)
        dev.release_session(loaded)
        assert path.exists(), "must not remove another session's file"
    finally:
        other.kill()
        other.wait()


def test_session_lock_takes_over_a_stale_file(project):
    loaded = load_project(project)
    path = dev.session_file(loaded)
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"pid": 9_999_999, "redis_url": "redis://old"}))
    dev.acquire_session(loaded)
    data = json.loads(path.read_text())
    assert data["pid"] == os.getpid() and data["redis_url"] is None
    dev.release_session(loaded)
    assert not path.exists()


def test_roles_to_restart(project):
    loaded = load_project(project)
    roles = ["triage", "responder"]
    assert roles_to_restart({str(project / "agents/triage.py")}, loaded, roles) == {"triage"}
    assert roles_to_restart({str(project / "agents/shared.py")}, loaded, roles) == set(roles)
    assert roles_to_restart({str(project / "jarviscore.yaml")}, loaded, roles) is None
    assert roles_to_restart({str(project / "notes.yaml")}, loaded, roles) == set()


def test_select_roles(project):
    loaded = load_project(project)
    assert _select_roles(loaded, []) == ["triage", "responder"]
    assert _select_roles(loaded, ["responder"]) == ["responder"]
    with pytest.raises(DevError, match="Unknown agent"):
        _select_roles(loaded, ["nope"])
    (project / "agents" / "triage.py").unlink()
    with pytest.raises(DevError, match="not found"):
        _select_roles(loaded, [])


# ── End to end: real peers against a fakeredis TCP server ─────────────────

@pytest.fixture
def redis_server():
    from fakeredis import TcpFakeServer

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = TcpFakeServer(("127.0.0.1", port), server_type="redis")
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"redis://127.0.0.1:{port}/0"
    server.shutdown()


def _lines(project, role):
    path = project / "markers" / f"{role}.log"
    return path.read_text().splitlines() if path.exists() else []


def _wait(predicate, proc, timeout=90):
    deadline = time.time() + timeout
    while not predicate():
        if proc.poll() is not None:
            pytest.fail(f"jarviscore dev exited early:\n{proc.stdout.read()}")
        if time.time() > deadline:
            proc.kill()
            pytest.fail(f"timed out:\n{proc.stdout.read()}")
        time.sleep(0.3)


def _start_dev(project, redis_url, *args):
    (project / "markers").mkdir(exist_ok=True)
    env = {**os.environ, "MARKER_DIR": str(project / "markers")}
    return subprocess.Popen(
        [sys.executable, "-m", "jarviscore.cli", "dev", "--redis", redis_url, *args],
        cwd=project, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )


def _ups(project, role):
    return [line for line in _lines(project, role) if line.startswith("up ")]


def test_dev_runs_every_replica_and_stops_cleanly(project, redis_server):
    proc = _start_dev(project, redis_server, "--no-reload")
    try:
        _wait(lambda: len(_ups(project, "triage")) == 1 and len(_ups(project, "responder")) == 2, proc)
        triage = _ups(project, "triage")[0]
        assert triage.startswith("up demo-triage-1 seed=") and triage.endswith("seed=")
        seeds = {line.split("seed=")[1] for line in _ups(project, "responder")}
        assert len(seeds) == 1 and seeds.pop().startswith("127.0.0.1:")
        assert {line.split()[1] for line in _ups(project, "responder")} == {"demo-responder-1", "demo-responder-2"}

        proc.send_signal(signal.SIGINT)
        out, _ = proc.communicate(timeout=60)
        assert proc.returncode == 0, out
        assert "Stopped." in out
        downs = [line for role in ("triage", "responder") for line in _lines(project, role) if line.startswith("down")]
        assert len(downs) == 3, out
    finally:
        if proc.poll() is None:
            proc.kill()


def test_dev_reload_restarts_only_the_edited_agent(project, redis_server):
    proc = _start_dev(project, redis_server, "--reload")
    try:
        _wait(lambda: len(_ups(project, "triage")) == 1 and len(_ups(project, "responder")) == 2, proc)
        time.sleep(2)  # let the watcher settle before editing
        agent = project / "agents" / "triage.py"
        agent.write_text(agent.read_text() + "\n# edited\n")
        _wait(lambda: len(_ups(project, "triage")) == 2, proc)
        assert len(_ups(project, "responder")) == 2
        assert any(line.startswith("down demo-triage-1") for line in _lines(project, "triage"))
        restarted_seed = _ups(project, "triage")[1].split("seed=")[1]
        responder_seed = _ups(project, "responder")[0].split("seed=")[1]
        # Restarted on new ports, rejoining through a responder that kept running.
        assert restarted_seed not in ("", responder_seed)
        time.sleep(3)
    finally:
        proc.send_signal(signal.SIGINT)
        try:
            out, _ = proc.communicate(timeout=60)
        except subprocess.TimeoutExpired:
            proc.kill()
            out = ""
    assert "PortValidationError" not in out and "is not available" not in out, out


def _agent_pids(project):
    out = subprocess.run(["pgrep", "-f", f"jarviscore.cli.serve {project}"], capture_output=True, text=True)
    return [int(p) for p in out.stdout.split()]


def test_second_dev_in_same_project_is_refused(project, redis_server):
    first = _start_dev(project, redis_server, "--no-reload")
    try:
        _wait(lambda: len(_ups(project, "triage")) == 1 and len(_ups(project, "responder")) == 2, first)
        second = subprocess.run(
            [sys.executable, "-m", "jarviscore.cli", "dev", "--no-reload", "--redis", redis_server],
            cwd=project, capture_output=True, text=True, timeout=60, check=False,
        )
        assert second.returncode == 2
        assert f"already running for this project (pid {first.pid})" in second.stderr
        session = json.loads((project / ".jarviscore" / "dev" / "session.json").read_text())
        assert session["pid"] == first.pid and session["redis_url"] == redis_server
        assert first.poll() is None
    finally:
        first.send_signal(signal.SIGINT)
        try:
            first.communicate(timeout=60)
        except subprocess.TimeoutExpired:
            first.kill()


def test_agents_stop_when_dev_is_killed_hard(project, redis_server):
    proc = _start_dev(project, redis_server, "--no-reload")
    _wait(lambda: len(_ups(project, "triage")) == 1 and len(_ups(project, "responder")) == 2, proc)
    pids = _agent_pids(project.resolve())
    assert len(pids) == 3, pids
    proc.kill()
    proc.wait()
    deadline = time.time() + 45
    while _agent_pids(project.resolve()) and time.time() < deadline:
        time.sleep(0.5)
    leftover = _agent_pids(project.resolve())
    for pid in leftover:
        os.kill(pid, signal.SIGKILL)
    assert leftover == [], "agents outlived a killed jarviscore dev"


def test_dev_without_project_exits_2(tmp_path):
    out = subprocess.run([sys.executable, "-m", "jarviscore.cli", "dev"], cwd=tmp_path,
                         capture_output=True, text=True, check=False)
    assert out.returncode == 2 and "jarviscore init" in out.stderr


def test_dev_unknown_role_exits_2(project):
    out = subprocess.run([sys.executable, "-m", "jarviscore.cli", "dev", "ghost", "--redis", "redis://x"],
                         cwd=project, capture_output=True, text=True, check=False)
    assert out.returncode == 2 and "Unknown agent(s) ghost" in out.stderr


def test_dev_command_is_listed():
    out = subprocess.run([sys.executable, "-m", "jarviscore.cli", "--help"], capture_output=True,
                         text=True, check=False)
    assert "Run all agents locally" in out.stdout
