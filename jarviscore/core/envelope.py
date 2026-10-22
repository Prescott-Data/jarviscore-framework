"""Canonical display field for task envelopes.

Every ``execute_task`` envelope carries ``result_summary``: always
present, always plain prose, never JSON. Structured data stays in
``output`` / ``payload`` / ``goal_execution`` for programmatic
consumers; ``result_summary`` is the display contract (issue #40).
"""

import json
from typing import Any, Dict, Optional

OBSERVATION_REASONING_RULE = (
    "The artifact is an agent-authored report, not proof that its claims are true. "
    "observed_tool_result is the original runtime observation. Reason from the "
    "observations before accepting the report. For each requirement, compare the "
    "actual query, scope, period and result coverage with the source request. "
    "Resolve contradictions between the report and observations explicitly; an "
    "unsupported claim of completeness cannot establish missing coverage. "
    "A real citation establishes that an observation exists, not that the agent's "
    "interpretation is correct."
)

def caller_view(result: Any) -> Any:
    """A result as the developer who asked for it reads it.

    Inside the mesh, a cited tool result carries its runtime observation
    (``observed_tool_result``) next to the agent's claim, so evaluators and later
    steps can check one against the other. Returned to application code, that
    put tool inputs and raw outputs in the middle of the answer. Here
    ``output``/``payload`` hold what the agent delivered, ``result_summary`` the
    prose answer, and the observations move, whole, to ``evidence``. The stored
    result and what later steps receive are unchanged.
    """
    if not isinstance(result, dict):
        return result
    evidence: list = []
    seen: set = set()

    def strip(value: Any) -> Any:
        if isinstance(value, list):
            return [strip(item) for item in value]
        if not isinstance(value, dict):
            return value
        kept = {}
        for key, item in value.items():
            if key == "observed_tool_result" and isinstance(item, dict):
                receipt = value.get("tool_receipt_id")
                marker = receipt or id(item)
                if marker not in seen:
                    seen.add(marker)
                    evidence.append({"tool_receipt_id": receipt, **item})
                continue
            kept[key] = strip(item)
        return kept

    view = dict(result)
    same = "payload" in view and view.get("payload") is view.get("output")
    if "output" in view:
        view["output"] = strip(view["output"])
    if "payload" in view:
        view["payload"] = view["output"] if same else strip(view["payload"])
    view["evidence"] = [*(view.get("evidence") or []), *evidence]
    return view


def dependency_artifact(result: Any) -> Any:
    """Return the delivered artifact without discarding unfinished work or its status."""
    if isinstance(result, dict) and not result.get("progress"):
        if result.get("status") in {None, "success", "complete"}:
            return result.get("output", result)
    return result


#: Artifact fields a specialist keeps to continue its own work, as opposed to what it delivered.
WORKING_STATE_FIELDS = ("browser_state", "browser_programs", "browser_calls")


def handoff_view(artifact: Any, step_id: str = "") -> Any:
    """The artifact as a later reader's prompt carries it: the delivered work whole, working state by reference.

    Nothing is cut: the working state stays whole in the step's durable output, where
    read_workflow_step and browser code (``prior``) read it.
    """
    if not isinstance(artifact, dict):
        return artifact
    if isinstance(artifact.get("status"), str) and any(
        field in artifact for field in ("output", "payload")
    ):
        view = dict(artifact)
        for field in ("output", "payload"):
            if field in view:
                view[field] = handoff_view(view[field], step_id)
        if "output" in artifact and "payload" in artifact and artifact["output"] == artifact["payload"]:
            view.pop("payload", None)
        return view
    held = {name: artifact[name] for name in WORKING_STATE_FIELDS if name in artifact}
    if not held:
        return artifact

    def described(value: Any) -> Dict[str, Any]:
        shape: Dict[str, Any] = {"chars": len(json.dumps(value, default=str, ensure_ascii=False))}
        if isinstance(value, dict):
            shape["keys"] = sorted(map(str, value))
        elif isinstance(value, list):
            shape["items"] = len(value)
        return shape

    view = {key: value for key, value in artifact.items() if key not in held}
    view["working_state"] = {
        "fields": {name: described(value) for name, value in held.items()},
        "read_whole": (
            f'read_workflow_step("{step_id}") returns it whole' if step_id
            else "read_workflow_step returns it whole"
        ) + "; browser code reads it from prior",
    }
    return view

# Keys downstream UIs were probing heuristically, in preference order.
_PROSE_KEYS = (
    "result_summary", "response", "content", "final_answer", "answer",
    "summary", "message", "text", "brief",
)


def _prose_from(value: Any) -> Optional[str]:
    """Extract display prose from a payload without serialising structures."""
    if isinstance(value, str):
        text = value.strip()
        return text or None
    if isinstance(value, dict):
        for key in _PROSE_KEYS:
            inner = value.get(key)
            if isinstance(inner, str) and inner.strip():
                return inner.strip()
            if isinstance(inner, dict):
                nested = _prose_from(inner)
                if nested:
                    return nested
    return None


def derive_result_summary(
    status: str,
    output: Any = None,
    error: Any = None,
    summary: Optional[str] = None,
) -> str:
    """Derive the canonical human-readable summary for an envelope.

    Failure paths yield the error sentence (never a traceback or repr);
    success paths prefer payload prose, then probed prose keys, then the
    execution summary.
    """
    if status not in ("success", "complete"):
        if isinstance(error, str) and error.strip():
            return error.strip().splitlines()[0]
        if error is not None:
            return str(error).splitlines()[0]
        if isinstance(summary, str) and summary.strip():
            return summary.strip()
        return f"Task ended with status: {status}"

    prose = _prose_from(output)
    if prose:
        return prose
    if isinstance(summary, str) and summary.strip():
        return summary.strip()
    return "Task completed."


def attach_result_summary(envelope: Dict[str, Any], summary: Optional[str] = None) -> Dict[str, Any]:
    """Ensure ``result_summary`` is present on *envelope* (idempotent)."""
    existing = envelope.get("result_summary")
    if isinstance(existing, str) and existing.strip():
        return envelope
    envelope["result_summary"] = derive_result_summary(
        status=str(envelope.get("status", "")),
        output=envelope.get("output", envelope.get("payload")),
        error=envelope.get("error"),
        summary=summary,
    )
    return envelope
