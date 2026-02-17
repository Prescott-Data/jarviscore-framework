"""
6D: Kernel — OODA-loop supervisor for AutoAgent execution.

The kernel replaces AutoAgent's linear pipeline (codegen → sandbox → repair)
with a supervised loop that:
1. Observes the task and context
2. Orients by selecting a subagent (coder, researcher, communicator)
3. Decides on lease budgets and model routing
4. Acts by dispatching to the subagent
5. Evaluates the result and loops if needed

Fast path: simple coding tasks skip full OODA and dispatch directly to coder.
"""

import logging
import time
from typing import Any, Dict, List, Optional

from jarviscore.context.truth import AgentOutput
from jarviscore.kernel.lease import ExecutionLease, ROLE_LEASE_PROFILES
from jarviscore.kernel.cognition import AgentCognitionManager
from jarviscore.kernel.state import KernelState
from jarviscore.kernel.hitl import AdaptiveHITLPolicy

logger = logging.getLogger(__name__)

# Keywords that suggest a task needs research before coding
_RESEARCH_KEYWORDS = frozenset({
    "find", "search", "look up", "investigate", "research",
    "what is", "how does", "explain", "analyze", "compare",
})

# Keywords that suggest a task is a communication/reporting task
_COMMUNICATION_KEYWORDS = frozenset({
    "send", "notify", "report", "summarize", "draft",
    "email", "message", "communicate", "format",
})


class Kernel:
    """
    OODA-loop supervisor for AutoAgent execution.

    The kernel manages the full lifecycle of a task:
    - Subagent selection (coder, researcher, communicator)
    - Lease budget allocation
    - Model routing (coding tier vs task tier)
    - Cognition tracking and safety guards
    - HITL escalation when needed
    - Result evaluation and retry decisions

    Usage:
        kernel = Kernel(
            llm_client=llm,
            sandbox=sandbox,
            config=config,
        )
        output = await kernel.execute(task="Calculate factorial of 10")
    """

    def __init__(
        self,
        llm_client,
        sandbox=None,
        code_registry=None,
        search_client=None,
        mailbox=None,
        redis_store=None,
        blob_storage=None,
        config: Optional[Dict] = None,
        hitl_policy: Optional[AdaptiveHITLPolicy] = None,
    ):
        self.llm_client = llm_client
        self.sandbox = sandbox
        self.code_registry = code_registry
        self.search_client = search_client
        self.mailbox = mailbox
        self.redis_store = redis_store
        self.blob_storage = blob_storage
        self.config = config or {}
        self.hitl_policy = hitl_policy

        # Optional auth manager (wired by AutoAgent in 6H)
        self.auth_manager = None

        # Subagent registry — populated lazily
        self._subagents: Dict[str, Any] = {}

    def _get_model_for_tier(self, tier: str) -> Optional[str]:
        """Resolve model name from tier using config.

        Checks generic settings first (coding_model, task_model),
        falls back to legacy claude-specific settings for backward compat.
        """
        if tier == "coding":
            return (self.config.get("coding_model")
                    or self.config.get("claude_coding_model")
                    or None)
        elif tier == "task":
            return (self.config.get("task_model")
                    or self.config.get("claude_task_model")
                    or None)
        return None

    def _classify_task(self, task: str, context: Optional[Dict] = None) -> str:
        """
        Classify a task into a subagent role.

        Returns: "coder", "researcher", or "communicator"
        """
        lower = task.lower()
        words = lower.split()

        # Check for communication keywords (word-level match to avoid
        # substring false positives like "format" in "information")
        for kw in _COMMUNICATION_KEYWORDS:
            kw_words = kw.split()
            if len(kw_words) == 1:
                if kw in words:
                    return "communicator"
            else:
                if kw in lower:
                    return "communicator"

        # Check for research keywords
        for kw in _RESEARCH_KEYWORDS:
            kw_words = kw.split()
            if len(kw_words) == 1:
                if kw in words:
                    return "researcher"
            else:
                if kw in lower:
                    return "researcher"

        # Default to coder (most common case)
        return "coder"

    def _create_subagent(self, role: str, agent_id: str):
        """Create a subagent instance for the given role."""
        from jarviscore.kernel.defaults import (
            CoderSubAgent,
            ResearcherSubAgent,
            CommunicatorSubAgent,
        )

        if role == "coder":
            return CoderSubAgent(
                agent_id=agent_id,
                llm_client=self.llm_client,
                sandbox=self.sandbox,
                code_registry=self.code_registry,
                redis_store=self.redis_store,
                blob_storage=self.blob_storage,
            )
        elif role == "researcher":
            return ResearcherSubAgent(
                agent_id=agent_id,
                llm_client=self.llm_client,
                search_client=self.search_client,
                code_registry=self.code_registry,
                redis_store=self.redis_store,
                blob_storage=self.blob_storage,
            )
        elif role == "communicator":
            return CommunicatorSubAgent(
                agent_id=agent_id,
                llm_client=self.llm_client,
                mailbox=self.mailbox,
                redis_store=self.redis_store,
                blob_storage=self.blob_storage,
            )
        else:
            raise ValueError(f"Unknown subagent role: {role}")

    async def execute(
        self,
        task: str,
        system_prompt: str = "",
        context: Optional[Dict] = None,
        agent_id: str = "kernel",
        max_dispatches: int = 3,
    ) -> AgentOutput:
        """
        Execute a task through the OODA loop.

        Args:
            task: Natural language task description
            system_prompt: System prompt from the AutoAgent
            context: Optional context (dependencies, previous results)
            agent_id: Agent identifier for tracking
            max_dispatches: Maximum subagent dispatches before giving up

        Returns:
            AgentOutput with the final result
        """
        start_time = time.time()
        dispatches: List[Dict[str, Any]] = []
        total_tokens = {"input": 0, "output": 0, "total": 0}
        total_cost = 0.0

        for dispatch_num in range(max_dispatches):
            # 1. OBSERVE + ORIENT: classify task and select subagent
            role = self._classify_task(task, context)
            logger.info(f"[Kernel] Dispatch {dispatch_num + 1}: task → {role}")

            # 2. DECIDE: create lease and resolve model
            lease = ExecutionLease.for_role(role)
            cognition = AgentCognitionManager(lease)
            model = self._get_model_for_tier(lease.model_tier)

            # Calculate max turns from lease
            max_turns = min(
                lease.emergency_turn_fuse,
                self.config.get("kernel_max_turns", 30),
            )

            # 3. ACT: create subagent and dispatch
            subagent = self._create_subagent(role, f"{agent_id}_{role}_{dispatch_num}")

            # Build enriched context with system prompt
            enriched_context = dict(context) if context else {}
            if system_prompt:
                enriched_context["system_prompt"] = system_prompt

            output = await subagent.run(
                task=task,
                context=enriched_context if enriched_context else None,
                max_turns=max_turns,
                model=model,
            )

            # Track costs
            meta = output.metadata or {}
            tokens = meta.get("tokens", {})
            total_tokens["input"] += tokens.get("input", 0)
            total_tokens["output"] += tokens.get("output", 0)
            total_tokens["total"] += tokens.get("total", 0)
            total_cost += meta.get("cost_usd", 0.0)

            dispatch_record = {
                "dispatch": dispatch_num + 1,
                "role": role,
                "status": output.status,
                "summary": output.summary,
                "model": model,
            }
            dispatches.append(dispatch_record)

            # 4. EVALUATE: check result
            if output.status == "success":
                return AgentOutput(
                    status="success",
                    payload=output.payload,
                    summary=output.summary,
                    trajectory=output.trajectory,
                    metadata={
                        "tokens": total_tokens,
                        "cost_usd": total_cost,
                        "dispatches": dispatches,
                        "elapsed_ms": (time.time() - start_time) * 1000,
                    },
                )

            if output.status == "yield":
                # HITL needed — pass through
                return AgentOutput(
                    status="yield",
                    payload=output.payload,
                    summary=output.summary,
                    trajectory=output.trajectory,
                    metadata={
                        "tokens": total_tokens,
                        "cost_usd": total_cost,
                        "dispatches": dispatches,
                        "yield_pending": True,
                    },
                )

            # Failure — check if we should retry with a different strategy
            logger.warning(
                f"[Kernel] Dispatch {dispatch_num + 1} failed: {output.summary}"
            )

            # Check HITL policy for escalation
            if self.hitl_policy:
                should_escalate, reason = self.hitl_policy.should_escalate(
                    reason_code="execution_failure",
                    confidence=0.3,
                    risk_score=0.5,
                )
                if should_escalate:
                    return AgentOutput(
                        status="yield",
                        summary=f"Escalated to human: {reason}",
                        trajectory=output.trajectory,
                        metadata={
                            "tokens": total_tokens,
                            "cost_usd": total_cost,
                            "dispatches": dispatches,
                            "yield_pending": True,
                            "escalation_reason": reason,
                        },
                    )

        # All dispatches exhausted
        elapsed = (time.time() - start_time) * 1000
        return AgentOutput(
            status="failure",
            summary=f"All {max_dispatches} dispatches failed",
            trajectory=[],
            metadata={
                "tokens": total_tokens,
                "cost_usd": total_cost,
                "dispatches": dispatches,
                "elapsed_ms": elapsed,
            },
        )
