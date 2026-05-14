import pytest

from jarviscore.orchestration.workflow_builder import WorkflowBuilder


class FakeMesh:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    async def run_task(self, *, agent_role, task, context):
        self.calls.append({"agent_role": agent_role, "task": task, "context": context})
        if self.responses:
            return self.responses.pop(0)
        return {"status": "success", "output": "ok"}


@pytest.mark.asyncio
async def test_workflow_builder_preserves_agent_failure_status():
    workflow = (
        WorkflowBuilder()
        .step("first", "worker", "do risky work")
        .build(title="failure visibility")
    )
    mesh = FakeMesh([
        {"status": "failure", "error": "agent failed visibly"},
    ])

    results = await workflow.execute(mesh)

    assert results == [
        {
            "step_id": "first",
            "agent": "worker",
            "status": "failure",
            "output": None,
            "error": "agent failed visibly",
            "elapsed_ms": results[0]["elapsed_ms"],
        }
    ]


@pytest.mark.asyncio
async def test_workflow_builder_failed_dependency_does_not_unblock_downstream():
    workflow = (
        WorkflowBuilder()
        .step("first", "worker", "fail")
        .step("second", "worker", "use {first.result}", depends_on=["first"])
        .build(title="dependency visibility")
    )
    mesh = FakeMesh([
        {"status": "yield", "summary": "needs human"},
        {"status": "success", "output": "should not run"},
    ])

    results = await workflow.execute(mesh)

    assert len(results) == 1
    assert results[0]["status"] == "yield"
    assert results[0]["error"] == "needs human"
    assert len(mesh.calls) == 1
