"""
Browser network capture and UI-derived API synthesis.
"""
from dataclasses import dataclass, asdict, field
from datetime import datetime
import json
import os
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlsplit, parse_qs

# Settings replaced with env vars — see os.environ usage below
# FunctionContract not needed in framework context


@dataclass
class CaptureConfig:
    enabled: bool
    max_body_bytes: int
    max_events: int
    include_request_body: bool
    include_response_body: bool
    redact_headers: List[str]


@dataclass
class NetworkCaptureEvent:
    id: str
    timestamp: str
    method: str
    url: str
    status: Optional[int] = None
    ok: Optional[bool] = None
    resource_type: Optional[str] = None
    request_headers: Dict[str, str] = field(default_factory=dict)
    request_body: Optional[str] = None
    response_headers: Dict[str, str] = field(default_factory=dict)
    response_body: Optional[str] = None
    response_content_type: Optional[str] = None
    response_truncated: bool = False
    error: Optional[str] = None
    profile: Optional[str] = None
    target_id: Optional[str] = None


def build_capture_config() -> CaptureConfig:
    raw_headers = os.environ.get("BROWSER_CAPTURE_REDACT_HEADERS", "") or ""
    redact = [h.strip().lower() for h in raw_headers.split(",") if h.strip()]
    return CaptureConfig(
        enabled=os.environ.get("BROWSER_CAPTURE_ENABLED", "false").lower() in ("1", "true", "yes"),
        max_body_bytes=int(os.environ.get("BROWSER_CAPTURE_MAX_BODY_BYTES", "10000")),
        max_events=int(os.environ.get("BROWSER_CAPTURE_MAX_EVENTS", "500")),
        include_request_body=os.environ.get("BROWSER_CAPTURE_INCLUDE_REQUEST_BODY", "true").lower() in ("1", "true", "yes"),
        include_response_body=os.environ.get("BROWSER_CAPTURE_INCLUDE_RESPONSE_BODY", "true").lower() in ("1", "true", "yes"),
        redact_headers=redact,
    )


def _redact_headers(headers: Dict[str, str], redact_headers: List[str]) -> Dict[str, str]:
    if not headers:
        return {}
    redact_set = {h.lower() for h in redact_headers}
    cleaned: Dict[str, str] = {}
    for key, value in headers.items():
        if key.lower() in redact_set:
            cleaned[key] = "<redacted>"
        else:
            cleaned[key] = value
    return cleaned


def _truncate_body(body: Optional[bytes], max_bytes: int) -> Tuple[Optional[str], bool]:
    if body is None:
        return None, False
    if max_bytes <= 0:
        return None, True
    truncated = len(body) > max_bytes
    if truncated:
        body = body[:max_bytes]
    try:
        return body.decode("utf-8", errors="replace"), truncated
    except Exception:
        return None, truncated


def _content_type_is_text(content_type: Optional[str]) -> bool:
    if not content_type:
        return False
    ctype = content_type.lower()
    return any(
        token in ctype
        for token in ("application/json", "text/", "application/xml", "text/xml", "application/x-www-form-urlencoded")
    )


def should_capture_body(headers: Dict[str, str], config: CaptureConfig) -> bool:
    if not config.include_response_body:
        return False
    content_type = headers.get("content-type") or headers.get("Content-Type")
    return _content_type_is_text(content_type)


class BrowserTrafficCapture:
    def __init__(self, session_id: str, config: CaptureConfig, trace_dir: Optional[str] = None):
        self.session_id = session_id
        self.config = config
        self.trace_dir = trace_dir or os.environ.get("BROWSER_CAPTURE_DIR", "/tmp/browser_captures")
        self.started_at = datetime.utcnow().isoformat() + "Z"
        self.events: List[NetworkCaptureEvent] = []
        self.events_by_id: Dict[str, NetworkCaptureEvent] = {}
        os.makedirs(self.trace_dir, exist_ok=True)

    def add_request(
        self,
        request_id: str,
        method: str,
        url: str,
        headers: Dict[str, str],
        body: Optional[str],
        resource_type: Optional[str],
        profile: Optional[str],
        target_id: Optional[str],
    ) -> None:
        if len(self.events) >= self.config.max_events:
            return
        event = NetworkCaptureEvent(
            id=request_id,
            timestamp=datetime.utcnow().isoformat() + "Z",
            method=method,
            url=url,
            resource_type=resource_type,
            request_headers=_redact_headers(headers, self.config.redact_headers),
            request_body=body if self.config.include_request_body else None,
            profile=profile,
            target_id=target_id,
        )
        self.events.append(event)
        self.events_by_id[request_id] = event

    def add_response(
        self,
        request_id: str,
        status: Optional[int],
        ok: Optional[bool],
        headers: Dict[str, str],
        body: Optional[bytes],
    ) -> None:
        event = self.events_by_id.get(request_id)
        if not event:
            return
        redacted_headers = _redact_headers(headers, self.config.redact_headers)
        content_type = redacted_headers.get("content-type") or redacted_headers.get("Content-Type")
        event.status = status
        event.ok = ok
        event.response_headers = redacted_headers
        event.response_content_type = content_type
        if self.config.include_response_body and _content_type_is_text(content_type):
            text, truncated = _truncate_body(body, self.config.max_body_bytes)
            event.response_body = text
            event.response_truncated = truncated

    def add_failure(self, request_id: str, error: Optional[str]) -> None:
        event = self.events_by_id.get(request_id)
        if not event:
            return
        event.error = error or "request_failed"

    def summary(self) -> Dict[str, Any]:
        ok_count = sum(1 for e in self.events if e.ok)
        return {
            "session_id": self.session_id,
            "events": len(self.events),
            "ok": ok_count,
            "failed": len(self.events) - ok_count,
            "started_at": self.started_at,
        }

    def save(self) -> str:
        path = os.path.join(self.trace_dir, f"capture_{self.session_id}.jsonl")
        with open(path, "a", encoding="utf-8") as f:
            for event in self.events:
                f.write(json.dumps(asdict(event)) + "\n")
        return path

    def save_contracts(self, contracts: List[Dict[str, Any]]) -> str:
        path = os.path.join(self.trace_dir, f"contracts_{self.session_id}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"session_id": self.session_id, "contracts": contracts}, f, indent=2)
        return path

    def synthesize_contracts(self, min_confidence: int = 40) -> List[Dict[str, Any]]:
        grouped: Dict[Tuple[str, str], List[NetworkCaptureEvent]] = {}
        for event in self.events:
            if not event.method or not event.url:
                continue
            endpoint = _normalize_endpoint(event.url)
            key = (event.method.upper(), endpoint)
            grouped.setdefault(key, []).append(event)

        contracts: List[Dict[str, Any]] = []
        for (method, endpoint), events in grouped.items():
            event = _pick_best_event(events)
            if not event:
                continue
            contract = _build_contract_from_event(event, endpoint, self.session_id)
            if not contract:
                continue
            if contract.get("capture_confidence", 0) < min_confidence:
                continue
            contracts.append(contract)
        return contracts


def _normalize_endpoint(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}{parts.path}"


def _pick_best_event(events: List[NetworkCaptureEvent]) -> Optional[NetworkCaptureEvent]:
    if not events:
        return None
    def score(e: NetworkCaptureEvent) -> int:
        score_val = 0
        if e.ok:
            score_val += 10
        if e.response_content_type and "json" in e.response_content_type.lower():
            score_val += 10
        if e.response_body:
            score_val += 5
        return score_val
    return sorted(events, key=score, reverse=True)[0]


def _infer_action_name(endpoint: str, method: str) -> str:
    parts = urlsplit(endpoint)
    path = parts.path.strip("/")
    if not path:
        return f"{method.lower()}_root"
    last = path.split("/")[-1]
    cleaned = "".join(ch if ch.isalnum() else "_" for ch in last).strip("_")
    return cleaned or f"{method.lower()}_endpoint"


def _guess_auth_scheme(headers: Dict[str, str]) -> Optional[str]:
    if not headers:
        return None
    auth = None
    for key, value in headers.items():
        if key.lower() == "authorization":
            auth = value.lower()
            break
    if auth:
        if auth.startswith("bearer "):
            return "bearer"
        if auth.startswith("basic "):
            return "basic"
        return "custom_header"
    for key in headers:
        if key.lower() in ("x-api-key", "x-api_token", "x-api-token"):
            return "api_key"
    return None


def _extract_parameters(event: NetworkCaptureEvent) -> Dict[str, Any]:
    params: Dict[str, Any] = {}
    parts = urlsplit(event.url)
    query = parse_qs(parts.query or "")
    for key in query.keys():
        params[key] = {"type": "string", "required": False}

    if event.request_body:
        try:
            payload = json.loads(event.request_body)
            if isinstance(payload, dict):
                for key in payload.keys():
                    params.setdefault(key, {"type": "string", "required": False})
            elif isinstance(payload, list):
                params.setdefault("items", {"type": "array", "required": False})
        except Exception:
            try:
                form = parse_qs(event.request_body or "")
                for key in form.keys():
                    params.setdefault(key, {"type": "string", "required": False})
            except Exception:
                pass
    return params


def _extract_example_payload(event: NetworkCaptureEvent) -> Optional[Dict[str, Any]]:
    if not event.request_body:
        return None
    try:
        payload = json.loads(event.request_body)
        if isinstance(payload, dict):
            return payload
    except Exception:
        return None
    return None


def _extract_example_query(event: NetworkCaptureEvent) -> Optional[Dict[str, Any]]:
    parts = urlsplit(event.url)
    query = parse_qs(parts.query or "")
    if not query:
        return None
    return {k: v[0] if isinstance(v, list) and v else v for k, v in query.items()}


def _extract_response_schema(event: NetworkCaptureEvent) -> Dict[str, Any]:
    if not event.response_body:
        return {}
    try:
        payload = json.loads(event.response_body)
        if isinstance(payload, dict):
            return {key: "string" for key in payload.keys()}
        if isinstance(payload, list):
            return {"items": "object"}
    except Exception:
        return {}
    return {}


def _build_contract_from_event(event: NetworkCaptureEvent, endpoint: str, session_id: Optional[str]) -> Optional[Dict[str, Any]]:
    """Build a framework-neutral API contract dict from a captured network event."""
    parts = urlsplit(endpoint)
    system = parts.netloc or "ui_capture"
    action = _infer_action_name(endpoint, event.method)
    response_schema = _extract_response_schema(event)
    params = _extract_parameters(event)
    example_payload = _extract_example_payload(event)
    example_query = _extract_example_query(event)
    auth_scheme = _guess_auth_scheme(event.request_headers)
    confidence = 40
    if event.ok:
        confidence += 20
    if response_schema:
        confidence += 20
    if event.request_body:
        confidence += 10
    if confidence > 95:
        confidence = 95

    contract = {
        "system": system,
        "action": action,
        "auth_scheme": auth_scheme,
        "endpoint": endpoint,
        "method": event.method.upper(),
        "parameters": params,
        "response_schema": response_schema,
        "source": "ui_derived_api",
        "capture_session_id": session_id,
        "capture_confidence": confidence,
        "contract_origin": "ui_capture",
        "example_payload": example_payload,
        "example_query": example_query,
    }
    # Validity: must have method + endpoint
    if not contract.get("method") or not contract.get("endpoint"):
        return None
    return contract
