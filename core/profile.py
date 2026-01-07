"""
Profile base class - defines HOW agents execute tasks.

Profiles are execution strategies:
- AutoAgent: Automated execution via LLM code generation (framework does everything)
- CustomAgent: Custom execution with user-defined logic (user has full control)
"""
from abc import ABC
from .agent import Agent


class Profile(Agent):
    """
    Abstract base for execution profiles.

    Profiles define HOW agents execute tasks, while the Agent base class
    defines WHAT they do (role, capabilities).

    This is an intermediate layer between Agent and concrete implementations
    (AutoAgent, CustomAgent). It provides a common place for profile-specific
    setup and teardown logic.

    Note: This class is optional - profiles can directly inherit from Agent.
    We use it to make the architecture clearer: Agent (WHAT) → Profile (HOW) → Concrete.
    """

    def __init__(self, agent_id=None):
        super().__init__(agent_id)

        # Profile-specific execution engine (initialized by subclasses)
        self._execution_engine = None

    async def setup(self):
        """
        Setup execution engine.

        Subclasses override to initialize their specific execution engines:
        - AutoAgent: LLM client, code generator, sandbox executor
        - CustomAgent: User's custom framework (LangChain, MCP, etc.)

        Example:
            async def setup(self):
                await super().setup()
                self.llm = create_llm_client(config)
                self.codegen = CodeGenerator(self.llm)
        """
        await super().setup()
        self._logger.debug(f"Profile setup: {self.__class__.__name__}")

    async def teardown(self):
        """
        Cleanup execution engine.

        Subclasses override to cleanup their specific resources.

        Example:
            async def teardown(self):
                await self.llm.close()
                await super().teardown()
        """
        await super().teardown()
        self._logger.debug(f"Profile teardown: {self.__class__.__name__}")

    # execute_task() remains abstract - implemented by concrete profiles
