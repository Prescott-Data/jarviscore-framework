"""
P2P Coordinator for JarvisCore Framework

Unified P2P coordination layer wrapping swim_p2p library.
Provides agent discovery, capability announcement, and message routing.

Adapted from integration-agent P2P infrastructure
"""
import asyncio
import logging
from typing import List, Dict, Any, Optional

from .swim_manager import SWIMThreadManager
from .keepalive import P2PKeepaliveManager
from .broadcaster import StepOutputBroadcaster
from .messages import IncomingMessage, MessageType

logger = logging.getLogger(__name__)


class P2PCoordinator:
    """
    Simplified P2P coordination layer wrapping swim_p2p library.

    Provides:
    - SWIM protocol membership management
    - Agent discovery and capability announcement
    - Message routing and broadcasting
    - Smart keepalive with traffic suppression
    - Step output broadcasting

    Example:
        coordinator = P2PCoordinator(agents, config)
        await coordinator.start()
        await coordinator.announce_capabilities()
    """

    def __init__(self, agents: List, config: Dict):
        """
        Initialize P2P Coordinator.

        Args:
            agents: List of Agent instances to coordinate
            config: Configuration dictionary containing:
                - bind_host: Host to bind SWIM (default: 127.0.0.1)
                - bind_port: Port to bind SWIM (default: 7946)
                - node_name: Node identifier (default: jarviscore-node)
                - seed_nodes: Comma-separated seed nodes (default: "")
                - transport_type: udp, tcp, or hybrid (default: hybrid)
                - zmq_port_offset: Offset for ZMQ port (default: 1000)
                - keepalive_enabled: Enable keepalive (default: True)
                - keepalive_interval: Keepalive interval in seconds (default: 90)
        """
        self.agents = agents
        self.config = config

        # Core components (from integration-agent)
        self.swim_manager: Optional[SWIMThreadManager] = None
        self.keepalive_manager: Optional[P2PKeepaliveManager] = None
        self.broadcaster: Optional[StepOutputBroadcaster] = None

        # State
        self._started = False
        self._capability_map: Dict[str, List[str]] = {}  # capability -> [agent_ids]
        self._agent_peer_clients: Dict[str, Any] = {}  # agent_id -> PeerClient
        self._remote_agent_registry: Dict[str, Dict[str, Any]] = {}  # agent_id -> agent info

    async def start(self):
        """
        Start P2P mesh.

        Steps:
        1. Start SWIM protocol in dedicated thread
        2. Setup keepalive manager
        3. Setup step output broadcaster
        4. Register message handlers
        """
        if self._started:
            logger.warning("P2P Coordinator already started")
            return

        logger.info("Starting P2P coordinator...")

        # 1. Start SWIM protocol (in dedicated thread)
        logger.info("Initializing SWIM protocol...")
        self.swim_manager = SWIMThreadManager(self.config)
        self.swim_manager.start_swim_in_thread_simple()

        if not self.swim_manager.wait_for_init(timeout=20):
            raise RuntimeError("SWIM initialization failed")
        logger.info("✓ SWIM protocol started")

        # 2. Setup keepalive manager
        logger.info("Starting P2P keepalive...")
        # Map jarviscore config keys to P2P_KEEPALIVE_* keys
        keepalive_config = {
            'P2P_KEEPALIVE_ENABLED': self.config.get('keepalive_enabled', True),
            'P2P_KEEPALIVE_INTERVAL': self.config.get('keepalive_interval', 90),
            'P2P_KEEPALIVE_TIMEOUT': self.config.get('keepalive_timeout', 10),
            'P2P_ACTIVITY_SUPPRESS_WINDOW': self.config.get('activity_suppress_window', 60),
        }
        self.keepalive_manager = P2PKeepaliveManager(
            agent_id=self._get_node_id(),
            send_p2p_callback=self._send_p2p_message,
            broadcast_p2p_callback=self._broadcast_p2p_message,
            config=keepalive_config
        )
        await self.keepalive_manager.start()
        logger.info("✓ Keepalive manager started")

        # 3. Setup broadcaster
        logger.info("Starting step output broadcaster...")
        self.broadcaster = StepOutputBroadcaster(
            agent_id=self._get_node_id(),
            zmq_agent=self.swim_manager.zmq_agent,
            swim_node=self.swim_manager.swim_node
        )
        logger.info("✓ Broadcaster started")

        # 4. Register message handlers
        self._register_handlers()
        logger.info("✓ Message handlers registered")

        self._started = True
        logger.info("P2P coordinator started successfully")

    def _register_handlers(self):
        """Register framework message handlers with ZMQ router."""
        if not self.swim_manager or not self.swim_manager.zmq_agent:
            logger.error("Cannot register handlers: ZMQ agent not available")
            return

        zmq = self.swim_manager.zmq_agent

        # Register message type handlers
        message_types = {
            "STEP_OUTPUT_BROADCAST": self._handle_step_broadcast,
            "STEP_OUTPUT_ACK": self._handle_step_ack,
            "STEP_COMPLETION_NUDGE": self._handle_nudge,
            "STEP_COMPLETION_NUDGE_RESPONSE": self._handle_nudge_response,
            "STEP_DATA_REQUEST": self._handle_data_request,
            "CAPABILITY_ANNOUNCEMENT": self._handle_capability_announcement,
            "CAPABILITY_DEANNOUNCEMENT": self._handle_capability_deannouncement,
            "CAPABILITY_QUERY": self._handle_capability_query,
            "CAPABILITY_REQUEST": self._handle_capability_request,
            "P2P_KEEPALIVE": self.keepalive_manager.handle_keepalive_received,
            "P2P_KEEPALIVE_ACK": self.keepalive_manager.handle_keepalive_ack,
            # Peer-to-peer messaging (PeerClient)
            "PEER_NOTIFY": self._handle_peer_notify,
            "PEER_REQUEST": self._handle_peer_request,
            "PEER_RESPONSE": self._handle_peer_response,
        }

        for msg_type, handler in message_types.items():
            try:
                zmq.router_manager.register_handler(msg_type, handler)
                logger.debug(f"Registered handler for {msg_type}")
            except Exception as e:
                logger.error(f"Failed to register handler for {msg_type}: {e}")

        logger.info(f"Registered {len(message_types)} message handlers")

    async def _wait_for_zmq_connections(self, timeout: float = 10.0) -> bool:
        """
        Wait for ZMQ connections to alive SWIM members to be established.

        This ensures we don't try to send messages before ZMQ is ready.
        The ZMQ connection establishment happens asynchronously after
        SWIM membership changes are detected.

        Args:
            timeout: Maximum time to wait in seconds

        Returns:
            True if connections are ready, False if timeout
        """
        import asyncio
        import time

        if not self.swim_manager or not self.swim_manager.zmq_agent:
            logger.warning("No ZMQ agent available")
            return False

        swim_node = self.swim_manager.swim_node
        if not swim_node:
            logger.warning("No SWIM node available")
            return False

        conn_mgr = self.swim_manager.zmq_agent.connection_manager
        start_time = time.time()

        while time.time() - start_time < timeout:
            # Get alive members (excluding self)
            alive_members = list(swim_node.members.get_alive_members(exclude_self=True))

            if not alive_members:
                # No peers to connect to - that's fine
                logger.debug("No alive peers to wait for")
                return True

            # Check if all have ZMQ connections ready
            all_ready = True
            for member in alive_members:
                swim_addr = str(member.address)
                zmq_addr = conn_mgr.get_zmq_address_for_swim(swim_addr)

                if zmq_addr and conn_mgr.can_send_to_node(zmq_addr):
                    logger.debug(f"ZMQ connection to {swim_addr} is ready")
                else:
                    logger.debug(f"ZMQ connection to {swim_addr} not ready yet")
                    all_ready = False
                    break

            if all_ready:
                logger.info(f"All ZMQ connections ready ({len(alive_members)} peers)")
                return True

            # Wait a bit before checking again
            await asyncio.sleep(0.2)

        logger.warning(f"Timeout waiting for ZMQ connections after {timeout}s")
        return False

    async def announce_capabilities(self):
        """Broadcast agent capabilities to mesh."""
        if not self._started:
            raise RuntimeError("P2P Coordinator not started")

        # Wait for ZMQ connections to be ready before announcing
        await self._wait_for_zmq_connections(timeout=5.0)

        capabilities = {}
        agents_info = {}  # Full agent info for remote registry

        for agent in self.agents:
            for cap in agent.capabilities:
                if cap not in capabilities:
                    capabilities[cap] = []
                capabilities[cap].append(agent.agent_id)

            # Collect full agent info for remote visibility
            agents_info[agent.agent_id] = {
                'agent_id': agent.agent_id,
                'role': agent.role,
                'capabilities': list(agent.capabilities),
                'description': getattr(agent, 'description', ''),
                'node_id': self._get_node_id()
            }

        # Merge local capabilities into the map (preserve remote agents)
        for cap, agent_ids in capabilities.items():
            if cap not in self._capability_map:
                self._capability_map[cap] = []
            for agent_id in agent_ids:
                if agent_id not in self._capability_map[cap]:
                    self._capability_map[cap].append(agent_id)

        payload = {
            'node_id': self._get_node_id(),
            'capabilities': capabilities,
            'agents': agents_info  # Include for remote agent registry
        }

        # Broadcast directly using CAPABILITY_ANNOUNCEMENT message type
        # This ensures the handler updates the capability map
        # Note: _send_p2p_message wraps in 'payload' key, so send payload directly
        success_count = await self._broadcast_p2p_message(
            'CAPABILITY_ANNOUNCEMENT',
            payload
        )

        logger.info(f"Announced capabilities to {success_count} peers: {list(capabilities.keys())}")

    async def request_peer_capabilities(self):
        """
        Request capabilities from all existing peers.

        Called when joining an existing mesh to discover what agents/capabilities
        already exist. This ensures late-joiners see existing agents.
        """
        if not self._started or not self.swim_manager:
            logger.warning("Cannot request capabilities - coordinator not started")
            return

        # Wait for ZMQ connections to be ready before requesting
        await self._wait_for_zmq_connections(timeout=5.0)

        # Get alive peers from SWIM
        swim_node = self.swim_manager.swim_node
        if not swim_node:
            logger.warning("SWIM node not available")
            return

        try:
            alive_members = list(swim_node.members.get_alive_members(exclude_self=True))
            logger.info(f"Requesting capabilities from {len(alive_members)} peers")

            for member in alive_members:
                # member.address is already a string like "127.0.0.1:9905"
                peer_addr = str(member.address)
                try:
                    # Send capability request - peers should respond with their capabilities
                    await self._send_p2p_message(
                        peer_addr,
                        'CAPABILITY_REQUEST',
                        {'node_id': self._get_node_id()}
                    )
                    logger.debug(f"Sent capability request to {peer_addr}")
                except Exception as e:
                    logger.debug(f"Failed to request capabilities from {peer_addr}: {e}")

        except Exception as e:
            logger.error(f"Error requesting peer capabilities: {e}")

    async def _handle_capability_request(self, sender, message):
        """Handle capability request from a new joiner - respond with our capabilities."""
        try:
            # Get the SWIM ID of the sender from the message (not the ZMQ identity)
            sender_swim_id = message.get('from_node')
            if not sender_swim_id:
                logger.warning(f"Capability request missing from_node, cannot respond")
                return

            # Re-announce our capabilities to this specific peer
            capabilities = {}
            agents_info = {}

            for agent in self.agents:
                for cap in agent.capabilities:
                    if cap not in capabilities:
                        capabilities[cap] = []
                    capabilities[cap].append(agent.agent_id)

                agents_info[agent.agent_id] = {
                    'agent_id': agent.agent_id,
                    'role': agent.role,
                    'capabilities': list(agent.capabilities),
                    'description': getattr(agent, 'description', ''),
                    'node_id': self._get_node_id()
                }

            response = {
                'node_id': self._get_node_id(),
                'capabilities': capabilities,
                'agents': agents_info
            }

            # Send to the SWIM address (from_node), not the ZMQ identity (sender)
            await self._send_p2p_message(sender_swim_id, 'CAPABILITY_ANNOUNCEMENT', response)
            logger.info(f"Sent capabilities to requesting peer {sender_swim_id}")

        except Exception as e:
            logger.error(f"Error handling capability request: {e}")

    async def deannounce_capabilities(self):
        """
        Broadcast capability removal to mesh.

        Called when agent leaves mesh gracefully to notify other nodes
        that this agent's capabilities are no longer available.
        """
        import time

        if not self._started or not self.swim_manager:
            return

        node_id = self._get_node_id()

        capabilities = []
        agent_ids = []
        for agent in self.agents:
            capabilities.extend(agent.capabilities)
            agent_ids.append(agent.agent_id)

        payload = {
            'type': 'CAPABILITY_DEANNOUNCEMENT',
            'node_id': node_id,
            'capabilities': list(set(capabilities)),
            'agent_ids': agent_ids,
            'timestamp': time.time()
        }

        await self._broadcast_p2p_message("CAPABILITY_DEANNOUNCEMENT", payload)
        logger.info(f"Deannounced capabilities: {capabilities}")

    async def query_mesh(self, capability: str) -> List[str]:
        """
        Find agents with specific capability across mesh.

        Args:
            capability: Required capability

        Returns:
            List of agent IDs that have the capability
        """
        # First check local cache
        if capability in self._capability_map:
            return self._capability_map[capability]

        # TODO Day 3: Implement distributed capability query via P2P
        logger.debug(f"No cached agents found for capability: {capability}")
        return []

    async def serve(self):
        """
        Run as service, handling P2P requests indefinitely.

        This keeps the coordinator running and responding to P2P messages.
        """
        logger.info("P2P service running (press Ctrl+C to stop)...")

        try:
            while True:
                await asyncio.sleep(10)
                # Service is event-driven via message handlers
                # Just keep the event loop alive
        except KeyboardInterrupt:
            logger.info("Service interrupted")

    async def stop(self):
        """Stop P2P coordinator and cleanup resources."""
        if not self._started:
            return

        logger.info("Stopping P2P coordinator...")

        # Stop keepalive manager
        if self.keepalive_manager:
            await self.keepalive_manager.stop()
            logger.info("✓ Keepalive manager stopped")

        # Stop SWIM manager
        if self.swim_manager:
            self.swim_manager.shutdown()
            logger.info("✓ SWIM manager stopped")

        self._started = False
        logger.info("P2P coordinator stopped")

    # Internal helpers

    def _get_node_id(self) -> str:
        """Get node identifier from SWIM."""
        if self.swim_manager and self.swim_manager.bind_addr:
            addr = self.swim_manager.bind_addr
            return f"{addr[0]}:{addr[1]}"
        return "unknown"

    async def _send_p2p_message(self, target: str, msg_type: str, payload: Dict) -> bool:
        """
        Send message to specific peer.

        Args:
            target: Target node ID (host:port)
            msg_type: Message type
            payload: Message payload

        Returns:
            True if sent successfully
        """
        try:
            if not self.swim_manager or not self.swim_manager.zmq_agent:
                logger.error("Cannot send P2P message: ZMQ agent not available")
                return False

            import json
            payload_json = json.dumps(payload)
            success = await self.swim_manager.zmq_agent.send_message_base(
                target,
                msg_type,
                "payload",
                payload_json,
                f"p2p_{msg_type}"
            )

            # Record activity for keepalive suppression
            if self.keepalive_manager:
                self.keepalive_manager.record_p2p_activity()

            return success
        except Exception as e:
            logger.error(f"Failed to send P2P message to {target}: {e}")
            return False

    async def _broadcast_p2p_message(self, msg_type: str, payload: Dict) -> int:
        """
        Broadcast message to all alive members.

        Args:
            msg_type: Message type
            payload: Message payload

        Returns:
            Number of successful sends
        """
        if not self.swim_manager or not self.swim_manager.swim_node:
            logger.error("Cannot broadcast: SWIM node not available")
            return 0

        count = 0
        try:
            alive_members = self.swim_manager.swim_node.members.get_alive_members(exclude_self=True)

            for member in alive_members:
                target = f"{member.addr[0]}:{member.addr[1]}"
                if await self._send_p2p_message(target, msg_type, payload):
                    count += 1

            logger.debug(f"Broadcasted {msg_type} to {count} peers")
        except Exception as e:
            logger.error(f"Error broadcasting message: {e}")

        return count

    # Message handlers (stubs for Day 3 implementation)

    async def _handle_step_broadcast(self, sender, message):
        """Handle step output broadcast."""
        logger.debug(f"Received step broadcast from {sender}")
        if self.broadcaster:
            await self.broadcaster.handle_step_output_broadcast(sender, message)

    async def _handle_step_ack(self, sender, message):
        """Handle step output acknowledgment."""
        logger.debug(f"Received step ACK from {sender}")
        if self.broadcaster:
            await self.broadcaster.handle_step_output_ack(sender, message)

    async def _handle_nudge(self, sender, message):
        """Handle step completion nudge."""
        logger.debug(f"Received nudge from {sender}")
        # TODO Day 3: Forward to nudging system

    async def _handle_nudge_response(self, sender, message):
        """Handle nudge response."""
        logger.debug(f"Received nudge response from {sender}")
        # TODO Day 3: Forward to nudging system

    async def _handle_data_request(self, sender, message):
        """Handle step data request."""
        logger.debug(f"Received data request from {sender}")
        # TODO Day 3: Forward to dependency manager

    async def _handle_capability_announcement(self, sender, message):
        """Handle capability announcement from peer."""
        import time
        import json

        try:
            payload = message.get('payload', {})
            # Handle both JSON string and dict payload
            if isinstance(payload, str):
                payload = json.loads(payload)

            caps = payload.get('capabilities', {})
            node_id = payload.get('node_id')
            agents_info = payload.get('agents', {})

            # Update local capability map
            for cap, agents in caps.items():
                if cap not in self._capability_map:
                    self._capability_map[cap] = []
                # Add remote agents (avoid duplicates)
                for agent_id in agents:
                    if agent_id not in self._capability_map[cap]:
                        self._capability_map[cap].append(agent_id)

            # Update remote agent registry for visibility
            for agent_id, info in agents_info.items():
                self._remote_agent_registry[agent_id] = {
                    **info,
                    'node_id': node_id,
                    'last_seen': time.time()
                }

            logger.info(
                f"Updated from {node_id}: caps={list(caps.keys())}, "
                f"agents={list(agents_info.keys())}"
            )
        except Exception as e:
            logger.error(f"Error handling capability announcement: {e}")

    async def _handle_capability_deannouncement(self, sender, message):
        """Handle capability deannouncement from departing node."""
        import json
        try:
            payload = message.get('payload', {})
            if isinstance(payload, str):
                payload = json.loads(payload)
            node_id = payload.get('node_id')
            agent_ids = payload.get('agent_ids', [])

            # Remove from capability map
            for cap in list(self._capability_map.keys()):
                self._capability_map[cap] = [
                    a for a in self._capability_map[cap]
                    if a not in agent_ids
                ]
                # Clean up empty capabilities
                if not self._capability_map[cap]:
                    del self._capability_map[cap]

            # Remove from remote agent registry
            for agent_id in agent_ids:
                self._remote_agent_registry.pop(agent_id, None)

            logger.info(f"Node {node_id} departed, removed agents: {agent_ids}")
        except Exception as e:
            logger.error(f"Error handling capability deannouncement: {e}")

    async def _handle_capability_query(self, sender, message):
        """Handle capability query from peer."""
        try:
            # Get the SWIM ID from the message (not the ZMQ identity)
            sender_swim_id = message.get('from_node')
            if not sender_swim_id:
                logger.warning("Capability query missing from_node, cannot respond")
                return

            capability = message.get('capability')
            response = {
                'capability': capability,
                'agents': self._capability_map.get(capability, [])
            }
            await self._send_p2p_message(sender_swim_id, 'CAPABILITY_QUERY_RESPONSE', response)
            logger.debug(f"Responded to capability query from {sender_swim_id} for {capability}")
        except Exception as e:
            logger.error(f"Error handling capability query: {e}")

    # ─────────────────────────────────────────────────────────────────
    # Peer-to-peer messaging handlers (PeerClient support)
    # ─────────────────────────────────────────────────────────────────

    def register_peer_client(self, agent_id: str, peer_client):
        """
        Register a PeerClient for an agent.

        Called by Mesh when injecting PeerClients into agents.
        """
        self._agent_peer_clients[agent_id] = peer_client
        logger.debug(f"Registered PeerClient for agent: {agent_id}")

    def unregister_peer_client(self, agent_id: str):
        """Unregister a PeerClient when agent leaves mesh."""
        self._agent_peer_clients.pop(agent_id, None)
        logger.debug(f"Unregistered PeerClient for agent: {agent_id}")

    def get_remote_agent(self, role_or_id: str) -> Optional[Dict[str, Any]]:
        """
        Find a remote agent by role or agent ID.

        Args:
            role_or_id: Role name or agent_id to search for

        Returns:
            Agent info dict with node_id, or None if not found

        Example:
            info = coordinator.get_remote_agent("analyst")
            if info:
                print(f"Found analyst at {info['node_id']}")
        """
        # Direct agent_id lookup
        if role_or_id in self._remote_agent_registry:
            return self._remote_agent_registry[role_or_id]

        # Role lookup
        for agent_id, info in self._remote_agent_registry.items():
            if info.get('role') == role_or_id:
                return {'agent_id': agent_id, **info}

        return None

    def list_remote_agents(self) -> List[Dict[str, Any]]:
        """
        List all known remote agents.

        Returns:
            List of agent info dicts with agent_id, role, capabilities, node_id
        """
        return [
            {'agent_id': aid, **info}
            for aid, info in self._remote_agent_registry.items()
        ]

    async def _handle_peer_notify(self, sender, message):
        """Handle peer notification message."""
        try:
            payload = message.get('payload', {})
            target = payload.get('target')

            # Find target agent's PeerClient
            target_client = self._find_peer_client_by_role_or_id(target)
            if not target_client:
                logger.warning(f"Peer notify: target '{target}' not found")
                return

            # Create incoming message and deliver
            incoming = IncomingMessage(
                sender=payload.get('sender', sender),
                sender_node=payload.get('sender_node', sender),
                type=MessageType.NOTIFY,
                data=payload.get('data', {}),
                correlation_id=payload.get('correlation_id'),
                timestamp=payload.get('timestamp', 0)
            )

            await target_client._deliver_message(incoming)
            logger.debug(f"Delivered peer notify to {target}")

        except Exception as e:
            logger.error(f"Error handling peer notify: {e}")

    async def _handle_peer_request(self, sender, message):
        """Handle peer request message (expects response)."""
        try:
            payload = message.get('payload', {})
            target = payload.get('target')

            # Find target agent's PeerClient
            target_client = self._find_peer_client_by_role_or_id(target)
            if not target_client:
                logger.warning(f"Peer request: target '{target}' not found")
                return

            # Create incoming message and deliver
            incoming = IncomingMessage(
                sender=payload.get('sender', sender),
                sender_node=payload.get('sender_node', sender),
                type=MessageType.REQUEST,
                data=payload.get('data', {}),
                correlation_id=payload.get('correlation_id'),
                timestamp=payload.get('timestamp', 0)
            )

            await target_client._deliver_message(incoming)
            logger.debug(f"Delivered peer request to {target}")

        except Exception as e:
            logger.error(f"Error handling peer request: {e}")

    async def _handle_peer_response(self, sender, message):
        """Handle peer response message."""
        try:
            payload = message.get('payload', {})
            target = payload.get('target')

            # Find target agent's PeerClient
            target_client = self._find_peer_client_by_role_or_id(target)
            if not target_client:
                logger.warning(f"Peer response: target '{target}' not found")
                return

            # Create incoming message and deliver
            incoming = IncomingMessage(
                sender=payload.get('sender', sender),
                sender_node=payload.get('sender_node', sender),
                type=MessageType.RESPONSE,
                data=payload.get('data', {}),
                correlation_id=payload.get('correlation_id'),
                timestamp=payload.get('timestamp', 0)
            )

            await target_client._deliver_message(incoming)
            logger.debug(f"Delivered peer response to {target}")

        except Exception as e:
            logger.error(f"Error handling peer response: {e}")

    def _find_peer_client_by_role_or_id(self, target: str):
        """
        Find a PeerClient by agent role or agent_id.

        Args:
            target: Role name or agent_id

        Returns:
            PeerClient instance or None
        """
        # Try direct agent_id lookup
        if target in self._agent_peer_clients:
            return self._agent_peer_clients[target]

        # Try role lookup via agents
        for agent in self.agents:
            if agent.role == target or agent.agent_id == target:
                return self._agent_peer_clients.get(agent.agent_id)

        return None
