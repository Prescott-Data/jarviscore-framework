# JarvisCore Troubleshooting Guide

Common issues and solutions for AutoAgent and CustomAgent users.

---

## Quick Diagnostics

Run these commands to diagnose issues:

```bash
# Check installation and configuration
python -m jarviscore.cli.check

# Test LLM connectivity
python -m jarviscore.cli.check --validate-llm

# Run end-to-end smoke test
python -m jarviscore.cli.smoketest

# Verbose output for debugging
python -m jarviscore.cli.smoketest --verbose
```

---

## Common Issues

1. [Installation Problems](#1-installation-problems)
2. [LLM Configuration Issues](#2-llm-configuration-issues)
3. [Execution Errors](#3-execution-errors)
4. [Workflow Issues](#4-workflow-issues)
5. [CustomAgent Issues](#5-customagent-issues)
6. [Environment Issues](#6-environment-issues)
7. [Sandbox Configuration](#7-sandbox-configuration)
8. [Infrastructure & Memory Issues (v0.4.0)](#8-infrastructure--memory-issues-v040)
9. [P2P/Distributed Mode Issues](#9-p2pdistributed-mode-issues)
10. [Performance Issues](#10-performance-issues)
11. [Testing Issues](#11-testing-issues)

---

### 1. Installation Problems

#### Issue: `ModuleNotFoundError: No module named 'jarviscore'`

**Solution:**
```bash
pip install jarviscore-framework

# Or install in development mode
cd jarviscore
pip install -e .
```

#### Issue: `ImportError: cannot import name 'AutoAgent'`

**Cause:** Old/cached installation

**Solution:**
```bash
pip uninstall jarviscore-framework
pip install jarviscore-framework
```

---

### 2. LLM Configuration Issues

#### Issue: `No LLM provider configured`

**Cause:** Missing API key in `.env`

**Solution:**
1. Initialize project and copy example config:
   ```bash
   python -m jarviscore.cli.scaffold
   cp .env.example .env
   ```

2. Add your API key:
   ```bash
   # Choose ONE:
   CLAUDE_API_KEY=sk-ant-...
   # OR
   AZURE_API_KEY=...
   # OR
   GEMINI_API_KEY=...
   ```

3. Validate:
   ```bash
   python -m jarviscore.cli.check --validate-llm
   ```

#### Issue: `Error code: 401 - Unauthorized`

**Cause:** Invalid API key

**Solution:**
1. Verify your API key is correct
2. Check it hasn't expired
3. For Azure: Ensure AZURE_ENDPOINT and AZURE_DEPLOYMENT are correct

#### Issue: `Error code: 529 - Overloaded`

**Cause:** LLM provider temporarily overloaded (Claude, Azure, etc.)

**Solution:**
- This is temporary - retry after a few seconds
- The smoke test automatically retries 3 times
- Consider adding a backup LLM provider in `.env`

#### Issue: `Error code: 429 - Rate limit exceeded`

**Cause:** Too many requests to LLM API

**Solution:**
- Wait 60 seconds before retrying
- Check your API plan limits
- Consider upgrading your API plan

---

### 3. Execution Errors

#### Issue: `Task failed: Code execution timed out`

**Cause:** Generated code runs longer than timeout (default: 300s)

**Solution:**
Increase timeout in `.env`:
```bash
EXECUTION_TIMEOUT=600  # 10 minutes
```

#### Issue: `Sandbox execution failed: <error>`

**Cause:** Generated code has errors

**What happens:**
- Framework automatically attempts repairs (max 3 attempts)
- If repairs fail, the task fails

**Solution:**
1. Check logs for details:
   ```bash
   ls -la logs/
   cat logs/<latest-log>.log
   ```

2. Make prompt more specific:
   ```python
   task="Calculate factorial of 10. Store result in variable named 'result'."
   ```

3. Adjust system prompt:
   ```python
   class MyAgent(AutoAgent):
       system_prompt = """
       You are a Python expert. Generate clean, working code.
       - Use only standard library
       - Store final result in 'result' variable
       - Handle edge cases
       """
   ```

#### Issue: `Maximum repair attempts exceeded`

**Cause:** LLM unable to generate working code after 3 tries

**Solution:**
1. Simplify your task
2. Be more explicit in prompt
3. Check logs to see what errors occurred:
   ```bash
   cat logs/<latest-log>.log
   ```

---

### 4. Workflow Issues

#### Issue: `Agent not found: <role>`

**Cause:** Agent role mismatch

**Solution:**
```python
# Agent definition
class CalculatorAgent(AutoAgent):
    role = "calculator"  # <-- This name

# Workflow must match
mesh.workflow("wf-1", [
    {"agent": "calculator", "task": "..."}  # <-- Must match role
])
```

#### Issue: `Dependency not satisfied: <step-id>`

**Cause:** Workflow dependency chain broken

**Solution:**
```python
# Ensure dependencies exist
await mesh.workflow("wf-1", [
    {"id": "step1", "agent": "agent1", "task": "..."},
    {"id": "step2", "agent": "agent2", "task": "...",
     "dependencies": ["step1"]}  # step1 must exist
])
```

---

### 5. CustomAgent Issues

#### Issue: `execute_task not called`

**Cause:** Wrong mode for your use case

**Solution:**
```python
# For workflow orchestration (autonomous/distributed modes)
class MyAgent(CustomAgent):
    async def execute_task(self, task):  # Called by workflow engine
        return {"status": "success", "output": ...}

# For P2P mode, use run() instead
class MyAgent(CustomAgent):
    async def run(self):  # Called in P2P mode
        while not self.shutdown_requested:
            msg = await self.peers.receive(timeout=0.5)
            ...
```

#### Issue: `self.peers is None`

**Cause:** Agent not in P2P or distributed mode

**Solution:**
```python
# Ensure mesh is in p2p or distributed mode
mesh = Mesh(mode="distributed", config={  # or "p2p"
    'bind_port': 7950,
    'node_name': 'my-node',
})

# Check peers is available before using
if self.peers:
    result = await self.peers.as_tool().execute("ask_peer", {...})
```

#### Issue: `No response from peer`

**Cause:** Target agent not listening or wrong role

**Solution:**
```python
# Ensure target agent is running its run() loop
# In researcher agent:
async def run(self):
    while not self.shutdown_requested:
        msg = await self.peers.receive(timeout=0.5)
        if msg and msg.is_request:
            await self.peers.respond(msg, {"response": ...})

# When asking, use correct role
result = await self.peers.as_tool().execute(
    "ask_peer",
    {"role": "researcher", "question": "..."}  # Must match agent's role
)
```

---

### 6. Environment Issues

#### Issue: `.env file not found`

**Solution:**
```bash
# Initialize project first (creates .env.example)
python -m jarviscore.cli.scaffold

# Then copy and configure
cp .env.example .env

# Or create manually
cat > .env << 'EOF'
CLAUDE_API_KEY=your-key-here
EOF
```

#### Issue: `Environment variable not loading`

**Cause:** `.env` file in wrong location

**Solution:**
Place `.env` in one of these locations:
- Current working directory: `./env`
- Project root: `jarviscore/.env`

Or set environment variable directly:
```bash
export CLAUDE_API_KEY=your-key-here
python your_script.py
```

---

### 7. Sandbox Configuration

#### Issue: `Remote sandbox connection failed`

**Cause:** SANDBOX_SERVICE_URL incorrect or service down

**Solution:**
1. Use local sandbox (default):
   ```bash
   SANDBOX_MODE=local
   ```

2. Or verify remote URL:
   ```bash
   SANDBOX_MODE=remote
   SANDBOX_SERVICE_URL=https://your-sandbox-service.com
   ```

3. Test connectivity:
   ```bash
   curl https://your-sandbox-service.com/health
   ```

---

### 8. Infrastructure & Memory Issues (v0.4.0)

#### Issue: `self._redis_store` / `self._blob_storage` / `self.mailbox` is `None` after `setup()`

**Cause:** Accessing injected attributes in `__init__` instead of `setup()`, or using a
Mesh mode that does not start the full infrastructure.

**Solution:**
```python
# Wrong — __init__ runs before injection
class MyAgent(CustomAgent):
    def __init__(self):
        self.memory = UnifiedMemory(..., redis_store=self._redis_store)  # None here!

# Correct — setup() runs after injection
class MyAgent(CustomAgent):
    async def setup(self):
        await super().setup()
        self.memory = UnifiedMemory(..., redis_store=self._redis_store)  # injected ✓
```

Verify injection after `mesh.start()`:
```python
await mesh.start()
for agent in mesh.agents:
    print(f"{agent.role}: redis={agent._redis_store is not None} "
          f"blob={agent._blob_storage is not None} "
          f"mailbox={agent.mailbox is not None}")
```

---

#### Issue: `ConnectionError: Redis connection refused` / `Redis unavailable`

**Cause:** Redis is not running, or `REDIS_URL` is not set / incorrect.

**Solution:**
```bash
# Start Redis (quickest)
docker compose -f docker-compose.infra.yml up -d

# Verify Redis is responding
redis-cli ping   # → PONG

# Check REDIS_URL in .env
grep REDIS_URL .env   # → REDIS_URL=redis://localhost:6379/0
```

Required for: mailbox, distributed workflow, and UnifiedMemory.
Without `REDIS_URL`, these degrade gracefully — `_redis_store` / `mailbox` become `None`.

---

#### Issue: Silent task success with `execution_time ≈ 0.003s` and `output: null`

**Cause:** Agent-generated function tool raised `NameError: name 'context' is not defined`.
The sandbox catches the exception silently and returns a fallback result. This happens
when `context=task.get('context')` is not passed to `sandbox.execute()`.

**Diagnostic tell:**
```json
{"status": "success", "execution_time": 0.003, "output": null}
```
Real LLM-driven computation takes 1–30s. Sub-10ms means the code crashed instantly.

**Solution (v0.4.0 — already fixed):** Confirm `jarviscore/profiles/autoagent.py` has:
```python
result = await self.sandbox.execute(code, context=task.get('context'))
```
If you have a custom AutoAgent subclass that overrides `execute_task`, ensure you pass
`context=task.get('context')` when calling `sandbox.execute()`.

**For agent-generated function tools that read prior steps**, use the simple access pattern:
```python
# In system_prompt — tell the LLM to use this pattern:
research = context.get('previous_step_results', {}).get('fetch', {})
```

---

#### Per-Process Port Configuration — Multi-Node Setup

In a multi-node deployment each process needs a **unique port**. A single `BIND_PORT`
value in a shared `.env` file cannot serve four nodes that require four different ports.

**The right approach — explicit Mesh config dict (recommended for example scripts):**
```python
# Each script declares its own port as an architecture constant
BIND_PORT = 7949   # synthesizer — this is its role; the port is part of its identity
mesh = Mesh(mode="distributed", config={"bind_port": BIND_PORT, ...})
```

**The right approach — per-process env var (recommended for production / containers):**
```bash
# Set at process launch — not in a shared .env file
JARVISCORE_BIND_PORT=7949 python ex2_synthesizer.py
JARVISCORE_BIND_PORT=7946 python ex2_research_node1.py
```

JarvisCore reads `JARVISCORE_BIND_PORT` (not `BIND_PORT`) to keep per-process port
config cleanly separated from other shared settings in `.env`.

Port reference for Ex2:
| Script | SWIM port | ZMQ port | Role |
|--------|-----------|----------|------|
| `ex2_synthesizer.py` | 7949 | 8949 | Seed (no SEED_NODES) |
| `ex2_research_node1.py` | 7946 | 8946 | TechResearcher |
| `ex2_research_node2.py` | 7947 | 8947 | MarketResearcher |
| `ex2_research_node3.py` | 7948 | 8948 | RegResearcher |

**What NOT to do — shared .env for per-process settings:**
```bash
# .env — wrong for multi-node
BIND_PORT=7946   # which node does this belong to?
```
All four processes would read the same value. Use the Mesh `config` dict or
`JARVISCORE_BIND_PORT` set per-process instead.

---

#### Issue: Distributed step never starts — stuck in `"pending"` forever

**Cause:** One of: (a) `are_dependencies_met()` returning `False` because a prior step
never wrote its status to Redis; (b) no node has the matching agent role; (c) the step
was already claimed by another node.

**Diagnose:**
```bash
# See all step statuses for a workflow
redis-cli hgetall "workflow_graph:your-workflow-id"

# Check what step outputs exist
redis-cli keys "step_output:your-workflow-id:*"

# Check which workflows are active
redis-cli smembers "jarviscore:active_workflows"
```

**Solutions:**
1. Ensure the prior step completed: its `step_output:wf:step_id` key must exist in Redis
2. Confirm the node running the expected agent is alive and has joined the cluster
3. If a step is stuck in `"claimed"` (crashed mid-run), reset it:
   ```bash
   redis-cli hset "workflow_graph:wf-id" "step-id:status" "pending"
   redis-cli del "claim:wf-id:step-id"
   ```

---

#### Issue: `self._auth_manager` is `None` despite `requires_auth = True`

**Cause:** `NEXUS_GATEWAY_URL` is not set in `.env`. The Mesh only injects
`AuthenticationManager` when a gateway URL is configured.

**Solution:**
```bash
# In .env
NEXUS_GATEWAY_URL=https://your-dromos-gateway.example.com
AUTH_MODE=production
```

For local development without a Nexus gateway, use mock mode:
```bash
AUTH_MODE=mock
```

Or guard the call in your agent:
```python
if self._auth_manager:
    result = await self._auth_manager.make_authenticated_request(...)
else:
    # Graceful degradation path
```

---

#### Issue: `EpisodicLedger.append()` raises / events not appearing in Redis

**Cause:** Redis unavailable, or `UnifiedMemory` initialised without a valid `redis_store`.

**Diagnose:**
```bash
redis-cli xrange ledgers:your-workflow-id - +
# → (empty list) if no events written
```

**Solution:**
1. Ensure `REDIS_URL` is set and Redis is reachable
2. Confirm `UnifiedMemory` is initialised in `setup()` (not `__init__`):
   ```python
   async def setup(self):
       await super().setup()
       self.memory = UnifiedMemory(
           workflow_id="wf-001", step_id=self.role,
           agent_id=self.role,
           redis_store=self._redis_store,    # must not be None
           blob_storage=self._blob_storage,
       )
   ```
3. Check `self._redis_store is not None` before init

---

#### Issue: `blob_storage.load()` returns `None` for a path that should exist

**Cause:** (a) Path was saved with a different base; (b) `STORAGE_BASE_PATH` differs
between save and load runs; (c) file was saved to a different process's working directory.

**Diagnose:**
```bash
ls -la blob_storage/
find blob_storage/ -name "*.json" -o -name "*.md" | head -20
```

**Solution:**
- Use consistent path conventions: `{type}/{workflow_id}/{filename}.{ext}`
- Pin `STORAGE_BASE_PATH` in `.env` rather than relying on the default `./blob_storage`
- In CI/Docker, use an absolute path:
  ```bash
  STORAGE_BASE_PATH=/app/blob_storage
  ```

---

### 9. P2P / Distributed Mode Issues

#### Issue: `P2P coordinator failed to start`

**Cause:** Port already in use or network issue

**Solution:**
```bash
# Check if port is in use
lsof -i :7950

# Try different port
mesh = Mesh(mode="distributed", config={
    'bind_port': 7960,  # Different port
})
```

#### Issue: `Cannot connect to seed nodes`

**Cause:** Firewall, wrong address, or seed node not running

**Solution:**
```bash
# Check connectivity
nc -zv 192.168.1.10 7950

# Open firewall ports
sudo ufw allow 7950/tcp
sudo ufw allow 7950/udp

# Ensure seed node is running first
# On seed node:
mesh = Mesh(mode="distributed", config={
    'bind_host': '0.0.0.0',  # Listen on all interfaces
    'bind_port': 7950,
})
```

#### Issue: `Workflow not available in p2p mode`

**Cause:** P2P mode doesn't include workflow engine

**Solution:**
```python
# Use distributed mode for both workflow + P2P
mesh = Mesh(mode="distributed", config={...})

# Or use p2p mode with run() loops instead
mesh = Mesh(mode="p2p", config={...})
await mesh.start()
await mesh.run_forever()  # Agents use run() loops
```

#### Issue: `Agents not discovering each other`

**Cause:** Network configuration or timing

**Solution:**
```python
# Wait for mesh to stabilize after start
await mesh.start()
await asyncio.sleep(1)  # Give time for peer discovery

# Check if peers are available
agent = mesh.get_agent("my_role")
if agent.peers:
    print("Peers available")
```

---

### 10. Performance Issues

#### Issue: Code generation is slow (>10 seconds)

**Cause:** LLM latency or complex prompt

**Solutions:**
1. **Use faster model:**
   ```bash
   # Claude
   CLAUDE_MODEL=claude-haiku-4

   # Gemini
   GEMINI_MODEL=gemini-1.5-flash
   ```

2. **Simplify system prompt:**
   - Remove unnecessary instructions
   - Be concise but specific

3. **Use local vLLM:**
   ```bash
   LLM_ENDPOINT=http://localhost:8000
   LLM_MODEL=Qwen/Qwen2.5-Coder-32B-Instruct
   ```

#### Issue: High LLM API costs

**Solutions:**
1. Use cheaper models (Haiku, Flash)
2. Set up local vLLM (free)
3. Cache common operations
4. Reduce MAX_REPAIR_ATTEMPTS in `.env`

---

### 11. Testing Issues

#### Issue: Smoke test fails but examples work

**Cause:** Temporary LLM issues or network

**Solution:**
- Smoke test is more strict than examples
- Run with verbose to see details:
  ```bash
  python -m jarviscore.cli.smoketest --verbose
  ```
- If retrying works eventually, it's temporary LLM overload

#### Issue: All tests pass but my agent fails

**Cause:** Task-specific issue

**Solution:**
1. Test with simpler task first:
   ```python
   task="Calculate 2 + 2"  # Simple
   ```

2. Gradually increase complexity:
   ```python
   task="Calculate factorial of 5"  # Medium
   ```

3. Check agent logs:
   ```bash
   cat logs/<agent-role>_*.log
   ```

---

## Debug Mode

Enable verbose logging for detailed diagnostics:

```bash
# In .env
LOG_LEVEL=DEBUG
```

Then check logs:
```bash
tail -f logs/<latest>.log
```

---

## Getting Help

If issues persist:

1. **Check logs:**
   ```bash
   ls -la logs/
   cat logs/<latest>.log
   ```

2. **Run diagnostics:**
   ```bash
   python -m jarviscore.cli.check --verbose
   python -m jarviscore.cli.smoketest --verbose
   ```

3. **Provide this info when asking for help:**
   - Python version: `python --version`
   - JarvisCore version: `pip show jarviscore-framework`
   - LLM provider used (Claude/Azure/Gemini)
   - Error message and logs
   - Minimal code to reproduce issue

4. **Create an issue:**
   - GitHub: https://github.com/Prescott-Data/jarviscore-framework/issues
   - Include diagnostics output above

---

## Best Practices to Avoid Issues

1. **Always validate setup first:**
   ```bash
   python -m jarviscore.cli.check --validate-llm
   python -m jarviscore.cli.smoketest
   ```

2. **Use specific prompts:**
   - ❌ "Do math"
   - ✅ "Calculate the factorial of 10 and store result in 'result' variable"

3. **Start simple, then scale:**
   - Test with simple tasks first
   - Add complexity gradually
   - Monitor logs for warnings

4. **Keep dependencies updated:**
   ```bash
   pip install --upgrade jarviscore-framework
   ```

5. **Use version control for `.env`:**
   - Never commit API keys
   - Use `.env.example` as template
   - Document required variables

---

## Performance Benchmarks (Expected)

Use these as baselines:

| Operation | Expected Time | Notes |
|-----------|--------------|-------|
| Sandbox execution | 2-5ms | Local code execution |
| Code generation | 2-4s | LLM response time |
| Simple task (e.g., 2+2) | 3-5s | End-to-end |
| Complex task | 5-15s | With potential repairs |
| Multi-step workflow (2 steps) | 7-10s | Sequential execution |

If significantly slower:
1. Check network latency
2. Try different LLM model
3. Consider local vLLM
4. Check LOG_LEVEL (DEBUG is slower)

---

*Last updated: 2026-02-19*

---

## Version

Troubleshooting Guide for JarvisCore v1.0.1
