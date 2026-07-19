"""
Tests for the long-horizon planning architecture.

What these tests prove:
  PLANNING CONTRACTS
  - GoalExecution initialises correctly and tracking properties work
  - PlannedStep.to_context_extras() produces the right dict
  - StepEvaluation verdict flags work (passed, needs_replan, needs_hitl)
  - record_completed() merges distilled facts + evaluator findings into truth
  - context_for_next_step() passes structured facts, not str()'d text
  - GoalExecution.to_summary_dict() / to_full_dict() are correct

  PLANNER
  - _parse_plan() accepts a raw JSON array
  - _parse_plan() accepts wrapped {"steps": [...]} response
  - _parse_plan() strips markdown fences if present
  - _parse_plan() raises PlannerError for invalid JSON
  - _parse_plan() raises PlannerError for missing required fields
  - _parse_plan() raises PlannerError for empty plan
  - subagent_hint "null" / None → normalised to None; unknown hints fail fast
  - step_id is auto-generated when missing

  STEP EVALUATOR
  - evaluate() short-circuits on output.status == "failure" without LLM call
  - evaluate() short-circuits on output.status == "yield" without LLM call
  - _parse_evaluation() accepts valid verdict and populates StepEvaluation
  - _parse_evaluation() raises EvaluatorError for invalid JSON
  - _parse_evaluation() raises EvaluatorError for bad verdict value
  - _parse_evaluation() clamps confidence to [0.0, 1.0]

  SCRATCHPAD SCOPE CHANGES (backward compatibility + new behaviour)
  - write() with no scope defaults to "step"
  - write() with scope="goal" stores the scope field
  - goal_scoped_entries() returns only scope="goal" entries
  - get_notes() returns only goal-scoped entries (no step-scoped noise)
  - promote_to_truth() merges goal-scoped entries into TruthContext
  - promote_to_truth() is a no-op when no goal-scoped entries exist

  KERNEL DISTILLATION WIRING
  - AgentOutput.distilled_facts() returns empty dict when metadata is empty
  - AgentOutput.distilled_facts() returns the dict from metadata
"""
import json
from unittest.mock import AsyncMock, MagicMock

import pytest

pytestmark = pytest.mark.asyncio

from jarviscore.context.truth import AgentOutput, TruthContext
from jarviscore.planning.evaluator import EvaluatorError, StepEvaluator
from jarviscore.planning.goal_context import (
    CompletedStep,
    GoalExecution,
    PlannedStep,
    StepEvaluation,
)
from jarviscore.planning.planner import PlannerError, Planner


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_output(status="success", payload=None, summary="done", metadata=None):
    return AgentOutput(
        status=status,
        payload=payload or {"result": "ok"},
        summary=summary,
        metadata=metadata or {},
    )


def _make_step(step_id="step_01", task="Do X", criterion="X is done"):
    return PlannedStep(
        step_id=step_id,
        task=task,
        success_criterion=criterion,
        expected_findings=["fact_a"],
        subagent_hint="researcher",
    )


def _make_evaluation(verdict="pass", confidence=0.9, note="Looks good", additional_findings=None):
    return StepEvaluation(
        verdict=verdict,
        confidence=confidence,
        evaluator_note=note,
        additional_findings=additional_findings or {"discovered_key": "discovered_value"},
    )


# ── GoalExecution contracts ───────────────────────────────────────────────────

class TestGoalExecution:

    def test_initialises_with_defaults(self):
        ge = GoalExecution(goal="Do something big", agent_id="agent-1")
        assert ge.status == "planning"
        assert ge.plan == []
        assert ge.completed == []
        assert isinstance(ge.truth, TruthContext)
        assert ge.goal_id.startswith("goal-")
        assert ge.plan_revision == 0

    def test_remaining_steps_excludes_completed(self):
        ge = GoalExecution(goal="G", agent_id="a")
        s1 = _make_step("s1")
        s2 = _make_step("s2")
        s3 = _make_step("s3")
        ge.plan = [s1, s2, s3]
        ev = _make_evaluation()
        out = _make_output()
        ge.record_completed(s1, out, ev, elapsed_ms=100.0)
        remaining = ge.remaining_steps
        assert len(remaining) == 2
        assert all(s.step_id != "s1" for s in remaining)

    def test_is_done_for_terminal_statuses(self):
        for status in ("complete", "failed", "blocked", "hitl"):
            ge = GoalExecution(goal="G", agent_id="a")
            ge.status = status
            assert ge.is_done is True

    def test_is_done_false_for_active_statuses(self):
        for status in ("planning", "executing"):
            ge = GoalExecution(goal="G", agent_id="a")
            ge.status = status
            assert ge.is_done is False

    def test_context_for_next_step_keys(self):
        ge = GoalExecution(goal="Analyse market", agent_id="researcher")
        ctx = ge.context_for_next_step(base_context={"auth": "token123"})
        # Base context preserved
        assert ctx["auth"] == "token123"
        # Goal context injected
        assert ctx["_goal"] == "Analyse market"
        assert "_goal_facts" in ctx
        assert "_goal_facts_high_confidence" in ctx
        assert "_completed_steps" in ctx
        assert "_plan_revision" in ctx

    def test_context_for_next_step_facts_are_dict_not_string(self):
        """The core fix: structured facts cross step boundaries, not str()."""
        ge = GoalExecution(goal="G", agent_id="a")
        # Manually add a fact
        from jarviscore.context.truth import TruthFact
        ge.truth.facts["api_auth"] = TruthFact(
            value="oauth2", source="step_01", confidence=0.95
        )
        ctx = ge.context_for_next_step()
        # Must be a dict, not a str()'d 500-char fragment
        assert isinstance(ctx["_goal_facts"], dict)
        assert ctx["_goal_facts"]["api_auth"] == "oauth2"

    def test_record_completed_increments_completed_list(self):
        ge = GoalExecution(goal="G", agent_id="a")
        step = _make_step()
        out = _make_output(
            metadata={"distilled_facts": {
                "result": {"value": "ok", "confidence": 0.8, "source": "step_01",
                           "version": 1, "updated_at": "2024-01-01T00:00:00", "evidence": []}
            }}
        )
        ev = _make_evaluation(additional_findings={"extra_key": "extra_value"})
        ge.record_completed(step, out, ev, elapsed_ms=250.0)
        assert len(ge.completed) == 1
        assert ge.completed[0].step.step_id == "step_01"
        assert ge.completed[0].elapsed_ms == 250.0

    def test_to_summary_dict_keys(self):
        ge = GoalExecution(goal="Test goal", agent_id="a")
        d = ge.to_summary_dict()
        for key in ("goal_id", "goal", "status", "steps_completed",
                    "plan_revision", "elapsed_ms", "fact_count"):
            assert key in d, f"Missing key: {key}"


class TestPlannedStep:

    def test_to_context_extras_with_hint(self):
        step = _make_step()
        extras = step.to_context_extras()
        assert extras["step_id"] == "step_01"
        assert extras["_success_criterion"] == "X is done"
        assert extras["_expected_findings"] == ["fact_a"]
        assert extras["_agent_default_kernel_role"] == "researcher"

    def test_to_context_extras_no_hint(self):
        step = PlannedStep(
            step_id="s2", task="Do Y", success_criterion="Y done"
        )
        extras = step.to_context_extras()
        # No subagent_hint → key should not be in extras
        assert "_agent_default_kernel_role" not in extras


class TestStepEvaluation:

    def test_passed_for_pass_and_partial(self):
        assert StepEvaluation(verdict="pass", confidence=0.9, evaluator_note="").passed
        assert StepEvaluation(verdict="partial", confidence=0.9, evaluator_note="").passed

    def test_needs_replan_for_fail(self):
        assert StepEvaluation(verdict="fail", confidence=0.2, evaluator_note="").needs_replan

    def test_needs_hitl(self):
        assert StepEvaluation(verdict="hitl", confidence=0.5, evaluator_note="").needs_hitl

    def test_not_needs_replan_for_pass(self):
        assert not StepEvaluation(verdict="pass", confidence=0.9, evaluator_note="").needs_replan


# ── Planner._parse_plan() ─────────────────────────────────────────────────────

class TestPlannerParsePlan:

    def _planner(self):
        return Planner(llm_client=None)

    def _valid_step_dict(self, step_id="step_01"):
        return {
            "step_id": step_id,
            "task": "Research the topic",
            "success_criterion": "3+ sources found",
            "expected_findings": ["source_count"],
            "subagent_hint": "researcher",
        }

    def test_parses_raw_json_array(self):
        p = self._planner()
        raw = json.dumps([self._valid_step_dict()])
        steps = p._parse_plan(raw, "test goal")
        assert len(steps) == 1
        assert steps[0].step_id == "step_01"
        assert steps[0].task == "Research the topic"
        assert steps[0].subagent_hint == "researcher"

    def test_parses_wrapped_steps_object(self):
        p = self._planner()
        raw = json.dumps({"steps": [self._valid_step_dict()]})
        steps = p._parse_plan(raw, "test goal")
        assert len(steps) == 1

    def test_parses_wrapped_plan_key(self):
        p = self._planner()
        raw = json.dumps({"plan": [self._valid_step_dict()]})
        steps = p._parse_plan(raw, "test goal")
        assert len(steps) == 1

    def test_strips_markdown_fences(self):
        p = self._planner()
        raw = "```json\n" + json.dumps([self._valid_step_dict()]) + "\n```"
        steps = p._parse_plan(raw, "test goal")
        assert len(steps) == 1

    def test_null_subagent_hint_normalised(self):
        p = self._planner()
        d = self._valid_step_dict()
        d["subagent_hint"] = "null"
        steps = p._parse_plan(json.dumps([d]), "goal")
        assert steps[0].subagent_hint is None

    def test_unknown_subagent_hint_raises(self):
        p = self._planner()
        d = self._valid_step_dict()
        d["subagent_hint"] = "wizard"
        with pytest.raises(PlannerError, match="invalid subagent_hint"):
            p._parse_plan(json.dumps([d]), "goal")

    def test_missing_step_id_autogenerated(self):
        p = self._planner()
        d = self._valid_step_dict()
        del d["step_id"]
        steps = p._parse_plan(json.dumps([d]), "goal")
        assert steps[0].step_id  # non-empty

    def test_raises_planner_error_for_invalid_json(self):
        p = self._planner()
        with pytest.raises(PlannerError, match="not valid JSON"):
            p._parse_plan("this is not json at all", "goal")

    def test_raises_for_missing_task_field(self):
        p = self._planner()
        d = {"step_id": "s1", "success_criterion": "done"}
        with pytest.raises(PlannerError, match="missing required field 'task'"):
            p._parse_plan(json.dumps([d]), "goal")

    def test_raises_for_missing_success_criterion(self):
        p = self._planner()
        d = {"step_id": "s1", "task": "Do something"}
        with pytest.raises(PlannerError, match="missing required field 'success_criterion'"):
            p._parse_plan(json.dumps([d]), "goal")

    def test_raises_for_empty_plan(self):
        p = self._planner()
        with pytest.raises(PlannerError, match="empty plan"):
            p._parse_plan(json.dumps([]), "my goal")

    def test_raises_for_object_with_no_array_key(self):
        p = self._planner()
        with pytest.raises(PlannerError, match="no recognisable steps array"):
            p._parse_plan(json.dumps({"foo": "bar"}), "goal")

    def test_multiple_steps_parsed_in_order(self):
        p = self._planner()
        steps_raw = [
            self._valid_step_dict("step_01"),
            self._valid_step_dict("step_02"),
            self._valid_step_dict("step_03"),
        ]
        steps = p._parse_plan(json.dumps(steps_raw), "goal")
        assert [s.step_id for s in steps] == ["step_01", "step_02", "step_03"]


# ── StepEvaluator ─────────────────────────────────────────────────────────────

class TestStepEvaluator:

    def _evaluator(self):
        return StepEvaluator(llm_client=None)

    @pytest.mark.asyncio
    async def test_short_circuits_failure_status(self):
        """No LLM call on output.status == 'failure'."""
        ev = self._evaluator()
        out = _make_output(status="failure", summary="sandbox blew up")
        ge = GoalExecution(goal="G", agent_id="a")
        result = await ev.evaluate(_make_step(), out, ge)
        assert result.verdict == "fail"
        assert result.confidence >= 0.9
        assert "sandbox blew up" in result.evaluator_note

    @pytest.mark.asyncio
    async def test_short_circuits_yield_status(self):
        """No LLM call on output.status == 'yield'."""
        ev = self._evaluator()
        out = _make_output(status="yield", summary="needs HITL")
        ge = GoalExecution(goal="G", agent_id="a")
        result = await ev.evaluate(_make_step(), out, ge)
        assert result.verdict == "hitl"
        assert result.confidence >= 0.9

    @pytest.mark.asyncio
    async def test_evaluate_repairs_invalid_verdict_contract_once(self):
        """The evaluator repairs schema drift without aliasing invalid enums."""
        llm = MagicMock()
        llm.nano_model = None
        llm.generate = AsyncMock(side_effect=[
            {
                "content": json.dumps({
                    "verdict": "success",
                    "confidence": 0.93,
                    "evaluator_note": "Criterion is met.",
                    "additional_findings": {},
                })
            },
            {
                "content": json.dumps({
                    "verdict": "pass",
                    "confidence": 0.93,
                    "evaluator_note": "Criterion is met.",
                    "additional_findings": {},
                })
            },
        ])
        ev = StepEvaluator(llm_client=llm)
        result = await ev.evaluate(_make_step(), _make_output(), GoalExecution(goal="G", agent_id="a"))
        assert result.verdict == "pass"
        assert llm.generate.await_count == 2
        repair_prompt = llm.generate.await_args_list[1].kwargs["messages"][0]["content"]
        assert "violated the required contract" in repair_prompt

    def test_parse_evaluation_valid(self):
        ev = self._evaluator()
        raw = json.dumps({
            "verdict": "pass",
            "confidence": 0.85,
            "evaluator_note": "criterion met",
            "additional_findings": {"row_count": "1200"},
        })
        result = ev._parse_evaluation(raw, _make_step())
        assert result.verdict == "pass"
        assert result.confidence == 0.85
        assert result.evaluator_note == "criterion met"
        assert result.additional_findings == {"row_count": "1200"}

    def test_parse_evaluation_partial(self):
        ev = self._evaluator()
        raw = json.dumps({
            "verdict": "partial",
            "confidence": 0.6,
            "evaluator_note": "some data missing",
            "additional_findings": {},
        })
        result = ev._parse_evaluation(raw, _make_step())
        assert result.verdict == "partial"

    def test_parse_evaluation_accepts_nested_success_criterion_shape(self):
        ev = self._evaluator()
        raw = json.dumps({
            "evaluation": {
                "success_criterion_met": "partial",
                "reason": [
                    "The output covers the decision.",
                    "The workflow artifact is still missing.",
                ],
            }
        })

        result = ev._parse_evaluation(raw, _make_step())

        assert result.verdict == "partial"
        assert result.confidence == 0.7
        assert "workflow artifact is still missing" in result.evaluator_note

    def test_parse_evaluation_accepts_status_reason_shape(self):
        ev = self._evaluator()
        raw = json.dumps({
            "status": "fail",
            "reason": "The output did not include the required decision log.",
        })

        result = ev._parse_evaluation(raw, _make_step())

        assert result.verdict == "fail"
        assert "decision log" in result.evaluator_note

    def test_parse_evaluation_accepts_top_level_success_criterion_shape(self):
        ev = self._evaluator()
        raw = json.dumps({
            "success_criterion_met": False,
            "evaluation": "No calendar invite evidence was provided.",
            "confidence": 0.8,
        })

        result = ev._parse_evaluation(raw, _make_step())

        assert result.verdict == "fail"
        assert "calendar invite" in result.evaluator_note

    def test_parse_evaluation_strips_fences(self):
        ev = self._evaluator()
        inner = json.dumps({
            "verdict": "pass", "confidence": 0.9,
            "evaluator_note": "ok", "additional_findings": {}
        })
        raw = f"```json\n{inner}\n```"
        result = ev._parse_evaluation(raw, _make_step())
        assert result.verdict == "pass"

    def test_parse_evaluation_clamps_confidence_above_1(self):
        ev = self._evaluator()
        raw = json.dumps({
            "verdict": "pass", "confidence": 1.5,
            "evaluator_note": "ok", "additional_findings": {}
        })
        result = ev._parse_evaluation(raw, _make_step())
        assert result.confidence == 1.0

    def test_parse_evaluation_clamps_confidence_below_0(self):
        ev = self._evaluator()
        raw = json.dumps({
            "verdict": "fail", "confidence": -0.5,
            "evaluator_note": "bad", "additional_findings": {}
        })
        result = ev._parse_evaluation(raw, _make_step())
        assert result.confidence == 0.0

    def test_parse_evaluation_raises_for_invalid_json(self):
        ev = self._evaluator()
        with pytest.raises(EvaluatorError, match="not valid JSON"):
            ev._parse_evaluation("not json", _make_step())

    def test_parse_evaluation_raises_for_bad_verdict(self):
        ev = self._evaluator()
        raw = json.dumps({
            "verdict": "maybe", "confidence": 0.5,
            "evaluator_note": "hmm", "additional_findings": {}
        })
        with pytest.raises(EvaluatorError, match="invalid verdict"):
            ev._parse_evaluation(raw, _make_step())

    def test_parse_evaluation_empty_findings_ok(self):
        ev = self._evaluator()
        raw = json.dumps({
            "verdict": "pass", "confidence": 0.8,
            "evaluator_note": "ok", "additional_findings": {}
        })
        result = ev._parse_evaluation(raw, _make_step())
        assert result.additional_findings == {}


# ── Scratchpad scope changes ──────────────────────────────────────────────────

class MockBlobStorage:
    """Minimal in-memory blob for scratchpad tests."""
    def __init__(self):
        self._store = {}

    async def read(self, path):
        return self._store.get(path)

    async def save(self, path, data):
        self._store[path] = data


class TestScratchpadScope:

    def _pad(self):
        from jarviscore.memory.scratchpad import WorkingScratchpad
        return WorkingScratchpad(MockBlobStorage(), "wf-1", "step1", "analyst")

    @pytest.mark.asyncio
    async def test_default_scope_is_step(self):
        pad = self._pad()
        await pad.write("thought", {"content": "thinking"})
        entries = await pad.read_all()
        assert entries[0]["scope"] == "step"

    @pytest.mark.asyncio
    async def test_explicit_scope_goal_stored(self):
        pad = self._pad()
        await pad.write("finding", {"content": "API uses OAuth2"}, scope="goal")
        entries = await pad.read_all()
        assert entries[0]["scope"] == "goal"

    @pytest.mark.asyncio
    async def test_mixed_scope_separation(self):
        pad = self._pad()
        await pad.write("thought", {"content": "noise"}, scope="step")
        await pad.write("finding", {"content": "api_key=sha256"}, scope="goal")
        await pad.write("attempt", {"content": "failed attempt"}, scope="step")

        goal_entries = await pad.goal_scoped_entries()
        all_entries = await pad.read_all()
        assert len(all_entries) == 3
        assert len(goal_entries) == 1
        assert goal_entries[0]["content"] == "api_key=sha256"

    @pytest.mark.asyncio
    async def test_get_notes_returns_only_goal_scoped(self):
        pad = self._pad()
        await pad.write("thought", {"content": "tactical noise"}, scope="step")
        await pad.write("finding", {"content": "critical api auth discovery"}, scope="goal")

        notes = await pad.get_notes()
        assert "critical api auth discovery" in notes
        assert "tactical noise" not in notes

    @pytest.mark.asyncio
    async def test_get_notes_empty_when_no_goal_scoped(self):
        pad = self._pad()
        await pad.write("thought", {"content": "step noise"}, scope="step")
        notes = await pad.get_notes()
        assert notes == ""

    @pytest.mark.asyncio
    async def test_promote_to_truth_merges_goal_entries(self):
        pad = self._pad()
        await pad.write("finding", {"content": "auth_method=oauth2"}, scope="goal")
        await pad.write("finding", {"content": "base_url=https://api.example.com"}, scope="goal")
        await pad.write("noise", {"content": "404 not found"}, scope="step")

        truth = TruthContext()
        updated = await pad.promote_to_truth(truth, source="step1")
        # Truth should have facts from goal-scoped entries
        assert len(updated.facts) >= 1

    @pytest.mark.asyncio
    async def test_promote_to_truth_noop_when_no_goal_entries(self):
        pad = self._pad()
        await pad.write("thought", {"content": "only step-scoped"}, scope="step")

        truth = TruthContext()
        original_version = truth.version
        updated = await pad.promote_to_truth(truth, source="step1")
        # Nothing should have changed
        assert updated.version == original_version
        assert len(updated.facts) == 0


# ── AgentOutput.distilled_facts() ────────────────────────────────────────────

class TestAgentOutputDistilledFacts:

    def test_returns_empty_dict_when_no_metadata(self):
        out = AgentOutput(status="success", payload="done")
        assert out.distilled_facts() == {}

    def test_returns_empty_dict_when_metadata_has_no_key(self):
        out = AgentOutput(status="success", metadata={"tokens": {"input": 10}})
        assert out.distilled_facts() == {}

    def test_returns_facts_when_present(self):
        facts = {
            "api_url": {"value": "https://api.example.com", "confidence": 0.9,
                        "source": "step1", "version": 1, "updated_at": "now", "evidence": []}
        }
        out = AgentOutput(status="success", metadata={"distilled_facts": facts})
        result = out.distilled_facts()
        assert result["api_url"]["value"] == "https://api.example.com"

    def test_failure_output_has_no_facts(self):
        out = AgentOutput(status="failure", summary="error occurred")
        assert out.distilled_facts() == {}


# ── Issue #73: goal persistence & resume ──────────────────────────────────────

class TestGoalSnapshotRoundTrip:

    def _executed_goal(self):
        ge = GoalExecution(goal="Analyse the market", agent_id="analyst-1")
        ge.plan = [_make_step("step_01"), _make_step("step_02", task="Do Y")]
        ge.plan_revision = 1
        ge.status = "executing"
        from jarviscore.context.truth import TruthFact
        ge.truth.facts["api_auth"] = TruthFact(
            value="oauth2", source="step_01", confidence=0.95
        )
        ge.record_completed(
            ge.plan[0],
            _make_output(summary="found the auth method"),
            _make_evaluation(verdict="pass"),
            elapsed_ms=120.0,
        )
        return ge

    def test_full_dict_is_json_safe_and_carries_the_plan(self):
        import json
        ge = self._executed_goal()
        data = json.loads(json.dumps(ge.to_full_dict(), default=str))
        assert [s["step_id"] for s in data["plan"]] == ["step_01", "step_02"]
        assert "truth_facts_full" in data
        assert data["completed_steps"][0]["summary"] == "found the auth method"

    def test_snapshot_round_trip_restores_plan_facts_and_history(self):
        import json
        ge = self._executed_goal()
        data = json.loads(json.dumps(ge.to_full_dict(), default=str))

        restored = GoalExecution.from_snapshot(data)

        assert restored.goal == "Analyse the market"
        assert restored.goal_id == ge.goal_id
        assert restored.agent_id == "analyst-1"
        assert [s.step_id for s in restored.plan] == ["step_01", "step_02"]
        assert restored.plan_revision == 1
        # Facts survive with value + confidence
        assert restored.truth.facts["api_auth"].value == "oauth2"
        assert restored.truth.facts["api_auth"].confidence == pytest.approx(0.95)
        # History survives as duck-typed completed steps
        assert len(restored.completed) == 1
        cs = restored.completed[0]
        assert cs.step.step_id == "step_01"
        assert cs.evaluation.verdict == "pass"
        assert cs.to_summary()["summary"] == "found the auth method"

    def test_resumed_context_chains_into_next_step(self):
        """The restored execution feeds context_for_next_step correctly."""
        import json
        ge = self._executed_goal()
        restored = GoalExecution.from_snapshot(
            json.loads(json.dumps(ge.to_full_dict(), default=str))
        )
        ctx = restored.context_for_next_step()
        assert ctx["_goal_facts"]["api_auth"] == "oauth2"
        assert ctx["_completed_steps"][0]["step_id"] == "step_01"

    def test_planned_step_round_trip(self):
        step = _make_step()
        restored = PlannedStep.from_dict(step.to_dict())
        assert restored == step

    def test_bad_fact_is_skipped_not_fatal(self):
        data = {
            "goal": "G", "agent_id": "a", "goal_id": "goal-x",
            "plan": [], "plan_revision": 0, "status": "executing",
            "truth_facts_full": {"broken": {"not_a_fact_field": 1}},
            "completed_steps": [],
        }
        restored = GoalExecution.from_snapshot(data)
        assert "broken" not in restored.truth.facts


# ── Issue #74: planner robustness ─────────────────────────────────────────────

class _PlanLLM:
    """Captures the prompt; returns a canned plan JSON."""

    def __init__(self, plan_json):
        self._plan_json = plan_json
        self.prompts = []

    async def generate(self, **kwargs):
        self.prompts.append(kwargs["messages"][0]["content"])
        return {"content": self._plan_json}


def _step_json(step_id, depends_on=None):
    import json
    return {
        "step_id": step_id,
        "task": f"do {step_id}",
        "success_criterion": "done",
        "expected_findings": [],
        "depends_on": depends_on or [],
        "subagent_hint": None,
    }


class TestPlanValidation:

    @pytest.mark.asyncio
    async def test_duplicate_step_ids_are_a_hard_error(self):
        import json
        from jarviscore.planning.planner import Planner, PlannerError
        llm = _PlanLLM(json.dumps({"steps": [_step_json("s1"), _step_json("s1")]}))
        ge = GoalExecution(goal="G", agent_id="a")
        with pytest.raises(PlannerError, match="duplicate step_id"):
            await Planner(llm).plan(goal="G", goal_execution=ge)

    @pytest.mark.asyncio
    async def test_unknown_and_self_depends_on_refs_are_stripped(self):
        import json
        from jarviscore.planning.planner import Planner
        llm = _PlanLLM(json.dumps({"steps": [
            _step_json("s1"),
            _step_json("s2", depends_on=["s1", "ghost_step", "s2"]),
        ]}))
        ge = GoalExecution(goal="G", agent_id="a")
        steps = await Planner(llm).plan(goal="G", goal_execution=ge)
        assert steps[1].depends_on == ["s1"]

    @pytest.mark.asyncio
    async def test_depends_on_round_trips_through_parse(self):
        import json
        from jarviscore.planning.planner import Planner
        llm = _PlanLLM(json.dumps({"steps": [
            _step_json("s1"), _step_json("s2", depends_on=["s1"]),
        ]}))
        ge = GoalExecution(goal="G", agent_id="a")
        steps = await Planner(llm).plan(goal="G", goal_execution=ge)
        assert steps[1].depends_on == ["s1"]


class TestHonestPlannerPrompts:

    @pytest.mark.asyncio
    async def test_facts_render_one_per_line_with_count(self):
        import json
        from jarviscore.planning.planner import Planner
        from jarviscore.context.truth import TruthFact
        llm = _PlanLLM(json.dumps({"steps": [_step_json("s1")]}))
        ge = GoalExecution(goal="G", agent_id="a")
        for i in range(25):
            ge.truth.facts[f"fact_{i:02d}"] = TruthFact(
                value=f"v{i}", source="s", confidence=0.9
            )
        await Planner(llm).plan(goal="G", goal_execution=ge)
        prompt = llm.prompts[0]
        assert "25 fact(s) known:" in prompt
        assert "- fact_00: v0" in prompt
        assert "…and 5 more facts not shown" in prompt

    @pytest.mark.asyncio
    async def test_long_fact_values_carry_markers(self):
        import json
        from jarviscore.planning.planner import Planner
        from jarviscore.context.truth import TruthFact
        llm = _PlanLLM(json.dumps({"steps": [_step_json("s1")]}))
        ge = GoalExecution(goal="G", agent_id="a")
        ge.truth.facts["huge"] = TruthFact(value="H" * 700, source="s", confidence=0.9)
        await Planner(llm).plan(goal="G", goal_execution=ge)
        assert "…[truncated: showing 200 of 700 chars]" in llm.prompts[0]


class TestReplanTailAndBudget:

    def _failed_execution(self):
        ge = GoalExecution(goal="G", agent_id="a")
        ge.record_completed(
            _make_step("s1"), _make_output(), _make_evaluation(verdict="fail"),
            elapsed_ms=10.0,
        )
        return ge

    @pytest.mark.asyncio
    async def test_pending_tail_and_budget_reach_the_prompt(self):
        import json
        from jarviscore.planning.planner import Planner
        llm = _PlanLLM(json.dumps({"steps": [_step_json("s9")]}))
        ge = self._failed_execution()
        pending = [_make_step("s2", task="untouched work")]

        await Planner(llm).replan(
            goal_execution=ge, failed_step=ge.completed[0], reason="broke",
            pending_steps=pending,
            budget_note="3 of max 30 steps used",
        )
        prompt = llm.prompts[0]
        assert "NOT yet attempted — KEEP these" in prompt
        assert "s2: untouched work" in prompt
        assert "Execution budget: 3 of max 30 steps used" in prompt

    @pytest.mark.asyncio
    async def test_replan_drops_completed_ids_defensively(self):
        import json
        from jarviscore.planning.planner import Planner
        # The model disobeys and re-includes the completed step s1
        llm = _PlanLLM(json.dumps({"steps": [_step_json("s1"), _step_json("s2")]}))
        ge = self._failed_execution()

        revised = await Planner(llm).replan(
            goal_execution=ge, failed_step=ge.completed[0], reason="broke",
        )
        assert [s.step_id for s in revised] == ["s2"]


class TestDependencyParallelExecution:
    """Plans that declare depends_on opt into concurrent co-ready steps."""

    @pytest.mark.asyncio
    async def test_co_ready_steps_overlap_and_dependents_wait(self, monkeypatch):
        import asyncio
        from unittest.mock import AsyncMock, patch
        from jarviscore.profiles.autoagent import AutoAgent

        class _GoalAgent(AutoAgent):
            role = "goal-test"
            capabilities = ["x"]
            system_prompt = "test"

        agent = _GoalAgent()
        agent.llm = object()  # never called: planner/evaluator are patched

        # Kernel fake: records in-flight overlap per step
        in_flight = set()
        overlap_seen = {"max": 0}
        order = []

        class _Kernel:
            blob_storage = None
            auth_manager = None

            async def execute(self, task, **kwargs):
                step_id = kwargs["context"]["step_id"]
                in_flight.add(step_id)
                overlap_seen["max"] = max(overlap_seen["max"], len(in_flight))
                await asyncio.sleep(0.05)
                in_flight.discard(step_id)
                order.append(step_id)
                return _make_output(summary=f"did {step_id}")

        agent._kernel = _Kernel()

        # Plan: a and b are independent; c depends on both
        plan = [
            PlannedStep("a", "task a", "done", depends_on=[]),
            PlannedStep("b", "task b", "done", depends_on=[]),
            PlannedStep("c", "task c", "done", depends_on=["a", "b"]),
        ]

        with patch(
            "jarviscore.planning.planner.Planner.plan",
            new=AsyncMock(return_value=plan),
        ), patch(
            "jarviscore.planning.evaluator.StepEvaluator.evaluate",
            new=AsyncMock(return_value=_make_evaluation(verdict="pass")),
        ):
            execution = await agent.execute_goal("test parallel goal")

        assert execution.status == "complete"
        assert len(execution.completed) == 3
        # a and b overlapped; c ran only after both finished
        assert overlap_seen["max"] >= 2
        assert order.index("c") == 2

    @pytest.mark.asyncio
    async def test_dep_free_plans_stay_strictly_sequential(self):
        import asyncio
        from unittest.mock import AsyncMock, patch
        from jarviscore.profiles.autoagent import AutoAgent

        class _GoalAgent(AutoAgent):
            role = "goal-test-seq"
            capabilities = ["x"]
            system_prompt = "test"

        agent = _GoalAgent()
        agent.llm = object()

        in_flight = set()
        overlap_seen = {"max": 0}

        class _Kernel:
            blob_storage = None
            auth_manager = None

            async def execute(self, task, **kwargs):
                step_id = kwargs["context"]["step_id"]
                in_flight.add(step_id)
                overlap_seen["max"] = max(overlap_seen["max"], len(in_flight))
                await asyncio.sleep(0.02)
                in_flight.discard(step_id)
                return _make_output(summary=f"did {step_id}")

        agent._kernel = _Kernel()

        # Historical plan shape: no depends_on anywhere
        plan = [PlannedStep(f"s{i}", f"task {i}", "done") for i in range(3)]

        with patch(
            "jarviscore.planning.planner.Planner.plan",
            new=AsyncMock(return_value=plan),
        ), patch(
            "jarviscore.planning.evaluator.StepEvaluator.evaluate",
            new=AsyncMock(return_value=_make_evaluation(verdict="pass")),
        ):
            execution = await agent.execute_goal("test sequential goal")

        assert execution.status == "complete"
        assert overlap_seen["max"] == 1  # byte-identical historical behavior

    @pytest.mark.asyncio
    async def test_misordered_plan_runs_dependency_first(self):
        """Review fix: a step listed BEFORE its dependency must wait for it."""
        from unittest.mock import AsyncMock, patch
        from jarviscore.profiles.autoagent import AutoAgent

        class _GoalAgent(AutoAgent):
            role = "goal-test-order"
            capabilities = ["x"]
            system_prompt = "test"

        agent = _GoalAgent()
        agent.llm = object()
        order = []

        class _Kernel:
            blob_storage = None
            auth_manager = None

            async def execute(self, task, **kwargs):
                order.append(kwargs["context"]["step_id"])
                return _make_output(summary="ok")

        agent._kernel = _Kernel()

        # b listed first but depends on a — the model misordered the list
        plan = [
            PlannedStep("b", "task b", "done", depends_on=["a"]),
            PlannedStep("a", "task a", "done", depends_on=[]),
        ]

        with patch(
            "jarviscore.planning.planner.Planner.plan",
            new=AsyncMock(return_value=plan),
        ), patch(
            "jarviscore.planning.evaluator.StepEvaluator.evaluate",
            new=AsyncMock(return_value=_make_evaluation(verdict="pass")),
        ):
            execution = await agent.execute_goal("test order goal")

        assert execution.status == "complete"
        assert order == ["a", "b"]

    @pytest.mark.asyncio
    async def test_unsatisfiable_deps_fail_honestly(self):
        """Review fix: a dependency that can never pass is a loud failure."""
        from unittest.mock import AsyncMock, patch
        from jarviscore.profiles.autoagent import AutoAgent

        class _GoalAgent(AutoAgent):
            role = "goal-test-deadlock"
            capabilities = ["x"]
            system_prompt = "test"

        agent = _GoalAgent()
        agent.llm = object()

        class _Kernel:
            blob_storage = None
            auth_manager = None

            async def execute(self, task, **kwargs):
                return _make_output(summary="ok")

        agent._kernel = _Kernel()

        # Planner validation strips unknown refs, so simulate the only path a
        # bad ref can survive: a plan injected directly (e.g. resume of a
        # snapshot written by an older version).
        plan = [PlannedStep("b", "task b", "done", depends_on=["never_exists"])]

        with patch(
            "jarviscore.planning.planner.Planner.plan",
            new=AsyncMock(return_value=plan),
        ), patch(
            "jarviscore.planning.evaluator.StepEvaluator.evaluate",
            new=AsyncMock(return_value=_make_evaluation(verdict="pass")),
        ):
            execution = await agent.execute_goal("test deadlock goal")

        assert execution.status == "failed"
        assert "Dependency deadlock" in execution.error

    @pytest.mark.asyncio
    async def test_partial_verdict_does_not_deadlock_dependents(self):
        """Review fix: partial output is usable output — dependents may run."""
        from unittest.mock import AsyncMock, patch
        from jarviscore.profiles.autoagent import AutoAgent

        class _GoalAgent(AutoAgent):
            role = "goal-test-partial"
            capabilities = ["x"]
            system_prompt = "test"

        agent = _GoalAgent()
        agent.llm = object()
        order = []

        class _Kernel:
            blob_storage = None
            auth_manager = None

            async def execute(self, task, **kwargs):
                order.append(kwargs["context"]["step_id"])
                return _make_output(summary="ok")

        agent._kernel = _Kernel()

        plan = [
            PlannedStep("a", "task a", "done", depends_on=[]),
            PlannedStep("b", "task b", "done", depends_on=["a"]),
        ]

        with patch(
            "jarviscore.planning.planner.Planner.plan",
            new=AsyncMock(return_value=plan),
        ), patch(
            "jarviscore.planning.evaluator.StepEvaluator.evaluate",
            new=AsyncMock(return_value=_make_evaluation(verdict="partial")),
        ):
            execution = await agent.execute_goal("test partial goal")

        assert execution.status == "complete"
        assert order == ["a", "b"]


class TestHITLConsentGate:
    """HITL is opt-in: a hitl verdict never dead-ends an unattended goal (#81)."""

    @pytest.mark.asyncio
    async def test_hitl_without_consent_replans_then_fails_loudly(self, monkeypatch):
        """No HITL_ENABLED, no queue: a hitl verdict downgrades to replan and,
        once attempts are exhausted, fails loudly. It never pauses."""
        monkeypatch.setenv("MAX_REPLAN_ATTEMPTS", "1")
        from unittest.mock import AsyncMock, patch
        from jarviscore.profiles.autoagent import AutoAgent

        class _GoalAgent(AutoAgent):
            role = "goal-hitl-noconsent"
            capabilities = ["x"]
            system_prompt = "test"

        agent = _GoalAgent()
        agent.llm = object()
        # The default unattended deployment: no consent, no queue.
        assert getattr(agent, "_hitl_enabled", False) is False
        assert getattr(agent, "hitl", None) is None

        class _Kernel:
            blob_storage = None
            auth_manager = None

            async def execute(self, task, **kwargs):
                return _make_output(summary="did it")

        agent._kernel = _Kernel()

        plan = [PlannedStep("a", "task a", "done")]
        replan_calls = {"n": 0}

        async def _fake_replan(*args, **kwargs):
            replan_calls["n"] += 1
            return [PlannedStep("a2", "task a2", "done")]

        with patch(
            "jarviscore.planning.planner.Planner.plan",
            new=AsyncMock(return_value=plan),
        ), patch(
            "jarviscore.planning.planner.Planner.replan",
            new=_fake_replan,
        ), patch(
            "jarviscore.planning.evaluator.StepEvaluator.evaluate",
            new=AsyncMock(return_value=_make_evaluation(verdict="hitl")),
        ):
            execution = await agent.execute_goal("unattended goal")

        assert execution.status != "hitl"      # the whole point: no dead-end
        assert execution.status == "failed"    # fails loudly instead
        assert replan_calls["n"] >= 1          # the replan path engaged

    @pytest.mark.asyncio
    async def test_hitl_with_consent_pauses_and_notifies(self):
        """With HITL_ENABLED and a queue attached, a hitl verdict pauses the
        goal and submits a request to the operator queue."""
        from unittest.mock import AsyncMock, patch, MagicMock
        from jarviscore.profiles.autoagent import AutoAgent

        class _GoalAgent(AutoAgent):
            role = "goal-hitl-consent"
            capabilities = ["x"]
            system_prompt = "test"

        agent = _GoalAgent()
        agent.llm = object()
        agent._hitl_enabled = True
        fake_queue = MagicMock()
        fake_queue.request = MagicMock(return_value="hitl-xyz")
        agent.hitl = fake_queue

        class _Kernel:
            blob_storage = None
            auth_manager = None

            async def execute(self, task, **kwargs):
                return _make_output(summary="did it")

        agent._kernel = _Kernel()

        plan = [PlannedStep("a", "task a", "done")]
        with patch(
            "jarviscore.planning.planner.Planner.plan",
            new=AsyncMock(return_value=plan),
        ), patch(
            "jarviscore.planning.evaluator.StepEvaluator.evaluate",
            new=AsyncMock(return_value=_make_evaluation(verdict="hitl")),
        ):
            execution = await agent.execute_goal("attended goal")

        assert execution.status == "hitl"
        fake_queue.request.assert_called_once()
