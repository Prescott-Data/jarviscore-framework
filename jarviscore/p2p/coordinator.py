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
            "CAPABILITY_QUERY": self._handle_capability_query,
            "P2P_KEEPALIVE": self.keepalive_manager.handle_keepalive_received,
            "P2P_KEEPALIVE_ACK": self.keepalive_manager.handle_keepalive_ack,
        }

        for msg_type, handler in message_types.items():
            try:
                zmq.router_manager.register_handler(msg_type, handler)
                logger.debug(f"Registered handler for {msg_type}")
            except Exception as e:
                logger.error(f"Failed to register handler for {msg_type}: {e}")

        logger.info(f"Registered {len(message_types)} message handlers")

    async def announce_capabilities(self):
        """Broadcast agent capabilities to mesh."""
        if not self._started:
            raise RuntimeError("P2P Coordinator not started")

        capabilities = {}
        for agent in self.agents:
            for cap in agent.capabilities:
                if cap not in capabilities:
                    capabilities[cap] = []
                capabilities[cap].append(agent.agent_id)

        self._capability_map = capabilities

        payload = {
            'node_id': self._get_node_id(),
            'capabilities': capabilities
        }

        # Broadcast using the broadcaster
        await self.broadcaster.broadcast_step_result(
            step_id='capability_announcement',
            workflow_id='system',
            output_data=payload,
            status='success'
        )

        logger.info(f"Announced capabilities: {list(capabilities.keys())}")

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

            await self.swim_manager.zmq_agent.send_message(target, msg_type, payload)

            # Record activity for keepalive suppression
            if self.keepalive_manager:
                self.keepalive_manager.record_p2p_activity()

            return True
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
        try:
            payload = message.get('payload', {})
            caps = payload.get('capabilities', {})
            node_id = payload.get('node_id')

            # Update local capability map
            for cap, agents in caps.items():
                if cap not in self._capability_map:
                    self._capability_map[cap] = []
                # Add remote agents (avoid duplicates)
                for agent_id in agents:
                    if agent_id not in self._capability_map[cap]:
                        self._capability_map[cap].append(agent_id)

            logger.info(f"Updated capabilities from {node_id}: {list(caps.keys())}")
        except Exception as e:
            logger.error(f"Error handling capability announcement: {e}")

    async def _handle_capability_query(self, sender, message):
        """Handle capability query from peer."""
        try:
            capability = message.get('capability')
            response = {
                'capability': capability,
                'agents': self._capability_map.get(capability, [])
            }
            await self._send_p2p_message(sender, 'CAPABILITY_QUERY_RESPONSE', response)
            logger.debug(f"Responded to capability query from {sender} for {capability}")
        except Exception as e:
            logger.error(f"Error handling capability query: {e}")
