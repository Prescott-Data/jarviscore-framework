"""A provider that has registered atoms is reached only through atoms."""

import tempfile
from unittest.mock import MagicMock

import pytest

from jarviscore.execution.atom_contract import read_contract
from jarviscore.execution.code_registry import create_function_registry
from jarviscore.execution.coder_sandbox import create_coder_sandbox
from jarviscore.kernel.defaults.coder import CoderSubAgent

LIST = '''\
async def gmail_list_messages(query: str = "") -> dict:
    """List Gmail message ids."""
    response = await nexus_call("GET", "https://gmail.googleapis.com/gmail/v1/users/me/messages",
                                params={"q": query})
    return {"success": True, "ids": [m["id"] for m in response["json"]["messages"]]}
'''

BATCH = '''\
async def gmail_get_messages_batch(message_ids: list = None) -> dict:
    """Fetch metadata for several Gmail messages."""
    found = []
    for message_id in message_ids or []:
        response = await nexus_call(
            "GET", f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{message_id}")
        found.append(response["json"]["id"])
    return {"success": True, "found": found}

async def main():
    return await nexus_call("GET", "https://gmail.googleapis.com/gmail/v1/users/me/profile")
'''

SCRIPT = '''\
async def main():
    response = await nexus_call("GET", "https://gmail.googleapis.com/gmail/v1/users/me/messages")
    return response["json"]
'''

CALENDAR_SCRIPT = SCRIPT.replace("gmail.googleapis.com/gmail/v1/users/me/messages",
                                 "www.googleapis.com/calendar/v3/users/me/calendarList")


class Proxy:
    def __init__(self):
        self.calls = []

    async def call(self, connection_id, method, url, **kwargs):
        self.calls.append(url)
        return {"ok": True, "status_code": 200, "content": True, "body": "",
                "json": {"messages": [{"id": "m1"}], "id": url.rsplit("/", 1)[-1]}}

    def connection_handle(self, provider):
        return f"connection:{provider}"


@pytest.fixture
def coder(tmp_path):
    registry = create_function_registry(tempfile.mkdtemp(), seed=False)
    registry.register_function("gmail_list_messages", LIST, metadata={
        "system": "gmail", "description": "List messages", "capabilities": ["messages"],
    })
    proxy = Proxy()
    agent = CoderSubAgent(agent_id="c", llm_client=MagicMock(), code_registry=registry,
                          sandbox=create_coder_sandbox(workspace_dir=tmp_path, timeout=60,
                                                       nexus_call_proxy=proxy,
                                                       allow_unsafe_local_execution=True))
    agent._run_context = {"system": "gmail", "_nexus_provider": "gmail",
                          "_nexus_connection_id": "connection:gmail"}
    agent._atoms = {"gmail_list_messages": read_contract(
        LIST, system="gmail", expected_name="gmail_list_messages").atom}
    agent.proxy = proxy
    return agent


@pytest.mark.asyncio
async def test_a_script_cannot_reach_a_provider_that_has_atoms(coder):
    result = await coder._tool_execute_code(code=SCRIPT)

    assert result["status"] != "success"
    assert "gmail has registered atoms (gmail_list_messages)" in str(result.get("error"))
    assert coder.proxy.calls == []


@pytest.mark.asyncio
async def test_a_script_may_reach_a_provider_with_no_atoms_yet(coder):
    coder._run_context.update(_nexus_provider="google_calendar",
                              _nexus_connection_id="connection:google_calendar")

    result = await coder._tool_execute_code(code=CALENDAR_SCRIPT)

    assert result["status"] == "success", result
    assert coder.proxy.calls == ["https://www.googleapis.com/calendar/v3/users/me/calendarList"]


@pytest.mark.asyncio
async def test_an_offered_atom_reaches_its_own_provider(coder):
    result = await coder._atom_tool("gmail_list_messages")(query="newer_than:7d")

    assert result["status"] == "success", result
    assert result["output"]["data"]["ids"] == ["m1"]


@pytest.mark.asyncio
async def test_a_new_atom_is_proven_by_its_stated_call_not_the_agents_main(coder):
    candidate = coder._tool_write_code(code=BATCH, system="gmail", atom="gmail_get_messages_batch",
                                       call={"message_ids": ["a1", "a2"]})
    result = await coder._tool_execute_code(candidate_id=candidate["candidate_id"])

    assert result["status"] == "success", result
    assert result["output"]["data"]["found"] == ["a1", "a2"]
    assert all("/profile" not in url for url in coder.proxy.calls)

    coder._candidates[-1]["status"] = "success"
    registered = coder._tool_register_function(
        function_name="gmail_get_messages_batch", candidate_id=candidate["candidate_id"],
        system="gmail", description="Fetch several messages",
    )
    assert registered["status"] == "registered"
    assert "gmail_get_messages_batch" in coder._atoms
    assert coder._registered_atom_names("gmail") == ["gmail_get_messages_batch", "gmail_list_messages"]


def test_a_new_atom_cannot_replace_a_registered_one_or_act_on_the_world(coder):
    replaced = coder._tool_write_code(code=LIST, system="gmail", atom="gmail_list_messages", call={})
    acting = coder._tool_write_code(
        code='ATOM_POLICY = {"effect": "notify", "approval": "required", '
             '"idempotency_fields": ["to"], "consequence": "Sends mail."}\n'
             'async def gmail_send_note(to: str) -> dict:\n'
             '    """Send."""\n'
             '    return await nexus_call("POST", "https://gmail.googleapis.com/x", json={"to": to})\n',
        system="gmail", atom="gmail_send_note", call={"to": "a@example.com"},
    )

    assert replaced["semantic_error"] == "ATOM_ALREADY_REGISTERED"
    assert acting["semantic_error"] == "ATOM_PROOF_WOULD_ACT"


@pytest.mark.asyncio
async def test_atom_authority_does_not_reach_another_provider(coder):
    other = LIST.replace("gmail.googleapis.com/gmail/v1/users/me/messages",
                         "www.googleapis.com/drive/v3/files").replace(
        'nexus_call("GET"', 'nexus_call(provider="google_drive", method="GET", url=').replace(
        'url=, "https', 'url="https')
    coder.code_registry.register_function("google_drive_list_files", other.replace(
        "gmail_list_messages", "google_drive_list_files"), metadata={
        "system": "google_drive", "description": "List files", "capabilities": ["files"]})
    coder._callable_atoms_by_system.clear()
    coder.code_registry.get_function_code = lambda name, _code=other: _code

    result = await coder._atom_tool("gmail_list_messages")(query="")

    assert result["status"] != "success"
    assert "google_drive has registered atoms" in str(result.get("error"))


def test_an_atom_module_cannot_run_code_when_loaded():
    hidden = "import os\nLEAK = os.listdir('/')\n" + LIST
    annotated = LIST.replace('query: str = ""', 'query: __import__("os").getcwd() = ""')

    for source in (hidden, annotated):
        problems = read_contract(source, system="gmail", expected_name="gmail_list_messages").problems
        assert any("runs nothing at module level" in problem for problem in problems)
