"""
PeerTool - LLM Tool Adapter for Peer-to-Peer Communication

Wraps PeerClient to provide LLM-friendly tool definitions and execution.
Get this via `self.peers.as_tool()` in your agent.

Example:
    class MyAgent:
        def run(self, task):
            # Get the tool adapter
            peer_tool = self.peers.as_tool()

            # Add to your tools list
            tools = [SearchTool(), peer_tool]

            # Get schemas for LLM (includes live peer list)
            schemas = [t.schema for t in tools]
            response = self.llm.chat(task, tools=schemas)

            # Execute tool calls
            for call in response.tool_calls:
                if call.name in peer_tool.tool_names:
                    result = await peer_tool.execute(call.name, call.args)
"""
import asyncio
import logging
from typing import List, Dict, Any, TYPE_CHECKING

if TYPE_CHECKING:
    from .peer_client import PeerClient

logger = logging.getLogger(__name__)


class PeerTool:
    """
    LLM tool adapter for mesh peer communication.

    Provides:
    - schema: Tool definitions with dynamic peer list
    - execute(): Dispatch tool calls to PeerClient
    - tool_names: List of tool names for filtering
    """

    # Tool names this adapter handles
    tool_names = ["ask_peer", "broadcast_update", "list_peers"]

    def __init__(self, peer_client: 'PeerClient'):
        """
        Initialize PeerTool.

        Args:
            peer_client: The PeerClient instance to wrap
        """
        self._peers = peer_client
        self._logger = logging.getLogger(
            f"jarviscore.peer_tool.{peer_client.my_id}"
        )

    @property
    def name(self) -> str:
        """Tool adapter name."""
        return "peer_communication"

    @property
    def schema(self) -> List[Dict[str, Any]]:
        """
        Tool definitions for LLM injection.

        Returns list of tool schemas in Anthropic format.
        Includes DYNAMIC peer information so LLM knows who's available.
        """
        return self.get_tool_definitions()

    def get_tool_definitions(self) -> List[Dict[str, Any]]:
        """
        Get tool definitions with live peer information.

        Returns:
            List of tool schema dicts (Anthropic tool_use format)
        """
        # Get live peer info
        active_roles = self._peers.list_roles()
        peers_info = self._peers.list_peers()

        # Format for LLM context
        if active_roles:
            roles_str = ", ".join(active_roles)
            peers_detail = "; ".join([
                f"{p['role']} (can: {', '.join(p['capabilities'])})"
                for p in peers_info
            ])
        else:
            roles_str = "none online"
            peers_detail = "No peers available"

        return [
            {
                "name": "ask_peer",
                "description": (
                    f"Ask another agent in the mesh for help, data, or analysis. "
                    f"CURRENTLY ONLINE: [{roles_str}]. "
                    f"Details: {peers_detail}. "
                    f"Use when you need capabilities you don't have."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "role": {
                            "type": "string",
                            "description": "The role of the agent to ask",
                            "enum": active_roles if active_roles else ["none"]
                        },
                        "question": {
                            "type": "string",
                            "description": "Your question or request for the peer"
                        }
                    },
                    "required": ["role", "question"]
                }
            },
            {
                "name": "broadcast_update",
                "description": (
                    "Send a notification to ALL peers in the mesh. "
                    "Use for announcing milestones, state changes, or "
                    "important updates everyone should know."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "message": {
                            "type": "string",
                            "description": "The update to broadcast"
                        }
                    },
                    "required": ["message"]
                }
            },
            {
                "name": "list_peers",
                "description": (
                    "Get fresh list of online peers and their capabilities. "
                    "Use to discover who can help with specific tasks."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            }
        ]

    async def execute(self, tool_name: str, args: Dict[str, Any]) -> str:
        """
        Execute a peer tool call.

        Args:
            tool_name: Tool name (ask_peer, broadcast_update, list_peers)
            args: Tool arguments from LLM

        Returns:
            String result to feed back to LLM
        """
        self._logger.debug(f"Executing {tool_name} with args: {args}")

        try:
            if tool_name == "ask_peer":
                return await self._ask_peer(args)
            elif tool_name == "broadcast_update":
                return await self._broadcast_update(args)
            elif tool_name == "list_peers":
                return self._list_peers()
            else:
                return f"Error: Unknown tool '{tool_name}'"
        except Exception as e:
            self._logger.error(f"Tool execution error: {e}")
            return f"Error: {str(e)}"

    async def _ask_peer(self, args: Dict[str, Any]) -> str:
        """Execute ask_peer tool."""
        role = args.get("role")
        question = args.get("question")

        if not role or not question:
            return "Error: 'role' and 'question' are required"

        # Check peer exists
        peer = self._peers.get_peer(role=role)
        if not peer:
            available = self._peers.list_roles()
            return (
                f"Error: '{role}' is not online. "
                f"Available: {', '.join(available) if available else 'none'}"
            )

        # Send request
        response = await self._peers.request(
            role,
            {"query": question, "from": self._peers.my_role},
            timeout=30.0
        )

        if response is None:
            return f"Error: {role} did not respond (timeout)"

        # Format response
        if isinstance(response, dict):
            if "error" in response:
                return f"Error from {role}: {response['error']}"
            elif "response" in response:
                return f"{role}: {response['response']}"
            else:
                return f"{role}: {response}"
        return f"{role}: {response}"

    async def _broadcast_update(self, args: Dict[str, Any]) -> str:
        """Execute broadcast_update tool."""
        message = args.get("message")

        if not message:
            return "Error: 'message' is required"

        count = await self._peers.broadcast({
            "type": "broadcast",
            "message": message,
            "from": self._peers.my_role
        })

        if count == 0:
            return "Broadcast sent (no peers online)"
        return f"Broadcast sent to {count} peer(s)"

    def _list_peers(self) -> str:
        """Execute list_peers tool."""
        peers = self._peers.list_peers()

        if not peers:
            return "No peers currently online"

        lines = ["Online peers:"]
        for p in peers:
            caps = ", ".join(p["capabilities"])
            lines.append(f"  - {p['role']}: {caps}")
        return "\n".join(lines)

    # ─────────────────────────────────────────────────────────────────
    # Sync wrapper
    # ─────────────────────────────────────────────────────────────────

    def execute_sync(self, tool_name: str, args: Dict[str, Any]) -> str:
        """
        Synchronous wrapper for execute().

        Use if your agent loop is not async.
        """
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # Create new loop in thread if needed
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                future = pool.submit(
                    asyncio.run,
                    self.execute(tool_name, args)
                )
                return future.result(timeout=60)
        else:
            return loop.run_until_complete(self.execute(tool_name, args))
