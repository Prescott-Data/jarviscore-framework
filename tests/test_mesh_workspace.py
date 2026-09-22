import hashlib
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
from typing import ClassVar

import pytest

from jarviscore.core.mesh import Mesh
from jarviscore.core.agent import Agent
from jarviscore.execution import BlobSnapshotStore, SourceRef, create_coder_sandbox
from jarviscore.storage import LocalBlobStorage


@pytest.mark.asyncio
async def test_mesh_prepares_explicit_source_with_configured_adapter(tmp_path):
    blobs = LocalBlobStorage(str(tmp_path / "blobs"))
    store = BlobSnapshotStore(blobs)
    expected = await store.capture(
        SourceRef("fixture", "project", "main"),
        "commit-1",
        {"README.md": "hello\n"},
    )

    class Adapter:
        async def capture(self, source):
            assert source == SourceRef("fixture", "project", "main")
            return expected

    mesh = Mesh(config={
        "workspace_source_adapters": {"fixture": Adapter()},
        "workspace_allowed_commands": ["cargo"],
        "workspace_snapshot_limits": {"max_files": 10},
    })
    mesh._blob_storage = blobs

    context = await mesh._prepare_workspace_source(
        "wf-1",
        {
            "workspace_source": {
                "provider": "fixture",
                "locator": "project",
                "revision": "main",
                "allowed_commands": ["untrusted-command"],
                "limits": {"max_files": 1_000_000},
            }
        },
    )

    assert context["source_snapshot"]["snapshot_id"] == expected.snapshot_id
    assert context["source_snapshot"]["resolved_revision"] == "commit-1"
    assert context["source_snapshot"]["file_count"] == 1
    assert context["source_snapshot"]["allowed_commands"] == ["cargo"]
    assert context["source_snapshot"]["storage_scope"] == "node"
    assert context["source_snapshot"]["materializer_node_id"] == mesh._node_id
    assert "limits" not in context["workspace_source"]
    assert "allowed_commands" not in context["workspace_source"]


@pytest.mark.asyncio
async def test_mesh_discards_caller_injected_snapshot_authority():
    mesh = Mesh()

    context = await mesh._prepare_workspace_source(
        "wf-1",
        {
            "source_snapshot": {"manifest_blob_path": "private/secret.json"},
            "workspace_binding": {"path": "/outside"},
            "business_context": "preserved",
        },
    )

    assert context == {"business_context": "preserved"}


@pytest.mark.asyncio
async def test_required_workspace_fails_before_planning_without_source():
    mesh = Mesh(config={"workspace_required": True})

    with pytest.raises(RuntimeError, match="no trusted source adapters"):
        await mesh._prepare_workspace_source("wf-1", {"business_context": "kept"})


@pytest.mark.asyncio
async def test_required_workspace_resolves_explicit_source_from_goal(tmp_path):
    blobs = LocalBlobStorage(str(tmp_path / "blobs"))
    store = BlobSnapshotStore(blobs)
    expected = await store.capture(
        SourceRef("fixture", "project", "main"),
        "commit-1",
        {"README.md": "hello\n"},
    )

    class Adapter:
        async def capture(self, source):
            assert source == SourceRef("fixture", "project", "main")
            return expected

    class ResolverLLM:
        async def generate(self, **kwargs):
            assert "Inspect fixture project at main" in kwargs["messages"][1]["content"]
            return {
                "content": json.dumps({
                    "provider": "fixture",
                    "locator": "project",
                    "revision": "main",
                })
            }

    mesh = Mesh(config={
        "workspace_required": True,
        "workspace_source_adapters": {"fixture": Adapter()},
    })
    mesh._blob_storage = blobs
    mesh._planning_llm = lambda: ResolverLLM()

    context = await mesh._prepare_workspace_source(
        "wf-1", {}, goal="Inspect fixture project at main"
    )

    assert context["workspace_source"] == {
        "provider": "fixture",
        "locator": "project",
        "revision": "main",
    }
    assert context["source_snapshot"]["resolved_revision"] == "commit-1"


@pytest.mark.asyncio
async def test_required_workspace_rejects_unavailable_resolved_provider():
    async def resolver(goal, context):
        return {"provider": "untrusted", "locator": "outside", "revision": ""}

    mesh = Mesh(config={
        "workspace_required": True,
        "workspace_source_adapters": {"fixture": object()},
        "workspace_source_resolver": resolver,
    })

    with pytest.raises(RuntimeError, match="unavailable provider"):
        await mesh._prepare_workspace_source("wf-1", {}, goal="Inspect outside")


@pytest.mark.asyncio
async def test_mesh_rejects_adapter_snapshot_outside_its_blob_store(tmp_path):
    mesh_blobs = LocalBlobStorage(str(tmp_path / "mesh-blobs"))
    other_store = BlobSnapshotStore(LocalBlobStorage(str(tmp_path / "other-blobs")))
    foreign = await other_store.capture(
        SourceRef("fixture", "project", "main"),
        "commit-1",
        {"README.md": "foreign\n"},
    )

    class Adapter:
        async def capture(self, source):
            return foreign

    mesh = Mesh(config={"workspace_source_adapters": {"fixture": Adapter()}})
    mesh._blob_storage = mesh_blobs

    with pytest.raises(RuntimeError, match="persisted integrity validation"):
        await mesh._prepare_workspace_source(
            "wf-1",
            {"workspace_source": {
                "provider": "fixture",
                "locator": "project",
                "revision": "main",
            }},
        )


@pytest.mark.asyncio
async def test_mesh_binds_and_restores_agent_sandbox_with_dependency_delta(tmp_path):
    blobs = LocalBlobStorage(str(tmp_path / "blobs"))
    store = BlobSnapshotStore(blobs)
    snapshot = await store.capture(
        SourceRef("fixture", "project", "main"),
        "commit-1",
        {"value.txt": "before\n"},
    )
    async with __import__(
        "jarviscore.execution.workspace", fromlist=["SandboxBinding"]
    ).SandboxBinding(store, snapshot) as first:
        (first.workspace / "value.txt").write_text("after\n")
        delta = await first.export_delta("workflows/wf-1/workspace_deltas/step-1")

    original = create_coder_sandbox(workspace_dir=tmp_path / "original")
    cached_coder = SimpleNamespace(role="coder", sandbox=original)
    kernel = SimpleNamespace(sandbox=original, _subagent_cache={"coder": cached_coder})
    agent = SimpleNamespace(sandbox=original, _kernel=kernel)
    mesh = Mesh(config={
        "workspace_command_timeout_seconds": 600,
        "workspace_command_environment": {"CARGO_HOME": str(tmp_path / "cargo")},
    })
    mesh._blob_storage = blobs
    mesh._redis_store = SimpleNamespace(
        get_step_output=lambda workflow_id, step_id: {
            "output": {
                "status": "success",
                "workspace_delta": {"manifest_blob_path": delta.manifest_blob_path},
            }
        }
    )
    task = {
        "context": {
            "source_snapshot": {"manifest_blob_path": snapshot.manifest_blob_path},
            "workflow_id": "wf-1",
            "step_id": "step-2",
            "workflow_plan": {
                "steps": [{"id": "step-2", "depends_on": ["step-1"]}]
            },
        }
    }

    async with mesh._bound_step_workspace(agent, task) as binding:
        assert agent.sandbox.workspace == binding.workspace
        assert agent.sandbox._bash.timeout == 600
        assert agent.sandbox._bash.command_environment == {
            "CARGO_HOME": str(tmp_path / "cargo")
        }
        assert kernel.sandbox is agent.sandbox
        assert cached_coder.sandbox is agent.sandbox
        assert (binding.workspace / "value.txt").read_text() == "after\n"
        assert task["context"]["workspace_binding"]["mode"] == "copy_on_write"

    assert agent.sandbox is original
    assert kernel.sandbox is original
    assert cached_coder.sandbox is original
    assert "workspace_binding" not in task["context"]


@pytest.mark.asyncio
async def test_mesh_materializes_maximal_cumulative_delta_lineage(tmp_path):
    blobs = LocalBlobStorage(str(tmp_path / "blobs"))
    store = BlobSnapshotStore(blobs)
    snapshot = await store.capture(
        SourceRef("fixture", "project", "main"),
        "commit-1",
        {"value.txt": "before\n"},
    )
    async with __import__(
        "jarviscore.execution.workspace", fromlist=["SandboxBinding"]
    ).SandboxBinding(store, snapshot) as ancestor:
        (ancestor.workspace / "value.txt").write_text("ancestor\n")
        ancestor_delta = await ancestor.export_delta(
            "workflows/wf-lineage/workspace_deltas/ancestor"
        )
    async with __import__(
        "jarviscore.execution.workspace", fromlist=["SandboxBinding"]
    ).SandboxBinding(store, snapshot) as descendant:
        await descendant.apply_delta(ancestor_delta)
        (descendant.workspace / "value.txt").write_text("descendant\n")
        descendant_delta = await descendant.export_delta(
            "workflows/wf-lineage/workspace_deltas/descendant"
        )

    original = create_coder_sandbox(workspace_dir=tmp_path / "original")
    agent = SimpleNamespace(
        sandbox=original,
        _kernel=SimpleNamespace(sandbox=original, _subagent_cache={}),
    )
    outputs = {
        "ancestor": {
            "output": {
                "status": "success",
                "workspace_delta": {
                    "manifest_blob_path": ancestor_delta.manifest_blob_path,
                },
            },
        },
        "descendant": {
            "output": {
                "status": "success",
                "workspace_delta": {
                    "manifest_blob_path": descendant_delta.manifest_blob_path,
                },
            },
        },
    }
    mesh = Mesh()
    mesh._blob_storage = blobs
    mesh._redis_store = SimpleNamespace(
        get_step_output=lambda workflow_id, step_id: outputs[step_id],
    )
    task = {
        "context": {
            "source_snapshot": {"manifest_blob_path": snapshot.manifest_blob_path},
            "workflow_id": "wf-lineage",
            "step_id": "verify",
            "workflow_plan": {
                "steps": [
                    {"id": "ancestor", "depends_on": []},
                    {"id": "descendant", "depends_on": ["ancestor"]},
                    {"id": "verify", "depends_on": ["ancestor", "descendant"]},
                ],
            },
        },
    }

    async with mesh._bound_step_workspace(agent, task) as binding:
        assert (binding.workspace / "value.txt").read_text() == "descendant\n"


def test_node_local_snapshot_is_claimed_only_by_materializer_node():
    mesh = Mesh()
    mesh._node_id = "node-a"
    mesh._blob_storage = SimpleNamespace(has_local_path=lambda _: False)
    mesh._redis_store = SimpleNamespace(
        get_workflow_definition=lambda _: {
            "context": {
                "source_snapshot": {
                    "storage_scope": "node",
                    "materializer_node_id": "node-b",
                }
            }
        }
    )

    assert mesh._node_can_access_workspace("wf-1") is False
    mesh._blob_storage = SimpleNamespace(has_local_path=lambda path: path == "snapshots/a.json")
    mesh._redis_store.get_workflow_definition = lambda _: {
        "context": {
            "source_snapshot": {
                "storage_scope": "node",
                "materializer_node_id": "node-b",
                "manifest_blob_path": "snapshots/a.json",
            }
        }
    }
    assert mesh._node_can_access_workspace("wf-1") is True
    mesh._redis_store.get_workflow_definition = lambda _: {
        "context": {"source_snapshot": {"storage_scope": "shared"}}
    }
    assert mesh._node_can_access_workspace("wf-1") is True


@pytest.mark.asyncio
async def test_mesh_terminalizes_step_at_execution_epoch_limit():
    class ExhaustingPeer(Agent):
        role = "analysis"
        capabilities: ClassVar[list[str]] = ["analysis"]

        async def execute_task(self, task):
            return {"status": "epoch_exhausted", "output": {"partial": True}}

    redis = __import__(
        "jarviscore.testing", fromlist=["MockRedisContextStore"]
    ).MockRedisContextStore()
    mesh = Mesh(config={"p2p_enabled": False})
    mesh._redis_store = redis
    peer = mesh.add(ExhaustingPeer)
    redis.publish_workflow(
        "wf-epoch-limit",
        goal="Bound continuation",
        context={},
        obligations=[],
        steps=[{
            "id": "step-1",
            "capability": "analysis",
            "effect": "read",
            "task": "Analyze",
            "depends_on": [],
        }],
        budget={"max_epochs_per_step": 2},
    )

    await mesh._execute_distributed_step(
        peer,
        "wf-epoch-limit",
        "step-1",
        redis.get_step_definition("wf-epoch-limit", "step-1"),
    )
    assert redis.get_step_status("wf-epoch-limit", "step-1") == "pending"
    assert redis.get_step_definition("wf-epoch-limit", "step-1")[
        "execution_epochs"
    ] == 2

    await mesh._execute_distributed_step(
        peer,
        "wf-epoch-limit",
        "step-1",
        redis.get_step_definition("wf-epoch-limit", "step-1"),
    )

    assert redis.get_step_status("wf-epoch-limit", "step-1") == "failed"
    output = redis.get_step_output("wf-epoch-limit", "step-1")["output"]
    assert output["typed_outcome"] == "EXECUTION_EPOCH_LIMIT_REACHED"


@pytest.mark.asyncio
async def test_mesh_preserves_workspace_mutation_across_execution_epochs(tmp_path):
    blobs = LocalBlobStorage(str(tmp_path / "blobs"))
    snapshot = await BlobSnapshotStore(blobs).capture(
        SourceRef("fixture", "project", "main"),
        "commit-1",
        {"service.py": "broken\n"},
    )
    authoritative = {
        "tool_receipt_id": "tool:wf-epoch-workspace:repair:1",
        "path": "service.py",
        "sha256": hashlib.sha256(b"fixed\n").hexdigest(),
        "bytes": len(b"fixed\n"),
        "executable": False,
        "observed_at": "2026-09-19T00:00:00Z",
    }

    class RepairPeer(Agent):
        role = "repair"
        capabilities: ClassVar[list[str]] = ["repair"]
        attempts = 0

        async def execute_task(self, task):
            self.attempts += 1
            path = self.sandbox.workspace / "service.py"
            if self.attempts == 1:
                path.write_text("fixed\n")
                return {"status": "epoch_exhausted", "output": None}
            assert path.read_text() == "fixed\n"
            return {
                "status": "success",
                "output": {"status": "applied", "mutations": [authoritative]},
                "_tool_receipts": [authoritative],
            }

    redis = __import__(
        "jarviscore.testing", fromlist=["MockRedisContextStore"]
    ).MockRedisContextStore()
    mesh = Mesh(config={"p2p_enabled": False})
    mesh._redis_store = redis
    mesh._blob_storage = blobs
    peer = mesh.add(RepairPeer)
    peer.sandbox = create_coder_sandbox(workspace_dir=tmp_path / "repair-base")
    redis.publish_workflow(
        "wf-epoch-workspace",
        goal="Repair",
        context={"source_snapshot": {
            "manifest_blob_path": snapshot.manifest_blob_path,
            "storage_scope": "node",
            "materializer_node_id": mesh._node_id,
        }},
        obligations=[],
        steps=[{
            "id": "repair", "capability": "repair", "effect": "propose",
            "task": "Repair", "depends_on": [],
        }],
        budget={"max_epochs_per_step": 2},
    )

    await mesh._execute_distributed_step(
        peer,
        "wf-epoch-workspace",
        "repair",
        redis.get_step_definition("wf-epoch-workspace", "repair"),
    )
    continued = redis.get_step_definition("wf-epoch-workspace", "repair")
    assert continued["continuation_workspace_delta"]["modified"][0]["path"] == (
        "service.py"
    )

    await mesh._execute_distributed_step(
        peer,
        "wf-epoch-workspace",
        "repair",
        redis.get_step_definition("wf-epoch-workspace", "repair"),
    )

    saved = redis.get_step_output("wf-epoch-workspace", "repair")["output"]
    assert redis.get_step_status("wf-epoch-workspace", "repair") == "completed"
    assert saved["output"]["mutations"] == [authoritative]
    assert saved["workspace_delta"]["modified"][0]["path"] == "service.py"


@pytest.mark.asyncio
async def test_mesh_clears_continuation_delta_after_epoch_reverts_to_source(tmp_path):
    blobs = LocalBlobStorage(str(tmp_path / "blobs"))
    snapshot = await BlobSnapshotStore(blobs).capture(
        SourceRef("fixture", "project", "main"),
        "commit-1",
        {"service.py": "broken\n"},
    )

    class RepairPeer(Agent):
        role = "repair"
        capabilities: ClassVar[list[str]] = ["repair"]
        attempts = 0

        async def execute_task(self, task):
            self.attempts += 1
            path = self.sandbox.workspace / "service.py"
            if self.attempts == 1:
                path.write_text("fixed\n")
                return {"status": "epoch_exhausted", "output": None}
            if self.attempts == 2:
                assert path.read_text() == "fixed\n"
                path.write_text("broken\n")
                return {"status": "epoch_exhausted", "output": None}
            assert path.read_text() == "broken\n"
            return {"status": "success", "output": {"status": "not_applied"}}

    redis = __import__(
        "jarviscore.testing", fromlist=["MockRedisContextStore"]
    ).MockRedisContextStore()
    mesh = Mesh(config={"p2p_enabled": False})
    mesh._redis_store = redis
    mesh._blob_storage = blobs
    peer = mesh.add(RepairPeer)
    peer.sandbox = create_coder_sandbox(workspace_dir=tmp_path / "repair-base")
    redis.publish_workflow(
        "wf-clear-epoch-delta",
        goal="Repair",
        context={"source_snapshot": {
            "manifest_blob_path": snapshot.manifest_blob_path,
            "storage_scope": "node",
            "materializer_node_id": mesh._node_id,
        }},
        obligations=[],
        steps=[{
            "id": "repair", "capability": "repair", "effect": "propose",
            "task": "Repair", "depends_on": [],
        }],
        budget={"max_epochs_per_step": 3},
    )

    for _ in range(3):
        await mesh._execute_distributed_step(
            peer,
            "wf-clear-epoch-delta",
            "repair",
            redis.get_step_definition("wf-clear-epoch-delta", "repair"),
        )

    assert redis.get_step_status("wf-clear-epoch-delta", "repair") == "completed"
    assert "continuation_workspace_delta" not in redis.get_step_definition(
        "wf-clear-epoch-delta", "repair"
    )


@pytest.mark.asyncio
async def test_capability_request_receives_isolated_workflow_workspace(tmp_path):
    blobs = LocalBlobStorage(str(tmp_path / "blobs"))
    store = BlobSnapshotStore(blobs)
    snapshot = await store.capture(
        SourceRef("fixture", "project", "main"),
        "commit-1",
        {"Cargo.toml": "[package]\nname = 'project'\n"},
    )

    class WorkspacePeer(Agent):
        role = "runtime_peer"
        capabilities: ClassVar[list[str]] = ["runtime_diagnosis"]

        async def execute_task(self, task):
            raise AssertionError("Capability peer should not execute a DAG step")

        async def execute_capability_request(self, capability, question, context):
            assert capability == "runtime_diagnosis"
            assert self.sandbox.workspace != original.workspace
            assert (self.sandbox.workspace / "Cargo.toml").is_file()
            assert "cargo" in self.sandbox._bash.allowed_commands
            assert self.sandbox._bash.timeout == 600
            assert context["workspace_binding"]["mode"] == "copy_on_write"
            return {"status": "success", "output": {"verified": True}}

    redis = __import__(
        "jarviscore.testing", fromlist=["MockRedisContextStore"]
    ).MockRedisContextStore()
    mesh = Mesh(config={
        "p2p_enabled": False,
        "workspace_allowed_commands": ["cargo"],
        "workspace_command_timeout_seconds": 600,
    })
    mesh._redis_store = redis
    mesh._blob_storage = blobs
    peer = mesh.add(WorkspacePeer)
    original = create_coder_sandbox(workspace_dir=tmp_path / "original")
    peer.sandbox = original
    redis.publish_workflow(
        "wf-capability-workspace",
        goal="Verify runtime",
        context={
            "source_snapshot": {
                "manifest_blob_path": snapshot.manifest_blob_path,
                "allowed_commands": ["cargo"],
                "storage_scope": "node",
                "materializer_node_id": mesh._node_id,
            }
        },
        obligations=[],
        steps=[{
            "id": "map",
            "capability": "mapping",
            "effect": "read",
            "task": "Map",
            "depends_on": [],
        }],
    )
    need_id = redis.publish_capability_need(
        "wf-capability-workspace",
        requester_agent_id="mapper",
        requester_step_id="map",
        capability="runtime_diagnosis",
        question="Verify Cargo",
        context={},
    )

    await mesh._service_capability_needs(peer, {"runtime_diagnosis"})

    need = redis.get_capability_need("wf-capability-workspace", need_id)
    assert need["status"] == "fulfilled"
    assert need["result"]["output"] == {"verified": True}
    assert peer.sandbox is original


@pytest.mark.asyncio
async def test_github_source_uses_trusted_mesh_limits(tmp_path, monkeypatch):
    blobs = LocalBlobStorage(str(tmp_path / "blobs"))
    store = BlobSnapshotStore(blobs)
    expected = await store.capture(
        SourceRef("github", "acme/project", "main"),
        "commit-1",
        {"README.md": "hello\n"},
    )
    observed = {}

    class GitHubAdapter:
        def __init__(self, nexus_call, snapshot_store, *, limits):
            observed["limits"] = limits

        async def capture(self, source):
            return expected

    monkeypatch.setattr(
        "jarviscore.execution.sources.GitHubRepositorySource", GitHubAdapter
    )
    mesh = Mesh(config={"workspace_snapshot_limits": {"max_files": 10}})
    mesh._blob_storage = blobs
    mesh._auth_manager = SimpleNamespace(discover=AsyncMock(return_value="resolved:github"))

    await mesh._prepare_workspace_source(
        "wf-1",
        {
            "workspace_source": {
                "provider": "github",
                "locator": "acme/project",
                "revision": "main",
                "limits": {"max_files": 1_000_000},
            }
        },
    )

    assert observed["limits"].max_files == 10


@pytest.mark.asyncio
async def test_repair_delta_reaches_independent_verifier_without_mutating_snapshot(tmp_path):
    blobs = LocalBlobStorage(str(tmp_path / "blobs"))
    store = BlobSnapshotStore(blobs)
    snapshot = await store.capture(
        SourceRef("fixture", "project", "main"),
        "commit-1",
        {"service.py": "def value():\n    return 'broken'\n"},
    )

    class RepairPeer(Agent):
        role = "repair"
        capabilities: ClassVar[list[str]] = ["repair"]

        async def execute_task(self, task):
            path = self.sandbox.workspace / "service.py"
            assert "broken" in path.read_text()
            path.write_text("def value():\n    return 'fixed'\n")
            return {"status": "success", "output": {"repair": "proposed"}}

    class VerifyPeer(Agent):
        role = "verify"
        capabilities: ClassVar[list[str]] = ["verify"]

        async def execute_task(self, task):
            content = (self.sandbox.workspace / "service.py").read_text()
            return {"status": "success", "output": {"verified": "fixed" in content}}

    redis = __import__(
        "jarviscore.testing", fromlist=["MockRedisContextStore"]
    ).MockRedisContextStore()
    mesh = Mesh(config={"p2p_enabled": False})
    mesh._redis_store = redis
    mesh._blob_storage = blobs
    repair = mesh.add(RepairPeer)
    verifier = mesh.add(VerifyPeer)
    original_repair_sandbox = create_coder_sandbox(workspace_dir=tmp_path / "repair-base")
    original_verify_sandbox = create_coder_sandbox(workspace_dir=tmp_path / "verify-base")
    repair.sandbox = original_repair_sandbox
    verifier.sandbox = original_verify_sandbox

    context = {
        "source_snapshot": {
            "manifest_blob_path": snapshot.manifest_blob_path,
            "storage_scope": "node",
            "materializer_node_id": mesh._node_id,
        }
    }
    steps = [
        {"id": "repair", "capability": "repair", "effect": "propose", "task": "Repair", "depends_on": []},
        {"id": "verify", "capability": "verify", "effect": "read", "task": "Verify", "depends_on": ["repair"]},
    ]
    redis.publish_workflow(
        "wf-repair",
        goal="Repair and verify",
        context=context,
        obligations=[{"id": "o1", "description": "Repair", "source_quote": "Repair"}],
        steps=steps,
    )

    await mesh._execute_distributed_step(
        repair,
        "wf-repair",
        "repair",
        redis.get_step_definition("wf-repair", "repair"),
    )
    await mesh._execute_distributed_step(
        verifier,
        "wf-repair",
        "verify",
        redis.get_step_definition("wf-repair", "verify"),
    )

    repair_result = redis.get_step_output("wf-repair", "repair")["output"]
    verify_result = redis.get_step_output("wf-repair", "verify")["output"]
    assert repair_result["workspace_delta"]["modified"][0]["path"] == "service.py"
    assert verify_result["output"] == {"verified": True}
    assert await blobs.read(snapshot.entries[0].blob_path) == "def value():\n    return 'broken'\n"
    assert repair.sandbox is original_repair_sandbox
    assert verifier.sandbox is original_verify_sandbox


@pytest.mark.asyncio
async def test_mesh_rejects_fabricated_workspace_mutation_before_delta_export(tmp_path):
    blobs = LocalBlobStorage(str(tmp_path / "blobs"))
    snapshot = await BlobSnapshotStore(blobs).capture(
        SourceRef("fixture", "project", "main"),
        "commit-1",
        {"service.py": "broken\n"},
    )

    class RepairPeer(Agent):
        role = "repair"
        capabilities: ClassVar[list[str]] = ["repair"]

        async def execute_task(self, task):
            return {
                "status": "success",
                "output": {
                    "status": "applied",
                    "mutations": [{
                        "tool_receipt_id": "tool:wf-fake:repair:missing",
                        "path": "service.py",
                        "sha256": "invented",
                        "bytes": 1,
                        "executable": False,
                        "observed_at": "2026-09-17T00:00:00Z",
                    }],
                },
                "_tool_receipts": [],
            }

    redis = __import__(
        "jarviscore.testing", fromlist=["MockRedisContextStore"]
    ).MockRedisContextStore()
    mesh = Mesh(config={"p2p_enabled": False})
    mesh._redis_store = redis
    mesh._blob_storage = blobs
    peer = mesh.add(RepairPeer)
    redis.publish_workflow(
        "wf-fake",
        goal="Repair",
        context={"source_snapshot": {
            "manifest_blob_path": snapshot.manifest_blob_path,
            "storage_scope": "node",
            "materializer_node_id": mesh._node_id,
        }},
        obligations=[],
        steps=[{
            "id": "repair", "capability": "repair", "effect": "propose",
            "task": "Repair", "depends_on": [],
        }],
    )

    await mesh._execute_distributed_step(
        peer, "wf-fake", "repair",
        redis.get_step_definition("wf-fake", "repair"),
    )

    saved = redis.get_step_output("wf-fake", "repair")["output"]
    assert redis.get_step_status("wf-fake", "repair") == "failed"
    assert "Unknown tool receipt" in saved["error"]
    assert "workspace_delta" not in saved


@pytest.mark.asyncio
async def test_mesh_grounds_workspace_mutation_before_delta_export(tmp_path):
    blobs = LocalBlobStorage(str(tmp_path / "blobs"))
    snapshot = await BlobSnapshotStore(blobs).capture(
        SourceRef("fixture", "project", "main"),
        "commit-1",
        {"service.py": "broken\n"},
    )
    receipt = {
        "tool_receipt_id": "tool:wf-grounded:repair:1",
        "path": "service.py",
        "sha256": "ignored-model-value",
        "bytes": 1,
        "executable": False,
        "observed_at": "2026-09-17T00:00:00Z",
    }
    authoritative = {
        **receipt,
        "sha256": hashlib.sha256(b"fixed\n").hexdigest(),
        "bytes": 6,
    }

    class RepairPeer(Agent):
        role = "repair"
        capabilities: ClassVar[list[str]] = ["repair"]

        async def execute_task(self, task):
            (self.sandbox.workspace / "service.py").write_text("fixed\n")
            return {
                "status": "success",
                "output": {"status": "applied", "mutations": [receipt]},
                "_tool_receipts": [authoritative],
            }

    redis = __import__(
        "jarviscore.testing", fromlist=["MockRedisContextStore"]
    ).MockRedisContextStore()
    mesh = Mesh(config={"p2p_enabled": False})
    mesh._redis_store = redis
    mesh._blob_storage = blobs
    peer = mesh.add(RepairPeer)
    peer.sandbox = create_coder_sandbox(workspace_dir=tmp_path / "repair-base")
    redis.publish_workflow(
        "wf-grounded",
        goal="Repair",
        context={"source_snapshot": {
            "manifest_blob_path": snapshot.manifest_blob_path,
            "storage_scope": "node",
            "materializer_node_id": mesh._node_id,
        }},
        obligations=[],
        steps=[{
            "id": "repair", "capability": "repair", "effect": "propose",
            "task": "Repair", "depends_on": [],
        }],
    )

    await mesh._execute_distributed_step(
        peer, "wf-grounded", "repair",
        redis.get_step_definition("wf-grounded", "repair"),
    )

    saved = redis.get_step_output("wf-grounded", "repair")["output"]
    assert redis.get_step_status("wf-grounded", "repair") == "completed"
    assert saved["output"]["mutations"] == [authoritative]
    assert saved["workspace_delta"]["modified"][0]["path"] == "service.py"


@pytest.mark.asyncio
async def test_mesh_rejects_mutation_receipt_without_final_workspace_change(tmp_path):
    blobs = LocalBlobStorage(str(tmp_path / "blobs"))
    snapshot = await BlobSnapshotStore(blobs).capture(
        SourceRef("fixture", "project", "main"),
        "commit-1",
        {"service.py": "unchanged\n"},
    )
    receipt = {
        "tool_receipt_id": "tool:wf-no-change:repair:1",
        "path": "service.py",
        "sha256": hashlib.sha256(b"unchanged\n").hexdigest(),
        "bytes": len(b"unchanged\n"),
        "executable": False,
        "observed_at": "2026-09-17T00:00:00Z",
    }

    class RepairPeer(Agent):
        role = "repair"
        capabilities: ClassVar[list[str]] = ["repair"]

        async def execute_task(self, task):
            (self.sandbox.workspace / "service.py").write_text("unchanged\n")
            return {
                "status": "success",
                "output": {"status": "applied", "mutations": [receipt]},
                "_tool_receipts": [receipt],
            }

    redis = __import__(
        "jarviscore.testing", fromlist=["MockRedisContextStore"]
    ).MockRedisContextStore()
    mesh = Mesh(config={"p2p_enabled": False})
    mesh._redis_store = redis
    mesh._blob_storage = blobs
    peer = mesh.add(RepairPeer)
    peer.sandbox = create_coder_sandbox(workspace_dir=tmp_path / "repair-base")
    redis.publish_workflow(
        "wf-no-change",
        goal="Repair",
        context={"source_snapshot": {
            "manifest_blob_path": snapshot.manifest_blob_path,
            "storage_scope": "node",
            "materializer_node_id": mesh._node_id,
        }},
        obligations=[],
        steps=[{
            "id": "repair", "capability": "repair", "effect": "propose",
            "task": "Repair", "depends_on": [],
        }],
    )

    await mesh._execute_distributed_step(
        peer, "wf-no-change", "repair",
        redis.get_step_definition("wf-no-change", "repair"),
    )

    saved = redis.get_step_output("wf-no-change", "repair")["output"]
    assert redis.get_step_status("wf-no-change", "repair") == "failed"
    assert "Unknown tool receipt" in saved["error"]
    assert "workspace_delta" not in saved


@pytest.mark.asyncio
async def test_mesh_rejects_receipt_overwritten_before_final_delta(tmp_path):
    blobs = LocalBlobStorage(str(tmp_path / "blobs"))
    snapshot = await BlobSnapshotStore(blobs).capture(
        SourceRef("fixture", "project", "main"),
        "commit-1",
        {"service.py": "broken\n"},
    )
    receipt = {
        "tool_receipt_id": "tool:wf-overwritten:repair:1",
        "path": "service.py",
        "sha256": hashlib.sha256(b"first repair\n").hexdigest(),
        "bytes": len(b"first repair\n"),
        "executable": False,
        "observed_at": "2026-09-22T00:00:00Z",
    }

    class RepairPeer(Agent):
        role = "repair"
        capabilities: ClassVar[list[str]] = ["repair"]

        async def execute_task(self, task):
            path = self.sandbox.workspace / "service.py"
            path.write_text("first repair\n")
            path.write_text("overwritten\n")
            return {
                "status": "success",
                "output": {"status": "applied", "mutations": [receipt]},
                "_tool_receipts": [receipt],
            }

    redis = __import__(
        "jarviscore.testing", fromlist=["MockRedisContextStore"]
    ).MockRedisContextStore()
    mesh = Mesh(config={"p2p_enabled": False})
    mesh._redis_store = redis
    mesh._blob_storage = blobs
    peer = mesh.add(RepairPeer)
    peer.sandbox = create_coder_sandbox(workspace_dir=tmp_path / "repair-base")
    redis.publish_workflow(
        "wf-overwritten",
        goal="Repair",
        context={"source_snapshot": {
            "manifest_blob_path": snapshot.manifest_blob_path,
            "storage_scope": "node",
            "materializer_node_id": mesh._node_id,
        }},
        obligations=[],
        steps=[{
            "id": "repair", "capability": "repair", "effect": "propose",
            "task": "Repair", "depends_on": [],
        }],
    )

    await mesh._execute_distributed_step(
        peer,
        "wf-overwritten",
        "repair",
        redis.get_step_definition("wf-overwritten", "repair"),
    )

    saved = redis.get_step_output("wf-overwritten", "repair")["output"]
    assert redis.get_step_status("wf-overwritten", "repair") == "failed"
    assert "Unknown tool receipt" in saved["error"]