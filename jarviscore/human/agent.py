"""
HumanAgent — a person as a peer on the mesh.

Not one of the agent profiles (AutoAgent, CustomAgent): a profile is how an
agent does work, and here a person does it.

A HumanAgent is registered, announced and discovered like any agent: it has a
role and capabilities, other nodes see it in their roster, mesh planners can
route steps to it, it claims workflow steps from the shared ledger, and peers
reach it with ``request_capability``. The difference is who does the work:
each task becomes a HITL item addressed to the person (``HITLQueue.assign``),
a channel puts it in front of them, and their answer is the result. Because
the item lives in the HITL store, it can be answered from wherever the person
is: their terminal, ``jarviscore human answer``, a dashboard, or a room's chat.

    from jarviscore import Mesh, HumanAgent

    mesh = Mesh(config={"p2p_enabled": True, "seed_nodes": "10.0.0.5:7949"})
    mesh.add(HumanAgent("alice", ["review", "approve"]))
    await mesh.start()

Or from a terminal, with no code: ``jarviscore human join alice --capabilities
review,approve --seed 10.0.0.5:7949``.

Every HumanAgent also carries the ``human`` capability, so a workflow step or
a peer can ask for "a person" without knowing who is online.
"""

from __future__ import annotations

import json
from typing import Any, Dict, Iterable, Optional

from jarviscore.core.envelope import attach_result_summary
from jarviscore.core.profile import Profile
from jarviscore.execution.workspace import WorkspaceAccess
from jarviscore.human.channels import (
    HumanChannel,
    TerminalChannel,
    from_hitl_decision,
    to_hitl_decision,
)

_TERMINAL: Any = object()

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
    """A person on the mesh. Their work is HITL items; a channel shows them (terminal by default)."""

    #: Seconds to wait for the person before the task fails.
    answer_timeout: float = 3600.0
    #: How often to look for the person's answer.
    poll_interval: float = 1.0

    def __init__(
        self,
        name: Optional[str] = None,
        capabilities: Optional[Iterable[str]] = None,
        *,
        channel: Optional[HumanChannel] = _TERMINAL,
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
        # The terminal unless told otherwise; None leaves items in the HITL inbox.
        self.channel = TerminalChannel() if channel is _TERMINAL else channel
        if answer_timeout is not None:
            self.answer_timeout = answer_timeout
        # On a step whose goal works on files (a room, a repository), the Mesh
        # hands the person a copy of them; what they change is their work.
        self.sandbox = WorkspaceAccess()

    async def setup(self):
        await super().setup()
        if getattr(self, "hitl", None) is None:  # the Mesh injects the deployment's queue
            from jarviscore.hitl import HITLQueue

            self.hitl = HITLQueue(agent_id=self.agent_id)
        if self.channel is not None:
            await self.channel.start(self)

    async def teardown(self):
        if self.channel is not None:
            await self.channel.stop()
        await super().teardown()

    async def execute_task(self, task: Dict[str, Any]) -> Dict[str, Any]:
        """Put the task in front of the person and return their answer."""
        context = task.get("context") or {}
        text = str(task.get("task") or "")
        upstream = _summaries(context.get("previous_step_results"))
        content = text + "".join(f"\n\n{step}:\n{summary}" for step, summary in upstream.items())
        item_id = self.hitl.assign(
            title=text.splitlines()[0][:200] if text else "Work for you",
            content=content,
            targets=[self.role],
            context={
                "workflow_id": str(context.get("workflow_id") or ""),
                "step_id": str(context.get("step_id") or ""),
                "capability": str(context.get("capability") or ""),
                "asked_by": str(context.get("peer_sender") or context.get("peer_requester_agent_id")
                                or context.get("acting_for") or ""),
                "upstream": upstream,
                "workspace": str((context.get("workspace_binding") or {}).get("path") or ""),
            },
        )
        if self.channel is not None:
            await self.channel.show(self._item(item_id))
        try:
            resolution = await self.hitl.wait(item_id, timeout=self.answer_timeout,
                                              poll_interval=self.poll_interval)
        except TimeoutError:
            self.hitl.expire(item_id)
            if self.channel is not None:
                await self.channel.withdraw(item_id)
            return attach_result_summary({
                "status": "failure",
                "error": f"{self.role} did not answer within {self.answer_timeout:.0f}s.",
            })

        decision = from_hitl_decision(resolution.decision)
        response = resolution.note or ""
        output = {"response": response, "decision": decision,
                  "answered_by": resolution.resolved_by or self.role}
        if decision in ("rejected", "declined"):
            return attach_result_summary({
                "status": "failure",
                "error": f"{self.role} {decision}: {response or 'no reason given'}",
                "output": output,
            })
        return attach_result_summary({"status": "success", "output": output})

    def answer(self, item_id: str, decision: str, response: str = "", by: str = "") -> bool:
        """Answer one of this person's items: ``decision`` is answered, approved, rejected or declined."""
        return self.hitl.resolve(item_id, to_hitl_decision(decision), response, by=by or self.role)

    def waiting(self):
        """This person's items that are still waiting for an answer, oldest first."""
        return self.hitl.inbox(self.role)

    def _item(self, item_id: str) -> Dict[str, Any]:
        return next((i for i in self.hitl.inbox(self.role) if i["id"] == item_id), {"id": item_id})

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
