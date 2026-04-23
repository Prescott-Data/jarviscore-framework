"""
AutoAgent - Automated execution profile.

Framework generates and executes code from natural language prompts.
User writes just 3 attributes, framework handles everything.
"""
import re
from typing import Dict, Any
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
    # Fix for Dogfooding Issue #2.
    default_kernel_role: str = None

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
        - Internet search (DuckDuckGo, no API key needed)
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
