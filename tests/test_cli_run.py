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

from jarviscore.cli.run import RunError, agent_role, resolve_run_redis
from jarviscore.project import load_project

YAML = """
service: demo
agents:
  helper: { path: agents/helper.py }
"""

AGENT = '''
from jarviscore.profiles import CustomAgent


class Helper(CustomAgent):
    role = "support_helper"
    capabilities = ["support_helper", "echo"]

    async def on_peer_request(self, msg):
        task = msg.data.get("task", "")
        if task == "explode":
            raise RuntimeError("helper failed on purpose")
        return {"echo": task.upper()}
'''


@pytest.fixture
def project(tmp_path):
    (tmp_path / "agents").mkdir()
    (tmp_path / "jarviscore.yaml").write_text(textwrap.dedent(YAML))
    (tmp_path / "agents" / "helper.py").write_text(AGENT)
    return tmp_path


def test_role_comes_from_the_agent_class(project):
    assert agent_role(load_project(project), "helper") == "support_helper"


def test_unknown_agent(project):
    with pytest.raises(RunError, match="Defined agents: helper"):
        agent_role(load_project(project), "nope")


def test_redis_order(project):
    loaded = load_project(project)
    assert resolve_run_redis(
        loaded, {"REDIS_URL": "redis://env"}, "redis://flag") == ("redis://flag", "--redis")

    session = project / ".jarviscore" / "dev" / "session.json"
    session.parent.mkdir(parents=True)
    session.write_text(json.dumps(
        {"pid": os.getpid(), "redis_url": "redis://dev"}))
    assert resolve_run_redis(loaded, {
                             "REDIS_URL": "redis://env"}, None) == ("redis://dev", "jarviscore dev session")

    session.write_text(json.dumps(
        {"pid": 999_999_9, "redis_url": "redis://stale"}))
    assert resolve_run_redis(
        loaded, {"REDIS_URL": "redis://env"}, None) == ("redis://env", "REDIS_URL")

    # dev has claimed the project but Redis is not up yet.
    session.write_text(json.dumps({"pid": os.getpid(), "redis_url": None}))
    assert resolve_run_redis(
        loaded, {"REDIS_URL": "redis://env"}, None) == ("redis://env", "REDIS_URL")

    with pytest.raises(RunError, match="jarviscore dev"):
        resolve_run_redis(loaded, {}, None)


# ── End to end: dev mesh + run ────────────────────────────────────────────

@pytest.fixture
def mesh(project):
    from fakeredis import TcpFakeServer

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = TcpFakeServer(("127.0.0.1", port), server_type="redis")
    threading.Thread(target=server.serve_forever, daemon=True).start()
    proc = subprocess.Popen(
        [sys.executable, "-m", "jarviscore.cli", "dev",
            "--no-reload", "--redis", f"redis://127.0.0.1:{port}/0"],
        cwd=project, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    session = project / ".jarviscore" / "dev" / "session.json"
    deadline = time.time() + 60
    while not session.exists():
        assert proc.poll() is None and time.time() < deadline, proc.stdout.read(
        ) if proc.poll() is not None else "timeout"
        time.sleep(0.3)
    time.sleep(2)  # distributed worker polling loop
    yield project
    proc.send_signal(signal.SIGINT)
    try:
        proc.communicate(timeout=60)
    except subprocess.TimeoutExpired:
        proc.kill()
    server.shutdown()
    assert not session.exists()


def _run(project, *args):
    return subprocess.run([sys.executable, "-m", "jarviscore.cli", "run", *args], cwd=project,
                          capture_output=True, text=True, check=False, timeout=120)


def test_run_against_dev_mesh(mesh):
    out = _run(mesh, "helper", "hello world", "--timeout", "60")
    assert out.returncode == 0, out.stdout + out.stderr
    assert json.loads(out.stdout) == {"echo": "HELLO WORLD"}
    assert "jarviscore dev session" in out.stderr

    as_json = _run(mesh, "helper", "again", "--json", "--timeout", "60")
    data = json.loads(as_json.stdout)
    assert data["status"] == "success" and data["workflow_id"].startswith(
        "run-support_helper-")

    failed = _run(mesh, "helper", "explode", "--timeout", "60")
    assert failed.returncode == 1 and "helper failed on purpose" in failed.stderr


def test_run_without_mesh(project):
    out = _run(project, "helper", "hi")
    assert out.returncode == 2 and "jarviscore dev" in out.stderr
