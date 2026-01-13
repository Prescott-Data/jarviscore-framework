# JarvisCore Framework

**P2P distributed agent framework with LLM code generation and production-grade state management**

## Features

- ✅ **Simple Agent Definition** - Write just 3 attributes, framework handles everything
- ✅ **P2P Mesh Architecture** - Automatic agent discovery and task routing via SWIM protocol
- ✅ **Event-Sourced State** - Complete audit trail with crash recovery
- ✅ **Autonomous Execution** - LLM code generation with automatic repair

## Installation

```bash
pip install jarviscore
```

## Setup & Validation

### 1. Configure LLM Provider

Copy the example config and add your API key:

```bash
cp .env.example .env
# Edit .env and add one of: CLAUDE_API_KEY, AZURE_API_KEY, GEMINI_API_KEY, or LLM_ENDPOINT
```

### 2. Validate Installation

```bash
# Check setup
python -m jarviscore.cli.check

# Test LLM connectivity
python -m jarviscore.cli.check --validate-llm

# Run smoke test (end-to-end validation)
python -m jarviscore.cli.smoketest
```

✅ **All checks pass?** You're ready to build agents!

## Quick Start

```python
from jarviscore import Mesh
from jarviscore.profiles import PromptDevAgent

# Define agent (3 lines)
class ScraperAgent(PromptDevAgent):
    role = "scraper"
    capabilities = ["web_scraping"]
    system_prompt = "You are an expert web scraper..."

# Create mesh and run workflow
mesh = Mesh(mode="autonomous")
mesh.add(ScraperAgent)
await mesh.start()

results = await mesh.workflow(
    workflow_id="wf-123",
    steps=[
        {"id": "scrape", "task": "Scrape example.com", "role": "scraper"}
    ]
)
```

## Architecture

JarvisCore is built on three layers:

1. **Execution Layer (20%)** - Profile-specific execution (Prompt-Dev, MCP)
2. **Orchestration Layer (60%)** - Workflow engine, dependencies, state management
3. **P2P Layer (20%)** - Agent discovery, task routing, mesh coordination

## Documentation

- [User Guide](jarviscore/docs/USER_GUIDE.md) - Complete guide for AutoAgent users
- [API Reference](jarviscore/docs/API_REFERENCE.md) - Detailed API documentation
- [Configuration Guide](jarviscore/docs/CONFIGURATION.md) - Settings and environment variables
- [Troubleshooting](jarviscore/docs/TROUBLESHOOTING.md) - Common issues and solutions
- [Examples](examples/) - Working code examples

## Development Status

**Version:** 0.1.0 (Alpha)
**Day 1:** Core framework foundation ✅

## License

MIT License - see LICENSE file for details
