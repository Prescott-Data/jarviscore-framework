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
from typing import Any, Dict, List, Optional
from jarviscore.core.profile import Profile


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

    # Additional user-defined attribute (beyond Agent base class)
    system_prompt: str = None

    # Optional: declare which kernel subagent role this agent should always use.
    # Overrides the keyword classifier in Kernel._classify_task().
    # Values: "coder" | "researcher" | "communicator" | None (auto-classify)
    # Example: class Sentinel(AutoAgent): default_kernel_role = "researcher"
    default_kernel_role: str = None

    # ── Long-horizon execution mode ──────────────────────────────────────────
    # Set goal_oriented = True on your AutoAgent subclass to route ALL tasks
    # through the Plan → Execute → Evaluate loop automatically.
    #
    # When False (default), execute_task() runs a single OODA loop — correct
    # for bounded, atomic tasks.
    #
    # When True, the SAME execute_task() call the developer already makes is
    # routed internally through Plan-Execute. The developer writes NOTHING
    # extra — just sets this flag and the framework handles the rest.
    #
    # The execute_task() response envelope is preserved:
    #   result["status"]           — "success" | "failure" | "hitl"
    #   result["output"]           — final synthesised output
    #   result["goal_execution"]  — summary dict (steps, facts, elapsed)
    #
    # Example:
    #     class ResearchAgent(AutoAgent):
    #         role = "researcher"
    #         capabilities = ["research", "analysis"]
    #         system_prompt = "You are a market researcher..."
    #         goal_oriented = True   # ← that's it. framework does the rest.
    goal_oriented: bool = False

    def __init__(self, agent_id=None):
        super().__init__(agent_id)

        if not self.system_prompt:
            raise ValueError(
                f"{self.__class__.__name__} must define 'system_prompt' class attribute\n"
                f"Example: system_prompt = 'You are an expert...'"
            )

        # Execution components (initialized in setup())
        self.llm = None
        self.codegen = None
        self.sandbox = None
        self.repair = None
        self._kernel = None  # Production Kernel (registry-first → coder → research-on-failure)

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
        self._logger.info(f"  System Prompt: {self.system_prompt[:50]}...")

        # ── Load agent intelligence profile ─────────────────────────────────────
        # Loads jarviscore/profiles/agents/{role}.yaml if it exists.
        # Graceful no-op if PyYAML not installed or profile file absent.
        try:
            from jarviscore.profiles.agent_profile import AgentProfile
            profile = AgentProfile.load(self.role)
            if profile:
                self._profile_block = profile.to_prompt_block()
                self._logger.info(
                    "[AutoAgent] Loaded intelligence profile for role=%s "
                    "(%d SOPs, %d owns)",
                    self.role, len(profile.sops), len(profile.owns)
                )
            else:
                self._logger.debug("[AutoAgent] No intelligence profile for role=%s", self.role)
        except Exception as _pe:
            self._logger.debug("[AutoAgent] Profile load failed (non-fatal): %s", _pe)


        # Get config from mesh (or use empty dict)
        config = self._mesh.config if self._mesh else {}

        # Import execution components
        from jarviscore.execution import (
            create_llm_client,
            create_search_client,
            create_code_generator,
            create_sandbox_executor,
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

        # 4. Initialize sandbox executor (with search access)
        timeout = config.get('execution_timeout', 300)
        self._logger.info(f"Initializing sandbox executor ({timeout}s timeout)...")
        self.sandbox = create_sandbox_executor(timeout, self.search, config)

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

        # NOTE: AuthenticationManager is NOT created here.
        # The Mesh owns auth — it creates AuthenticationManager from mesh config
        # and injects it as self._auth_manager on agents with requires_auth=True.
        # Injection happens AFTER setup() completes (see mesh.py:292-312).
        # The Kernel receives _auth_manager lazily at execute_task() time.

        self._logger.info(f"✓ AutoAgent ready: {self.agent_id}")

    async def execute_task(self, task: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute task through the production Kernel pipeline.

        Pipeline (matches integration-agent staging branch):
        1. Registry-first: check FunctionRegistry for verified function (Option A)
        2. Coder writes from training knowledge + ValidationLayer gate (Option B)
        3. Sandbox execution — real test
        4. Research-on-failure ONLY (Option C) — researcher fires with real error
        5. Auto-register success in FunctionRegistry (CANDIDATE → VERIFIED → GOLDEN)

        Falls back to legacy direct codegen pipeline if Kernel unavailable.

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
        # If goal_oriented=True, every task is a goal — route to execute_goal().
        if self.goal_oriented:
            ctx = task.get('context', {}) if isinstance(task, dict) else {}
            execution = await self.execute_goal(
                goal=task_desc,
                context=ctx,
            )
            # Wrap GoalExecution in the standard execute_task() response envelope
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
                output = await self._kernel.execute(
                    task=task_desc,
                    system_prompt=effective_system_prompt,
                    context=task.get('context') if isinstance(task, dict) else None,
                    agent_id=self.agent_id,
                    agent_default_role=self.default_kernel_role,
                )

                meta = output.metadata or {}
                result = {
                    "status": output.status,
                    "output": output.payload,
                    "error": None if output.status == "success" else output.summary,
                    "tokens": meta.get("tokens", {"input": 0, "output": 0, "total": 0}),
                    "cost_usd": meta.get("cost_usd", 0.0),
                    "repairs": 0,
                    "agent_id": self.agent_id,
                    "role": self.role,
                    "function_id": meta.get("function_id"),
                    "dispatches": meta.get("dispatches", []),
                }

                if hasattr(self, 'result_handler') and self.result_handler:
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
                    "Kernel raised exception — falling back to legacy pipeline: %s", exc,
                    exc_info=True,
                )
                # Fall through to legacy pipeline

        # ── Legacy pipeline (fallback if Kernel unavailable or crashed) ────────
        self._logger.warning("[AutoAgent] Using legacy direct-codegen pipeline for %s", self.agent_id)

        total_tokens = {"input": 0, "output": 0, "total": 0}
        total_cost = 0.0
        repairs_attempted = 0

        try:
            code_result = await self.codegen.generate(
                task=task,
                system_prompt=effective_system_prompt,
                context=task.get('context') if isinstance(task, dict) else None,
                enable_search=True,
            )
            exec_code = code_result if isinstance(code_result, str) else getattr(code_result, 'code', str(code_result))
            self._logger.debug(f"Generated {len(exec_code)} chars of code")

            result = await self.sandbox.execute(
                exec_code,
                context=task.get('context') if isinstance(task, dict) else None,
            )

            if result['status'] == 'failure':
                self._logger.info("Attempting autonomous repair...")
                repair_result = await self.repair.repair_with_retries(
                    code=exec_code,
                    error=Exception(result.get('error', 'Unknown error')),
                    task=task,
                    system_prompt=effective_system_prompt,
                    executor=self.sandbox,
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

    async def execute_goal(
        self,
        goal: str,
        context: Optional[Dict[str, Any]] = None,
        max_steps: int = 15,
        max_replan_attempts: int = int(os.environ.get("MAX_REPLAN_ATTEMPTS", "4")),
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
            max_steps:            Hard ceiling on steps (safety guard, default 15).
            max_replan_attempts:  Max replanning cycles before failing (default 4,
                                  override with MAX_REPLAN_ATTEMPTS env var).

        Returns:
            GoalExecution — summarised into execute_task() response by the caller.
        """
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
        planner = Planner(self.llm, system_prompt_excerpt=self.system_prompt[:400])
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
                execution.status = "hitl"
                execution.error = evaluation.evaluator_note
                execution.completed_at = time.time()
                self._logger.warning(
                    "[AutoAgent] Goal execution paused for HITL: %s",
                    evaluation.evaluator_note,
                )
                # Surface the HITL request on the dashboard via the injected queue.
                # self.hitl is always available (injected by Mesh at start time).
                _hitl = getattr(self, "hitl", None)
                if _hitl is not None:
                    try:
                        _hitl.request(
                            title=f"{self.role}: human review needed — {step.task[:80]}",
                            content=(
                                f"**Goal:** {goal}\n\n"
                                f"**Step:** {step.task}\n\n"
                                f"**Why HITL:** {evaluation.evaluator_note}\n\n"
                                f"**Confidence:** {evaluation.confidence:.0%}"
                            ),
                            urgency="normal",
                            context={
                                "goal": goal,
                                "step_id": step.step_id,
                                "step_task": step.task,
                                "evaluator_note": evaluation.evaluator_note,
                                "confidence": evaluation.confidence,
                                "agent_id": self.agent_id,
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
