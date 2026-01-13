# JarvisCore Troubleshooting Guide

Common issues and solutions for AutoAgent/Prompt-Dev users.

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
pip install jarviscore

# Or install in development mode
cd jarviscore
pip install -e .
```

#### Issue: `ImportError: cannot import name 'AutoAgent'`

**Cause:** Old/cached installation

**Solution:**
```bash
pip uninstall jarviscore
pip install jarviscore
```

---

### 2. LLM Configuration Issues

#### Issue: `No LLM provider configured`

**Cause:** Missing API key in `.env`

**Solution:**
1. Copy example config:
   ```bash
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

### 5. Environment Issues

#### Issue: `.env file not found`

**Solution:**
```bash
# Create from example
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

### 6. Sandbox Configuration

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

### 7. Performance Issues

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

### 8. Testing Issues

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
   - JarvisCore version: `pip show jarviscore`
   - LLM provider used (Claude/Azure/Gemini)
   - Error message and logs
   - Minimal code to reproduce issue

4. **Create an issue:**
   - GitHub: https://github.com/yourusername/jarviscore/issues
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
   pip install --upgrade jarviscore
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

*Last updated: 2026-01-13*
