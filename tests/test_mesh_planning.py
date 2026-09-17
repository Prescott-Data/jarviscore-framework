import json

import pytest

from jarviscore.planning.mesh_planner import (
    GoalObligation,
    MeshPlan,
    MeshPlanError,
    MeshPlannedStep,
    MeshPlanner,
)
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
    assert "provider-readback evidence of usable content" in dag_prompt
    assert "umbrella obligation" in obligation_prompt
    assert "source goal or an ancestor step" in audit_prompt
    assert "independently verifiable success criterion" in audit_prompt
    assert "Resource existence, title, identifier, link or MIME type" in audit_prompt
    assert all("json" in prompt for prompt in (obligation_prompt, dag_prompt, audit_prompt))


@pytest.mark.asyncio
async def test_mesh_planner_audit_removes_redundant_umbrella_obligation():
    goal = "Execute the launch playbook: find the account and draft the email."
    initial_obligations = [
        {
            "id": "umbrella", "description": "Execute the launch playbook",
            "source_quote": "Execute the launch playbook",
        },
        {
            "id": "find", "description": "Find the account",
            "source_quote": "find the account",
        },
        {
            "id": "draft", "description": "Draft the email",
            "source_quote": "draft the email",
        },
    ]
    initial_step = {
        "step_id": "work", "capability": "work", "effect": "read", "systems": [],
        "task": "Execute the playbook", "success_criterion": "Everything completed",
        "expected_findings": [], "depends_on": [],
        "covers": ["umbrella", "find", "draft"],
    }
    corrected_obligations = initial_obligations[1:]
    corrected_step = {
        **initial_step,
        "task": "Find the account and draft the email",
        "covers": ["find", "draft"],
    }
    llm = MockLLMClient(responses=[
        {"content": json.dumps({"obligations": initial_obligations})},
        {"content": json.dumps({"steps": [initial_step]})},
        {"content": json.dumps({
            "complete": False,
            "missing": ["The umbrella duplicates the concrete outcomes."],
            "obligations": corrected_obligations,
        })},
        {"content": json.dumps({"steps": [corrected_step]})},
        {"content": json.dumps({"complete": True, "missing": []})},
    ])
    planner = MeshPlanner(llm, capabilities={"work": "Perform launch work"})

    plan = await planner.plan(goal)

    assert [item.id for item in plan.obligations] == ["find", "draft"]
    assert plan.steps[0].covers == ["find", "draft"]


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
async def test_mesh_amendment_repairs_reused_completed_ids_to_a_delta():
    obligations = [{
        "id": "o1", "description": "Verify evidence", "source_quote": "Verify evidence",
    }]
    completed_response = {
        "id": "final_response", "capability": "briefing", "effect": "final_response",
        "systems": [], "task": "Report the first outcome", "success_criterion": "Reported",
        "expected_findings": [], "depends_on": ["verify"], "covers": [],
        "status": "completed", "output": {"result_summary": "First response"},
        "claim_id": "responder:claim", "completed_by": "responder",
    }
    verify = {
        "id": "verify", "capability": "verification", "effect": "read",
        "systems": [], "task": "Verify evidence", "success_criterion": "Verified",
        "expected_findings": [], "depends_on": [], "covers": ["o1"],
        "status": "completed", "output": {"interpretation": {"decision": "hold"}},
    }
    rejected = [
        {key: value for key, value in verify.items() if key not in {"status", "output"}},
        {
            **{key: value for key, value in completed_response.items()
               if key not in {"status", "output", "claim_id", "completed_by"}},
            "depends_on": ["verify", "verify_content"],
        },
        {
            "id": "verify_content", "capability": "verification", "effect": "read",
            "systems": [], "task": "Verify content", "success_criterion": "Verified",
            "expected_findings": [], "depends_on": ["verify"], "covers": ["o1"],
        },
    ]
    repaired = [rejected[-1]]
    llm = MockLLMClient(responses=[
        {"content": json.dumps({"steps": rejected})},
        {"content": json.dumps({"steps": repaired})},
        {"content": json.dumps({"complete": True, "missing": []})},
    ])
    planner = MeshPlanner(
        llm,
        capabilities={
            "verification": {"description": "Verify", "effects": ["read"], "systems": []},
            "briefing": {
                "description": "Report", "effects": ["final_response"], "systems": [],
            },
        },
        response_capability="briefing",
    )

    plan = await planner.amend(
        "Verify evidence", obligations=obligations,
        current_steps=[verify, completed_response], reason="Content remains unverified",
        revision=1,
    )

    assert [step.step_id for step in plan.steps] == [
        "verify_content", "final_response_2",
    ]
    assert "CURRENT STEP DEFINITIONS" in llm.calls[1]["messages"][0]["content"]
    assert "already exists" in llm.calls[1]["messages"][0]["content"]
    assert "claim_id" not in llm.calls[1]["messages"][0]["content"]


@pytest.mark.asyncio
async def test_mesh_amendment_repairs_unknown_capability_before_audit():
    obligations = [{
        "id": "o1", "description": "Verify evidence", "source_quote": "Verify evidence",
    }]
    valid_step = {
        "id": "verify", "capability": "verification", "effect": "read",
        "systems": [], "task": "Verify evidence", "success_criterion": "Verified",
        "expected_findings": [], "depends_on": [], "covers": ["o1"],
    }
    llm = MockLLMClient(responses=[
        {"content": json.dumps({"steps": [{
            **valid_step, "capability": "invented_reconciliation",
        }]})},
        {"content": json.dumps({"steps": [valid_step]})},
        {"content": json.dumps({"complete": True, "missing": []})},
    ])
    planner = MeshPlanner(
        llm,
        capabilities={
            "verification": {"description": "Verify", "effects": ["read"], "systems": []},
        },
    )

    plan = await planner.amend(
        "Verify evidence", obligations=obligations, current_steps=[],
        reason="A new verification path is available", revision=1,
    )

    assert plan.steps[0].capability == "verification"
    repair_prompt = llm.calls[1]["messages"][0]["content"]
    assert "unknown capability" in repair_prompt
    assert "invented_reconciliation" in repair_prompt


def test_amendment_audit_distinguishes_attempt_completion_from_effect_execution():
    plan = MeshPlan(
        goal="Draft an invitation",
        obligations=[GoalObligation("o1", "Draft invitation", "Draft an invitation")],
        steps=[MeshPlannedStep(
            step_id="draft_retry", capability="email", effect="write",
            systems=["gmail"], task="Create the draft", success_criterion="Draft exists",
            depends_on=["draft_first"], covers=["o1"],
        )],
        revision=2,
    )
    prompt = MeshPlanner._amendment_audit_prompt(
        plan,
        current_steps=[{
            "id": "draft_first", "capability": "email", "effect": "write",
            "systems": ["gmail"], "task": "Create the draft",
            "success_criterion": "Draft exists", "expected_findings": [],
            "depends_on": [], "covers": ["o1"], "status": "completed",
            "semantic_decision": "reject",
            "output": {"output": {"status": "blocked", "execution_state": "not_executed"}},
        }],
        reason="The first attempt did not execute",
    )

    assert '"execution_state": "not_executed"' in prompt
    assert "attempt ended; it does not prove its provider" in prompt
    assert "must not repeat an already executed" in prompt
    assert "may advance only the blocked obligations named" in prompt


@pytest.mark.asyncio
async def test_reconciliation_can_only_settle_an_existing_gap_as_blocked():
    planner = MeshPlanner(
        MockLLMClient(responses=[{"content": json.dumps({
            "decision": "settle_blocked", "reason": "A human-only fact is missing.",
        })}]),
        capabilities={"verification": "Verify evidence"},
    )
    decision = await planner.reconciliation_decision(
        "Verify evidence", obligations=[], current_steps=[], revision=1,
    )
    assert decision["decision"] == "settle_blocked"

    ambiguous = MeshPlanner(
        MockLLMClient(responses=[{"content": json.dumps({
            "decision": "settle", "reason": "Everything is satisfied.",
        })}]),
        capabilities={"verification": "Verify evidence"},
    )
    with pytest.raises(MeshPlanError, match="settle_blocked"):
        await ambiguous.reconciliation_decision(
            "Verify evidence", obligations=[], current_steps=[], revision=1,
        )


@pytest.mark.asyncio
async def test_mesh_amendment_uses_second_repair_after_invalid_first_repair():
    obligations = [{
        "id": "o1", "description": "Verify evidence", "source_quote": "Verify evidence",
    }]
    valid_step = {
        "id": "verify", "capability": "verification", "effect": "read",
        "systems": [], "task": "Verify evidence", "success_criterion": "Verified",
        "expected_findings": [], "depends_on": [], "covers": ["o1"],
    }
    llm = MockLLMClient(responses=[
        {"content": json.dumps({"steps": [valid_step]})},
        {"content": json.dumps({"complete": False, "missing": ["Needs repair"]})},
        {"content": json.dumps({"steps": [{**valid_step, "effect": "invented"}]})},
        {"content": json.dumps({"steps": [valid_step]})},
        {"content": json.dumps({"complete": True, "missing": []})},
    ])
    planner = MeshPlanner(
        llm,
        capabilities={
            "verification": {"description": "Verify", "effects": ["read"], "systems": []},
        },
    )

    plan = await planner.amend(
        "Verify evidence", obligations=obligations, current_steps=[],
        reason="A new verification path is available", revision=1,
    )

    assert plan.steps[0].effect == "read"
    assert "Repair draft failed validation" in llm.calls[3]["messages"][0]["content"]


@pytest.mark.asyncio
async def test_mesh_amendment_returns_only_new_work():
    obligations = [{
        "id": "o1", "description": "Verify evidence", "source_quote": "Verify evidence",
    }]
    completed = {
        "id": "verify_first", "capability": "verification", "effect": "read",
        "systems": [], "task": "First verification", "success_criterion": "Attempted",
        "expected_findings": [], "depends_on": [], "covers": ["o1"],
        "status": "completed", "output": {"interpretation": {"decision": "hold"}},
    }
    remediation = {
        "id": "verify_again", "capability": "verification", "effect": "read",
        "systems": [], "task": "Verify with the new capability",
        "success_criterion": "Verified", "expected_findings": [],
        "depends_on": ["verify_first"], "covers": ["o1"],
    }
    llm = MockLLMClient(responses=[
        {"content": json.dumps({"steps": [remediation]})},
        {"content": json.dumps({"complete": True, "missing": []})},
    ])
    planner = MeshPlanner(
        llm,
        capabilities={
            "verification": {"description": "Verify", "effects": ["read"], "systems": []},
        },
    )

    plan = await planner.amend(
        "Verify evidence", obligations=obligations, current_steps=[completed],
        reason="A new verification path is available", revision=1,
    )

    assert [step.step_id for step in plan.steps] == ["verify_again"]


@pytest.mark.asyncio
async def test_mesh_amendment_cannot_supersede_satisfied_obligations():
    obligations = [
        {"id": "satisfied", "description": "Keep verified evidence", "source_quote": "verified evidence"},
        {"id": "unresolved", "description": "Resolve missing evidence", "source_quote": "missing evidence"},
    ]
    overbroad = {
        "id": "restate", "capability": "verification", "effect": "read",
        "systems": [], "task": "Restate all evidence", "success_criterion": "Restated",
        "expected_findings": [], "depends_on": [], "covers": ["satisfied", "unresolved"],
    }
    targeted = {
        **overbroad, "id": "resolve", "task": "Resolve missing evidence",
        "covers": ["unresolved"],
    }
    llm = MockLLMClient(responses=[
        {"content": json.dumps({"steps": [overbroad]})},
        {"content": json.dumps({"steps": [targeted]})},
        {"content": json.dumps({"complete": True, "missing": []})},
    ])
    planner = MeshPlanner(llm, capabilities={"verification": "Verify evidence"})

    plan = await planner.amend(
        "Keep verified evidence and resolve missing evidence",
        obligations=obligations,
        target_obligation_ids={"unresolved"},
        current_steps=[],
        reason="Missing evidence remains unresolved",
        revision=1,
    )

    assert [step.covers for step in plan.steps] == [["unresolved"]]
    assert "outside the amendment target" in llm.calls[1]["messages"][0]["content"]


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
async def test_mesh_planner_accepts_canonical_step_id_from_current_ledger():
    llm = MockLLMClient(responses=responses(steps=[{
        "id": "research", "capability": "research", "effect": "read",
        "systems": [], "task": "Find evidence", "success_criterion": "Found",
        "expected_findings": [], "depends_on": [], "covers": ["o1"],
    }]))
    planner = MeshPlanner(llm, capabilities={"research": "Research evidence"})

    plan = await planner.plan("Find evidence")

    assert plan.steps[0].step_id == "research"


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