"""
Mock implementations for testing JarvisCore agents.

These mocks allow testing agent logic without:
- Real ZMQ connections
- SWIM protocol
- Network operations
- Multiple processes

Example:
    from jarviscore.testing import MockMesh, MockPeerClient

    # Create mock mesh with simulated peers
    mesh = MockMesh()
    mesh.add(MyAgent)
    await mesh.start()

    # Inject mock peer client for testing
    agent = mesh.get_agent("my_role")
    agent.peers.set_mock_response("analyst", {"result": "test"})

    # Test agent behavior
    response = await agent.peers.request("analyst", {"question": "test"})
    assert response == {"result": "test"}

    # Verify interactions
    agent.peers.assert_requested("analyst")
"""
import asyncio
import time
from typing import List, Dict, Any, Optional, Callable
from dataclasses import dataclass, field
from uuid import uuid4

from jarviscore.core.agent import Agent
from jarviscore.p2p.messages import PeerInfo, IncomingMessage, MessageType


@dataclass
class MockPeerInfo:
    """Mock peer for testing discovery."""
    role: str
    capabilities: List[str] = field(default_factory=list)
    agent_id: str = ""
    node_id: str = "mock-node"
    status: str = "alive"
    description: str = ""

    def __post_init__(self):
        if not self.agent_id:
            self.agent_id = f"{self.role}-{uuid4().hex[:8]}"


class MockPeerClient:
    """
    Mock PeerClient for unit testing.

    Simulates peer discovery and messaging without real P2P.
    Can be configured with mock responses for testing specific scenarios.

    Example:
        client = MockPeerClient(
            mock_peers=[
                {"role": "analyst", "capabilities": ["analysis"]},
                {"role": "scout", "capabilities": ["research"]}
            ]
        )

        # Configure mock response
        client.set_mock_response("analyst", {"result": "test data"})

        # Now test your agent
        response = await agent.peers.request("analyst", {"question": "..."})
        assert response == {"result": "test data"}
    """

    def __init__(
        self,
        agent_id: str = "mock-agent",
        agent_role: str = "mock",
        mock_peers: List[Dict[str, Any]] = None,
        auto_respond: bool = True
    ):
        """
        Initialize MockPeerClient.

        Args:
            agent_id: ID for the mock agent
            agent_role: Role for the mock agent
            mock_peers: List of peer definitions with role, capabilities
            auto_respond: If True, automatically respond to requests with mock data
        """
        self._agent_id = agent_id
        self._agent_role = agent_role
        self._auto_respond = auto_respond

        # Build mock peer registry
        self._mock_peers: List[MockPeerInfo] = []
        if mock_peers:
            for peer_def in mock_peers:
                self._mock_peers.append(MockPeerInfo(
                    role=peer_def.get("role", "unknown"),
                    capabilities=peer_def.get("capabilities", []),
                    agent_id=peer_def.get("agent_id", ""),
                    node_id=peer_def.get("node_id", "mock-node"),
                    description=peer_def.get("description", "")
                ))

        # Mock responses for request()
        self._mock_responses: Dict[str, Dict[str, Any]] = {}
        self._default_response: Dict[str, Any] = {"status": "success", "mock": True}

        # Message tracking for assertions
        self._sent_notifications: List[Dict[str, Any]] = []
        self._sent_requests: List[Dict[str, Any]] = []
        self._sent_broadcasts: List[Dict[str, Any]] = []

        # Message queue for receive()
        self._message_queue: asyncio.Queue = asyncio.Queue()

        # Request handler for custom responses
        self._request_handler: Optional[Callable] = None

        # Load balancing state (for strategy support)
        self._round_robin_index: Dict[str, int] = {}
        self._peer_last_used: Dict[str, float] = {}

    # Identity properties
    @property
    def my_role(self) -> str:
        return self._agent_role

    @property
    def my_id(self) -> str:
        return self._agent_id

    # Discovery methods
    def get_peer(self, role: str) -> Optional[PeerInfo]:
        """Get mock peer by role."""
        for peer in self._mock_peers:
            if peer.role == role:
                return PeerInfo(
                    agent_id=peer.agent_id,
                    role=peer.role,
                    capabilities=peer.capabilities,
                    node_id=peer.node_id,
                    status=peer.status
                )
        return None

    def discover(
        self,
        capability: str = None,
        role: str = None,
        strategy: str = "first"
    ) -> List[PeerInfo]:
        """Discover mock peers with strategy support."""
        results = []
        for peer in self._mock_peers:
            if role and peer.role != role:
                continue
            if capability and capability not in peer.capabilities:
                continue
            results.append(PeerInfo(
                agent_id=peer.agent_id,
                role=peer.role,
                capabilities=peer.capabilities,
                node_id=peer.node_id,
                status=peer.status
            ))

        # Apply strategy if needed
        if results and strategy != "first":
            import random
            key = capability or role or "all"

            if strategy == "random":
                random.shuffle(results)
            elif strategy == "round_robin":
                idx = self._round_robin_index.get(key, 0)
                results = results[idx:] + results[:idx]
                self._round_robin_index[key] = (idx + 1) % len(results) if results else 0
            elif strategy == "least_recent":
                results.sort(key=lambda p: self._peer_last_used.get(p.agent_id, 0.0))

        return results

    def discover_one(
        self,
        capability: str = None,
        role: str = None,
        strategy: str = "first"
    ) -> Optional[PeerInfo]:
        """Discover single mock peer."""
        peers = self.discover(capability=capability, role=role, strategy=strategy)
        return peers[0] if peers else None

    def record_peer_usage(self, peer_id: str):
        """Record peer usage for least_recent strategy."""
        self._peer_last_used[peer_id] = time.time()

    def list_roles(self) -> List[str]:
        """List available mock roles."""
        return list(set(p.role for p in self._mock_peers))

    def list_peers(self) -> List[Dict[str, Any]]:
        """List all mock peers."""
        return [
            {
                "role": p.role,
                "agent_id": p.agent_id,
                "capabilities": p.capabilities,
                "status": p.status,
                "location": "mock"
            }
            for p in self._mock_peers
        ]

    # Messaging methods
    async def notify(
        self,
        target: str,
        message: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None
    ) -> bool:
        """Send mock notification (tracked for assertions)."""
        self._sent_notifications.append({
            "target": target,
            "message": message,
            "context": context,
            "timestamp": time.time()
        })
        return True

    async def request(
        self,
        target: str,
        message: Dict[str, Any],
        timeout: float = 30.0,
        context: Optional[Dict[str, Any]] = None
    ) -> Optional[Dict[str, Any]]:
        """Send mock request and return configured response."""
        self._sent_requests.append({
            "target": target,
            "message": message,
            "context": context,
            "timeout": timeout,
            "timestamp": time.time()
        })

        # Use custom handler if set
        if self._request_handler:
            return await self._request_handler(target, message, context)

        # Return configured mock response
        if target in self._mock_responses:
            return self._mock_responses[target]

        if self._auto_respond:
            return self._default_response

        return None

    async def respond(
        self,
        message: IncomingMessage,
        response: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None
    ) -> bool:
        """Mock respond (no-op, returns True)."""
        return True

    async def broadcast(
        self,
        message: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None
    ) -> int:
        """Send mock broadcast (tracked for assertions)."""
        self._sent_broadcasts.append({
            "message": message,
            "context": context,
            "timestamp": time.time()
        })
        return len(self._mock_peers)

    async def receive(self, timeout: float = None) -> Optional[IncomingMessage]:
        """Receive from mock message queue."""
        try:
            if timeout:
                return await asyncio.wait_for(
                    self._message_queue.get(),
                    timeout=timeout
                )
            return self._message_queue.get_nowait()
        except (asyncio.TimeoutError, asyncio.QueueEmpty):
            return None

    def has_pending_messages(self) -> bool:
        """Check mock message queue."""
        return not self._message_queue.empty()

    # Async request methods (Feature 2 compatibility)
    async def ask_async(
        self,
        target: str,
        message: Dict[str, Any],
        timeout: float = 120.0,
        context: Optional[Dict[str, Any]] = None
    ) -> str:
        """Mock async request."""
        correlation_id = f"mock-{uuid4().hex[:12]}"
        self._sent_requests.append({
            "target": target,
            "message": message,
            "context": context,
            "correlation_id": correlation_id,
            "async": True,
            "timestamp": time.time()
        })
        return correlation_id

    async def check_inbox(
        self,
        request_id: str,
        timeout: float = 0.0,
        remove: bool = True
    ) -> Optional[Dict[str, Any]]:
        """Mock inbox check - returns default response."""
        if self._auto_respond:
            return self._default_response
        return None

    def get_pending_async_requests(self) -> List[Dict[str, Any]]:
        """Get pending async requests (always empty for mock)."""
        return []

    def clear_inbox(self, request_id: Optional[str] = None):
        """Clear inbox (no-op for mock)."""
        pass

    # Cognitive context (Feature 4 compatibility)
    def get_cognitive_context(
        self,
        format: str = "markdown",
        include_capabilities: bool = True,
        include_description: bool = True,
        tool_name: str = "ask_peer"
    ) -> str:
        """Generate mock cognitive context."""
        if not self._mock_peers:
            return ""

        lines = ["## AVAILABLE MESH PEERS (Mock)", ""]
        for peer in self._mock_peers:
            lines.append(f"- **{peer.role}** (`{peer.agent_id}`)")
            if include_capabilities and peer.capabilities:
                lines.append(f"  - Capabilities: {', '.join(peer.capabilities)}")
            if include_description and peer.description:
                lines.append(f"  - {peer.description}")
        lines.append("")
        lines.append(f"Use the `{tool_name}` tool to communicate with these peers.")

        return "\n".join(lines)

    # Test configuration methods
    def set_mock_response(self, target: str, response: Dict[str, Any]):
        """Configure response for a specific target."""
        self._mock_responses[target] = response

    def set_default_response(self, response: Dict[str, Any]):
        """Set default response for all requests."""
        self._default_response = response

    def set_request_handler(self, handler: Callable):
        """
        Set custom request handler.

        Args:
            handler: Async function(target, message, context) -> response
        """
        self._request_handler = handler

    def add_mock_peer(self, role: str, capabilities: List[str] = None, **kwargs):
        """Add a mock peer dynamically."""
        self._mock_peers.append(MockPeerInfo(
            role=role,
            capabilities=capabilities or [],
            **kwargs
        ))

    def inject_message(
        self,
        sender: str,
        message_type: MessageType,
        data: Dict[str, Any],
        correlation_id: str = None,
        context: Optional[Dict[str, Any]] = None
    ):
        """
        Inject a message into the receive queue for testing.

        Example:
            client.inject_message(
                sender="analyst",
                message_type=MessageType.NOTIFY,
                data={"event": "analysis_complete", "result": {...}}
            )

            # Agent receives the injected message
            msg = await agent.peers.receive()
        """
        incoming = IncomingMessage(
            sender=sender,
            sender_node="mock-node",
            type=message_type,
            data=data,
            correlation_id=correlation_id,
            context=context
        )
        self._message_queue.put_nowait(incoming)

    # Assertion helpers
    def get_sent_notifications(self) -> List[Dict[str, Any]]:
        """Get all notifications sent during test."""
        return self._sent_notifications.copy()

    def get_sent_requests(self) -> List[Dict[str, Any]]:
        """Get all requests sent during test."""
        return self._sent_requests.copy()

    def get_sent_broadcasts(self) -> List[Dict[str, Any]]:
        """Get all broadcasts sent during test."""
        return self._sent_broadcasts.copy()

    def assert_notified(self, target: str, message_contains: Dict[str, Any] = None):
        """Assert that a notification was sent to target."""
        for notif in self._sent_notifications:
            if notif["target"] == target:
                if message_contains:
                    for key, value in message_contains.items():
                        if notif["message"].get(key) != value:
                            continue
                return True
        raise AssertionError(f"Expected notification to {target} not found")

    def assert_requested(self, target: str, message_contains: Dict[str, Any] = None):
        """Assert that a request was sent to target."""
        for req in self._sent_requests:
            if req["target"] == target:
                if message_contains:
                    for key, value in message_contains.items():
                        if req["message"].get(key) != value:
                            continue
                return True
        raise AssertionError(f"Expected request to {target} not found")

    def assert_broadcasted(self, message_contains: Dict[str, Any] = None):
        """Assert that a broadcast was sent."""
        if not self._sent_broadcasts:
            raise AssertionError("No broadcasts sent")
        if message_contains:
            for broadcast in self._sent_broadcasts:
                match = all(
                    broadcast["message"].get(k) == v
                    for k, v in message_contains.items()
                )
                if match:
                    return True
            raise AssertionError(f"Broadcast with {message_contains} not found")
        return True

    def reset(self):
        """Clear all tracking state."""
        self._sent_notifications.clear()
        self._sent_requests.clear()
        self._sent_broadcasts.clear()
        self._mock_responses.clear()
        self._round_robin_index.clear()
        self._peer_last_used.clear()
        while not self._message_queue.empty():
            try:
                self._message_queue.get_nowait()
            except asyncio.QueueEmpty:
                break


class MockMesh:
    """
    Mock Mesh for unit testing.

    Provides agent registration and setup without P2P infrastructure.

    Example:
        mesh = MockMesh()
        mesh.add(MyAgent)
        await mesh.start()

        agent = mesh.get_agent("my_role")
        # Test agent behavior...
    """

    def __init__(self, mode: str = "p2p"):
        self.mode = mode
        self.agents: List[Agent] = []
        self._agent_registry: Dict[str, List[Agent]] = {}
        self._capability_index: Dict[str, List[Agent]] = {}
        self._started = False

    def add(self, agent_class_or_instance, agent_id: str = None, **kwargs) -> Agent:
        """Register agent with mock mesh."""
        if isinstance(agent_class_or_instance, Agent):
            agent = agent_class_or_instance
        else:
            agent = agent_class_or_instance(agent_id=agent_id, **kwargs)

        agent._mesh = self
        self.agents.append(agent)

        if agent.role not in self._agent_registry:
            self._agent_registry[agent.role] = []
        self._agent_registry[agent.role].append(agent)

        for capability in agent.capabilities:
            if capability not in self._capability_index:
                self._capability_index[capability] = []
            self._capability_index[capability].append(agent)

        return agent

    async def start(self):
        """Start mock mesh (runs agent setup)."""
        for agent in self.agents:
            await agent.setup()
            # Inject mock peer client
            agent.peers = MockPeerClient(
                agent_id=agent.agent_id,
                agent_role=agent.role,
                mock_peers=self._build_peer_list(agent)
            )
        self._started = True

    async def stop(self):
        """Stop mock mesh."""
        for agent in self.agents:
            await agent.teardown()
        self._started = False

    def get_agent(self, role: str) -> Optional[Agent]:
        """Get agent by role."""
        agents = self._agent_registry.get(role, [])
        return agents[0] if agents else None

    def get_agents_by_capability(self, capability: str) -> List[Agent]:
        """Get all agents with a specific capability."""
        return self._capability_index.get(capability, [])

    def _build_peer_list(self, exclude_agent: Agent) -> List[Dict[str, Any]]:
        """Build peer list excluding the specified agent."""
        peers = []
        for agent in self.agents:
            if agent.agent_id != exclude_agent.agent_id:
                peers.append({
                    "role": agent.role,
                    "agent_id": agent.agent_id,
                    "capabilities": list(agent.capabilities),
                    "description": getattr(agent, 'description', '')
                })
        return peers

    def get_diagnostics(self) -> Dict[str, Any]:
        """Get mock diagnostics."""
        return {
            "local_node": {
                "mode": self.mode,
                "started": self._started,
                "agent_count": len(self.agents)
            },
            "known_peers": [],
            "local_agents": [
                {
                    "role": a.role,
                    "agent_id": a.agent_id,
                    "capabilities": list(a.capabilities)
                }
                for a in self.agents
            ],
            "connectivity_status": "mock"
        }


# ======================================================================
# Storage Mocks (v1.0.0)
# ======================================================================

class MockBlobStorage:
    """
    In-memory blob storage for testing.

    Drop-in replacement for LocalBlobStorage/AzureBlobStorage.
    All data lives in a dict — no filesystem or network needed.

    Example:
        storage = MockBlobStorage()
        await storage.save("path/to/file.json", '{"key": "value"}')
        content = await storage.read("path/to/file.json")
        assert content == '{"key": "value"}'
    """

    def __init__(self):
        self._data: Dict[str, Any] = {}

    async def save(self, path: str, content) -> str:
        self._data[path] = content
        return path

    async def read(self, path: str):
        return self._data.get(path)

    async def list(self, prefix: str) -> list:
        return sorted(k for k in self._data if k.startswith(prefix))

    async def delete(self, path: str) -> bool:
        if path in self._data:
            del self._data[path]
            return True
        return False

    async def exists(self, path: str) -> bool:
        return path in self._data

    async def save_scratchpad(self, workflow_id: str, step_id: str,
                              content: str) -> str:
        path = f"workflows/{workflow_id}/scratchpads/{step_id}.md"
        return await self.save(path, content)

    async def read_scratchpad(self, workflow_id: str,
                              step_id: str):
        path = f"workflows/{workflow_id}/scratchpads/{step_id}.md"
        return await self.read(path)

    async def save_artifact(self, workflow_id: str, step_id: str,
                            filename: str, content) -> str:
        path = f"workflows/{workflow_id}/artifacts/{step_id}/{filename}"
        return await self.save(path, content)

    async def read_artifact(self, workflow_id: str, step_id: str,
                            filename: str):
        path = f"workflows/{workflow_id}/artifacts/{step_id}/{filename}"
        return await self.read(path)

    def clear(self):
        """Clear all stored data."""
        self._data.clear()

    @property
    def stored_paths(self) -> list:
        """Get all stored paths (useful for test assertions)."""
        return sorted(self._data.keys())


class MockRedisContextStore:
    """
    In-memory Redis context store for testing.

    Uses fakeredis under the hood — provides a real Redis-compatible backend
    without needing a running Redis server.

    Example:
        store = MockRedisContextStore()
        store.save_step_output("wf-1", "step-1", output={"result": 42})
        result = store.get_step_output("wf-1", "step-1")
        assert result["output"] == {"result": 42}
    """

    def __init__(self):
        import fakeredis
        from jarviscore.storage.redis_store import RedisContextStore

        fake_client = fakeredis.FakeRedis(decode_responses=True)
        # Build a minimal settings-like object
        self._store = RedisContextStore(client=fake_client)

    def __getattr__(self, name):
        """Delegate all method calls to the underlying RedisContextStore."""
        return getattr(self._store, name)
