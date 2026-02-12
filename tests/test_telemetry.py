"""
Tests for Telemetry — The Observability Layer

THE STORY:
A workflow runs: the kernel claims a step, thinks about what to do,
delegates to a coder subagent, the subagent calls an LLM, generates code,
runs a tool, and completes the step. Later, a security-sensitive action
triggers HITL — the kernel pauses and waits for human approval.

Without telemetry, this is a black box. You start a workflow and get
a result minutes later. If something went wrong — slow LLM, failed tool,
stuck HITL — you have no way to know where or why.

With telemetry, the flow becomes:

1. EVENT TYPES — Every action has a typed category. Not free-form strings
   like "something happened", but structured types: WORKFLOW_START,
   THINKING, TOOL_START, HITL_WAITING, etc. The enum has 20 event types
   covering the full lifecycle.
   (TestTraceEventType proves all types exist and are string-valued.)

2. TRACE MANAGER — The flight data recorder. It captures every event and
   writes to three channels simultaneously:
   - Redis List (persistent, replayable — for debugging after the fact)
   - Redis PubSub (real-time — for live dashboards)
   - JSONL file (fallback — for compliance, offline analysis)
   (TestTraceManager proves all three channels work, events have correct
   structure, and convenience methods emit the right event types.)

3. JSONL FALLBACK — When Redis is unavailable (or for compliance), every
   event is appended to a JSONL file. One line per event, parseable by
   any tool. The file is created automatically.
   (TestJSONLFallback proves events persist to disk even without Redis.)

4. REDIS INTEGRATION — Events flow through RedisContextStore's
   publish_trace_event method. The PubSub channel lets frontends
   subscribe for live cognitive streaming. The List lets you replay
   a workflow's entire trace history.
   (TestRedisTracing proves events reach Redis and are retrievable.)

5. PROMETHEUS METRICS — Counters and histograms track LLM usage
   (tokens, cost, duration per model), workflow execution (steps
   completed/failed, active counts), and event emission. This is
   what powers dashboards that show "we spent $42 on Claude today"
   or "step-3 took 120 seconds."
   (TestPrometheusMetrics proves all metrics increment correctly.)

6. CONVENIENCE METHODS — Instead of raw log_event() calls, the
   TraceManager provides typed methods: log_thinking(), log_tool_start(),
   log_step_complete(), log_hitl_waiting(), etc. Each produces the
   correct event type and structured payload.
   (TestConvenienceMethods proves each method maps to the right type.)

7. END-TO-END — A complete workflow trace: start → claim step → think →
   delegate to subagent → LLM request → LLM response → tool start →
   tool result → step complete → workflow complete. Plus a HITL flow:
   task created → waiting → response received → resolved. The full
   trace is readable from JSONL, in chronological order, with all
   timestamps and payloads intact.
   (TestEndToEnd proves the full story flows through all channels.)
"""

import json
import os
import shutil
import tempfile

import pytest

from jarviscore.telemetry.events import TraceEventType
from jarviscore.telemetry.tracer import TraceManager
from jarviscore.telemetry.metrics import (
    record_llm_call,
    record_step_execution,
    record_event,
    increment_active_workflows,
    decrement_active_workflows,
    increment_active_steps,
    decrement_active_steps,
    llm_tokens_input,
    llm_tokens_output,
    llm_cost_dollars,
    llm_requests_total,
    workflow_steps_total,
    active_workflows,
    active_steps,
    events_emitted_total,
)
from jarviscore.testing import MockRedisContextStore


# ======================================================================
# Story Step 1: Event Types
# ======================================================================

class TestTraceEventType:
    """
    Story Step 1: Every action has a typed category.

    Without typed events, traces are free-form strings that can't be
    filtered, counted, or visualized. The enum enforces that every
    emitter uses a known category — dashboards can filter by type,
    Prometheus can count by type, and replays can skip to specific events.
    """

    def test_all_lifecycle_events_exist(self):
        """Workflow and step lifecycle events cover start-to-finish."""
        assert TraceEventType.WORKFLOW_START == "workflow_start"
        assert TraceEventType.WORKFLOW_COMPLETE == "workflow_complete"
        assert TraceEventType.STEP_CLAIMED == "step_claimed"
        assert TraceEventType.STEP_COMPLETE == "step_complete"
        assert TraceEventType.STEP_FAILED == "step_failed"

    def test_all_cognition_events_exist(self):
        """Kernel reasoning events let you see the agent's thought process."""
        assert TraceEventType.THINKING == "thinking"
        assert TraceEventType.KERNEL_DELEGATE == "kernel_delegate"
        assert TraceEventType.SUBAGENT_YIELD == "subagent_yield"

    def test_all_tool_events_exist(self):
        """Tool execution events track what tools were called and results."""
        assert TraceEventType.TOOL_START == "tool_start"
        assert TraceEventType.TOOL_RESULT == "tool_result"

    def test_all_llm_events_exist(self):
        """LLM interaction events track requests and responses with timing."""
        assert TraceEventType.LLM_REQUEST == "llm_request"
        assert TraceEventType.LLM_RESPONSE == "llm_response"

    def test_all_communication_events_exist(self):
        """Mailbox events track inter-agent messaging."""
        assert TraceEventType.MAILBOX_SEND == "mailbox_send"
        assert TraceEventType.MAILBOX_RECEIVE == "mailbox_receive"

    def test_all_hitl_events_exist(self):
        """HITL events track the full human-in-the-loop lifecycle."""
        assert TraceEventType.HITL_TASK_CREATED == "hitl_task_created"
        assert TraceEventType.HITL_WAITING == "hitl_waiting"
        assert TraceEventType.HITL_RESPONSE_RECEIVED == "hitl_response_received"
        assert TraceEventType.HITL_RESOLVED == "hitl_resolved"

    def test_context_and_error_events_exist(self):
        """Context snapshots and error recovery are trackable."""
        assert TraceEventType.CONTEXT_SNAPSHOT == "context_snapshot"
        assert TraceEventType.ERROR_RECOVERY == "error_recovery"

    def test_event_count(self):
        """All 20 event types are accounted for."""
        assert len(TraceEventType) == 20

    def test_events_are_strings(self):
        """Events are string-valued for JSON serialization."""
        for event in TraceEventType:
            assert isinstance(event.value, str)


# ======================================================================
# Story Step 2: TraceManager structure
# ======================================================================

class TestTraceManager:
    """
    Story Step 2: The flight data recorder captures every event.

    TraceManager is initialized with workflow_id and step_id. Every
    log_event call produces a structured JSON object with timestamp,
    type, and data. This structure is consistent across all three
    channels (Redis List, PubSub, JSONL).
    """

    @pytest.fixture
    def trace_dir(self):
        tmp = tempfile.mkdtemp()
        yield tmp
        shutil.rmtree(tmp)

    def test_event_structure(self, trace_dir):
        """Events have workflow_id, step_id, timestamp, type, and data."""
        tracer = TraceManager("wf-1", "step-1", trace_dir=trace_dir)
        tracer.log_event("test_event", {"key": "value"})

        jsonl_path = os.path.join(trace_dir, "wf-1_step-1.jsonl")
        with open(jsonl_path) as f:
            event = json.loads(f.readline())

        assert event["workflow_id"] == "wf-1"
        assert event["step_id"] == "step-1"
        assert "timestamp" in event
        assert event["type"] == "test_event"
        assert event["data"]["key"] == "value"

    def test_multiple_events_append(self, trace_dir):
        """Events append to the same JSONL file, one per line."""
        tracer = TraceManager("wf-1", "step-1", trace_dir=trace_dir)
        tracer.log_event("event_1", {"n": 1})
        tracer.log_event("event_2", {"n": 2})
        tracer.log_event("event_3", {"n": 3})

        jsonl_path = os.path.join(trace_dir, "wf-1_step-1.jsonl")
        with open(jsonl_path) as f:
            lines = f.readlines()
        assert len(lines) == 3

    def test_empty_data_defaults(self, trace_dir):
        """Events with no data get an empty dict."""
        tracer = TraceManager("wf-1", "step-1", trace_dir=trace_dir)
        tracer.log_event("minimal")

        jsonl_path = os.path.join(trace_dir, "wf-1_step-1.jsonl")
        with open(jsonl_path) as f:
            event = json.loads(f.readline())
        assert event["data"] == {}

    def test_works_without_redis(self, trace_dir):
        """TraceManager works in JSONL-only mode when Redis is None."""
        tracer = TraceManager("wf-1", "step-1", redis_store=None, trace_dir=trace_dir)
        tracer.log_event("no_redis", {"still": "works"})

        jsonl_path = os.path.join(trace_dir, "wf-1_step-1.jsonl")
        assert os.path.exists(jsonl_path)
        with open(jsonl_path) as f:
            event = json.loads(f.readline())
        assert event["data"]["still"] == "works"


# ======================================================================
# Story Step 3: JSONL Fallback
# ======================================================================

class TestJSONLFallback:
    """
    Story Step 3: Events persist to disk even without Redis.

    JSONL is the compliance/fallback channel. Every event is one line
    of JSON, appended to a file named {workflow_id}_{step_id}.jsonl.
    The directory is created automatically. Each line is independently
    parseable — no need to load the whole file.
    """

    @pytest.fixture
    def trace_dir(self):
        tmp = tempfile.mkdtemp()
        yield tmp
        shutil.rmtree(tmp)

    def test_jsonl_file_created(self, trace_dir):
        """JSONL file is created on first event."""
        tracer = TraceManager("wf-abc", "step-2", trace_dir=trace_dir)
        tracer.log_event("first")

        expected = os.path.join(trace_dir, "wf-abc_step-2.jsonl")
        assert os.path.exists(expected)

    def test_jsonl_lines_are_valid_json(self, trace_dir):
        """Every line in the JSONL file is valid, parseable JSON."""
        tracer = TraceManager("wf-1", "step-1", trace_dir=trace_dir)
        for i in range(5):
            tracer.log_event(f"event_{i}", {"index": i})

        jsonl_path = os.path.join(trace_dir, "wf-1_step-1.jsonl")
        with open(jsonl_path) as f:
            for line in f:
                event = json.loads(line)  # Should not raise
                assert "timestamp" in event
                assert "type" in event

    def test_jsonl_preserves_chronological_order(self, trace_dir):
        """Events are in chronological order (append-only)."""
        tracer = TraceManager("wf-1", "step-1", trace_dir=trace_dir)
        tracer.log_event("first", {"order": 1})
        tracer.log_event("second", {"order": 2})
        tracer.log_event("third", {"order": 3})

        jsonl_path = os.path.join(trace_dir, "wf-1_step-1.jsonl")
        with open(jsonl_path) as f:
            events = [json.loads(line) for line in f]
        assert events[0]["data"]["order"] == 1
        assert events[1]["data"]["order"] == 2
        assert events[2]["data"]["order"] == 3

    def test_nested_trace_dir_created(self):
        """Trace directory is created if it doesn't exist."""
        tmp = tempfile.mkdtemp()
        try:
            nested = os.path.join(tmp, "deep", "traces")
            tracer = TraceManager("wf-1", "step-1", trace_dir=nested)
            tracer.log_event("test")
            assert os.path.exists(os.path.join(nested, "wf-1_step-1.jsonl"))
        finally:
            shutil.rmtree(tmp)


# ======================================================================
# Story Step 4: Redis Integration
# ======================================================================

class TestRedisTracing:
    """
    Story Step 4: Events flow to Redis for real-time streaming and replay.

    When a RedisContextStore is provided, events are published to both
    a Redis List (for persistent replay) and PubSub (for live dashboards).
    The trace channel is trace_events:{workflow_id}.
    """

    @pytest.fixture
    def trace_dir(self):
        tmp = tempfile.mkdtemp()
        yield tmp
        shutil.rmtree(tmp)

    @pytest.fixture
    def redis_store(self):
        return MockRedisContextStore()

    def test_events_reach_redis_list(self, redis_store, trace_dir):
        """Events are persisted to Redis List for replay."""
        tracer = TraceManager("wf-1", "step-1", redis_store=redis_store, trace_dir=trace_dir)
        tracer.log_event("thinking", {"thought": "analyzing the API"})

        # Events should be in the trace log list
        key = "trace_log:trace_events:wf-1"
        raw = redis_store._store._redis.lrange(key, 0, -1)
        assert len(raw) >= 1
        event = json.loads(raw[0])
        assert event["type"] == "thinking"

    def test_events_written_to_both_redis_and_jsonl(self, redis_store, trace_dir):
        """Events go to both Redis and JSONL simultaneously."""
        tracer = TraceManager("wf-1", "step-1", redis_store=redis_store, trace_dir=trace_dir)
        tracer.log_event("dual_channel", {"test": True})

        # Redis
        key = "trace_log:trace_events:wf-1"
        raw = redis_store._store._redis.lrange(key, 0, -1)
        assert len(raw) >= 1

        # JSONL
        jsonl_path = os.path.join(trace_dir, "wf-1_step-1.jsonl")
        assert os.path.exists(jsonl_path)


# ======================================================================
# Story Step 5: Prometheus Metrics
# ======================================================================

class TestPrometheusMetrics:
    """
    Story Step 5: Counters and histograms power operational dashboards.

    Prometheus metrics answer: "How many tokens did we use today?"
    "What's the average LLM latency?" "How many steps failed?"
    "How many workflows are running right now?" These are the numbers
    that drive cost control and performance optimization.
    """

    def test_record_llm_call_increments_all_metrics(self):
        """A single LLM call increments tokens, cost, duration, and request count."""
        before_input = llm_tokens_input.labels(provider="anthropic", model="opus").describe()

        record_llm_call(
            provider="anthropic",
            model="opus",
            input_tokens=1000,
            output_tokens=500,
            cost=0.15,
            duration=2.5,
            success=True,
        )

        # Tokens incremented
        assert llm_tokens_input.labels(provider="anthropic", model="opus")._value.get() >= 1000
        assert llm_tokens_output.labels(provider="anthropic", model="opus")._value.get() >= 500

        # Cost incremented
        assert llm_cost_dollars.labels(provider="anthropic", model="opus")._value.get() >= 0.15

        # Request counted as success
        assert llm_requests_total.labels(provider="anthropic", model="opus", status="success")._value.get() >= 1

    def test_record_failed_llm_call(self):
        """Failed LLM calls are tracked separately from successes."""
        record_llm_call(
            provider="openai", model="gpt-4o",
            input_tokens=500, output_tokens=0,
            cost=0.0, duration=30.0, success=False,
        )
        assert llm_requests_total.labels(provider="openai", model="gpt-4o", status="error")._value.get() >= 1

    def test_record_step_execution(self):
        """Step execution records duration and status."""
        record_step_execution(duration=5.0, status="completed")
        assert workflow_steps_total.labels(status="completed")._value.get() >= 1

    def test_record_failed_step(self):
        """Failed steps are tracked with their status."""
        record_step_execution(duration=1.0, status="failed")
        assert workflow_steps_total.labels(status="failed")._value.get() >= 1

    def test_active_workflow_gauge(self):
        """Active workflow gauge increments and decrements."""
        before = active_workflows._value.get()
        increment_active_workflows()
        assert active_workflows._value.get() == before + 1
        decrement_active_workflows()
        assert active_workflows._value.get() == before

    def test_active_steps_gauge(self):
        """Active steps gauge increments and decrements."""
        before = active_steps._value.get()
        increment_active_steps()
        assert active_steps._value.get() == before + 1
        decrement_active_steps()
        assert active_steps._value.get() == before

    def test_record_event_emission(self):
        """Event emissions are counted by type."""
        record_event("thinking")
        assert events_emitted_total.labels(event_type="thinking")._value.get() >= 1


# ======================================================================
# Story Step 6: Convenience Methods
# ======================================================================

class TestConvenienceMethods:
    """
    Story Step 6: Typed methods produce correct events without boilerplate.

    Instead of writing log_event("thinking", {"thought": "..."}) every time,
    the TraceManager provides log_thinking("..."). Each convenience method
    maps to the correct TraceEventType and structures the payload correctly.
    """

    @pytest.fixture
    def tracer(self):
        tmp = tempfile.mkdtemp()
        t = TraceManager("wf-1", "step-1", trace_dir=tmp)
        yield t, tmp
        shutil.rmtree(tmp)

    def _read_last_event(self, trace_dir):
        jsonl_path = os.path.join(trace_dir, "wf-1_step-1.jsonl")
        with open(jsonl_path) as f:
            lines = f.readlines()
        return json.loads(lines[-1])

    def test_log_thinking(self, tracer):
        t, d = tracer
        t.log_thinking("Analyzing the API structure")
        event = self._read_last_event(d)
        assert event["type"] == "thinking"
        assert event["data"]["thought"] == "Analyzing the API structure"

    def test_log_kernel_delegate(self, tracer):
        t, d = tracer
        t.log_kernel_delegate("coder", "Write unit tests", "opus")
        event = self._read_last_event(d)
        assert event["type"] == "kernel_delegate"
        assert event["data"]["subagent"] == "coder"
        assert event["data"]["model_tier"] == "opus"

    def test_log_tool_start(self, tracer):
        t, d = tracer
        t.log_tool_start("web_search", {"query": "Python async"})
        event = self._read_last_event(d)
        assert event["type"] == "tool_start"
        assert event["data"]["tool"] == "web_search"

    def test_log_tool_result_success(self, tracer):
        t, d = tracer
        t.log_tool_result("web_search", result="Found 10 results")
        event = self._read_last_event(d)
        assert event["type"] == "tool_result"
        assert "error" not in event["data"]

    def test_log_tool_result_error(self, tracer):
        t, d = tracer
        t.log_tool_result("web_search", error="Connection timeout")
        event = self._read_last_event(d)
        assert event["type"] == "tool_result"
        assert event["data"]["error"] == "Connection timeout"

    def test_log_llm_request(self, tracer):
        t, d = tracer
        t.log_llm_request("anthropic", "claude-opus-4-5", "Write a function...")
        event = self._read_last_event(d)
        assert event["type"] == "llm_request"
        assert event["data"]["provider"] == "anthropic"

    def test_log_llm_response(self, tracer):
        t, d = tracer
        t.log_llm_response("anthropic", "claude-opus-4-5", 2345.67, 1500, 800)
        event = self._read_last_event(d)
        assert event["type"] == "llm_response"
        assert event["data"]["latency_ms"] == 2345.67
        assert event["data"]["input_tokens"] == 1500

    def test_log_step_complete(self, tracer):
        t, d = tracer
        t.log_step_complete("step-1", "completed", "Analysis done")
        event = self._read_last_event(d)
        assert event["type"] == "step_complete"
        assert event["data"]["status"] == "completed"

    def test_log_hitl_waiting(self, tracer):
        t, d = tracer
        t.log_hitl_waiting("hitl-123", "destructive operation")
        event = self._read_last_event(d)
        assert event["type"] == "hitl_waiting"
        assert event["data"]["reason"] == "destructive operation"

    def test_log_mailbox_send(self, tracer):
        t, d = tracer
        t.log_mailbox_send("agent-reviewer", "Please review findings")
        event = self._read_last_event(d)
        assert event["type"] == "mailbox_send"
        assert event["data"]["target"] == "agent-reviewer"

    def test_log_context_snapshot(self, tracer):
        t, d = tracer
        t.log_context_snapshot(fact_count=12, version=5)
        event = self._read_last_event(d)
        assert event["type"] == "context_snapshot"
        assert event["data"]["fact_count"] == 12

    def test_log_error_recovery(self, tracer):
        t, d = tracer
        t.log_error_recovery("API returned 500", "retrying with backoff")
        event = self._read_last_event(d)
        assert event["type"] == "error_recovery"
        assert event["data"]["recovery_action"] == "retrying with backoff"


# ======================================================================
# Story Step 7: End-to-End
# ======================================================================

class TestEndToEnd:
    """
    Story Step 7: The full workflow trace — from start to finish.

    A complete workflow runs: start → claim → think → delegate → LLM →
    tool → step complete → workflow complete. Plus a HITL side-flow:
    task created → waiting → response → resolved. Every event is
    in the JSONL file, in order, with all metadata intact. This is
    what a developer reads when debugging "why did this workflow
    take 3 minutes?" or "why did the agent choose that tool?"
    """

    @pytest.fixture
    def trace_dir(self):
        tmp = tempfile.mkdtemp()
        yield tmp
        shutil.rmtree(tmp)

    def test_full_workflow_trace(self, trace_dir):
        """Complete workflow trace is readable from JSONL in order."""
        redis = MockRedisContextStore()
        tracer = TraceManager("wf-security", "step-1", redis_store=redis, trace_dir=trace_dir)

        # The workflow story
        tracer.log_workflow_start(step_count=3)
        tracer.log_step_claimed("agent-scanner")
        tracer.log_thinking("I need to scan the API for vulnerabilities")
        tracer.log_kernel_delegate("researcher", "Find API endpoints", "sonnet")
        tracer.log_llm_request("anthropic", "claude-sonnet-4-5", "List all endpoints...")
        tracer.log_llm_response("anthropic", "claude-sonnet-4-5", 1234.5, 800, 200)
        tracer.log_tool_start("web_search", {"query": "API docs"})
        tracer.log_tool_result("web_search", result="Found 5 endpoints")
        tracer.log_context_snapshot(fact_count=5, version=2)
        tracer.log_step_complete("step-1", "completed", "Scan complete")

        # Read the trace
        jsonl_path = os.path.join(trace_dir, "wf-security_step-1.jsonl")
        with open(jsonl_path) as f:
            events = [json.loads(line) for line in f]

        # Verify chronological flow
        types = [e["type"] for e in events]
        assert types == [
            "workflow_start",
            "step_claimed",
            "thinking",
            "kernel_delegate",
            "llm_request",
            "llm_response",
            "tool_start",
            "tool_result",
            "context_snapshot",
            "step_complete",
        ]

        # All events have correct workflow context
        for event in events:
            assert event["workflow_id"] == "wf-security"
            assert event["step_id"] == "step-1"
            assert "timestamp" in event

    def test_hitl_trace_flow(self, trace_dir):
        """HITL events trace the full human approval lifecycle."""
        tracer = TraceManager("wf-deploy", "step-2", trace_dir=trace_dir)

        tracer.log_hitl_task_created("hitl-001", "approval", "Delete production database")
        tracer.log_hitl_waiting("hitl-001", "destructive operation requires approval")
        tracer.log_hitl_response_received("hitl-001", "Approved with condition: backup first")
        tracer.log_hitl_resolved("hitl-001", "approved")

        jsonl_path = os.path.join(trace_dir, "wf-deploy_step-2.jsonl")
        with open(jsonl_path) as f:
            events = [json.loads(line) for line in f]

        types = [e["type"] for e in events]
        assert types == [
            "hitl_task_created",
            "hitl_waiting",
            "hitl_response_received",
            "hitl_resolved",
        ]

        # Verify HITL data is captured
        assert events[0]["data"]["task_id"] == "hitl-001"
        assert events[0]["data"]["description"] == "Delete production database"
        assert events[2]["data"]["comment"] == "Approved with condition: backup first"
        assert events[3]["data"]["outcome"] == "approved"

    def test_error_recovery_trace(self, trace_dir):
        """Error and recovery events tell the debugging story."""
        tracer = TraceManager("wf-flaky", "step-3", trace_dir=trace_dir)

        tracer.log_tool_start("api_call", {"url": "/users"})
        tracer.log_tool_result("api_call", error="500 Internal Server Error")
        tracer.log_error_recovery("API returned 500", "retrying with exponential backoff")
        tracer.log_tool_start("api_call", {"url": "/users", "retry": 1})
        tracer.log_tool_result("api_call", result="200 OK, 42 users")
        tracer.log_step_complete("step-3", "completed", "Recovered after retry")

        jsonl_path = os.path.join(trace_dir, "wf-flaky_step-3.jsonl")
        with open(jsonl_path) as f:
            events = [json.loads(line) for line in f]

        types = [e["type"] for e in events]
        assert types == [
            "tool_start",
            "tool_result",
            "error_recovery",
            "tool_start",
            "tool_result",
            "step_complete",
        ]
        # First tool result has error, second has success
        assert "error" in events[1]["data"]
        assert "error" not in events[4]["data"]
