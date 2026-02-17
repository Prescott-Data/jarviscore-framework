"""
Testing utilities for JarvisCore.

Provides mock implementations for unit testing agents without
requiring real P2P infrastructure or network connections.

Example:
    from jarviscore.testing import MockMesh, MockPeerClient

    # Using MockMesh for full integration testing
    mesh = MockMesh()
    mesh.add(MyAgent)
    await mesh.start()

    agent = mesh.get_agent("my_role")
    agent.peers.set_mock_response("analyst", {"result": "test"})

    # Test and verify
    await agent.process_request(...)
    agent.peers.assert_requested("analyst")

    # Using MockPeerClient for unit testing
    agent = MyAgent()
    agent.peers = MockPeerClient(mock_peers=[
        {"role": "analyst", "capabilities": ["analysis"]}
    ])
"""

from .mocks import (
    MockMesh, MockPeerClient, MockPeerInfo,
    MockBlobStorage, MockRedisContextStore,
    MockLLMClient, MockSandboxExecutor,
)

__all__ = [
    'MockMesh',
    'MockPeerClient',
    'MockPeerInfo',
    'MockBlobStorage',
    'MockRedisContextStore',
    'MockLLMClient',
    'MockSandboxExecutor',
]
