"""
Telemetry package for JarvisCore v1.0.0.

Provides three layers of observability:
- TraceManager: Event recording to Redis + JSONL
- TraceEventType: Typed event categories
- Prometheus metrics: Counters, histograms, gauges for LLM/workflow/events
"""

from .events import TraceEventType
from .tracer import TraceManager
from .metrics import (
    record_llm_call,
    record_step_execution,
    record_event,
    increment_active_workflows,
    decrement_active_workflows,
    increment_active_steps,
    decrement_active_steps,
    start_prometheus_server,
)

__all__ = [
    "TraceEventType",
    "TraceManager",
    "record_llm_call",
    "record_step_execution",
    "record_event",
    "increment_active_workflows",
    "decrement_active_workflows",
    "increment_active_steps",
    "decrement_active_steps",
    "start_prometheus_server",
]
