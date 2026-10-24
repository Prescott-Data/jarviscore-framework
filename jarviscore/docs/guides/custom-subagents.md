---
icon: material/layers-triple-outline
title: "Build Custom JarvisCore Kernel Sub-Agents"
description: "Create domain-specific Kernel execution units for database queries, PDF parsing, structured validation, and other specialized agent tasks."
---

# Custom Sub-agents

Sub-agents are the specialised execution units that live inside the Kernel and run the OODA loop for every task dispatch. JarvisCore ships four: `CoderSubAgent`, `ResearcherSubAgent`, `CommunicatorSubAgent`, and `BrowserSubAgent`. When none of these fit your needs, you can subclass `BaseSubAgent` to build a fifth.

> [!NOTE]
> Custom sub-agents are a Kernel-layer extensibility point, not a replacement for `AutoAgent` or `CustomAgent`. Build one when you have a narrow, repeatable task class (database queries, PDF parsing, structured validation) that the four built-in sub-agents handle poorly on every invocation.

---

## What a sub-agent is

A sub-agent is not a mesh agent. It has no `role` in peer discovery, cannot be addressed by `peers`, and is never added to the Mesh directly. It is an internal worker that the Kernel dispatches to when it classifies a task.

Each sub-agent exposes a **system prompt** that shapes LLM behaviour and a **tool set** that defines what the LLM can call. The OODA loop, working notes, failure ledger, and token budget tracking are all inherited from `BaseSubAgent`. You provide the prompt and the tools.

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
    phase: str = "action",  # "action" or "thinking": informational only
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
    1. Only use SELECT, never INSERT, UPDATE, DELETE, or DROP.
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

### `_can_complete(state, parsed) -> tuple[bool, GateEvidence | str]`

Called when the LLM emits `DONE`. Return `(True, "")` to allow, or `(False, evidence)` to reject and keep the loop running.

Only `DONE` completes a step. `RESULT` is the structured payload that accompanies `DONE`; a `RESULT` on its own (a plan, a partial table, `{"status": "in_progress"}`) is not a completion, and the agent is asked to repair the protocol on its next turn.

Report what the agent produced, not a verdict on it:

```python
from jarviscore.kernel.gate import GateEvidence

def _can_complete(self, state, parsed) -> tuple:
    rows = parsed.get("result", {}).get("rows")
    if not rows:
        return False, GateEvidence(
            check="rows_returned",
            requirement="at least one row in the result",
            observed={
                "rows": len(rows or []),
                "query_calls": sum(1 for t in state.tool_history if t.tool_name == "query"),
            },
        )
    return True, ""
```

A verdict — *"No rows returned. Run a query before finishing."* — restates your rule in your vocabulary. The agent cannot map it onto anything it did, so its next attempt tends to be the last one reworded, and the gate becomes a loop. Counts move only when the work moves, so evidence gives the agent something it can act on and cannot talk its way past.

Leave the advice out. Naming the missing fact is the gate's job; deciding what to do about it is the agent's.

The harness watches for attempts that carry no new information — the same check failing on the same values, the same result submitted, and no tool run in between. It tells the agent when its last attempt changed nothing, and ends the step after `max_identical_done_attempts` (default 3) of them rather than letting a gate it cannot satisfy consume the lease. An agent that is still changing its output is never cut off, however many rejections it takes.

A plain string is still accepted, and is passed through as a verdict with no observations behind it.

## Product-owned Kernel roles

An application can add a domain-specific Kernel role without replacing
AutoAgent orchestration. Extend `Kernel`, construct only the additional role, and
delegate every built-in role to `super()`:

```python
from jarviscore.kernel.kernel import Kernel


class ProductKernel(Kernel):
    def _create_subagent(self, role: str, agent_id: str):
        if role == "domain_reasoner":
            subagent = DomainReasoner(
                agent_id=agent_id,
                llm_client=self.llm_client,
                redis_store=self.redis_store,
                blob_storage=self.blob_storage,
            )
            self._attach_mesh_tools(subagent)
            return subagent
        return super()._create_subagent(role, agent_id)
```

The product's shared `AutoAgent` subclass overrides `_create_kernel()` and
returns `ProductKernel` with the framework clients and current Mesh config. Add
the role to `kernel_role_profiles` and `kernel_role_catalog`; capabilities select
it through `execution_contract.kernel_role`. Product roles own domain completion
semantics, while JarvisCore continues to own routing, leases, checkpoints,
receipts, tools, and distributed execution.

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
        config = self._mesh.config if self._mesh else {}
        return ExtendedKernel(
            llm_client=self.llm,
            sandbox=self.sandbox,
            code_registry=self.code_registry,
            search_client=self.search,
            redis_store=getattr(self, "_redis_store", None),
            blob_storage=getattr(self, "_blob_storage", None),
            config={
                **config,
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
            db_dsn=config["database_dsn"],
        )
```

`kernel_role_profiles` is required for custom roles because leases, model tier
selection, context budgets, and tracing must remain explicit. `kernel_role_catalog`
is optional but recommended when the structured router may infer the custom role
instead of receiving it through `default_kernel_role`.

`AutoAgent.setup()` initializes the shared LLM, sandbox, registry, search client,
and storage handles before calling `_create_kernel()`. An override should reuse
those initialized components, as above, rather than constructing a parallel
execution stack.

---

## What is inherited from `BaseSubAgent`

| Feature | Notes |
|---|---|
| OODA loop (Observe → Orient → Decide → Act) | Full loop with at least the last 10 exchanges in view (older ones leave five at a time), carried through checkpoints so a resumed step continues the same conversation. Each turn's prompt extends the previous one, so providers that cache prompt prefixes serve most of it from cache |
| Runtime notices | The date, and the remaining tokens, wall clock and turns, are reported as facts, never stored as the agent's own thoughts. Under native tool calls the budget is stated when a run starts and again each turn once any part of it is down to a quarter, and the agent is told before exchanges leave view; text-protocol turns report the budget every turn |
| Token budget and lease enforcement | Via `AgentCognitionManager` |
| Failure record | Via `FailureLedger`, classifies and records failures; recent failures are shown to the agent, never used to refuse a call |
| Identical-call record | An exact repeat of an earlier call runs, and its result notes the earlier receipt and whether the result changed |
| Trace event emission | `log_thinking`, `log_tool_start`, `log_tool_result`, `log_step_complete` |
| Memory checkpointing | Per-turn checkpoint to `UnifiedMemory` when injected by Kernel |
| Working notes | The `working_notes` argument on any native tool call, or `NOTE: <fact>` lines on the text protocol, is written to the step's `WorkingScratchpad` and kept across epochs; notes cost no turn. A native call's notes are read in that call while it is in view and in MY WORKING NOTES after it leaves |
| Approved actions | A person's decisions are carried out once when the step resumes, before the next turn. A tool that refuses before acting returns `"performed": False`, which leaves the approval open instead of settling it |
| Parallel calls | Calls that do not depend on each other arrive in one reply and all run that turn, in order, each through the same hooks, receipts and checkpoints. A `done` sent alongside them waits for their results |
| Tool programs | `run_tool_program` lets the model call your tools from a Python program in the Kernel's sandbox (see below) |

### What the model is offered

Each turn offers your tools plus the built-ins that can act on this run. Peer tools
(`ask_peer`, `ask_capability`, `send_to_peer`, `list_peers`, `broadcast_update`,
`read_mailbox`) appear only while another agent is reachable; `remember` and
`recall` only when cross-session memory is attached; `inspect_workflow` and
`read_workflow_step` only when the step has a workflow around it; and
`read_turn_result` once an earlier result can have left the model's view. A tool
that could do nothing here would cost its schema on every turn and invite a
wasted call.

To keep a method callable but never offered to the model, name it in
`hidden_tools`:

```python
class ReportWriter(BaseSubAgent):
    hidden_tools = BaseSubAgent.hidden_tools | {"render_preview"}
```

### Tool programs

When the Kernel has a sandbox that can run code on this host, a sub-agent with its
own tools is also offered `run_tool_program`. The model writes a short Python
program that calls your tools as functions, loops over pages, filters, joins and
totals, and only what the program prints (or puts in `result`) returns to the
model. The tool results it reads never enter the model's context.

```python
# What the model writes; list_invoices and get_customer_name are your tools.
totals = {}
first = list_invoices(1)
for page in range(1, first["pages"] + 1):
    for invoice in list_invoices(page)["invoices"]:
        if invoice["status"] == "open" and invoice["due"] < "2026-09-23":
            totals[invoice["customer_id"]] = totals.get(invoice["customer_id"], 0) + invoice["amount"]
for customer_id, total in sorted(totals.items(), key=lambda kv: -kv[1])[:5]:
    print(get_customer_name(customer_id), round(total, 2))
```

- The program runs in the sandbox's child process. Each call crosses back to the
  agent and goes through its normal tool path: `_pre_execute_hook`, execution, a
  receipt and trace events. Receipts are marked `via_program` and kept as
  evidence, outside the model's context.
- A call that would wait for a person's decision is refused inside a program; the
  model calls that tool directly instead. A tool error is raised in the program.
- JSON text comes back already decoded. The function list shows each tool's
  return shape (field names and types, never values), learned from earlier calls
  for the agent's lifetime, so programs use real field names.
- The report names the calls made per function, so a program that read one page
  of eight shows it.

Set `programmable = False` on a role that should not host programs; the built-in
coder does, since it already writes and runs code.

---

## Further Reading

- [AutoAgent Guide](./autoagent.md), built-in sub-agent roles, lease budgets, and task routing
- [Architecture Overview](../concepts/architecture.md), how Kernel, sub-agents, and OODA loop relate
- [Model Routing](../concepts/model-routing.md), assigning a model tier to a custom sub-agent role
