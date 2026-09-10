import json

import pytest

from jarviscore.planning.mesh_planner import MeshPlanError, MeshPlanner
from jarviscore.testing import MockLLMClient


def responses(*, obligations=None, steps=None, audit=None):
    obligations = obligations or [{
            "id": "o1",
            "description": "Find evidence",
            "source_quote": "Find evidence",
        }]
    steps = steps or [{
            "step_id": "research",
            "capability": "research",
        "effect": "read",
            "systems": [],
            "task": "Find evidence and cite it",
            "success_criterion": "At least one source is cited",
            "expected_findings": ["evidence"],
            "depends_on": [],
            "covers": ["o1"],
        }]
    return [
        {"content": json.dumps({"obligations": obligations})},
        {"content": json.dumps({"steps": steps})},
        {"content": json.dumps(audit or {"complete": True, "missing": []})},
    ]


@pytest.mark.asyncio
async def test_mesh_planner_builds_capability_dag_with_complete_obligation_coverage():
    llm = MockLLMClient(responses=responses())
    planner = MeshPlanner(llm, capabilities={"research": "Research evidence"})

    plan = await planner.plan("Find evidence")

    assert plan.goal == "Find evidence"
    assert plan.steps[0].capability == "research"
    assert plan.steps[0].effect == "read"
    assert plan.steps[0].covers == ["o1"]
    assert "agent" not in plan.steps[0].to_dict()
    obligation_prompt = llm.calls[0]["messages"][0]["content"]
    dag_prompt = llm.calls[1]["messages"][0]["content"]
    audit_prompt = llm.calls[2]["messages"][0]["content"]
    assert "LIVE CAPABILITY CATALOG" not in obligation_prompt
    assert "research" in dag_prompt
    assert "agent ID" in dag_prompt
    assert "inspect-or-create" in dag_prompt
    assert "one provider-owned outcome" in dag_prompt
    assert "information required to execute each effectful outcome" in dag_prompt
    assert "naming an entity does not supply its provider identifiers" in dag_prompt
    assert "source goal or an ancestor step" in audit_prompt
    assert all("json" in prompt for prompt in (obligation_prompt, dag_prompt, audit_prompt))


@pytest.mark.asyncio
async def test_mesh_planner_adds_configured_user_response_as_the_terminal_step():
    llm = MockLLMClient(responses=responses())
    planner = MeshPlanner(
        llm,
        capabilities={
            "research": "Research evidence",
            "action_briefing": "Produce the user-facing decision",
        },
        response_capability="action_briefing",
    )

    plan = await planner.plan("Find evidence")

    assert [step.step_id for step in plan.steps] == ["research", "final_response"]
    response_step = plan.steps[-1]
    assert response_step.capability == "action_briefing"
    assert response_step.depends_on == ["research"]
    assert response_step.covers == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("steps", "error"),
    [
        ([{
            "step_id": "research", "capability": "unknown", "effect": "read",
            "task": "Find evidence",
            "success_criterion": "Found", "expected_findings": [], "depends_on": [],
            "covers": ["o1"],
        }], "unknown capability"),
        ([{
            "step_id": "research", "capability": "research", "effect": "read",
            "task": "Find evidence",
            "success_criterion": "Found", "expected_findings": [], "depends_on": [],
            "covers": [],
        }], "uncovered obligation"),
        ([
            {"step_id": "a", "capability": "research", "effect": "read", "task": "A", "success_criterion": "A", "expected_findings": [], "depends_on": ["b"], "covers": ["o1"]},
            {"step_id": "b", "capability": "research", "effect": "read", "task": "B", "success_criterion": "B", "expected_findings": [], "depends_on": ["a"], "covers": []},
        ], "cycle"),
    ],
)
async def test_mesh_planner_rejects_unexecutable_or_lossy_dags(steps, error):
    llm = MockLLMClient(responses=responses(steps=steps))
    planner = MeshPlanner(llm, capabilities={"research": "Research evidence"})

    with pytest.raises(MeshPlanError, match=error):
        await planner.plan("Find evidence")


@pytest.mark.asyncio
async def test_mesh_planner_requires_each_obligation_quote_to_exist_in_source_goal():
    llm = MockLLMClient(responses=responses(obligations=[{
        "id": "o1", "description": "Invented requirement", "source_quote": "send an email",
    }]))
    planner = MeshPlanner(llm, capabilities={"research": "Research evidence"})

    with pytest.raises(MeshPlanError, match="source_quote"):
        await planner.plan("Find evidence")


@pytest.mark.asyncio
async def test_mesh_planner_repairs_invalid_obligation_quotes_before_dag_compilation():
    invalid = {
        "content": json.dumps({"obligations": [{
            "id": "o1", "description": "Find evidence",
            "source_quote": "Find the evidence",
        }]})
    }
    repaired = {
        "content": json.dumps({"obligations": [{
            "id": "o1", "description": "Find evidence",
            "source_quote": "Find evidence",
        }]})
    }
    valid = responses()
    llm = MockLLMClient(responses=[invalid, repaired, valid[1], valid[2]])
    planner = MeshPlanner(llm, capabilities={"research": "Research evidence"})

    plan = await planner.plan("Find evidence")

    assert plan.obligations[0].source_quote == "Find evidence"
    repair_prompt = llm.calls[1]["messages"][0]["content"]
    assert "Find the evidence" in repair_prompt
    assert "not present in the source goal" in repair_prompt
    assert "Do not add, remove, merge or split obligations" in repair_prompt


@pytest.mark.asyncio
async def test_mesh_planner_rejects_a_dag_when_independent_audit_finds_an_omission():
    llm = MockLLMClient(responses=responses(audit={
        "complete": False,
        "missing": [{"description": "Preserve approval boundary", "source_quote": "Find evidence"}],
    }))
    planner = MeshPlanner(llm, capabilities={"research": "Research evidence"})

    with pytest.raises(MeshPlanError, match="coverage audit"):
        await planner.plan("Find evidence")


@pytest.mark.asyncio
async def test_mesh_planner_repairs_one_failed_coverage_audit_before_publication():
    initial_steps = responses()[1]
    audit_failure = {
        "content": json.dumps({
            "complete": False,
            "missing": [{
                "description": "The evidence path is incomplete",
                "source_quote": "Find evidence",
            }],
        }),
    }
    repaired_steps = responses(steps=[{
        "step_id": "research",
        "capability": "research",
        "effect": "read",
        "systems": [],
        "task": "Find and cite the requested evidence",
        "success_criterion": "The requested evidence is cited",
        "expected_findings": ["cited evidence"],
        "depends_on": [],
        "covers": ["o1"],
    }])[1]
    llm = MockLLMClient(responses=[
        responses()[0], initial_steps, audit_failure, repaired_steps,
        {"content": json.dumps({"complete": True, "missing": []})},
    ])
    planner = MeshPlanner(llm, capabilities={"research": "Research evidence"})

    plan = await planner.plan("Find evidence")

    assert plan.steps[0].task == "Find and cite the requested evidence"
    assert len(llm.calls) == 5
    repair_prompt = llm.calls[3]["messages"][0]["content"]
    assert "The evidence path is incomplete" in repair_prompt
    assert "Find evidence" in repair_prompt


@pytest.mark.asyncio
async def test_mesh_planner_can_converge_on_second_bounded_audit_repair():
    valid = responses()
    missing = {
        "content": json.dumps({
            "complete": False,
            "missing": [{
                "description": "Provider identifier is unresolved",
                "source_quote": "Find evidence",
            }],
        }),
    }
    repaired_once = responses(steps=[{
        "step_id": "research", "capability": "research", "effect": "read",
        "systems": [], "task": "Find evidence", "success_criterion": "Found",
        "expected_findings": ["evidence"], "depends_on": [], "covers": ["o1"],
    }])[1]
    repaired_twice = responses(steps=[{
        "step_id": "research", "capability": "research", "effect": "read",
        "systems": [], "task": "Resolve and return the source identifier",
        "success_criterion": "Concrete source identifier returned",
        "expected_findings": ["source identifier"], "depends_on": [], "covers": ["o1"],
    }])[1]
    llm = MockLLMClient(responses=[
        valid[0], valid[1], missing, repaired_once, missing, repaired_twice,
        {"content": json.dumps({"complete": True, "missing": []})},
    ])
    planner = MeshPlanner(llm, capabilities={"research": "Research evidence"})

    plan = await planner.plan("Find evidence")

    assert plan.steps[0].task == "Resolve and return the source identifier"
    assert len(llm.calls) == 7


@pytest.mark.asyncio
async def test_mesh_planner_treats_one_expected_finding_as_one_finding():
    llm = MockLLMClient(responses=responses(steps=[{
        "step_id": "research",
        "capability": "research",
        "effect": "read",
        "systems": [],
        "task": "Find evidence",
        "success_criterion": "Evidence found",
        "expected_findings": "one evidence summary",
        "depends_on": [],
        "covers": ["o1"],
    }]))
    planner = MeshPlanner(llm, capabilities={"research": "Research evidence"})

    plan = await planner.plan("Find evidence")

    assert plan.steps[0].expected_findings == ["one evidence summary"]


@pytest.mark.asyncio
async def test_mesh_planner_requires_an_explicit_valid_effect_for_every_step():
    missing_effect = responses(steps=[{
        "step_id": "research", "capability": "research", "task": "Find evidence",
        "success_criterion": "Found", "expected_findings": [], "depends_on": [],
        "covers": ["o1"],
    }])
    planner = MeshPlanner(
        MockLLMClient(responses=missing_effect),
        capabilities={"research": "Research evidence"},
    )
    with pytest.raises(MeshPlanError, match="valid effect"):
        await planner.plan("Find evidence")


@pytest.mark.asyncio
async def test_mesh_planner_rejects_effect_outside_capability_authority():
    planner = MeshPlanner(
        MockLLMClient(responses=responses(steps=[{
            "step_id": "research", "capability": "research", "effect": "write",
            "systems": ["public_web"],
            "task": "Create a record", "success_criterion": "Record created",
            "expected_findings": [], "depends_on": [], "covers": ["o1"],
        }])),
        capabilities={
            "research": {
                "description": "Read evidence",
                "effects": ["read"],
                "systems": ["public_web"],
            },
        },
    )

    with pytest.raises(MeshPlanError, match="does not authorize effect 'write'"):
        await planner.plan("Find evidence")


@pytest.mark.asyncio
async def test_mesh_planner_rejects_system_outside_capability_authority():
    planner = MeshPlanner(
        MockLLMClient(responses=responses(steps=[{
            "step_id": "research", "capability": "research", "effect": "read",
            "systems": ["slack"], "task": "Read Slack", "success_criterion": "Read",
            "expected_findings": [], "depends_on": [], "covers": ["o1"],
        }])),
        capabilities={
            "research": {
                "description": "Read public evidence",
                "effects": ["read"],
                "systems": ["public_web"],
            },
        },
    )

    with pytest.raises(MeshPlanError, match="does not authorize systems.*slack"):
        await planner.plan("Find evidence")


@pytest.mark.asyncio
@pytest.mark.parametrize("systems", [[], ["hubspot", "slack"]])
async def test_mesh_planner_requires_one_provider_for_mutating_outcomes(systems):
    planner = MeshPlanner(
        MockLLMClient(responses=responses(steps=[{
            "step_id": "manage_deal", "capability": "deal_management",
            "effect": "write", "systems": systems,
            "task": "Establish the lead's deal and current stage",
            "success_criterion": "A verified deal and stage exist",
            "expected_findings": ["deal identity", "deal stage"],
            "depends_on": [], "covers": ["o1"],
        }])),
        capabilities={
            "deal_management": {
                "description": "Establish CRM deal state",
                "effects": ["read", "write"],
                "systems": ["hubspot", "slack"],
            },
        },
    )

    with pytest.raises(MeshPlanError, match="exactly one system"):
        await planner.plan("Find evidence")