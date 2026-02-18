"""
Redis Context Store for JarvisCore v1.0.0.

Provides durable state for: step outputs, shared context/truth, mailbox,
workflow DAG, episodic ledger, checkpoints, trace events, and HITL requests.
"""

import json
import logging
import time
from typing import Any, Dict, List, Optional

import redis

logger = logging.getLogger(__name__)


class RedisContextStore:
    """
    Redis-backed context store for workflow state, truth, mailbox, and more.

    All keys are prefixed with workflow_id or agent_id for isolation.
    TTL is applied to prevent unbounded growth.
    """

    def __init__(self, settings=None, client: redis.Redis = None):
        """
        Initialize Redis context store.

        Args:
            settings: Settings instance with redis_* fields
            client: Pre-built Redis client (for testing with fakeredis)
        """
        if client is not None:
            self._redis = client
        elif settings is not None:
            url = getattr(settings, "redis_url", None)
            if url:
                self._redis = redis.Redis.from_url(url, decode_responses=True)
            else:
                self._redis = redis.Redis(
                    host=getattr(settings, "redis_host", "localhost"),
                    port=getattr(settings, "redis_port", 6379),
                    password=getattr(settings, "redis_password", None),
                    db=getattr(settings, "redis_db", 0),
                    decode_responses=True,
                )
        else:
            self._redis = redis.Redis(
                host="localhost", port=6379, db=0, decode_responses=True
            )

        self._ttl_seconds = getattr(settings, "redis_context_ttl_days", 7) * 86400
        self.enabled = True

        try:
            self._redis.ping()
            logger.info("RedisContextStore connected")
        except redis.ConnectionError as e:
            logger.warning(f"Redis connection failed: {e}")
            self.enabled = False

    # ------------------------------------------------------------------
    # Step Outputs
    # ------------------------------------------------------------------

    def save_step_output(self, workflow_id: str, step_id: str,
                         output: Any = None, summary: str = None,
                         context_vars: Dict = None) -> bool:
        """Save step result to Redis."""
        key = f"step_output:{workflow_id}:{step_id}"
        data = {
            "output": json.dumps(output) if output is not None else None,
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
            self._redis.hset(f"{key}:sources", source, json.dumps(list(updates.keys())))
        return True

    def merge_shared_facts(self, workflow_id: str, facts: Dict,
                           source: str = "") -> bool:
        """Merge typed TruthFacts into shared context."""
        key = f"shared_facts:{workflow_id}"
        for fact_key, fact_value in facts.items():
            serialized = json.dumps(fact_value) if not isinstance(fact_value, str) else fact_value
            self._redis.hset(key, fact_key, serialized)
        self._redis.expire(key, self._ttl_seconds)
        if source:
            meta_key = f"{key}:sources"
            self._redis.hset(meta_key, source, json.dumps(list(facts.keys())))
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
        """Send a durable message to an agent's mailbox."""
        key = f"mailbox:{target_id}"
        entry = json.dumps({
            "message": message,
            "timestamp": time.time(),
        })
        self._redis.rpush(key, entry)
        self._redis.expire(key, self._ttl_seconds)
        return True

    def read_mailbox(self, agent_id: str,
                     max_messages: int = 10) -> List[Dict]:
        """Drain messages from agent's mailbox (destructive read)."""
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
        """Non-destructive peek at agent's mailbox."""
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
    # Workflow DAG
    # ------------------------------------------------------------------

    def init_workflow_graph(self, workflow_id: str, steps: List[Dict]) -> bool:
        """Initialize Redis DAG for a workflow."""
        key = f"workflow_graph:{workflow_id}"
        graph = {}
        for step in steps:
            step_id = step.get("id") or step.get("step_id", "")
            deps = step.get("depends_on", [])
            graph[step_id] = json.dumps({
                "status": "pending",
                "depends_on": deps,
                "agent": step.get("agent", ""),
                "task": step.get("task", ""),
            })
        if graph:
            self._redis.hset(key, mapping=graph)
            self._redis.expire(key, self._ttl_seconds)
        return True

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
        self._redis.hset(key, step_id, json.dumps(data))
        return True

    def are_dependencies_met(self, workflow_id: str, step_id: str) -> bool:
        """Check if all dependencies for a step are completed."""
        key = f"workflow_graph:{workflow_id}"
        raw = self._redis.hget(key, step_id)
        if raw is None:
            return True  # No entry = no dependencies
        try:
            step_data = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return True
        deps = step_data.get("depends_on", [])
        if not deps:
            return True
        for dep_id in deps:
            dep_status = self.get_step_status(workflow_id, dep_id)
            if dep_status != "completed":
                return False
        return True

    def claim_step(self, workflow_id: str, step_id: str,
                   agent_id: str) -> bool:
        """Atomically claim a step for an agent (prevents double-execution)."""
        lock_key = f"step_lock:{workflow_id}:{step_id}"
        # SETNX-based atomic claim
        acquired = self._redis.set(lock_key, agent_id, nx=True,
                                   ex=self._ttl_seconds)
        if acquired:
            self.update_step_status(workflow_id, step_id, "in_progress")
        return bool(acquired)

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
        """Record human decision on a HITL request."""
        key = f"hitl_request:{workflow_id}:{step_id}"
        if not self._redis.exists(key):
            return False
        updates = {
            "status": "resolved",
            "decision": decision,
            "responder": responder,
            "comment": comment,
            "resolved_at": str(time.time()),
        }
        self._redis.hset(key, mapping=updates)
        logger.info(f"HITL resolved: {workflow_id}/{step_id} -> {decision}")
        return True

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
