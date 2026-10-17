"""
How a person on the mesh receives work and answers it.

A ``HumanAgent`` hands each piece of work to a channel as a ``WorkItem`` and
waits for a ``HumanAnswer``. Two channels ship:

- ``TerminalChannel``: an interactive console. Tasks appear as they arrive and
  the person types the answer. The same console lets the person ``/ask`` any
  capability on the mesh and see ``/peers``, so a human is a full peer, not
  only an approver.
- ``InboxChannel``: one JSON file per task in a directory. Answered with
  ``jarviscore human answer`` or by anything that writes the file, such as a
  dashboard or a chat bridge.

A channel only needs ``ask``; ``start``, ``notify`` and ``stop`` are optional.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import threading
import time
from collections import deque
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Deque, Dict, List, Optional, TextIO, Tuple

#: answered — the person did the work; approved — they signed it off;
#: rejected — they refused it; declined — they will not or cannot do it.
DECISIONS = ("answered", "approved", "rejected", "declined")

_COMMANDS = (("approved", "/approve"), ("rejected", "/reject"), ("declined", "/decline"))


@dataclass
class WorkItem:
    """One piece of work put in front of a person."""

    id: str
    task: str
    asked_by: str = ""
    capability: str = ""
    workflow_id: str = ""
    step_id: str = ""
    upstream: Dict[str, str] = field(default_factory=dict)
    asked_at: float = field(default_factory=time.time)

    def to_record(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class HumanAnswer:
    decision: str
    response: str = ""
    by: str = ""

    def __post_init__(self):
        if self.decision not in DECISIONS:
            raise ValueError(f"decision must be one of {DECISIONS}, not {self.decision!r}")

    @classmethod
    def parse(cls, line: str, by: str = "") -> "HumanAnswer":
        """Free text is an answer; /approve, /reject and /decline set the decision."""
        text = line.strip()
        for decision, command in _COMMANDS:
            if text == command or text.startswith(command + " "):
                return cls(decision, text[len(command):].strip(), by)
        return cls("answered", text, by)


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
    """Base channel. Subclasses implement ``ask``."""

    async def start(self, agent: Any) -> None:
        self.agent = agent

    async def ask(self, item: WorkItem) -> HumanAnswer:
        raise NotImplementedError

    async def notify(self, sender: str, message: Any) -> None:
        return None

    async def stop(self) -> None:
        return None


# ── Terminal ─────────────────────────────────────────────────────────────────

_HELP = """\
  <text>                  answer the task in front of you
  /approve [note]         sign it off
  /reject <why>           refuse it; the step fails with your reason
  /decline <why>          you will not or cannot do it
  /ask <capability> <q>   ask whoever on the mesh has that capability
  /peers                  who is on the mesh
  /help                   this list"""


class TerminalChannel(HumanChannel):
    """Interactive console: tasks queue up and are shown one at a time."""

    def __init__(self, input_stream: Optional[TextIO] = None, output: Optional[TextIO] = None,
                 peer_timeout: float = 300.0):
        self._in = input_stream or sys.stdin
        self._out = output or sys.stdout
        self._peer_timeout = peer_timeout
        self._waiting: Deque[Tuple[WorkItem, asyncio.Future]] = deque()
        self._current: Optional[Tuple[WorkItem, asyncio.Future]] = None
        self._background: set = set()
        self._console: Optional[asyncio.Task] = None

    async def start(self, agent: Any) -> None:
        await super().start(agent)
        self._loop = asyncio.get_running_loop()
        self._lines: asyncio.Queue = asyncio.Queue()
        # A daemon thread, not run_in_executor: a blocked read must not keep the
        # process alive after the mesh stops.
        threading.Thread(target=self._read, name="human-console", daemon=True).start()
        self._console = asyncio.create_task(self._run_console(), name=f"human-console-{agent.role}")
        caps = ", ".join(c for c in agent.capabilities if c != "human")
        self._print(f"\nYou are on the mesh as {agent.role} ({caps}).")
        self._print("Tasks for you will appear here. /help for commands.\n")

    async def stop(self) -> None:
        for task in [self._console, *self._background]:
            if task and not task.done():
                task.cancel()

    def _read(self) -> None:
        for line in self._in:
            self._loop.call_soon_threadsafe(self._lines.put_nowait, line.rstrip("\n"))
        self._loop.call_soon_threadsafe(self._lines.put_nowait, None)

    async def _run_console(self) -> None:
        while True:
            line = await self._lines.get()
            if line is None:
                return
            try:
                await self._handle(line)
            except Exception as exc:  # the console outlives any one bad line
                self._print(f"  ! {type(exc).__name__}: {exc}")

    async def _handle(self, line: str) -> None:
        text = line.strip()
        if not text:
            return
        if text in ("/help", "?"):
            self._print(_HELP)
        elif text == "/peers":
            self._print_peers()
        elif text == "/ask" or text.startswith("/ask "):
            parts = text.split(maxsplit=2)
            if len(parts) < 3:
                self._print("  usage: /ask <capability> <question>")
                return
            task = asyncio.create_task(self._ask_peer(parts[1], parts[2]))
            self._background.add(task)
            task.add_done_callback(self._background.discard)
        elif self._current is not None:
            item, future = self._current
            self._current = None
            if not future.done():
                future.set_result(HumanAnswer.parse(text, by=self.agent.role))
            self._print(f"  ✓ sent ({item.id})")
            self._show_next()
        else:
            self._print("  Nothing is waiting on you. /ask <capability> <question>, /peers, /help")

    async def ask(self, item: WorkItem) -> HumanAnswer:
        future = self._loop.create_future()
        self._waiting.append((item, future))
        if self._current is None:
            self._show_next()
        else:
            self._print(f"  (+1 task queued: {item.id})")
        try:
            return await future
        except asyncio.CancelledError:
            if self._current and self._current[1] is future:
                self._current = None
                self._print(f"  ✗ {item.id} was withdrawn by the mesh")
                self._show_next()
            raise

    async def notify(self, sender: str, message: Any) -> None:
        self._print(f"\n  ✉ {sender}: {readable(message)}\n")

    def _show_next(self) -> None:
        while self._waiting:
            item, future = self._waiting.popleft()
            if future.done():
                continue
            self._current = (item, future)
            self._print_item(item)
            return

    def _print_item(self, item: WorkItem) -> None:
        origin = " · ".join(p for p in (
            item.capability, f"from {item.asked_by}" if item.asked_by else "",
            f"{item.workflow_id}/{item.step_id}" if item.workflow_id else "",
        ) if p)
        self._print(f"\n━━ Task for you{f'  ({origin})' if origin else ''}  [{item.id}]")
        self._print(item.task)
        for step, summary in item.upstream.items():
            self._print(f"  ↳ {step}: {summary}")
        more = f"  {len(self._waiting)} more waiting." if self._waiting else ""
        self._print(f"Answer, or /approve [note] · /reject <why> · /decline <why>.{more}")

    def _print_peers(self) -> None:
        peers = self.agent.peers.list_peers() if getattr(self.agent, "peers", None) else []
        if not peers:
            self._print("  No peers yet.")
            return
        for peer in peers:
            caps = ", ".join(peer.get("capabilities") or [])
            kind = "person" if "human" in (peer.get("capabilities") or []) else "agent"
            self._print(f"  {peer.get('role')}  [{kind}, {peer.get('location', '')}]  {caps}")

    async def _ask_peer(self, capability: str, question: str) -> None:
        self._print(f"  → asking {capability} …")
        result = await self.agent.peers.request_capability(
            capability, question, timeout=self._peer_timeout
        )
        if result.get("status") != "success":
            self._print(f"\n  ✗ {capability}: {result.get('error')}\n")
            return
        who = result.get("peer_role") or capability
        self._print(f"\n  ← {who}: {readable(result.get('result'))}\n")

    def _print(self, text: str) -> None:
        print(text, file=self._out, flush=True)


# ── Inbox ────────────────────────────────────────────────────────────────────

def _write_json(path: Path, record: Dict[str, Any]) -> None:
    """Replace the file in one step so a reader never sees half a record."""
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(record, indent=2, default=str))
    os.replace(tmp, path)


def _read_json(path: Path) -> Optional[Dict[str, Any]]:
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None


class InboxChannel(HumanChannel):
    """One JSON file per task under ``<directory>/<role>/``."""

    def __init__(self, directory: str = "human_inbox", poll_interval: float = 1.0):
        self._root = Path(directory)
        self._poll = poll_interval

    async def start(self, agent: Any) -> None:
        await super().start(agent)
        self._dir = self._root / agent.role
        self._dir.mkdir(parents=True, exist_ok=True)

    async def ask(self, item: WorkItem) -> HumanAnswer:
        path = self._dir / f"{item.id}.json"
        _write_json(path, {**item.to_record(), "for": self.agent.role, "status": "open"})
        try:
            while True:
                record = _read_json(path) or {}
                if record.get("status") == "answered":
                    return HumanAnswer(
                        record.get("decision") or "answered",
                        record.get("response") or "",
                        record.get("answered_by") or self.agent.role,
                    )
                await asyncio.sleep(self._poll)
        except asyncio.CancelledError:
            record = _read_json(path) or {}
            if record.get("status") == "open":
                _write_json(path, {**record, "status": "withdrawn"})
            raise

    async def notify(self, sender: str, message: Any) -> None:
        with open(self._dir / "notices.jsonl", "a") as handle:
            handle.write(json.dumps({"from": sender, "message": message, "at": time.time()},
                                    default=str) + "\n")


def open_items(directory: str = "human_inbox") -> List[Dict[str, Any]]:
    """Every task still waiting on a person, oldest first."""
    items = []
    for path in Path(directory).glob("*/*.json"):
        record = _read_json(path)
        if record and record.get("status") == "open":
            items.append(record)
    return sorted(items, key=lambda r: r.get("asked_at", 0))


def answer_item(item_id: str, decision: str, response: str = "", by: str = "",
                directory: str = "human_inbox") -> Dict[str, Any]:
    """Answer an open task. Raises LookupError if it is unknown or no longer open."""
    HumanAnswer(decision, response, by)
    for path in Path(directory).glob(f"*/{item_id}.json"):
        record = _read_json(path)
        if not record:
            continue
        if record.get("status") != "open":
            raise LookupError(f"{item_id} is {record.get('status')}, not open")
        record.update(status="answered", decision=decision, response=response,
                      answered_by=by or record.get("for", ""), answered_at=time.time())
        _write_json(path, record)
        return record
    raise LookupError(f"No task {item_id!r} under {directory}")
