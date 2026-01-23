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

### 8. P2P/Distributed Mode Issues

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

### 9. Performance Issues

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

### 9. Testing Issues

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

*Last updated: 2026-01-23*

---

## Version

Troubleshooting Guide for JarvisCore v0.2.1
