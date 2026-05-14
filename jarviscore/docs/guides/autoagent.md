---
icon: material/robot
---

# AutoAgent Guide

`AutoAgent` is JarvisCore's fully autonomous reasoning agent. You define three class attributes and the framework handles everything else: LLM selection, code generation, sandboxed execution, autonomous repair, and registry-first routing. For multi-step goals, setting `goal_oriented = True` activates the Plan, Execute, Evaluate loop with automatic replanning.

---

## Defining an AutoAgent

```python title="agents/researcher.py"
from jarviscore import AutoAgent

class ResearcherAgent(AutoAgent):
    role = "researcher"
    capabilities = ["research", "synthesis", "web-search"]
    system_prompt = """
    You are a rigorous research analyst. Prioritise primary sources,
    cross-reference findings, and structure outputs as actionable intelligence.
    Always store your final output in a variable named `result`.
    """
```

The framework raises `ValueError` at startup if `system_prompt` is absent. Every other attribute is optional.

### Class Attributes

| Attribute | Required | Description |
|---|---|---|
| `role` | Yes | Slug used for peer discovery, profile loading, and workflow routing |
| `capabilities` | Yes | Tags for capability-based peer discovery |
| `system_prompt` | Yes | Base LLM system prompt; framework raises ValueError if absent |
| `name` | No | Human-readable display name |
| `description` | No | One-sentence purpose used by peers for routing decisions |
| `default_kernel_role` | No | Preferred fallback role for specialist agents; one of `"researcher"`, `"coder"`, `"communicator"`, `"browser"`. Leave unset for generalists. |
| `goal_oriented` | No | Defaults to `False`; set `True` for multi-step goal decomposition |
| `requires_auth` | No | Defaults to `False`; set `True` to receive Nexus-backed `_auth_manager` |

---

## Running an AutoAgent

### Standalone script

```python title="main.py"
import asyncio
from jarviscore import Mesh
from agents import ResearcherAgent

async def main():
    mesh = Mesh()
    mesh.add(ResearcherAgent)
    await mesh.start()

    results = await mesh.workflow("research-001", [
        {"agent": "researcher", "task": "Summarise the state of AI hardware in 2026"}
    ])

    step = results[0]
    print(step["status"])    # "success"
    print(step["payload"])   # the value stored in `result` by the generated code
    await mesh.stop()

asyncio.run(main())
```

`Mesh()` takes no mode argument. It auto-detects available infrastructure at `start()` time. Pass `REDIS_URL` in your environment and the Mesh will use Redis automatically. Pass it explicitly via the config dict if you need to override:

```python
mesh = Mesh(config={"redis_url": "redis://localhost:6379/0"})
```

For P2P between nodes, add `p2p_enabled: True` and `bind_port` to the config dict. No mode string required.

### FastAPI service

```python title="main.py"
from contextlib import asynccontextmanager
from fastapi import FastAPI
from jarviscore import Mesh
from agents import ResearcherAgent

mesh = Mesh()

@asynccontextmanager
async def lifespan(app: FastAPI):
    mesh.add(ResearcherAgent)
    await mesh.start()
    yield
    await mesh.stop()

app = FastAPI(lifespan=lifespan)

@app.post("/research")
async def research(request: dict):
    results = await mesh.workflow("req-001", [
        {"agent": "researcher", "task": request["task"]}
    ])
    step = results[0]
    return {"status": step["status"], "output": step.get("payload")}
```

---

## What workflow() Returns

`mesh.workflow()` returns a list of step result dicts, one per step, in execution order. Each dict contains:

| Key | Description |
|---|---|
| `status` | `"success"`, `"failure"`, or `"yield"` |
| `payload` | The value stored in `result` by the generated code |
| `summary` | Human-readable outcome description |
| `metadata` | Execution detail: tokens, cost, elapsed time, distilled facts |

Always check `step["status"] == "success"` before reading `step["payload"]`. A `"failure"` result has a populated `"summary"` explaining what went wrong.

---

## Lifecycle Hooks

`AutoAgent.setup()` is called once by the Mesh after instantiation. It initialises the Kernel, LLM client, sandbox, FunctionRegistry, and loads the agent persona from YAML if configured. Override it for one-time setup:

```python
async def setup(self):
    await super().setup()   # must come first
    self.data_client = await MyDataClient.connect()
```

`teardown()` is called during Mesh shutdown. Release any resources opened in `setup()`:

```python
async def teardown(self):
    await self.data_client.close()
    await super().teardown()
```

You will rarely need to override `execute_task()`. The Kernel pipeline routes internally. Override it only if you need to enrich the task dict before the Kernel processes it:

```python
async def execute_task(self, task: dict) -> dict:
    enriched = {**task, "task": f"{task.get('task', '')}\n\nUser context: {self.user_id}"}
    return await super().execute_task(enriched)
```

---

## System Prompt Best Practices

The system prompt is the primary way to shape the code the agent generates.

```python
system_prompt = """
You are a financial data analyst.

Data source: Yahoo Finance API at https://query1.finance.yahoo.com/v8/finance/chart/{ticker}
Parse the JSON response carefully and handle missing keys with .get().

Your output must be stored in a variable named `result` as a dict with keys:
  ticker    (str)
  price     (float)
  change_pct (float)
  analysis  (str, 2-3 sentences)
"""
```

Tell the agent exactly what variable name to use (`result`), the expected shape of that variable, what APIs or tools are available in the sandbox, and what to do when data is missing or a request fails. Vague prompts produce fragile code.

---

## Kernel Role Routing

The Kernel classifies each task and routes it to the appropriate sub-agent. You do not configure this directly. The Kernel infers the right sub-agent from the task. On specialist agents where every task always uses the same sub-agent, skip classification entirely by setting `default_kernel_role`:

```python
class SlackNotifier(AutoAgent):
    role = "notifier"
    default_kernel_role = "communicator"   # always sends, never codes or searches
```

The four sub-agents the Kernel routes to are the `CoderSubAgent` for tasks that require writing and running Python, the `ResearcherSubAgent` for tasks that require web search and synthesis, the `CommunicatorSubAgent` for tasks that require formatting and delivering output, and the `BrowserSubAgent` for web navigation tasks when `BROWSER_ENABLED=true` is set.

---

## Coder Sandbox

When the Kernel routes a task to the `CoderSubAgent`, code executes inside `CoderSandbox` — a deliberately file-capable execution environment that is distinct from the `SandboxExecutor` used by other sub-agents.

`SandboxExecutor` (used by ResearcherSubAgent and CommunicatorSubAgent) blocks `open()`, `subprocess`, and filesystem access. `CoderSandbox` intentionally grants those capabilities, scoped to a controlled workspace directory.

Inside every execution, generated code receives these names in its namespace:

| Name | Type | Description |
|---|---|---|
| `workspace` | `Path` | Project root directory. All file reads and writes are expected here. |
| `output_dir` | `Path` | `workspace/output/` — the preferred write location for produced files. |
| `blob_path(name)` | `Path` | Shorthand for `output_dir / name`. Creates parent directories. |
| `bash(cmd)` | `BashExecutor` | Run allowed shell commands. Returns `{success, stdout, stderr, returncode}`. |
| `git` | `GitHelper` | High-level git: `checkout_branch`, `add_all`, `commit`, `push`, `describe_pr`. |
| `nexus_call` | async fn | Make authenticated HTTP calls to any provider via Nexus. Never exposes credentials. |
| `json`, `os`, `re`, `Path`, `datetime`, `math`, `shutil`, `uuid` | stdlib | Pre-imported for convenience. |

The Coder can `import` any installed package from within the sandbox. The security boundary is the bash allow-list, not Python builtins.

The bash allow-list covers: `git`, `pip`, `pip3`, `cp`, `mv`, `mkdir`, `rm`, `ls`, `cat`, `echo`, `touch`, `find`, `grep`, `sed`, `awk`, `pandoc`, `npm`, `npx`, `node`, `python`, `python3`, `curl`. Hard-blocked regardless: `sudo`, `rm -rf /`, `eval`, `curl | bash`, and pipe-to-shell patterns.

The `CoderResult` output shape — what gets written to `result` by generated code and surfaced in `step["payload"]`:

```python
result = {
    "success":        bool,         # did the task complete?
    "files_created":  [str],        # absolute paths of files written
    "files_modified": [str],        # absolute paths of files changed
    "git_branch":     str | None,   # branch name if git ops were performed
    "stdout":         str,          # captured print() output
    "data":           Any,          # any structured data to return
    "error":          str | None,   # error message if success=False
}
```

Configure the workspace root and timeouts:

```bash title=".env"
# Workspace directory — defaults to the process working directory
CODER_WORKSPACE=/path/to/your/project

# Sandbox execution timeout in seconds (default: 300)
SANDBOX_TIMEOUT=300
```

When writing system prompts for agents that route to the Coder, always tell the agent what files it should write and where. The Coder will use `output_dir` by default if you do not specify a location.

---

## Execution Budgets

Every sub-agent dispatch runs against an `ExecutionLease` — a token, turn, and wall-clock budget specific to the sub-agent role. When the lease is exhausted, the Kernel stops the sub-agent and returns whatever has been produced so far.

| Role | Thinking tokens | Action tokens | Total tokens | Wall clock | Turn fuse |
|---|---|---|---|---|---|
| `coder` | 132,000 | 108,000 | 240,000 | 4 min | 32 turns |
| `researcher` | 180,000 | 60,000 | 240,000 | 4 min | 36 turns |
| `communicator` | 72,000 | 48,000 | 120,000 | 4 min | 18 turns |
| `browser` | 60,000 | 60,000 | 120,000 | 5 min | 28 turns |

The turn fuse is an emergency hard-stop. If a sub-agent reaches 32 turns without completing, the Kernel terminates it regardless of token budget. This prevents runaway loops on adversarial or ambiguous tasks.

You do not configure lease budgets per-agent — they are role-level defaults. If a specific task consistently exhausts the budget, the right fix is usually to narrow the task scope (break it into smaller steps in the workflow DAG), not to increase the budget.

Token budget consumption appears in `step["metadata"]["tokens"]` on every workflow result:

```python
results = await mesh.workflow("report", [
    {"id": "analyse", "agent": "analyst", "task": "..."}
])
step = results[0]
print(step["metadata"]["tokens"])
# {"input": 14200, "output": 3100, "total": 17300}
```

---


## Model Routing

JarvisCore routes each sub-agent dispatch to a capability tier — `nano`, `standard`, or `heavy` — based on the role and an optional per-step hint. Pass `complexity` in a workflow step to override the default for that dispatch:

```python
results = await mesh.workflow("task-001", [
    {"agent": "analyst", "task": "Summarise this paragraph.",       "complexity": "nano"},
    {"agent": "analyst", "task": "Produce a competitive analysis.", "complexity": "heavy"},
])
```

When `complexity` is omitted, the role's built-in default applies — `communicator` defaults to `nano`, `researcher` and `browser` default to `standard`. See [Model Routing](../concepts/model-routing.md) for the full tier configuration, fallback chain, and provider compatibility reference.

---

## Infrastructure Injection

The Mesh injects infrastructure stores into every agent before `setup()` runs. They are available immediately inside `setup()` and `execute_task()`:

| Attribute | Available when |
|---|---|
| `self._redis_store` | `REDIS_URL` is set |
| `self._blob_storage` | Always — falls back to local filesystem |
| `self.mailbox` | `REDIS_URL` is set |

```python
from jarviscore.memory import UnifiedMemory

async def setup(self):
    await super().setup()
    self.memory = UnifiedMemory(
        workflow_id="wf-001",
        step_id=self.role,
        agent_id=self.role,
        redis_store=self._redis_store,
        blob_storage=self._blob_storage,
    )
```

Agents running inside a workflow write their step output to `step_output:{workflow_id}:{step_id}` in Redis. Read a prior step's output from another agent using `RedisMemoryAccessor`:

```python
from jarviscore.memory import RedisMemoryAccessor

accessor = RedisMemoryAccessor(self._redis_store, workflow_id="wf-001")
raw = accessor.get("fetch")
prior = raw.get("output", raw) if isinstance(raw, dict) else {}
```

### Checkpointing

Checkpointing happens automatically. After every OODA loop turn, the Kernel calls `UnifiedMemory.save_checkpoint()` which writes the current `KernelState` — all accumulated findings, tool history, and reasoning progress — to Redis under `checkpoint:{workflow_id}:{step_id}`. If the process crashes and the workflow restarts, the `WorkflowEngine` detects the existing checkpoint and resumes from that turn rather than restarting from scratch.

You do not call `save_checkpoint()` or `load_checkpoint()` in application code. The framework manages this transparently when `REDIS_URL` is configured. Without Redis, there is no persistence and no crash recovery — the workflow starts from the beginning on failure.

---


## Nexus Auth: requires_auth

Set `requires_auth = True` on agents that call third-party services. The Mesh creates an `AuthenticationManager` backed by Nexus and injects it as `self._auth_manager` after `setup()` completes. The Kernel wires `NexusCallProxy` into the sandbox so generated code receives resolved credentials without ever seeing raw tokens.

```python
class GitHubAgent(AutoAgent):
    role = "github_agent"
    capabilities = ["github", "code-review"]
    requires_auth = True
    system_prompt = """
    You have access to GitHub via the injected auth_manager.
    Use it to create issues, review PRs, and update files.
    Always store results in `result`.
    """
```

`_auth_manager` is `None` when `NEXUS_GATEWAY_URL` is not set. Always check `if self._auth_manager:` before accessing it directly in `setup()`.

---

## Multi-Agent Workflows

Steps in a workflow run in dependency order. Steps with no `depends_on` run immediately; steps that declare dependencies wait for those steps to complete.

```python
results = await mesh.workflow("pipeline-001", [
    {"id": "fetch",   "agent": "fetcher",   "task": "Fetch AAPL price data for the last 30 days"},
    {"id": "analyse", "agent": "analyst",   "task": "Analyse the price trend",   "depends_on": ["fetch"]},
    {"id": "report",  "agent": "reporter",  "task": "Write an executive summary", "depends_on": ["analyse"]},
])
```

Prior step outputs are delivered to each downstream agent automatically. The WorkflowEngine builds the dependency output map from every step listed in `depends_on`, places it in `context["previous_step_results"]`, and the ContextManager renders it as a clearly labelled section in the LLM's context window before every decision turn. The agent reads what the prior step produced and acts on it without any additional code or system prompt instructions from the developer.

The `depends_on` declaration is the only thing required. A step that does not declare a dependency does not receive the output of steps it has no declared relationship with, even if those steps happened to finish earlier.

Steps without `depends_on` that share no dependency chain run concurrently. The WorkflowEngine dispatches them in parallel automatically.

Workflow execution is crash-safe. If the process restarts with the same `workflow_id`, completed steps are not re-run. Only pending steps resume.

---

## Goal-Oriented Execution

Setting `goal_oriented = True` switches the agent from a single OODA loop to a Plan, Execute, Evaluate loop. The agent decomposes the goal into steps, executes each through the Kernel, evaluates the outcome, and replans automatically if a step fails.

```python
class ResearchAgent(AutoAgent):
    role = "researcher"
    capabilities = ["research", "analysis"]
    system_prompt = "You are a market researcher. Always store results in `result`."
    goal_oriented = True
```

The `execute_task()` interface and `mesh.workflow()` call are identical. The response gains a `goal_execution` summary:

```python
step["status"]                   # "success" | "failure" | "hitl"
step["payload"]                  # final synthesised answer
step["metadata"]["goal_execution"]  # {"steps": 4, "facts": 12, "elapsed_ms": 18420}
```

Control the loop ceiling with environment variables:

| Variable | Default | Description |
|---|---|---|
| `MAX_GOAL_STEPS` | `30` | Hard ceiling on plan steps |
| `MAX_REPLAN_ATTEMPTS` | `8` | Maximum replanning cycles before the goal fails |

---

## Human-in-the-Loop Escalation

In goal-oriented mode, if the evaluator's confidence on a step falls below the configured threshold, the Kernel pauses and emits a HITL event. Your application receives this and presents it to a human operator. The operator response is injected as the step result.

```bash title=".env"
HITL_ENABLED=true
HITL_MAX_CONFIDENCE=0.8
HITL_MIN_RISK_SCORE=0.7
```

Per-agent escalation targets are configured in the agent profile YAML under `escalates_to`. See the [Agent Personas](../concepts/agent-personas.md) concept page for the full schema. For the full HITL API — `request()`, `wait()`, `check()`, `resolve()` — see the [HITL Escalation guide](hitl.md).

---

## Production Example: Financial Pipeline

The `financial_pipeline.py` example runs three AutoAgents sequentially — a market data fetcher, an analyst, and a report writer — with Redis crash recovery, UnifiedMemory episodic logging, and blob storage output.

```bash
docker compose -f docker-compose.infra.yml up -d
cp .env.example .env   # set GEMINI_API_KEY and REDIS_URL
python examples/financial_pipeline.py
```

Verify the outputs:

```bash
redis-cli hgetall "step_output:financial-daily-001:fetch"
cat blob_storage/reports/financial-daily-001.md
redis-cli xrange ledgers:financial-daily-001 - +
```

Running with the same `workflow_id` a second time skips already-completed steps. See the [Financial Pipeline example](../examples/financial-pipeline.md) for the full annotated walkthrough.

---

## Troubleshooting

If a task returns a success status with `execution_time` under 10 milliseconds and a null payload, the generated code failed instantly before doing any real work. This almost always means `context` was not passed in the task dict, so the generated code raised a `NameError` on the first line that referenced it. Make sure every step dict includes a `"context"` key, even if empty.

If code keeps failing after autonomous repairs, improve the system prompt. The LLM generates code from the prompt. Vague prompts produce fragile code — the more explicit you are about available tools, input format, and the exact shape of `result`, the fewer repairs are needed.
