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
            "source_ref": "source-1",
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
    assert "directly listed in `depends_on`" in dag_prompt
    assert "Transitive ancestry establishes ordering only" in dag_prompt
    assert "direct dependency supplies only the artifact promised" in dag_prompt
    assert "both original evidence and a transformed decision" in dag_prompt
    assert "directly listed in `depends_on`" in audit_prompt
    assert "Transitive ancestry establishes ordering only" in audit_prompt
    assert "direct dependency as supplying only the artifact promised" in audit_prompt
    assert "independently verifiable success criterion" in audit_prompt
    assert "Resource existence, title, identifier, link or MIME type" in audit_prompt
    assert "operation=`add_dependencies`" in audit_prompt
    assert "producer_step_ids" in audit_prompt
    assert all("json" in prompt for prompt in (obligation_prompt, dag_prompt, audit_prompt))


def test_mesh_planner_renders_declared_capability_artifact():
    planner = MeshPlanner(
        MockLLMClient(),
        capabilities={
            "prioritize": {
                "description": "Rank a finding",
                "effects": ["propose"],
                "systems": [],
                "produces": "DecisionRecord(subject_id, decision, rank)",
                "artifact_types": ["DecisionRecord"],
                "requires_artifact_types": ["FindingRecord"],
            },
        },
    )

    catalog = planner._render_capability_catalog()

    assert "produces: DecisionRecord(subject_id, decision, rank)" in catalog
    assert "artifact types: DecisionRecord" in catalog
    assert "requires artifact types: FindingRecord" in catalog


def test_declared_artifact_requirements_close_direct_dependencies():
    planner = MeshPlanner(
        MockLLMClient(),
        capabilities={
            "discover": {
                "description": "Discover findings",
                "effects": ["read"],
                "systems": [],
                "artifact_types": ["CandidateFinding"],
            },
            "repair": {
                "description": "Repair findings",
                "effects": ["propose"],
                "systems": [],
                "artifact_types": ["PatchArtifact"],
            },
            "synthesize": {
                "description": "Join exact evidence",
                "effects": ["propose"],
                "systems": [],
                "requires_artifact_types": ["CandidateFinding", "PatchArtifact"],
            },
        },
    )
    steps = [
        MeshPlannedStep(
            "find", "discover", "read", [], "Find", "Found", [], [], []
        ),
        MeshPlannedStep(
            "fix", "repair", "propose", [], "Fix", "Fixed", [], ["find"], []
        ),
        MeshPlannedStep(
            "brief", "synthesize", "propose", [], "Brief", "Briefed", [],
            ["fix"], [],
        ),
    ]

    closed = planner._ensure_declared_artifact_dependencies(steps)

    assert closed[-1].depends_on == ["fix", "find"]

    amended = planner._ensure_declared_artifact_dependencies(
        [MeshPlannedStep(
            "brief_v2", "synthesize", "propose", [], "Brief", "Briefed", [],
            [], [],
        )],
        external_steps=[
            {"id": "find", "capability": "discover"},
            {"id": "fix", "capability": "repair"},
        ],
    )

    assert amended[0].depends_on == ["find", "fix"]


@pytest.mark.asyncio
async def test_mesh_planning_brief_informs_dag_audit_and_repair_not_obligations():
    brief = "Use the target Mesh method, including independent verification when applicable."
    initial_steps = responses()[1]
    repaired_steps = responses(steps=[{
        "step_id": "research", "capability": "research", "effect": "read",
        "systems": [], "task": "Find and independently verify evidence",
        "success_criterion": "Evidence and verification are cited",
        "expected_findings": ["evidence", "verification"],
        "depends_on": [], "covers": ["o1"],
    }])[1]
    llm = MockLLMClient(responses=[
        responses()[0],
        initial_steps,
        {"content": json.dumps({
            "complete": False,
            "missing": [{
                "description": "Independent verification is missing",
                "source_ref": "source-1",
            }],
        })},
        repaired_steps,
        {"content": json.dumps({"complete": True, "missing": []})},
    ])
    planner = MeshPlanner(
        llm,
        capabilities={"research": "Research and verify evidence"},
        planning_brief=brief,
    )

    await planner.plan("Find evidence")

    prompts = [call["messages"][0]["content"] for call in llm.calls]
    assert brief not in prompts[0]
    assert all(brief in prompt for prompt in prompts[1:])
    for prompt in prompts[1:]:
        assert "Explicit source scope, prohibitions and approval boundaries override" in prompt
        assert "Never derive source obligations from this brief" in prompt
        assert "decision-capable outcome" in prompt
        assert "verified no-op" in prompt
    assert "Never derive\nsource provenance from TARGET MESH PLANNING BRIEF" in prompts[2]


def test_mesh_planning_brief_reaches_amendment_and_reconciliation_prompts():
    brief = "Preserve the product method while resolving unfinished work."
    planner = MeshPlanner(
        MockLLMClient(),
        capabilities={"research": "Research evidence"},
        planning_brief=brief,
    )
    obligation = GoalObligation("o1", "Find evidence", "Find evidence")
    plan = MeshPlan(
        goal="Find evidence",
        obligations=[obligation],
        steps=[MeshPlannedStep(
            step_id="research", capability="research", effect="read", systems=[],
            task="Find evidence", success_criterion="Evidence found", covers=["o1"],
        )],
    )

    prompts = [
        planner._amendment_prompt(
            plan.goal, plan.obligations, {"o1"}, [], "Evidence missing", {},
        ),
        planner._reconciliation_prompt(
            plan.goal,
            [],
            [],
            2,
            [{
                "event": "semantic_reconciliation_requested",
                "revision": 1,
                "decision": "amend",
                "reason": "Evidence missing",
                "target_obligation_ids": ["o1"],
            }],
        ),
        planner._amendment_audit_prompt(
            plan, current_steps=[], reason="Evidence missing", planning_brief=brief,
        ),
        planner._amendment_repair_prompt(
            plan, audit={"complete": False}, current_steps=[],
            reason="Evidence missing", planning_brief=brief,
        ),
        planner._invalid_amendment_repair_prompt(
            plan.goal, plan.obligations, current_steps=[], rejected={"steps": []},
            reason="Evidence missing", validation_error="Invalid dependency",
        ),
    ]

    assert all(brief in prompt for prompt in prompts)
    assert "PRIOR RECONCILIATION HISTORY" in prompts[1]
    assert '"target_obligation_ids": ["o1"]' in prompts[1]
    assert "do not assume another revision is progress" in prompts[1]
    step_prompts = [
        prompt
        for prompt in prompts
        if "Return one valid json object" in prompt or "Audit one reconciled" in prompt
    ]
    assert all("directly listed in `depends_on`" in prompt for prompt in step_prompts)
    assert all(
        "Transitive ancestry establishes ordering only" in prompt
        for prompt in step_prompts
    )
    assert all(
        "direct dependency supplies only its own declared artifact" in prompt
        for prompt in step_prompts
    )


def test_reconciliation_compacts_bulk_artifacts_with_exact_references():
    planner = MeshPlanner(
        MockLLMClient(),
        capabilities={"verification": "Verify evidence"},
    )
    raw_receipt = "command output that must stay durable, not in planning context" * 500
    artifact = {
        "status": "passed",
        "commit_sha": "abc123",
        "runs": [{"stdout": raw_receipt, "exit_code": 0}],
        "execution_state": "executed",
    }
    prompt = planner._reconciliation_prompt(
        "Verify evidence",
        [{"id": "o1", "state": "unresolved"}],
        [{
            "id": "verify", "capability": "verification", "effect": "read",
            "systems": [], "task": "Run checks", "success_criterion": "Checks run",
            "expected_findings": [], "depends_on": [], "covers": ["o1"],
            "status": "completed", "semantic_decision": "proceed",
            "output": {
                "status": "success", "output": artifact, "payload": artifact,
                "result_summary": "Checks ran.",
                "interpretation": {"verdict": "partial", "unmet_requirements": ["o1"]},
            },
        }],
        revision=1,
    )

    assert raw_receipt not in prompt
    assert '"execution_state": "executed"' in prompt
    assert '"artifact_ref": {"step_id": "verify", "path": ["output", "runs"]}' in prompt
    assert '"kind": "duplicate_of_output"' in prompt
    assert '"verdict": "partial"' in prompt


@pytest.mark.asyncio
async def test_mesh_planner_audit_removes_redundant_umbrella_obligation():
    goal = "Execute the launch playbook: find the account and draft the email."
    initial_obligations = [
        {
            "id": "umbrella", "description": "Execute the launch playbook",
            "source_ref": "source-1",
        },
        {
            "id": "find", "description": "Find the account",
            "source_ref": "source-1",
        },
        {
            "id": "draft", "description": "Draft the email",
            "source_ref": "source-1",
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
    assert "source goal's requested format" in response_step.task
    assert "source goal's output constraints" in response_step.success_criterion


@pytest.mark.asyncio
async def test_mesh_planner_assigns_obligation_truth_to_terminal_domain_work():
    steps = [
        {
            "step_id": "inspect", "capability": "research", "effect": "read",
            "systems": [], "task": "Inspect", "success_criterion": "Mapped",
            "expected_findings": [], "depends_on": [], "covers": ["o1"],
        },
        {
            "step_id": "verify", "capability": "research", "effect": "read",
            "systems": [], "task": "Verify", "success_criterion": "Verified",
            "expected_findings": [], "depends_on": ["inspect"], "covers": ["o1"],
        },
    ]
    planner = MeshPlanner(
        MockLLMClient(responses=responses(steps=steps)),
        capabilities={
            "research": "Research evidence",
            "action_briefing": {
                "description": "Produce the user-facing decision",
                "effects": ["final_response"],
                "systems": [],
            },
        },
        response_capability="action_briefing",
    )

    plan = await planner.plan("Find evidence")

    assert plan.steps[0].covers == []
    assert plan.steps[1].covers == ["o1"]
    assert plan.steps[2].covers == []


@pytest.mark.asyncio
async def test_mesh_planner_owns_final_response_obligation_coverage():
    steps = responses()[1]["content"]
    domain_step = json.loads(steps)["steps"][0]
    model_response = {
        "step_id": "model_response",
        "capability": "action_briefing",
        "effect": "final_response",
        "systems": [],
        "task": "Report the outcome",
        "success_criterion": "The outcome is reported",
        "expected_findings": [],
        "depends_on": ["research"],
        "covers": ["o1"],
    }
    planner = MeshPlanner(
        MockLLMClient(responses=responses(steps=[domain_step, model_response])),
        capabilities={
            "research": "Research evidence",
            "action_briefing": {
                "description": "Produce the user-facing decision",
                "effects": ["final_response"],
                "systems": [],
            },
        },
        response_capability="action_briefing",
    )

    plan = await planner.plan("Find evidence")

    assert [step.step_id for step in plan.steps] == ["research", "final_response"]
    assert plan.steps[-1].covers == []


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
async def test_mesh_planner_repairs_initially_uncovered_prohibitions():
    obligations = [
        {"id": "o1", "description": "Inspect the repository", "source_ref": "source-1"},
        {"id": "o2", "description": "Do not publish", "source_ref": "source-1"},
        {"id": "o3", "description": "Do not push", "source_ref": "source-1"},
        {"id": "o4", "description": "Do not merge", "source_ref": "source-1"},
    ]
    invalid_steps = [{
        "step_id": "inspect", "capability": "research", "effect": "read",
        "systems": [], "task": "Inspect the repository",
        "success_criterion": "Repository evidence is collected",
        "expected_findings": ["evidence"], "depends_on": [], "covers": ["o1"],
        "dependency_policy": "satisfied",
    }]
    repaired_steps = [{
        **invalid_steps[0],
        "success_criterion": "Repository evidence is collected without publication",
        "covers": ["o1", "o2", "o3", "o4"],
    }]
    llm = MockLLMClient(responses=[
        {"content": json.dumps({"obligations": obligations})},
        {"content": json.dumps({"steps": invalid_steps})},
        {"content": json.dumps({"steps": repaired_steps})},
        {"content": json.dumps({"complete": True, "missing": []})},
    ])
    planner = MeshPlanner(llm, capabilities={"research": "Research evidence"})

    plan = await planner.plan("Inspect the repository. Do not publish, push, or merge.")

    assert plan.steps[0].covers == ["o1", "o2", "o3", "o4"]
    repair_prompt = llm.calls[2]["messages"][0]["content"]
    assert "uncovered obligation" in repair_prompt
    assert "constraints, prohibitions and approval boundaries" in repair_prompt


@pytest.mark.asyncio
async def test_mesh_planner_repairs_a_cycle_introduced_by_first_step_repair():
    obligations = [
        {"id": "o1", "description": "Inspect", "source_ref": "source-1"},
        {"id": "o2", "description": "Do not publish", "source_ref": "source-1"},
    ]
    invalid_steps = [{
        "step_id": "inspect", "capability": "research", "effect": "read",
        "systems": [], "task": "Inspect", "success_criterion": "Inspected",
        "expected_findings": [], "depends_on": [], "covers": ["o1"],
        "dependency_policy": "satisfied",
    }]
    cyclic_repair = [
        {**invalid_steps[0], "depends_on": ["guard"]},
        {
            "step_id": "guard", "capability": "research", "effect": "read",
            "systems": [], "task": "Verify no publication",
            "success_criterion": "No publication occurred", "expected_findings": [],
            "depends_on": ["inspect"], "covers": ["o2"],
            "dependency_policy": "satisfied",
        },
    ]
    valid_repair = [
        invalid_steps[0],
        {**cyclic_repair[1], "depends_on": ["inspect"]},
    ]
    llm = MockLLMClient(responses=[
        {"content": json.dumps({"obligations": obligations})},
        {"content": json.dumps({"steps": invalid_steps})},
        {"content": json.dumps({"steps": cyclic_repair})},
        {"content": json.dumps({"steps": valid_repair})},
        {"content": json.dumps({"complete": True, "missing": []})},
    ])
    planner = MeshPlanner(llm, capabilities={"research": "Research evidence"})

    plan = await planner.plan("Inspect. Do not publish.")

    assert [step.step_id for step in plan.steps] == ["inspect", "guard"]
    assert "dependency cycle" in llm.calls[3]["messages"][0]["content"]


@pytest.mark.asyncio
async def test_mesh_planner_rejects_unknown_obligation_source_reference():
    llm = MockLLMClient(responses=responses(obligations=[{
        "id": "o1", "description": "Invented requirement", "source_ref": "source-missing",
    }]))
    planner = MeshPlanner(llm, capabilities={"research": "Research evidence"})

    with pytest.raises(MeshPlanError, match="source_ref"):
        await planner.plan("Find evidence")


@pytest.mark.asyncio
async def test_mesh_planner_hydrates_source_quote_from_compiler_owned_reference():
    valid = responses()
    llm = MockLLMClient(responses=[
        {"content": json.dumps({"obligations": [{
            "id": "o1",
            "description": "Run the requested deep reliability scan",
            "source_ref": "source-1",
        }]})},
        valid[1],
        valid[2],
    ])
    planner = MeshPlanner(llm, capabilities={"research": "Research evidence"})

    plan = await planner.plan("Run a deep reliability scan of https://example.com/repo.")

    assert plan.obligations[0].source_quote == (
        "Run a deep reliability scan of https://example.com/repo."
    )
    obligation_prompt = llm.calls[0]["messages"][0]["content"]
    assert '"id": "source-1"' in obligation_prompt
    assert "source_ref" in obligation_prompt
    assert "source_quote" not in obligation_prompt


@pytest.mark.asyncio
async def test_mesh_planner_preserves_selected_multiline_source_block_exactly():
    goal = "Run the reliability scan.\n  Do not publish changes."
    valid = responses(steps=[{
        "step_id": "respect_boundary",
        "capability": "research",
        "effect": "read",
        "systems": [],
        "task": "Inspect without publishing",
        "success_criterion": "No publication occurs",
        "expected_findings": [],
        "depends_on": [],
        "covers": ["approval"],
    }])
    llm = MockLLMClient(responses=[
        {"content": json.dumps({"obligations": [{
            "id": "approval",
            "description": "Do not publish changes",
            "source_ref": "source-2",
        }]})},
        valid[1],
        valid[2],
    ])
    planner = MeshPlanner(llm, capabilities={"research": "Research evidence"})

    plan = await planner.plan(goal)

    assert plan.obligations[0].source_quote == "  Do not publish changes."
    prompt = llm.calls[0]["messages"][0]["content"]
    assert '"id": "source-2", "text": "  Do not publish changes."' in prompt
    assert '"id": "source-all"' in prompt


@pytest.mark.asyncio
async def test_mesh_planner_requires_source_reference_from_model_output():
    invalid_quote = {"content": json.dumps({"obligations": [{
        "id": "o1",
        "description": "Find evidence",
        "source_quote": "Find evidence",
    }]})}
    valid = responses()
    llm = MockLLMClient(responses=[invalid_quote, valid[0], valid[1], valid[2]])
    planner = MeshPlanner(llm, capabilities={"research": "Research evidence"})

    plan = await planner.plan("Find evidence")

    assert plan.obligations[0].source_quote == "Find evidence"
    assert "has no source_ref" in llm.calls[1]["messages"][0]["content"]


@pytest.mark.asyncio
async def test_mesh_planner_repairs_invalid_source_reference_before_dag_compilation():
    invalid = {
        "content": json.dumps({"obligations": [{
            "id": "o1", "description": "Find evidence",
            "source_ref": "source-missing",
        }]})
    }
    repaired = {
        "content": json.dumps({"obligations": [{
            "id": "o1", "description": "Find evidence",
            "source_ref": "source-1",
        }]})
    }
    valid = responses()
    llm = MockLLMClient(responses=[invalid, repaired, valid[1], valid[2]])
    planner = MeshPlanner(llm, capabilities={"research": "Research evidence"})

    plan = await planner.plan("Find evidence")

    assert plan.obligations[0].source_quote == "Find evidence"
    repair_prompt = llm.calls[1]["messages"][0]["content"]
    assert "source-missing" in repair_prompt
    assert "unknown source_ref" in repair_prompt
    assert '"id": "source-1"' in repair_prompt
    assert "Do not add, remove, merge or split obligations" in repair_prompt


@pytest.mark.asyncio
async def test_mesh_planner_rejects_a_dag_when_independent_audit_finds_an_omission():
    llm = MockLLMClient(responses=responses(audit={
        "complete": False,
        "missing": [{"description": "Preserve approval boundary", "source_ref": "source-1"}],
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
async def test_mesh_planner_applies_typed_audit_dependency_correction():
    initial_steps = responses(steps=[
        {
            "step_id": "candidate", "capability": "research", "effect": "read",
            "systems": [], "task": "Find candidate evidence",
            "success_criterion": "Candidate evidence returned",
            "expected_findings": ["candidate evidence"], "depends_on": [],
            "covers": ["o1"],
        },
        {
            "step_id": "ranking", "capability": "research", "effect": "read",
            "systems": [], "task": "Rank candidate evidence",
            "success_criterion": "Evidence-backed ranking returned",
            "expected_findings": ["ranking"], "depends_on": [], "covers": [],
        },
    ])[1]
    audit_failure = {
        "content": json.dumps({
            "complete": False,
            "missing": [{
                "description": "Ranking needs the original candidate evidence",
                "source_ref": "source-1",
            }],
            "corrections": [{
                "operation": "add_dependencies",
                "step_id": "ranking",
                "producer_step_ids": ["candidate"],
            }],
        }),
    }
    audit_success = {
        "content": json.dumps({"complete": True, "missing": []}),
    }
    llm = MockLLMClient(responses=[
        responses()[0], initial_steps, audit_failure, audit_success,
    ])
    planner = MeshPlanner(llm, capabilities={"research": "Research evidence"})

    plan = await planner.plan("Find evidence")

    assert plan.steps[1].depends_on == ["candidate"]
    assert len(llm.calls) == 4


@pytest.mark.asyncio
async def test_mesh_planner_repair_can_return_typed_dependency_correction():
    initial_steps = responses(steps=[
        {
            "step_id": "mapping", "capability": "research", "effect": "read",
            "systems": [], "task": "Map the repository",
            "success_criterion": "Repository map returned",
            "expected_findings": ["repository map"], "depends_on": [],
            "covers": [],
        },
        {
            "step_id": "candidate", "capability": "research", "effect": "read",
            "systems": [], "task": "Find candidate evidence",
            "success_criterion": "Candidate evidence returned",
            "expected_findings": ["candidate evidence"], "depends_on": ["mapping"],
            "covers": ["o1"],
        },
        {
            "step_id": "repair", "capability": "research", "effect": "propose",
            "systems": [], "task": "Repair the reproduced defect",
            "success_criterion": "Repair returned",
            "expected_findings": ["repair"], "depends_on": ["candidate"],
            "covers": [],
        },
    ])[1]
    audit_failure = {
        "content": json.dumps({
            "complete": False,
            "missing": [{
                "description": "Repair also needs the repository map",
                "source_ref": "source-1",
            }],
        }),
    }
    typed_repair = {
        "content": json.dumps({
            "corrections": [{
                "operation": "add_dependencies",
                "step_id": "repair",
                "producer_step_ids": ["mapping"],
            }],
        }),
    }
    audit_success = {
        "content": json.dumps({"complete": True, "missing": []}),
    }
    llm = MockLLMClient(responses=[
        responses()[0], initial_steps, audit_failure, typed_repair, audit_success,
    ])
    planner = MeshPlanner(llm, capabilities={"research": "Research evidence"})

    plan = await planner.plan("Find evidence")

    assert plan.steps[2].depends_on == ["candidate", "mapping"]
    repair_prompt = llm.calls[3]["messages"][0]["content"]
    assert "return only `corrections`" in repair_prompt


@pytest.mark.parametrize(
    ("correction", "error"),
    [
        (
            {
                "operation": "add_dependencies",
                "step_id": "ranking",
                "producer_step_ids": ["missing"],
            },
            "invalid producer 'missing'",
        ),
        (
            {
                "operation": "add_dependencies",
                "step_id": "candidate",
                "producer_step_ids": ["ranking"],
            },
            "dependency cycle",
        ),
    ],
)
def test_mesh_planner_rejects_invalid_typed_audit_correction(correction, error):
    plan = MeshPlan(
        goal="Find evidence",
        obligations=[GoalObligation("o1", "Find evidence", "Find evidence")],
        steps=[
            MeshPlannedStep(
                step_id="candidate", capability="research", effect="read",
                systems=[], task="Find candidate evidence",
                success_criterion="Candidate evidence returned",
                depends_on=[], covers=["o1"],
            ),
            MeshPlannedStep(
                step_id="ranking", capability="research", effect="read",
                systems=[], task="Rank candidate evidence",
                success_criterion="Evidence-backed ranking returned",
                depends_on=["candidate"], covers=[],
            ),
        ],
    )

    with pytest.raises(MeshPlanError, match=error):
        MeshPlanner._apply_audit_corrections(plan, {"corrections": [correction]})


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


@pytest.mark.asyncio
async def test_mesh_amendment_repair_receives_authoritative_step_invariants():
    obligations = [{
        "id": "o1", "description": "Verify evidence", "source_quote": "Verify evidence",
    }]
    valid_step = {
        "id": "verify", "capability": "verification", "effect": "read",
        "systems": [], "task": "Verify evidence", "success_criterion": "Verified",
        "expected_findings": [], "depends_on": [], "covers": ["o1"],
        "dependency_policy": "terminal_evidence",
    }
    llm = MockLLMClient(responses=[
        {"content": json.dumps({"steps": [{
            **valid_step, "dependency_policy": "all_must_succeed",
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

    await planner.amend(
        "Verify evidence", obligations=obligations, current_steps=[],
        reason="A new verification path is available", revision=1,
    )

    amendment_prompt = llm.calls[0]["messages"][0]["content"]
    repair_prompt = llm.calls[1]["messages"][0]["content"]
    for prompt in (amendment_prompt, repair_prompt):
        assert "dependency_policy must be exactly `satisfied` or `terminal_evidence`" in prompt
        assert "cover every UNRESOLVED OBLIGATION ID" in prompt


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
    assert "must not repeat an already\nexecuted provider outcome" in prompt
    assert "may advance only the blocked obligations named" in prompt


def test_amendment_audit_allows_corrective_work_after_rejected_evidence_attempts():
    plan = MeshPlan(
        goal="Repair and verify",
        obligations=[GoalObligation("o1", "Repair defect", "Repair defect")],
        steps=[MeshPlannedStep(
            step_id="repair_followup", capability="repair", effect="propose",
            systems=[], task="Complete caller migration",
            success_criterion="Patch compiles", depends_on=["repair_first"],
            covers=["o1"], dependency_policy="terminal_evidence",
        )],
        revision=2,
    )
    prompt = MeshPlanner._amendment_audit_prompt(
        plan,
        current_steps=[{
            "id": "repair_first", "capability": "repair", "effect": "propose",
            "systems": [], "task": "Repair constructor",
            "success_criterion": "Patch compiles", "expected_findings": [],
            "depends_on": [], "covers": ["o1"], "status": "completed",
            "semantic_decision": "reject",
            "output": {"output": {"status": "applied"}},
        }],
        reason="The applied patch did not update callers.",
    )

    assert "semantically rejected read or propose attempts" in prompt
    assert "distinct corrective successors" in prompt
    assert "no new write, notify or destructive step repeats" in prompt


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


def test_amendment_audit_and_repair_include_failed_terminal_evidence():
    obligations = [GoalObligation("o1", "Verify evidence", "Verify evidence")]
    failed = {
        "id": "verify_failed", "capability": "verification", "effect": "read",
        "systems": [], "task": "Verify evidence", "success_criterion": "Verified",
        "expected_findings": [], "depends_on": [], "covers": ["o1"],
        "status": "failed", "output": {"error": "selector was incomplete"},
    }
    remediation = MeshPlannedStep(
        step_id="verify_again", capability="verification", effect="read", systems=[],
        task="Verify from failed evidence", success_criterion="Verified",
        depends_on=["verify_failed"], covers=["o1"],
        dependency_policy="terminal_evidence",
    )
    plan = MeshPlan("Verify evidence", obligations, [remediation], revision=2)

    audit_prompt = MeshPlanner._amendment_audit_prompt(
        plan, current_steps=[failed], reason="Correct the failed verification",
    )
    repair_prompt = MeshPlanner._amendment_repair_prompt(
        plan, audit={"complete": False, "missing": ["repair"]},
        current_steps=[failed], reason="Correct the failed verification",
    )

    assert "verify_failed" in audit_prompt
    assert '"status": "failed"' in audit_prompt
    assert "TERMINAL ATTEMPT DEFINITIONS" in audit_prompt
    assert "verify_failed" in repair_prompt
    assert '"status": "failed"' in repair_prompt
    assert "TERMINAL STEP DEFINITIONS" in repair_prompt


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