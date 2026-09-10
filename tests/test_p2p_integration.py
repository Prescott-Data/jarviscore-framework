"""
Tests for P2P Integration (Day 2)

Tests SWIM protocol, keepalive, broadcaster, and P2P coordinator.
"""
import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock

from jarviscore import Mesh
from jarviscore.p2p.peer_client import PeerClient
from jarviscore.p2p.peer_tool import PeerTool
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
    async def test_p2p_disabled_when_config_says_false(self, monkeypatch):
        """Test that P2P is disabled when explicitly set to False in config."""
        monkeypatch.delenv("P2P_ENABLED", raising=False)
        mesh = Mesh(config={"p2p_enabled": False})
        mesh.add(TestP2PAgent)
        await mesh.start()

        # P2P should not be initialized when disabled via config
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
    async def test_autoagents_answer_peer_requests_without_custom_listener_wiring(self, monkeypatch):
        class Requester(AutoAgent):
            role = "requester"
            capabilities = ["coordination"]
            system_prompt = "Coordinate work."

            async def setup(self):
                pass

            async def execute_task(self, task):
                return {"status": "success", "output": task["task"]}

        class Analyst(AutoAgent):
            role = "analyst"
            capabilities = ["analysis"]
            system_prompt = "Analyse evidence."

            async def setup(self):
                pass

            async def execute_task(self, task):
                return {"status": "success", "output": f"analysed: {task['task']}"}

        monkeypatch.setattr(Mesh, "_init_redis", lambda self, settings: None)
        monkeypatch.setattr(Mesh, "_init_blob_storage", lambda self, settings: None)
        monkeypatch.setattr(Mesh, "_init_nexus", lambda self: None)
        monkeypatch.setattr(Mesh, "_init_athena", lambda self, settings: None)
        mesh = Mesh()
        requester = mesh.add(Requester)
        mesh.add(Analyst)

        await mesh.start()
        try:
            response = await requester.peers.as_tool().execute(
                "ask_peer", {"role": "analyst", "question": "Review Acme"}
            )
            assert "analysed: Review Acme" in response
        finally:
            await mesh.stop()

    @pytest.mark.asyncio
    async def test_autoagents_request_help_by_capability_with_recipient_authority(
        self, monkeypatch
    ):
        received = []

        class Requester(AutoAgent):
            role = "requester"
            capabilities = ["coordination"]
            system_prompt = "Coordinate work."

            async def setup(self):
                pass

        class ContactVerifier(AutoAgent):
            role = "contact_verifier"
            capabilities = ["contact_verification"]
            capability_descriptions = {
                "contact_verification": "Resolve contact identity from connected sources.",
            }
            capability_contracts = {
                "contact_verification": {
                    "effects": ["read"], "systems": ["gmail", "hubspot"],
                },
            }
            system_prompt = "Verify contacts."

            async def setup(self):
                pass

            async def execute_task(self, task):
                received.append(task)
                return {"status": "success", "output": {"email": "ephy@example.com"}}

        monkeypatch.setattr(Mesh, "_init_redis", lambda self, settings: None)
        monkeypatch.setattr(Mesh, "_init_blob_storage", lambda self, settings: None)
        monkeypatch.setattr(Mesh, "_init_nexus", lambda self: None)
        monkeypatch.setattr(Mesh, "_init_athena", lambda self, settings: None)
        mesh = Mesh(config={"p2p_enabled": False})
        requester = mesh.add(Requester, agent_id="requester-1")
        mesh.add(ContactVerifier, agent_id="verifier-1")

        await mesh.start()
        try:
            ask_schema = next(
                item
                for item in requester.peers.as_tool().schema
                if item["name"] == "ask_capability"
            )
            assert "Resolve contact identity" in ask_schema["description"]
            response = await requester.peers.as_tool().execute(
                "ask_capability",
                {
                    "capability": "contact_verification",
                    "question": "Find a verified contact path for Ephy Kizito.",
                },
                context={
                    "workflow_id": "wf-1", "objective": "Prepare the customer meeting",
                    "system": "google_calendar", "effect": "write",
                    "_nexus_connection_id": "caller-secret",
                },
            )
        finally:
            await mesh.stop()

        assert "ephy@example.com" in response
        context = received[0]["context"]
        assert context["workflow_id"] == "wf-1"
        assert context["objective"] == "Prepare the customer meeting"
        assert context["capability"] == "contact_verification"
        assert context["effect"] == "read"
        assert context["systems"] == ["gmail", "hubspot"]
        assert "system" not in context
        assert "_nexus_connection_id" not in context

    @pytest.mark.asyncio
    async def test_peer_tool_schema_error_is_typed_and_never_dispatched(self):
        peers = MagicMock()
        peers.my_id = "requester-1"
        peers.my_role = "requester"
        peers.list_roles.return_value = ["analyst"]
        peers.list_peers.return_value = [{
            "role": "analyst",
            "capabilities": ["analysis"],
        }]
        tool = PeerTool(peers)

        result = await tool.execute_result(
            "ask_peer",
            {
                "peer": "analyst",
                "task": "Review Acme",
                "context": "Known facts",
            },
        )

        assert result["status"] == "error"
        assert result["semantic_error"] == "INVALID_PEER_TOOL_ARGUMENTS"
        assert result["peer_request_attempted"] is False
        peers.request.assert_not_called()

    @pytest.mark.asyncio
    async def test_peer_request_timeout_is_distinct_from_missing_identity(self):
        class SlowPeer:
            agent_id = "slow-peer"
            role = "slow_peer"

        client = PeerClient.__new__(PeerClient)
        client._agent_id = "requester"
        client._agent_role = "requester"
        client._node_id = "node-1"
        client._pending_requests = {}
        client._logger = MagicMock()
        client._resolve_target = MagicMock(return_value=SlowPeer())
        client._send_message = AsyncMock(return_value=True)

        result = await client.request(
            "slow_peer", {"query": "Review evidence"}, timeout=0.001
        )

        assert result["semantic_error"] == "PEER_RESPONSE_TIMEOUT"
        assert result["peer_request_attempted"] is True

    @pytest.mark.asyncio
    async def test_capability_request_rejects_an_active_ancestor(self, monkeypatch):
        class Requester(AutoAgent):
            role = "requester"
            capabilities = ["coordination"]
            system_prompt = "Coordinate work."

            async def setup(self):
                pass

        class Reconciler(AutoAgent):
            role = "reconciler"
            capabilities = ["crm_reconciliation"]
            system_prompt = "Reconcile CRM evidence."

            async def setup(self):
                pass

        monkeypatch.setattr(Mesh, "_init_redis", lambda self, settings: None)
        monkeypatch.setattr(Mesh, "_init_blob_storage", lambda self, settings: None)
        monkeypatch.setattr(Mesh, "_init_nexus", lambda self: None)
        monkeypatch.setattr(Mesh, "_init_athena", lambda self, settings: None)
        mesh = Mesh(config={"p2p_enabled": False})
        requester = mesh.add(Requester, agent_id="requester-1")
        mesh.add(Reconciler, agent_id="reconciler-1")

        await mesh.start()
        try:
            response = await requester.peers.as_tool().execute(
                "ask_capability",
                {
                    "capability": "crm_reconciliation",
                    "question": "Inspect the associated CRM records.",
                },
                context={"peer_request_lineage": ["reconciler-1"]},
            )
        finally:
            await mesh.stop()

        assert "no non-cyclic peer" in response

    @pytest.mark.asyncio
    async def test_autoagent_notifications_enter_its_durable_mailbox(self, monkeypatch):
        class Peer(AutoAgent):
            role = "peer"
            capabilities = ["work"]
            system_prompt = "Do peer work."

            async def setup(self):
                pass

            async def execute_task(self, task):
                return {"status": "success", "output": "done"}

        monkeypatch.setattr(Mesh, "_init_redis", lambda self, settings: None)
        monkeypatch.setattr(Mesh, "_init_blob_storage", lambda self, settings: None)
        monkeypatch.setattr(Mesh, "_init_nexus", lambda self: None)
        monkeypatch.setattr(Mesh, "_init_athena", lambda self, settings: None)
        mesh = Mesh()
        sender = mesh.add(Peer, agent_id="sender")
        receiver = mesh.add(Peer, agent_id="receiver")

        await mesh.start()
        try:
            await sender.peers.notify(
                "receiver", {"event": "evidence_ready", "step_id": "research"},
                context={"workflow_id": "wf-1"},
            )
            messages = receiver.mailbox.peek()
            assert messages[0]["sender"] == "sender"
            assert messages[0]["message"]["event"] == "evidence_ready"
            assert messages[0]["workflow_id"] == "wf-1"
        finally:
            await mesh.stop()

    @pytest.mark.asyncio
    async def test_autoagent_preserves_application_peer_request_handler(self, monkeypatch):
        class Peer(AutoAgent):
            role = "peer"
            capabilities = ["work"]
            system_prompt = "Do peer work."

            async def setup(self):
                pass

            async def execute_task(self, task):
                raise AssertionError("custom peer handler must run first")

        class Specialist(Peer):
            role = "specialist"
            capabilities = ["specialized"]

            async def on_peer_request(self, message):
                return {"status": "success", "output": message.data["artifact"]}

        monkeypatch.setattr(Mesh, "_init_redis", lambda self, settings: None)
        monkeypatch.setattr(Mesh, "_init_blob_storage", lambda self, settings: None)
        monkeypatch.setattr(Mesh, "_init_nexus", lambda self: None)
        monkeypatch.setattr(Mesh, "_init_athena", lambda self, settings: None)
        mesh = Mesh(config={"p2p_enabled": False})
        sender = mesh.add(Peer, agent_id="sender")
        mesh.add(Specialist, agent_id="specialist-1")

        await mesh.start()
        try:
            response = await sender.peers.request(
                "specialist", {"artifact": {"id": "typed-1"}}, timeout=1
            )
        finally:
            await mesh.stop()

        assert response["output"] == {"id": "typed-1"}

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
