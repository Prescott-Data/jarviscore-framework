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

import json
import logging
import os
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, cast

from jarviscore.context.truth import AgentOutput
from jarviscore.context.context_manager import ContextManager, BudgetConfig
from jarviscore.kernel.lease import ExecutionLease, ROLE_LEASE_PROFILES
from jarviscore.kernel.cognition import AgentCognitionManager
from jarviscore.kernel.state import KernelState
from jarviscore.kernel.hitl import AdaptiveHITLPolicy

logger = logging.getLogger(__name__)

# Minimum registry confidence to skip code generation
_REGISTRY_REUSE_SCORE_THRESHOLD = 2  # semantic_search score units
_BUILTIN_KERNEL_ROLES = frozenset(ROLE_LEASE_PROFILES.keys())


class RoutingError(RuntimeError):
    """Raised when Kernel cannot obtain a valid, typed routing decision."""


@dataclass(frozen=True)
class RoutingDecision:
    role: str
    confidence: float
    reason: str
    evidence_required: bool = False


class TaskRouter:
    """Structured LLM router for Kernel subagent role selection."""

    _SYSTEM_PROMPT = """\
You are JarvisCore's Kernel router. Choose the single best subagent role for one task.

Return ONLY a JSON object:
{
  "role": "<one value from valid_roles>",
  "confidence": 0.0-1.0,
  "reason": "one concise sentence",
  "evidence_required": true | false
}

Built-in role contract:
- coder: write/execute code, process files/data, call APIs, compute or transform data.
- researcher: gather unknown facts from web/docs/files, investigate, compare evidence.
- communicator: draft/review/summarize/structure decisions, reports, messages, requests, JSON contracts.
- browser: operate an interactive browser/UI: navigation, clicks, screenshots, forms, login flows.

Use the task, context summary, agent default role, and available registry/handoff context.
For custom roles, use role_catalog from the payload as the authoritative contract.
Do not use keyword matching. If the task asks for missing access/data/founder input, route to
communicator unless it explicitly requires browser UI work. Prefer coder only when executable
processing is actually required.
"""

    def __init__(
        self,
        llm_client,
        model: Optional[str] = None,
        min_confidence: float = 0.55,
        valid_roles: Optional[List[str]] = None,
        role_catalog: Optional[Dict[str, str]] = None,
    ):
        self.llm = llm_client
        self.model = model
        self.min_confidence = min_confidence
        self.valid_roles = frozenset(valid_roles or sorted(_BUILTIN_KERNEL_ROLES))
        self.role_catalog = role_catalog or {}

    async def route(
        self,
        *,
        task: str,
        context: Optional[Dict[str, Any]] = None,
        agent_default_role: Optional[str] = None,
    ) -> RoutingDecision:
        if self.llm is None:
            raise RoutingError("Kernel routing requires an LLM client when no explicit role is provided")

        context_summary = self._summarize_context(context or {})
        payload = {
            "task": task,
            "context_summary": context_summary,
            "agent_default_role": agent_default_role,
            "valid_roles": sorted(self.valid_roles),
            "role_catalog": self.role_catalog,
        }
        messages = [
            {"role": "system", "content": self._SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False, default=str)},
        ]
        kwargs: Dict[str, Any] = {
            "messages": messages,
            "temperature": 0.0,
            "max_tokens": 500,
            "response_format": {"type": "json_object"},
        }
        if self.model:
            kwargs["model"] = self.model
        try:
            response = await self.llm.generate(**kwargs)
        except TypeError:
            kwargs.pop("response_format", None)
            response = await self.llm.generate(**kwargs)
        except Exception as exc:
            raise RoutingError(f"Kernel router LLM call failed: {exc}") from exc

        content = response.get("content", "") if isinstance(response, dict) else str(response)
        data = self._parse_json_object(content)
        role = str(data.get("role", "")).lower().strip()
        if role not in self.valid_roles:
            raise RoutingError(f"Kernel router returned invalid role {role!r}: {content[:300]}")

        try:
            confidence = float(data.get("confidence", 0.0))
        except (TypeError, ValueError):
            confidence = 0.0
        confidence = max(0.0, min(1.0, confidence))
        if confidence < self.min_confidence:
            raise RoutingError(
                f"Kernel router confidence too low ({confidence:.2f}) for role {role!r}: "
                f"{data.get('reason', '')}"
            )

        return RoutingDecision(
            role=role,
            confidence=confidence,
            reason=str(data.get("reason", ""))[:500],
            evidence_required=bool(data.get("evidence_required", False)),
        )

    @staticmethod
    def _summarize_context(context: Dict[str, Any]) -> Dict[str, Any]:
        keys = [
            "workflow_id",
            "step_id",
            "complexity",
            "system",
            "previous_step_results",
            "registry_candidate",
            "meeting_step_id",
            "task_id",
        ]
        summary: Dict[str, Any] = {}
        for key in keys:
            if key in context:
                value = context[key]
                rendered = json.dumps(value, ensure_ascii=False, default=str)
                summary[key] = rendered[:1200]
        return summary

    @staticmethod
    def _parse_json_object(content: str) -> Dict[str, Any]:
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            start = content.find("{")
            end = content.rfind("}") + 1
            if start < 0 or end <= start:
                raise RoutingError(f"Kernel router response is not JSON: {content[:300]}")
            try:
                parsed = json.loads(content[start:end])
            except json.JSONDecodeError as exc:
                raise RoutingError(f"Kernel router response is not valid JSON: {content[:300]}") from exc
        if not isinstance(parsed, dict):
            raise RoutingError(f"Kernel router response must be a JSON object, got {type(parsed).__name__}")
        return parsed


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
        self.auth_manager: Any = None

        # Subagent cache — reuse within same workflow step
        self._subagent_cache: Dict[str, Any] = {}
        self._role_lease_profiles: Dict[str, Dict[str, Any]] = dict(ROLE_LEASE_PROFILES)
        self._role_lease_profiles.update(self.config.get("kernel_role_profiles", {}) or {})
        self._role_catalog: Dict[str, str] = dict(self.config.get("kernel_role_catalog", {}) or {})
        self._task_router = TaskRouter(
            llm_client=llm_client,
            model=self._get_model_for_tier("task", complexity="nano"),
            min_confidence=float(self.config.get("kernel_router_min_confidence", 0.55)),
            valid_roles=sorted(self._role_lease_profiles),
            role_catalog=self._role_catalog,
        )

    def _get_model_for_tier(self, tier: str, complexity: Optional[str] = None) -> Optional[str]:
        """Resolve model name from tier using config.

        For the coding tier, returns coding_model.
        For the browser tier, returns browser_model (should be a CUA or multimodal model).
        For the task tier, respects an optional complexity hint:
          - "nano"     -> task_model_nano     (fast/cheap)
          - "standard" -> task_model_standard (general, default)
          - "heavy"    -> task_model_heavy    (deep reasoning)
        Falls back to task_model / coding_model if tier-specific setting unset.
        Legacy claude-specific settings are checked last for backward compat.
        """
        if tier == "coding":
            return (
                self.config.get("coding_model")
                or self.config.get("claude_coding_model")
                or None
            )
        elif tier == "browser":
            # Prefer an explicit CUA/multimodal model; fall back to standard task model.
            # If browser_model is not set, the sub-agent still runs but vision-based
            # screenshot reasoning may be degraded on non-multimodal models.
            return (
                self.config.get("browser_model")
                or self.config.get("task_model_standard")
                or self.config.get("task_model")
                or None
            )
        elif tier == "task":
            # Multi-tier resolution: complexity hint -> specific setting -> base task_model
            if complexity == "nano":
                resolved = self.config.get("task_model_nano")
                if resolved:
                    return resolved
            elif complexity == "heavy":
                resolved = self.config.get("task_model_heavy")
                if resolved:
                    return resolved
            elif complexity == "standard":
                resolved = self.config.get("task_model_standard")
                if resolved:
                    return resolved
            # Fallback to 2-tier base
            return (
                self.config.get("task_model_standard")  # prefer standard if set, even without hint
                or self.config.get("task_model")
                or self.config.get("claude_task_model")
                or None
            )
        return None


    async def _route_task(
        self,
        task: str,
        context: Optional[Dict] = None,
        *,
        agent_default_role: Optional[str] = None,
        use_default_role_as_fallback: bool = False,
    ) -> RoutingDecision:
        """
        Route a task into a subagent role using explicit contracts first, then
        a structured LLM router. Keyword routing is intentionally not used.
        """
        explicit_role = None
        if context:
            explicit_role = context.get("_agent_default_kernel_role")
        if agent_default_role and not use_default_role_as_fallback:
            explicit_role = agent_default_role

        if explicit_role:
            normalized_role = str(explicit_role).lower().strip()
            if normalized_role not in self._role_lease_profiles:
                raise RoutingError(f"Explicit kernel role {explicit_role!r} is not valid")
            return RoutingDecision(
                role=normalized_role,
                confidence=1.0,
                reason="Explicit planner/profile role.",
            )

        return await self._task_router.route(
            task=task,
            context=context,
            agent_default_role=agent_default_role,
        )

    def _lease_for_role(self, role: str) -> ExecutionLease:
        """Create a lease from built-in or application-registered role profile."""
        profile = self._role_lease_profiles.get(role)
        if profile is None:
            raise RoutingError(
                f"No lease profile registered for kernel role {role!r}. "
                "Add config['kernel_role_profiles'][role] or use a built-in role."
            )
        return ExecutionLease(**profile)

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

    async def _cleanup_step(self, step_id: str) -> None:
        """Remove cached subagents for a completed step."""
        keys_to_remove = [k for k in self._subagent_cache if k.startswith(f"{step_id}:")]
        for key in keys_to_remove:
            subagent = self._subagent_cache.pop(key)
            teardown = getattr(subagent, "teardown", None)
            if teardown is not None:
                try:
                    result = teardown()
                    if hasattr(result, "__await__"):
                        await result
                except Exception as exc:
                    logger.warning("[Kernel] Subagent teardown failed for %s: %s", key, exc)

    async def teardown(self) -> None:
        """Release all cached subagent resources owned by this Kernel."""
        keys_to_remove = list(self._subagent_cache)
        for key in keys_to_remove:
            subagent = self._subagent_cache.pop(key)
            teardown = getattr(subagent, "teardown", None)
            if teardown is not None:
                try:
                    result = teardown()
                    if hasattr(result, "__await__"):
                        await result
                except Exception as exc:
                    logger.warning("[Kernel] Subagent teardown failed for %s: %s", key, exc)

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
                search_client=self.search_client,  # Self-research tools
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
                athena_configured = False
                try:
                    from jarviscore.config.settings import Settings
                    from jarviscore.memory.athena_client import AthenaClient
                    _settings = cast(Any, Settings)()
                    athena_configured = bool(
                        getattr(_settings, "athena_url", None)
                        or os.environ.get("ATHENA_URL")
                    )
                    if athena_configured:
                        athena_client = AthenaClient.from_env()
                except Exception as exc:
                    if athena_configured or os.environ.get("ATHENA_URL"):
                        logger.warning("[Kernel] Athena memory tier configured but unavailable: %s", exc)
                    else:
                        logger.debug("[Kernel] Athena memory tier not configured: %s", exc)

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
        profile = self._role_lease_profiles.get(role, {})
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
        use_default_role_as_fallback: bool = False,
    ) -> AgentOutput:
        """
        Execute a task through the OODA loop.

        Args:
            task: Natural language task description
            system_prompt: System prompt from the AutoAgent
            context: Optional context (dependencies, previous results)
            agent_id: Agent identifier for tracking
            max_dispatches: Maximum subagent dispatches before giving up
            agent_default_role: Preferred role from the agent/profile.
            use_default_role_as_fallback: If true, classify the task first and use
                agent_default_role only when the classifier has no stronger signal.

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

            # 1. OBSERVE + ORIENT: obtain a typed routing decision.
            class_ctx = dict(context) if context else {}
            try:
                routing = await self._route_task(
                    task,
                    class_ctx,
                    agent_default_role=agent_default_role,
                    use_default_role_as_fallback=use_default_role_as_fallback,
                )
            except RoutingError as route_exc:
                logger.error("[Kernel] Routing failed: %s", route_exc)
                return AgentOutput(
                    status="failure",
                    payload={"error": str(route_exc), "stage": "kernel_routing"},
                    summary=f"Kernel routing failed: {route_exc}",
                    trajectory=[],
                    metadata={
                        "tokens": total_tokens,
                        "cost_usd": total_cost,
                        "dispatches": dispatches,
                        "elapsed_ms": (time.time() - start_time) * 1000,
                        "routing_error": str(route_exc),
                    },
                )
            role = routing.role
            enriched_context["_kernel_routing"] = {
                "role": routing.role,
                "confidence": routing.confidence,
                "reason": routing.reason,
                "evidence_required": routing.evidence_required,
            }
            logger.info(
                "[Kernel] Dispatch %d: task → %s (confidence=%.2f, reason=%s)",
                dispatch_num + 1,
                role,
                routing.confidence,
                routing.reason,
            )

            # 2. DECIDE: create lease, cognition, memory, context manager
            lease = self._lease_for_role(role)
            cognition = AgentCognitionManager(
                lease=lease,
                agent_id=agent_id,
                workflow_id=workflow_id,
                redis_store=self.redis_store,
            )
            # Resolve complexity: explicit context override wins; lease profile
            # provides the role-level default (e.g. communicator→nano, researcher→standard).
            # Developers can always override per-goal via context["complexity"].
            complexity = (
                (context.get("complexity") if context else None)
                or getattr(lease, "complexity", None)
            )
            model = self._get_model_for_tier(
                lease.model_tier,
                complexity=complexity,
            )

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
                role, agent_id, step_id
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
            output = await cast(Any, subagent).run(
                task=task,
                context=enriched_context if enriched_context else None,
                max_turns=max_turns,
                model=model,
                cognition=cognition,
                context_manager=ctx_manager,
                memory=memory,
                trace=_kernel_trace,
            )

            # ── Track costs ──────────────────────────────────────────────────
            meta = output.metadata or {}
            tokens = meta.get("tokens", {})
            total_tokens["input"] += tokens.get("input", 0)
            total_tokens["output"] += tokens.get("output", 0)
            total_tokens["total"] += tokens.get("total", 0)
            total_cost += meta.get("cost_usd", 0.0)

            # ── Distil output into typed TruthFacts ──────────────────────────
            # This runs on every successful dispatch so that execute_goal()
            # and any caller that wants structured facts can read them from
            # output.metadata["distilled_facts"] without re-parsing the payload.
            if output.status == "success" and output.payload is not None:
                try:
                    from jarviscore.context.distillation import distill_output as _distill
                    _distilled = _distill(
                        raw_output=output.payload,
                        source=f"{agent_id}:{step_id}:{role}",
                        confidence=0.8,
                    )
                    output.metadata["distilled_facts"] = {
                        k: v.model_dump() for k, v in _distilled.items()
                    }
                except Exception as _de:
                    logger.debug("[Kernel] Distillation failed (non-fatal): %s", _de)

            dispatch_record = {
                "dispatch": dispatch_num + 1,
                "role": role,
                "status": output.status,
                "summary": output.summary,
                "model": model,
                "typed_outcome": meta.get("typed_outcome"),
                "routing": enriched_context.get("_kernel_routing"),
            }
            dispatches.append(dispatch_record)

            # 4. EVALUATE: check result
            if output.status == "success":
                await self._cleanup_step(step_id)
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
                        "distilled_facts": output.metadata.get("distilled_facts", {}),
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
                        "elapsed_ms": (time.time() - start_time) * 1000,
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
                    "researcher", agent_id, step_id
                )
                research_task = (
                    f"Research the API documentation needed to fix this error:\n"
                    f"Original task: {task}\n"
                    f"Error: {output.summary}\n\n"
                    "Find the correct endpoint, request format, authentication method, "
                    "and any required parameters. Return structured API specs."
                )
                research_output = await cast(Any, research_agent).run(
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
                await self._cleanup_step(step_id)
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

            # Check HITL policy for escalation — only on the FINAL dispatch.
            # Intermediate failures should be retried (possibly with research
            # findings), not dumped to human review.  Goal-oriented agents get
            # their recovery from the Planner's replan loop; premature HITL
            # escalation short-circuits that and floods the review queue.
            is_final_dispatch = (dispatch_num == max_dispatches - 1)
            if self.hitl_policy and is_final_dispatch:
                # Gentler confidence decay: 0.15 per dispatch instead of 0.25.
                # dispatch 0 → 0.85, dispatch 1 → 0.70, dispatch 2 → 0.55.
                # This gives the retry loop room to succeed before the
                # confidence drops below the escalation threshold.
                dispatch_confidence = max(0.1, 1.0 - (dispatch_num * 0.15))
                tokens_spent = total_tokens.get("total", 0)
                risk_from_spend = min(0.9, tokens_spent / 200_000)

                should_escalate, reason = self.hitl_policy.should_escalate(
                    reason_code="execution_failure",
                    confidence=dispatch_confidence,
                    risk_score=risk_from_spend,
                )
                if should_escalate:
                    await self._cleanup_step(step_id)
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
        await self._cleanup_step(step_id)
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
