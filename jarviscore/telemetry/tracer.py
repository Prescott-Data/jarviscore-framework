"""
TraceManager for JarvisCore v1.0.0.

Three output channels for every trace event:
1. Redis List — persistent, replayable (key: traces:{workflow_id}:{step_id})
2. Redis PubSub — real-time streaming (channel: trace_events:{workflow_id})
3. JSONL file — fallback for compliance and offline replay

Ported from IA's tracing.py with improvements:
- Typed event enum (not free-form strings)
- Convenience methods for common events (thinking, tool, step, HITL)
- Non-blocking — failures are logged, never raised
- Works without Redis (JSONL-only mode)
"""

import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from .events import TraceEventType

logger = logging.getLogger(__name__)


class TraceManager:
    """
    Flight data recorder for agent execution.

    Every kernel turn, tool call, mailbox message, and HITL request
    is recorded through this manager. Consumers can:
    - Subscribe to Redis PubSub for live dashboards
    - Read Redis List for replay/debugging
    - Parse JSONL files for offline analysis
    """

    def __init__(
        self,
        workflow_id: str,
        step_id: str,
        redis_store=None,
        trace_dir: str = "traces",
    ):
        self.workflow_id = workflow_id
        self.step_id = step_id
        self._redis_store = redis_store
        self._trace_dir = trace_dir
        self._jsonl_path = os.path.join(
            trace_dir, f"{workflow_id}_{step_id}.jsonl"
        )

    # ------------------------------------------------------------------
    # Core: log_event
    # ------------------------------------------------------------------

    def log_event(self, event_type: str, data: Dict[str, Any] = None) -> None:
        """
        Emit a trace event to all three channels.

        Args:
            event_type: TraceEventType value or custom string
            data: Event payload (must be JSON-serializable)
        """
        event = {
            "workflow_id": self.workflow_id,
            "step_id": self.step_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "type": event_type,
            "data": data or {},
        }

        # Channel 1: Redis List (persistent)
        # Channel 2: Redis PubSub (real-time)
        if self._redis_store is not None:
            try:
                channel = f"trace_events:{self.workflow_id}"
                self._redis_store.publish_trace_event(channel, event)
            except Exception as e:
                logger.debug(f"Redis trace failed (non-blocking): {e}")

        # Channel 3: JSONL file (fallback)
        self._write_jsonl(event)

    # ------------------------------------------------------------------
    # Convenience: Kernel cognition
    # ------------------------------------------------------------------

    def log_thinking(self, thought: str) -> None:
        """Log kernel/subagent reasoning."""
        self.log_event(TraceEventType.THINKING, {"thought": thought})

    def log_kernel_delegate(
        self, subagent: str, task: str, model_tier: str = ""
    ) -> None:
        """Log kernel dispatching work to a subagent."""
        self.log_event(
            TraceEventType.KERNEL_DELEGATE,
            {"subagent": subagent, "task": task, "model_tier": model_tier},
        )

    def log_subagent_yield(self, subagent: str, reason: str) -> None:
        """Log subagent returning with a yield (needs human input)."""
        self.log_event(
            TraceEventType.SUBAGENT_YIELD,
            {"subagent": subagent, "reason": reason},
        )

    # ------------------------------------------------------------------
    # Convenience: Tool execution
    # ------------------------------------------------------------------

    def log_tool_start(self, tool_name: str, params: Dict = None) -> None:
        """Log tool invocation start."""
        self.log_event(
            TraceEventType.TOOL_START,
            {"tool": tool_name, "params": params or {}},
        )

    def log_tool_result(
        self, tool_name: str, result: Any = None, error: str = None
    ) -> None:
        """Log tool invocation result."""
        data = {"tool": tool_name}
        if error:
            data["error"] = error
        else:
            data["result_preview"] = str(result)[:500] if result else ""
        self.log_event(TraceEventType.TOOL_RESULT, data)

    # ------------------------------------------------------------------
    # Convenience: LLM interaction
    # ------------------------------------------------------------------

    def log_llm_request(
        self, provider: str, model: str, prompt_preview: str = ""
    ) -> None:
        """Log outgoing LLM request."""
        self.log_event(
            TraceEventType.LLM_REQUEST,
            {
                "provider": provider,
                "model": model,
                "prompt_preview": prompt_preview[:200],
            },
        )

    def log_llm_response(
        self,
        provider: str,
        model: str,
        latency_ms: float,
        input_tokens: int = 0,
        output_tokens: int = 0,
    ) -> None:
        """Log LLM response with timing and token usage."""
        self.log_event(
            TraceEventType.LLM_RESPONSE,
            {
                "provider": provider,
                "model": model,
                "latency_ms": round(latency_ms, 2),
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
            },
        )

    # ------------------------------------------------------------------
    # Convenience: Step lifecycle
    # ------------------------------------------------------------------

    def log_step_claimed(self, agent_id: str) -> None:
        """Log step being claimed by an agent."""
        self.log_event(
            TraceEventType.STEP_CLAIMED,
            {"step_id": self.step_id, "agent_id": agent_id},
        )

    def log_step_complete(
        self, step_id: str, status: str, summary: str = ""
    ) -> None:
        """Log step completion."""
        self.log_event(
            TraceEventType.STEP_COMPLETE,
            {"step_id": step_id, "status": status, "summary": summary},
        )

    def log_step_failed(self, step_id: str, error: str) -> None:
        """Log step failure."""
        self.log_event(
            TraceEventType.STEP_FAILED,
            {"step_id": step_id, "error": error},
        )

    # ------------------------------------------------------------------
    # Convenience: Workflow lifecycle
    # ------------------------------------------------------------------

    def log_workflow_start(self, step_count: int = 0) -> None:
        """Log workflow start."""
        self.log_event(
            TraceEventType.WORKFLOW_START,
            {"workflow_id": self.workflow_id, "step_count": step_count},
        )

    def log_workflow_complete(self, status: str, summary: str = "") -> None:
        """Log workflow completion."""
        self.log_event(
            TraceEventType.WORKFLOW_COMPLETE,
            {"workflow_id": self.workflow_id, "status": status, "summary": summary},
        )

    # ------------------------------------------------------------------
    # Convenience: Mailbox
    # ------------------------------------------------------------------

    def log_mailbox_send(self, target: str, message_preview: str = "") -> None:
        """Log message sent to another agent."""
        self.log_event(
            TraceEventType.MAILBOX_SEND,
            {"target": target, "preview": message_preview[:200]},
        )

    def log_mailbox_receive(self, count: int) -> None:
        """Log messages received from mailbox."""
        self.log_event(
            TraceEventType.MAILBOX_RECEIVE,
            {"message_count": count},
        )

    # ------------------------------------------------------------------
    # Convenience: Context
    # ------------------------------------------------------------------

    def log_context_snapshot(self, fact_count: int, version: int) -> None:
        """Log periodic context state capture."""
        self.log_event(
            TraceEventType.CONTEXT_SNAPSHOT,
            {"fact_count": fact_count, "version": version},
        )

    # ------------------------------------------------------------------
    # Convenience: Error recovery
    # ------------------------------------------------------------------

    def log_error_recovery(self, error: str, action: str) -> None:
        """Log error recovery action taken."""
        self.log_event(
            TraceEventType.ERROR_RECOVERY,
            {"error": error, "recovery_action": action},
        )

    # ------------------------------------------------------------------
    # Convenience: HITL
    # ------------------------------------------------------------------

    def log_hitl_task_created(
        self, task_id: str, task_type: str, description: str
    ) -> None:
        """Log HITL task creation."""
        self.log_event(
            TraceEventType.HITL_TASK_CREATED,
            {"task_id": task_id, "type": task_type, "description": description},
        )

    def log_hitl_waiting(self, task_id: str, reason: str) -> None:
        """Log kernel entering wait state for human input."""
        self.log_event(
            TraceEventType.HITL_WAITING,
            {"task_id": task_id, "reason": reason},
        )

    def log_hitl_response_received(
        self, request_id: str, comment: str = ""
    ) -> None:
        """Log human response received."""
        self.log_event(
            TraceEventType.HITL_RESPONSE_RECEIVED,
            {"request_id": request_id, "comment": comment},
        )

    def log_hitl_resolved(self, request_id: str, outcome: str) -> None:
        """Log HITL task resolution."""
        self.log_event(
            TraceEventType.HITL_RESOLVED,
            {"request_id": request_id, "outcome": outcome},
        )

    # ------------------------------------------------------------------
    # Internal: JSONL writer
    # ------------------------------------------------------------------

    def _write_jsonl(self, event: Dict[str, Any]) -> None:
        """Append event to JSONL file (non-blocking)."""
        try:
            os.makedirs(os.path.dirname(self._jsonl_path), exist_ok=True)
            with open(self._jsonl_path, "a") as f:
                f.write(json.dumps(event) + "\n")
        except Exception as e:
            logger.debug(f"JSONL write failed (non-blocking): {e}")
