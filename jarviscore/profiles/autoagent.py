"""
AutoAgent - Automated execution profile.

Framework generates and executes code from natural language prompts.
User writes just 3 attributes, framework handles everything.
"""
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

    def __init__(self, agent_id=None):
        super().__init__(agent_id)

        if not self.system_prompt:
            raise ValueError(
                f"{self.__class__.__name__} must define 'system_prompt' class attribute\n"
                f"Example: system_prompt = 'You are an expert...'"
            )

        # Execution components (initialized in setup() on Day 4)
        self.llm = None
        self.codegen = None
        self.sandbox = None
        self.repair = None

    async def setup(self):
        """
        Initialize LLM and execution components with ZERO CONFIG.

        Framework auto-detects available LLM providers and sets up:
        - LLM client (tries vLLM → Azure → Gemini → Claude)
        - Internet search (DuckDuckGo, no API key needed)
        - Code generator with search injection
        - Sandbox executor with timeout
        - Autonomous repair system
        """
        await super().setup()

        self._logger.info(f"AutoAgent setup: {self.agent_id}")
        self._logger.info(f"  Role: {self.role}")
        self._logger.info(f"  Capabilities: {self.capabilities}")
        self._logger.info(f"  System Prompt: {self.system_prompt[:50]}...")

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
            create_code_registry
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

        # 7. Initialize code registry (reusable generated functions)
        registry_dir = f"{log_dir}/code_registry"
        self._logger.info(f"Initializing code registry (dir: {registry_dir})...")
        self.code_registry = create_code_registry(registry_dir)

        self._logger.info(f"✓ AutoAgent ready: {self.agent_id}")

    async def execute_task(self, task: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute task via LLM code generation with automatic repair.

        Pipeline:
        1. Generate Python code from natural language task
        2. Execute code in sandbox
        3. If fails → autonomous repair (up to 3 attempts)
        4. Return result with tokens/cost

        Args:
            task: Task specification with 'task' key (natural language)

        Returns:
            {
                "status": "success" | "failure",
                "output": Any,  # Task result
                "error": str,   # Error if failed
                "tokens": {...},  # Token usage
                "cost_usd": float,
                "code": str,    # Generated code
                "repairs": int  # Number of repair attempts
            }

        Example:
            result = await agent.execute_task({
                "task": "Calculate factorial of 10"
            })
        """
        task_desc = task.get('task', '')
        self._logger.info(f"[AutoAgent] Executing: {task_desc[:80]}...")

        total_tokens = {"input": 0, "output": 0, "total": 0}
        total_cost = 0.0
        repairs_attempted = 0

        try:
            # Step 1: Generate code from natural language
            self._logger.info("Step 1: Generating code...")
            code = await self.codegen.generate(
                task=task,
                system_prompt=self.system_prompt,
                context=task.get('context'),  # Dependencies from previous steps
                enable_search=True
            )

            # Track generation cost (from LLM response)
            # Note: codegen now returns just code, cost tracked in llm
            self._logger.debug(f"Generated {len(code)} characters of code")

            # Step 2: Execute in sandbox
            self._logger.info("Step 2: Executing code in sandbox...")
            result = await self.sandbox.execute(code)

            # Step 3: Handle execution failure with autonomous repair
            if result['status'] == 'failure':
                self._logger.warning(f"Execution failed: {result.get('error')}")
                self._logger.info("Step 3: Attempting autonomous repair...")

                # Use repair system with automatic retries
                repair_result = await self.repair.repair_with_retries(
                    code=code,
                    error=Exception(result.get('error', 'Unknown error')),
                    task=task,
                    system_prompt=self.system_prompt,
                    executor=self.sandbox
                )

                # Update result and track repairs
                result = repair_result
                repairs_attempted = len(repair_result.get('attempts', []))
                self._logger.info(f"Repair attempts: {repairs_attempted}")

            # Enrich result with metadata
            result['code'] = code
            result['repairs'] = repairs_attempted
            result['agent_id'] = self.agent_id
            result['role'] = self.role

            # Add token/cost info if not already present
            if 'tokens' not in result:
                result['tokens'] = total_tokens
            if 'cost_usd' not in result:
                result['cost_usd'] = total_cost

            # Store result to file system + in-memory cache
            stored_result = self.result_handler.process_result(
                agent_id=self.agent_id,
                task=task_desc,
                code=code,
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
                    'system_prompt': self.system_prompt[:100]  # First 100 chars
                }
            )

            # Add result_id to response
            result['result_id'] = stored_result['result_id']

            # Register successful code in registry for reuse
            if result['status'] == 'success':
                function_id = self.code_registry.register(
                    code=code,
                    agent_id=self.agent_id,
                    task=task_desc,
                    capabilities=self.capabilities,
                    output=result.get('output'),
                    result_id=result['result_id'],
                    metadata={
                        'role': self.role,
                        'execution_time': result.get('execution_time'),
                        'repairs': repairs_attempted
                    }
                )
                result['function_id'] = function_id
                self._logger.info(f"✓ Task completed successfully (result_id: {result['result_id']}, function_id: {function_id})")
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
                "cost_usd": total_cost
            }
