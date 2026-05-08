---
icon: material/chat-processing
---

# Chat Endpoint

JarvisCore agents are not just task executors — they can function as conversational interfaces. The `create_chat_router` factory produces a FastAPI router with a `POST /chat` endpoint and a real-time Server-Sent Events stream, letting you build a chat UI backed by any JarvisCore `AutoAgent` in minutes.

---

## How It Works

```
User message (HTTP POST)
        ↓
   POST /chat  →  kernel.execute(message)
        ↓
   Kernel routes automatically:
     - Questions / research  → ResearcherSubAgent
     - Coding tasks          → CoderSubAgent
     - Browser/navigation    → BrowserSubAgent
        ↓
   TraceManager publishes events to Redis PubSub
        ↓
   GET /chat/stream/{workflow_id}  ←  UI EventSource
     ├── thinking events (OODA loop thoughts)
     ├── tool_start / tool_result (live tool calls)
     └── step_complete (final answer + sources)
```

The user sees the agent thinking in real time through the SSE stream, then receives the final answer.

---

## Mounting the Router

```python title="main.py"
from contextlib import asynccontextmanager
from fastapi import FastAPI
from jarviscore import Mesh
from jarviscore.integrations import create_chat_router
from agents import ResearcherAgent

mesh = Mesh()
kernel = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global kernel
    mesh.add(ResearcherAgent)
    await mesh.start()
    agent = mesh.get_agent("researcher")
    if agent is None or agent._kernel is None:
        raise ValueError("ResearcherAgent did not initialise correctly")
    kernel = agent._kernel
    yield
    await mesh.stop()

app = FastAPI(lifespan=lifespan)

# Mount chat endpoints at /api/v1
app.include_router(
    create_chat_router(kernel=kernel),
    prefix="/api/v1",
)
```

> [!NOTE]
> `create_chat_router` requires FastAPI. Install with `pip install fastapi[all]`.

---

## Endpoints

### `POST /api/v1/chat`

Send a message, get a response.

**Request body:**

| Field | Type | Required | Description |
|---|---|---|---|
| `message` | `str` | Yes | The user's message in natural language |
| `workflow_id` | `str` | No | Reuse an existing workflow for continuity (multi-turn). Auto-generated if omitted. |
| `agent_id` | `str` | No | Agent identifier (default `"chat"`) |
| `system_prompt` | `str` | No | Override or extend the agent's base system prompt for this request |
| `context` | `dict` | No | Additional context key-value pairs injected into the agent's context window |

**Response:**

| Field | Type | Description |
|---|---|---|
| `workflow_id` | `str` | ID to use for the SSE stream and history replay |
| `step_id` | `str` | Step identifier within the workflow |
| `status` | `str` | `"success"`, `"failure"`, or `"yield"` |
| `answer` | `str` | The agent's final response |
| `sources` | `list` | Citations from ResearcherSubAgent web results (URLs, titles) |
| `tokens` | `dict` | Token usage breakdown |
| `elapsed_ms` | `float` | Wall-clock execution time |

```bash
curl -X POST http://localhost:8000/api/v1/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "What is the current state of LLM inference hardware?"}'
```

```json
{
  "workflow_id": "chat-a3f2b1",
  "step_id": "step-1",
  "status": "success",
  "answer": "As of 2026, the LLM inference hardware landscape is dominated by...",
  "sources": [
    {"title": "NVIDIA H200 Datasheet", "url": "https://..."},
    {"title": "Groq LPU Architecture", "url": "https://..."}
  ],
  "tokens": {"input": 842, "output": 341},
  "elapsed_ms": 4230.1
}
```

---

### `GET /api/v1/chat/stream/{workflow_id}`

Real-time SSE stream of trace events for a workflow. Connect before or after the `POST /chat` call — missed events are replayed from Redis on connection.

```javascript title="Browser SSE client"
const workflowId = "chat-a3f2b1";
const es = new EventSource(`/api/v1/chat/stream/${workflowId}`);

es.onmessage = (e) => {
    const event = JSON.parse(e.data);

    switch (event.type) {
        case "thinking":
            appendThought(event.data.thought);         // truncated to 2000 chars
            break;
        case "tool_start":
            showToolCall(event.data.tool, event.data.args);
            break;
        case "tool_result":
            showToolResult(event.data.tool, event.data.result, event.data.success);
            break;
        case "step_complete":
            renderAnswer(event.data.summary);          // sources come from POST response
            es.close();
            break;
        case "error":
            showError(event.data.message);
            es.close();
            break;
    }
};
```

**Event types emitted:**

| `event.type` | `event.data` keys | Description |
|---|---|---|
| `thinking` | `thought: str` | Kernel OODA loop reasoning text (truncated at 2000 chars) |
| `tool_start` | `tool: str, args: dict` | Tool invocation about to run |
| `tool_result` | `tool: str, result: str, success: bool, error: str\|null` | Tool result returned |
| `llm_request` | `system_preview: str, user_preview: str` | LLM call dispatched |
| `llm_response` | `content_preview: str, latency_ms: float` | LLM response received |
| `step_complete` | `success: bool, summary: str` | Execution finished — read `answer` and `sources` from the POST response |
| `error` | `message: str` | Something went wrong |
| `timeout` | `message: str` | Stream timed out (default: 300 seconds) |

The stream closes automatically when `step_complete` is emitted or the client disconnects. Sources (citations) are returned in the `POST /chat` response body, not in the SSE stream.

> [!NOTE]
> SSE streaming requires Redis (`REDIS_URL` set). Without Redis, the endpoint returns a single `error` event explaining that live trace is unavailable, and the `POST /chat` response still works normally.

---

### `GET /api/v1/chat/history/{workflow_id}/{step_id}`

Retrieve the full buffered trace event log for a past step. Useful for replaying a conversation in a UI, for debugging, or for building a "show me the agent's thinking" feature.

```bash
curl http://localhost:8000/api/v1/chat/history/chat-a3f2b1/step-1
```

```json
{
  "events": [
    {"type": "thinking", "data": {"thought": "The user wants to know about..."}},
    {"type": "tool_start", "data": {"tool": "web_search", "input": {"query": "..."}}}
  ]
}
```

---

## Multi-Turn Conversations

Pass the same `workflow_id` across multiple `POST /chat` calls to give the Kernel a shared memory anchor. Each call generates its own `step_id` (a timestamp-based key), so the episodic ledger entries are separate. What persists across calls is the Athena and long-term memory context — the Kernel rehydrates that on each request using the same `workflow_id` as the lookup key.

In practice this means the agent can refer to what it learned in an earlier turn when Athena is configured. Without Athena, each call is stateless regardless of `workflow_id`.

```python
import httpx

client = httpx.Client(base_url="http://localhost:8000")

# Turn 1
r1 = client.post("/api/v1/chat", json={"message": "Tell me about transformer attention."})
workflow_id = r1.json()["workflow_id"]

# Turn 2 — same workflow_id; Kernel rehydrates shared memory context
r2 = client.post("/api/v1/chat", json={
    "message": "How does that compare to state space models?",
    "workflow_id": workflow_id,
})
```

> [!IMPORTANT]
> Multi-turn context continuity requires Redis and Athena configured. Without Redis, the Kernel starts fresh on each request.

---

## Adding a System Prompt Per Request

The `system_prompt` field in the request is passed directly to `kernel.execute()` as the system prompt for the Kernel's subagent dispatch. It replaces the subagent's default system prompt for that request. The AutoAgent class's own `system_prompt` attribute is not affected — this field is a per-request override, not an extension of it.

The `context` dict is injected into the agent's task context alongside the message:

```python
httpx.post("/api/v1/chat", json={
    "message": "Summarise our Q1 pipeline status.",
    "system_prompt": "You are advising the executive team. Be concise and direct. No jargon.",
    "context": {"company": "Prescott Data", "quarter": "Q1 2026"},
})
```

---

## Further Reading

- [FastAPI Integration](fastapi.md) — Full FastAPI setup with `JarvisLifespan` and `mesh.workflow()`
- [Observability](observability.md) — How trace events are stored and what metrics are emitted
- [AutoAgent Guide](autoagent.md) — The Kernel OODA loop that drives the chat endpoint
