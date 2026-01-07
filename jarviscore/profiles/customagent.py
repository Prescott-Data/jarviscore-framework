"""
CustomAgent - User-controlled execution profile.

User provides their own implementation using any framework:
- LangChain
- MCP (Model Context Protocol)
- CrewAI
- Raw Python
- Any other tool/framework
"""
from typing import Dict, Any
from jarviscore.core.profile import Profile


class CustomAgent(Profile):
    """
    Custom execution profile with full user control.

    User defines:
    - role: str
    - capabilities: List[str]
    - setup(): Initialize custom framework/tools
    - execute_task(): Custom execution logic

    Framework provides:
    - Orchestration (task claiming, dependencies, nudging)
    - P2P coordination (agent discovery, task routing)
    - State management (crash recovery, HITL)
    - Cost tracking (if user provides token counts)

    Example with LangChain:
        class APIAgent(CustomAgent):
            role = "api_client"
            capabilities = ["api_calls"]

            async def setup(self):
                await super().setup()
                from langchain.agents import Agent
                self.lc_agent = Agent(...)

            async def execute_task(self, task):
                result = await self.lc_agent.run(task["task"])
                return {"status": "success", "output": result}

    Example with MCP:
        class MCPAgent(CustomAgent):
            role = "tool_user"
            capabilities = ["mcp_tools"]
            mcp_server_url = "stdio://./server.py"

            async def setup(self):
                await super().setup()
                from mcp import Client
                self.mcp = Client(self.mcp_server_url)
                await self.mcp.connect()

            async def execute_task(self, task):
                result = await self.mcp.call_tool("my_tool", task["params"])
                return {"status": "success", "data": result}

    Example with Raw Python:
        class DataProcessor(CustomAgent):
            role = "processor"
            capabilities = ["data_processing"]

            async def execute_task(self, task):
                # Pure Python logic
                data = task["params"]["data"]
                processed = [x * 2 for x in data]
                return {"status": "success", "output": processed}
    """

    def __init__(self, agent_id=None):
        super().__init__(agent_id)

        # User can add any custom attributes
        # e.g., mcp_server_url, langchain_config, etc.

    async def setup(self):
        """
        User implements this to initialize custom framework/tools.

        DAY 1: Base implementation (user overrides)
        DAY 5+: Full examples with LangChain, MCP, etc.

        Example:
            async def setup(self):
                await super().setup()
                # Initialize your framework
                from langchain.agents import Agent
                self.agent = Agent(...)
        """
        await super().setup()

        self._logger.info(f"CustomAgent setup: {self.agent_id}")
        self._logger.info(
            f"  Note: Override setup() to initialize your custom framework"
        )

    async def execute_task(self, task: Dict[str, Any]) -> Dict[str, Any]:
        """
        User implements this with custom execution logic.

        DAY 1: Raises NotImplementedError (user must override)
        DAY 5+: Full examples provided

        Args:
            task: Task specification

        Returns:
            Result dictionary with at least:
            - status: "success" or "failure"
            - output: Task result
            - error (optional): Error message if failed
            - tokens_used (optional): For cost tracking
            - cost_usd (optional): For cost tracking

        Raises:
            NotImplementedError: User must override this method

        Example:
            async def execute_task(self, task):
                result = await self.my_framework.run(task)
                return {
                    "status": "success",
                    "output": result,
                    "tokens_used": 1000,  # Optional
                    "cost_usd": 0.002     # Optional
                }
        """
        raise NotImplementedError(
            f"{self.__class__.__name__} must implement execute_task()\n\n"
            f"Example:\n"
            f"    async def execute_task(self, task):\n"
            f"        result = await self.my_framework.run(task['task'])\n"
            f"        return {{'status': 'success', 'output': result}}\n"
        )
