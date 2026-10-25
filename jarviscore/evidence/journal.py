"""An append-only, hash-linked record of what the runtime decided and did.

Each run (a workflow step) is one file of JSON lines. Every event carries its
run, a sequence number, the hash of the event before it and its own hash, so an
edit, a reordering or a gap breaks the chain. A separate head log, itself
hash-linked, registers each run's latest head as it is written: a run that is
cut short, or removed, after its head was registered no longer matches the log.

What this proves, and what it does not (``jarviscore verify`` says the same):

- Integrity: an event written here cannot be changed without detection.
- Completeness, within what is mediated: every provider call the broker decided
  on was written before the call left, so a call without its record is visible.
- Not yet: protection against whoever controls this directory rewriting the
  whole of it. That needs the head log anchored outside the deployment
  (signed, witnessed checkpoints), which comes later.

Events hold what an auditor needs and nothing a log should not: methods, hosts,
paths, decisions, digests. Never query strings, bodies or credentials.
"""
from __future__ import annotations

import collections
import hashlib
import json
import logging
import os
import re
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Iterator, List, Optional, Tuple

logger = logging.getLogger(__name__)

FORMAT_VERSION = 1
GENESIS = "0" * 64
HEADS = "heads.jsonl"
RUNS = "runs"

_SAFE = re.compile(r"[^A-Za-z0-9._-]+")


def canonical(value: Any) -> str:
    """The one serialisation hashed: sorted keys, no whitespace, UTF-8 kept as is."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def _sealed(event: Dict[str, Any]) -> Tuple[Dict[str, Any], str]:
    """The event with its hash, and the line that stores it, serialised once."""
    body = canonical(event)
    sealed_hash = hashlib.sha256(body.encode("utf-8")).hexdigest()
    return {**event, "hash": sealed_hash}, f'{body[:-1]},"hash":"{sealed_hash}"}}\n'


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _last_line(path: str) -> Optional[Dict[str, Any]]:
    """The last complete event in a file, read from its end."""
    try:
        with open(path, "rb") as handle:
            handle.seek(0, os.SEEK_END)
            end = handle.tell()
            if end == 0:
                return None
            block = min(end, 65536)
            handle.seek(end - block)
            lines = handle.read(block).splitlines()
    except FileNotFoundError:
        return None
    for line in reversed(lines):
        if line.strip():
            return json.loads(line)
    return None


class _Locked:
    """An exclusive lock across processes on one file, where the platform has one."""

    def __init__(self, handle):
        self.handle = handle

    def __enter__(self):
        try:
            import fcntl

            fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX)
        except ImportError:  # pragma: no cover - Windows keeps the in-process lock only
            pass
        return self.handle

    def __exit__(self, *exc):
        try:
            import fcntl

            fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
        except ImportError:  # pragma: no cover
            pass


class _Chain:
    """One hash-linked file kept open, with its last event in memory.

    Another process may append to the same file; the tail is read again only
    when the file has grown since this process last wrote, so the common case is
    one ``fstat`` and one write under the lock.
    """

    def __init__(self, path: str):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self.path = path
        self.handle = open(path, "a", encoding="utf-8")
        self.size = -1
        self.last: Optional[Dict[str, Any]] = None

    def append(self, build) -> Dict[str, Any]:
        """Write ``build(last_event)`` as the next event, under an exclusive lock."""
        with _Locked(self.handle):
            size = os.fstat(self.handle.fileno()).st_size
            if size != self.size:
                self.last = _last_line(self.path)
            event, line = build(self.last)
            self.handle.write(line)
            self.handle.flush()
            self.size = size + len(line.encode("utf-8"))
            self.last = event
        return event

    def close(self) -> None:
        try:
            self.handle.close()
        except Exception:  # noqa: BLE001
            pass


class Journal:
    """Append events to runs under ``root``; every append also registers the run's new head."""

    #: Open run files kept per journal; the least recently used is closed beyond this.
    MAX_OPEN = 64

    def __init__(self, root: str):
        self.root = root
        self._lock = threading.Lock()
        self._chains: "collections.OrderedDict[str, _Chain]" = collections.OrderedDict()
        self._heads: Optional[_Chain] = None

    def run_path(self, run: str) -> str:
        return os.path.join(self.root, RUNS, f"{_SAFE.sub('_', run)[:200]}.jsonl")

    def _chain(self, path: str) -> _Chain:
        chain = self._chains.get(path)
        if chain is None or chain.handle.closed or not os.path.exists(path):
            chain = self._chains[path] = _Chain(path)
            while len(self._chains) > self.MAX_OPEN:
                self._chains.popitem(last=False)[1].close()
        self._chains.move_to_end(path)
        return chain

    def append(self, run: str, kind: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """Write one event and return it, sealed with its hash."""
        with self._lock:
            event = self._chain(self.run_path(run)).append(lambda last: _sealed({
                "v": FORMAT_VERSION,
                "run": run,
                "seq": (last["seq"] + 1) if last else 0,
                "ts": _now(),
                "kind": kind,
                "data": data,
                "prev": last["hash"] if last else GENESIS,
            }))
            heads_path = os.path.join(self.root, HEADS)
            if self._heads is None or self._heads.handle.closed or not os.path.exists(heads_path):
                self._heads = _Chain(heads_path)
            self._heads.append(lambda last: _sealed({
                "v": FORMAT_VERSION,
                "seq": (last["seq"] + 1) if last else 0,
                "run": event["run"],
                "run_seq": event["seq"],
                "run_hash": event["hash"],
                "prev": last["hash"] if last else GENESIS,
            }))
        return event

    def close(self) -> None:
        with self._lock:
            for chain in self._chains.values():
                chain.close()
            self._chains.clear()
            if self._heads is not None:
                self._heads.close()
                self._heads = None


_journal: Optional[Journal] = None
_journal_root: Optional[str] = None


def journal_root() -> Optional[str]:
    """Where this deployment's journal lives, or None when it is switched off."""
    import importlib

    settings_module = importlib.import_module("jarviscore.config.settings")

    configured = os.environ.get("JARVISCORE_JOURNAL_DIR")
    if configured is None:
        configured = getattr(settings_module.settings, "journal_dir", None)
    if configured is None or str(configured).strip().lower() in {"", "off", "none"}:
        return None
    return str(configured)


def current_journal() -> Optional[Journal]:
    global _journal, _journal_root
    root = journal_root()
    if root is None:
        return None
    if _journal is None or _journal_root != root:
        _journal, _journal_root = Journal(root), root
    return _journal


# ── Verification ──────────────────────────────────────────────────────────


@dataclass
class Verification:
    root: str
    runs: int = 0
    events: int = 0
    effects: int = 0
    refused: int = 0
    #: Changes refused when previewed, before a person was asked.
    refused_in_preview: int = 0
    problems: List[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems

    def summary(self) -> str:
        state = "intact" if self.ok else f"{len(self.problems)} problem(s)"
        preview = f", {self.refused_in_preview} refused before approval" if self.refused_in_preview else ""
        return (
            f"{self.runs} run(s), {self.events} event(s), {self.effects} provider call(s) "
            f"({self.refused} refused{preview}): {state}"
        )


def _events(path: str) -> Iterator[Tuple[int, Optional[Dict[str, Any]], str]]:
    with open(path, encoding="utf-8") as handle:
        for number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                yield number, json.loads(line), line
            except json.JSONDecodeError:
                yield number, None, line


def _check_chain(path: str, label: str, problems: List[str]) -> List[Dict[str, Any]]:
    """The events of one hash-linked file, with every break in its chain reported."""
    events: List[Dict[str, Any]] = []
    previous = GENESIS
    expected = 0
    for number, event, _ in _events(path):
        if event is None:
            problems.append(f"{label} line {number}: not a JSON event")
            continue
        claimed = event.get("hash")
        body = {key: value for key, value in event.items() if key != "hash"}
        if digest(body) != claimed:
            problems.append(f"{label} event {event.get('seq')}: its content does not match its hash")
        if event.get("prev") != previous:
            problems.append(f"{label} event {event.get('seq')}: does not follow the event before it")
        if event.get("seq") != expected:
            problems.append(f"{label}: expected event {expected}, found {event.get('seq')}")
        previous = claimed or ""
        expected = int(event.get("seq", expected)) + 1
        events.append(event)
    return events


def verify(root: str) -> Verification:
    """Check every run under ``root`` against its own chain, the head log, and its decisions."""
    report = Verification(root=root)
    heads_path = os.path.join(root, HEADS)
    heads: Dict[str, Tuple[int, str]] = {}
    if os.path.exists(heads_path):
        for head in _check_chain(heads_path, "head log", report.problems):
            heads[head["run"]] = (head["run_seq"], head["run_hash"])
    runs_dir = os.path.join(root, RUNS)
    seen = set()
    every: Dict[Tuple[str, int], Dict[str, Any]] = {}
    groundings: List[Tuple[str, Dict[str, Any]]] = []
    for name in sorted(os.listdir(runs_dir)) if os.path.isdir(runs_dir) else []:
        if not name.endswith(".jsonl"):
            continue
        path = os.path.join(runs_dir, name)
        events = _check_chain(path, f"run {name[:-6]}", report.problems)
        if not events:
            continue
        run = events[0].get("run", name[:-6])
        seen.add(run)
        report.runs += 1
        report.events += len(events)
        registered = heads.get(run)
        last = events[-1]
        if registered is None:
            report.problems.append(f"run {run}: not registered in the head log")
        elif registered != (last["seq"], last["hash"]):
            report.problems.append(
                f"run {run}: the head log registered event {registered[0]}, the run ends at "
                f"event {last['seq']} (cut short or rewritten)"
            )
        _check_decisions(run, events, report)
        for event in events:
            every[(run, event.get("seq"))] = event
            data = event.get("data") or {}
            if event.get("kind") == "policy.decision" and isinstance(data.get("grounding"), dict):
                groundings.append((f"run {run} event {event.get('seq')}", data))
    for run in sorted(set(heads) - seen):
        report.problems.append(f"run {run}: registered in the head log but its record is missing")
    for where, decision in groundings:
        _check_grounding(where, decision, every, report)
    return report


def _check_grounding(where: str, decision: Dict[str, Any], every, report: Verification) -> None:
    """A grounded call cites, for every record it relied on, the response the broker recorded."""
    grounding = decision["grounding"]
    if decision.get("outcome") == "allow" and decision.get("enforced") and not grounding.get("grounded"):
        report.problems.append(f"{where}: an ungrounded call was allowed in strict mode")
    if not grounding.get("grounded"):
        return
    for citation in grounding.get("citations") or []:
        ref = citation.get("event")
        if not isinstance(ref, dict):
            report.problems.append(f"{where}: grounded on {citation.get('binding')} with no record of reading it")
            continue
        cited = every.get((ref.get("run"), ref.get("seq")))
        if cited is None or cited.get("hash") != ref.get("hash"):
            report.problems.append(f"{where}: grounded on {citation.get('binding')}, whose read is not in the record")
        elif cited.get("kind") != "effect.outcome" or (cited.get("data") or {}).get("observed") != citation.get("observed"):
            report.problems.append(f"{where}: grounded on {citation.get('binding')}, which is not the response recorded")


def _check_decisions(run: str, events: List[Dict[str, Any]], report: Verification) -> None:
    """Every provider call left only after an allow decision, and every decision led where it said."""
    from jarviscore.contracts.hitl import APPROVED_DECISIONS

    approving = {decision.value for decision in APPROVED_DECISIONS}
    decisions: Dict[str, Dict[str, Any]] = {}
    approved: set = set()
    for event in events:
        data = event.get("data") or {}
        call = data.get("call_id")
        if event.get("kind") == "approval.decision" and data.get("decision") in approving:
            approved.add(data.get("binding"))
        elif event.get("kind") == "approval.claim":
            approved.add(data.get("binding"))
        if event.get("kind") == "policy.preview" and data.get("outcome") == "deny" and data.get("enforced"):
            report.refused_in_preview += 1
        if event.get("kind") == "policy.decision":
            decisions[call] = data
            if data.get("outcome") == "deny" and data.get("enforced"):
                report.refused += 1
            if data.get("approval") and data.get("outcome") == "allow" and data["approval"] not in approved:
                report.problems.append(
                    f"run {run} event {event['seq']}: a call carrying an approval with no "
                    "approval of that exact action before it"
                )
        elif event.get("kind") == "effect.attempt":
            report.effects += 1
            decision = decisions.get(call)
            if decision is None:
                report.problems.append(f"run {run} event {event['seq']}: a provider call with no decision before it")
            elif decision.get("outcome") == "deny" and decision.get("enforced"):
                report.problems.append(f"run {run} event {event['seq']}: a provider call that policy refused")
