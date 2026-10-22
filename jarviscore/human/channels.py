"""
How a person on the mesh is shown work and answers it.

A ``HumanAgent``'s work items are HITL requests (``HITLQueue.assign``): stored
with the rest of the deployment's human decisions, and answerable from
anywhere: ``jarviscore human answer``, a review dashboard, or a room's chat.
A channel only puts them in front of the person and sends back what the
person decided:

- ``TerminalChannel``: an interactive console. Each item appears as it
  arrives; the person types their answer and picks how to send it.
- no channel: items wait in the HITL inbox (``jarviscore human inbox``).

Write your own channel by subclassing ``HumanChannel``: ``show`` is called
with each new item, and the person's answer goes to ``agent.answer(...)``.
"""

from __future__ import annotations

import asyncio
import json
import sys
import threading
from typing import Any, Dict, Optional, TextIO

#: What a person can do with a piece of work. answered: they did it;
#: approved: they signed it off; rejected: they refused it (the step fails
#: with their reason); declined: they will not or cannot do it (it fails too).
DECISIONS = ("answered", "approved", "rejected", "declined")

# The HITL decision each one is stored as, and back.
_TO_HITL = {"answered": "continue", "approved": "approved", "rejected": "rejected", "declined": "denied"}
_FROM_HITL = {"continue": "answered", "resume": "answered", "approve": "approved", "approved": "approved",
              "yes": "approved", "reject": "rejected", "rejected": "rejected", "no": "rejected",
              "deny": "declined", "denied": "declined"}


def to_hitl_decision(decision: str) -> str:
    if decision not in _TO_HITL:
        raise ValueError(f"decision must be one of {DECISIONS}, not {decision!r}")
    return _TO_HITL[decision]


def from_hitl_decision(decision: Any) -> str:
    value = str(getattr(decision, "value", decision) or "").lower()
    return _FROM_HITL.get(value, "answered")


def readable(value: Any, limit: int = 2000) -> str:
    """Render a peer result for a person: the answer, not the envelope around it."""
    while isinstance(value, dict):
        for key in ("response", "output", "result", "answer", "text"):
            if key in value and value[key] not in (None, ""):
                value = value[key]
                break
        else:
            break
    if not isinstance(value, str):
        value = json.dumps(value, indent=2, default=str)
    return value if len(value) <= limit else value[:limit] + " …"


class HumanChannel:
    """Puts a HumanAgent's items in front of the person. Every method is optional."""

    async def start(self, agent: Any) -> None:
        self.agent = agent

    async def show(self, item: Dict[str, Any]) -> None:
        """A new item for the person (a HITL inbox record; its ``context`` has the details)."""

    async def withdraw(self, item_id: str) -> None:
        """The item is no longer needed (the step timed out or was cancelled)."""

    async def notify(self, sender: str, message: Any) -> None:
        """A peer sent the person a message."""

    async def stop(self) -> None:
        return None


class TerminalChannel(HumanChannel):
    """An interactive console: items are shown one at a time and answered there."""

    def __init__(self, input_stream: Optional[TextIO] = None, output: Optional[TextIO] = None):
        self._in = input_stream or sys.stdin
        self._out = output or sys.stdout
        self._items: asyncio.Queue = asyncio.Queue()
        self._withdrawn: set = set()
        self._console: Optional[asyncio.Task] = None

    async def start(self, agent: Any) -> None:
        await super().start(agent)
        self._loop = asyncio.get_running_loop()
        self._lines: asyncio.Queue = asyncio.Queue()
        # A daemon thread, not run_in_executor: a blocked read must not keep the
        # process alive after the mesh stops.
        threading.Thread(target=self._read, name="human-console", daemon=True).start()
        self._console = asyncio.create_task(self._run(), name=f"human-console-{agent.role}")
        caps = ", ".join(c for c in agent.capabilities if c != "human")
        self._print(f"\nYou are on the mesh as {agent.role}" + (f" ({caps})." if caps else "."))
        self._print("Work for you will appear here.\n")

    async def stop(self) -> None:
        if self._console and not self._console.done():
            self._console.cancel()

    async def show(self, item: Dict[str, Any]) -> None:
        await self._items.put(item)

    async def withdraw(self, item_id: str) -> None:
        self._withdrawn.add(item_id)

    async def notify(self, sender: str, message: Any) -> None:
        self._print(f"\n  ✉ {sender}: {readable(message)}\n")

    def _read(self) -> None:
        for line in self._in:
            self._loop.call_soon_threadsafe(self._lines.put_nowait, line.rstrip("\n"))
        self._loop.call_soon_threadsafe(self._lines.put_nowait, None)

    async def _run(self) -> None:
        while True:
            item = await self._items.get()
            if item["id"] in self._withdrawn:
                continue
            self._print_item(item)
            response = await self._lines.get()
            if response is None:
                return
            self._print("  Send it as: 1 answer · 2 approval · 3 rejection · 4 decline  [1]")
            choice = await self._lines.get()
            if choice is None:
                return
            if item["id"] in self._withdrawn:
                self._print("  ✗ That item was withdrawn before you answered.")
                continue
            decision = {"2": "approved", "3": "rejected", "4": "declined"}.get(choice.strip(), "answered")
            self.agent.answer(item["id"], decision, response.strip())
            self._print(f"  ✓ sent as {decision}")

    def _print_item(self, item: Dict[str, Any]) -> None:
        context = item.get("context") or {}
        origin = " · ".join(p for p in (
            context.get("capability", ""),
            f"for {context['asked_by']}" if context.get("asked_by") else "",
            f"{context.get('workflow_id')}/{context.get('step_id')}" if context.get("workflow_id") else "",
        ) if p)
        self._print(f"\n━━ Work for you{f'  ({origin})' if origin else ''}")
        self._print(item.get("content") or item.get("title", ""))
        if context.get("workspace"):
            self._print(f"  📂 {context['workspace']}")
            self._print("     Edit the files there in your editor; your changes go in when you answer.")
        waiting = self._items.qsize()
        self._print(f"Type your answer and press Enter.{f'  {waiting} more waiting.' if waiting else ''}")

    def _print(self, text: str) -> None:
        print(text, file=self._out, flush=True)
