"""The done gate reports what the agent produced, not a verdict on it (#144).

A rejection that only restates the rule gives an agent nothing to act on, so its
next attempt is the previous one reworded and the gate becomes a loop. These
tests hold the gate to evidence, hold the harness to noticing when an attempt
carries no new information, and hold the boundary that ends a step which cannot
move rather than letting it burn the lease.
"""

import asyncio
import json
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

    def test_failed_action_can_finish_with_an_honest_blocked_result(self):
        state = _state(tool_history=[
            ToolResult(tool_name="write_code", status="failure", error="boom"),
            ToolResult(tool_name="check_registry", status="success", tool_output={}),
        ])
        parsed = {"result": {"status": "blocked", "reason": "Provider call failed"}}

        ok, reason = self._coder()._can_complete(state, parsed)

        assert ok is True
        assert reason == ""
        assert parsed["result"]["status"] == "blocked"

    def test_blocked_result_requires_a_peer_resolution_attempt(self):
        coder = self._coder()
        coder._tools = {"ask_capability": object(), "ask_peer": object()}
        state = _state(tool_history=[
            ToolResult(tool_name="hubspot_list_contacts", status="success", tool_output=[]),
        ])
        parsed = {"result": {"status": "blocked", "reason": "Contact unresolved"}}

        ok, evidence = coder._can_complete(state, parsed)

        assert ok is False
        assert evidence.check == "peer_resolution_review"
        assert evidence.observed["peer_tool_calls"] == 0

        ok, repeated = coder._can_complete(state, parsed)
        assert ok is False
        assert repeated.check == "peer_resolution_review"

    def test_unresolved_facts_require_peer_resolution_even_for_existing_record(self):
        coder = self._coder()
        coder._tools = {"ask_capability": object()}
        state = _state(tool_history=[
            ToolResult(
                tool_name="hubspot_search_contacts",
                status="success",
                tool_output={"contacts": []},
            ),
        ])
        parsed = {"result": {
            "status": "existing",
            "deal_id": "deal-1",
            "unresolved": [{"fact": "Contact identity remains unresolved"}],
        }}

        ok, evidence = coder._can_complete(state, parsed)

        assert ok is False
        assert evidence.check == "peer_resolution_review"

    def test_peer_responder_is_not_forced_to_delegate_its_response_again(self):
        coder = self._coder()
        coder._tools = {"ask_capability": object()}
        state = _state(
            context={"peer_requester_agent_id": "requester-1"},
            tool_history=[
                ToolResult(
                    tool_name="hubspot_search_contacts",
                    status="success",
                    tool_output={"contacts": []},
                ),
            ],
        )
        parsed = {"result": {
            "status": "research_incomplete",
            "unresolved": [{"fact": "No additional CRM record was found"}],
        }}

        ok, reason = coder._can_complete(state, parsed)

        assert ok is True
        assert reason == ""

    def test_peer_attempt_allows_honest_blocked_completion(self):
        coder = self._coder()
        coder._tools = {"ask_capability": object()}
        state = _state(tool_history=[
            ToolResult(
                tool_name="ask_capability",
                status="failure",
                error="No peer fulfilled the need",
                tool_output={"peer_request_attempted": True},
            ),
        ])

        ok, reason = coder._can_complete(
            state, {"result": {"status": "blocked", "reason": "Contact unresolved"}}
        )

        assert ok is True
        assert reason == ""

    def test_malformed_peer_call_does_not_satisfy_resolution_attempt(self):
        coder = self._coder()
        coder._tools = {"ask_peer": object()}
        state = _state(tool_history=[
            ToolResult(
                tool_name="ask_peer",
                status="failure",
                error="Missing required peer arguments: role, question",
                tool_output={
                    "status": "error",
                    "semantic_error": "INVALID_PEER_TOOL_ARGUMENTS",
                    "peer_request_attempted": False,
                },
            ),
        ])

        ok, evidence = coder._can_complete(
            state,
            {"result": {"status": "blocked", "reason": "Deck unavailable"}},
        )

        assert ok is False
        assert evidence.check == "peer_resolution_review"

    def test_no_attempt_cannot_finish_with_an_unsupported_result(self):
        state = _state(tool_history=[])

        ok, evidence = self._coder()._can_complete(
            state, {"result": {"status": "blocked", "reason": "Assumed failure"}}
        )

        assert ok is False
        assert evidence.check == "meaningful_attempt"

    def test_first_turn_prompt_requires_a_relevant_tool_not_success(self):
        coder = self._coder()
        coder.role = "coder"
        coder._tools = {
            "ask_capability": object(), "ask_peer": object(), "write_code": object()
        }
        coder._atom_tools = ["hubspot_list_deals"]

        prompt = coder._build_user_prompt(_state(tool_history=[]), "## MISSION")

        assert "MUST use one relevant tool" in prompt
        assert "hubspot_list_deals" in prompt
        assert "ask_peer" in prompt
        assert "ask_capability" in prompt
        assert "successful execution" not in prompt

    def test_a_successful_execution_satisfies_the_gate(self):
        """The gate checks proof exists; it does not swap the answer for it."""
        state = _state(tool_history=[
            ToolResult(tool_name="execute_code", status="success", tool_output={"output": 42}),
        ])
        parsed: Dict[str, Any] = {"result": {"answer": "forty-two"}}

        ok, reason = self._coder()._can_complete(state, parsed)

        assert ok is True
        assert reason == ""
        assert parsed["result"] == {"answer": "forty-two"}
        assert "evidence" not in parsed

    @pytest.mark.asyncio
    async def test_effect_intent_review_redirects_unsupported_mutation(self):
        from types import SimpleNamespace

        class ReviewLLM:
            async def generate(self, **kwargs):
                return {"content": json.dumps({
                    "decision": "redirect",
                    "reason": "Deal absence has not been verified.",
                    "missing_evidence": ["Inspect existing deals"],
                })}

        coder = self._coder()
        coder.llm_client = ReviewLLM()
        coder._atoms = {
            "provider_create_record": SimpleNamespace(
                policy=SimpleNamespace(effect="write")
            )
        }
        state = _state(
            task="Create the record only if absent",
            context={"objective": "Create the record only if absent"},
            tool_history=[
                ToolResult(
                    tool_name="provider_search_contacts",
                    status="success",
                    tool_output={"contacts": []},
                ),
            ],
        )

        result = await coder._pre_execute_hook(
            "provider_create_record", {"name": "Acme"}, state
        )

        assert result["semantic_error"] == "EFFECT_INTENT_REDIRECT"
        assert result["missing_evidence"] == ["Inspect existing deals"]

    @pytest.mark.asyncio
    async def test_effect_intent_review_allows_supported_mutation(self):
        from types import SimpleNamespace

        class ReviewLLM:
            async def generate(self, **kwargs):
                return {"content": json.dumps({
                    "decision": "allow",
                    "reason": "The requested target was inspected and is absent.",
                    "missing_evidence": [],
                })}

        coder = self._coder()
        coder.llm_client = ReviewLLM()
        coder._atoms = {
            "provider_create_record": SimpleNamespace(
                policy=SimpleNamespace(effect="write")
            )
        }
        state = _state(tool_history=[
            ToolResult(
                tool_name="provider_search_records",
                status="success",
                tool_output={"records": []},
            ),
        ])

        result = await coder._pre_execute_hook(
            "provider_create_record", {"name": "Acme"}, state
        )

        assert result is None

    @pytest.mark.asyncio
    async def test_effect_intent_review_skips_an_already_satisfied_mutation(self):
        from types import SimpleNamespace

        class ReviewLLM:
            async def generate(self, **kwargs):
                return {"content": json.dumps({
                    "decision": "already_satisfied",
                    "reason": "The requested meeting already exists.",
                    "missing_evidence": [],
                    "supporting_evidence": [
                        "event-1 has the requested attendee and schedule"
                    ],
                })}

        coder = self._coder()
        coder.llm_client = ReviewLLM()
        coder._atoms = {
            "provider_create_event": SimpleNamespace(
                policy=SimpleNamespace(effect="write")
            )
        }
        state = _state(tool_history=[
            ToolResult(
                tool_name="provider_list_events",
                status="success",
                tool_output={
                    "events": [{
                        "id": "event-1",
                        "attendees": ["ephy@example.com"],
                    }],
                },
            ),
        ])

        result = await coder._pre_execute_hook(
            "provider_create_event",
            {"attendees": ["ephy@example.com"]},
            state,
        )

        assert result["status"] == "success"
        assert result["skipped"] is True
        assert result["semantic_outcome"] == "EFFECT_ALREADY_SATISFIED"
