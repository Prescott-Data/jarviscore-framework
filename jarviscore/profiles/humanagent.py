"""
HumanAgent — a person as a peer on the mesh.

A HumanAgent is registered, announced and discovered like any agent: it has a
role and capabilities, other nodes see it in their roster, mesh planners can
route steps to it, it claims workflow steps from the shared ledger, and peers
reach it with ``request_capability``. The difference is who does the work:
each task is put in front of a person through a channel, and the person's
answer is the result.

    from jarviscore import Mesh
    from jarviscore.profiles import HumanAgent

    mesh = Mesh(config={"p2p_enabled": True, "seed_nodes": "10.0.0.5:7949"})
    mesh.add(HumanAgent("alice", ["review", "approve"]))
    await mesh.start()

Or from a terminal, with no code: ``jarviscore human join alice --capabilities
review,approve --seed 10.0.0.5:7949``.

Every HumanAgent also carries the ``human`` capability, so a workflow step or
a peer can ask for "a person" without knowing who is online.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, Iterable, Optional
from uuid import uuid4

from jarviscore.core.envelope import attach_result_summary
from jarviscore.core.profile import Profile
from jarviscore.human.channels import HumanChannel, TerminalChannel, WorkItem

#: Shown to a person per upstream result; enough to judge, not a data dump.
UPSTREAM_SUMMARY_CHARS = 1500


def _summaries(previous: Any) -> Dict[str, str]:
    if not isinstance(previous, dict):
        return {}
    out = {}
    for step, value in previous.items():
        text = value if isinstance(value, str) else json.dumps(value, default=str)
        out[str(step)] = text if len(text) <= UPSTREAM_SUMMARY_CHARS else text[:UPSTREAM_SUMMARY_CHARS] + " …"
    return out


class HumanAgent(Profile):
    """A person on the mesh, reached through a channel (terminal by default)."""

    #: Seconds to wait for the person before the task fails.
    answer_timeout: float = 3600.0

    def __init__(
        self,
        name: Optional[str] = None,
        capabilities: Optional[Iterable[str]] = None,
        *,
        channel: Optional[HumanChannel] = None,
        description: Optional[str] = None,
        capability_descriptions: Optional[Dict[str, str]] = None,
        answer_timeout: Optional[float] = None,
        agent_id: Optional[str] = None,
    ):
        # Instance values take precedence over class attributes, so both
        # HumanAgent("alice", ["review"]) and a subclass with role/capabilities work.
        if name:
            self.role = name
        caps = list(capabilities) if capabilities is not None else list(type(self).capabilities or [])
        if caps and "human" not in caps:
            caps.append("human")
        self.capabilities = caps
        super().__init__(agent_id)

        self.description = (
            description
            or getattr(type(self), "description", "")
            or f"{self.role} is a person, not a model: answers take minutes, not seconds."
        )
        descriptions = dict(capability_descriptions or type(self).capability_descriptions or {})
        for capability in self.capabilities:
            descriptions.setdefault(capability, f"{capability}, done by {self.role} (a person)")
        self.capability_descriptions = descriptions
        self.channel = channel or TerminalChannel()
        if answer_timeout is not None:
            self.answer_timeout = answer_timeout

    async def setup(self):
        await super().setup()
        await self.channel.start(self)

    async def teardown(self):
        await self.channel.stop()
        await super().teardown()

    async def execute_task(self, task: Dict[str, Any]) -> Dict[str, Any]:
        """Put the task in front of the person and return their answer."""
        context = task.get("context") or {}
        item = WorkItem(
            id=f"task-{uuid4().hex[:10]}",
            task=str(task.get("task") or ""),
            asked_by=str(
                context.get("peer_sender")
                or context.get("peer_requester_agent_id")
                or ("workflow" if context.get("workflow_id") else "")
            ),
            capability=str(context.get("capability") or ""),
            workflow_id=str(context.get("workflow_id") or ""),
            step_id=str(context.get("step_id") or ""),
            upstream=_summaries(context.get("previous_step_results")),
        )
        try:
            answer = await asyncio.wait_for(self.channel.ask(item), timeout=self.answer_timeout)
        except asyncio.TimeoutError:
            return attach_result_summary({
                "status": "failure",
                "error": f"{self.role} did not answer within {self.answer_timeout:.0f}s.",
            })

        output = {
            "response": answer.response,
            "decision": answer.decision,
            "answered_by": answer.by or self.role,
        }
        if answer.decision in ("rejected", "declined"):
            return attach_result_summary({
                "status": "failure",
                "error": f"{self.role} {answer.decision}: {answer.response or 'no reason given'}",
                "output": output,
            })
        return attach_result_summary({"status": "success", "output": output})

    async def authorize_dependencies(self, task, artifacts, interpretations):
        """The person sees upstream results with the task and decides for themselves."""
        from jarviscore.orchestration.envelopes import DependencyAuthorization

        return DependencyAuthorization("allow", "A person judges upstream results directly.")

    async def _handle_peer_request(self, message) -> Dict[str, Any]:
        data = message.data if isinstance(message.data, dict) else {}
        question = data.get("query") or data.get("task")
        if not isinstance(question, str) or not question.strip():
            return {"status": "failure", "error": "Peer requests require a query or task."}
        context = dict(message.context or {})
        capability = str(data.get("capability") or "").strip()
        if capability:
            if capability not in self.capabilities:
                return {
                    "status": "failure",
                    "error": f"{self.role} does not own capability {capability!r}.",
                }
            context["capability"] = capability
        context.update(
            peer_sender=data.get("from") or message.sender,
            peer_correlation_id=message.correlation_id,
        )
        return await self.execute_task({"task": question.strip(), "context": context})

    async def _handle_peer_notify(self, message) -> None:
        await self.channel.notify(str(message.sender), message.data)
