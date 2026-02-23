# AutoAgent Guide

Build AI agents that write and execute their own code — you define **what** the agent does, the framework handles **how**.

---

## What You'll Build

An AutoAgent takes a natural language task, generates Python code using an LLM, executes it in a sandbox, and returns the result. If the code fails, the framework auto-repairs it (up to 3 attempts).

```
Your prompt → LLM generates Python → Sandbox executes → Result returned
                                         ↓ (if error)
                                    Auto-repair (up to 3x)
```

---

## Step 1: Install

```bash
pip install jarviscore-framework
```

Requirements: Python 3.10+

---

## Step 2: Configure

Scaffold your project and create a `.env` file:

```bash
python -m jarviscore.cli.scaffold --examples
cp .env.example .env
```

Open `.env` and set **one** LLM provider. The framework tries them in this order: Claude → vLLM → Azure → Gemini.

**Claude (recommended):**
```bash
CLAUDE_API_KEY=sk-ant-your-key-here
```

**Azure OpenAI:**
```bash
AZURE_API_KEY=your-key-here
AZURE_ENDPOINT=https://your-resource.openai.azure.com
AZURE_DEPLOYMENT=gpt-4o
AZURE_API_VERSION=2024-02-15-preview
```

**Google Gemini:**
```bash
GEMINI_API_KEY=your-key-here
```

**Local vLLM (free, self-hosted):**
```bash
LLM_ENDPOINT=http://localhost:8000
LLM_MODEL=Qwen/Qwen2.5-Coder-32B-Instruct
```

Other settings you may want to adjust:

```bash
EXECUTION_TIMEOUT=300        # Max seconds per task (default: 300)
MAX_REPAIR_ATTEMPTS=3        # Auto-fix retries on failure (default: 3)
SANDBOX_MODE=local           # "local" for dev, "remote" for production
LOG_DIRECTORY=./logs         # Where results and generated code are stored
LOG_LEVEL=INFO               # DEBUG, INFO, WARNING, ERROR, CRITICAL
```

---

## Step 3: Validate

```bash
python -m jarviscore.cli.check --validate-llm
```

You should see:
```
 Python Version: OK
 JarvisCore Package: OK
 Dependencies: OK
 .env File: OK
 Claude/Azure/Gemini: OK
```

Run the end-to-end smoke test:
```bash
python -m jarviscore.cli.smoketest
```

---

## Step 4: Define Your Agent

An AutoAgent needs exactly **3 attributes**:

| Attribute | What It Does |
|-----------|-------------|
| `role` | Unique identifier — this is how you reference the agent |
| `capabilities` | List of skills (used for agent discovery in P2P mode) |
| `system_prompt` | Instructions for the LLM on how to generate code |

Create `agents.py`:

```python
from jarviscore.profiles import AutoAgent


class CalculatorAgent(AutoAgent):
    role = "calculator"
    capabilities = ["math", "calculations"]
    system_prompt = """
    You are a math expert. Generate Python code to solve problems.
    Always store the result in a variable named 'result'.
    """
```

That's it. The framework handles:
- Connecting to your LLM
- Generating Python code from the task
- Executing the code in a sandboxed environment
- Auto-repairing failures
- Storing results to disk

---

## Step 5: Run Your Agent

You can run an agent in two ways: as a **standalone script** or as a **FastAPI service**. Both use the same agents.py from Step 4.

### Option A: Standalone Script (simplest)

Create `main.py`:

```python
import asyncio
from jarviscore import Mesh
from agents import CalculatorAgent


async def main():
    # 1. Create a mesh in autonomous mode
    mesh = Mesh(mode="autonomous")

    # 2. Add your agent
    mesh.add(CalculatorAgent)

    # 3. Start (initializes LLM, sandbox, etc.)
    await mesh.start()

    # 4. Run a task
    results = await mesh.workflow("calc-task", [
        {"agent": "calculator", "task": "Calculate the factorial of 10"}
    ])

    # 5. Get the result
    print(f"Status: {results[0]['status']}")    # success
    print(f"Output: {results[0]['output']}")     # 3628800
    print(f"Code: {results[0]['code']}")         # result = math.factorial(10)
    print(f"Repairs: {results[0]['repairs']}")    # 0

    # 6. Stop
    await mesh.stop()


if __name__ == "__main__":
    asyncio.run(main())
```

Run it:
```bash
python main.py
```

### Option B: FastAPI Service (for APIs and dashboards)

Create `main.py`:

```python
from fastapi import FastAPI
from jarviscore import Mesh
from agents import CalculatorAgent
import uvicorn

app = FastAPI()
mesh = None


@app.on_event("startup")
async def startup():
    global mesh
    mesh = Mesh(mode="autonomous")
    mesh.add(CalculatorAgent)
    await mesh.start()


@app.on_event("shutdown")
async def shutdown():
    if mesh:
        await mesh.stop()


@app.post("/calculate")
async def calculate(request: dict):
    agent = next(a for a in mesh.agents if a.role == "calculator")
    result = await agent.execute_task({
        "id": "calc",
        "task": request["task"],
        "context": {}
    })
    return {
        "status": result["status"],
        "output": result["output"]
    }


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000)
```

Run it:
```bash
python main.py
# Then: curl -X POST http://localhost:8000/calculate \
#   -H "Content-Type: application/json" \
#   -d '{"task": "Calculate the factorial of 10"}'
```

---

## Project Structure

For a single-agent project, you need **2 files** + `.env`:

```
my_project/
├── .env              # LLM keys and settings
├── agents.py         # Agent definitions (role, capabilities, system_prompt)
└── main.py           # Orchestration (mesh setup, task execution)
```

For multi-agent projects:

```
my_project/
├── .env
├── agents.py         # All agent classes
├── main.py           # Orchestration + API endpoints
└── logs/             # Auto-created: results + generated code
```

The separation is intentional:
- **agents.py** = *what* your agents are (pure definitions, no logic)
- **main.py** = *how* they run (mesh, workflows, API, context injection)

---

## Multi-Agent Workflows

### Sequential: A → B → C

Each step passes its output to the next via `context`:

```python
# agents.py
from jarviscore.profiles import AutoAgent


class Researcher(AutoAgent):
    role = "researcher"
    capabilities = ["research"]
    system_prompt = """
    Research the given topic. Store findings in `result` as:
    {"insights": [...], "keywords": [...]}
    """


class Writer(AutoAgent):
    role = "writer"
    capabilities = ["writing"]
    system_prompt = """
    INPUT: Research from previous step in `context.get('research', {})`.
    Write an article using those findings.
    Store the article string in `result`.
    """
```

```python
# main.py
import asyncio
from jarviscore import Mesh
from agents import Researcher, Writer


async def main():
    mesh = Mesh(mode="autonomous")
    mesh.add(Researcher)
    mesh.add(Writer)
    await mesh.start()

    # Step 1: Research
    researcher = next(a for a in mesh.agents if a.role == "researcher")
    research = await researcher.execute_task({
        "id": "research",
        "task": "Research AI trends in 2025",
        "context": {}
    })

    # Step 2: Write (pass step 1 output as context)
    writer = next(a for a in mesh.agents if a.role == "writer")
    article = await writer.execute_task({
        "id": "write",
        "task": "Write a blog post about AI trends",
        "context": {
            "previous_step_results": {
                "research": research.get("output", {})
            }
        }
    })

    print(article["output"])
    await mesh.stop()


asyncio.run(main())
```

### Parallel + Merge: [A, B, C] → D

Run multiple agents concurrently, then merge results:

```python
# agents.py
from jarviscore.profiles import AutoAgent


class SecurityReviewer(AutoAgent):
    role = "security_reviewer"
    capabilities = ["security"]
    system_prompt = """
    Review the code in `context.get('code', '')` for security issues.
    Store in `result`: {"severity": "...", "issues": [...]}
    """


class PerformanceReviewer(AutoAgent):
    role = "performance_reviewer"
    capabilities = ["performance"]
    system_prompt = """
    Review the code in `context.get('code', '')` for performance issues.
    Store in `result`: {"impact": "...", "issues": [...]}
    """


class Summarizer(AutoAgent):
    role = "summarizer"
    capabilities = ["summarization"]
    system_prompt = """
    Combine review results from:
    - context.get('security', {})
    - context.get('performance', {})
    Store a unified report string in `result`.
    """
```

```python
# main.py
import asyncio
from jarviscore import Mesh
from agents import SecurityReviewer, PerformanceReviewer, Summarizer


async def main():
    mesh = Mesh(mode="autonomous")
    mesh.add(SecurityReviewer)
    mesh.add(PerformanceReviewer)
    mesh.add(Summarizer)
    await mesh.start()

    code = "def login(user, pwd): return db.query(f'SELECT * FROM users WHERE name={user}')"

    # Run reviewers in parallel
    security_agent = next(a for a in mesh.agents if a.role == "security_reviewer")
    perf_agent = next(a for a in mesh.agents if a.role == "performance_reviewer")

    security_result, perf_result = await asyncio.gather(
        security_agent.execute_task({
            "id": "security", "task": "Review this code for security issues",
            "context": {"code": code}
        }),
        perf_agent.execute_task({
            "id": "performance", "task": "Review this code for performance issues",
            "context": {"code": code}
        })
    )

    # Merge with summarizer
    summarizer = next(a for a in mesh.agents if a.role == "summarizer")
    summary = await summarizer.execute_task({
        "id": "summary",
        "task": "Summarize all review findings",
        "context": {
            "previous_step_results": {
                "security": security_result.get("output", {}),
                "performance": perf_result.get("output", {})
            }
        }
    })

    print(summary["output"])
    await mesh.stop()


asyncio.run(main())
```

---

## Context Injection

When agents need access to external tools (databases, APIs, files), you inject them into the sandbox by wrapping `sandbox.execute` and `execute_task`:

```python
def inject_tools_into_agent(agent, my_database):
    """Make external tools available to agent-generated function tools."""
    original_execute = agent.sandbox.execute
    original_execute_task = agent.execute_task
    agent._current_task_context = {}

    async def execute_with_tools(code, timeout=None, context=None):
        ctx = context or {}

        # Inject your tools — these become Python variables in the sandbox
        ctx['database'] = my_database

        # Inject workflow context from previous steps
        task_ctx = agent._current_task_context
        if task_ctx:
            ctx['context'] = task_ctx
            prev = task_ctx.get('previous_step_results', {})
            for step_id, output in prev.items():
                ctx[step_id] = {'output': output}

        return await original_execute(code, timeout=timeout, context=ctx)

    async def execute_task_with_context(task):
        agent._current_task_context = task.get('context', {})
        try:
            return await original_execute_task(task)
        finally:
            agent._current_task_context = {}

    agent.sandbox.execute = execute_with_tools
    agent.execute_task = execute_task_with_context
```

Use it after `mesh.start()`:

```python
await mesh.start()

for agent in mesh.agents:
    inject_tools_into_agent(agent, my_database)
```

Then in your agent's `system_prompt`, tell the LLM the tool exists:

```python
class DataAgent(AutoAgent):
    role = "data_agent"
    capabilities = ["data_retrieval"]
    system_prompt = """
    TOOL AVAILABLE:
    database.query(sql) - Execute SQL, returns list of dicts

    TASK: Query the database and return results.
    Store in `result`.
    """
```

---

## What execute_task Returns

Every `agent.execute_task()` call returns a dict:

```python
{
    "status": "success",           # "success" or "failure"
    "output": {...},               # The value stored in `result` by the agent-generated function tool
    "code": "result = ...",        # The function tool code the agent generated
    "repairs": 0,                  # Number of auto-repair attempts (0 = worked first try)
    "execution_time": 3.14,        # Seconds
    "tokens": {...},               # Token usage breakdown
    "cost_usd": 0.003,             # LLM cost
    "result_id": "abc123",         # Storage ID (in logs/)
    "function_id": "fn-xyz",       # Code registry ID (reusable)
    "error": null                  # Error message if status is "failure"
}
```

---

## System Prompt Best Practices

The `system_prompt` is the most important part of your agent. It tells the LLM what code to generate.

**Always include:**
1. What tools/variables are available in the sandbox
2. What the task is
3. What format to store in `result`

**Good prompt:**
```python
system_prompt = """
You are a data analyst.

TOOLS AVAILABLE:
- warehouse.query(sql) - Execute SQL, returns list of dicts
- warehouse.tables() - Returns list of table names

TABLES:
- daily_revenue: date, region, revenue, partner
- partner_status: partner, status, last_sync

TASK: Query the warehouse to answer the user's question.

OUTPUT: Store in `result` as a dict with:
- "data": the query results
- "summary": one-line description of findings
"""
```

**For agents receiving context from previous steps:**
```python
system_prompt = """
You are an analyst.

INPUT: Previous results in `context` variable.
Access via: context.get('step_name', {}).get('output', {})

TASK: Analyze the data from the previous step.

OUTPUT: Store in `result` as a dict.
"""
```

**Rules:**
- Always tell the LLM to store output in `result` — that's how the framework captures it
- Keep prompts direct and specific — the LLM generates code from these instructions
- List available tools explicitly — the LLM can't discover them on its own
- For context access, use simple patterns like `context.get('key', {})` — LLMs follow these reliably

---

## Distributed Mode

Same agents, same code — just change the mesh config to enable P2P networking:

```python
# Single machine (autonomous)
mesh = Mesh(mode="autonomous")

# Multi-node capable (distributed)
mesh = Mesh(
    mode="distributed",
    config={
        'bind_port': 7950,
        'node_name': 'my-node',
    }
)
```

Everything else stays the same. See [CUSTOMAGENT_GUIDE.md](CUSTOMAGENT_GUIDE.md) for multi-node setups.

---

## Infrastructure Injection in AutoAgent

Before `setup()` runs, the Mesh auto-injects three infrastructure objects onto every
agent — including AutoAgent. No constructor wiring or boilerplate required:

| Attribute | Type | Requires |
|-----------|------|---------|
| `self._redis_store` | `RedisContextStore` | `REDIS_URL` |
| `self._blob_storage` | `LocalBlobStorage` / `AzureBlobStorage` | always present |
| `self.mailbox` | `MailboxManager` | `REDIS_URL` |

```python
from jarviscore.profiles import AutoAgent
from jarviscore.memory import UnifiedMemory
import json, time

class ResearchAgent(AutoAgent):
    role = "researcher"
    capabilities = ["research"]
    system_prompt = "Research the topic. Store findings in `result` as a dict."

    async def setup(self):
        await super().setup()
        # All infrastructure already wired — no __init__ boilerplate needed
        self.memory = UnifiedMemory(
            workflow_id="research-wf", step_id="research",
            agent_id=self.role,
            redis_store=self._redis_store,
            blob_storage=self._blob_storage,
        )

    async def execute_task(self, task):
        result = await super().execute_task(task)

        if result.get("status") == "success":
            # Save output artifact
            await self._blob_storage.save(
                f"research/{task.get('id', 'step')}.json",
                json.dumps(result["output"]),
            )
            # Log to episodic ledger
            await self.memory.episodic.append({
                "step": task.get("id"),
                "status": "success",
                "ts": time.time(),
            })

        return result
```

---

## Memory Access in AutoAgent

### UnifiedMemory

```python
from jarviscore.memory import UnifiedMemory

# In setup() — after super().setup()
self.memory = UnifiedMemory(
    workflow_id="wf-001", step_id="analyst",
    agent_id=self.role,
    redis_store=self._redis_store,
    blob_storage=self._blob_storage,
)
```

### RedisMemoryAccessor — Reading Prior Step Outputs

AutoAgent steps running under the WorkflowEngine automatically write their output to
`step_output:{workflow_id}:{step_id}` in Redis. Use `RedisMemoryAccessor` to read
a prior step's output without re-running it:

```python
from jarviscore.memory import RedisMemoryAccessor

async def execute_task(self, task):
    accessor = RedisMemoryAccessor(self._redis_store, workflow_id=task.get("workflow_id"))
    raw = accessor.get("fetch")                          # reads step_output:wf:fetch
    prior_data = raw.get("output", raw) if isinstance(raw, dict) else {}
    # prior_data is now available for agent-generated function tools via context injection
    ...
```

---

## Context Injection — Why It Matters

### The Critical Line

```python
result = await self.sandbox.execute(code, context=task.get('context'))
```

This line (in `AutoAgent.execute_task`) passes the workflow's `context` dict into the
sandbox namespace before executing agent-generated function tools. Without it, `previous_step_results`
is undefined inside the generated code and any reference raises `NameError`.

### What Happens Without It

The sandbox catches the `NameError` silently and returns an empty / fallback result:

```python
# LLM generates this code for an analysis step:
research = context.get('previous_step_results', {}).get('fetch', {})
result = analyze(research)

# Without context injection:
# → NameError: name 'context' is not defined
# → Sandbox catches exception → returns {"status": "success", "output": None}
# → Silent failure: downstream steps get empty data
```

### The Diagnostic Tell

If `execution_time ≈ 0.003s` on an analysis step, the generated code failed instantly:

```
{"status": "success", "execution_time": 0.003, "output": null}
```

A real LLM-driven computation takes 1–30s depending on complexity. Sub-10ms means the
code errored before doing any work.

**Fix already applied** in `jarviscore/profiles/autoagent.py` as of v0.4.0 — context is
always passed. This note exists so you recognise the symptom if you see it in custom sandboxes.

---

## Production Example: Ex1 — Financial Pipeline

**Profile:** AutoAgent | **Mode:** autonomous | **Phases:** 1, 5, 6, 7, 8, 9

### Architecture

```
MarketDataAgent  ──→  AnalysisAgent  ──→  ReportAgent
   (fetch)              (analyse)           (report)
```

Three AutoAgents run sequentially. Each step's output is stored in Redis by the
WorkflowEngine. The analysis and report agents read prior step outputs via
`RedisMemoryAccessor`. The final report is saved to blob storage.

### Phases at Work

| Phase | What happens |
|-------|-------------|
| 9 | `_redis_store`, `_blob_storage`, `mailbox` injected before each agent's `setup()` |
| 7 | WorkflowEngine dispatches steps in `depends_on` order; crash recovery via Redis hash |
| 8 | `UnifiedMemory` logs each step to `EpisodicLedger`; `RedisMemoryAccessor` reads prior outputs |
| 6 | Kernel routes: fetch → ResearcherSubAgent, analyse → CoderSubAgent, report → CommunicatorSubAgent |
| 5 | Successful generated functions are graduated to `code_registry` for reuse |
| 1 | Final report Markdown saved to `blob_storage.save("reports/financial-daily-001.md", ...)` |

### Run

```bash
docker compose -f docker-compose.infra.yml up -d
cp .env.example .env   # set CLAUDE_API_KEY and REDIS_URL

python examples/ex1_financial_pipeline.py
```

### Verify

```bash
redis-cli hgetall "step_output:financial-daily-001:fetch"
redis-cli hgetall "step_output:financial-daily-001:analyse"
cat blob_storage/reports/financial-daily-001.md
redis-cli xrange ledgers:financial-daily-001 - +
curl -s http://localhost:9090/metrics | grep jarviscore
```

Re-run with the same `workflow_id` — already-completed steps are skipped (crash recovery).

---

## Production Example: Ex2 — Distributed Research Network

**Profile:** AutoAgent | **Mode:** distributed (4-node)

### Architecture

```
ex2_synthesizer.py    port 7949 (seed, no SEED_NODES)
ex2_research_node1.py port 7946, SEED_NODES=127.0.0.1:7949  → TechResearcher
ex2_research_node2.py port 7947, SEED_NODES=127.0.0.1:7949  → MarketResearcher
ex2_research_node3.py port 7948, SEED_NODES=127.0.0.1:7949  → RegResearcher
```

ZMQ port = SWIM port + 1000 (e.g. 7949 → 8949).

### How Distributed Step Claiming Works

The synthesizer calls `mesh.workflow(...)` which writes the full DAG to Redis
(`workflow_graph:{wf_id}` hash). Each node runs `Mesh._run_distributed_worker()` as a
background asyncio task. The worker:

1. Scans `jarviscore:active_workflows` for workflow IDs
2. Reads all step definitions from `workflow_graph:{wf_id}`
3. Filters steps matching its local agents
4. Calls `are_dependencies_met(step_id)` — skips if deps incomplete
5. Uses `claim_step(step_id)` — atomic Redis SETNX — only one node wins
6. Executes the step, writes output + status back to Redis
7. Synthesizer's engine polls via `_wait_remote_step()` every 2s until `"completed"`

**No `STEP_ID` hardcoding required.** Nodes autonomously claim matching steps.

### Per-Node Port Configuration

In a multi-node setup each process needs a **unique port** — a single value in a
shared `.env` cannot serve all nodes. JarvisCore reads `JARVISCORE_BIND_PORT`
(not `BIND_PORT`) to keep per-process P2P config isolated from shared settings.

**Option 1 — explicit constant in script (used in the examples):**
```python
BIND_PORT = 7949   # synthesizer — fixed by architecture
mesh = Mesh(mode="distributed", config={"bind_port": BIND_PORT, ...})
```

**Option 2 — per-process env var at launch (production / containers):**
```bash
JARVISCORE_BIND_PORT=7949 python ex2_synthesizer.py
JARVISCORE_BIND_PORT=7946 python ex2_research_node1.py
```

Do not set `BIND_PORT` (or `JARVISCORE_BIND_PORT`) in a shared `.env` file for
multi-node deployments — each node needs its own value.

### Run

```bash
docker compose -f docker-compose.infra.yml up -d

# Start seed first — wait ~2s for SWIM to stabilise
python examples/ex2_synthesizer.py &       # port 7949
sleep 2
python examples/ex2_research_node1.py &    # port 7946
python examples/ex2_research_node2.py &    # port 7947
python examples/ex2_research_node3.py &    # port 7948
```

### Verify

```bash
redis-cli hgetall "step_output:ai-landscape-q1:tech"
redis-cli hgetall "step_output:ai-landscape-q1:synth"
redis-cli xrange ledgers:ai-landscape-q1 - +
```

---

## Troubleshooting

**"No LLM providers configured"**
```bash
python -m jarviscore.cli.check --validate-llm
```
Check that `.env` has a valid API key.

**"Task failed"** — check the logs:
```bash
ls logs/
cat logs/<agent-id>/<latest>.json
```

**Slow execution** — try a faster model:
```bash
CLAUDE_MODEL=claude-haiku-4-5-20251001
# or
GEMINI_MODEL=gemini-2.0-flash
```

**Code keeps failing** — improve your `system_prompt`. Be more explicit about available tools, expected input format, and output structure.
