"""
LongTermMemory — Dual-store compressed workflow summaries.

Summaries are written to two tiers:
  1. Redis  (key: ltm:{workflow_id}) — hot path, 7-day TTL
  2. Blob   (path: workflows/{wf_id}/ltm/summary.txt) — durable, no expiry

Reads always try Redis first (fast). On cache miss, fall back to Blob
(crash-recovery path after Redis TTL expires).

The compress() method calls the LLM client to distill a list of episodic
entries into a compact summary. Token counts come from the LLM response —
no client-side tokeniser required.
"""
import json
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_COMPRESS_PROMPT = """\
You are summarising a workflow execution log. Condense the following
turn-by-turn entries into a compact summary that preserves:
- Key findings and decisions made
- Important errors and how they were resolved
- Final state / result of each meaningful action

Be concise. Omit redundant details. Write in past tense.

Entries:
{entries}
"""


class LongTermMemory:
    """
    Compressed workflow summaries stored in Redis + BlobStorage.

    Used by UnifiedMemory to persist cross-turn context that would
    otherwise be lost to LLM context-window limits.

    Example:
        ltm = LongTermMemory(redis_store, blob_storage, "wf-1")
        summary = await ltm.compress(recent_entries, llm_client)
        await ltm.save_summary(summary)
        restored = await ltm.load_summary()
    """

    def __init__(self, redis_store, blob_storage, workflow_id: str):
        self._redis = redis_store
        self._blob = blob_storage
        self._wf = workflow_id
        self._blob_path = f"workflows/{workflow_id}/ltm/summary.txt"

    async def save_summary(self, summary: str) -> None:
        """
        Save a compressed summary to both Redis (TTL) and Blob (durable).

        Args:
            summary: Compressed text summary of workflow execution so far.
        """
        # Redis — fast hot path (7-day TTL)
        self._redis.save_ltm(self._wf, summary)
        # Blob — durable backup (no expiry)
        await self._blob.save(self._blob_path, summary)
        logger.info(f"LTM saved for {self._wf} ({len(summary)} chars)")

    async def load_summary(self) -> Optional[str]:
        """
        Load the compressed summary. Redis first, Blob fallback.

        Returns:
            Summary string, or None if no summary exists yet.
        """
        # Try Redis first (fast)
        cached = self._redis.load_ltm(self._wf)
        if cached:
            logger.debug(f"LTM loaded from Redis for {self._wf}")
            return cached

        # Fall back to Blob (cold path — after crash or Redis expiry)
        raw = await self._blob.read(self._blob_path)
        if raw:
            summary = raw if isinstance(raw, str) else raw.decode()
            # Rehydrate Redis cache
            self._redis.save_ltm(self._wf, summary)
            logger.info(f"LTM rehydrated from Blob for {self._wf}")
            return summary

        return None

    async def compress(
        self,
        entries: List[Dict[str, Any]],
        llm_client,
        max_tokens: int = 2000,
    ) -> str:
        """
        Distil a list of episodic entries into a compact summary via LLM.

        Args:
            entries: List of episodic ledger dicts to summarise.
            llm_client: UnifiedLLMClient (has async generate() method).
            max_tokens: Output token limit for the summary.

        Returns:
            Compressed summary string.
        """
        if not entries:
            return ""

        formatted = "\n".join(
            json.dumps(e, ensure_ascii=False, default=str) for e in entries
        )
        prompt = _COMPRESS_PROMPT.format(entries=formatted)

        response = await llm_client.generate(
            prompt=prompt,
            temperature=0.3,
            max_tokens=max_tokens,
        )
        summary = response.get("content", "")
        logger.info(
            f"LTM compressed {len(entries)} entries → {len(summary)} chars "
            f"({response.get('tokens', {}).get('total', 0)} tokens)"
        )
        return summary
