"""The done gate reports what the agent produced, not a verdict on it (#144).

A rejection that only restates the rule gives an agent nothing to act on, so its
next attempt is the previous one reworded and the gate becomes a loop. These
tests hold the gate to evidence, hold the harness to noticing when an attempt
carries no new information, and hold the boundary that ends a step which cannot
move rather than letting it burn the lease.
"""

import asyncio
from typing import Any, Dict, List, Optional

import pytest

from jarviscore.kernel.gate import (
    GateAttempt,
    GateEvidence,
    as_evidence,
    record_attempt,
)
from jarviscore.kernel.state import KernelState, ToolResult
from jarviscore.kernel.subagent import BaseSubAgent


# ──────────────────────────────────────────────────────────────────
# Evidence shape
# ──────────────────────────────────────────────────────────────────

class TestGateEvidence:

    def test_render_names_check_requirement_and_observations(self):
        rendered = GateEvidence(
            check="evidence_pointers",
            requirement="every evidence entry carries a pointer or url",
            observed={"evidence_count": 3, "bad_evidence": 3},
        ).render()

        assert "DONE_GATE_UNSATISFIED: evidence_pointers" in rendered
        assert "every evidence entry carries a pointer or url" in rendered
        assert "evidence_count" in rendered and "3" in rendered
        assert "bad_evidence" in rendered

    def test_render_states_facts_not_advice(self):
        rendered = GateEvidence(
            check="proof_of_work",
            requirement="one execute_code call that succeeded",
            observed={"execute_code_calls": 0},
        ).render()

        # The gate names what is missing. What to do about it is the agent's call.
        for coaching in ("you must", "you should", "consider", "try ", "do not"):
            assert coaching not in rendered.lower()

    def test_empty_observations_render_without_a_table(self):
        rendered = GateEvidence(check="unspecified", requirement="something").render()
        assert "observed" not in rendered

    def test_booleans_and_lists_render_readably(self):
        rendered = GateEvidence(
            check="c",
            observed={"summary_present": False, "incomplete_specs": [], "tools": ["a", "b"]},
        ).render()
        assert "no" in rendered
        assert "none" in rendered
        assert "a, b" in rendered


class TestFingerprint:

    def test_same_check_and_observations_fingerprint_alike(self):
        one = GateEvidence(check="evidence", observed={"evidence_count": 0, "bad": 2})
        two = GateEvidence(check="evidence", observed={"bad": 2, "evidence_count": 0})
        assert one.fingerprint() == two.fingerprint()

    def test_progress_changes_the_fingerprint(self):
        before = GateEvidence(check="evidence_pointers", observed={"bad_evidence": 3})
        after = GateEvidence(check="evidence_pointers", observed={"bad_evidence": 2})
        assert before.fingerprint() != after.fingerprint()

    def test_a_different_check_is_a_different_failure(self):
        one = GateEvidence(check="summary", observed={"n": 1})
        two = GateEvidence(check="evidence", observed={"n": 1})
        assert one.fingerprint() != two.fingerprint()

    def test_unserialisable_observations_still_fingerprint(self):
        evidence = GateEvidence(check="c", observed={"obj": object()})
        assert len(evidence.fingerprint()) == 64


class TestLegacyStringReason:
    """A gate that returns a bare string is reporting a verdict. Say so."""

    def test_string_is_carried_through_as_unspecified(self):
        evidence = as_evidence("Research completion requires evidence")
        assert evidence.check == "unspecified"
        assert evidence.requirement == "Research completion requires evidence"
        assert evidence.observed == {}

    def test_evidence_passes_through_untouched(self):
        original = GateEvidence(check="x", observed={"a": 1})
        assert as_evidence(original) is original

    def test_empty_reason_is_tolerated(self):
        assert as_evidence(None).check == "unspecified"
        assert as_evidence("").requirement == ""


# ──────────────────────────────────────────────────────────────────
# Repetition: what counts as a new attempt
# ──────────────────────────────────────────────────────────────────

class TestRecordAttempt:

    def _record(self, history, evidence, payload, tool_calls, turn=0):
        return record_attempt(
            history, turn=turn, evidence=evidence, payload=payload, tool_calls=tool_calls,
        )

    def test_first_attempt_is_never_a_repeat(self):
        history: List[Dict[str, Any]] = []
        _, streak, previous = self._record(history, GateEvidence(check="c"), {"a": 1}, 2)
        assert streak == 1
        assert previous is None

    def test_identical_attempt_counts_as_a_repeat(self):
        history: List[Dict[str, Any]] = []
        evidence = GateEvidence(check="c", observed={"n": 0})
        self._record(history, evidence, {"a": 1}, 2, turn=3)
        _, streak, previous = self._record(history, evidence, {"a": 1}, 2, turn=4)
        assert streak == 2
        assert previous.turn == 3

    def test_a_changed_result_is_a_new_attempt(self):
        history: List[Dict[str, Any]] = []
        evidence = GateEvidence(check="c", observed={"n": 0})
        self._record(history, evidence, {"a": 1}, 2)
        _, streak, _ = self._record(history, evidence, {"a": 2}, 2)
        assert streak == 1

    def test_work_done_in_between_is_a_new_attempt(self):
        """An agent that ran a tool has produced something the gate has not seen."""
        history: List[Dict[str, Any]] = []
        evidence = GateEvidence(check="c", observed={"n": 0})
        self._record(history, evidence, {"a": 1}, 2)
        _, streak, _ = self._record(history, evidence, {"a": 1}, 3)
        assert streak == 1

    def test_changed_observations_are_a_new_attempt(self):
        history: List[Dict[str, Any]] = []
        self._record(history, GateEvidence(check="c", observed={"n": 3}), {"a": 1}, 2)
        _, streak, _ = self._record(history, GateEvidence(check="c", observed={"n": 2}), {"a": 1}, 2)
        assert streak == 1

    def test_streak_resumes_from_zero_after_progress(self):
        history: List[Dict[str, Any]] = []
        stuck = GateEvidence(check="c", observed={"n": 0})
        self._record(history, stuck, {"a": 1}, 2)
        self._record(history, stuck, {"a": 1}, 2)
        self._record(history, stuck, {"a": 2}, 2)          # moved
        _, streak, _ = self._record(history, stuck, {"a": 2}, 2)
        assert streak == 2

    def test_history_is_plain_data_so_it_survives_checkpointing(self):
        history: List[Dict[str, Any]] = []
        self._record(history, GateEvidence(check="c"), {"a": 1}, 2)
        assert all(isinstance(entry, dict) for entry in history)
        assert GateAttempt(**history[0]).tool_calls == 2


# ──────────────────────────────────────────────────────────────────
# Harness behaviour
# ──────────────────────────────────────────────────────────────────

class _ScriptedLLM:
    """Replays canned assistant turns and records what it was shown."""

    def __init__(self, replies: List[str]):
        self._replies = list(replies)
        self.seen: List[List[Dict[str, str]]] = []

    async def generate(self, messages=None, **kwargs):
        self.seen.append(list(messages or []))
        reply = self._replies.pop(0) if self._replies else self._replies_last()
        return {"content": reply, "tokens": {"input": 1, "output": 1, "total": 2}, "cost_usd": 0.0}

    def _replies_last(self):
        return "THOUGHT: again\nDONE: done\nRESULT: {\"a\": 1}"


class _GatedAgent(BaseSubAgent):
    """Rejects every completion with a fixed piece of evidence."""

    def __init__(self, llm, evidence=None):
        self.rejections = 0
        self._evidence = evidence or GateEvidence(
            check="evidence",
            requirement="at least one evidence entry",
            observed={"evidence_count": 0},
        )
        super().__init__(agent_id="gated", role="researcher", llm_client=llm)

    def get_system_prompt(self, *args, **kwargs) -> str:
        return "system"

    def setup_tools(self) -> None:
        return None

    def _can_complete(self, state, parsed):
        self.rejections += 1
        return False, self._evidence


def _done(result: str = '{"a": 1}') -> str:
    return f"THOUGHT: finishing\nDONE: summary\nRESULT: {result}"


def _observations(llm: _ScriptedLLM) -> List[str]:
    return [
        message["content"]
        for exchange in llm.seen
        for message in exchange
        if message["role"] == "user"
    ]


class TestRejectionReachesTheAgent:

    def test_the_agent_is_shown_the_evidence(self):
        llm = _ScriptedLLM([_done(), _done('{"a": 2}')])
        agent = _GatedAgent(llm)

        asyncio.run(agent.run(task="t", max_turns=2))

        shown = "\n".join(_observations(llm))
        assert "DONE_GATE_UNSATISFIED: evidence" in shown
        assert "evidence_count" in shown

    def test_a_repeat_is_reported_as_unchanged(self):
        llm = _ScriptedLLM([_done(), _done(), _done()])
        agent = _GatedAgent(llm)

        asyncio.run(agent.run(task="t", max_turns=3))

        shown = "\n".join(_observations(llm))
        assert "unchanged" in shown

    def test_a_first_rejection_is_not_reported_as_unchanged(self):
        llm = _ScriptedLLM([_done(), "THOUGHT: t\nTOOL: nope\nPARAMS: {}"])
        agent = _GatedAgent(llm)

        asyncio.run(agent.run(task="t", max_turns=2))

        assert "unchanged" not in "\n".join(_observations(llm))


class TestTerminalBoundary:

    def test_identical_attempts_end_the_step_rather_than_the_lease(self):
        llm = _ScriptedLLM([_done()] * 12)
        agent = _GatedAgent(llm)

        result = asyncio.run(agent.run(task="t", max_turns=12))

        assert result.status == "failure"
        assert result.metadata["typed_outcome"] == "FAIL_DONE_GATE_UNSATISFIED"
        assert agent.rejections == BaseSubAgent.max_identical_done_attempts

    def test_the_failure_carries_the_evidence(self):
        llm = _ScriptedLLM([_done()] * 12)
        agent = _GatedAgent(llm)

        result = asyncio.run(agent.run(task="t", max_turns=12))

        assert result.metadata["gate_evidence"]["check"] == "evidence"
        assert result.metadata["gate_evidence"]["observed"] == {"evidence_count": 0}
        assert "evidence" in result.summary

    def test_an_agent_that_keeps_changing_its_answer_is_not_cut_off(self):
        """Movement is not a stall, however many rejections it takes."""
        llm = _ScriptedLLM([_done(f'{{"a": {n}}}') for n in range(8)])
        agent = _GatedAgent(llm)

        result = asyncio.run(agent.run(task="t", max_turns=8))

        assert result.metadata.get("typed_outcome") != "FAIL_DONE_GATE_UNSATISFIED"
        assert agent.rejections == 8

    def test_the_boundary_is_configurable_per_agent(self):
        class _Patient(_GatedAgent):
            max_identical_done_attempts = 5

        llm = _ScriptedLLM([_done()] * 12)
        agent = _Patient(llm)

        asyncio.run(agent.run(task="t", max_turns=12))

        assert agent.rejections == 5

    def test_a_legacy_string_gate_still_terminates(self):
        class _Verdict(_GatedAgent):
            def _can_complete(self, state, parsed):
                self.rejections += 1
                return False, "evidence is required"

        llm = _ScriptedLLM([_done()] * 12)
        agent = _Verdict(llm)
        result = asyncio.run(agent.run(task="t", max_turns=12))

        assert result.metadata["typed_outcome"] == "FAIL_DONE_GATE_UNSATISFIED"
        assert result.metadata["gate_evidence"]["check"] == "unspecified"


class TestAttemptLedger:

    def test_attempts_are_recorded_on_state(self):
        llm = _ScriptedLLM([_done()] * 12)
        agent = _GatedAgent(llm)

        asyncio.run(agent.run(task="t", max_turns=12))

        recorded = agent._current_state.internal_variables["done_gate_attempts"]
        assert len(recorded) == BaseSubAgent.max_identical_done_attempts
        assert {entry["fingerprint"] for entry in recorded} == {
            GateEvidence(
                check="evidence",
                requirement="at least one evidence entry",
                observed={"evidence_count": 0},
            ).fingerprint()
        }


# ──────────────────────────────────────────────────────────────────
# The default agents report facts
# ──────────────────────────────────────────────────────────────────

def _state(**overrides) -> KernelState:
    defaults = {"workflow_id": "w", "step_id": "s", "agent_id": "a", "task": "t"}
    defaults.update(overrides)
    return KernelState(**defaults)


class TestResearcherGate:

    def _researcher(self):
        from jarviscore.kernel.defaults.researcher import ResearcherSubAgent
        return ResearcherSubAgent.__new__(ResearcherSubAgent)

    def test_no_research_reports_what_was_run(self):
        ok, evidence = self._researcher()._can_complete(_state(), {"result": {}})

        assert ok is False
        assert evidence.check == "research_performed"
        assert evidence.observed["tool_calls"] == 0
        assert evidence.observed["content_tool_successes"] == 0

    def test_no_evidence_at_all_is_counted(self, monkeypatch):
        monkeypatch.setenv("RESEARCH_STRICT_DONE_VALIDATION", "true")
        state = _state(tool_history=[
            ToolResult(tool_name="read_web_content", status="success", tool_output="x"),
        ])
        parsed = {"result": {"summary": "s", "evidence": [{"text": "a"}, {"text": "b"}]}}

        ok, evidence = self._researcher()._can_complete(state, parsed)

        assert ok is False
        assert evidence.check == "evidence"
        assert evidence.observed["evidence_count"] == 0
        assert evidence.observed["bad_evidence"] == 2

    def test_missing_pointers_are_counted_not_described(self, monkeypatch):
        monkeypatch.setenv("RESEARCH_STRICT_DONE_VALIDATION", "true")
        state = _state(tool_history=[
            ToolResult(tool_name="read_web_content", status="success", tool_output="x"),
        ])
        parsed = {"result": {
            "summary": "s",
            "evidence": [{"pointer": "http://x"}, {"text": "b"}],
        }}

        ok, evidence = self._researcher()._can_complete(state, parsed)

        assert ok is False
        assert evidence.check == "evidence_pointers"
        assert evidence.observed["evidence_count"] == 1
        assert evidence.observed["bad_evidence"] == 1
        assert evidence.observed["content_tool_successes"] == 1

    def test_a_satisfied_gate_says_nothing(self, monkeypatch):
        monkeypatch.setenv("RESEARCH_STRICT_DONE_VALIDATION", "true")
        state = _state(tool_history=[
            ToolResult(tool_name="read_web_content", status="success", tool_output="x"),
        ])
        parsed = {"result": {"summary": "s", "evidence": [{"pointer": "http://x"}]}}

        ok, reason = self._researcher()._can_complete(state, parsed)

        assert ok is True
        assert reason == ""

    def test_progress_moves_the_fingerprint(self, monkeypatch):
        monkeypatch.setenv("RESEARCH_STRICT_DONE_VALIDATION", "true")
        state = _state(tool_history=[
            ToolResult(tool_name="read_web_content", status="success", tool_output="x"),
        ])
        researcher = self._researcher()

        _, before = researcher._can_complete(
            state, {"result": {"summary": "s", "evidence": [{"t": "a"}, {"t": "b"}]}},
        )
        _, after = researcher._can_complete(
            state, {"result": {"summary": "s", "evidence": [{"pointer": "u"}, {"t": "b"}]}},
        )

        assert before.fingerprint() != after.fingerprint()


class TestCoderGate:

    def _coder(self):
        from jarviscore.kernel.defaults.coder import CoderSubAgent
        return CoderSubAgent.__new__(CoderSubAgent)

    def test_unproven_work_reports_the_calls_that_were_made(self):
        state = _state(tool_history=[
            ToolResult(tool_name="write_code", status="failure", error="boom"),
            ToolResult(tool_name="check_registry", status="success", tool_output={}),
        ])

        ok, evidence = self._coder()._can_complete(state, {"result": "42"})

        assert ok is False
        assert evidence.check == "proof_of_work"
        assert evidence.observed["write_code_calls"] == 1
        assert evidence.observed["execute_code_calls"] == 0
        assert evidence.observed["successful_executions"] == 0
        assert evidence.observed["tool_calls"] == 2

    def test_a_successful_execution_satisfies_the_gate(self):
        state = _state(tool_history=[
            ToolResult(tool_name="execute_code", status="success", tool_output={"output": 42}),
        ])
        parsed: Dict[str, Any] = {"result": None}

        ok, reason = self._coder()._can_complete(state, parsed)

        assert ok is True
        assert reason == ""
        assert parsed["result"] == 42
