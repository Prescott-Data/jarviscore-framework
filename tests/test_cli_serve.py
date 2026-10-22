import os
import signal
import socket
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest
from typer.testing import CliRunner

from jarviscore.cli import serve as serve_mod
from jarviscore.cli.app import app
from jarviscore.cli.serve import AgentResolutionError, load_agent_module, resolve_agent

runner = CliRunner()

AGENT_HEADER = "from jarviscore.profiles import CustomAgent\n"
AGENT_CLASS = """
class {name}(CustomAgent):
    role = "{role}"
    capabilities = ["{role}"]

    async def on_peer_request(self, msg):
        return {{}}
"""


def agent_source(*names, extra=""):
    body = "".join(AGENT_CLASS.format(name=n, role=n.lower()) for n in names)
    return AGENT_HEADER + body + extra


def module_from(tmp_path, source, name="agent_mod.py"):
    path = tmp_path / name
    path.write_text(textwrap.dedent(source))
    return load_agent_module(tmp_path, path)


# ── resolve_agent ─────────────────────────────────────────────────────────

def test_single_subclass_is_used(tmp_path):
    cls = resolve_agent(module_from(tmp_path, agent_source("Triage")))
    assert cls.__name__ == "Triage"


def test_explicit_instance_wins(tmp_path):
    mod = module_from(tmp_path, agent_source("Triage", "Other", extra="\nagent = Other()\n"))
    assert type(resolve_agent(mod)).__name__ == "Other"


def test_explicit_class_wins(tmp_path):
    mod = module_from(tmp_path, agent_source("Triage", "Other", extra="\nagent = Triage\n"))
    assert resolve_agent(mod).__name__ == "Triage"


def test_imported_agents_are_ignored(tmp_path):
    (tmp_path / "shared.py").write_text(textwrap.dedent(agent_source("Base")))
    mod = module_from(tmp_path, "from shared import Base\n" + agent_source("Triage"))
    assert resolve_agent(mod).__name__ == "Triage"


def test_no_agent_explains_both_options(tmp_path):
    with pytest.raises(AgentResolutionError, match="agent = MyAgent"):
        resolve_agent(module_from(tmp_path, "x = 1\n"))


def test_several_agents_must_pick_one(tmp_path):
    with pytest.raises(AgentResolutionError, match=r"several agents \(One, Two\)"):
        resolve_agent(module_from(tmp_path, agent_source("One", "Two")))


def test_agent_variable_of_wrong_type(tmp_path):
    with pytest.raises(AgentResolutionError, match="must be an Agent"):
        resolve_agent(module_from(tmp_path, "agent = 42\n"))


# ── serve command ─────────────────────────────────────────────────────────

@pytest.fixture
def project(tmp_path, monkeypatch):
    (tmp_path / "agents").mkdir()
    (tmp_path / "agents" / "triage.py").write_text(agent_source("Triage"))
    (tmp_path / "jarviscore.yaml").write_text(textwrap.dedent("""
        service: support-bot
        agents:
          triage: { path: agents/triage.py, env: { clear: { TONE: calm } } }
          ghost:  { path: agents/missing.py }
        env:
          clear: { LOG_LEVEL: DEBUG }
    """))
    monkeypatch.chdir(tmp_path / "agents")
    return tmp_path


def test_serve_execs_runner_with_resolved_env(project, monkeypatch):
    captured = {}

    def fake_execve(path, argv, env):
        captured.update(path=path, argv=argv, env=env, cwd=os.getcwd())
        raise SystemExit(0)

    monkeypatch.setattr(serve_mod.os, "execve", fake_execve)
    monkeypatch.setenv("LOG_LEVEL", "WARNING")
    monkeypatch.delenv("JARVISCORE_NODE_NAME", raising=False)

    result = runner.invoke(app, ["serve", "--role", "triage", "--replica", "2"])
    assert result.exit_code == 0, result.output
    env = captured["env"]
    assert captured["argv"][1:3] == ["-m", "jarviscore.cli.serve"]
    assert captured["argv"][3:] == [str(project.resolve()), str(project.resolve() / "agents/triage.py")]
    assert captured["cwd"] == str(project.resolve())
    assert env["TONE"] == "calm"
    assert env["LOG_LEVEL"] == "WARNING"  # process env wins over the project file
    assert env["JARVISCORE_ROLE"] == "triage"
    assert env["JARVISCORE_NODE_NAME"] == "support-bot-triage-2"


def test_serve_unknown_role(project):
    result = runner.invoke(app, ["serve", "--role", "nope"])
    assert result.exit_code == 2
    assert "Defined agents: triage, ghost" in result.output


def test_serve_missing_agent_file(project):
    result = runner.invoke(app, ["serve", "--role", "ghost"])
    assert result.exit_code == 2
    assert "agents/missing.py does not exist" in result.output


def test_serve_without_project(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["serve", "--role", "triage"])
    assert result.exit_code == 2
    assert "jarviscore init" in result.output


# ── end to end: real process, real mesh, SIGTERM shutdown ─────────────────

def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


LIFECYCLE_AGENT = """
import os
from pathlib import Path
from jarviscore.profiles import CustomAgent

class Triage(CustomAgent):
    role = "triage"
    capabilities = ["triage"]

    async def setup(self):
        await super().setup()
        Path(os.environ["MARKER"]).write_text(os.environ.get("JARVISCORE_NODE_NAME", ""))

    async def teardown(self):
        Path(os.environ["MARKER"] + ".down").write_text("down")
        await super().teardown()

    async def on_peer_request(self, msg):
        return {}
"""


def test_serve_runs_agent_and_stops_cleanly_on_sigterm(project):
    (project / "agents" / "triage.py").write_text(LIFECYCLE_AGENT)
    marker = project / "up.marker"
    env = {
        **os.environ,
        "MARKER": str(marker),
        "JARVISCORE_BIND_PORT": str(_free_port()),
        "JARVISCORE_BIND_HOST": "127.0.0.1",
    }
    env.pop("REDIS_URL", None)
    proc = subprocess.Popen(
        [sys.executable, "-m", "jarviscore.cli", "serve", "--role", "triage"],
        cwd=project, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    try:
        deadline = time.time() + 60
        while not marker.exists():
            assert proc.poll() is None, proc.stdout.read()
            assert time.time() < deadline, "agent never started"
            time.sleep(0.2)
        assert marker.read_text() == "support-bot-triage-1"

        proc.send_signal(signal.SIGTERM)
        assert proc.wait(timeout=30) == 0, proc.stdout.read()
        assert Path(str(marker) + ".down").exists()
    finally:
        if proc.poll() is None:
            proc.kill()


TASK_DRIVEN_AGENT = """
import os
from pathlib import Path
from jarviscore import Agent

class Worker(Agent):
    role = "triage"
    capabilities = ["triage"]

    async def setup(self):
        await super().setup()
        Path(os.environ["MARKER"]).write_text("up")

    async def teardown(self):
        Path(os.environ["MARKER"] + ".down").write_text("down")
        await super().teardown()

    async def execute_task(self, task):
        return {"status": "success", "output": None}
"""


def test_task_driven_agent_keeps_its_mesh_until_signalled(project):
    # Agents without their own run() loop (AutoAgent, every `jarviscore init` template)
    # used to have their mesh stopped right after start while the process stayed up.
    (project / "agents" / "triage.py").write_text(TASK_DRIVEN_AGENT)
    marker = project / "up.marker"
    env = {**os.environ, "MARKER": str(marker), "JARVISCORE_BIND_PORT": str(_free_port()),
           "JARVISCORE_BIND_HOST": "127.0.0.1"}
    env.pop("REDIS_URL", None)
    proc = subprocess.Popen(
        [sys.executable, "-m", "jarviscore.cli", "serve", "--role", "triage"],
        cwd=project, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    try:
        deadline = time.time() + 60
        while not marker.exists():
            assert proc.poll() is None, proc.stdout.read()
            assert time.time() < deadline, "agent never started"
            time.sleep(0.2)
        time.sleep(3)
        assert proc.poll() is None
        assert not Path(str(marker) + ".down").exists(), "mesh was stopped without a signal"

        proc.send_signal(signal.SIGTERM)
        assert proc.wait(timeout=30) == 0, proc.stdout.read()
        assert Path(str(marker) + ".down").exists()
    finally:
        if proc.poll() is None:
            proc.kill()


@pytest.mark.parametrize("source, expected", [
    ("from jarviscore.profiles import CustomAgent as Base", True),
    ("from jarviscore.profiles import AutoAgent as Base", False),
    ("from jarviscore import Agent as Base", False),
])
def test_has_run_loop(tmp_path, source, expected):
    module = module_from(tmp_path, source + """

class Thing(Base):
    role = "thing"
    capabilities = ["thing"]
""")
    assert serve_mod.has_run_loop(module.Thing) is expected


# ── runner argv and orphan handling ───────────────────────────────────────

@pytest.mark.parametrize("args", [[], ["--help"], ["only-one"]])
def test_runner_validates_argv(args):
    out = subprocess.run([sys.executable, "-m", "jarviscore.cli.serve", *args],
                         capture_output=True, text=True, check=False)
    assert out.returncode == 2
    assert "usage: python -m jarviscore.cli.serve" in out.stderr
    assert "Traceback" not in out.stderr


def test_runner_rejects_missing_files(tmp_path):
    out = subprocess.run([sys.executable, "-m", "jarviscore.cli.serve", str(tmp_path),
                          str(tmp_path / "nope.py")], capture_output=True, text=True, check=False)
    assert out.returncode == 2 and "nope.py does not exist" in out.stderr


def test_runner_import_does_not_load_typer_or_the_schema():
    code = ("import sys, jarviscore.cli.serve; "
            "print(any(m in sys.modules for m in ('typer', 'pydantic', 'jarviscore.project.schema')))")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "False"


async def test_orphaned_agent_stops_and_arms_an_exit_watchdog(monkeypatch):
    import asyncio

    armed = []
    monkeypatch.setenv(serve_mod.PARENT_PID_ENV, str(os.getppid() + 100000))
    monkeypatch.setattr(serve_mod, "_detach_output", lambda: None)
    monkeypatch.setattr(serve_mod, "_arm_exit_watchdog", armed.append)
    stop = asyncio.Event()
    assert await asyncio.wait_for(serve_mod._stop_when_orphaned(stop, interval=0.01), 2) is True
    assert stop.is_set() and armed == [serve_mod.ORPHAN_STOP_TIMEOUT]


async def test_agent_with_live_parent_keeps_running(monkeypatch):
    import asyncio

    monkeypatch.setenv(serve_mod.PARENT_PID_ENV, str(os.getppid()))
    stop = asyncio.Event()
    watch = asyncio.create_task(serve_mod._stop_when_orphaned(stop, interval=0.01))
    await asyncio.sleep(0.1)
    assert not watch.done() and not stop.is_set()
    stop.set()
    assert await asyncio.wait_for(watch, 1) is False


def test_serve_uses_the_project_venv(project, monkeypatch):
    captured = {}

    def fake_execve(path, argv, env):
        captured.update(path=path, argv=argv)
        raise SystemExit(0)

    monkeypatch.setattr(serve_mod.os, "execve", fake_execve)
    bindir = project / ".venv" / "bin"
    bindir.mkdir(parents=True)
    python = bindir / "python"
    python.write_text(f'#!/bin/sh\nexec "{sys.executable}" "$@"\n')
    python.chmod(0o755)
    result = runner.invoke(app, ["serve", "--role", "triage"])
    assert result.exit_code == 0, result.output
    assert captured["path"] == str(python) and captured["argv"][0] == str(python)
