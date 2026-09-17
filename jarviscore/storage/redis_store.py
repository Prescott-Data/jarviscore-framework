"""
Redis Context Store for JarvisCore v1.0.1.

Provides durable state for: step outputs, shared context/truth, mailbox,
workflow DAG, episodic ledger, checkpoints, trace events, and HITL requests.
"""

import json
import logging
import os
import time
from typing import Any, Dict, List, Optional, cast
from uuid import uuid4

import redis

from jarviscore.contracts.hitl import (
    HITLRequest,
    HITLResolution,
    HITLStatus,
    normalize_hitl_decision,
)
from jarviscore.orchestration.envelopes import (
    CapabilityMandate,
    ExecutionBudget,
    WorkflowEvidence,
    WorkflowEnvelope,
    neutral_context,
    terminal_step_status,
)

logger = logging.getLogger(__name__)


class RedisContextStore:
    """
    Redis-backed context store for workflow state, truth, mailbox, and more.

    All keys are prefixed with workflow_id or agent_id for isolation.
    TTL is applied to prevent unbounded growth.
    """

    def __init__(self, settings=None, client: Optional[redis.Redis] = None):
        """
        Initialize Redis context store.

        Args:
            settings: Settings instance with redis_* fields
            client: Pre-built Redis client (for testing with fakeredis)
        """
        self._redis: Any
        if client is not None:
            self._redis = cast(Any, client)
        elif settings is not None:
            url = getattr(settings, "redis_url", None)
            if url:
                self._redis = cast(Any, redis.Redis.from_url(url, decode_responses=True))
            else:
                self._redis = cast(Any, redis.Redis(
                    host=getattr(settings, "redis_host", "localhost"),
                    port=getattr(settings, "redis_port", 6379),
                    password=getattr(settings, "redis_password", None),
                    db=getattr(settings, "redis_db", 0),
                    decode_responses=True,
                ))
        else:
            self._redis = cast(Any, redis.Redis(
                host="localhost", port=6379, db=0, decode_responses=True
            ))

        self._ttl_seconds = getattr(settings, "redis_context_ttl_days", 7) * 86400
        self.enabled = True

        try:
            self._redis.ping()
            logger.info("RedisContextStore connected")
        except redis.ConnectionError as e:
            logger.warning(f"Redis connection failed: {e}")
            self.enabled = False

    def get_atom_execution(self, action_id: str) -> Optional[Dict[str, Any]]:
        """Return the first successful result for a destructive action identity."""
        if not self.enabled:
            return None
        raw = self._redis.get(f"atom_execution:{action_id}")
        return json.loads(raw) if raw else None

    def save_atom_execution(self, action_id: str, result: Dict[str, Any]) -> None:
        """Persist success so retries cannot repeat an irreversible action."""
        if self.enabled:
            self._redis.set(
                f"atom_execution:{action_id}", json.dumps(result, default=str),
                ex=self._ttl_seconds,
            )

    # ------------------------------------------------------------------
    # Step Outputs
    # ------------------------------------------------------------------

    # Env-tunable size caps (bytes of serialised JSON).
    # Outputs above STEP_OUTPUT_MAX_BYTES are stored as a truncated preview
    # with an _overflow flag so downstream steps know to retrieve the full
    # result from blob storage rather than expect it inline.
    _STEP_OUTPUT_MAX_BYTES: int = int(
        os.getenv("STEP_OUTPUT_MAX_BYTES", str(200_000))
    )  # 200 KB default
    _STEP_OUTPUT_PREVIEW_BYTES: int = int(
        os.getenv("STEP_OUTPUT_PREVIEW_BYTES", str(20_000))
    )  # 20 KB preview

    def save_step_output(self, workflow_id: str, step_id: str,
                         output: Any = None, summary: Optional[str] = None,
                         context_vars: Optional[Dict] = None) -> bool:
        """
        Save step result to Redis.

        Idempotent write guard: if a successful result already exists for this
        step, a subsequent call carrying an error payload (e.g. from a stalled
        re-execution) will not overwrite it. This prevents the last-write-wins
        race condition that poisons downstream context with stale error data.

        Payload size guard: outputs larger than STEP_OUTPUT_MAX_BYTES are
        stored as a truncated preview with an _overflow marker. The full
        payload should be written to blob storage by the caller; downstream
        steps receive the preview in their context window and can retrieve the
        full artifact via blob storage if they need the complete data.
        """
        key = f"step_output:{workflow_id}:{step_id}"

        # ── Idempotent write guard ────────────────────────────────────────────
        # Protect a valid prior result from being overwritten by an error payload
        # produced by a retry or crash-resumed execution.
        existing_raw = self._redis.hget(key, "output")
        if existing_raw:
            try:
                existing_output = json.loads(existing_raw)
                existing_ok = (
                    (isinstance(existing_output, dict) and existing_output.get("success") is True)
                    or (isinstance(existing_output, list) and len(existing_output) > 0)
                )
                new_is_error = False
                if isinstance(output, dict):
                    new_is_error = (
                        output.get("success") is False
                        or "CONVERGENCE_STALL" in str(output.get("error", ""))
                        or "CONVERGENCE_STALL" in str(output.get("status", ""))
                    )
                elif isinstance(output, str) and "CONVERGENCE_STALL" in output:
                    new_is_error = True
                if existing_ok and new_is_error:
                    logger.warning(
                        "[IDEMPOTENT GUARD] Blocked overwrite of valid output for "
                        "%s:%s by erroneous re-execution payload.",
                        workflow_id, step_id,
                    )
                    return True
            except Exception as exc:
                logger.warning(
                    "Could not inspect existing step output for %s:%s before overwrite guard: %s",
                    workflow_id,
                    step_id,
                    exc,
                )

        # ── Payload size guard ───────────────────────────────────────────────
        # Serialise first so we know the exact byte cost before pushing to Redis.
        try:
            output_serialised = json.dumps(output) if output is not None else None
        except Exception:
            output_serialised = str(output)

        output_to_store = output_serialised
        if output_serialised and len(output_serialised) > self._STEP_OUTPUT_MAX_BYTES:
            preview = output_serialised[: self._STEP_OUTPUT_PREVIEW_BYTES]
            output_to_store = json.dumps({
                "_overflow": True,
                "_size_bytes": len(output_serialised),
                "_preview": preview,
                "_note": (
                    "Output exceeded STEP_OUTPUT_MAX_BYTES. "
                    "Retrieve full result from blob storage using "
                    f"workflow_id={workflow_id}, step_id={step_id}."
                ),
            })
            logger.warning(
                "Step output for %s:%s exceeds %d bytes (%d bytes). "
                "Storing preview only — write full output to blob storage.",
                workflow_id, step_id,
                self._STEP_OUTPUT_MAX_BYTES, len(output_serialised),
            )

        data = {
            "output": output_to_store,
            "summary": summary or "",
            "context_vars": json.dumps(context_vars or {}),
            "timestamp": time.time(),
        }
        self._redis.hset(key, mapping={k: v for k, v in data.items() if v is not None})
        self._redis.expire(key, self._ttl_seconds)
        return True

    def get_step_output(self, workflow_id: str,
                        step_id: str) -> Optional[Dict]:
        """Read step result from Redis."""
        key = f"step_output:{workflow_id}:{step_id}"
        data = self._redis.hgetall(key)
        if not data:
            return None
        result = dict(data)
        if "output" in result:
            try:
                result["output"] = json.loads(result["output"])
            except (json.JSONDecodeError, TypeError):
                pass
        if "context_vars" in result:
            try:
                result["context_vars"] = json.loads(result["context_vars"])
            except (json.JSONDecodeError, TypeError):
                pass
        return result

    def list_step_output_ids(self, workflow_id: str) -> List[str]:
        """Return all step IDs that have saved outputs for this workflow.

        Uses SCAN (non-blocking) to find keys matching
        step_output:{workflow_id}:*  and strips the prefix to return
        just the step_id portion.
        """
        prefix = f"step_output:{workflow_id}:"
        return [
            k[len(prefix):]
            for k in self._redis.scan_iter(match=f"{prefix}*")
        ]

    # ------------------------------------------------------------------
    # Shared Context / Truth
    # ------------------------------------------------------------------

    def merge_shared_context(self, workflow_id: str, updates: Dict,
                             source: str = "") -> bool:
        """Merge key-value updates into workflow shared context."""
        key = f"shared_context:{workflow_id}"
        flat = {}
        for k, v in updates.items():
            flat[k] = json.dumps(v) if not isinstance(v, str) else v
        if flat:
            self._redis.hset(key, mapping=flat)
            self._redis.expire(key, self._ttl_seconds)
        if source:
            self._redis.hset(f"{key}:sources", mapping={source: json.dumps(list(updates.keys()))})
        return True

    def merge_shared_facts(self, workflow_id: str, facts: Dict,
                           source: str = "") -> bool:
        """Merge typed TruthFacts into shared context."""
        key = f"shared_facts:{workflow_id}"
        for fact_key, fact_value in facts.items():
            serialized = json.dumps(fact_value) if not isinstance(fact_value, str) else fact_value
            self._redis.hset(key, mapping={fact_key: serialized})
        self._redis.expire(key, self._ttl_seconds)
        if source:
            meta_key = f"{key}:sources"
            self._redis.hset(meta_key, mapping={source: json.dumps(list(facts.keys()))})
            self._redis.expire(meta_key, self._ttl_seconds)
        return True

    def get_shared_context(self, workflow_id: str) -> Dict:
        """Read canonical shared context."""
        key = f"shared_context:{workflow_id}"
        data = self._redis.hgetall(key)
        result = {}
        for k, v in data.items():
            try:
                result[k] = json.loads(v)
            except (json.JSONDecodeError, TypeError):
                result[k] = v
        return result

    def get_shared_facts(self, workflow_id: str) -> Dict:
        """Read shared facts (TruthContext data)."""
        key = f"shared_facts:{workflow_id}"
        data = self._redis.hgetall(key)
        result = {}
        for k, v in data.items():
            try:
                result[k] = json.loads(v)
            except (json.JSONDecodeError, TypeError):
                result[k] = v
        return result

    def get_shared_facts_flat(self, workflow_id: str) -> Dict[str, Any]:
        """Flattened key→value view of shared facts (strips metadata)."""
        facts = self.get_shared_facts(workflow_id)
        flat = {}
        for k, v in facts.items():
            if isinstance(v, dict) and "value" in v:
                flat[k] = v["value"]
            else:
                flat[k] = v
        return flat

    # ------------------------------------------------------------------
    # Mailbox
    # ------------------------------------------------------------------

    def send_mailbox_message(self, target_id: str, message: Dict) -> bool:
        """
        Send a durable message to an agent's mailbox.

        Schema (flat — single JSON object per Redis List entry):
            {
                "sender":      "<agent_id>",
                "message":     { ... },          # the actual payload
                "timestamp":   <float>,          # arrival epoch, set here if absent
                "workflow_id": "...",            # optional
                "step_id":     "...",            # optional
            }

        The envelope is stored flat — no outer wrapper.  MailboxManager._flatten()
        and the dashboard _unwrap_mailbox_entry() both expect this flat schema.
        """
        key = f"mailbox:{target_id}"
        # Stamp arrival time at the storage layer if the caller didn't.
        if "timestamp" not in message:
            message = {**message, "timestamp": time.time()}
        self._redis.rpush(key, json.dumps(message))
        self._redis.expire(key, self._ttl_seconds)
        return True

    def read_mailbox(self, agent_id: str,
                     max_messages: int = 10) -> List[Dict]:
        """
        Drain messages from agent's mailbox (destructive, FIFO).

        Returns a list of flat envelope dicts — no outer wrapper.
        """
        key = f"mailbox:{agent_id}"
        messages = []
        for _ in range(max_messages):
            raw = self._redis.lpop(key)
            if raw is None:
                break
            try:
                messages.append(json.loads(raw))
            except (json.JSONDecodeError, TypeError):
                logger.warning(f"Malformed mailbox message for {agent_id}")
        return messages

    def peek_mailbox(self, agent_id: str, limit: int = 10) -> List[Dict]:
        """
        Non-destructive peek at agent's mailbox.

        Returns a list of flat envelope dicts — messages remain in queue.
        """
        key = f"mailbox:{agent_id}"
        raw_list = self._redis.lrange(key, 0, limit - 1)
        messages = []
        for raw in raw_list:
            try:
                messages.append(json.loads(raw))
            except (json.JSONDecodeError, TypeError):
                pass
        return messages

    # ------------------------------------------------------------------
    # Capability needs
    # ------------------------------------------------------------------

    def publish_capability_need(
        self,
        workflow_id: str,
        *,
        requester_agent_id: str,
        requester_step_id: str,
        capability: str,
        question: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Publish a durable peer-resolvable gap without assigning an owner."""
        need_id = f"need-{uuid4().hex}"
        now = time.time()
        record = CapabilityMandate.open(
            mandate_id=need_id,
            workflow_id=workflow_id,
            requester_agent_id=requester_agent_id,
            requester_step_id=requester_step_id,
            capability=capability,
            question=question,
            context=context,
            now=now,
        ).to_record()
        needs_key = f"capability_needs:{workflow_id}"
        pipe = self._redis.pipeline(transaction=True)
        pipe.hset(needs_key, mapping={need_id: json.dumps(record, default=str)})
        pipe.expire(needs_key, self._ttl_seconds)
        pipe.sadd("jarviscore:workflows_with_capability_needs", workflow_id)
        pipe.expire("jarviscore:workflows_with_capability_needs", self._ttl_seconds)
        pipe.xadd(f"ledgers:{workflow_id}", {
            "event": "capability_need_published",
            "need_id": need_id,
            "requester_agent_id": requester_agent_id,
            "requester_step_id": requester_step_id,
            "capability": capability,
            "timestamp": str(now),
        })
        pipe.expire(f"ledgers:{workflow_id}", self._ttl_seconds)
        pipe.execute()
        return need_id

    def get_workflows_with_capability_needs(self) -> List[str]:
        return sorted(self._redis.smembers(
            "jarviscore:workflows_with_capability_needs"
        ))

    def get_capability_need(
        self, workflow_id: str, need_id: str
    ) -> Optional[Dict[str, Any]]:
        raw = self._redis.hget(f"capability_needs:{workflow_id}", need_id)
        return CapabilityMandate.from_record(json.loads(raw)).to_record() if raw else None

    def get_open_capability_needs(self, workflow_id: str) -> List[Dict[str, Any]]:
        records = []
        for raw in self._redis.hvals(f"capability_needs:{workflow_id}"):
            try:
                record = CapabilityMandate.from_record(json.loads(raw)).to_record()
            except (json.JSONDecodeError, TypeError):
                continue
            if record.get("status") in {"open", "claimed"}:
                records.append(record)
        return sorted(records, key=lambda item: float(item.get("created_at", 0)))

    def claim_capability_need(
        self,
        workflow_id: str,
        need_id: str,
        claim_id: str,
        capabilities: set[str],
        lease_seconds: int = 60,
    ) -> bool:
        needs_key = f"capability_needs:{workflow_id}"
        lock_key = f"capability_need_lock:{workflow_id}:{need_id}"
        lease_seconds = max(1, int(lease_seconds))
        pipe = self._redis.pipeline()
        while True:
            try:
                pipe.watch(needs_key, lock_key)
                if pipe.exists(lock_key):
                    pipe.unwatch()
                    return False
                raw = pipe.hget(needs_key, need_id)
                if raw is None:
                    pipe.unwatch()
                    return False
                mandate = CapabilityMandate.from_record(json.loads(raw))
                if (
                    mandate.status != "open"
                    or mandate.capability not in capabilities
                    or mandate.requester_agent_id == claim_id.split(":", 1)[0]
                ):
                    pipe.unwatch()
                    return False
                now = time.time()
                mandate = mandate.claimed(
                    claim_id,
                    claim_id.split(":", 1)[0],
                    now + lease_seconds,
                    now,
                )
                record = mandate.to_record()
                pipe.multi()
                pipe.set(lock_key, claim_id, ex=lease_seconds)
                pipe.hset(needs_key, mapping={need_id: json.dumps(record, default=str)})
                pipe.xadd(f"ledgers:{workflow_id}", {
                    "event": "capability_need_claimed",
                    "need_id": need_id,
                    "agent_id": record["claimed_by"],
                    "claim_id": claim_id,
                    "timestamp": str(now),
                })
                pipe.expire(f"ledgers:{workflow_id}", self._ttl_seconds)
                pipe.execute()
                return True
            except redis.WatchError:
                continue

    def fulfill_capability_need(
        self,
        workflow_id: str,
        need_id: str,
        claim_id: str,
        result: Dict[str, Any],
    ) -> bool:
        needs_key = f"capability_needs:{workflow_id}"
        lock_key = f"capability_need_lock:{workflow_id}:{need_id}"
        pipe = self._redis.pipeline()
        while True:
            try:
                pipe.watch(needs_key, lock_key)
                raw = pipe.hget(needs_key, need_id)
                if raw is None or pipe.get(lock_key) != claim_id:
                    pipe.unwatch()
                    return False
                mandate = CapabilityMandate.from_record(json.loads(raw))
                if (
                    mandate.status != "claimed"
                    or mandate.claim is None
                    or mandate.claim.claim_id != claim_id
                ):
                    pipe.unwatch()
                    return False
                now = time.time()
                failed = str(result.get("status") or "").lower() in {
                    "error", "failed", "failure"
                }
                if failed:
                    record = mandate.failed(
                        str(result.get("error") or "Peer execution failed"), now
                    ).to_record()
                    event = "capability_need_failed"
                else:
                    record = mandate.fulfilled(
                        claim_id.split(":", 1)[0], result, now
                    ).to_record()
                    event = "capability_need_fulfilled"
                pipe.multi()
                pipe.hset(needs_key, mapping={need_id: json.dumps(record, default=str)})
                pipe.delete(lock_key)
                pipe.xadd(f"ledgers:{workflow_id}", {
                    "event": event,
                    "need_id": need_id,
                    "agent_id": claim_id.split(":", 1)[0],
                    "timestamp": str(now),
                })
                pipe.expire(f"ledgers:{workflow_id}", self._ttl_seconds)
                pipe.execute()
                if not self.get_open_capability_needs(workflow_id):
                    self._redis.srem(
                        "jarviscore:workflows_with_capability_needs", workflow_id
                    )
                return True
            except redis.WatchError:
                continue

    def fail_capability_need(
        self,
        workflow_id: str,
        need_id: str,
        requester_agent_id: str,
        reason: str,
    ) -> bool:
        """End an active mandate from its requester and invalidate its claim."""
        needs_key = f"capability_needs:{workflow_id}"
        lock_key = f"capability_need_lock:{workflow_id}:{need_id}"
        pipe = self._redis.pipeline()
        while True:
            try:
                pipe.watch(needs_key, lock_key)
                raw = pipe.hget(needs_key, need_id)
                if raw is None:
                    pipe.unwatch()
                    return False
                mandate = CapabilityMandate.from_record(json.loads(raw))
                if (
                    mandate.requester_agent_id != requester_agent_id
                    or mandate.status not in {"open", "claimed"}
                ):
                    pipe.unwatch()
                    return False
                now = time.time()
                record = mandate.failed(reason, now).to_record()
                pipe.multi()
                pipe.hset(needs_key, mapping={need_id: json.dumps(record, default=str)})
                pipe.delete(lock_key)
                pipe.xadd(f"ledgers:{workflow_id}", {
                    "event": "capability_need_failed",
                    "need_id": need_id,
                    "agent_id": requester_agent_id,
                    "timestamp": str(now),
                })
                pipe.expire(f"ledgers:{workflow_id}", self._ttl_seconds)
                pipe.execute()
                if not self.get_open_capability_needs(workflow_id):
                    self._redis.srem(
                        "jarviscore:workflows_with_capability_needs", workflow_id
                    )
                return True
            except redis.WatchError:
                continue

    def renew_capability_need_claim(
        self,
        workflow_id: str,
        need_id: str,
        claim_id: str,
        lease_seconds: int = 60,
    ) -> bool:
        """Extend an active capability claim while preserving fencing."""
        needs_key = f"capability_needs:{workflow_id}"
        lock_key = f"capability_need_lock:{workflow_id}:{need_id}"
        cancelled_key = f"workflow_cancelled:{workflow_id}"
        lease_seconds = max(1, int(lease_seconds))
        pipe = self._redis.pipeline()
        while True:
            try:
                pipe.watch(needs_key, lock_key, cancelled_key)
                if pipe.exists(cancelled_key) or pipe.get(lock_key) != claim_id:
                    pipe.unwatch()
                    return False
                raw = pipe.hget(needs_key, need_id)
                if raw is None:
                    pipe.unwatch()
                    return False
                mandate = CapabilityMandate.from_record(json.loads(raw))
                if (
                    mandate.status != "claimed"
                    or mandate.claim is None
                    or mandate.claim.claim_id != claim_id
                ):
                    pipe.unwatch()
                    return False
                now = time.time()
                record = mandate.renewed(now + lease_seconds, now).to_record()
                pipe.multi()
                pipe.expire(lock_key, lease_seconds)
                pipe.hset(
                    needs_key,
                    mapping={need_id: json.dumps(record, default=str)},
                )
                pipe.execute()
                return True
            except redis.WatchError:
                continue

    def recover_expired_capability_need(
        self, workflow_id: str, need_id: str
    ) -> bool:
        needs_key = f"capability_needs:{workflow_id}"
        lock_key = f"capability_need_lock:{workflow_id}:{need_id}"
        pipe = self._redis.pipeline()
        while True:
            try:
                pipe.watch(needs_key, lock_key)
                raw = pipe.hget(needs_key, need_id)
                if raw is None or pipe.exists(lock_key):
                    pipe.unwatch()
                    return False
                mandate = CapabilityMandate.from_record(json.loads(raw))
                if mandate.status != "claimed":
                    pipe.unwatch()
                    return False
                record = mandate.reopened(time.time()).to_record()
                pipe.multi()
                pipe.hset(needs_key, mapping={need_id: json.dumps(record, default=str)})
                pipe.execute()
                return True
            except redis.WatchError:
                continue

    # ------------------------------------------------------------------
    # Workflow DAG
    # ------------------------------------------------------------------

    def register_workflow_goal(
        self,
        workflow_id: str,
        goal: str,
        context: Optional[Dict[str, Any]] = None,
        budget: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Persist source intent once; the same workflow id cannot change meaning."""
        key = f"workflow_goal:{workflow_id}"
        ledger_key = f"ledgers:{workflow_id}"
        budget_key = f"workflow_budget:{workflow_id}"
        normalized_budget = ExecutionBudget.from_record(budget).to_record()
        encoded = json.dumps({
            "workflow_id": workflow_id,
            "goal": goal,
            "context": neutral_context(context),
            "budget": normalized_budget,
        }, default=str)
        pipe = self._redis.pipeline()
        while True:
            try:
                pipe.watch(key)
                existing = pipe.get(key)
                if existing is not None:
                    pipe.unwatch()
                    try:
                        same_binding = json.loads(existing) == json.loads(encoded)
                    except (json.JSONDecodeError, TypeError):
                        same_binding = existing == encoded
                    if not same_binding:
                        raise ValueError(
                            f"Workflow {workflow_id!r} is already bound to another goal"
                        )
                    return False
                now = time.time()
                pipe.multi()
                pipe.set(key, encoded, ex=self._ttl_seconds)
                pipe.hset(budget_key, mapping={
                    "max_tokens_per_epoch": normalized_budget["max_tokens"],
                    "used_tokens": 0,
                    "cost_usd": 0.0,
                    "call_count": 0,
                    "epoch_count": 0,
                })
                pipe.expire(budget_key, self._ttl_seconds)
                pipe.sadd("jarviscore:pending_goal_plans", workflow_id)
                pipe.expire("jarviscore:pending_goal_plans", self._ttl_seconds)
                pipe.xadd(ledger_key, {
                    "event": "goal_registered",
                    "timestamp": str(now),
                })
                pipe.expire(ledger_key, self._ttl_seconds)
                pipe.execute()
                return True
            except redis.WatchError:
                continue

    def reserve_workflow_tokens(
        self,
        workflow_id: str,
        epoch_id: str,
        reservation_id: str,
        tokens: int,
        *,
        lease_seconds: float = 900.0,
    ) -> bool:
        """Atomically reserve workflow-global LLM capacity before dispatch."""
        budget_key = f"workflow_budget:{workflow_id}"
        epoch_key = f"workflow_budget_epoch:{workflow_id}:{epoch_id}"
        reservations_key = f"workflow_budget_reservations:{workflow_id}:{epoch_id}"
        amount = max(1, int(tokens))
        if not self._redis.exists(budget_key):
            source = self.get_workflow_goal(workflow_id) or {}
            budget = ExecutionBudget.from_record(source.get("budget")).to_record()
            initial = self._redis.pipeline(transaction=True)
            initial.hsetnx(budget_key, "max_tokens_per_epoch", budget["max_tokens"])
            initial.hsetnx(budget_key, "used_tokens", 0)
            initial.hsetnx(budget_key, "cost_usd", 0.0)
            initial.hsetnx(budget_key, "call_count", 0)
            initial.hsetnx(budget_key, "epoch_count", 0)
            initial.expire(budget_key, self._ttl_seconds)
            initial.execute()
        if not self._redis.exists(epoch_key):
            epoch_init = self._redis.pipeline(transaction=True)
            epoch_init.hsetnx(epoch_key, "used_tokens", 0)
            epoch_init.hsetnx(epoch_key, "reserved_tokens", 0)
            epoch_init.hsetnx(epoch_key, "created_at", time.time())
            epoch_init.expire(epoch_key, self._ttl_seconds)
            epoch_init.hincrby(budget_key, "epoch_count", 1)
            epoch_init.execute()
        pipe = self._redis.pipeline()
        while True:
            try:
                pipe.watch(budget_key, epoch_key, reservations_key)
                budget = pipe.hgetall(budget_key)
                if not budget:
                    pipe.unwatch()
                    return False
                now = time.time()
                live = {}
                for key, raw in pipe.hgetall(reservations_key).items():
                    try:
                        value = json.loads(raw)
                    except (TypeError, json.JSONDecodeError):
                        continue
                    if float(value.get("expires_at") or 0.0) > now:
                        live[key] = value
                epoch = pipe.hgetall(epoch_key)
                used = int(float(epoch.get("used_tokens") or 0))
                reserved = sum(int(item.get("tokens") or 0) for item in live.values())
                limit = int(float(
                    budget.get("max_tokens_per_epoch")
                    or budget.get("max_tokens")
                    or 0
                ))
                if "max_tokens_per_epoch" not in budget and limit:
                    pipe.multi()
                    pipe.hset(budget_key, "max_tokens_per_epoch", limit)
                    pipe.execute()
                    continue
                if used + reserved + amount > limit:
                    pipe.unwatch()
                    return False
                live[reservation_id] = {
                    "tokens": amount,
                    "expires_at": now + max(1.0, float(lease_seconds)),
                }
                pipe.multi()
                pipe.delete(reservations_key)
                if live:
                    pipe.hset(reservations_key, mapping={
                        key: json.dumps(value) for key, value in live.items()
                    })
                    pipe.expire(reservations_key, self._ttl_seconds)
                pipe.hset(epoch_key, "reserved_tokens", reserved + amount)
                pipe.expire(epoch_key, self._ttl_seconds)
                pipe.execute()
                return True
            except redis.WatchError:
                continue

    def settle_workflow_tokens(
        self,
        workflow_id: str,
        epoch_id: str,
        reservation_id: str,
        tokens: int,
        cost_usd: float,
    ) -> bool:
        """Replace one live reservation with provider-reported usage."""
        budget_key = f"workflow_budget:{workflow_id}"
        epoch_key = f"workflow_budget_epoch:{workflow_id}:{epoch_id}"
        reservations_key = f"workflow_budget_reservations:{workflow_id}:{epoch_id}"
        pipe = self._redis.pipeline()
        while True:
            try:
                pipe.watch(budget_key, epoch_key, reservations_key)
                raw = pipe.hget(reservations_key, reservation_id)
                budget = pipe.hgetall(budget_key)
                epoch = pipe.hgetall(epoch_key)
                if raw is None or not budget or not epoch:
                    pipe.unwatch()
                    return False
                reservation = json.loads(raw)
                reserved = max(0, int(float(epoch.get("reserved_tokens") or 0)))
                epoch_used = max(0, int(float(epoch.get("used_tokens") or 0)))
                used = max(0, int(float(budget.get("used_tokens") or 0)))
                cost = max(0.0, float(budget.get("cost_usd") or 0.0))
                calls = max(0, int(float(budget.get("call_count") or 0)))
                pipe.multi()
                pipe.hdel(reservations_key, reservation_id)
                pipe.hset(epoch_key, mapping={
                    "reserved_tokens": max(
                        0, reserved - int(reservation.get("tokens") or 0)
                    ),
                    "used_tokens": epoch_used + max(0, int(tokens)),
                })
                pipe.hset(budget_key, mapping={
                    "used_tokens": used + max(0, int(tokens)),
                    "cost_usd": cost + max(0.0, float(cost_usd)),
                    "call_count": calls + 1,
                })
                pipe.expire(budget_key, self._ttl_seconds)
                pipe.execute()
                return True
            except redis.WatchError:
                continue

    def release_workflow_token_reservation(
        self,
        workflow_id: str,
        epoch_id: str,
        reservation_id: str,
    ) -> bool:
        """Release capacity when dispatch fails before reporting usage."""
        budget_key = f"workflow_budget:{workflow_id}"
        epoch_key = f"workflow_budget_epoch:{workflow_id}:{epoch_id}"
        reservations_key = f"workflow_budget_reservations:{workflow_id}:{epoch_id}"
        pipe = self._redis.pipeline()
        while True:
            try:
                pipe.watch(epoch_key, reservations_key)
                raw = pipe.hget(reservations_key, reservation_id)
                if raw is None:
                    pipe.unwatch()
                    return False
                reservation = json.loads(raw)
                reserved = int(float(pipe.hget(epoch_key, "reserved_tokens") or 0))
                pipe.multi()
                pipe.hdel(reservations_key, reservation_id)
                pipe.hset(
                    epoch_key,
                    "reserved_tokens",
                    max(0, reserved - int(reservation.get("tokens") or 0)),
                )
                pipe.execute()
                return True
            except redis.WatchError:
                continue

    def get_workflow_budget_usage(
        self,
        workflow_id: str,
        epoch_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        raw = self._redis.hgetall(f"workflow_budget:{workflow_id}")
        if not raw:
            return None
        result = {
            "max_tokens_per_epoch": int(
                float(raw.get("max_tokens_per_epoch") or raw.get("max_tokens") or 0)
            ),
            "used_tokens": int(float(raw.get("used_tokens") or 0)),
            "cost_usd": float(raw.get("cost_usd") or 0.0),
            "call_count": int(float(raw.get("call_count") or 0)),
            "epoch_count": int(float(raw.get("epoch_count") or 0)),
        }
        if epoch_id is not None:
            epoch = self._redis.hgetall(
                f"workflow_budget_epoch:{workflow_id}:{epoch_id}"
            )
            result.update({
                "epoch_id": epoch_id,
                "epoch_used_tokens": int(float(epoch.get("used_tokens") or 0)),
                "epoch_reserved_tokens": int(
                    float(epoch.get("reserved_tokens") or 0)
                ),
            })
        return result

    def get_workflow_goal(self, workflow_id: str) -> Optional[Dict[str, Any]]:
        raw = self._redis.get(f"workflow_goal:{workflow_id}")
        if not raw:
            return None
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return None

    def get_pending_workflow_goals(self) -> List[str]:
        return list(self._redis.smembers("jarviscore:pending_goal_plans"))

    def save_workflow_planning_status(
        self,
        workflow_id: str,
        status: str,
        *,
        planner_id: str = "",
        error: str = "",
    ) -> None:
        payload = {
            "status": status,
            "planner_id": planner_id,
            "error": error,
            "updated_at": time.time(),
        }
        self._redis.set(
            f"workflow_planning_status:{workflow_id}",
            json.dumps(payload),
            ex=self._ttl_seconds,
        )
        if status in {"published", "failed"}:
            self._redis.srem("jarviscore:pending_goal_plans", workflow_id)
        self.append_ledger_entry(workflow_id, {
            "event": f"planning_{status}",
            "planner_id": planner_id,
            "error": error,
        })

    def get_workflow_planning_status(self, workflow_id: str) -> Optional[Dict[str, Any]]:
        raw = self._redis.get(f"workflow_planning_status:{workflow_id}")
        if not raw:
            return None
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return None

    def claim_workflow_planning(
        self, workflow_id: str, claimant_id: str, lease_seconds: int = 300
    ) -> bool:
        """Acquire the temporary right to compile a goal, never to assign its work."""
        return bool(self._redis.set(
            f"workflow_planning_lock:{workflow_id}",
            claimant_id,
            nx=True,
            ex=max(1, int(lease_seconds)),
        ))

    def release_workflow_planning(self, workflow_id: str, claimant_id: str) -> bool:
        key = f"workflow_planning_lock:{workflow_id}"
        pipe = self._redis.pipeline()
        while True:
            try:
                pipe.watch(key)
                if pipe.get(key) != claimant_id:
                    pipe.unwatch()
                    return False
                pipe.multi()
                pipe.delete(key)
                pipe.execute()
                return True
            except redis.WatchError:
                continue

    def claim_workflow_reconciliation(
        self,
        workflow_id: str,
        revision: int,
        claimant_id: str,
        lease_seconds: int = 300,
    ) -> bool:
        return bool(self._redis.set(
            f"workflow_reconciliation_lock:{workflow_id}:{revision}",
            claimant_id,
            nx=True,
            ex=max(1, int(lease_seconds)),
        ))

    def release_workflow_reconciliation(
        self, workflow_id: str, revision: int, claimant_id: str
    ) -> bool:
        key = f"workflow_reconciliation_lock:{workflow_id}:{revision}"
        pipe = self._redis.pipeline()
        while True:
            try:
                pipe.watch(key)
                if pipe.get(key) != claimant_id:
                    pipe.unwatch()
                    return False
                pipe.multi()
                pipe.delete(key)
                pipe.execute()
                return True
            except redis.WatchError:
                continue

    def save_workflow_reconciliation_settlement(
        self, workflow_id: str, revision: int, settlement: Dict[str, Any]
    ) -> bool:
        key = f"workflow_reconciliation_settlement:{workflow_id}:{revision}"
        payload = {**settlement, "revision": revision}
        pipe = self._redis.pipeline()
        while True:
            try:
                pipe.watch(key)
                if pipe.exists(key):
                    pipe.unwatch()
                    return False
                pipe.multi()
                pipe.set(key, json.dumps(payload, default=str), ex=self._ttl_seconds)
                pipe.xadd(f"ledgers:{workflow_id}", {
                    field: json.dumps(value) if not isinstance(value, str) else value
                    for field, value in payload.items()
                })
                pipe.expire(f"ledgers:{workflow_id}", self._ttl_seconds)
                pipe.execute()
                return True
            except redis.WatchError:
                continue

    def get_workflow_reconciliation_settlement(
        self, workflow_id: str, revision: int
    ) -> Optional[Dict[str, Any]]:
        raw = self._redis.get(
            f"workflow_reconciliation_settlement:{workflow_id}:{revision}"
        )
        if not raw:
            return None
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return None

    def unregister_active_workflow(self, workflow_id: str) -> None:
        self._redis.srem("jarviscore:active_workflows", workflow_id)

    def is_workflow_cancelled(self, workflow_id: str) -> bool:
        return bool(self._redis.exists(f"workflow_cancelled:{workflow_id}"))

    def cancel_workflow(self, workflow_id: str, *, reason: str) -> bool:
        """Atomically tombstone a workflow and invalidate every unfinished claim."""
        graph_key = f"workflow_graph:{workflow_id}"
        needs_key = f"capability_needs:{workflow_id}"
        cancelled_key = f"workflow_cancelled:{workflow_id}"
        pipe = self._redis.pipeline()
        while True:
            try:
                pipe.watch(graph_key, needs_key, cancelled_key)
                if pipe.exists(cancelled_key):
                    pipe.unwatch()
                    return False
                graph = {
                    str(step_id): json.loads(raw)
                    for step_id, raw in pipe.hgetall(graph_key).items()
                }
                needs = {
                    str(need_id): json.loads(raw)
                    for need_id, raw in pipe.hgetall(needs_key).items()
                }
                if not graph and not needs:
                    pipe.unwatch()
                    return False
                now = time.time()
                cancelled = {}
                lock_keys = []
                for step_id, record in graph.items():
                    if record.get("status") not in {"completed", "failed", "cancelled"}:
                        record.update({
                            "status": "cancelled",
                            "cancel_reason": reason,
                            "updated_at": now,
                        })
                        record.pop("claim_expires_at", None)
                        record.pop("resume_agent_id", None)
                        record.pop("resume_context", None)
                    cancelled[step_id] = json.dumps(record, default=str)
                    lock_keys.append(f"step_lock:{workflow_id}:{step_id}")
                cancelled_needs = {}
                need_lock_keys = []
                for need_id, record in needs.items():
                    mandate = CapabilityMandate.from_record(record)
                    cancelled_needs[need_id] = json.dumps(
                        mandate.cancelled(reason, now).to_record(), default=str
                    )
                    need_lock_keys.append(
                        f"capability_need_lock:{workflow_id}:{need_id}"
                    )
                pipe.multi()
                pipe.set(
                    cancelled_key,
                    json.dumps({"reason": reason, "cancelled_at": now}),
                    ex=self._ttl_seconds,
                )
                if cancelled:
                    pipe.hset(graph_key, mapping=cancelled)
                if cancelled_needs:
                    pipe.hset(needs_key, mapping=cancelled_needs)
                if lock_keys:
                    pipe.delete(*lock_keys)
                if need_lock_keys:
                    pipe.delete(*need_lock_keys)
                pipe.delete(f"workflow_planning_lock:{workflow_id}")
                pipe.srem("jarviscore:active_workflows", workflow_id)
                pipe.srem("jarviscore:pending_goal_plans", workflow_id)
                pipe.srem(
                    "jarviscore:workflows_with_capability_needs", workflow_id
                )
                pipe.xadd(f"ledgers:{workflow_id}", {
                    "event": "workflow_cancelled",
                    "reason": reason,
                    "timestamp": str(now),
                })
                pipe.expire(graph_key, self._ttl_seconds)
                if cancelled_needs:
                    pipe.expire(needs_key, self._ttl_seconds)
                pipe.expire(f"ledgers:{workflow_id}", self._ttl_seconds)
                pipe.execute()
                return True
            except redis.WatchError:
                continue

    def publish_workflow(
        self,
        workflow_id: str,
        *,
        goal: str,
        obligations: List[Dict],
        steps: List[Dict],
        context: Optional[Dict[str, Any]] = None,
        budget: Optional[Dict[str, Any]] = None,
        revision: int = 1,
    ) -> bool:
        """Atomically publish the source contract and complete executable DAG."""
        graph_key = f"workflow_graph:{workflow_id}"
        definition_key = f"workflow_definition:{workflow_id}"
        normalized = []
        graph = {}
        for step in steps:
            step_id = str(step.get("id") or step.get("step_id") or "")
            if not step_id:
                raise ValueError("Every workflow step requires an id")
            record = dict(step)
            record["id"] = step_id
            record["status"] = "pending"
            record["plan_revision"] = revision
            normalized.append(record)
            graph[step_id] = json.dumps(record, default=str)
        definition = WorkflowEnvelope(
            workflow_id=workflow_id,
            goal=goal,
            context=context or {},
            obligations=obligations,
            steps=normalized,
            budget=ExecutionBudget.from_record(budget),
            revision=revision,
            published_at=time.time(),
        ).to_record()
        projection = self._initial_obligation_projection(
            obligations, normalized, revision
        )
        projection_key = f"workflow_obligations:{workflow_id}"
        pipe = self._redis.pipeline(transaction=True)
        pipe.delete(graph_key)
        if graph:
            pipe.hset(graph_key, mapping=graph)
        pipe.set(definition_key, json.dumps(definition, default=str))
        pipe.set(projection_key, json.dumps(projection, default=str))
        pipe.sadd("jarviscore:active_workflows", workflow_id)
        pipe.srem("jarviscore:pending_goal_plans", workflow_id)
        pipe.xadd(f"ledgers:{workflow_id}", {
            "event": "dag_published",
            "revision": str(revision),
            "step_count": str(len(normalized)),
            "timestamp": str(time.time()),
        })
        pipe.set(
            f"workflow_planning_status:{workflow_id}",
            json.dumps({
                "status": "published",
                "planner_id": "",
                "error": "",
                "updated_at": time.time(),
            }),
            ex=self._ttl_seconds,
        )
        pipe.expire(graph_key, self._ttl_seconds)
        pipe.expire(definition_key, self._ttl_seconds)
        pipe.expire(projection_key, self._ttl_seconds)
        pipe.expire("jarviscore:active_workflows", self._ttl_seconds)
        pipe.expire(f"ledgers:{workflow_id}", self._ttl_seconds)
        pipe.execute()
        return True

    @staticmethod
    def _initial_obligation_projection(
        obligations: List[Dict], steps: List[Dict], revision: int
    ) -> Dict[str, Dict[str, Any]]:
        projection = {}
        for obligation in obligations:
            obligation_id = str(obligation.get("id") or "")
            if not obligation_id:
                continue
            current_step_ids = [
                str(step.get("id") or step.get("step_id"))
                for step in steps
                if obligation_id in map(str, step.get("covers", []))
            ]
            projection[obligation_id] = {
                **obligation,
                "state": "pending",
                "revision": revision,
                "current_step_ids": current_step_ids,
                "superseded_step_ids": [],
                "attempt_states": {
                    step_id: "pending" for step_id in current_step_ids
                },
                "attempt_interpretations": {},
            }
        return projection

    def get_obligation_projection(
        self, workflow_id: str
    ) -> Dict[str, Dict[str, Any]]:
        """Return the durable current truth for every source obligation."""
        raw = self._redis.get(f"workflow_obligations:{workflow_id}")
        if raw:
            try:
                return json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                return {}
        definition = self.get_workflow_definition(workflow_id)
        if definition is None:
            return {}
        return self._initial_obligation_projection(
            definition.get("obligations", []),
            definition.get("steps", []),
            int(definition.get("revision", 0)),
        )

    def get_workflow_definition(self, workflow_id: str) -> Optional[Dict]:
        raw = self._redis.get(f"workflow_definition:{workflow_id}")
        if raw:
            try:
                return WorkflowEnvelope.from_record(json.loads(raw)).to_record()
            except (json.JSONDecodeError, TypeError):
                return None
        steps = [
            self.get_step_definition(workflow_id, step_id)
            for step_id in self.get_all_step_ids(workflow_id)
        ]
        if not steps:
            return None
        return {
            "workflow_id": workflow_id,
            "goal": "",
            "obligations": [],
            "steps": [step for step in steps if step is not None],
            "revision": 0,
        }

    def amend_workflow(
        self,
        workflow_id: str,
        *,
        expected_revision: int,
        obligations: List[Dict],
        steps: List[Dict],
        reason: str,
    ) -> bool:
        """Atomically append a revision delta while retaining immutable attempts."""
        definition_key = f"workflow_definition:{workflow_id}"
        graph_key = f"workflow_graph:{workflow_id}"
        projection_key = f"workflow_obligations:{workflow_id}"
        cancelled_key = f"workflow_cancelled:{workflow_id}"
        pipe = self._redis.pipeline()
        while True:
            try:
                pipe.watch(definition_key, graph_key, projection_key, cancelled_key)
                if pipe.exists(cancelled_key):
                    pipe.unwatch()
                    raise ValueError("A cancelled workflow cannot be amended")
                raw_definition = pipe.get(definition_key)
                if not raw_definition:
                    pipe.unwatch()
                    raise KeyError(workflow_id)
                current = json.loads(raw_definition)
                if int(current.get("revision", 0)) != expected_revision:
                    pipe.unwatch()
                    raise ValueError("Workflow revision changed before amendment")
                live = {
                    step_id: json.loads(value)
                    for step_id, value in pipe.hgetall(graph_key).items()
                }
                current_ids = set(live)
                if obligations != current.get("obligations", []):
                    pipe.unwatch()
                    raise ValueError("Amendment cannot change source obligations")
                if not steps:
                    pipe.unwatch()
                    raise ValueError("Amendment requires at least one new step")
                proposed = []
                proposed_ids = set()
                for step in steps:
                    step_id = str(step.get("id") or step.get("step_id") or "")
                    if not step_id or step_id in proposed_ids:
                        pipe.unwatch()
                        raise ValueError("Amended steps require unique non-empty ids")
                    if step_id in current_ids:
                        pipe.unwatch()
                        raise ValueError(f"Amended step {step_id!r} already exists")
                    proposed_ids.add(step_id)
                    proposed.append({
                        **step,
                        "id": step_id,
                        "status": "pending",
                        "plan_revision": expected_revision + 1,
                    })
                all_ids = current_ids | proposed_ids
                for step in proposed:
                    unknown = set(step.get("depends_on", [])) - all_ids
                    if unknown:
                        pipe.unwatch()
                        raise ValueError(f"Step {step['id']!r} has unknown dependencies: {sorted(unknown)}")
                combined = [*live.values(), *proposed]
                self._validate_acyclic_steps(combined)
                covered_by_delta = {
                    str(obligation_id)
                    for step in proposed
                    for obligation_id in step.get("covers", [])
                }
                raw_projection = pipe.get(projection_key)
                projection = (
                    json.loads(raw_projection)
                    if raw_projection
                    else self._initial_obligation_projection(
                        current.get("obligations", []),
                        list(live.values()),
                        expected_revision,
                    )
                )
                for obligation_id in covered_by_delta:
                    record = projection.get(obligation_id)
                    if record is None:
                        continue
                    current_step_ids = [
                        step["id"] for step in proposed
                        if obligation_id in map(str, step.get("covers", []))
                    ]
                    superseded = list(record.get("superseded_step_ids", []))
                    superseded.extend(
                        step_id for step_id in record.get("current_step_ids", [])
                        if step_id not in superseded
                    )
                    projection[obligation_id] = {
                        **record,
                        "state": "pending",
                        "revision": expected_revision + 1,
                        "current_step_ids": current_step_ids,
                        "superseded_step_ids": superseded,
                        "attempt_states": {
                            step_id: "pending" for step_id in current_step_ids
                        },
                        "attempt_interpretations": {},
                    }
                superseded_ids = []
                for step_id, record in live.items():
                    if (
                        record.get("status") in {"pending", "waiting", "blocked"}
                        and covered_by_delta.intersection(map(str, record.get("covers", [])))
                    ):
                        record = {
                            **record,
                            "status": "superseded",
                            "superseded_by_revision": expected_revision + 1,
                        }
                        live[step_id] = record
                        superseded_ids.append(step_id)
                graph = {
                    step_id: json.dumps(record, default=str)
                    for step_id, record in {**live, **{
                        step["id"]: step for step in proposed
                    }}.items()
                }
                normalized = [*live.values(), *proposed]
                amended = {
                    **current,
                    "steps": normalized,
                    "revision": expected_revision + 1,
                    "amended_at": time.time(),
                    "amendment_reason": reason,
                }
                pipe.multi()
                pipe.delete(graph_key)
                pipe.hset(graph_key, mapping=graph)
                pipe.set(definition_key, json.dumps(amended, default=str))
                pipe.set(projection_key, json.dumps(projection, default=str))
                pipe.sadd("jarviscore:active_workflows", workflow_id)
                pipe.xadd(f"ledgers:{workflow_id}", {
                    "event": "dag_amended",
                    "revision": str(expected_revision + 1),
                    "reason": reason,
                    "added_step_ids": json.dumps(sorted(proposed_ids)),
                    "superseded_step_ids": json.dumps(sorted(superseded_ids)),
                    "timestamp": str(time.time()),
                })
                pipe.expire(graph_key, self._ttl_seconds)
                pipe.expire(definition_key, self._ttl_seconds)
                pipe.expire(projection_key, self._ttl_seconds)
                pipe.expire(f"ledgers:{workflow_id}", self._ttl_seconds)
                pipe.execute()
                return True
            except redis.WatchError:
                continue

    @staticmethod
    def _validate_acyclic_steps(steps: List[Dict]) -> None:
        dependencies = {
            str(step["id"]): {str(value) for value in step.get("depends_on", [])}
            for step in steps
        }
        visiting = set()
        visited = set()

        def visit(step_id: str) -> None:
            if step_id in visiting:
                raise ValueError("Workflow amendment contains a dependency cycle")
            if step_id in visited:
                return
            visiting.add(step_id)
            for dependency in dependencies[step_id]:
                visit(dependency)
            visiting.remove(step_id)
            visited.add(step_id)

        for step_id in dependencies:
            visit(step_id)

    def get_dependency_outputs(self, workflow_id: str, step_id: str) -> Dict[str, Any]:
        step = self.get_step_definition(workflow_id, step_id) or {}
        outputs = {}
        for dependency_id in step.get("depends_on", []):
            saved = self.get_step_output(workflow_id, str(dependency_id))
            if saved is not None:
                output = saved.get("output", saved)
                if (
                    isinstance(output, dict)
                    and output.get("status") == "success"
                    and "output" in output
                ):
                    output = output["output"]
                outputs[str(dependency_id)] = output
        return outputs

    def get_workflow_outputs(
        self, workflow_id: str, *, exclude_step_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Return every persisted artifact for workflow-level synthesis."""
        outputs = {}
        for output_id in self.list_step_output_ids(workflow_id):
            if output_id == exclude_step_id:
                continue
            saved = self.get_step_output(workflow_id, output_id)
            if saved is None:
                continue
            output = saved.get("output", saved)
            if (
                isinstance(output, dict)
                and output.get("status") == "success"
                and "output" in output
            ):
                output = output["output"]
            outputs[output_id] = output
        return outputs

    def get_workflow_step_states(self, workflow_id: str) -> Dict[str, str]:
        """Return every DAG step's current state for final-response synthesis."""
        states = {}
        for step_id, raw in self._redis.hgetall(
            f"workflow_graph:{workflow_id}"
        ).items():
            try:
                states[str(step_id)] = str(json.loads(raw).get("status") or "")
            except (json.JSONDecodeError, TypeError):
                continue
        return states

    def get_workflow_evidence(
        self, workflow_id: str, *, exclude_step_id: Optional[str] = None
    ) -> WorkflowEvidence:
        """Build one canonical workflow-level evidence snapshot."""
        artifacts = self.get_workflow_outputs(
            workflow_id, exclude_step_id=exclude_step_id
        )
        interpretations = {}
        for output_id in self.list_step_output_ids(workflow_id):
            if output_id == exclude_step_id:
                continue
            saved = self.get_step_output(workflow_id, output_id)
            envelope = saved.get("output") if isinstance(saved, dict) else None
            interpretation = (
                envelope.get("interpretation")
                if isinstance(envelope, dict)
                else None
            )
            if isinstance(interpretation, dict):
                interpretations[output_id] = interpretation
        return WorkflowEvidence(
            artifacts=artifacts,
            interpretations=interpretations,
            states=self.get_workflow_step_states(workflow_id),
            obligations=self.get_obligation_projection(workflow_id),
        )

    def get_dependency_interpretations(
        self, workflow_id: str, step_id: str
    ) -> Dict[str, Any]:
        """Return semantic assessments without changing artifact payload shapes."""
        step = self.get_step_definition(workflow_id, step_id) or {}
        interpretations = {}
        for dependency_id in step.get("depends_on", []):
            saved = self.get_step_output(workflow_id, str(dependency_id))
            envelope = saved.get("output") if isinstance(saved, dict) else None
            interpretation = (
                envelope.get("interpretation") if isinstance(envelope, dict) else None
            )
            if isinstance(interpretation, dict):
                interpretations[str(dependency_id)] = interpretation
        return interpretations

    def init_workflow_graph(self, workflow_id: str, steps: List[Dict]) -> bool:
        """Initialize Redis DAG for a workflow."""
        return self.publish_workflow(
            workflow_id,
            goal="",
            obligations=[],
            steps=steps,
        )

    def get_step_status(self, workflow_id: str, step_id: str) -> Optional[str]:
        """Read step status from workflow DAG."""
        key = f"workflow_graph:{workflow_id}"
        raw = self._redis.hget(key, step_id)
        if raw is None:
            return None
        try:
            return json.loads(raw).get("status")
        except (json.JSONDecodeError, TypeError):
            return None

    def update_step_status(self, workflow_id: str, step_id: str,
                           status: str) -> bool:
        """Update step status in workflow DAG."""
        key = f"workflow_graph:{workflow_id}"
        raw = self._redis.hget(key, step_id)
        if raw is None:
            return False
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            data = {}
        data["status"] = status
        data["updated_at"] = time.time()
        self._redis.hset(key, mapping={step_id: json.dumps(data)})
        return True

    def are_dependencies_met(self, workflow_id: str, step_id: str) -> bool:
        """Check execution completion and semantic authorization for a step."""
        key = f"workflow_graph:{workflow_id}"
        raw = self._redis.hget(key, step_id)
        if raw is None:
            return True  # No entry = no dependencies
        try:
            step_data = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return True
        graph = {
            str(dependency_id): json.loads(value)
            for dependency_id, value in self._redis.hgetall(key).items()
        }
        return self._dependencies_authorize(step_data, graph)

    @staticmethod
    def _dependencies_authorize(step: Dict, graph: Dict[str, Dict]) -> bool:
        dependencies = [str(value) for value in step.get("depends_on", [])]
        if not dependencies:
            return True
        records = [graph.get(dependency_id, {}) for dependency_id in dependencies]
        effect = str(step.get("effect") or "read")
        if effect == "final_response":
            return all(
                record.get("status") in {
                    "completed", "failed", "waiting", "blocked", "cancelled"
                }
                for record in records
            )
        if not all(record.get("status") == "completed" for record in records):
            return False
        return True

    def get_dependency_statuses(self, workflow_id: str, step_id: str) -> Dict[str, str]:
        step = self.get_step_definition(workflow_id, step_id) or {}
        return {
            str(dependency_id): self.get_step_status(workflow_id, str(dependency_id))
            for dependency_id in step.get("depends_on", [])
        }

    def get_dependency_blockers(self, workflow_id: str, step_id: str) -> Dict[str, str]:
        """Return terminal dependency outcomes that forbid this step's effect."""
        graph_key = f"workflow_graph:{workflow_id}"
        graph = {
            str(dependency_id): json.loads(value)
            for dependency_id, value in self._redis.hgetall(graph_key).items()
        }
        step = graph.get(str(step_id), {})
        effect = str(step.get("effect") or "read")
        if effect == "final_response":
            return {}
        blockers = {}
        for dependency_id in map(str, step.get("depends_on", [])):
            dependency = graph.get(dependency_id, {})
            status = dependency.get("status")
            if status in {"failed", "waiting", "blocked", "cancelled"}:
                blockers[dependency_id] = f"execution:{status}"
                continue
        return blockers

    def block_step(
        self,
        workflow_id: str,
        step_id: str,
        blockers: Dict[str, str],
    ) -> bool:
        key = f"workflow_graph:{workflow_id}"
        raw = self._redis.hget(key, step_id)
        if raw is None:
            return False
        data = json.loads(raw)
        data.update({
            "status": "blocked",
            "blocked_by": blockers,
            "updated_at": time.time(),
        })
        pipe = self._redis.pipeline(transaction=True)
        pipe.hset(key, mapping={step_id: json.dumps(data)})
        pipe.xadd(f"ledgers:{workflow_id}", {
            "event": "step_blocked",
            "step_id": step_id,
            "blockers": json.dumps(blockers),
            "timestamp": str(time.time()),
        })
        pipe.expire(f"ledgers:{workflow_id}", self._ttl_seconds)
        pipe.execute()
        return True

    def requeue_blocked_step(self, workflow_id: str, step_id: str) -> bool:
        key = f"workflow_graph:{workflow_id}"
        raw = self._redis.hget(key, step_id)
        if raw is None:
            return False
        data = json.loads(raw)
        if data.get("status") != "blocked":
            return False
        if not data.get("blocked_by"):
            return False
        if not self.are_dependencies_met(workflow_id, step_id):
            return False
        data.update({"status": "pending", "updated_at": time.time()})
        data.pop("blocked_by", None)
        pipe = self._redis.pipeline(transaction=True)
        pipe.hset(key, mapping={step_id: json.dumps(data)})
        pipe.xadd(f"ledgers:{workflow_id}", {
            "event": "step_requeued",
            "step_id": step_id,
            "timestamp": str(time.time()),
        })
        pipe.expire(f"ledgers:{workflow_id}", self._ttl_seconds)
        pipe.execute()
        return True

    def claim_step(
        self,
        workflow_id: str,
        step_id: str,
        agent_id: str,
        lease_seconds: int = 60,
    ) -> bool:
        """Atomically lease a step to one execution identity."""
        lock_key = f"step_lock:{workflow_id}:{step_id}"
        cancelled_key = f"workflow_cancelled:{workflow_id}"
        lease_seconds = max(1, int(lease_seconds))
        graph_key = f"workflow_graph:{workflow_id}"
        owner_id = agent_id.split(":", 1)[0]
        pipe = self._redis.pipeline()
        while True:
            try:
                pipe.watch(lock_key, graph_key, cancelled_key)
                if pipe.exists(cancelled_key) or pipe.exists(lock_key):
                    pipe.unwatch()
                    return False
                raw = pipe.hget(graph_key, step_id)
                if raw is None:
                    pipe.unwatch()
                    return False
                data = json.loads(raw)
                if data.get("status") != "pending":
                    pipe.unwatch()
                    return False
                graph = {
                    str(dependency_id): json.loads(value)
                    for dependency_id, value in pipe.hgetall(graph_key).items()
                }
                if not self._dependencies_authorize(data, graph):
                    pipe.unwatch()
                    return False
                now = time.time()
                data.update({
                    "status": "in_progress",
                    "claimed_by": owner_id,
                    "claim_id": agent_id,
                    "claim_expires_at": now + lease_seconds,
                    "updated_at": now,
                })
                pipe.multi()
                pipe.set(lock_key, agent_id, ex=lease_seconds)
                pipe.hset(graph_key, mapping={step_id: json.dumps(data)})
                pipe.xadd(f"ledgers:{workflow_id}", {
                    "event": "step_claimed",
                    "step_id": step_id,
                    "agent_id": owner_id,
                    "claim_id": agent_id,
                    "timestamp": str(now),
                })
                pipe.expire(f"ledgers:{workflow_id}", self._ttl_seconds)
                pipe.execute()
                return True
            except redis.WatchError:
                continue

    def resume_workflow_step(
        self,
        workflow_id: str,
        step_id: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Requeue a waiting step on the same peer with durable resume context."""
        graph_key = f"workflow_graph:{workflow_id}"
        pipe = self._redis.pipeline()
        while True:
            try:
                pipe.watch(graph_key)
                raw = pipe.hget(graph_key, step_id)
                if raw is None:
                    pipe.unwatch()
                    raise KeyError(step_id)
                data = json.loads(raw)
                if data.get("status") != "waiting":
                    pipe.unwatch()
                    raise ValueError(f"Step {step_id!r} is not waiting")
                owner = data.get("completed_by") or data.get("claimed_by")
                data.update({
                    "status": "pending",
                    "resume_agent_id": owner,
                    "resume_context": dict(context or {}),
                    "updated_at": time.time(),
                })
                data.pop("blocked_by", None)
                pipe.multi()
                pipe.hset(graph_key, mapping={step_id: json.dumps(data, default=str)})
                pipe.sadd("jarviscore:active_workflows", workflow_id)
                pipe.xadd(f"ledgers:{workflow_id}", {
                    "event": "step_resumed",
                    "step_id": step_id,
                    "agent_id": str(owner or ""),
                    "timestamp": str(time.time()),
                })
                pipe.expire(f"ledgers:{workflow_id}", self._ttl_seconds)
                pipe.execute()
                return data
            except redis.WatchError:
                continue

    def renew_step_claim(
        self,
        workflow_id: str,
        step_id: str,
        agent_id: str,
        lease_seconds: int = 60,
    ) -> bool:
        lock_key = f"step_lock:{workflow_id}:{step_id}"
        cancelled_key = f"workflow_cancelled:{workflow_id}"
        graph_key = f"workflow_graph:{workflow_id}"
        lease_seconds = max(1, int(lease_seconds))
        pipe = self._redis.pipeline()
        while True:
            try:
                pipe.watch(lock_key, graph_key, cancelled_key)
                if pipe.exists(cancelled_key) or pipe.get(lock_key) != agent_id:
                    pipe.unwatch()
                    return False
                raw = pipe.hget(graph_key, step_id)
                if raw is None:
                    pipe.unwatch()
                    return False
                data = json.loads(raw)
                data.update({
                    "claimed_by": agent_id.split(":", 1)[0],
                    "claim_expires_at": time.time() + lease_seconds,
                    "updated_at": time.time(),
                })
                pipe.multi()
                pipe.expire(lock_key, lease_seconds)
                pipe.hset(graph_key, mapping={step_id: json.dumps(data)})
                pipe.execute()
                return True
            except redis.WatchError:
                continue

    def recover_expired_step_claim(self, workflow_id: str, step_id: str) -> bool:
        lock_key = f"step_lock:{workflow_id}:{step_id}"
        cancelled_key = f"workflow_cancelled:{workflow_id}"
        graph_key = f"workflow_graph:{workflow_id}"
        pipe = self._redis.pipeline()
        while True:
            try:
                pipe.watch(lock_key, graph_key, cancelled_key)
                if pipe.exists(cancelled_key) or pipe.exists(lock_key):
                    pipe.unwatch()
                    return False
                raw = pipe.hget(graph_key, step_id)
                if raw is None:
                    pipe.unwatch()
                    return False
                data = json.loads(raw)
                if data.get("status") != "in_progress":
                    pipe.unwatch()
                    return False
                data.update({"status": "pending", "updated_at": time.time()})
                data.pop("claimed_by", None)
                data.pop("claim_expires_at", None)
                pipe.multi()
                pipe.hset(graph_key, mapping={step_id: json.dumps(data)})
                pipe.xadd(f"ledgers:{workflow_id}", {
                    "event": "step_claim_expired",
                    "step_id": step_id,
                    "timestamp": str(time.time()),
                })
                pipe.expire(f"ledgers:{workflow_id}", self._ttl_seconds)
                pipe.execute()
                return True
            except redis.WatchError:
                continue

    def finish_claimed_step(
        self,
        workflow_id: str,
        step_id: str,
        agent_id: str,
        output: Any,
        *,
        status: str | None = None,
    ) -> bool:
        """Commit output and terminal status only while the caller owns the lease."""
        lock_key = f"step_lock:{workflow_id}:{step_id}"
        cancelled_key = f"workflow_cancelled:{workflow_id}"
        graph_key = f"workflow_graph:{workflow_id}"
        output_key = f"step_output:{workflow_id}:{step_id}"
        projection_key = f"workflow_obligations:{workflow_id}"
        result_status = output.get("status") if isinstance(output, dict) else None
        terminal = status or terminal_step_status(result_status)
        if terminal not in {"completed", "failed", "waiting", "blocked"}:
            raise ValueError(f"Invalid terminal step status: {terminal}")
        try:
            serialized = json.dumps(output) if output is not None else None
        except Exception:
            serialized = str(output)
        if serialized and len(serialized) > self._STEP_OUTPUT_MAX_BYTES:
            serialized = json.dumps({
                "_overflow": True,
                "_size_bytes": len(serialized),
                "_preview": serialized[: self._STEP_OUTPUT_PREVIEW_BYTES],
                "_note": (
                    "Output exceeded STEP_OUTPUT_MAX_BYTES. Retrieve full result "
                    f"from blob storage using workflow_id={workflow_id}, step_id={step_id}."
                ),
            })
        pipe = self._redis.pipeline()
        while True:
            try:
                pipe.watch(lock_key, graph_key, projection_key, cancelled_key)
                if pipe.exists(cancelled_key) or pipe.get(lock_key) != agent_id:
                    pipe.unwatch()
                    return False
                raw = pipe.hget(graph_key, step_id)
                if raw is None:
                    pipe.unwatch()
                    return False
                data = json.loads(raw)
                now = time.time()
                interpretation = (
                    output.get("interpretation") if isinstance(output, dict) else None
                )
                data.update({
                    "status": terminal,
                    "completed_by": agent_id.split(":", 1)[0],
                    "claim_id": agent_id,
                    "updated_at": now,
                })
                if isinstance(interpretation, dict):
                    data["semantic_outcome"] = interpretation.get("verdict")
                    data["semantic_decision"] = interpretation.get("decision")
                raw_projection = pipe.get(projection_key)
                projection = json.loads(raw_projection) if raw_projection else {}
                for obligation_id in map(str, data.get("covers", [])):
                    record = projection.get(obligation_id)
                    if not record or step_id not in record.get("current_step_ids", []):
                        continue
                    satisfied = set(map(str, interpretation.get(
                        "satisfied_requirements", []
                    ))) if isinstance(interpretation, dict) else set()
                    unmet = set(map(str, interpretation.get(
                        "unmet_requirements", []
                    ))) if isinstance(interpretation, dict) else set()
                    verdict = str(interpretation.get("verdict") or "") if isinstance(
                        interpretation, dict
                    ) else ""
                    if obligation_id in satisfied or verdict == "satisfied":
                        attempt_state = "satisfied"
                    elif terminal == "waiting":
                        attempt_state = "pending"
                    elif obligation_id in unmet or isinstance(interpretation, dict):
                        attempt_state = "unresolved"
                    else:
                        attempt_state = (
                            "satisfied" if terminal == "completed" else "unresolved"
                        )
                    attempt_states = {
                        **record.get("attempt_states", {}),
                        step_id: attempt_state,
                    }
                    attempt_interpretations = dict(
                        record.get("attempt_interpretations", {})
                    )
                    if isinstance(interpretation, dict):
                        attempt_interpretations[step_id] = interpretation
                    states = list(attempt_states.values())
                    state = (
                        "satisfied" if "satisfied" in states
                        else "pending" if "pending" in states
                        else "unresolved"
                    )
                    projection[obligation_id] = {
                        **record,
                        "state": state,
                        "attempt_states": attempt_states,
                        "attempt_interpretations": attempt_interpretations,
                    }
                data.pop("claim_expires_at", None)
                data.pop("resume_agent_id", None)
                data.pop("resume_context", None)
                mapping = {
                    "output": serialized,
                    "summary": "",
                    "context_vars": "{}",
                    "timestamp": now,
                }
                pipe.multi()
                pipe.hset(output_key, mapping={k: v for k, v in mapping.items() if v is not None})
                pipe.expire(output_key, self._ttl_seconds)
                pipe.hset(graph_key, mapping={step_id: json.dumps(data)})
                if projection:
                    pipe.set(projection_key, json.dumps(projection, default=str))
                    pipe.expire(projection_key, self._ttl_seconds)
                pipe.xadd(f"ledgers:{workflow_id}", {
                    "event": f"step_{terminal}",
                    "step_id": step_id,
                    "agent_id": agent_id.split(":", 1)[0],
                    "claim_id": agent_id,
                    "timestamp": str(now),
                })
                pipe.expire(f"ledgers:{workflow_id}", self._ttl_seconds)
                pipe.delete(lock_key)
                pipe.execute()
                return True
            except redis.WatchError:
                continue

    def continue_claimed_step(
        self,
        workflow_id: str,
        step_id: str,
        claim_id: str,
        *,
        resume_agent_id: str,
    ) -> bool:
        """Release an exhausted epoch without terminalizing its durable step."""
        lock_key = f"step_lock:{workflow_id}:{step_id}"
        graph_key = f"workflow_graph:{workflow_id}"
        cancelled_key = f"workflow_cancelled:{workflow_id}"
        pipe = self._redis.pipeline()
        while True:
            try:
                pipe.watch(lock_key, graph_key, cancelled_key)
                if pipe.exists(cancelled_key) or pipe.get(lock_key) != claim_id:
                    pipe.unwatch()
                    return False
                raw = pipe.hget(graph_key, step_id)
                if raw is None:
                    pipe.unwatch()
                    return False
                data = json.loads(raw)
                now = time.time()
                data.update({
                    "status": "pending",
                    "resume_agent_id": resume_agent_id,
                    "resume_context": {
                        "_resume": True,
                        "_new_execution_epoch": True,
                    },
                    "updated_at": now,
                    "execution_epochs": int(data.get("execution_epochs") or 1) + 1,
                })
                data.pop("claim_expires_at", None)
                pipe.multi()
                pipe.hset(graph_key, mapping={step_id: json.dumps(data, default=str)})
                pipe.xadd(f"ledgers:{workflow_id}", {
                    "event": "step_epoch_continued",
                    "step_id": step_id,
                    "agent_id": resume_agent_id,
                    "claim_id": claim_id,
                    "timestamp": str(now),
                })
                pipe.expire(f"ledgers:{workflow_id}", self._ttl_seconds)
                pipe.delete(lock_key)
                pipe.execute()
                return True
            except redis.WatchError:
                continue

    def get_step_definition(self, workflow_id: str, step_id: str) -> Optional[Dict]:
        """Get full step definition (task, agent, deps) from workflow DAG."""
        key = f"workflow_graph:{workflow_id}"
        raw = self._redis.hget(key, step_id)
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return None

    def register_active_workflow(self, workflow_id: str) -> None:
        """Register a workflow as active so distributed workers can discover it."""
        key = "jarviscore:active_workflows"
        self._redis.sadd(key, workflow_id)
        self._redis.expire(key, self._ttl_seconds)

    def get_active_workflows(self) -> List[str]:
        """Return all active workflow IDs (published by WorkflowEngine on execute())."""
        return list(self._redis.smembers("jarviscore:active_workflows"))

    def get_all_step_ids(self, workflow_id: str) -> List[str]:
        """Return all step IDs stored in the workflow DAG hash."""
        return list(self._redis.hkeys(f"workflow_graph:{workflow_id}"))

    # ------------------------------------------------------------------
    # Workflow State (crash recovery)
    # ------------------------------------------------------------------

    def save_workflow_state(self, workflow_id: str, state_json: str) -> bool:
        """Save full workflow state for crash recovery."""
        key = f"workflow_state:{workflow_id}"
        self._redis.set(key, state_json, ex=self._ttl_seconds)
        return True

    def load_workflow_state(self, workflow_id: str) -> Optional[str]:
        """Load workflow state for crash recovery."""
        key = f"workflow_state:{workflow_id}"
        return self._redis.get(key)

    # ------------------------------------------------------------------
    # Episodic Ledger
    # ------------------------------------------------------------------

    def append_ledger_entry(self, workflow_id: str, entry: Dict) -> str:
        """Append entry to episodic ledger (Redis Stream)."""
        key = f"ledgers:{workflow_id}"
        entry_data = {k: json.dumps(v) if not isinstance(v, str) else v
                      for k, v in entry.items()}
        entry_id = self._redis.xadd(key, entry_data)
        self._redis.expire(key, self._ttl_seconds)
        return entry_id

    def get_ledger_tail(self, workflow_id: str,
                        count: int = 10) -> List[Dict]:
        """Read recent ledger entries."""
        key = f"ledgers:{workflow_id}"
        entries = self._redis.xrevrange(key, count=count)
        results = []
        for entry_id, data in entries:
            parsed = {"_id": entry_id}
            for k, v in data.items():
                try:
                    parsed[k] = json.loads(v)
                except (json.JSONDecodeError, TypeError):
                    parsed[k] = v
            results.append(parsed)
        return list(reversed(results))  # Chronological order

    def get_ledger_full(self, workflow_id: str) -> List[Dict]:
        """Read all ledger entries in chronological order (XRANGE *)."""
        key = f"ledgers:{workflow_id}"
        entries = self._redis.xrange(key)
        results = []
        for entry_id, data in entries:
            parsed = {"_id": entry_id}
            for k, v in data.items():
                try:
                    parsed[k] = json.loads(v)
                except (json.JSONDecodeError, TypeError):
                    parsed[k] = v
            results.append(parsed)
        return results

    # ------------------------------------------------------------------
    # Long-Term Memory (LTM)
    # ------------------------------------------------------------------

    def save_ltm(self, workflow_id: str, summary: str,
                 ttl_days: int = 7) -> bool:
        """Save compressed LTM summary to Redis with configurable TTL."""
        key = f"ltm:{workflow_id}"
        self._redis.set(key, summary, ex=ttl_days * 86400)
        return True

    def load_ltm(self, workflow_id: str) -> Optional[str]:
        """Load LTM summary from Redis."""
        key = f"ltm:{workflow_id}"
        raw = self._redis.get(key)
        if raw is None:
            return None
        return raw if isinstance(raw, str) else raw.decode()

    # ------------------------------------------------------------------
    # Checkpoints (per-step state snapshots)
    # ------------------------------------------------------------------

    def save_checkpoint(self, workflow_id: str, step_id: str,
                        state_json: str) -> bool:
        """Save kernel state checkpoint for resume."""
        key = f"checkpoint:{workflow_id}:{step_id}"
        self._redis.set(key, state_json, ex=self._ttl_seconds)
        return True

    def load_checkpoint(self, workflow_id: str,
                        step_id: str) -> Optional[str]:
        """Load kernel state checkpoint."""
        key = f"checkpoint:{workflow_id}:{step_id}"
        return self._redis.get(key)

    # ------------------------------------------------------------------
    # Trace Events
    # ------------------------------------------------------------------

    def publish_trace_event(self, channel: str, event: Dict) -> int:
        """Publish trace event to Redis PubSub + persist to List."""
        serialized = json.dumps(event)
        # PubSub for real-time streaming
        receivers = self._redis.publish(channel, serialized)
        # List for replay/audit
        list_key = f"trace_log:{channel}"
        self._redis.rpush(list_key, serialized)
        self._redis.expire(list_key, self._ttl_seconds)
        return receivers

    # ------------------------------------------------------------------
    # Human-in-the-Loop (HITL)
    # ------------------------------------------------------------------

    def create_hitl_request(self, workflow_id: str, step_id: str,
                            payload: Dict) -> Dict:
        """Create a HITL request for human approval/input."""
        key = f"hitl_request:{workflow_id}:{step_id}"
        request_id = f"hitl-{workflow_id}-{step_id}-{int(time.time())}"
        data = {
            "request_id": request_id,
            "status": "pending",
            "payload": json.dumps(payload),
            "created_at": time.time(),
        }
        self._redis.hset(key, mapping={k: str(v) for k, v in data.items()})
        self._redis.expire(key, self._ttl_seconds)
        logger.info(f"HITL request created: {request_id}")
        return {"request_id": request_id, "status": "pending"}

    def get_hitl_request(self, workflow_id: str,
                         step_id: str) -> Optional[Dict]:
        """Read HITL request status and human response."""
        key = f"hitl_request:{workflow_id}:{step_id}"
        data = self._redis.hgetall(key)
        if not data:
            return None
        result = dict(data)
        if "payload" in result:
            try:
                result["payload"] = json.loads(result["payload"])
            except (json.JSONDecodeError, TypeError):
                pass
        return result

    def resolve_hitl_request(self, workflow_id: str, step_id: str,
                             decision: str, responder: str = "",
                             comment: str = "") -> bool:
        """Record human decision on a HITL request (legacy untyped API)."""
        key = f"hitl_request:{workflow_id}:{step_id}"
        if not self._redis.exists(key):
            return False
        updates = {
            "status": HITLStatus.resolved.value,
            "decision": normalize_hitl_decision(decision).value,
            "responder": responder,
            "comment": comment,
            "resolved_at": str(time.time()),
        }
        self._redis.hset(key, mapping=updates)
        logger.info(f"HITL resolved: {workflow_id}/{step_id} -> {decision}")
        return True

    # ── Typed HITL API (preferred) ────────────────────────────────────────────

    def create_hitl_request_typed(self, request: HITLRequest) -> HITLRequest:
        """
        Persist a typed HITLRequest to Redis.

        Preferred over create_hitl_request() — validates the contract before
        writing and returns the persisted object with any defaults applied.
        """
        key = f"hitl_request:{request.workflow_id}:{request.step_id}"
        self._redis.hset(key, mapping=request.to_redis_mapping())
        self._redis.expire(key, self._ttl_seconds)
        logger.info(f"HITL request created (typed): {request.request_id}")
        return request

    def get_hitl_resolution(self, workflow_id: str,
                            step_id: str) -> Optional[HITLResolution]:
        """
        Return a typed HITLResolution if the request has been resolved.

        Returns None if the request is still pending, not found, or expired.
        This is the typed counterpart to get_hitl_request() — preferred for
        kernel polling.
        """
        raw = self.get_hitl_request(workflow_id, step_id)
        if not raw:
            return None
        return HITLResolution.from_raw(raw)

    # ------------------------------------------------------------------
    # Function Registry Index (Cognitive Projection)
    # ------------------------------------------------------------------

    def save_registry_index(self, index: Dict) -> bool:
        """Persist registry capability index for shared discovery.

        Stores a compact summary of all registered functions, indexed
        by system, with capability counts and graduation stage breakdown.
        Used by the kernel and other agents for function discovery.

        Args:
            index: Registry index dict with systems, capabilities, stages

        Returns:
            True if saved successfully
        """
        key = "registry:index"
        self._redis.set(key, json.dumps(index), ex=self._ttl_seconds)
        logger.debug(f"Registry index saved: {index.get('total_functions', 0)} functions")
        return True

    def get_registry_index(self) -> Optional[Dict]:
        """Retrieve registry capability index.

        Returns:
            Registry index dict, or None if not found
        """
        key = "registry:index"
        data = self._redis.get(key)
        if data:
            return json.loads(data)
        return None

    # ------------------------------------------------------------------
    # Agent Telemetry (schema-enforced write path)
    # ------------------------------------------------------------------

    def publish_agent_telemetry(
        self,
        agent_id: str,
        action: str,
        note: str = "",
        team: str = "",
        extra: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        Write a structured telemetry event for an agent.

        Enforces a canonical field schema so consumers can use a single
        field path instead of double-fallback heuristics.

        Canonical fields written to ``agent:telemetry:{agent_id}``:
            agent, team, action, note, timestamp

        Args:
            agent_id: The agent's unique identifier (e.g. "researcher", "planner")
            action:   Short verb describing the action (e.g. "task_completed", "step_started")
            note:     Human-readable description for activity feeds and dashboards
            team:     Logical team or group the agent belongs to (caller-supplied)
            extra:    Optional additional string-valued fields to merge into the record

        Returns:
            True if written successfully
        """
        key = f"agent:telemetry:{agent_id}"
        mapping: Dict[str, str] = {
            "agent":     agent_id,
            "team":      team,
            "action":    action,
            "note":      note[:500],
            "timestamp": str(time.time()),
        }
        if extra:
            for k, v in extra.items():
                mapping[k] = str(v)[:500]
        try:
            # Verify the key is a hash (or absent) before writing
            key_type = self._redis.type(key)
            if key_type not in ("hash", "none"):
                # Wrong type — delete stale key and rewrite
                self._redis.delete(key)
            self._redis.hset(key, mapping=mapping)
            self._redis.expire(key, self._ttl_seconds)
            return True
        except Exception as exc:
            logger.warning("publish_agent_telemetry failed for %s: %s", agent_id, exc)
            return False

    # ------------------------------------------------------------------
    # Locking (for atomic registry operations)
    # ------------------------------------------------------------------

    def lock(self, key: str, timeout: int = 30):
        """Acquire a Redis lock (returns context manager)."""
        return self._redis.lock(f"lock:{key}", timeout=timeout)

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    def ping(self) -> bool:
        """Check Redis connectivity."""
        try:
            return self._redis.ping()
        except redis.ConnectionError:
            return False

    def flush_workflow(self, workflow_id: str) -> int:
        """Delete all keys for a workflow (cleanup)."""
        pattern = f"*:{workflow_id}*"
        keys = list(self._redis.scan_iter(match=pattern))
        if keys:
            return self._redis.delete(*keys)
        return 0
