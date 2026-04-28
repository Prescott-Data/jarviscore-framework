"""
Browser action protocol and schema validation.
Provides a consistent action contract across agents.
"""
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Literal

BrowserActionKind = Literal[
    "navigate",
    "snapshot",
    "snapshot_ai",
    "click",
    "type",
    "hover",
    "select",
    "check",
    "drag",
    "scroll",
    "wait",
    "evaluate",
    "screenshot",
    "get_text",
    "download",
    "upload",
    "cookies_get",
    "cookies_set",
    "cookies_clear",
    "storage_get",
    "storage_set",
    "storage_clear",
    "offline",
    "pdf",
    "close",
    "capture_start",
    "capture_stop",
    "capture_status",
    "capture_export",
]

SUPPORTED_ACTION_KINDS = list(BrowserActionKind.__args__)


@dataclass
class BrowserAction:
    """Normalized browser action."""
    kind: BrowserActionKind
    target_id: Optional[str] = None
    profile: Optional[str] = None
    payload: Dict[str, Any] = field(default_factory=dict)


@dataclass
class BrowserActionResult:
    """Standard action result."""
    success: bool
    data: Any = None
    error: Optional[str] = None
    kind: Optional[str] = None
    ref: Optional[str] = None


def normalize_action(raw: Dict[str, Any]) -> BrowserAction:
    """
    Normalize a raw action payload into a BrowserAction.
    """
    if not isinstance(raw, dict):
        raise ValueError("Action payload must be a dict")
    kind = raw.get("kind")
    if not kind:
        raise ValueError("Action must include 'kind'")
    if kind not in BrowserActionKind.__args__:
        raise ValueError(f"Unsupported action kind: {kind}")
    return BrowserAction(
        kind=kind,
        target_id=raw.get("target_id"),
        profile=raw.get("profile"),
        payload=raw.get("payload") or {},
    )


def validate_action(action: BrowserAction) -> None:
    """Basic validation for action payloads."""
    payload = action.payload or {}
    kind = action.kind
    if kind == "navigate":
        if not payload.get("url"):
            raise ValueError("navigate requires payload.url")
    elif kind in ("click", "type", "hover", "select", "check", "scroll", "get_text"):
        if not payload.get("ref"):
            raise ValueError(f"{kind} requires payload.ref")
    elif kind == "drag":
        if not payload.get("start_ref") or not payload.get("end_ref"):
            raise ValueError("drag requires payload.start_ref and payload.end_ref")
    elif kind == "wait":
        if not any(payload.get(k) for k in ("text", "text_gone", "time_ms", "url", "load_state")):
            raise ValueError("wait requires at least one condition")
    elif kind == "select":
        values = payload.get("values") or []
        if not isinstance(values, list) or not values:
            raise ValueError("select requires payload.values (non-empty list)")
    elif kind == "upload":
        if not payload.get("ref") and not payload.get("element"):
            raise ValueError("upload requires payload.ref or payload.element")
        if not payload.get("paths"):
            raise ValueError("upload requires payload.paths")
    elif kind in ("cookies_set", "storage_set"):
        if kind == "cookies_set" and not payload.get("cookie"):
            raise ValueError("cookies_set requires payload.cookie")
        if kind == "storage_set" and not payload.get("key"):
            raise ValueError("storage_set requires payload.key")
    elif kind in ("storage_get", "storage_clear"):
        if payload.get("kind") not in ("local", "session"):
            raise ValueError("storage kind must be local|session")

