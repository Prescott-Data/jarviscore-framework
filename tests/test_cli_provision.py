import os
import signal
import subprocess
import sys
import time

import pytest

from jarviscore.cli import _provision as prov
from jarviscore.cli import dev
from jarviscore.cli._provision import (
    NO_SYNC_ENV,
    Interrupted,
    ProvisionError,
    _minimal_dependencies,
    project_dependencies,
    provision,
    run_step,
    should_provision,
    venv_python,
)
from jarviscore.project import load_project

PYPROJECT = '''
[project]
name = "demo"
version = "0.1.0"
dependencies = [
    "jarviscore-framework[p2p,redis]>=2.1.0",  # the framework
    'httpx>=0.27; python_version >= "3.10"',
]

[project.optional-dependencies]
dev = ["pytest>=7.4"]

[tool.uv]
package = false

[tool.other]
dependencies = ["not-this"]
'''

YAML = "service: demo\nagents:\n  helper: { path: agents/helper.py }\n"


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.delenv(NO_SYNC_ENV, raising=False)
    (tmp_path / "agents").mkdir()
    (tmp_path / "agents" / "helper.py").write_text("")
    (tmp_path / "jarviscore.yaml").write_text(YAML)
    (tmp_path / "pyproject.toml").write_text(PYPROJECT)
    return tmp_path


class Recorder:
    """Stands in for run_step: records argv and plays scripted results."""

    def __init__(self, *results, make_venv=False):
        self.calls = []
        self.results = list(results)
        self.make_venv = make_venv

    def __call__(self, argv, cwd, timeout):
        self.calls.append((argv, cwd, timeout))
        if self.make_venv:
            (cwd / ".venv" / "bin").mkdir(parents=True, exist_ok=True)
        result = self.results.pop(0) if self.results else (0, [])
        if isinstance(result, BaseException):
            raise result
        return result


EXPECTED = ["jarviscore-framework[p2p,redis]>=2.1.0", 'httpx>=0.27; python_version >= "3.10"']


# ── Choosing what to do ──────────────────────────────────────────────────

@pytest.mark.parametrize("setup, sync, env, expected", [
    (None, True, {}, True),
    ("venv", True, {}, False),
    ("no-pyproject", True, {}, False),
    (None, False, {}, False),
    (None, True, {NO_SYNC_ENV: "1"}, False),
    (None, True, {NO_SYNC_ENV: "true"}, False),
    (None, True, {NO_SYNC_ENV: "0"}, True),
    (None, True, {NO_SYNC_ENV: ""}, True),
])
def test_should_provision(project, setup, sync, env, expected):
    if setup == "venv":
        (project / ".venv").mkdir()
    elif setup == "no-pyproject":
        (project / "pyproject.toml").unlink()
    assert should_provision(project, sync=sync, environ=env) is expected


def test_uv_is_used_when_on_path(project):
    run = Recorder()
    provision(project, which=lambda name: "/opt/bin/uv" if name == "uv" else None,
              runner=run, note=lambda _: None)
    assert [(argv, cwd) for argv, cwd, _ in run.calls] == [(["/opt/bin/uv", "sync"], project)]


def test_without_uv_creates_venv_and_pip_installs_the_dependencies(project):
    run = Recorder()
    notes = []
    provision(project, which=lambda _: None, python="/usr/bin/python3", runner=run,
              note=notes.append)
    venv = project / ".venv"
    assert [argv for argv, _, _ in run.calls] == [
        ["/usr/bin/python3", "-m", "venv", str(venv)],
        [str(venv_python(venv)), "-m", "pip", "install", "--disable-pip-version-check", *EXPECTED],
    ]
    assert all(cwd == project for _, cwd, _ in run.calls)
    assert notes[0] == "Setting up project environment in .venv (first run)…"
    assert any("uv not found" in n and "pip" in n for n in notes)
    assert "-e" not in run.calls[1][0]


def test_dependencies_are_required_without_uv(project):
    (project / "pyproject.toml").write_text('[project]\nname = "demo"\n')
    run = Recorder()
    with pytest.raises(ProvisionError, match="no \\[project\\].dependencies"):
        provision(project, which=lambda _: None, runner=run, note=lambda _: None)
    assert run.calls == [] and not (project / ".venv").exists()


@pytest.mark.parametrize("text", [
    PYPROJECT,
    '[project]\ndependencies = []\n',
    '[project]\nname = "x"\n',
    '[tool.x]\ndependencies = ["a"]\n[project]\ndependencies = ["b[c]>=1", \'d\']\n',
    '[project]\ndependencies = [\n  # leading comment\n  "a",\n  "b",  # trailing\n]\n[tool.x]\n',
    '[project]\ndependencies = ["esc\\"aped"]\n',
])
def test_minimal_parser_matches_tomllib(text):
    tomllib = pytest.importorskip("tomllib")
    expected = tomllib.loads(text).get("project", {}).get("dependencies", [])
    assert _minimal_dependencies(text) == expected


def test_project_dependencies_reads_project_table_only(project):
    assert project_dependencies(project / "pyproject.toml") == EXPECTED


def test_project_dependencies_fallback_without_toml_library(project, monkeypatch):
    monkeypatch.setattr(prov, "_toml_loads", lambda: None)
    assert project_dependencies(project / "pyproject.toml") == EXPECTED


def test_invalid_pyproject_is_reported(project):
    (project / "pyproject.toml").write_text("[project\n")
    with pytest.raises(ProvisionError, match="not valid TOML"):
        project_dependencies(project / "pyproject.toml")


# ── Failure and interruption ─────────────────────────────────────────────

def test_failure_removes_venv_and_shows_tail_and_manual_command(project):
    run = Recorder((0, []), (1, ["Collecting swim", "ERROR: no matching distribution"]),
                   make_venv=True)
    with pytest.raises(ProvisionError) as info:
        provision(project, which=lambda _: None, python="/usr/bin/python3", runner=run,
                  note=lambda _: None)
    message = str(info.value)
    assert "exited with code 1" in message
    assert "ERROR: no matching distribution" in message
    assert "/usr/bin/python3 -m venv .venv" in message
    assert ".venv/bin/python -m pip install 'jarviscore-framework[p2p,redis]>=2.1.0'" in message
    assert "--no-sync" in message
    assert not (project / ".venv").exists()


def test_timeout_is_reported(project):
    run = Recorder((None, []), make_venv=True)
    with pytest.raises(ProvisionError, match="(?s)timed out after 1800s.*uv sync"):
        provision(project, which=lambda _: "uv", runner=run, note=lambda _: None)
    assert not (project / ".venv").exists()


def test_interrupt_removes_half_created_venv(project):
    run = Recorder((0, []), Interrupted(signal.SIGINT), make_venv=True)
    with pytest.raises(Interrupted):
        provision(project, which=lambda _: None, runner=run, note=lambda _: None)
    assert not (project / ".venv").exists()


def test_run_step_keeps_the_tail_and_exit_code(tmp_path):
    code, tail = run_step(
        [sys.executable, "-c", "import sys\nfor i in range(100): print(i)\nsys.exit(3)"],
        tmp_path, 30)
    assert code == 3
    assert tail[-1] == "99" and len(tail) == prov.TAIL_LINES


def test_run_step_timeout_stops_the_process(tmp_path):
    started = time.monotonic()
    code, _ = run_step([sys.executable, "-c", "import time; time.sleep(60)"], tmp_path, 0.5)
    assert code is None and time.monotonic() - started < 10


def test_run_step_missing_program(tmp_path):
    code, tail = run_step([str(tmp_path / "nope")], tmp_path, 5)
    assert code == 127 and "could not run" in tail[0]


# ── Wired into `jarviscore dev` ──────────────────────────────────────────

def test_dev_provision_failure_exits_1(project, monkeypatch, capsys):
    monkeypatch.chdir(project)

    def fail(root):
        raise ProvisionError("Setting up .venv failed: boom")

    monkeypatch.setattr(prov, "provision", fail)
    assert dev.run_dev([], None, None, reload=False) == 1
    assert "✗ Setting up .venv failed: boom" in capsys.readouterr().err
    assert not dev.session_file(load_project(project)).exists()


@pytest.mark.parametrize("sync, env", [(False, {}), (True, {NO_SYNC_ENV: "1"})])
def test_dev_skips_provisioning(project, monkeypatch, sync, env):
    monkeypatch.chdir(project)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    called = []
    monkeypatch.setattr(prov, "provision", lambda root: called.append(root))
    monkeypatch.setattr(dev, "_agent_python", lambda loaded: (_ for _ in ()).throw(
        dev.DevError("stop here")))
    assert dev.run_dev([], None, None, reload=False, sync=sync) == 1
    assert called == []


def test_dev_help_documents_no_sync():
    out = subprocess.run([sys.executable, "-m", "jarviscore.cli", "dev", "--help"],
                         capture_output=True, text=True, check=False,
                         env={**os.environ, "COLUMNS": "200", "NO_COLOR": "1"})
    assert out.returncode == 0 and "--no-sync" in out.stdout and NO_SYNC_ENV in out.stdout


FAKE_UV = '''#!/bin/sh
mkdir -p .venv/bin
echo "Resolved 42 packages"
{body}
'''


def _fake_uv(tmp_path, body):
    bindir = tmp_path / "fakebin"
    bindir.mkdir()
    uv = bindir / "uv"
    uv.write_text(FAKE_UV.format(body=body))
    uv.chmod(0o755)
    return {**os.environ, "PATH": f"{bindir}:/usr/bin:/bin"}


def test_dev_reports_uv_failure_with_tail(project, tmp_path_factory):
    env = _fake_uv(tmp_path_factory.mktemp("uv"), 'echo "error: network down"; exit 2')
    out = subprocess.run([sys.executable, "-m", "jarviscore.cli", "dev", "--no-reload"],
                         cwd=project, env=env, capture_output=True, text=True, timeout=60,
                         check=False)
    assert out.returncode == 1, out.stderr
    assert "Setting up project environment in .venv (first run)" in out.stderr
    assert "error: network down" in out.stderr and "uv sync" in out.stderr
    assert not (project / ".venv").exists()


def test_ctrl_c_during_provisioning_exits_130_and_cleans_up(project, tmp_path_factory):
    marker = tmp_path_factory.mktemp("marker") / "uv.pid"
    env = _fake_uv(tmp_path_factory.mktemp("uv"), f'echo $$ > {marker}; exec sleep 60')
    proc = subprocess.Popen([sys.executable, "-m", "jarviscore.cli", "dev", "--no-reload"],
                            cwd=project, env=env, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True)
    try:
        deadline = time.time() + 30
        while not (marker.exists() and marker.read_text().strip()):
            assert proc.poll() is None and time.time() < deadline, proc.communicate()
            time.sleep(0.1)
        uv_pid = int(marker.read_text())
        started = time.monotonic()
        proc.send_signal(signal.SIGINT)
        _, err = proc.communicate(timeout=20)
        assert proc.returncode == 130, err
        assert time.monotonic() - started < 10
        assert "Interrupted." in err
        assert not (project / ".venv").exists()
        assert not (project / ".jarviscore" / "dev" / "session.json").exists()
        with pytest.raises(ProcessLookupError):
            os.kill(uv_pid, 0)
    finally:
        if proc.poll() is None:
            proc.kill()


def test_sigterm_during_provisioning_exits_143(project, tmp_path_factory):
    marker = tmp_path_factory.mktemp("marker") / "uv.pid"
    env = _fake_uv(tmp_path_factory.mktemp("uv"), f'echo $$ > {marker}; exec sleep 60')
    proc = subprocess.Popen([sys.executable, "-m", "jarviscore.cli", "dev", "--no-reload"],
                            cwd=project, env=env, stdout=subprocess.DEVNULL,
                            stderr=subprocess.PIPE, text=True)
    try:
        deadline = time.time() + 30
        while not (marker.exists() and marker.read_text().strip()):
            assert proc.poll() is None and time.time() < deadline, proc.communicate()
            time.sleep(0.1)
        proc.send_signal(signal.SIGTERM)
        _, err = proc.communicate(timeout=20)
        assert proc.returncode == 143, err
        assert not (project / ".venv").exists()
    finally:
        if proc.poll() is None:
            proc.kill()
