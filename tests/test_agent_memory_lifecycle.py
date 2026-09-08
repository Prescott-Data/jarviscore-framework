"""The agent is the memory lifecycle: it decides what deserves to persist.

Every intermediate thought used to be written to cross-session memory, then the
last fifteen were dumped into the next run under INPUT CONTEXT beside the task.
A mid-run diagnosis of a bug outlived the bug and returned as a premise, and an
agent on a fixed system opened with "prior attempts showed this is blocked".
"""

import pytest

from jarviscore.context.context_manager import ContextManager
from jarviscore.kernel.state import KernelState
from jarviscore.kernel.subagent import BaseSubAgent
from jarviscore.memory.unified import UnifiedMemory


class FakeAthena:
    def __init__(self):
        self.thoughts, self.actions, self.observations = [], [], []
        self.searched = []

    async def record_thought(self, content, metadata=None):
        self.thoughts.append(content)

    async def record_action(self, content, metadata=None):
        self.actions.append(content)

    async def record_observation(self, content, metadata=None):
        self.observations.append((content, metadata or {}))

    async def search(self, query, limit=5):
        self.searched.append(query)
        return [{"content": "Drive holds 100 files", "similarity_score": 0.91}]


@pytest.fixture
def memory():
    m = UnifiedMemory.__new__(UnifiedMemory)
    m.working = None
    m.episodic = None
    m.ltm = None
    m._redis = None
    m._wf, m._step = "wf", "step"
    athena = FakeAthena()

    async def get():
        return athena

    m._get_athena_memory = get
    m._athena = athena
    return m


# ── Writing ───────────────────────────────────────────────────────────────────

async def test_a_turn_is_not_a_memory(memory):
    """Reasoning about a failing call must not outlive the failure."""
    await memory.log_turn("t1", thought="Drive is blocked by host rules", action="execute_code", result="HostNotAllowed")
    assert memory._athena.thoughts == []
    assert memory._athena.actions == []


async def test_the_agent_decides_what_persists(memory):
    kept = await memory.remember("Handled Gmail messages 101, 102, 103", kind="progress")
    assert kept is True
    content, meta = memory._athena.observations[0]
    assert "101, 102, 103" in content
    assert meta["event"] == "remembered"
    assert meta["kind"] == "progress"


async def test_remember_says_so_when_nothing_can_be_kept(memory):
    async def nothing():
        return None

    memory._get_athena_memory = nothing
    assert await memory.remember("anything") is False


# ── Reading ───────────────────────────────────────────────────────────────────

async def test_recall_is_a_question_about_this_task(memory):
    results = await memory.recall("list Google Drive files")
    assert memory._athena.searched == ["list Google Drive files"]
    assert results[0]["content"] == "Drive holds 100 files"


def test_recalled_memory_is_labelled_as_the_past():
    block = ContextManager._build_recalled_block([
        {"content": "Drive calls were blocked", "similarity_score": 0.8, "timestamp": "2026-09-07"},
    ])
    assert block.startswith("## FROM EARLIER SESSIONS")
    assert "hypothesis to re-test" in block
    assert "Drive calls were blocked (2026-09-07) [relevance 0.80]" in block


def test_recalled_memory_never_lands_in_input_context():
    """Under INPUT CONTEXT it read as part of the task."""
    cm = ContextManager()
    state = KernelState(
        workflow_id="wf", step_id="s", task="list files", role="coder",
        context={"_recalled": [{"content": "stale diagnosis"}], "_athena_memory": {"x": 1}, "_ltm_summary": "old"},
    )
    rendered = cm.build_context(state)
    input_block = rendered.split("## INPUT CONTEXT")[1].split("##")[0] if "## INPUT CONTEXT" in rendered else ""
    assert "_recalled" not in input_block
    assert "_athena_memory" not in input_block
    assert "_ltm_summary" not in input_block
    assert "## FROM EARLIER SESSIONS" in rendered


def test_nothing_recalled_renders_no_block():
    assert ContextManager._build_recalled_block([]) == ""


# ── The agent's lever ─────────────────────────────────────────────────────────

class _Agent(BaseSubAgent):
    def setup_tools(self):
        pass

    def get_system_prompt(self):
        return ""


@pytest.fixture
def agent(memory):
    a = _Agent(agent_id="a1", role="coder", llm_client=None)
    a._current_memory = memory
    return a


def test_every_role_has_remember_and_recall(agent):
    assert "remember" in agent.tool_names
    assert "recall" in agent.tool_names


async def test_remember_tool_persists_a_fact(agent, memory):
    result = await agent._tool_remember("Funder contact: alice@acme.example", kind="fact")
    assert result["status"] == "success"
    assert memory._athena.observations[0][0] == "Funder contact: alice@acme.example"


async def test_remember_tool_refuses_emptiness(agent):
    assert (await agent._tool_remember("   "))["status"] == "error"


async def test_remember_tool_is_honest_without_memory(agent):
    agent._current_memory = None
    result = await agent._tool_remember("something")
    assert result["semantic_error"] == "NO_MEMORY"


async def test_recall_tool_asks_the_question(agent, memory):
    result = await agent._tool_recall("Drive")
    assert result["count"] == 1
    assert memory._athena.searched == ["Drive"]
