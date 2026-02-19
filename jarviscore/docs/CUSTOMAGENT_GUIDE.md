# CustomAgent Guide

CustomAgent lets you integrate your **existing agent code** with JarvisCore's networking and orchestration capabilities.

**You keep**: Your execution logic, LLM calls, and business logic.
**Framework provides**: Agent discovery, peer communication, workflow orchestration, and multi-node deployment.

---

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Choose Your Mode](#choose-your-mode)

**v0.4.0 — Infrastructure Stack (Phases 1–9):**

3. [Phase 9 — Auto-Injected Infrastructure](#phase-9--auto-injected-infrastructure) - `_redis_store`, `_blob_storage`, `mailbox` wired before `setup()`
4. [Phase 1 — Blob Storage](#phase-1--blob-storage) - Save / load artifacts
5. [Phase 4 — MailboxManager](#phase-4--mailboxmanager) - Async agent-to-agent messaging
6. [Phase 5 — Prometheus Metrics](#phase-5--prometheus-metrics) - `record_step_execution`
7. [Phase 7 — Distributed Workflow](#phase-7--distributed-workflow) - Redis DAG, crash recovery
8. [Phase 7D — Nexus Auth Injection](#phase-7d--nexus-auth-injection) - OAuth via `requires_auth=True`
9. [Phase 8 — UnifiedMemory](#phase-8--unifiedmemory) - EpisodicLedger, LTM, accessor
10. [Production Example: Ex3 — Support Swarm](#production-example-ex3--customer-support-swarm) - P2P + Nexus auth walkthrough
11. [Production Example: Ex4 — Content Pipeline](#production-example-ex4--content-pipeline) - Distributed + LTM walkthrough

**Agent Modes & Patterns:**

12. [P2P Mode](#p2p-mode) - Handler-based peer communication
13. [Distributed Mode](#distributed-mode) - Workflow tasks + P2P
14. [Cognitive Discovery (v0.3.0)](#cognitive-discovery-v030) - Dynamic peer awareness for LLMs
15. [FastAPI Integration (v0.3.0)](#fastapi-integration-v030) - 3-line setup with JarvisLifespan
16. [Framework Integration Patterns](#framework-integration-patterns) - aiohttp, Flask, Django
17. [Cloud Deployment (v0.3.0)](#cloud-deployment-v030) - Self-registration for containers
18. [API Reference](#api-reference)
19. [Multi-Node Deployment](#multi-node-deployment)
20. [Error Handling](#error-handling)
21. [Troubleshooting](#troubleshooting)
22. [Session Context Propagation (v0.3.2)](#session-context-propagation-v032) - Request tracking and metadata
23. [Async Request Pattern (v0.3.2)](#async-request-pattern-v032) - Non-blocking parallel requests
24. [Load Balancing Strategies (v0.3.2)](#load-balancing-strategies-v032) - Round-robin and random selection
25. [Mesh Diagnostics (v0.3.2)](#mesh-diagnostics-v032) - Health monitoring and debugging
26. [Testing with MockMesh (v0.3.2)](#testing-with-mockmesh-v032) - Unit testing patterns

---

## Prerequisites

### Installation

```bash
pip install jarviscore-framework
```

### Your LLM Client

Throughout this guide, we use `MyLLMClient()` as a placeholder for your LLM. Replace it with your actual client:

```python
# Example: OpenAI
from openai import OpenAI
client = OpenAI()

def chat(prompt: str) -> str:
    response = client.chat.completions.create(
        model="gpt-4",
        messages=[{"role": "user", "content": prompt}]
    )
    return response.choices[0].message.content

# Example: Anthropic
from anthropic import Anthropic
client = Anthropic()

def chat(prompt: str) -> str:
    response = client.messages.create(
        model="claude-3-sonnet-20240229",
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}]
    )
    return response.content[0].text

# Example: Local/Custom
class MyLLMClient:
    def chat(self, prompt: str) -> str:
        # Your implementation
        return "response"
```

---

## Choose Your Mode

```
┌─────────────────────────────────────────────────────────────┐
│                  Which mode should I use?                   │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
              ┌───────────────────────────────┐
              │ Do agents need to coordinate  │
              │ continuously in real-time?    │
              └───────────────────────────────┘
                     │                │
                    YES              NO
                     │                │
                     ▼                ▼
              ┌──────────┐    ┌───────────────────────┐
              │ P2P Mode │    │ Do you have task      │
              └──────────┘    │ pipelines with        │
                              │ dependencies?         │
                              └───────────────────────┘
                                   │           │
                                  YES         NO
                                   │           │
                                   ▼           ▼
                            ┌────────────┐  ┌──────────┐
                            │Distributed │  │ P2P Mode │
                            │   Mode     │  └──────────┘
                            └────────────┘
```

### Quick Comparison

| Feature | P2P Mode (CustomAgent) | P2P Mode (CustomAgent) | Distributed Mode |
|---------|------------------------|--------------------------|------------------|
| **Primary method** | `run()` - continuous loop | `on_peer_request()` handlers | `execute_task()` - on-demand |
| **Communication** | Direct peer messaging | Handler-based (no loop) | Workflow orchestration |
| **Best for** | Custom message loops | API-first agents, FastAPI | Pipelines, batch processing |
| **Coordination** | Agents self-coordinate | Framework handles loop | Framework coordinates |
| **Supports workflows** | No | No | Yes |

> **CustomAgent** includes built-in P2P handlers - just implement `on_peer_request()` and `on_peer_notify()`. No need to write your own `run()` loop.

---

## Phase 9 — Auto-Injected Infrastructure

Before every agent's `setup()` call, the Mesh wires three infrastructure objects directly
onto the agent instance. **Do not create these in `__init__`** — they are not available
there. Use them in `setup()` and `execute_task()`.

| Attribute | Type | Available when |
|-----------|------|---------------|
| `self._redis_store` | `RedisContextStore` | `REDIS_URL` set |
| `self._blob_storage` | `LocalBlobStorage` \| `AzureBlobStorage` | always (local is default) |
| `self.mailbox` | `MailboxManager` | `REDIS_URL` set |

```python
class MyAgent(CustomAgent):
    role = "worker"
    capabilities = ["processing"]

    async def setup(self):
        await super().setup()
        # All three are already injected — use them immediately
        self.memory = UnifiedMemory(
            workflow_id="my-wf", step_id="worker",
            agent_id=self.role,
            redis_store=self._redis_store,
            blob_storage=self._blob_storage,
        )

    async def execute_task(self, task):
        # Phase 1: blob
        await self._blob_storage.save("output/result.json", json.dumps(result))
        # Phase 4: mailbox
        self.mailbox.send(other_agent_id, {"event": "done"})
        return {"status": "success", "output": result}
```

**Verification pattern** — confirm injection before a run:

```python
for agent in mesh.agents:
    redis_ok  = agent._redis_store  is not None
    blob_ok   = agent._blob_storage is not None
    mailbox_ok = agent.mailbox      is not None
    print(f"{agent.role}: redis={redis_ok} blob={blob_ok} mailbox={mailbox_ok}")
```

---

## Phase 1 — Blob Storage

`LocalBlobStorage` writes to `./blob_storage/` by default. Switch to Azure via
`STORAGE_BACKEND=azure`.

```python
# Save artifacts
await self._blob_storage.save("research/ai-landscape.json", json.dumps(research))
await self._blob_storage.save("drafts/article.md",          markdown_text)
await self._blob_storage.save("escalations/ticket-001.json", json.dumps(record))

# Load artifact
content = await self._blob_storage.load("research/ai-landscape.json")
data = json.loads(content) if content else {}
```

**Path convention:** `{type}/{workflow_id}/{filename}.{ext}`

Examples: `research/wf-001/findings.json`, `reports/daily-001/summary.md`

---

## Phase 4 — MailboxManager

Fire-and-forget messages between agents, backed by Redis Streams.

```python
# Route a query to a specialist (ex3 gateway pattern)
self.mailbox.send(technical_agent_id, {
    "query": "API auth broken",
    "customer_id": "cust-42",
})

# Drain inbox
messages = self.mailbox.read(max_messages=10)
for msg in messages:
    query = msg.get("query")
    # handle it...

# Notification after completing a step (ex4 publisher pattern)
self.mailbox.send(researcher_agent_id, {"event": "published", "workflow": "content-2026"})
```

`target_id` is the `agent_id` string (usually `"{role}-{uuid4[:8]}"`).
Messages survive process restarts when `REDIS_URL` is set.

---

## Phase 5 — Prometheus Metrics

Record step execution time and status at the end of every `execute_task()`:

```python
import time
from jarviscore.telemetry.metrics import record_step_execution

async def execute_task(self, task):
    start = time.time()
    try:
        result = self._do_work(task)
        record_step_execution(time.time() - start, "success")
        return {"status": "success", "output": result}
    except Exception as e:
        record_step_execution(time.time() - start, "failure")
        return {"status": "failure", "error": str(e)}
```

Enable metrics: `PROMETHEUS_ENABLED=true`, `PROMETHEUS_PORT=9090`.
View in Grafana: metric `jarviscore_step_duration_seconds`.

---

## Phase 7 — Distributed Workflow + `depends_on`

```python
mesh = Mesh(mode="distributed", config={
    "redis_url": "redis://localhost:6379/0",
    "bind_port": 7950,
})
mesh.add(ResearchAgent)
mesh.add(WriterAgent)
await mesh.start()

results = await mesh.workflow("content-2026", [
    {"id": "research", "agent": "researcher", "task": "Research AI agents"},
    {"id": "write",    "agent": "writer",     "task": "Write article",
     "depends_on": ["research"]},
])
```

- `depends_on` is a list of step IDs that must complete before this step is dispatched
- The WorkflowEngine writes the full DAG to Redis hash `workflow_graph:{workflow_id}`
- **Crash recovery**: restart the process with the same `workflow_id` — completed steps
  are not re-run; pending steps resume from where they stopped

---

## Phase 7D — Nexus Auth Injection

Set `requires_auth = True` on any `CustomAgent` to receive an injected `_auth_manager`
before `setup()`:

```python
class TechnicalAgent(CustomAgent):
    role = "technical_support"
    requires_auth = True       # → self._auth_manager injected

    async def execute_task(self, task):
        if self._auth_manager:   # None when NEXUS_GATEWAY_URL not set
            result = await self._auth_manager.make_authenticated_request(
                provider="github",
                method="GET",
                url="https://api.github.com/user",
            )
        else:
            result = {"status": "degraded", "note": "no auth configured"}
        return {"status": "success", "output": result}
```

Full Nexus flow on first call: `request_connection → browser OAuth →
poll ACTIVE → resolve_strategy → apply Authorization header`.

Config keys: `auth_mode` (`production`|`mock`), `nexus_gateway_url`,
`nexus_default_user_id`, `auth_open_browser`.

**Graceful degradation:** always check `if self._auth_manager:` —
`_auth_manager` is `None` when `NEXUS_GATEWAY_URL` is not set.

---

## Phase 8 — UnifiedMemory

```python
from jarviscore.memory import UnifiedMemory, RedisMemoryAccessor

# In setup()
self.memory = UnifiedMemory(
    workflow_id="content-2026", step_id="writer",
    agent_id=self.role,
    redis_store=self._redis_store,
    blob_storage=self._blob_storage,
)

# EpisodicLedger — append event
await self.memory.episodic.append({"event": "task_started", "topic": topic, "ts": time.time()})

# EpisodicLedger — read recent events
recent = await self.memory.episodic.tail(5)

# LongTermMemory — save and load summary
await self.memory.ltm.save_summary("Style: concise, technical, no jargon.")
style_notes = await self.memory.ltm.load_summary()

# Compress LTM after publish (saves tokens on next run)
await self.memory.ltm.save_summary(compressed_summary)
```

**RedisMemoryAccessor** — read any prior step's output cross-agent:

```python
accessor = RedisMemoryAccessor(self._redis_store, workflow_id="content-2026")
raw = accessor.get("research")
research = raw.get("output", raw) if isinstance(raw, dict) else {}
# research now has the ResearchAgent's output dict
```

Redis key: `step_output:{workflow_id}:{step_id}`

---

## Production Example: Ex3 — Customer Support Swarm

**Profile:** CustomAgent | **Mode:** p2p | **Phases:** 1, 4, 7D, 8, 9

### Architecture

```
GatewayAgent   ──mailbox──→  TechnicalAgent  (requires_auth=True)
               ──mailbox──→  BillingAgent
               ──mailbox──→  EscalationAgent ──blob──→ escalation record
```

Single process, 4 agents, P2P mode. Gateway reads queries and routes via mailbox.
`TechnicalAgent` exercises the full Nexus OAuth flow.

### Key Agent Patterns

**GatewayAgent — keyword routing via mailbox:**

```python
class GatewayAgent(CustomAgent):
    role = "gateway"
    capabilities = ["routing", "intake"]

    async def execute_task(self, task):
        query = task.get("task", "")
        if any(w in query.lower() for w in ["api", "error", "bug", "auth"]):
            target = self._find_agent("technical_support")
        elif any(w in query.lower() for w in ["invoice", "billing", "charge"]):
            target = self._find_agent("billing_support")
        else:
            target = self._find_agent("escalation")

        self.mailbox.send(target, {"query": query, "customer_id": task.get("customer_id")})
        return {"status": "success", "output": f"Routed to {target}"}
```

**TechnicalAgent — Nexus auth + EpisodicLedger:**

```python
class TechnicalAgent(CustomAgent):
    role = "technical_support"
    requires_auth = True

    async def setup(self):
        await super().setup()
        self.memory = UnifiedMemory("support-swarm", self.agent_id,
                                   self.role, self._redis_store, self._blob_storage)

    async def execute_task(self, task):
        await self.memory.episodic.append({"query": task.get("task"), "ts": time.time()})
        if self._auth_manager:
            api_result = await self._auth_manager.make_authenticated_request(
                "github", "GET", "https://api.github.com/user")
        return {"status": "success", "output": f"Resolved: {task.get('task')}"}
```

**EscalationAgent — blob record for human review:**

```python
class EscalationAgent(CustomAgent):
    role = "escalation"

    async def execute_task(self, task):
        record = {"query": task.get("task"), "ts": time.time(), "needs_human": True}
        await self._blob_storage.save(
            f"escalations/support-swarm/{int(time.time())}.json",
            json.dumps(record),
        )
        return {"status": "success", "output": "Escalated and recorded"}
```

### Run

```bash
docker compose -f docker-compose.infra.yml up -d
# Optional: set NEXUS_GATEWAY_URL and AUTH_MODE=production in .env for real OAuth
python examples/ex3_support_swarm.py
```

### Verify

```bash
redis-cli xrange ledgers:support-swarm - +          # episodic events
ls blob_storage/escalations/support-swarm/          # escalation records
```

---

## Production Example: Ex4 — Content Pipeline

**Profile:** CustomAgent | **Mode:** distributed | **Phases:** 1, 4, 5, 7, 8, 9

### Architecture

```
ResearchAgent ──→ WriterAgent ──→ SEOAgent ──→ PublisherAgent
  (research)        (write)        (seo)         (publish)
                      ↑ reads research via RedisMemoryAccessor
                                              ↓ mailbox → ResearchAgent
                                              ↓ LTM compressed
```

4-step sequential workflow, single process, distributed mode.

### Key Patterns

**WriterAgent — cross-step data via RedisMemoryAccessor:**

```python
class WriterAgent(CustomAgent):
    role = "writer"

    async def setup(self):
        await super().setup()
        ltm_notes = (await self._redis_store.get("ltm:content-pipeline")) or ""
        self._style_notes = ltm_notes

    async def execute_task(self, task):
        # Read research output from Redis without passing it explicitly
        accessor = RedisMemoryAccessor(self._redis_store, task.get("workflow_id", "content-pipeline"))
        raw = accessor.get("research")
        research = raw.get("output", raw) if isinstance(raw, dict) else {}

        draft = self._write_article(task.get("task"), research, self._style_notes)

        # Save draft to blob
        path = f"content/drafts/{task.get('task','draft').replace(' ','_')}.md"
        await self._blob_storage.save(path, draft)

        return {"status": "success", "output": {"draft": draft, "blob_path": path}}
```

**PublisherAgent — LTM compress + mailbox notify:**

```python
class PublisherAgent(CustomAgent):
    role = "publisher"

    async def execute_task(self, task):
        # ... publish logic ...
        # Compress LTM for next run
        await self.memory.ltm.save_summary("Published: AI agents article. Style: concise.")
        # Notify researcher
        researcher_id = self._find_agent("researcher")
        self.mailbox.send(researcher_id, {"event": "published", "workflow": "content-pipeline"})
        return {"status": "success", "output": "Published"}
```

### Workflow definition

```python
await mesh.workflow("content-2026", [
    {"id": "research", "agent": "researcher", "task": "Research: future of AI agents"},
    {"id": "write",    "agent": "writer",     "task": "Write article",     "depends_on": ["research"]},
    {"id": "seo",      "agent": "seo",        "task": "Optimise keywords", "depends_on": ["write"]},
    {"id": "publish",  "agent": "publisher",  "task": "Publish article",   "depends_on": ["seo"]},
])
```

### Run

```bash
docker compose -f docker-compose.infra.yml up -d
python examples/ex4_content_pipeline.py
```

### Verify

```bash
redis-cli hgetall "step_output:content-2026:research"
ls blob_storage/content/drafts/
redis-cli get "ltm:content-pipeline"                # LTM summary after publish
```

---

## P2P Mode

P2P mode is for agents that run continuously and communicate directly with each other.

### v0.3.1 Update: Handler-Based Pattern

**We've simplified P2P agents!** No more manual `run()` loops.

```
┌────────────────────────────────────────────────────────────────┐
│                    OLD vs NEW Pattern                          │
├────────────────────────────────────────────────────────────────┤
│                                                                │
│  ❌ OLD (v0.2.x) - Manual Loop                                 │
│  ┌──────────────────────────────────────────────┐              │
│  │ async def run(self):                         │              │
│  │     while not self.shutdown_requested:       │              │
│  │         msg = await self.peers.receive()     │ ← Polling    │
│  │         if msg and msg.is_request:           │              │
│  │             result = self.process(msg)       │              │
│  │             await self.peers.respond(...)    │ ← Manual     │
│  │         await asyncio.sleep(0.1)             │              │
│  └──────────────────────────────────────────────┘              │
│                                                                │
│  ✅ NEW (v0.3.0+) - Handler-Based                              │
│  ┌──────────────────────────────────────────────┐              │
│  │ async def on_peer_request(self, msg):        │              │
│  │     result = self.process(msg)               │              │
│  │     return result                            │ ← Simple!    │
│  └──────────────────────────────────────────────┘              │
│         ▲                                                      │
│         │                                                      │
│         └─ Framework calls this automatically                 │
│                                                                │
└────────────────────────────────────────────────────────────────┘
```

**Benefits:**
- ✅ **Less Code**: No boilerplate loops
- ✅ **Simpler**: Just return your result
- ✅ **Automatic**: Framework handles message dispatch
- ✅ **Error Handling**: Built-in exception capture
- ✅ **FastAPI Ready**: Works with `JarvisLifespan` out of the box

### Migration Overview

```
YOUR PROJECT STRUCTURE
──────────────────────────────────────────────────────────────────

BEFORE (standalone):          AFTER (with JarvisCore):
├── my_agent.py              ├── agents.py        ← Modified agent code
└── (run directly)           └── main.py          ← NEW entry point
                                  ▲
                                  │
                         This is now how you
                         start your agents
```

### Step 1: Install the Framework

```bash
pip install jarviscore-framework
```

### Step 2: Your Existing Code (Before)

Let's say you have a standalone agent like this:

```python
# my_agent.py (YOUR EXISTING CODE)
class MyResearcher:
    """Your existing agent - runs standalone."""

    def __init__(self):
        self.llm = MyLLMClient()

    def research(self, query: str) -> str:
        return self.llm.chat(f"Research: {query}")

# You currently run it directly:
if __name__ == "__main__":
    agent = MyResearcher()
    result = agent.research("What is AI?")
    print(result)
```

### Step 3: Modify Your Agent Code → `agents.py`

**🚨 IMPORTANT CHANGE (v0.3.0+)**: We've moved from `run()` loops to **handler-based** agents!

#### ❌ OLD Pattern (Deprecated)
```python
# DON'T DO THIS ANYMORE!
class ResearcherAgent(CustomAgent):
    async def run(self):  # ❌ Manual loop
        while not self.shutdown_requested:
            msg = await self.peers.receive(timeout=0.5)
            if msg and msg.is_request:
                result = self.llm.chat(f"Research: {msg.data['question']}")
                await self.peers.respond(msg, {"response": result})
            await asyncio.sleep(0.1)
```
**Problems**: Manual loops, boilerplate, error-prone

#### ✅ NEW Pattern (Recommended)
```python
# agents.py (MODERN VERSION)
from jarviscore.profiles import CustomAgent


class ResearcherAgent(CustomAgent):
    """Your agent, now framework-integrated with handlers."""

    # Required class attributes for discovery
    role = "researcher"
    capabilities = ["research", "analysis"]
    description = "Research specialist that gathers and synthesizes information"

    async def setup(self):
        """Called once on startup. Initialize your LLM here."""
        await super().setup()
        self.llm = MyLLMClient()  # Your existing initialization

    async def on_peer_request(self, msg):
        """
        Handle incoming requests from other agents.
        
        This is called AUTOMATICALLY when another agent asks you a question.
        No loops, no polling, no boilerplate!
        """
        query = msg.data.get("question", "")
        
        # YOUR EXISTING LOGIC:
        result = self.llm.chat(f"Research: {query}")
        
        # Just return the data - framework handles the response
        return {"response": result}

    async def execute_task(self, task: dict) -> dict:
        """
        Required by base Agent class for workflow mode.
        
        In pure P2P mode, your logic is in on_peer_request().
        This is used when agent is part of a workflow pipeline.
        """
        return {"status": "success", "note": "This agent uses handlers for P2P mode"}
```

**What changed:**

| Before (v0.2.x) | After (v0.3.0+) | Why? |
|-----------------|-----------------|------|
| `async def run(self):` with `while` loop | `async def on_peer_request(self, msg):` handler | Automatic dispatch, less boilerplate |
| Manual `await self.peers.receive()` | Framework calls your handler | No polling needed |
| Manual `await self.peers.respond(msg, data)` | Just `return data` | Simpler error handling |
| `asyncio.create_task(agent.run())` | Not needed - handlers run automatically | Cleaner lifecycle |

#### Migration Checklist (v0.2.x → v0.3.0+)

If you have existing agents using the `run()` loop pattern:

- [ ] Replace `async def run(self):` with `async def on_peer_request(self, msg):`
- [ ] Remove `while not self.shutdown_requested:` loop
- [ ] Remove `msg = await self.peers.receive(timeout=0.5)` polling
- [ ] Change `await self.peers.respond(msg, data)` to `return data`
- [ ] Remove manual `asyncio.create_task(agent.run())` calls in main.py
- [ ] Consider using `JarvisLifespan` for FastAPI integration (see Step 4)
- [ ] Add `description` class attribute for better cognitive discovery
- [ ] Use `get_cognitive_context()` instead of hardcoded peer lists

> **Note**: The `run()` method is **still supported** for backward compatibility, but handlers are now the recommended approach. For the full pattern with **LLM-driven peer communication** (where your LLM autonomously decides when to call other agents), see the [Complete Example](#complete-example-llm-driven-peer-communication) below.

### Step 4: Create New Entry Point → `main.py`

**This is your NEW main file.** Instead of running `python my_agent.py`, you'll run `python main.py`.

```python
# main.py (NEW FILE - YOUR NEW ENTRY POINT)
import asyncio
from jarviscore import Mesh
from agents import ResearcherAgent


async def main():
    # Create the mesh network
    mesh = Mesh(
        mode="p2p",
        config={
            "bind_port": 7950,      # Port for P2P communication
            "node_name": "my-node", # Identifies this node in the network
        }
    )

    # Register your agent(s)
    mesh.add(ResearcherAgent)

    # Start the mesh (calls setup() on all agents)
    await mesh.start()

    # Run forever - agents handle their own work in run() loops
    await mesh.run_forever()


if __name__ == "__main__":
    asyncio.run(main())
```

**Why a new entry file?**

| Reason | Explanation |
|--------|-------------|
| **Mesh setup** | The Mesh handles networking, discovery, and lifecycle |
| **Multiple agents** | You can add many agents to one mesh |
| **Clean separation** | Agent logic in `agents.py`, orchestration in `main.py` |
| **Standard pattern** | Consistent entry point across all JarvisCore projects |

### Step 5: Run Your Agents

```bash
# OLD WAY (no longer used):
# python my_agent.py

# NEW WAY:
python main.py
```

---

### Complete Example: LLM-Driven Peer Communication

This is the **key pattern** for P2P mode. Your LLM gets peer tools added to its toolset, and it **autonomously decides** when to ask other agents for help.

```
┌─────────────────────────────────────────────────────────────────┐
│                    LLM-DRIVEN PEER COMMUNICATION                │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  User: "Analyze this sales data"                                │
│                    │                                            │
│                    ▼                                            │
│  ┌─────────────────────────────────────┐                        │
│  │         ASSISTANT'S LLM             │                        │
│  │                                     │                        │
│  │  Tools available:                   │                        │
│  │  - web_search (local)               │                        │
│  │  - ask_peer   (peer) ◄── NEW!       │                        │
│  │  - broadcast  (peer) ◄── NEW!       │                        │
│  │                                     │                        │
│  │  LLM decides: "I need analysis      │                        │
│  │  help, let me ask the analyst"      │                        │
│  └─────────────────────────────────────┘                        │
│                    │                                            │
│                    ▼ uses ask_peer tool                         │
│  ┌─────────────────────────────────────┐                        │
│  │          ANALYST AGENT              │                        │
│  │  (processes with its own LLM)       │                        │
│  └─────────────────────────────────────┘                        │
│                    │                                            │
│                    ▼ returns analysis                           │
│  ┌─────────────────────────────────────┐                        │
│  │         ASSISTANT'S LLM             │                        │
│  │  "Based on the analyst's findings,  │                        │
│  │   here's your answer..."            │                        │
│  └─────────────────────────────────────┘                        │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

**The key insight**: You add peer tools to your LLM's toolset. The LLM decides when to use them.

```python
# agents.py - UPDATED FOR v0.3.0+
from jarviscore.profiles import CustomAgent


class AnalystAgent(CustomAgent):
    """
    Analyst agent - specialist in data analysis.

    NEW PATTERN (v0.3.0+):
    - Uses @on_peer_request HANDLER instead of run() loop
    - Automatically receives and responds to peer requests
    - No manual message polling needed!
    """
    role = "analyst"
    capabilities = ["analysis", "data_interpretation", "reporting"]
    description = "Expert data analyst for statistics and insights"

    async def setup(self):
        await super().setup()
        self.llm = MyLLMClient()  # Your LLM client

    def get_tools(self) -> list:
        """
        Tools available to THIS agent's LLM.

        The analyst has local analysis tools.
        It can also ask other peers if needed.
        """
        tools = [
            {
                "name": "statistical_analysis",
                "description": "Run statistical analysis on numeric data",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "data": {"type": "string", "description": "Data to analyze"}
                    },
                    "required": ["data"]
                }
            }
        ]

        # ADD PEER TOOLS - so LLM can ask other agents if needed
        if self.peers:
            tools.extend(self.peers.as_tool().schema)

        return tools

    async def execute_tool(self, tool_name: str, args: dict) -> str:
        """
        Execute a tool by name.

        Routes to peer tools or local tools as appropriate.
        """
        # PEER TOOLS - check and execute
        if self.peers and tool_name in self.peers.as_tool().tool_names:
            return await self.peers.as_tool().execute(tool_name, args)

        # LOCAL TOOLS
        if tool_name == "statistical_analysis":
            data = args.get("data", "")
            return f"Analysis of '{data}': mean=150.3, std=23.4, trend=positive"

        return f"Unknown tool: {tool_name}"

    async def process_with_llm(self, query: str) -> str:
        """Process a request using LLM with tools."""
        system_prompt = """You are an expert data analyst.
You have tools for statistical analysis.
Analyze data thoroughly and provide insights."""

        tools = self.get_tools()
        messages = [{"role": "user", "content": query}]

        # Call LLM with tools
        response = self.llm.chat(messages, tools=tools, system=system_prompt)

        # Handle tool use if LLM decides to use a tool
        if response.get("type") == "tool_use":
            tool_result = await self.execute_tool(
                response["tool_name"],
                response["tool_args"]
            )
            # Continue conversation with tool result
            response = self.llm.continue_with_tool_result(
                messages, response["tool_use_id"], tool_result
            )

        return response.get("content", "Analysis complete.")

    async def on_peer_request(self, msg):
        """
        Handle incoming requests from peers.
        
        ✅ NEW: This is called automatically when another agent sends a request.
        ❌ OLD: Manual while loop with receive() polling
        """
        query = msg.data.get("question", msg.data.get("query", ""))

        # Process with LLM
        result = await self.process_with_llm(query)

        # Just return the data - framework handles the response!
        return {"response": result}

    async def execute_task(self, task: dict) -> dict:
        """Required by base class."""
        return {"status": "success"}


class AssistantAgent(CustomAgent):
    """
    Assistant agent - coordinates with other specialists.

    NEW PATTERN (v0.3.0+):
    1. Has its own LLM for reasoning
    2. Uses get_cognitive_context() to discover available peers
    3. Peer tools (ask_peer, broadcast) added to LLM toolset
    4. LLM AUTONOMOUSLY decides when to ask other agents
    5. Uses on_peer_request handler instead of run() loop
    """
    role = "assistant"
    capabilities = ["chat", "coordination", "search"]
    description = "General assistant that delegates specialized tasks to experts"

    async def setup(self):
        await super().setup()
        self.llm = MyLLMClient()  # Your LLM client
        self.tool_calls = []  # Track tool usage

    def get_tools(self) -> list:
        """
        Tools available to THIS agent's LLM.

        IMPORTANT: This includes PEER TOOLS!
        The LLM sees ask_peer, broadcast_update, list_peers
        and decides when to use them.
        """
        # Local tools
        tools = [
            {
                "name": "web_search",
                "description": "Search the web for information",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search query"}
                    },
                    "required": ["query"]
                }
            }
        ]

        # ADD PEER TOOLS TO LLM'S TOOLSET
        # This is the key! LLM will see:
        # - ask_peer: Ask another agent for help
        # - broadcast_update: Send message to all peers
        # - list_peers: See available agents
        if self.peers:
            tools.extend(self.peers.as_tool().schema)

        return tools

    async def execute_tool(self, tool_name: str, args: dict) -> str:
        """
        Execute a tool by name.

        When LLM calls ask_peer, this routes to the peer system.
        """
        self.tool_calls.append({"tool": tool_name, "args": args})

        # PEER TOOLS - route to peer system
        if self.peers and tool_name in self.peers.as_tool().tool_names:
            return await self.peers.as_tool().execute(tool_name, args)

        # LOCAL TOOLS
        if tool_name == "web_search":
            return f"Search results for '{args.get('query')}': Found 10 articles."

        return f"Unknown tool: {tool_name}"

    async def chat(self, user_message: str) -> str:
        """
        Complete LLM chat with autonomous tool use.

        The LLM sees all tools (including peer tools) and decides
        which to use. If user asks for analysis, LLM will use
        ask_peer to contact the analyst.
        """
        # System prompt tells LLM about its capabilities
        system_prompt = """You are a helpful assistant.

You have access to these capabilities:
- web_search: Search the web for information
- ask_peer: Ask specialist agents for help (e.g., analyst for data analysis)
- broadcast_update: Send updates to all connected agents
- list_peers: See what other agents are available

When a user needs data analysis, USE ask_peer to ask the analyst.
When a user needs web information, USE web_search.
Be concise in your responses."""

        tools = self.get_tools()
        messages = [{"role": "user", "content": user_message}]

        # Call LLM - it will decide which tools to use
        response = self.llm.chat(messages, tools=tools, system=system_prompt)

        # Handle tool use loop
        while response.get("type") == "tool_use":
            tool_name = response["tool_name"]
            tool_args = response["tool_args"]

            # Execute the tool (might be ask_peer!)
            tool_result = await self.execute_tool(tool_name, tool_args)

            # Continue conversation with tool result
            response = self.llm.continue_with_tool_result(
                messages, response["tool_use_id"], tool_result, tools
            )

        return response.get("content", "")

    async def on_peer_request(self, msg):
        """
        Handle incoming requests from other agents.
        
        ✅ NEW: Handler-based - called automatically on request
        ❌ OLD: Manual while loop with receive() polling
        """
        query = msg.data.get("query", "")
        result = await self.chat(query)
        return {"response": result}

    async def execute_task(self, task: dict) -> dict:
        """Required by base class."""
        return {"status": "success"}
```

```python
# main.py - UPDATED FOR v0.3.0+ (Handler-Based Pattern)
import asyncio
from jarviscore import Mesh
from agents import AnalystAgent, AssistantAgent


async def main():
    """Simple P2P mesh without web server."""
    mesh = Mesh(
        mode="p2p",
        config={
            "bind_port": 7950,
            "node_name": "my-agents",
        }
    )

    # Add both agents - they'll use handlers automatically
    mesh.add(AnalystAgent)
    assistant = mesh.add(AssistantAgent)

    await mesh.start()

    # ✅ NO MORE MANUAL run() TASKS! Handlers are automatic.
    
    # Give time for mesh to stabilize
    await asyncio.sleep(0.5)

    # User asks a question - LLM will autonomously decide to use ask_peer
    print("User: Please analyze the Q4 sales trends")
    response = await assistant.chat("Please analyze the Q4 sales trends")
    print(f"Assistant: {response}")

    # Check what tools were used
    print(f"\nTools used: {assistant.tool_calls}")
    # Output: [{'tool': 'ask_peer', 'args': {'role': 'analyst', 'question': '...'}}]

    # Cleanup
    await mesh.stop()


if __name__ == "__main__":
    asyncio.run(main())
```

**Or better yet, use FastAPI + JarvisLifespan:**

```python
# main.py - PRODUCTION PATTERN (FastAPI + JarvisLifespan)
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from jarviscore.integrations import JarvisLifespan
from agents import AnalystAgent, AssistantAgent
import uvicorn


# ✅ ONE-LINE MESH SETUP with JarvisLifespan!
app = FastAPI(lifespan=JarvisLifespan([AnalystAgent, AssistantAgent]))


@app.post("/chat")
async def chat(request: Request):
    """Chat endpoint - assistant may autonomously delegate to analyst."""
    data = await request.json()
    message = data.get("message", "")
    
    # Get assistant from mesh (JarvisLifespan manages it)
    assistant = app.state.mesh.get_agent("assistant")
    
    # Chat - LLM autonomously discovers and delegates if needed
    response = await assistant.chat(message)
    
    return JSONResponse(response)


@app.get("/agents")
async def list_agents():
    """Show what each agent sees (cognitive context)."""
    mesh = app.state.mesh
    agents_info = {}
    
    for agent in mesh.agents:
        if agent.peers:
            context = agent.peers.get_cognitive_context(format="markdown")
            agents_info[agent.role] = {
                "role": agent.role,
                "capabilities": agent.capabilities,
                "peers_visible": len(agent.peers.get_all_peers()),
                "cognitive_context": context[:200] + "..."
            }
    
    return JSONResponse(agents_info)


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
```

### Key Concepts for P2P Mode

#### Adding Peer Tools to Your LLM

This is the most important pattern. Add peer tools to `get_tools()`:

```python
def get_tools(self) -> list:
    tools = [
        # Your local tools...
    ]

    # ADD PEER TOOLS - LLM will see ask_peer, broadcast, list_peers
    if self.peers:
        tools.extend(self.peers.as_tool().schema)

    return tools
```

#### Routing Tool Execution

Route tool calls to either peer tools or local tools:

```python
async def execute_tool(self, tool_name: str, args: dict) -> str:
    # Check peer tools first
    if self.peers and tool_name in self.peers.as_tool().tool_names:
        return await self.peers.as_tool().execute(tool_name, args)

    # Then local tools
    if tool_name == "my_local_tool":
        return self.my_local_tool(args)

    return f"Unknown tool: {tool_name}"
```

#### System Prompt for Peer Awareness

Tell the LLM about peer capabilities:

```python
system_prompt = """You are a helpful assistant.

You have access to:
- ask_peer: Ask specialist agents for help
- broadcast_update: Send updates to all agents

When a user needs specialized help, USE ask_peer to contact the right agent."""
```

#### The `run()` Loop

Listen for incoming requests and process with LLM:

```python
async def run(self):
    while not self.shutdown_requested:
        if self.peers:
            msg = await self.peers.receive(timeout=0.5)
            if msg and msg.is_request:
                result = await self.process_with_llm(msg.data)
                await self.peers.respond(msg, {"response": result})
        await asyncio.sleep(0.1)
```

---

## P2P Message Handlers

CustomAgent includes built-in handlers for P2P communication - just implement the handlers you need.

### Handler-Based P2P (Recommended)

```python
from jarviscore.profiles import CustomAgent

class MyAgent(CustomAgent):
    role = "processor"
    capabilities = ["processing"]

    async def on_peer_request(self, msg):
        """Called when another agent sends a request."""
        return {"result": msg.data.get("task", "").upper()}

    async def on_peer_notify(self, msg):
        """Called when another agent broadcasts a notification."""
        print(f"Notification received: {msg.data}")
```

**What the framework handles:**
- Message receiving loop (`run()` is built-in)
- Routing requests to `on_peer_request()`
- Routing notifications to `on_peer_notify()`
- Automatic response sending (configurable with `auto_respond`)
- Shutdown handling

**Configuration:**
- `listen_timeout` (float): Seconds to wait for messages (default: 1.0)
- `auto_respond` (bool): Auto-send `on_peer_request()` return value (default: True)

### Complete P2P Example

```python
# agents.py
from jarviscore.profiles import CustomAgent


class AnalystAgent(CustomAgent):
    """A data analyst that responds to peer requests."""

    role = "analyst"
    capabilities = ["analysis", "data_interpretation"]

    async def setup(self):
        await super().setup()
        self.llm = MyLLMClient()  # Your LLM client

    async def on_peer_request(self, msg):
        """
        Handle incoming requests from other agents.

        Args:
            msg: IncomingMessage with msg.data, msg.sender_role, etc.

        Returns:
            dict: Response sent back to the requesting agent
        """
        query = msg.data.get("question", "")

        # Your analysis logic
        result = self.llm.chat(f"Analyze: {query}")

        return {"response": result, "status": "success"}

    async def on_peer_notify(self, msg):
        """
        Handle broadcast notifications.

        Args:
            msg: IncomingMessage with notification data

        Returns:
            None (notifications don't expect responses)
        """
        print(f"[{self.role}] Received notification: {msg.data}")


class AssistantAgent(CustomAgent):
    """An assistant that coordinates with specialists."""

    role = "assistant"
    capabilities = ["chat", "coordination"]

    async def setup(self):
        await super().setup()
        self.llm = MyLLMClient()

    async def on_peer_request(self, msg):
        """Handle incoming chat requests."""
        query = msg.data.get("query", "")

        # Use peer tools to ask specialists
        if self.peers and "data" in query.lower():
            # Ask the analyst for help
            analyst_response = await self.peers.as_tool().execute(
                "ask_peer",
                {"role": "analyst", "question": query}
            )
            return {"response": analyst_response.get("response", "")}

        # Handle directly
        return {"response": self.llm.chat(query)}
```

```python
# main.py
import asyncio
from jarviscore import Mesh
from agents import AnalystAgent, AssistantAgent


async def main():
    mesh = Mesh(mode="p2p", config={"bind_port": 7950})

    mesh.add(AnalystAgent)
    mesh.add(AssistantAgent)

    await mesh.start()

    # Agents automatically run their listeners
    await mesh.run_forever()


if __name__ == "__main__":
    asyncio.run(main())
```

### When to Use Handlers vs Custom run()

| Use handlers (`on_peer_request`) when... | Override `run()` when... |
|------------------------------------------|--------------------------|
| Request/response pattern fits your use case | You need custom message loop timing |
| You're integrating with FastAPI | You need to initiate messages proactively |
| You want minimal boilerplate | You have complex coordination logic |

### CustomAgent with FastAPI

CustomAgent works seamlessly with FastAPI. See [FastAPI Integration](#fastapi-integration-v030) below.

---

## Distributed Mode

Distributed mode is for task pipelines where the framework orchestrates execution order and passes data between steps.

### Migration Overview

```
YOUR PROJECT STRUCTURE
──────────────────────────────────────────────────────────────────

BEFORE (standalone):          AFTER (with JarvisCore):
├── pipeline.py              ├── agents.py        ← Modified agent code
└── (manual orchestration)   └── main.py          ← NEW entry point
                                  ▲
                                  │
                         This is now how you
                         start your pipeline
```

### Step 1: Install the Framework

```bash
pip install jarviscore-framework
```

### Step 2: Your Existing Code (Before)

Let's say you have a manual pipeline like this:

```python
# pipeline.py (YOUR EXISTING CODE)
class Researcher:
    def execute(self, task: str) -> dict:
        return {"output": f"Research on: {task}"}

class Writer:
    def execute(self, task: str, context: dict = None) -> dict:
        return {"output": f"Article based on: {context}"}

# Manual orchestration - you pass data between steps yourself:
if __name__ == "__main__":
    researcher = Researcher()
    writer = Writer()

    research = researcher.execute("AI trends")
    article = writer.execute("Write article", context=research)  # Manual!
    print(article)
```

**Problems with this approach:**
- You manually pass context between steps
- No dependency management
- Hard to run on multiple machines
- No automatic retries on failure

### Step 3: Modify Your Agent Code → `agents.py`

Convert your existing classes to inherit from `CustomAgent`:

```python
# agents.py (MODIFIED VERSION OF YOUR CODE)
from jarviscore.profiles import CustomAgent


class ResearcherAgent(CustomAgent):
    """Your researcher, now framework-integrated."""

    # NEW: Required class attributes
    role = "researcher"
    capabilities = ["research"]

    async def setup(self):
        """NEW: Called once on startup."""
        await super().setup()
        # Your initialization here (DB connections, LLM clients, etc.)

    async def execute_task(self, task: dict) -> dict:
        """
        MODIFIED: Now receives a task dict, returns a result dict.

        The framework calls this method - you don't call it manually.
        """
        task_desc = task.get("task", "")

        # YOUR EXISTING LOGIC:
        result = f"Research on: {task_desc}"

        # NEW: Return format for framework
        return {
            "status": "success",
            "output": result
        }


class WriterAgent(CustomAgent):
    """Your writer, now framework-integrated."""

    role = "writer"
    capabilities = ["writing"]

    async def setup(self):
        await super().setup()

    async def execute_task(self, task: dict) -> dict:
        """
        Context from previous steps is AUTOMATICALLY injected.
        No more manual passing!
        """
        task_desc = task.get("task", "")
        context = task.get("context", {})  # ← Framework injects this!

        # YOUR EXISTING LOGIC:
        research_output = context.get("research", {}).get("output", "")
        result = f"Article based on: {research_output}"

        return {
            "status": "success",
            "output": result
        }
```

**What changed:**

| Before | After |
|--------|-------|
| `class Researcher:` | `class ResearcherAgent(CustomAgent):` |
| `def execute(self, task):` | `async def execute_task(self, task: dict):` |
| Return anything | Return `{"status": "...", "output": ...}` |
| Manual `context=research` | Framework auto-injects via `depends_on` |

### Step 4: Create New Entry Point → `main.py`

**This is your NEW main file.** Instead of running `python pipeline.py`, you'll run `python main.py`.

```python
# main.py (NEW FILE - YOUR NEW ENTRY POINT)
import asyncio
from jarviscore import Mesh
from agents import ResearcherAgent, WriterAgent


async def main():
    # Create the mesh network
    mesh = Mesh(
        mode="distributed",
        config={
            "bind_port": 7950,
            "node_name": "pipeline-node",
        }
    )

    # Register your agents
    mesh.add(ResearcherAgent)
    mesh.add(WriterAgent)

    # Start the mesh (calls setup() on all agents)
    await mesh.start()

    # Define your workflow - framework handles orchestration!
    results = await mesh.workflow("content-pipeline", [
        {
            "id": "research",           # Step identifier
            "agent": "researcher",      # Which agent handles this
            "task": "AI trends 2024"    # Task description
        },
        {
            "id": "write",
            "agent": "writer",
            "task": "Write a blog post",
            "depends_on": ["research"]  # ← Framework auto-injects research output!
        }
    ])

    # Results in workflow order
    print("Research:", results[0]["output"])
    print("Article:", results[1]["output"])

    await mesh.stop()


if __name__ == "__main__":
    asyncio.run(main())
```

**Why a new entry file?**

| Reason | Explanation |
|--------|-------------|
| **Workflow orchestration** | `mesh.workflow()` handles dependencies, ordering, retries |
| **No manual context passing** | `depends_on` automatically injects previous step outputs |
| **Multiple agents** | Register all agents in one place |
| **Multi-node ready** | Same code works across machines with `seed_nodes` config |
| **Clean separation** | Agent logic in `agents.py`, orchestration in `main.py` |

### Step 5: Run Your Pipeline

```bash
# OLD WAY (no longer used):
# python pipeline.py

# NEW WAY:
python main.py
```

---

### Complete Example: Three-Stage Content Pipeline

This example shows a research → write → review pipeline.

```python
# agents.py
from jarviscore.profiles import CustomAgent


class ResearcherAgent(CustomAgent):
    """Researches topics and returns findings."""

    role = "researcher"
    capabilities = ["research"]

    async def setup(self):
        await super().setup()
        # self.llm = MyLLMClient()

    async def execute_task(self, task: dict) -> dict:
        topic = task.get("task", "")

        # Your research logic
        findings = f"Research findings on: {topic}"
        # findings = self.llm.chat(f"Research: {topic}")

        return {
            "status": "success",
            "output": findings
        }


class WriterAgent(CustomAgent):
    """Writes content based on research."""

    role = "writer"
    capabilities = ["writing"]

    async def setup(self):
        await super().setup()
        # self.llm = MyLLMClient()

    async def execute_task(self, task: dict) -> dict:
        instruction = task.get("task", "")
        context = task.get("context", {})  # Output from depends_on steps

        # Combine context from previous steps
        research = context.get("research", {}).get("output", "")

        # Your writing logic
        article = f"Article based on: {research}\nTopic: {instruction}"
        # article = self.llm.chat(f"Based on: {research}\nWrite: {instruction}")

        return {
            "status": "success",
            "output": article
        }


class EditorAgent(CustomAgent):
    """Reviews and polishes content."""

    role = "editor"
    capabilities = ["editing", "review"]

    async def setup(self):
        await super().setup()

    async def execute_task(self, task: dict) -> dict:
        instruction = task.get("task", "")
        context = task.get("context", {})

        # Get output from the writing step
        draft = context.get("write", {}).get("output", "")

        # Your editing logic
        polished = f"[EDITED] {draft}"

        return {
            "status": "success",
            "output": polished
        }
```

```python
# main.py
import asyncio
from jarviscore import Mesh
from agents import ResearcherAgent, WriterAgent, EditorAgent


async def main():
    mesh = Mesh(
        mode="distributed",
        config={
            "bind_port": 7950,
            "node_name": "content-node",
        }
    )

    mesh.add(ResearcherAgent)
    mesh.add(WriterAgent)
    mesh.add(EditorAgent)

    await mesh.start()

    # Define a multi-step workflow with dependencies
    results = await mesh.workflow("content-pipeline", [
        {
            "id": "research",           # Unique step identifier
            "agent": "researcher",      # Which agent handles this
            "task": "AI trends in 2024" # Task description
        },
        {
            "id": "write",
            "agent": "writer",
            "task": "Write a blog post about the research",
            "depends_on": ["research"]  # Wait for research, inject its output
        },
        {
            "id": "edit",
            "agent": "editor",
            "task": "Polish and improve the article",
            "depends_on": ["write"]     # Wait for writing step
        }
    ])

    # Results are in workflow order
    print("Research:", results[0]["output"])
    print("Draft:", results[1]["output"])
    print("Final:", results[2]["output"])

    await mesh.stop()


if __name__ == "__main__":
    asyncio.run(main())
```

### Key Concepts for Distributed Mode

#### The `execute_task()` Method

Called by the workflow engine when a task is assigned to your agent.

```python
async def execute_task(self, task: dict) -> dict:
    # task dict contains:
    # - "id": str - the step ID from the workflow
    # - "task": str - the task description
    # - "context": dict - outputs from depends_on steps (keyed by step ID)

    return {
        "status": "success",  # or "error"
        "output": result,     # your result data
        # "error": "message"  # if status is "error"
    }
```

#### The `task` Dictionary Structure

```python
{
    "id": "step_id",              # Step identifier from workflow
    "task": "task description",   # What to do
    "context": {                  # Outputs from dependencies
        "previous_step_id": {
            "status": "success",
            "output": "..."       # Whatever previous step returned
        }
    }
}
```

#### Workflow Step Definition

```python
{
    "id": "unique_step_id",       # Required: unique identifier
    "agent": "agent_role",        # Required: which agent handles this
    "task": "description",        # Required: task description
    "depends_on": ["step1", ...]  # Optional: steps that must complete first
}
```

#### Parallel Execution

Steps without `depends_on` or with satisfied dependencies run in parallel:

```python
results = await mesh.workflow("parallel-example", [
    {"id": "a", "agent": "worker", "task": "Task A"},          # Runs immediately
    {"id": "b", "agent": "worker", "task": "Task B"},          # Runs in parallel with A
    {"id": "c", "agent": "worker", "task": "Task C",
     "depends_on": ["a", "b"]},                                 # Waits for A and B
])
```

---

## Cognitive Discovery (v0.3.0)

**Cognitive Discovery** lets your LLM dynamically learn about available peers instead of hardcoding agent names in prompts.

### The Problem: Hardcoded Peer Names

Before v0.3.0, you had to hardcode peer information in your system prompts:

```python
# BEFORE: Hardcoded peer names - breaks when peers change
system_prompt = """You are a helpful assistant.

You have access to:
- ask_peer: Ask specialist agents for help
  - Use role="analyst" for data analysis
  - Use role="researcher" for research tasks
  - Use role="writer" for content creation

When a user needs data analysis, USE ask_peer with role="analyst"."""
```

**Problems:**
- If you add a new agent, you must update every prompt
- If an agent is offline, the LLM still tries to call it
- Prompts become stale as your system evolves
- Difficult to manage across many agents

### The Solution: `get_cognitive_context()`

```python
# AFTER: Dynamic peer awareness - always up to date
async def get_system_prompt(self) -> str:
    base_prompt = """You are a helpful assistant.

You have access to peer tools for collaborating with other agents."""

    # Generate LLM-ready peer descriptions dynamically
    if self.peers:
        peer_context = self.peers.get_cognitive_context()
        return f"{base_prompt}\n\n{peer_context}"

    return base_prompt
```

The `get_cognitive_context()` method generates text like:

```
Available Peers:
- analyst (capabilities: analysis, data_interpretation)
  Use ask_peer with role="analyst" for data analysis tasks
- researcher (capabilities: research, web_search)
  Use ask_peer with role="researcher" for research tasks
```

### Complete Example: Dynamic Peer Discovery

```python
# agents.py
from jarviscore.profiles import CustomAgent


class AssistantAgent(CustomAgent):
    """An assistant that dynamically discovers and uses peers."""

    role = "assistant"
    capabilities = ["chat", "coordination"]

    async def setup(self):
        await super().setup()
        self.llm = MyLLMClient()

    def get_system_prompt(self) -> str:
        """Build system prompt with dynamic peer context."""
        base_prompt = """You are a helpful AI assistant.

When users ask questions that require specialized knowledge:
1. Check what peers are available
2. Use ask_peer to get help from the right specialist
3. Synthesize their response for the user"""

        # DYNAMIC: Add current peer information
        if self.peers:
            peer_context = self.peers.get_cognitive_context()
            return f"{base_prompt}\n\n{peer_context}"

        return base_prompt

    def get_tools(self) -> list:
        """Get tools including peer tools."""
        tools = [
            # Your local tools...
        ]

        if self.peers:
            tools.extend(self.peers.as_tool().schema)

        return tools

    async def chat(self, user_message: str) -> str:
        """Chat with dynamic peer awareness."""
        # System prompt now includes current peer info
        system = self.get_system_prompt()
        tools = self.get_tools()

        response = self.llm.chat(
            messages=[{"role": "user", "content": user_message}],
            tools=tools,
            system=system
        )

        # Handle tool use...
        return response.get("content", "")
```

### Benefits of Cognitive Discovery

| Before (Hardcoded) | After (Dynamic) |
|--------------------|-----------------|
| Update prompts manually when peers change | Prompts auto-update |
| LLM tries to call offline agents | Only shows available agents |
| Difficult to manage at scale | Scales automatically |
| Stale documentation in prompts | Always current |

---

## FastAPI Integration (v0.3.0)

**JarvisLifespan** reduces FastAPI integration from ~100 lines to 3 lines.

### The Problem: Manual Lifecycle Management

Before v0.3.0, integrating an agent with FastAPI required manual lifecycle management:

```python
# BEFORE: ~100 lines of boilerplate
from contextlib import asynccontextmanager
from fastapi import FastAPI
from jarviscore import Mesh
from jarviscore.profiles import CustomAgent
import asyncio


class MyAgent(CustomAgent):
    role = "processor"
    capabilities = ["processing"]

    async def run(self):
        while not self.shutdown_requested:
            if self.peers:
                msg = await self.peers.receive(timeout=0.5)
                if msg and msg.is_request:
                    result = self.process(msg.data)
                    await self.peers.respond(msg, {"response": result})
            await asyncio.sleep(0.1)

    async def execute_task(self, task):
        return {"status": "success"}


# Manual lifecycle management
mesh = None
agent = None
run_task = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global mesh, agent, run_task

    # Startup
    mesh = Mesh(mode="p2p", config={"bind_port": 7950})
    agent = mesh.add(MyAgent)
    await mesh.start()
    run_task = asyncio.create_task(agent.run())

    yield

    # Shutdown
    agent.request_shutdown()
    run_task.cancel()
    await mesh.stop()


app = FastAPI(lifespan=lifespan)


@app.post("/process")
async def process(data: dict):
    # Your endpoint logic
    return {"result": "processed"}
```

### The Solution: JarvisLifespan

```python
# AFTER: 3 lines to integrate
from fastapi import FastAPI
from jarviscore.profiles import CustomAgent
from jarviscore.integrations.fastapi import JarvisLifespan


class ProcessorAgent(CustomAgent):
    role = "processor"
    capabilities = ["processing"]

    async def on_peer_request(self, msg):
        return {"result": msg.data.get("task", "").upper()}


# That's it - 3 lines!
app = FastAPI(lifespan=JarvisLifespan(ProcessorAgent(), mode="p2p"))


@app.post("/process")
async def process(data: dict):
    return {"result": "processed"}
```

### JarvisLifespan Configuration

```python
from jarviscore.integrations.fastapi import JarvisLifespan

# Basic usage
app = FastAPI(lifespan=JarvisLifespan(agent, mode="p2p"))

# With configuration
app = FastAPI(
    lifespan=JarvisLifespan(
        agent,
        mode="p2p",              # or "distributed"
        bind_port=7950,          # P2P port
        seed_nodes="ip:port",    # For multi-node
    )
)
```

### Complete FastAPI Example

```python
# app.py
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from jarviscore.profiles import CustomAgent
from jarviscore.integrations.fastapi import JarvisLifespan


class AnalysisRequest(BaseModel):
    data: str


class AnalystAgent(CustomAgent):
    """Agent that handles both API requests and P2P messages."""

    role = "analyst"
    capabilities = ["analysis"]

    async def setup(self):
        await super().setup()
        self.llm = MyLLMClient()

    async def on_peer_request(self, msg):
        """Handle requests from other agents in the mesh."""
        query = msg.data.get("question", "")
        result = self.llm.chat(f"Analyze: {query}")
        return {"response": result}

    def analyze(self, data: str) -> dict:
        """Method called by API endpoint."""
        result = self.llm.chat(f"Analyze this data: {data}")
        return {"analysis": result}


# Create agent instance
analyst = AnalystAgent()

# Create FastAPI app with automatic lifecycle management
app = FastAPI(
    title="Analyst Service",
    lifespan=JarvisLifespan(analyst, mode="p2p", bind_port=7950)
)


@app.post("/analyze")
async def analyze(request: AnalysisRequest):
    """API endpoint - also accessible as a peer in the mesh."""
    result = analyst.analyze(request.data)
    return result


@app.get("/peers")
async def list_peers():
    """See what other agents are in the mesh."""
    if analyst.peers:
        return {"peers": analyst.peers.list()}
    return {"peers": []}
```

Run with:
```bash
uvicorn app:app --host 0.0.0.0 --port 8000
```

Your agent is now:
- Serving HTTP API on port 8000
- Participating in P2P mesh on port 7950
- Discoverable by other agents
- Automatically handles lifecycle

### Testing the Flow

**Step 1: Start the FastAPI server (Terminal 1)**
```bash
python examples/fastapi_integration_example.py
```

**Step 2: Join a scout agent (Terminal 2)**
```bash
python examples/fastapi_integration_example.py --join-as scout
```

**Step 3: Test with curl (Terminal 3)**
```bash
# Chat with assistant (may delegate to analyst)
curl -X POST http://localhost:8000/chat -H "Content-Type: application/json" -d '{"message": "Analyze Q4 sales trends"}'

# Ask analyst directly
curl -X POST http://localhost:8000/ask/analyst -H "Content-Type: application/json" -d '{"message": "What are key revenue metrics?"}'

# See what each agent knows about peers (cognitive context)
curl http://localhost:8000/agents
```

**Expected flow for `/chat`:**
1. Request goes to **assistant** agent
2. Assistant's LLM sees peers via `get_cognitive_context()`
3. LLM decides to delegate to **analyst** (data analysis request)
4. Assistant uses `ask_peer` tool → P2P message to analyst
5. Analyst processes and responds via P2P
6. Response includes `"delegated_to": "analyst"` and `"peer_data"`

**Example response:**
```json
{
  "message": "Analyze Q4 sales trends",
  "response": "Based on the analyst's findings...",
  "delegated_to": "analyst",
  "peer_data": {"analysis": "...", "confidence": 0.9}
}
```

---

## Cloud Deployment (v0.3.0)

**Self-registration** lets agents join existing meshes without a central orchestrator - perfect for Docker, Kubernetes, and auto-scaling.

### The Problem: Central Orchestrator Required

Before v0.3.0, all agents had to be registered with a central Mesh:

```python
# BEFORE: Central orchestrator pattern
# You needed one "main" node that registered all agents

# main_node.py (central orchestrator)
mesh = Mesh(mode="distributed", config={"bind_port": 7950})
mesh.add(ResearcherAgent)  # Must be on this node
mesh.add(WriterAgent)      # Must be on this node
await mesh.start()
```

**Problems with this approach:**
- Single point of failure
- Can't easily scale agent instances
- Doesn't work well with Kubernetes/Docker
- All agents must be on the same node or manually configured

### The Solution: `join_mesh()` and `leave_mesh()`

```python
# AFTER: Self-registering agents
# Each agent can join any mesh independently

# agent_container.py (runs in Docker/K8s)
from jarviscore.profiles import CustomAgent
import os


class WorkerAgent(CustomAgent):
    role = "worker"
    capabilities = ["processing"]

    async def on_peer_request(self, msg):
        return {"result": "processed"}


async def main():
    agent = WorkerAgent()
    await agent.setup()

    # Join existing mesh via environment variable
    seed_nodes = os.environ.get("JARVISCORE_SEED_NODES", "mesh-service:7950")
    await agent.join_mesh(seed_nodes=seed_nodes)

    # Agent is now part of the mesh, discoverable by others
    await agent.serve_forever()

    # Clean shutdown
    await agent.leave_mesh()
```

### Environment Variables for Cloud

| Variable | Description | Example |
|----------|-------------|---------|
| `JARVISCORE_SEED_NODES` | Comma-separated list of mesh nodes | `"10.0.0.1:7950,10.0.0.2:7950"` |
| `JARVISCORE_MESH_ENDPOINT` | This agent's reachable address | `"worker-pod-abc:7950"` |
| `JARVISCORE_BIND_PORT` | Port to listen on | `"7950"` |

### Docker Deployment Example

```dockerfile
# Dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
CMD ["python", "agent.py"]
```

```python
# agent.py
import asyncio
import os
from jarviscore.profiles import CustomAgent


class WorkerAgent(CustomAgent):
    role = "worker"
    capabilities = ["processing"]

    async def on_peer_request(self, msg):
        task = msg.data.get("task", "")
        return {"result": f"Processed: {task}"}


async def main():
    agent = WorkerAgent()
    await agent.setup()

    # Configuration from environment
    seed_nodes = os.environ.get("JARVISCORE_SEED_NODES")
    mesh_endpoint = os.environ.get("JARVISCORE_MESH_ENDPOINT")

    if seed_nodes:
        await agent.join_mesh(
            seed_nodes=seed_nodes,
            advertise_endpoint=mesh_endpoint
        )
        print(f"Joined mesh via {seed_nodes}")
    else:
        print("Running standalone (no JARVISCORE_SEED_NODES)")

    await agent.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
```

```yaml
# docker-compose.yml
version: '3.8'
services:
  mesh-seed:
    build: .
    environment:
      - JARVISCORE_BIND_PORT=7950
    ports:
      - "7950:7950"

  worker-1:
    build: .
    environment:
      - JARVISCORE_SEED_NODES=mesh-seed:7950
      - JARVISCORE_MESH_ENDPOINT=worker-1:7950
    depends_on:
      - mesh-seed

  worker-2:
    build: .
    environment:
      - JARVISCORE_SEED_NODES=mesh-seed:7950
      - JARVISCORE_MESH_ENDPOINT=worker-2:7950
    depends_on:
      - mesh-seed
```

### Kubernetes Deployment Example

```yaml
# k8s-deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: jarvis-worker
spec:
  replicas: 3  # Scale as needed
  selector:
    matchLabels:
      app: jarvis-worker
  template:
    metadata:
      labels:
        app: jarvis-worker
    spec:
      containers:
      - name: worker
        image: myregistry/jarvis-worker:latest
        env:
        - name: JARVISCORE_SEED_NODES
          value: "jarvis-mesh-service:7950"
        - name: JARVISCORE_MESH_ENDPOINT
          valueFrom:
            fieldRef:
              fieldPath: status.podIP
        ports:
        - containerPort: 7950
---
apiVersion: v1
kind: Service
metadata:
  name: jarvis-mesh-service
spec:
  selector:
    app: jarvis-mesh-seed
  ports:
  - port: 7950
    targetPort: 7950
```

### How Self-Registration Works

```
┌─────────────────────────────────────────────────────────────┐
│                    SELF-REGISTRATION FLOW                    │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  1. New container starts                                    │
│     │                                                       │
│     ▼                                                       │
│  2. agent.join_mesh(seed_nodes="mesh:7950")                │
│     │                                                       │
│     ▼                                                       │
│  3. Agent connects to seed node                            │
│     │                                                       │
│     ▼                                                       │
│  4. SWIM protocol discovers all peers                      │
│     │                                                       │
│     ▼                                                       │
│  5. Agent registers its role/capabilities                  │
│     │                                                       │
│     ▼                                                       │
│  6. Other agents can now discover and call this agent      │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### RemoteAgentProxy (Automatic)

When agents join from different nodes, the framework automatically creates `RemoteAgentProxy` objects. You don't need to do anything special - the mesh handles it:

```python
# On any node, you can discover and call remote agents
if agent.peers:
    # This works whether the peer is local or remote
    response = await agent.peers.as_tool().execute(
        "ask_peer",
        {"role": "worker", "question": "Process this data"}
    )
```

---

## Session Context Propagation (v0.3.2)

Pass metadata (mission IDs, trace IDs, priorities) through message flows:

### Sending Context

```python
# All messaging methods accept context parameter
await self.peers.notify("logger", {"event": "started"},
                       context={"mission_id": "m-123", "trace_id": "t-abc"})

response = await self.peers.request("analyst", {"query": "..."},
                                   context={"priority": "high", "user_id": "u-456"})

await self.peers.broadcast({"alert": "ready"},
                          context={"source": "coordinator"})
```

### Receiving Context

```python
async def on_peer_request(self, msg):
    # Context is available on the message
    mission_id = msg.context.get("mission_id") if msg.context else None
    trace_id = msg.context.get("trace_id") if msg.context else None

    self._logger.info(f"Request for mission {mission_id}, trace {trace_id}")

    return {"result": "processed"}
```

### Auto-Propagation in respond()

Context automatically propagates from request to response:

```python
async def on_peer_request(self, msg):
    # msg.context = {"mission_id": "m-123", "trace_id": "t-abc"}
    result = await self.process(msg.data)

    # Context auto-propagates - original sender receives same context
    await self.peers.respond(msg, {"result": result})

    # Override if needed
    await self.peers.respond(msg, {"result": result},
                            context={"status": "completed", "mission_id": msg.context.get("mission_id")})
```

---

## Async Request Pattern (v0.3.2)

Fire multiple requests without blocking, collect responses later:

### Fire-and-Collect Pattern

```python
async def parallel_analysis(self, data_chunks):
    # Fire off requests to all available analysts
    analysts = self.peers.discover(role="analyst")
    request_ids = []

    for i, (analyst, chunk) in enumerate(zip(analysts, data_chunks)):
        req_id = await self.peers.ask_async(
            analyst.agent_id,
            {"chunk_id": i, "data": chunk},
            context={"batch_id": "batch-001"}
        )
        request_ids.append((req_id, analyst.agent_id))

    # Do other work while analysts process
    await self.update_status("processing")

    # Collect results
    results = []
    for req_id, analyst_id in request_ids:
        response = await self.peers.check_inbox(req_id, timeout=30)
        if response:
            results.append(response)
        else:
            self._logger.warning(f"Timeout waiting for {analyst_id}")

    return results
```

### API Methods

```python
# Fire async request - returns immediately with request_id
req_id = await self.peers.ask_async(target, message, timeout=120, context=None)

# Check for response
response = await self.peers.check_inbox(req_id, timeout=0)  # Non-blocking
response = await self.peers.check_inbox(req_id, timeout=10)  # Wait up to 10s

# Manage pending requests
pending = self.peers.get_pending_async_requests()
self.peers.clear_inbox(req_id)  # Clear specific
self.peers.clear_inbox()        # Clear all
```

---

## Load Balancing Strategies (v0.3.2)

Distribute work across multiple peers:

### Discovery Strategies

```python
# Default: first in discovery order (deterministic)
workers = self.peers.discover(role="worker", strategy="first")

# Random: shuffle for basic distribution
workers = self.peers.discover(role="worker", strategy="random")

# Round-robin: rotate through workers on each call
workers = self.peers.discover(role="worker", strategy="round_robin")

# Least-recent: prefer workers not used recently
workers = self.peers.discover(role="worker", strategy="least_recent")
```

### discover_one() Convenience

```python
# Get single peer with strategy applied
worker = self.peers.discover_one(role="worker", strategy="round_robin")
if worker:
    response = await self.peers.request(worker.agent_id, {"task": "..."})
```

### Tracking Usage for least_recent

```python
# Track usage to influence least_recent ordering
worker = self.peers.discover_one(role="worker", strategy="least_recent")
response = await self.peers.request(worker.agent_id, {"task": "..."})
self.peers.record_peer_usage(worker.agent_id)  # Update timestamp
```

### Example: Load-Balanced Task Distribution

```python
class Coordinator(CustomAgent):
    role = "coordinator"
    capabilities = ["coordination"]

    async def distribute_work(self, tasks):
        results = []
        for task in tasks:
            # Round-robin automatically rotates through workers
            worker = self.peers.discover_one(
                capability="processing",
                strategy="round_robin"
            )
            if worker:
                response = await self.peers.request(
                    worker.agent_id,
                    {"task": task}
                )
                results.append(response)
        return results
```

---

## Mesh Diagnostics (v0.3.2)

Monitor mesh health for debugging and operations:

### Getting Diagnostics

```python
# From mesh
diag = mesh.get_diagnostics()

# Structure:
# {
#     "local_node": {
#         "mode": "p2p",
#         "started": True,
#         "agent_count": 3,
#         "bind_address": "127.0.0.1:7950"
#     },
#     "known_peers": [
#         {"role": "analyst", "node_id": "10.0.0.2:7950", "status": "alive"}
#     ],
#     "local_agents": [
#         {"role": "coordinator", "agent_id": "...", "capabilities": [...]}
#     ],
#     "connectivity_status": "healthy"
# }
```

### Connectivity Status

| Status | Meaning |
|--------|---------|
| `healthy` | P2P active, peers connected |
| `isolated` | P2P active, no peers found |
| `degraded` | Some connectivity issues |
| `not_started` | Mesh not started yet |
| `local_only` | Autonomous mode (no P2P) |

### FastAPI Health Endpoint

```python
from fastapi import FastAPI, Request
from jarviscore.integrations.fastapi import JarvisLifespan

app = FastAPI(lifespan=JarvisLifespan(agent, mode="p2p"))

@app.get("/health")
async def health(request: Request):
    mesh = request.app.state.jarvis_mesh
    diag = mesh.get_diagnostics()
    return {
        "status": diag["connectivity_status"],
        "agents": diag["local_node"]["agent_count"],
        "peers": len(diag.get("known_peers", []))
    }
```

---

## Testing with MockMesh (v0.3.2)

Unit test agents without real P2P infrastructure:

### Basic Test Setup

```python
import pytest
from jarviscore.testing import MockMesh, MockPeerClient
from jarviscore.profiles import CustomAgent

class AnalystAgent(CustomAgent):
    role = "analyst"
    capabilities = ["analysis"]

    async def on_peer_request(self, msg):
        return {"analysis": f"Analyzed: {msg.data.get('query')}"}

@pytest.mark.asyncio
async def test_analyst_responds():
    mesh = MockMesh()
    mesh.add(AnalystAgent)
    await mesh.start()

    analyst = mesh.get_agent("analyst")

    # Inject a test message
    from jarviscore.p2p.messages import MessageType
    analyst.peers.inject_message(
        sender="tester",
        message_type=MessageType.REQUEST,
        data={"query": "test data"},
        correlation_id="test-123"
    )

    # Receive and verify
    msg = await analyst.peers.receive(timeout=1)
    assert msg is not None
    assert msg.data["query"] == "test data"

    await mesh.stop()
```

### Mocking Peer Responses

```python
@pytest.mark.asyncio
async def test_coordinator_delegates():
    class CoordinatorAgent(CustomAgent):
        role = "coordinator"
        capabilities = ["coordination"]

        async def on_peer_request(self, msg):
            # This agent delegates to analyst
            analysis = await self.peers.request("analyst", {"data": msg.data})
            return {"coordinated": True, "analysis": analysis}

    mesh = MockMesh()
    mesh.add(CoordinatorAgent)
    await mesh.start()

    coordinator = mesh.get_agent("coordinator")

    # Mock the analyst response
    coordinator.peers.add_mock_peer("analyst", capabilities=["analysis"])
    coordinator.peers.set_mock_response("analyst", {"result": "mocked analysis"})

    # Test the flow
    response = await coordinator.peers.request("analyst", {"test": "data"})

    assert response["result"] == "mocked analysis"
    coordinator.peers.assert_requested("analyst")

    await mesh.stop()
```

### Assertion Helpers

```python
# Verify notifications were sent
agent.peers.assert_notified("target_role")
agent.peers.assert_notified("target", message_contains={"event": "completed"})

# Verify requests were sent
agent.peers.assert_requested("analyst")
agent.peers.assert_requested("analyst", message_contains={"query": "test"})

# Verify broadcasts
agent.peers.assert_broadcasted()
agent.peers.assert_broadcasted(message_contains={"alert": "important"})

# Access sent messages for custom assertions
notifications = agent.peers.get_sent_notifications()
requests = agent.peers.get_sent_requests()
broadcasts = agent.peers.get_sent_broadcasts()

# Reset between tests
agent.peers.reset()
```

### Custom Response Handler

```python
async def dynamic_handler(target, message, context):
    """Return different responses based on message content."""
    if "urgent" in message.get("query", ""):
        return {"priority": "high", "result": "fast response"}
    return {"priority": "normal", "result": "standard response"}

agent.peers.set_request_handler(dynamic_handler)
```

---

## API Reference

### CustomAgent Class Attributes

| Attribute | Type | Required | Description |
|-----------|------|----------|-------------|
| `role` | `str` | Yes | Unique identifier for this agent type (e.g., `"researcher"`) |
| `capabilities` | `list[str]` | Yes | List of capabilities for discovery (e.g., `["research", "analysis"]`) |

### CustomAgent Methods

| Method | Mode | Description |
|--------|------|-------------|
| `setup()` | Both | Called once on startup. Initialize resources here. Always call `await super().setup()` |
| `run()` | P2P | Main loop for continuous operation. Required for P2P mode |
| `execute_task(task)` | Distributed | Handle a workflow task. Required for Distributed mode |
| `join_mesh(seed_nodes, ...)` | Both | **(v0.3.0)** Self-register with an existing mesh |
| `leave_mesh()` | Both | **(v0.3.0)** Gracefully leave the mesh |
| `serve_forever()` | Both | **(v0.3.0)** Block until shutdown signal |

### P2P Message Handlers (v0.3.1)

CustomAgent includes built-in P2P message handlers for handler-based communication.

| Attribute/Method | Type | Description |
|------------------|------|-------------|
| `listen_timeout` | `float` | Seconds to wait for messages in `run()` loop. Default: 1.0 |
| `auto_respond` | `bool` | Auto-send `on_peer_request` return value. Default: True |
| `on_peer_request(msg)` | async method | Handle incoming requests. Return value sent as response |
| `on_peer_notify(msg)` | async method | Handle broadcast notifications. No return needed |
| `on_error(error, msg)` | async method | Handle errors during message processing |
| `run()` | async method | Built-in listener loop that dispatches to handlers |

**Note:** Override `on_peer_request()` and `on_peer_notify()` for your business logic. The `run()` method handles the message dispatch automatically.

### Why `execute_task()` Exists in CustomAgent

You may notice that P2P agents must implement `execute_task()` even though they primarily use `run()`. Here's why:

```
Agent (base class)
    │
    ├── @abstractmethod execute_task()  ← Python REQUIRES this to be implemented
    │
    └── run()  ← Optional, default does nothing
```

**The technical reason:**

1. `Agent.execute_task()` is declared as `@abstractmethod` in `core/agent.py`
2. Python's ABC (Abstract Base Class) requires ALL abstract methods to be implemented
3. If you don't implement it, Python raises:
   ```
   TypeError: Can't instantiate abstract class MyAgent with abstract method execute_task
   ```

**The design reason:**

- **Unified interface**: All agents can be called via `execute_task()`, regardless of mode
- **Flexibility**: A P2P agent can still participate in workflows if needed
- **Testing**: You can test any agent by calling `execute_task()` directly

**What to put in it for P2P mode:**

```python
async def execute_task(self, task: dict) -> dict:
    """Minimal implementation - main logic is in run()."""
    return {"status": "success", "note": "This agent uses run() for P2P mode"}
```

### Peer Tools (P2P Mode)

Access via `self.peers.as_tool().execute(tool_name, params)`:

| Tool | Parameters | Description |
|------|------------|-------------|
| `ask_peer` | `{"role": str, "question": str}` | Send a request to a peer by role and wait for response |
| `broadcast` | `{"message": str}` | Send a message to all connected peers |
| `list_peers` | `{}` | Get list of available peers and their capabilities |

### PeerClient Methods (v0.3.0)

Access via `self.peers`:

| Method | Returns | Description |
|--------|---------|-------------|
| `get_cognitive_context()` | `str` | Generate LLM-ready text describing available peers |
| `list()` | `list[PeerInfo]` | Get list of connected peers |
| `as_tool()` | `PeerTool` | Get peer tools for LLM tool use |
| `receive(timeout)` | `IncomingMessage` | Receive next message (for CustomAgent run loops) |
| `respond(msg, data)` | `None` | Respond to a request message |

### JarvisLifespan (v0.3.0)

FastAPI integration helper:

```python
from jarviscore.integrations.fastapi import JarvisLifespan

JarvisLifespan(
    agent,                      # Agent instance
    mode="p2p",                 # "p2p" or "distributed"
    bind_port=7950,             # Optional: P2P port
    seed_nodes="ip:port",       # Optional: for multi-node
)
```

### Mesh Configuration

```python
mesh = Mesh(
    mode="p2p" | "distributed",
    config={
        "bind_host": "0.0.0.0",          # IP to bind to (default: "127.0.0.1")
        "bind_port": 7950,                # Port to listen on
        "node_name": "my-node",           # Human-readable node name
        "seed_nodes": "ip:port,ip:port",  # Comma-separated list of known nodes
    }
)
```

### Mesh Methods

| Method | Description |
|--------|-------------|
| `mesh.add(AgentClass)` | Register an agent class |
| `mesh.start()` | Initialize and start all agents |
| `mesh.stop()` | Gracefully shut down all agents |
| `mesh.run_forever()` | Block until shutdown signal |
| `mesh.serve_forever()` | Same as `run_forever()` |
| `mesh.get_agent(role)` | Get agent instance by role |
| `mesh.workflow(name, steps)` | Run a workflow (Distributed mode) |

---

## Multi-Node Deployment

Run agents across multiple machines. Nodes discover each other via seed nodes.

### Machine 1: Research Node

```python
# research_node.py
import asyncio
from jarviscore import Mesh
from agents import ResearcherAgent


async def main():
    mesh = Mesh(
        mode="distributed",
        config={
            "bind_host": "0.0.0.0",        # Accept connections from any IP
            "bind_port": 7950,
            "node_name": "research-node",
        }
    )

    mesh.add(ResearcherAgent)
    await mesh.start()

    print("Research node running on port 7950...")
    await mesh.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
```

### Machine 2: Writer Node + Orchestrator

```python
# writer_node.py
import asyncio
from jarviscore import Mesh
from agents import WriterAgent


async def main():
    mesh = Mesh(
        mode="distributed",
        config={
            "bind_host": "0.0.0.0",
            "bind_port": 7950,
            "node_name": "writer-node",
            "seed_nodes": "192.168.1.10:7950",  # IP of research node
        }
    )

    mesh.add(WriterAgent)
    await mesh.start()

    # Wait for nodes to discover each other
    await asyncio.sleep(2)

    # Run workflow - tasks automatically route to correct nodes
    results = await mesh.workflow("cross-node-pipeline", [
        {"id": "research", "agent": "researcher", "task": "AI trends"},
        {"id": "write", "agent": "writer", "task": "Write article",
         "depends_on": ["research"]},
    ])

    print(results)
    await mesh.stop()


if __name__ == "__main__":
    asyncio.run(main())
```

### How Node Discovery Works

1. On startup, nodes connect to seed nodes
2. Seed nodes share their known peers
3. Nodes exchange agent capability information
4. Workflows automatically route tasks to nodes with matching agents

---

## Error Handling

### In P2P Mode

```python
async def run(self):
    while not self.shutdown_requested:
        try:
            if self.peers:
                msg = await self.peers.receive(timeout=0.5)
                if msg and msg.is_request:
                    try:
                        result = await self.process(msg.data)
                        await self.peers.respond(msg, {"response": result})
                    except Exception as e:
                        await self.peers.respond(msg, {
                            "error": str(e),
                            "status": "failed"
                        })
        except Exception as e:
            print(f"Error in run loop: {e}")

        await asyncio.sleep(0.1)
```

### In Distributed Mode

```python
async def execute_task(self, task: dict) -> dict:
    try:
        result = await self.do_work(task)
        return {
            "status": "success",
            "output": result
        }
    except ValueError as e:
        return {
            "status": "error",
            "error": f"Invalid input: {e}"
        }
    except Exception as e:
        return {
            "status": "error",
            "error": f"Unexpected error: {e}"
        }
```

### Handling Missing Peers

```python
async def ask_researcher(self, question: str) -> str:
    if not self.peers:
        raise RuntimeError("Peer system not initialized")

    try:
        response = await asyncio.wait_for(
            self.peers.as_tool().execute(
                "ask_peer",
                {"role": "researcher", "question": question}
            ),
            timeout=30.0  # 30 second timeout
        )
        return response.get("response", "")
    except asyncio.TimeoutError:
        raise RuntimeError("Researcher did not respond in time")
    except Exception as e:
        raise RuntimeError(f"Failed to contact researcher: {e}")
```

---

## Troubleshooting

### Agent not receiving messages

**Problem**: `self.peers.receive()` always returns `None`

**Solutions**:
1. Ensure the sending agent is using the correct `role` in `ask_peer`
2. Check that both agents are registered with the mesh
3. Verify `await super().setup()` is called in your `setup()` method
4. Add logging to confirm your `run()` loop is executing

### Workflow tasks not executing

**Problem**: `mesh.workflow()` hangs or returns empty results

**Solutions**:
1. Verify agent `role` matches the `agent` field in workflow steps
2. Check `execute_task()` returns a dict with `status` key
3. Ensure all `depends_on` step IDs exist in the workflow
4. Check for circular dependencies

### Nodes not discovering each other

**Problem**: Multi-node setup, but workflows fail to find agents

**Solutions**:
1. Verify `seed_nodes` IP and port are correct
2. Check firewall allows connections on the bind port
3. Ensure `bind_host` is `"0.0.0.0"` (not `"127.0.0.1"`) for remote connections
4. Wait a few seconds after `mesh.start()` for discovery to complete

### "Peer system not available" errors

**Problem**: `self.peers` is `None`

**Solutions**:
1. Only access `self.peers` after `setup()` completes
2. Check that mesh is started with `await mesh.start()`
3. Verify the agent was added with `mesh.add(AgentClass)`

---

## Examples

For complete, runnable examples, see:

- `examples/customagent_p2p_example.py` - P2P mode with LLM-driven peer communication
- `examples/customagent_distributed_example.py` - Distributed mode with workflows
- `examples/customagent_cognitive_discovery_example.py` - CustomAgent + cognitive discovery (v0.3.0)
- `examples/fastapi_integration_example.py` - FastAPI + JarvisLifespan (v0.3.0)
- `examples/cloud_deployment_example.py` - Self-registration with join_mesh (v0.3.0)

---

*CustomAgent Guide - JarvisCore Framework v0.3.2*
