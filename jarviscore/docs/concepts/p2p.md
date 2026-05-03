---
icon: material/transit-connection-variant
---

# P2P Communication

JarvisCore agents can communicate directly with one another without going through the workflow orchestrator. This direct messaging layer is called the P2P mesh. It uses the SWIM (Scalable Weakly-consistent Infection-style Membership) gossip protocol for node discovery and ZeroMQ (ZMQ) for message transport.

The P2P mesh is designed for two distinct use cases. The first is same-node communication between agents running in the same Python process, where messages are delivered in memory without any network overhead. The second is cross-node communication between agents running on separate machines, where the SWIM coordinator handles discovery and ZMQ handles serialisation and delivery.

---

## Enabling P2P

P2P is disabled by default. Enable it by setting `P2P_ENABLED=true` in your environment.

```bash title=".env"
P2P_ENABLED=true
JC_SWIM_HOST=0.0.0.0
JC_SWIM_PORT=7946
```

When `P2P_ENABLED=true`, `Mesh.start()` initialises the SWIM coordinator automatically. No code changes are required.

For a multi-node deployment, each node specifies the other nodes as seed peers:

```bash title=".env (node 2)"
P2P_ENABLED=true
JC_SWIM_HOST=0.0.0.0
JC_SWIM_PORT=7947
JC_SEED_NODES=10.0.0.1:7946
```

!!! warning "Port uniqueness on the same machine"
    Each JarvisCore node on the same machine must use a different `JC_SWIM_PORT`. The ZMQ data port is set automatically to `JC_SWIM_PORT + 1000`. If you run two nodes locally, assign ports `7946` and `7947` respectively.

!!! note "Redis is required for multi-node P2P"
    Cross-node workflow state (mailboxes, step claiming) is coordinated through Redis. P2P messaging itself uses ZMQ directly, but without Redis, distributed workflow execution will not function correctly.

---

## The PeerClient API

Every agent that participates in the mesh receives a `PeerClient` instance as `self.peers`. This object is the complete interface for peer discovery and messaging.

`PeerClient` is injected by the Mesh during `setup()`. You never construct it directly.

### Discovery

#### get_peer

Returns the first agent registered with the given role, or `None` if no such agent exists.

```python
analyst = self.peers.get_peer(role="analyst")
if analyst:
    print(f"Found analyst: {analyst.agent_id} on node {analyst.node_id}")
```

#### discover

Returns a list of agents matching a role or capability filter. Supports multiple selection strategies for load distribution.

```python
# All analysts, in round-robin order
analysts = self.peers.discover(role="analyst", strategy="round_robin")

# Any agent with the "data-analysis" capability, selected randomly
workers = self.peers.discover(capability="data-analysis", strategy="random")
```

| Strategy | Behaviour |
|---|---|
| `"first"` | Returns agents in discovery order. This is the default. |
| `"random"` | Shuffles the result list randomly on each call. |
| `"round_robin"` | Rotates through agents on each call, distributing load evenly. |
| `"least_recent"` | Returns agents sorted by last-used timestamp, oldest first. |

#### discover_one

Convenience method that returns the single best match from `discover()`, or `None` if no match is found.

```python
worker = self.peers.discover_one(capability="processing", strategy="least_recent")
if worker:
    response = await self.peers.request(worker.agent_id, {"task": "..."})
```

#### list_roles

Returns the set of all roles currently available in the mesh, excluding the calling agent's own role.

```python
available = self.peers.list_roles()
# ["analyst", "reporter", "scout"]
```

#### list_peers

Returns detailed information about all peers, including both local and remote agents.

```python
peers = self.peers.list_peers()
for peer in peers:
    print(f"{peer['role']} ({peer['location']}): {peer['capabilities']}")
```

Each entry in the returned list contains: `role`, `agent_id`, `capabilities`, `description`, `status`, and `location` (`"local"` or `"remote"`).

#### registry

Read-only property that returns the full agent registry as a dict mapping `agent_id` to `PeerInfo`.

```python
for agent_id, info in self.peers.registry.items():
    print(f"{agent_id}: {info.role}")
```

#### Identity properties

```python
self.peers.my_id    # This agent's unique agent_id
self.peers.my_role  # This agent's role string
```

### Messaging

#### notify

Sends a fire-and-forget message to a peer. The call returns immediately after the message is dispatched; there is no acknowledgement.

```python
await self.peers.notify(
    "analyst",
    {"event": "scouting_complete", "data": {"findings": summary}},
    context={"mission_id": "abc123", "priority": "high"},
)
```

| Parameter | Type | Description |
|---|---|---|
| `target` | `str` | Target agent role or `agent_id` |
| `message` | `dict` | JSON-serialisable message payload |
| `context` | `dict` | Optional metadata propagated with the message |

Returns `True` if the message was sent successfully, `False` if the target could not be resolved.

#### request

Sends a request and blocks until a response is received or the timeout elapses.

```python
response = await self.peers.request(
    "scout",
    {"need": "clarification", "entity": "Entity_X"},
    timeout=30,
    context={"mission_id": "abc123"},
)

if response:
    print(f"Scout responded: {response}")
```

| Parameter | Type | Default | Description |
|---|---|---|---|
| `target` | `str` | — | Target agent role or `agent_id` |
| `message` | `dict` | — | Request payload |
| `timeout` | `float` | `30.0` | Seconds to wait for a response |
| `context` | `dict` | `None` | Optional metadata |

Returns the response dict, or `None` if the timeout was reached or the send failed.

#### respond

Sends a reply to an incoming request. Context is propagated automatically from the original request unless you override it.

```python
message = await self.peers.receive()
if message and message.is_request:
    result = await process(message.data)
    await self.peers.respond(message, {"result": result})
```

#### broadcast

Sends a notification to every peer currently in the mesh.

```python
count = await self.peers.broadcast(
    {"event": "status_update", "status": "completed"},
    context={"mission_id": "abc123"},
)
print(f"Notified {count} peers")
```

Returns the number of peers that were successfully notified.

#### receive

Reads the next message from this agent's incoming message queue.

```python
# Non-blocking: returns None immediately if no message is waiting
message = await self.peers.receive(timeout=0)

# Blocking with timeout: waits up to 5 seconds
message = await self.peers.receive(timeout=5)

if message:
    print(f"From {message.sender}: {message.data}")
    if message.is_request:
        await self.peers.respond(message, {"status": "acknowledged"})
```

### Async Request Pattern

For workflows that need to send multiple requests in parallel and collect responses later, use the async request pattern.

```python
# Fire off multiple requests without blocking
request_ids = []
for analyst in analysts:
    req_id = await self.peers.ask_async(analyst.agent_id, {"question": "Analyse sector X"})
    request_ids.append(req_id)

# Do other work while responses arrive
await process_other_tasks()

# Collect responses
results = []
for req_id in request_ids:
    response = await self.peers.check_inbox(req_id, timeout=10)
    if response:
        results.append(response)
```

#### ask_async

Sends a request without blocking. Returns a `request_id` immediately.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `target` | `str` | — | Target agent role or `agent_id` |
| `message` | `dict` | — | Request payload |
| `timeout` | `float` | `120.0` | Time to keep the request active before expiry |
| `context` | `dict` | `None` | Optional metadata |

Raises `ValueError` if the target cannot be resolved or the send fails.

#### check_inbox

Checks for a response to a previously sent async request.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `request_id` | `str` | — | ID returned by `ask_async()` |
| `timeout` | `float` | `0.0` | Seconds to wait if no response is available yet |
| `remove` | `bool` | `True` | Remove the entry from the inbox after reading |

Returns the response dict if available, or `None`.

---

## Load Balancing

The `round_robin` and `least_recent` strategies in `discover()` implement stateful load balancing within the calling agent's process. State is not shared across agents or nodes.

Call `record_peer_usage(peer_id)` after communicating with a peer to keep the `least_recent` strategy accurate:

```python
worker = self.peers.discover_one(capability="processing", strategy="least_recent")
if worker:
    response = await self.peers.request(worker.agent_id, {"task": "..."})
    if response:
        self.peers.record_peer_usage(worker.agent_id)
```

---

## SWIM Gossip Protocol

When `P2P_ENABLED=true`, the `SWIMManager` runs a background gossip loop on the configured `JC_SWIM_PORT`. SWIM provides:

- **Membership**: each node maintains a view of all other live nodes in the cluster.
- **Failure detection**: nodes that stop responding are marked as suspect and eventually evicted from the membership list.
- **Agent advertisement**: when a node joins the cluster, it broadcasts its local agent registry so that remote agents become discoverable via `discover()` and `get_peer()`.

The SWIM protocol does not require a leader or centralised registry. Any node can discover any other node as long as at least one seed node address is shared.

---

## Practical Example: CustomAgent with Peer Communication

```python title="agents/scout.py"
from jarviscore import CustomAgent

class ScoutAgent(CustomAgent):
    name = "Scout"
    role = "scout"
    capabilities = ["reconnaissance", "data-gathering"]

    async def run(self, task: str, context: dict) -> dict:
        # Perform primary data gathering
        raw_data = await self.gather_data(task)

        # Notify the analyst that data is ready
        await self.peers.notify(
            "analyst",
            {"event": "data_ready", "data": raw_data},
            context={"mission_id": context.get("mission_id")},
        )

        # Request a quality check from another scout if available
        peer_scout = self.peers.discover_one(role="scout", strategy="random")
        if peer_scout:
            validation = await self.peers.request(
                peer_scout.agent_id,
                {"action": "validate", "data": raw_data},
                timeout=15,
            )
            if validation and not validation.get("valid"):
                raw_data = await self.re_gather(task, validation["feedback"])

        return {"status": "complete", "data": raw_data}
```
