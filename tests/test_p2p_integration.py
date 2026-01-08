"""
Tests for P2P Integration (Day 2)

Tests SWIM protocol, keepalive, broadcaster, and P2P coordinator.
"""
import pytest
import asyncio
from jarviscore import Mesh
from jarviscore.profiles import AutoAgent, CustomAgent


class TestP2PAgent(AutoAgent):
    """Test agent for P2P tests"""
    role = "p2p_test"
    capabilities = ["testing", "p2p"]
    system_prompt = "Test agent for P2P integration"

    async def execute_task(self, task):
        return {"status": "success", "output": "test"}


class TestP2PStartup:
    """Test P2P initialization and startup"""

    @pytest.mark.asyncio
    async def test_p2p_disabled_by_default_in_autonomous_mode(self):
        """Test that P2P is disabled by default in autonomous mode"""
        mesh = Mesh(mode="autonomous")
        mesh.add(TestP2PAgent)
        await mesh.start()

        # P2P should not be initialized in autonomous mode by default
        assert mesh._p2p_coordinator is None

        await mesh.stop()

    @pytest.mark.asyncio
    async def test_p2p_enabled_in_distributed_mode(self):
        """Test that P2P is enabled in distributed mode"""
        mesh = Mesh(mode="distributed", config={'bind_port': 7950})
        mesh.add(TestP2PAgent)

        try:
            await mesh.start()

            # P2P should be initialized in distributed mode
            assert mesh._p2p_coordinator is not None
            assert mesh._p2p_coordinator._started is True

            await mesh.stop()
        except Exception as e:
            # If SWIM library is not installed, skip test
            if "swim" in str(e).lower():
                pytest.skip("SWIM library not available")
            raise

    @pytest.mark.asyncio
    async def test_p2p_can_be_explicitly_enabled(self):
        """Test that P2P can be explicitly enabled via config"""
        config = {
            'p2p_enabled': True,
            'bind_port': 7951
        }
        mesh = Mesh(mode="autonomous", config=config)
        mesh.add(TestP2PAgent)

        try:
            await mesh.start()

            # P2P should be initialized when explicitly enabled
            assert mesh._p2p_coordinator is not None
            assert mesh._p2p_coordinator._started is True

            await mesh.stop()
        except Exception as e:
            if "swim" in str(e).lower():
                pytest.skip("SWIM library not available")
            raise


class TestP2PConfiguration:
    """Test P2P configuration"""

    @pytest.mark.asyncio
    async def test_custom_bind_port(self):
        """Test custom bind port configuration"""
        config = {
            'p2p_enabled': True,
            'bind_host': '127.0.0.1',
            'bind_port': 7952,
            'node_name': 'test-node-1'
        }
        mesh = Mesh(mode="autonomous", config=config)
        mesh.add(TestP2PAgent)

        try:
            await mesh.start()

            # Verify configuration was applied
            assert mesh._p2p_coordinator is not None

            await mesh.stop()
        except Exception as e:
            if "swim" in str(e).lower():
                pytest.skip("SWIM library not available")
            raise

    @pytest.mark.asyncio
    async def test_keepalive_configuration(self):
        """Test keepalive configuration"""
        config = {
            'p2p_enabled': True,
            'bind_port': 7953,
            'keepalive_enabled': True,
            'keepalive_interval': 60,
            'keepalive_timeout': 10
        }
        mesh = Mesh(mode="autonomous", config=config)
        mesh.add(TestP2PAgent)

        try:
            await mesh.start()

            # Verify keepalive was configured
            assert mesh._p2p_coordinator is not None
            assert mesh._p2p_coordinator.keepalive_manager is not None
            assert mesh._p2p_coordinator.keepalive_manager.interval == 60

            await mesh.stop()
        except Exception as e:
            if "swim" in str(e).lower():
                pytest.skip("SWIM library not available")
            raise


class TestP2PCapabilities:
    """Test P2P capability announcement"""

    @pytest.mark.asyncio
    async def test_capabilities_announced(self):
        """Test that agent capabilities are announced to mesh"""
        config = {
            'p2p_enabled': True,
            'bind_port': 7954
        }
        mesh = Mesh(mode="autonomous", config=config)

        # Add agents with different capabilities
        class Agent1(AutoAgent):
            role = "agent1"
            capabilities = ["cap1", "cap2"]
            system_prompt = "Agent 1"

            async def execute_task(self, task):
                return {"status": "success"}

        class Agent2(AutoAgent):
            role = "agent2"
            capabilities = ["cap2", "cap3"]
            system_prompt = "Agent 2"

            async def execute_task(self, task):
                return {"status": "success"}

        mesh.add(Agent1)
        mesh.add(Agent2)

        try:
            await mesh.start()

            # Verify capabilities were announced
            assert mesh._p2p_coordinator is not None
            cap_map = mesh._p2p_coordinator._capability_map

            assert "cap1" in cap_map
            assert "cap2" in cap_map
            assert "cap3" in cap_map

            # cap1 should only have agent1
            assert len(cap_map["cap1"]) >= 1

            # cap2 should have both agents
            assert len(cap_map["cap2"]) >= 2

            await mesh.stop()
        except Exception as e:
            if "swim" in str(e).lower():
                pytest.skip("SWIM library not available")
            raise


class TestP2PLifecycle:
    """Test P2P lifecycle management"""

    @pytest.mark.asyncio
    async def test_clean_startup_and_shutdown(self):
        """Test clean P2P startup and shutdown"""
        config = {
            'p2p_enabled': True,
            'bind_port': 7955
        }
        mesh = Mesh(mode="autonomous", config=config)
        mesh.add(TestP2PAgent)

        try:
            # Start mesh
            await mesh.start()
            assert mesh._started is True
            assert mesh._p2p_coordinator is not None
            assert mesh._p2p_coordinator._started is True

            # Stop mesh
            await mesh.stop()
            assert mesh._started is False

        except Exception as e:
            if "swim" in str(e).lower():
                pytest.skip("SWIM library not available")
            raise

    @pytest.mark.asyncio
    async def test_multiple_start_calls_fail(self):
        """Test that starting mesh twice raises error"""
        config = {
            'p2p_enabled': True,
            'bind_port': 7956
        }
        mesh = Mesh(mode="autonomous", config=config)
        mesh.add(TestP2PAgent)

        try:
            await mesh.start()

            # Second start should fail
            with pytest.raises(RuntimeError, match="already started"):
                await mesh.start()

            await mesh.stop()
        except Exception as e:
            if "swim" in str(e).lower():
                pytest.skip("SWIM library not available")
            # Clean up even if test fails
            try:
                await mesh.stop()
            except:
                pass
            raise


class TestP2PIntegrationWithAgents:
    """Test P2P integration with different agent types"""

    @pytest.mark.asyncio
    async def test_autoagent_with_p2p(self):
        """Test AutoAgent with P2P enabled"""
        config = {
            'p2p_enabled': True,
            'bind_port': 7957
        }
        mesh = Mesh(mode="autonomous", config=config)

        class TestAutoAgent(AutoAgent):
            role = "auto"
            capabilities = ["testing"]
            system_prompt = "Test auto agent"

            async def execute_task(self, task):
                return {"status": "success", "output": "auto"}

        mesh.add(TestAutoAgent)

        try:
            await mesh.start()

            # Agent should work with P2P
            assert len(mesh.agents) == 1
            assert mesh._p2p_coordinator is not None

            await mesh.stop()
        except Exception as e:
            if "swim" in str(e).lower():
                pytest.skip("SWIM library not available")
            raise

    @pytest.mark.asyncio
    async def test_customagent_with_p2p(self):
        """Test CustomAgent with P2P enabled"""
        config = {
            'p2p_enabled': True,
            'bind_port': 7958
        }
        mesh = Mesh(mode="autonomous", config=config)

        class TestCustomAgent(CustomAgent):
            role = "custom"
            capabilities = ["testing"]

            async def execute_task(self, task):
                return {"status": "success", "output": "custom"}

        mesh.add(TestCustomAgent)

        try:
            await mesh.start()

            # Agent should work with P2P
            assert len(mesh.agents) == 1
            assert mesh._p2p_coordinator is not None

            await mesh.stop()
        except Exception as e:
            if "swim" in str(e).lower():
                pytest.skip("SWIM library not available")
            raise


class TestP2PHealthChecks:
    """Test P2P health monitoring"""

    @pytest.mark.asyncio
    async def test_swim_manager_health(self):
        """Test SWIM manager health check"""
        config = {
            'p2p_enabled': True,
            'bind_port': 7959
        }
        mesh = Mesh(mode="autonomous", config=config)
        mesh.add(TestP2PAgent)

        try:
            await mesh.start()

            # Check SWIM manager health
            swim_mgr = mesh._p2p_coordinator.swim_manager
            assert swim_mgr is not None
            assert swim_mgr.is_healthy() is True

            status = swim_mgr.get_status()
            assert status['healthy'] is True
            assert status['started'] is True

            await mesh.stop()
        except Exception as e:
            if "swim" in str(e).lower():
                pytest.skip("SWIM library not available")
            raise

    @pytest.mark.asyncio
    async def test_keepalive_health(self):
        """Test keepalive manager health"""
        config = {
            'p2p_enabled': True,
            'bind_port': 7960,
            'keepalive_enabled': True
        }
        mesh = Mesh(mode="autonomous", config=config)
        mesh.add(TestP2PAgent)

        try:
            await mesh.start()

            # Check keepalive health
            keepalive = mesh._p2p_coordinator.keepalive_manager
            assert keepalive is not None
            assert keepalive._running is True

            health = keepalive.get_health_status()
            assert health['enabled'] is True
            assert health['running'] is True

            await mesh.stop()
        except Exception as e:
            if "swim" in str(e).lower():
                pytest.skip("SWIM library not available")
            raise
