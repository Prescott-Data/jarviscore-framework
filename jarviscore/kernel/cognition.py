"""
6B: AgentCognitionManager — Budget tracking, phase detection, and safety guards.

Tracks tool usage against the lease budget, detects cognitive phases,
catches spinning (same tool 3+ times in a row), and enforces a cognitive
gate (can't call done() without having taken any action).

Added (dogfooding Gap #4 + #9):
  ConvergenceGovernor  — detects stall conditions across:
      - same-tool streak          (same tool N times consecutively)
      - equivalent-outcome streak (same semantic result from different calls)
      - stagnant turns            (no meaningful progress score for N turns)
  FailureLedger        — fingerprints (tool, params) pairs and guards against
      repeating the same failing action within a session. Optionally persists
      the guard across sessions via Redis (same pattern as integration-agent).

  Pattern sourced from integration-agent main:
      src/agent/capabilities/base.py (_convergence_policy, _evaluate_convergence,
      _record_failure, _has_recent_repeat_failure)
"""

import hashlib
import json
import logging
import os
import re
import time
from collections import deque
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from .lease import ExecutionLease

logger = logging.getLogger(__name__)


class AgentPhase(str, Enum):
    """Cognitive phase of the agent within a single dispatch."""
    DISCOVERY = "discovery"
    ANALYSIS = "analysis"
    IMPLEMENTATION = "implementation"
    COMPLETION = "completion"


# Tool classification sets
THINKING_TOOLS = frozenset({
    "web_search",
    "extract_page",
    "analyze",
    "get_context",
    "inspect_error",
    "scan_peers",
    "read_mailbox",
})

ACTION_TOOLS = frozenset({
    "generate_code",
    "validate_code",
    "fix_code",
    "execute_code",
    "send_message",
    "send_mailbox",
    "broadcast",
    "done",
})

# (Legacy _SPIN_THRESHOLD and _PARALYSIS_THRESHOLD removed in Phase 2.
#  The ConvergenceGovernor handles all stall detection now.)

# Convergence governor defaults (all env-overridable)
_CONV_MAX_STAGNANT_TURNS = int(os.getenv("CONVERGENCE_MAX_STAGNANT_TURNS", "6"))
_CONV_MAX_SAME_TOOL_STREAK = int(os.getenv("CONVERGENCE_MAX_SAME_TOOL_STREAK", "5"))
_CONV_MAX_EQUIV_STREAK = int(os.getenv("CONVERGENCE_MAX_EQUIVALENT_ACTION_STREAK", "4"))
_CONV_MIN_PROGRESS_SCORE = float(os.getenv("CONVERGENCE_MIN_PROGRESS_SCORE", "1.0"))
_CONV_STALL_ACTION = os.getenv("CONVERGENCE_STALL_ACTION", "yield").strip().lower()

# Failure guard TTL (in-process guard; Redis uses its own TTL)
_FAILURE_GUARD_HORIZON_SECONDS = int(os.getenv("FAILURE_GUARD_HORIZON_SECONDS", "1800"))
# Whether unclassifiable failures block retries. "guard" (default, historical)
# treats UNKNOWN as permanent; "skip" treats it as weak evidence and allows
# retries — an error we could not classify is thin grounds for a 30-min block.
_FAILURE_GUARD_UNKNOWN = os.getenv("FAILURE_GUARD_UNKNOWN", "guard").strip().lower()

# HTTP-ish status codes → failure class, for structured classification.
_STATUS_CODE_CLASSES = {
    401: "AUTH_UNAUTHORIZED",
    403: "AUTH_FORBIDDEN",
    404: "NOT_FOUND",
    408: "TIMEOUT",
    429: "RATE_LIMIT",
}


# ─────────────────────────────────────────────────────────────────────────────
# ConvergenceGovernor
# ─────────────────────────────────────────────────────────────────────────────

class ConvergenceGovernor:
    """
    Detects stall conditions that indicate an agent is no longer making progress.

    Three independent stall signals (any one triggers a stall verdict):
    1. same_tool_streak    — same tool called N times consecutively
    2. equivalent_streak   — same semantic outcome N times (different calls OK)
    3. stagnant_turns      — no meaningful progress score for N consecutive turns

    Pattern from integration-agent:
        src/agent/capabilities/base.py :: _convergence_policy + _evaluate_convergence
    """

    def __init__(
        self,
        max_same_tool_streak: int = _CONV_MAX_SAME_TOOL_STREAK,
        max_equiv_streak: int = _CONV_MAX_EQUIV_STREAK,
        max_stagnant_turns: int = _CONV_MAX_STAGNANT_TURNS,
        min_progress_score: float = _CONV_MIN_PROGRESS_SCORE,
        stall_action: str = _CONV_STALL_ACTION,
    ) -> None:
        self.max_same_tool_streak = max_same_tool_streak
        self.max_equiv_streak = max_equiv_streak
        self.max_stagnant_turns = max_stagnant_turns
        self.min_progress_score = min_progress_score
        self.stall_action = stall_action if stall_action in {"yield", "fail"} else "yield"

        # Mutable governor state
        self._same_tool_streak: int = 0
        self._last_tool: Optional[str] = None
        self._equiv_streak: int = 0
        self._last_outcome_sig: Optional[str] = None
        self._stagnant_turns: int = 0
        self._turn: int = 0
        self._last_verdict: Optional[Dict[str, Any]] = None

    @staticmethod
    def _progress_score(tool_output: Any) -> float:
        """
        Estimate meaningful progress from a tool result.
        Higher score = more progress. 0 = no progress (error / empty).
        """
        if tool_output is None:
            return 0.0
        if isinstance(tool_output, str):
            return 0.5 if tool_output.strip() else 0.0
        if not isinstance(tool_output, dict):
            return 0.25

        status = str(tool_output.get("status", "")).lower()
        if status in {"error", "failed", "blocked"} or tool_output.get("error"):
            return 0.0

        score = 0.0
        if status in {"success", "completed", "done"} or tool_output.get("success") is True:
            score += 1.0
        content = tool_output.get("content") or tool_output.get("output")
        if isinstance(content, str) and content.strip():
            score += 1.5
        if isinstance(tool_output.get("results"), list):
            score += min(1.5, len(tool_output["results"]) * 0.2)
        return score

    @staticmethod
    def _outcome_signature(tool_name: str, tool_output: Any) -> str:
        """
        Canonical signature of a (tool, result) pair for detecting
        semantically equivalent repeated outcomes.
        """
        if not isinstance(tool_output, dict):
            return f"{tool_name}:{str(tool_output)[:120]}"
        stable: Dict[str, Any] = {"tool": tool_name}
        for key in ("status", "success", "error"):
            if key in tool_output:
                stable[key] = tool_output[key]
        results = tool_output.get("results")
        if isinstance(results, list):
            stable["results_count"] = len(results)
        content = tool_output.get("content") or tool_output.get("output")
        if isinstance(content, str):
            stable["content_len"] = len(content)
        return json.dumps(stable, sort_keys=True, default=str)[:300]

    def evaluate(
        self,
        tool_name: str,
        tool_output: Any,
    ) -> Optional[Dict[str, Any]]:
        """
        Evaluate one tool call and return a stall verdict dict if stall is detected.

        Returns:
            None if no stall.
            {"action": "yield"|"fail", "reason": str, "typed_outcome": str} on stall.
        """
        self._turn += 1

        # 1. Same-tool streak
        if self._last_tool == tool_name:
            self._same_tool_streak += 1
        else:
            self._same_tool_streak = 1
        self._last_tool = tool_name

        # 2. Equivalent-outcome streak
        sig = self._outcome_signature(tool_name, tool_output)
        if self._last_outcome_sig == sig:
            self._equiv_streak += 1
        else:
            self._equiv_streak = 1
        self._last_outcome_sig = sig

        # 3. Stagnant turns
        score = self._progress_score(tool_output)
        if score >= self.min_progress_score:
            self._stagnant_turns = 0
        else:
            self._stagnant_turns += 1

        # Check stall conditions
        tripped: List[str] = []
        if self._same_tool_streak >= self.max_same_tool_streak:
            tripped.append(f"same_tool_streak={self._same_tool_streak} ({tool_name!r})")
        if self._equiv_streak >= self.max_equiv_streak:
            tripped.append(f"equivalent_outcome_streak={self._equiv_streak}")
        if self._stagnant_turns >= self.max_stagnant_turns:
            tripped.append(f"stagnant_turns={self._stagnant_turns}")

        if not tripped:
            self._last_verdict = None
            return None

        reason = (
            f"CONVERGENCE_STALL: no meaningful progress on turn {self._turn} "
            f"({', '.join(tripped)})."
        )
        typed_outcome = (
            "YIELD_CONVERGENCE_STALL" if self.stall_action == "yield"
            else "FAIL_CONVERGENCE_STALL"
        )
        verdict = {"action": self.stall_action, "reason": reason, "typed_outcome": typed_outcome}
        self._last_verdict = verdict
        return verdict

    def check_stall_verdict(self) -> Optional[Dict[str, Any]]:
        """Return the cached stall verdict from the most recent evaluate() call.

        This avoids double-evaluation — callers can check the verdict
        without re-running evaluate() and double-counting streaks.
        """
        return self._last_verdict

    def get_intervention(self) -> Optional[str]:
        """Return a coaching message if the agent's trajectory suggests it
        should reconsider its approach. Uses informational tone — the agent
        decides what to do with the signal."""
        if self._same_tool_streak >= self.max_same_tool_streak:
            return (
                f"You have called '{self._last_tool}' {self._same_tool_streak} times "
                f"consecutively. Each call returned similar results. Consider: "
                f"(1) trying a different tool, (2) adjusting your parameters, or "
                f"(3) synthesizing the results you already have."
            )
        if self._equiv_streak >= self.max_equiv_streak:
            return (
                f"Your last {self._equiv_streak} tool calls produced equivalent "
                f"outcomes. A different approach may yield new information, or you "
                f"may already have what you need to produce a result."
            )
        if self._stagnant_turns >= self.max_stagnant_turns:
            return (
                f"{self._stagnant_turns} consecutive turns without new results. "
                f"Consider stepping back to re-evaluate your strategy, or "
                f"synthesize what you have into a partial result."
            )
        return None

    @property
    def state(self) -> Dict[str, Any]:
        """Snapshot of governor state for logging."""
        return {
            "turn": self._turn,
            "same_tool_streak": self._same_tool_streak,
            "last_tool": self._last_tool,
            "equiv_streak": self._equiv_streak,
            "stagnant_turns": self._stagnant_turns,
        }


# ─────────────────────────────────────────────────────────────────────────────
# FailureLedger
# ─────────────────────────────────────────────────────────────────────────────

class FailureLedger:
    """
    Fingerprints failing (tool, params) pairs and guards against retrying them.

    Each failure is fingerprinted as SHA-256(tool_name + canonical_params_json).
    If the same fingerprint fails within FAILURE_GUARD_HORIZON_SECONDS:
      - The in-process ledger blocks it immediately.
      - If a redis_store is attached, the guard is also indexed cross-session
        (same pattern as integration-agent RedisContextStore.index_failure_event).

    Usage:
        ledger = FailureLedger()
        fingerprint = ledger.fingerprint("web_search", {"query": "AML trends"})
        if ledger.is_guarded(fingerprint):
            # Skip — we already know this fails
        ...
        ledger.record("web_search", {"query": "AML trends"}, error="Timeout")

    Pattern from integration-agent:
        src/agent/capabilities/base.py :: _record_failure + _has_recent_repeat_failure
    """

    _MAX_LEDGER_ENTRIES = 50

    def __init__(
        self,
        agent_id: str = "unknown",
        workflow_id: str = "unknown",
        redis_store=None,
        horizon_seconds: int = _FAILURE_GUARD_HORIZON_SECONDS,
    ) -> None:
        self.agent_id = agent_id
        self.workflow_id = workflow_id
        self.redis_store = redis_store
        self.horizon_seconds = horizon_seconds
        self._ledger: List[Dict[str, Any]] = []

    @staticmethod
    def fingerprint(tool_name: str, params: Dict[str, Any]) -> str:
        """SHA-256 of canonical (tool_name, params) pair."""
        try:
            payload = json.dumps(params or {}, sort_keys=True, default=str, separators=(",", ":"))
        except Exception:
            payload = str(params or {})
        return hashlib.sha256(f"{tool_name}:{payload}".encode("utf-8")).hexdigest()

    @staticmethod
    def _classify_error(error_text: str, output: Any = None) -> str:
        """Classify a failure — structured signals first, prose last.

        Classification decides retryability (TIMEOUT/NETWORK are never
        guarded), so it must prefer machine-readable evidence over substring
        sniffing (issue #60):

        1. output["error_type"] — an explicit class from the tool wins outright
        2. output["status_code"] / output["code"] — numeric HTTP-ish codes
        3. Prose heuristics — word-boundary matched numeric codes, so
           "1404 rows" never reads as a 404
        """
        # 1. Explicit class from the tool
        if isinstance(output, dict):
            explicit = output.get("error_type")
            if isinstance(explicit, str) and explicit.strip():
                return explicit.strip().upper()
            # 2. Numeric status code
            for key in ("status_code", "code"):
                code = output.get(key)
                try:
                    code = int(code)
                except (TypeError, ValueError):
                    continue
                if code in _STATUS_CODE_CLASSES:
                    return _STATUS_CODE_CLASSES[code]
                if code >= 500:
                    return "NETWORK"

        # 3. Prose heuristics (fallback only)
        text = str(error_text).lower()

        def _code(n: str) -> bool:
            return bool(re.search(rf"\b{n}\b", text))

        if _code("401") or "unauthorized" in text:
            return "AUTH_UNAUTHORIZED"
        if _code("403") or "forbidden" in text:
            return "AUTH_FORBIDDEN"
        if _code("429") or "rate limit" in text:
            return "RATE_LIMIT"
        if "timeout" in text or "timed out" in text:
            return "TIMEOUT"
        if "network" in text or "connection" in text or "dns" in text:
            return "NETWORK"
        if "schema" in text or "validation" in text:
            return "SCHEMA_VALIDATION"
        if "not found" in text or _code("404"):
            return "NOT_FOUND"
        return "UNKNOWN"

    def record(
        self,
        tool_name: str,
        params: Dict[str, Any],
        error: Optional[str] = None,
        output: Any = None,
    ) -> str:
        """
        Record a failure and return the fingerprint.

        The fingerprint is returned so callers can log it.
        The ledger is capped at _MAX_LEDGER_ENTRIES (oldest dropped).
        If redis_store is attached, the failure is also indexed there.
        """
        fp = self.fingerprint(tool_name, params)
        error_type = self._classify_error(error or str(output or ""), output=output)
        entry: Dict[str, Any] = {
            "ts": time.time(),
            "tool": tool_name,
            "fingerprint": fp,
            "error_type": error_type,
            "error": str(error or output or "")[:500],
        }
        self._ledger.append(entry)
        # Keep bounded
        if len(self._ledger) > self._MAX_LEDGER_ENTRIES:
            self._ledger = self._ledger[-self._MAX_LEDGER_ENTRIES:]

        # Cross-session persistence via Redis (optional)
        if self.redis_store and hasattr(self.redis_store, "index_failure_event"):
            try:
                self.redis_store.index_failure_event(
                    tenant_id="global",
                    workflow_id=str(self.workflow_id),
                    agent_role=str(self.agent_id),
                    tool=str(tool_name),
                    fingerprint=str(fp),
                    error_type=str(error_type),
                    error_message=str(entry["error"]),
                    metadata={},
                )
            except Exception as exc:
                logger.debug(f"[FailureLedger] Redis index_failure_event failed: {exc}")

        return fp

    def is_guarded(self, fp: str) -> bool:
        """
        Return True if this fingerprint has failed recently and should not be retried.

        Checks Redis cross-session guard first (if attached), then in-process ledger.
        Transient failures (TIMEOUT, NETWORK) are NOT guarded — they may succeed
        on retry. UNKNOWN failures follow FAILURE_GUARD_UNKNOWN ("guard", the
        historical default, or "skip" — an error we could not classify is weak
        evidence for a 30-minute block).
        """
        # Redis cross-session check — keyed exactly as record() writes it
        # (issue #60: this used to query workflow_id="unknown" while record()
        # indexed under the real workflow id, so the cross-session guard
        # could never match what was written).
        if self.redis_store and hasattr(self.redis_store, "has_failure_guard"):
            try:
                if self.redis_store.has_failure_guard(
                    "global", str(self.workflow_id), fp
                ):
                    return True
            except Exception as exc:
                logger.warning(
                    "[FailureLedger] Redis failure guard unavailable; using in-process guard only: %s",
                    exc,
                )

        # In-process ledger check
        now = time.time()
        skip_types = {"TIMEOUT", "NETWORK"}
        if _FAILURE_GUARD_UNKNOWN == "skip":
            skip_types = skip_types | {"UNKNOWN"}
        for entry in reversed(self._ledger[-20:]):
            if entry.get("fingerprint") != fp:
                continue
            ts = entry.get("ts")
            if not isinstance(ts, (int, float)):
                continue
            if (now - float(ts)) > self.horizon_seconds:
                continue
            # Don't guard transient failures — they might succeed next time
            if entry.get("error_type") in skip_types:
                continue
            return True
        return False

    def render_block(self) -> str:
        """
        Render the failure ledger as a context block for injection into the LLM prompt.

        Format:
            ## FAILURE MEMORY (Do Not Repeat Blindly)
            - web_search -> TIMEOUT: Connection timed out\n...
        """
        if not self._ledger:
            return ""
        recent = self._ledger[-5:]
        lines = ["## FAILURE MEMORY (Do Not Repeat Blindly)"]
        for entry in recent:
            lines.append(
                f"- {entry.get('tool')} → {entry.get('error_type')}: "
                f"{str(entry.get('error', ''))[:160]}"
            )
        lines.append(
            "Rule: if tool+params already failed recently (non-transient), "
            "choose a different tool or approach instead of retrying blindly."
        )
        return "\n".join(lines)

    @property
    def recent_failures(self) -> List[Dict[str, Any]]:
        """Last N ledger entries (read-only copy)."""
        return list(self._ledger[-20:])


# ─────────────────────────────────────────────────────────────────────────────
# AgentCognitionManager  (updated to compose ConvergenceGovernor + FailureLedger)
# ─────────────────────────────────────────────────────────────────────────────

class AgentCognitionManager:
    """
    Tracks cognitive budget, phase transitions, and convergence.

    Usage:
        cognition = AgentCognitionManager(lease)
        cognition.track_usage("web_search", tokens=500)
        stall = cognition.check_stall_verdict()
        if stall:
            # Agent is stalling — inject coaching or escalate
        if not cognition.should_continue():
            # Budget exhausted — stop
    """

    def __init__(
        self,
        lease: ExecutionLease,
        agent_id: str = "unknown",
        workflow_id: str = "unknown",
        redis_store=None,
    ):
        self.lease = lease
        self._tool_history: List[str] = []
        self._recent_tools: deque = deque(maxlen=6)  # diagnostic window
        self._has_acted: bool = False
        self._phase: AgentPhase = AgentPhase.DISCOVERY
        self._done_called: bool = False
        self._thinking_only_streak: int = 0

        # Gap #4 — Convergence Governor
        self.convergence = ConvergenceGovernor()

        # Gap #9 — Failure Ledger
        self.failures = FailureLedger(
            agent_id=agent_id,
            workflow_id=workflow_id,
            redis_store=redis_store,
        )

    def classify_tool(self, tool_name: str) -> str:
        """
        Classify a tool as 'thinking' or 'action'.

        Unknown tools default to 'action' (conservative — charges action budget).
        """
        if tool_name in THINKING_TOOLS:
            return "thinking"
        return "action"

    def track_usage(
        self,
        tool_name: str,
        tokens: int = 0,
        tool_output: Any = None,
    ) -> None:
        """
        Record a tool invocation and charge tokens to the appropriate budget.

        Args:
            tool_name: Name of the tool invoked
            tokens: Tokens consumed by this invocation
            tool_output: Result from the tool (used by ConvergenceGovernor)
        """
        phase = self.classify_tool(tool_name)
        if tokens > 0:
            self.lease.consume(tokens, phase)

        self._tool_history.append(tool_name)
        self._recent_tools.append(tool_name)

        if phase == "action" and tool_name != "done":
            self._has_acted = True
            self._thinking_only_streak = 0
        elif phase == "thinking":
            self._thinking_only_streak += 1
        else:
            self._thinking_only_streak = 0

        if tool_name == "done":
            self._done_called = True

        # Feed the Convergence Governor
        if tool_name != "done":
            self.convergence.evaluate(tool_name, tool_output)

        # Update phase
        self._update_phase(tool_name)

    def _update_phase(self, tool_name: str) -> None:
        """Update cognitive phase based on budget consumption and tool usage."""
        if self._done_called:
            self._phase = AgentPhase.COMPLETION
            return

        if self._has_acted:
            self._phase = AgentPhase.IMPLEMENTATION
            return

        thinking_pct = (
            self.lease.thinking_used / self.lease.thinking_budget
            if self.lease.thinking_budget > 0
            else 0.0
        )

        if thinking_pct >= 0.6:
            self._phase = AgentPhase.IMPLEMENTATION
        elif thinking_pct >= 0.3:
            self._phase = AgentPhase.ANALYSIS
        else:
            self._phase = AgentPhase.DISCOVERY

    @property
    def phase(self) -> AgentPhase:
        """Current cognitive phase."""
        return self._phase

    def should_continue(self) -> bool:
        """Return True if the agent should keep running (budget remains, not done)."""
        if self._done_called:
            return False
        return not self.lease.is_expired()

    def detect_spinning(self, tool_name: str) -> bool:
        """Legacy spinning check — DEPRECATED.

        Use check_stall_verdict() instead, which provides richer
        diagnostics via the ConvergenceGovernor.

        Kept for backward compatibility with existing tests.
        """
        if len(self._recent_tools) < 3:
            return False
        return all(t == tool_name for t in list(self._recent_tools)[-3:])

    def detect_premature_done(self, has_acted: bool = None) -> bool:
        """
        Detect if done() is being called too early.

        Returns True if:
        - Still in DISCOVERY phase (haven't done enough research)
        - No action tools have been called (nothing was actually done)
        """
        acted = has_acted if has_acted is not None else self._has_acted
        if self._phase == AgentPhase.DISCOVERY:
            return True
        if not acted:
            return True
        return False

    def get_intervention(self) -> Optional[str]:
        """
        Return a coaching message if the agent should reconsider its approach.

        Priority order (highest first):
        1. Budget exhaustion (thinking 80%+ used, nothing produced yet)
        2. Convergence Governor coaching (stall / same-tool / equiv-outcome)
        3. Low remaining budget

        Returns None if no intervention is needed.
        """
        # 1. Nudge when thinking budget mostly consumed without output
        thinking_pct = (
            self.lease.thinking_used / self.lease.thinking_budget
            if getattr(self.lease, "thinking_budget", 0) > 0
            else 0.0
        )
        if thinking_pct >= 0.80 and not self._has_acted:
            return (
                "You have used most of your research budget without producing "
                "output yet. Focus on synthesizing what you've gathered so far "
                "into a clear result."
            )

        # 2. Convergence Governor — single source of truth for stall detection
        conv_warning = self.convergence.get_intervention()
        if conv_warning:
            return conv_warning

        # 3. Low budget awareness
        total_remaining = self.lease.remaining_total()
        total_budget = self.lease.max_total_tokens
        if total_budget > 0 and total_remaining / total_budget < 0.10:
            return (
                f"About {total_remaining} tokens remaining "
                f"({total_remaining / total_budget:.0%} of budget). "
                f"Consider wrapping up with what you have."
            )

        return None

    # ── Failure Ledger convenience pass-throughs ──────────────────────────────

    def record_failure(
        self,
        tool_name: str,
        params: Dict[str, Any],
        error: Optional[str] = None,
        output: Any = None,
    ) -> str:
        """Record a tool failure. Returns the fingerprint."""
        return self.failures.record(tool_name, params, error=error, output=output)

    def is_repeat_failure(
        self, tool_name: str, params: Dict[str, Any]
    ) -> bool:
        """Return True if this (tool, params) pair is guarded against retry."""
        fp = FailureLedger.fingerprint(tool_name, params)
        return self.failures.is_guarded(fp)

    def failure_memory_block(self) -> str:
        """Render the failure ledger as a prompt-injection block."""
        return self.failures.render_block()

    # ── Convergence Governor convenience pass-through ─────────────────────────

    def evaluate_convergence(
        self, tool_name: str, tool_output: Any
    ) -> Optional[Dict[str, Any]]:
        """
        Evaluate for stall (called automatically by track_usage).
        Can also be called explicitly if caller wants the stall verdict object.
        """
        return self.convergence.evaluate(tool_name, tool_output)

    def check_stall_verdict(self) -> Optional[Dict[str, Any]]:
        """Return cached stall verdict from the most recent evaluate() call.

        This avoids re-running evaluate() and double-counting streaks.
        The verdict is set by track_usage() → convergence.evaluate().
        """
        return self.convergence.check_stall_verdict()

    def get_budget_summary(self) -> Dict[str, Any]:
        """Return a summary for prompt injection."""
        return {
            "phase": self._phase.value,
            "has_acted": self._has_acted,
            "tool_count": len(self._tool_history),
            "done_called": self._done_called,
            "thinking_only_streak": self._thinking_only_streak,
            "convergence": self.convergence.state,
            "failure_count": len(self.failures.recent_failures),
            "lease": self.lease.summary(),
        }

    @property
    def tool_history(self) -> List[str]:
        """List of all tools invoked (in order)."""
        return list(self._tool_history)

    @property
    def has_acted(self) -> bool:
        """Whether any action tool (excluding done) has been called."""
        return self._has_acted
