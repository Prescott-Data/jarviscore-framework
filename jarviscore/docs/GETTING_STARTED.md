# Getting Started with JarvisCore

Build your first AI agent in 5 minutes!

---

## What You'll Build

An **AutoAgent** that takes natural language prompts and automatically:
1. Generates Python code using an LLM
2. Executes the code securely
3. Returns the result

**No manual coding required** - just describe what you want!

---

## Prerequisites

- ✅ Python 3.10 or higher
- ✅ An API key from one of these LLM providers:
  - [Claude (Anthropic)](https://console.anthropic.com/) - Recommended
  - [Azure OpenAI](https://azure.microsoft.com/en-us/products/ai-services/openai-service)
  - [Google Gemini](https://ai.google.dev/)
  - Local vLLM server (free, self-hosted)

---

## Step 1: Install JarvisCore (30 seconds)

```bash
pip install jarviscore
```

---

## Step 2: Configure Your LLM (2 minutes)

Create a `.env` file in your project directory:

```bash
# Copy the example config
cp .env.example .env
```

Edit `.env` and add **ONE** of these API keys:

### Option 1: Claude (Recommended)
```bash
CLAUDE_API_KEY=sk-ant-your-key-here
```

### Option 2: Azure OpenAI
```bash
AZURE_API_KEY=your-key-here
AZURE_ENDPOINT=https://your-resource.openai.azure.com
AZURE_DEPLOYMENT=gpt-4o
```

### Option 3: Google Gemini
```bash
GEMINI_API_KEY=your-key-here
```

### Option 4: Local vLLM (Free, Self-Hosted)
```bash
LLM_ENDPOINT=http://localhost:8000
LLM_MODEL=Qwen/Qwen2.5-Coder-32B-Instruct
```

**Tip:** JarvisCore automatically tries providers in this order:
Claude → Azure → Gemini → vLLM

---

## Step 3: Validate Your Setup (30 seconds)

Run the health check to ensure everything works:

```bash
# Basic check
python -m jarviscore.cli.check

# Test LLM connectivity
python -m jarviscore.cli.check --validate-llm
```

You should see:
```
✓ Python Version: OK
✓ JarvisCore Package: OK
✓ Dependencies: OK
✓ .env File: OK
✓ Claude/Azure/Gemini: OK
```

Run the smoke test for end-to-end validation:

```bash
python -m jarviscore.cli.smoketest
```

✅ **If all tests pass**, you're ready to build agents!

---

## Step 4: Build Your First Agent (3 minutes)

Create a file called `my_first_agent.py`:

```python
import asyncio
from jarviscore import Mesh
from jarviscore.profiles import AutoAgent


# 1. Define your agent
class CalculatorAgent(AutoAgent):
    role = "calculator"
    capabilities = ["math", "calculations"]
    system_prompt = """
    You are a math expert. Generate Python code to solve problems.
    Always store the result in a variable named 'result'.
    """


# 2. Create and run
async def main():
    # Initialize the mesh
    mesh = Mesh(mode="autonomous")

    # Add your agent
    mesh.add(CalculatorAgent)

    # Start the mesh
    await mesh.start()

    # Execute a task with a simple prompt
    results = await mesh.workflow("calc-workflow", [
        {
            "agent": "calculator",
            "task": "Calculate the factorial of 10"
        }
    ])

    # Get the result
    result = results[0]
    print(f"Status: {result['status']}")
    print(f"Output: {result['output']}")
    print(f"Execution time: {result['execution_time']:.2f}s")

    # Stop the mesh
    await mesh.stop()


if __name__ == "__main__":
    asyncio.run(main())
```

### Run it:

```bash
python my_first_agent.py
```

### Expected Output:

```
Status: success
Output: 3628800
Execution time: 4.23s
```

**🎉 Congratulations!** You just built an AI agent with zero manual coding!

---

## What Just Happened?

Behind the scenes, JarvisCore:

1. **Received your prompt**: "Calculate the factorial of 10"
2. **Generated Python code** using Claude/Azure/Gemini:
   ```python
   def factorial(n):
       if n == 0 or n == 1:
           return 1
       return n * factorial(n - 1)

   result = factorial(10)
   ```
3. **Executed the code** safely in a sandbox
4. **Returned the result**: 3628800

All from a single natural language prompt!

---

## Step 5: Try More Complex Examples

### Example 1: Data Processing

```python
class DataAgent(AutoAgent):
    role = "data_analyst"
    capabilities = ["data_processing", "statistics"]
    system_prompt = "You are a data analyst. Generate Python code for data tasks."


async def analyze_data():
    mesh = Mesh(mode="autonomous")
    mesh.add(DataAgent)
    await mesh.start()

    results = await mesh.workflow("data-workflow", [
        {
            "agent": "data_analyst",
            "task": """
            Given this list: [10, 20, 30, 40, 50]
            Calculate: mean, median, min, max, sum
            Return as a dict
            """
        }
    ])

    print(results[0]['output'])
    # Output: {'mean': 30.0, 'median': 30, 'min': 10, 'max': 50, 'sum': 150}

    await mesh.stop()
```

### Example 2: Text Processing

```python
class TextAgent(AutoAgent):
    role = "text_processor"
    capabilities = ["text", "nlp"]
    system_prompt = "You are a text processing expert."


async def process_text():
    mesh = Mesh(mode="autonomous")
    mesh.add(TextAgent)
    await mesh.start()

    results = await mesh.workflow("text-workflow", [
        {
            "agent": "text_processor",
            "task": """
            Count the words in this sentence:
            "JarvisCore makes building AI agents incredibly easy"
            """
        }
    ])

    print(results[0]['output'])  # Output: 7

    await mesh.stop()
```

### Example 3: Multi-Step Workflow

```python
async def multi_step_workflow():
    mesh = Mesh(mode="autonomous")
    mesh.add(CalculatorAgent)
    mesh.add(DataAgent)
    await mesh.start()

    results = await mesh.workflow("multi-step", [
        {
            "id": "step1",
            "agent": "calculator",
            "task": "Calculate 5 factorial"
        },
        {
            "id": "step2",
            "agent": "data_analyst",
            "task": "Take the result from step1 and calculate its square root",
            "dependencies": ["step1"]  # Waits for step1 to complete
        }
    ])

    print(f"Factorial(5): {results[0]['output']}")      # 120
    print(f"Square root: {results[1]['output']:.2f}")   # 10.95

    await mesh.stop()
```

---

## Key Concepts

### 1. AutoAgent Profile

The `AutoAgent` profile handles the "prompt → code → result" workflow automatically:

```python
class MyAgent(AutoAgent):
    role = "unique_name"              # Unique identifier
    capabilities = ["skill1", "skill2"]  # What it can do
    system_prompt = "Instructions for the LLM"  # How to generate code
```

### 2. Mesh

The `Mesh` is the orchestrator that manages agents and workflows:

```python
mesh = Mesh(mode="autonomous")  # Autonomous mode for AutoAgent
mesh.add(MyAgent)               # Register your agent
await mesh.start()              # Initialize
results = await mesh.workflow(...)  # Execute tasks
await mesh.stop()               # Cleanup
```

### 3. Workflow

A workflow is a list of tasks to execute:

```python
results = await mesh.workflow("workflow-id", [
    {
        "agent": "agent_role",     # Which agent to use
        "task": "What to do",      # Natural language prompt
        "dependencies": []         # Optional: wait for other steps
    }
])
```

### 4. Results

Each task returns a result dict:

```python
{
    "status": "success",           # success or failure
    "output": 42,                  # The actual result
    "execution_time": 3.14,        # Seconds
    "repairs": 0,                  # Auto-fix attempts
    "code": "result = 6 * 7",      # Generated code
    "agent_id": "calculator-abc123"
}
```

---

## Configuration Options

### Sandbox Mode

Choose between local or remote code execution:

```bash
# Local (default) - runs on your machine
SANDBOX_MODE=local

# Remote - runs on Azure Container Apps (more secure)
SANDBOX_MODE=remote
SANDBOX_SERVICE_URL=https://your-sandbox-service.com
```

### LLM Settings

Fine-tune LLM behavior:

```bash
# Model selection (provider-specific)
CLAUDE_MODEL=claude-sonnet-4        # Claude
AZURE_DEPLOYMENT=gpt-4o             # Azure
GEMINI_MODEL=gemini-1.5-flash       # Gemini
LLM_MODEL=Qwen/Qwen2.5-Coder-32B   # vLLM

# Generation parameters
LLM_TEMPERATURE=0.0   # 0.0 = deterministic, 1.0 = creative
LLM_MAX_TOKENS=2000   # Max response length
LLM_TIMEOUT=120       # Request timeout (seconds)
```

### Logging

Control log verbosity:

```bash
LOG_LEVEL=INFO   # DEBUG, INFO, WARNING, ERROR, CRITICAL
```

---

## Common Patterns

### Pattern 1: Error Handling

```python
try:
    results = await mesh.workflow("workflow-1", [
        {"agent": "calculator", "task": "Calculate 1/0"}
    ])

    if results[0]['status'] == 'failure':
        print(f"Error: {results[0]['error']}")
        # The agent automatically attempted repairs
        print(f"Repair attempts: {results[0]['repairs']}")

except Exception as e:
    print(f"Workflow failed: {e}")
```

### Pattern 2: Dynamic Tasks

```python
user_input = "Calculate the area of a circle with radius 5"

results = await mesh.workflow("dynamic", [
    {"agent": "calculator", "task": user_input}
])

print(results[0]['output'])  # 78.54
```

### Pattern 3: Context Passing

Pass data between steps:

```python
results = await mesh.workflow("context-workflow", [
    {
        "id": "generate",
        "agent": "data_analyst",
        "task": "Generate a list of 10 random numbers between 1 and 100"
    },
    {
        "id": "analyze",
        "agent": "data_analyst",
        "task": "Calculate statistics on the numbers from step 'generate'",
        "dependencies": ["generate"]
    }
])

numbers = results[0]['output']
stats = results[1]['output']
print(f"Numbers: {numbers}")
print(f"Statistics: {stats}")
```

---

## Troubleshooting

### Issue: "No LLM providers configured"

**Solution:** Check your `.env` file has a valid API key:
```bash
python -m jarviscore.cli.check --validate-llm
```

### Issue: "Task failed: Unknown error"

**Solution:** Check logs for details:
```bash
ls -la logs/
cat logs/<agent>/<latest>.json
```

Run smoke test with verbose output:
```bash
python -m jarviscore.cli.smoketest --verbose
```

### Issue: Slow execution

**Causes:**
1. LLM latency (2-5s per request)
2. Complex prompts
3. Network issues

**Solutions:**
- Use faster models (Claude Haiku, Gemini Flash)
- Simplify prompts
- Use local vLLM for zero-latency

### Issue: Generated code has errors

**Good news:** AutoAgent automatically attempts to fix errors!

It will:
1. Detect the error
2. Ask the LLM to fix the code
3. Retry execution (up to 3 times)

Check `repairs` in the result to see how many fixes were needed.

---

## Next Steps

1. **Read the User Guide**: Complete documentation at [USER_GUIDE.md](USER_GUIDE.md)
2. **Explore Examples**: Check out `examples/` directory
3. **Try the API Reference**: [API_REFERENCE.md](API_REFERENCE.md)
4. **Configuration Guide**: [CONFIGURATION.md](CONFIGURATION.md)
5. **Troubleshooting**: [TROUBLESHOOTING.md](TROUBLESHOOTING.md)

---

## Best Practices

### ✅ DO

- **Be specific in prompts**: "Calculate factorial of 10" > "Do math"
- **Test with simple tasks first**: Validate your setup works
- **Use appropriate models**: Haiku/Flash for simple tasks, Opus/GPT-4 for complex
- **Monitor costs**: Check LLM usage if using paid APIs
- **Read error messages**: They contain helpful hints

### ❌ DON'T

- **Use vague prompts**: "Do something" won't work well
- **Expect instant results**: LLM generation takes 2-5 seconds
- **Skip validation**: Always run health check after setup
- **Commit API keys**: Keep `.env` out of version control
- **Ignore logs**: They help debug issues

---

## FAQ

### Q: How much does it cost?

**A:** Depends on your LLM provider:
- **Claude**: ~$3-15 per million tokens (most expensive but best quality)
- **Azure**: ~$3-15 per million tokens (enterprise-grade)
- **Gemini**: $0.10-5 per million tokens (cheapest cloud option)
- **vLLM**: FREE (self-hosted, no API costs)

A typical simple task uses ~500 tokens = $0.0015 with Claude.

### Q: Is the code execution safe?

**A:** Yes! Code runs in an isolated sandbox:
- **Local mode**: Restricted Python environment (no file/network access)
- **Remote mode**: Azure Container Apps (fully isolated containers)

### Q: Can I use my own LLM?

**A:** Yes! Point `LLM_ENDPOINT` to any OpenAI-compatible API:
```bash
LLM_ENDPOINT=http://localhost:8000  # Local vLLM
LLM_ENDPOINT=https://your-api.com   # Custom endpoint
```

### Q: What if the LLM generates bad code?

**A:** AutoAgent automatically detects and fixes errors:
1. Catches syntax/runtime errors
2. Sends error to LLM with fix instructions
3. Retries with corrected code (up to 3 attempts)

Check `repairs` in the result to see how many fixes were needed.

### Q: Can I see the generated code?

**A:** Yes! It's in the result:
```python
result = results[0]
print(result['code'])  # Shows the generated Python code
```

Or check logs:
```bash
cat logs/<agent-role>/<result-id>.json
```

### Q: How do I deploy this in production?

**A:** See the User Guide for:
- Remote sandbox configuration (Azure Container Apps)
- High-availability setup
- Monitoring and logging
- Cost optimization

---

## Support

Need help?

1. **Check docs**: [USER_GUIDE.md](USER_GUIDE.md) | [TROUBLESHOOTING.md](TROUBLESHOOTING.md)
2. **Run diagnostics**:
   ```bash
   python -m jarviscore.cli.check --verbose
   python -m jarviscore.cli.smoketest --verbose
   ```
3. **Check logs**: `cat logs/<agent>/<latest>.json`
4. **Report issues**: [GitHub Issues](https://github.com/yourusername/jarviscore/issues)

---

**🚀 Happy building with JarvisCore!**

*Built for the AutoAgent/Prompt-Dev generation - where AI writes the code, you write the prompts.*
