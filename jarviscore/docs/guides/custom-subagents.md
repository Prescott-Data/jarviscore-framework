---
icon: material/layers-triple-outline
---

# Custom Sub-agents

Sub-agents are the specialised execution units that live inside the Kernel and run the OODA loop for every task dispatch. JarvisCore ships four: `CoderSubAgent`, `ResearcherSubAgent`, `CommunicatorSubAgent`, and `BrowserSubAgent`. When none of these fit your needs, you can subclass `BaseSubAgent` to build a fifth.

> [!NOTE]
> Custom sub-agents are a Kernel-layer extensibility point, not a replacement for `AutoAgent` or `CustomAgent`. Build one when you have a narrow, repeatable task class (database queries, PDF parsing, structured validation) that the four built-in sub-agents handle poorly on every invocation.

---

## What a sub-agent is

A sub-agent is not a mesh agent. It has no `role` in peer discovery, cannot be addressed by `peers`, and is never added to the Mesh directly. It is an internal worker that the Kernel dispatches to when it classifies a task.

Each sub-agent exposes a **system prompt** that shapes LLM behaviour and a **tool set** that defines what the LLM can call. The OODA loop, convergence governor, epistemic ledger, failure ledger, and token budget tracking are all inherited from `BaseSubAgent`. You provide the prompt and the tools.

The Kernel caches sub-agents by `(step_id, role)`, they are reused within a workflow step and destroyed when the step completes.

---

## The two mandatory methods

### `get_system_prompt() -> str`

Returns the system prompt injected at the top of every LLM call. The base class appends the tool list and the THOUGHT/TOOL/DONE protocol automatically, do not include those.

### `setup_tools() -> None`

Called by `BaseSubAgent.__init__()`. Register every tool the LLM can call using `register_tool()`:

```python
def register_tool(
    self,
    name: str,           # String the LLM emits in TOOL: <name>
    func: Callable,      # Async or sync callable
    description: str,    # Shown to LLM; include param schema
    phase: str = "action",  # "action" or "thinking" — informational only
)
```

---

## Full implementation example

```python title="my_agent/subagents/database.py"
from jarviscore.kernel.subagent import BaseSubAgent
import asyncpg

class DatabaseSubAgent(BaseSubAgent):
    SYSTEM_PROMPT = """
    You are a DATABASE QUERY SPECIALIST.
    Rules:
    1. Only use SELECT — never INSERT, UPDATE, DELETE, or DROP.
    2. Limit results to 100 rows unless the task says otherwise.
    3. Include the query and row count in your DONE summary.
    """

    def __init__(self, agent_id: str, llm_client, db_dsn: str, **kwargs):
        self._db_dsn = db_dsn    # assign BEFORE super().__init__()
        self._conn = None
        super().__init__(agent_id=agent_id, role="database", llm_client=llm_client, **kwargs)

    def get_system_prompt(self) -> str:
        return self.SYSTEM_PROMPT

    def setup_tools(self) -> None:
        self.register_tool("query",          self._tool_query,          'Run a SELECT. Params: {"sql": "<query>"}',      phase="action")
        self.register_tool("list_tables",    self._tool_list_tables,    "List public tables. Params: {}",                phase="thinking")
        self.register_tool("describe_table", self._tool_describe_table, 'Column info. Params: {"table": "<name>"}',      phase="thinking")

    # Lifecycle hooks ────────────────────────────────────────────────────────

    async def _pre_run_hook(self, state) -> None:
        self._conn = await asyncpg.connect(self._db_dsn)

    async def _post_run_hook(self) -> None:
        if self._conn:
            await self._conn.close()
            self._conn = None

    # Tool implementations ───────────────────────────────────────────────────

    async def _tool_query(self, sql: str, **kwargs):
        if not self._conn:
            return {"status": "error", "error": "No DB connection"}
        try:
            rows = await self._conn.fetch(sql)
            return {"status": "success", "rows": [dict(r) for r in rows[:100]], "count": len(rows)}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    async def _tool_list_tables(self, **kwargs):
        if not self._conn:
            return {"status": "error", "error": "No DB connection"}
        rows = await self._conn.fetch(
            "SELECT table_name FROM information_schema.tables WHERE table_schema='public' ORDER BY table_name"
        )
        return {"status": "success", "tables": [r["table_name"] for r in rows]}

    async def _tool_describe_table(self, table: str, **kwargs):
        if not self._conn:
            return {"status": "error", "error": "No DB connection"}
        rows = await self._conn.fetch(
            "SELECT column_name, data_type FROM information_schema.columns WHERE table_name=$1", table
        )
        return {"status": "success", "table": table, "columns": [dict(r) for r in rows]}
```

> [!IMPORTANT]
> Always assign your instance attributes **before** calling `super().__init__()`. The base class calls `setup_tools()` during `__init__`, so any attributes your tools depend on must already exist.

---

## Lifecycle hooks

| Hook | When it runs | Common use |
|---|---|---|
| `_pre_run_hook(state)` | Before the OODA loop starts | Open connections, launch browsers, load models |
| `_post_run_hook()` | After the loop exits, even on exception | Close connections, release resources |

Both are `async`. The base class defaults are no-ops; you do not need to call `super()`.

---

## Gate hooks

Override these to intervene inside the loop without modifying it.

### `_can_complete(state, parsed) -> tuple[bool, str]`

Called when the LLM emits `DONE`. Return `(True, "")` to allow, or `(False, "reason")` to reject and keep the loop running:

```python
def _can_complete(self, state, parsed) -> tuple:
    if not parsed.get("result", {}).get("rows"):
        return False, "No rows returned — run a query before finishing."
    return True, ""
```

### `_pre_execute_hook(tool_name, params, state) -> Optional[dict]`

Called before each tool execution. Return `None` to allow, or a result dict to substitute (tool does not run):

```python
async def _pre_execute_hook(self, tool_name, params, state):
    if tool_name == "query":
        sql = params.get("sql", "").upper()
        for kw in ("INSERT", "UPDATE", "DELETE", "DROP", "TRUNCATE"):
            if kw in sql:
                return {"status": "error", "error": "Write operations are not permitted."}
    return None
```

---

## Wiring into the Kernel

The Kernel routes built-in tasks through a structured router rather than keyword matching. Custom roles still need an explicit Kernel extension so the runtime knows how to construct the sub-agent. Override `_create_subagent()` on a Kernel subclass:

```python title="my_agent/kernel_extension.py"
from jarviscore.kernel.kernel import Kernel
from my_agent.subagents.database import DatabaseSubAgent

class ExtendedKernel(Kernel):
    def __init__(self, *args, db_dsn: str, **kwargs):
        super().__init__(*args, **kwargs)
        self._db_dsn = db_dsn

    def _create_subagent(self, role: str, agent_id: str):
        if role == "database":
            return DatabaseSubAgent(
                agent_id=agent_id,
                llm_client=self.llm_client,
                db_dsn=self._db_dsn,
                redis_store=self.redis_store,
                blob_storage=self.blob_storage,
            )
        return super()._create_subagent(role, agent_id)
```

Override `_create_kernel()` on your `AutoAgent` and set `default_kernel_role` so the Kernel receives an explicit planner/profile role for this agent:

```python title="my_agent/agents/db_agent.py"
from jarviscore import AutoAgent
from my_agent.kernel_extension import ExtendedKernel

class DatabaseAgent(AutoAgent):
    role = "db-analyst"
    capabilities = ["database", "sql"]
    system_prompt = "You are a database analyst. Store results in `result`."
    default_kernel_role = "database"

    def _create_kernel(self):
        from jarviscore.execution.llm import UnifiedLLMClient
        from jarviscore.config.settings import get_settings
        settings = get_settings()
        return ExtendedKernel(
            llm_client=UnifiedLLMClient(settings),
            config={
                **settings.model_dump(),
                "kernel_role_profiles": {
                    "database": {
                        "thinking_budget": 80_000,
                        "action_budget": 40_000,
                        "max_total_tokens": 120_000,
                        "wall_clock_ms": 180_000,
                        "emergency_turn_fuse": 18,
                        "model_tier": "task",
                        "complexity": "standard",
                    },
                },
                "kernel_role_catalog": {
                    "database": "Read-only SQL/database analysis and query execution role.",
                },
            },
            db_dsn=settings.db_dsn,
            redis_store=self._redis_store,
            blob_storage=self._blob_storage,
        )
```

`kernel_role_profiles` is required for custom roles because leases, model tier
selection, context budgets, and tracing must remain explicit. `kernel_role_catalog`
is optional but recommended when the structured router may infer the custom role
instead of receiving it through `default_kernel_role`.

---

## What is inherited from `BaseSubAgent`

| Feature | Notes |
|---|---|
| OODA loop (Observe → Orient → Decide → Act) | Full loop with rolling 10-turn conversation history |
| Token budget and lease enforcement | Via `AgentCognitionManager` |
| Same-tool streak detection | Via `ConvergenceGovernor`, grants one strategic pivot, then yields |
| Repeat failure blocking | Via `FailureLedger`, fingerprints `(tool, params)` pairs |
| Duplicate search/URL blocking | Via `EpistemicLedger`, prevents wasteful re-reads before they happen |
| Trace event emission | `log_thinking`, `log_tool_start`, `log_tool_result`, `log_step_complete` |
| Memory checkpointing | Per-turn checkpoint to `UnifiedMemory` when injected by Kernel |

---

## Further Reading

- [AutoAgent Guide](./autoagent.md), built-in sub-agent roles, lease budgets, and task routing
- [Architecture Overview](../concepts/architecture.md), how Kernel, sub-agents, and OODA loop relate
- [Model Routing](../concepts/model-routing.md), assigning a model tier to a custom sub-agent role
