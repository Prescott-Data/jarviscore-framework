"""Client for Prescott's limited JarvisCore launch promotion.

The token accepted by this client is a revocable Prescott entitlement token.
It is never an upstream model-provider credential. The server owns provider
credentials, model selection, expiry, quotas, and campaign budget controls.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import aiohttp

DEFAULT_PROMO_ENDPOINT = "https://jarviscore.developers.prescottdata.io/api/promo/v1/generate"


class PromoAccessError(RuntimeError):
    """The promotion rejected or could not authorize an inference request."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        status: int,
        call_id: str,
        raw_response: Any = None,
        raw_artifact_path: Optional[str] = None,
    ):
        super().__init__(message)
        self.code = code
        self.status = status
        self.call_id = call_id
        self.raw_response = raw_response
        self.raw_artifact_path = raw_artifact_path


class PromoProtocolError(RuntimeError):
    """The promotion endpoint returned a response outside its public contract."""


@dataclass(frozen=True)
class _HTTPResult:
    status: int
    headers: Dict[str, str]
    body: str


class PromoLLMClient:
    """Call the restricted Prescott promotional inference endpoint."""

    def __init__(
        self,
        token: str,
        *,
        endpoint: str = DEFAULT_PROMO_ENDPOINT,
        model: str = "jarviscore-promo",
        timeout: float = 120.0,
        artifact_dir: str = "./traces/promo_calls",
    ) -> None:
        if not token or not token.strip():
            raise ValueError("A non-empty JARVISCORE_PROMO_TOKEN is required")
        if not endpoint.startswith("https://"):
            raise ValueError("The promotional inference endpoint must use HTTPS")

        self._token = token.strip()
        self.endpoint = endpoint
        self.model = model
        self.timeout = timeout
        self.artifact_dir = Path(artifact_dir)

    async def generate(
        self,
        messages: List[Dict[str, Any]],
        *,
        temperature: float,
        max_tokens: int,
        requested_model: Optional[str] = None,
        options: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Generate one completion and preserve the complete exchange locally."""
        call_id = f"jcp_{uuid.uuid4().hex}"
        payload: Dict[str, Any] = {
            "call_id": call_id,
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "requested_model": requested_model,
            "options": options or {},
        }

        started = time.monotonic()
        try:
            http_result = await self._send(payload, call_id)
        except Exception as exc:
            safe_error = str(exc).replace(self._token, "***")
            http_result = _HTTPResult(
                status=0,
                headers={},
                body=json.dumps(
                    {"code": "promotion_network_error", "message": safe_error},
                    ensure_ascii=False,
                ),
            )
            artifact_path = self._write_raw_artifact(call_id, payload, http_result)
            raise PromoAccessError(
                "promotion_network_error",
                f"Could not reach the JarvisCore promotion endpoint: {safe_error}",
                status=0,
                call_id=call_id,
                raw_response={
                    "exception_type": type(exc).__name__,
                    "message": safe_error,
                },
                raw_artifact_path=str(artifact_path),
            ) from exc
        duration = time.monotonic() - started
        artifact_path = self._write_raw_artifact(call_id, payload, http_result)

        try:
            data = json.loads(http_result.body)
        except json.JSONDecodeError as exc:
            raise PromoProtocolError(
                f"Promotion endpoint returned non-JSON data for call {call_id}; "
                f"complete response preserved at {artifact_path}"
            ) from exc

        if not isinstance(data, dict):
            raise PromoProtocolError(
                f"Promotion endpoint returned a non-object response for call {call_id}; "
                f"complete response preserved at {artifact_path}"
            )

        if http_result.status != 200:
            code = str(data.get("code") or "promotion_request_failed")
            message = str(
                data.get("message") or f"Promotion request failed with HTTP {http_result.status}"
            )
            raise PromoAccessError(
                code,
                message,
                status=http_result.status,
                call_id=call_id,
                raw_response=data,
                raw_artifact_path=str(artifact_path),
            )

        required = {"call_id", "content", "tool_calls", "usage", "model", "finish_reason"}
        missing = sorted(required.difference(data))
        if missing:
            raise PromoProtocolError(
                f"Promotion endpoint omitted required fields {missing} for call {call_id}; "
                f"complete response preserved at {artifact_path}"
            )
        if data["call_id"] != call_id:
            raise PromoProtocolError(
                f"Promotion endpoint returned a mismatched call_id for {call_id}; "
                f"complete response preserved at {artifact_path}"
            )

        usage = data["usage"]
        if not isinstance(usage, dict) or not {"input", "output", "total"}.issubset(usage):
            raise PromoProtocolError(
                f"Promotion endpoint returned invalid usage for call {call_id}; "
                f"complete response preserved at {artifact_path}"
            )

        return {
            "content": data["content"],
            "provider": "promo",
            "tool_calls": data["tool_calls"],
            "tokens": {
                "input": usage["input"],
                "output": usage["output"],
                "total": usage["total"],
            },
            "cost_usd": 0.0,
            "model": data["model"],
            "duration_seconds": duration,
            "finish_reason": data["finish_reason"],
            "call_id": call_id,
            "entitlement": data.get("entitlement"),
            "raw_response": data,
            "raw_artifact_path": str(artifact_path),
            "raw_artifact_excluded_diagnostics": ["request.headers.Authorization"],
        }

    async def _send(self, payload: Dict[str, Any], call_id: str) -> _HTTPResult:
        timeout = aiohttp.ClientTimeout(total=self.timeout)
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
            "X-JarvisCore-Call-ID": call_id,
        }
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(self.endpoint, json=payload, headers=headers) as response:
                return _HTTPResult(
                    status=response.status,
                    headers=dict(response.headers),
                    body=await response.text(),
                )

    def _write_raw_artifact(
        self,
        call_id: str,
        payload: Dict[str, Any],
        http_result: _HTTPResult,
    ) -> Path:
        """Atomically persist the complete request and HTTP response."""
        self.artifact_dir.mkdir(parents=True, exist_ok=True)
        artifact_path = self.artifact_dir / f"{call_id}.json"
        artifact = {
            "call_id": call_id,
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            "request": {
                "endpoint": self.endpoint,
                "payload": payload,
            },
            "response": {
                "status": http_result.status,
                "headers": http_result.headers,
                "body": http_result.body,
            },
            "excluded_diagnostics": ["request.headers.Authorization"],
        }

        fd, temporary_name = tempfile.mkstemp(
            prefix=f".{call_id}.", suffix=".tmp", dir=self.artifact_dir
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(artifact, handle, ensure_ascii=False)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_name, artifact_path)
        except Exception:
            try:
                os.unlink(temporary_name)
            except FileNotFoundError:
                pass
            raise
        return artifact_path
