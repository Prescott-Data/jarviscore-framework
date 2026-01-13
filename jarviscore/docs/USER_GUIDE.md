# JarvisCore User Guide

Practical guide to building agent systems with JarvisCore.

---

## Table of Contents

1. [Quick Start](#quick-start)
2. [Basic Concepts](#basic-concepts)
3. [AutoAgent Tutorial](#autoagent-tutorial)
4. [CustomAgent Tutorial](#customagent-tutorial)
5. [Multi-Agent Workflows](#multi-agent-workflows)
6. [Internet Search](#internet-search)
7. [Remote Sandbox](#remote-sandbox)
8. [Result Storage](#result-storage)
9. [Code Registry](#code-registry)
10. [Best Practices](#best-practices)
11. [Common Patterns](#common-patterns)
12. [Troubleshooting](#troubleshooting)

---

## Quick Start

### Step 1: Installation (1 minute)

```bash
pip install jarviscore
```

### Step 2: Configuration (2 minutes)

JarvisCore needs an LLM provider to generate code for AutoAgent. Copy the example config:

```bash
cp .env.example .env
```

Edit `.env` and add **one** of these API keys:

```bash
# Option 1: Claude (Recommended)
CLAUDE_API_KEY=sk-ant-your-key-here

# Option 2: Azure OpenAI
AZURE_API_KEY=your-key-here
AZURE_ENDPOINT=https://your-resource.openai.azure.com
AZURE_DEPLOYMENT=gpt-4o

# Option 3: Google Gemini
GEMINI_API_KEY=your-key-here

# Option 4: Local vLLM
LLM_ENDPOINT=http://localhost:8000
```

### Step 3: Validate Setup (30 seconds)

Run the health check to ensure everything works:

```bash
# Basic check
python -m jarviscore.cli.check

# Test LLM connectivity
python -m jarviscore.cli.check --validate-llm
```

Run the smoke test to validate end-to-end:

```bash
python -m jarviscore.cli.smoketest
```

### Step 4: Your First Agent (30 seconds)

```python
import asyncio
from jarviscore import Mesh
from jarviscore.profiles import AutoAgent

async def main():
    # Create mesh
    mesh = Mesh(mode="autonomous")

    # Add calculator agent
    mesh.add_agent(
        AutoAgent,
        role="calculator",
        capabilities=["math", "calculation"],
        system_prompt="You are a math expert"
    )

    # Start mesh
    await mesh.start()

    # Execute task
    results = await mesh.run_workflow([
        {"agent": "calculator", "task": "Calculate the factorial of 10"}
    ])

    print(results[0]['output'])  # 3628800

    # Cleanup
    await mesh.stop()

if __name__ == '__main__':
    asyncio.run(main())
```

**That's it!** No configuration files, no setup, just three steps:
1. Create mesh
2. Add agent
3. Run task

---

## Basic Concepts

### The Mesh

The **Mesh** is your control center. It manages agents and orchestrates workflows.

```python
# Autonomous mode (single machine)
mesh = Mesh(mode="autonomous")

# Distributed mode (P2P mesh across network)
mesh = Mesh(mode="distributed")
```

### Agents

**Agents** are workers that execute tasks. JarvisCore has two agent types:

1. **AutoAgent**: Zero-config, LLM-powered (for rapid prototyping)
2. **CustomAgent**: Full control (for production systems)

### Workflows

**Workflows** are sequences of tasks with dependencies:

```python
await mesh.run_workflow([
    {"agent": "scraper", "task": "Scrape data"},
    {"agent": "processor", "task": "Clean data", "depends_on": [0]},
    {"agent": "storage", "task": "Save data", "depends_on": [1]}
])
```

---

## AutoAgent Tutorial

### Example 1: Simple Calculator

```python
import asyncio
from jarviscore import Mesh
from jarviscore.profiles import AutoAgent

async def calculator_demo():
    mesh = Mesh()

    mesh.add_agent(
        AutoAgent,
        role="calculator",
        capabilities=["math", "calculation"],
        system_prompt="You are a mathematical calculation expert"
    )

    await mesh.start()

    # Single calculation
    result = await mesh.run_workflow([
        {"agent": "calculator", "task": "Calculate 15!"}
    ])

    print(f"15! = {result[0]['output']}")

    await mesh.stop()

asyncio.run(calculator_demo())
```

### Example 2: Data Analyst

```python
async def data_analyst_demo():
    mesh = Mesh()

    mesh.add_agent(
        AutoAgent,
        role="analyst",
        capabilities=["data_analysis", "statistics"],
        system_prompt="You are a data analyst expert"
    )

    await mesh.start()

    result = await mesh.run_workflow([{
        "agent": "analyst",
        "task": """
        Given this data: [23, 45, 12, 67, 89, 34, 56, 78, 90, 11]
        Calculate: mean, median, mode, standard deviation, and min/max
        """
    }])

    print(result[0]['output'])
    # {'mean': 50.5, 'median': 50.5, 'std': 28.7, ...}

    await mesh.stop()

asyncio.run(data_analyst_demo())
```

### Example 3: Text Processor

```python
async def text_processor_demo():
    mesh = Mesh()

    mesh.add_agent(
        AutoAgent,
        role="processor",
        capabilities=["text_processing", "nlp"],
        system_prompt="You are a text processing expert"
    )

    await mesh.start()

    text = """
    The quick brown fox jumps over the lazy dog.
    Python is a popular programming language.
    """

    result = await mesh.run_workflow([{
        "agent": "processor",
        "task": f"""
        Analyze this text and return:
        - Word count
        - Sentence count
        - Most common word
        - Text: {text}
        """
    }])

    print(result[0]['output'])

    await mesh.stop()

asyncio.run(text_processor_demo())
```

---

## CustomAgent Tutorial

### Example 1: API Integration

```python
from jarviscore.profiles import CustomAgent
import aiohttp

class WeatherAgent(CustomAgent):
    """Agent that fetches weather data from external API."""

    async def setup(self):
        """Initialize API client."""
        self.api_key = "your-api-key"
        self.base_url = "https://api.weather.com"

    async def execute_task(self, task):
        """Execute weather query."""
        task_desc = task.get('task', '')

        # Extract city from task description
        city = self._extract_city(task_desc)

        # Fetch weather data
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{self.base_url}/weather?city={city}&key={self.api_key}"
            ) as response:
                data = await response.json()

        # Track cost (optional)
        self.track_cost(cost_usd=0.001)

        return {
            "status": "success",
            "output": {
                "city": city,
                "temperature": data['temp'],
                "conditions": data['conditions']
            },
            "agent": self.agent_id
        }

    def _extract_city(self, text):
        """Simple city extraction logic."""
        # Your parsing logic here
        return "New York"

# Usage
async def weather_demo():
    mesh = Mesh()

    mesh.add_agent(
        WeatherAgent,
        role="weather",
        capabilities=["weather", "api"]
    )

    await mesh.start()

    result = await mesh.run_workflow([
        {"agent": "weather", "task": "Get weather for New York"}
    ])

    print(result[0]['output'])

    await mesh.stop()

asyncio.run(weather_demo())
```

### Example 2: Database Agent

```python
from jarviscore.profiles import CustomAgent
import asyncpg

class DatabaseAgent(CustomAgent):
    """Agent that queries PostgreSQL database."""

    async def setup(self):
        """Connect to database."""
        self.pool = await asyncpg.create_pool(
            host='localhost',
            database='mydb',
            user='user',
            password='password'
        )

    async def teardown(self):
        """Close database connection."""
        await self.pool.close()

    async def execute_task(self, task):
        """Execute database query."""
        query = task.get('task', '')

        async with self.pool.acquire() as conn:
            # Execute query
            rows = await conn.fetch(query)

            # Convert to list of dicts
            results = [dict(row) for row in rows]

        return {
            "status": "success",
            "output": results,
            "agent": self.agent_id
        }

# Usage
async def database_demo():
    mesh = Mesh()

    mesh.add_agent(
        DatabaseAgent,
        role="database",
        capabilities=["database", "query"]
    )

    await mesh.start()

    result = await mesh.run_workflow([
        {"agent": "database", "task": "SELECT * FROM users LIMIT 10"}
    ])

    print(f"Found {len(result[0]['output'])} users")

    await mesh.stop()

asyncio.run(database_demo())
```

### Example 3: LangChain Integration

```python
from jarviscore.profiles import CustomAgent
from langchain_openai import ChatOpenAI
from langchain.prompts import ChatPromptTemplate
from langchain.schema.runnable import RunnableSequence

class LangChainAgent(CustomAgent):
    """Agent using LangChain for LLM interactions."""

    async def setup(self):
        """Initialize LangChain components."""
        self.llm = ChatOpenAI(model="gpt-4")

        self.prompt = ChatPromptTemplate.from_messages([
            ("system", "You are a helpful assistant"),
            ("user", "{input}")
        ])

        self.chain = self.prompt | self.llm

    async def execute_task(self, task):
        """Execute task using LangChain."""
        task_desc = task.get('task', '')

        # Run LangChain
        response = await self.chain.ainvoke({"input": task_desc})

        # Track tokens and cost
        self.track_cost(
            input_tokens=100,
            output_tokens=50,
            cost_usd=0.002
        )

        return {
            "status": "success",
            "output": response.content,
            "agent": self.agent_id
        }

# Usage
async def langchain_demo():
    mesh = Mesh()

    mesh.add_agent(
        LangChainAgent,
        role="assistant",
        capabilities=["chat", "qa"]
    )

    await mesh.start()

    result = await mesh.run_workflow([
        {"agent": "assistant", "task": "Explain quantum computing"}
    ])

    print(result[0]['output'])

    await mesh.stop()

asyncio.run(langchain_demo())
```

---

## Multi-Agent Workflows

### Example 1: Data Pipeline

```python
async def data_pipeline():
    mesh = Mesh()

    # Add three agents
    mesh.add_agent(
        AutoAgent,
        role="scraper",
        capabilities=["web_scraping", "data_collection"],
        system_prompt="You are a web scraping expert"
    )

    mesh.add_agent(
        AutoAgent,
        role="processor",
        capabilities=["data_processing", "cleaning"],
        system_prompt="You are a data cleaning expert"
    )

    mesh.add_agent(
        AutoAgent,
        role="analyzer",
        capabilities=["analysis", "statistics"],
        system_prompt="You are a data analysis expert"
    )

    await mesh.start()

    # Run workflow with dependencies
    results = await mesh.run_workflow([
        {
            "id": "scrape",
            "agent": "scraper",
            "task": "Generate sample e-commerce data (10 products with prices)"
        },
        {
            "id": "clean",
            "agent": "processor",
            "task": "Clean and normalize the product data",
            "depends_on": ["scrape"]
        },
        {
            "id": "analyze",
            "agent": "analyzer",
            "task": "Calculate price statistics (mean, median, range)",
            "depends_on": ["clean"]
        }
    ])

    # Each step gets context from previous steps
    print("Scrape result:", results[0]['output'])
    print("Clean result:", results[1]['output'])
    print("Analysis:", results[2]['output'])

    await mesh.stop()

asyncio.run(data_pipeline())
```

### Example 2: Report Generator

```python
async def report_generator():
    mesh = Mesh()

    mesh.add_agent(
        AutoAgent,
        role="researcher",
        capabilities=["research", "data_gathering"],
        system_prompt="You are a researcher",
        enable_search=True  # Enable internet search
    )

    mesh.add_agent(
        AutoAgent,
        role="writer",
        capabilities=["writing", "formatting"],
        system_prompt="You are a technical writer"
    )

    await mesh.start()

    results = await mesh.run_workflow([
        {
            "id": "research",
            "agent": "researcher",
            "task": "Research latest Python 3.12 features"
        },
        {
            "id": "write",
            "agent": "writer",
            "task": "Write a 2-paragraph summary of the research findings",
            "depends_on": ["research"]
        }
    ])

    print("Research:", results[0]['output'])
    print("\nReport:", results[1]['output'])

    await mesh.stop()

asyncio.run(report_generator())
```

---

## Internet Search

Enable web search for research tasks:

```python
from jarviscore import Mesh
from jarviscore.profiles import AutoAgent

async def search_demo():
    mesh = Mesh()

    mesh.add_agent(
        AutoAgent,
        role="researcher",
        capabilities=["research", "web_search"],
        system_prompt="You are an expert researcher",
        enable_search=True  # ← Enable internet search
    )

    await mesh.start()

    result = await mesh.run_workflow([{
        "agent": "researcher",
        "task": "Search for 'Python asyncio best practices' and summarize the top 3 results"
    }])

    print(result[0]['output'])
    # Returns: Summary of top 3 search results

    await mesh.stop()

asyncio.run(search_demo())
```

**Search Capabilities:**
- DuckDuckGo web search
- Content extraction from URLs
- Automatic summarization
- No API keys required

---

## Remote Sandbox

Use remote code execution for better security:

### Enable Remote Sandbox

```bash
# .env file
SANDBOX_MODE=remote
SANDBOX_SERVICE_URL=https://browser-task-executor.bravesea-3f5f7e75.eastus.azurecontainerapps.io
```

### Test Remote Execution

```python
from jarviscore.execution import create_sandbox_executor

async def test_remote():
    executor = create_sandbox_executor(
        timeout=30,
        config={
            'sandbox_mode': 'remote',
            'sandbox_service_url': 'https://...'
        }
    )

    code = "result = 2 + 2"
    result = await executor.execute(code)

    print(f"Mode: {result['mode']}")  # "remote"
    print(f"Output: {result['output']}")  # 4
    print(f"Time: {result['execution_time']}s")

asyncio.run(test_remote())
```

**Benefits:**
- Full process isolation
- Better security
- Azure Container Apps hosting
- Automatic fallback to local

**When to use:**
- Production deployments
- Untrusted code execution
- Multi-tenant systems
- High security requirements

---

## Result Storage

All execution results are automatically stored:

### Access Result Storage

```python
from jarviscore.execution import create_result_handler

handler = create_result_handler()

# Get specific result
result = handler.get_result("calculator-abc123_2026-01-12T12-00-00_123456")

# Get agent's recent results
recent = handler.get_agent_results("calculator-abc123", limit=10)

for r in recent:
    print(f"{r['task']}: {r['output']}")
```

### Storage Location

```
logs/
├── calculator-abc123/
│   ├── calculator-abc123_2026-01-12T12-00-00_123456.json
│   └── calculator-abc123_2026-01-12T12-05-30_789012.json
├── analyzer-def456/
│   └── analyzer-def456_2026-01-12T12-10-00_345678.json
└── code_registry/
    ├── index.json
    └── functions/
        ├── calculator-abc123_3a5b2f76.py
        └── analyzer-def456_8b2c4d91.py
```

**What's Stored:**
- Task description
- Generated code
- Execution output
- Status (success/failure)
- Execution time
- Token usage
- Cost (if tracked)
- Repair attempts
- Timestamp

---

## Code Registry

Reuse successful code across agents:

### Search Registry

```python
from jarviscore.execution import create_code_registry

registry = create_code_registry()

# Search for math functions
matches = registry.search(
    query="factorial calculation",
    capabilities=["math"],
    limit=3
)

for match in matches:
    print(f"Function: {match['function_id']}")
    print(f"Task: {match['task']}")
    print(f"Output sample: {match['output_sample']}")
```

### Get Function Code

```python
# Get specific function
func = registry.get("calculator-abc123_3a5b2f76")

print("Code:")
print(func['code'])

print("\nMetadata:")
print(f"Agent: {func['agent_id']}")
print(f"Capabilities: {func['capabilities']}")
print(f"Registered: {func['registered_at']}")
```

**Use Cases:**
- Share functions between agents
- Build function library
- Audit generated code
- Performance analysis

---

## Best Practices

### 1. Always Use Context Managers

```python
# Good
async with Mesh() as mesh:
    mesh.add_agent(AutoAgent, ...)
    await mesh.start()
    results = await mesh.run_workflow([...])
    # Automatic cleanup

# Manual (also works)
mesh = Mesh()
try:
    await mesh.start()
    results = await mesh.run_workflow([...])
finally:
    await mesh.stop()
```

### 2. Handle Errors Gracefully

```python
try:
    results = await mesh.run_workflow([...])

    for i, result in enumerate(results):
        if result['status'] == 'failure':
            print(f"Step {i} failed: {result['error']}")
        else:
            print(f"Step {i} succeeded: {result['output']}")

except TimeoutError:
    print("Workflow timed out")
except RuntimeError as e:
    print(f"Runtime error: {e}")
```

### 3. Use Clear System Prompts

```python
# Good
system_prompt = """
You are a financial data analyst expert.
Your task is to analyze stock data and provide insights.
Always return results as structured JSON.
"""

# Bad
system_prompt = "You are helpful"
```

### 4. Set Appropriate Timeouts

```python
# Short tasks
mesh.add_agent(AutoAgent, ..., max_repair_attempts=1)

# Long-running tasks
config = {'execution_timeout': 600}  # 10 minutes
mesh = Mesh(config=config)
```

### 5. Monitor Costs

```python
class MyAgent(CustomAgent):
    async def execute_task(self, task):
        # ... do work ...

        # Track costs
        self.track_cost(
            input_tokens=500,
            output_tokens=200,
            cost_usd=0.015
        )

        return result
```

---

## Common Patterns

### Pattern 1: Fan-Out, Fan-In

```python
# Process multiple items in parallel, then aggregate
results = await mesh.run_workflow([
    # Fan-out: Process items
    {"id": "item1", "agent": "processor", "task": "Process item 1"},
    {"id": "item2", "agent": "processor", "task": "Process item 2"},
    {"id": "item3", "agent": "processor", "task": "Process item 3"},

    # Fan-in: Aggregate results
    {
        "id": "aggregate",
        "agent": "aggregator",
        "task": "Combine all processed items",
        "depends_on": ["item1", "item2", "item3"]
    }
])
```

### Pattern 2: Conditional Execution

```python
# Execute step 1
results = await mesh.run_workflow([
    {"id": "check", "agent": "validator", "task": "Validate input data"}
])

# Decide next step based on result
if results[0]['output']['valid']:
    results = await mesh.run_workflow([
        {"agent": "processor", "task": "Process valid data"}
    ])
else:
    print("Validation failed, skipping processing")
```

### Pattern 3: Retry with Different Agent

```python
try:
    # Try primary agent
    result = await mesh.run_workflow([
        {"agent": "primary_scraper", "task": "Scrape website"}
    ])
except Exception:
    # Fallback to backup agent
    result = await mesh.run_workflow([
        {"agent": "backup_scraper", "task": "Scrape website"}
    ])
```

---

## Troubleshooting

### Issue: Agent not found

```python
# Error: No agent found for step
# Solution: Check role/capability spelling
mesh.add_agent(AutoAgent, role="calculator", capabilities=["math"])

# This will fail
await mesh.run_workflow([
    {"agent": "calcul", "task": "..."}  # Typo!
])

# This works
await mesh.run_workflow([
    {"agent": "calculator", "task": "..."}  # Correct role
])

# This also works
await mesh.run_workflow([
    {"agent": "math", "task": "..."}  # Uses capability
])
```

### Issue: Mesh not started

```python
# Error: RuntimeError: Workflow engine not started
# Solution: Call mesh.start() before run_workflow()

mesh = Mesh()
mesh.add_agent(...)
await mesh.start()  # ← Don't forget this!
await mesh.run_workflow([...])
```

### Issue: Timeout

```python
# Error: TimeoutError: Execution exceeded 300 seconds
# Solution: Increase timeout

config = {'execution_timeout': 600}  # 10 minutes
mesh = Mesh(config=config)
```

### Issue: No LLM provider configured

```python
# Error: RuntimeError: No LLM provider configured
# Solution: Set environment variables

# .env file
CLAUDE_API_KEY=your-key
# or
AZURE_API_KEY=your-key
AZURE_ENDPOINT=https://...
```

### Issue: Code execution fails

```python
# Check logs for details
import logging
logging.basicConfig(level=logging.DEBUG)

# Enable verbose output
config = {'log_level': 'DEBUG'}
mesh = Mesh(config=config)
```

---

## Next Steps

1. **Read the [API Reference](API_REFERENCE.md)** for detailed component documentation
2. **Check the [Configuration Guide](CONFIGURATION.md)** for environment setup
3. **Explore examples/** directory for more code samples
4. **Join the community** on GitHub for support

---

## Version

User Guide for JarvisCore v0.1.0

Last Updated: 2026-01-12
