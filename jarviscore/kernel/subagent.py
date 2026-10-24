"""
6C: BaseSubAgent — Abstract base for all kernel subagents.

Subagents are specialized execution units dispatched by the kernel.
Each has a set of tools and a system prompt. Each turn the model takes one
action: a tool call, or done with the answer and its data.

Where every provider the LLM client can reach carries native tool calls, the
tools are offered as functions and the model must call one each turn
(``done`` finishes). Elsewhere the text protocol below carries the same turn:

Tool call protocol (LLM output):
    THOUGHT: <reasoning>
    TOOL: <tool_name>
    PARAMS: <json>

Completion protocol:
    THOUGHT: <reasoning>
    DONE: <summary>
    RESULT: <json>

OODA Loop Architecture:
    Each turn follows OBSERVE → ORIENT → DECIDE → ACT:
    1. OBSERVE  — ContextManager builds a priority-stack prompt from state
    2. ORIENT   — the turn states the budget that remains
    3. DECIDE   — LLM call produces a tool call or completion signal
    4. ACT      — Tool execution and failure recording

    The runtime enforces boundaries and reports facts; the agent decides:
    - ExecutionLease budget (thinking + action tokens, wall clock, turn fuse)
    - FailureLedger (records and classifies failures)
    - each result says when the identical call ran before and how it went

    Subclass hooks (all have safe defaults):
    - _pre_run_hook()       — one-time setup before the loop starts
    - _pre_execute_hook()   — gate tool calls (e.g. approval of a consequential action)
    - _can_complete()       — gate DONE signals (e.g. evidence quality check)

    Exit paths:
    - parsed["type"] == "done"  — LLM signals completion (subject to _can_complete)
    - state.status == "completed" — tool-driven exit (e.g. publish_research_findings)
    - Lease/budget exhaustion   — emergency yield
    - Emergency turn fuse       — max_turns reached
"""

import ast
import asyncio
import copy
import inspect
import json
import logging
import os
import re
import time
import types
import typing
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Tuple, Union, cast

from jarviscore.context.truth import AgentOutput
from jarviscore.execution import multimodal
from jarviscore.kernel.cognition import AgentCognitionManager, FailureLedger
from jarviscore.auth.spending import SpendCapReached
from jarviscore.orchestration.budget import WorkflowBudgetExceeded
from jarviscore.kernel.gate import GateEvidence, as_evidence, record_attempt
from jarviscore.kernel.state import KernelState, ToolReceiptError

logger = logging.getLogger(__name__)


class SubagentLogAdapter(logging.LoggerAdapter):
    """LoggerAdapter that automatically prepends [role][turn=N] to every log line.

    Subclasses should use ``self._log`` instead of ``logger`` directly so that
    all log lines carry the agent's role and current OODA turn without
    requiring manual f-string prefixes.

    Usage in subclasses::

        self._log.info("Starting pre-flight")
        # emits: [researcher][turn=0] Starting pre-flight
    """

    def __init__(self, base_logger: logging.Logger, role: str) -> None:
        super().__init__(base_logger, extra={"role": role, "turn": 0})

    def set_turn(self, turn: int) -> None:
        cast(Dict[str, Any], self.extra)["turn"] = turn

    def process(self, msg, kwargs):
        role = self.extra.get("role", "?")
        turn = self.extra.get("turn", 0)
        return f"[{role}][turn={turn}] {msg}", kwargs

# Regex patterns for parsing LLM tool call responses
_TOOL_PATTERN = re.compile(r"^TOOL:\s*(.+)$", re.MULTILINE)
_PARAMS_PATTERN = re.compile(r"^PARAMS:\s*(.+)$", re.MULTILINE | re.DOTALL)
_DONE_PATTERN = re.compile(r"^DONE:\s*(.+?)(?=\nRESULT:|\Z)", re.MULTILINE | re.DOTALL)
_RESULT_PATTERN = re.compile(r"^RESULT:\s*(.+)$", re.MULTILINE | re.DOTALL)
_COMPLETE_PATTERN = re.compile(r"^COMPLETE:\s*(yes|no)\b", re.MULTILINE | re.IGNORECASE)
_COMBINED_DONE_RESULT_PATTERN = re.compile(
    r"^DONE/RESULT\s*:?\s*\n(.+)$", re.MULTILINE | re.DOTALL
)
_THOUGHT_PATTERN = re.compile(r"^THOUGHT:\s*(.+?)(?=\n(?:TOOL|DONE|RESULT|THOUGHT|NOTE):|\Z)", re.MULTILINE | re.DOTALL)
# Notes ride along with any action: writing down what is established costs no turn.
_NOTE_PATTERN = re.compile(r"^NOTE:\s*(.+?)(?=\n(?:NOTE|THOUGHT|TOOL|PARAMS|DONE|RESULT):|\Z)", re.MULTILINE | re.DOTALL)

# ── Observation channel integrity (issue #57) ─────────────────────────────
# The agent sees every tool result whole. Results of earlier turns stay
# readable through read_turn_result for the lifetime of the step, across epochs.
# Whole results of the last N tool turns are kept; older turns are released
# whole, never cut, when the window or the total-size budget is exceeded.
_TURN_RESULT_WINDOW = int(os.getenv("SUBAGENT_TURN_RESULT_WINDOW", "10"))
# Exchanges the agent sees each turn, at least, and carries into a continued step.
_CONVERSATION_WINDOW = 10
# Older exchanges leave view this many at a time: the conversation's start then stays
# put between slides, so each prompt repeats the one before and is served from cache.
_WINDOW_SLIDE = 5
_TURN_RESULT_BUDGET = int(os.getenv("SUBAGENT_TURN_RESULT_BUDGET", "2000000"))
# Characters of earlier tool results each prompt carries whole; the newest is always whole.
_THREAD_RESULT_BUDGET = int(os.getenv("SUBAGENT_THREAD_RESULT_BUDGET", "120000"))
# read_turn_result pages are shown whole, so each page is sized to fit the agent's view.
_READ_PAGE_LIMIT = int(os.getenv("SUBAGENT_READ_PAGE_LIMIT", "20000"))


def _retain_turn_result(internal_variables: Dict[str, Any], turn: int, text: str) -> None:
    """Keep this turn's result whole; release older turns whole, recording why."""
    ring = internal_variables.setdefault("_turn_results", {})
    released = internal_variables.setdefault("_released_turn_results", {})
    ring[str(turn)] = text
    for stale in sorted(ring, key=int)[:-_TURN_RESULT_WINDOW]:
        del ring[stale]
        released[stale] = f"only the last {_TURN_RESULT_WINDOW} tool turns are kept"
    while len(ring) > 1 and sum(len(value) for value in ring.values()) > _TURN_RESULT_BUDGET:
        oldest = min(ring, key=int)
        del ring[oldest]
        released[oldest] = (
            f"retained results are kept within {_TURN_RESULT_BUDGET} chars and later "
            "results needed the room"
        )


def _checkpoint(state: KernelState, conversation_history: list) -> str:
    """The step state with the agent's recent exchanges; images stay as their receipts."""
    state.conversation = [
        {key: value for key, value in entry.items() if key != "images"}
        for entry in conversation_history[-_CONVERSATION_WINDOW:]
    ]
    return state.model_dump_json()


def _now_fact() -> str:
    """The date and time where this runs, so relative dates on pages and in tasks can be resolved."""
    now = datetime.now().astimezone()
    offset = now.strftime("%z")
    return f"Now: {now.strftime('%A %d %B %Y, %H:%M')} local time (UTC{offset[:3]}:{offset[3:]})."


def _observe(tool_name: str, tool_result: Any, turn: int, whole: bool = True) -> str:
    """The agent's view of a tool result: all of it, without a success envelope around it."""
    if (
        isinstance(tool_result, dict) and set(tool_result) == {"status", "output"}
        and tool_result["status"] == "success"
    ):
        return str(tool_result["output"])
    return str(tool_result)


def _canonical(value: Any) -> str:
    try:
        return json.dumps(value, sort_keys=True, default=str, separators=(",", ":"))
    except (TypeError, ValueError):
        return repr(value)


def _identical_call_record(
    earlier: List[Any], tool_name: str, params: Dict[str, Any], result: Any
) -> str:
    """What the tool log shows about earlier calls identical to this one, if any."""
    fingerprint = FailureLedger.fingerprint(tool_name, params)
    same = [
        receipt for receipt in earlier
        if receipt.tool_name == tool_name
        and FailureLedger.fingerprint(receipt.tool_name, receipt.tool_input) == fingerprint
    ]
    if not same:
        return ""
    last = same[-1]
    unchanged = _canonical(last.tool_output) == _canonical(result)
    return (
        f"This exact call (same tool, same arguments) ran {len(same)} time(s) earlier "
        f"in this run; the last, receipt {last.receipt_id}, ended {last.status}, and "
        f"its result was {'identical to' if unchanged else 'different from'} this one."
    )


def _in_view(conversation_history: list) -> list:
    """The exchanges the agent sees: the last 10 at least, and up to 4 more before the next slide."""
    excess = len(conversation_history) - _CONVERSATION_WINDOW
    if excess <= 0:
        return list(conversation_history)
    return conversation_history[excess // _WINDOW_SLIDE * _WINDOW_SLIDE:]


def _leaves_view_soon(conversation_history: list) -> bool:
    """Whether the oldest exchanges in view are within a turn or two of leaving it."""
    return len(conversation_history) >= _CONVERSATION_WINDOW and (
        len(_in_view(conversation_history)) >= _CONVERSATION_WINDOW + _WINDOW_SLIDE - 3
    )


def _notes_in_view(visible: list) -> frozenset:
    """Notes the agent can read in the calls it made within view."""
    seen = set()
    for entry in visible:
        call = entry.get("tool_call") or {}
        arguments = _extract_json_object(call.get("arguments") or "") if call else None
        notes = (arguments or {}).get(_NOTES_ARGUMENT)
        for note in notes if isinstance(notes, list) else [notes] if notes else []:
            if str(note).strip():
                seen.add(str(note).strip())
    return frozenset(seen)


def _thread_history(messages: List[Dict[str, Any]], conversation_history: list) -> None:
    """Prior turns in view: a native turn as its tool call and result, a text turn as a pair.

    A perception a later one replaced is shown as a pointer to it: the agent
    acts on the latest view of the world, and can still read the older one. The
    newest result is always whole; earlier ones are whole while they fit the thread
    budget, newest first, and otherwise shown as a reference to read them whole again.
    A turn's lead, what the runtime told the agent before it acted, precedes it,
    so each prompt extends the one before rather than rewriting its end.
    """
    recent = _in_view(conversation_history)
    latest = max((i for i, entry in enumerate(recent) if entry.get("perception")), default=None)
    shown: List[str] = [""] * len(recent)
    carried = 0
    for i in range(len(recent) - 1, -1, -1):
        observation = recent[i]["observation"]
        if recent[i].get("perception") and i != latest:
            observation = recent[i]["superseded"]
        elif (
            i != len(recent) - 1 and recent[i].get("reference")
            and carried + len(observation) > _THREAD_RESULT_BUDGET
        ):
            observation = recent[i]["reference"]
        carried += len(observation)
        shown[i] = observation
    for hist_entry, observation in zip(recent, shown):
        if hist_entry.get("lead"):
            messages.append({"role": "user", "content": hist_entry["lead"]})
        call = hist_entry.get("tool_call")
        images = hist_entry.get("images", ())
        if call is None:
            messages.append({"role": "assistant", "content": hist_entry["assistant"]})
            messages.append({
                "role": "user",
                "content": multimodal.with_images(observation, images),
            })
            continue
        messages.append({
            "role": "assistant",
            "content": hist_entry["assistant"] or None,
            "tool_calls": [{
                "id": call["id"],
                "type": "function",
                "function": {"name": call["name"], "arguments": call["arguments"]},
                **({"signature": call["signature"]} if call.get("signature") else {}),
            }],
        })
        messages.append({
            "role": "tool",
            "tool_call_id": call["id"],
            "content": observation,
        })
        if images:
            # A tool message carries text only, so the images it returned follow it.
            messages.append({
                "role": "user",
                "content": multimodal.with_images(f"Images returned by {call['name']}:", images),
            })


#: The function that finishes a native turn, as DONE/RESULT finishes a text one.
_DONE_FUNCTION = "done"
#: The argument every native function carries for notes, as NOTE: lines carry them in text.
_NOTES_ARGUMENT = "working_notes"
# Described once in the system prompt; repeating it in every function cost ~60
# tokens per tool per turn.
_NOTES_SCHEMA = {"type": "array", "items": {"type": "string"}}
#: Tools that reach other agents: offered only while another agent is reachable.
_PEER_TOOLS = frozenset({
    "ask_peer", "ask_capability", "send_to_peer", "list_peers", "broadcast_update", "read_mailbox",
})
#: Cross-session memory tools: offered only when memory that keeps and recalls is attached.
_MEMORY_TOOLS = {"remember": "remember", "recall": "recall"}
#: Tools that read the rest of the workflow: offered only when there is a rest to read.
_WORKFLOW_TOOLS = frozenset({"inspect_workflow", "read_workflow_step"})
#: Tools a program never calls: finishing, memory, runtime and peer controls, and
#: the coder's own code and workspace tools (a program already is code).
_UNBRIDGED_TOOLS = frozenset({
    "run_tool_program", "read_turn_result", "remember", "recall", "time_s", "is_actionable",
    "write_code", "execute_code", "validate_code", "register_function", "repair_atom",
    "inspect_atom_for_repair", "check_registry", "delegate_research", "evaluate_decisions",
    "workspace_list", "workspace_read", "workspace_search", "workspace_write",
    "workspace_edit", "workspace_run",
}) | _PEER_TOOLS | _WORKFLOW_TOOLS
_WORKFLOW_CONTEXT_KEYS = (
    "previous_step_results", "downstream_roles", "workflow_plan", "_goal", "_completed_steps",
)
_INVALID_FUNCTION_CHARS = re.compile(r"[^a-zA-Z0-9_-]")
_JSON_SCALARS = {str: "string", bool: "boolean", int: "integer", float: "number"}


def _json_schema_for(annotation: Any) -> Dict[str, Any]:
    """JSON Schema for one annotated argument; an empty schema where none is declared."""
    origin = typing.get_origin(annotation)
    if origin is typing.Literal:
        values = list(typing.get_args(annotation))
        kinds = {_JSON_SCALARS.get(type(value)) for value in values}
        return {"enum": values, **({"type": kinds.pop()} if len(kinds) == 1 else {})}
    if origin in (Union, types.UnionType):
        options = [arg for arg in typing.get_args(annotation) if arg is not type(None)]
        return _json_schema_for(options[0]) if len(options) == 1 else {}
    base = origin or annotation
    if base in _JSON_SCALARS:
        return {"type": _JSON_SCALARS[base]}
    if base in (list, tuple, set, frozenset):
        return {"type": "array", "items": {}}
    if base is dict:
        return {"type": "object"}
    return {}


def _result_shape(value: Any, depth: int = 0) -> Any:
    """The shape of a tool's result (field names and types, never values)."""
    if isinstance(value, str):
        text = value.strip()
        if depth == 0 and text[:1] in "{[":
            try:
                return _result_shape(json.loads(text), depth)
            except ValueError:
                pass
        return "text" if depth == 0 else "str"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if value is None:
        return "null"
    if depth >= 3:
        return "..."
    if isinstance(value, dict):
        keys = list(value)[:15]
        shape = {str(key): _result_shape(value[key], depth + 1) for key in keys}
        if len(value) > len(keys):
            shape["..."] = f"{len(value) - len(keys)} more"
        return shape
    if isinstance(value, (list, tuple)):
        return [_result_shape(value[0], depth + 1)] if value else []
    return type(value).__name__


def _render_shape(value: Any) -> str:
    if isinstance(value, str) and value == "text":
        return "plain text"
    rendered = json.dumps(value, separators=(",", ":"))
    return rendered if len(rendered) <= 400 else rendered[:397] + "..."


def _parameters_schema(func: Callable) -> Dict[str, Any]:
    """A tool's arguments as JSON Schema, read from its signature."""
    schema: Dict[str, Any] = {"type": "object", "properties": {}}
    try:
        signature = inspect.signature(func)
    except (TypeError, ValueError):
        return schema
    try:
        hints = typing.get_type_hints(func)
    except Exception:
        hints = {}
    required = []
    for name, parameter in signature.parameters.items():
        if parameter.kind in (parameter.VAR_POSITIONAL, parameter.VAR_KEYWORD):
            continue
        schema["properties"][name] = _json_schema_for(hints.get(name, parameter.annotation))
        if parameter.default is parameter.empty:
            required.append(name)
    if required:
        schema["required"] = required
    return schema


def _extract_json_object(text: str) -> Optional[Dict[str, Any]]:
    """Extract the first complete JSON object from *text* using brace-counting.

    Handles multi-line JSON (e.g. when a ``code`` param contains literal
    newlines) which would break the naive ``split("\\n")[0]`` approach.
    Returns the parsed dict, or None if no valid JSON object is found.

    String-aware: braces inside quoted strings are ignored so that code
    like ``{"code": "if x > 0: {print('yes')}"}`` parses correctly.

    If the initial ``json.loads`` fails (typically because the LLM emitted
    literal newlines/tabs inside JSON string values), the function repairs
    the JSON by escaping unescaped control characters within strings and
    retries the parse.
    """
    start = text.find("{")
    if start == -1:
        return None

    depth = 0
    in_string = False
    escape_next = False
    end = start

    for i in range(start, len(text)):
        ch = text[i]
        if escape_next:
            escape_next = False
            continue
        if ch == "\\":
            escape_next = True
            continue
        if ch == '"' and not escape_next:
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    else:
        # Never closed — incomplete JSON
        return None

    candidate = text[start:end]

    # Fast path: valid JSON as-is
    try:
        return json.loads(candidate)
    except (json.JSONDecodeError, ValueError):
        pass

    # Repair path: escape raw newlines/tabs/carriage-returns inside strings.
    # LLMs frequently emit multi-line code values with literal newlines
    # instead of \\n escape sequences, producing invalid JSON.
    repaired = _repair_json_strings(candidate)
    try:
        return json.loads(repaired)
    except (json.JSONDecodeError, ValueError):
        pass

    # Repair path: trailing commas before } or ] (valid python, invalid JSON).
    detrailed = re.sub(r",(\s*[}\]])", r"\1", repaired)
    if detrailed != repaired:
        try:
            return json.loads(detrailed)
        except (json.JSONDecodeError, ValueError):
            pass

    # Repair path: python-literal dicts (single quotes, True/False/None).
    # Normalization of common structured variants, never prose guessing.
    try:
        result = ast.literal_eval(candidate)
        if isinstance(result, dict):
            return result
    except (ValueError, SyntaxError, MemoryError, RecursionError):
        pass
    return None


def _repair_json_strings(text: str) -> str:
    """Escape unescaped control characters (newlines, tabs) inside JSON string values.

    Walks the JSON text character-by-character, tracking whether we're inside
    a string literal. When a raw \\n, \\r, or \\t is found inside a string,
    it's replaced with the JSON escape sequence.
    """
    out: list[str] = []
    in_string = False
    escape_next = False

    for ch in text:
        if escape_next:
            out.append(ch)
            escape_next = False
            continue

        if ch == "\\":
            out.append(ch)
            escape_next = True
            continue

        if ch == '"':
            in_string = not in_string
            out.append(ch)
            continue

        if in_string:
            if ch == "\n":
                out.append("\\n")
                continue
            if ch == "\r":
                out.append("\\r")
                continue
            if ch == "\t":
                out.append("\\t")
                continue

        out.append(ch)

    return "".join(out)



class ToolDefinition:
    """A registered tool available to a subagent."""

    def __init__(
        self, name: str, func: Callable, description: str, phase: Optional[str] = None,
        parameters: Optional[Dict[str, Any]] = None,
    ):
        self.name = name
        self.func = func
        self.description = description
        # A declared JSON Schema wins over the signature, which wrappers taking **kwargs hide.
        self.parameters = parameters
        # The phase the registrant declared, if any. Only a declared phase
        # overrides the cognition name sets when budgeting the tool.
        self.declared_phase = phase
        self.phase = phase or "action"


class BaseSubAgent(ABC):
    """
    Abstract base for all subagents dispatched by the kernel.

    Subclasses implement:
    - get_system_prompt(): Returns the system prompt for this subagent
    - setup_tools(): Registers tools via register_tool()

    The base class handles:
    - Tool registration and lookup
    - OODA loop execution with turn-by-turn reasoning
    - Context management with priority-stack prompt building
    - Convergence detection and failure memory
    - AgentOutput construction
    """

    #: How many times the same completion attempt may be rejected before the step
    #: ends. An attempt only counts as the same when the gate observed identical
    #: values, the agent submitted an identical result, and no tool ran in between
    #: — so an agent that is still working is never cut off, however long it takes.
    max_identical_done_attempts: int = 3

    #: Whether this dispatch's turns are native tool calls; set by run() from the LLM client.
    _native_protocol: bool = False

    #: Seconds after the lease ends that a tool keeping its own deadline has to hand back
    #: what it did, before the call is stopped.
    tool_handback_s: float = float(os.getenv("SUBAGENT_TOOL_HANDBACK_S", "60"))

    #: Tools whose results are the agent's perception and are shown whole, never clipped.
    whole_observation_tools: frozenset = frozenset()
    #: Perceptions of a changing world: a newer result replaces older ones in the agent's view.
    perception_tools: frozenset = frozenset()
    #: Registered and callable, but never offered to the model: runtime helpers that
    #: share the ``_tool_`` prefix, and tools that only echo their input back, which
    #: cost a turn and add nothing to the answer.
    hidden_tools: frozenset = frozenset({"time_s", "is_actionable"})
    #: Directory of the other agents this one can reach; set by the Kernel.
    peer_directory = None
    #: Sandbox that runs tool programs; set by the Kernel. None leaves them off.
    program_sandbox = None
    #: Whether this role is offered run_tool_program over its own tools.
    programmable: bool = True

    def __init__(
        self,
        agent_id: str,
        role: str,
        llm_client,
        redis_store=None,
        blob_storage=None,
        search_client=None,
        code_registry=None,
        memory_enabled: bool = False,
    ):
        self.agent_id = agent_id
        self.role = role
        self.llm_client = llm_client
        self.redis_store = redis_store
        self.blob_storage = blob_storage
        self.search_client = search_client
        self.code_registry = code_registry
        self.memory_enabled = memory_enabled
        self._tools: Dict[str, ToolDefinition] = {}

        # Structured logger — use self._log instead of bare logger in subclasses
        self._log = SubagentLogAdapter(logger, role)

        # Cognition infrastructure — reset per run() call
        self._cognition: Optional[AgentCognitionManager] = None

        # Live KernelState for the current dispatch — set at the top of run()
        # so built-in tools (read_turn_result) can reach the retention ring.
        self._current_state: Optional[KernelState] = None
        self._current_memory = None

        # Let subclass register its tools explicitly
        self.setup_tools()

        # Auto-discover any _tool_* methods not already registered by setup_tools()
        self._autodiscover_tools()

    #: Root of the run workspace; file tools resolve every path inside it.
    workspace_root = None

    def _workspace_path(self, path: str = ".") -> str:
        """Resolve a tool path inside the run workspace; anything else is refused."""
        from pathlib import Path

        if self.workspace_root is None:
            raise PermissionError("No workspace is attached to this run, so files are unavailable.")
        root = Path(self.workspace_root).resolve()
        target = (root / str(path or ".")).resolve()
        if target != root and root not in target.parents:
            raise PermissionError(f"{path} is outside this run's workspace.")
        return str(target)

    def register_tool(
        self, name: str, func: Callable, description: str, phase: Optional[str] = None,
        parameters: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Register a tool available to this subagent."""
        self._tools[name] = ToolDefinition(name, func, description, phase, parameters)

    async def _keep_notes(self, state: KernelState, notes) -> None:
        """Write the agent's notes to its step scratchpad and its every-turn view."""
        working = getattr(self._current_memory, "working", None)
        for note in notes or ():
            if working is not None:
                await working.write("note", {"content": note, "turn": state.turn})
            state.working_notes.append({"turn": state.turn, "note": note})

    async def _tool_remember(self, fact: str, kind: str = "fact") -> Dict[str, Any]:
        """Keep something worth knowing in a later session (params: fact, optional kind).

        You are the memory lifecycle: nothing persists across sessions unless
        you decide it should. Record outcomes and durable facts, in the words a
        future you would want to read: what was done, what was found, what a
        person decided. Do not record diagnoses of failures or guesses about
        why something did not work; those expire with the bug.
        """
        memory = self._current_memory
        if memory is None or not hasattr(memory, "remember"):
            return {
                "status": "error",
                "error": "No cross-session memory is attached to this run, so nothing can be kept.",
                "semantic_error": "NO_MEMORY",
            }
        text = (fact or "").strip()
        if not text:
            return {"status": "error", "error": "Nothing to remember: fact was empty."}
        kept = await memory.remember(text, kind=kind, role=self.role)
        if not kept:
            return {
                "status": "error",
                "error": "The memory tier did not accept this; it was not kept.",
                "semantic_error": "NOT_KEPT",
            }
        getattr(self, "_kept_memories", []).append({"kind": kind, "fact": text})
        return {"status": "success", "kept": text, "kind": kind}

    async def _tool_recall(self, query: str, limit: int = 5) -> Dict[str, Any]:
        """Ask what earlier sessions recorded about something (params: query, optional limit).

        Results are the past, scored by relevance. They tell you what was true
        then, not what is true now.
        """
        memory = self._current_memory
        if memory is None or not hasattr(memory, "recall"):
            return {"status": "success", "results": [], "note": "No cross-session memory is attached to this run."}
        results = await memory.recall((query or "").strip(), limit=max(1, min(int(limit), 20)))
        return {"status": "success", "results": results, "count": len(results)}

    def _tool_read_turn_result(self, turn: int, offset: int = 0, length: int = 0) -> Dict[str, Any]:
        """Read the whole output of an earlier tool call (params: turn, optional offset/length).

        ``turn`` is the number in the result's [Turn N] label, the last part of its
        receipt; it names the call across the step's epochs. Results of earlier turns
        leave the conversation as it moves on; the last few are retained whole and
        readable here, a page at a time.
        """
        state = self._current_state
        variables = state.internal_variables if state is not None else {}
        ring = variables.get("_turn_results") or {}
        full = ring.get(str(turn))
        if full is None:
            available = sorted(ring, key=int) if ring else []
            released = (variables.get("_released_turn_results") or {}).get(str(turn))
            why = (
                f"Turn {turn}'s result was released because {released}; repeat that call "
                "if you still need it."
                if released else f"No retained result for turn {turn}."
            )
            return {
                "status": "error",
                "error": f"{why} Retained turns: {available or 'none'}.",
            }
        offset = max(0, int(offset))
        length = min(int(length) or _READ_PAGE_LIMIT, _READ_PAGE_LIMIT)
        chunk = full[offset:offset + length]
        remaining = max(0, len(full) - (offset + len(chunk)))
        return {
            "status": "success",
            "turn": turn,
            "offset": offset,
            "total_chars": len(full),
            "remaining_chars": remaining,
            "output": chunk,
            **({"note": f'call again with {{"turn": {turn}, "offset": {offset + len(chunk)}}} for the rest'}
               if remaining else {}),
        }

    @property
    def tool_names(self) -> List[str]:
        """List of registered tool names."""
        return list(self._tools.keys())

    def _peers_reachable(self) -> bool:
        directory = self.peer_directory if self.peer_directory is not None else getattr(self, "peers", None)
        if directory is None:
            return False
        try:
            return bool(directory.list_peers())
        except Exception:  # noqa: BLE001 - an unanswerable directory keeps the tools offered
            return True

    def _offers_tool(self, name: str, context: Optional[Dict]) -> bool:
        """Whether the model is offered this tool on this run.

        A tool that cannot do anything here (no other agent to ask, no memory to
        keep in, no other step to read) costs its schema on every turn and invites
        a wasted call, so it is left out while that holds.
        """
        if name in self.hidden_tools:
            return False
        if name in _PEER_TOOLS:
            return self._peers_reachable()
        if name in _MEMORY_TOOLS:
            return hasattr(self._current_memory, _MEMORY_TOOLS[name])
        if name in _WORKFLOW_TOOLS:
            return any((context or {}).get(key) for key in _WORKFLOW_CONTEXT_KEYS)
        if name == "run_tool_program":
            return (
                self.programmable and self._programs_can_run()
                and bool(self._program_tools(context))
            )
        return True

    def _programs_can_run(self) -> bool:
        """Whether the Kernel's sandbox will run model-written code on this host."""
        sandbox = self.program_sandbox
        if sandbox is None:
            return False
        cached = getattr(self, "_program_sandbox_ready", None)
        if cached is None or cached[0] is not sandbox:
            try:
                ready = bool(
                    getattr(sandbox, "allow_unsafe_local_execution", False) is True
                    or getattr(sandbox, "confined", False)
                )
            except Exception:  # noqa: BLE001 - a sandbox that cannot answer runs nothing
                ready = False
            cached = (sandbox, ready)
            self._program_sandbox_ready = cached
        return cached[1]

    def _program_tools(self, context: Optional[Dict]) -> List["ToolDefinition"]:
        """The agent's own tools a program may call."""
        return [
            tool for tool in self._tools.values()
            if tool.name not in _UNBRIDGED_TOOLS and tool.name.isidentifier()
            and self._offers_tool(tool.name, context)
        ]

    @staticmethod
    def _tool_signature(tool: "ToolDefinition") -> Tuple[List[str], str]:
        schema = copy.deepcopy(tool.parameters) if tool.parameters else _parameters_schema(tool.func)
        properties = schema.get("properties") or {}
        required = set(schema.get("required") or [])
        rendered = ", ".join(
            f"{name}: {spec.get('type', 'any')}" + ("" if name in required else " = ...")
            for name, spec in properties.items()
        )
        return list(properties), f"{tool.name}({rendered})"

    def _note_result_shape(self, tool_name: str, result: Any) -> None:
        """Remember what a tool returns, so programs are written against its real fields."""
        if isinstance(result, dict) and set(result) == {"status", "output"}:
            result = result["output"]
        if isinstance(result, dict) and result.get("status") == "error":
            return
        shapes = self.__dict__.setdefault("_result_shapes", {})
        shapes[tool_name] = _render_shape(_result_shape(result))

    def _program_description(self, context: Optional[Dict]) -> str:
        # Each function is the tool of the same name, described in its own definition;
        # repeating that here was paid for on every call of every run.
        lines = [
            "Run a Python program that calls your tools as functions. Only what it "
            "prints and what it puts in `result` come back to you; the tool results "
            "it reads stay out of your view. Use it whenever you need several tool "
            "results, or must loop over, filter, join, count or total them. Each "
            "function returns what the tool returns, with JSON already decoded into "
            "dicts and lists, and raises on a tool error. Write against the return "
            "shapes below; for a function whose return is not known yet, print a "
            "small sample first rather than guess its fields. json, re, datetime and "
            "math are available. Print a compact answer, not raw data. Your functions:",
        ]
        shapes = getattr(self, "_result_shapes", {})
        for tool in self._program_tools(context):
            _, signature = self._tool_signature(tool)
            lines.append(f"  {signature} -> {shapes.get(tool.name) or 'not seen yet'}")
        return "\n".join(lines)

    async def _tool_run_tool_program(self, code: str) -> Dict[str, Any]:
        """Run a Python program that calls your tools as functions."""
        state = self._current_state
        context = getattr(state, "context", None)
        tools = {tool.name: tool for tool in self._program_tools(context)}
        if not tools or not self._programs_can_run():
            return {"status": "error", "error": "Tool programs are not available on this run."}
        trace = getattr(self, "_run_trace", None)
        receipts: List[str] = []
        counts: Dict[str, int] = {}

        async def bridge(name: str, params: Dict[str, Any]) -> Any:
            if name not in tools:
                raise RuntimeError(f"{name} is not one of the functions this program was given.")
            params = dict(params or {})
            started_at, started = time.time(), time.monotonic()
            if trace is not None:
                trace.log_tool_start(name, params)
            result = await self._pre_execute_hook(name, params, state)
            if result is None:
                result = await self._execute_tool(name, params)
            error = result.get("error") if isinstance(result, dict) else None
            receipt = state.add_tool_result(
                name, params, result, error=error, timestamp=started_at,
                duration_ms=round((time.monotonic() - started) * 1000), via_program=True,
            )
            receipts.append(receipt.receipt_id)
            counts[name] = counts.get(name, 0) + 1
            self._note_result_shape(name, result)
            if trace is not None:
                trace.log_tool_result(name, result, error=error)
            if isinstance(result, dict) and result.get("status") == "waiting":
                raise RuntimeError(
                    f"{name} needs a person's decision; call it directly, not from a program."
                )
            if isinstance(result, dict) and result.get("status") == "error":
                raise RuntimeError(f"{name}: {result.get('error')}")
            if isinstance(result, dict) and set(result) == {"status", "output"}:
                result = result["output"]
            if isinstance(result, str) and result.lstrip()[:1] in ("{", "["):
                # Programs work with data: JSON text arrives already decoded.
                try:
                    return json.loads(result)
                except ValueError:
                    pass
            return result

        outcome = await self.program_sandbox.execute(
            code,
            context={
                "_tool_bridge": bridge,
                "_tool_signatures": {
                    name: self._tool_signature(tool)[0] for name, tool in tools.items()
                },
            },
        )
        # What the program reported, once: the sandbox envelope repeats itself and
        # carries file bookkeeping a tool program does not produce.
        failed = outcome.get("success") is False or outcome.get("status") in ("error", "failure")
        report: Dict[str, Any] = {"status": "error" if failed else "success"}
        stdout = outcome.get("stdout")
        if stdout:
            report["stdout"] = stdout
        data = outcome.get("data", outcome.get("result"))
        if data is not None:
            report["result"] = data
        if failed:
            report["error"] = outcome.get("error") or "The program failed."
            if outcome.get("error_type"):
                report["error_type"] = outcome["error_type"]
        # Calls per function, so a program that read one page of eight shows it.
        report["tool_calls"] = counts
        report["tool_receipts"] = receipts
        return report

    def _offered_tools(self, context: Optional[Dict]) -> List["ToolDefinition"]:
        return [tool for tool in self._tools.values() if self._offers_tool(tool.name, context)]

    def get_tool_descriptions(self) -> str:
        """Format tool descriptions for prompt injection."""
        context = getattr(getattr(self, "_current_state", None), "context", None)
        lines = ["Available tools:"]
        for tool in self._offered_tools(context):
            description = (
                self._program_description(context)
                if tool.name == "run_tool_program" else tool.description
            )
            lines.append(f"  - {tool.name}: {description} [{tool.phase}]")
        return "\n".join(lines)

    def _native_tool_specs(self, context: Optional[Dict]) -> Tuple[List[Dict[str, Any]], Dict[str, str]]:
        """The offered tools and done as provider functions, and each function's tool.

        Fixed for the run once built: tool definitions lead every prompt, so one
        that changed mid-run (a newly learned return shape, a tool appearing) made
        every later turn miss the provider's cache. They are rebuilt only when the
        offered set itself changes.
        """
        offered = tuple(tool.name for tool in self._offered_tools(context))
        snapshot = getattr(self, "_spec_snapshot", None)
        run = id(getattr(self, "_current_state", None))
        if snapshot is not None and snapshot[0] == (run, offered):
            return snapshot[1], snapshot[2]
        specs, tools_by_function = self._build_native_tool_specs(context)
        self._spec_snapshot = ((run, offered), specs, tools_by_function)
        self._shapes_described = dict(getattr(self, "_result_shapes", {}) or {})
        return specs, tools_by_function

    def _shapes_learned_this_run(self, in_view: frozenset = frozenset()) -> str:
        """Return shapes learned after the tool definitions were fixed, for the turn's tail.

        A tool whose result is in the conversation shows its shape there already.
        """
        described = getattr(self, "_shapes_described", None)
        state = getattr(self, "_current_state", None)
        if described is None or not self._offers_tool("run_tool_program", getattr(state, "context", None)):
            return ""
        shapes = getattr(self, "_result_shapes", {}) or {}
        fresh = {
            name: shape for name, shape in shapes.items()
            if described.get(name) != shape and name not in in_view
        }
        if not fresh:
            return ""
        return "## RETURN SHAPES LEARNED THIS RUN (for run_tool_program)\n" + "\n".join(
            f"- {name}: {shape}" for name, shape in fresh.items()
        )

    def _build_native_tool_specs(self, context: Optional[Dict]) -> Tuple[List[Dict[str, Any]], Dict[str, str]]:
        specs, tools_by_function = [], {}
        for tool in self._offered_tools(context):
            function = _INVALID_FUNCTION_CHARS.sub("_", tool.name)[:64]
            while function in tools_by_function or function == _DONE_FUNCTION:
                function = f"{function[:56]}_{len(tools_by_function)}"
            tools_by_function[function] = tool.name
            parameters = (
                copy.deepcopy(tool.parameters) if tool.parameters else _parameters_schema(tool.func)
            )
            parameters.setdefault("properties", {})
            if _NOTES_ARGUMENT in parameters["properties"]:
                raise ValueError(
                    f"Tool {tool.name!r} declares {_NOTES_ARGUMENT!r}, which native turns "
                    "reserve for the agent's notes; rename the parameter."
                )
            parameters["properties"][_NOTES_ARGUMENT] = _NOTES_SCHEMA
            specs.append({"type": "function", "function": {
                "name": function,
                "description": (
                    self._program_description(context)
                    if tool.name == "run_tool_program" else tool.description
                ),
                "parameters": parameters,
            }})
        specs.append(self._done_function(context))
        return specs, tools_by_function

    @staticmethod
    def _done_function(context: Optional[Dict], landing: bool = False) -> Dict[str, Any]:
        # How to finish is said here, where done is called, and nowhere else.
        result: Dict[str, Any] = {
            "description": (
                "Only data a later step or the caller needs that the summary does not "
                "hold (a list, a record, figures), never a copy of the answer; leave it "
                "out when there is none. Where it reports what a tool did, cite that "
                "call's receipt in it as tool_receipt_id."
            ),
        }
        declared = (context or {}).get("output_schema")
        definitions: Dict[str, Any] = {}
        if hasattr(declared, "model_json_schema"):
            schema = declared.model_json_schema()
            # "#/$defs/..." references resolve from the parameters root.
            definitions = schema.pop("$defs", {})
            result = {**schema, **result}
        parameters: Dict[str, Any] = {
            "type": "object",
            "properties": {
                "summary": {
                    "type": "string",
                    "description": (
                        "The complete answer the person reads, with any lists or "
                        "details they asked for. No receipt ids here."
                    ),
                },
                "result": result,
                # No working_notes: done ends the run, so a note written here is never read.
            },
            # A declared output schema is the step's contract; otherwise the answer
            # is the summary, and a required result was written out as a second copy.
            "required": ["summary", "result"] if declared is not None else ["summary"],
        }
        parameters["properties"]["complete"] = {
            "type": "boolean",
            "description": (
                "True only when this answer covers everything the task asked for, "
                "from what was gathered; false when any part was not reached."
                if landing else
                "True when you carried out the task; false when you could not: something "
                "you needed was unavailable, refused or failed, or you stopped short of "
                "what was asked; say in summary what stopped you. Facts you looked for "
                "and found do not exist still count as carried out."
            ),
        }
        parameters["required"].append("complete")
        if definitions:
            parameters["$defs"] = definitions
        return {"type": "function", "function": {
            "name": _DONE_FUNCTION,
            "description": (
                "Finish the task with the complete answer. Call it only when the task "
                "is complete, never merely because more tool calls are needed."
            ),
            "parameters": parameters,
        }}

    @staticmethod
    def _parse_native_turn(llm_result: Dict[str, Any], tools_by_function: Dict[str, str]) -> Dict[str, Any]:
        """The turn's action from the model's first function call."""
        content = (llm_result.get("content") or "").strip()
        calls = llm_result.get("tool_calls") or []
        if not calls:
            return {"type": "raw", "content": content}
        # Calls that do not depend on each other arrive together and all run this
        # turn. A done sent alongside them was written before their results
        # existed, so it is not taken; the agent finishes once it has seen them.
        actions = [call for call in calls if call["name"] != _DONE_FUNCTION] or calls[:1]
        parsed = [
            BaseSubAgent._parse_native_call(call, content if index == 0 else "", tools_by_function)
            for index, call in enumerate(actions)
        ]
        first = parsed[0]
        if first["type"] == "tool" and len(parsed) > 1:
            first["more_calls"] = parsed[1:]
        if len(actions) < len(calls):
            first["dropped_done"] = True
        return first

    @staticmethod
    def _parse_native_call(
        call: Dict[str, Any], content: str, tools_by_function: Dict[str, str],
    ) -> Dict[str, Any]:
        native_call = {key: call[key] for key in ("id", "name", "arguments", "signature") if key in call}
        arguments = _extract_json_object(call["arguments"]) if call["arguments"].strip() else {}
        raw_notes = arguments.pop(_NOTES_ARGUMENT, None) if arguments is not None else None
        notes = [
            str(note).strip()
            for note in (raw_notes if isinstance(raw_notes, list) else [raw_notes] if raw_notes else [])
            if str(note).strip()
        ]
        kept = {"notes": notes} if notes else {}
        if call["name"] == _DONE_FUNCTION:
            if arguments is None:
                return {"type": "raw", "content": call["arguments"], "native_call": native_call}
            summary = str(arguments.get("summary") or "").strip()
            return {
                "type": "done",
                "thought": content,
                "summary": summary or "Completed via done",
                # An omitted result is the empty object it replaced as the default.
                "result": arguments["result"] if "result" in arguments else {},
                "answer": summary or None,
                "complete": arguments.get("complete"),
                "native_call": native_call,
                **kept,
            }
        return {
            "type": "tool",
            "thought": content,
            "tool": tools_by_function.get(call["name"], call["name"]),
            "params": arguments if arguments is not None else {"raw": call["arguments"]},
            "native_call": native_call,
            **kept,
        }

    @abstractmethod
    def get_system_prompt(self) -> str:
        """Return the system prompt for this subagent."""
        ...

    @abstractmethod
    def setup_tools(self) -> None:
        """Register tools for this subagent. Called during __init__."""
        ...

    def _autodiscover_tools(self) -> None:
        """Auto-register any _tool_* methods not already registered by setup_tools().

        Walks the MRO of the concrete subclass and picks up methods whose names
        begin with ``_tool_`` that were not already registered via register_tool().
        This lets subclass authors use arbitrary decorators (``@property``,
        ``@cached_property``, custom wrappers) without losing tool discovery.

        Explicit register_tool() calls always take priority — auto-discovered
        tools only fill in the gaps.
        """
        for name, method in inspect.getmembers(self, predicate=inspect.ismethod):
            if not name.startswith("_tool_"):
                continue
            tool_name = name[len("_tool_"):]
            if tool_name in self._tools or tool_name in self.hidden_tools:
                continue  # already registered explicitly, or a helper, not a tool
            doc = inspect.getdoc(method) or ""
            description = doc.splitlines()[0] if doc else "No description"
            self._tools[tool_name] = ToolDefinition(tool_name, method, description)

    # ──────────────────────────────────────────────────────────────────────
    # Cross-task persistent memory (opt-in via memory_enabled=True)
    # ──────────────────────────────────────────────────────────────────────

    _MEMORY_KEY_PREFIX = "subagent_memory"

    def _memory_key(self) -> str:
        return f"{self._MEMORY_KEY_PREFIX}:{self.agent_id}"

    async def _restore_memory(self, state: KernelState) -> None:
        """Load persisted internal_variables from Redis into state (if memory_enabled)."""
        if not self.memory_enabled or not self.redis_store:
            return
        try:
            raw = await self.redis_store.get(self._memory_key())
            if raw:
                data = json.loads(raw) if isinstance(raw, (str, bytes)) else raw
                state.internal_variables.update(data)
                self._log.info("Restored %d memory keys from previous run", len(data))
        except Exception as exc:
            self._log.warning("Memory restore failed: %s", exc)

    async def _persist_memory(self, state: KernelState) -> None:
        """Save state.internal_variables to Redis for the next run (if memory_enabled)."""
        if not self.memory_enabled or not self.redis_store:
            return
        try:
            await self.redis_store.set(
                self._memory_key(),
                json.dumps(state.internal_variables),
            )
            self._log.info("Persisted %d memory keys for next run", len(state.internal_variables))
        except Exception as exc:
            self._log.warning("Memory persist failed: %s", exc)

    # ──────────────────────────────────────────────────────────────────────
    # Prompt Building
    # ──────────────────────────────────────────────────────────────────────

    def _build_system_prompt(self) -> str:
        """Build the full system prompt including tool descriptions and protocol.

        The calling agent's identity leads: a sub-agent prompt is an execution
        harness, not a persona, and an application that trains its agent through
        ``system_prompt`` must not lose that the moment work enters the kernel.
        """
        state = getattr(self, "_current_state", None)
        identity = ((getattr(state, "context", None) or {}).get("system_prompt") or "").strip()
        parts = []
        if identity:
            parts += [
                identity,
                "",
                "═══ EXECUTION HARNESS (how you operate this turn) ═══",
                "",
            ]
        if self._native_protocol:
            parts += [
                self.get_system_prompt(),
                "",
                "Protocol:",
                "  Act by calling the functions offered. Call several in one turn when they",
                "  do not depend on each other; they run in order and you see every result",
                "  next turn. Keep calling tools until the task is complete, then call done,",
                "  on its own. Never call done merely because more tool calls are needed.",
                "",
                "Your memory:",
                f"  You see the task and at least your last {_CONVERSATION_WINDOW} exchanges; older ones",
                "  leave your view a few at a time (read_turn_result shows an earlier result",
                "  whole), and a long task may continue across several sittings. A runtime",
                "  notice says when exchanges are about to leave: keep anything from them you",
                "  will still need (a price, a constraint you checked, a decision) in",
                "  working_notes, which every tool call accepts at no extra turn and which you",
                "  see every turn. Until then everything is in view and no note is needed.",
            ]
            return "\n".join(parts)
        parts += [
            self.get_system_prompt(),
            "",
            self.get_tool_descriptions(),
            "",
            "Protocol:",
            "  To use a tool: THOUGHT: <reasoning>\\nTOOL: <name>\\nPARAMS: <json>",
            "  To finish:     THOUGHT: <reasoning>\\nDONE: <complete human answer>\\nRESULT: <json>",
            "  If you could not carry out the task: COMPLETE: no on the line before DONE,",
            "  and say in DONE what stopped you.",
            "  To keep what you established: NOTE: <fact> lines before TOOL or DONE.",
            "  JSON alternative: {\"thought\": \"...\", \"notes\": [...], \"tool\": \"...\", \"params\": {...}}",
            "  JSON finish:      {\"thought\": \"...\", \"done\": \"<complete human answer>\", \"result\": {...}}",
            "  This protocol is one action per turn, not one action per task. After each",
            "  tool result you receive another turn; continue calling tools until the task",
            "  is complete. Never use DONE merely because additional tool calls are needed.",
            "",
            "Finishing:",
            "  DONE is read by the person who asked. Put the complete answer there,",
            "  including any lists or details they asked for. DONE may span lines.",
            "  RESULT carries the data behind that answer, shaped for whoever will",
            "  use it next: the list, the record, the figures. It is not a place",
            "  for status flags, booleans about your own process, or a diagnosis",
            "  of the runtime, and it is not a second copy of the answer: DONE is",
            "  the only answer the person and downstream agents read. If there is",
            "  no data beyond the answer, RESULT may be an empty object. Where RESULT",
            "  reports what a tool did, cite that call's receipt in it as tool_receipt_id.",
            "",
            "Your memory:",
            f"  You see the task, your working notes and at least your last {_CONVERSATION_WINDOW} exchanges. Older",
            "  exchanges are gone from view, and a long task continues across several",
            "  sittings. A large earlier result may appear as a reference that",
            "  read_turn_result shows whole again.",
            "  What you have established (a price, an option, a constraint you",
            "  checked, a page that has or lacks something, a decision) is kept only if",
            "  you write it on a NOTE: line. A note costs no turn: write it in the same",
            "  reply as your next TOOL or DONE. Your notes are shown to you every turn.",
        ]
        return "\n".join(parts)

    @staticmethod
    def _epochs_remain(context: Optional[Dict]) -> bool:
        """True while the workflow budget grants this step another execution epoch."""
        if not isinstance(context, dict):
            return False
        budget = context.get("execution_budget")
        if not isinstance(budget, dict):
            return False
        max_epochs = int(budget.get("max_epochs_per_step") or 1)
        current = int(context.get("execution_epoch") or 1)
        return current < max_epochs

    def _tool_time_s(self) -> Optional[float]:
        """Seconds a tool call may run: the rest of this epoch, plus one epoch's time when the step continues in another.

        An epoch bounds the agent's turns; a read in flight at its end spends no tokens,
        and cutting it would only make the next epoch read the same pages again.
        """
        lease = getattr(getattr(self, "_cognition", None), "lease", None)
        if lease is None:
            return None
        seconds = lease.remaining_wall_clock_ms() / 1000
        state = getattr(self, "_current_state", None)
        if getattr(self, "_current_memory", None) is not None and self._epochs_remain(
            getattr(state, "context", None)
        ):
            seconds += lease.wall_clock_ms / 1000
        return seconds

    async def _landing_turn(
        self,
        state,
        system_prompt: str,
        conversation_history: list,
        model,
        total_tokens: dict,
        total_cost: float,
        exhausted: str,
    ):
        """One tools-disabled synthesis turn after lease expiry (issue #139).

        Gives the agent a chance to land the plane: produce a final answer from
        what it already gathered instead of yielding dead air. Returns an
        AgentOutput on a usable synthesis, None to fall through to the yield.
        """
        if not conversation_history:
            return None  # nothing gathered, nothing to synthesize
        try:
            messages = [{"role": "system", "content": system_prompt}]
            _thread_history(messages, conversation_history)
            kwargs: Dict[str, Any] = {"model": model} if model else {}
            if self._native_protocol:
                instruction = (
                    f"Your execution budget is exhausted ({exhausted}). Only done is "
                    "available now. Call done with your final answer from what you have "
                    "already gathered, and set complete to whether it covers everything "
                    "the task asked for."
                )
                kwargs.update(
                    tools=[self._done_function(state.context, landing=True)],
                    tool_choice="required",
                    parallel_tool_calls=False,
                )
            else:
                instruction = (
                    f"Your execution budget is exhausted ({exhausted}). Tools are no "
                    "longer available. Produce your final answer NOW from what you "
                    "have already gathered. Respond with exactly:\n"
                    "COMPLETE: yes when the answer covers everything the task asked for, "
                    "no when any part was not reached\n"
                    "DONE: <complete human answer; may span lines>\nRESULT: <json result>"
                )
            messages.append({"role": "user", "content": instruction})
            llm_result = await self.llm_client.generate(messages=messages, **kwargs)
            content = llm_result.get("content") or ""
            tokens = llm_result.get("tokens", {})
            total_tokens["input"] += tokens.get("input", 0)
            total_tokens["output"] += tokens.get("output", 0)
            total_tokens["total"] += tokens.get("total", 0)
            if self._native_protocol:
                parsed = self._parse_native_turn(llm_result, {})
            else:
                parsed = self._parse_response_for_contract(content, state.context)
                declared = _COMPLETE_PATTERN.search(content)
                parsed["complete"] = (
                    declared.group(1).lower() == "yes" if declared else None
                )
            if parsed.get("type") != "done":
                return None
            can_exit, reject_reason = self._ground_completion(state, parsed)
            if can_exit and parsed.get("complete") is False and not self._epochs_remain(state.context):
                # No later epoch will pick this up: what the agent says it could
                # not finish is the result, not a checkpoint nobody resumes.
                return await self._finish_incomplete(
                    state, parsed, state.turn, [], getattr(self, "_current_memory", None),
                    None, total_tokens, total_cost, tokens.get("total", 0),
                )
            if can_exit:
                can_exit, reject_reason = self._can_complete(state, parsed)
            if can_exit:
                can_exit, reject_reason = self._records_support_completion(state, parsed)
            if not can_exit:
                evidence = as_evidence(reject_reason)
                state.add_thought(f"[LANDING_DONE_GATE] {evidence.render()}")
                state.last_error = evidence.render()
                state.refuse_answer(parsed, evidence.render())
                await self._persist_memory(state)
                self._log.info(
                    "Landing completion rejected: check=%s",
                    evidence.check,
                )
                return None
            state.status = "completed"
            state.output = parsed.get("result")
            await self._persist_memory(state)
            self._log.info("Landing turn produced a final result after lease expiry")
            return AgentOutput(
                status="success",
                summary=f"Completed on landing turn after budget exhaustion ({exhausted}): {parsed['summary']}",
                payload=state.get_final_output(),
                trajectory=[{"turn": state.turn, "type": "landing", "summary": parsed["summary"]}],
                metadata={"tokens": total_tokens, "cost_usd": total_cost,
                          "lease_exhausted": exhausted, "landing_turn": True,
                          "typed_outcome": "SUCCESS_ON_LANDING",
                          "tool_receipts": state.receipt_evidence(state.output),
                          "work_record": self._work_record(state),
                          "answer": parsed.get("answer"),
                          "kept_memories": list(getattr(self, "_kept_memories", []))},
            )
        except Exception as exc:
            self._log.warning("Landing turn failed: %s", exc)
            return None

    def _build_user_prompt(self, state: KernelState, context_block: str) -> str:
        """Build the user prompt for a single OODA turn.

        Combines the context block (from ContextManager) with the
        Epistemic Decision Contract — a structured self-assessment
        that forces the LLM to reason about gaps before acting.
        """
        parts = [context_block, "\n---"]
        if self._native_protocol:
            # The model reasons internally; asking it to also write its reasoning
            # out every turn was paid for as output on every call.
            parts.append(f"**ROLE: {self.role.upper()} AGENT**")
            parts.append("Call the functions for your next step, or done.")
        else:
            parts.append(f"**ROLE: {self.role.upper()} AGENT** | Turn {state.turn}")
            # Epistemic Decision Contract — forces self-assessment
            parts.append(
                "**DECISION CONTRACT (follow this structure in your THOUGHT):**\n"
                "1. **KNOWN:** What have I established so far? (my working notes and findings above, and this turn's result)\n"
                "2. **GAP:** What specific information am I still missing?\n"
                "3. **STRATEGY:** What is the most efficient next step to close the gap?\n\n"
                "Write anything newly established on NOTE: lines; your THOUGHT is gone "
                "from view after a few turns, your notes are not. "
                "Then emit your TOOL/PARAMS or DONE/RESULT."
            )
        if "ask_peer" in self._tools and self._offers_tool("ask_peer", state.context):
            parts.append(
                "**PEER RESOLUTION:** Before concluding blocked, incomplete, or DONE "
                "with a material gap, ask whether an available peer can resolve it. "
                "Use `ask_capability` for the exact missing fact when you know the "
                "needed capability, or `ask_peer` when a specific role is already clear. "
                "Include known identifiers, then treat the response as new context and "
                "re-evaluate. Do not delegate work you can complete with your own tools."
            )
        return "\n\n".join(parts)

    # ──────────────────────────────────────────────────────────────────────
    # OODA Loop
    # ──────────────────────────────────────────────────────────────────────

    async def run(
        self,
        task: str,
        context: Optional[Dict] = None,
        max_turns: int = 15,
        model: Optional[str] = None,
        cognition: Optional[AgentCognitionManager] = None,
        context_manager=None,
        memory=None,
        trace=None,  # Optional[TraceManager] — injected by Kernel
    ) -> AgentOutput:
        """Execute the subagent's task via the OODA loop.

        A run that ends without an accepted answer carries what it established in
        ``metadata["progress"]``, whichever way it stopped.
        """
        self._current_state = None
        output = await self._run_turns(
            task, context, max_turns, model, cognition, context_manager, memory, trace,
        )
        state = self._current_state
        if output.status != "success" and state is not None:
            progress = state.progress()
            if progress is not None:
                output.metadata = {**(output.metadata or {}), "progress": progress}
        return output

    async def _run_turns(
        self,
        task: str,
        context: Optional[Dict] = None,
        max_turns: int = 15,
        model: Optional[str] = None,
        cognition: Optional[AgentCognitionManager] = None,
        context_manager=None,
        memory=None,
        trace=None,  # Optional[TraceManager] — injected by Kernel
    ) -> AgentOutput:
        """
        Execute the subagent's task via the OODA loop.

        Args:
            task: Natural language task description
            context: Optional context from kernel (prior steps, auth, etc.)
            max_turns: Emergency turn fuse (not the primary governor)
            model: Optional model override
            cognition: Optional pre-built AgentCognitionManager from the Kernel.
                If not provided a minimal one is created.
            context_manager: Optional ContextManager for priority-stack prompts.
                If not provided, falls back to simple prompt building.
            memory: Optional UnifiedMemory for turn logging and checkpoints.

        Returns:
            AgentOutput with status, payload, summary, trajectory
        """
        trajectory: List[Dict[str, Any]] = []

        # ── Initialize cognition (budget governance) ──
        if cognition is not None:
            self._cognition = cognition
        else:
            from jarviscore.kernel.lease import ExecutionLease
            self._cognition = AgentCognitionManager(
                lease=ExecutionLease(),
                agent_id=self.agent_id,
                workflow_id=context.get("workflow_id", "unknown") if context else "unknown",
                redis_store=self.redis_store,
            )

        # ── Initialize context manager ──
        if context_manager is None:
            from jarviscore.context.context_manager import ContextManager
            context_manager = ContextManager()
        context_manager.perception_tools = self.perception_tools

        # ── Initialize or resume state ──
        state = KernelState(
            workflow_id=context.get("workflow_id", "unknown") if context else "unknown",
            step_id=context.get("step_id", "unknown") if context else "unknown",
            agent_id=self.agent_id,
            task=task,
            context=context or {},
            tokens_budget=self._cognition.lease.max_total_tokens,
        )

        if context and context.get("_resume") and memory is not None:
            raw_checkpoint = await memory.load_checkpoint()
            if raw_checkpoint:
                restored = KernelState.model_validate_json(raw_checkpoint)
                if restored.agent_id == self.agent_id and restored.task == task:
                    state = restored
                    state.status = "active"
                    state.context.update(context)
                    self._cognition.lease.thinking_used = state.thinking_tokens_used
                    self._cognition.lease.action_used = state.action_tokens_used
                    self._cognition.lease.turns_used = state.turn
                    self._restore_subagent_state(state)
                    if context.get("_new_execution_epoch"):
                        state.turn = 0
                        state.retry_count = 0
                        if not state.internal_variables.get("done_gate_attempts"):
                            state.last_error = None
                        state.thinking_tokens_used = 0
                        state.action_tokens_used = 0
                        state.tokens_used = 0
                        state.total_cost_usd = 0.0
                        self._cognition.lease.thinking_used = 0
                        self._cognition.lease.action_used = 0
                        self._cognition.lease.turns_used = 0

        # Restore cross-task memory (no-op unless memory_enabled=True)
        await self._restore_memory(state)

        # Expose state to built-in tools (read_turn_result) for this dispatch.
        self._current_state = state
        # And the memory handle, so remember/recall reach the same tiers.
        self._current_memory = memory
        self._kept_memories = []

        # Pre-run hook — subclasses can do deterministic pre-flight work
        await self._pre_run_hook(state)

        # ── TraceManager: use injected trace or no-op ──
        from jarviscore.kernel.tracing import create_noop_trace
        _trace = trace if trace is not None else create_noop_trace()
        self._run_trace = _trace
        await self._carry_out_decided_actions(state, _trace)
        total_tokens = {"input": 0, "output": 0, "total": state.tokens_used}
        total_cost = state.total_cost_usd
        carries_native = getattr(self.llm_client, "carries_native_tools", None)
        self._native_protocol = callable(carries_native) and carries_native(model) is True
        system_prompt = self._build_system_prompt()

        # Rolling conversation history for multi-turn LLM continuity
        # (prevents amnesia — the LLM sees its own prior reasoning); a
        # continued step picks up the exchanges its last epoch checkpointed.
        conversation_history: List[Dict[str, Any]] = list(state.conversation)

        # Per-dispatch metadata channel (issue #88): tools stamp identity
        # facts here (e.g. the coder's registry function_id) and the success
        # envelope carries them out. Reset every run so nothing leaks across
        # dispatches.
        self._dispatch_metadata: Dict[str, Any] = {}
        self._pending_lead = None
        opening_turn = state.turn

        for turn in range(state.turn, max_turns):
            state.turn = turn
            self._log.set_turn(turn)
            self._attach_turn_lead(conversation_history)

            # ── Emergency guards ──
            if self._cognition.lease.is_expired():
                exhausted = ", ".join(self._cognition.lease.expired_dimensions()) or "unknown"
                self._log.warning(f"Lease expired: {exhausted}")
                # Landing turn (issue #139): one tools-disabled synthesis attempt
                # so exhaustion yields a partial result instead of dead air. It is
                # the last resort: while the workflow still grants this step
                # another execution epoch, unfinished work continues there.
                landing = None
                if memory is None or not self._epochs_remain(state.context):
                    landing = await self._landing_turn(
                        state, system_prompt, conversation_history, model,
                        total_tokens, total_cost, exhausted,
                    )
                if landing is not None:
                    return landing
                if memory is not None:
                    return await self._continue_in_new_epoch(
                        state, conversation_history, memory, turn, total_tokens,
                        total_cost, trajectory, exhausted,
                    )
                return AgentOutput(
                    status="yield",
                    summary=f"Lease budget exhausted after {turn} turns: {exhausted}",
                    payload=state.get_final_output(),
                    trajectory=trajectory,
                    metadata={"tokens": total_tokens, "cost_usd": total_cost,
                              "lease_exhausted": exhausted,
                              "typed_outcome": "YIELD_LEASE_EXHAUSTED"},
                )

            if not self._cognition.should_continue():
                reason = (
                    ", ".join(self._cognition.lease.expired_dimensions())
                    or ("completion already signalled" if self._cognition.done_called else "unknown")
                )
                return AgentOutput(
                    status="yield",
                    summary=f"Cognitive budget exhausted: {reason}",
                    payload=state.get_final_output(),
                    trajectory=trajectory,
                    metadata={"tokens": total_tokens, "cost_usd": total_cost,
                              "exhausted": reason,
                              "typed_outcome": "YIELD_BUDGET_EXHAUSTED"},
                )

            self._cognition.lease.consume_turn()

            # ═══ 1. OBSERVE — Build context from state ═══
            # Results in the conversation are shown there whole; the action list points to them.
            visible = _in_view(conversation_history)
            in_conversation = frozenset(
                entry["receipt_id"] for entry in visible if entry.get("receipt_id")
            )
            build_parts = getattr(context_manager, "build_context_parts", None)
            split = self._native_protocol and callable(build_parts)
            if split:
                constant_block, context_block = build_parts(
                    state, in_conversation=in_conversation, notes_in_view=_notes_in_view(visible),
                )
            else:
                context_block = context_manager.build_context(state, in_conversation=in_conversation)

            # ═══ 2. ORIENT — the budget that remains, as a fact for this turn ═══
            # A notice about this run's budget belongs to this turn; kept as a
            # thought it would outlive the run it describes.
            learned = ""
            if self._native_protocol:
                learned = self._shapes_learned_this_run(frozenset(
                    turn.tool_name for turn in state.tool_history
                    if turn.receipt_id in in_conversation
                ))
            if learned:
                context_block += f"\n\n{learned}"
            if not split:
                context_block += (
                    f"\n\n## RUNTIME NOTICE (this turn)\n{_now_fact()}\n{self._cognition.budget_facts()}"
                )
            state.failure_ledger = self._cognition.failures.recent_failures

            # ═══ 3. DECIDE — LLM call ═══
            messages = [{"role": "system", "content": system_prompt}]
            if split:
                # Every prompt extends the one before: the task leads, each turn's
                # news stays where it was said, and only the state that changed
                # since the last turn follows the conversation.
                user_prompt = self._build_user_prompt(state, constant_block)
                messages.append({"role": "user", "content": user_prompt})
                _thread_history(messages, conversation_history)
                news = self._turn_news(conversation_history, visible, first=turn == opening_turn)
                if news:
                    messages.append({"role": "user", "content": news})
                    self._pending_lead = (len(conversation_history), news)
                if context_block.strip():
                    messages.append({"role": "user", "content": context_block.strip()})
                user_prompt = "\n\n".join(
                    part for part in (user_prompt, news, context_block.strip()) if part
                )
            else:
                user_prompt = self._build_user_prompt(state, context_block)
                _thread_history(messages, conversation_history)
                messages.append({"role": "user", "content": user_prompt})

            _trace.log_llm_request(system_prompt[:300], user_prompt[:500], model=model)

            kwargs = {}
            if model:
                kwargs["model"] = model
            tools_by_function: Dict[str, str] = {}
            if self._native_protocol:
                tool_specs, tools_by_function = self._native_tool_specs(state.context)
                kwargs.update(
                    tools=tool_specs, tool_choice="required", parallel_tool_calls=True,
                )

            _llm_t0 = __import__('time').monotonic()
            try:
                llm_result = await self.llm_client.generate(
                    messages=messages, **kwargs
                )
            except Exception as e:
                if isinstance(e, WorkflowBudgetExceeded):
                    state.status = "active"
                    state.last_error = str(e)
                    state.thinking_tokens_used = self._cognition.lease.thinking_used
                    state.action_tokens_used = self._cognition.lease.action_used
                    state.tokens_used = total_tokens["total"]
                    state.total_cost_usd = total_cost
                    if memory is not None:
                        await memory.save_checkpoint(self._checkpoint_json(state, conversation_history))
                    if isinstance(e, SpendCapReached):
                        _trace.log_step_complete(False, str(e))
                        return AgentOutput(
                            status="failure", payload=state.output, summary=str(e),
                            trajectory=trajectory,
                            metadata={"error": str(e), "tokens": total_tokens, "cost_usd": total_cost,
                                      "typed_outcome": "SPEND_CAP_REACHED",
                                      "checkpointed": memory is not None},
                        )
                    if not e.recoverable:
                        _trace.log_step_complete(
                            False,
                            "LLM request exceeds the execution epoch capacity.",
                        )
                        return AgentOutput(
                            status="failure",
                            payload=state.output,
                            summary=(
                                "The current request cannot fit in any execution epoch; "
                                "its context must be reduced before retrying."
                            ),
                            trajectory=trajectory,
                            metadata={
                                "error": str(e),
                                "tokens": total_tokens,
                                "cost_usd": total_cost,
                                "typed_outcome": "CONTEXT_EXCEEDS_EPOCH_CAPACITY",
                                "checkpointed": memory is not None,
                            },
                        )
                    _trace.log_step_complete(
                        False,
                        "Active execution epoch exhausted; checkpointed for continuation.",
                    )
                    return AgentOutput(
                        status="epoch_exhausted",
                        payload=state.output,
                        summary=(
                            "Active execution epoch exhausted; durable state was "
                            "checkpointed for continuation."
                        ),
                        trajectory=trajectory,
                        metadata={
                            "tokens": total_tokens,
                            "cost_usd": total_cost,
                            "typed_outcome": "CONTINUE_NEW_EXECUTION_EPOCH",
                            "checkpointed": memory is not None,
                        },
                    )
                self._log.error("LLM call failed: %s", e)
                state.retry_count += 1
                if state.retry_count > state.max_retries:
                    _trace.log_step_complete(False, f"LLM call failed: {e}")
                    return AgentOutput(
                        status="failure",
                        summary=f"LLM call failed: {e}",
                        trajectory=trajectory,
                        metadata={"error": str(e), "tokens": total_tokens,
                                  "cost_usd": total_cost},
                    )
                continue

            content = llm_result.get("content") or ""
            tokens = llm_result.get("tokens", {})
            total_tokens["input"] += tokens.get("input", 0)
            total_tokens["output"] += tokens.get("output", 0)
            total_tokens["total"] += tokens.get("total", 0)
            total_cost += llm_result.get("cost_usd", 0.0)
            if self._native_protocol:
                parsed = self._parse_native_turn(llm_result, tools_by_function)
            else:
                parsed = self._parse_response_for_contract(content, context)
                if parsed.get("type") == "done":
                    declared = _COMPLETE_PATTERN.search(content)
                    parsed["complete"] = (
                        declared.group(1).lower() == "yes" if declared else None
                    )
            native_call = parsed.get("native_call")
            reply = content
            if native_call:
                reply = f"{content}\n{native_call['name']}({native_call['arguments']})".strip()
            _trace.log_llm_response(
                reply[:500],
                round((__import__('time').monotonic() - _llm_t0) * 1000, 1),
                tokens=tokens.get("total", 0),
                model=llm_result.get("model") or model,
            )
            llm_tokens_this_turn = tokens.get("total", 0)
            state.tokens_used = total_tokens["total"]

            # Parse response
            await self._keep_notes(state, parsed.get("notes"))
            if parsed["type"] != "raw":
                # Repairs bound a run of malformed replies, not a session's lifetime.
                state.internal_variables["_protocol_violation_count"] = 0

            # ── Auto-summarize if context is getting large ──
            try:
                await context_manager.auto_summarize_if_needed(
                    state, self.llm_client, memory
                )
            except Exception as e:
                self._log.warning("Auto-summarization failed: %s", e)

            # ═══ Handle DONE ═══
            if parsed["type"] == "done":
                # ── Done-gate: subclasses can reject premature completion ──
                can_exit, reject_reason = self._ground_completion(state, parsed)
                if can_exit and parsed.get("complete") is False:
                    return await self._finish_incomplete(
                        state, parsed, turn, trajectory, memory, _trace,
                        total_tokens, total_cost, llm_tokens_this_turn,
                    )
                if can_exit:
                    can_exit, reject_reason = self._can_complete(state, parsed)
                if not can_exit:
                    evidence = as_evidence(reject_reason)
                    state.refuse_answer(parsed, evidence.render())
                    attempts = state.internal_variables.setdefault("done_gate_attempts", [])
                    _, streak, previous = record_attempt(
                        attempts,
                        turn=turn,
                        evidence=evidence,
                        payload=parsed.get("result"),
                        tool_calls=len(state.tool_history),
                    )
                    self._log.info(
                        "Done rejected: check=%s attempt=%d", evidence.check, streak,
                    )
                    report = evidence.render()
                    if previous is not None and streak > 1:
                        report += (
                            f"\n  unchanged  since turn {previous.turn}: same check, same values, "
                            f"same result submitted, no tool call in between"
                        )

                    if streak >= self.max_identical_done_attempts:
                        summary = (
                            f"Completion gate '{evidence.check}' unsatisfied after "
                            f"{streak} identical attempts"
                        )
                        state.status = "active" if memory is not None else "failed"
                        state.last_error = report
                        state.add_thought(f"[DONE_GATE] {report}")
                        trajectory.append({
                            "turn": turn,
                            "type": "done_gate_unsatisfied",
                            "check": evidence.check,
                            "attempts": streak,
                        })
                        _trace.log_step_complete(False, summary)
                        if memory is not None:
                            state.thinking_tokens_used = self._cognition.lease.thinking_used
                            state.action_tokens_used = self._cognition.lease.action_used
                            state.tokens_used = total_tokens["total"]
                            state.total_cost_usd = total_cost
                            await memory.save_checkpoint(self._checkpoint_json(state, conversation_history))
                            return AgentOutput(
                                status="epoch_exhausted",
                                summary=f"{summary}; durable state was checkpointed",
                                payload=state.get_final_output(),
                                trajectory=trajectory,
                                metadata={
                                    "tokens": total_tokens,
                                    "cost_usd": total_cost,
                                    "typed_outcome": "CONTINUE_NEW_EXECUTION_EPOCH",
                                    "checkpointed": True,
                                    "gate_evidence": evidence.as_dict(),
                                    "gate_attempts": streak,
                                    "cognition": self._cognition.get_budget_summary(),
                                },
                            )
                        return AgentOutput(
                            status="failure",
                            summary=summary,
                            payload=state.get_final_output(),
                            trajectory=trajectory,
                            metadata={
                                "tokens": total_tokens, "cost_usd": total_cost,
                                "typed_outcome": "FAIL_DONE_GATE_UNSATISFIED",
                                "gate_evidence": evidence.as_dict(),
                                "gate_attempts": streak,
                                "cognition": self._cognition.get_budget_summary(),
                            },
                        )

                    state.add_thought(f"[DONE_GATE] {report}")
                    conversation_history.append({
                        "assistant": content,
                        "observation": (
                            f"[Turn {turn}] {report}\n"
                            f"DONE was not recorded. It may be attempted again."
                        ),
                        "tool_call": native_call,
                    })
                    # Charge tokens WITHOUT the "done" label: track_usage("done")
                    # sets done_called, which made should_continue() kill the agent
                    # next turn for a completion that was just rejected (issue #139).
                    self._cognition.track_usage("continue_after_done_gate", tokens=llm_tokens_this_turn)
                    continue

                state.status = "completed"
                state.output = parsed.get("result")
                thought = parsed.get("thought", "")
                if thought:
                    _trace.log_thinking(thought)
                trajectory.append({
                    "turn": turn,
                    "type": "done",
                    "thought": thought,
                    "summary": parsed["summary"],
                })
                _trace.log_step_complete(True, parsed["summary"])
                self._cognition.track_usage("done", tokens=llm_tokens_this_turn)

                # Log turn to memory
                if memory:
                    try:
                        await memory.log_turn(
                            turn_id=str(turn), thought=parsed.get("thought", ""),
                            action="done", result=parsed["summary"],
                            tokens=llm_tokens_this_turn,
                        )
                    except Exception as exc:
                        self._log.warning(
                            "Memory turn log failed on DONE for %s turn=%s: %s",
                            self.agent_id,
                            turn,
                            exc,
                        )

                await self._persist_memory(state)
                return AgentOutput(
                    status="success",
                    payload=parsed.get("result"),
                    summary=parsed["summary"],
                    trajectory=trajectory,
                    metadata={
                        "tokens": total_tokens,
                        "cost_usd": total_cost,
                        "tool_receipts": state.receipt_evidence(parsed.get("result")),
                        "work_record": self._work_record(state),
                        "answer": parsed.get("answer"),
                        "kept_memories": list(getattr(self, "_kept_memories", [])),
                        **getattr(self, "_dispatch_metadata", {}),
                    },
                )

            # ═══ 4. ACT — Tool execution ═══
            async def _act(parsed, content, native_call, llm_tokens_this_turn):
                """Carry out one tool call of this turn; an AgentOutput ends the run."""
                nonlocal total_cost
                tool_name = parsed["tool"]
                tool_params = parsed.get("params", {})

                # ── Pre-execute hook: subclass-level gating ──
                # Subclasses override _pre_execute_hook to enforce boundaries
                # (e.g. approval of a consequential action). If it returns a dict,
                # that dict is used as the tool result and execution is skipped.
                hook_result = await self._pre_execute_hook(
                    tool_name, tool_params, state
                )
                if hook_result is not None:
                    hook_succeeded = (
                        isinstance(hook_result, dict)
                        and hook_result.get("status") == "success"
                    )
                    hook_event = (
                        "pre_execute_resolution" if hook_succeeded
                        else "pre_execute_block"
                    )
                    self._record_pre_execute_result(
                        state, trajectory, conversation_history, content,
                        turn, tool_name, tool_params, hook_result, hook_event,
                        tool_call=native_call,
                    )
                    return None

                # Execute tool
                turn_log: Dict[str, Any] = {
                    "turn": turn,
                    "type": "tool_call",
                    "thought": parsed.get("thought", ""),
                    "tool": tool_name,
                    "params": tool_params,
                    "status": "pending",
                }

                # Emit thinking + tool_start trace events
                thought = parsed.get("thought", "") or "\n".join(parsed.get("notes") or [])
                if thought:
                    _trace.log_thinking(thought)
                _trace.log_tool_start(tool_name, tool_params)

                tool_started_at = time.time()
                tool_started = time.monotonic()
                try:
                    tool_result = await self._execute_tool(tool_name, tool_params)
                except WorkflowBudgetExceeded as exc:
                    state.status = "active"
                    state.last_error = str(exc)
                    state.thinking_tokens_used = self._cognition.lease.thinking_used
                    state.action_tokens_used = self._cognition.lease.action_used
                    state.tokens_used = total_tokens["total"]
                    state.total_cost_usd = total_cost
                    if isinstance(exc, SpendCapReached):
                        return AgentOutput(
                            status="failure", payload=state.output, summary=str(exc),
                            trajectory=trajectory,
                            metadata={"error": str(exc), "tokens": total_tokens, "cost_usd": total_cost,
                                      "typed_outcome": "SPEND_CAP_REACHED"},
                        )
                    turn_log["status"] = "epoch_exhausted"
                    turn_log["error"] = str(exc)
                    trajectory.append(turn_log)
                    if memory is not None:
                        await memory.save_checkpoint(self._checkpoint_json(state, conversation_history))
                    _trace.log_step_complete(
                        False,
                        "Active execution epoch exhausted; checkpointed for continuation.",
                    )
                    return AgentOutput(
                        status="epoch_exhausted",
                        payload=state.output,
                        summary=(
                            "Active execution epoch exhausted; durable state was "
                            "checkpointed for continuation."
                        ),
                        trajectory=trajectory,
                        metadata={
                            "tokens": total_tokens,
                            "cost_usd": total_cost,
                            "typed_outcome": "CONTINUE_NEW_EXECUTION_EPOCH",
                            "checkpointed": memory is not None,
                        },
                    )
                tool_duration_ms = round((time.monotonic() - tool_started) * 1000)
                tool_result, observed_images = multimodal.split_images(tool_result)
                decision = tool_result.get("decision") if isinstance(tool_result, dict) else None
                decision_usage = (
                    tool_result.get("decision_usage")
                    if isinstance(tool_result, dict)
                    else None
                )
                if not isinstance(decision_usage, dict) and isinstance(decision, dict):
                    decision_usage = decision.get("usage")
                if isinstance(decision_usage, dict):
                    decision_input = int(decision_usage.get("input_tokens") or 0)
                    decision_output = int(decision_usage.get("output_tokens") or 0)
                    total_tokens["input"] += decision_input
                    total_tokens["output"] += decision_output
                    total_tokens["total"] += decision_input + decision_output
                    decision_cost = (
                        tool_result.get("decision_cost_usd")
                        if isinstance(tool_result, dict)
                        else None
                    )
                    if decision_cost is None and isinstance(decision, dict):
                        decision_cost = decision.get("cost_usd")
                    total_cost += float(decision_cost or 0.0)
                    state.tokens_used = total_tokens["total"]
                    state.total_cost_usd = total_cost
                turn_log["result"] = str(tool_result)[:500]

                # Record in state
                error_str = tool_result.get("error") if isinstance(tool_result, dict) else None
                repeat_note = _identical_call_record(
                    state.tool_history, tool_name, tool_params, tool_result
                )
                tool_receipt = state.add_tool_result(
                    tool_name,
                    tool_params,
                    tool_result,
                    error=error_str,
                    timestamp=tool_started_at,
                    duration_ms=tool_duration_ms,
                )
                turn_log["tool_receipt_id"] = tool_receipt.receipt_id
                # The receipt's number names this result across the step's epochs; the loop's turn restarts in each.
                call = state.tool_results_recorded

                # ── Retain the full result for honest retrieval (issue #57) ──
                if tool_name != "read_turn_result":
                    _retain_turn_result(state.internal_variables, call, str(tool_result))
                if tool_name not in _UNBRIDGED_TOOLS:
                    self._note_result_shape(tool_name, tool_result)

                # ── Track usage ──
                registered = self._tools.get(tool_name)
                self._cognition.track_usage(
                    tool_name, tokens=llm_tokens_this_turn, tool_output=tool_result,
                    params=tool_params,
                    declared_phase=getattr(registered, "declared_phase", None),
                )

                # ── Record failure if tool errored ──
                if tool_result.get("status") == "error":
                    turn_log["status"] = "error"
                    turn_log["error"] = tool_result.get("error", "")
                    _trace.log_tool_result(tool_name, tool_result, error=tool_result.get("error"))
                    self._cognition.record_failure(
                        tool_name, tool_params, error=tool_result.get("error"),
                    )
                else:
                    turn_log["status"] = "success"
                    _trace.log_tool_result(tool_name, tool_result)

                if isinstance(tool_result, dict) and tool_result.get("status") == "waiting":
                    state.status = "waiting"
                    state.turn = turn + 1
                    state.thinking_tokens_used = self._cognition.lease.thinking_used
                    state.action_tokens_used = self._cognition.lease.action_used
                    state.total_cost_usd = total_cost
                    trajectory.append(turn_log)
                    conversation_history.append({
                        "assistant": content,
                        "observation": (
                            f"[Turn {call}] waiting:\n"
                            f"{_observe(tool_name, tool_result, call)}"
                        ),
                    })
                    if memory is not None:
                        await memory.save_checkpoint(self._checkpoint_json(state, conversation_history))
                    return AgentOutput(
                        status="yield",
                        payload=tool_result,
                        summary=tool_result.get("detail", "Waiting for user action."),
                        trajectory=trajectory,
                        metadata={
                            "tokens": total_tokens,
                            "cost_usd": total_cost,
                            "yield_pending": True,
                            "typed_outcome": tool_result.get("typed_outcome"),
                            "hitl_type": tool_result.get("hitl_type"),
                            "system": tool_result.get("system"),
                            "connection_id": tool_result.get("connection_id"),
                            "workflow_id": state.workflow_id,
                            "step_id": state.step_id,
                            "action_id": tool_result.get("action_id"),
                            "action": tool_result.get("action"),
                            "consequence": tool_result.get("consequence"),
                        },
                    )

                trajectory.append(turn_log)

                # Record conversation history for multi-turn LLM continuity
                # Structured turn digest instead of raw output — helps the LLM
                # retain what was learned and reason about strategy changes.
                result_str = _observe(
                    tool_name, tool_result, call, tool_name in self.whole_observation_tools
                )
                # Repeated in history on every later turn, so it carries only what the
                # agent uses: which call, its receipt, and the result. The call it
                # answers, tool name and arguments, sits right before it.
                observation = (
                    f"[Turn {call}] {turn_log['status']}, "
                    f"receipt {tool_receipt.receipt_id}:\n{result_str}"
                    + (f"\n\n{repeat_note}" if repeat_note else "")
                )
                conversation_history.append({
                    "assistant": content,
                    "observation": observation,
                    "images": observed_images,
                    "tool_call": native_call,
                    "receipt_id": tool_receipt.receipt_id,
                    "perception": tool_name in self.perception_tools,
                    "superseded": (
                        f"[Turn {call}] {turn_log['status']}; "
                        "a later perception replaced this view. Full result: call "
                        f'read_turn_result with {{"turn": {call}}}'
                    ),
                    "reference": (
                        f"[Turn {call}] {turn_log['status']}, "
                        f"receipt {tool_receipt.receipt_id}, {len(result_str)} characters, "
                        "shown whole when it arrived. Read it whole again: call "
                        f'read_turn_result with {{"turn": {call}}}'
                    ),
                })

                # Log turn to memory
                if memory:
                    try:
                        await memory.log_turn(
                            turn_id=str(turn), thought=parsed.get("thought", ""),
                            action=tool_name,
                            result=str(tool_result),
                            tokens=llm_tokens_this_turn,
                        )
                    except Exception as exc:
                        self._log.warning(
                            "Memory turn log failed for %s turn=%s tool=%s: %s",
                            self.agent_id,
                            turn,
                            tool_name,
                            exc,
                        )

                # Save checkpoint
                if memory:
                    try:
                        await memory.save_checkpoint(self._checkpoint_json(state, conversation_history))
                    except Exception as e:
                        self._log.warning("Checkpoint save failed for %s turn=%s: %s", self.agent_id, turn, e)

                # ── State-driven exit ──
                # Tools like publish_research_findings set state.status = "completed"
                # to signal they've produced a final result. This check makes that
                # a first-class exit path — no separate DONE emission needed.
                if getattr(state, "status", None) == "completed":
                    stated = tool_result.get("summary") if isinstance(tool_result, dict) else None
                    # The tool's own account of what it delivered is the answer.
                    answer = stated.strip() if isinstance(stated, str) and stated.strip() else None
                    summary = answer or (
                        f"Completed via tool '{tool_name}' "
                        f"(state-driven exit on turn {turn})"
                    )
                    _trace.log_step_complete(True, summary)
                    await self._persist_memory(state)
                    return AgentOutput(
                        status="success",
                        payload=tool_result,
                        summary=summary,
                        trajectory=trajectory,
                        metadata={
                            "tokens": total_tokens, "cost_usd": total_cost,
                            "exit_type": "state_driven",
                            "answer": answer,
                            "tool_receipts": state.receipt_evidence(state.output),
                        },
                    )

                return None

            if parsed["type"] == "tool":
                batch = [parsed, *parsed.get("more_calls", ())]
                for index, action in enumerate(batch):
                    if index:
                        await self._keep_notes(state, action.get("notes"))
                    # The turn's tokens and its text belong to its first call only.
                    ended = await _act(
                        action,
                        content if index == 0 else "",
                        action.get("native_call"),
                        llm_tokens_this_turn if index == 0 else 0,
                    )
                    if ended is not None:
                        return ended
                continue

            # ── Unparseable response — protocol failure, not completion ──
            # Keep this inside the OODA loop so the agent sees the failure and
            # can repair its protocol on the next turn. If it cannot repair
            # before the turn fuse, return an explicit failure.
            raw_turn = {
                "turn": turn,
                "type": "raw",
                "content": content[:500],
                "status": "protocol_violation",
            }
            trajectory.append(raw_turn)
            protocol_violations = int(
                state.internal_variables.get("_protocol_violation_count", 0)
            ) + 1
            state.internal_variables["_protocol_violation_count"] = protocol_violations
            max_protocol_repairs = int(os.getenv("SUBAGENT_MAX_PROTOCOL_REPAIRS", "1"))
            self._cognition.track_usage(
                "protocol_violation",
                tokens=llm_tokens_this_turn,
                tool_output={"status": "error", "error": "Protocol violation"},
            )
            self._cognition.record_failure(
                "protocol_violation",
                {"raw": content[:500]},
                error="Subagent response did not match TOOL or DONE protocol.",
            )
            if protocol_violations <= max_protocol_repairs and turn < max_turns - 1:
                if native_call:
                    repair = (
                        f"[Turn {turn}] PROTOCOL VIOLATION: the arguments of "
                        f"{native_call['name']} were not a JSON object. Call it again "
                        "with a valid JSON object."
                    )
                elif self._native_protocol:
                    repair = (
                        f"[Turn {turn}] PROTOCOL VIOLATION: your reply called no function. "
                        "Act by calling exactly one of the offered functions; call done "
                        "to finish."
                    )
                else:
                    repair = (
                        f"[Turn {turn}] PROTOCOL VIOLATION: Your response did not match "
                        "the required TOOL/PARAMS or DONE/RESULT protocol.\n"
                        "Repair on the next turn. Emit exactly one of:\n"
                        "THOUGHT: <reasoning>\\nTOOL: <tool_name>\\nPARAMS: <json>\n"
                        "or\n"
                        "THOUGHT: <reasoning>\\nDONE: <summary>\\nRESULT: <json>."
                    )
                conversation_history.append({
                    "assistant": content,
                    "observation": repair,
                    "tool_call": native_call,
                })
                state.add_thought(
                    "[PROTOCOL_VIOLATION] The previous reply took no valid action. "
                    "Repair on the next turn."
                )
                continue
            return AgentOutput(
                status="failure",
                payload={
                    "error": (
                        "Subagent response did not match TOOL or DONE protocol "
                        f"after {protocol_violations} violation(s)."
                    ),
                    "raw": content[:1000],
                },
                summary=(
                    "Subagent response repeatedly violated the required TOOL/DONE protocol."
                    if protocol_violations > 1
                    else "Subagent response violated the required TOOL/DONE protocol."
                ),
                trajectory=trajectory,
                metadata={
                    "tokens": total_tokens,
                    "cost_usd": total_cost,
                    "typed_outcome": "PROTOCOL_VIOLATION",
                    "protocol_violations": protocol_violations,
                },
            )

        # Max turns reached (emergency fuse). A step still making progress with
        # durable state continues in its next epoch, as for any exhausted budget;
        # the workflow's epoch limit bounds it.
        if memory is not None and self._epochs_remain(state.context):
            return await self._continue_in_new_epoch(
                state, conversation_history, memory, state.turn + 1, total_tokens,
                total_cost, trajectory, f"turn_cap({max_turns})",
            )
        _trace.log_step_complete(False, f"Emergency turn fuse reached ({max_turns} turns)")
        return AgentOutput(
            status="yield",
            summary=f"Emergency turn fuse reached ({max_turns} turns)",
            payload=state.get_final_output(),
            trajectory=trajectory,
            metadata={
                "tokens": total_tokens, "cost_usd": total_cost,
                "typed_outcome": "YIELD_EMERGENCY_TURN_FUSE",
            },
        )

    # ──────────────────────────────────────────────────────────────────────
    # Subclass Hooks (overridable)
    # ──────────────────────────────────────────────────────────────────────

    async def _continue_in_new_epoch(
        self, state, conversation_history, memory, turn, total_tokens, total_cost, trajectory, exhausted,
    ) -> AgentOutput:
        """Checkpoint the step so its next execution epoch carries on where this one stopped."""
        state.status = "active"
        state.thinking_tokens_used = self._cognition.lease.thinking_used
        state.action_tokens_used = self._cognition.lease.action_used
        state.tokens_used = total_tokens["total"]
        state.total_cost_usd = total_cost
        await memory.save_checkpoint(self._checkpoint_json(state, conversation_history))
        return AgentOutput(
            status="epoch_exhausted",
            summary=(
                f"Execution lease exhausted after {turn} turns; durable "
                "state was checkpointed for continued agent work."
            ),
            payload=state.get_final_output(),
            trajectory=trajectory,
            metadata={
                "tokens": total_tokens,
                "cost_usd": total_cost,
                "lease_exhausted": exhausted,
                "typed_outcome": "CONTINUE_NEW_EXECUTION_EPOCH",
                "checkpointed": True,
            },
        )

    async def _pre_run_hook(self, state: KernelState) -> None:
        """Deterministic pre-flight operations before the OODA loop starts.

        Override in subclasses for pre-run setup (e.g. API discovery,
        registry warm-up, context seeding). Default is a no-op.
        """
        pass

    async def _carry_out_decided_actions(self, state: KernelState, trace) -> None:
        """Act on each decision a person made while this step waited, exactly once.

        An approved action runs here, through the normal tool path, so its
        receipt is authoritative; a declined one is reported and never run.
        """
        from jarviscore.kernel import approval

        workflow_id = state.context.get("workflow_id")
        step_id = state.context.get("step_id")
        decisions = approval.decided(self.redis_store, workflow_id, step_id)
        if decisions:
            # Completion pressure from before the pause describes a world the decision changed.
            state.output = None
            state.thoughts = [
                thought for thought in state.thoughts
                if not thought.startswith("[DONE_GATE]")
            ]
        for action, approved in decisions:
            if not approved:
                approval.settle(self.redis_store, workflow_id, step_id, action.action_id, {
                    "status": "declined",
                })
                state.add_thought(
                    f"[HITL DECLINED] The person declined: {action.consequence}. "
                    "It was not performed and must not be attempted. Report that outcome."
                )
                continue
            if not await self._approved_action_applies(action):
                approval.settle(self.redis_store, workflow_id, step_id, action.action_id, {
                    "status": "not_performed",
                    "reason": "the approved target is no longer where it was approved",
                })
                state.add_thought(
                    f"[HITL APPROVED, NOT PERFORMED] The person approved: {action.consequence}. "
                    f"JarvisCore did not perform it because {action.description or action.tool} "
                    "is no longer where it was approved. Inspect current provider state; "
                    "if the action is still needed it must be proposed again for a new decision."
                )
                continue
            params = self._approved_action_params(action)
            trace.log_tool_start(action.tool, params)
            started_at = time.time()
            started = time.monotonic()
            result = await self._execute_tool(action.tool, params)
            error = result.get("error") if isinstance(result, dict) else None
            trace.log_tool_result(action.tool, result, error=error)
            receipt = state.add_tool_result(
                action.tool, params, result, error=error, timestamp=started_at,
                duration_ms=round((time.monotonic() - started) * 1000),
            )
            if isinstance(result, dict) and result.get("performed") is False:
                state.add_thought(
                    f"[HITL APPROVED, NOT YET PERFORMED] The person approved: {action.consequence}. "
                    f"When JarvisCore tried it as this step resumed, nothing happened: {error}. "
                    "The approval stands for this exact action: deal with what blocked it, then "
                    "call the same action again with irreversible and consequence; it runs once."
                )
                continue
            state.add_thought(
                f"[HITL APPROVED, PERFORMED] The person approved: {action.consequence}. "
                f"JarvisCore performed {action.description or action.tool} as this step "
                f"resumed (tool receipt {receipt.receipt_id}): {json.dumps(result, default=str)}. "
                "Observe the provider's outcome before finishing; never repeat this action."
            )

    def _approved_action_params(self, action) -> Dict[str, Any]:
        """Tool parameters that perform an approved action."""
        return dict(action.params)

    async def _approved_action_applies(self, action) -> bool:
        """Whether the approved action still targets what the person approved."""
        return True

    def _checkpoint_json(self, state: KernelState, conversation_history: list) -> str:
        """The checkpoint a resume or the next epoch restores, with this subagent's runtime as it stands."""
        self._attach_turn_lead(conversation_history)
        self._save_subagent_state(state)
        return _checkpoint(state, conversation_history)

    def _attach_turn_lead(self, conversation_history: list) -> None:
        """Keep what the runtime told the agent this turn before the first exchange it led to."""
        pending = getattr(self, "_pending_lead", None)
        if pending is None:
            return
        index, news = pending
        if index < len(conversation_history):
            conversation_history[index].setdefault("lead", news)
            self._pending_lead = None

    def _turn_news(self, conversation_history: list, visible: list, first: bool) -> str:
        """What the runtime tells the agent this turn, said once and kept where it was said.

        The date while no notice in view states it; the budget at the start of a
        run and again once any part of it runs low; and a warning before the
        oldest exchanges leave view, so what they hold can be noted in time.
        """
        lines = []
        today = datetime.now().astimezone().strftime("%A %d %B %Y")
        if not any(today in (entry.get("lead") or "") for entry in visible):
            lines.append(_now_fact())
        running_low = getattr(self._cognition, "budget_running_low", None)
        if first or (callable(running_low) and running_low()):
            lines.append(self._cognition.budget_facts())
        if _leaves_view_soon(conversation_history):
            lines.append(
                "Your oldest exchanges leave your view within a turn or two; keep in "
                "working_notes anything from them you will still need."
            )
        return "## RUNTIME NOTICE\n" + "\n".join(lines) if lines else ""

    def _save_subagent_state(self, state: KernelState) -> None:
        """Place subclass runtime state into the serializable checkpoint."""

    def _restore_subagent_state(self, state: KernelState) -> None:
        """Restore subclass runtime state from a checkpoint."""

    async def teardown(self) -> None:
        """Release resources owned by this subagent instance."""
        pass

    async def _pre_execute_hook(
        self,
        tool_name: str,
        params: Dict[str, Any],
        state: KernelState,
    ) -> Optional[Dict[str, Any]]:
        """Called before tool execution — subclass gate point.

        If this returns a dict, that dict is used as the tool result and
        the actual tool is NOT executed. This enables subclass-specific
        enforcement (e.g. research phase gating, tool allowlists).

        If this returns None, the tool executes normally.

        Default: always allow (returns None).
        """
        return None

    def _can_complete(
        self,
        state: KernelState,
        parsed: Dict[str, Any],
    ) -> tuple:
        """Called before accepting a DONE signal — subclass gate point.

        Returns ``(True, "")`` to allow completion, or ``(False, reason)`` to
        reject it. On rejection the loop continues and the agent sees the reason.

        ``reason`` should be a :class:`~jarviscore.kernel.gate.GateEvidence`:
        the check that did not hold, what it reads, and what was observed in the
        agent's own output. A gate that reports a verdict instead ("evidence is
        required") gives the agent nothing it can act on, so its next attempt is
        a reworded version of the last one — which is how a rejection turns into
        a loop. A bare string is still accepted and carried through unchanged.

        Do not advise here. Naming the missing fact is this method's whole job;
        deciding what to do about it is the agent's.

        Peer tools remain available reasoning actions, not a mandatory route for
        every unresolved result. Product evidence contracts and concrete attempt
        history decide whether completion is supported.

        The base gate checks the result against the step's declared
        ``output_schema``, validators included: a contract the JSON schema
        cannot express ("a reproduction needs a failing run") is still the
        contract, and the agent can only meet it if it is told which rule failed.
        """
        return self._satisfies_output_schema(state, parsed)

    @staticmethod
    def _satisfies_output_schema(state: KernelState, parsed: Dict[str, Any]) -> tuple:
        """Whether ``done``'s result is a valid instance of the declared ``output_schema``."""
        declared = (state.context or {}).get("output_schema")
        if parsed.get("complete") is False or not hasattr(declared, "model_validate"):
            return (True, "")
        try:
            declared.model_validate(parsed.get("result"))
        except Exception as exc:  # pydantic.ValidationError, without importing pydantic here
            errors = getattr(exc, "errors", None)
            problems = [
                f"{'.'.join(str(part) for part in error.get('loc', ())) or 'result'}: {error.get('msg')}"
                for error in (errors() if callable(errors) else [])
            ] or [str(exc)]
            return (False, GateEvidence(
                check="output_schema",
                requirement=f"the result is a valid {declared.__name__}",
                observed={"violations": problems[:10]},
            ))
        return (True, "")

    async def _finish_incomplete(
        self, state, parsed, turn, trajectory, memory, trace,
        total_tokens, total_cost, turn_tokens,
    ) -> AgentOutput:
        """The agent says it could not carry out the task: report that as failure.

        Its explanation and whatever it gathered travel with the result, so the
        caller sees why without opening a trace.
        """
        summary = parsed.get("summary") or "The agent could not carry out the task."
        state.status = "failed"
        state.output = parsed.get("result")
        state.last_error = summary
        trajectory.append({
            "turn": turn, "type": "incomplete", "summary": summary,
            "thought": parsed.get("thought", ""),
        })
        if trace is not None:
            trace.log_step_complete(False, summary)
        if getattr(self, "_cognition", None) is not None:
            self._cognition.track_usage("done", tokens=turn_tokens)
        if memory:
            try:
                await memory.log_turn(
                    turn_id=str(turn), thought=parsed.get("thought", ""),
                    action="done", result=f"[INCOMPLETE] {summary}", tokens=turn_tokens,
                )
            except Exception as exc:
                self._log.warning("Memory turn log failed on incomplete DONE: %s", exc)
        await self._persist_memory(state)
        return AgentOutput(
            status="failure",
            payload=parsed.get("result"),
            summary=summary,
            trajectory=trajectory,
            metadata={
                "tokens": total_tokens,
                "cost_usd": total_cost,
                "typed_outcome": "FAIL_INCOMPLETE",
                "declared_incomplete": True,
                "tool_receipts": state.receipt_evidence(parsed.get("result")),
                "work_record": self._work_record(state),
                "answer": parsed.get("answer"),
                "kept_memories": list(getattr(self, "_kept_memories", [])),
            },
        )

    def _records_support_completion(self, state: KernelState, parsed: Dict[str, Any]) -> tuple:
        """Whether a clock expiry may be reported as completion.

        A landing turn is the runtime forcing done because the lease ended. The
        model's announcement is not the work: only an answer that declares it covers
        everything asked completes; a role with checkable records adds its own check.
        """
        complete = parsed.get("complete")
        if complete is not True:
            return False, GateEvidence(
                check="landing_complete",
                requirement=(
                    "a clock expiry is completion only when the final answer declares "
                    "complete: true"
                ),
                observed={"complete": complete},
            )
        return True, ""

    @staticmethod
    def _work_record(state: KernelState) -> Dict[str, Dict[str, int]]:
        """What this run did, per tool, counted from its tool log.

        Completion is not refused for how the work was done; the record travels with
        the result so the product, a reviewer or a person decides what it supports.
        """
        record: Dict[str, Dict[str, int]] = {}
        for receipt in state.tool_history:
            entry = record.setdefault(receipt.tool_name, {"calls": 0, "succeeded": 0})
            entry["calls"] += 1
            entry["succeeded"] += receipt.status == "success"
        return record

    @staticmethod
    def _ground_completion(
        state: KernelState,
        parsed: Dict[str, Any],
    ) -> tuple:
        """Bind tool evidence before any product-owned completion hook runs."""
        try:
            parsed["result"] = state.hydrate_tool_receipts(
                parsed.get("result"),
                require_command_receipts=True,
            )
        except ToolReceiptError as exc:
            return (
                False,
                GateEvidence(
                    check="tool_receipt_grounding",
                    requirement=(
                        "command and workspace mutation observations must reference "
                        "authoritative tool receipts"
                    ),
                    observed={"error": str(exc)},
                ),
            )
        return (True, "")

    def _tool_is_actionable(self, tool_name: str, state: KernelState) -> bool:
        """Whether a registered tool can execute in the current agent state."""
        return tool_name in getattr(self, "_tools", {}) and self._offers_tool(
            tool_name, getattr(state, "context", None)
        )

    # ──────────────────────────────────────────────────────────────────────
    # Tool Execution
    # ──────────────────────────────────────────────────────────────────────

    def _record_pre_execute_result(
        self,
        state: KernelState,
        trajectory: list,
        conversation_history: list,
        content: str,
        turn: int,
        tool_name: str,
        tool_params: Dict[str, Any],
        hook_result: Dict[str, Any],
        hook_event: str,
        tool_call: Optional[Dict[str, str]] = None,
    ) -> None:
        hook_succeeded = hook_result.get("status") == "success"
        disposition = "resolved" if hook_succeeded else "blocked"
        self._log.info(
            "Pre-execute hook %s '%s': %s",
            disposition,
            tool_name,
            str(hook_result)[:200],
        )
        state.add_tool_result(
            tool_name,
            tool_params,
            hook_result,
            error=hook_result.get("error"),
        )
        trajectory.append({
            "turn": turn,
            "type": hook_event,
            "tool": tool_name,
            "reason": hook_result.get(
                "reason",
                hook_result.get("error", "blocked by pre-execute hook"),
            ),
        })
        conversation_history.append({
            "assistant": content,
            "observation": (
                f"[Turn {turn}] Tool '{tool_name}' {disposition} by "
                f"pre-execute review: {hook_result}"
            ),
            "tool_call": tool_call,
        })

    async def _execute_tool(self, tool_name: str, params: Dict) -> Dict[str, Any]:
        """Execute a registered tool."""
        tool = self._tools.get(tool_name)
        if not tool:
            return {"status": "error", "error": f"Unknown tool: {tool_name}", "available": self.tool_names}

        # Guard: if params are the {"raw": ...} fallback from _parse_response
        # (line 592), don't unpack them as kwargs — the tool won't accept a
        # 'raw' argument and will crash with "unexpected keyword argument".
        if "raw" in params and len(params) == 1:
            try:
                sig = inspect.signature(tool.func)
                expected = [p for p in sig.parameters if p != "self"]
            except (ValueError, TypeError):
                expected = ["(could not inspect)"]
            self._log.warning(
                "Tool '%s' received malformed params (JSON parse failed). Expected: %s",
                tool_name, expected,
            )
            return {
                "status": "error",
                "error": (
                    f"Could not parse your arguments as a JSON object. "
                    f"Tool '{tool_name}' expects these parameters: {expected}. "
                    f"Call it again with a valid JSON object."
                ),
                "semantic_error": "MALFORMED_PARAMS",
                "expected_params": expected,
            }

        try:
            if inspect.iscoroutinefunction(tool.func):
                call = tool.func(**params)
            else:
                call = asyncio.to_thread(tool.func, **params)
            running = asyncio.ensure_future(call)
            tool_time = self._tool_time_s()
            limit = None if tool_time is None else tool_time + self.tool_handback_s
            try:
                done, _ = await asyncio.wait({running}, timeout=limit)
            except asyncio.CancelledError:
                running.cancel()
                await asyncio.gather(running, return_exceptions=True)
                raise
            if not done:
                running.cancel()
                # Cleanup that hangs (a page that no longer answers) must not hold the step past its time.
                await asyncio.wait({running}, timeout=self.tool_handback_s)
                return {
                    "status": "error",
                    "error": f"The step's time ran out while {tool_name} was running; it was stopped.",
                    "error_type": "LeaseExpired",
                }
            result = running.result()
            if inspect.isawaitable(result):
                result = await result
            # Normalize to dict
            if not isinstance(result, dict):
                return {"status": "success", "output": result}
            if result.get("success") is False and not result.get("error"):
                result["error"] = (
                    result.get("stderr") or "Tool reported unsuccessful execution."
                )
            # Ensure status field exists
            if "status" not in result:
                result["status"] = (
                    "error" if result.get("success") is False else "success"
                )
            return result
        except WorkflowBudgetExceeded:
            raise
        except Exception as e:
            self._log.warning("Tool '%s' failed: %s", tool_name, e)
            return {"status": "error", "error": str(e)}

    # ──────────────────────────────────────────────────────────────────────
    # Response Parsing
    # ──────────────────────────────────────────────────────────────────────

    @staticmethod
    def _parse_response(content: str) -> Dict[str, Any]:
        """The reply's directive, plus any notes the agent wrote alongside it."""
        parsed = BaseSubAgent._parse_directive(content)
        notes = [match.group(1).strip() for match in _NOTE_PATTERN.finditer(content)]
        if not notes and not _TOOL_PATTERN.search(content) and not _DONE_PATTERN.search(content):
            # A JSON-protocol reply; a text reply's JSON is its PARAMS, whose fields are the tool's.
            obj = _extract_json_object(content) or {}
            raw = obj.get("notes") if ("tool" in obj or "done" in obj) else None
            notes = [str(note).strip() for note in (raw if isinstance(raw, list) else [raw] if raw else [])]
        notes = [note for note in notes if note]
        if notes:
            parsed["notes"] = notes
        return parsed

    @staticmethod
    def _parse_directive(content: str) -> Dict[str, Any]:
        """
        Parse LLM response for tool calls or completion.

        Supports two protocols:
        1. Text-based (THOUGHT/TOOL/PARAMS or THOUGHT/DONE/RESULT)
        2. JSON fallback ({"thought": ..., "tool": ..., "parameters": ...})

        Returns dict with:
            type: "tool" | "done" | "raw"
            + type-specific fields
        """
        thought_match = _THOUGHT_PATTERN.search(content)
        thought = thought_match.group(1).strip() if thought_match else ""

        combined_match = _COMBINED_DONE_RESULT_PATTERN.search(content)
        done_match = _DONE_PATTERN.search(content)
        result_match = _RESULT_PATTERN.search(content)
        tool_match = _TOOL_PATTERN.search(content)

        if combined_match and not tool_match:
            result = _extract_json_object(combined_match.group(1).strip())
            if result is not None:
                return {
                    "type": "done",
                    "thought": thought,
                    "summary": "Completed via DONE/RESULT block",
                    "result": result,
                }

        # DONE is the completion directive; RESULT is the structured payload that
        # accompanies it. A RESULT without DONE ({"status": "in_progress"}, a
        # plan, a partial table) is not a completion: treating it as one
        # recorded unfinished steps as successful (issues #61, browser epochs).
        if result_match and not done_match:
            result_match = None

        # Directive precedence: models quote protocol keywords in their
        # reasoning constantly — the system prompt itself teaches the magic
        # strings. When one response carries BOTH an actionable TOOL and a
        # DONE/RESULT completion, the LAST directive wins (models emit their
        # decision at the end). A false completion destroys the dispatch;
        # a false tool call costs one turn (issue #61).
        if tool_match and (done_match or result_match):
            completion_pos = max(
                done_match.start() if done_match else -1,
                result_match.start() if result_match else -1,
            )
            logger.info(
                "Protocol ambiguity: TOOL@%d and DONE/RESULT@%d in one response — "
                "taking the later directive",
                tool_match.start(), completion_pos,
            )
            if tool_match.start() > completion_pos:
                done_match = None
                result_match = None

        # Check for DONE
        if done_match or result_match:
            answer = done_match.group(1).strip() if done_match else None
            summary = answer or "Completed via RESULT block"
            result = None
            if result_match:
                try:
                    result = json.loads(result_match.group(1).strip())
                except (json.JSONDecodeError, ValueError):
                    result = result_match.group(1).strip()
            return {
                "type": "done", "thought": thought, "summary": summary,
                "result": result, "answer": answer or None,
            }

        # Check for TOOL (matched above, before precedence resolution)
        if tool_match:
            tool_name = tool_match.group(1).strip()
            params = {}
            params_match = _PARAMS_PATTERN.search(content)
            if params_match:
                params_str = params_match.group(1).strip()
                # Try parsing the full JSON object using brace-counting.
                # The LLM often emits multi-line JSON (e.g. write_code with
                # code containing literal newlines), so split("\n")[0] would
                # truncate the JSON and cause a parse failure.
                params = _extract_json_object(params_str)
                if params is None:
                    # Fallback: try first line (works for simple single-line params)
                    try:
                        params = json.loads(params_str.split("\n")[0])
                    except (json.JSONDecodeError, ValueError):
                        params = {"raw": params_str}
            return {"type": "tool", "thought": thought, "tool": tool_name, "params": params}

        # ── JSON protocol fallback ──
        # Some models emit the protocol as a single structured object. Accept
        # only explicit protocol fields; arbitrary JSON remains unparseable.
        obj = _extract_json_object(content)
        if obj is not None:
            json_thought = obj.get("thought", thought)
            if isinstance(obj.get("tool"), str) and obj["tool"].strip():
                return {
                    "type": "tool",
                    "thought": json_thought,
                    "tool": obj["tool"].strip(),
                    "params": obj.get("parameters", obj.get("params", {})),
                }

            done_summary = obj.get("done")
            if done_summary is None and "summary" in obj and "result" in obj:
                done_summary = obj.get("summary")
            if done_summary is not None:
                return {
                    "type": "done",
                    "thought": json_thought,
                    "summary": str(done_summary),
                    "result": obj.get("result"),
                    "answer": str(done_summary).strip() or None,
                }

        # Unparseable
        return {"type": "raw", "content": content}

    @classmethod
    def _parse_response_for_contract(
        cls, content: str, context: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        parsed = cls._parse_response(content)
        contract = (context or {}).get("execution_contract")
        if (
            parsed.get("type") == "raw"
            and isinstance(contract, dict)
            and contract.get("execution_shape") == "single_artifact"
        ):
            artifact = _extract_json_object(content)
            if artifact is not None:
                return {
                    "type": "done",
                    "thought": "",
                    "summary": "Structured artifact completed.",
                    "result": artifact,
                }
        return parsed
