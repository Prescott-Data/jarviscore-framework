"""Opt-in resource lifetimes must precede defaults and never close another run."""

import asyncio
from types import SimpleNamespace
from typing import ClassVar
from unittest.mock import AsyncMock, Mock

import pytest

from jarviscore.profiles.autoagent import AutoAgent


class Worker(AutoAgent):
    role = "isolated_test_worker"
    capabilities: ClassVar[list[str]] = ["isolated_test_worker"]
    system_prompt = "Test worker"
    requires_auth = True


def factories(monkeypatch):
    from jarviscore import execution

    monkeypatch.setattr(Worker, "_load_agent_profile", lambda self: None)
    monkeypatch.setattr(
        execution, "create_llm_client", lambda config: SimpleNamespace(close=AsyncMock())
    )
    monkeypatch.setattr(
        execution, "create_search_client", lambda: SimpleNamespace(close=AsyncMock())
    )
    monkeypatch.setattr(execution, "create_code_generator", lambda *a: object())
    monkeypatch.setattr(execution, "create_autonomous_repair", lambda *a: object())
    calls = []
    monkeypatch.setattr(
        execution, "create_coder_sandbox", lambda **kw: calls.append(kw) or SimpleNamespace()
    )
    return calls


@pytest.mark.asyncio
async def test_opt_in_resources_precede_defaults_and_are_instance_owned(monkeypatch, tmp_path):
    from jarviscore.execution import code_registry
    from jarviscore.profiles.run_resources import AutoAgentRunResources

    calls = factories(monkeypatch)
    shared = Mock(side_effect=AssertionError("shared registry must not be allocated"))
    monkeypatch.setattr("jarviscore.execution.shared_function_registry", shared)
    mesh = SimpleNamespace(config={"log_directory": "must-not-write", "local_memory": True})
    runs = [
        AutoAgentRunResources(
            workspace_dir=tmp_path / f"work-{i}",
            log_directory=tmp_path / f"logs-{i}",
            nexus_call_proxy=SimpleNamespace(aclose=AsyncMock()),
            config_overrides={"memory_enabled": False},
        )
        for i in range(2)
    ]
    agents = [Worker(run_resources=run) for run in runs]
    for agent in agents:
        agent._mesh = mesh
        agent._auth_manager = object()
    await asyncio.gather(*(a.setup() for a in agents))
    assert agents[0].sandbox is not agents[1].sandbox
    assert agents[0].code_registry is not agents[1].code_registry
    assert agents[0].result_handler.log_directory != agents[1].result_handler.log_directory
    assert all(call["workspace_dir"] == run.workspace_dir for call, run in zip(calls, runs))
    assert all(a._kernel.config["memory_enabled"] is False for a in agents)
    assert mesh.config == {"log_directory": "must-not-write", "local_memory": True}
    for agent in agents:
        await agent.teardown()
    assert not code_registry._SHARED_REGISTRIES.get(str(tmp_path / "logs-0" / "function_registry"))
    with pytest.raises(RuntimeError):
        Worker(run_resources=runs[0])


@pytest.mark.asyncio
async def test_scoped_cleanup_survives_failure_and_cancellation(monkeypatch, tmp_path):
    import jarviscore.nexus.call_proxy as proxy
    from jarviscore.profiles.run_resources import AutoAgentRunResources

    global_close = AsyncMock()
    monkeypatch.setattr(proxy, "close_pooled_clients", global_close)
    started, finish = asyncio.Event(), asyncio.Event()
    cleaned = []

    async def cleanup():
        started.set()
        await finish.wait()
        cleaned.append(True)

    run = AutoAgentRunResources(
        tmp_path / "work",
        tmp_path / "logs",
        cleanup=cleanup,
        nexus_call_proxy=SimpleNamespace(aclose=AsyncMock()),
    )
    agent = Worker(run_resources=run)
    agent._kernel = SimpleNamespace(teardown=AsyncMock(side_effect=RuntimeError("failed")))
    task = asyncio.create_task(agent.teardown())
    await started.wait()
    task.cancel()
    finish.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert cleaned == [True]
    run.nexus_call_proxy.aclose.assert_awaited_once()
    global_close.assert_not_awaited()
    await agent.teardown()
    assert cleaned == [True]


@pytest.mark.asyncio
async def test_setup_failure_releases_owned_resources(monkeypatch, tmp_path):
    from jarviscore.profiles.run_resources import AutoAgentRunResources

    factories(monkeypatch)
    cleanup = AsyncMock()
    run = AutoAgentRunResources(tmp_path / "work", tmp_path / "logs", cleanup=cleanup)
    agent = Worker(run_resources=run)
    monkeypatch.setattr(
        "jarviscore.execution.create_llm_client", Mock(side_effect=RuntimeError("setup"))
    )
    with pytest.raises(RuntimeError, match="setup"):
        await agent.setup()
    cleanup.assert_awaited_once()


@pytest.mark.asyncio
async def test_owned_http_pool_is_independent_of_event_loop_pool(monkeypatch):
    import jarviscore.nexus.call_proxy as native
    from jarviscore.nexus.call_proxy import NexusCallProxy, NexusHttpPool, _pooled_client

    made = []

    def client_factory():
        client = SimpleNamespace(is_closed=False, aclose=AsyncMock())
        made.append(client)
        return client

    monkeypatch.setattr(native.httpx, "AsyncClient", client_factory)
    monkeypatch.setattr(native, "_clients", {})
    shared = _pooled_client()
    pool1, pool2 = NexusHttpPool(), NexusHttpPool()
    assert pool1.client() is not pool2.client()
    assert pool1.client() is not shared
    proxy = NexusCallProxy(object(), http_pool=pool1, original_download_hosts={})
    await proxy.aclose()
    made[1].aclose.assert_awaited_once()
    made[0].aclose.assert_not_awaited()
    made[2].aclose.assert_not_awaited()
    with pytest.raises(RuntimeError):
        pool1.client()
    await pool2.aclose()
    await shared.aclose()


@pytest.mark.asyncio
async def test_native_isolated_mesh_scope_injects_auth_without_shared_stores(monkeypatch, tmp_path):
    from jarviscore.core.mesh import Mesh
    from jarviscore.profiles.run_resources import AutoAgentRunResources

    mesh = Mesh()
    mesh._started = True
    mesh._auth_manager = object()
    mesh._redis_store = object()
    mesh._blob_storage = object()
    agent = Worker(run_resources=AutoAgentRunResources(tmp_path / "work", tmp_path / "logs"))
    agent.setup = AsyncMock()
    agent.teardown = AsyncMock()
    async with mesh.isolated_agent(agent):
        assert agent._auth_manager is mesh._auth_manager
        assert agent._mesh is mesh
        assert agent._redis_store is None and agent._blob_storage is None
        assert agent not in mesh.agents
        assert agent.peers is None and agent.mailbox is None
    agent.teardown.assert_awaited_once()
    mesh._auth_manager = None
    other = Worker(run_resources=AutoAgentRunResources(tmp_path / "work2", tmp_path / "logs2"))
    with pytest.raises(RuntimeError, match="auth"):
        async with mesh.isolated_agent(other):
            pass


@pytest.mark.asyncio
async def test_native_context_policy_and_journal_are_task_local(tmp_path):
    from jarviscore.control.policy import ControlPolicy, current_policy, using_policy
    from jarviscore.evidence.journal import Journal, current_journal, using_journal

    baseline_policy, baseline_journal = current_policy(), current_journal()
    gate = asyncio.Barrier(2)

    async def run(i):
        policy, journal = (
            ControlPolicy(mode="strict", digest=str(i)),
            Journal(str(tmp_path / str(i))),
        )
        with using_policy(policy), using_journal(journal):
            await gate.wait()
            assert current_policy() is policy
            assert current_journal() is journal
            journal.append("wf/step", "test", {"run": i})
        journal.close()

    await asyncio.gather(run(0), run(1))
    assert current_policy() is baseline_policy
    assert current_journal() is baseline_journal


def test_private_memory_and_trace_cannot_discover_shared_services(monkeypatch, tmp_path):
    from jarviscore.kernel.kernel import Kernel
    from jarviscore.kernel.tracing import TraceManager

    monkeypatch.setattr(
        TraceManager, "_init_redis", Mock(side_effect=AssertionError("shared redis"))
    )
    trace = TraceManager("private", "step", trace_dir=str(tmp_path), allow_redis_discovery=False)
    assert trace.redis_client is None
    kernel = Kernel(llm_client=object(), config={"memory_enabled": False})
    kernel.redis_store = object()
    assert kernel._create_memory("private", "step", "agent", {"room_id": "firm/shared"}) is None


def test_native_sandbox_factory_can_keep_outputs_inside_owned_workspace(tmp_path):
    from jarviscore.execution.coder_sandbox import create_coder_sandbox

    sandbox = create_coder_sandbox(workspace_dir=tmp_path / "workspace", output_subdir="output")
    assert sandbox.output_dir == tmp_path / "workspace" / "output"


@pytest.mark.asyncio
async def test_private_native_log_context_keeps_messages_and_exceptions_out_of_shared_logs(caplog):
    import logging

    from jarviscore.profiles.run_resources import using_private_logs

    private = []

    class Sink(logging.Handler):
        def emit(self, record):
            private.append(self.format(record))

    handler = Sink()

    async def private_run():
        with using_private_logs(handler):
            await asyncio.sleep(0)
            try:
                raise RuntimeError("private-original-exception")
            except RuntimeError:
                logging.getLogger("jarviscore.test.private").exception(
                    "original=%s", "private-original-bytes"
                )

    async def ordinary_run():
        await asyncio.sleep(0)
        logging.getLogger("jarviscore.test.ordinary").warning("ordinary-preserved")

    await asyncio.gather(private_run(), ordinary_run())
    assert "private-original-bytes" in private[0] and "private-original-exception" in private[0]
    assert "private-original" not in caplog.text
    assert "ordinary-preserved" in caplog.text
