"""
Agent base class - defines WHAT an agent does (role, capabilities).

This is the foundation of the JarvisCore framework. All agents inherit from this class.
"""
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
from uuid import uuid4
import logging

logger = logging.getLogger(__name__)


class Agent(ABC):
    """
    Base class for all agents in JarvisCore framework.

    Agents define WHAT they do via class attributes:
    - role: The agent's role identifier
    - capabilities: List of capabilities this agent provides

    Subclasses (Profiles) define HOW they execute tasks.

    Example:
        class MyAgent(PromptDevAgent):
            role = "scraper"
            capabilities = ["web_scraping", "data_extraction"]
            system_prompt = "You are an expert web scraper..."
    """

    # Class attributes - user must define these
    role: str = None
    capabilities: List[str] = []

    def __init__(self, agent_id: Optional[str] = None):
        """
        Initialize agent with validation.

        Args:
            agent_id: Optional unique identifier (auto-generated if not provided)

        Raises:
            ValueError: If role or capabilities are not defined
        """
        # Validate required attributes
        if not self.role:
            raise ValueError(
                f"{self.__class__.__name__} must define 'role' class attribute\n"
                f"Example: role = 'scraper'"
            )

        if not self.capabilities:
            raise ValueError(
                f"{self.__class__.__name__} must define 'capabilities' class attribute\n"
                f"Example: capabilities = ['web_scraping']"
            )

        # Initialize instance attributes
        self.agent_id = agent_id or f"{self.role}-{uuid4().hex[:8]}"
        self._mesh = None  # Set by Mesh when agent is added
        self._logger = logging.getLogger(f"jarviscore.agent.{self.agent_id}")

        self._logger.debug(f"Agent initialized: {self.agent_id}")

    @abstractmethod
    async def execute_task(self, task: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute a task (implemented by profile subclasses).

        This defines HOW the agent executes tasks. Different profiles implement
        this differently:
        - PromptDevAgent: LLM code generation + sandbox execution
        - MCPAgent: User-defined MCP tool calls

        Args:
            task: Task specification containing:
                - task (str): Task description
                - id (str): Task identifier
                - params (dict, optional): Additional parameters

        Returns:
            Result dictionary containing:
                - status (str): "success" or "failure"
                - output (Any): Task output
                - error (str, optional): Error message if failed
                - tokens_used (int, optional): LLM tokens consumed
                - cost_usd (float, optional): Cost in USD

        Raises:
            NotImplementedError: If subclass doesn't implement this method
        """
        raise NotImplementedError(
            f"{self.__class__.__name__} must implement execute_task()"
        )

    async def setup(self):
        """
        Optional setup hook called when agent joins mesh.

        Override this to perform initialization:
        - Connect to external services
        - Load models
        - Setup resources

        Example:
            async def setup(self):
                await super().setup()
                self.db = await connect_to_database()
        """
        self._logger.info(f"Setting up agent: {self.agent_id}")

    async def teardown(self):
        """
        Optional cleanup hook called when agent leaves mesh.

        Override this to cleanup resources:
        - Close connections
        - Save state
        - Release resources

        Example:
            async def teardown(self):
                await self.db.close()
                await super().teardown()
        """
        self._logger.info(f"Tearing down agent: {self.agent_id}")

    def can_handle(self, task: Dict[str, Any]) -> bool:
        """
        Check if agent can handle a task based on capabilities.

        Args:
            task: Task specification with 'capability' or 'role' key

        Returns:
            True if agent has the required capability

        Example:
            task = {"task": "Scrape website", "role": "scraper"}
            if agent.can_handle(task):
                result = await agent.execute_task(task)
        """
        required = task.get("capability") or task.get("role")
        can_handle = required in self.capabilities or required == self.role

        self._logger.debug(
            f"Can handle task requiring '{required}': {can_handle}"
        )

        return can_handle

    def __repr__(self) -> str:
        """String representation of agent."""
        return (
            f"<{self.__class__.__name__} "
            f"id={self.agent_id} "
            f"role={self.role} "
            f"capabilities={self.capabilities}>"
        )

    def __str__(self) -> str:
        """Human-readable string representation."""
        return f"{self.role} ({self.agent_id})"
