"""
jarviscore.hitl.queue — HITLQueue implementation.
==================================================

Dual-backend HITL queue: persists to Redis (via ``RedisContextStore``)
when available AND to flat JSON files (for file-based dashboard polling).
Works gracefully without Redis — file persistence is always active.

Content guard
-------------
HITL payloads are capped at framework level to prevent multi-KB data dumps
from polluting the review UI.  ``MAX_CONTENT_CHARS`` and ``MAX_CONTEXT_CHARS``
are the hard limits.

API
---
The public interface matches what agents expect (injected as ``self.hitl``
by the Mesh):

- ``request(title, content, urgency, context)`` → ``str`` (request_id)
- ``check(request_id)``                         → ``HITLResolution | None``
- ``wait(request_id, timeout)``                  → ``HITLResolution``
- ``pending()``                                  → ``List[HITLRequest]``
- ``resolve(request_id, decision, reason)``      → ``bool``
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from jarviscore.contracts.hitl import (
    HITLCategory,
    HITLRequest,
    HITLResolution,
    HITLStatus,
    HITLType,
    normalize_hitl_decision,
)


logger = logging.getLogger("jarviscore.hitl")

# ── Content size guards ──────────────────────────────────────────────────────
# HITL payloads are human-readable summaries, not data dumps.
MAX_CONTENT_CHARS = 2000   # ~2 KB — plenty for a review summary
MAX_CONTEXT_CHARS = 1000   # structured context field — keep lean


def _truncate(text: str, limit: int) -> str:
    """Truncate text to *limit* characters with an ellipsis marker."""
    if not text or len(text) <= limit:
        return text or ""
    return text[:limit] + "\n\n… (truncated)"


class HITLQueue:
    """
    Human-in-the-Loop escalation queue for JarvisCore agents.

    Injected into every agent by the Mesh at ``start()`` time as
    ``agent.hitl``.  Agents call ``self.hitl.request(...)`` to submit
    items for human review.

    Dual persistence:
      - **File**: Always writes a JSON file to ``inbox_dir/`` so
        file-based dashboards can poll for new items immediately.
      - **Redis**: When a ``redis_store`` is provided, also persists
        a typed ``HITLRequest`` via ``create_hitl_request_typed()``
        for real-time push and structured queries.

    Usage::

        # Inside any agent (self.hitl is injected by Mesh):
        item_id = self.hitl.request(
            title="Review investor deck before sending",
            content=deck_summary,
            urgency="high",
            context={"file": "output/q2_deck.pptx"},
        )

        # Optionally block until human decides:
        resolution = await self.hitl.wait(item_id, timeout=3600)
        if resolution and resolution.is_approved:
            await self._send_deck()
    """

    VALID_URGENCY = {"low", "normal", "high", "critical"}

    # Default inbox location — can be overridden via inbox_dir parameter
    _DEFAULT_INBOX = Path("hitl_inbox")

    def __init__(
        self,
        agent_id: str,
        inbox_dir: Optional[str] = None,
        redis_store=None,
    ):
        self._agent_id = agent_id
        self._inbox_dir = Path(inbox_dir) if inbox_dir else self._DEFAULT_INBOX
        self._inbox_dir.mkdir(parents=True, exist_ok=True)
        self._redis_store = redis_store
        self._logger = logging.getLogger(f"jarviscore.hitl.{agent_id}")

    # ─────────────────────────────────────────────────────────────────────────
    # Public API
    # ─────────────────────────────────────────────────────────────────────────

    def request(
        self,
        title: str,
        content: str,
        urgency: str = "normal",
        context: Optional[Dict[str, Any]] = None,
        category: str = "",
    ) -> str:
        """
        Submit a human review request.

        CATEGORY IS REQUIRED and must be one of the three permitted values:

          auth_required   — Nexus/API credentials missing or expired.
          data_required   — Critical data only the founder can supply.
          critical_action — Irreversible or sensitive action needing sign-off.

        Any other reason (output quality checks, self-validation, content
        completeness doubts, "the output looked truncated", etc.) is NOT
        a valid escalation.  Agents must handle those autonomously.
        Passing an invalid category raises ValueError so the agent is forced
        to reconsider before the item reaches the founder's inbox.

        Args:
            title:    Headline shown in the review list — never truncated, keep it descriptive
            content:  Full details for the reviewer — markdown supported
            urgency:  One of "low", "normal", "high", "critical"
            context:  Arbitrary dict for structured metadata (file paths,
                      downstream actions, agent state snapshots, etc.)
            category: One of "auth_required", "data_required", "critical_action"

        Returns:
            request_id: Unique identifier for this review request.
                        Use with ``check()`` or ``wait()`` to poll.

        Raises:
            ValueError: If urgency is not one of the valid levels
            ValueError: If category is not one of the three permitted values
        """
        if urgency not in self.VALID_URGENCY:
            raise ValueError(
                f"Invalid urgency '{urgency}'. Must be one of: {self.VALID_URGENCY}"
            )

        # ── Category gate — hard enforcement ────────────────────────────────
        valid_categories = {c.value for c in HITLCategory}
        if category not in valid_categories:
            raise ValueError(
                f"Invalid HITL category '{category}'. "
                f"Permitted values: {sorted(valid_categories)}. "
                "Only escalate for auth failures, missing founder-supplied data, "
                "or irreversible/sensitive actions. "
                "Everything else must be handled autonomously."
            )
        hitl_category = HITLCategory(category)

        ts = time.strftime("%Y%m%d-%H%M%S")
        request_id = f"hitl-{ts}-{uuid.uuid4().hex[:8]}"
        now_iso = time.strftime("%Y-%m-%dT%H:%M:%S")

        # ── Apply content guards ─────────────────────────────────────────────
        # Titles are labels — never truncated. Content/context are size-guarded
        # to prevent multi-KB data dumps from polluting the review UI.
        safe_title = (title or "").strip()
        safe_content = _truncate(content or "", MAX_CONTENT_CHARS)
        safe_context = self._truncate_context(context or {})

        # ── Build typed request ──────────────────────────────────────────────
        hitl_request = HITLRequest(
            request_id=request_id,
            workflow_id=safe_context.get("workflow_id", self._agent_id),
            step_id=safe_context.get("step_id", request_id),
            type=HITLType.approval,
            status=HITLStatus.pending,
            category=hitl_category,
            description=safe_content,
            payload={
                "title": safe_title,
                "urgency": urgency,
                "category": hitl_category.value,
                "content": safe_content,
            },
            targets=["founder"],
            channels=["dashboard"],
            mode="adaptive",
            metadata={
                "agent_id": self._agent_id,
                "context": safe_context,
            },
        )

        # ── Persist to flat file (always) ────────────────────────────────────
        self._write_file(request_id, hitl_request, safe_title, safe_content,
                         urgency, hitl_category.value, safe_context, now_iso)

        # ── Persist to Redis (when available) ────────────────────────────────
        if self._redis_store:
            try:
                self._redis_store.create_hitl_request_typed(hitl_request)
            except Exception as exc:
                self._logger.warning(
                    "Redis HITL write failed (file write succeeded): %s", exc
                )

        self._logger.info(
            "HITL request submitted: id=%s category=%s urgency=%s title=%r",
            request_id, hitl_category.value, urgency, safe_title[:60],
        )
        return request_id

    def check(self, request_id: str) -> Optional[HITLResolution]:
        """
        Check whether a review request has been decided.

        Non-blocking — returns None if still pending or not found.

        Checks file first (always available), then Redis for real-time
        updates from dashboards that write to Redis directly.

        Args:
            request_id: ID returned from ``request()``

        Returns:
            HITLResolution if resolved, None if pending or not found.
        """
        # Check flat file first
        filepath = self._inbox_dir / f"{request_id}.json"
        if filepath.exists():
            try:
                data = json.loads(filepath.read_text())
                if data.get("status") in ("approved", "rejected", "resolved"):
                    return HITLResolution.from_raw(data)
            except (json.JSONDecodeError, OSError) as exc:
                self._logger.warning("Could not read HITL item %s: %s", request_id, exc)

        # Fallback: check Redis
        if self._redis_store:
            try:
                # Extract workflow_id and step_id from the file metadata
                if filepath.exists():
                    data = json.loads(filepath.read_text())
                    wf_id = data.get("context", {}).get("workflow_id", self._agent_id)
                    step_id = data.get("context", {}).get("step_id", request_id)
                else:
                    wf_id = self._agent_id
                    step_id = request_id
                return self._redis_store.get_hitl_resolution(wf_id, step_id)
            except Exception as exc:
                self._logger.warning("Redis HITL lookup failed: %s", exc)

        return None

    async def wait(
        self,
        request_id: str,
        timeout: float = 3600.0,
        poll_interval: float = 10.0,
    ) -> HITLResolution:
        """
        Async-poll until the review request is decided or timeout expires.

        Suspends the calling coroutine (agent's run loop keeps going) rather
        than blocking the event loop.

        Args:
            request_id:    ID returned from ``request()``
            timeout:       Max seconds to wait (default 1 hour)
            poll_interval: How often to check in seconds (default 10s)

        Returns:
            HITLResolution with final decision

        Raises:
            TimeoutError: If timeout expires before a decision is made
        """
        elapsed = 0.0
        while elapsed < timeout:
            resolution = self.check(request_id)
            if resolution is not None:
                return resolution
            await asyncio.sleep(poll_interval)
            elapsed += poll_interval

        raise TimeoutError(
            f"HITL item {request_id!r} timed out after {timeout:.0f}s without a decision"
        )

    def pending(self) -> List[Dict[str, Any]]:
        """
        Return all pending HITL items submitted by this agent.

        Useful for agents that want to avoid submitting duplicates.
        """
        items = []
        for f in sorted(self._inbox_dir.glob("hitl-*.json"), reverse=True):
            try:
                data = json.loads(f.read_text())
                if (
                    data.get("agent") == self._agent_id
                    and data.get("status") == "pending"
                    and data.get("type") == "hitl"
                ):
                    items.append(data)
            except (json.JSONDecodeError, OSError):
                pass
        return items

    def resolve(
        self,
        request_id: str,
        decision: str,
        reason: str = "",
    ) -> bool:
        """
        Programmatically resolve a HITL item (for testing or auto-approval).

        Args:
            request_id: Item to resolve
            decision:   "approved" or "rejected"
            reason:     Optional reason string

        Returns:
            True if item was found and updated, False otherwise
        """
        filepath = self._inbox_dir / f"{request_id}.json"
        if not filepath.exists():
            return False
        try:
            data = json.loads(filepath.read_text())
            normalized = normalize_hitl_decision(decision)
            # `status` is the lifecycle state (pending -> resolved); the
            # approve/reject verdict lives in `decision`. Writing the verdict
            # into `status` broke HITLResolution.from_raw(), which only builds a
            # resolution when status == "resolved" — so check() could never read
            # a file-resolved item back (HITL queue contract fix).
            data["status"] = HITLStatus.resolved.value
            data["decision"] = normalized.value
            data["decision_reason"] = reason
            data["request_id"] = request_id
            data["resolved_by"] = data.get("resolved_by") or "auto"
            data["resolved_at"] = time.time()
            data["decided_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
            filepath.write_text(json.dumps(data, indent=2))

            # Also update Redis if available
            if self._redis_store:
                try:
                    wf_id = data.get("context", {}).get("workflow_id", self._agent_id)
                    step_id = data.get("context", {}).get("step_id", request_id)
                    self._redis_store.resolve_hitl_request(
                        wf_id, step_id, decision=normalized.value,
                        responder="auto", comment=reason,
                    )
                except Exception as exc:
                    self._logger.warning("Redis HITL resolve failed: %s", exc)

            self._logger.info("HITL item %s resolved: %s", request_id, decision)
            return True
        except (json.JSONDecodeError, OSError) as exc:
            self._logger.error("Failed to resolve HITL item %s: %s", request_id, exc)
            return False

    # ─────────────────────────────────────────────────────────────────────────
    # Internals
    # ─────────────────────────────────────────────────────────────────────────

    def _write_file(
        self,
        request_id: str,
        hitl_request: HITLRequest,
        title: str,
        content: str,
        urgency: str,
        category: str,
        context: Dict[str, Any],
        created_at: str,
    ) -> None:
        """Write HITL item to flat JSON file for dashboard polling."""
        data = {
            "id": request_id,
            "agent": self._agent_id,
            "title": title,
            "content": content,
            "urgency": urgency,
            "category": category,
            "context": context,
            "created_at": created_at,
            "status": "pending",
            "decision": None,
            "decision_reason": None,
            "decided_at": None,
            "type": "hitl",
        }
        filepath = self._inbox_dir / f"{request_id}.json"
        try:
            filepath.write_text(json.dumps(data, indent=2))
        except OSError as exc:
            self._logger.error("Failed to write HITL file %s: %s", filepath, exc)

    def _truncate_context(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Truncate string values in context dict to prevent bloat."""
        safe = {}
        for key, value in context.items():
            if isinstance(value, str):
                safe[key] = _truncate(value, MAX_CONTEXT_CHARS)
            elif isinstance(value, dict):
                # One level deep — don't recurse infinitely
                safe[key] = {
                    k: _truncate(v, MAX_CONTEXT_CHARS) if isinstance(v, str) else v
                    for k, v in value.items()
                }
            else:
                safe[key] = value
        return safe
