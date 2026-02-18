"""
UnifiedMemory — Single entry point composing all three memory tiers.

Provides the Kernel with one object to interact with across OODA loop
turns. Each tier is optional — the class degrades gracefully when either
redis_store or blob_storage is absent.

Tier availability:
  blob_storage present  → working scratchpad enabled
  redis_store present   → episodic ledger + LTM + checkpoints enabled
  both present          → all tiers active
  neither               → all writes are no-ops (pure in-memory run)
"""
import logging
import time
from typing import Any, Dict, Optional

from .scratchpad import WorkingScratchpad
from .episodic import EpisodicLedger
from .ltm import LongTermMemory

logger = logging.getLogger(__name__)


class UnifiedMemory:
    """
    Composes WorkingScratchpad, EpisodicLedger, and LongTermMemory.

    Used by the Kernel to record reasoning, persist checkpoints, and
    rehydrate context after a crash or cold-start.

    Example:
        mem = UnifiedMemory(
            workflow_id="wf-1",
            step_id="step2",
            agent_id="analyst",
            redis_store=redis_store,
            blob_storage=blob_storage,
        )
        await mem.log_turn("t1", thought="Analysing data", action="http_get", result="200 OK")
        await mem.save_checkpoint(json.dumps(kernel_state))
        bundle = await mem.rehydrate_bundle()
    """

    def __init__(
        self,
        workflow_id: str,
        step_id: str,
        agent_id: str,
        redis_store=None,
        blob_storage=None,
    ):
        self._wf = workflow_id
        self._step = step_id
        self._agent = agent_id
        self._redis = redis_store

        self.working: Optional[WorkingScratchpad] = (
            WorkingScratchpad(blob_storage, workflow_id, step_id, agent_id)
            if blob_storage else None
        )
        self.episodic: Optional[EpisodicLedger] = (
            EpisodicLedger(redis_store, workflow_id)
            if redis_store else None
        )
        self.ltm: Optional[LongTermMemory] = (
            LongTermMemory(redis_store, blob_storage, workflow_id)
            if (redis_store and blob_storage) else None
        )

        tiers = [
            "scratchpad" if self.working else None,
            "episodic" if self.episodic else None,
            "ltm" if self.ltm else None,
        ]
        active = [t for t in tiers if t]
        logger.info(
            f"UnifiedMemory initialised for {workflow_id}/{step_id} "
            f"(active tiers: {active or ['none']})"
        )

    async def log_turn(
        self,
        turn_id: str,
        thought: str,
        action: str,
        result: str,
        tokens: int = 0,
    ) -> None:
        """
        Record a single OODA loop turn to scratchpad + episodic ledger.

        Args:
            turn_id: Unique identifier for this turn (e.g. "t1", "t2")
            thought: Kernel's reasoning / orientation text
            action: Action taken (tool name, subagent call, etc.)
            result: Outcome / observation from the action
            tokens: Token count used this turn (for budget tracking)
        """
        entry = {
            "turn_id": turn_id,
            "ts": time.time(),
            "thought": thought,
            "action": action,
            "result": result,
            "tokens": tokens,
        }

        if self.working:
            await self.working.write("turn", entry)

        if self.episodic:
            await self.episodic.append(entry)

    async def save_checkpoint(self, state_json: str) -> None:
        """
        Save the Kernel's state snapshot to Redis for crash recovery.

        Args:
            state_json: JSON-serialised Kernel state string.
        """
        if self._redis:
            self._redis.save_checkpoint(self._wf, self._step, state_json)
            logger.debug(f"Checkpoint saved: {self._wf}/{self._step}")

    async def load_checkpoint(self) -> Optional[str]:
        """
        Load the most recent Kernel checkpoint.

        Returns:
            JSON state string, or None if no checkpoint exists.
        """
        if self._redis:
            return self._redis.load_checkpoint(self._wf, self._step)
        return None

    async def rehydrate_bundle(self, ledger_tail: int = 10) -> Dict[str, Any]:
        """
        Assemble a context bundle for Kernel cold-start / crash recovery.

        Returns a dict containing:
          ltm_summary   — compressed long-term summary (str or None)
          recent_turns  — last N episodic entries (list)
          checkpoint    — last saved Kernel state JSON (str or None)
          scratchpad    — current working notes in markdown (str or "")

        Args:
            ledger_tail: How many recent episodic entries to include.

        Returns:
            Dict with keys: ltm_summary, recent_turns, checkpoint, scratchpad
        """
        bundle: Dict[str, Any] = {
            "ltm_summary": None,
            "recent_turns": [],
            "checkpoint": None,
            "scratchpad": "",
        }

        if self.ltm:
            bundle["ltm_summary"] = await self.ltm.load_summary()

        if self.episodic:
            bundle["recent_turns"] = await self.episodic.tail(ledger_tail)

        bundle["checkpoint"] = await self.load_checkpoint()

        if self.working:
            bundle["scratchpad"] = await self.working.get_notes()

        logger.info(
            f"Rehydrated bundle for {self._wf}/{self._step}: "
            f"ltm={'yes' if bundle['ltm_summary'] else 'no'}, "
            f"turns={len(bundle['recent_turns'])}, "
            f"checkpoint={'yes' if bundle['checkpoint'] else 'no'}"
        )
        return bundle
