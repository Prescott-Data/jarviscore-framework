---
icon: material/test-tube
---

# Testing Agents

JarvisCore provides a complete set of mock objects for testing agents without real infrastructure. You can write fast, deterministic unit tests without a running Redis instance, a live LLM API key, or an active P2P mesh.

All mocks are in `jarviscore.testing`:

```python
from jarviscore.testing import MockMesh, MockPeerClient, MockBlobStorage, MockRedisContextStore, MockLLMClient
```

---

## MockMesh

`MockMesh` registers agents, runs their `setup()` lifecycle methods, and injects a `MockPeerClient` into each agent.

```python
import pytest
from jarviscore.testing import MockMesh

@pytest.mark.asyncio
async def test_notifier_sends_to_analyst():
    mesh = MockMesh()
    mesh.add(NotifierAgent)
    mesh.add(AnalystAgent)
    await mesh.start()

    notifier = mesh.get_agent("notifier")
    await notifier.run("Notify analyst of data readiness.", context={})

    notifier.peers.assert_notified("analyst", message_contains={"event": "data_ready"})

    await mesh.stop()
```

| Method | Description |
|---|---|
| `add(agent_class_or_instance)` | Register an agent. Returns the instantiated agent. |
| `await start()` | Runs `setup()` on all agents and injects `MockPeerClient`. |
| `await stop()` | Runs `teardown()` on all agents. |
| `get_agent(role)` | Returns the agent by role slug. |
| `get_diagnostics()` | Returns a dict summarising mock mesh state. |

---

## MockPeerClient

Full drop-in replacement for `PeerClient`. Simulates discovery and messaging without network I/O. `MockMesh.start()` injects it automatically; you can also construct it directly.

### Configuring responses

```python
# Exact response for a specific target
client.set_mock_response("analyst", {"analysis": "Revenue up 12%", "confidence": 0.91})

# Default response for all other targets
client.set_default_response({"status": "ok"})

# Custom async handler for dynamic logic
async def handler(target, message, context):
    return {"result": f"handled by {target}"}

client.set_request_handler(handler)
```

### Injecting incoming messages

```python
from jarviscore.p2p.messages import MessageType

client.inject_message(
    sender="orchestrator",
    message_type=MessageType.NOTIFY,
    data={"event": "data_ready", "payload": {"rows": 420}},
)
msg = await client.receive(timeout=1)
assert msg.data["event"] == "data_ready"
```

### Assertion helpers

```python
client.assert_notified("analyst")
client.assert_notified("analyst", message_contains={"event": "data_ready"})
client.assert_requested("analyst")
client.assert_broadcasted(message_contains={"action": "ping"})

# Manual inspection
notifications = client.get_sent_notifications()
requests = client.get_sent_requests()

# Reset between tests
client.reset()
```

---

## MockBlobStorage

In-memory blob storage. All data lives in a dict — no filesystem access required.

```python
from jarviscore.testing import MockBlobStorage

storage = MockBlobStorage()
await storage.save_scratchpad("wf-001", "step-1", "# Working notes\n- Found 42 results")
content = await storage.read_scratchpad("wf-001", "step-1")
assert "42 results" in content

# Inspect all written paths
assert "workflows/wf-001/scratchpads/step-1.md" in storage.stored_paths
storage.clear()
```

| Method | Description |
|---|---|
| `await save(path, content)` | Save content at path. |
| `await read(path)` | Return content or `None`. |
| `await list(prefix)` | Return paths matching prefix. |
| `await save_scratchpad(wf_id, step_id, content)` | Save scratchpad at standard path. |
| `await save_artifact(wf_id, step_id, filename, content)` | Save agent output artifact. |
| `stored_paths` | Sorted list of all paths in the store. |
| `clear()` | Clear all stored data. |

---

## MockRedisContextStore

Backed by `fakeredis` — provides a real Redis-compatible API without a running server. All `RedisContextStore` methods work identically.

```python
from jarviscore.testing import MockRedisContextStore

store = MockRedisContextStore()
store.save_step_output("wf-001", "step-1", output={"result": 42}, summary="step complete")
result = store.get_step_output("wf-001", "step-1")
assert result["output"] == {"result": 42}
```

> [!NOTE]
> Requires `fakeredis`:
> ```bash
> pip install fakeredis
> ```

---

## MockLLMClient

Returns canned responses from a queue. Tracks all `generate()` calls for assertion.

```python
from jarviscore.testing import MockLLMClient

llm = MockLLMClient(responses=[
    {"content": "TOOL: search_web\nPARAMS: {\"query\": \"EV market\"}"},
    {"content": "DONE: Research complete."},
])

result = await llm.generate(prompt="Research EV adoption")
assert result["content"].startswith("TOOL:")
assert len(llm.calls) == 1
llm.reset()
```

When the queue is exhausted, `MockLLMClient` returns `{"content": "DONE: no more responses"}`.

---

## Testing HITL Flows

Use `HITLQueue.resolve()` to simulate human decisions:

```python
@pytest.mark.asyncio
async def test_campaign_approved():
    mesh = MockMesh()
    mesh.add(CampaignSenderAgent)
    await mesh.start()

    agent = mesh.get_agent("campaign-sender")

    import asyncio

    async def approve():
        await asyncio.sleep(0.1)
        pending = agent.hitl.pending()
        if pending:
            agent.hitl.resolve(pending[0]["id"], "approved", "Test auto-approval")

    asyncio.create_task(approve())
    result = await agent.run("Send Q2 newsletter", context={})
    assert result["status"] == "sent"

    await mesh.stop()
```

---

## Complete Example

```python title="tests/test_transformer.py"
import json, pytest
from jarviscore.testing import MockMesh
from agents.transformer import DataTransformerAgent

@pytest.mark.asyncio
async def test_transformer_notifies_analyst():
    mesh = MockMesh()
    mesh.add(DataTransformerAgent)
    await mesh.start()

    agent = mesh.get_agent("transformer")
    payload = json.dumps({"revenue": 1_500_000, "region": "EMEA"})
    result = await agent.run(payload, context={"schema": "financial-v2", "turn_id": "t1"})

    assert "data" in result
    agent.peers.assert_notified("analyst", message_contains={"event": "transformation_complete"})

    await mesh.stop()
```
