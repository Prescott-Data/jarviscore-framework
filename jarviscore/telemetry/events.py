"""
Trace Event Types for JarvisCore v1.0.0.

Every significant action in the framework emits a typed trace event.
These flow through TraceManager to Redis (real-time + persistent)
and JSONL (compliance fallback).

Event types cover:
- Workflow lifecycle (start, complete)
- Step execution (claimed, complete, failed)
- Kernel cognition (thinking, delegation)
- Tool execution (start, result)
- Mailbox communication (send, receive)
- Human-in-the-loop (created, waiting, response, resolved)
- Context snapshots (periodic state captures)
- Error recovery (fallback actions)

Ported from IA's tracing.py + CA's HITL events, unified into one enum.
"""

from enum import Enum


class TraceEventType(str, Enum):
    """Typed event categories emitted by kernel, subagents, and infrastructure."""

    # Workflow lifecycle
    WORKFLOW_START = "workflow_start"
    WORKFLOW_COMPLETE = "workflow_complete"

    # Step execution
    STEP_CLAIMED = "step_claimed"
    STEP_COMPLETE = "step_complete"
    STEP_FAILED = "step_failed"

    # Kernel cognition (OODA loop)
    THINKING = "thinking"
    KERNEL_DELEGATE = "kernel_delegate"
    SUBAGENT_YIELD = "subagent_yield"

    # Tool execution
    TOOL_START = "tool_start"
    TOOL_RESULT = "tool_result"

    # LLM interaction
    LLM_REQUEST = "llm_request"
    LLM_RESPONSE = "llm_response"

    # Mailbox communication
    MAILBOX_SEND = "mailbox_send"
    MAILBOX_RECEIVE = "mailbox_receive"

    # Context
    CONTEXT_SNAPSHOT = "context_snapshot"

    # Error handling
    ERROR_RECOVERY = "error_recovery"

    # Human-in-the-loop (HITL)
    HITL_TASK_CREATED = "hitl_task_created"
    HITL_WAITING = "hitl_waiting"
    HITL_RESPONSE_RECEIVED = "hitl_response_received"
    HITL_RESOLVED = "hitl_resolved"
