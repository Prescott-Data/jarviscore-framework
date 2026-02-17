"""
6C: BaseSubAgent — Abstract base for all kernel subagents.

Subagents are specialized execution units dispatched by the kernel.
Each has a set of tools, a system prompt, and uses a text-based
tool call protocol that works with any LLM provider.

Tool call protocol (LLM output):
    THOUGHT: <reasoning>
    TOOL: <tool_name>
    PARAMS: <json>

Completion protocol:
    THOUGHT: <reasoning>
    DONE: <summary>
    RESULT: <json>
"""

import json
import logging
import re
from abc import ABC, abstractmethod
from typing import Any, Callable, Dict, List, Optional

from jarviscore.context.truth import AgentOutput

logger = logging.getLogger(__name__)

# Regex patterns for parsing LLM tool call responses
_TOOL_PATTERN = re.compile(r"^TOOL:\s*(.+)$", re.MULTILINE)
_PARAMS_PATTERN = re.compile(r"^PARAMS:\s*(.+)$", re.MULTILINE | re.DOTALL)
_DONE_PATTERN = re.compile(r"^DONE:\s*(.+)$", re.MULTILINE)
_RESULT_PATTERN = re.compile(r"^RESULT:\s*(.+)$", re.MULTILINE | re.DOTALL)
_THOUGHT_PATTERN = re.compile(r"^THOUGHT:\s*(.+?)(?=\n(?:TOOL|DONE|RESULT|THOUGHT):|\Z)", re.MULTILINE | re.DOTALL)


class ToolDefinition:
    """A registered tool available to a subagent."""

    def __init__(self, name: str, func: Callable, description: str, phase: str = "action"):
        self.name = name
        self.func = func
        self.description = description
        self.phase = phase  # "thinking" or "action"


class BaseSubAgent(ABC):
    """
    Abstract base for all subagents dispatched by the kernel.

    Subclasses implement:
    - get_system_prompt(): Returns the system prompt for this subagent
    - setup_tools(): Registers tools via register_tool()

    The base class handles:
    - Tool registration and lookup
    - LLM interaction with text-based tool call protocol
    - Multi-turn execution loop
    - AgentOutput construction
    """

    def __init__(
        self,
        agent_id: str,
        role: str,
        llm_client,
        redis_store=None,
        blob_storage=None,
    ):
        self.agent_id = agent_id
        self.role = role
        self.llm_client = llm_client
        self.redis_store = redis_store
        self.blob_storage = blob_storage
        self._tools: Dict[str, ToolDefinition] = {}
        self._trajectory: List[Dict[str, Any]] = []

        # Let subclass register its tools
        self.setup_tools()

    def register_tool(
        self, name: str, func: Callable, description: str, phase: str = "action"
    ) -> None:
        """Register a tool available to this subagent."""
        self._tools[name] = ToolDefinition(name, func, description, phase)

    @property
    def tool_names(self) -> List[str]:
        """List of registered tool names."""
        return list(self._tools.keys())

    def get_tool_descriptions(self) -> str:
        """Format tool descriptions for prompt injection."""
        lines = ["Available tools:"]
        for tool in self._tools.values():
            lines.append(f"  - {tool.name}: {tool.description} [{tool.phase}]")
        return "\n".join(lines)

    @abstractmethod
    def get_system_prompt(self) -> str:
        """Return the system prompt for this subagent."""
        ...

    @abstractmethod
    def setup_tools(self) -> None:
        """Register tools for this subagent. Called during __init__."""
        ...

    def _build_prompt(self, task: str, context: Optional[Dict] = None) -> str:
        """Build the full prompt for the LLM."""
        parts = [
            self.get_system_prompt(),
            "",
            self.get_tool_descriptions(),
            "",
            "Protocol:",
            "  To use a tool: THOUGHT: <reasoning>\\nTOOL: <name>\\nPARAMS: <json>",
            "  To finish:     THOUGHT: <reasoning>\\nDONE: <summary>\\nRESULT: <json>",
        ]

        if context:
            parts.append("")
            parts.append(f"Context: {json.dumps(context, default=str)}")

        parts.append("")
        parts.append(f"Task: {task}")

        return "\n".join(parts)

    async def run(
        self,
        task: str,
        context: Optional[Dict] = None,
        max_turns: int = 1,
        model: Optional[str] = None,
    ) -> AgentOutput:
        """
        Execute the subagent's task via LLM + tool loop.

        Args:
            task: Natural language task description
            context: Optional context from kernel
            max_turns: Maximum LLM round-trips
            model: Optional model override

        Returns:
            AgentOutput with status, payload, summary, trajectory
        """
        self._trajectory = []
        prompt = self._build_prompt(task, context)
        messages = [{"role": "user", "content": prompt}]
        total_tokens = {"input": 0, "output": 0, "total": 0}
        total_cost = 0.0

        for turn in range(max_turns):
            # Call LLM
            kwargs = {}
            if model:
                kwargs["model"] = model

            try:
                llm_result = await self.llm_client.generate(
                    messages=messages, **kwargs
                )
            except Exception as e:
                logger.error(f"[{self.role}] LLM call failed: {e}")
                return AgentOutput(
                    status="failure",
                    summary=f"LLM call failed: {e}",
                    trajectory=self._trajectory,
                    metadata={"error": str(e), "tokens": total_tokens, "cost_usd": total_cost},
                )

            content = llm_result.get("content", "")
            tokens = llm_result.get("tokens", {})
            total_tokens["input"] += tokens.get("input", 0)
            total_tokens["output"] += tokens.get("output", 0)
            total_tokens["total"] += tokens.get("total", 0)
            total_cost += llm_result.get("cost_usd", 0.0)

            # Parse response
            parsed = self._parse_response(content)

            if parsed["type"] == "done":
                self._trajectory.append({
                    "turn": turn,
                    "type": "done",
                    "thought": parsed.get("thought", ""),
                    "summary": parsed["summary"],
                })
                return AgentOutput(
                    status="success",
                    payload=parsed.get("result"),
                    summary=parsed["summary"],
                    trajectory=self._trajectory,
                    metadata={"tokens": total_tokens, "cost_usd": total_cost},
                )

            if parsed["type"] == "tool":
                tool_name = parsed["tool"]
                tool_params = parsed.get("params", {})

                self._trajectory.append({
                    "turn": turn,
                    "type": "tool_call",
                    "thought": parsed.get("thought", ""),
                    "tool": tool_name,
                    "params": tool_params,
                })

                # Execute tool
                tool_result = await self._execute_tool(tool_name, tool_params)
                self._trajectory[-1]["result"] = tool_result

                # Add tool result to conversation for next turn
                messages.append({"role": "assistant", "content": content})
                messages.append({
                    "role": "user",
                    "content": f"Tool result for {tool_name}:\n{json.dumps(tool_result, default=str)}",
                })
                continue

            # Unparseable response — treat as done with raw content
            self._trajectory.append({
                "turn": turn,
                "type": "raw",
                "content": content[:500],
            })
            return AgentOutput(
                status="success",
                payload=content,
                summary=content[:200],
                trajectory=self._trajectory,
                metadata={"tokens": total_tokens, "cost_usd": total_cost},
            )

        # Max turns reached
        return AgentOutput(
            status="failure",
            summary=f"Max turns ({max_turns}) reached without completion",
            trajectory=self._trajectory,
            metadata={"tokens": total_tokens, "cost_usd": total_cost},
        )

    async def _execute_tool(self, tool_name: str, params: Dict) -> Dict[str, Any]:
        """Execute a registered tool."""
        tool = self._tools.get(tool_name)
        if not tool:
            return {"error": f"Unknown tool: {tool_name}", "available": self.tool_names}

        try:
            result = tool.func(**params)
            # Handle coroutines
            if hasattr(result, "__await__"):
                result = await result
            return {"status": "success", "output": result}
        except Exception as e:
            logger.warning(f"[{self.role}] Tool '{tool_name}' failed: {e}")
            return {"status": "error", "error": str(e)}

    @staticmethod
    def _parse_response(content: str) -> Dict[str, Any]:
        """
        Parse LLM response for tool calls or completion.

        Returns dict with:
            type: "tool" | "done" | "raw"
            + type-specific fields
        """
        thought_match = _THOUGHT_PATTERN.search(content)
        thought = thought_match.group(1).strip() if thought_match else ""

        # Check for DONE first
        done_match = _DONE_PATTERN.search(content)
        if done_match:
            summary = done_match.group(1).strip()
            result = None
            result_match = _RESULT_PATTERN.search(content)
            if result_match:
                try:
                    result = json.loads(result_match.group(1).strip())
                except (json.JSONDecodeError, ValueError):
                    result = result_match.group(1).strip()
            return {"type": "done", "thought": thought, "summary": summary, "result": result}

        # Check for TOOL
        tool_match = _TOOL_PATTERN.search(content)
        if tool_match:
            tool_name = tool_match.group(1).strip()
            params = {}
            params_match = _PARAMS_PATTERN.search(content)
            if params_match:
                params_str = params_match.group(1).strip()
                # Extract just the first JSON object/line
                try:
                    params = json.loads(params_str.split("\n")[0])
                except (json.JSONDecodeError, ValueError):
                    params = {"raw": params_str}
            return {"type": "tool", "thought": thought, "tool": tool_name, "params": params}

        # Unparseable
        return {"type": "raw", "content": content}
