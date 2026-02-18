"""
EpisodicLedger — Chronological event log backed by Redis Streams.

Every meaningful event in a workflow step (turn start, tool call, result,
error) is appended here via Redis XADD. The stream preserves insertion
order with auto-incrementing IDs, making it a reliable audit trail.

Redis key: ledgers:{workflow_id}
TTL: managed by RedisContextStore (default 7 days)

Delegates entirely to RedisContextStore methods:
  append  → append_ledger_entry(workflow_id, entry)
  tail    → get_ledger_tail(workflow_id, count)
  full    → get_ledger_full(workflow_id)   [Phase 8 addition]
"""
import logging
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


class EpisodicLedger:
    """
    Chronological workflow event log via Redis Streams.

    Provides an append-only ledger of agent reasoning steps. Used by
    UnifiedMemory.log_turn() and by LongTermMemory.compress() to build
    summaries from recent history.

    Example:
        ledger = EpisodicLedger(redis_store, "wf-1")
        entry_id = await ledger.append({"turn": 1, "thought": "..."})
        recent = await ledger.tail(5)
        history = await ledger.full_history()
    """

    def __init__(self, redis_store, workflow_id: str):
        self._redis = redis_store
        self._wf = workflow_id

    async def append(self, entry: Dict[str, Any]) -> str:
        """
        Append an entry to the ledger.

        Args:
            entry: Dict of string-serialisable values. All values are
                   JSON-encoded by RedisContextStore before XADD.

        Returns:
            Redis Stream entry ID (e.g. "1700000000000-0")
        """
        entry_id = self._redis.append_ledger_entry(self._wf, entry)
        logger.debug(f"Ledger append → {self._wf}:{entry_id}")
        return entry_id

    async def tail(self, count: int = 10) -> List[Dict[str, Any]]:
        """
        Read the most recent N entries in chronological order.

        Args:
            count: Maximum number of entries to return (default 10)

        Returns:
            List of entry dicts, oldest first.
        """
        return self._redis.get_ledger_tail(self._wf, count)

    async def full_history(self) -> List[Dict[str, Any]]:
        """
        Read all entries in chronological order (XRANGE *).

        Use sparingly on long-running workflows — prefer tail() for
        context-window inclusion and reserve full_history() for
        compression / audit.

        Returns:
            Complete list of entry dicts, oldest first.
        """
        return self._redis.get_ledger_full(self._wf)
