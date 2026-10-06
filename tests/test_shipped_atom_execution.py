from unittest.mock import AsyncMock

import pytest

from jarviscore.execution.atom_contract import (
    SHIPPED_ATOMS_DIR,
    invocation,
    read_contract,
    shipped_source,
)
from jarviscore.execution.coder_sandbox import BashPermissionError, create_coder_sandbox
from jarviscore.kernel.defaults.coder import CoderSubAgent

GMAIL_LIST = (SHIPPED_ATOMS_DIR / "gmail" / "gmail_list_messages.py").read_text(encoding="utf-8")

ECHO_SOURCE = '''
async def demo_search_items(query: str = "") -> dict:
    """Search items."""
    return {"query": query}
'''


class Proxy:
    def __init__(self):
        self.calls = []

    async def call(self, connection_id, method, url, **kwargs):
        self.calls.append((connection_id, method, url, kwargs))
        return {"ok": True, "status_code": 200, "content": True, "body": "",
                "json": {"messages": [], "resultSizeEstimate": 0}}

    def connection_handle(self, provider):
        return f"connection:{provider}"


class Registry:
    def __init__(self, code):
        self.code = code

    def get_function_code(self, name):
        return self.code

    def update_execution_stats(self, *args, **kwargs):
        pass


def gmail_list_atom():
    return read_contract(GMAIL_LIST, system="gmail", expected_name="gmail_list_messages").atom


@pytest.mark.asyncio
async def test_atom_arguments_reach_the_atom_as_data():
    atom = read_contract(ECHO_SOURCE, system="demo", expected_name="demo_search_items").atom
    hostile = "x'); import os; os.system('touch /tmp/pwned') #"
    namespace = {}

    exec(f"{ECHO_SOURCE}\n\n{invocation(atom, {'query': hostile})}", namespace)

    assert await namespace["main"]() == {"query": hostile}
    with pytest.raises(ValueError):
        invocation(atom, {"query='' or __import__('os').getcwd(), query": "x"})


@pytest.mark.asyncio
async def test_a_shipped_atom_runs_without_the_unsafe_opt_in(tmp_path):
    proxy = Proxy()
    sandbox = create_coder_sandbox(workspace_dir=tmp_path, timeout=20, nexus_call_proxy=proxy)

    result = await sandbox.execute_shipped_atom(
        gmail_list_atom(), {"query": "from:school", "max_results": 5},
        context={"_nexus_connection_id": "gmail-1", "_nexus_provider": "gmail"},
    )

    assert result["status"] == "success"
    assert [(call[0], call[1]) for call in proxy.calls] == [("gmail-1", "GET")]
    assert proxy.calls[0][3]["params"] == {"maxResults": 5, "q": "from:school"}


@pytest.mark.asyncio
async def test_model_written_code_needs_confinement_or_opt_in(tmp_path, monkeypatch):
    import jarviscore.execution.isolation as isolation

    monkeypatch.setattr(isolation, "confinement_unavailable_reason", lambda: "bwrap: no namespaces")
    sandbox = create_coder_sandbox(workspace_dir=tmp_path, timeout=20)
    unshipped = read_contract(ECHO_SOURCE, system="demo", expected_name="demo_search_items").atom

    with pytest.raises(BashPermissionError, match="bwrap: no namespaces"):
        await sandbox.execute("async def main():\n    return 1\n")
    with pytest.raises(BashPermissionError):
        await sandbox.execute_shipped_atom(unshipped, {})
    with pytest.raises(BashPermissionError):
        await sandbox.execute_shipped_atom(["gmail_list_messages", "gmail"], {})


@pytest.mark.asyncio
async def test_a_refused_run_is_a_tool_result_the_agent_can_work_around(tmp_path, monkeypatch):
    import jarviscore.execution.isolation as isolation

    monkeypatch.setattr(isolation, "confinement_unavailable_reason", lambda: "bwrap: no namespaces")
    agent = CoderSubAgent.__new__(CoderSubAgent)
    agent.sandbox = create_coder_sandbox(workspace_dir=tmp_path, timeout=20)
    agent.code_registry = None
    agent._run_context = {}

    result = await agent._tool_execute_code(code="async def main():\n    return 1\n")

    assert result["status"] == "error"
    assert result["semantic_error"] == "CODE_EXECUTION_UNAVAILABLE"
    assert "other tools" in result["error"]


@pytest.mark.asyncio
@pytest.mark.parametrize("registry_code, shipped", [
    (GMAIL_LIST, True),
    (GMAIL_LIST + "\n# changed after shipping\n", False),
])
async def test_only_code_identical_to_the_shipped_atom_takes_the_shipped_path(
    registry_code, shipped
):
    atom = gmail_list_atom()
    assert shipped_source(atom) == GMAIL_LIST
    agent = CoderSubAgent.__new__(CoderSubAgent)
    agent._atoms = {atom.name: atom}
    agent._run_context = {"workflow_id": "wf", "step_id": "step"}
    agent.code_registry = Registry(registry_code)
    agent.redis_store = None
    agent._connection_handle = lambda system: f"connection:{system}"
    agent._tool_execute_code = AsyncMock(return_value={"status": "success"})

    await agent._atom_tool(atom.name)(query="from:school")

    passed = agent._tool_execute_code.await_args.kwargs["_shipped_atom"]
    assert passed == ((atom, {"query": "from:school"}) if shipped else None)
