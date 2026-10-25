"""What agents did for a person, or for everyone in a tenant, from the journal.

    account(root, "acme/u_1")         # each run done for that person
    account(root, "acme/")            # ... for anyone in tenant acme
    export(root, "acme/", "out/")     # those runs, which `jarviscore verify out/` checks

Whom a run was for is what the runtime recorded on it (``acting_for``, set by
``on_behalf_of`` / ``act_for``), never what an agent wrote. An export holds those
runs exactly as written and the head-log entries the deployment wrote for them
(no other run's name), so each run still shows it ends where the deployment
registered it; the manifest records the head log's last hash and length when
exported, for comparison with a checkpoint kept outside the deployment. It
cannot prove that no run for the person was left out: that needs the whole
journal, checked with ``verify``.
"""
from __future__ import annotations

import json
import os
import re
import shutil
from datetime import datetime, timezone
from typing import Any, Dict, Iterator, List, Optional, Set

from jarviscore.evidence.journal import CONTENT, HEADS, RUNS

#: Written into an export; ``verify`` reads it to know which runs were left out on purpose.
EXPORT = "export.json"
_DIGEST = re.compile(r"^[0-9a-f]{64}$")


def matches(person: Optional[str], who: str) -> bool:
    """``who`` is a person key (``acme/u_1``) or a whole tenant (``acme/``)."""
    if not person:
        return False
    return person.startswith(who) if who.endswith("/") else person == who


def _runs(root: str) -> Iterator[tuple]:
    folder = os.path.join(root, RUNS)
    for name in sorted(os.listdir(folder)) if os.path.isdir(folder) else []:
        if not name.endswith(".jsonl"):
            continue
        events = []
        with open(os.path.join(folder, name), encoding="utf-8") as handle:
            for line in handle:
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        if events:
            yield name, events


def _people(events: List[Dict[str, Any]]) -> Set[str]:
    return {str(p) for e in events if (p := (e.get("data") or {}).get("acting_for"))}


def _action(event: Dict[str, Any]) -> Dict[str, Any]:
    data = event.get("data") or {}
    return {
        "seq": event.get("seq"), "at": event.get("ts"),
        "sink": data.get("sink") or "provider",
        "action": data.get("action") or data.get("method"),
        "target": data.get("target") or f"{data.get('host', '')}{data.get('path', '')}",
        "outcome": data.get("outcome"), "rule": data.get("rule"), "enforced": data.get("enforced"),
        **({"reason": data["reason"]} if data.get("reason") else {}),
        **({"scopes": (data.get("scope") or {}).get("requirements") or []} if data.get("scope") else {}),
    }


def account(root: str, who: str) -> List[Dict[str, Any]]:
    """Each run done for ``who``: when, by which agent, every decision and how it ended.

    A run that also acted for someone ``who`` does not cover is listed with
    ``"shared": true`` (it is never exported).
    """
    who = str(who or "").strip()
    if not who:
        raise ValueError("account() needs a person key (acme/u_1) or a tenant (acme/)")
    found = []
    for _, events in _runs(root):
        people = _people(events)
        mine = {p for p in people if matches(p, who)}
        if not mine:
            continue
        start = next((e.get("data") or {} for e in events if e.get("kind") == "run.start"), {})
        end = next((e.get("data") or {} for e in reversed(events) if e.get("kind") == "run.end"), None)
        decisions = [_action(e) for e in events if e.get("kind") == "policy.decision"]
        found.append({
            "run": events[0].get("run"),
            "for": sorted(mine),
            "shared": bool(people - mine),
            "started": events[0].get("ts"), "last": events[-1].get("ts"),
            "agent": start.get("agent_id") or next((d.get("agent") for d in (e.get("data") or {} for e in events) if d.get("agent")), None),
            "decisions": decisions,
            "refused": sum(1 for d in decisions if d["outcome"] == "deny" and d["enforced"]),
            "effects": sum(1 for e in events if e.get("kind") == "effect.attempt"),
            "approvals": [
                {"seq": e.get("seq"), "at": e.get("ts"), "kind": e["kind"],
                 "decision": (e.get("data") or {}).get("decision"), "by": (e.get("data") or {}).get("by")}
                for e in events if str(e.get("kind", "")).startswith("approval.")
            ],
            "outcome": (end or {}).get("status"),
        })
    return sorted(found, key=lambda r: r["started"] or "")


def _digests(value: Any, into: Set[str]) -> None:
    if isinstance(value, str):
        if _DIGEST.match(value):
            into.add(value)
    elif isinstance(value, dict):
        for item in value.values():
            _digests(item, into)
    elif isinstance(value, list):
        for item in value:
            _digests(item, into)


def export(root: str, who: str, dest: str, content: bool = False) -> Dict[str, Any]:
    """Copy the runs done for ``who`` into ``dest``, verifiable on their own.

    Runs shared with anyone ``who`` does not cover are left out and listed.
    ``content=True`` also copies what replay needs (the task, model calls and
    tool results those runs kept), which is personal data: hand it over only
    where that is allowed.
    """
    runs = account(root, who)
    if os.path.exists(dest) and os.listdir(dest):
        raise FileExistsError(f"{dest} is not empty")
    os.makedirs(os.path.join(dest, RUNS), exist_ok=True)
    included, shared, copied = [], [], 0
    recorded = {events[0].get("run"): (name, events) for name, events in _runs(root)}
    for entry in runs:
        if entry["shared"]:
            shared.append(entry["run"])
            continue
        name, events = recorded[entry["run"]]
        shutil.copy2(os.path.join(root, RUNS, name), os.path.join(dest, RUNS, name))
        included.append(entry["run"])
        if not content:
            continue
        keys: Set[str] = set()
        for event in events:
            _digests(event.get("data"), keys)
        for key in sorted(keys):
            source = os.path.join(root, CONTENT, key[:2], f"{key}.json")
            target = os.path.join(dest, CONTENT, key[:2], f"{key}.json")
            if os.path.exists(source) and not os.path.exists(target):
                os.makedirs(os.path.dirname(target), exist_ok=True)
                shutil.copy2(source, target)
                copied += 1
    checkpoint = {"entries": 0, "last_hash": None}
    heads = os.path.join(root, HEADS)
    if os.path.exists(heads):
        # Only these runs' head entries: the deployment's other runs (and their names) stay out.
        wanted = set(included)
        with open(heads, encoding="utf-8") as source, open(os.path.join(dest, HEADS), "w", encoding="utf-8") as out:
            for line in source:
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                checkpoint = {"entries": checkpoint["entries"] + 1, "last_hash": entry.get("hash")}
                if entry.get("run") in wanted:
                    out.write(line if line.endswith("\n") else line + "\n")
    manifest = {
        "for": who, "runs": included, "left_out_shared": shared,
        # The deployment's head log when exported, to compare with a checkpoint anchored outside it.
        "head_log": checkpoint,
        "content": copied if content else None,
        "exported_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    with open(os.path.join(dest, EXPORT), "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=2)
    return manifest


def erase(root: str, who: str, dry_run: bool = False) -> Dict[str, int]:
    """Erase the replay content kept for ``who``'s runs (a person's right to erasure).

    The chain keeps only digests of that content, so it still verifies and still
    shows every decision (and still names the person); those runs just cannot be
    replayed any more. Content of a run that also worked for someone else, or
    that another person's run also used, is kept. ``dry_run`` counts without erasing.
    """
    who = str(who or "").strip()
    if not who:
        raise ValueError("erase() needs a person key (acme/u_1) or a tenant (acme/)")
    theirs: Set[str] = set()
    others: Set[str] = set()
    runs = 0
    for _, events in _runs(root):
        keys: Set[str] = set()
        for event in events:
            _digests(event.get("data"), keys)
        people = _people(events)
        if people and all(matches(p, who) for p in people):
            theirs |= keys
            runs += 1
        else:
            # A run that also worked for someone else is their record too: its content stays.
            others |= keys
    erased = 0
    for key in sorted(theirs - others):
        path = os.path.join(root, CONTENT, key[:2], f"{key}.json")
        if os.path.exists(path):
            erased += 1
            if not dry_run:
                os.remove(path)
    return {"runs": runs, "erased": erased, "kept_shared": len(theirs & others)}
