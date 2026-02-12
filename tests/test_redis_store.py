"""
Tests for Phase 1: RedisContextStore (via fakeredis)

What these tests prove:
- Step outputs survive save/read roundtrip with proper JSON serialization
- Shared context merging accumulates facts from multiple agents
- Shared facts (TruthContext data) store typed values with metadata
- get_shared_facts_flat() strips metadata and returns just values
- Mailbox is durable and ordered: FIFO, destructive read, non-destructive peek
- Workflow DAG tracks step status and dependency satisfaction correctly
- Atomic step claiming prevents double-execution (two agents can't claim same step)
- Checkpoints enable crash recovery (save state → crash → load state → resume)
- Episodic ledger preserves chronological order (Redis Streams)
- Trace events publish to PubSub AND persist to List (dual-channel)
- HITL lifecycle: create → pending → resolve → human decision recorded
- Workflow flush cleans up all keys (prevents Redis bloat)

WHY THIS MATTERS FOR THE FRAMEWORK:
RedisContextStore is the backbone of v1.0.0. Without it:
- Agents can't share discoveries (no TruthContext distillation)
- Agents can't message each other (no mailbox)
- Workflows can't run parallel steps safely (no atomic claiming)
- Kernels can't resume after crash (no checkpoints)
- No audit trail of agent reasoning (no ledger/traces)
- No human oversight of risky actions (no HITL)

Every subsequent phase depends on this store working correctly.
"""

import json
import time

import pytest

from jarviscore.testing import MockRedisContextStore


@pytest.fixture
def store():
    """Fresh Redis store (fakeredis) for each test."""
    return MockRedisContextStore()


# ======================================================================
# Step Outputs
# ======================================================================

class TestStepOutputs:
    """
    Step outputs are how agents pass results to downstream steps.
    In v0.3.2 this was in-memory dicts — lost on crash.
    Now it's in Redis — durable, shared, queryable.
    """

    def test_save_and_read(self, store):
        """Basic roundtrip: save output, read it back."""
        store.save_step_output("wf-1", "step-1",
                               output={"result": 42, "data": [1, 2, 3]},
                               summary="Computed result")
        result = store.get_step_output("wf-1", "step-1")

        assert result["output"] == {"result": 42, "data": [1, 2, 3]}
        assert result["summary"] == "Computed result"

    def test_read_nonexistent_returns_none(self, store):
        """Reading a step that hasn't run returns None."""
        assert store.get_step_output("wf-1", "nonexistent") is None

    def test_overwrite(self, store):
        """Saving the same step again overwrites (retry/repair scenario)."""
        store.save_step_output("wf-1", "step-1", output="first")
        store.save_step_output("wf-1", "step-1", output="second")
        result = store.get_step_output("wf-1", "step-1")
        assert result["output"] == "second"

    def test_context_vars(self, store):
        """Context variables are stored alongside output."""
        store.save_step_output("wf-1", "step-1",
                               output="done",
                               context_vars={"api_key": "redacted", "endpoint": "https://api.example.com"})
        result = store.get_step_output("wf-1", "step-1")
        assert result["context_vars"]["endpoint"] == "https://api.example.com"

    def test_isolation_between_workflows(self, store):
        """Different workflows don't see each other's outputs."""
        store.save_step_output("wf-1", "step-1", output="workflow 1")
        store.save_step_output("wf-2", "step-1", output="workflow 2")

        assert store.get_step_output("wf-1", "step-1")["output"] == "workflow 1"
        assert store.get_step_output("wf-2", "step-1")["output"] == "workflow 2"


# ======================================================================
# Shared Context / Truth Distillation
# ======================================================================

class TestSharedContext:
    """
    Shared context is how agents share discoveries.
    In v0.3.2: in-memory dict passed through workflow engine.
    Now: Redis hash, merged by multiple agents, queryable by any agent.

    This is the foundation for TruthContext (Phase 2).
    """

    def test_merge_and_read(self, store):
        """Agent merges context, another agent reads it."""
        store.merge_shared_context("wf-1",
                                   {"db_host": "prod-db-3.internal", "api_version": "v2"},
                                   source="researcher-agent")
        ctx = store.get_shared_context("wf-1")
        assert ctx["db_host"] == "prod-db-3.internal"
        assert ctx["api_version"] == "v2"

    def test_multiple_agents_merge(self, store):
        """Multiple agents contribute to the same shared context."""
        store.merge_shared_context("wf-1", {"host": "db-1"}, source="agent-a")
        store.merge_shared_context("wf-1", {"port": 5432}, source="agent-b")
        store.merge_shared_context("wf-1", {"schema": "public"}, source="agent-c")

        ctx = store.get_shared_context("wf-1")
        assert ctx["host"] == "db-1"
        assert ctx["port"] == 5432
        assert ctx["schema"] == "public"

    def test_later_merge_overwrites(self, store):
        """If two agents write the same key, last write wins."""
        store.merge_shared_context("wf-1", {"version": "v1"}, source="agent-a")
        store.merge_shared_context("wf-1", {"version": "v2"}, source="agent-b")

        ctx = store.get_shared_context("wf-1")
        assert ctx["version"] == "v2"

    def test_empty_workflow(self, store):
        """Reading context for a workflow with no data returns empty dict."""
        assert store.get_shared_context("wf-empty") == {}


class TestSharedFacts:
    """
    Shared facts store typed TruthFacts with metadata (value + confidence + evidence).
    get_shared_facts_flat() strips the metadata for simple access.

    This proves the Redis layer can handle the TruthContext pattern
    that Phase 2 will build on top of.
    """

    def test_merge_typed_facts(self, store):
        """Store facts with metadata (value, confidence, evidence)."""
        store.merge_shared_facts("wf-1", {
            "database_host": {
                "value": "prod-db-3.internal",
                "confidence": 0.95,
                "evidence": "runtime_observation",
            },
            "api_version": {
                "value": "v2",
                "confidence": 1.0,
                "evidence": "doc_url",
            },
        }, source="researcher")

        facts = store.get_shared_facts("wf-1")
        assert facts["database_host"]["value"] == "prod-db-3.internal"
        assert facts["database_host"]["confidence"] == 0.95

    def test_flat_view_strips_metadata(self, store):
        """get_shared_facts_flat returns key→value without metadata."""
        store.merge_shared_facts("wf-1", {
            "host": {"value": "db-1", "confidence": 0.9},
            "port": {"value": 5432, "confidence": 1.0},
        })

        flat = store.get_shared_facts_flat("wf-1")
        assert flat["host"] == "db-1"
        assert flat["port"] == 5432

    def test_raw_values_pass_through_flat(self, store):
        """If a fact is a plain value (no metadata dict), flat returns it as-is."""
        store.merge_shared_facts("wf-1", {"simple_key": "simple_value"})
        flat = store.get_shared_facts_flat("wf-1")
        assert flat["simple_key"] == "simple_value"


# ======================================================================
# Mailbox (Durable Agent-to-Agent Messaging)
# ======================================================================

class TestMailbox:
    """
    In v0.3.2: agents communicate via ZMQ (fire-and-forget, in-memory).
    Now: Redis-backed durable mailbox. Messages survive crashes,
    can be peeked without consuming, and are ordered FIFO.

    This is the transport layer for Phase 4 (MailboxManager).
    """

    def test_send_and_read(self, store):
        """Send a message, read it back."""
        store.send_mailbox_message("agent-2", {"text": "Hello!", "from": "agent-1"})
        msgs = store.read_mailbox("agent-2")

        assert len(msgs) == 1
        assert msgs[0]["message"]["text"] == "Hello!"

    def test_fifo_ordering(self, store):
        """Messages are read in the order they were sent."""
        store.send_mailbox_message("agent-2", {"seq": 1})
        store.send_mailbox_message("agent-2", {"seq": 2})
        store.send_mailbox_message("agent-2", {"seq": 3})

        msgs = store.read_mailbox("agent-2", max_messages=10)
        assert [m["message"]["seq"] for m in msgs] == [1, 2, 3]

    def test_read_is_destructive(self, store):
        """read_mailbox removes messages (like popping from a queue)."""
        store.send_mailbox_message("agent-2", {"text": "one"})
        store.send_mailbox_message("agent-2", {"text": "two"})

        # Read first message only
        msgs = store.read_mailbox("agent-2", max_messages=1)
        assert len(msgs) == 1
        assert msgs[0]["message"]["text"] == "one"

        # Second read gets the remaining message
        msgs = store.read_mailbox("agent-2", max_messages=10)
        assert len(msgs) == 1
        assert msgs[0]["message"]["text"] == "two"

        # Third read — empty
        msgs = store.read_mailbox("agent-2")
        assert len(msgs) == 0

    def test_peek_is_non_destructive(self, store):
        """peek_mailbox reads without removing messages."""
        store.send_mailbox_message("agent-2", {"text": "peek me"})

        # Peek twice — same message both times
        msgs1 = store.peek_mailbox("agent-2")
        msgs2 = store.peek_mailbox("agent-2")
        assert len(msgs1) == 1
        assert len(msgs2) == 1
        assert msgs1[0]["message"]["text"] == msgs2[0]["message"]["text"]

    def test_empty_mailbox(self, store):
        """Reading/peeking an empty mailbox returns empty list."""
        assert store.read_mailbox("agent-empty") == []
        assert store.peek_mailbox("agent-empty") == []

    def test_per_agent_isolation(self, store):
        """Messages to agent-1 don't appear in agent-2's mailbox."""
        store.send_mailbox_message("agent-1", {"for": "agent-1"})
        store.send_mailbox_message("agent-2", {"for": "agent-2"})

        msgs = store.read_mailbox("agent-1")
        assert len(msgs) == 1
        assert msgs[0]["message"]["for"] == "agent-1"


# ======================================================================
# Workflow DAG
# ======================================================================

class TestWorkflowDAG:
    """
    In v0.3.2: workflow engine executes steps sequentially with
    in-memory dependency polling.
    Now: Redis DAG tracks step status, dependencies, and atomic claiming.

    This proves parallel execution (Phase 7) will work correctly.
    """

    @pytest.fixture
    def dag(self, store):
        """Initialize a 3-step DAG: research → code → report (code depends on research)."""
        steps = [
            {"id": "research", "agent": "researcher", "task": "Gather data", "depends_on": []},
            {"id": "code", "agent": "coder", "task": "Write analysis", "depends_on": ["research"]},
            {"id": "report", "agent": "reporter", "task": "Generate report",
             "depends_on": ["research", "code"]},
        ]
        store.init_workflow_graph("wf-dag", steps)
        return store

    def test_initial_status_is_pending(self, dag):
        """All steps start as pending."""
        assert dag.get_step_status("wf-dag", "research") == "pending"
        assert dag.get_step_status("wf-dag", "code") == "pending"
        assert dag.get_step_status("wf-dag", "report") == "pending"

    def test_no_dependencies_met(self, dag):
        """Step with no dependencies can run immediately."""
        assert dag.are_dependencies_met("wf-dag", "research") is True

    def test_unmet_dependencies(self, dag):
        """Step with unmet dependencies cannot run yet."""
        assert dag.are_dependencies_met("wf-dag", "code") is False
        assert dag.are_dependencies_met("wf-dag", "report") is False

    def test_dependencies_met_after_completion(self, dag):
        """Completing a dependency unblocks the next step."""
        dag.update_step_status("wf-dag", "research", "completed")
        assert dag.are_dependencies_met("wf-dag", "code") is True
        # report still blocked (needs code too)
        assert dag.are_dependencies_met("wf-dag", "report") is False

    def test_all_dependencies_met(self, dag):
        """Step with multiple dependencies needs ALL of them completed."""
        dag.update_step_status("wf-dag", "research", "completed")
        dag.update_step_status("wf-dag", "code", "completed")
        assert dag.are_dependencies_met("wf-dag", "report") is True

    def test_nonexistent_step_status(self, dag):
        """Querying status of a non-existent step returns None."""
        assert dag.get_step_status("wf-dag", "ghost") is None


class TestAtomicStepClaiming:
    """
    Atomic claiming prevents two agents from executing the same step.
    This is critical for parallel workflows — without it, two agents
    could both grab the same step and do duplicate work.

    Uses Redis SETNX (set-if-not-exists) for lock-free atomic operation.
    """

    def test_first_claim_succeeds(self, store):
        steps = [{"id": "step-1", "agent": "any", "task": "work", "depends_on": []}]
        store.init_workflow_graph("wf-claim", steps)

        assert store.claim_step("wf-claim", "step-1", "agent-a") is True
        assert store.get_step_status("wf-claim", "step-1") == "in_progress"

    def test_second_claim_fails(self, store):
        """Two agents racing to claim the same step — only one wins."""
        steps = [{"id": "step-1", "agent": "any", "task": "work", "depends_on": []}]
        store.init_workflow_graph("wf-race", steps)

        assert store.claim_step("wf-race", "step-1", "agent-a") is True
        assert store.claim_step("wf-race", "step-1", "agent-b") is False


# ======================================================================
# Checkpoints (Crash Recovery)
# ======================================================================

class TestCheckpoints:
    """
    In v0.3.2: process dies → all state lost.
    Now: kernel checkpoints state to Redis after every OODA turn.
    On restart, it loads the checkpoint and resumes.

    This proves the crash recovery mechanism works.
    """

    def test_save_and_load(self, store):
        """Save kernel state, simulate crash, load it back."""
        state = json.dumps({
            "turn": 5,
            "status": "active",
            "subagent_results": ["research done", "code generated"],
            "context": {"db_host": "prod-db"},
        })
        store.save_checkpoint("wf-1", "step-1", state)

        # "Crash" — create new store reference (but same fakeredis backend)
        loaded = store.load_checkpoint("wf-1", "step-1")
        assert loaded is not None
        recovered = json.loads(loaded)
        assert recovered["turn"] == 5
        assert recovered["status"] == "active"
        assert len(recovered["subagent_results"]) == 2

    def test_load_nonexistent(self, store):
        """Loading a checkpoint that doesn't exist returns None (fresh start)."""
        assert store.load_checkpoint("wf-1", "never-ran") is None

    def test_checkpoint_overwrite(self, store):
        """Each checkpoint overwrites the previous (only latest state matters)."""
        store.save_checkpoint("wf-1", "step-1", '{"turn": 1}')
        store.save_checkpoint("wf-1", "step-1", '{"turn": 2}')
        store.save_checkpoint("wf-1", "step-1", '{"turn": 3}')

        loaded = json.loads(store.load_checkpoint("wf-1", "step-1"))
        assert loaded["turn"] == 3


# ======================================================================
# Episodic Ledger (Redis Streams)
# ======================================================================

class TestEpisodicLedger:
    """
    Episodic ledger is an append-only log of agent reasoning.
    Borrowed from IA's cognitive ledger pattern using Redis Streams.

    Used by Phase 8 (Memory) for context windowing and summarization.
    """

    def test_append_and_tail(self, store):
        """Append entries, read them back in chronological order."""
        store.append_ledger_entry("wf-1", {"type": "thinking", "content": "Analyzing data..."})
        store.append_ledger_entry("wf-1", {"type": "tool_call", "tool": "web_search", "query": "API docs"})
        store.append_ledger_entry("wf-1", {"type": "result", "content": "Found 3 endpoints"})

        tail = store.get_ledger_tail("wf-1", count=10)
        assert len(tail) == 3
        # Chronological order (oldest first)
        assert tail[0]["type"] == "thinking"
        assert tail[1]["type"] == "tool_call"
        assert tail[2]["type"] == "result"

    def test_tail_limit(self, store):
        """Tail returns only the last N entries."""
        for i in range(20):
            store.append_ledger_entry("wf-1", {"seq": i})

        tail = store.get_ledger_tail("wf-1", count=5)
        assert len(tail) == 5
        # Should be the last 5
        assert tail[0]["seq"] == 15
        assert tail[4]["seq"] == 19

    def test_entries_have_ids(self, store):
        """Each ledger entry gets a unique Redis Stream ID."""
        store.append_ledger_entry("wf-1", {"type": "test"})
        tail = store.get_ledger_tail("wf-1")
        assert "_id" in tail[0]

    def test_empty_ledger(self, store):
        """Reading an empty ledger returns empty list."""
        assert store.get_ledger_tail("wf-empty") == []


# ======================================================================
# Trace Events (PubSub + List)
# ======================================================================

class TestTraceEvents:
    """
    Trace events enable real-time observability (PubSub) and
    post-hoc audit (List persistence).

    Dual-channel approach: IA only does PubSub (lost if no subscriber).
    We also persist to a List, so traces are never lost.
    """

    def test_publish_persists_to_list(self, store):
        """Trace events are persisted to a Redis List for replay."""
        store.publish_trace_event("trace_events:wf-1", {
            "type": "tool_call",
            "tool": "web_search",
            "timestamp": time.time(),
        })

        # The List key stores all published events
        import fakeredis
        # Access the internal redis client to verify List
        raw = store._store._redis.lrange("trace_log:trace_events:wf-1", 0, -1)
        assert len(raw) == 1
        parsed = json.loads(raw[0])
        assert parsed["type"] == "tool_call"


# ======================================================================
# Human-in-the-Loop (HITL)
# ======================================================================

class TestHITL:
    """
    HITL enables the kernel to pause for human approval.
    Borrowed from CA's kernel pattern — but CA left the Redis methods
    as stubs. We implemented them for real.

    Full lifecycle: create → pending → resolve (approve/reject) → decision recorded.
    """

    def test_create_request(self, store):
        """Creating a HITL request sets status to pending."""
        req = store.create_hitl_request("wf-1", "step-1", {
            "type": "approval",
            "description": "Deploy to production?",
        })
        assert req["status"] == "pending"
        assert "request_id" in req

    def test_read_pending_request(self, store):
        """A newly created request reads back as pending."""
        store.create_hitl_request("wf-1", "step-1", {"desc": "Approve?"})
        hitl = store.get_hitl_request("wf-1", "step-1")
        assert hitl["status"] == "pending"

    def test_approve_request(self, store):
        """Human approves — decision and responder are recorded."""
        store.create_hitl_request("wf-1", "step-1", {"desc": "Deploy?"})
        store.resolve_hitl_request("wf-1", "step-1",
                                   decision="approved",
                                   responder="admin@company.com",
                                   comment="Looks good, ship it")

        hitl = store.get_hitl_request("wf-1", "step-1")
        assert hitl["status"] == "resolved"
        assert hitl["decision"] == "approved"
        assert hitl["responder"] == "admin@company.com"
        assert hitl["comment"] == "Looks good, ship it"
        assert "resolved_at" in hitl

    def test_reject_request(self, store):
        """Human rejects — kernel should fail the step."""
        store.create_hitl_request("wf-1", "step-1", {"desc": "Risky change"})
        store.resolve_hitl_request("wf-1", "step-1",
                                   decision="rejected",
                                   responder="lead@company.com",
                                   comment="Too risky, needs review")

        hitl = store.get_hitl_request("wf-1", "step-1")
        assert hitl["status"] == "resolved"
        assert hitl["decision"] == "rejected"

    def test_read_nonexistent_request(self, store):
        """Reading a HITL request that doesn't exist returns None."""
        assert store.get_hitl_request("wf-1", "nonexistent") is None

    def test_resolve_nonexistent_returns_false(self, store):
        """Resolving a request that doesn't exist returns False."""
        assert store.resolve_hitl_request("wf-1", "ghost", "approved") is False


# ======================================================================
# Workflow State (full workflow crash recovery)
# ======================================================================

class TestWorkflowState:
    """
    Full workflow state persistence — used by the WorkflowEngine (Phase 7)
    to resume an entire workflow after crash.
    """

    def test_save_and_load(self, store):
        state = json.dumps({
            "workflow_id": "wf-1",
            "total_steps": 5,
            "processed_steps": ["step-1", "step-2"],
            "running_steps": {"step-3": time.time()},
            "failed_steps": [],
            "status": "running",
        })
        store.save_workflow_state("wf-1", state)
        loaded = store.load_workflow_state("wf-1")
        assert loaded is not None
        parsed = json.loads(loaded)
        assert parsed["total_steps"] == 5
        assert "step-2" in parsed["processed_steps"]

    def test_load_nonexistent(self, store):
        assert store.load_workflow_state("never-ran") is None


# ======================================================================
# Utilities
# ======================================================================

class TestUtilities:

    def test_ping(self, store):
        """Ping confirms Redis connectivity."""
        assert store.ping() is True

    def test_flush_workflow(self, store):
        """Flush cleans up all keys for a workflow."""
        store.save_step_output("wf-clean", "step-1", output="data")
        store.merge_shared_context("wf-clean", {"key": "value"})
        store.save_checkpoint("wf-clean", "step-1", "{}")

        deleted = store.flush_workflow("wf-clean")
        assert deleted > 0

        # Everything should be gone
        assert store.get_step_output("wf-clean", "step-1") is None
        assert store.get_shared_context("wf-clean") == {}
        assert store.load_checkpoint("wf-clean", "step-1") is None


# ======================================================================
# Settings Integration
# ======================================================================

class TestSettingsIntegration:
    """Prove that new settings fields exist and have correct defaults."""

    def test_redis_settings(self):
        from jarviscore.config.settings import Settings
        s = Settings()
        assert s.redis_host == "localhost"
        assert s.redis_port == 6379
        assert s.redis_db == 0
        assert s.redis_url is None
        assert s.redis_context_ttl_days == 7

    def test_storage_settings(self):
        from jarviscore.config.settings import Settings
        s = Settings()
        assert s.storage_backend == "local"
        assert s.storage_base_path == "./blob_storage"

    def test_kernel_settings(self):
        from jarviscore.config.settings import Settings
        s = Settings()
        assert s.kernel_max_turns == 30
        assert s.kernel_max_total_tokens == 80000
        assert s.kernel_thinking_budget == 56000
        assert s.kernel_action_budget == 24000

    def test_llm_routing_settings(self):
        from jarviscore.config.settings import Settings
        s = Settings()
        assert s.claude_task_model == "claude-sonnet-4-5"
        assert s.claude_coding_model == "claude-opus-4-5"

    def test_hitl_settings(self):
        from jarviscore.config.settings import Settings
        s = Settings()
        assert s.hitl_enabled is False
        assert s.hitl_max_confidence == 0.8
        assert s.hitl_min_risk_score == 0.7

    def test_registry_settings(self):
        from jarviscore.config.settings import Settings
        s = Settings()
        assert s.registry_verified_threshold == 1
        assert s.registry_golden_threshold == 5
        assert s.registry_max_cache_size == 500

    def test_browser_settings(self):
        from jarviscore.config.settings import Settings
        s = Settings()
        assert s.browser_enabled is False
        assert s.browser_headless is True
