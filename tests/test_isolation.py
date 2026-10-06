"""Confinement is what lets model-written code run: it must actually confine."""

import sys
from pathlib import Path

import pytest

from jarviscore.execution import isolation
from jarviscore.execution.coder_sandbox import create_coder_sandbox
from jarviscore.execution.isolation import confinement_prefix

confined_host = pytest.mark.skipif(
    confinement_prefix(Path.cwd()) is None, reason="this host offers no process confinement"
)


def probe(path):
    return (
        "import os, socket\n"
        "async def main():\n"
        "    out = {}\n"
        f"    try:\n        open({str(path)!r}).read(); out['outside_read'] = 'allowed'\n"
        "    except Exception as exc:\n        out['outside_read'] = type(exc).__name__\n"
        "    try:\n        socket.create_connection(('1.1.1.1', 443), timeout=3); out['network'] = 'allowed'\n"
        "    except Exception as exc:\n        out['network'] = type(exc).__name__\n"
        "    open('note.txt', 'w').write('kept'); out['workspace_write'] = open('note.txt').read()\n"
        "    try:\n        open('logs/function_registry/atom.py', 'w').write('x'); out['registry_write'] = 'allowed'\n"
        "    except Exception as exc:\n        out['registry_write'] = type(exc).__name__\n"
        "    return out\n"
    )


@confined_host
@pytest.mark.asyncio
async def test_confined_code_runs_without_the_opt_in_but_cannot_escape(tmp_path):
    secret = tmp_path.parent / f"{tmp_path.name}-secret.env"
    secret.write_text("API_KEY=do-not-read")
    workspace = tmp_path / "run"
    registry = workspace / "logs" / "function_registry"
    registry.mkdir(parents=True)
    (registry / "atom.py").write_text("original")
    sandbox = create_coder_sandbox(workspace_dir=workspace, timeout=60)
    sandbox.protected_paths = (workspace / "logs",)

    result = await sandbox.execute(probe(secret))

    assert result["status"] == "success", result
    assert result["data"]["workspace_write"] == "kept"
    assert result["data"]["outside_read"] != "allowed"
    assert result["data"]["network"] != "allowed"
    assert result["data"]["registry_write"] != "allowed"
    assert (registry / "atom.py").read_text() == "original"


@confined_host
def test_the_profile_names_no_home_directory_beyond_runtime_and_workspace(tmp_path):
    prefix = confinement_prefix(tmp_path)
    if sys.platform != "darwin":
        pytest.skip("seatbelt profile is macOS-specific")
    profile = prefix[2]
    assert "(deny default)" in profile
    assert "network" not in profile.replace("(deny default)", "")
    assert f'(subpath "{Path.home()}")' not in profile


def test_an_installed_mechanism_that_cannot_start_a_child_is_not_confinement(tmp_path, monkeypatch):
    refuse = [sys.executable, "-c", "import sys; sys.exit('No permissions to create a new namespace')"]
    monkeypatch.setattr(isolation, "_mechanism", lambda: "bubblewrap")
    monkeypatch.setattr(isolation, "_prefix_for", lambda *args: refuse)
    isolation.confinement_unavailable_reason.cache_clear()
    try:
        assert confinement_prefix(tmp_path) is None
        assert "No permissions to create a new namespace" in isolation.confinement_unavailable_reason()
    finally:
        isolation.confinement_unavailable_reason.cache_clear()
