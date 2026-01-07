# JarvisCore Framework

**P2P distributed agent framework with LLM code generation and production-grade state management**

## Features

- ✅ **Simple Agent Definition** - Write just 3 attributes, framework handles everything
- ✅ **P2P Mesh Architecture** - Automatic agent discovery and task routing via SWIM protocol
- ✅ **Event-Sourced State** - Complete audit trail with crash recovery
- ✅ **Autonomous Execution** - LLM code generation with automatic repair
- ✅ **Human-in-the-Loop** - Days/weeks-long approval workflows
- ✅ **Cost Tracking** - Track LLM token usage per step and workflow

## Installation

```bash
pip install jarviscore
```

With all features:
```bash
pip install jarviscore[all]
```

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

- [User Guide](docs/USER_GUIDE.md)
- [API Reference](docs/API_REFERENCE.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Examples](examples/)

## Development Status

**Version:** 0.1.0 (Alpha)
**Day 1:** Core framework foundation ✅

## License

MIT License - see LICENSE file for details
