---
icon: material/api
---

# FastAPI Integration

JarvisCore integrates with FastAPI through `JarvisLifespan` — a lifespan context manager that starts the Mesh on app startup, runs agent loops as background tasks, and shuts everything down cleanly when the server stops.

The integration reduces ~100 lines of boilerplate to 3.

---

## Prerequisites

```bash
pip install fastapi uvicorn
pip install "jarviscore-framework"
```

---

## Minimal Integration

```python title="app.py"
from fastapi import FastAPI
from jarviscore.integrations import JarvisLifespan
from agents.processor import ProcessorAgent

agent = ProcessorAgent()
app = FastAPI(lifespan=JarvisLifespan(agent, bind_port=7950))
```

That is the entire integration. `JarvisLifespan` handles:

1. Creating and starting the Mesh on startup
2. Running the agent's `run()` loop as a background task
3. Injecting mesh and agent references into `app.state`
4. Graceful shutdown: signalling `run()` loops to exit, cancelling background tasks, calling `agent.teardown()`

---

## JarvisLifespan Parameters

```python
JarvisLifespan(
    agents,               # Single agent instance or list of agents
    bind_host="127.0.0.1",
    bind_port=7946,
    seed_nodes="",        # Comma-separated, e.g. "10.0.0.1:7946,10.0.0.2:7946"
    node_name="",
)
```

| Parameter | Default | Description |
|---|---|---|
| `agents` | Required | Agent instance or list of agent instances |
| `bind_host` | `"127.0.0.1"` | P2P bind address |
| `bind_port` | `7946` | SWIM gossip port |
| `seed_nodes` | `""` | Seed nodes for joining an existing cluster |

For P2P between nodes, set `P2P_ENABLED=true` in your environment or pass `config={"p2p_enabled": True}` to `JarvisLifespan`. Redis and other infrastructure is detected automatically from environment variables.

---

## Accessing Agents in Route Handlers

`JarvisLifespan` injects two objects into `app.state`:

| Key | Type | Description |
|---|---|---|
| `app.state.jarvis_mesh` | `Mesh` | The active Mesh instance |
| `app.state.jarvis_agents` | `dict[role, agent]` | Dict of role → agent instance |

```python
from fastapi import Request

@app.get("/health")
async def health(request: Request):
    mesh = request.app.state.jarvis_mesh
    diagnostics = mesh.get_diagnostics()
    return {"status": "healthy", "agents": diagnostics.get("agents", [])}

@app.post("/chat")
async def chat(request: Request):
    body = await request.json()
    agent = request.app.state.jarvis_agents.get("assistant")
    result = await agent.chat(body["message"])
    return result
```

---

## Multiple Agents

Pass a list to run multiple agents in the same process:

```python
from jarviscore.integrations import JarvisLifespan
from agents.assistant import AssistantAgent
from agents.analyst import AnalystAgent
from agents.researcher import ResearcherAgent

agents = [AssistantAgent(), AnalystAgent(), ResearcherAgent()]
app = FastAPI(lifespan=JarvisLifespan(agents, bind_port=7980))
```

Each agent gets its own background task and is accessible via `app.state.jarvis_agents["analyst"]` etc.

---

## Convenience Function: create_jarvis_app

For simple single-agent deployments, `create_jarvis_app` creates the FastAPI app with the lifespan pre-configured:

```python
from jarviscore.integrations.fastapi import create_jarvis_app
from agents.processor import ProcessorAgent

app = create_jarvis_app(
    ProcessorAgent(),
    mode="p2p",
    bind_port=7950,
    title="Processor API",
    description="API powered by JarvisCore",
    version="1.0.0",
)

@app.get("/health")
async def health():
    return {"status": "ok"}

# Run with: uvicorn app:app --host 0.0.0.0 --port 8000
```

---

## Handling Peer Requests

A `CustomAgent` running inside FastAPI handles peer requests via `on_peer_request`:

```python title="agents/analyst.py"
from jarviscore import CustomAgent

class AnalystAgent(CustomAgent):
    role = "analyst"
    capabilities = ["data-analysis", "statistics"]

    async def on_peer_request(self, msg):
        """Called by the Mesh when another agent sends a request to this agent."""
        question = msg.data.get("question", "")
        analysis = await self.run_analysis(question)
        return {"analysis": analysis, "confidence": 0.9}

    async def run(self, task: str = "", context: dict = None) -> dict:
        """Receive loop — keeps the agent alive to handle peer messages."""
        while not self.shutdown_requested:
            message = await self.peers.receive(timeout=5)
            if not message:
                continue
            if message.is_request:
                result = await self.on_peer_request(message)
                await self.peers.respond(message, result)
```

---

## Joining an Existing Mesh (Cloud Deployment)

A standalone agent running in a separate process or container can join an existing mesh:

```python title="standalone_scout.py"
import asyncio
from agents.scout import ScoutAgent

async def main():
    scout = ScoutAgent()
    await scout.join_mesh(seed_nodes="192.168.1.10:7946")

    # Discover peers after joining
    await asyncio.sleep(2)
    peers = scout.peers.list_peers()
    print(f"Discovered {len(peers)} peers")

    # Run the agent's event loop
    try:
        await scout.run()
    finally:
        await scout.leave_mesh()

asyncio.run(main())
```

```bash
# Terminal 1 — start the FastAPI server with embedded agents
uvicorn app:app --host 0.0.0.0 --port 8000

# Terminal 2 — join the mesh from a separate process
python standalone_scout.py
```

---

## Full Production Example

```python title="app.py"
import uuid
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from jarviscore.integrations import JarvisLifespan
from agents.assistant import AssistantAgent
from agents.analyst import AnalystAgent
from agents.researcher import ResearcherAgent

agents = [AssistantAgent(), AnalystAgent(), ResearcherAgent()]

app = FastAPI(
    title="Autonomous Agent API",
    lifespan=JarvisLifespan(agents, bind_port=7980),
)

@app.get("/health")
async def health(request: Request):
    mesh = getattr(request.app.state, "jarvis_mesh", None)
    if not mesh:
        return JSONResponse(status_code=503, content={"status": "unhealthy"})
    d = mesh.get_diagnostics()
    return {"status": "healthy", "agent_count": d.get("agent_count", 0)}

@app.get("/agents")
async def list_agents(request: Request):
    result = {}
    for role, agent in request.app.state.jarvis_agents.items():
        result[role] = {
            "peers": [p["role"] for p in agent.peers.list_peers()],
        }
    return result

@app.post("/chat")
async def chat(request: Request):
    body = await request.json()
    request_id = str(uuid.uuid4())
    assistant = request.app.state.jarvis_agents.get("assistant")
    if not assistant:
        return JSONResponse(status_code=503, content={"error": "Assistant unavailable"})
    result = await assistant.chat(body["message"], request_id=request_id)
    return {"request_id": request_id, **result}
```

```bash
uvicorn app:app --host 0.0.0.0 --port 8000 --workers 1
```

> [!WARNING]
> Use `--workers 1` with `uvicorn`. The Mesh and P2P coordinator are process-local. Multiple workers will start separate, uncoordinated Mesh instances. For horizontal scaling, run one agent process per machine and connect them via the P2P mesh using `seed_nodes`.
