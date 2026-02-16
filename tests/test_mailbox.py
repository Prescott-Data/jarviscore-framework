"""
Tests for Phase 4: Natural Language Mailboxes

What these tests prove:
- MailboxManager wraps Redis primitives with proper sender envelopes
- Workflow context (workflow_id, step_id) survives roundtrip in envelopes
- Capability-based routing finds agents via Mesh.get_agents_by_capability()
- Role-based routing finds agents via Mesh._agent_registry
- Broadcast reaches all mesh agents except the sender
- format_for_context produces LLM-ready markdown with timestamp/sender
- Sensitive data (passwords, API keys, tokens) is scrubbed before LLM sees it
- Scrubbing can be disabled for trusted internal contexts
- Agent base class has mailbox attribute ready for Phase 9 injection

WHY THIS MATTERS FOR THE FRAMEWORK:
The kernel (Phase 6) ingests mailbox messages every OODA loop turn.
Without mailbox:
- Agents can't collaborate asynchronously during workflows
- No capability-based "send to whoever can do X" routing
- No broadcast for mesh-wide coordination events
- No security scrubbing before messages reach LLM context
- Kernel has no way to check for peer messages between turns

The Redis transport (Phase 1) handles durability and ordering.
This layer handles addressing, routing, and LLM presentation.
"""

import time

import pytest

from jarviscore.core.agent import Agent
from jarviscore.mailbox import MailboxManager
from jarviscore.testing import MockRedisContextStore
from jarviscore.testing.mocks import MockMesh


# ─────────────────────────────────────────────────────────────────
# Test Agents (reusable across test classes)
# ─────────────────────────────────────────────────────────────────

class AnalystAgent(Agent):
    role = "analyst"
    capabilities = ["analysis", "data_processing"]

    async def execute_task(self, task):
        return {"status": "success"}


class ScraperAgent(Agent):
    role = "scraper"
    capabilities = ["web_scraping", "data_extraction"]

    async def execute_task(self, task):
        return {"status": "success"}


class WorkerAgent(Agent):
    role = "worker"
    capabilities = ["processing"]

    async def execute_task(self, task):
        return {"status": "success"}


# ─────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────

@pytest.fixture
def store():
    """Fresh Redis store (fakeredis) for each test."""
    return MockRedisContextStore()


@pytest.fixture
def mesh_two_agents():
    """Mesh with analyst + scraper agents."""
    mesh = MockMesh()
    mesh.add(AnalystAgent, agent_id="analyst-001")
    mesh.add(ScraperAgent, agent_id="scraper-001")
    return mesh


@pytest.fixture
def mesh_three_workers():
    """Mesh with three worker agents."""
    mesh = MockMesh()
    mesh.add(WorkerAgent, agent_id="worker-1")
    mesh.add(WorkerAgent, agent_id="worker-2")
    mesh.add(WorkerAgent, agent_id="worker-3")
    return mesh


# ═════════════════════════════════════════════════════════════════
# TEST CLASS 1: Direct Agent-to-Agent Messaging
# ═════════════════════════════════════════════════════════════════

class TestMailboxManagerDirect:
    """
    Direct agent-to-agent messaging using agent IDs.

    This is the foundation — send() wraps Redis primitives with
    envelopes containing sender metadata. read() flattens the Redis
    wrapper so callers get clean dicts with sender, message, timestamp.
    """

    def test_send_and_read(self, store):
        """Send a message, read it back with envelope metadata."""
        sender = MailboxManager("agent-a", store)
        receiver = MailboxManager("agent-b", store)

        sender.send("agent-b", {"query": "What's the status?"})

        messages = receiver.read()
        assert len(messages) == 1
        assert messages[0]["sender"] == "agent-a"
        assert messages[0]["message"]["query"] == "What's the status?"
        assert "timestamp" in messages[0]
        assert messages[0]["timestamp"] > 0

    def test_send_with_workflow_context(self, store):
        """Workflow context is preserved in message envelope."""
        sender = MailboxManager("agent-a", store)
        receiver = MailboxManager("agent-b", store)

        sender.send(
            "agent-b",
            {"task": "analyze"},
            workflow_id="wf-123",
            step_id="step-research",
        )

        messages = receiver.read()
        assert len(messages) == 1
        assert messages[0]["workflow_id"] == "wf-123"
        assert messages[0]["step_id"] == "step-research"

    def test_send_with_optional_context(self, store):
        """Extra context dict is attached to the envelope."""
        sender = MailboxManager("agent-a", store)
        receiver = MailboxManager("agent-b", store)

        sender.send(
            "agent-b",
            {"task": "check"},
            context={"priority": "high", "source": "kernel"},
        )

        messages = receiver.read()
        assert messages[0]["context"]["priority"] == "high"
        assert messages[0]["context"]["source"] == "kernel"

    def test_peek_then_read(self, store):
        """Peek is non-destructive, read consumes."""
        sender = MailboxManager("agent-a", store)
        receiver = MailboxManager("agent-b", store)

        sender.send("agent-b", {"text": "hello"})

        # Peek twice — same message both times
        peek1 = receiver.peek()
        peek2 = receiver.peek()
        assert len(peek1) == 1
        assert len(peek2) == 1
        assert peek1[0]["message"]["text"] == "hello"

        # Read consumes
        read = receiver.read()
        assert len(read) == 1
        assert read[0]["message"]["text"] == "hello"

        # After read — empty
        assert receiver.peek() == []
        assert receiver.read() == []

    def test_fifo_ordering_preserved(self, store):
        """Messages are read in the order they were sent."""
        sender = MailboxManager("agent-a", store)
        receiver = MailboxManager("agent-b", store)

        sender.send("agent-b", {"seq": 1})
        sender.send("agent-b", {"seq": 2})
        sender.send("agent-b", {"seq": 3})

        messages = receiver.read(max_messages=10)
        assert [m["message"]["seq"] for m in messages] == [1, 2, 3]

    def test_omitted_optional_fields_not_in_envelope(self, store):
        """Optional fields (workflow_id, step_id, context) are omitted
        when not provided, not set to None."""
        sender = MailboxManager("agent-a", store)
        receiver = MailboxManager("agent-b", store)

        sender.send("agent-b", {"text": "simple"})

        messages = receiver.read()
        assert "workflow_id" not in messages[0]
        assert "step_id" not in messages[0]
        assert "context" not in messages[0]


# ═════════════════════════════════════════════════════════════════
# TEST CLASS 2: Capability-Based Routing
# ═════════════════════════════════════════════════════════════════

class TestCapabilityRouting:
    """
    Capability-based routing enables "send to anyone who can do X"
    without knowing agent IDs. Uses Mesh.get_agents_by_capability()
    — the same index used by StepClaimer and WorkflowEngine.
    """

    def test_send_by_capability(self, store, mesh_two_agents):
        """Send to first agent with a capability."""
        analyst = MailboxManager("analyst-001", store)

        result = analyst.send_by_capability(
            "web_scraping",
            {"url": "https://example.com"},
            mesh_two_agents,
        )

        assert result is True

        # Scraper receives the message
        scraper = MailboxManager("scraper-001", store)
        messages = scraper.read()
        assert len(messages) == 1
        assert messages[0]["sender"] == "analyst-001"
        assert messages[0]["message"]["url"] == "https://example.com"

    def test_send_by_capability_not_found(self, store, mesh_two_agents):
        """Returns False when no agent has the capability."""
        manager = MailboxManager("agent-x", store)

        result = manager.send_by_capability(
            "nonexistent_capability",
            {"task": "impossible"},
            mesh_two_agents,
        )

        assert result is False

    def test_send_by_capability_with_workflow_context(
        self, store, mesh_two_agents
    ):
        """Workflow context is forwarded through capability routing."""
        analyst = MailboxManager("analyst-001", store)

        analyst.send_by_capability(
            "web_scraping",
            {"url": "https://example.com"},
            mesh_two_agents,
            workflow_id="wf-99",
            step_id="step-3",
        )

        scraper = MailboxManager("scraper-001", store)
        messages = scraper.read()
        assert messages[0]["workflow_id"] == "wf-99"
        assert messages[0]["step_id"] == "step-3"


# ═════════════════════════════════════════════════════════════════
# TEST CLASS 3: Role-Based Routing
# ═════════════════════════════════════════════════════════════════

class TestRoleRouting:
    """
    Role-based routing sends to "the analyst" without knowing
    the agent_id. Uses Mesh._agent_registry — same index used
    by Mesh.get_agent() and _find_agent_for_step().
    """

    def test_send_by_role(self, store, mesh_two_agents):
        """Send to first agent with a role."""
        scraper = MailboxManager("scraper-001", store)

        result = scraper.send_by_role(
            "analyst",
            {"question": "What patterns do you see?"},
            mesh_two_agents,
        )

        assert result is True

        analyst = MailboxManager("analyst-001", store)
        messages = analyst.read()
        assert len(messages) == 1
        assert messages[0]["sender"] == "scraper-001"
        assert messages[0]["message"]["question"] == "What patterns do you see?"

    def test_send_by_role_not_found(self, store, mesh_two_agents):
        """Returns False when no agent has the role."""
        manager = MailboxManager("agent-x", store)

        result = manager.send_by_role(
            "nonexistent_role",
            {"task": "impossible"},
            mesh_two_agents,
        )

        assert result is False


# ═════════════════════════════════════════════════════════════════
# TEST CLASS 4: Broadcast
# ═════════════════════════════════════════════════════════════════

class TestBroadcast:
    """
    Broadcast enables mesh-wide notifications (e.g., "workflow started").
    Useful for coordination without knowing specific agent IDs.
    Sender is excluded — you don't broadcast to yourself.
    """

    def test_broadcast_to_all(self, store, mesh_three_workers):
        """Broadcast reaches all agents except sender."""
        # External coordinator broadcasts
        coordinator = MailboxManager("coordinator", store)
        count = coordinator.broadcast(
            {"event": "workflow_started", "workflow_id": "wf-1"},
            mesh_three_workers,
        )

        assert count == 3

        # Each worker received the broadcast
        for wid in ["worker-1", "worker-2", "worker-3"]:
            worker = MailboxManager(wid, store)
            messages = worker.read()
            assert len(messages) == 1
            assert messages[0]["message"]["event"] == "workflow_started"
            assert messages[0]["sender"] == "coordinator"

    def test_broadcast_excludes_sender(self, store, mesh_three_workers):
        """Sender doesn't receive their own broadcast."""
        worker1 = MailboxManager("worker-1", store)
        count = worker1.broadcast(
            {"event": "status_update"},
            mesh_three_workers,
        )

        # worker-1 is in the mesh, so only worker-2 and worker-3 receive
        assert count == 2

        # worker-1's mailbox is empty
        assert worker1.read() == []

    def test_broadcast_returns_count(self, store, mesh_two_agents):
        """Returns correct count of recipients."""
        manager = MailboxManager("external", store)
        count = manager.broadcast(
            {"event": "ping"},
            mesh_two_agents,
        )

        assert count == 2  # analyst + scraper


# ═════════════════════════════════════════════════════════════════
# TEST CLASS 5: Context Formatting for LLM Injection
# ═════════════════════════════════════════════════════════════════

class TestContextFormatting:
    """
    Context formatting converts mailbox messages into markdown for
    LLM scratchpad injection. This is how agents "see" their mailbox
    in the kernel's OODA loop (Phase 6).

    Security: scrubs sensitive data (passwords, API keys, tokens)
    before the LLM sees it — using the same scrub_sensitive() from
    Phase 2's distillation module.
    """

    def test_format_empty_returns_empty_string(self, store):
        """Empty mailbox produces empty string, not headers."""
        manager = MailboxManager("test", store)
        assert manager.format_for_context([]) == ""

    def test_format_includes_sender_and_content(self, store):
        """Messages are formatted with sender and payload."""
        manager = MailboxManager("test", store)

        messages = [
            {
                "sender": "analyst-001",
                "message": {"finding": "API uses OAuth2"},
                "timestamp": 1700000000.0,
            },
        ]

        formatted = manager.format_for_context(messages)

        assert "## MAILBOX MESSAGES" in formatted
        assert "analyst-001" in formatted
        assert "API uses OAuth2" in formatted

    def test_format_includes_workflow_context(self, store):
        """Workflow/step context appears in header when present."""
        manager = MailboxManager("test", store)

        messages = [
            {
                "sender": "agent-a",
                "message": {"data": "test"},
                "timestamp": 1700000000.0,
                "workflow_id": "wf-42",
                "step_id": "step-research",
            },
        ]

        formatted = manager.format_for_context(messages)
        assert "wf-42" in formatted
        assert "step-research" in formatted

    def test_format_scrubs_sensitive_data(self, store):
        """Passwords, API keys, tokens are redacted before LLM sees them."""
        manager = MailboxManager("test", store)

        messages = [
            {
                "sender": "db-agent",
                "message": {
                    "db_host": "postgres.internal",
                    "password": "super_secret_123",
                    "api_key": "sk-abc123xyz",
                    "safe_data": "this is fine",
                },
                "timestamp": 1700000000.0,
            },
        ]

        formatted = manager.format_for_context(messages, scrub=True)

        # Safe data passes through
        assert "postgres.internal" in formatted
        assert "this is fine" in formatted

        # Sensitive data is redacted
        assert "super_secret_123" not in formatted
        assert "sk-abc123xyz" not in formatted
        assert "[REDACTED]" in formatted

    def test_format_no_scrub_when_disabled(self, store):
        """Scrubbing can be disabled for trusted internal contexts."""
        manager = MailboxManager("test", store)

        messages = [
            {
                "sender": "agent-a",
                "message": {"api_key": "sk-test-key"},
                "timestamp": 1700000000.0,
            },
        ]

        formatted = manager.format_for_context(messages, scrub=False)

        assert "sk-test-key" in formatted
        assert "[REDACTED]" not in formatted


# ═════════════════════════════════════════════════════════════════
# TEST CLASS 6: Agent Base Class Integration
# ═════════════════════════════════════════════════════════════════

class TestAgentMailboxAttribute:
    """
    Agent base class has mailbox attribute (set to None initially).
    Mesh will inject MailboxManager during start() in Phase 9.

    This is the same pattern as agent.peers (PeerClient, set to None,
    injected by Mesh._inject_peer_clients() during start()).
    """

    def test_agent_has_mailbox_attribute(self):
        """Agent instances have mailbox attribute, defaults to None."""
        agent = AnalystAgent(agent_id="test-analyst")
        assert hasattr(agent, "mailbox")
        assert agent.mailbox is None

    def test_mailbox_can_be_assigned(self, store):
        """MailboxManager can be assigned to agent.mailbox."""
        agent = AnalystAgent(agent_id="test-analyst")
        agent.mailbox = MailboxManager(agent.agent_id, store)

        assert agent.mailbox is not None
        assert agent.mailbox.agent_id == "test-analyst"

    def test_mailbox_coexists_with_peers(self):
        """Mailbox and peers are independent attributes."""
        agent = AnalystAgent(agent_id="test-analyst")
        assert agent.mailbox is None
        assert agent.peers is None
        # Both can be set independently
        agent.mailbox = "mock_mailbox"
        assert agent.mailbox == "mock_mailbox"
        assert agent.peers is None
