"""
Tests for Context Distillation — The Knowledge Layer

THE STORY:
Imagine a security review workflow. A researcher agent scans an API and
discovers endpoints. A scanner agent finds a SQL injection vulnerability.
A reviewer agent decides whether to escalate to a human.

Without context distillation, each agent returns opaque dicts. The next
agent has no idea how confident the previous one was, where it got its
information, or whether the data contains leaked secrets.

With context distillation, the flow becomes:

1. EVIDENCE — Every claim cites its source. The researcher says "I found
   this endpoint" and points to the docs URL with 0.9 confidence. The
   scanner says "SQL injection here" and points to the code at line 42.
   (TestEvidence proves sources are tracked and confidence is bounded.)

2. FACTS — Evidence gets wrapped into TruthFacts. Each fact has a value,
   a confidence score, a version number, and who produced it. Facts are
   the atoms of shared knowledge.
   (TestTruthFact proves facts carry metadata correctly.)

3. SHARED TRUTH — Facts live in a TruthContext, the single source of truth
   for the entire workflow. Any agent can query it: "what do we know?",
   "what are we confident about?", "give me just the values."
   (TestTruthContext proves the store is queryable and filterable.)

4. STANDARDIZED OUTPUT — Every subagent returns an AgentOutput envelope
   with status (success/failure/yield), payload, summary, and trajectory.
   This gives the kernel a consistent shape to work with.
   (TestAgentOutput proves the envelope enforces the contract.)

5. SCRUBBING — Before anything reaches the truth store, sensitive data
   (passwords, tokens, API keys, PEM keys) is scrubbed. Agents encounter
   secrets during execution — those must NEVER persist.
   (TestScrubSensitive proves 15 sensitive key patterns + value patterns
   are caught, nested structures are handled, and originals aren't mutated.)

6. DISTILLATION — Raw agent output is converted to structured TruthFacts.
   Dict outputs become one fact per key. AgentOutput envelopes are unwrapped.
   Scalars are wrapped. Sensitive data is scrubbed. Values already shaped
   like TruthFacts keep their metadata.
   (TestDistillOutput proves every output shape is handled correctly.)

7. MERGING — Distilled facts are merged into the shared TruthContext.
   New keys are added. Existing keys get updated with version bumps.
   Evidence is deduplicated by pointer. Every merge is recorded in a
   capped history ledger for audit.
   (TestMergeFacts proves versioning, dedup, history, and accumulation.)

8. BACKWARDS COMPATIBILITY — JarvisContext gains truth, mailbox, tracer,
   human_tasks — all defaulting to None. Existing agents that only use
   workflow_id, step_id, task, params, memory, deps work unchanged.
   (TestJarvisContextV1Fields proves zero breakage.)

9. END-TO-END — Two agents run in sequence. The researcher distills API
   findings. The scanner distills a vulnerability with 0.95 confidence.
   Both merge into a single TruthContext. The reviewer queries high-confidence
   facts and finds the vulnerability. Passwords encountered along the way
   never reach the truth store.
   (TestDistillMergeQuery proves the full pipeline works together.)
"""

import pytest

from jarviscore.context.truth import (
    AgentOutput,
    Evidence,
    TruthContext,
    TruthFact,
)
from jarviscore.context.distillation import (
    distill_output,
    merge_facts,
    scrub_sensitive,
    SENSITIVE_KEYS,
)
from jarviscore.context import JarvisContext, create_context


# ======================================================================
# Evidence Model
# ======================================================================

class TestEvidence:
    """
    Story Step 1: Every claim must cite its source.

    An agent can't just say "the API uses OAuth2" — it must say WHERE
    it learned that (doc_url, code_pointer, runtime_observation, etc.),
    HOW confident it is (0.0 to 1.0), and WHEN it gathered the evidence.
    This is what makes facts trustworthy, not just assertions.
    """

    def test_basic_evidence(self):
        """Evidence captures kind, pointer, and default confidence."""
        ev = Evidence(kind="doc_url", pointer="https://docs.example.com/api")
        assert ev.kind == "doc_url"
        assert ev.pointer == "https://docs.example.com/api"
        assert ev.confidence == 0.5
        assert ev.collected_at  # auto-populated

    def test_evidence_with_quote(self):
        """Evidence can include a verbatim quote from the source."""
        ev = Evidence(
            kind="code_pointer",
            pointer="src/auth.py:42",
            quote="def authenticate(user, password):",
            confidence=0.9,
        )
        assert ev.quote == "def authenticate(user, password):"
        assert ev.confidence == 0.9

    def test_all_evidence_kinds(self):
        """All six evidence kinds are valid."""
        kinds = ["doc_url", "internal_doc", "code_pointer",
                 "ui_capture", "runtime_observation", "other"]
        for kind in kinds:
            ev = Evidence(kind=kind, pointer="test")
            assert ev.kind == kind

    def test_invalid_kind_rejected(self):
        """Evidence rejects unknown kinds."""
        with pytest.raises(Exception):
            Evidence(kind="blog_post", pointer="test")

    def test_confidence_bounds_low(self):
        """Evidence rejects confidence below 0."""
        with pytest.raises(ValueError, match="confidence must be 0.0-1.0"):
            Evidence(kind="other", pointer="test", confidence=-0.1)

    def test_confidence_bounds_high(self):
        """Evidence rejects confidence above 1."""
        with pytest.raises(ValueError, match="confidence must be 0.0-1.0"):
            Evidence(kind="other", pointer="test", confidence=1.5)

    def test_edge_confidence_values(self):
        """Confidence at 0.0 and 1.0 are valid (inclusive bounds)."""
        ev_low = Evidence(kind="other", pointer="a", confidence=0.0)
        ev_high = Evidence(kind="other", pointer="b", confidence=1.0)
        assert ev_low.confidence == 0.0
        assert ev_high.confidence == 1.0


# ======================================================================
# TruthFact Model
# ======================================================================

class TestTruthFact:
    """
    Story Step 2: Evidence gets wrapped into versioned facts.

    A TruthFact is the atom of shared knowledge. It wraps any value
    (string, dict, list) with: who produced it (source), how confident
    we are (confidence), supporting evidence, and a version number
    that increments on every update — so we can detect conflicts.
    """

    def test_basic_fact(self):
        """A fact wraps any value with default metadata."""
        fact = TruthFact(value="Python 3.12 is required")
        assert fact.value == "Python 3.12 is required"
        assert fact.confidence == 0.5
        assert fact.source == "unknown"
        assert fact.version == 1
        assert fact.evidence == []

    def test_fact_with_evidence(self):
        """Facts can carry supporting evidence."""
        ev = Evidence(kind="doc_url", pointer="https://python.org", confidence=0.9)
        fact = TruthFact(
            value="Python 3.12 is required",
            evidence=[ev],
            confidence=0.9,
            source="step-researcher",
        )
        assert len(fact.evidence) == 1
        assert fact.evidence[0].pointer == "https://python.org"
        assert fact.source == "step-researcher"

    def test_fact_with_complex_value(self):
        """Facts can hold dicts, lists, nested structures."""
        fact = TruthFact(
            value={"endpoints": ["/api/v1/users", "/api/v1/auth"], "version": 2},
            source="api-scanner",
        )
        assert fact.value["version"] == 2
        assert len(fact.value["endpoints"]) == 2

    def test_fact_confidence_validation(self):
        """Confidence is validated on creation."""
        with pytest.raises(ValueError):
            TruthFact(value="test", confidence=2.0)


# ======================================================================
# TruthContext Model
# ======================================================================

class TestTruthContext:
    """
    Story Step 3: Facts live in a shared truth store that anyone can query.

    TruthContext is the single source of truth for a workflow. Multiple
    agents write facts into it, and any agent can ask: "what do we know?"
    (fact_keys), "what's the value of X?" (get_fact_value), "what are we
    confident about?" (high_confidence_facts), "give me everything flat"
    (to_flat_dict). This replaces opaque output passing with a queryable
    knowledge base.
    """

    def test_empty_context(self):
        """New TruthContext starts with no facts, version 1."""
        ctx = TruthContext()
        assert ctx.facts == {}
        assert ctx.history == []
        assert ctx.version == 1

    def test_get_fact_value(self):
        """get_fact_value returns the unwrapped value."""
        ctx = TruthContext(facts={
            "language": TruthFact(value="Python", confidence=0.9),
        })
        assert ctx.get_fact_value("language") == "Python"
        assert ctx.get_fact_value("missing") is None
        assert ctx.get_fact_value("missing", "default") == "default"

    def test_get_fact_full(self):
        """get_fact returns the full TruthFact with metadata."""
        fact = TruthFact(value="Python", confidence=0.9, source="scanner")
        ctx = TruthContext(facts={"language": fact})
        retrieved = ctx.get_fact("language")
        assert retrieved.confidence == 0.9
        assert retrieved.source == "scanner"

    def test_fact_keys(self):
        """fact_keys lists all known facts."""
        ctx = TruthContext(facts={
            "a": TruthFact(value=1),
            "b": TruthFact(value=2),
            "c": TruthFact(value=3),
        })
        assert sorted(ctx.fact_keys()) == ["a", "b", "c"]

    def test_to_flat_dict(self):
        """to_flat_dict strips metadata, returns {key: value}."""
        ctx = TruthContext(facts={
            "language": TruthFact(value="Python", confidence=0.9),
            "version": TruthFact(value="3.12", confidence=0.8),
        })
        flat = ctx.to_flat_dict()
        assert flat == {"language": "Python", "version": "3.12"}

    def test_high_confidence_facts(self):
        """high_confidence_facts filters by threshold."""
        ctx = TruthContext(facts={
            "confirmed": TruthFact(value="yes", confidence=0.95),
            "uncertain": TruthFact(value="maybe", confidence=0.3),
            "likely": TruthFact(value="probably", confidence=0.7),
        })
        high = ctx.high_confidence_facts(threshold=0.7)
        assert "confirmed" in high
        assert "likely" in high
        assert "uncertain" not in high


# ======================================================================
# AgentOutput Model
# ======================================================================

class TestAgentOutput:
    """
    Story Step 4: Every subagent returns a standardized envelope.

    Without a standard shape, the kernel would need custom parsing for
    every subagent type. AgentOutput gives a consistent contract:
    status (success/failure/yield), payload, summary, trajectory.
    "yield" is special — it means the agent needs human input (HITL)
    before it can continue.
    """

    def test_success_output(self):
        """Success output with payload and summary."""
        output = AgentOutput(
            status="success",
            payload={"code": "print('hello')"},
            summary="Generated hello world script",
        )
        assert output.status == "success"
        assert output.payload["code"] == "print('hello')"

    def test_failure_output(self):
        """Failure output carries error details."""
        output = AgentOutput(
            status="failure",
            summary="API returned 403 Forbidden",
            metadata={"http_status": 403},
        )
        assert output.status == "failure"
        assert output.metadata["http_status"] == 403

    def test_yield_output(self):
        """Yield status signals HITL pause needed."""
        output = AgentOutput(
            status="yield",
            summary="Needs human approval for database migration",
            metadata={"hitl_reason": "destructive_operation"},
        )
        assert output.status == "yield"

    def test_invalid_status_rejected(self):
        """Only success/failure/yield are valid statuses."""
        with pytest.raises(Exception):
            AgentOutput(status="pending")

    def test_trajectory_tracking(self):
        """Trajectory records the tool execution path."""
        output = AgentOutput(
            status="success",
            trajectory=[
                {"tool": "web_search", "query": "Python async patterns"},
                {"tool": "code_gen", "language": "python"},
            ],
        )
        assert len(output.trajectory) == 2
        assert output.trajectory[0]["tool"] == "web_search"


# ======================================================================
# scrub_sensitive
# ======================================================================

class TestScrubSensitive:
    """
    Story Step 5: Secrets are scrubbed before anything reaches the truth store.

    Agents encounter passwords, tokens, API keys, and PEM private keys
    during execution. If these leak into TruthContext → Redis → blob
    storage, they become a security vulnerability. Scrubbing happens
    BEFORE distillation, so secrets never enter the knowledge system.
    This covers 15 sensitive key names, nested structures, and value
    patterns like Bearer tokens and sk- prefixed API keys.
    """

    def test_scrub_password(self):
        """Password values are redacted."""
        data = {"username": "admin", "password": "s3cret!"}
        clean = scrub_sensitive(data)
        assert clean["username"] == "admin"
        assert clean["password"] == "[REDACTED]"

    def test_scrub_api_key(self):
        """API keys are redacted regardless of casing."""
        data = {"api_key": "sk-12345abc", "name": "my-service"}
        clean = scrub_sensitive(data)
        assert clean["api_key"] == "[REDACTED]"
        assert clean["name"] == "my-service"

    def test_scrub_nested_dict(self):
        """Scrubbing works recursively through nested dicts."""
        data = {
            "config": {
                "database": {
                    "host": "localhost",
                    "password": "db_pass_123",
                }
            }
        }
        clean = scrub_sensitive(data)
        assert clean["config"]["database"]["host"] == "localhost"
        assert clean["config"]["database"]["password"] == "[REDACTED]"

    def test_scrub_list_of_dicts(self):
        """Scrubbing works through lists containing dicts."""
        data = [
            {"service": "api", "token": "abc123"},
            {"service": "db", "password": "xyz"},
        ]
        clean = scrub_sensitive(data)
        assert clean[0]["service"] == "api"
        assert clean[0]["token"] == "[REDACTED]"
        assert clean[1]["password"] == "[REDACTED]"

    def test_scrub_bearer_token_in_value(self):
        """Bearer tokens in string values are detected and redacted."""
        data = {"header": "Bearer eyJhbGciOiJIUzI1NiJ9.payload.sig"}
        clean = scrub_sensitive(data)
        assert clean["header"] == "[REDACTED]"

    def test_scrub_openai_key_pattern(self):
        """OpenAI-style sk- keys in values are detected."""
        data = {"note": "Use key sk-abcdef1234567890 for API access"}
        clean = scrub_sensitive(data)
        assert clean["note"] == "[REDACTED]"

    def test_scrub_private_key(self):
        """PEM private keys are detected in values."""
        data = {"cert": "-----BEGIN PRIVATE KEY-----\nMIIE..."}
        clean = scrub_sensitive(data)
        assert clean["cert"] == "[REDACTED]"

    def test_safe_data_passes_through(self):
        """Non-sensitive data is unchanged."""
        data = {"name": "JarvisCore", "version": "1.0.0", "count": 42}
        clean = scrub_sensitive(data)
        assert clean == data

    def test_original_not_mutated(self):
        """Scrubbing returns a copy, doesn't mutate the original."""
        data = {"password": "secret", "name": "test"}
        clean = scrub_sensitive(data)
        assert data["password"] == "secret"  # original unchanged
        assert clean["password"] == "[REDACTED]"

    def test_all_sensitive_keys_covered(self):
        """All keys in SENSITIVE_KEYS are actually scrubbed."""
        data = {key: f"value_{key}" for key in SENSITIVE_KEYS}
        clean = scrub_sensitive(data)
        for key in SENSITIVE_KEYS:
            assert clean[key] == "[REDACTED]", f"{key} was not scrubbed"


# ======================================================================
# distill_output
# ======================================================================

class TestDistillOutput:
    """
    Story Step 6: Raw agent output becomes structured knowledge.

    This is the bridge between free-form agent results and the typed
    truth store. An agent might return a flat dict, an AgentOutput
    envelope, a scalar string, or even a dict with pre-shaped TruthFact
    values. Distillation handles all of these, scrubs secrets, and
    produces clean TruthFacts ready for merging.
    """

    def test_dict_output(self):
        """Dict output creates one TruthFact per key."""
        raw = {"language": "Python", "framework": "FastAPI"}
        facts = distill_output(raw, source="researcher")
        assert "language" in facts
        assert "framework" in facts
        assert facts["language"].value == "Python"
        assert facts["language"].source == "researcher"

    def test_agent_output_envelope(self):
        """AgentOutput-shaped dict unwraps payload and captures summary."""
        raw = {
            "status": "success",
            "payload": {"endpoint": "/api/v1/users", "method": "GET"},
            "summary": "Found REST API endpoint",
        }
        facts = distill_output(raw, source="scanner")
        assert "summary" in facts
        assert facts["summary"].value == "Found REST API endpoint"
        assert "endpoint" in facts
        assert facts["endpoint"].value == "/api/v1/users"

    def test_scalar_output(self):
        """Non-dict output is wrapped as a single 'result' fact."""
        facts = distill_output("build succeeded", source="builder")
        assert "result" in facts
        assert facts["result"].value == "build succeeded"

    def test_none_payload_in_envelope(self):
        """AgentOutput with None payload produces summary fact only."""
        raw = {"status": "failure", "payload": None, "summary": "API down"}
        facts = distill_output(raw, source="monitor")
        assert "summary" in facts
        assert facts["summary"].value == "API down"

    def test_sensitive_data_scrubbed(self):
        """Sensitive data in output is scrubbed before creating facts."""
        raw = {"api_key": "sk-secret123", "result": "success"}
        facts = distill_output(raw, source="test")
        assert facts["api_key"].value == "[REDACTED]"
        assert facts["result"].value == "success"

    def test_custom_confidence(self):
        """Custom confidence is applied to all distilled facts."""
        facts = distill_output({"x": 1}, source="test", confidence=0.9)
        assert facts["x"].confidence == 0.9

    def test_evidence_attached(self):
        """Evidence is attached to all distilled facts."""
        ev = Evidence(kind="doc_url", pointer="https://example.com")
        facts = distill_output({"x": 1}, source="test", evidence=[ev])
        assert len(facts["x"].evidence) == 1
        assert facts["x"].evidence[0].pointer == "https://example.com"

    def test_truthfact_shaped_value_preserved(self):
        """Values already shaped like TruthFacts preserve their metadata."""
        raw = {
            "finding": {
                "value": "SQL injection vulnerability",
                "confidence": 0.95,
                "source": "security-scanner",
            }
        }
        facts = distill_output(raw, source="reviewer")
        assert facts["finding"].value == "SQL injection vulnerability"
        assert facts["finding"].confidence == 0.95
        assert facts["finding"].source == "security-scanner"


# ======================================================================
# merge_facts
# ======================================================================

class TestMergeFacts:
    """
    Story Step 7: Multiple agents' facts merge into one truth.

    This is the core operation. Agent A finds the API version. Agent B
    finds a vulnerability. Agent C updates the API version with new info.
    Each merge: adds new facts, updates existing ones with version bumps,
    deduplicates evidence by pointer, and records every change in a
    capped history ledger. The result is a single, versioned, auditable
    truth store that reflects everything the workflow has learned.
    """

    def test_merge_new_facts(self):
        """New facts are added to an empty TruthContext."""
        ctx = TruthContext()
        new = {
            "language": TruthFact(value="Python", source="researcher"),
            "version": TruthFact(value="3.12", source="researcher"),
        }
        result = merge_facts(ctx, new, source="step-1")
        assert result.get_fact_value("language") == "Python"
        assert result.get_fact_value("version") == "3.12"
        assert result.version == 2  # bumped from 1

    def test_merge_updates_existing(self):
        """Merging an existing key updates value and bumps version."""
        ctx = TruthContext(facts={
            "status": TruthFact(value="investigating", version=1),
        })
        new = {"status": TruthFact(value="confirmed", source="analyst")}
        result = merge_facts(ctx, new, source="step-2")
        assert result.get_fact_value("status") == "confirmed"
        assert result.get_fact("status").version == 2  # bumped

    def test_merge_preserves_other_facts(self):
        """Merging new facts doesn't remove existing ones."""
        ctx = TruthContext(facts={
            "existing": TruthFact(value="keep me"),
        })
        new = {"added": TruthFact(value="new fact")}
        result = merge_facts(ctx, new, source="step-2")
        assert result.get_fact_value("existing") == "keep me"
        assert result.get_fact_value("added") == "new fact"

    def test_merge_records_history(self):
        """Every merge is recorded in the history ledger."""
        ctx = TruthContext()
        new = {"fact1": TruthFact(value="data")}
        result = merge_facts(ctx, new, source="agent-alpha")
        assert len(result.history) == 1
        assert result.history[0]["source"] == "agent-alpha"
        assert result.history[0]["action"] == "merge"
        assert "fact1" in result.history[0]["keys"]

    def test_merge_evidence_deduplication(self):
        """Evidence with the same pointer is not duplicated on merge."""
        ev = Evidence(kind="doc_url", pointer="https://docs.example.com")
        ctx = TruthContext(facts={
            "api": TruthFact(value="REST", evidence=[ev]),
        })
        new_ev = Evidence(kind="doc_url", pointer="https://docs.example.com")
        new = {"api": TruthFact(value="REST v2", evidence=[new_ev])}
        result = merge_facts(ctx, new, source="step-2")
        # Same pointer → should not duplicate
        assert len(result.get_fact("api").evidence) == 1

    def test_merge_evidence_new_pointer_added(self):
        """Evidence with a new pointer is appended on merge."""
        ev1 = Evidence(kind="doc_url", pointer="https://source1.com")
        ctx = TruthContext(facts={
            "api": TruthFact(value="REST", evidence=[ev1]),
        })
        ev2 = Evidence(kind="code_pointer", pointer="src/api.py:10")
        new = {"api": TruthFact(value="REST v2", evidence=[ev2])}
        result = merge_facts(ctx, new, source="step-2")
        assert len(result.get_fact("api").evidence) == 2

    def test_merge_history_capped(self):
        """History is capped at max_history to prevent unbounded growth."""
        ctx = TruthContext()
        for i in range(60):
            new = {f"fact_{i}": TruthFact(value=i)}
            merge_facts(ctx, new, source=f"step-{i}", max_history=50)
        assert len(ctx.history) == 50

    def test_empty_merge_no_change(self):
        """Merging empty facts doesn't bump version or add history."""
        ctx = TruthContext(version=5)
        result = merge_facts(ctx, {}, source="noop")
        assert result.version == 5
        assert len(result.history) == 0

    def test_multiple_sequential_merges(self):
        """Multiple merges accumulate facts and history correctly."""
        ctx = TruthContext()
        merge_facts(ctx, {"a": TruthFact(value=1)}, source="step-1")
        merge_facts(ctx, {"b": TruthFact(value=2)}, source="step-2")
        merge_facts(ctx, {"c": TruthFact(value=3)}, source="step-3")
        assert len(ctx.facts) == 3
        assert ctx.version == 4  # 1 + 3 merges
        assert len(ctx.history) == 3


# ======================================================================
# JarvisContext Backwards Compatibility
# ======================================================================

class TestJarvisContextV1Fields:
    """
    Story Step 8: Existing agents keep working, new capabilities are opt-in.

    JarvisContext gains truth, mailbox, tracer, human_tasks — all
    defaulting to None. An agent written for v0.3.2 that only uses
    ctx.workflow_id, ctx.memory, ctx.deps works identically on v1.0.0.
    New agents can opt into ctx.truth to read/write shared facts,
    ctx.mailbox for peer messaging, ctx.tracer for telemetry. This is
    an additive change, not a breaking one.
    """

    def test_existing_fields_unchanged(self):
        """All original fields still work exactly as before."""
        ctx = JarvisContext(
            workflow_id="wf-1",
            step_id="step-1",
            task="Process data",
            params={"threshold": 0.5},
        )
        assert ctx.workflow_id == "wf-1"
        assert ctx.step_id == "step-1"
        assert ctx.task == "Process data"
        assert ctx.params["threshold"] == 0.5

    def test_new_fields_default_to_none(self):
        """New v1.0.0 fields default to None — no breakage."""
        ctx = JarvisContext(
            workflow_id="wf-1",
            step_id="step-1",
            task="test",
        )
        assert ctx.truth is None
        assert ctx.mailbox is None
        assert ctx.tracer is None
        assert ctx.human_tasks is None

    def test_truth_can_be_set(self):
        """TruthContext can be attached to JarvisContext."""
        truth = TruthContext(facts={
            "language": TruthFact(value="Python"),
        })
        ctx = JarvisContext(
            workflow_id="wf-1",
            step_id="step-1",
            task="test",
            truth=truth,
        )
        assert ctx.truth.get_fact_value("language") == "Python"

    def test_create_context_still_works(self):
        """The factory function works unchanged (new fields stay None)."""
        ctx = create_context(
            workflow_id="wf-1",
            step_id="step-1",
            task="Process data",
            params={"mode": "fast"},
            memory_dict={},
        )
        assert ctx.workflow_id == "wf-1"
        assert ctx.truth is None
        assert ctx.mailbox is None

    def test_repr_unchanged(self):
        """__repr__ still works (doesn't crash on new fields)."""
        ctx = JarvisContext(
            workflow_id="wf-1",
            step_id="step-1",
            task="test",
            params={"a": 1},
        )
        r = repr(ctx)
        assert "wf-1" in r
        assert "step-1" in r


# ======================================================================
# Integration: Distill → Merge → Query
# ======================================================================

class TestDistillMergeQuery:
    """
    Story Step 9: The full story — two agents share knowledge through truth.

    A researcher scans an API and returns endpoints + auth type. A security
    scanner finds a SQL injection with 0.95 confidence. Both outputs are
    distilled, scrubbed, and merged into one TruthContext. A reviewer can
    now query: "what are we highly confident about?" and find the vulnerability.
    Meanwhile, any passwords encountered along the way were scrubbed and
    never reached the truth store. This is the complete pipeline the kernel
    will orchestrate in Phase 6.
    """

    def test_full_pipeline(self):
        """Complete flow: distill two outputs, merge, query."""
        ctx = TruthContext()

        # Agent 1: researcher finds API info
        raw1 = {
            "api_version": "v2",
            "endpoints": ["/users", "/auth"],
            "auth_type": "OAuth2",
        }
        facts1 = distill_output(raw1, source="researcher", confidence=0.8)
        merge_facts(ctx, facts1, source="step-research")

        # Agent 2: security scanner finds vulnerability
        raw2 = {
            "status": "success",
            "payload": {
                "vulnerability": {
                    "value": "SQL injection in /users endpoint",
                    "confidence": 0.95,
                    "source": "security-scanner",
                }
            },
            "summary": "Critical vulnerability found",
        }
        facts2 = distill_output(raw2, source="scanner", confidence=0.7)
        merge_facts(ctx, facts2, source="step-scan")

        # Query the merged context
        assert ctx.get_fact_value("api_version") == "v2"
        assert ctx.get_fact_value("auth_type") == "OAuth2"
        assert ctx.get_fact_value("vulnerability") == "SQL injection in /users endpoint"
        assert ctx.get_fact("vulnerability").confidence == 0.95

        # High confidence filter
        high = ctx.high_confidence_facts(threshold=0.9)
        assert "vulnerability" in high
        assert "api_version" not in high  # 0.8 < 0.9

        # Flat view for simple access
        flat = ctx.to_flat_dict()
        assert "summary" in flat
        assert "vulnerability" in flat

        # History shows both merges
        assert len(ctx.history) == 2
        assert ctx.version == 3

    def test_sensitive_data_never_reaches_truth(self):
        """Passwords in agent output are scrubbed before reaching TruthContext."""
        ctx = TruthContext()
        raw = {
            "db_host": "postgres.internal",
            "password": "super_secret_123",
            "connection_string": "postgres://user:pass@host/db",
        }
        facts = distill_output(raw, source="db-agent")
        merge_facts(ctx, facts, source="step-db")

        assert ctx.get_fact_value("db_host") == "postgres.internal"
        assert ctx.get_fact_value("password") == "[REDACTED]"
        assert ctx.get_fact_value("connection_string") == "[REDACTED]"
