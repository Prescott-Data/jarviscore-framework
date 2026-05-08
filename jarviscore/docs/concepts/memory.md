---
icon: material/database
---

# Memory

JarvisCore agents maintain state across OODA loop turns through a four-tier memory system. Each tier serves a distinct purpose: fast in-turn working state, a durable audit trail, compressed long-horizon context, and cross-session semantic recall.

The tiers compose automatically. You interact with all of them through a single object: `UnifiedMemory`.

---

## The Four Memory Tiers

### Tier 1: Working Scratchpad

The `WorkingScratchpad` holds the agent's active reasoning notes for the current workflow step. It is backed by blob storage (local filesystem or Azure Blob) and is scoped to a single `(workflow_id, step_id, agent_id)` tuple.

Every call to `UnifiedMemory.log_turn()` appends a JSONL entry to the scratchpad. The scratchpad is included in the `rehydrate_bundle()` output as a formatted markdown string, which the Kernel injects into its context window at the start of each turn.

The scratchpad is ephemeral relative to the session: it is created fresh for each step and is not carried across steps. Use the Episodic Ledger and LTM for cross-step continuity.

**Activates when:** `blob_storage` is provided to `UnifiedMemory`.

### Tier 2: Episodic Ledger

The `EpisodicLedger` is an append-only, ordered log of every turn event in a workflow. It is backed by a Redis Stream (key: `ledgers:{workflow_id}`) with a default TTL of seven days.

Each entry records the turn ID, timestamp, thought, action, result, and token count. The ledger provides the complete chronological audit trail for a workflow execution.

During context assembly, the Kernel reads the last N entries via `tail(count)` rather than the full history, keeping the context window bounded regardless of how long the workflow runs.

**Activates when:** `redis_store` is provided to `UnifiedMemory`.

### Tier 3: Long-Term Memory

`LongTermMemory` stores compressed summaries of episodic history. When a workflow accumulates enough turns that including the full ledger would exceed the context window, the Kernel calls `LongTermMemory.compress()`, which uses the LLM to distil the episodic entries into a compact narrative.

The summary is written to two stores simultaneously:

- Redis (key: `ltm:{workflow_id}`, seven-day TTL) for fast retrieval on the hot path.
- Blob storage (`workflows/{wf_id}/ltm/summary.txt`) as a durable backup with no expiry.

On `load_summary()`, Redis is tried first. If the key has expired (for example after a crash and Redis restart), the summary is read from blob storage and the Redis cache is repopulated.

**Activates when:** both `redis_store` and `blob_storage` are provided to `UnifiedMemory`.

### Tier 4: Athena MemOS

Athena is an external memory service that provides cross-session, semantically searchable memory. It is the only tier that persists context beyond a single workflow execution.

Athena operates its own three-tier pipeline internally:

| Athena tier | Storage backend | Purpose |
|---|---|---|
| Short-Term Memory (STM) | Redis | Timestamped event stream for the active session |
| Mid-Term Memory (MTM) | MongoDB and Milvus | Cognitive chains grouped by topic with heat scoring |
| Long-Term Memory (LTM) | ArangoDB | Knowledge graph built from consolidated chains |

When Athena is configured, `UnifiedMemory.log_turn()` writes the thought and action outcome to Athena STM on every turn. On `rehydrate_bundle()`, the Kernel receives `athena_context`, which includes recent STM events and the highest-heat MTM chains. This context spans sessions: an agent restarted after a crash recovers not just its last checkpoint but its accumulated semantic understanding of the domain.

**Activates when:** `ATHENA_URL` is set and `athena_client` is passed to `UnifiedMemory`.

---

## UnifiedMemory API

`UnifiedMemory` is the single object the Kernel uses for all memory operations. It is instantiated by the Mesh during agent setup; you do not construct it directly in normal usage.

```python
from jarviscore.memory import UnifiedMemory

mem = UnifiedMemory(
    workflow_id="wf-abc123",
    step_id="step-1",
    agent_id="researcher",
    redis_store=redis_store,        # Optional — enables Tiers 2 and 3
    blob_storage=blob_storage,      # Optional — enables Tiers 1 and 3
    athena_client=athena_client,    # Optional — enables Tier 4
)
```

### log_turn

Records a single OODA loop turn to all active tiers.

```python
await mem.log_turn(
    turn_id="t1",
    thought="Identifying relevant data sources for the market analysis.",
    action="http_get",
    result="200 OK — retrieved 42 records",
    tokens=1240,
)
```

| Parameter | Type | Description |
|---|---|---|
| `turn_id` | `str` | Unique identifier for this turn within the step (e.g. `"t1"`, `"t2"`) |
| `thought` | `str` | The Kernel's reasoning text for this turn |
| `action` | `str` | The action taken: tool name, sub-agent call, or decision type |
| `result` | `str` | The outcome or observation returned by the action |
| `tokens` | `int` | Token count used this turn, for budget tracking |

### save_checkpoint

Saves a JSON snapshot of the Kernel's internal state to Redis. Used for crash recovery.

```python
await mem.save_checkpoint(json.dumps(kernel_state))
```

### load_checkpoint

Loads the most recent checkpoint from Redis.

```python
state_json = await mem.load_checkpoint()
if state_json:
    kernel_state = json.loads(state_json)
```

### rehydrate_bundle

Assembles the full context bundle for Kernel cold-start or crash recovery. Returns a dict with the following keys:

| Key | Type | Source |
|---|---|---|
| `ltm_summary` | `str` or `None` | LongTermMemory — compressed narrative |
| `recent_turns` | `list` | EpisodicLedger — last N turns |
| `checkpoint` | `str` or `None` | Redis — last Kernel state snapshot |
| `scratchpad` | `str` | WorkingScratchpad — current working notes |
| `athena_context` | `dict` or `None` | Athena — STM events and MTM chains |

```python
bundle = await mem.rehydrate_bundle(ledger_tail=10)
```

The `ledger_tail` parameter controls how many recent episodic entries are included. The default is `10`. Increase it for tasks that require broader recent context; decrease it if you are operating under a strict token budget.

---

## Tier Degradation

`UnifiedMemory` degrades gracefully when storage backends are absent. The active tiers at runtime depend on what was provided to the constructor.

| `redis_store` | `blob_storage` | `athena_client` | Active tiers |
|---|---|---|---|
| Not set | Not set | Not set | None (pure in-process run) |
| Set | Not set | Not set | Episodic Ledger only |
| Not set | Set | Not set | Working Scratchpad only |
| Set | Set | Not set | Scratchpad, Episodic Ledger, LTM |
| Set | Set | Set | All four tiers |

When a tier is inactive, all writes to it are no-ops and all reads return empty defaults. The Kernel continues to function correctly; it simply has less historical context available.

---

## The AthenaMemory Bridge

`AthenaMemory` is the per-agent object that manages the Athena STM/MTM session. It is created lazily the first time `UnifiedMemory._get_athena_memory()` is awaited.

You can use `AthenaMemory` directly for lower-level Athena operations:

```python
from jarviscore.memory import get_athena_client, AthenaMemory

athena = get_athena_client()
if athena:
    am = await AthenaMemory.create(
        agent_id="researcher",
        client=athena,
        redis_store=redis_store,
    )
    await am.on_task_assigned("task-1", "Analyse Q1 revenue trends", "researcher")
    ctx = await am.get_memory_context(limit=15)
```

The `get_athena_client()` factory reads `ATHENA_URL` and `ATHENA_TENANT_ID` from the environment and returns `None` if `ATHENA_URL` is not set. This lets you safely call `get_athena_client()` unconditionally and treat the result as optional.

---

## Setting Up Athena

Athena runs as a Docker-composed stack. The `jarviscore memory init` command automates the setup from source.

```bash
git clone https://github.com/Prescott-Data/athena ~/athena
jarviscore memory init
```

`memory init` performs the following steps automatically:

1. Locates the Athena source repository at `~/athena` or at the path set in `ATHENA_DIR`.
2. Detects an LLM API key from the current environment (prefers Gemini, then Anthropic, then OpenAI).
3. Builds and starts all Athena services with `docker compose up -d --build`.
4. Waits up to 90 seconds for the Athena health endpoint to return `ok`.
5. Writes `ATHENA_URL=http://localhost:8080` to the project `.env` file.

After setup, verify that all memory tiers are reachable:

```bash
jarviscore memory status
```

!!! note "First-build duration"
    The first `memory init` build takes approximately two minutes because it compiles the Milvus vector database from source. Subsequent starts use Docker layer caching and complete in under 10 seconds.

---

## Managing Agent Memory via the CLI

The `jarviscore memory` command group provides operational access to agent memory state at runtime.

```bash
# Inspect recent STM events and MTM chains for an agent
jarviscore memory context --agent researcher

# Semantic search across an agent's full memory
jarviscore memory search --agent researcher --query "market analysis findings"

# Check health of all memory tiers
jarviscore memory status
```

See the [CLI Reference](../reference/cli.md) for the complete argument specification for each subcommand.

---

## Further Reading

- [Athena MemOS (GitHub)](https://github.com/Prescott-Data/athena) — Open-source memory operating system: STM/MTM/LTM pipeline, vector store, and knowledge graph
- [CLI Reference: memory](../reference/cli.md#jarviscore-memory) — Full argument specification for `jarviscore memory` subcommands
- [Architecture Overview](architecture.md) — How memory fits into the OODA loop and the Kernel execution model
