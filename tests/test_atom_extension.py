"""An atom that runs but cannot do what the task needs is extended, not worked around."""

import tempfile
from unittest.mock import AsyncMock, MagicMock

import pytest

from jarviscore.execution.atom_contract import read_contract
from jarviscore.execution.code_registry import create_function_registry
from jarviscore.kernel.defaults.coder import CoderSubAgent

LIST_IDS = '''\
async def gmail_list_messages(query: str = "", max_results: int = 20) -> dict:
    """List message ids matching a Gmail query."""
    response = await nexus_call("GET", "https://gmail.googleapis.com/gmail/v1/users/me/messages",
                                params={"q": query, "maxResults": max_results})
    return {"success": True, "messages": response["json"].get("messages", [])}
'''

WITH_PAGING = '''\
async def gmail_list_messages(query: str = "", max_results: int = 20, page_token: str = "") -> dict:
    """List messages matching a Gmail query, with the token for the next page."""
    params = {"q": query, "maxResults": max_results}
    if page_token:
        params["pageToken"] = page_token
    response = await nexus_call("GET", "https://gmail.googleapis.com/gmail/v1/users/me/messages",
                                params=params)
    data = response["json"]
    return {"success": True, "messages": data.get("messages", []),
            "next_page_token": data.get("nextPageToken")}
'''

DROPS_QUERY = WITH_PAGING.replace('query: str = "", ', "").replace('"q": query, ', "")
NEW_REQUIRED = WITH_PAGING.replace(
    'query: str = "", max_results: int = 20, page_token: str = ""',
    'page_token: str, query: str = "", max_results: int = 20',
)

SEND = '''\
ATOM_POLICY = {"effect": "notify", "approval": "required",
               "idempotency_fields": ["to", "subject"], "consequence": "Sends one email."}

async def gmail_send_email(to: str, subject: str, body: str) -> dict:
    """Send one email."""
    return await nexus_call("POST", "https://gmail.googleapis.com/gmail/v1/users/me/messages/send",
                            json={"to": to, "subject": subject, "body": body})
'''


def coder_with(registry, source, name, system="gmail"):
    registry.register_function(name, source, metadata={
        "system": system, "description": "Gmail", "capabilities": ["messages"],
    })
    coder = CoderSubAgent(agent_id="c", llm_client=MagicMock(), sandbox=MagicMock(),
                          code_registry=registry)
    coder._run_context = {"system": system}
    coder._atoms = {name: read_contract(source, system=system, expected_name=name).atom}
    return coder


@pytest.mark.asyncio
async def test_a_working_atom_that_falls_short_is_extended_and_reoffered():
    with tempfile.TemporaryDirectory() as directory:
        registry = create_function_registry(directory, seed=False)
        coder = coder_with(registry, LIST_IDS, "gmail_list_messages")
        coder._record_atom_outcome("gmail_list_messages", {"status": "success"},
                                   params={"query": "newer_than:7d"})
        coder.sandbox.execute = AsyncMock(return_value={
            "status": "success", "output": {"success": True, "messages": [], "next_page_token": "p2"},
        })

        assert coder._tool_repair_atom("gmail_list_messages", WITH_PAGING)["semantic_error"] == (
            "ATOM_REPAIR_NOT_OBSERVED"
        )
        gap = "Returns only the first page; no way to reach later messages."
        inspected = coder._tool_inspect_atom_for_repair("gmail_list_messages", gap=gap)
        candidate = coder._tool_repair_atom("gmail_list_messages", WITH_PAGING, gap=gap)
        executed = await coder._tool_execute_code(candidate_id=candidate["candidate_id"])
        registered = coder._tool_register_function(
            function_name="gmail_list_messages", candidate_id=candidate["candidate_id"],
            system="gmail",
        )

        metadata = registry.get_function_metadata("gmail_list_messages")
        assert inspected["kind"] == "extension" and inspected["source"] == LIST_IDS
        assert executed["status"] == "success"
        assert "query='newer_than:7d'" in coder.sandbox.execute.await_args.args[0] or (
            "newer_than:7d" in coder.sandbox.execute.await_args.args[0]
        )
        assert registered["status"] == "registered"
        assert metadata["version"] == 2
        assert metadata["repair_failure"] == f"Extended: {gap}"
        assert registry.get_function_code("gmail_list_messages") == WITH_PAGING
        assert "page_token" in {p.name for p in coder._atoms["gmail_list_messages"].parameters}


@pytest.mark.parametrize("source, reason", [
    (DROPS_QUERY, "must keep every existing parameter"),
    (NEW_REQUIRED, "need defaults"),
])
def test_an_extension_cannot_break_existing_callers(source, reason):
    with tempfile.TemporaryDirectory() as directory:
        registry = create_function_registry(directory, seed=False)
        coder = coder_with(registry, LIST_IDS, "gmail_list_messages")
        coder._record_atom_outcome("gmail_list_messages", {"status": "success"}, params={})

        result = coder._tool_repair_atom("gmail_list_messages", source, gap="Needs paging.")

        assert result["semantic_error"] == "ATOM_EXTENSION_NOT_ADDITIVE"
        assert reason in result["error"]


def test_an_atom_with_real_world_effects_is_never_extended_by_rerunning_it():
    with tempfile.TemporaryDirectory() as directory:
        registry = create_function_registry(directory, seed=False)
        coder = coder_with(registry, SEND, "gmail_send_email")
        coder._record_atom_outcome("gmail_send_email", {"status": "success"},
                                   params={"to": "a@example.com", "subject": "Hi", "body": "x"})

        result = coder._tool_repair_atom(
            "gmail_send_email", SEND.replace("Send one email.", "Send one email, with cc."),
            gap="Cannot cc anyone.",
        )

        assert result["semantic_error"] == "ATOM_EXTENSION_NOT_ADDITIVE"
        assert "Only read atoms" in result["error"]
