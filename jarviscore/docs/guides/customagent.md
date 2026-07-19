---
icon: material/code-braces
---

# CustomAgent Guide

`CustomAgent` is JarvisCore's structured execution agent. You implement the handlers yourself, which gives you complete control over what happens when a message arrives. The framework provides the infrastructure layer — memory, peer communication, Nexus auth, mailbox, blob storage, and mesh connectivity — all injected automatically before your `setup()` runs.

Use `CustomAgent` when the steps required to complete a task are known in advance, when you are wrapping an existing service or LangChain agent, when you need deterministic auditable execution, or when you want to build a long-running message-driven worker rather than a one-shot task executor.

---

## The Core Interface

`CustomAgent` is a message-driven agent. The primary method to implement is `on_peer_request()`, not `run()`. The `run()` method is the framework's internal listener loop — it receives P2P messages and dispatches them to your handlers. You do not override it.

```python title="agents/analyst.py"
from jarviscore import CustomAgent

class AnalystAgent(CustomAgent):
    role = "analyst"
    capabilities = ["analysis", "reporting"]

    async def on_peer_request(self, msg) -> dict:
        data = msg.data
        result = await self.analyse(data["payload"])
        return {"status": "success", "result": result}

    async def on_peer_notify(self, msg) -> None:
        if msg.data.get("event") == "task_complete":
            await self.update_dashboard(msg.data)

    async def on_error(self, error: Exception, msg=None) -> None:
        self._logger.error("Error from %s: %s", msg.sender if msg else "loop", error)
```

The `msg` parameter is an `IncomingMessage` object. Its fields are:

| Field | Description |
|---|---|
| `msg.sender` | Sender agent ID or role string |
| `msg.data` | Payload dict |
| `msg.type` | `MessageType.REQUEST` or `MessageType.NOTIFY` |
| `msg.correlation_id` | For response matching — handled automatically |

Return a dict from `on_peer_request()` and the framework sends it back to the requester automatically (controlled by `auto_respond = True`, the default). Return `None` to skip sending a response.

`on_peer_notify()` handles fire-and-forget messages. No response is expected or sent.

### Class Attributes

| Attribute | Required | Description |
|---|---|---|
| `role` | Yes | Slug used for peer discovery and workflow routing |
| `capabilities` | Yes | Tags for capability-based peer discovery |
| `name` | No | Human-readable display name |
| `description` | No | One-sentence purpose |
| `requires_auth` | No | Set `True` to receive Nexus-backed `_auth_manager` injection |
| `listen_timeout` | No | Seconds to wait for messages in the receive loop (default `1.0`) |
| `auto_respond` | No | Automatically send `on_peer_request()` return value (default `True`) |

---

## Lifecycle

### setup

Called once by the Mesh after instantiation. Override to initialise connections, load configuration, or perform one-time setup. Always call `await super().setup()` first — this connects the agent to memory tiers and the peer registry:

```python
async def setup(self):
    await super().setup()
    self.schema_registry = await SchemaRegistry.load(self.config.schema_path)
    self._logger.info("%s setup complete", self.name)
```

### teardown

Called during Mesh shutdown. Release any resources opened in `setup()`:

```python
async def teardown(self):
    await self.schema_registry.close()
    await super().teardown()
```

---

## Running a CustomAgent

```python title="main.py"
import asyncio
from jarviscore import Mesh
from agents import AnalystAgent

async def main():
    mesh = Mesh()
    mesh.add(AnalystAgent)
    await mesh.start()
    await mesh.run_forever()   # starts on_peer_request loop for all agents that have run()

asyncio.run(main())
```

`Mesh()` takes no mode argument. Infrastructure is auto-detected at `start()` time. Pass `p2p_enabled: True` in the config dict to activate SWIM/ZMQ peer transport between nodes.

---

## Auto-Injected Infrastructure

The Mesh injects these stores into every agent before `setup()` runs. All three are available immediately inside `setup()`:

| Attribute | Type | Available when |
|---|---|---|
| `self._redis_store` | `RedisStore` | `REDIS_URL` is set |
| `self._blob_storage` | `LocalBlobStorage` or `AzureBlobStorage` | Always — falls back to local filesystem |
| `self.mailbox` | `MailboxManager` | `REDIS_URL` is set |

```python
async def setup(self):
    await super().setup()
    # All three already injected — use them immediately
    self.memory = UnifiedMemory(
        workflow_id="wf-001", step_id=self.role,
        agent_id=self.role,
        redis_store=self._redis_store,
        blob_storage=self._blob_storage,
    )
```

---

## Memory

`UnifiedMemory` gives access to all four memory tiers. Instantiate it in `setup()` after calling `super().setup()`:

```python
from jarviscore.memory import UnifiedMemory, RedisMemoryAccessor

async def setup(self):
    await super().setup()
    self.memory = UnifiedMemory(
        workflow_id="content-2026", step_id="writer",
        agent_id=self.role,
        redis_store=self._redis_store,
        blob_storage=self._blob_storage,
    )

async def on_peer_request(self, msg) -> dict:
    # Log this interaction to the episodic ledger
    await self.memory.episodic.append({"event": "request", "sender": msg.sender})

    # Load a prior step's output from another agent
    accessor = RedisMemoryAccessor(self._redis_store, workflow_id="content-2026")
    raw = accessor.get("research")
    research = raw.get("output", raw) if isinstance(raw, dict) else {}

    result = await self.write(research, msg.data)

    # Save output artifact
    await self._blob_storage.save("drafts/article.md", result)

    # Persist a style note for next run
    await self.memory.ltm.save_summary("Style: concise, technical, no jargon.")

    return {"status": "success", "output": result}
```

For the full `UnifiedMemory` API, see the [Memory](../concepts/memory.md) concept page.

---

## Blob Storage

`LocalBlobStorage` writes to `./blob_storage/` by default. Switch to Azure by setting `STORAGE_BACKEND=azure` in your `.env`.

```python
# Save artifacts
await self._blob_storage.save("research/findings.json", json.dumps(research))
await self._blob_storage.save("reports/summary.md", markdown_text)

# Load an artifact
content = await self._blob_storage.read("research/findings.json")
data = json.loads(content) if content else {}
```

The conventional path structure is `{type}/{workflow_id}/{filename}.{ext}`.

---

## MailboxManager

`MailboxManager` provides fire-and-forget messaging between agents backed by Redis Streams. Messages survive process restarts when `REDIS_URL` is set.

```python
# Route a query to a specialist agent
self.mailbox.send(technical_agent_id, {
    "query": "API auth broken",
    "customer_id": "cust-42",
})

# Drain inbox
messages = self.mailbox.read(max_messages=10)
for msg in messages:
    query = msg.get("query")
    # handle it...
```

The `target_id` is the agent's `agent_id` string, which is usually `"{role}-{uuid4[:8]}"`. You can retrieve a peer's agent ID from the peer registry before sending.

---

## Peer Communication

For request-response patterns between agents, use `self.peers`:

```python
async def on_peer_request(self, msg) -> dict:
    result = await self.process(msg.data)

    # Notify a downstream reporter (fire-and-forget)
    await self.peers.notify(
        "reporter",
        {"event": "analysis_complete", "data": result},
    )

    # Request validation from a peer (request-response)
    peer = self.peers.discover_one(role="validator")
    if peer:
        validation = await self.peers.request(
            peer.agent_id,
            {"action": "validate", "data": result},
            timeout=20,
        )
        if validation and not validation.get("valid"):
            result = await self.remediate(result, validation.get("feedback"))

    return {"status": "success", "result": result}
```

For the complete `PeerClient` API, see the [P2P Communication](../concepts/p2p.md) concept page.

---

## Nexus Auth: requires_auth

Set `requires_auth = True` on agents that call third-party services. The Mesh creates an `AuthenticationManager` backed by Nexus and injects it as `self._auth_manager` after `setup()` completes. The full OAuth flow — browser consent, token refresh — is handled automatically.

```python
class TechnicalAgent(CustomAgent):
    role = "technical_support"
    capabilities = ["github", "technical-support"]
    requires_auth = True

    async def on_peer_request(self, msg) -> dict:
        if self._auth_manager:
            result = await self._auth_manager.make_authenticated_request(
                provider="github",
                method="GET",
                url="https://api.github.com/user",
            )
        else:
            result = {"status": "degraded", "note": "no auth configured"}
        return {"status": "success", "output": result}
```

`_auth_manager` is `None` when `NEXUS_GATEWAY_URL` is not set. Always check `if self._auth_manager:` before using it — this is the graceful degradation path for environments without Nexus configured.

---

## Workflow Compatibility

`CustomAgent` can participate in `mesh.workflow()` calls, not just P2P message loops. The `execute_task()` method is already implemented — it creates a synthetic `IncomingMessage` from the workflow step dict and delegates to `on_peer_request()`. You get workflow participation for free by implementing `on_peer_request()`.

```python
results = await mesh.workflow("support-pipeline", [
    {"id": "classify", "agent": "gateway",   "task": "Route this query: API 401 error"},
    {"id": "resolve",  "agent": "technical", "task": "Resolve API auth issue", "depends_on": ["classify"]},
])
```

If you need workflow logic that is distinct from your message handling, override `execute_task()` directly:

```python
async def execute_task(self, task: dict) -> dict:
    query = task.get("task", "")
    result = await self.process_query(query)
    return {"status": "success", "output": result}
```

---

## Agent Profile Integration

Like `AutoAgent`, `CustomAgent` loads an agent profile YAML file during `setup()` if `JARVISCORE_PROFILES_DIR` is configured. The rendered profile block is available as `self._profile_block`. Use it when you are making LLM calls directly from your `on_peer_request()`:

```python
async def on_peer_request(self, msg) -> dict:
    system_prompt = (
        f"{self._profile_block}\n\n---\n\n{self.base_prompt}"
        if self._profile_block else self.base_prompt
    )
    response = await self.llm.generate(prompt=msg.data["query"], system=system_prompt)
    return {"result": response["content"]}
```

For the profile YAML schema, see the [Agent Personas](../concepts/agent-personas.md) concept page.

---

## Prometheus Metrics

Record step execution time and status at the end of every handler:

```python
import time
from jarviscore.telemetry.metrics import record_step_execution

async def on_peer_request(self, msg) -> dict:
    start = time.time()
    try:
        result = await self.process(msg.data)
        record_step_execution(time.time() - start, "success")
        return {"status": "success", "output": result}
    except Exception as e:
        record_step_execution(time.time() - start, "failure")
        return {"status": "failure", "error": str(e)}
```

Enable with `PROMETHEUS_ENABLED=true` and `PROMETHEUS_PORT=9090` in your `.env`. The metric is `jarviscore_step_duration_seconds`.

---

## Wrapping Third-Party Frameworks

`CustomAgent` is designed to wrap existing frameworks without requiring you to rewrite them. Initialise the third-party client in `setup()` and delegate to it in `on_peer_request()`.

Wrapping LangChain:

```python
class LangChainAgent(CustomAgent):
    role = "assistant"
    capabilities = ["chat", "reasoning"]

    async def setup(self):
        await super().setup()
        from langchain.agents import initialize_agent
        self.lc_agent = initialize_agent(...)

    async def on_peer_request(self, msg) -> dict:
        result = await self.lc_agent.arun(msg.data["query"])
        return {"status": "success", "output": result}
```

Wrapping an MCP server:

```python
class MCPAgent(CustomAgent):
    role = "mcp_bridge"
    capabilities = ["mcp_tools"]

    async def setup(self):
        await super().setup()
        from mcp import Client
        self.mcp = Client("stdio://./server.py")
        await self.mcp.connect()

    async def on_peer_request(self, msg) -> dict:
        result = await self.mcp.call_tool("my_tool", msg.data)
        return {"status": "success", "data": result}
```

---

## Production Examples

The [Support Swarm example](../examples/support-swarm.md) shows four `CustomAgent` instances running in a single process with P2P messaging. A `GatewayAgent` reads incoming queries and routes them via mailbox to specialist agents — `TechnicalAgent` (with `requires_auth = True` for GitHub), `BillingAgent`, and `EscalationAgent`.

```bash
docker compose -f docker-compose.infra.yml up -d
cp .env.example .env   # set GEMINI_API_KEY, REDIS_URL, NEXUS_GATEWAY_URL
python examples/support_swarm.py
```

The [Content Pipeline example](../examples/content-pipeline.md) shows a `CustomAgent` (`PublisherAgent`) running alongside `AutoAgent` research and writing agents in a distributed workflow. The publisher coordinates final delivery and blob storage persistence.

---

## Scheduled Tasks

JarvisCore does not include a built-in scheduler or cron primitive. Recurring tasks are implemented with `CustomAgent` and `asyncio` — the `run_forever()` loop is async, so you can add timed work directly inside the agent:

```python
import asyncio
from jarviscore import CustomAgent, Mesh

class DailyReportAgent(CustomAgent):
    role = "reporter"
    capabilities = ["reporting"]

    INTERVAL_SECONDS = 86_400  # 24 hours

    async def setup(self):
        await super().setup()
        # Launch the scheduled loop as a background task
        self._schedule_task = asyncio.create_task(self._scheduled_loop())

    async def _scheduled_loop(self):
        while not self._shutdown_requested:
            try:
                await self._run_report()
            except Exception as exc:
                self._logger.error("Scheduled report failed: %s", exc)
            await asyncio.sleep(self.INTERVAL_SECONDS)

    async def teardown(self):
        if hasattr(self, "_schedule_task"):
            self._schedule_task.cancel()
        await super().teardown()

    async def on_peer_request(self, msg) -> dict:
        return {"status": "active"}
```

For production scheduling, integrate [APScheduler](https://apscheduler.readthedocs.io/) (`pip install apscheduler[asyncio]`) in `setup()`, or trigger workflows from an external cron via a FastAPI endpoint.

---

## Human-in-the-Mesh

A human can participate in an agent mesh as an addressable peer by implementing a `CustomAgent` that bridges between your application's human-facing interface and the agent network. Agents message the operator peer exactly like any other agent.

```python
class OperatorAgent(CustomAgent):
    role = "operator"
    capabilities = ["human-review", "approval"]

    async def on_peer_request(self, msg) -> dict:
        # Forward to your review queue (DB, WebSocket, Slack, etc.)
        review_id = await self._enqueue_for_human(msg.sender, msg.data)
        response = await self._wait_for_human_response(review_id, timeout=3600)
        return {"status": "success", "decision": response["decision"]}
```

Other agents address this peer directly:

```python
response = await self._peer_client.send("operator", {
    "question": "Approve this trade?",
    "context": {"symbol": "AAPL", "quantity": 500},
})
```

JarvisCore provides the peer messaging infrastructure. You wire the human-facing interface — Slack, web dashboard, mobile app, or CLI.
