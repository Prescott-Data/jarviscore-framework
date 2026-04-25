"""
WorkingScratchpad — Per-step JSONL working notes backed by BlobStorage.

The scratchpad is the Kernel's short-term notepad for a single step.
Each turn the Kernel writes a JSONL entry (thought, action, result).

Entries carry a `scope` field that controls their lifecycle:
  - scope="step"  (default) — ephemeral, relevant only to this step's
                               OODA loop. Discarded when the step completes.
  - scope="goal"            — durable, should survive into the next step's
                               context. Promoted into GoalExecution.truth
                               via promote_to_truth() at step completion.

After each step completes the scratchpad is readable in markdown for
inclusion in the next step's context (goal-scoped entries only).

Blob path: workflows/{wf_id}/scratchpads/{step_id}_{role}.md
           (role omitted when empty → {step_id}.md)

Read-append-write: BlobStorage has no streaming append, so each write
reads the existing blob, appends the new JSONL line, and saves back.
"""
import json
import logging
from typing import Any, Dict, List, Literal, Optional

logger = logging.getLogger(__name__)


class WorkingScratchpad:
    """
    Per-step JSONL working notes stored in BlobStorage.

    Scope lifecycle:
        scope="step"  (default): ephemeral notes for the current OODA loop only.
                                  Only used within this step — not propagated forward.
        scope="goal":             durable findings that should inform future steps.
                                  Promoted into GoalExecution.truth via promote_to_truth()
                                  when the step completes.

    Example — within a subagent tool loop:
        pad = WorkingScratchpad(blob_storage, "wf-1", "step2", "researcher")

        # Critical finding — must survive to next step
        await pad.write("finding",
            {"content": "API uses OAuth2. Token endpoint: /oauth/token"},
            scope="goal",
        )

        # Tactical noise — only relevant to this attempt
        await pad.write("attempt",
            {"content": "Tried GET /v1/data — 404, wrong endpoint"},
            scope="step",
        )

        # At step completion, promote goal-scoped entries to TruthContext:
        goal_exec.truth = await pad.promote_to_truth(goal_exec.truth, source="step2")
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

    async def write(
        self,
        entry_type: str,
        data: Dict[str, Any],
        scope: Literal["step", "goal"] = "step",
    ) -> None:
        """
        Append a JSONL entry to the scratchpad.

        Args:
            entry_type: Category label (e.g. "thought", "finding", "attempt")
            data:       Payload dict — must be JSON-serialisable
            scope:      "step" (default, ephemeral) or "goal" (durable, promoted
                        to TruthContext at step completion via promote_to_truth())
        """
        entry = {"type": entry_type, "scope": scope, **data}
        line = json.dumps(entry, ensure_ascii=False)

        existing = await self._blob.read(self._path) or ""
        if isinstance(existing, bytes):
            existing = existing.decode()

        updated = (existing + "\n" + line).lstrip("\n")
        await self._blob.save(self._path, updated)
        logger.debug("Scratchpad write [%s|%s] → %s", entry_type, scope, self._path)

    async def read_all(self) -> List[Dict[str, Any]]:
        """
        Read all entries from the scratchpad.

        Returns:
            List of entry dicts in chronological order (both scopes).
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
                logger.warning("Scratchpad: skipping malformed line in %s", self._path)
        return entries

    async def goal_scoped_entries(self) -> List[Dict[str, Any]]:
        """
        Return only scope="goal" entries — findings that should survive
        the step boundary and inform future steps.

        Used by promote_to_truth() and by the GoalExecution loop when
        injecting prior step context into the next step.
        """
        all_entries = await self.read_all()
        return [e for e in all_entries if e.get("scope") == "goal"]

    async def get_notes(self) -> str:
        """
        Return scope="goal" entries as a markdown-formatted string.

        Only goal-scoped entries are returned — tactical noise is excluded.
        Suitable for injection into the next step's LLM prompt as prior context.

        Returns:
            Markdown string, or empty string if no goal-scoped entries exist.
        """
        entries = await self.goal_scoped_entries()
        if not entries:
            return ""

        lines = [f"## Findings from prior step ({self._step})"]
        for entry in entries:
            entry_copy = dict(entry)
            entry_type = entry_copy.pop("type", "finding")
            entry_copy.pop("scope", None)
            summary = json.dumps(entry_copy, ensure_ascii=False)
            lines.append(f"- **{entry_type}**: {summary}")
        return "\n".join(lines)

    async def promote_to_truth(
        self,
        truth_context,
        source: str,
    ):
        """
        Promote all scope="goal" entries into a TruthContext.

        Called at step completion by the GoalExecution loop to carry
        durable findings forward into the shared goal knowledge store.

        Args:
            truth_context: GoalExecution.truth (TruthContext instance)
            source:        Identifier string (e.g. "step_01_research")

        Returns:
            The updated TruthContext (same instance, mutated).
        """
        entries = await self.goal_scoped_entries()
        if not entries:
            return truth_context

        try:
            from jarviscore.context.distillation import distill_output, merge_facts

            # Convert entries into a dict suitable for distill_output
            raw = {}
            for i, entry in enumerate(entries):
                ec = dict(entry)
                ec.pop("scope", None)
                entry_type = ec.pop("type", "finding")
                content = ec.get("content", json.dumps(ec, ensure_ascii=False))
                raw[f"{entry_type}_{i}"] = content

            new_facts = distill_output(raw_output=raw, source=source, confidence=0.75)
            merge_facts(truth_context, new_facts, source=source)
            logger.info(
                "Scratchpad promoted %d goal-scoped entries from %s into TruthContext",
                len(entries), source,
            )
        except Exception as exc:
            logger.warning(
                "Scratchpad.promote_to_truth failed (non-fatal): %s", exc
            )

        return truth_context
