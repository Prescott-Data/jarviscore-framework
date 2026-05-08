"""
JarvisCore Chat Integration — HTTP chat endpoint with SSE trace streaming.

Provides two FastAPI endpoints:

  POST /chat
    Accept a natural language message, dispatch through the Kernel,
    stream live traces via Redis PubSub → SSE, return final answer.

  GET /chat/stream/{workflow_id}
    Server-Sent Events stream. Replays buffered events then subscribes
    to the Redis PubSub channel for the workflow, forwarding each event
    as an SSE message until a "step_complete" event is seen or the
    client disconnects.

  GET /chat/history/{workflow_id}/{step_id}
    Retrieve the full event log for a past workflow step.

Usage (mount on your FastAPI app):

    from fastapi import FastAPI
    from jarviscore.integrations.chat import create_chat_router

    app = FastAPI()
    app.include_router(
        create_chat_router(kernel=my_kernel),
        prefix="/api/v1",
    )

Wire thinking traces in the UI:

    const eventSource = new EventSource(`/api/v1/chat/stream/${workflowId}`)
    eventSource.onmessage = (e) => {
        const event = JSON.parse(e.data)
        if (event.type === 'thinking')    renderThought(event.data.thought)
        if (event.type === 'tool_start')  renderToolCall(event.data)
        if (event.type === 'tool_result') renderToolResult(event.data)
        if (event.type === 'step_complete') {
            renderAnswer(event.data.summary)
            eventSource.close()
        }
    }
"""
import asyncio
import json
import logging
import time
import uuid
from typing import Any, AsyncGenerator, Dict, List, Optional

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Router factory
# ─────────────────────────────────────────────────────────────────────────────

def create_chat_router(
    kernel,
    prefix: str = "",
    tags: Optional[List[str]] = None,
):
    """
    Create a FastAPI router with chat + SSE trace endpoints.

    Args:
        kernel: Kernel instance (jarviscore.kernel.kernel.Kernel)
        prefix:  Optional route prefix (added in addition to app.include_router prefix)
        tags:    FastAPI tag list for OpenAPI docs

    Returns:
        APIRouter ready for app.include_router()
    """
    try:
        from fastapi import APIRouter, Request
        from fastapi.responses import JSONResponse, StreamingResponse
        from pydantic import BaseModel
    except ImportError as exc:
        raise ImportError(
            "FastAPI is required for the chat router. "
            "Install with: pip install fastapi[all]"
        ) from exc

    router = APIRouter(prefix=prefix, tags=tags or ["chat"])

    # ──────────────────────────────────────────────────────────────────────
    # Request/Response models
    # ──────────────────────────────────────────────────────────────────────

    class ChatRequest(BaseModel):
        message: str
        workflow_id: Optional[str] = None
        agent_id: Optional[str] = "chat"
        system_prompt: Optional[str] = ""
        context: Optional[Dict[str, Any]] = None

    class ChatResponse(BaseModel):
        workflow_id: str
        step_id: str
        status: str       # "success" | "failure" | "yield"
        answer: str
        sources: List[Dict[str, Any]] = []
        tokens: Dict[str, int] = {}
        elapsed_ms: float = 0.0

    # ──────────────────────────────────────────────────────────────────────
    # POST /chat
    # ──────────────────────────────────────────────────────────────────────

    @router.post("/chat", response_model=ChatResponse)
    async def chat(req: ChatRequest):
        """
        Send a message to the agent and get an answer.

        The agent routes automatically:
          - Questions / research tasks   → ResearcherSubAgent (uses web search)
          - Coding tasks                 → CoderSubAgent
          - Browser / navigation tasks   → BrowserSubAgent
          - Communication tasks          → CommunicatorSubAgent

        Trace events stream live on GET /chat/stream/{workflow_id}.
        """
        t0 = time.monotonic()

        workflow_id = req.workflow_id or f"chat_{uuid.uuid4().hex[:12]}"
        step_id = f"step_{int(time.time())}"

        context: Dict[str, Any] = dict(req.context or {})
        context["workflow_id"] = workflow_id
        context["step_id"] = step_id

        logger.info("[chat] workflow=%s message=%s", workflow_id, req.message[:80])

        try:
            output = await kernel.execute(
                task=req.message,
                system_prompt=req.system_prompt or "",
                context=context,
                agent_id=req.agent_id or "chat",
            )
        except Exception as exc:
            logger.error("[chat] Kernel execute failed: %s", exc, exc_info=True)
            return JSONResponse(
                status_code=500,
                content={"error": "Internal server error", "workflow_id": workflow_id},
            )

        elapsed_ms = round((time.monotonic() - t0) * 1000, 1)

        # Extract sources from researcher output (list of {title, url} dicts)
        sources = _extract_sources(output)

        answer = output.summary or (
            str(output.payload)[:2000] if output.payload else "No answer"
        )

        return ChatResponse(
            workflow_id=workflow_id,
            step_id=step_id,
            status=output.status,
            answer=answer,
            sources=sources,
            tokens=(output.metadata or {}).get("tokens", {}),
            elapsed_ms=elapsed_ms,
        )

    # ──────────────────────────────────────────────────────────────────────
    # GET /chat/stream/{workflow_id} — SSE
    # ──────────────────────────────────────────────────────────────────────

    @router.get("/chat/stream/{workflow_id}")
    async def chat_stream(workflow_id: str, request: Request):
        """
        Server-Sent Events stream for a chat workflow.

        Replays all buffered events first (catch-up), then subscribes to
        the Redis PubSub channel and forwards new events until:
          - A "step_complete" event is received, OR
          - The client disconnects

        Event format (each SSE message data field):
            {
                "workflow_id": "...",
                "step_id": "...",
                "type": "thinking" | "tool_start" | "tool_result" |
                        "llm_request" | "llm_response" | "step_complete",
                "timestamp": "2026-04-23T10:00:00Z",
                "data": { ... }
            }

        Client usage:
            const es = new EventSource(`/chat/stream/${workflowId}`)
            es.onmessage = e => console.log(JSON.parse(e.data))
        """
        return StreamingResponse(
            _sse_generator(workflow_id, request),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",           # nginx: disable proxy buffering
                "Connection": "keep-alive",
            },
        )

    # ──────────────────────────────────────────────────────────────────────
    # GET /chat/history/{workflow_id}/{step_id}
    # ──────────────────────────────────────────────────────────────────────

    @router.get("/chat/history/{workflow_id}/{step_id}")
    async def chat_history(workflow_id: str, step_id: str):
        """
        Return the full buffered trace event log for a past step.

        Useful for replaying a conversation's trace in a UI without
        maintaining an SSE connection.
        """
        from jarviscore.kernel.tracing import TraceManager
        try:
            tm = TraceManager.__new__(TraceManager)
            tm.workflow_id = workflow_id
            tm.step_id = step_id
            import os
            tm.trace_dir = "traces"
            tm.trace_file = os.path.join("traces", f"{workflow_id}_{step_id}.jsonl")
            tm.redis_client = TraceManager._init_redis()
            return {"events": tm.get_history()}
        except Exception as exc:
            logger.error("[chat] chat_history failed: %s", exc, exc_info=True)
            return JSONResponse(status_code=500, content={"error": "Internal server error"})

    return router


# ─────────────────────────────────────────────────────────────────────────────
# SSE generator
# ─────────────────────────────────────────────────────────────────────────────

async def _sse_generator(
    workflow_id: str,
    request,
    timeout_s: float = 300.0,
) -> AsyncGenerator[str, None]:
    """
    Async generator that yields SSE-formatted trace events.

    Strategy:
      1. Replay buffered events from Redis List (catch-up for late connections)
      2. Subscribe to Redis PubSub channel for real-time events
      3. Yield each event as `data: <json>\\n\\n`
      4. Exit on step_complete, client disconnect, or timeout
    """
    redis_client = _get_redis()

    # ── Step 1: Catch-up replay ──
    if redis_client:
        try:
            key = f"traces:{workflow_id}:*"
            # Scan for matching keys (step_id is part of key but we stream all steps)
            buffered_events: List[str] = []
            for k in redis_client.scan_iter(f"traces:{workflow_id}:*"):
                buffered_events.extend(redis_client.lrange(k, 0, -1))
            for raw in buffered_events:
                yield f"data: {raw}\n\n"
        except Exception as exc:
            logger.debug("SSE catch-up failed: %s", exc)

    # ── Step 2: Live PubSub ──
    if not redis_client:
        # No Redis — yield a single no-redis message and close
        yield f"data: {json.dumps({'type': 'error', 'data': {'message': 'Redis not configured — live trace unavailable'}})}\n\n"
        return

    channel = f"trace_events:{workflow_id}"
    deadline = asyncio.get_event_loop().time() + timeout_s

    try:
        pubsub = redis_client.pubsub()
        pubsub.subscribe(channel)

        while True:
            # Client disconnect check
            if await request.is_disconnected():
                break

            # Timeout
            if asyncio.get_event_loop().time() > deadline:
                yield f"data: {json.dumps({'type': 'timeout', 'data': {'message': 'Stream timeout'}})}\n\n"
                break

            # Non-blocking get from pubsub
            try:
                message = await asyncio.to_thread(pubsub.get_message, ignore_subscribe_messages=True, timeout=0.5)
            except Exception:
                message = None

            if message and message.get("type") == "message":
                raw = message.get("data", "")
                if raw:
                    yield f"data: {raw}\n\n"
                    # Close stream on step_complete
                    try:
                        evt = json.loads(raw)
                        if evt.get("type") == "step_complete":
                            break
                    except json.JSONDecodeError:
                        pass

            # Heartbeat keep-alive comment every 15 seconds
            yield ": heartbeat\n\n"
            await asyncio.sleep(0.1)

    except asyncio.CancelledError:
        pass
    except Exception as exc:
        logger.error("SSE generator error: %s", exc, exc_info=True)
        yield f"data: {json.dumps({'type': 'error', 'data': {'message': 'Stream error'}})}\n\n"
    finally:
        try:
            pubsub.unsubscribe(channel)
            pubsub.close()
        except Exception:
            pass


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

_redis_singleton = None


def _get_redis():
    """Lazy singleton Redis client for SSE (reuses TraceManager pattern)."""
    global _redis_singleton
    if _redis_singleton is not None:
        return _redis_singleton
    import os
    redis_url = os.environ.get("REDIS_URL")
    if not redis_url:
        return None
    try:
        import redis as _redis
        _redis_singleton = _redis.Redis.from_url(redis_url, decode_responses=True)
        _redis_singleton.ping()
        return _redis_singleton
    except Exception as exc:
        logger.debug("Chat SSE: Redis unavailable (%s)", exc)
        return None


def _extract_sources(output) -> List[Dict[str, Any]]:
    """
    Extract citation sources from a researcher AgentOutput.

    Sources are emitted by the researcher's _tool_note_finding calls
    and stored in the payload or trajectory.
    """
    sources: List[Dict[str, Any]] = []
    try:
        payload = output.payload
        if isinstance(payload, dict):
            # Researcher returns {findings, sources, ...}
            raw_sources = payload.get("sources") or []
            for s in raw_sources:
                if isinstance(s, str) and s.startswith("http"):
                    sources.append({"url": s})
                elif isinstance(s, dict):
                    sources.append(s)
        # Also scan trajectory for web_search results
        trajectory = getattr(output, "trajectory", []) or []
        for step in trajectory:
            result = step.get("result", "")
            if isinstance(result, str) and "url" in result:
                try:
                    r = json.loads(result)
                    if "results" in r:
                        for item in r["results"][:3]:
                            if item.get("url") and not any(
                                s.get("url") == item["url"] for s in sources
                            ):
                                sources.append(
                                    {
                                        "title": item.get("title", ""),
                                        "url": item.get("url", ""),
                                        "source": item.get("source", ""),
                                    }
                                )
                except Exception:
                    pass
    except Exception:
        pass
    return sources[:10]  # cap at 10 citations
