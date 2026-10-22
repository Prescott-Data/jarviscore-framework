"""
Local cross-session memory: what an agent chose to keep, on this machine.

The default tier behind ``remember`` and ``recall`` when Athena is not
configured. Facts are appended to one JSON-lines file per agent identity (and
tenant, when the Mesh separates tenants) under ``.jarviscore/memory/``, so a
fact kept in one run is there in the next, with no service to start.

Recall scores by the words a query shares with each fact. It is exact and
cheap, not semantic; Athena is the upgrade when that matters.
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from jarviscore.config.paths import runtime_path

logger = logging.getLogger(__name__)

_WORD = re.compile(r"[a-z0-9]+")
_STOP = frozenset(
    "a an and are as at be but by do does for from has have how i in is it its "
    "me my of on or our so than that the their them then there these they this "
    "to was we were what when where which who whom why will with you your".split()
)
_READ_LIMIT = 5000


def _words(text: str) -> set:
    return {w for w in _WORD.findall(text.lower()) if w not in _STOP and len(w) > 1}


def _safe(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", name).strip("._") or "agent"


class LocalMemory:
    """Facts an agent kept, in a file that outlives the process."""

    def __init__(self, identity: str, scope: Optional[str] = None, base_dir: Optional[str] = None):
        self.identity = identity
        self.scope = scope
        self.base_dir = base_dir or runtime_path("memory")
        name = _safe(identity) + (f"__{_safe(scope)}" if scope else "")
        self.path = os.path.join(self.base_dir, f"{name}.jsonl")

    def for_scope(self, scope: str) -> "LocalMemory":
        """The same agent's memory in another scope (a person's private memory)."""
        return LocalMemory(self.identity, scope=scope, base_dir=self.base_dir)

    @staticmethod
    def erase_scope(scope: str, base_dir: Optional[str] = None) -> int:
        """Delete every agent's memory kept in ``scope``. Returns the facts removed."""
        base = base_dir or runtime_path("memory")
        suffix = f"__{_safe(scope)}.jsonl"
        removed = 0
        try:
            names = os.listdir(base)
        except FileNotFoundError:
            return 0
        for name in names:
            if not name.endswith(suffix):
                continue
            path = os.path.join(base, name)
            try:
                with open(path, encoding="utf-8") as handle:
                    entries = [json.loads(line) for line in handle if line.strip()]
            except (FileNotFoundError, ValueError):
                continue
            # The file name is a sanitised scope; the facts name it exactly.
            if not entries or any(entry.get("scope") != scope for entry in entries):
                continue
            try:
                os.remove(path)
            except FileNotFoundError:
                continue
            removed += len(entries)
        return removed

    def _entries(self) -> List[Dict[str, Any]]:
        try:
            with open(self.path, encoding="utf-8") as handle:
                lines = handle.readlines()[-_READ_LIMIT:]
        except FileNotFoundError:
            return []
        entries = []
        for line in lines:
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            if isinstance(entry, dict) and entry.get("content"):
                entries.append(entry)
        return entries

    def remember(self, fact: str, kind: str = "fact", **metadata: Any) -> bool:
        fact = (fact or "").strip()
        if not fact:
            return False
        if any(entry["content"] == fact for entry in self._entries()):
            return True
        entry = {
            "content": fact,
            "kind": kind,
            "scope": self.scope or "",
            "metadata": {k: str(v) for k, v in metadata.items()},
            "kept_at": datetime.now(timezone.utc).isoformat(),
        }
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            with open(self.path, "a", encoding="utf-8") as handle:
                try:
                    import fcntl

                    fcntl.flock(handle, fcntl.LOCK_EX)
                except (ImportError, OSError):
                    pass
                handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
            return True
        except OSError as exc:
            logger.warning("[LocalMemory] could not keep a fact in %s: %s", self.path, exc)
            return False

    def recall(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        wanted = _words(query or "")
        if not wanted:
            return []
        scored = []
        for order, entry in enumerate(self._entries()):
            shared = wanted & _words(entry["content"])
            if shared:
                scored.append((len(shared) / len(wanted), order, entry))
        # Best match first; among equals, the most recently kept.
        scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
        return [
            {
                "content": entry["content"],
                "kind": entry.get("kind", "fact"),
                "kept_at": entry.get("kept_at"),
                "metadata": entry.get("metadata") or {},
                "score": round(score, 3),
                "source": "local",
            }
            for score, _, entry in scored[: max(1, limit)]
        ]
