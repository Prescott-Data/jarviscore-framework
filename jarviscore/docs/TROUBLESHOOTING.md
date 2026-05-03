---
icon: material/wrench
---

# Troubleshooting

Common issues and solutions for JarvisCore developers — from installation through production mesh deployments.

---

## Quick Diagnostics

Run these first before digging into individual issues:

```bash
# Check installation, env vars, and LLM connectivity
jarviscore check

# Validate LLM connectivity (makes real API calls)
jarviscore check --validate-llm

# Verbose health check output
jarviscore check --verbose

# End-to-end smoke test
jarviscore smoketest

# Verbose output for debugging
jarviscore smoketest --verbose
```

---

## Installation

### `ModuleNotFoundError: No module named 'jarviscore'`

```bash
pip install jarviscore-framework

# Development install
pip install -e .
```

### `ImportError: cannot import name 'AutoAgent'`

Stale cached install. Reinstall:

```bash
pip uninstall jarviscore-framework -y
pip install jarviscore-framework
```

---

## LLM Configuration

### `No LLM provider configured`

Missing API key. Add one of the following to `.env`:

```bash
GEMINI_API_KEY=...
CLAUDE_API_KEY=...       # or ANTHROPIC_API_KEY
AZURE_API_KEY=...        # also requires AZURE_ENDPOINT and AZURE_DEPLOYMENT
```

Then validate:

```bash
jarviscore check --validate-llm
```

### `Error code: 401 — Unauthorized`

Invalid or expired API key. Verify the key value, check expiry, and for Azure confirm `AZURE_ENDPOINT` and `AZURE_DEPLOYMENT` are set.

### `Error code: 429 — Rate limit exceeded`

Wait 60 seconds, then retry. If persistent, upgrade your API plan or switch to a less-loaded model.

### `Error code: 529 — Overloaded`

Provider temporarily overloaded (common with Claude). The smoke test retries automatically 3 times. Retry manually after a few seconds or add a secondary provider.

---

## Execution Errors

### `Task failed: Code execution timed out`

Default timeout is controlled by `SANDBOX_TIMEOUT`. Increase it in `.env`:

```bash
SANDBOX_TIMEOUT=600   # seconds — default is 300
```

### `Sandbox execution failed`

The framework auto-repairs up to 3 times. If all attempts fail:

1. Check traces for the exact error:
   ```bash
   ls traces/
   cat traces/<workflow>_<step>.jsonl | python -m json.tool | grep error
   ```

2. Make the task more explicit — the agent needs to know exactly what to produce:
   ```python
   system_prompt = """
   You are a Python expert. Generate clean, working code.
   Use only the standard library.
   Store the final answer in a variable named `result`.
   Handle edge cases explicitly.
   """
   ```

3. Simplify the task first, then add complexity once it runs.

### `Maximum repair attempts exceeded`

The LLM could not generate working code in 3 tries. Simplify the task or add more detail to the system prompt. Check the trace log to see what errors occurred each attempt.

### Silent success with `execution_time ≈ 0.003s` and `output: null`

**This is a known diagnostic tell.** Real LLM-driven computation takes 1–30 seconds. Sub-10ms means the sandbox code crashed instantly.

**Cause:** Agent-generated code raised `NameError: name 'context' is not defined` — the sandbox caught it silently.

**Fix:** Confirm `autoagent.py` passes context to the sandbox:

```python
result = await self.sandbox.execute(code, context=task.get('context'))
```

If you subclass `AutoAgent` and override `execute_task`, pass `context=task.get('context')` in your `sandbox.execute()` call.

---

## Workflow Issues

### `Agent not found: <role>`

Role string mismatch between agent definition and workflow step:

```python
class CalculatorAgent(AutoAgent):
    role = "calculator"        # ← this value

results = await mesh.workflow("wf-1", [
    {"agent": "calculator", "task": "..."},  # ← must match exactly
])
```

### `Dependency not satisfied: <step-id>`

The `depends_on` step ID does not exist in the workflow, or it failed. The correct key is `depends_on` (not `dependencies`):

```python
results = await mesh.workflow("wf-1", [
    {"id": "step1", "agent": "agent1", "task": "..."},
    {"id": "step2", "agent": "agent2", "task": "...",
     "depends_on": ["step1"]},   # ← correct key
])
```

---

## CustomAgent Issues

### `self.mailbox is None` / `self._redis_store is None`

Infrastructure attributes are injected by the Mesh **after** `__init__` runs — they are only available inside `setup()`:

```python
# ❌ Wrong — __init__ runs before injection
class MyAgent(CustomAgent):
    def __init__(self):
        self.memory = UnifiedMemory(redis_store=self._redis_store)  # None!

# ✅ Correct — setup() runs after injection
class MyAgent(CustomAgent):
    async def setup(self):
        await super().setup()
        self.memory = UnifiedMemory(redis_store=self._redis_store)  # injected ✓
```

Verify injection after `mesh.start()`:

```python
await mesh.start()
for agent in mesh.agents:
    print(f"{agent.role}: redis={agent._redis_store is not None} "
          f"mailbox={agent.mailbox is not None}")
```

---

## Redis & Memory Issues

### `ConnectionError: Redis connection refused`

Redis is not running, or `REDIS_URL` is not set.

```bash
# Start Redis
docker compose -f docker-compose.infra.yml up -d

# Verify
redis-cli ping   # → PONG

# Check .env
grep REDIS_URL .env
```

> [!NOTE]
> Without `REDIS_URL`, the Mesh degrades gracefully — `_redis_store` and `mailbox` become `None`. Workflow execution still works but checkpointing, mailboxes, and distributed coordination are disabled.

### `EpisodicLedger.append()` fails / events not in Redis

1. Ensure `REDIS_URL` is set and Redis is reachable
2. Confirm `UnifiedMemory` is initialised in `setup()` (not `__init__`)
3. Check the ledger stream directly:
   ```bash
   redis-cli xrange ledgers:your-workflow-id - +
   ```

### `blob_storage.load()` returns `None`

The file was saved with a different `STORAGE_BASE_PATH` or in a different process's working directory.

```bash
ls -la blob_storage/
find blob_storage/ -name "*.json" -o -name "*.md" | head -20
```

Fix: pin `STORAGE_BASE_PATH` in `.env` to an absolute path:

```bash
STORAGE_BASE_PATH=/app/blob_storage
```

---

## Distributed Mesh Issues

### Step stuck in `"pending"` forever

**Causes:**

- A prior step's `step_output:wf:step_id` key never written to Redis
- No node has the agent role the step requires
- Step was claimed by a crashed node

**Diagnose:**

```bash
redis-cli hgetall "workflow_graph:your-workflow-id"
redis-cli keys "step_output:your-workflow-id:*"
redis-cli smembers "jarviscore:active_workflows"
```

**Reset a stuck step:**

```bash
redis-cli hset "workflow_graph:wf-id" "step-id:status" "pending"
redis-cli del "claim:wf-id:step-id"
```

### Per-process port conflicts in multi-node setups

Each process needs a **unique port**. A shared `.env` with a single `BIND_PORT` won't work for four nodes.

**Recommended approach — explicit config dict:**

```python
BIND_PORT = 7949   # this script's port — part of its identity
mesh = Mesh(config={"bind_port": BIND_PORT, ...})
```

**Production approach — per-process env var:**

```bash
JARVISCORE_BIND_PORT=7949 python synthesizer.py
JARVISCORE_BIND_PORT=7946 python research_node1.py
```

JarvisCore reads `JARVISCORE_BIND_PORT` (not `BIND_PORT`) to keep per-process config cleanly separated from shared `.env` values.

### `self._auth_manager` is `None` despite `requires_auth = True`

`NEXUS_GATEWAY_URL` is not set. The Mesh only injects `AuthenticationManager` when a gateway URL is configured:

```bash
# In .env
NEXUS_GATEWAY_URL=https://your-dromos-gateway.example.com
AUTH_MODE=production
```

For local development:

```bash
AUTH_MODE=mock
```

Or guard the call in your agent:

```python
if self._auth_manager:
    result = await self._auth_manager.make_authenticated_request(...)
else:
    pass  # graceful degradation
```

---

## Performance

### Code generation is slow (> 10 seconds)

Switch to a faster model in `.env`:

```bash
# Gemini
GEMINI_MODEL=gemini-2.0-flash

# Claude
CLAUDE_MODEL=claude-haiku-4

# Local vLLM (free, no API cost)
LLM_ENDPOINT=http://localhost:8000
LLM_MODEL=Qwen/Qwen2.5-Coder-32B-Instruct
```

Also simplify the system prompt — shorter, more specific prompts generate faster.

### High API costs

1. Use cheaper models (`gemini-2.0-flash`, `claude-haiku-4`)
2. Run a local vLLM server
3. Reduce OODA loop turns by making tasks and system prompts more precise

---

## Testing

### Smoke test fails but agents work in examples

The smoke test is stricter than examples. Run with `--verbose` to see which assertion failed:

```bash
jarviscore smoketest --verbose
```

If retrying eventually passes, it is temporary LLM overload — not a code issue.

### All tests pass but my agent fails

1. Test with the simplest possible task first:
   ```python
   task = "Calculate 2 + 2. Store the result in `result`."
   ```
2. Check the trace log:
   ```bash
   cat traces/<workflow>_<step>.jsonl | python -m json.tool
   ```
3. Add complexity incrementally once the simple case passes.

---

## Debug Mode

```bash
# .env
LOG_LEVEL=DEBUG
```

Then tail:

```bash
tail -f logs/<latest>.log
```

---

## Getting Help

When opening an issue on [GitHub](https://github.com/Prescott-Data/jarviscore-framework/issues), include:

- Python version: `python --version`
- JarvisCore version: `pip show jarviscore-framework`
- LLM provider (Gemini / Claude / Azure / vLLM)
- Full error message and relevant log lines
- Minimal code to reproduce

Run diagnostics first and paste the output:

```bash
jarviscore check --verbose
jarviscore smoketest --verbose
```
