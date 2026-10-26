"""Replay: re-simulate a recorded agent run from its record, every effect stubbed.

While a sub-agent runs, :class:`Recorder` keeps in the step's journal everything
from outside the agent's own logic that its decisions depended on:

- ``run.start``: the agent's class, task, context, tools, budget and versions;
- ``model.call``: each model request and the response it got;
- ``hook.result``: what each pre-execution gate returned (approvals, previews,
  effect reviews);
- ``tool.result``: what each tool returned (including approved actions carried
  out on resume);
- ``run.end``: the outcome.

The chain holds digests; the content is kept content-addressed beside it
(``journal.store_content``), so it can be erased without breaking ``verify``.

:func:`replay` rebuilds the agent, answers every model call, gate and tool from
the record, and so makes no model call and has no effect, then compares what
the agent decided (each tool it called, with which arguments, and how the run
ended) with what was recorded. A run whose logic, prompts or record changed
since diverges, and the report says where.
"""
from __future__ import annotations

import contextvars
import importlib
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

#: Set while a run is being replayed: a replay records nothing.
REPLAYING: contextvars.ContextVar[bool] = contextvars.ContextVar("jarviscore_replaying", default=False)
LEASE_FIELDS = ("max_total_tokens", "thinking_budget", "action_budget", "wall_clock_ms", "emergency_turn_fuse", "model_tier")


def _jsonable(value: Any) -> Any:
    """``value`` as plain JSON: keys as text, anything else by its text."""
    import json

    def plain(item):
        if isinstance(item, dict):
            return {str(key): plain(child) for key, child in item.items()}
        if isinstance(item, (list, tuple, set, frozenset)):
            return [plain(child) for child in item]
        return item

    return json.loads(json.dumps(plain(value), default=str))


_CLOCK = (
    (r"Now: [^\n]*", "Now: <clock>"),
    (r"\d+s of \d+s wall clock", "<clock> wall clock"),
    (r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?(?:Z|[+-]\d\d:?\d\d)?", "<clock>"),
)
#: Keys whose values are the runtime's clock readings, not anything the agent decided.
_CLOCK_KEYS = frozenset({"observed_at", "timestamp", "ts", "started_at", "finished_at", "created_at"})


def comparable(value: Any) -> Any:
    """``value`` with the runtime clock masked: the one thing a replay cannot reproduce."""
    import re

    if isinstance(value, str):
        for pattern, mask in _CLOCK:
            value = re.sub(pattern, mask, value)
        return value
    if isinstance(value, dict):
        return {key: "<clock>" if key in _CLOCK_KEYS else comparable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [comparable(item) for item in value]
    return value


#: The recorder of the run in progress in this task (concurrent runs never share one).
CURRENT: contextvars.ContextVar[Optional["Recorder"]] = contextvars.ContextVar("jarviscore_recorder", default=None)


class Recorder:
    """Keeps what one sub-agent run depended on, in its step's journal run.

    Recording never fails or changes the run: what cannot be kept is logged, and
    content that cannot be stored is kept as its digest only.
    """

    def __init__(self, journal, root: str, run: str, full: bool):
        self.journal, self.root, self.run, self.full = journal, root, run, full
        self.phase = "loop"
        #: 0 for the agent's own decisions; deeper for tools a tool program called.
        self.depth = 0

    @classmethod
    def for_run(cls, context: Optional[Dict[str, Any]]) -> Optional["Recorder"]:
        try:
            from jarviscore.control.policy import current_policy
            from jarviscore.evidence.journal import capture_mode, current_journal, prune_content_soon
            from jarviscore.nexus.call_proxy import _run_name

            mode = capture_mode()
            if REPLAYING.get() or mode == "off" or current_policy().mode == "off":
                return None
            journal = current_journal()
            if journal is None:
                return None
            if mode == "full":
                prune_content_soon(journal.root)
            return cls(journal, journal.root, _run_name({
                "workflow_id": (context or {}).get("workflow_id"), "step_id": (context or {}).get("step_id"),
            }), full=mode == "full")
        except Exception as exc:  # noqa: BLE001 - recording never fails a run
            logger.warning("Run not recorded for replay: %s", exc)
            return None

    def keep(self, value: Any) -> str:
        from jarviscore.evidence.journal import digest, store_content

        try:
            value = _jsonable(value)
        except Exception:  # noqa: BLE001
            value = repr(value)
        if self.full:
            try:
                return store_content(self.root, value)
            except Exception as exc:  # noqa: BLE001 - kept as its digest: verifiable, not replayable
                logger.warning("Replay content not stored (%s); its digest is kept", exc)
        return digest(value)

    def note(self, kind: str, data: Dict[str, Any]) -> None:
        try:
            self.journal.append(self.run, kind, data)
        except Exception as exc:  # noqa: BLE001 - the record must never break the run
            logger.warning("Replay record %s not written: %s", kind, exc)

    def safely(self, record) -> None:
        try:
            record()
        except Exception as exc:  # noqa: BLE001 - recording never fails a run
            logger.warning("Replay record not written: %s", exc)

    # ── One run ───────────────────────────────────────────────────────────

    def start(self, agent, task: str, context: Optional[Dict[str, Any]], max_turns: int, model, cognition=None) -> None:
        def record():
            import jarviscore

            from jarviscore.control.policy import current_policy

            lease = getattr(cognition, "lease", None)
            carries = getattr(agent.llm_client, "carries_native_tools", None)
            from jarviscore.auth.principal import acting_for, mandate, scopes

            held, delegated = scopes.get(), mandate.get()
            self.note("run.start", {
                "acting_for": acting_for.get(),
                **({"scopes": self.keep(held)} if held is not None else {}),
                **({"mandate": self.keep(delegated)} if delegated is not None else {}),
                "agent_class": f"{type(agent).__module__}.{type(agent).__qualname__}",
                "agent_id": getattr(agent, "agent_id", None),
                "role": getattr(agent, "role", None),
                "task": self.keep(task),
                "context": self.keep({k: v for k, v in (context or {}).items() if not str(k).startswith("_")}),
                "tools": sorted(getattr(agent, "_tools", {}) or {}),
                # How each tool was offered: a replay offers the ones it cannot rebuild the same way.
                "tool_specs": self.keep({
                    name: {"description": getattr(tool, "description", ""), "phase": getattr(tool, "declared_phase", None),
                           "parameters": getattr(tool, "parameters", None)}
                    for name, tool in (getattr(agent, "_tools", {}) or {}).items()
                }),
                "max_turns": max_turns,
                "model": str(model) if model else None,
                "lease": {name: getattr(lease, name) for name in LEASE_FIELDS if hasattr(lease, name)} if lease else None,
                "native": bool(callable(carries) and carries(model) is True),
                "version": getattr(jarviscore, "__version__", ""),
                "policy": current_policy().digest,
            })
        self.safely(record)

    def end(self, output) -> None:
        self.safely(lambda: self.note("run.end", _outcome(self, output)))


class _RecordingLLM:
    """The agent's model client, recording each call into the current run's record."""

    def __init__(self, inner):
        self._jc_inner = inner

    def __getattr__(self, name):
        return getattr(self._jc_inner, name)

    async def generate(self, *args, **kwargs):
        response = await self._jc_inner.generate(*args, **kwargs)
        recorder = CURRENT.get()
        if recorder is not None:
            recorder.safely(lambda: recorder.note("model.call", {
                "request": recorder.keep({"args": list(args), "kwargs": dict(kwargs)}),
                "response": recorder.keep(response),
                "model": kwargs.get("model") or (response.get("model") if isinstance(response, dict) else None),
            }))
        return response


def install(agent) -> None:
    """Make ``agent`` recordable: once per instance, passing through when nothing records."""
    if not isinstance(agent.llm_client, _RecordingLLM) and agent.llm_client is not None:
        agent.llm_client = _RecordingLLM(agent.llm_client)
    if agent.__dict__.get("_jc_recordable"):
        return
    hook, execute, carry = agent._pre_execute_hook, agent._execute_tool, agent._carry_out_decided_actions

    async def recorded_hook(name, params, state):
        result = await hook(name, params, state)
        recorder = CURRENT.get()
        if recorder is not None:
            recorder.safely(lambda: recorder.note("hook.result", {
                "tool": name, "params": recorder.keep(params), "result": recorder.keep(result), "depth": recorder.depth,
            }))
        return result

    async def recorded_tool(name, params):
        recorder = CURRENT.get()
        if recorder is None:
            return await execute(name, params)
        depth = recorder.depth
        recorder.depth += 1
        try:
            result = await execute(name, params)
        finally:
            recorder.depth = depth
        recorder.safely(lambda: recorder.note("tool.result", {
            "tool": name, "params": recorder.keep(params), "result": recorder.keep(result),
            "phase": recorder.phase, "depth": depth,
        }))
        return result

    async def recorded_carry(state, trace):
        recorder = CURRENT.get()
        if recorder is not None:
            recorder.phase = "carry_out"
        try:
            return await carry(state, trace)
        finally:
            if recorder is not None:
                recorder.phase = "loop"

    agent._pre_execute_hook, agent._execute_tool = recorded_hook, recorded_tool
    agent._carry_out_decided_actions = recorded_carry
    agent.__dict__["_jc_recordable"] = True


def _outcome(recorder, output) -> Dict[str, Any]:
    status = getattr(output, "status", None)
    metadata = getattr(output, "metadata", None) or {}
    return {
        "wall_clock": "wall_clock" in str(metadata.get("lease_exhausted") or getattr(output, "summary", "") or ""),
        "status": status,
        "typed_outcome": metadata.get("typed_outcome"),
        "summary": recorder.keep(getattr(output, "summary", None)),
        "payload": recorder.keep(getattr(output, "payload", None)),
    }


# ── Replaying ─────────────────────────────────────────────────────────────


@dataclass
class ReplayReport:
    run: str
    reproduced: bool = False
    decisions: int = 0
    model_calls: int = 0
    requests_matched: int = 0
    divergence: Optional[str] = None
    notes: List[str] = field(default_factory=list)

    def summary(self) -> str:
        state = "reproduced" if self.reproduced else f"diverged: {self.divergence}"
        return (
            f"{self.run}: {state} ({self.decisions} decision(s), {self.model_calls} model call(s), "
            f"{self.requests_matched} request(s) identical to the record)"
        )


class _Diverged(RuntimeError):
    pass


def _records(root: str, run: str) -> List[Dict[str, Any]]:
    import json
    import os

    from jarviscore.evidence.journal import Journal

    path = Journal(root).run_path(run)
    if not os.path.exists(path):
        raise FileNotFoundError(f"No run {run!r} under {root}")
    with open(path, encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def runs(root: str) -> List[str]:
    """Runs under ``root`` that can be replayed (they recorded a full run)."""
    import glob
    import json
    import os

    found = []
    for path in sorted(glob.glob(os.path.join(root, "runs", "*.jsonl"))):
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                event = json.loads(line)
                if event.get("kind") == "run.start":
                    found.append(event["run"])
                    break
    return found


async def replay(root: str, run: str, factory: Optional[Callable[[str, Any], Any]] = None,
                 attempt: int = -1) -> ReplayReport:
    """Re-simulate ``run`` (its ``attempt``-th recorded run, the last by default) from its record."""
    from jarviscore.evidence.journal import digest, load_content

    events = _records(root, run)
    starts = [i for i, e in enumerate(events) if e["kind"] == "run.start"]
    if not starts:
        raise ValueError(f"{run} recorded no agent run to replay")
    begin = starts[attempt]
    end = next((i for i in range(begin + 1, len(events)) if events[i]["kind"] in ("run.start",)), len(events))
    window = events[begin:end]
    start = window[0]["data"]
    report = ReplayReport(run=run)

    def content(key):
        try:
            return load_content(root, key)
        except KeyError:
            raise _Diverged(f"content {key[:12]} is not kept (JOURNAL_CAPTURE=full is needed to replay)") from None

    calls = [e["data"] for e in window if e["kind"] == "model.call"]
    hooks = [e["data"] for e in window if e["kind"] == "hook.result" and not e["data"].get("depth")]
    # The agent's own decisions; calls a tool program made travel with the program's result.
    tools, inner, pending = [], {}, []
    for event in window:
        if event["kind"] != "tool.result":
            continue
        if event["data"].get("depth"):
            pending.append(event["data"])
        else:
            inner[len(tools)] = pending
            pending = []
            tools.append(event["data"])
    ended = next((e["data"] for e in window if e["kind"] == "run.end"), None)
    report.model_calls = len(calls)

    module, _, name = start["agent_class"].rpartition(".")
    if factory is None and ("<locals>" in start["agent_class"] or module == "__main__"):
        raise ValueError(
            f"{start['agent_class']} is defined inside a function or a script, so it cannot be "
            "rebuilt by name; replay it from Python with replay(root, run, factory=...)."
        )
    cls = None if factory else getattr(importlib.import_module(module), name)
    position = {"call": 0, "hook": 0, "tool": 0}

    wall_clock_end = "wall_clock" in str((ended or {}).get("typed_outcome") or "") or bool((ended or {}).get("wall_clock"))

    class _RecordEnds(Exception):
        pass

    class Player:
        nano_model = None

        def __getattr__(self, attribute):
            return None

        def carries_native_tools(self, model=None):
            return bool(start.get("native"))

        async def generate(self, *args, **kwargs):
            index = position["call"]
            if index >= len(calls):
                if wall_clock_end:
                    # The recorded run stopped on the clock here; a replay has no clock to run out.
                    raise _RecordEnds()
                raise _Diverged(f"the agent made model call {index + 1}; the record has {len(calls)}")
            position["call"] += 1
            asked = comparable(_jsonable({"args": list(args), "kwargs": kwargs}))
            if asked == comparable(content(calls[index]["request"])):
                report.requests_matched += 1
            return content(calls[index]["response"])

    agent = factory(start.get("agent_id") or "replay", Player()) if factory else _build(cls, start, Player())

    async def played_hook(tool, params, state):
        index = position["hook"]
        if index >= len(hooks) or hooks[index]["tool"] != tool:
            raise _Diverged(f"gate {index + 1}: the agent asked about {tool}; the record has "
                            f"{hooks[index]['tool'] if index < len(hooks) else 'nothing'}")
        position["hook"] += 1
        return content(hooks[index]["result"])

    async def played_tool(tool, params):
        index = position["tool"]
        if index >= len(tools):
            raise _Diverged(f"decision {index + 1}: the agent called {tool}; the record ends at {len(tools)}")
        recorded = tools[index]
        if recorded["tool"] != tool:
            raise _Diverged(f"decision {index + 1}: the agent called {tool}, the record {recorded['tool']}")
        if digest(_jsonable(params)) != recorded["params"]:
            raise _Diverged(f"decision {index + 1}: {tool} was called with other arguments than recorded")
        state = getattr(agent, "_current_state", None)
        for call in inner.get(index, ()):
            if state is not None:
                # What the program's own calls returned, back on the record as they were.
                state.add_tool_result(call["tool"], content(call["params"]), content(call["result"]), via_program=True)
        position["tool"] += 1
        report.decisions += 1
        return content(recorded["result"])

    async def played_carry(state, trace):
        while position["tool"] < len(tools) and tools[position["tool"]].get("phase") == "carry_out":
            recorded = tools[position["tool"]]
            await played_tool(recorded["tool"], content(recorded["params"]))
            state.add_tool_result(recorded["tool"], content(recorded["params"]), content(recorded["result"]))

    async def nothing(*args, **kwargs):
        return None

    agent._pre_execute_hook, agent._execute_tool = played_hook, played_tool
    agent._carry_out_decided_actions = played_carry
    agent._pre_run_hook = agent._post_run_hook = nothing
    specs = {}
    if start.get("tool_specs"):
        try:
            specs = content(start["tool_specs"])
        except _Diverged:
            specs = {}
    for tool in start.get("tools") or ():
        if tool not in agent._tools:
            # Offered as it was (description, schema, and the budget phase it is charged to).
            spec = specs.get(tool) or {}
            agent.register_tool(tool, nothing, spec.get("description") or f"(recorded tool {tool})",
                                phase=spec.get("phase"), parameters=spec.get("parameters"))
    try:
        from jarviscore.auth.principal import act_for
        from jarviscore.control.effects import scope

        token, replaying = scope.set({"replay": True}), REPLAYING.set(True)
        try:
            # The same person the run worked for, with what they held and delegated.
            held = content(start["scopes"]) if start.get("scopes") else None
            delegated = content(start["mandate"]) if start.get("mandate") else None
            with act_for(start.get("acting_for"), delegated, held):
                output = await agent.run(task=content(start["task"]), context=content(start["context"]),
                                         max_turns=start.get("max_turns") or 15, model=start.get("model"),
                                         cognition=_cognition(start, agent))
        finally:
            REPLAYING.reset(replaying)
            scope.reset(token)
    except _Diverged as exc:
        report.divergence = str(exc)
        return report
    except _RecordEnds:
        report.notes.append("the recorded run ended on its wall clock; replayed to that point")
        output = None
    if position["tool"] != len(tools):
        report.divergence = f"the agent stopped after {position['tool']} of {len(tools)} recorded decisions"
        return report
    if ended is not None and output is not None:
        replayed = {
            "status": getattr(output, "status", None),
            "typed_outcome": (getattr(output, "metadata", None) or {}).get("typed_outcome"),
            "summary": _jsonable(getattr(output, "summary", None)),
            "payload": _jsonable(getattr(output, "payload", None)),
        }
        for key in ("status", "typed_outcome", "summary", "payload"):
            if key == "summary" and ended.get("wall_clock"):
                continue
            recorded = content(ended[key]) if key in ("summary", "payload") else ended.get(key)
            if comparable(replayed[key]) != comparable(recorded):
                report.divergence = f"the run ended differently: {key}"
                return report
        report.notes.append("compared with the runtime clock masked")
    report.reproduced = True
    return report


class SimpleRecorder:
    def keep(self, value):
        from jarviscore.evidence.journal import digest

        return digest(_jsonable(value))


def _cognition(start: Dict[str, Any], agent):
    """The budget the recorded run had; the wall clock never runs out in a replay."""
    from jarviscore.kernel.cognition import AgentCognitionManager
    from jarviscore.kernel.lease import ExecutionLease

    lease = ExecutionLease()
    for name, value in (start.get("lease") or {}).items():
        if name in LEASE_FIELDS:
            setattr(lease, name, value)
    lease.wall_clock_ms = 10 ** 12
    return AgentCognitionManager(lease=lease, agent_id=getattr(agent, "agent_id", "replay"), workflow_id="replay")


def _build(cls, start: Dict[str, Any], llm) -> Any:
    """The recorded agent class, with nothing it could act through."""
    agent = cls.__new__(cls)
    from jarviscore.kernel.subagent import BaseSubAgent

    try:
        cls.__init__(agent, agent_id=start.get("agent_id") or "replay", llm_client=llm)
    except TypeError:
        BaseSubAgent.__init__(agent, agent_id=start.get("agent_id") or "replay",
                              role=start.get("role") or "replay", llm_client=llm)
    return agent
