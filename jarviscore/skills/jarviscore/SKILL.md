---
name: jarviscore
description: Build multi-agent AI systems with the JarvisCore Python framework. Use when writing, reviewing, or debugging code that imports jarviscore, defines AutoAgent or CustomAgent classes, runs a Mesh, or configures agent memory (Athena), P2P, Nexus credentials, or tracing.
---

# JarvisCore

Python framework for production multi-agent AI. Agents run on a peer-to-peer mesh, remember across sessions, and trace everything they do. Package: `jarviscore-framework` (import name `jarviscore`). Python 3.10+.

## The one decision that matters: pick the right profile

- `CustomAgent`: you bring the brain. Deterministic control, you implement the logic. Use for workers with known logic, API-driven services, wrapping existing code.
- `AutoAgent`: the framework brings the brain. LLM task execution with sandboxed code generation, self-repair, and a verified-work registry. Use when the task is described, not coded.

There is nothing in between. Do not simulate one with the other.

## Minimal AutoAgent (correct, complete)

```python
import asyncio
from jarviscore import Mesh
from jarviscore.profiles import AutoAgent

class ResearcherAgent(AutoAgent):
    role = "researcher"                      # required
    capabilities = ["research", "analysis"]  # required
    system_prompt = "You are a rigorous research analyst."  # required

async def main():
    mesh = Mesh()
    mesh.add(ResearcherAgent)
    await mesh.start()
    result = await mesh.run_task(agent="researcher", task="Compare SWIM and Raft.")
    print(result)

asyncio.run(main())
```

Optional AutoAgent class attributes: `goal_oriented = True` (routes tasks through a Plan, Execute, Evaluate loop), `default_kernel_role = "..."`, `requires_auth = True` (injects Nexus-backed `_auth_manager`).

## Minimal CustomAgent

```python
from jarviscore.profiles import CustomAgent

class ProcessorAgent(CustomAgent):
    role = "processor"
    capabilities = ["processing"]

    async def execute_task(self, task):
        return {"status": "success", "output": ...}

    async def on_peer_request(self, msg):          # P2P handler
        return {"status": "success", "result": ...}
```

## Two ways to run, one rule

- `mesh.run_task(agent=..., task=...)`: one task, one agent. Single asks and hand-rolled pipelines.
- `mesh.workflow(id, steps)`: declared steps as one traced unit with ordering, dependencies, and retries.

Rule: if you are pasting one agent's output into another agent's prompt by hand, use `workflow`.

```python
results = await mesh.workflow("wf-1", [
    {"agent": "researcher", "task": "Gather data on X"},
    {"agent": "analyst", "task": "Write a report from the research"},
])
print(results[0]["output"])   # results carry status, output, metadata
```

## Configuration

Exactly one LLM provider is required. Set in `.env`:

- Claude: `CLAUDE_API_KEY` + `CLAUDE_MODEL`
- Azure OpenAI: `AZURE_API_KEY` + `AZURE_ENDPOINT` + `AZURE_DEPLOYMENT`
- Gemini: `GEMINI_API_KEY` + `GEMINI_MODEL`
- vLLM/local: `LLM_ENDPOINT` + `LLM_MODEL`

Everything else is optional and additive: `REDIS_URL` (distributed workflows, cross-session state), `ATHENA_URL` (cross-session semantic memory, wired into AutoAgent automatically), `P2P_ENABLED=true` (multi-machine mesh, needs `pip install "jarviscore-framework[p2p]"`).

Verify a setup with `jarviscore check --validate-llm`, never by guessing.

## CLI verbs

```
jarviscore init            # scaffold .env.example (--full for every option)
jarviscore check           # health check; --validate-llm makes a real call
jarviscore memory init     # pull + start the Athena memory stack (Docker)
jarviscore memory status   # health of all memory tiers
jarviscore nexus init      # zero-trust credential broker (Docker)
jarviscore inspect [wf]    # read recorded traces: what did my agents do?
jarviscore atom list       # 46 service integrations, 237+ prebuilt actions
```

## House rules the framework enforces (do not fight them)

- Nothing is truncated silently. If you clip content in agent context, label it and keep a retrieval path. The framework does; your code should too.
- Failures are loud. Do not swallow exceptions in handlers; return `{"status": "failure", ...}` shapes or raise.
- Credentials never enter agent reasoning. Use `requires_auth`/Nexus atoms, never put raw secrets in prompts or task strings.
- Memory tiers are additive. Code must work with tiers absent; check for None rather than assuming Redis or Athena exists.

## Common mistakes

- Inventing constructor arguments. Profiles configure via class attributes; `Mesh()` needs no arguments for a single process.
- Forgetting `await mesh.start()` before running tasks.
- Using `AutoAgent` for deterministic logic (slow, expensive) or `CustomAgent` for open-ended tasks (you will rebuild the kernel badly).
- Reading `result["payload"]`. The output key is `output`.
- Assuming P2P works without the `[p2p]` extra installed.

## Deeper documentation

Full docs: https://jarviscore.developers.prescottdata.io/ (guides for workflows, HITL, browser automation, RAG, FastAPI integration, observability, production deployment).
