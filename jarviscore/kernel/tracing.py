"""
JarvisCore Trace Manager — Real-time agent trace streaming.

Architecture:
  ┌──────────────────────────────────────────────────────────────┐
  │  OODA Loop (subagent.py)                                     │
  │    → log_thinking()  → log_tool_start/result()              │
  │    → log_llm_request/response()  → log_step_complete()      │
  └──────────────────┬───────────────────────────────────────────┘
                     │ TraceManager.log_event()
         ┌───────────┴──────────────┐
         ▼                          ▼
   Redis List                Redis PubSub channel
   traces:{wf}:{step}        trace_events:{workflow_id}
   (7-day TTL)               (real-time → SSE endpoint)
         │
         ▼
   File fallback: traces/{mission_id}.jsonl

Design choices (OSS-clean port from CA TraceManager):
  - All trace values are secret-scrubbed before writing
  - Redis failures are non-fatal (log + continue)
  - No dependencies beyond redis-py (optional) and stdlib
"""

import json
import logging
import os
import re
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class _NoOpTrace:
    """
    Silent no-op TraceManager used when Redis is unavailable and
    file tracing is disabled.  Keeps OODA loop call sites identical
    whether tracing is on or off.
    """

    def log_event(self, event_type: str, data: Dict[str, Any]) -> None:
        pass

    def log_thinking(self, thought: str) -> None:
        pass

    def log_tool_start(self, tool_name: str, args: Dict[str, Any]) -> None:
        pass

    def log_tool_result(
        self, tool_name: str, result: Any, error: Optional[str] = None
    ) -> None:
        pass

    def log_llm_request(self, system_preview: str, user_preview: str) -> None:
        pass

    def log_llm_response(self, content_preview: str, latency_ms: float) -> None:
        pass

    def log_step_complete(self, success: bool, summary: str) -> None:
        pass


class TraceManager:
    """
    Flight data recorder for JarvisCore agent execution.

    Emits structured events from every turn of the OODA loop so the UI
    can render a live "thinking" panel alongside chat responses.

    Event types emitted:
      step_start        — TraceManager created
      thinking          — agent THOUGHT block parsed
      tool_start        — tool call dispatched
      tool_result       — tool call completed (success or error)
      llm_request       — LLM API called
      llm_response      — LLM API returned
      step_complete     — DONE or YIELD emitted

    Storage:
      Redis List  traces:{workflow_id}:{step_id}  — queryable history (7d TTL)
      Redis PubSub trace_events:{workflow_id}      — real-time fan-out
      File        traces/{mission_id}.jsonl         — debug fallback

    Usage:
        trace = TraceManager(workflow_id="wf_abc", step_id="step_1")
        trace.log_thinking("I need to search for this term")
        trace.log_tool_start("web_search", {"query": "latest AI news"})
        trace.log_tool_result("web_search", {"results": [...]})
        trace.log_step_complete(True, "Found 5 relevant results")
    """

    def __init__(
        self,
        workflow_id: str,
        step_id: str,
        trace_dir: str = "traces",
        redis_client=None,
    ):
        self.workflow_id = workflow_id
        self.step_id = step_id
        self.mission_id = f"{workflow_id}:{step_id}"
        self.trace_dir = trace_dir
        self.trace_file = os.path.join(
            trace_dir, f"{self.mission_id.replace(':', '_')}.jsonl"
        )

        # Redis — accept injected client or init from env
        self.redis_client = redis_client
        if self.redis_client is None:
            self.redis_client = self._init_redis()

        os.makedirs(trace_dir, exist_ok=True)

        # Emit start event
        self.log_event(
            "step_start",
            {
                "workflow_id": workflow_id,
                "step_id": step_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        )

    # ──────────────────────────────────────────────────────────────────────
    # Redis init
    # ──────────────────────────────────────────────────────────────────────

    @staticmethod
    def _init_redis():
        """Try to connect to Redis. Returns None if unavailable."""
        redis_url = os.environ.get("REDIS_URL")
        if not redis_url:
            return None
        try:
            import redis as _redis
            client = _redis.Redis.from_url(redis_url, decode_responses=True)
            client.ping()
            return client
        except Exception as exc:
            logger.debug("TraceManager: Redis unavailable (%s) — file-only mode", exc)
            return None

    # ──────────────────────────────────────────────────────────────────────
    # Core write path
    # ──────────────────────────────────────────────────────────────────────

    def log_event(self, event_type: str, data: Dict[str, Any]) -> None:
        """
        Write a structured trace event to Redis (List + PubSub) and file.

        Redis PubSub is the real-time channel consumed by the SSE endpoint.
        The Redis List provides queryable history. The file is a debug fallback.
        """
        event = {
            "workflow_id": self.workflow_id,
            "step_id": self.step_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "type": event_type,
            "data": self._scrub(data),
        }
        event_json = json.dumps(event, default=str)

        # 1. Redis dual write: List + PubSub
        if self.redis_client:
            try:
                key = f"traces:{self.workflow_id}:{self.step_id}"
                channel = f"trace_events:{self.workflow_id}"
                pipe = self.redis_client.pipeline()
                pipe.rpush(key, event_json)
                pipe.publish(channel, event_json)   # real-time fan-out → SSE
                pipe.expire(key, 604_800)            # 7-day TTL
                pipe.execute()
            except Exception as exc:
                logger.debug("TraceManager: Redis write failed: %s", exc)

        # 2. File fallback
        try:
            with open(self.trace_file, "a", encoding="utf-8") as f:
                f.write(event_json + "\n")
        except Exception as exc:
            logger.debug("TraceManager: file write failed: %s", exc)

    # ──────────────────────────────────────────────────────────────────────
    # Secret scrubbing
    # ──────────────────────────────────────────────────────────────────────

    _SENSITIVE_KEYS = frozenset(
        {
            "authorization", "auth", "token", "access_token", "refresh_token",
            "id_token", "api_key", "secret", "password", "credentials",
            "private_key", "client_secret",
        }
    )
    _SECRET_PATTERN = re.compile(
        r"(?i)(authorization)\s*[:=]\s*bearer\s+[A-Za-z0-9\-._~+/]+=*|"
        r"(?i)(access_token|refresh_token|id_token|api_key|secret|password|token)\s*[:=]\s*['\"]?[^'\"\s,}]+"
    )

    def _scrub(self, value: Any) -> Any:
        """Recursively redact secrets from trace data."""
        if isinstance(value, dict):
            return {
                k: "***" if any(s in str(k).lower() for s in self._SENSITIVE_KEYS) else self._scrub(v)
                for k, v in value.items()
            }
        if isinstance(value, list):
            return [self._scrub(v) for v in value]
        if isinstance(value, str):
            return self._SECRET_PATTERN.sub(r"\1\2=***", value)
        return value

    # ──────────────────────────────────────────────────────────────────────
    # Semantic log helpers
    # ──────────────────────────────────────────────────────────────────────

    def log_thinking(self, thought: str) -> None:
        """Agent THOUGHT block — reasoning visible in the UI thinking panel."""
        self.log_event("thinking", {"thought": thought[:2000]})

    def log_tool_start(self, tool_name: str, args: Dict[str, Any]) -> None:
        """Tool call dispatched."""
        self.log_event(
            "tool_start",
            {"tool": tool_name, "args": self._scrub(args)},
        )

    def log_tool_result(
        self, tool_name: str, result: Any, error: Optional[str] = None
    ) -> None:
        """
        Tool call completed.

        success = True when error is None or empty string.
        Result is truncated to 2000 chars for the trace event.
        """
        has_error = bool(error) and str(error).strip() != ""
        payload: Dict[str, Any] = {
            "tool": tool_name,
            "result": str(self._scrub(result))[:2000] if result is not None else None,
            "error": self._scrub(error) if has_error else None,
            "success": not has_error,
        }
        # Surface screenshot_url if tool returned one (browser automation)
        if isinstance(result, dict):
            if result.get("screenshot_url"):
                payload["screenshot_url"] = result["screenshot_url"]
            elif result.get("screenshot_path"):
                payload["screenshot_path"] = result["screenshot_path"]
        self.log_event("tool_result", payload)

    def log_llm_request(self, system_preview: str, user_preview: str) -> None:
        """LLM API call dispatched."""
        self.log_event(
            "llm_request",
            {
                "system_preview": self._scrub(system_preview[:300]),
                "user_preview": self._scrub(user_preview[:500]),
            },
        )

    def log_llm_response(self, content_preview: str, latency_ms: float) -> None:
        """LLM API call returned."""
        self.log_event(
            "llm_response",
            {
                "content_preview": self._scrub(content_preview[:500]),
                "latency_ms": round(latency_ms, 1),
            },
        )

    def log_step_complete(self, success: bool, summary: str) -> None:
        """
        Step finished (DONE or YIELD).

        Fsyncs the trace file before returning so downstream trace readers
        (e.g. evaluation workers) see a fully committed log.
        """
        self.log_event("step_complete", {"success": success, "summary": summary[:1000]})
        # fsync — prevents race with evaluation workers that read the file immediately
        try:
            with open(self.trace_file, "a") as f:
                f.flush()
                os.fsync(f.fileno())
        except Exception:
            pass

    # ──────────────────────────────────────────────────────────────────────
    # History replay (for SSE catch-up on re-connect)
    # ──────────────────────────────────────────────────────────────────────

    def get_history(self, max_events: int = 200) -> List[Dict[str, Any]]:
        """
        Return all buffered trace events for this step.

        Used by the SSE endpoint to replay missed events on reconnect.
        Falls back to parsing the JSONL file if Redis is unavailable.
        """
        if self.redis_client:
            try:
                key = f"traces:{self.workflow_id}:{self.step_id}"
                raw_events = self.redis_client.lrange(key, -max_events, -1)
                return [json.loads(e) for e in raw_events]
            except Exception:
                pass
        # File fallback
        events = []
        try:
            with open(self.trace_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            events.append(json.loads(line))
                        except json.JSONDecodeError:
                            pass
        except FileNotFoundError:
            pass
        return events[-max_events:]


def create_noop_trace() -> _NoOpTrace:
    """Return a silent no-op trace when tracing is not needed."""
    return _NoOpTrace()
