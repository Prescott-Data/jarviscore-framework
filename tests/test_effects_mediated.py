"""Effects other than provider calls: decided before they happen, recorded, refusable."""
import ast
import json
import pathlib

import pytest

from jarviscore.control import effects as effects_module
from jarviscore.control import policy as policy_module
from jarviscore.control.effects import Effect, EffectDenied, decide, mediated
from jarviscore.evidence import journal as journal_module
from jarviscore.evidence.journal import Journal, verify


@pytest.fixture
def control(monkeypatch, tmp_path):
    def configure(mode="strict", effects=None):
        path = tmp_path / "policy.json"
        path.write_text(json.dumps({"effects": effects or []}))
        monkeypatch.setenv("JARVISCORE_CONTROL_MODE", mode)
        monkeypatch.setenv("JARVISCORE_CONTROL_POLICY", str(path))
        monkeypatch.setenv("JARVISCORE_JOURNAL_DIR", str(tmp_path / "journal"))
        monkeypatch.setattr(policy_module, "_cached", None)
        monkeypatch.setattr(journal_module, "_journal", None)
        return str(tmp_path / "journal")
    return configure


def events(root, run="wf/s1"):
    with open(Journal(root).run_path(run), encoding="utf-8") as handle:
        return [json.loads(line) for line in handle]


def decisions(root, run="wf/s1"):
    return [e["data"] for e in events(root, run) if e["kind"] == "policy.decision"]


# ── The decision ────────────────────────────────────────────────────────────


def test_model_code_outside_a_confined_sandbox_is_refused_unless_the_deployment_allows_it(control):
    control("strict")
    unconfined = Effect("code", "run", origin="model", attributes={"confined": False})

    assert decide(unconfined).rule == "unconfined-execution" and not decide(unconfined).allowed
    assert decide(Effect("code", "run", origin="registry", attributes={"confined": False})).allowed is False
    assert decide(Effect("code", "run", origin="shipped", attributes={"confined": False})).allowed
    assert decide(Effect("code", "run", origin="model", attributes={"confined": True})).allowed
    assert decide(Effect("process", "run", origin="runtime", attributes={"confined": False})).allowed

    control("strict", [{"name": "dev-laptop", "decision": "allow", "match": {"sink": "code"}}])
    lifted = decide(unconfined)
    assert lifted.allowed and lifted.rule == "deployment:dev-laptop"


def test_a_deployment_rule_refuses_any_effect_by_sink_action_target_or_agent(control):
    control("strict", [
        {"name": "no-broadcast", "decision": "deny", "match": {"sink": "peer", "action": "broadcast"}},
        {"name": "no-exports", "decision": "deny", "match": {"sink": "artifact", "target": "*/exports/*"}},
    ])

    assert decide(Effect("peer", "broadcast", target="*")).rule == "deployment:no-broadcast"
    assert decide(Effect("peer", "send", target="analyst")).allowed
    assert not decide(Effect("artifact", "publish", target="wf/exports/ledger.csv")).allowed
    assert decide(Effect("artifact", "publish", target="wf/report.md")).allowed


def test_an_effect_rule_that_cannot_be_read_refuses_every_effect(control):
    control("strict", [{"name": "typo", "decision": "deny", "match": {"sinkk": "peer"}}])

    assert not decide(Effect("memory", "write")).allowed


# ── The record ──────────────────────────────────────────────────────────────


def test_an_effect_is_decided_then_attempted_then_its_outcome_recorded(control):
    root = control("strict")

    with mediated(Effect("memory", "write", target="fact", attributes={"bytes": 3}),
                  workflow_id="wf", step_id="s1") as effect:
        effect.done(ok=True)

    assert [e["kind"] for e in events(root)] == ["policy.decision", "effect.attempt", "effect.outcome"]
    decision = events(root)[0]["data"]
    assert decision["sink"] == "memory" and decision["outcome"] == "allow"
    assert events(root)[2]["data"]["ok"] is True
    check = verify(root)
    assert check.ok and check.effects == 1


def test_a_refused_effect_does_not_happen_and_the_refusal_is_on_record(control):
    root = control("strict", [{"name": "no-memory", "decision": "deny", "match": {"sink": "memory"}}])
    happened = []

    with pytest.raises(EffectDenied):
        with mediated(Effect("memory", "write"), workflow_id="wf", step_id="s1"):
            happened.append(True)

    assert not happened
    assert [e["kind"] for e in events(root)] == ["policy.decision"]
    assert verify(root).ok and verify(root).refused == 1


def test_report_mode_records_what_strict_would_refuse_and_lets_it_happen(control):
    root = control("report", [{"name": "no-memory", "decision": "deny", "match": {"sink": "memory"}}])

    with mediated(Effect("memory", "write"), workflow_id="wf", step_id="s1"):
        pass

    assert decisions(root)[0]["outcome"] == "deny" and decisions(root)[0]["enforced"] is False


def test_effects_inside_an_agent_run_belong_to_its_step(control):
    root = control("report")
    token = effects_module.scope.set({"workflow_id": "wf", "step_id": "s1", "agent": "writer-1"})
    try:
        with mediated(Effect("peer", "send", target="analyst")):
            pass
    finally:
        effects_module.scope.reset(token)

    assert decisions(root)[0]["agent"] == "writer-1"


# ── At the sinks ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_model_code_on_an_unconfined_host_is_not_run_in_strict_mode(control, tmp_path):
    from jarviscore.execution.coder_sandbox import create_coder_sandbox

    root = control("strict")
    marker = tmp_path / "ran"
    sandbox = create_coder_sandbox(workspace_dir=tmp_path / "ws", timeout=30, allow_unsafe_local_execution=True)
    sandbox.__class__ = type("Unconfined", (sandbox.__class__,), {"confined": property(lambda self: False)})

    result = await sandbox.execute(f"open({str(marker)!r}, 'w').write('x')\nresult = 1",
                                   context={"workflow_id": "wf", "step_id": "s1"})

    assert result["status"] == "failure" and result["error_type"] == "PolicyDenied"
    assert not marker.exists()
    assert decisions(root)[0]["rule"] == "unconfined-execution"


@pytest.mark.asyncio
async def test_code_that_runs_is_recorded_with_its_digest_and_whether_it_was_confined(control, tmp_path):
    from jarviscore.execution.coder_sandbox import create_coder_sandbox

    root = control("report")
    sandbox = create_coder_sandbox(workspace_dir=tmp_path / "ws", timeout=30, allow_unsafe_local_execution=True)
    code = "result = 2 + 2"

    result = await sandbox.execute(code, context={"workflow_id": "wf", "step_id": "s1"})

    assert result["status"] == "success"
    [decision] = decisions(root)
    assert decision["sink"] == "code" and decision["origin"] == "model"
    assert decision["attributes"]["confined"] is sandbox.confined
    import hashlib
    assert decision["attributes"]["digest"] == hashlib.sha256(code.encode()).hexdigest()
    assert events(root)[-1]["data"]["ok"] is True


def test_a_command_on_the_host_is_refused_in_strict_mode_and_recorded_in_report_mode(control, tmp_path):
    from jarviscore.execution.coder_sandbox import BashExecutor, BashPermissionError

    bash = BashExecutor(tmp_path, allow_unsafe_local_execution=True)
    control("strict")
    with pytest.raises(BashPermissionError, match="outside a confined sandbox"):
        bash("ls")

    root = control("report")
    token = effects_module.scope.set({"workflow_id": "wf", "step_id": "s1"})
    try:
        assert bash("ls")["success"]
    finally:
        effects_module.scope.reset(token)
    assert decisions(root)[0]["sink"] == "process" and decisions(root)[0]["target"] == "ls"


def test_commands_inside_the_sandbox_child_are_its_own_scratch_work(control, tmp_path, monkeypatch):
    from jarviscore.execution.coder_sandbox import BashExecutor

    root = control("strict")
    monkeypatch.setenv("JARVISCORE_SANDBOX_CHILD", "1")

    assert BashExecutor(tmp_path, allow_unsafe_local_execution=True)("ls")["success"]
    assert not pathlib.Path(root).exists()


@pytest.mark.asyncio
async def test_a_published_artifact_is_recorded_and_a_refused_one_stays_unpublished(control, tmp_path):
    from jarviscore.execution.coder_sandbox import create_coder_sandbox
    from jarviscore.storage import LocalBlobStorage

    blobs = LocalBlobStorage(str(tmp_path / "blobs"))
    root = control("strict", [
        {"name": "dev", "decision": "allow", "match": {"sink": "code"}},
        {"name": "no-csv", "decision": "deny", "match": {"sink": "artifact", "target": "*.csv"}},
    ])
    sandbox = create_coder_sandbox(workspace_dir=tmp_path / "ws", timeout=30, allow_unsafe_local_execution=True,
                                   blob_storage=blobs)
    code = ("import pathlib\n"
            "pathlib.Path(output_dir, 'report.md').write_text('# ok')\n"
            "pathlib.Path(output_dir, 'ledger.csv').write_text('a,b')\n"
            "result = 1")

    result = await sandbox.execute(code, context={"workflow_id": "wf", "step_id": "s1"})

    artifacts = {a["name"]: a for a in result["artifacts"]}
    assert artifacts["report.md"]["key"] and await blobs.read(artifacts["report.md"]["key"]) == "# ok"
    assert artifacts["ledger.csv"]["key"] is None and "Not published" in artifacts["ledger.csv"]["error"]
    published = [d for d in decisions(root) if d["sink"] == "artifact"]
    assert {d["outcome"] for d in published} == {"allow", "deny"}
    assert verify(root).ok


@pytest.mark.asyncio
async def test_a_memory_write_is_recorded_and_a_refused_one_is_not_kept(control, tmp_path):
    from jarviscore.memory.local import LocalMemory
    from jarviscore.memory.unified import UnifiedMemory

    root = control("strict")
    memory = UnifiedMemory("wf", "s1", "writer-1", local_memory=LocalMemory("writer", base_dir=str(tmp_path / "mem")))

    assert await memory.remember("The client prefers PDF reports.") is True
    assert decisions(root)[0]["sink"] == "memory" and decisions(root)[0]["agent"] == "writer-1"

    control("strict", [{"name": "no-memory", "decision": "deny", "match": {"sink": "memory"}}])
    assert await memory.remember("Remember this forever.") is False


@pytest.mark.asyncio
async def test_a_workspace_export_is_recorded_with_what_changed(control, tmp_path):
    from jarviscore.execution.workspace import BlobSnapshotStore, SandboxBinding, SourceRef
    from jarviscore.storage import LocalBlobStorage

    root = control("strict")
    store = BlobSnapshotStore(LocalBlobStorage(str(tmp_path / "blobs")))
    snapshot = await store.capture(SourceRef(provider="archive", locator="f", revision="main"), "c1",
                                   {"README.md": "before\n", "old.py": "x\n"})
    token = effects_module.scope.set({"workflow_id": "wf", "step_id": "s1"})
    try:
        async with SandboxBinding(store, snapshot, temporary_root=tmp_path / "b", cleanup=True) as binding:
            (binding.workspace / "README.md").write_text("after\n")
            (binding.workspace / "old.py").unlink()
            delta = await binding.export_delta("workflows/wf/deltas/s1")
    finally:
        effects_module.scope.reset(token)

    assert [e.path for e in delta.modified] == ["README.md"] and delta.deleted == ("old.py",)
    [decision] = decisions(root)
    assert decision["sink"] == "workspace" and decision["attributes"]["changed"] == 1
    assert decision["attributes"]["deleted"] == 1


@pytest.mark.asyncio
async def test_a_message_to_a_peer_is_recorded_and_a_refused_one_is_not_sent(control):
    from unittest.mock import AsyncMock, MagicMock

    from jarviscore.kernel.defaults.communicator import CommunicatorSubAgent

    agent = CommunicatorSubAgent.__new__(CommunicatorSubAgent)
    agent.peers = MagicMock(notify=AsyncMock(return_value=True))
    agent.mailbox = None
    agent._current_state = None
    root = control("strict")
    token = effects_module.scope.set({"workflow_id": "wf", "step_id": "s1"})
    try:
        sent = await agent._tool_send_to_peer(peer_role="analyst", message="numbers attached")
        control("strict", [{"name": "quiet", "decision": "deny", "match": {"sink": "peer"}}])
        refused = await agent._tool_send_to_peer(peer_role="analyst", message="again")
    finally:
        effects_module.scope.reset(token)

    assert sent["status"] == "sent" and refused["semantic_error"] == "POLICY_REFUSED"
    assert agent.peers.notify.await_count == 1
    assert decisions(root)[0]["target"] == "analyst"


# ── Nothing reaches the world around the decision point ─────────────────────

#: Every raw call in the package that runs a process, stores a blob, keeps a memory,
#: messages peers or writes a file from an agent's tool, with where it is decided on.
#: A new one fails this test until it is mediated or classified here.
INVENTORY = {
    ("execution/coder_sandbox.py", "BashExecutor._spawn", "subprocess.Popen"): "mediated by BashExecutor._run",
    ("execution/coder_sandbox.py", "BashExecutor._terminate_process_tree", "subprocess.run"): "runtime: stops a process it started",
    ("execution/coder_sandbox.py", "CoderSandbox._run_child", "asyncio.create_subprocess_exec"): "mediated by CoderSandbox._execute_subprocess",
    ("execution/coder_sandbox.py", "CoderSandbox._terminate_process_tree", "asyncio.create_subprocess_exec"): "runtime: stops a process it started",
    ("execution/coder_sandbox.py", "CoderSandbox._serve_child_rpc", "*._mesh_proxy.delegate"): "mediated in place (peer delegate)",
    ("execution/coder_sandbox.py", "CoderSandbox._collect_artifacts", "*.blob_storage.save"): "mediated in place (artifact publish)",
    ("execution/workspace.py", "SandboxBinding._export", "*.blob_storage.save"): "mediated by SandboxBinding.export_delta",
    ("execution/workspace.py", "BlobSnapshotStore.capture_entries", "*.blob_storage.save"): "runtime: snapshot of a source the caller named",
    ("execution/workspace.py", "BlobSnapshotStore.compose", "*.blob_storage.save"): "runtime: snapshot composition from recorded deltas",
    ("execution/code_registry.py", "FunctionRegistry._upload_registry_path", "*.blob_storage.save"): "runtime: registry replication",
    ("room/room.py", "Room._store", "*.blob_storage.save"): "runtime: room content a person accepted or proposed through Room",
    ("memory/unified.py", "UnifiedMemory._remember", "local.remember"): "mediated by UnifiedMemory.remember",
    ("kernel/subagent.py", "BaseSubAgent._tool_remember", "memory.remember"): "mediated by UnifiedMemory.remember",
    ("kernel/kernel.py", "Kernel.retain_browser_procedure", "memory.remember"): "mediated by UnifiedMemory.remember",
    ("orchestration/engine.py", "WorkflowEngine._execute_step_on", "*.broadcaster.broadcast_step_result"): "mediated in place (peer broadcast)",
    ("kernel/defaults/researcher.py", "ResearcherSubAgent._tool_grep_codebase", "subprocess.run"): "mediated in place (process, runtime)",
    ("kernel/defaults/communicator.py", "CommunicatorSubAgent._tool_write_file", "open:w"): "mediated in place (workspace write)",
    ("core/mesh.py", "Mesh.run_task", "self.delegate"): "application call: the caller's own request",
    ("core/mesh.py", "Mesh._execute_distributed_step", "*._redis_store.finish_claimed_step"): "mediated in place (output deliver; an exhausted epoch's failure is the runtime's)",
    ("orchestration/engine.py", "WorkflowEngine._record_result", "*.redis_store.save_step_output"): "mediated by WorkflowEngine._execute_step_on",
    ("context/memory.py", "RedisMemoryAccessor.put", "*._redis.save_step_output"): "application code: a CustomAgent's own shared memory",
    ("kernel/tracing.py", "TraceManager.log_event", "open:w"): "runtime: the run's own trace file",
    ("kernel/tracing.py", "TraceManager.log_step_complete", "open:w"): "runtime: the run's own trace file",
    ("execution/isolation.py", "confinement_unavailable_reason", "subprocess.run"): "runtime: probes the host's confinement",
    ("cli/memory.py", "cmd_init", "subprocess.run"): "operator command line",
    ("cli/nexus.py", "_compose", "subprocess.run"): "operator command line",
    ("cli/nexus.py", "cmd_status", "subprocess.run"): "operator command line",
}
_PROCESS = {"subprocess.Popen", "subprocess.run", "subprocess.call", "subprocess.check_call",
            "subprocess.check_output", "asyncio.create_subprocess_exec", "asyncio.create_subprocess_shell",
            "os.system", "os.popen", "os.execv", "os.execvp", "os.spawnv"}


def _sink_calls():
    package = pathlib.Path(__file__).resolve().parents[1] / "jarviscore"
    for path in sorted(package.rglob("*.py")):
        relative = path.relative_to(package).as_posix()
        if relative.startswith(("data/", "atoms/")) or "/atoms/" in relative:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        stack = []

        class Visitor(ast.NodeVisitor):
            found = []

            def visit_FunctionDef(self, node):
                stack.append(node.name)
                self.generic_visit(node)
                stack.pop()

            visit_AsyncFunctionDef = visit_ClassDef = visit_FunctionDef

            def visit_Call(self, node):
                func, name = node.func, None
                if isinstance(func, ast.Attribute):
                    if isinstance(func.value, ast.Name):
                        name = f"{func.value.id}.{func.attr}"
                    elif isinstance(func.value, ast.Attribute):
                        name = f"*.{func.value.attr}.{func.attr}"
                elif isinstance(func, ast.Name) and func.id == "open" and relative.startswith("kernel/"):
                    modes = [a.value for a in node.args[1:2] if isinstance(a, ast.Constant)]
                    modes += [k.value.value for k in node.keywords if k.arg == "mode" and isinstance(k.value, ast.Constant)]
                    if any(isinstance(m, str) and set(m) & set("wax+") for m in modes) or (
                        node.args[1:2] and not isinstance(node.args[1], ast.Constant)
                    ):
                        name = "open:w"
                if name and (
                    name in _PROCESS or name.endswith("blob_storage.save") or name.endswith(".remember")
                    or "broadcast_step_result" in name or name.endswith(".delegate") or name == "open:w"
                    or name.endswith(".finish_claimed_step") or name.endswith(".save_step_output")
                ):
                    self.found.append((relative, ".".join(stack), name))
                self.generic_visit(node)

        visitor = Visitor()
        visitor.found = []
        visitor.visit(tree)
        yield from visitor.found


def test_every_effect_sink_in_the_package_is_decided_on_or_classified():
    found = set(_sink_calls())

    unclassified = sorted(found - set(INVENTORY))
    assert not unclassified, f"Effect sinks with no decision point: {unclassified}"
    gone = sorted(set(INVENTORY) - found)
    assert not gone, f"Inventory entries that no longer exist: {gone}"


def test_every_mediated_sink_really_is_mediated_where_the_inventory_says():
    package = pathlib.Path(__file__).resolve().parents[1] / "jarviscore"
    for (module, function, _), reason in INVENTORY.items():
        if not reason.startswith("mediated"):
            continue
        holder = function if "in place" in reason else reason.split(" by ", 1)[1]
        cls, _, name = holder.rpartition(".")
        tree = ast.parse((package / module).read_text(encoding="utf-8")) if cls else None
        source = (package / module).read_text(encoding="utf-8")
        if holder.startswith("UnifiedMemory."):
            source = (package / "memory/unified.py").read_text(encoding="utf-8")
            tree = ast.parse(source)
        body = next(
            ast.get_source_segment(source, item)
            for node in ast.walk(tree) if isinstance(node, ast.ClassDef) and node.name == cls
            for item in node.body
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name == name
        )
        assert "mediated(" in body or "_mediated_code_run(" in body, f"{holder} does not decide on {module}:{function}"
