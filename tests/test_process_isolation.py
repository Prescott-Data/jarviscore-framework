import os

import pytest

from jarviscore.execution.coder_sandbox import create_coder_sandbox


class RecordingProxy:
    def __init__(self):
        self.calls = []

    async def call(self, connection_id, method, url, **kwargs):
        self.calls.append((connection_id, method, url, kwargs))
        return {"ok": True, "status_code": 200, "body": "ok"}

    def connection_handle(self, provider):
        return f"connection:{provider}"


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
async def test_provider_access_crosses_the_parent_rpc_only():
    proxy = RecordingProxy()
    sandbox = create_coder_sandbox(timeout=10, nexus_call_proxy=proxy)

    result = await sandbox.execute(
        "async def main():\n"
        "    return await nexus_call('POST', 'https://example.invalid/items', json={'x': 1})\n",
        context={"_nexus_connection_id": "demo", "_nexus_provider": "demo"},
    )

    assert result["status"] == "success"
    assert result["data"]["status_code"] == 200
    assert proxy.calls == [
        ("demo", "POST", "https://example.invalid/items", {"json": {"x": 1}})
    ]


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
