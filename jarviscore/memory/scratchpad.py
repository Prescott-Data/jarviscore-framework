"""
WorkingScratchpad — Per-step JSONL working notes backed by BlobStorage.

The scratchpad is the Kernel's short-term notepad for a single step.
Each turn the Kernel writes a JSONL entry (thought, action, result).
After the step completes the scratchpad is readable in markdown for
inclusion in the next step's context.

Blob path: workflows/{wf_id}/scratchpads/{step_id}_{role}.md
           (role omitted when empty → {step_id}.md)

Read-append-write: BlobStorage has no streaming append, so each write
reads the existing blob, appends the new JSONL line, and saves back.
"""
import json
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class WorkingScratchpad:
    """
    Per-step JSONL working notes stored in BlobStorage.

    Used by the Kernel to persist turn-by-turn reasoning so the agent's
    thought process survives across async context switches and is available
    for inclusion in downstream step prompts.

    Example:
        pad = WorkingScratchpad(blob_storage, "wf-1", "step2", "analyst")
        await pad.write("thought", {"content": "I should query the API first"})
        await pad.write("action", {"tool": "http_get", "url": "..."})
        notes = await pad.get_notes()
    """

    def __init__(
        self,
        blob_storage,
        workflow_id: str,
        step_id: str,
        role: str = "",
    ):
        self._blob = blob_storage
        self._wf = workflow_id
        self._step = step_id
        self._role = role
        suffix = f"{step_id}_{role}" if role else step_id
        self._path = f"workflows/{workflow_id}/scratchpads/{suffix}.md"

    async def write(self, entry_type: str, data: Dict[str, Any]) -> None:
        """
        Append a JSONL entry to the scratchpad.

        Args:
            entry_type: Category label (e.g. "thought", "action", "result")
            data: Payload dict — must be JSON-serialisable
        """
        entry = {"type": entry_type, **data}
        line = json.dumps(entry, ensure_ascii=False)

        existing = await self._blob.read(self._path) or ""
        if isinstance(existing, bytes):
            existing = existing.decode()

        updated = (existing + "\n" + line).lstrip("\n")
        await self._blob.save(self._path, updated)
        logger.debug(f"Scratchpad write [{entry_type}] → {self._path}")

    async def read_all(self) -> List[Dict[str, Any]]:
        """
        Read all entries from the scratchpad.

        Returns:
            List of entry dicts in chronological order.
            Returns [] if scratchpad is empty or doesn't exist.
        """
        raw = await self._blob.read(self._path)
        if not raw:
            return []
        if isinstance(raw, bytes):
            raw = raw.decode()

        entries = []
        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                logger.warning(f"Scratchpad: skipping malformed line in {self._path}")
        return entries

    async def get_notes(self) -> str:
        """
        Return scratchpad contents as a markdown-formatted string.

        Suitable for inclusion in LLM prompts. Each entry becomes a
        bullet under its type heading.

        Returns:
            Markdown string, or empty string if scratchpad is empty.
        """
        entries = await self.read_all()
        if not entries:
            return ""

        lines = [f"## Working Notes ({self._step})"]
        for entry in entries:
            entry_type = entry.pop("type", "note")
            summary = json.dumps(entry, ensure_ascii=False)
            lines.append(f"- **{entry_type}**: {summary}")
        return "\n".join(lines)
