"""
Test 20: Load Balancing Strategies (Feature F7)

Tests the discovery load balancing strategies:
- strategy="first" (default behavior)
- strategy="random" (shuffled order)
- strategy="round_robin" (rotates each call)
- strategy="least_recent" (oldest used first)
- discover_one() convenience method
- record_peer_usage()

Run with: pytest tests/test_20_load_balancing.py -v -s
"""
import asyncio
import sys
import time
import pytest
import logging
from unittest.mock import MagicMock, patch
from collections import Counter

sys.path.insert(0, '.')

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# =============================================================================
# TEST: STRATEGY FIRST (DEFAULT)
# =============================================================================

class TestStrategyFirst:
    """Test strategy='first' (default behavior)."""

    def test_discover_first_returns_consistent_order(self):
        """Test 'first' strategy returns peers in consistent order."""
        from jarviscore.testing import MockPeerClient

        client = MockPeerClient(
            agent_id="test-agent",
            agent_role="test",
            mock_peers=[
                {"role": "worker", "agent_id": "worker-a", "capabilities": ["work"]},
                {"role": "worker", "agent_id": "worker-b", "capabilities": ["work"]},
                {"role": "worker", "agent_id": "worker-c", "capabilities": ["work"]}
            ]
        )

        # Multiple calls should return same order
        result1 = client.discover(role="worker", strategy="first")
        result2 = client.discover(role="worker", strategy="first")
        result3 = client.discover(role="worker", strategy="first")

        ids1 = [p.agent_id for p in result1]
        ids2 = [p.agent_id for p in result2]
        ids3 = [p.agent_id for p in result3]

        assert ids1 == ids2 == ids3

    def test_discover_default_strategy_is_first(self):
        """Test default strategy is 'first'."""
        from jarviscore.testing import MockPeerClient

        client = MockPeerClient(
            agent_id="test-agent",
            agent_role="test",
            mock_peers=[
                {"role": "worker", "agent_id": "worker-1", "capabilities": ["work"]},
                {"role": "worker", "agent_id": "worker-2", "capabilities": ["work"]}
            ]
        )

        # No strategy specified
        result_default = client.discover(role="worker")
        # Explicit first
        result_first = client.discover(role="worker", strategy="first")

        ids_default = [p.agent_id for p in result_default]
        ids_first = [p.agent_id for p in result_first]

        assert ids_default == ids_first


# =============================================================================
# TEST: STRATEGY RANDOM
# =============================================================================

class TestStrategyRandom:
    """Test strategy='random' (shuffled order)."""

    def test_discover_random_returns_all_peers(self):
        """Test 'random' strategy returns all peers."""
        from jarviscore.testing import MockPeerClient

        client = MockPeerClient(
            agent_id="test-agent",
            agent_role="test",
            mock_peers=[
                {"role": "worker", "agent_id": "worker-1", "capabilities": ["work"]},
                {"role": "worker", "agent_id": "worker-2", "capabilities": ["work"]},
                {"role": "worker", "agent_id": "worker-3", "capabilities": ["work"]}
            ]
        )

        result = client.discover(role="worker", strategy="random")

        assert len(result) == 3
        ids = {p.agent_id for p in result}
        assert ids == {"worker-1", "worker-2", "worker-3"}

    def test_discover_random_varies_order(self):
        """Test 'random' strategy produces different orders over many calls."""
        from jarviscore.testing import MockPeerClient

        client = MockPeerClient(
            agent_id="test-agent",
            agent_role="test",
            mock_peers=[
                {"role": "worker", "agent_id": "w-1", "capabilities": ["work"]},
                {"role": "worker", "agent_id": "w-2", "capabilities": ["work"]},
                {"role": "worker", "agent_id": "w-3", "capabilities": ["work"]},
                {"role": "worker", "agent_id": "w-4", "capabilities": ["work"]}
            ]
        )

        # Collect first elements over many iterations
        first_peers = []
        for _ in range(50):
            result = client.discover(role="worker", strategy="random")
            first_peers.append(result[0].agent_id)

        # Should have variation in first position
        unique_first = set(first_peers)
        # With 4 workers and 50 iterations, should see at least 2 different first peers
        assert len(unique_first) >= 2, "Random strategy should vary the order"


# =============================================================================
# TEST: STRATEGY ROUND ROBIN
# =============================================================================

class TestStrategyRoundRobin:
    """Test strategy='round_robin' (rotates each call)."""

    def test_discover_round_robin_rotates(self):
        """Test 'round_robin' strategy rotates through peers."""
        from jarviscore.testing import MockPeerClient

        client = MockPeerClient(
            agent_id="test-agent",
            agent_role="test",
            mock_peers=[
                {"role": "worker", "agent_id": "w-0", "capabilities": ["work"]},
                {"role": "worker", "agent_id": "w-1", "capabilities": ["work"]},
                {"role": "worker", "agent_id": "w-2", "capabilities": ["work"]}
            ]
        )

        # First call
        result1 = client.discover(role="worker", strategy="round_robin")
        first1 = result1[0].agent_id

        # Second call - should rotate
        result2 = client.discover(role="worker", strategy="round_robin")
        first2 = result2[0].agent_id

        # Third call - should rotate again
        result3 = client.discover(role="worker", strategy="round_robin")
        first3 = result3[0].agent_id

        # Fourth call - should wrap around
        result4 = client.discover(role="worker", strategy="round_robin")
        first4 = result4[0].agent_id

        # Should have rotated through all three
        firsts = [first1, first2, first3]
        assert len(set(firsts)) == 3, "Round robin should cycle through all peers"

        # Fourth should match first (wrapped around)
        assert first4 == first1, "Round robin should wrap around"

    def test_round_robin_independent_keys(self):
        """Test round robin maintains separate indices per discovery key."""
        from jarviscore.testing import MockPeerClient

        client = MockPeerClient(
            agent_id="test-agent",
            agent_role="test",
            mock_peers=[
                {"role": "analyst", "agent_id": "a-0", "capabilities": ["analysis"]},
                {"role": "analyst", "agent_id": "a-1", "capabilities": ["analysis"]},
                {"role": "worker", "agent_id": "w-0", "capabilities": ["work"]},
                {"role": "worker", "agent_id": "w-1", "capabilities": ["work"]}
            ]
        )

        # Query analysts
        analysts1 = client.discover(role="analyst", strategy="round_robin")
        analyst_first1 = analysts1[0].agent_id

        # Query workers
        workers1 = client.discover(role="worker", strategy="round_robin")
        worker_first1 = workers1[0].agent_id

        # Query analysts again - should have rotated independently
        analysts2 = client.discover(role="analyst", strategy="round_robin")
        analyst_first2 = analysts2[0].agent_id

        # Query workers again
        workers2 = client.discover(role="worker", strategy="round_robin")
        worker_first2 = workers2[0].agent_id

        # Each role should have rotated independently
        assert analyst_first1 != analyst_first2
        assert worker_first1 != worker_first2


# =============================================================================
# TEST: STRATEGY LEAST RECENT
# =============================================================================

class TestStrategyLeastRecent:
    """Test strategy='least_recent' (oldest used first)."""

    def test_discover_least_recent_prefers_unused(self):
        """Test 'least_recent' returns unused peers first."""
        from jarviscore.testing import MockPeerClient

        client = MockPeerClient(
            agent_id="test-agent",
            agent_role="test",
            mock_peers=[
                {"role": "worker", "agent_id": "w-1", "capabilities": ["work"]},
                {"role": "worker", "agent_id": "w-2", "capabilities": ["work"]},
                {"role": "worker", "agent_id": "w-3", "capabilities": ["work"]}
            ]
        )

        # Mark w-2 as recently used
        client.record_peer_usage("w-2")

        result = client.discover(role="worker", strategy="least_recent")

        # w-2 should be last (most recently used)
        assert result[-1].agent_id == "w-2"

    def test_discover_least_recent_ordering(self):
        """Test 'least_recent' orders by usage time."""
        from jarviscore.testing import MockPeerClient

        client = MockPeerClient(
            agent_id="test-agent",
            agent_role="test",
            mock_peers=[
                {"role": "worker", "agent_id": "w-1", "capabilities": ["work"]},
                {"role": "worker", "agent_id": "w-2", "capabilities": ["work"]},
                {"role": "worker", "agent_id": "w-3", "capabilities": ["work"]}
            ]
        )

        # Mark usage in specific order
        client.record_peer_usage("w-3")  # First used
        time.sleep(0.01)
        client.record_peer_usage("w-1")  # Second used
        time.sleep(0.01)
        client.record_peer_usage("w-2")  # Most recently used

        result = client.discover(role="worker", strategy="least_recent")

        ids = [p.agent_id for p in result]

        # w-3 should be first (least recently used), w-2 last (most recent)
        assert ids[0] == "w-3"
        assert ids[-1] == "w-2"


# =============================================================================
# TEST: RECORD_PEER_USAGE
# =============================================================================

class TestRecordPeerUsage:
    """Test record_peer_usage() method."""

    def test_record_peer_usage_updates_timestamp(self):
        """Test record_peer_usage() updates internal timestamp."""
        from jarviscore.testing import MockPeerClient

        client = MockPeerClient()

        # Initially no usage recorded
        assert client._peer_last_used.get("peer-1") is None

        client.record_peer_usage("peer-1")

        assert client._peer_last_used.get("peer-1") is not None
        assert isinstance(client._peer_last_used["peer-1"], float)

    def test_record_peer_usage_updates_on_repeated_calls(self):
        """Test record_peer_usage() updates timestamp on repeated calls."""
        from jarviscore.testing import MockPeerClient

        client = MockPeerClient()

        client.record_peer_usage("peer-1")
        first_time = client._peer_last_used["peer-1"]

        time.sleep(0.01)

        client.record_peer_usage("peer-1")
        second_time = client._peer_last_used["peer-1"]

        assert second_time > first_time


# =============================================================================
# TEST: DISCOVER_ONE
# =============================================================================

class TestDiscoverOne:
    """Test discover_one() convenience method."""

    def test_discover_one_returns_single_peer(self):
        """Test discover_one() returns single PeerInfo."""
        from jarviscore.testing import MockPeerClient
        from jarviscore.p2p.messages import PeerInfo

        client = MockPeerClient(
            agent_id="test-agent",
            agent_role="test",
            mock_peers=[
                {"role": "analyst", "agent_id": "a-1", "capabilities": ["analysis"]},
                {"role": "analyst", "agent_id": "a-2", "capabilities": ["analysis"]}
            ]
        )

        result = client.discover_one(role="analyst")

        assert result is not None
        assert isinstance(result, PeerInfo)
        assert result.role == "analyst"

    def test_discover_one_returns_none_if_no_match(self):
        """Test discover_one() returns None if no peers match."""
        from jarviscore.testing import MockPeerClient

        client = MockPeerClient(
            agent_id="test-agent",
            agent_role="test",
            mock_peers=[{"role": "worker", "capabilities": ["work"]}]
        )

        result = client.discover_one(role="analyst")

        assert result is None

    def test_discover_one_with_strategy(self):
        """Test discover_one() respects strategy parameter."""
        from jarviscore.testing import MockPeerClient

        client = MockPeerClient(
            agent_id="test-agent",
            agent_role="test",
            mock_peers=[
                {"role": "worker", "agent_id": "w-0", "capabilities": ["work"]},
                {"role": "worker", "agent_id": "w-1", "capabilities": ["work"]},
                {"role": "worker", "agent_id": "w-2", "capabilities": ["work"]}
            ]
        )

        # Round robin should rotate
        first1 = client.discover_one(role="worker", strategy="round_robin")
        first2 = client.discover_one(role="worker", strategy="round_robin")
        first3 = client.discover_one(role="worker", strategy="round_robin")

        ids = [first1.agent_id, first2.agent_id, first3.agent_id]
        assert len(set(ids)) == 3, "Round robin via discover_one should rotate"

    def test_discover_one_with_capability(self):
        """Test discover_one() filters by capability."""
        from jarviscore.testing import MockPeerClient

        client = MockPeerClient(
            agent_id="test-agent",
            agent_role="test",
            mock_peers=[
                {"role": "agent1", "agent_id": "a-1", "capabilities": ["analysis"]},
                {"role": "agent2", "agent_id": "a-2", "capabilities": ["reporting"]},
                {"role": "agent3", "agent_id": "a-3", "capabilities": ["analysis", "reporting"]}
            ]
        )

        result = client.discover_one(capability="reporting")

        assert result is not None
        assert "reporting" in result.capabilities


# =============================================================================
# TEST: REAL PEER CLIENT STRATEGIES
# =============================================================================

class TestRealPeerClientStrategies:
    """Test strategies with real PeerClient."""

    def test_real_client_round_robin(self):
        """Test real PeerClient round robin strategy."""
        from jarviscore.p2p.peer_client import PeerClient

        mock_coordinator = MagicMock()
        mock_coordinator._remote_agent_registry = {}

        # Create mock agents
        class MockAgent:
            def __init__(self, aid, role):
                self.agent_id = aid
                self.role = role
                self.capabilities = ["work"]

        agents = [
            MockAgent("w-0", "worker"),
            MockAgent("w-1", "worker"),
            MockAgent("w-2", "worker")
        ]

        agent_registry = {"worker": agents}

        client = PeerClient(
            coordinator=mock_coordinator,
            agent_id="client-1",
            agent_role="client",
            agent_registry=agent_registry,
            node_id="localhost:7946"
        )

        # Collect first results
        firsts = []
        for _ in range(6):  # 2 full cycles
            result = client.discover(role="worker", strategy="round_robin")
            firsts.append(result[0].agent_id)

        # Should cycle: 0,1,2,0,1,2
        assert firsts[:3] != firsts[3:] or len(set(firsts[:3])) == 3

    def test_real_client_least_recent(self):
        """Test real PeerClient least_recent strategy."""
        from jarviscore.p2p.peer_client import PeerClient

        mock_coordinator = MagicMock()
        mock_coordinator._remote_agent_registry = {}

        class MockAgent:
            def __init__(self, aid, role):
                self.agent_id = aid
                self.role = role
                self.capabilities = ["work"]

        agents = [
            MockAgent("w-1", "worker"),
            MockAgent("w-2", "worker"),
            MockAgent("w-3", "worker")
        ]

        agent_registry = {"worker": agents}

        client = PeerClient(
            coordinator=mock_coordinator,
            agent_id="client-1",
            agent_role="client",
            agent_registry=agent_registry,
            node_id="localhost:7946"
        )

        # Mark some as used
        client.record_peer_usage("w-2")

        result = client.discover(role="worker", strategy="least_recent")

        # w-2 should be last
        assert result[-1].agent_id == "w-2"


# =============================================================================
# TEST: EDGE CASES
# =============================================================================

class TestLoadBalancingEdgeCases:
    """Test edge cases for load balancing."""

    def test_single_peer_all_strategies(self):
        """Test all strategies work with single peer."""
        from jarviscore.testing import MockPeerClient

        client = MockPeerClient(
            agent_id="test-agent",
            agent_role="test",
            mock_peers=[{"role": "worker", "agent_id": "w-1", "capabilities": ["work"]}]
        )

        for strategy in ["first", "random", "round_robin", "least_recent"]:
            result = client.discover(role="worker", strategy=strategy)
            assert len(result) == 1
            assert result[0].agent_id == "w-1"

    def test_empty_results_all_strategies(self):
        """Test all strategies handle empty results."""
        from jarviscore.testing import MockPeerClient

        client = MockPeerClient(
            agent_id="test-agent",
            agent_role="test",
            mock_peers=[{"role": "analyst", "capabilities": ["analysis"]}]
        )

        for strategy in ["first", "random", "round_robin", "least_recent"]:
            result = client.discover(role="nonexistent", strategy=strategy)
            assert result == []

    def test_unknown_strategy_falls_back_to_first(self):
        """Test unknown strategy falls back to 'first' behavior."""
        from jarviscore.testing import MockPeerClient

        client = MockPeerClient(
            agent_id="test-agent",
            agent_role="test",
            mock_peers=[
                {"role": "worker", "agent_id": "w-1", "capabilities": ["work"]},
                {"role": "worker", "agent_id": "w-2", "capabilities": ["work"]}
            ]
        )

        result1 = client.discover(role="worker", strategy="unknown_strategy")
        result2 = client.discover(role="worker", strategy="first")

        ids1 = [p.agent_id for p in result1]
        ids2 = [p.agent_id for p in result2]

        assert ids1 == ids2


# =============================================================================
# RUN TESTS
# =============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
