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


@pytest.fixture(autouse=True)
def _no_env_provisioning(monkeypatch):
    # These projects must never trigger a real `uv sync` / pip install from `jarviscore dev`.
    monkeypatch.setenv("JARVISCORE_DEV_NO_SYNC", "1")

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


# ── Latency and invocation ────────────────────────────────────────────────

async def test_cli_polls_for_the_result_fast_then_backs_off(monkeypatch):
    import asyncio

    from jarviscore.cli.run import RESULT_POLL
    from jarviscore.orchestration import engine as engine_mod

    class Pending:
        def get_step_status(self, workflow_id, step_id):
            return "pending"

    sleeps = []
    real_sleep = asyncio.sleep
    owner = asyncio.current_task()

    async def fake_sleep(seconds):
        # asyncio.sleep is patched process-wide; ignore tasks other tests leaked.
        if asyncio.current_task() is not owner:
            return await real_sleep(seconds)
        sleeps.append(seconds)
        if len(sleeps) >= 12:
            raise asyncio.CancelledError
        await real_sleep(0)

    monkeypatch.setattr(engine_mod.asyncio, "sleep", fake_sleep)
    engine = engine_mod.WorkflowEngine(mesh=type("MeshStub", (), {"agents": []})(),
                                       config=dict(RESULT_POLL), redis_store=Pending())
    with pytest.raises(asyncio.CancelledError):
        await engine._wait_remote_step("wf", "step0", timeout=60)
    assert sleeps[0] == 0.1 and sleeps == sorted(sleeps) and max(sleeps) == 1.0

    sleeps.clear()
    default = engine_mod.WorkflowEngine(mesh=type("MeshStub", (), {"agents": []})(),
                                        redis_store=Pending())
    with pytest.raises(asyncio.CancelledError):
        await default._wait_remote_step("wf", "step0", timeout=60)
    assert set(sleeps) == {2.0}, "the default poll for deployed meshes is unchanged"


def test_run_module_invocation_runs_the_command():
    out = subprocess.run([sys.executable, "-m", "jarviscore.cli.run", "--help"],
                         capture_output=True, text=True, check=False)
    assert out.returncode == 0 and "Usage: jarviscore run" in out.stdout


@pytest.mark.parametrize("command", ["dev", "run", "serve"])
def test_help_does_not_load_the_project_schema(command):
    code = ("import sys; from jarviscore.cli.app import main\n"
            "try:\n"
            f"    main(['{command}', '--help'])\n"
            "except SystemExit:\n"
            "    pass\n"
            "print('LOADED' if {'pydantic', 'yaml', 'dotenv', 'asyncio'} & set(sys.modules) else 'LAZY',"
            " file=sys.stderr)")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=False)
    assert out.stderr.strip().endswith("LAZY"), out.stderr
