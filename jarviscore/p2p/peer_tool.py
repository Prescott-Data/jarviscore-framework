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
from typing import List, Dict, Any, Optional, TYPE_CHECKING

from jarviscore.orchestration.envelopes import neutral_context

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
    tool_names = ["ask_peer", "ask_capability", "broadcast_update", "list_peers"]

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
        active_capabilities = sorted({
            capability
            for peer in peers_info
            for capability in peer.get("capabilities", [])
        })
        capability_descriptions = {
            capability: description
            for peer in peers_info
            for capability, description in (
                peer.get("capability_descriptions", {}) or {}
            ).items()
            if description
        }
        capability_details = "; ".join(
            f"{capability}: {capability_descriptions[capability]}"
            for capability in active_capabilities
            if capability in capability_descriptions
        )

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
                            "enum": active_roles if active_roles else []
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
                "name": "ask_capability",
                "description": (
                    "Ask any available peer that owns a specific capability to resolve "
                    "a missing fact or perform specialist analysis. The requesting peer "
                    "selects the capability; the recipient controls its own tools and authority. "
                    f"CURRENT CAPABILITIES: [{', '.join(active_capabilities) or 'none online'}]. "
                    f"CAPABILITY MEANINGS: [{capability_details or 'not supplied'}]."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "capability": {
                            "type": "string",
                            "enum": active_capabilities,
                            "description": "Capability needed to resolve the current gap",
                        },
                        "question": {
                            "type": "string",
                            "description": "Exact missing fact or specialist request",
                        },
                    },
                    "required": ["capability", "question"],
                },
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

    async def execute(
        self,
        tool_name: str,
        args: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
        timeout_seconds: Optional[float] = None,
    ) -> str:
        """
        Execute a peer tool call.

        Args:
            tool_name: Tool name (ask_peer, broadcast_update, list_peers)
            args: Tool arguments from LLM

        Returns:
            String result to feed back to LLM
        """
        result = await self.execute_result(
            tool_name,
            args,
            context=context,
            timeout_seconds=timeout_seconds,
        )
        if result.get("status") == "success":
            return str(result.get("output") or "")
        return f"Error: {result.get('error', 'peer request failed')}"

    async def execute_result(
        self,
        tool_name: str,
        args: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
        timeout_seconds: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Execute a peer tool and preserve transport/schema failure semantics."""
        self._logger.debug(f"Executing {tool_name} with args: {args}")

        try:
            if tool_name == "ask_peer":
                return await self._ask_peer_result(
                    args,
                    context=context,
                    timeout_seconds=timeout_seconds,
                )
            elif tool_name == "ask_capability":
                return await self._ask_capability_result(
                    args,
                    context=context,
                    timeout_seconds=timeout_seconds,
                )
            elif tool_name == "broadcast_update":
                return {"status": "success", "output": await self._broadcast_update(args)}
            elif tool_name == "list_peers":
                return {"status": "success", "output": self._list_peers()}
            else:
                return {
                    "status": "error",
                    "error": f"Unknown peer tool '{tool_name}'",
                    "semantic_error": "UNKNOWN_PEER_TOOL",
                    "peer_request_attempted": False,
                }
        except Exception as e:
            self._logger.error(f"Tool execution error: {e}")
            return {
                "status": "error",
                "error": str(e),
                "semantic_error": "PEER_TOOL_EXECUTION_ERROR",
                "peer_request_attempted": True,
            }

    async def _ask_peer_result(
        self,
        args: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
        timeout_seconds: Optional[float] = None,
    ) -> Dict[str, Any]:
        role = str(args.get("role") or "").strip()
        question = str(args.get("question") or "").strip()
        missing = [
            field for field, value in (("role", role), ("question", question))
            if not value
        ]
        if missing:
            return {
                "status": "error",
                "error": f"Missing required peer arguments: {', '.join(missing)}",
                "semantic_error": "INVALID_PEER_TOOL_ARGUMENTS",
                "missing_fields": missing,
                "peer_request_attempted": False,
            }
        response = await self._peers.request(
            role,
            {"query": question, "from": self._peers.my_role},
            timeout=max(1.0, float(timeout_seconds or 300.0)),
            context=neutral_context(context),
        )
        if response is None:
            available_roles = [p["role"] for p in self._peers.list_peers()]
            return {
                "status": "error",
                "error": f"'{role}' not found or did not respond",
                "semantic_error": "PEER_UNAVAILABLE",
                "available_roles": available_roles,
                "peer_request_attempted": True,
            }
        if isinstance(response, dict) and response.get("error"):
            return {
                "status": "error",
                "error": str(response["error"]),
                "semantic_error": "PEER_RESPONSE_ERROR",
                "peer_request_attempted": True,
            }
        payload = response.get("response", response) if isinstance(response, dict) else response
        return {
            "status": "success",
            "output": f"{role}: {payload}",
            "peer_request_attempted": True,
        }

    async def _ask_capability_result(
        self,
        args: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
        timeout_seconds: Optional[float] = None,
    ) -> Dict[str, Any]:
        capability = str(args.get("capability") or "").strip()
        question = str(args.get("question") or "").strip()
        missing = [
            field
            for field, value in (("capability", capability), ("question", question))
            if not value
        ]
        if missing:
            return {
                "status": "error",
                "error": f"Missing required capability arguments: {', '.join(missing)}",
                "semantic_error": "INVALID_PEER_TOOL_ARGUMENTS",
                "missing_fields": missing,
                "peer_request_attempted": False,
            }
        response = await self._peers.request_capability(
            capability,
            question,
            context=context,
            timeout=max(1.0, float(timeout_seconds or 300.0)),
        )
        if response.get("status") != "success":
            return {
                "status": "error",
                "error": str(response.get("error") or "request failed"),
                "semantic_error": "CAPABILITY_REQUEST_FAILED",
                "peer_request_attempted": True,
            }
        peer = response.get("peer_role") or capability
        return {
            "status": "success",
            "output": f"{peer} ({capability}): {response.get('result')}",
            "peer_request_attempted": True,
        }

    async def _ask_peer(
        self,
        args: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Execute ask_peer tool."""
        role = args.get("role")
        question = args.get("question")

        if not role or not question:
            return "Error: 'role' and 'question' are required"

        self._logger.info(f"ask_peer: Attempting to contact role='{role}'")
        
        # Send request (request() will handle resolution of local/remote peers)
        # Use 2 hour timeout to allow analyst time for complex queries and analysis
        response = await self._peers.request(
            role,
            {"query": question, "from": self._peers.my_role},
            timeout=7200.0,
            context=neutral_context(context),
        )
        
        self._logger.info(f"ask_peer: Got response: {response}")
        
        # If request() returns None, peer wasn't found or didn't respond
        if response is None:
            peers = self._peers.list_peers()
            available_roles = [p['role'] for p in peers]
            self._logger.warning(f"ask_peer: request() returned None. Available peers: {available_roles}")
            return (
                f"Error: '{role}' not found or did not respond. "
                f"Available: {', '.join(available_roles) if available_roles else 'none'}"
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

    async def _ask_capability(
        self,
        args: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
    ) -> str:
        capability = str(args.get("capability") or "").strip()
        question = str(args.get("question") or "").strip()
        if not capability or not question:
            return "Error: 'capability' and 'question' are required"
        response = await self._peers.request_capability(
            capability,
            question,
            context=context,
            timeout=float(args.get("timeout") or 7200.0),
        )
        if response.get("status") != "success":
            return f"Error from {capability}: {response.get('error', 'request failed')}"
        peer = response.get("peer_role") or capability
        return f"{peer} ({capability}): {response.get('result')}"

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
