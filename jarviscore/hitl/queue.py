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

from jarviscore.config.paths import runtime_path
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
#: Who responds when neither the deployment nor the request names anyone.
DEFAULT_TARGETS = ("reviewer",)

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
    _DEFAULT_INBOX = Path(runtime_path("hitl_inbox"))

    def __init__(
        self,
        agent_id: str,
        inbox_dir: Optional[str] = None,
        redis_store=None,
        targets: Optional[List[str]] = None,
    ):
        self._agent_id = agent_id
        #: Who responds to this agent's requests unless a request names someone.
        self._targets = list(targets or DEFAULT_TARGETS)
        self._inbox_dir = Path(inbox_dir) if inbox_dir else self._DEFAULT_INBOX
        # created lazily on first write; an unused HITL queue leaves no dir
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
        targets: Optional[List[str]] = None,
    ) -> str:
        """
        Submit a human review request.

        CATEGORY IS REQUIRED and must be one of the three permitted values:

          auth_required   — Nexus/API credentials missing or expired.
          data_required   — Critical data only a person can supply.
          critical_action — Irreversible or sensitive action needing sign-off.

        Any other reason (output quality checks, self-validation, content
        completeness doubts, "the output looked truncated", etc.) is NOT
        a valid escalation.  Agents must handle those autonomously.
        Passing an invalid category raises ValueError so the agent is forced
        to reconsider before the item reaches a person.

        Args:
            title:    Headline shown in the review list — never truncated, keep it descriptive
            content:  Full details for the reviewer — markdown supported
            urgency:  One of "low", "normal", "high", "critical"
            context:  Arbitrary dict for structured metadata (file paths,
                      downstream actions, agent state snapshots, etc.)
            category: One of "auth_required", "data_required", "critical_action"
            targets:  Who should respond, e.g. ["finance-approver"]. Defaults to
                      the queue's targets (Mesh config ``hitl_targets``).

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
                "Only escalate for auth failures, data only a person can supply, "
                "or irreversible/sensitive actions. "
                "Everything else must be handled autonomously."
            )
        return self._submit(
            title, content, urgency=urgency, context=context,
            category=HITLCategory(category), kind=HITLType.approval,
            targets=list(targets or self._targets),
        )

    def assign(
        self,
        title: str,
        content: str,
        *,
        targets: List[str],
        context: Optional[Dict[str, Any]] = None,
        urgency: str = "normal",
    ) -> str:
        """
        Put work routed to a person in front of them, and return its id.

        This is not an escalation: a person on the mesh owns a capability (a
        review, a sign-off, a decision) and a workflow step was routed to them,
        so there is no category gate. The item is stored like any HITL request
        and is answered with ``resolve()``; ``wait()`` returns the answer, with
        the person's words in ``note``.

        Args:
            title:    What is asked, in a line
            content:  The full task, with what came before it
            targets:  Who it is for (the person's role on the mesh)
            context:  workflow_id, step_id and anything a review surface shows
        """
        if urgency not in self.VALID_URGENCY:
            raise ValueError(f"Invalid urgency '{urgency}'. Must be one of: {self.VALID_URGENCY}")
        return self._submit(title, content, urgency=urgency, context=context, category=None,
                            kind=HITLType.input_request, targets=list(targets))

    def inbox(self, target: Optional[str] = None, *, tenant: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Pending items for ``target`` (a person or role), from every agent, oldest first.

        Without a target, every pending item. With ``tenant``, only items raised
        by work done for someone in that tenant.
        """
        found: Dict[str, Dict[str, Any]] = {}
        shared = False
        if self._redis_store is not None and hasattr(self._redis_store, "hitl_pending"):
            try:
                for data in self._redis_store.hitl_pending(tenant):  # every host's items
                    found[data["id"]] = data
                shared = True
            except Exception as exc:
                self._logger.warning("Shared HITL inbox unavailable: %s", exc)
        for f in sorted(self._inbox_dir.glob("hitl-*.json")):
            try:
                data = json.loads(f.read_text())
            except (json.JSONDecodeError, OSError):
                continue
            request_id = data.get("id", f.stem)
            if shared and request_id not in found and data.get("status") == "pending":
                # Redis is the truth when it has the item: it may have been
                # answered on another host since this copy was written.
                try:
                    if self._redis_store.get_hitl_request(*self._hitl_key(request_id, data)):
                        continue
                except Exception:
                    pass
            found.setdefault(request_id, data)
        items = [
            data for data in found.values()
            if data.get("type") == "hitl" and data.get("status") == "pending"
            and (target is None or target in (data.get("targets") or []))
            and (tenant is None or (data.get("context") or {}).get("tenant") == tenant)
        ]
        return sorted(items, key=lambda d: d.get("created_at") or "")

    def _submit(
        self,
        title: str,
        content: str,
        *,
        urgency: str,
        context: Optional[Dict[str, Any]],
        category: Optional[HITLCategory],
        kind: HITLType,
        targets: List[str],
    ) -> str:
        ts = time.strftime("%Y%m%d-%H%M%S")
        request_id = f"hitl-{ts}-{uuid.uuid4().hex[:8]}"
        now_iso = time.strftime("%Y-%m-%dT%H:%M:%S")

        # ── Apply content guards ─────────────────────────────────────────────
        # Titles are labels — never truncated. Content/context are size-guarded
        # to prevent multi-KB data dumps from polluting the review UI.
        safe_title = (title or "").strip()
        safe_content = _truncate(content or "", MAX_CONTENT_CHARS)
        safe_context = self._truncate_context(context or {})
        # Which mesh step asked, so answering it can resume that step, and whose
        # tenant it is, so only that tenant's people see it.
        from jarviscore.auth.principal import acting_for
        from jarviscore.orchestration.step_context import current_step

        step = current_step.get()
        if step is not None:
            safe_context.setdefault("mesh_workflow_id", step[0])
            safe_context.setdefault("mesh_step_id", step[1])
        principal = acting_for.get() or ""
        if "/" in principal:
            safe_context.setdefault("tenant", principal.split("/", 1)[0])
        # Where the Redis copy lives. Work routed to a person gets a key of its
        # own: several items can belong to one step, or to none.
        workflow_id = safe_context.get("workflow_id") or self._agent_id
        step_id = (request_id if kind == HITLType.input_request
                   else safe_context.get("step_id") or request_id)

        # ── Build typed request ──────────────────────────────────────────────
        hitl_request = HITLRequest(
            request_id=request_id,
            workflow_id=workflow_id,
            step_id=step_id,
            type=kind,
            status=HITLStatus.pending,
            category=category,
            description=safe_content,
            payload={
                "title": safe_title,
                "urgency": urgency,
                "category": category.value if category else "",
                "content": safe_content,
            },
            targets=targets,
            channels=["dashboard"],
            mode="adaptive",
            metadata={
                "agent_id": self._agent_id,
                "context": safe_context,
            },
        )

        # ── Persist to flat file (always) ────────────────────────────────────
        self._write_file(request_id, hitl_request, safe_title, safe_content,
                         urgency, category.value if category else "", safe_context, now_iso)

        # ── Persist to Redis (when available) ────────────────────────────────
        if self._redis_store:
            try:
                self._redis_store.create_hitl_request_typed(hitl_request)
                record = self._read_file(request_id)
                if record:
                    self._redis_store.index_hitl_pending(request_id, record)
            except Exception as exc:
                self._logger.warning(
                    "Redis HITL write failed (file write succeeded): %s", exc
                )

        self._logger.info(
            "HITL %s submitted: id=%s category=%s urgency=%s title=%r",
            kind.value, request_id, category.value if category else "-", urgency, safe_title[:60],
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
                wf_id, step_id = self._hitl_key(request_id)
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
        if not self._inbox_dir.exists():    # hitl inbox dir created here
            return items
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
        by: str = "",
    ) -> bool:
        """
        Resolve a HITL item: a person's decision, or auto-approval in tests.

        An item is resolved once: when several people answer at the same time,
        the first answer stands and the others get False. With Redis, Redis
        decides who was first, across hosts. Answering an item that paused a
        mesh step (an agent's escalation) resumes that step with the answer.

        Args:
            request_id: Item to resolve
            decision:   "approved", "rejected", or another HITLDecision value
            reason:     The person's reason or answer, returned as the resolution's note
            by:         Who decided

        Returns:
            True if this call resolved the item, False if it was not pending.
        """
        data = self._read_file(request_id)
        if data is None and self._redis_store is not None and hasattr(self._redis_store, "hitl_pending"):
            data = next((r for r in self._redis_store.hitl_pending() if r.get("id") == request_id), None)
        if data is None or data.get("status") != "pending":
            return False
        normalized = normalize_hitl_decision(decision)
        if self._redis_store is not None and hasattr(self._redis_store, "resolve_hitl_once"):
            wf_id, step_id = self._hitl_key(request_id, data)
            try:
                won = self._redis_store.resolve_hitl_once(
                    wf_id, step_id, decision=normalized.value, responder=by or "auto", comment=reason)
            except Exception as exc:
                self._logger.warning("Redis HITL resolve failed; resolving the local copy: %s", exc)
                won = None
            if won is False:
                return False  # someone else answered first
            try:
                self._redis_store.unindex_hitl_pending(request_id)
            except Exception as exc:
                self._logger.warning("Could not unlist HITL item %s: %s", request_id, exc)
        filepath = self._inbox_dir / f"{request_id}.json"
        if filepath.exists():
            try:
                # `status` is the lifecycle state (pending -> resolved); the
                # approve/reject verdict lives in `decision` (HITLResolution.from_raw
                # only builds a resolution when status == "resolved").
                data.update({
                    "status": HITLStatus.resolved.value, "decision": normalized.value,
                    "decision_reason": reason, "note": reason, "request_id": request_id,
                    "resolved_by": by or data.get("resolved_by") or "auto",
                    "resolved_at": time.time(), "decided_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                })
                filepath.write_text(json.dumps(data, indent=2))
            except OSError as exc:
                self._logger.error("Failed to resolve HITL item %s: %s", request_id, exc)
                return False
        self._resume_step(data, normalized.value, reason, by)
        self._logger.info("HITL item %s resolved: %s", request_id, decision)
        return True

    def _resume_step(self, data: Dict[str, Any], decision: str, reason: str, by: str) -> None:
        """Resume the mesh step an escalation paused, with the person's answer."""
        context = data.get("context") or {}
        workflow_id, step_id = context.get("mesh_workflow_id"), context.get("mesh_step_id")
        if (data.get("kind") != HITLType.approval.value or not workflow_id or not step_id
                or self._redis_store is None or not hasattr(self._redis_store, "resume_workflow_step")):
            return
        try:
            self._redis_store.resume_workflow_step(workflow_id, step_id, context={
                "hitl_resolution": {"request_id": data.get("id"), "decision": decision,
                                    "note": reason, "resolved_by": by}})
        except (KeyError, ValueError):
            pass  # the step is not paused (it moved on, or was never waiting)
        except Exception as exc:
            self._logger.warning("Could not resume %s/%s after HITL answer: %s", workflow_id, step_id, exc)

    def expire(self, request_id: str) -> bool:
        """Close a pending item nobody answered in time, so it leaves every inbox.
        False if it was answered first."""
        data = self._read_file(request_id)
        if data is None or data.get("status") != "pending":
            return False
        if self._redis_store is not None and hasattr(self._redis_store, "expire_hitl_request"):
            try:
                if self._redis_store.expire_hitl_request(*self._hitl_key(request_id, data)) is False:
                    return False
                self._redis_store.unindex_hitl_pending(request_id)
            except Exception as exc:
                self._logger.warning("Could not expire HITL item %s in Redis: %s", request_id, exc)
        data["status"] = HITLStatus.expired.value
        data["decided_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        (self._inbox_dir / f"{request_id}.json").write_text(json.dumps(data, indent=2))
        return True

    # ─────────────────────────────────────────────────────────────────────────
    # Internals
    # ─────────────────────────────────────────────────────────────────────────

    def _read_file(self, request_id: str) -> Optional[Dict[str, Any]]:
        try:
            return json.loads((self._inbox_dir / f"{request_id}.json").read_text())
        except (OSError, json.JSONDecodeError):
            return None

    def _hitl_key(self, request_id: str, data: Optional[Dict[str, Any]] = None):
        """The (workflow_id, step_id) an item's Redis copy is stored under."""
        data = data if data is not None else (self._read_file(request_id) or {})
        if data.get("hitl_key"):
            return tuple(data["hitl_key"])
        context = data.get("context") or {}
        return (context.get("workflow_id") or self._agent_id, context.get("step_id") or request_id)

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
            "kind": hitl_request.type.value,
            "targets": list(hitl_request.targets),
            "hitl_key": [hitl_request.workflow_id, hitl_request.step_id],
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
            self._inbox_dir.mkdir(parents=True, exist_ok=True)  # ensure hitl inbox dir exists
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
