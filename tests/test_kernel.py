"""
Tests for Kernel — OODA-loop supervisor.

Tests task classification, subagent dispatch, model routing,
multi-dispatch retry, HITL escalation, and cost aggregation.
"""

import asyncio
import json
import threading
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import BaseModel
from jarviscore.kernel import Kernel
from jarviscore.kernel.hitl import AdaptiveHITLPolicy
from jarviscore.execution.decisions import DecisionResult
from jarviscore.kernel.state import (
    ArtifactReferenceError,
    KernelState,
    ToolReceiptError,
    hydrate_artifact_references,
    hydrate_receipt_evidence,
)
from jarviscore.context.context_manager import BudgetConfig, ContextManager
from jarviscore.orchestration.budget import (
    WorkflowBudgetExceeded,
    current_workflow_budget,
    workflow_budget_scope,
)
from jarviscore.testing import MockLLMClient, MockSandboxExecutor


def _llm_response(content, tokens=None, cost=0.001):
    return {
        "content": content,
        "provider": "mock",
        "tokens": tokens or {"input": 10, "output": 20, "total": 30},
        "cost_usd": cost,
        "model": "mock-model",
    }


def _router_response(role, confidence=0.9, reason="test route"):
    return _llm_response(
        f'{{"role": "{role}", "confidence": {confidence}, '
        f'"reason": "{reason}", "evidence_required": false}}',
        tokens={"input": 5, "output": 5, "total": 10},
        cost=0.0,
    )


def _coder_write_response(code='result = {"ok": True}'):
    return _llm_response(
        "THOUGHT: Write executable code\n"
        "TOOL: write_code\n"
        f"PARAMS: {json.dumps({'code': code})}"
    )


@pytest.fixture
def mock_llm():
    return MockLLMClient()


@pytest.fixture
def mock_sandbox():
    return MockSandboxExecutor()


@pytest.fixture
def kernel(mock_llm, mock_sandbox):
    return Kernel(
        llm_client=mock_llm,
        sandbox=mock_sandbox,
        config={
            "coding_model": "dromos-gpt-4.1",
            "task_model": "gpt-4o",
            "kernel_max_turns": 10,
        },
    )


@pytest.mark.asyncio
async def test_sync_tool_execution_does_not_block_event_loop(kernel):
    subagent = kernel._create_subagent("researcher", "test_researcher")
    loop_thread_id = threading.get_ident()
    ticker_ran = asyncio.Event()

    def blocking_tool():
        time.sleep(0.05)
        budget = current_workflow_budget()
        return {
            "status": "success",
            "thread_id": threading.get_ident(),
            "workflow_id": budget.workflow_id if budget else None,
            "epoch_id": budget.epoch_id if budget else None,
        }

    async def tick():
        await asyncio.sleep(0.01)
        ticker_ran.set()

    subagent.register_tool("blocking_tool", blocking_tool, "Block briefly")
    ticker = asyncio.create_task(tick())

    with workflow_budget_scope(object(), "wf-1", epoch_id="step:claim-1"):
        result = await subagent._execute_tool("blocking_tool", {})

    assert ticker_ran.is_set()
    assert result["thread_id"] != loop_thread_id
    assert result["workflow_id"] == "wf-1"
    assert result["epoch_id"] == "step:claim-1"
    await ticker


@pytest.mark.asyncio
async def test_async_tool_execution_stays_on_event_loop(kernel):
    subagent = kernel._create_subagent("researcher", "test_researcher")
    loop_thread_id = threading.get_ident()

    async def async_tool():
        await asyncio.sleep(0)
        return {"status": "success", "thread_id": threading.get_ident()}

    subagent.register_tool("async_tool", async_tool, "Yield once")

    result = await subagent._execute_tool("async_tool", {})

    assert result["thread_id"] == loop_thread_id


def test_command_receipt_overrides_model_authored_execution_facts():
    state = KernelState(
        workflow_id="wf-1",
        step_id="reproduce",
        agent_id="coder-1",
        task="Reproduce the defect",
    )
    receipt = state.add_tool_result(
        "workspace_run",
        {"command": "cargo test --test focused", "cwd": "."},
        {
            "success": True,
            "stdout": "1 passed",
            "stderr": "",
            "returncode": 0,
        },
        duration_ms=1250,
    )

    hydrated = state.hydrate_tool_receipts({
        "observation": {
            "tool_receipt_id": receipt.receipt_id,
            "command": ["cargo", "test", "--test", "focused"],
            "exit_code": 101,
            "stdout": "invented failure",
            "stderr": "invented panic",
            "duration_ms": 9999,
            "observed_at": "2000-01-01T00:00:00Z",
        },
    }, require_command_receipts=True)

    assert hydrated["observation"] == {
        "tool_receipt_id": receipt.receipt_id,
        "command": ["cargo", "test", "--test", "focused"],
        "exit_code": 0,
        "stdout": "1 passed",
        "stderr": "",
        "duration_ms": 1250,
        "observed_at": receipt.command_observation().model_dump(mode="json")["observed_at"],
    }


@pytest.mark.parametrize(
    "observation",
    [
        {
            "command": ["cargo", "test"],
            "exit_code": 1,
            "stdout": "",
            "stderr": "failed",
            "duration_ms": 1,
            "observed_at": "2000-01-01T00:00:00Z",
        },
        {
            "tool_receipt_id": "tool:wf-1:reproduce:missing",
            "command": ["cargo", "test"],
            "exit_code": 1,
            "stdout": "",
            "stderr": "failed",
            "duration_ms": 1,
            "observed_at": "2000-01-01T00:00:00Z",
        },
    ],
)
def test_command_receipt_validation_fails_closed(observation):
    state = KernelState(
        workflow_id="wf-1",
        step_id="reproduce",
        agent_id="coder-1",
        task="Reproduce the defect",
    )

    with pytest.raises(ToolReceiptError):
        state.hydrate_tool_receipts(
            {"observation": observation},
            require_command_receipts=True,
        )


def test_coder_done_gate_binds_authoritative_command_receipt(kernel):
    coder = kernel._create_subagent("coder", "test-coder")
    state = KernelState(
        workflow_id="wf-1",
        step_id="reproduce",
        agent_id="test-coder",
        task="Reproduce the defect",
        context={
            "execution_contract": {
                "required_tool_groups": [["workspace_run"]],
            },
        },
    )
    receipt = state.add_tool_result(
        "workspace_run",
        {"command": "cargo test --test focused", "cwd": "."},
        {"success": True, "stdout": "1 passed", "stderr": "", "returncode": 0},
        duration_ms=10,
    )
    parsed = {
        "result": {
            "observation": {
                "tool_receipt_id": receipt.receipt_id,
                "command": ["cargo", "test", "--test", "focused"],
                "exit_code": 101,
                "stdout": "invented failure",
                "stderr": "invented panic",
                "duration_ms": 9999,
                "observed_at": "2000-01-01T00:00:00Z",
            },
        },
    }

    allowed, _ = coder._ground_completion(state, parsed)

    assert allowed is True
    assert parsed["result"]["observation"]["exit_code"] == 0
    assert parsed["result"]["observation"]["stdout"] == "1 passed"


def test_coder_done_gate_rejects_unreceipted_command_observation(kernel):
    coder = kernel._create_subagent("coder", "test-coder")
    state = KernelState(
        workflow_id="wf-1",
        step_id="reproduce",
        agent_id="test-coder",
        task="Reproduce the defect",
        context={
            "execution_contract": {
                "required_tool_groups": [["workspace_run"]],
            },
        },
    )
    state.add_tool_result(
        "workspace_run",
        {"command": "cargo test", "cwd": "."},
        {"success": True, "stdout": "passed", "stderr": "", "returncode": 0},
    )
    parsed = {
        "result": {
            "observation": {
                "command": ["cargo", "test"],
                "exit_code": 1,
                "stdout": "",
                "stderr": "failed",
                "duration_ms": 1,
                "observed_at": "2000-01-01T00:00:00Z",
            },
        },
    }

    allowed, evidence = coder._ground_completion(state, parsed)

    assert allowed is False
    assert evidence.check == "tool_receipt_grounding"


def test_command_receipt_is_visible_after_checkpoint_resume():
    state = KernelState(
        workflow_id="wf-1",
        step_id="reproduce",
        agent_id="coder-1",
        task="Reproduce the defect",
    )
    receipt = state.add_tool_result(
        "workspace_run",
        {"command": "cargo test", "cwd": "."},
        {"success": True, "stdout": "passed", "stderr": "", "returncode": 0},
    )
    restored = KernelState.model_validate_json(state.model_dump_json())

    context = ContextManager().build_context(restored)

    assert f"Receipt: {receipt.receipt_id}" in context


def test_command_receipt_survives_context_recovery_pressure():
    state = KernelState(
        workflow_id="wf-1",
        step_id="reproduce",
        agent_id="coder-1",
        task="x " * 1_000,
    )
    receipt = state.add_tool_result(
        "workspace_run",
        {"command": "cargo test", "cwd": "."},
        {"success": True, "stdout": "y " * 1_000, "stderr": "", "returncode": 0},
    )

    context = ContextManager(BudgetConfig(
        total_tokens=300,
        output_reserve=50,
        system_reserve=50,
    )).build_context(state)

    assert "Tier: **recovery**" in context
    assert f"`{receipt.receipt_id}`: workspace_run" in context
    assert "y y y" not in context


@pytest.mark.asyncio
async def test_coder_hydrates_command_receipt_before_returning_output(kernel, mock_llm):
    coder = kernel._create_subagent("coder", "test-coder")
    coder.register_tool(
        "workspace_run",
        lambda command, cwd=".": {
            "success": True,
            "stdout": "1 passed",
            "stderr": "",
            "returncode": 0,
        },
        "Run a workspace command",
    )
    mock_llm.responses = [
        _llm_response(
            "THOUGHT: Execute the check\n"
            "TOOL: workspace_run\n"
            'PARAMS: {"command": "cargo test --test focused", "cwd": "."}'
        ),
        _llm_response(
            "THOUGHT: Report the observed command\n"
            "DONE: Check complete\n"
            "RESULT: " + json.dumps({
                "observation": {
                    "tool_receipt_id": "tool:wf-1:reproduce:1",
                    "command": ["cargo", "test", "--test", "focused"],
                    "exit_code": 101,
                    "stdout": "invented failure",
                    "stderr": "invented panic",
                    "duration_ms": 9999,
                    "observed_at": "2000-01-01T00:00:00Z",
                },
            })
        ),
    ]

    output = await coder.run(
        "Run the focused test",
        context={
            "workflow_id": "wf-1",
            "step_id": "reproduce",
            "execution_contract": {
                "required_tool_groups": [["workspace_run"]],
            },
        },
        max_turns=2,
    )

    assert output.status == "success"
    assert output.payload["observation"]["exit_code"] == 0
    assert output.payload["observation"]["stdout"] == "1 passed"
    assert "tool:wf-1:reproduce:1" in mock_llm.calls[1]["messages"][-2]["content"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("tool_result", "expected_status"),
    [
        (
            {"success": False, "stdout": "", "stderr": "failed", "returncode": 1},
            "error",
        ),
        (
            {
                "success": False,
                "stdout": "",
                "stderr": "timed out",
                "returncode": -1,
                "status": "timeout",
            },
            "timeout",
        ),
    ],
)
async def test_unsuccessful_tool_result_has_error_without_losing_timeout_marker(
    kernel, tool_result, expected_status
):
    coder = kernel._create_subagent("coder", "test-coder")
    coder.register_tool("workspace_run", lambda: dict(tool_result), "Run command")

    result = await coder._execute_tool("workspace_run", {})

    assert result["status"] == expected_status
    assert result["error"] == tool_result["stderr"]


def test_downstream_output_can_cite_grounded_dependency_receipt():
    observation = {
        "tool_receipt_id": "tool:wf-1:reproduce:1",
        "command": ["cargo", "test"],
        "exit_code": 1,
        "stdout": "",
        "stderr": "failed",
        "duration_ms": 10,
        "observed_at": "2026-09-17T00:00:00Z",
    }
    state = KernelState(
        workflow_id="wf-1",
        step_id="synthesize",
        agent_id="strategist",
        task="Synthesize evidence",
        context={
            "previous_step_results": {
                "reproduce": {"output": {"vulnerable_run": observation}},
            },
        },
    )

    hydrated = state.hydrate_tool_receipts(
        {"finding": {"reproduction": {"vulnerable_run": observation}}},
        require_command_receipts=True,
    )

    assert hydrated["finding"]["reproduction"]["vulnerable_run"] == observation


def test_receipt_catalog_contains_only_evidence_cited_by_output():
    state = KernelState(
        workflow_id="wf-1",
        step_id="analyse",
        agent_id="coder-1",
        task="Analyse",
    )
    cited = state.add_tool_result(
        "workspace_run",
        {"command": "cargo test"},
        {"success": True, "stdout": "passed", "stderr": "", "returncode": 0},
    )
    state.add_tool_result(
        "workspace_run",
        {"command": "echo secret"},
        {"success": True, "stdout": "not cited", "stderr": "", "returncode": 0},
    )

    evidence = state.receipt_evidence({
        "run": {"tool_receipt_id": cited.receipt_id},
    })

    assert [item["tool_receipt_id"] for item in evidence] == [cited.receipt_id]
    assert "not cited" not in json.dumps(evidence)


def test_standalone_receipt_scopes_do_not_collide():
    first = KernelState(agent_id="coder", task="first", started_at=1.0)
    second = KernelState(agent_id="coder", task="second", started_at=2.0)

    first_receipt = first.add_tool_result("workspace_read", {}, {"status": "success"})
    second_receipt = second.add_tool_result("workspace_read", {}, {"status": "success"})

    assert first_receipt.receipt_id != second_receipt.receipt_id


def test_workspace_mutation_receipt_overrides_model_authored_file_facts():
    state = KernelState(
        workflow_id="wf-1",
        step_id="repair",
        agent_id="coder-1",
        task="Repair the defect",
    )
    receipt = state.add_tool_result(
        "workspace_write",
        {"path": "src/store.rs", "content": "fixed", "executable": False},
        {
            "status": "success",
            "path": "src/store.rs",
            "bytes": 5,
            "sha256": "0123456789abcdef",
            "executable": False,
        },
    )

    hydrated = state.hydrate_tool_receipts({
        "mutation": {
            "tool_receipt_id": receipt.receipt_id,
            "path": "invented.py",
            "sha256": "invented",
            "bytes": 999,
            "executable": True,
        },
    })

    assert hydrated["mutation"] == {
        "tool_receipt_id": receipt.receipt_id,
        "path": "src/store.rs",
        "sha256": "0123456789abcdef",
        "bytes": 5,
        "executable": False,
        "observed_at": receipt.workspace_mutation().model_dump(mode="json")["observed_at"],
    }

    cited = state.hydrate_tool_receipts({
        "mutation": {"tool_receipt_id": receipt.receipt_id},
    })
    assert cited["mutation"] == hydrated["mutation"]


def test_workspace_edit_receipt_is_authoritative_mutation_evidence():
    state = KernelState(
        workflow_id="wf-1",
        step_id="repair",
        agent_id="coder-1",
        task="Repair the defect",
    )
    receipt = state.add_tool_result(
        "workspace_edit",
        {
            "path": "src/store.rs",
            "start_line": 3,
            "end_line": 3,
            "replacement": "fixed",
            "expected_sha256": "before",
        },
        {
            "status": "success",
            "path": "src/store.rs",
            "bytes": 5,
            "sha256": "after",
            "executable": False,
        },
    )

    mutation = receipt.workspace_mutation()

    assert mutation.path == "src/store.rs"
    assert mutation.sha256 == "after"


def test_workspace_mutation_receipt_rejects_non_write_receipt():
    state = KernelState(
        workflow_id="wf-1",
        step_id="repair",
        agent_id="coder-1",
        task="Repair the defect",
    )
    receipt = state.add_tool_result(
        "workspace_read",
        {"path": "src/store.rs"},
        {"status": "success", "path": "src/store.rs", "content": "old"},
    )

    with pytest.raises(ToolReceiptError, match="not workspace mutation evidence"):
        state.hydrate_tool_receipts({
            "mutation": {
                "tool_receipt_id": receipt.receipt_id,
                "path": "src/store.rs",
                "sha256": "invented",
                "bytes": 1,
                "executable": False,
                "observed_at": "2000-01-01T00:00:00Z",
            },
        })


def test_workspace_mutation_claim_requires_receipt_at_completion_gate():
    state = KernelState(
        workflow_id="wf-1",
        step_id="repair",
        agent_id="coder-1",
        task="Repair the defect",
    )

    with pytest.raises(ToolReceiptError, match="Workspace mutations require"):
        state.hydrate_tool_receipts(
            {
                "mutation": {
                    "path": "src/store.rs",
                    "sha256": "invented",
                    "bytes": 5,
                    "executable": False,
                }
            },
            require_command_receipts=True,
        )


def test_post_normalization_hydrator_rejects_fabricated_mutation():
    with pytest.raises(ToolReceiptError, match="Unknown tool receipt"):
        hydrate_receipt_evidence(
            {
                "status": "applied",
                "mutations": [{
                    "tool_receipt_id": "tool:wf-1:repair:missing",
                    "path": "src/store.rs",
                    "sha256": "invented",
                    "bytes": 1,
                    "executable": False,
                    "observed_at": "2000-01-01T00:00:00Z",
                }],
            },
            receipt_evidence=[],
        )


def test_post_normalization_hydrator_binds_workspace_mutation():
    evidence = {
        "tool_receipt_id": "tool:wf-1:repair:1",
        "path": "src/store.rs",
        "sha256": "0123456789abcdef",
        "bytes": 5,
        "executable": False,
        "observed_at": "2026-09-17T00:00:00Z",
    }

    hydrated = hydrate_receipt_evidence(
        {
            "status": "applied",
            "mutations": [{**evidence, "path": "invented.py"}],
        },
        receipt_evidence=[evidence],
        workflow_id="wf-1",
    )

    assert hydrated["mutations"] == [evidence]

    cited = hydrate_receipt_evidence(
        {"mutations": [{"tool_receipt_id": evidence["tool_receipt_id"]}]},
        receipt_evidence=[evidence],
        workflow_id="wf-1",
    )
    assert cited["mutations"] == [evidence]


def test_post_normalization_hydrator_rejects_cross_workflow_receipt():
    evidence = {
        "tool_receipt_id": "tool:other-workflow:repair:1",
        "path": "src/store.rs",
        "sha256": "0123456789abcdef",
        "bytes": 5,
        "executable": False,
        "observed_at": "2026-09-17T00:00:00Z",
    }

    with pytest.raises(ToolReceiptError, match="another workflow"):
        hydrate_receipt_evidence(
            {"mutations": [evidence]},
            receipt_evidence=[evidence],
            workflow_id="wf-1",
        )


def test_artifact_reference_hydrator_preserves_exact_dependency_evidence():
    mutation = {
        "tool_receipt_id": "tool:wf-1:repair:1",
        "path": "src/store.rs",
        "sha256": "0123456789abcdef",
        "bytes": 5,
        "executable": False,
        "observed_at": "2026-09-17T00:00:00Z",
    }
    dependencies = {
        "repair": {"status": "applied", "mutations": [mutation]},
        "verify": {"status": "verified", "regression_runs": []},
    }

    hydrated = hydrate_artifact_references(
        {
            "findings": [{
                "patch": {"artifact_ref": {"step_id": "repair"}},
                "verification": {"artifact_ref": {"step_id": "verify"}},
            }]
        },
        previous_step_results=dependencies,
        required_reference_paths=(
            ("findings", "*", "patch"),
            ("findings", "*", "verification"),
        ),
    )

    assert hydrated["findings"][0]["patch"] == dependencies["repair"]
    assert hydrated["findings"][0]["patch"]["mutations"] == [mutation]
    assert hydrated["findings"][0]["verification"] == dependencies["verify"]


@pytest.mark.asyncio
async def test_coder_hydrates_artifact_reference_before_schema_validation(kernel):
    class Output(BaseModel):
        patch: dict[str, str]

    coder = kernel._create_subagent("coder", "test-coder")
    coder.sandbox = SimpleNamespace(execute=AsyncMock(return_value={
        "status": "success",
        "output": {
            "data": {"patch": {"artifact_ref": {"step_id": "repair"}}}
        },
    }))
    coder._run_context = {
        "output_schema": Output,
        "artifact_reference_paths": (("patch",),),
        "previous_step_results": {"repair": {"status": "applied"}},
    }

    result = await coder._tool_execute_code(code="result = {}")

    assert result["status"] == "success"
    assert result["output"]["data"]["patch"] == {"status": "applied"}


def test_artifact_reference_hydrator_rejects_copied_required_artifact():
    with pytest.raises(ArtifactReferenceError, match="must use an exact artifact_ref"):
        hydrate_artifact_references(
            {"findings": [{"patch": {"status": "applied"}}]},
            previous_step_results={"repair": {"status": "applied"}},
            required_reference_paths=(("findings", "*", "patch"),),
        )


def test_artifact_reference_hydrator_rejects_non_dependency_step():
    with pytest.raises(ArtifactReferenceError, match="unavailable direct dependency"):
        hydrate_artifact_references(
            {"patch": {"artifact_ref": {"step_id": "unrelated"}}},
            previous_step_results={"repair": {"status": "applied"}},
        )


def test_artifact_reference_hydrator_rejects_malformed_reference():
    with pytest.raises(ArtifactReferenceError, match="Invalid artifact reference"):
        hydrate_artifact_references(
            {"patch": {"artifact_ref": {"path": ["patch"]}}},
            previous_step_results={"repair": {"status": "applied"}},
        )


# ── Task Classification ──────────────────────────────────────────────

class TestTaskClassification:

    @pytest.mark.asyncio
    async def test_typesafe_router_selects_role_and_preserves_probability_evidence(
        self, mock_llm, mock_sandbox
    ):
        decision_client = SimpleNamespace(
            evaluate=AsyncMock(
                return_value=DecisionResult(
                    model="jev-1.13",
                    answers={
                        "kernel_role": {
                            "type": "choice",
                            "choice": "researcher",
                            "probabilities": {
                                "browser": 0.03,
                                "coder": 0.06,
                                "communicator": 0.01,
                                "researcher": 0.9,
                            },
                            "confidence": 0.86,
                        }
                    },
                    usage={"input_tokens": 30, "output_tokens": 8},
                    cost_usd=0.00000126,
                    request_id="request-router",
                )
            )
        )
        kernel = Kernel(
            llm_client=mock_llm,
            sandbox=mock_sandbox,
            decision_client=decision_client,
            config={"kernel_router_provider": "typesafe"},
        )

        decision = await kernel._route_task("Find current evidence")

        assert decision.role == "researcher"
        assert decision.provider == "typesafe"
        assert decision.probabilities["researcher"] == 0.9
        assert decision.request_id == "request-router"
        assert decision.model == "jev-1.13"
        assert decision.usage == {"input_tokens": 30, "output_tokens": 8}
        assert decision.cost_usd == 0.00000126
        assert mock_llm.calls == []

    @pytest.mark.asyncio
    async def test_typesafe_router_budget_exhaustion_requests_a_new_epoch(
        self, mock_llm, mock_sandbox
    ):
        decision_client = SimpleNamespace(
            evaluate=AsyncMock(
                side_effect=WorkflowBudgetExceeded(
                    "The routing decision does not fit in this epoch."
                )
            )
        )
        kernel = Kernel(
            llm_client=mock_llm,
            sandbox=mock_sandbox,
            decision_client=decision_client,
            config={"kernel_router_provider": "typesafe"},
        )

        output = await kernel.execute(task="Route this task", max_dispatches=1)

        assert output.status == "epoch_exhausted"
        assert output.metadata["typed_outcome"] == "CONTINUE_NEW_EXECUTION_EPOCH"
        assert output.metadata["checkpointed"] is False
        assert output.metadata["dispatches"] == []
        assert "routing decision" in output.metadata["budget_error"]
        assert mock_llm.calls == []

    def test_unknown_kernel_router_provider_is_rejected(self, mock_llm, mock_sandbox):
        with pytest.raises(ValueError, match="kernel_router_provider"):
            Kernel(
                llm_client=mock_llm,
                sandbox=mock_sandbox,
                config={"kernel_router_provider": "unknown"},
            )

    def test_typesafe_router_requires_a_configured_client(self, mock_llm, mock_sandbox):
        with pytest.raises(ValueError, match="TYPESAFE_API_KEY"):
            Kernel(
                llm_client=mock_llm,
                sandbox=mock_sandbox,
                config={"kernel_router_provider": "typesafe"},
            )

    @pytest.mark.asyncio
    async def test_explicit_role_bypasses_configured_typesafe_router(
        self, mock_llm, mock_sandbox
    ):
        decision_client = SimpleNamespace(evaluate=AsyncMock())
        kernel = Kernel(
            llm_client=mock_llm,
            sandbox=mock_sandbox,
            decision_client=decision_client,
            config={"kernel_router_provider": "typesafe"},
        )

        decision = await kernel._route_task(
            "Run the planner-assigned research step",
            agent_default_role="researcher",
        )

        assert decision.role == "researcher"
        decision_client.evaluate.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_configured_jev_client_is_available_as_a_subagent_tool(
        self, mock_llm, mock_sandbox
    ):
        decision_client = SimpleNamespace(
            evaluate=AsyncMock(
                return_value=DecisionResult(
                    model="jev-1.13",
                    answers={"route": {"type": "choice", "choice": "researcher"}},
                    usage={"input_tokens": 20, "output_tokens": 4},
                    cost_usd=0.00000084,
                    request_id="request-tool",
                )
            )
        )
        kernel = Kernel(
            llm_client=mock_llm,
            sandbox=mock_sandbox,
            decision_client=decision_client,
        )
        subagent = kernel._create_subagent("researcher", "test-researcher")

        result = await subagent._execute_tool(
            "evaluate_decisions",
            {
                "state": {"task": "Find evidence"},
                "questions": {
                    "route": {
                        "type": "choice",
                        "instructions": "Which role should handle this?",
                        "criteria": {"coder": None, "researcher": None},
                    }
                },
            },
        )

        assert result["status"] == "success"
        assert result["decision"]["answers"]["route"]["choice"] == "researcher"
        assert result["decision"]["request_id"] == "request-tool"
        decision_client.evaluate.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_jev_tool_budget_exhaustion_requests_a_new_execution_epoch(
        self, mock_llm, mock_sandbox
    ):
        decision_client = SimpleNamespace(
            evaluate=AsyncMock(
                side_effect=WorkflowBudgetExceeded(
                    "The decision call does not fit in this epoch."
                )
            )
        )
        kernel = Kernel(
            llm_client=mock_llm,
            sandbox=mock_sandbox,
            decision_client=decision_client,
        )
        mock_llm.responses = [
            _llm_response(
                "THOUGHT: Classify the task\n"
                "TOOL: evaluate_decisions\n"
                "PARAMS: "
                + json.dumps(
                    {
                        "state": {"task": "Find evidence"},
                        "questions": {
                            "route": {
                                "type": "choice",
                                "instructions": "Which role should handle this?",
                                "criteria": {"coder": None, "researcher": None},
                            }
                        },
                    }
                )
            )
        ]

        output = await kernel.execute(
            task="Find evidence",
            agent_default_role="communicator",
            max_dispatches=1,
        )

        assert output.status == "epoch_exhausted"
        assert output.metadata["typed_outcome"] == "CONTINUE_NEW_EXECUTION_EPOCH"
        assert output.metadata["dispatches"][0]["status"] == "epoch_exhausted"

    @pytest.mark.asyncio
    async def test_explicit_role_routes_without_llm(self, kernel, mock_llm):
        decision = await kernel._route_task(
            "Run the exact planner-assigned step",
            agent_default_role="researcher",
        )
        assert decision.role == "researcher"
        assert decision.confidence == 1.0
        assert mock_llm.calls == []

    @pytest.mark.asyncio
    async def test_structured_router_selects_role(self, kernel, mock_llm):
        mock_llm.responses = [_router_response("communicator", reason="request needs coordination")]
        decision = await kernel._route_task(
            "Secure read-only access or PDFs for all bank accounts and confirm completeness.",
            agent_default_role="coder",
            use_default_role_as_fallback=True,
        )
        assert decision.role == "communicator"
        assert decision.reason == "request needs coordination"

    @pytest.mark.asyncio
    async def test_router_rejects_invalid_role(self, kernel, mock_llm):
        mock_llm.responses = [_llm_response('{"role": "hacker", "confidence": 0.99, "reason": "bad"}')]
        decision = await kernel.execute(task="Route impossible task", max_dispatches=1)
        assert decision.status == "failure"
        assert decision.metadata["routing_error"]

    @pytest.mark.asyncio
    async def test_custom_explicit_role_uses_registered_lease_profile(self, mock_llm, mock_sandbox):
        from jarviscore.kernel.defaults.communicator import CommunicatorSubAgent

        class DatabaseKernel(Kernel):
            def _create_subagent(self, role: str, agent_id: str):
                if role == "database":
                    return CommunicatorSubAgent(agent_id=agent_id, llm_client=self.llm_client)
                return super()._create_subagent(role, agent_id)

        kernel = DatabaseKernel(
            llm_client=mock_llm,
            sandbox=mock_sandbox,
            config={
                "kernel_role_profiles": {
                    "database": {
                        "thinking_budget": 40_000,
                        "action_budget": 20_000,
                        "max_total_tokens": 60_000,
                        "wall_clock_ms": 120_000,
                        "emergency_turn_fuse": 8,
                        "model_tier": "task",
                        "complexity": "standard",
                    },
                },
                "kernel_role_catalog": {
                    "database": "Read-only SQL/database analysis role.",
                },
            },
        )
        mock_llm.responses = [
            _llm_response('THOUGHT: Done\nDONE: Query summarized\nRESULT: {"rows": 3}')
        ]
        output = await kernel.execute(
            task="Summarize customer table row count",
            agent_default_role="database",
            max_dispatches=1,
        )
        assert output.status == "success"
        assert output.metadata["dispatches"][0]["role"] == "database"
        assert "COMMUNICATION SPECIALIST" in mock_llm.calls[0]["messages"][0]["content"]

    def test_workflow_budget_caps_existing_role_lease(self, kernel):
        lease = kernel._lease_for_role(
            "coder",
            {"max_tokens": 60_000, "max_seconds": 45},
        )

        assert lease.max_total_tokens == 60_000
        assert lease.thinking_budget + lease.action_budget == 60_000
        assert lease.wall_clock_ms == 45_000


# ── Model Routing ─────────────────────────────────────────────────────

class TestModelRouting:

    def test_coding_tier(self, kernel):
        assert kernel._get_model_for_tier("coding") == "dromos-gpt-4.1"

    def test_task_tier(self, kernel):
        assert kernel._get_model_for_tier("task") == "gpt-4o"

    def test_unknown_tier(self, kernel):
        assert kernel._get_model_for_tier("unknown") is None


# ── Subagent Creation ─────────────────────────────────────────────────

class TestSubagentCreation:

    def test_create_coder(self, kernel):
        from jarviscore.kernel.defaults.coder import CoderSubAgent
        agent = kernel._create_subagent("coder", "test_coder")
        assert isinstance(agent, CoderSubAgent)

    def test_create_researcher(self, kernel):
        from jarviscore.kernel.defaults.researcher import ResearcherSubAgent
        agent = kernel._create_subagent("researcher", "test_researcher")
        assert isinstance(agent, ResearcherSubAgent)

    def test_create_communicator(self, kernel):
        from jarviscore.kernel.defaults.communicator import CommunicatorSubAgent
        agent = kernel._create_subagent("communicator", "test_comm")
        assert isinstance(agent, CommunicatorSubAgent)

    def test_unknown_role_raises(self, kernel):
        with pytest.raises(ValueError, match="Unknown subagent role"):
            kernel._create_subagent("hacker", "test")

    def test_mesh_capabilities_reach_every_subagent_including_cached(self, kernel):
        class FakePeerTool:
            tool_names = ["ask_peer", "broadcast_update", "list_peers"]

            @property
            def schema(self):
                return [
                    {"name": name, "description": name, "input_schema": {"type": "object"}}
                    for name in self.tool_names
                ]

            async def execute(self, name, args):
                return {"name": name, "args": args}

        class FakePeers:
            def as_tool(self):
                return FakePeerTool()

        cached = kernel._create_subagent("researcher", "test_researcher")
        kernel._subagent_cache["test:researcher"] = cached
        mailbox = object()

        kernel.attach_mesh_capabilities(peers=FakePeers(), mailbox=mailbox)

        for role in ("coder", "researcher", "communicator", "browser"):
            subagent = cached if role == "researcher" else kernel._create_subagent(role, f"test_{role}")
            assert {"ask_peer", "broadcast_update", "list_peers"} <= set(subagent.tool_names)
        assert kernel.mailbox is mailbox

    @pytest.mark.asyncio
    async def test_ask_peer_carries_shared_context_without_caller_authority(self, kernel):
        class FakePeerTool:
            tool_names = ["ask_peer"]

            def __init__(self):
                self.calls = []

            @property
            def schema(self):
                return [{"name": "ask_peer", "description": "ask", "input_schema": {}}]

            async def execute(self, name, args, context=None):
                self.calls.append((name, args, context))
                return {"status": "success"}

        class FakePeers:
            def __init__(self, tool):
                self.tool = tool

            def as_tool(self):
                return self.tool

        peer_tool = FakePeerTool()
        kernel.attach_mesh_capabilities(peers=FakePeers(peer_tool))
        subagent = kernel._create_subagent("coder", "calendar-agent")
        subagent._current_state = SimpleNamespace(
            workflow_id="wf-1",
            step_id="calendar",
            context={
                "objective": "Coordinate the full customer workflow",
                "workflow_plan": {"steps": [{"id": "calendar"}]},
                "previous_step_results": {"crm": {"email": "known@example.com"}},
                "system": "google_calendar",
                "systems": ["google_calendar"],
                "effect": "write",
                "capability": "calendar_scheduling",
                "_nexus_connection_id": "secret-handle",
            },
        )

        await subagent._tools["ask_peer"].func(
            role="revenue_operations", question="Resolve the lead identity"
        )

        _, _, context = peer_tool.calls[0]
        assert context["workflow_id"] == "wf-1"
        assert context["objective"] == "Coordinate the full customer workflow"
        assert context["previous_step_results"]["crm"]["email"] == "known@example.com"
        assert context["peer_requester_step_id"] == "calendar"
        assert not ({"system", "systems", "effect", "capability", "step_id"} & set(context))
        assert all(not key.startswith("_") for key in context)

    @pytest.mark.asyncio
    async def test_every_subagent_can_inspect_its_workflow_and_read_step_output(
        self, kernel
    ):
        class Store:
            def get_workflow_definition(self, workflow_id):
                assert workflow_id == "wf-1"
                return {
                    "workflow_id": workflow_id,
                    "goal": "Research then analyse",
                    "obligations": [{"id": "o1"}],
                    "steps": [{"id": "research"}, {"id": "analyse"}],
                }

            def get_step_definition(self, workflow_id, step_id):
                return {"id": step_id, "status": "completed", "completed_by": "peer-1"}

            def get_step_output(self, workflow_id, step_id):
                return {"output": {"evidence": ["source-1"]}}

        kernel.redis_store = Store()
        subagent = kernel._create_subagent("researcher", "test_researcher")
        subagent._current_state = SimpleNamespace(workflow_id="wf-1")

        workflow = await subagent._execute_tool("inspect_workflow", {})
        step = await subagent._execute_tool(
            "read_workflow_step", {"step_id": "research"}
        )

        assert workflow["goal"] == "Research then analyse"
        assert workflow["steps"][0]["completed_by"] == "peer-1"
        assert step["output"] == {"evidence": ["source-1"]}


# ── Execute: Success Path ─────────────────────────────────────────────

class TestKernelExecuteSuccess:

    @pytest.mark.asyncio
    async def test_simple_coding_task(self, kernel, mock_llm, mock_sandbox):
        mock_sandbox.responses = [{"status": "success", "output": {"factorial": 3628800}}]
        mock_llm.responses = [
            _router_response("coder"),
            _coder_write_response('import math\nresult = {"factorial": math.factorial(10)}'),
            _llm_response('THOUGHT: Read it\nDONE: 10! is 3628800\nRESULT: {"factorial": 3628800}'),
        ]
        output = await kernel.execute(task="Calculate factorial of 10")
        assert output.status == "success"
        assert output.payload == {"factorial": 3628800}
        assert output.metadata["dispatches"][0]["role"] == "coder"

    @pytest.mark.asyncio
    async def test_research_task(self, kernel, mock_llm, monkeypatch):
        monkeypatch.setenv("RESEARCH_STRICT_DONE_VALIDATION", "false")
        mock_llm.responses = [
            _router_response("researcher"),
            _llm_response(
                "THOUGHT: Research complete\n"
                "DONE: Found the answer\n"
                'RESULT: {"answer": "FastAPI", "summary": "FastAPI is the best Python web framework"}'
            )
        ]
        output = await kernel.execute(task="Research the best Python web framework")
        assert output.status == "success"
        assert output.metadata["dispatches"][0]["role"] == "researcher"

    @pytest.mark.asyncio
    async def test_communication_task(self, kernel, mock_llm):
        mock_llm.responses = [
            _router_response("communicator"),
            _llm_response(
                "THOUGHT: Drafted\n"
                "DONE: Message drafted\n"
                'RESULT: {"message": "All systems go"}'
            )
        ]
        output = await kernel.execute(task="Draft a status report")
        assert output.status == "success"
        assert output.metadata["dispatches"][0]["role"] == "communicator"

    @pytest.mark.asyncio
    async def test_context_passed_to_subagent(self, kernel, mock_llm):
        mock_llm.responses = [
            _router_response("communicator"),
            _llm_response("THOUGHT: Done\nDONE: Used context\nRESULT: {\"used_context\": true}")
        ]
        output = await kernel.execute(
            task="Process data",
            context={"data": [1, 2, 3]},
            system_prompt="You are a data processor.",
        )
        assert output.status == "success"
        # Context data reaches the LLM in the user message; the agent's identity
        # leads the system message (issue #91).
        all_content = " ".join(
            str(m.get("content", "")) for m in mock_llm.calls[1]["messages"]
        )
        assert "data" in all_content
        assert "Process data" in all_content
        assert mock_llm.calls[1]["messages"][0]["content"].startswith("You are a data processor.")

    @pytest.mark.asyncio
    async def test_agent_identity_leads_the_system_message(self, kernel, mock_llm):
        """issue #91 — a sub-agent prompt is an execution harness, not a persona."""
        mock_llm.responses = [
            _router_response("communicator"),
            _llm_response("THOUGHT: Answered\nDONE: Answered\nRESULT: {\"who\": \"Acme\"}"),
        ]
        await kernel.execute(
            task="Who are you and what company do you work for?",
            system_prompt="You are the VP of Marketing at Acme.",
        )
        system = mock_llm.calls[1]["messages"][0]["content"]
        assert system.startswith("You are the VP of Marketing at Acme.")
        assert system.index("Acme") < system.index("EXECUTION HARNESS")
        # The harness still ships in full: role prompt, tools and protocol.
        assert "COMMUNICATION SPECIALIST" in system.upper()
        assert "Available tools:" in system and "Protocol:" in system
        assert "one action per turn, not one action per task" in system
        assert "continue calling tools until the task" in system
        assert "Never use DONE merely because additional tool calls are needed" in system

    @pytest.mark.asyncio
    async def test_callers_passing_no_identity_are_unchanged(self, kernel, mock_llm):
        mock_llm.responses = [
            _router_response("communicator"),
            _llm_response("THOUGHT: Drafted\nDONE: Drafted\nRESULT: {}"),
        ]
        await kernel.execute(task="Draft a status report")
        system = mock_llm.calls[1]["messages"][0]["content"]
        assert "EXECUTION HARNESS" not in system
        assert "Available tools:" in system


# ── Execute: Failure + Retry ──────────────────────────────────────────

class TestKernelExecuteFailure:

    @pytest.mark.asyncio
    async def test_all_dispatches_fail(self, kernel, mock_llm):
        """Protocol-invalid responses must not become successful work."""
        mock_llm.responses = [
            _router_response("coder"),
            _llm_response("This response has neither TOOL nor DONE."),
            _llm_response("Still not following the execution protocol."),
            _llm_response("No valid action or completion marker."),
        ]
        output = await kernel.execute(
            task="Do something complex",
            max_dispatches=2,
            agent_default_role="coder",
        )
        assert output.status == "failure"
        assert output.metadata["typed_outcome"] == "FAIL_ALL_DISPATCHES_EXHAUSTED"

    @pytest.mark.asyncio
    async def test_failure_then_success(self, kernel, mock_llm):
        """Kernel succeeds when coder produces executable proof of work."""
        mock_llm.responses = [
            _router_response("coder"),
            _coder_write_response('result = {"ok": True}'),
        ]
        output = await kernel.execute(task="Calculate pi", max_dispatches=2)
        assert output.status == "success"
        assert len(output.metadata["dispatches"]) == 1  # Succeeded first try

    @pytest.mark.asyncio
    async def test_cost_aggregation(self, kernel, mock_llm):
        """Token and cost metadata is aggregated across dispatches."""
        mock_llm.responses = [
            _router_response("coder"),
            _llm_response(
                "THOUGHT: Done\nDONE: Result\nRESULT: {\"v\": 1}",
                tokens={"input": 100, "output": 200, "total": 300},
                cost=0.05,
            )
        ]
        output = await kernel.execute(task="Compute something")
        # Aggregation across dispatches: at least the known contributions land.
        # Exact totals grew when issue #139 stopped killing agents after a
        # rejected DONE, so the run legitimately spends more turns now.
        assert output.metadata["tokens"]["total"] >= 300
        assert output.metadata["cost_usd"] >= 0.05

    @pytest.mark.asyncio
    async def test_elapsed_time_tracked(self, kernel, mock_llm):
        mock_llm.responses = [
            _router_response("coder"),
            _llm_response("THOUGHT: Done\nDONE: Quick result\nRESULT: {\"ok\": true}")
        ]
        output = await kernel.execute(task="Fast task")
        assert "elapsed_ms" in output.metadata
        assert output.metadata["elapsed_ms"] >= 0


# ── HITL Escalation ───────────────────────────────────────────────────

class TestKernelHITL:

    @pytest.mark.asyncio
    async def test_yield_passthrough(self, mock_llm, mock_sandbox):
        """If subagent returns yield, kernel passes it through."""
        # We can't easily make a subagent return yield via LLM responses
        # since BaseSubAgent only returns success/failure. Test the kernel's
        # response to a yield output by testing the HITL escalation path instead.
        pass

    @pytest.mark.asyncio
    async def test_hitl_escalation_on_failure(self, mock_llm, mock_sandbox):
        """Kernel escalates to HITL on repeated failure if policy is enabled."""
        policy = AdaptiveHITLPolicy(
            enabled=True,
            reason_codes=["execution_failure"],
            max_confidence=0.5,
            min_risk_score=0.3,
        )
        kernel = Kernel(
            llm_client=mock_llm,
            sandbox=mock_sandbox,
            hitl_policy=policy,
            config={"kernel_max_turns": 1},
        )
        # Empty content violates the subagent protocol and must not become success.
        mock_llm.responses = [
            _router_response("coder"),
            {"content": "", "provider": "mock", "tokens": {"input": 0, "output": 0, "total": 0}, "cost_usd": 0, "model": "m"},
        ]
        output = await kernel.execute(task="Risky operation", max_dispatches=1)
        assert output.status in {"failure", "yield"}


# ── Dispatch Records ──────────────────────────────────────────────────

def _patch_vault(monkeypatch, *, connected=(), unconsented=()):
    """A vault double that separates holding an app from holding a credential."""
    from jarviscore.nexus.store import ConnectionState

    class Vault:
        def get(self, name):
            if name in connected or name in unconsented:
                return {"auth_type": "oauth2"}
            return None

        def connection_state(self, name):
            if name in connected:
                return ConnectionState.CONNECTED
            if name in unconsented:
                return ConnectionState.REGISTERED
            return ConnectionState.ABSENT

        def needs_consent(self, name):
            return name in unconsented

    monkeypatch.setattr("jarviscore.nexus.store.get_store", lambda: Vault())


class TestDeclaredSystemCredentials:
    """issue #151 — a declared provider with no credentials is a human decision."""

    @pytest.mark.asyncio
    async def test_missing_credentials_yield_before_spending_a_dispatch(
        self, kernel, mock_llm, monkeypatch
    ):
        _patch_vault(monkeypatch)
        mock_llm.responses = [_router_response("coder"), _coder_write_response()]
        output = await kernel.execute(task="Read our CRM contacts", context={"system": "hubspot"})

        assert output.status == "yield"
        assert output.metadata["typed_outcome"] == "YIELD_AUTH_REQUIRED"
        assert output.metadata["escalation_reason"] == "auth_required"
        assert output.metadata["system"] == "hubspot"
        assert output.metadata["yield_pending"] is True
        assert "not connected here" in output.summary
        # Routing costs one call; the dispatch that could not authenticate never ran.
        assert len(mock_llm.calls) == 1
        assert output.metadata["dispatches"] == []

    @pytest.mark.asyncio
    async def test_registered_provider_still_dispatches(
        self, kernel, mock_llm, mock_sandbox, monkeypatch
    ):
        _patch_vault(monkeypatch, connected={"hubspot"})
        mock_sandbox.responses = [{"status": "success", "output": {"contacts": 2}}]
        mock_llm.responses = [
            _router_response("coder"),
            _coder_write_response('result = {"contacts": 2}'),
            _llm_response('THOUGHT: Read it\nDONE: Two contacts\nRESULT: {"contacts": 2}'),
        ]
        output = await kernel.execute(task="Read our CRM contacts", context={"system": "hubspot"})
        assert output.status == "success"
        assert output.payload == {"contacts": 2}

    @pytest.mark.asyncio
    async def test_provider_mutation_uses_coder_without_preselecting_an_atom(
        self, kernel, mock_llm, monkeypatch
    ):
        _patch_vault(monkeypatch, connected={"hubspot"})

        decision = await kernel._route_task(
            "Establish the lead's deal and current stage",
            {"system": "hubspot", "effect": "write"},
            agent_default_role="researcher",
            use_default_role_as_fallback=True,
        )

        assert decision.role == "coder"
        assert decision.reason == "Provider mutation requires the credentialed Coder harness."

    @pytest.mark.asyncio
    async def test_execution_contract_role_precedes_classifier_and_profile_default(
        self, kernel, mock_llm
    ):
        decision = await kernel._route_task(
            "Inspect and execute repository tests",
            {"execution_contract": {"kernel_role": "coder"}},
            agent_default_role="researcher",
            use_default_role_as_fallback=True,
        )

        assert decision.role == "coder"
        assert decision.reason == "Explicit planner/profile role."
        assert mock_llm.calls == []

    @pytest.mark.asyncio
    async def test_provider_authority_overrides_planner_browser_hint(self, kernel):
        decision = await kernel._route_task(
            "Search the connected Drive account",
            context={
                "system": "google_drive",
                "systems": ["google_drive"],
                "effect": "read",
                "_agent_default_kernel_role": "browser",
            },
            agent_default_role="researcher",
            use_default_role_as_fallback=True,
        )

        assert decision.role == "coder"
        assert decision.reason == (
            "Connected-system work requires the credentialed Coder harness."
        )

    @pytest.mark.asyncio
    async def test_multi_provider_read_capability_uses_credentialed_coder(
        self, kernel, mock_llm
    ):
        decision = await kernel._route_task(
            "Resolve the contact from connected systems",
            {"systems": ["gmail", "hubspot"], "effect": "read"},
            agent_default_role="researcher",
            use_default_role_as_fallback=True,
        )

        assert decision.role == "coder"
        assert decision.reason == "Connected-system work requires the credentialed Coder harness."
        assert mock_llm.calls == []

    @pytest.mark.asyncio
    async def test_unconsented_app_without_channel_reports_auth_required(
        self, kernel, mock_llm, monkeypatch
    ):
        """Telling someone to register what they already registered is a dead end."""
        _patch_vault(monkeypatch, unconsented={"slack"})
        mock_llm.responses = [_router_response("coder"), _coder_write_response()]
        output = await kernel.execute(
            task="Post the update to Slack", context={"system": "slack"}
        )

        assert output.status == "yield"
        assert output.metadata["typed_outcome"] == "YIELD_AUTH_REQUIRED"
        assert output.metadata["escalation_reason"] == "auth_required"
        assert "not connected here" in output.summary
        assert output.metadata["dispatches"] == []

    @pytest.mark.asyncio
    async def test_a_task_naming_no_system_is_unaffected(self, kernel, mock_llm, mock_sandbox):
        mock_sandbox.responses = [{"status": "success", "output": {"v": 1}}]
        mock_llm.responses = [
            _router_response("coder"),
            _coder_write_response('result = {"v": 1}'),
        ]
        output = await kernel.execute(task="Add two numbers")
        assert output.status == "success"


class TestDispatchRecords:

    @pytest.mark.asyncio
    async def test_dispatch_records_in_metadata(self, kernel, mock_llm):
        mock_llm.responses = [
            _router_response("coder"),
            _coder_write_response('result = {"ok": True}')
        ]
        output = await kernel.execute(task="Build a widget")
        dispatches = output.metadata["dispatches"]
        assert len(dispatches) == 1
        assert dispatches[0]["role"] == "coder"
        assert dispatches[0]["status"] == "success"
        assert dispatches[0]["dispatch"] == 1

    @pytest.mark.asyncio
    async def test_model_in_dispatch_record(self, kernel, mock_llm):
        mock_llm.responses = [
            _router_response("researcher"),
            _llm_response("THOUGHT: Done\nDONE: Researched")
        ]
        output = await kernel.execute(task="Research Python typing")
        dispatches = output.metadata["dispatches"]
        # Researcher uses task tier
        assert dispatches[0]["model"] == "gpt-4o"
