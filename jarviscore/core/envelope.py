"""Canonical display field for task envelopes.

Every ``execute_task`` envelope carries ``result_summary``: always
present, always plain prose, never JSON. Structured data stays in
``output`` / ``payload`` / ``goal_execution`` for programmatic
consumers; ``result_summary`` is the display contract (issue #40).
"""

from typing import Any, Dict, Optional

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
