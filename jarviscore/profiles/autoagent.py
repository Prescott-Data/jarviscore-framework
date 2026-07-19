"""
AutoAgent - Automated execution profile.

Framework generates and executes code from natural language prompts.
User writes just 3 attributes, framework handles everything.

For long-horizon autonomous work, set goal_oriented = True on your
subclass — all tasks will be routed through the Plan → Execute → Evaluate
loop automatically. The execute_task() contract is unchanged.
"""
import os
import re
import time
from typing import Any, Dict, List, Optional, TYPE_CHECKING, cast
from jarviscore.core.profile import Profile

if TYPE_CHECKING:
    from jarviscore.planning.goal_context import GoalExecution




class AutoAgent(Profile):

    """
    Automated execution profile.

    User defines:
    - role: str
    - capabilities: List[str]
    - system_prompt: str

    Framework provides:
    - LLM code generation from task descriptions
    - Sandboxed code execution with resource limits
    - Autonomous repair when execution fails
    - Meta-cognition (detect spinning, paralysis)
    - Token budget tracking
    - Cost tracking per task
    - Kernel: Registry-first routing + ValidationLayer + Research-on-failure

    Example:
        class ScraperAgent(AutoAgent):
            role = "scraper"
            capabilities = ["web_scraping", "data_extraction"]
            system_prompt = '''
            You are an expert web scraper. Use BeautifulSoup or Selenium
            to extract structured data from websites. Return JSON results.
            '''

        # That's it! Framework handles execution automatically.
    """

    # ── Required class attributes ────────────────────────────────────────────
    # Every AutoAgent subclass must define these three.
    # role and capabilities are declared on the Agent base class.
    system_prompt: Optional[str] = None

    # ── Optional capabilities — full reference ───────────────────────────────
    #
    # ┌─────────────────────────────┬──────────┬──────────────────────────────────────────────────────┐
    # │ Knob                        │ Where    │ What it does                                         │
    # ├─────────────────────────────┼──────────┼──────────────────────────────────────────────────────┤
    # │ goal_oriented = True        │ class    │ Routes all tasks through Plan→Execute→Evaluate loop  │
    # │ default_kernel_role = "..." │ class    │ Fallback role when Planner emits subagent_hint: null │
    # │ requires_auth = True        │ class    │ Mesh injects _auth_manager (Nexus-backed credentials)│
    # │ complexity = "nano|heavy"   │ task     │ Per-task model tier hint passed in the workflow dict │
    # │ HITL_ENABLED=true           │ .env     │ AdaptiveHITLPolicy — escalates on low-confidence     │
    # │ BROWSER_ENABLED=true        │ .env     │ Activates BrowserSubAgent for web-automation tasks   │
    # │ MAX_GOAL_STEPS=N            │ .env     │ Override step ceiling for goal_oriented agents        │
    # │ MAX_REPLAN_ATTEMPTS=N       │ .env     │ Override max replanning cycles before failing         │
    # └─────────────────────────────┴──────────┴──────────────────────────────────────────────────────┘

    # ── goal_oriented ────────────────────────────────────────────────────────
    # Routes every execute_task() call through the Plan → Execute → Evaluate
    # loop. The Planner generates a DAG of steps, each with an explicit
    # subagent_hint; the Kernel executes steps in order with full OODA context
    # and TruthContext state persisted across steps.
    #
    # When False (default): single OODA loop — correct for bounded atomic tasks.
    # When True: same execute_task() call, same response envelope. No API change.
    #
    #   result["status"]          — "success" | "failure" | "hitl"
    #   result["output"]          — final synthesised answer
    #   result["goal_execution"]  — summary dict (steps, facts, elapsed_ms)
    #
    # Example:
    #     class ResearchAgent(AutoAgent):
    #         role = "researcher"
    #         capabilities = ["research", "analysis"]
    #         system_prompt = "You are a market researcher..."
    #         goal_oriented = True   # ← that's it. framework handles the rest.
    goal_oriented: bool = False

    # ── default_kernel_role ──────────────────────────────────────────────────
    # Declare this agent's fixed subagent role for the Planner null-hint case.
    #
    # In goal_oriented mode the Planner assigns a subagent_hint to every step
    # ("coder", "researcher", "communicator", "browser"). This attribute is the
    # agent-level explicit role used when the Planner returns subagent_hint: null.
    #
    # Use this on SPECIALIST agents where every task always uses the same role,
    # so the Planner null-hint path also routes correctly.
    # Leave None for generalist agents — the Planner handles routing per step.
    #
    # Values: "coder" | "researcher" | "communicator" | "browser" | None
    # Example:
    #     class SlackNotifier(AutoAgent):
    #         default_kernel_role = "communicator"  # always sends, never codes
    default_kernel_role: Optional[str] = None

    # ── requires_auth ────────────────────────────────────────────────────────
    # Set True on agents that call third-party services (GitHub, Jira, Slack…).
    #
    # When True, the Mesh creates an AuthenticationManager from the Nexus
    # gateway config and injects it as self._auth_manager AFTER setup().
    # The Kernel then wires NexusCallProxy into the sandbox so LLM-generated
    # code gets resolved credentials without ever seeing raw tokens.
    #
    # Requires NEXUS_GATEWAY_URL in .env (see: jarviscore nexus status).
    # No-op when Nexus is not configured — agent runs without auth injection.
    #
    # Example:
    #     class GithubAgent(AutoAgent):
    #         requires_auth = True   # Mesh injects _auth_manager before first task
    requires_auth: bool = False

    def __init__(self, agent_id=None):
        super().__init__(agent_id)

        if not self.system_prompt:
            raise ValueError(
                f"{self.__class__.__name__} must define 'system_prompt' class attribute\n"
                f"Example: system_prompt = 'You are an expert...'"
            )

        # Execution components (initialized in setup())
        self.llm: Any = None
        self.codegen: Any = None
        self.sandbox: Any = None
        self.repair: Any = None
        self._kernel: Any = None  # Production Kernel (registry-first → coder → research-on-failure)

        # ── Agent intelligence: profile block prepended to system prompt ──
        # Loaded lazily in setup() from jarviscore/profiles/agents/{role}.yaml
        self._profile_block: str = ""

    async def setup(self):
        """
        Initialize LLM and execution components with ZERO CONFIG.

        Framework auto-detects available LLM providers and sets up:
        - LLM client (tries vLLM → Azure → Gemini → Claude)
        - Internet search (SearXNG metasearch, no API key needed)
        - Code generator with search injection
        - Sandbox executor with timeout
        - Autonomous repair system
        - Kernel: production routing pipeline
        - AgentProfile: role intelligence injected into system prompt
        """
        await super().setup()

        self._logger.info(f"AutoAgent setup: {self.agent_id}")
        self._logger.info(f"  Role: {self.role}")
        self._logger.info(f"  Capabilities: {self.capabilities}")
        self._logger.info(f"  System Prompt: {str(self.system_prompt or '')[:50]}...")

        self._load_agent_profile()


        # Get config from mesh (or use empty dict)
        config = self._mesh.config if self._mesh else {}

        # Import execution components
        from jarviscore.execution import (
            create_llm_client,
            create_search_client,
            create_code_generator,
            create_coder_sandbox,
            create_autonomous_repair,
            create_result_handler,
            create_function_registry
        )

        # 1. Initialize LLM (auto-detects providers)
        self._logger.info("Initializing LLM client...")
        self.llm = create_llm_client(config)

        # 2. Initialize search (zero-config)
        self._logger.info("Initializing internet search...")
        self.search = create_search_client()

        # 3. Initialize code generator (with search injection)
        self._logger.info("Initializing code generator...")
        self.codegen = create_code_generator(self.llm, self.search)

        # 4. Initialize coder sandbox (file-capable runtime for CoderSubAgent)
        timeout = config.get('execution_timeout', 300)
        self._logger.info(f"Initializing coder sandbox ({timeout}s timeout)...")
        self.sandbox = create_coder_sandbox(timeout=timeout)

        # 5. Initialize autonomous repair
        max_repairs = config.get('max_repair_attempts', 3)
        self._logger.info(f"Initializing autonomous repair ({max_repairs} attempts)...")
        self.repair = create_autonomous_repair(self.codegen, max_repairs)

        # 6. Initialize result handler (file + in-memory storage)
        log_dir = config.get('log_directory', './logs')
        self._logger.info(f"Initializing result handler (dir: {log_dir})...")
        self.result_handler = create_result_handler(log_dir)

        # 7. Initialize function registry (graduated, reusable generated functions)
        registry_dir = f"{log_dir}/function_registry"
        self._logger.info(f"Initializing function registry (dir: {registry_dir})...")
        self.code_registry = create_function_registry(registry_dir)

        # 8. Initialize Kernel — production routing:
        #    Registry-first (Option A) → Coder with ValidationLayer (Option B)
        #    → Research-on-failure only (Option C)
        #    Matches integration-agent staging pipeline.
        from jarviscore.kernel.kernel import Kernel
        self._logger.info("Initializing Kernel (registry-first routing + ValidationLayer)...")
        self._kernel = Kernel(
            llm_client=self.llm,
            sandbox=self.sandbox,
            code_registry=self.code_registry,
            search_client=self.search,
            redis_store=getattr(self, '_redis_store', None),
            blob_storage=getattr(self, '_blob_storage', None),
            config=config,
        )

        # 9. Wire AdaptiveHITLPolicy from mesh config if enabled.
        #    The Kernel's execute() checks self.hitl_policy.should_escalate()
        #    on every dispatch — no agent code required.
        if config.get("hitl_enabled", False):
            try:
                from jarviscore.kernel.hitl import AdaptiveHITLPolicy
                self._kernel.hitl_policy = AdaptiveHITLPolicy(
                    enabled=True,
                    max_confidence=config.get("hitl_max_confidence", 0.8),
                    min_risk_score=config.get("hitl_min_risk_score", 0.7),
                )
                self._logger.info(
                    "AdaptiveHITLPolicy enabled (max_confidence=%.2f, min_risk=%.2f)",
                    config.get("hitl_max_confidence", 0.8),
                    config.get("hitl_min_risk_score", 0.7),
                )
            except ImportError:
                self._logger.debug("AdaptiveHITLPolicy import failed — HITL adaptive escalation disabled")

        # NOTE: AuthenticationManager is NOT created here.
        # The Mesh owns auth — it creates AuthenticationManager from mesh config
        # and injects it as self._auth_manager on agents with requires_auth=True.
        # Injection happens AFTER setup() completes (see mesh.py:292-312).
        # The Kernel receives _auth_manager lazily at execute_task() time.

        self._logger.info(f"✓ AutoAgent ready: {self.agent_id}")

    async def teardown(self) -> None:
        """Release AutoAgent-owned runtime resources."""
        kernel = getattr(self, "_kernel", None)
        if kernel is not None and hasattr(kernel, "teardown"):
            try:
                await kernel.teardown()
            except Exception as exc:
                self._logger.warning("[AutoAgent] Kernel teardown failed: %s", exc)
        search = getattr(self, "search", None)
        if search is not None and hasattr(search, "close"):
            try:
                await search.close()
            except Exception as exc:
                self._logger.warning("[AutoAgent] Search client close failed: %s", exc)
        await super().teardown()

    def _load_agent_profile(self) -> None:
        """
        Load structured role intelligence from AgentProfile, if available.

        The rendered profile is prompt context. Runtime routing fields are also
        applied when the class did not explicitly declare them, so persona YAML
        can carry real framework semantics instead of being documentation only.
        """
        try:
            from jarviscore.profiles.agent_profile import AgentProfile
            profile = AgentProfile.load(self.role)
            if profile:
                self._profile_block = profile.to_prompt_block()
                if self.default_kernel_role is None and profile.default_kernel_role:
                    self.default_kernel_role = profile.default_kernel_role
                    self._logger.info(
                        "[AutoAgent] Applied profile default_kernel_role=%s for role=%s",
                        self.default_kernel_role,
                        self.role,
                    )
                self._logger.info(
                    "[AutoAgent] Loaded intelligence profile for role=%s "
                    "(%d SOPs, %d owns)",
                    self.role, len(profile.sops), len(profile.owns)
                )
            else:
                self._logger.debug("[AutoAgent] No intelligence profile for role=%s", self.role)
        except Exception as _pe:
            self._logger.debug("[AutoAgent] Profile load failed (non-fatal): %s", _pe)

    async def execute_task(self, task: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute task through the production Kernel pipeline.

        Pipeline (matches integration-agent staging branch):
        1. Registry-first: check FunctionRegistry for verified function (Option A)
        2. Coder writes from training knowledge + ValidationLayer gate (Option B)
        3. Sandbox execution — real test
        4. Research-on-failure ONLY (Option C) — researcher fires with real error
        5. Auto-register success in FunctionRegistry (CANDIDATE → VERIFIED → GOLDEN)

        Args:
            task: Task specification with 'task' key (natural language)

        Returns:
            {
                "status": "success" | "failure" | "yield",
                "output": Any,
                "error": str,
                "tokens": {...},
                "cost_usd": float,
                "function_id": str,
                "repairs": int,
            }
        """
        task_desc = task.get('task', '') if isinstance(task, dict) else str(task)

        self._logger.info(f"[AutoAgent] Executing via Kernel: {task_desc[:100]}...")

        # ── Goal-oriented routing ─────────────────────────────────────────────
        # goal_oriented=True means planner-capable, not planner-forced. The
        # structured complexity classifier decides whether this task needs the
        # full Plan→Execute→Evaluate loop or a direct Kernel turn.
        if self.goal_oriented:
            ctx = task.get('context', {}) if isinstance(task, dict) else {}
            self._direct_kernel_turn = False
            self._direct_kernel_complexity = None
            self._direct_kernel_reason = None
            try:
                from jarviscore.planning.classifier import ComplexityVerdict, TaskComplexityClassifier

                execution_contract: Dict[str, Any] = {}
                if isinstance(ctx, dict) and isinstance(ctx.get("execution_contract"), dict):
                    execution_contract = cast(Dict[str, Any], ctx.get("execution_contract"))
                if execution_contract.get("execution_shape") in {"single_response", "single_artifact"}:
                    complexity = ComplexityVerdict(
                        level="moderate",
                        reason=(
                            "Task execution contract declares a bounded single-turn "
                            f"{execution_contract.get('execution_shape')} deliverable."
                        ),
                    )
                else:
                    classifier = TaskComplexityClassifier(self.llm)
                    complexity = await classifier.classify(task_desc, context=ctx)
            except Exception as e:
                self._logger.error("[AutoAgent] Complexity classifier failed: %s", e)
                return {
                    "status": "failure",
                    "output": None,
                    "error": f"Complexity classification failed: {e}",
                    "agent_id": self.agent_id,
                    "role": self.role,
                    "goal_execution": {
                        "status": "failed",
                        "error": f"Complexity classification failed: {e}",
                        "steps_completed": 0,
                        "facts": 0,
                    },
                    "tokens": {},
                    "cost_usd": 0.0,
                    "repairs": 0,
                }

            if complexity is not None and complexity.level != "complex":
                self._logger.info(
                    "[AutoAgent] Task classified as %s; routing directly to Kernel: %s",
                    complexity.level,
                    complexity.reason,
                )
                self._direct_kernel_turn = True
                self._direct_kernel_complexity = complexity.level
                self._direct_kernel_reason = complexity.reason
            elif not getattr(self, '_direct_kernel_turn', False):
                if complexity is not None:
                    self._logger.info("[AutoAgent] Task classified as complex, routing to Planner.")
                execution = await self.execute_goal(
                    goal=task_desc,
                    context=ctx,
                )
                return {
                    "status": execution.status if execution.status != "complete" else "success",
                    "output": execution.result,
                    "error": execution.error,
                    "agent_id": self.agent_id,
                    "role": self.role,
                    "goal_execution": execution.to_summary_dict(),
                    "tokens": {},
                    "cost_usd": 0.0,
                    "repairs": 0,
                }

        # ── Build effective system prompt = profile intelligence + role prompt ──
        effective_system_prompt = (
            f"{self._profile_block}\n\n---\n\n{self.system_prompt}"
            if self._profile_block
            else self.system_prompt
        )

        # ── Kernel path (production pipeline) ────────────────────────────────
        if self._kernel is not None:
            # Lazily wire Mesh-injected auth into the Kernel.
            # _auth_manager is set by the Mesh AFTER setup() on agents with
            # requires_auth=True.  We forward it to the Kernel each call so the
            # CoderSubAgent can resolve credentials before sandbox execution.
            auth_mgr = getattr(self, '_auth_manager', None)
            if auth_mgr and self._kernel.auth_manager is not auth_mgr:
                self._kernel.auth_manager = auth_mgr
                self._logger.debug("Forwarded Mesh _auth_manager → Kernel")

            try:
                kernel_ctx = task.get('context') if isinstance(task, dict) else {}
                if kernel_ctx is None:
                    kernel_ctx = {}
                if getattr(self, "output_schema", None):
                    kernel_ctx["output_schema"] = self.output_schema

                output = await self._kernel.execute(
                    task=task_desc,
                    system_prompt=effective_system_prompt,
                    context=kernel_ctx,
                    agent_id=self.agent_id,
                    agent_default_role=self.default_kernel_role,
                    use_default_role_as_fallback=True,
                )

                meta = output.metadata or {}
                result = {
                    "status": output.status,
                    "output": output.payload,
                    "payload": output.payload,
                    "error": None if output.status == "success" else output.summary,
                    "tokens": meta.get("tokens", {"input": 0, "output": 0, "total": 0}),
                    "cost_usd": meta.get("cost_usd", 0.0),
                    "repairs": 0,
                    "agent_id": self.agent_id,
                    "role": self.role,
                    "function_id": meta.get("function_id"),
                    "dispatches": meta.get("dispatches", []),
                }

                if getattr(self, '_direct_kernel_turn', False):
                    elapsed_ms = meta.get("elapsed_ms", 0)
                    result["goal_execution"] = {
                        "steps_completed": 1,
                        "facts": 0,
                        "elapsed_ms": elapsed_ms,
                        "planner_mode": "direct_kernel",
                        "complexity": getattr(self, "_direct_kernel_complexity", None) or "moderate",
                        "reason": getattr(self, "_direct_kernel_reason", None),
                    }
                    self._direct_kernel_turn = False
                    self._direct_kernel_complexity = None
                    self._direct_kernel_reason = None

                if hasattr(self, 'result_handler') and self.result_handler:
                    _task_ctx = task.get('context', {}) if isinstance(task, dict) else {}
                    _ctx_meta = {
                        k: _task_ctx[k]
                        for k in ('task_type', 'task_label', 'session_id', 'workflow_id', 'step_id')
                        if isinstance(_task_ctx, dict) and _task_ctx.get(k)
                    }
                    stored = self.result_handler.process_result(
                        agent_id=self.agent_id,
                        task=task_desc,
                        code="(via Kernel)",
                        output=output.payload,
                        status=output.status,
                        error=result["error"],
                        execution_time=meta.get("elapsed_ms", 0) / 1000,
                        tokens=meta.get("tokens"),
                        cost_usd=meta.get("cost_usd"),
                        repairs=0,
                        metadata={
                            "role": self.role,
                            "capabilities": self.capabilities,
                            "pipeline": "kernel",
                            **_ctx_meta,
                        }
                    )
                    result["result_id"] = stored.get("result_id")

                if output.status == "success":
                    self._logger.info(
                        "✓ Kernel execution succeeded (agent=%s, dispatches=%d)",
                        self.agent_id, len(meta.get("dispatches", []))
                    )
                else:
                    self._logger.warning("✗ Kernel execution: %s", output.summary)

                return result

            except Exception as exc:
                self._logger.error(
                    "Kernel raised exception: %s", exc,
                    exc_info=True,
                )
                return {
                    "status": "failure",
                    "output": None,
                    "payload": None,
                    "error": f"Kernel exception: {exc}",
                    "tokens": {"input": 0, "output": 0, "total": 0},
                    "cost_usd": 0.0,
                    "repairs": 0,
                    "agent_id": self.agent_id,
                    "role": self.role,
                    "dispatches": [],
                }

        # ── Legacy pipeline (only when Kernel has not been initialised) ────────
        self._logger.warning("[AutoAgent] Using legacy direct-codegen pipeline for %s", self.agent_id)

        total_tokens = {"input": 0, "output": 0, "total": 0}
        total_cost = 0.0
        repairs_attempted = 0

        try:
            code_result = await cast(Any, self.codegen).generate(
                task=task,
                system_prompt=effective_system_prompt,
                context=task.get('context') if isinstance(task, dict) else None,
                enable_search=True,
            )
            exec_code = code_result if isinstance(code_result, str) else getattr(code_result, 'code', str(code_result))
            self._logger.debug(f"Generated {len(exec_code)} chars of code")

            result = await cast(Any, self.sandbox).execute(
                exec_code,
                context=task.get('context') if isinstance(task, dict) else None,
            )

            if result['status'] == 'failure':
                self._logger.info("Attempting autonomous repair...")
                repair_result = await cast(Any, self.repair).repair_with_retries(
                    code=exec_code,
                    error=Exception(result.get('error', 'Unknown error')),
                    task=task,
                    system_prompt=effective_system_prompt,
                    executor=cast(Any, self.sandbox),
                )
                result = repair_result
                repairs_attempted = len(repair_result.get('attempts', []))

            result['code'] = exec_code
            result['repairs'] = repairs_attempted
            result['agent_id'] = self.agent_id
            result['role'] = self.role
            if 'tokens' not in result:
                result['tokens'] = total_tokens
            if 'cost_usd' not in result:
                result['cost_usd'] = total_cost

            if hasattr(self, 'result_handler') and self.result_handler:
                _task_ctx = task.get('context', {}) if isinstance(task, dict) else {}
                _ctx_meta = {
                    k: _task_ctx[k]
                    for k in ('task_type', 'task_label', 'session_id', 'workflow_id', 'step_id')
                    if isinstance(_task_ctx, dict) and _task_ctx.get(k)
                }
                stored = self.result_handler.process_result(
                    agent_id=self.agent_id,
                    task=task_desc,
                    code=exec_code,
                    output=result.get('output'),
                    status=result['status'],
                    error=result.get('error'),
                    execution_time=result.get('execution_time'),
                    tokens=result.get('tokens'),
                    cost_usd=result.get('cost_usd'),
                    repairs=repairs_attempted,
                    metadata={
                        'role': self.role,
                        'capabilities': self.capabilities,
                        'pipeline': 'legacy',
                        **_ctx_meta,
                    },
                )
                result['result_id'] = stored.get('result_id')

            if result['status'] == 'success' and hasattr(self, 'code_registry') and self.code_registry:
                func_name = re.sub(r'[^a-z0-9_]', '_', task_desc.lower())[:50].strip('_')
                func_name = func_name or f"task_{result.get('result_id', 'unknown')}"
                registered = self.code_registry.register_function(
                    function_name=func_name,
                    function=exec_code,
                    metadata={
                        'agent_id': self.agent_id,
                        'task': task_desc,
                        'capabilities': self.capabilities,
                        'system': task.get('system') if isinstance(task, dict) else None,
                        'description': task_desc,
                        'strategy': 'sandbox',
                        'tags': [self.role],
                        'type': 'utility',
                    }
                )
                if registered:
                    self.code_registry.update_execution_stats(
                        func_name,
                        success=True,
                        execution_time=result.get('execution_time', 0.0),
                    )
                result['function_id'] = func_name
                self._logger.info(f"✓ Task completed (legacy, function_id: {func_name})")
            else:
                self._logger.error(f"✗ Task failed: {result.get('error')}")

            return result

        except Exception as e:
            self._logger.error(f"Fatal error in execute_task: {e}", exc_info=True)
            return {
                "status": "failure",
                "error": f"Fatal error: {str(e)}",
                "error_type": type(e).__name__,
                "agent_id": self.agent_id,
                "role": self.role,
                "repairs": repairs_attempted,
                "tokens": total_tokens,
                "cost_usd": total_cost,
            }

    # ── Long-horizon goal execution ───────────────────────────────────────────

    def _hitl_category_from_output(self, output: Any) -> str:
        """Map Kernel yield metadata to the strict HITL category contract."""
        metadata = getattr(output, "metadata", None) or {}
        typed_outcome = str(metadata.get("typed_outcome", "")).lower()
        reason = str(metadata.get("escalation_reason", "")).lower()

        if "auth" in typed_outcome or "auth" in reason:
            return "auth_required"
        if any(marker in reason for marker in ("approve", "irreversible", "sensitive", "critical")):
            return "critical_action"
        return "data_required"

    async def execute_goal(
        self,
        goal: str,
        context: Optional[Dict[str, Any]] = None,
        max_steps: int = 30,
        max_replan_attempts: Optional[int] = None,
    ) -> "GoalExecution":
        """
        Internal method — driven by execute_task() when goal_oriented = True.

        Executes a goal via the Plan → Execute → Evaluate loop. Developers
        do NOT call this directly. The entry point is always execute_task()
        with a standard task dict — the framework routes internally based on
        the goal_oriented class attribute.

        Developer contract (unchanged):
            class MyAgent(AutoAgent):
                role = "researcher"
                capabilities = ["research", "analysis"]
                system_prompt = "You are a market researcher..."
                goal_oriented = True   # ← only thing a dev adds

            # Called exactly as before — no API change:
            result = await mesh.workflow("research", [{
                "agent": "researcher",
                "task": "Produce EV market analysis"
            }])
            result["status"]          # "success" | "failure" | "hitl"
            result["output"]          # final synthesised answer
            result["goal_execution"]  # summary dict: steps, facts, elapsed

        Framework internals (for framework contributors):
            The GoalExecution object carries the live TruthContext (all facts
            accumulated across steps) and the full step history. These are
            summarised into the standard execute_task() envelope before returning.

        Args:
            goal:                 Natural language goal string (from execute_task).
            context:              Initial context dict (from the task dict).
            max_steps:            Hard ceiling on steps (safety guard, default 30).
                                  Override via MAX_GOAL_STEPS env var.
            max_replan_attempts:  Max replanning cycles before failing (default 8,
                                  override with MAX_REPLAN_ATTEMPTS env var).

        Returns:
            GoalExecution — summarised into execute_task() response by the caller.
        """
        # Resolve at call-time so .env / dotenv loaders are respected
        if max_replan_attempts is None:
            max_replan_attempts = int(os.environ.get("MAX_REPLAN_ATTEMPTS", "8"))
        # Allow env override of step ceiling without code changes
        env_max_steps = os.environ.get("MAX_GOAL_STEPS")
        if env_max_steps:
            max_steps = int(env_max_steps)
        if self._kernel is None:
            raise RuntimeError(
                f"{self.__class__.__name__}.execute_goal() called before setup(). "
                "Call await agent.setup() first."
            )

        from jarviscore.planning.goal_context import GoalExecution
        from jarviscore.planning.planner import Planner, PlannerError
        from jarviscore.planning.evaluator import StepEvaluator, EvaluatorError
        from jarviscore.context.distillation import merge_facts

        self._logger.info(
            "[AutoAgent] execute_goal started: goal=%s (max_steps=%d)",
            goal[:100], max_steps,
        )

        effective_system_prompt = (
            f"{self._profile_block}\n\n---\n\n{self.system_prompt}"
            if self._profile_block else self.system_prompt
        )

        # Shared planner and evaluator — stateless, reused across steps
        planner = Planner(self.llm, system_prompt_excerpt=str(self.system_prompt or "")[:400])
        evaluator = StepEvaluator(self.llm)

        # The live execution state — carries the TruthContext across all steps
        execution = GoalExecution(goal=goal, agent_id=self.agent_id)
        replan_count = 0
        steps_run = 0

        # ── Phase 1: Plan ─────────────────────────────────────────────────────
        execution.status = "planning"
        try:
            execution.plan = await planner.plan(
                goal=goal,
                goal_execution=execution,
                context=context,
            )
        except PlannerError as exc:
            self._logger.error("[AutoAgent] Planning failed: %s", exc)
            execution.status = "failed"
            execution.error = f"Planning failed: {exc}"
            execution.completed_at = time.time()
            return execution

        self._logger.info(
            "[AutoAgent] Plan ready: %d steps", len(execution.plan)
        )
        execution.status = "executing"

        # ── Phase 2: Execute → Evaluate → loop ───────────────────────────────
        remaining = list(execution.plan)

        while remaining and steps_run < max_steps:
            step = remaining.pop(0)
            steps_run += 1

            self._logger.info(
                "[AutoAgent] Executing step %d/%d: %s [%s]",
                steps_run, len(execution.plan), step.step_id, step.task[:80],
            )

            # Build enriched context: accumulated facts + step metadata
            step_ctx = execution.context_for_next_step(base_context=context)
            step_ctx.update(step.to_context_extras())

            # ── Execute step via Kernel (full OODA) ───────────────────────────
            step_start = time.time()
            try:
                auth_mgr = getattr(self, '_auth_manager', None)
                if auth_mgr and self._kernel.auth_manager is not auth_mgr:
                    self._kernel.auth_manager = auth_mgr

                output = await self._kernel.execute(
                    task=step.task,
                    system_prompt=effective_system_prompt,
                    context=step_ctx,
                    agent_id=self.agent_id,
                    agent_default_role=step.subagent_hint or self.default_kernel_role,
                )
            except Exception as exc:
                self._logger.error(
                    "[AutoAgent] Kernel raised on step %s: %s", step.step_id, exc
                )
                execution.status = "failed"
                execution.error = f"Kernel exception on step {step.step_id}: {exc}"
                execution.completed_at = time.time()
                return execution

            elapsed = (time.time() - step_start) * 1000

            # ── Promote goal-scoped scratchpad entries into TruthContext ──────
            if self._kernel.blob_storage:
                try:
                    from jarviscore.memory.scratchpad import WorkingScratchpad
                    pad = WorkingScratchpad(
                        self._kernel.blob_storage,
                        workflow_id=step_ctx.get("workflow_id", execution.goal_id),
                        step_id=step.step_id,
                        role=self.role,
                    )
                    await pad.promote_to_truth(execution.truth, source=step.step_id)
                except Exception as _se:
                    self._logger.debug(
                        "[AutoAgent] Scratchpad promote failed (non-fatal): %s", _se
                    )

            # ── Evaluate step ─────────────────────────────────────────────────
            try:
                evaluation = await evaluator.evaluate(step, output, execution)
            except EvaluatorError as exc:
                self._logger.error(
                    "[AutoAgent] Evaluation failed on step %s: %s", step.step_id, exc
                )
                execution.status = "failed"
                execution.error = f"Evaluation error on step {step.step_id}: {exc}"
                execution.completed_at = time.time()
                return execution

            # Record: merges distilled_facts + evaluator findings into truth
            execution.record_completed(step, output, evaluation, elapsed)

            self._logger.info(
                "[AutoAgent] Step %s: verdict=%s (confidence=%.2f) — %s",
                step.step_id, evaluation.verdict, evaluation.confidence,
                evaluation.evaluator_note[:120],
            )

            # ── Handle verdict ────────────────────────────────────────────────
            if evaluation.needs_hitl:
                # Audit log: only genuine HITL escalations reach here now
                # (routine budget yields are downgraded to partial by evaluator)
                self._logger.info(
                    "[AutoAgent] HITL escalation — cause: %s",
                    evaluation.evaluator_note[:200],
                )
                execution.status = "hitl"
                execution.error = evaluation.evaluator_note
                execution.completed_at = time.time()
                self._logger.warning(
                    "[AutoAgent] Goal execution paused for HITL: %s",
                    evaluation.evaluator_note,
                )
                # Submit via the native HITLQueue (injected by Mesh).
                # The queue handles content truncation and typed persistence.
                _hitl = getattr(self, "hitl", None)
                if _hitl is not None:
                    display_name = self.__class__.__name__
                    try:
                        _hitl.request(
                            title=f"{display_name}: human review needed — {step.task[:200]}",
                            content=(
                                f"**Agent:** {display_name} (`{self.agent_id}`)\n\n"
                                f"**Goal:** {goal[:500]}\n\n"
                                f"**Step:** `{step.step_id}` — {step.task[:500]}\n\n"
                                f"**Why HITL:** {evaluation.evaluator_note}\n\n"
                                f"**Confidence:** {evaluation.confidence:.0%}"
                            ),
                            urgency="normal",
                            category=self._hitl_category_from_output(output),
                            context={
                                "goal": goal,
                                "step_id": step.step_id,
                                "step_task": step.task,
                                "evaluator_note": evaluation.evaluator_note,
                                "confidence": evaluation.confidence,
                                "agent_id": self.agent_id,
                                "display_name": display_name,
                            },
                        )
                    except Exception as _he:
                        self._logger.warning("[AutoAgent] hitl.request() failed (non-fatal): %s", _he)
                return execution

            if evaluation.needs_replan:
                if replan_count >= max_replan_attempts:
                    self._logger.error(
                        "[AutoAgent] Max replan attempts (%d) reached. Failing goal.",
                        max_replan_attempts,
                    )
                    execution.status = "failed"
                    execution.error = (
                        f"Max replan attempts ({max_replan_attempts}) reached. "
                        f"Last failure: {evaluation.evaluator_note}"
                    )
                    execution.completed_at = time.time()
                    return execution

                replan_count += 1
                self._logger.info(
                    "[AutoAgent] Replanning (attempt %d/%d): %s",
                    replan_count, max_replan_attempts, evaluation.evaluator_note,
                )
                try:
                    completed_step = execution.completed[-1]
                    revised = await planner.replan(
                        goal_execution=execution,
                        failed_step=completed_step,
                        reason=evaluation.evaluator_note,
                    )
                    execution.plan_revision += 1
                    remaining = revised   # replace remaining steps with revised plan
                    execution.plan = [cs.step for cs in execution.completed] + revised
                    self._logger.info(
                        "[AutoAgent] Revised plan: %d remaining steps", len(revised)
                    )
                except PlannerError as pe:
                    self._logger.error("[AutoAgent] Replanning failed: %s", pe)
                    execution.status = "failed"
                    execution.error = f"Replanning failed: {pe}"
                    execution.completed_at = time.time()
                    return execution

                continue  # proceed with revised plan

        # ── Phase 3: Safety check ─────────────────────────────────────────────
        if steps_run >= max_steps and remaining:
            self._logger.warning(
                "[AutoAgent] max_steps=%d reached with %d steps still remaining.",
                max_steps, len(remaining),
            )
            execution.status = "blocked"
            execution.error = (
                f"Goal execution stopped at max_steps={max_steps}. "
                f"{len(remaining)} steps were not executed."
            )
            execution.completed_at = time.time()
            return execution

        # ── Phase 4: Synthesise final result ──────────────────────────────────
        execution.status = "complete"
        execution.completed_at = time.time()

        # Final result = last step's output summary + high-confidence facts
        if execution.completed:
            last = execution.completed[-1]
            last_summary = getattr(last.output, "summary", "") or ""
            high_conf = execution.truth.high_confidence_facts(threshold=0.7)
            facts_str = (
                "\n".join(f"- {k}: {v.value}" for k, v in high_conf.items())
                if high_conf else ""
            )
            execution.result = (
                f"{last_summary}\n\n{facts_str}".strip()
                if facts_str else last_summary
            )
        else:
            execution.result = "Goal completed with no steps executed."

        self._logger.info(
            "[AutoAgent] Goal complete: %d steps, %d facts, %.0fms | %s",
            execution.steps_completed,
            len(execution.truth.facts),
            execution.elapsed_ms,
            goal[:80],
        )
        return execution
