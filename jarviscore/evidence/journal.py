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
    #: Not tampering, but worth knowing: records still being written, or an interrupted write.
    notes: List[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems

    def summary(self) -> str:
        state = "intact" if self.ok else f"{len(self.problems)} problem(s)"
        preview = f", {self.refused_in_preview} refused before approval" if self.refused_in_preview else ""
        return (
            f"{self.runs} run(s), {self.events} event(s), {self.effects} effect(s) "
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


def verify(root: str, export: bool = False) -> Verification:
    """Check every run under ``root`` against its own chain, the head log, and its decisions.

    ``export=True`` checks an export of one person's or tenant's runs
    (``evidence.people.export``): runs it left out are expected to be missing.
    """
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
            report.notes.append(
                f"run {run}: not yet in the head log (being written, an interrupted write, "
                "or added outside the journal)"
            )
        else:
            seq, hashed = registered
            at = next((e for e in events if e.get("seq") == seq), None)
            if at is None:
                report.problems.append(
                    f"run {run}: the head log registered event {seq}, the run ends at "
                    f"event {last['seq']} (cut short)"
                )
            elif at.get("hash") != hashed:
                report.problems.append(f"run {run}: event {seq} is not the one the head log registered (rewritten)")
            elif last["seq"] > seq:
                report.notes.append(
                    f"run {run}: {last['seq'] - seq} event(s) after its registered head "
                    "(being written, or an interrupted write)"
                )
        _check_decisions(run, events, report)
        for event in events:
            every[(run, event.get("seq"))] = event
            data = event.get("data") or {}
            if event.get("kind") == "policy.decision" and isinstance(data.get("grounding"), dict):
                groundings.append((f"run {run} event {event.get('seq')}", data))
    exported = _export_manifest(root) if export else None
    if not export and _export_manifest(root) is not None:
        report.problems.append(
            "export.json: this is an export of some runs, not a whole journal; "
            "check it as one (jarviscore verify --export)"
        )
    if export and exported is None:
        report.problems.append("export.json is missing: this is not an export")
    if exported is None:
        for run in sorted(set(heads) - seen):
            report.problems.append(f"run {run}: registered in the head log but its record is missing")
    else:
        # An export of one person's or tenant's runs: the rest were left out on purpose.
        for run in sorted(set(exported.get("runs") or []) - seen):
            report.problems.append(f"run {run}: listed in this export but its record is missing")
        left_out = len(set(heads) - seen - set(exported.get("runs") or []))
        report.notes.append(
            f"an export for {exported.get('for')}: {len(seen)} run(s), each checked against the "
            f"deployment's head log; {left_out} other run(s) in that log are not part of it"
        )
    for where, decision in groundings:
        _check_grounding(where, decision, every, report, partial=exported is not None)
    return report


def _export_manifest(root: str) -> Optional[Dict[str, Any]]:
    path = os.path.join(root, "export.json")
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as handle:
            manifest = json.load(handle)
    except (OSError, ValueError):
        return {"for": "(unreadable export.json)", "runs": []}
    return manifest if isinstance(manifest, dict) else {"for": "(unreadable export.json)", "runs": []}


def _check_grounding(where: str, decision: Dict[str, Any], every, report: Verification,
                     partial: bool = False) -> None:
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
        if cited is None and partial and not any(run == ref.get("run") for run, _ in every):
            report.notes.append(f"{where}: grounded on a read in run {ref.get('run')}, not part of this export")
            continue
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


# ── Content: what the chain's digests stand for ─────────────────────────────

CONTENT = "content"


def store_content(root: str, value: Any) -> str:
    """Keep ``value`` content-addressed beside the journal; return its digest.

    The hash-linked chain holds only digests, so content can be erased (a person's
    right to erasure, a retention limit) without breaking ``verify``; what it was
    can still be proven against the digest while it is kept.
    """
    key = digest(value)
    # Kept as it was (key order included), so a replay sees exactly what the agent saw;
    # the digest is over the canonical form, which reading it back checks.
    text = json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)
    path = os.path.join(root, CONTENT, key[:2], f"{key}.json")
    if os.path.exists(path):
        try:
            os.utime(path)  # used again: it is as recent as its newest use, for retention
        except OSError:
            pass
    else:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        temporary = f"{path}.{os.getpid()}.tmp"
        with open(temporary, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.replace(temporary, path)
    return key


def load_content(root: str, key: str) -> Any:
    """Content kept under ``key``, checked against it; KeyError when it is not kept."""
    path = os.path.join(root, CONTENT, str(key)[:2], f"{key}.json")
    if not os.path.exists(path):
        raise KeyError(key)
    with open(path, encoding="utf-8") as handle:
        value = json.loads(handle.read())
    if digest(value) != key:
        raise ValueError(f"content {key} does not match its digest")
    return value


def capture_mode() -> str:
    """What runs keep for replay: ``full`` (default), ``digests`` or ``off`` (JOURNAL_CAPTURE)."""
    import importlib

    settings = importlib.import_module("jarviscore.config.settings").settings
    value = os.environ.get("JARVISCORE_JOURNAL_CAPTURE") or getattr(settings, "journal_capture", None) or "full"
    value = str(value).lower()
    return value if value in ("full", "digests", "off") else "full"



def content_days() -> int:
    """Days replay content is kept after its last use (JOURNAL_CONTENT_DAYS; 0 keeps it)."""
    import importlib

    settings = importlib.import_module("jarviscore.config.settings").settings
    value = os.environ.get("JARVISCORE_JOURNAL_CONTENT_DAYS") or getattr(settings, "journal_content_days", 30)
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 30


def prune_content(root: str, days: int) -> int:
    """Erase replay content unused for ``days``; the chain, holding digests, stays verifiable."""
    import time as _time

    if days <= 0:
        return 0
    cutoff, removed = _time.time() - days * 86400, 0
    for folder, _, names in os.walk(os.path.join(root, CONTENT)):
        for name in names:
            path = os.path.join(folder, name)
            try:
                if os.path.getmtime(path) < cutoff:
                    os.remove(path)
                    removed += 1
            except OSError:
                continue
    return removed


_PRUNED: Dict[str, float] = {}


def prune_content_soon(root: str) -> None:
    """Prune ``root``'s replay content in the background, at most once a day per process."""
    import time as _time

    days = content_days()
    if days <= 0 or _time.time() - _PRUNED.get(root, 0.0) < 86400:
        return
    _PRUNED[root] = _time.time()

    def run():
        try:
            removed = prune_content(root, days)
            if removed:
                logger.info("Pruned %d replay content file(s) unused for %d days", removed, days)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Replay content not pruned: %s", exc)

    threading.Thread(target=run, name="jarviscore-journal-prune", daemon=True).start()
