"""
Browser trace recording.
Lightweight JSONL trace for action auditing.
"""
from dataclasses import dataclass, asdict
from datetime import datetime
import json
import os
from typing import Any, Dict, Optional

# Settings replaced with env vars — see os.environ usage below


@dataclass
class BrowserTraceEvent:
    timestamp: str
    kind: str
    profile: Optional[str]
    target_id: Optional[str]
    success: bool
    duration_ms: int
    error: Optional[str] = None
    data: Optional[Dict[str, Any]] = None


class BrowserTraceRecorder:
    """
    Append-only JSONL trace of browser actions.
    """
    def __init__(self, trace_dir: Optional[str] = None):
        self.trace_dir = trace_dir or os.environ.get("BROWSER_TRACE_DIR", "/tmp/browser_traces")
        os.makedirs(self.trace_dir, exist_ok=True)
        self.trace_path = os.path.join(self.trace_dir, "browser_actions.jsonl")
        self._shot_dir = os.path.join(self.trace_dir, "screenshots")
        os.makedirs(self._shot_dir, exist_ok=True)
        self._shot_counter = 0

    def record(self, event: BrowserTraceEvent) -> None:
        payload = asdict(event)
        with open(self.trace_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(payload) + "\n")

    def record_action(
        self,
        kind: str,
        profile: Optional[str],
        target_id: Optional[str],
        success: bool,
        duration_ms: int,
        error: Optional[str] = None,
        data: Optional[Dict[str, Any]] = None,
    ) -> None:
        event = BrowserTraceEvent(
            timestamp=datetime.utcnow().isoformat() + "Z",
            kind=kind,
            profile=profile,
            target_id=target_id,
            success=success,
            duration_ms=duration_ms,
            error=error,
            data=data,
        )
        self.record(event)

    def save_screenshot(self, image_bytes: bytes, format: str = "png") -> Optional[str]:
        max_bytes = int(os.environ.get("BROWSER_TRACE_SCREENSHOT_MAX_BYTES", "500000"))
        if max_bytes and len(image_bytes) > max_bytes:
            return None
        self._shot_counter += 1
        name = f"shot_{self._shot_counter:06d}.{format}"
        path = os.path.join(self._shot_dir, name)
        with open(path, "wb") as f:
            f.write(image_bytes)
        return path

    def build_screenshot_url(self, path: str) -> Optional[str]:
        base = os.environ.get("BROWSER_TRACE_SCREENSHOT_BASE_URL", "")
        if not base:
            return None
        base = base.rstrip("/")
        rel = path.replace(self.trace_dir, "").lstrip(os.sep).replace(os.sep, "/")
        return f"{base}/{rel}"
