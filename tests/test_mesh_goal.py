import asyncio
import json
import time
from typing import ClassVar

import pytest

from jarviscore import Agent, Mesh
from jarviscore.testing import MockLLMClient, MockRedisContextStore


class ResearchPeer(Agent):
    role = "research_peer"
    capabilities: ClassVar[list[str]] = ["research"]

    def __init__(self, llm, agent_id=None):
        super().__init__(agent_id)
        self.llm = llm
        self.received = []

    async def execute_task(self, task):
        self.received.append(task)
        return {
            "status": "success",
            "output": {"evidence": ["source-1"]},
            "interpretation": {
                "verdict": "satisfied",
                "meaning": "The required evidence was found.",
                "decision": "proceed",
                "satisfied_requirements": ["Evidence exists"],
                "unmet_requirements": [],
                "evidence_refs": ["source-1"],
            },
        }


class AnalysisPeer(Agent):
    role = "analysis_peer"
    capabilities: ClassVar[list[str]] = ["analysis"]

    def __init__(self, agent_id=None):
        super().__init__(agent_id)
        self.received = []

    async def execute_task(self, task):
        self.received.append(task)
        evidence = next(iter(task["context"]["previous_step_results"].values()))
        return {
            "status": "success",
            "output": {"used": evidence},
            "result_summary": "The evidence was analysed successfully.",
        }


class FailingResearchPeer(ResearchPeer):
    async def execute_task(self, task):
        self.received.append(task)
        return {"status": "failure", "error": "source unavailable"}


class RecoveringResearchPeer(ResearchPeer):
    async def execute_task(self, task):
        self.received.append(task)
        if len(self.received) == 1:
            return {"status": "failure", "error": "source unavailable"}
        return {"status": "success", "output": {"evidence": ["source-2"]}}


class WaitingResearchPeer(ResearchPeer):
    async def execute_task(self, task):
        self.received.append(task)
        if task.get("context", {}).get("_resume"):
            return {"status": "success", "output": {"evidence": ["approved-source"]}}
        return {"status": "waiting", "reason": "approval required"}


class SubmitterPeer(Agent):
    role = "submitter"
    capabilities: ClassVar[list[str]] = ["submission"]

    async def execute_task(self, task):
        return {"status": "success", "output": "submitted"}


class SlowPeer(Agent):
    def __init__(self, role, capability, agent_id=None):
        self.role = role
        self.capabilities = [capability]
        super().__init__(agent_id)
        self.started = None

    async def execute_task(self, task):
        self.started = time.perf_counter()
        await asyncio.sleep(0.1)
        return {"status": "success", "output": self.role}


class HoldingPeer(Agent):
    role = "holding_peer"
    capabilities = ["verification"]

    async def execute_task(self, task):
        return {
            "status": "success",
            "output": {"verified": False},
            "interpretation": {
                "verdict": "partial",
                "decision": "hold",
                "meaning": "The identity is not verified.",
                "satisfied_requirements": [],
                "unmet_requirements": ["Verified identity"],
                "evidence_refs": [],
            },
        }


class RemediatingPeer(Agent):
    role = "remediating_peer"
    capabilities = ["verification"]

    def __init__(self, llm, agent_id=None):
        super().__init__(agent_id)
        self.llm = llm
        self.received = []

    async def execute_task(self, task):
        self.received.append(task)
        remediating = task["id"] == "verify_content"
        return {
            "status": "success",
            "output": {"content_verified": remediating},
            "interpretation": {
                "verdict": "satisfied" if remediating else "partial",
                "decision": "proceed" if remediating else "hold",
                "meaning": "Content is verified." if remediating else "Content is unverified.",
                "satisfied_requirements": ["o1"] if remediating else ["o0"],
                "unmet_requirements": [] if remediating else ["o1"],
                "evidence_refs": ["document-readback"] if remediating else [],
            },
        }


class WritePeer(Agent):
    role = "write_peer"
    capabilities = ["external_write"]

    def __init__(self, agent_id=None):
        super().__init__(agent_id)
        self.received = []

    async def execute_task(self, task):
        self.received.append(task)
        return {"status": "success", "output": {"written": True}}


class EdgeAwareWritePeer(WritePeer):
    capabilities = ["edge_aware_write"]

    def __init__(self, llm, agent_id=None):
        super().__init__(agent_id)
        self.llm = llm


class PartialContactPeer(Agent):
    role = "partial_contact"
    capabilities = ["partial_contact"]

    async def execute_task(self, task):
        return {
            "status": "success",
            "output": {"email": "lead@example.com"},
            "interpretation": {
                "verdict": "partial",
                "decision": "hold",
                "meaning": "Contact is verified; duplicate cleanup remains.",
                "satisfied_requirements": ["Verified contact"],
                "unmet_requirements": ["Duplicate cleanup"],
                "evidence_refs": ["contact-1"],
            },
        }


class NotifyPeer(Agent):
    role = "notify_peer"
    capabilities = ["team_notification"]

    def __init__(self, agent_id=None):
        super().__init__(agent_id)
        self.received = []

    async def execute_task(self, task):
        self.received.append(task)
        return {"status": "success", "output": {"notified": True}}


class ResponsePeer(Agent):
    role = "response_peer"
    capabilities = ["final_response"]

    def __init__(self, agent_id=None):
        super().__init__(agent_id)
        self.received = []

    async def execute_task(self, task):
        self.received.append(task)
        return {
            "status": "success",
            "output": {"decision": "hold"},
            "result_summary": "Identity was not verified, so no external write was performed.",
        }


class FailingResponsePeer(ResponsePeer):
    async def execute_task(self, task):
        self.received.append(task)
        return {"status": "failure", "error": "response synthesis failed"}


class RevisionResponsePeer(ResponsePeer):
    async def execute_task(self, task):
        self.received.append(task)
        return {
            "status": "success",
            "output": {"decision": "proceed"},
            "result_summary": f"Response for revision {len(self.received)}.",
        }


class CollateralPeer(Agent):
    role = "collateral_peer"
    capabilities = ["sales_collateral"]

    async def execute_task(self, task):
        return {
            "status": "success",
            "output": {"document_id": "deck-1", "status": "existing"},
        }


class NeedRequesterPeer(Agent):
    role = "need_requester"
    capabilities = ["coordination"]

    async def execute_task(self, task):
        return {"status": "success", "output": "requester"}


class NeedResolverPeer(Agent):
    role = "need_resolver"
    capabilities = ["contact_verification"]
    capability_contracts = {
        "contact_verification": {
            "effects": ["read"], "systems": ["gmail", "hubspot"],
        },
    }

    def __init__(self, agent_id=None):
        super().__init__(agent_id)
        self.received = []

    async def execute_task(self, task):
        self.received.append(task)
        return {
            "status": "success",
            "output": {"email": "ephy@example.com", "source": "connected systems"},
        }


def goal_responses():
    return [
        {"content": json.dumps({"obligations": [
            {"id": "o1", "description": "Find evidence", "source_quote": "Find evidence"},
            {"id": "o2", "description": "Analyse it", "source_quote": "analyse it"},
        ]})},
        {"content": json.dumps({"steps": [
            {
                "step_id": "research", "capability": "research", "effect": "read",
                "task": "Find evidence", "success_criterion": "Evidence exists",
                "expected_findings": ["evidence"], "depends_on": [], "covers": ["o1"],
            },
            {
                "step_id": "analyse", "capability": "analysis", "effect": "read",
                "task": "Analyse the evidence", "success_criterion": "Analysis uses evidence",
                "expected_findings": ["analysis"], "depends_on": ["research"], "covers": ["o2"],
            },
        ]})},
        {"content": json.dumps({"complete": True, "missing": []})},
    ]


@pytest.mark.asyncio
async def test_execute_goal_compiles_publishes_and_peers_claim_by_capability(monkeypatch):
    obligations = [
            {"id": "o1", "description": "Find evidence", "source_quote": "Find evidence"},
            {"id": "o2", "description": "Analyse it", "source_quote": "analyse it"},
        ]
    steps = [
            {
                "step_id": "research", "capability": "research", "effect": "read",
                "task": "Find evidence", "success_criterion": "Evidence exists",
                "expected_findings": ["evidence"], "depends_on": [], "covers": ["o1"],
            },
            {
                "step_id": "analyse", "capability": "analysis", "effect": "read",
                "task": "Analyse the evidence", "success_criterion": "Analysis uses evidence",
                "expected_findings": ["analysis"], "depends_on": ["research"], "covers": ["o2"],
            },
        ]
    llm = MockLLMClient(responses=[
        {"content": json.dumps({"obligations": obligations})},
        {"content": json.dumps({"steps": steps})},
        {"content": json.dumps({"complete": True, "missing": []})},
    ])
    store = MockRedisContextStore()
    monkeypatch.setattr(Mesh, "_init_redis", lambda self, settings: store)
    monkeypatch.setattr(Mesh, "_init_blob_storage", lambda self, settings: None)
    monkeypatch.setattr(Mesh, "_init_nexus", lambda self: None)
    monkeypatch.setattr(Mesh, "_init_athena", lambda self, settings: None)
    mesh = Mesh(config={"p2p_enabled": False, "distributed_poll_interval": 0.01})
    researcher = mesh.add(ResearchPeer(llm, agent_id="researcher-1"))
    analyst = mesh.add(AnalysisPeer(agent_id="analyst-1"))

    await mesh.start()
    try:
        result = await mesh.execute_goal(
            "Find evidence and analyse it",
            workflow_id="wf-natural-goal",
            context={
                "source_context": {
                    "trigger": "contact_form",
                    "lead": {"email": "lead@example.com"},
                },
            },
            timeout=2,
        )
    finally:
        await mesh.stop()

    assert result["status"] == "completed"
    assert result["result_summary"] == "The evidence was analysed successfully."
    assert [step["status"] for step in result["steps"]] == ["completed", "completed"]
    assert researcher.received[0]["context"]["objective"] == "Find evidence and analyse it"
    assert researcher.received[0]["context"]["source_context"]["lead"]["email"] == (
        "lead@example.com"
    )
    assert analyst.received[0]["context"]["source_context"]["trigger"] == "contact_form"
    assert analyst.received[0]["context"]["previous_step_results"] == {
        "research": {"evidence": ["source-1"]},
    }
    assert analyst.received[0]["context"]["previous_step_interpretations"] == {
        "research": {
            "verdict": "satisfied",
            "meaning": "The required evidence was found.",
            "decision": "proceed",
            "satisfied_requirements": ["Evidence exists"],
            "unmet_requirements": [],
            "evidence_refs": ["source-1"],
        },
    }
    persisted = store.get_workflow_definition("wf-natural-goal")
    assert [step["capability"] for step in persisted["steps"]] == ["research", "analysis"]
    assert all("agent" not in step for step in persisted["steps"])
    events = store.get_ledger_full("wf-natural-goal")
    event_types = [event["event"] for event in events]
    assert event_types.index("goal_registered") < event_types.index("dag_published")
    assert event_types.count("step_claimed") == 2
    assert event_types.count("step_completed") == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("peer_class", "expected_status", "upstream_status"),
    [
        (FailingResearchPeer, "failed", "failed"),
        (WaitingResearchPeer, "waiting", "waiting"),
    ],
)
async def test_execute_goal_propagates_non_success_without_hanging(
    monkeypatch, peer_class, expected_status, upstream_status
):
    llm = MockLLMClient(responses=goal_responses())
    store = MockRedisContextStore()
    monkeypatch.setattr(Mesh, "_init_redis", lambda self, settings: store)
    monkeypatch.setattr(Mesh, "_init_blob_storage", lambda self, settings: None)
    monkeypatch.setattr(Mesh, "_init_nexus", lambda self: None)
    monkeypatch.setattr(Mesh, "_init_athena", lambda self, settings: None)
    mesh = Mesh(config={"p2p_enabled": False, "distributed_poll_interval": 0.01})
    mesh.add(peer_class(llm, agent_id="researcher-1"))
    analyst = mesh.add(AnalysisPeer(agent_id="analyst-1"))

    await mesh.start()
    try:
        result = await mesh.execute_goal(
            "Find evidence and analyse it",
            workflow_id=f"wf-{expected_status}",
            timeout=1,
        )
    finally:
        await mesh.stop()

    assert result["status"] == expected_status
    assert [step["status"] for step in result["steps"]] == [upstream_status, "blocked"]
    assert analyst.received == []


@pytest.mark.asyncio
async def test_waiting_goal_resumes_same_peer_and_unblocks_downstream(monkeypatch):
    llm = MockLLMClient(responses=goal_responses())
    store = MockRedisContextStore()
    monkeypatch.setattr(Mesh, "_init_redis", lambda self, settings: store)
    monkeypatch.setattr(Mesh, "_init_blob_storage", lambda self, settings: None)
    monkeypatch.setattr(Mesh, "_init_nexus", lambda self: None)
    monkeypatch.setattr(Mesh, "_init_athena", lambda self, settings: None)
    mesh = Mesh(config={"p2p_enabled": False, "distributed_poll_interval": 0.01})
    waiting = mesh.add(WaitingResearchPeer(llm, agent_id="researcher-1"))
    analyst = mesh.add(AnalysisPeer(agent_id="analyst-1"))

    await mesh.start()
    try:
        first = await mesh.execute_goal(
            "Find evidence and analyse it",
            workflow_id="wf-resume",
            timeout=1,
        )
        resumed = await mesh.resume_goal(
            "wf-resume",
            "research",
            context={"human_response": "approved"},
            timeout=1,
        )
    finally:
        await mesh.stop()

    assert first["status"] == "waiting"
    assert resumed["status"] == "completed"
    assert waiting.received[1]["context"]["_resume"] is True
    assert waiting.received[1]["context"]["human_response"] == "approved"
    assert analyst.received[0]["context"]["previous_step_results"] == {
        "research": {"evidence": ["approved-source"]},
    }


@pytest.mark.asyncio
async def test_failed_goal_can_be_replanned_under_a_revision_lease(monkeypatch):
    amended_steps = [
        {
            "step_id": "research_v2", "capability": "research", "effect": "read",
            "task": "Retry evidence collection", "success_criterion": "Evidence exists",
            "expected_findings": ["evidence"], "depends_on": [], "covers": ["o1"],
        },
        {
            "step_id": "analyse_v2", "capability": "analysis", "effect": "read",
            "task": "Analyse the replacement evidence",
            "success_criterion": "Analysis uses evidence",
            "expected_findings": ["analysis"], "depends_on": ["research_v2"],
            "covers": ["o2"],
        },
    ]
    llm = MockLLMClient(responses=[
        *goal_responses(),
        {"content": json.dumps({"steps": amended_steps})},
        {"content": json.dumps({"complete": True, "missing": []})},
    ])
    store = MockRedisContextStore()
    monkeypatch.setattr(Mesh, "_init_redis", lambda self, settings: store)
    monkeypatch.setattr(Mesh, "_init_blob_storage", lambda self, settings: None)
    monkeypatch.setattr(Mesh, "_init_nexus", lambda self: None)
    monkeypatch.setattr(Mesh, "_init_athena", lambda self, settings: None)
    mesh = Mesh(config={"p2p_enabled": False, "distributed_poll_interval": 0.01})
    researcher = mesh.add(RecoveringResearchPeer(llm, agent_id="researcher-1"))
    analyst = mesh.add(AnalysisPeer(agent_id="analyst-1"))

    await mesh.start()
    try:
        failed = await mesh.execute_goal(
            "Find evidence and analyse it",
            workflow_id="wf-replan",
            timeout=1,
        )
        recovered = await mesh.replan_goal(
            "wf-replan",
            reason="The first source was unavailable",
            timeout=1,
        )
    finally:
        await mesh.stop()

    assert failed["status"] == "failed"
    assert recovered["status"] == "completed"
    assert recovered["goal"] == "Find evidence and analyse it"
    assert store.get_workflow_definition("wf-replan")["revision"] == 2
    assert researcher.received[1]["task"] == "Retry evidence collection"
    assert analyst.received[0]["context"]["previous_step_results"] == {
        "research_v2": {"evidence": ["source-2"]},
    }
    assert "dag_amended" in [
        event["event"] for event in store.get_ledger_full("wf-replan")
    ]


@pytest.mark.asyncio
async def test_execute_goal_reconciles_actionable_semantic_hold(monkeypatch):
    initial_steps = [{
        "step_id": "locate", "capability": "verification", "effect": "read",
        "task": "Locate and verify usable content", "success_criterion": "Content is verified",
        "expected_findings": ["content verification"], "depends_on": [],
        "covers": ["o0", "o1"],
    }]
    amended_steps = [{
        "step_id": "verify_content", "capability": "verification", "effect": "read",
        "task": "Inspect the located resource and verify its content",
        "success_criterion": "Content is verified by readback",
        "expected_findings": ["content verification"], "depends_on": ["locate"],
        "covers": ["o1"],
    }]
    llm = MockLLMClient(responses=[
        {"content": json.dumps({"obligations": [{
            "id": "o0", "description": "Locate the resource",
            "source_quote": "Locate",
        }, {
            "id": "o1", "description": "Verify usable content",
            "source_quote": "verify usable content",
        }]})},
        {"content": json.dumps({"steps": initial_steps})},
        {"content": json.dumps({"complete": True, "missing": []})},
        {"content": json.dumps({
            "decision": "amend", "reason": "The available verification capability can inspect content.",
        })},
        {"content": json.dumps({"steps": amended_steps})},
        {"content": json.dumps({"complete": True, "missing": []})},
        {"content": json.dumps({
            "decision": "settle_blocked", "reason": "The remaining fact needs human input.",
        })},
    ])
    store = MockRedisContextStore()
    monkeypatch.setattr(Mesh, "_init_redis", lambda self, settings: store)
    monkeypatch.setattr(Mesh, "_init_blob_storage", lambda self, settings: None)
    monkeypatch.setattr(Mesh, "_init_nexus", lambda self: None)
    monkeypatch.setattr(Mesh, "_init_athena", lambda self, settings: None)
    mesh = Mesh(config={
        "p2p_enabled": False,
        "distributed_poll_interval": 0.01,
        "mesh_response_capability": "final_response",
    })
    peer = mesh.add(RemediatingPeer(llm, agent_id="verifier"))
    responder = mesh.add(RevisionResponsePeer(agent_id="responder"))

    await mesh.start()
    try:
        result = await mesh.execute_goal(
            "Locate and verify usable content", workflow_id="wf-auto-reconcile", timeout=2,
        )
    finally:
        await mesh.stop()

    assert result["status"] == "completed"
    assert result["obligation_status"] == "satisfied"
    assert result["response_status"] == "completed"
    assert result["result_summary"] == "Response for revision 2."
    assert len(responder.received) == 2
    assert result["revision"] == 2, (
        store.get_workflow_planning_status("wf-auto-reconcile"),
        [{
            key: event.get(key)
            for key in ("event", "decision", "reason", "error", "revision")
            if event.get(key) is not None
        } for event in store.get_ledger_full("wf-auto-reconcile")
         if "reconcil" in str(event.get("event")) or event.get("event") == "dag_amended"],
    )
    assert [task["id"] for task in peer.received] == ["locate", "verify_content"]
    assert store.get_step_status("wf-auto-reconcile", "locate") == "completed"
    assert store.get_step_status("wf-auto-reconcile", "verify_content") == "completed"
    projection = store.get_obligation_projection("wf-auto-reconcile")
    assert projection["o0"]["current_step_ids"] == ["locate"]
    assert projection["o0"]["superseded_step_ids"] == []
    assert projection["o1"]["current_step_ids"] == ["verify_content"]
    assert projection["o1"]["superseded_step_ids"] == ["locate"]
    events = [event["event"] for event in store.get_ledger_full("wf-auto-reconcile")]
    assert "semantic_reconciliation_requested" in events
    assert "dag_amended" in events
    assert "semantic_reconciliation_settled" in events


@pytest.mark.asyncio
async def test_execute_goal_surfaces_durable_planning_failure_without_timeout(monkeypatch):
    llm = MockLLMClient(responses=[{"content": "not json"}])
    store = MockRedisContextStore()
    monkeypatch.setattr(Mesh, "_init_redis", lambda self, settings: store)
    monkeypatch.setattr(Mesh, "_init_blob_storage", lambda self, settings: None)
    monkeypatch.setattr(Mesh, "_init_nexus", lambda self: None)
    monkeypatch.setattr(Mesh, "_init_athena", lambda self, settings: None)
    mesh = Mesh(config={"p2p_enabled": False, "distributed_poll_interval": 0.01})
    mesh.add(ResearchPeer(llm, agent_id="researcher-1"))

    await mesh.start()
    try:
        with pytest.raises(RuntimeError, match="planning failed.*not valid JSON"):
            await mesh.execute_goal(
                "Find evidence",
                workflow_id="wf-invalid-plan",
                timeout=1,
            )
    finally:
        await mesh.stop()

    assert store.get_workflow_planning_status("wf-invalid-plan")["status"] == "failed"
    assert "wf-invalid-plan" not in store.get_pending_workflow_goals()


@pytest.mark.asyncio
async def test_goal_submitter_need_not_be_the_node_that_compiles_or_executes(monkeypatch):
    llm = MockLLMClient(responses=goal_responses())
    store = MockRedisContextStore()
    monkeypatch.setattr(Mesh, "_init_redis", lambda self, settings: store)
    monkeypatch.setattr(Mesh, "_init_blob_storage", lambda self, settings: None)
    monkeypatch.setattr(Mesh, "_init_nexus", lambda self: None)
    monkeypatch.setattr(Mesh, "_init_athena", lambda self, settings: None)
    config = {"p2p_enabled": False, "distributed_poll_interval": 0.01}
    worker_mesh = Mesh(config=config)
    worker_mesh.add(ResearchPeer(llm, agent_id="researcher-1"))
    worker_mesh.add(AnalysisPeer(agent_id="analyst-1"))
    submitter_mesh = Mesh(config=config)
    submitter_mesh.add(SubmitterPeer, agent_id="submitter-1")

    await worker_mesh.start()
    await submitter_mesh.start()
    try:
        result = await submitter_mesh.execute_goal(
            "Find evidence and analyse it",
            workflow_id="wf-cross-node",
            timeout=2,
        )
    finally:
        await submitter_mesh.stop()
        await worker_mesh.stop()

    assert result["status"] == "completed"
    assert store.get_workflow_planning_status("wf-cross-node")["status"] == "published"


@pytest.mark.asyncio
async def test_independent_mesh_steps_run_concurrently_on_separate_peers(monkeypatch):
    steps = [
        {"step_id": "left", "capability": "left_work", "effect": "read", "task": "Do left", "success_criterion": "Left done", "expected_findings": [], "depends_on": [], "covers": ["o1"]},
        {"step_id": "right", "capability": "right_work", "effect": "read", "task": "Do right", "success_criterion": "Right done", "expected_findings": [], "depends_on": [], "covers": ["o2"]},
    ]
    llm = MockLLMClient(responses=[
        {"content": json.dumps({"obligations": [
            {"id": "o1", "description": "Do left", "source_quote": "Do left"},
            {"id": "o2", "description": "Do right", "source_quote": "do right"},
        ]})},
        {"content": json.dumps({"steps": steps})},
        {"content": json.dumps({"complete": True, "missing": []})},
    ])
    store = MockRedisContextStore()
    monkeypatch.setattr(Mesh, "_init_redis", lambda self, settings: store)
    monkeypatch.setattr(Mesh, "_init_blob_storage", lambda self, settings: None)
    monkeypatch.setattr(Mesh, "_init_nexus", lambda self: None)
    monkeypatch.setattr(Mesh, "_init_athena", lambda self, settings: None)
    mesh = Mesh(config={"p2p_enabled": False, "distributed_poll_interval": 0.01})
    planner = mesh.add(ResearchPeer(llm, agent_id="planner-peer"))
    left = mesh.add(SlowPeer("left_peer", "left_work", "left-1"))
    right = mesh.add(SlowPeer("right_peer", "right_work", "right-1"))

    await mesh.start()
    started = time.perf_counter()
    try:
        result = await mesh.execute_goal(
            "Do left and do right",
            workflow_id="wf-parallel-peers",
            timeout=2,
        )
    finally:
        await mesh.stop()

    assert result["status"] == "completed"
    assert left.started is not None and right.started is not None
    assert abs(left.started - right.started) < 0.05
    assert time.perf_counter() - started < 0.3
    assert planner.received == []


@pytest.mark.asyncio
async def test_hold_blocks_multi_system_effects_but_final_response_still_runs(monkeypatch):
    store = MockRedisContextStore()
    monkeypatch.setattr(Mesh, "_init_redis", lambda self, settings: store)
    monkeypatch.setattr(Mesh, "_init_blob_storage", lambda self, settings: None)
    monkeypatch.setattr(Mesh, "_init_nexus", lambda self: None)
    monkeypatch.setattr(Mesh, "_init_athena", lambda self, settings: None)
    mesh = Mesh(config={"p2p_enabled": False, "distributed_poll_interval": 0.01})
    mesh.add(HoldingPeer, agent_id="verifier")
    mesh.add(CollateralPeer, agent_id="collateral")
    writer = mesh.add(WritePeer, agent_id="writer")
    notifier = mesh.add(NotifyPeer, agent_id="notifier")
    responder = mesh.add(ResponsePeer, agent_id="responder")

    await mesh.start()
    store.publish_workflow(
        "wf-hold-gate",
        goal="Verify identity before writing",
        obligations=[],
        steps=[
            {
                "id": "verify", "capability": "verification", "effect": "read",
                "systems": ["hubspot"], "task": "Verify identity", "depends_on": [],
            },
            {
                "id": "collateral", "capability": "sales_collateral",
                "effect": "read", "systems": ["google_drive"],
                "task": "Find collateral", "depends_on": [],
            },
            {
                "id": "write", "capability": "external_write", "effect": "write",
                "systems": ["hubspot"], "task": "Perform write",
                "depends_on": ["verify"],
            },
            {
                "id": "notify", "capability": "team_notification", "effect": "notify",
                "systems": ["slack"], "task": "Notify the team",
                "depends_on": ["verify", "write"],
            },
            {
                "id": "respond", "capability": "final_response",
                "effect": "final_response", "task": "Explain outcome",
                "depends_on": ["verify", "write", "notify"],
            },
        ],
    )
    try:
        result = await mesh.execute_goal(
            "Verify identity before writing", workflow_id="wf-hold-gate", timeout=1,
        )
    finally:
        await mesh.stop()

    assert result["status"] == "completed"
    assert result["result_summary"] == (
        "Identity was not verified, so no external write was performed."
    )
    assert store.get_step_status("wf-hold-gate", "write") == "blocked"
    assert store.get_step_status("wf-hold-gate", "notify") == "blocked"
    assert writer.received == []
    assert notifier.received == []
    assert len(responder.received) == 1
    final_context = responder.received[0]["context"]
    assert final_context["previous_step_results"]["collateral"] == {
        "document_id": "deck-1", "status": "existing",
    }
    assert final_context["workflow_step_states"]["collateral"] == "completed"
    assert final_context["workflow_step_states"]["write"] == "blocked"
    assert final_context["workflow_evidence"]["artifacts"]["collateral"] == {
        "document_id": "deck-1", "status": "existing",
    }
    assert final_context["workflow_evidence"]["states"]["write"] == "blocked"
    assert responder.received[0]["context"]["previous_step_interpretations"]["verify"][
        "decision"
    ] == "hold"
    persisted = store.get_workflow_definition("wf-hold-gate")
    assert [
        (step["capability"], step["effect"], step.get("systems", []))
        for step in persisted["steps"]
    ] == [
        ("verification", "read", ["hubspot"]),
        ("sales_collateral", "read", ["google_drive"]),
        ("external_write", "write", ["hubspot"]),
        ("team_notification", "notify", ["slack"]),
        ("final_response", "final_response", []),
    ]
    assert all("agent" not in step and "atom" not in step for step in persisted["steps"])


@pytest.mark.asyncio
async def test_failed_final_response_does_not_erase_satisfied_obligations(monkeypatch):
    store = MockRedisContextStore()
    monkeypatch.setattr(Mesh, "_init_redis", lambda self, settings: store)
    monkeypatch.setattr(Mesh, "_init_blob_storage", lambda self, settings: None)
    monkeypatch.setattr(Mesh, "_init_nexus", lambda self: None)
    monkeypatch.setattr(Mesh, "_init_athena", lambda self, settings: None)
    mesh = Mesh(config={"p2p_enabled": False, "distributed_poll_interval": 0.01})
    mesh.add(SubmitterPeer, agent_id="worker")
    mesh.add(FailingResponsePeer, agent_id="responder")

    await mesh.start()
    store.publish_workflow(
        "wf-response-failure",
        goal="Submit work and report it",
        obligations=[{
            "id": "o1", "description": "Submit work", "source_quote": "Submit work",
        }],
        steps=[
            {
                "id": "submit", "capability": "submission", "effect": "write",
                "systems": ["provider"], "task": "Submit work", "depends_on": [],
                "covers": ["o1"],
            },
            {
                "id": "respond", "capability": "final_response",
                "effect": "final_response", "systems": [], "task": "Report outcome",
                "depends_on": ["submit"], "covers": [],
            },
        ],
    )
    try:
        result = await mesh.execute_goal(
            "Submit work and report it", workflow_id="wf-response-failure", timeout=1,
        )
    finally:
        await mesh.stop()

    assert result["status"] == "failed"
    assert result["obligation_status"] == "satisfied"
    assert result["response_status"] == "failed"
    assert result["result_summary"] == ""


@pytest.mark.asyncio
async def test_reasoning_recipient_authorizes_unrelated_partial_dependency(monkeypatch):
    store = MockRedisContextStore()
    monkeypatch.setattr(Mesh, "_init_redis", lambda self, settings: store)
    monkeypatch.setattr(Mesh, "_init_blob_storage", lambda self, settings: None)
    monkeypatch.setattr(Mesh, "_init_nexus", lambda self: None)
    monkeypatch.setattr(Mesh, "_init_athena", lambda self, settings: None)
    llm = MockLLMClient(responses=[{
        "content": json.dumps({
            "decision": "allow",
            "reason": "Duplicate cleanup is unrelated to calendar scheduling.",
        }),
    }])
    mesh = Mesh(config={"p2p_enabled": False, "distributed_poll_interval": 0.01})
    mesh.add(PartialContactPeer, agent_id="partial-contact")
    writer = mesh.add(EdgeAwareWritePeer(llm), agent_id="edge-writer")

    await mesh.start()
    store.publish_workflow(
        "wf-edge-aware",
        goal="Schedule from a verified contact",
        obligations=[],
        steps=[
            {
                "id": "verify", "capability": "partial_contact", "effect": "read",
                "task": "Verify contact", "depends_on": [],
            },
            {
                "id": "write", "capability": "edge_aware_write", "effect": "write",
                "task": "Schedule using the verified contact", "depends_on": ["verify"],
            },
        ],
    )
    try:
        result = await mesh.execute_goal(
            "Schedule from a verified contact",
            workflow_id="wf-edge-aware",
            timeout=1,
        )
    finally:
        await mesh.stop()

    assert result["status"] == "completed"
    assert len(writer.received) == 1


@pytest.mark.asyncio
async def test_reasoning_recipient_must_work_a_relevant_dependency_gap(monkeypatch):
    store = MockRedisContextStore()
    monkeypatch.setattr(Mesh, "_init_redis", lambda self, settings: store)
    monkeypatch.setattr(Mesh, "_init_blob_storage", lambda self, settings: None)
    monkeypatch.setattr(Mesh, "_init_nexus", lambda self: None)
    monkeypatch.setattr(Mesh, "_init_athena", lambda self, settings: None)
    llm = MockLLMClient(responses=[{
        "content": json.dumps({
            "decision": "block",
            "reason": "A required detail is unresolved; attempt resolution.",
        }),
    }])
    mesh = Mesh(config={"p2p_enabled": False, "distributed_poll_interval": 0.01})
    mesh.add(PartialContactPeer, agent_id="partial-contact")
    writer = mesh.add(EdgeAwareWritePeer(llm), agent_id="edge-writer")
    await mesh.start()
    store.publish_workflow(
        "wf-edge-gap",
        goal="Resolve then act",
        obligations=[],
        steps=[
            {
                "id": "verify", "capability": "partial_contact", "effect": "read",
                "task": "Verify contact", "depends_on": [],
            },
            {
                "id": "write", "capability": "edge_aware_write", "effect": "write",
                "task": "Resolve remaining detail and act", "depends_on": ["verify"],
            },
        ],
    )
    try:
        result = await mesh.execute_goal(
            "Resolve then act", workflow_id="wf-edge-gap", timeout=1
        )
    finally:
        await mesh.stop()

    assert result["status"] == "completed"
    assert len(writer.received) == 1
    assert writer.received[0]["context"]["dependency_authorization"] == {
        "decision": "block",
        "reason": "A required detail is unresolved; attempt resolution.",
    }


@pytest.mark.asyncio
async def test_capability_need_is_claimed_fulfilled_and_returned_to_requester(monkeypatch):
    store = MockRedisContextStore()
    monkeypatch.setattr(Mesh, "_init_redis", lambda self, settings: store)
    monkeypatch.setattr(Mesh, "_init_blob_storage", lambda self, settings: None)
    monkeypatch.setattr(Mesh, "_init_nexus", lambda self: None)
    monkeypatch.setattr(Mesh, "_init_athena", lambda self, settings: None)
    mesh = Mesh(config={"p2p_enabled": False, "distributed_poll_interval": 0.01})
    requester = mesh.add(NeedRequesterPeer, agent_id="requester-1")
    resolver = mesh.add(NeedResolverPeer, agent_id="resolver-1")

    await mesh.start()
    try:
        response = await asyncio.wait_for(
            requester.peers.as_tool().execute(
                "ask_capability",
                {
                    "capability": "contact_verification",
                    "question": "Resolve Ephy Kizito's contact path.",
                    "timeout": 2,
                },
                context={
                    "workflow_id": "wf-capability-need",
                    "objective": "Prepare the customer meeting",
                    "peer_requester_step_id": "schedule",
                },
            ),
            timeout=3,
        )
    finally:
        await mesh.stop()

    assert "ephy@example.com" in response
    assert len(resolver.received) == 1
    resolver_context = resolver.received[0]["context"]
    assert resolver_context["capability"] == "contact_verification"
    assert resolver_context["effect"] == "read"
    assert resolver_context["systems"] == ["gmail", "hubspot"]
    events = [item["event"] for item in store.get_ledger_tail("wf-capability-need")]
    assert events == [
        "capability_need_published",
        "capability_need_claimed",
        "capability_need_fulfilled",
    ]


@pytest.mark.asyncio
async def test_cancelling_execute_goal_tombstones_shared_workflow(monkeypatch):
    store = MockRedisContextStore()
    monkeypatch.setattr(Mesh, "_init_redis", lambda self, settings: store)
    monkeypatch.setattr(Mesh, "_init_blob_storage", lambda self, settings: None)
    monkeypatch.setattr(Mesh, "_init_nexus", lambda self: None)
    monkeypatch.setattr(Mesh, "_init_athena", lambda self, settings: None)
    mesh = Mesh(config={"p2p_enabled": False, "distributed_poll_interval": 0.01})
    mesh.add(SubmitterPeer, agent_id="submitter")

    await mesh.start()
    store.publish_workflow(
        "wf-cancel-goal",
        goal="Wait for unavailable work",
        obligations=[],
        steps=[{
            "id": "unavailable", "capability": "missing", "effect": "write",
            "task": "Never claimed", "depends_on": [],
        }],
    )
    task = asyncio.create_task(mesh.execute_goal(
        "Wait for unavailable work", workflow_id="wf-cancel-goal", timeout=5,
    ))
    await asyncio.sleep(0.03)
    task.cancel()
    try:
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        await mesh.stop()

    assert store.is_workflow_cancelled("wf-cancel-goal") is True
    assert store.get_step_status("wf-cancel-goal", "unavailable") == "cancelled"
    assert "wf-cancel-goal" not in store.get_active_workflows()