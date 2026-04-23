"""
6D: Kernel — OODA-loop supervisor for AutoAgent execution.

The kernel replaces AutoAgent's linear pipeline (codegen → sandbox → repair)
with a supervised loop that:
1. Observes the task and context
2. Orients by selecting a subagent (coder, researcher, communicator)
3. Decides on lease budgets and model routing
4. Acts by dispatching to the subagent
5. Evaluates the result and loops if needed

The kernel owns:
- Subagent lifecycle (create, reuse, cleanup)
- Budget governance (lease creation, model routing)
- Memory management (UnifiedMemory creation, checkpoint/resume)
- Context management (ContextManager creation, budget config)
- Blocker detection and escalation
"""

import logging
import time
from typing import Any, Dict, List, Optional

from jarviscore.context.truth import AgentOutput
from jarviscore.context.context_manager import ContextManager, BudgetConfig
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

# Keywords that suggest a task requires a real browser (JS, auth, interactive UI)
_BROWSER_KEYWORDS = frozenset({
    "browser", "click", "navigate", "screenshot", "fill form",
    "login to", "log in to", "scrape", "automate", "playwright",
    "selenium", "headless", "web automation", "interact with",
})

# Minimum registry confidence to skip code generation
_REGISTRY_REUSE_SCORE_THRESHOLD = 2  # semantic_search score units


class Kernel:
    """
    OODA-loop supervisor for AutoAgent execution.

    The kernel manages the full lifecycle of a task:
    - Subagent selection (coder, researcher, communicator)
    - Lease budget allocation
    - Model routing (coding tier vs task tier)
    - Cognition tracking and safety guards
    - Memory and context management
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

        # Auth manager — Mesh-injected via requires_auth=True on agent class.
        # AutoAgent forwards it lazily at execute_task() time (because Mesh
        # injects _auth_manager AFTER setup() completes — see mesh.py:292-312).
        # Kernel uses it to resolve credentials before sandbox execution.
        self.auth_manager = None

        # Subagent cache — reuse within same workflow step
        self._subagent_cache: Dict[str, Any] = {}

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

        Respects `default_kernel_role` declared on the AutoAgent subclass first.
        This lets agents like Sentinel (always researcher) and Quill (always
        communicator) skip keyword guessing and route correctly every time.

        Returns: "coder", "researcher", "communicator", or "browser"
        """
        # Check for agent-declared default role (from enriched context set by kernel)
        if context and context.get("_agent_default_kernel_role"):
            return context["_agent_default_kernel_role"]

        lower = task.lower()
        words = lower.split()

        # Browser tasks take highest priority — real browser needed
        for kw in _BROWSER_KEYWORDS:
            kw_words = kw.split()
            if len(kw_words) == 1:
                if kw in words:
                    return "browser"
            else:
                if kw in lower:
                    return "browser"

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

    def _get_or_create_subagent(self, role: str, agent_id: str, step_id: str):
        """Get a cached subagent or create a new one.

        Subagents are cached by (step_id, role) so they retain state
        (tool history, findings, candidates) across dispatches within
        the same workflow step.
        """
        cache_key = f"{step_id}:{role}"
        if cache_key in self._subagent_cache:
            return self._subagent_cache[cache_key]

        subagent = self._create_subagent(role, agent_id)
        self._subagent_cache[cache_key] = subagent
        return subagent

    def _cleanup_step(self, step_id: str) -> None:
        """Remove cached subagents for a completed step."""
        keys_to_remove = [k for k in self._subagent_cache if k.startswith(f"{step_id}:")]
        for key in keys_to_remove:
            del self._subagent_cache[key]

    def _create_subagent(self, role: str, agent_id: str):
        """Create a subagent instance for the given role."""
        from jarviscore.kernel.defaults import (
            CoderSubAgent,
            ResearcherSubAgent,
            CommunicatorSubAgent,
            BrowserSubAgent,
        )

        if role == "coder":
            return CoderSubAgent(
                agent_id=agent_id,
                llm_client=self.llm_client,
                sandbox=self.sandbox,
                code_registry=self.code_registry,
                auth_manager=self.auth_manager,  # Nexus auth wiring
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
        elif role == "browser":
            return BrowserSubAgent(
                agent_id=agent_id,
                llm_client=self.llm_client,
                headless=self.config.get("browser_headless", True),
                viewport=None,  # uses BrowserSubAgent default 1280x720
                redis_store=self.redis_store,
                blob_storage=self.blob_storage,
            )
        else:
            raise ValueError(f"Unknown subagent role: {role}")

    def _create_memory(self, workflow_id: str, step_id: str, agent_id: str):
        """Create a UnifiedMemory instance for the current step.

        Includes Athena as Tier 4 when ATHENA_URL is configured in settings.
        Returns None if neither Redis nor blob storage is available.
        Graceful degradation — the OODA loop works without memory.
        """
        try:
            from jarviscore.memory.unified import UnifiedMemory
            if self.redis_store or self.blob_storage:
                # Try to get AthenaClient from settings
                athena_client = None
                try:
                    from jarviscore.config.settings import get_settings
                    from jarviscore.memory.athena_client import AthenaClient
                    _settings = get_settings()
                    if getattr(_settings, "athena_url", None):
                        athena_client = AthenaClient.from_env()
                except Exception:
                    pass   # Athena not configured — no Tier 4

                return UnifiedMemory(
                    workflow_id=workflow_id,
                    step_id=step_id,
                    agent_id=agent_id,
                    redis_store=self.redis_store,
                    blob_storage=self.blob_storage,
                    athena_client=athena_client,
                )
        except ImportError:
            logger.debug("[Kernel] UnifiedMemory not available — running without memory")
        return None


    def _create_context_manager(self, role: str) -> ContextManager:
        """Create a ContextManager with role-appropriate budget config."""
        profile = ROLE_LEASE_PROFILES.get(role, {})
        total_tokens = profile.get("max_total_tokens", 80_000)

        config = BudgetConfig(
            total_tokens=total_tokens,
            output_reserve=4_000,
            system_reserve=8_000,
            history_limit=min(20_000, total_tokens // 4),
            summarization_threshold=0.8,
        )
        return ContextManager(config)

    def _check_registry_reuse(
        self,
        task: str,
        system: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Option A: Registry-first reuse check.

        Returns a registry candidate dict if a verified/golden function matches.
        Returns None if no match found — caller should proceed to coder.
        """
        if not self.code_registry:
            return None
        try:
            matches = self.code_registry.semantic_search(task, limit=5)
            # Filter: verified/golden only
            production = [
                m for m in matches
                if m.get("registry_stage") in ("verified", "golden")
                and m.get("_score", 0) >= _REGISTRY_REUSE_SCORE_THRESHOLD
            ]
            if system:
                system_matches = [m for m in production if m.get("system") == system]
                if system_matches:
                    production = system_matches
            if not production:
                return None
            top = production[0]
            code = self.code_registry.get_function_code(top["function_name"])
            if not code:
                return None
            return {
                "function_name": top["function_name"],
                "code": code,
                "system": top.get("system"),
                "stage": top.get("registry_stage"),
                "success_count": top.get("success_count", 0),
                "score": top.get("_score", 0),
            }
        except Exception as exc:
            logger.debug("[Kernel] Registry reuse check failed: %s", exc)
            return None

    def _should_escalate_to_researcher(
        self, output, dispatch_num: int
    ) -> bool:
        """
        Check if coder output signals that research is needed.

        Research fires ONLY on runtime failure with a real error —
        NOT as a prerequisite to coding.
        """
        if not self.search_client:
            return False
        meta = getattr(output, "metadata", {}) or {}
        if meta.get("signal_researcher"):
            return True
        # Failed with a real error on first attempt → researcher can fetch live docs
        if output.status == "failure" and dispatch_num == 0:
            summary = (output.summary or "").lower()
            research_signals = [
                "404", "not found", "api error", "invalid endpoint",
                "schema mismatch", "unexpected field", "rate limit",
            ]
            if any(sig in summary for sig in research_signals):
                return True
        return False

    async def execute(
        self,
        task: str,
        system_prompt: str = "",
        context: Optional[Dict] = None,
        agent_id: str = "kernel",
        max_dispatches: int = 3,
        agent_default_role: Optional[str] = None,
    ) -> AgentOutput:
        """
        Execute a task through the OODA loop.

        Args:
            task: Natural language task description
            system_prompt: System prompt from the AutoAgent
            context: Optional context (dependencies, previous results)
            agent_id: Agent identifier for tracking
            max_dispatches: Maximum subagent dispatches before giving up
            agent_default_role: If set, skip keyword classification and use this role.

        Returns:
            AgentOutput with the final result
        """
        start_time = time.time()
        dispatches: List[Dict[str, Any]] = []
        total_tokens = {"input": 0, "output": 0, "total": 0}
        total_cost = 0.0

        workflow_id = context.get("workflow_id", "unknown") if context else "unknown"
        step_id = context.get("step_id", f"step_{int(time.time())}") if context else f"step_{int(time.time())}"

        # Create TraceManager for real-time streaming to UI
        from jarviscore.kernel.tracing import TraceManager, create_noop_trace
        try:
            _kernel_trace = TraceManager(
                workflow_id=workflow_id,
                step_id=step_id,
            )
        except Exception as _te:
            logger.debug("[Kernel] TraceManager init failed (non-fatal): %s", _te)
            _kernel_trace = create_noop_trace()

        for dispatch_num in range(max_dispatches):
            # ─────────────────────────────────────────────────────
            # OPTION A: Registry-first fast path
            # ─────────────────────────────────────────────────────
            role_hint = context.get("system") if context else None
            registry_candidate = self._check_registry_reuse(task, system=role_hint)

            if registry_candidate and dispatch_num == 0:
                logger.info(
                    "[Kernel] Option A: registry reuse — function=%s stage=%s score=%s",
                    registry_candidate["function_name"],
                    registry_candidate["stage"],
                    registry_candidate["score"],
                )
                enriched_context = dict(context) if context else {}
                enriched_context["registry_candidate"] = registry_candidate
                enriched_context["_hint"] = (
                    f"Verified function `{registry_candidate['function_name']}` found in registry. "
                    "Call execute_code with its code directly — skip write_code."
                )
            else:
                enriched_context = dict(context) if context else {}

            # 1. OBSERVE + ORIENT: classify task and select subagent
            role = self._classify_task(task, context)
            logger.info(f"[Kernel] Dispatch {dispatch_num + 1}: task → {role}")

            # 2. DECIDE: create lease, cognition, memory, context manager
            lease = ExecutionLease.for_role(role)
            cognition = AgentCognitionManager(
                lease=lease,
                agent_id=agent_id,
                workflow_id=workflow_id,
                redis_store=self.redis_store,
            )
            model = self._get_model_for_tier(lease.model_tier)

            # Calculate max turns from lease
            max_turns = min(
                lease.emergency_turn_fuse,
                self.config.get("kernel_max_turns", 30),
            )

            # Create memory (graceful degradation if no Redis/blob)
            memory = self._create_memory(workflow_id, step_id, agent_id)

            # ── Inject Athena memory context into enriched_context ──────────────
            # Agents see their cross-session STM + MTM chains before deciding.
            # This is what gives them continuity across shifts and sessions.
            if memory is not None:
                try:
                    bundle = await memory.rehydrate_bundle(ledger_tail=5)
                    if bundle.get("athena_context"):
                        enriched_context["_athena_memory"] = bundle["athena_context"]
                    if bundle.get("ltm_summary"):
                        enriched_context["_ltm_summary"] = bundle["ltm_summary"]
                except Exception as _me:
                    logger.debug("[Kernel] Memory rehydration failed (non-fatal): %s", _me)

            ctx_manager = self._create_context_manager(role)

            # 3. ACT: create (or reuse) subagent and dispatch
            subagent = self._get_or_create_subagent(
                role, f"{agent_id}_{role}_{dispatch_num}", step_id
            )

            # Build enriched context with system prompt
            enriched_context["workflow_id"] = workflow_id
            enriched_context["step_id"] = step_id
            if system_prompt:
                enriched_context["system_prompt"] = system_prompt
            if agent_default_role:
                enriched_context["_agent_default_kernel_role"] = agent_default_role

            # Wire Nexus connection — agents receive connection_id only, never credentials.
            # NexusCallProxy (injected into CoderSandbox) is the sole credential boundary.
            if role == "coder" and self.auth_manager:
                system_name = (
                    enriched_context.get("system")
                    or (context.get("system") if context else None)
                )
                if system_name:
                    try:
                        conn_id = await self.auth_manager.get_connection_id(system_name)
                        # Only the opaque handle goes into context — NEVER tokens or keys
                        enriched_context["_nexus_connection_id"] = conn_id
                        enriched_context["_nexus_provider"] = system_name
                        logger.info(
                            "[Kernel] Nexus connection_id tagged for system=%s",
                            system_name,
                        )
                    except Exception as auth_exc:
                        logger.warning(
                            "[Kernel] Nexus connection unavailable for system=%s "
                            "(set NEXUS_GATEWAY_URL): %s",
                            system_name, auth_exc,
                        )


            # ── Dispatch subagent with full infrastructure ──
            output = await subagent.run(
                task=task,
                context=enriched_context if enriched_context else None,
                max_turns=max_turns,
                model=model,
                cognition=cognition,
                context_manager=ctx_manager,
                memory=memory,
                trace=_kernel_trace,
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
                "typed_outcome": meta.get("typed_outcome"),
            }
            dispatches.append(dispatch_record)

            # 4. EVALUATE: check result
            if output.status == "success":
                self._cleanup_step(step_id)
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
                # HITL needed or budget exhausted — pass through
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
                        "typed_outcome": meta.get("typed_outcome"),
                    },
                )

            # ─────────────────────────────────────────────────────
            # OPTION C: Research-on-failure
            # Researcher fires with a REAL error — not as a prerequisite.
            # ─────────────────────────────────────────────────────
            if self._should_escalate_to_researcher(output, dispatch_num):
                logger.info(
                    "[Kernel] Option C: research-on-failure — escalating to researcher. "
                    "Coder error: %s",
                    (output.summary or "")[:200],
                )
                research_agent = self._get_or_create_subagent(
                    "researcher", f"{agent_id}_researcher_{dispatch_num}", step_id
                )
                research_task = (
                    f"Research the API documentation needed to fix this error:\n"
                    f"Original task: {task}\n"
                    f"Error: {output.summary}\n\n"
                    "Find the correct endpoint, request format, authentication method, "
                    "and any required parameters. Return structured API specs."
                )
                research_output = await research_agent.run(
                    task=research_task,
                    context=enriched_context,
                    max_turns=8,
                    model=model,
                    cognition=AgentCognitionManager(
                        lease=ExecutionLease.for_role("researcher"),
                        agent_id=agent_id,
                        workflow_id=workflow_id,
                        redis_store=self.redis_store,
                    ),
                    context_manager=self._create_context_manager("researcher"),
                    memory=memory,
                )
                if research_output.status == "success" and research_output.payload:
                    enriched_context["research_findings"] = research_output.payload
                    enriched_context["_hint"] = (
                        "Research findings above contain the correct API specs. "
                        "Use them to rewrite the code. Do NOT use your prior failed approach."
                    )
                    context = enriched_context
                    logger.info("[Kernel] Research complete — retrying coder with findings.")
                    continue

            # Failure — check if we should retry with a different strategy
            logger.warning(
                f"[Kernel] Dispatch {dispatch_num + 1} failed: {output.summary}"
            )

            # Auth errors: yield to human
            coder_payload = output.payload or {}
            if isinstance(coder_payload, dict) and coder_payload.get("hitl_required"):
                auth_error_type = coder_payload.get("auth_error_type", "auth_required")
                system_name = enriched_context.get("system", "unknown")
                self._cleanup_step(step_id)
                return AgentOutput(
                    status="yield",
                    summary=(
                        f"Auth failure — {auth_error_type} for system={system_name}. "
                        "Human must provide or refresh credentials via Nexus."
                    ),
                    trajectory=output.trajectory,
                    metadata={
                        "tokens": total_tokens,
                        "cost_usd": total_cost,
                        "dispatches": dispatches,
                        "yield_pending": True,
                        "escalation_reason": auth_error_type,
                        "system": system_name,
                        "hitl_type": "auth",
                        "typed_outcome": "YIELD_AUTH_REQUIRED",
                    },
                )

            # Check HITL policy for escalation
            if self.hitl_policy:
                should_escalate, reason = self.hitl_policy.should_escalate(
                    reason_code="execution_failure",
                    confidence=0.3,
                    risk_score=0.5,
                )
                if should_escalate:
                    self._cleanup_step(step_id)
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
                            "typed_outcome": "YIELD_HITL_POLICY",
                        },
                    )

        # All dispatches exhausted
        elapsed = (time.time() - start_time) * 1000
        self._cleanup_step(step_id)
        return AgentOutput(
            status="failure",
            summary=f"All {max_dispatches} dispatches failed",
            trajectory=[],
            metadata={
                "tokens": total_tokens,
                "cost_usd": total_cost,
                "dispatches": dispatches,
                "elapsed_ms": elapsed,
                "typed_outcome": "FAIL_ALL_DISPATCHES_EXHAUSTED",
            },
        )
