---
icon: material/chart-line
---

# Observability & Telemetry

JarvisCore ships with a built-in, two-layer observability system. Every agent turn, tool call, LLM request, mailbox message, and HITL event is captured automatically — no instrumentation required in your agent code.

The two layers serve different purposes:

| Layer | What it does | Where data goes |
|---|---|---|
| **Structured Tracing** (`TraceManager`) | Records *what happened* — the full execution narrative | Redis List (persistent), Redis PubSub (real-time), JSONL (compliance fallback) |
| **Operational Metrics** (`metrics.py`) | Records *how it performed* — counters, histograms, and gauges | Prometheus (scrape endpoint on port 9090) |

Both layers are **non-blocking by design**. If Redis is unavailable, tracing falls back to JSONL. If `prometheus-client` is not installed, metrics become silent no-ops. Neither failure will crash your agent.

---

## Structured Tracing

### TraceManager

`TraceManager` is the framework's flight data recorder. It is instantiated automatically by the kernel for each workflow step and receives events for the lifetime of that step.

```python
from jarviscore.telemetry import TraceManager

tracer = TraceManager(
    workflow_id="wf-abc123",
    step_id="step-001",
    redis_store=redis_store,   # optional — omit to use JSONL-only mode
    trace_dir="traces",        # directory for JSONL fallback files
)
```

### Event Output Channels

Every event emitted through `TraceManager.log_event()` is written to up to three places simultaneously:

**1. Redis List (persistent)**
```
Key: traces:{workflow_id}:{step_id}
```
Suitable for replay, post-mortem debugging, and audit log retention. Survives process restarts.

**2. Redis PubSub (real-time)**
```
Channel: trace_events:{workflow_id}
```
Subscribe from a dashboard, alerting system, or log aggregator to receive events as they happen.

**3. JSONL file (compliance fallback)**
```
Path: {trace_dir}/{workflow_id}_{step_id}.jsonl
```
Written even when Redis is unavailable. Each line is a self-contained JSON event — parseable with any standard tooling.

### Trace Event Shape

Every event has the same envelope:

```json
{
  "workflow_id": "wf-abc123",
  "step_id": "step-001",
  "timestamp": "2026-05-01T17:00:00.000000+00:00",
  "type": "tool_start",
  "data": {
    "tool": "slack_send_message_v1",
    "params": { "channel": "#alerts", "text": "Deploy complete" }
  }
}
```

### Event Types

All event types are defined in `TraceEventType` (a typed `str` enum). The full set:

#### Workflow Lifecycle
| Event | When emitted |
|---|---|
| `workflow_start` | Workflow begins; includes `step_count` |
| `workflow_complete` | Workflow finishes; includes `status` and `summary` |

#### Step Execution
| Event | When emitted |
|---|---|
| `step_claimed` | An agent claims a step from the queue |
| `step_complete` | Step finishes successfully |
| `step_failed` | Step terminates with an unrecoverable error |

#### Kernel Cognition
| Event | When emitted |
|---|---|
| `thinking` | Kernel or subagent logs a reasoning step |
| `kernel_delegate` | Kernel dispatches work to a subagent |
| `subagent_yield` | Subagent returns control and requests human input |

#### Tool Execution
| Event | When emitted |
|---|---|
| `tool_start` | Tool invocation begins; includes tool name and parameters |
| `tool_result` | Tool invocation completes; includes result preview or error |

#### LLM Interaction
| Event | When emitted |
|---|---|
| `llm_request` | Outgoing request to an LLM provider; includes provider, model, prompt preview |
| `llm_response` | LLM response received; includes latency, input tokens, output tokens |

#### Mailbox
| Event | When emitted |
|---|---|
| `mailbox_send` | Agent sends a message to another agent |
| `mailbox_receive` | Agent reads messages from its inbox |

#### HITL
| Event | When emitted |
|---|---|
| `hitl_task_created` | A human review task is created |
| `hitl_waiting` | Kernel enters wait state for human input |
| `hitl_response_received` | Human provides a response |
| `hitl_resolved` | HITL task is closed with an outcome |

#### Infrastructure
| Event | When emitted |
|---|---|
| `context_snapshot` | Periodic capture of the context store state |
| `error_recovery` | Automatic recovery action is taken after an error |

### Emitting Events Manually

The kernel handles all standard events automatically. If you are building a custom subagent or tool, you can emit custom events directly:

```python
# Convenience methods — the recommended approach
tracer.log_tool_start("my_custom_tool", params={"key": "value"})
tracer.log_tool_result("my_custom_tool", result="Done")
tracer.log_thinking("Evaluating whether the output meets the acceptance criteria")

# Raw event — for custom types not covered by convenience methods
tracer.log_event("my_custom_event", data={"detail": "something happened"})
```

### Consuming Traces

**Live stream (Redis PubSub):**
```python
import redis, json

r = redis.Redis()
ps = r.pubsub()
ps.subscribe("trace_events:wf-abc123")

for message in ps.listen():
    if message["type"] == "message":
        event = json.loads(message["data"])
        print(event["type"], event["data"])
```

**Replay from JSONL:**
```bash
# All events for a workflow
cat traces/wf-abc123_step-001.jsonl | jq .

# Filter for tool events only
cat traces/wf-abc123_step-001.jsonl | jq 'select(.type | startswith("tool_"))'

# LLM cost summary
cat traces/*.jsonl | jq 'select(.type == "llm_response") | .data.latency_ms' | awk '{sum+=$1} END {print "Total latency:", sum, "ms"}'
```

---

## Operational Metrics (Prometheus)

### Installation

Prometheus metrics require the `prometheus-client` package. Without it, all metric calls are silent no-ops — your agent runs normally but no metrics are collected.

```bash
pip install "jarviscore-framework[prometheus]"
# or directly:
pip install prometheus-client
```

### Starting the Metrics Server

```python
from jarviscore.telemetry.metrics import start_prometheus_server

start_prometheus_server(port=9090)
```

Metrics are then available at `http://localhost:9090/metrics` for Prometheus to scrape.

### Available Metrics

#### LLM Metrics

| Metric | Type | Labels | Description |
|---|---|---|---|
| `jarviscore_llm_tokens_input_total` | Counter | `provider`, `model` | Total input tokens consumed |
| `jarviscore_llm_tokens_output_total` | Counter | `provider`, `model` | Total output tokens generated |
| `jarviscore_llm_cost_dollars_total` | Counter | `provider`, `model` | Total LLM cost in USD |
| `jarviscore_llm_request_duration_seconds` | Histogram | `provider`, `model` | LLM request latency |
| `jarviscore_llm_requests_total` | Counter | `provider`, `model`, `status` | Total LLM requests (success/error) |

#### Workflow & Step Metrics

| Metric | Type | Labels | Description |
|---|---|---|---|
| `jarviscore_workflow_steps_total` | Counter | `status` | Steps processed by outcome |
| `jarviscore_step_execution_duration_seconds` | Histogram | `status` | Step duration in seconds |
| `jarviscore_active_workflows` | Gauge | — | Currently running workflows |
| `jarviscore_active_steps` | Gauge | — | Currently executing steps |

#### Event Metrics

| Metric | Type | Labels | Description |
|---|---|---|---|
| `jarviscore_events_emitted_total` | Counter | `event_type` | Total trace events by type |

### Recording Metrics Manually

```python
from jarviscore.telemetry.metrics import record_llm_call, record_step_execution

# After an LLM call completes
record_llm_call(
    provider="anthropic",
    model="claude-opus-4-5",
    input_tokens=1500,
    output_tokens=800,
    cost=0.12,
    duration=2.3,
    success=True,
)

# After a workflow step completes
record_step_execution(duration=8.5, status="completed")
```

### Prometheus Configuration

Add a scrape target to your `prometheus.yml`:

```yaml
scrape_configs:
  - job_name: jarviscore
    static_configs:
      - targets: ["localhost:9090"]
    scrape_interval: 15s
```

### Grafana Dashboard

With the Prometheus scrape active, you can build dashboards around these queries:

```promql
# LLM cost rate over 1 hour
rate(jarviscore_llm_cost_dollars_total[1h])

# P95 step latency
histogram_quantile(0.95, rate(jarviscore_step_execution_duration_seconds_bucket[5m]))

# Error rate per model
rate(jarviscore_llm_requests_total{status="error"}[5m])
  / rate(jarviscore_llm_requests_total[5m])

# Active workflow count
jarviscore_active_workflows
```

---

## Exporting to External Stacks

### Datadog

Use the [Datadog Agent with OpenMetrics](https://docs.datadoghq.com/integrations/openmetrics/) to scrape the Prometheus endpoint:

```yaml
# datadog.yaml
instances:
  - openmetrics_endpoint: http://localhost:9090/metrics
    namespace: jarviscore
    metrics:
      - jarviscore_llm_.*
      - jarviscore_workflow_.*
      - jarviscore_active_.*
```

### Grafana Cloud / Mimir

Use `prometheus-remote-write` or the Grafana Agent to forward metrics directly without self-hosting Prometheus.

### Splunk / ELK

The JSONL trace files are the simplest integration point. Point a Filebeat or Splunk Universal Forwarder at the `traces/` directory — each line is already structured JSON, with `workflow_id`, `step_id`, `timestamp`, and `type` as top-level fields for indexing.

---

## Running Without Redis

JarvisCore observability works in three modes:

| Mode | Configuration | Behaviour |
|---|---|---|
| **Full** | Redis connected, `prometheus-client` installed | All three trace channels active; Prometheus metrics collected |
| **JSONL-only** | No Redis | Traces written to JSONL files only; no real-time stream |
| **Local dev** | No Redis, no `prometheus-client` | JSONL traces only; metrics are silent no-ops |

No configuration flag is needed — the system detects what is available at runtime and degrades gracefully.
