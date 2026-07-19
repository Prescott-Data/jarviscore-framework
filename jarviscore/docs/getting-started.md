---
icon: material/rocket-launch
---

# Getting Started

This guide takes you from a fresh Python environment to a running JarvisCore agent in under ten minutes. It covers installation, initial configuration, and your first working agent.

---

## Requirements

JarvisCore requires Python 3.10 or later. No infrastructure is required to run a minimal agent — the first working example in this guide uses only an LLM API key.

**Optional: Docker** is required for two capabilities:

- `jarviscore nexus up` — starts the local Nexus broker and gateway for OAuth2 credential management
- `jarviscore-framework[browser]` — Playwright runs in a Docker-managed Chromium for browser automation

If you are not using Nexus or browser automation, Docker is not needed.

---

## Installation

```bash
pip install jarviscore-framework
```

To install optional extras for specific capabilities:

=== "P2P Mesh"
    ```bash
    pip install "jarviscore-framework[p2p]"
    ```
    Enables distributed multi-node agent deployments via the SWIM gossip protocol and ZMQ transport. Required when `P2P_ENABLED=true`.

=== "Web"
    ```bash
    pip install "jarviscore-framework[web]"
    ```
    Adds FastAPI, Uvicorn, and BeautifulSoup4. Required to run the built-in dashboard, chat endpoints, and FastAPI integration.

=== "Redis"
    ```bash
    pip install "jarviscore-framework[redis]"
    ```
    Enables distributed workflows, cross-session agent state, and peer routing via Redis. Required when `REDIS_URL` is set.

=== "Browser Automation"
    ```bash
    pip install "jarviscore-framework[browser]"
    playwright install chromium
    ```
    Enables `BrowserSubAgent` and Playwright-based web interaction tools. Required when `BROWSER_ENABLED=true`.

=== "RAG"
    ```bash
    pip install "jarviscore-framework[rag]"
    ```
    Adds local vector search (FAISS) and sentence-transformers for embedding-backed research and knowledge retrieval.

=== "Research"
    ```bash
    pip install "jarviscore-framework[research]"
    ```
    Full researcher stack — installs `browser` + `rag` + BeautifulSoup4. Everything `ResearcherSubAgent` needs for deep web research.

=== "Athena Memory"
    ```bash
    pip install "jarviscore-framework[memory-athena]"
    ```
    No extra Python dependencies. Athena is called over HTTP. Run the Athena service separately, then set `ATHENA_URL=http://localhost:8080`.

=== "Azure Blob Storage"
    ```bash
    pip install "jarviscore-framework[azure]"
    ```
    Adds the Azure Storage Blob client for the registry storage backend and `azure_storage` atoms.

=== "Prometheus Metrics"
    ```bash
    pip install "jarviscore-framework[prometheus]"
    ```
    Exposes a `/metrics` endpoint for operational dashboards and alerting.

=== "Full"
    ```bash
    pip install "jarviscore-framework[full]"
    ```
    Installs every optional dependency — use for production deployments where you need all capabilities enabled.

---

## Scaffold Your Project

Run `jarviscore init` to create the initial project structure and a pre-populated `.env.example`:

```bash
jarviscore init
```

This creates:

```
.env.example        — environment variable template
```

Copy the example to create your working configuration:

```bash
cp .env.example .env
```

---

## Configure an LLM Provider

JarvisCore supports four LLM providers. Configure exactly one by adding the appropriate variables to your `.env` file.

=== "Anthropic Claude"
    ```bash title=".env"
    CLAUDE_API_KEY=sk-ant-...
    CLAUDE_MODEL=claude-sonnet-4
    ```

=== "Google Gemini"
    ```bash title=".env"
    GEMINI_API_KEY=AIza...
    GEMINI_MODEL=gemini-2.0-flash
    ```

=== "Azure OpenAI"
    ```bash title=".env"
    AZURE_API_KEY=...
    AZURE_ENDPOINT=https://your-resource.openai.azure.com/
    AZURE_DEPLOYMENT=gpt-4o
    AZURE_API_VERSION=2024-02-15-preview
    ```

=== "Local / vLLM"
    ```bash title=".env"
    LLM_ENDPOINT=http://localhost:8000
    LLM_MODEL=mistral-7b-instruct
    ```

---

## Verify Your Installation

```bash
jarviscore check
```

This command validates your Python version, package installation, and LLM configuration. To also test live inference against the configured provider:

```bash
jarviscore check --validate-llm
```

Expected output when everything is correctly configured:

```
======================================================================
  JarvisCore Health Check
======================================================================

[System Requirements]
  Python Version:             3.12.2
  JarvisCore Package:         v1.2.0

[Dependencies]
  pydantic:                   Core validation
  pydantic_settings:          Configuration management

[LLM Configuration]
  Claude:                     CLAUDE_API_KEY=sk-a...key

[LLM Connectivity Test]
  Claude API:                 Connected

  All checks passed. Ready to use JarvisCore.
```

---

## Your First Agent

Create a file named `main.py`:

```python title="main.py"
import asyncio
from jarviscore import Mesh, AutoAgent


class ResearcherAgent(AutoAgent):
    name = "Researcher"
    role = "researcher"
    description = "Researches topics and produces concise summaries."
    system_prompt = """
    You are a systematic research analyst. When given a topic,
    you identify the most relevant facts, verify them against
    multiple angles, and summarise your findings clearly.
    """


async def main():
    mesh = Mesh()
    mesh.add(ResearcherAgent)
    await mesh.start()

    result = await mesh.run_task(
        agent="researcher",
        task="What are the main architectural differences between the SWIM and Raft consensus protocols?",
    )

    print(result)


if __name__ == "__main__":
    asyncio.run(main())
```

Run it:

```bash
python main.py
```

The agent will reason through the task using the OODA loop and return a structured response. Because no infrastructure is configured beyond the LLM key, all state is held in process memory and discarded when the script exits.

---

## Your First Multi-Agent Workflow

The following example demonstrates a two-agent pipeline where a Scout gathers raw data and an Analyst processes it.

```python title="multi_agent.py"
import asyncio
from jarviscore import Mesh, AutoAgent


class ScoutAgent(AutoAgent):
    name = "Scout"
    role = "scout"
    description = "Gathers raw data on a given subject."
    system_prompt = "You gather raw, factual data on the subject provided. Be thorough and cite your sources."


class AnalystAgent(AutoAgent):
    name = "Analyst"
    role = "analyst"
    description = "Analyses data and produces structured intelligence reports."
    system_prompt = "You receive raw research data and produce a structured intelligence report with clear conclusions."


async def main():
    mesh = Mesh()
    mesh.add(ScoutAgent)
    mesh.add(AnalystAgent)
    await mesh.start()

    # Step 1: Scout gathers raw data
    raw_data = await mesh.run_task(
        agent="scout",
        task="Gather data on the current state of vector database technology.",
    )

    # Step 2: Analyst processes the raw data
    report = await mesh.run_task(
        agent="analyst",
        task=f"Analyse the following research data and produce a structured report:\n\n{raw_data}",
    )

    print(report)


if __name__ == "__main__":
    asyncio.run(main())
```

---

## Next Steps

Once you have a working agent, add infrastructure incrementally based on your requirements.

**Add persistent memory** so agents retain context across runs:

```bash
docker run -d -p 6379:6379 redis:7-alpine
```

```bash title=".env"
REDIS_URL=redis://localhost:6379/0
```

**Add cross-session semantic memory** with Athena:

```bash
jarviscore memory init
```

**Add third-party service credentials** for agents that call external APIs:

```bash
jarviscore nexus init
jarviscore nexus register github --client-id=YOUR_ID --client-secret=YOUR_SECRET
```

**Enable multi-node distributed execution** with P2P:

```bash title=".env"
P2P_ENABLED=true
JC_SWIM_PORT=7946
```

See the [Configuration Reference](reference/configuration.md) for the complete list of environment variables and their defaults.
