import os
from typing import ClassVar

import pytest

from jarviscore import Mesh
from jarviscore.execution.coder_sandbox import create_coder_sandbox
from jarviscore.profiles.autoagent import AutoAgent, _AutoAgentMeshProxy


class RecordingProxy:
    def __init__(self):
        self.calls = []

    async def call(self, connection_id, method, url, **kwargs):
        self.calls.append((connection_id, method, url, kwargs))
        return {"ok": True, "status_code": 200, "body": "ok"}

    def connection_handle(self, provider):
        return f"connection:{provider}"


class RecordingMeshProxy:
    def __init__(self):
        self.calls = []

    async def delegate(self, to, task, context=None, capability=None, timeout=None):
        self.calls.append((to, task, context, capability, timeout))
        return {"status": "success", "output": {"review": "complete"}}

    def list_peers(self):
        return [{"role": "analyst", "capabilities": ["analysis"]}]


@pytest.mark.asyncio
async def test_generated_code_runs_in_a_different_process(monkeypatch):
    monkeypatch.setenv("JARVISCORE_PARENT_SECRET", "must-not-cross")
    sandbox = create_coder_sandbox(timeout=10)

    result = await sandbox.execute(
        "import os\n"
        "async def main():\n"
        "    return {\n"
        "        'pid': os.getpid(),\n"
        "        'secret': os.environ.get('JARVISCORE_PARENT_SECRET'),\n"
        "    }\n"
    )

    assert result["status"] == "success"
    assert result["data"]["pid"] != os.getpid()
    assert result["data"]["secret"] is None


@pytest.mark.asyncio
async def test_allowlisted_commands_remain_available_in_the_scrubbed_child():
    sandbox = create_coder_sandbox(timeout=10)

    result = await sandbox.execute(
        "result = {\n"
        "    'git': bash('git --version'),\n"
        "    'ls': bash('ls'),\n"
        "    'python': bash('python --version'),\n"
        "}\n"
    )

    assert result["status"] == "success"
    assert all(command["success"] for command in result["data"].values())


@pytest.mark.asyncio
async def test_provider_read_access_crosses_the_parent_rpc_only():
    proxy = RecordingProxy()
    sandbox = create_coder_sandbox(timeout=10, nexus_call_proxy=proxy)

    result = await sandbox.execute(
        "async def main():\n"
        "    return await nexus_call('GET', 'https://example.invalid/items')\n",
        context={"_nexus_connection_id": "demo", "_nexus_provider": "demo"},
    )

    assert result["status"] == "success"
    assert result["data"]["status_code"] == 200
    assert proxy.calls == [
        ("demo", "GET", "https://example.invalid/items", {})
    ]


@pytest.mark.asyncio
async def test_generated_code_cannot_mutate_provider_through_raw_nexus_call():
    proxy = RecordingProxy()
    sandbox = create_coder_sandbox(timeout=10, nexus_call_proxy=proxy)

    result = await sandbox.execute(
        "async def main():\n"
        "    return await nexus_call('POST', 'https://example.invalid/items', json={'x': 1})\n",
        context={"_nexus_connection_id": "demo", "_nexus_provider": "demo"},
    )

    assert result["status"] == "failure"
    assert "registered atom" in result["error"]
    assert proxy.calls == []


@pytest.mark.asyncio
async def test_one_child_routes_multiple_providers_through_parent_handles():
    proxy = RecordingProxy()
    sandbox = create_coder_sandbox(timeout=10, nexus_call_proxy=proxy)

    result = await sandbox.execute(
        "async def main():\n"
        "    gmail = await nexus_call('GET', 'https://gmail.googleapis.com/gmail/v1/users/me/profile', provider='gmail')\n"
        "    calendar = await nexus_call('GET', 'https://www.googleapis.com/calendar/v3/users/me/calendarList', provider='google_calendar')\n"
        "    return {'gmail': gmail['status_code'], 'calendar': calendar['status_code']}\n"
    )

    assert result["data"] == {"gmail": 200, "calendar": 200}
    assert [call[0] for call in proxy.calls] == [
        "connection:gmail", "connection:google_calendar",
    ]


@pytest.mark.asyncio
async def test_generated_code_delegates_through_a_restricted_parent_mesh_facade():
    proxy = RecordingMeshProxy()
    sandbox = create_coder_sandbox(timeout=10, mesh_proxy=proxy)

    result = await sandbox.execute(
        "async def main():\n"
        "    peers = await mesh.list_peers()\n"
        "    delegated = await mesh.delegate(\n"
        "        to='analyst', task='Review Acme',\n"
        "        context={'workflow_id': 'wf-1'}, capability='analysis', timeout=30,\n"
        "    )\n"
        "    return {\n"
        "        'peers': peers, 'delegated': delegated,\n"
        "        'has_stop': hasattr(mesh, 'stop'),\n"
        "        'has_add': hasattr(mesh, 'add'),\n"
        "    }\n"
    )

    assert result["status"] == "success"
    assert result["data"]["delegated"]["output"]["review"] == "complete"
    assert result["data"]["peers"][0]["role"] == "analyst"
    assert result["data"]["has_stop"] is False
    assert result["data"]["has_add"] is False
    assert proxy.calls == [
        ("analyst", "Review Acme", {"workflow_id": "wf-1"}, "analysis", 30),
    ]


@pytest.mark.asyncio
async def test_generated_code_delegates_to_a_live_autoagent_peer(monkeypatch):
    class Peer(AutoAgent):
        role = "peer"
        capabilities: ClassVar[list[str]] = ["coordination"]
        system_prompt = "Coordinate."

        async def setup(self):
            pass

        async def execute_task(self, task):
            return {"status": "success", "output": task["task"]}

    class Analyst(Peer):
        role = "analyst"
        capabilities: ClassVar[list[str]] = ["analysis"]

        async def execute_task(self, task):
            return {"status": "success", "output": f"analysed: {task['task']}"}

    monkeypatch.setattr(Mesh, "_init_redis", lambda self, settings: None)
    monkeypatch.setattr(Mesh, "_init_blob_storage", lambda self, settings: None)
    monkeypatch.setattr(Mesh, "_init_nexus", lambda self: None)
    monkeypatch.setattr(Mesh, "_init_athena", lambda self, settings: None)
    mesh = Mesh(config={"p2p_enabled": False})
    requester = mesh.add(Peer, agent_id="requester")
    mesh.add(Analyst, agent_id="analyst-1")

    await mesh.start()
    try:
        sandbox = create_coder_sandbox(
            timeout=10,
            mesh_proxy=_AutoAgentMeshProxy(requester),
        )
        result = await sandbox.execute(
            "async def main():\n"
            "    return await mesh.delegate(\n"
            "        to='any', capability='analysis', task='Review Acme'\n"
            "    )\n"
        )
    finally:
        await mesh.stop()

    assert result["status"] == "success"
    assert result["data"]["output"] == "analysed: Review Acme"
