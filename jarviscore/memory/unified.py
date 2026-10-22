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
from typing import Callable, Any, Dict, List, Optional

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

    # Defaults for an instance built without __init__ (tests, subclasses).
    _memory_tenant: Optional[str] = None
    _private_scope: Optional[str] = None
    _on_private_recall: Optional[Callable[[], None]] = None
    _team_agent: Optional[str] = None
    _private_memory = None
    _team_memory = None

    @staticmethod
    def _is_private() -> bool:
        return False

    def __init__(
        self,
        workflow_id: str,
        step_id: str,
        agent_id: str,
        redis_store=None,
        blob_storage=None,
        athena_client=None,   # Optional AthenaClient — enables 4th memory tier
        memory_scope: Optional[str] = None,
        memory_tenant: Optional[str] = None,
        private_scope: Optional[str] = None,
        is_private: Optional[Callable[[], bool]] = None,
        on_private_recall: Optional[Callable[[], None]] = None,
        team_agent: Optional[str] = None,
        memory_identity: Optional[str] = None,
        local_memory=None,    # Optional LocalMemory — cross-session tier without Athena
    ):
        self._wf = workflow_id
        self._step = step_id
        self._agent = agent_id
        # Cross-session memory belongs to who the agent is, not to this process:
        # agent_id carries a per-process suffix, so a fact kept under it was
        # never found again after a restart.
        self._identity = memory_identity or agent_id
        self.local = local_memory
        self._redis = redis_store
        self._memory_scope = memory_scope
        #: Athena tenant: the room's, for work in a room. Athena never mixes tenants.
        self._memory_tenant = memory_tenant
        #: Where what this work learns from someone's own access is kept: theirs alone.
        self._private_scope = private_scope
        if is_private is not None:
            self._is_private = is_private
        self._on_private_recall = on_private_recall
        #: The shared session the team's conversation and decisions are written to.
        self._team_agent = team_agent
        self._private_memory = None
        self._team_memory = None

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

        # ── Tier 4: Athena MemOS (optional) ──────────────────────────────────
        # AthenaMemory bridges this session to Athena's STM/MTM/LTM pipeline.
        # Created lazily via AthenaMemory.create() (async) the first time
        # get_athena_memory() is awaited. Stored after first creation.
        self._athena_client = athena_client              # the HTTP client
        self._athena_memory = None                       # AthenaMemory instance (set lazily)

        tiers = [
            "scratchpad" if self.working else None,
            "episodic" if self.episodic else None,
            "ltm" if self.ltm else None,
            "athena" if athena_client else None,
            "local" if (local_memory is not None and not athena_client) else None,
        ]
        active = [t for t in tiers if t]
        logger.info(
            f"UnifiedMemory initialised for {workflow_id}/{step_id} "
            f"(active tiers: {active or ['none']}, scope: {memory_scope or agent_id})"
        )

    async def _get_athena_memory(self):
        """Lazy init: create AthenaMemory on first access. Thread-safe for async."""
        if self._athena_memory is not None:
            return self._athena_memory
        if self._athena_client is None:
            return None
        try:
            from .athena_memory import AthenaMemory
            self._athena_memory = await AthenaMemory.create(
                agent_id=getattr(self, "_identity", None) or self._agent,
                client=self._athena_client,
                redis_store=self._redis,
                user_id=self._memory_scope,
                tenant_id=self._memory_tenant,
            )
        except Exception as exc:
            # Athena restarting is a condition to recover from, not a reason to
            # disable the tier for the life of the process. The client's breaker
            # keeps the retry cheap while it is down (#128).
            logger.warning("[UnifiedMemory] Athena init failed (non-fatal): %s", exc)
        return self._athena_memory

    def _note_private_scope(self) -> bool:
        """Record a person's private scope in the room before anything is kept in it,
        so erasing the room always finds it. False when it could not be recorded."""
        record = getattr(self._redis, "record_room_memory_scope", None)
        if record is None or not self._memory_scope:
            return True
        try:
            record(self._memory_scope, self._private_scope)
            return True
        except Exception as exc:
            logger.warning("[UnifiedMemory] private memory off: could not note scope %s: %s",
                           self._private_scope, exc)
            return False

    async def _session(self, attr: str, user_id: Optional[str], agent_id: str):
        """Another Athena session in this step's tenant (the person's private memory,
        the team's), created on first use."""
        if getattr(self, attr) is not None or self._athena_client is None or not user_id:
            return getattr(self, attr)
        if attr == "_private_memory" and self._memory_scope:
            record = getattr(self._redis, "record_room_memory_scope", None)
            if record is not None:
                try:
                    # Before anything is written, so erasing the room always finds it.
                    record(self._memory_scope, user_id)
                except Exception as exc:
                    # Write nothing private that the room could not later erase.
                    logger.warning("[UnifiedMemory] private memory off: could not note scope %s: %s", user_id, exc)
                    return None
        try:
            from .athena_memory import AthenaMemory

            setattr(self, attr, await AthenaMemory.create(
                agent_id=agent_id, client=self._athena_client, redis_store=self._redis,
                user_id=user_id, tenant_id=self._memory_tenant))
        except Exception as exc:
            logger.warning("[UnifiedMemory] Athena session for %s failed (non-fatal): %s", user_id, exc)
        return getattr(self, attr)

    @property
    def athena_delivery_stats(self) -> Optional[Dict[str, Any]]:
        """Delivery counters for the Athena tier, or None when it is not active."""
        if self._athena_memory is None:
            return None
        return self._athena_memory.delivery_stats

    async def close(self, timeout: float = 5.0) -> bool:
        """Flush queued memory writes. False if anything was still unsent."""
        closed = True
        for am in (self._athena_memory, self._private_memory, self._team_memory):
            if am is not None:
                closed = await am.close(timeout=timeout) and closed
        return closed


    async def log_turn(
        self,
        turn_id: str,
        thought: str,
        action: str,
        result: str,
        tokens: int = 0,
    ) -> None:
        """
        Record a single OODA loop turn to all active memory tiers.

        Tiers written (when available):
          - WorkingScratchpad (blob) — working notes for this step
          - EpisodicLedger (Redis Stream) — full chronological history

        Athena is not written: a turn is not a memory. ``remember()`` is how
        something reaches cross-session memory.

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

        # Athena is cross-session memory, and a turn is not a memory. Writing
        # every intermediate thought there made a mid-run diagnosis of a bug
        # ("Drive calls are blocked") outlive the bug and return as a premise the
        # next day. Turns stay in the scratchpad and ledger for recovery within a
        # session; Athena receives outcomes and what the agent chose to remember.

    async def remember(self, fact: str, kind: str = "fact", **metadata: str) -> bool:
        """Keep something the agent decided is worth knowing next time.

        The agent is the memory lifecycle: it chooses what deserves to persist.
        Returns False when no cross-session tier is available, so the caller can
        say so instead of believing something was kept.
        """
        local = getattr(self, "local", None)
        if local is not None and getattr(self, "_athena_client", None) is None:
            if self._private_scope and self._is_private():
                # Learned through someone's own access: theirs alone, as in Athena.
                if not self._note_private_scope():
                    return False
                return local.for_scope(self._private_scope).remember(
                    fact, kind=kind, **{**metadata, "private": "true"})
            return local.remember(fact, kind=kind, **metadata)
        am = await self._get_athena_memory()
        if am and self._private_scope and self._is_private():
            # This work used someone's own access: what it learned is theirs, never
            # the shared scope's, where everyone else's work would recall it.
            am = await self._session("_private_memory", self._private_scope, self._identity)
            metadata = {**metadata, "private": "true"}
        if not am:
            return False
        try:
            dropped = am.delivery_stats.get("dropped", 0)
            await am.record_observation(
                fact, metadata={"event": "remembered", "kind": kind, **metadata}
            )
            # Kept means delivered: a queued write dies with the process that queued it.
            delivered = await am.flush(timeout=10.0)
            return delivered and am.delivery_stats.get("dropped", 0) == dropped
        except Exception as exc:
            logger.debug("[UnifiedMemory] remember failed (non-fatal): %s", exc)
            return False

    async def recall(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        """What earlier sessions hold that bears on this, scored by relevance.

        A question, not a dump: the last N things the agent thought about
        anything are not what it needs to know about this.
        """
        local = getattr(self, "local", None)
        if local is not None and getattr(self, "_athena_client", None) is None:
            found = local.recall(query, limit=limit)
            if self._private_scope and self._on_private_recall is not None:
                private = local.for_scope(self._private_scope).recall(query, limit=limit)
                if private:
                    # Work that draws on someone's private memory is private work.
                    self._on_private_recall()
                    found.extend({**item, "private": True} for item in private)
            return found
        am = await self._get_athena_memory()
        if not am:
            return []
        try:
            # Search covers every agent's consolidated memory in this scope, the
            # team's conversation and decisions included.
            found = [item for item in await am.search(query, limit=limit) if isinstance(item, dict)][:limit]
            recent = (await am.get_memory_context(limit=50)).get("stm_events") or []
        except Exception as exc:
            logger.debug("[UnifiedMemory] recall failed (non-fatal): %s", exc)
            return []
        if self._team_agent:
            team = await self._session("_team_memory", self._memory_scope, self._team_agent)
            if team is not None:
                try:
                    # What the team said and decided lately, before Athena consolidates it.
                    for event in ((await team.get_memory_context(limit=20)).get("stm_events") or [])[:20]:
                        if isinstance(event, dict) and event.get("content"):
                            found.append({**event, "source": "team"})
                except Exception as exc:
                    logger.debug("[UnifiedMemory] team recall failed (non-fatal): %s", exc)
        if self._private_scope and self._on_private_recall is not None:
            mine = await self._session("_private_memory", self._private_scope, self._identity)
            if mine is not None:
                try:
                    private = await mine.search(query, limit=limit)
                    private += [e for e in ((await mine.get_memory_context(limit=50)).get("stm_events") or [])
                                if isinstance(e, dict) and (e.get("metadata") or {}).get("event") == "remembered"]
                except Exception as exc:
                    logger.debug("[UnifiedMemory] private recall failed (non-fatal): %s", exc)
                    private = []
                if private:
                    # Work that draws on someone's private memory is private work.
                    self._on_private_recall()
                    found.extend({**item, "private": True} for item in private if isinstance(item, dict))
        # Search covers consolidated memory only; a fact the agent kept stays
        # short-term until Athena consolidates it, and must still be recallable.
        # It is not a relevance match, so it is labelled, and the search and these
        # together stay within the limit. Team and private sources are added above.
        seen = {str(item.get("content")) for item in found if isinstance(item, dict)}
        searched = sum(1 for item in found if "source" not in item and "private" not in item)
        for event in recent:
            if searched >= limit:
                break
            if not isinstance(event, dict):
                continue
            if (event.get("metadata") or {}).get("event") != "remembered":
                continue
            content = str(event.get("content") or "")
            if content and content not in seen:
                seen.add(content)
                found.append({**event, "match": "kept recently, not yet searchable"})
                searched += 1
        return found


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
          ltm_summary    — compressed long-term summary (str or None)
          recent_turns   — last N episodic entries (list)
          checkpoint     — last saved Kernel state JSON (str or None)
          scratchpad     — current working notes in markdown (str or "")
          athena_context — STM events + MTM chains from Athena (dict or None)

        Args:
            ledger_tail: How many recent episodic entries to include.
        """
        bundle: Dict[str, Any] = {
            "ltm_summary": None,
            "recent_turns": [],
            "checkpoint": None,
            "scratchpad": "",
            "athena_context": None,
        }

        if self.ltm:
            bundle["ltm_summary"] = await self.ltm.load_summary()

        if self.episodic:
            bundle["recent_turns"] = await self.episodic.tail(ledger_tail)

        bundle["checkpoint"] = await self.load_checkpoint()

        if self.working:
            bundle["scratchpad"] = await self.working.get_notes()

        # ── Tier 4: Athena context pull ───────────────────────────────────────
        am = await self._get_athena_memory()
        if am:
            try:
                bundle["athena_context"] = await am.get_memory_context(limit=15)
            except Exception as exc:
                logger.debug("[UnifiedMemory] Athena rehydrate failed (non-fatal): %s", exc)

        logger.info(
            f"Rehydrated bundle for {self._wf}/{self._step}: "
            f"ltm={'yes' if bundle['ltm_summary'] else 'no'}, "
            f"turns={len(bundle['recent_turns'])}, "
            f"checkpoint={'yes' if bundle['checkpoint'] else 'no'}, "
            f"athena={'yes' if bundle['athena_context'] else 'no'}"
        )
        return bundle
