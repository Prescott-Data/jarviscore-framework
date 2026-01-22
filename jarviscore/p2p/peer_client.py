"""
PeerClient - Direct peer-to-peer communication for agents.

Provides a simple API for agents to discover and communicate
with other agents in the mesh without going through workflow orchestration.

Example:
    class MyAgent(JarvisAgent):
        async def run(self):
            # Discovery
            analyst = self.peers.get_peer(role="analyst")

            # Notify (fire-and-forget)
            await self.peers.notify("analyst", {"event": "done", "data": result})

            # Request-response
            response = await self.peers.request("scout", {"need": "clarification"}, timeout=30)

            # Receive incoming messages
            message = await self.peers.receive(timeout=5)
"""
import asyncio
import logging
from typing import List, Dict, Any, Optional, TYPE_CHECKING
from uuid import uuid4

from .messages import PeerInfo, IncomingMessage, OutgoingMessage, MessageType

if TYPE_CHECKING:
    from .coordinator import P2PCoordinator

logger = logging.getLogger(__name__)


class PeerClient:
    """
    Client for peer-to-peer agent communication.

    Injected into agents during mesh startup, provides direct access
    to peer discovery and messaging without workflow orchestration.
    """

    def __init__(
        self,
        coordinator: 'P2PCoordinator',
        agent_id: str,
        agent_role: str,
        agent_registry: Dict[str, List],
        node_id: str = ""
    ):
        """
        Initialize PeerClient.

        Args:
            coordinator: P2P coordinator for message routing
            agent_id: This agent's unique ID
            agent_role: This agent's role
            agent_registry: Registry mapping roles to agent lists
            node_id: This node's P2P identifier (host:port)
        """
        self._coordinator = coordinator
        self._agent_id = agent_id
        self._agent_role = agent_role
        self._agent_registry = agent_registry
        self._node_id = node_id

        # Message queue for incoming messages
        self._message_queue: asyncio.Queue[IncomingMessage] = asyncio.Queue()

        # Pending requests waiting for responses (correlation_id -> Future)
        self._pending_requests: Dict[str, asyncio.Future] = {}

        self._logger = logging.getLogger(f"jarviscore.peer_client.{agent_id}")

    # ─────────────────────────────────────────────────────────────────
    # DISCOVERY
    # ─────────────────────────────────────────────────────────────────

    def get_peer(self, role: str) -> Optional[PeerInfo]:
        """
        Get information about a peer by role.

        Args:
            role: The role to look for (e.g., "analyst", "scout")

        Returns:
            PeerInfo if found, None otherwise

        Example:
            analyst = self.peers.get_peer(role="analyst")
            if analyst:
                print(f"Found analyst: {analyst.agent_id}")
        """
        agents = self._agent_registry.get(role, [])
        if not agents:
            self._logger.debug(f"No peer found with role: {role}")
            return None

        # Return first agent with this role
        agent = agents[0]
        return PeerInfo(
            agent_id=agent.agent_id,
            role=agent.role,
            capabilities=list(agent.capabilities),
            node_id=self._node_id,
            status="alive"
        )

    def discover(
        self,
        capability: str = None,
        role: str = None
    ) -> List[PeerInfo]:
        """
        Discover peers by capability or role.

        Args:
            capability: Filter by capability (e.g., "analysis")
            role: Filter by role (e.g., "analyst")

        Returns:
            List of matching PeerInfo objects

        Example:
            analysts = self.peers.discover(capability="analysis")
            for peer in analysts:
                print(f"Found: {peer.role} - {peer.capabilities}")
        """
        results = []

        if role:
            agents = self._agent_registry.get(role, [])
            for agent in agents:
                if agent.agent_id != self._agent_id:  # Exclude self
                    results.append(PeerInfo(
                        agent_id=agent.agent_id,
                        role=agent.role,
                        capabilities=list(agent.capabilities),
                        node_id=self._node_id,
                        status="alive"
                    ))

        elif capability:
            # Search all agents for capability
            for role_name, agents in self._agent_registry.items():
                for agent in agents:
                    if agent.agent_id != self._agent_id:  # Exclude self
                        if capability in agent.capabilities:
                            results.append(PeerInfo(
                                agent_id=agent.agent_id,
                                role=agent.role,
                                capabilities=list(agent.capabilities),
                                node_id=self._node_id,
                                status="alive"
                            ))

        else:
            # Return all peers
            for role_name, agents in self._agent_registry.items():
                for agent in agents:
                    if agent.agent_id != self._agent_id:  # Exclude self
                        results.append(PeerInfo(
                            agent_id=agent.agent_id,
                            role=agent.role,
                            capabilities=list(agent.capabilities),
                            node_id=self._node_id,
                            status="alive"
                        ))

        return results

    @property
    def registry(self) -> Dict[str, PeerInfo]:
        """
        Read-only access to the full agent registry.

        Returns:
            Dictionary mapping agent_id to PeerInfo

        Example:
            for agent_id, info in self.peers.registry.items():
                print(f"{agent_id}: {info.role}")
        """
        result = {}
        for role_name, agents in self._agent_registry.items():
            for agent in agents:
                if agent.agent_id != self._agent_id:  # Exclude self
                    result[agent.agent_id] = PeerInfo(
                        agent_id=agent.agent_id,
                        role=agent.role,
                        capabilities=list(agent.capabilities),
                        node_id=self._node_id,
                        status="alive"
                    )
        return result

    # ─────────────────────────────────────────────────────────────────
    # IDENTITY
    # ─────────────────────────────────────────────────────────────────

    @property
    def my_role(self) -> str:
        """This agent's role."""
        return self._agent_role

    @property
    def my_id(self) -> str:
        """This agent's unique ID."""
        return self._agent_id

    # ─────────────────────────────────────────────────────────────────
    # DISCOVERY (simplified for tool use)
    # ─────────────────────────────────────────────────────────────────

    def list_roles(self) -> List[str]:
        """
        Get list of available peer roles (excluding self).

        Returns:
            List of role strings like ["scout", "analyst"]

        Example:
            roles = self.peers.list_roles()
            # ["scout", "analyst", "reporter"]
        """
        roles = set()
        for role_name, agents in self._agent_registry.items():
            for agent in agents:
                if agent.agent_id != self._agent_id:
                    roles.add(role_name)
        return sorted(list(roles))

    def list_peers(self) -> List[Dict[str, Any]]:
        """
        Get detailed list of peers with capabilities.

        Returns:
            List of dicts with role, agent_id, capabilities, status

        Example:
            peers = self.peers.list_peers()
            # [{"role": "scout", "capabilities": ["reasoning"], ...}]
        """
        seen = set()
        peers = []
        for role_name, agents in self._agent_registry.items():
            for agent in agents:
                if agent.agent_id != self._agent_id and agent.agent_id not in seen:
                    seen.add(agent.agent_id)
                    peers.append({
                        "role": agent.role,
                        "agent_id": agent.agent_id,
                        "capabilities": list(agent.capabilities),
                        "status": "online"
                    })
        return peers

    # ─────────────────────────────────────────────────────────────────
    # MESSAGING - SEND
    # ─────────────────────────────────────────────────────────────────

    async def notify(self, target: str, message: Dict[str, Any]) -> bool:
        """
        Send a fire-and-forget notification to a peer.

        Args:
            target: Target agent role (e.g., "analyst") or agent_id
            message: Message payload (any JSON-serializable dict)

        Returns:
            True if message was sent successfully

        Example:
            await self.peers.notify("analyst", {
                "event": "scouting_complete",
                "data": {"findings": 42}
            })
        """
        target_agent = self._resolve_target(target)
        if not target_agent:
            self._logger.warning(f"Cannot notify: no peer found for '{target}'")
            return False

        outgoing = OutgoingMessage(
            target=target,
            type=MessageType.NOTIFY,
            data=message,
            sender=self._agent_id,
            sender_node=self._node_id
        )

        return await self._send_message(target_agent, outgoing)

    async def request(
        self,
        target: str,
        message: Dict[str, Any],
        timeout: float = 30.0
    ) -> Optional[Dict[str, Any]]:
        """
        Send a request and wait for a response.

        Args:
            target: Target agent role (e.g., "scout") or agent_id
            message: Request payload
            timeout: Max seconds to wait for response (default: 30)

        Returns:
            Response data dict, or None if timeout/failure

        Example:
            response = await self.peers.request("scout", {
                "need": "clarification",
                "entity": "Entity_X"
            }, timeout=10)

            if response:
                print(f"Got clarification: {response}")
        """
        target_agent = self._resolve_target(target)
        if not target_agent:
            self._logger.warning(f"Cannot request: no peer found for '{target}'")
            return None

        # Generate correlation ID for request-response matching
        correlation_id = f"req-{uuid4().hex[:12]}"

        outgoing = OutgoingMessage(
            target=target,
            type=MessageType.REQUEST,
            data=message,
            correlation_id=correlation_id,
            sender=self._agent_id,
            sender_node=self._node_id
        )

        # Create future to wait for response
        response_future: asyncio.Future = asyncio.get_event_loop().create_future()
        self._pending_requests[correlation_id] = response_future

        try:
            # Send request
            sent = await self._send_message(target_agent, outgoing)
            if not sent:
                return None

            # Wait for response with timeout
            response = await asyncio.wait_for(response_future, timeout=timeout)
            return response

        except asyncio.TimeoutError:
            self._logger.debug(f"Request to '{target}' timed out after {timeout}s")
            return None

        finally:
            # Cleanup pending request
            self._pending_requests.pop(correlation_id, None)

    async def respond(self, message: IncomingMessage, response: Dict[str, Any]) -> bool:
        """
        Respond to an incoming request.

        Args:
            message: The incoming request message
            response: Response data to send back

        Returns:
            True if response was sent successfully

        Example:
            message = await self.peers.receive()
            if message and message.is_request:
                await self.peers.respond(message, {"result": "done"})
        """
        if not message.correlation_id:
            self._logger.warning("Cannot respond: message has no correlation_id")
            return False

        # Find target agent
        target_agent = self._resolve_target(message.sender)
        if not target_agent:
            self._logger.warning(f"Cannot respond: sender '{message.sender}' not found")
            return False

        outgoing = OutgoingMessage(
            target=message.sender,
            type=MessageType.RESPONSE,
            data=response,
            correlation_id=message.correlation_id,
            sender=self._agent_id,
            sender_node=self._node_id
        )

        return await self._send_message(target_agent, outgoing)

    async def broadcast(self, message: Dict[str, Any]) -> int:
        """
        Broadcast notification to ALL peers.

        Args:
            message: Message payload to broadcast

        Returns:
            Number of peers successfully notified

        Example:
            count = await self.peers.broadcast({
                "event": "status_update",
                "status": "completed"
            })
            print(f"Notified {count} peers")
        """
        count = 0
        for peer in self.discover():
            if await self.notify(peer.role, message):
                count += 1
        return count

    # ─────────────────────────────────────────────────────────────────
    # TOOL ADAPTER
    # ─────────────────────────────────────────────────────────────────

    def as_tool(self) -> 'PeerTool':
        """
        Get LLM tool adapter for this PeerClient.

        Returns a PeerTool that wraps this client, providing:
        - Tool definitions for LLM injection
        - Tool execution dispatch

        Returns:
            PeerTool instance

        Example:
            # In your agent
            tools = [SearchTool(), self.peers.as_tool()]
            response = llm.chat(task, tools=[t.schema for t in tools])
        """
        from .peer_tool import PeerTool
        return PeerTool(self)

    # ─────────────────────────────────────────────────────────────────
    # MESSAGING - RECEIVE
    # ─────────────────────────────────────────────────────────────────

    async def receive(self, timeout: float = None) -> Optional[IncomingMessage]:
        """
        Receive the next incoming message.

        Args:
            timeout: Max seconds to wait (None = wait forever)

        Returns:
            IncomingMessage if received, None if timeout

        Example:
            # Wait up to 5 seconds for a message
            message = await self.peers.receive(timeout=5)
            if message:
                print(f"Got message from {message.sender}: {message.data}")
        """
        try:
            if timeout is not None:
                message = await asyncio.wait_for(
                    self._message_queue.get(),
                    timeout=timeout
                )
            else:
                message = await self._message_queue.get()

            return message

        except asyncio.TimeoutError:
            return None

    def has_pending_messages(self) -> bool:
        """Check if there are messages waiting to be received."""
        return not self._message_queue.empty()

    # ─────────────────────────────────────────────────────────────────
    # INTERNAL METHODS
    # ─────────────────────────────────────────────────────────────────

    def _resolve_target(self, target: str):
        """
        Resolve target string to agent.

        Args:
            target: Role name or agent_id

        Returns:
            Agent instance or None
        """
        # First try as role
        agents = self._agent_registry.get(target, [])
        if agents:
            return agents[0]

        # Try as agent_id
        for role_name, agents in self._agent_registry.items():
            for agent in agents:
                if agent.agent_id == target:
                    return agent

        return None

    async def _send_message(self, target_agent, message: OutgoingMessage) -> bool:
        """
        Send message to target agent via coordinator.

        For local agents (same mesh), delivers directly to their queue.
        For remote agents, sends via P2P coordinator.
        """
        try:
            # Check if target has a peer client (local agent)
            if hasattr(target_agent, 'peers') and target_agent.peers:
                # Direct local delivery
                incoming = IncomingMessage(
                    sender=message.sender,
                    sender_node=message.sender_node,
                    type=message.type,
                    data=message.data,
                    correlation_id=message.correlation_id,
                    timestamp=message.timestamp
                )
                await target_agent.peers._deliver_message(incoming)
                self._logger.debug(
                    f"Delivered {message.type.value} to local agent {target_agent.agent_id}"
                )
                return True

            # Remote delivery via P2P coordinator
            if self._coordinator:
                msg_type = f"PEER_{message.type.value.upper()}"
                payload = {
                    'sender': message.sender,
                    'sender_node': message.sender_node,
                    'target': message.target,
                    'data': message.data,
                    'correlation_id': message.correlation_id,
                    'timestamp': message.timestamp
                }
                return await self._coordinator._send_p2p_message(
                    target_agent.node_id or self._node_id,
                    msg_type,
                    payload
                )

            self._logger.warning("No delivery mechanism available")
            return False

        except Exception as e:
            self._logger.error(f"Failed to send message: {e}")
            return False

    async def _deliver_message(self, message: IncomingMessage):
        """
        Deliver an incoming message to this client.

        Called by other PeerClients (local) or coordinator (remote).
        """
        # Check if this is a response to a pending request
        if message.type == MessageType.RESPONSE and message.correlation_id:
            future = self._pending_requests.get(message.correlation_id)
            if future and not future.done():
                future.set_result(message.data)
                self._logger.debug(
                    f"Delivered response for {message.correlation_id}"
                )
                return

        # Otherwise queue for receive()
        await self._message_queue.put(message)
        self._logger.debug(
            f"Queued {message.type.value} from {message.sender}"
        )
