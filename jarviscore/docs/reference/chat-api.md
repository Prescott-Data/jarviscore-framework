---
icon: material/chat-outline
---

# Chat API Reference

The chat router is a FastAPI router factory that wires three HTTP endpoints onto your application. Import it from `jarviscore.integrations.chat`.

```python
from jarviscore.integrations.chat import create_chat_router

app.include_router(
    create_chat_router(kernel=my_kernel),
    prefix="/api/v1",
)
```

The `kernel` argument must be a `jarviscore.kernel.kernel.Kernel` instance. The router is stateless — the same Kernel can be shared across multiple router mounts or agent instances.

---

## create_chat_router

```python
def create_chat_router(
    kernel,
    prefix: str = "",
    tags: Optional[List[str]] = None,
) -> APIRouter
```

| Parameter | Type | Default | Description |
|---|---|---|---|
| `kernel` | `Kernel` | required | The Kernel that executes chat messages |
| `prefix` | `str` | `""` | Additional route prefix appended inside the router (independent of `app.include_router(prefix=...)`) |
| `tags` | `List[str]` | `["chat"]` | FastAPI OpenAPI tag list |

Returns an `APIRouter` ready for `app.include_router()`.

Raises `ImportError` if `fastapi` is not installed.

---

## <span class="jc-http-post">POST</span> /chat

Send a natural language message to the agent and receive a synchronous answer.

The Kernel routes the task automatically based on its content: research and factual questions go to `ResearcherSubAgent`, coding tasks to `CoderSubAgent`, browser navigation to `BrowserSubAgent`, and communication tasks to `CommunicatorSubAgent`.

Trace events stream in real time on `GET /chat/stream/{workflow_id}` while the POST is in flight.

### Request body

```json
{
  "message": "string",
  "workflow_id": "string | null",
  "agent_id": "string | null",
  "system_prompt": "string | null",
  "context": "object | null"
}
```

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `message` | `str` | Yes | — | Natural language task or question |
| `workflow_id` | `str` | No | auto-generated (`chat_<12hex>`) | Workflow identifier; supply your own to correlate with the SSE stream |
| `agent_id` | `str` | No | `"chat"` | Agent identity passed to the Kernel |
| `system_prompt` | `str` | No | `""` | System prompt prepended to the Kernel call |
| `context` | `dict` | No | `{}` | Arbitrary key-value context forwarded to the Kernel. `workflow_id` and `step_id` are merged in automatically |

### Response body

HTTP 200 on success. HTTP 500 with `{"error": "...", "workflow_id": "..."}` on Kernel exception.

```json
{
  "workflow_id": "string",
  "step_id": "string",
  "status": "string",
  "answer": "string",
  "sources": [],
  "tokens": {},
  "elapsed_ms": 0.0
}
```

| Field | Type | Description |
|---|---|---|
| `workflow_id` | `str` | Workflow identifier (use this to open the SSE stream) |
| `step_id` | `str` | Step identifier, formatted as `step_<unix_timestamp>` |
| `status` | `str` | `"success"`, `"failure"`, or `"yield"` — taken directly from `output.status` |
| `answer` | `str` | Final answer text. Taken from `output.summary`, falling back to `str(output.payload)[:2000]` |
| `sources` | `List[dict]` | Citation sources extracted from researcher output. Each entry is `{"title": "...", "url": "...", "source": "..."}`. Capped at 10 entries |
| `tokens` | `dict` | Token usage from `output.metadata["tokens"]`. Keys depend on the provider |
| `elapsed_ms` | `float` | Wall-clock milliseconds from request receipt to response |

---

## <span class="jc-http-get">GET</span> /chat/stream/{workflow_id}

Server-Sent Events stream for a running or completed workflow. Returns `Content-Type: text/event-stream`.

Response headers set by the router:

```
Cache-Control: no-cache
X-Accel-Buffering: no
Connection: keep-alive
```

### Behaviour

On connect, the stream replays all buffered events from Redis for the given `workflow_id` (catch-up for clients that connect after the POST has started). It then subscribes to the Redis PubSub channel `trace_events:{workflow_id}` and forwards new events until a `step_complete` event is received or the client disconnects.

The stream closes automatically after 300 seconds of inactivity. A heartbeat comment (`: heartbeat`) is sent every iteration to keep proxies from closing the connection.

When Redis is not configured, the stream returns a single error event and closes.

### Event format

Each SSE message data field is a JSON object:

```json
{
  "workflow_id": "string",
  "step_id": "string",
  "type": "string",
  "timestamp": "string",
  "data": {}
}
```

| `type` value | Description |
|---|---|
| `thinking` | Internal reasoning token from the Kernel's OODA loop. `data.thought` contains the text |
| `tool_start` | A sub-agent tool call has begun. `data` contains the tool name and arguments |
| `tool_result` | A tool call has completed. `data` contains the result |
| `llm_request` | An LLM call is being made |
| `llm_response` | An LLM call has returned |
| `step_complete` | The workflow step is done. `data.summary` contains the final answer. The client should close the stream after receiving this event |
| `timeout` | The 300-second stream timeout was reached |
| `error` | An internal error occurred. `data.message` contains the description |

### Client example

```javascript
const es = new EventSource(`/api/v1/chat/stream/${workflowId}`)
es.onmessage = (e) => {
    const event = JSON.parse(e.data)
    if (event.type === 'thinking')      renderThought(event.data.thought)
    if (event.type === 'tool_start')    renderToolCall(event.data)
    if (event.type === 'tool_result')   renderToolResult(event.data)
    if (event.type === 'step_complete') {
        renderAnswer(event.data.summary)
        es.close()
    }
}
```

---

## <span class="jc-http-get">GET</span> /chat/history/{workflow_id}/{step_id}

Returns the full buffered trace event log for a completed workflow step. Useful for replaying a conversation trace in a UI without maintaining an SSE connection.

### Path parameters

| Parameter | Description |
|---|---|
| `workflow_id` | Workflow identifier from the POST /chat response |
| `step_id` | Step identifier from the POST /chat response |

### Response body

HTTP 200 on success. HTTP 500 with `{"error": "..."}` if the trace cannot be read.

```json
{
  "events": []
}
```

`events` is a list of trace event objects in the same format as the SSE stream messages.

Requires Redis to be configured. Events are read from the trace files in the `traces/` directory.

---

## Further Reading

- [Chat Endpoint guide](../guides/chat.md) — integration walkthrough with full examples
- [Configuration Reference](configuration.md) — `REDIS_URL` required for live SSE streaming
- [Model Routing](../concepts/model-routing.md) — how the Kernel classifies and routes chat messages
