"""
Tests for the asyncio cross-loop Future fix in PeerClient._deliver_message().

The bug (seen in v0.3.2 production logs):
  The SWIM ZMQ router runs in a dedicated thread with its own event loop.
  When a PEER_RESPONSE arrives, _deliver_message() is called from the
  SWIM thread's loop and calls future.set_result() on a Future that was
  created in the main event loop.
  Result: RuntimeError: Future is bound to a different event loop
  → request() blocks silently until timeout.

The fix:
  Use future.get_loop().call_soon_threadsafe(future.set_result, data)
  when the caller's running loop differs from the future's own loop.
"""
import asyncio
import threading
import pytest

from jarviscore.p2p.peer_client import PeerClient
from jarviscore.p2p.messages import IncomingMessage, MessageType


def _make_client() -> PeerClient:
    """Minimal PeerClient with no real coordinator needed."""
    return PeerClient(
        coordinator=None,
        agent_id="test-agent-abc",
        agent_role="tester",
        agent_registry={},
        node_id="",
    )


# ── helpers ──────────────────────────────────────────────────────────────────

def _response_message(correlation_id: str, data: dict) -> IncomingMessage:
    return IncomingMessage(
        sender="peer-agent",
        sender_node="",
        type=MessageType.RESPONSE,
        data=data,
        correlation_id=correlation_id,
    )


def _run_deliver_in_new_thread_loop(client: PeerClient, msg: IncomingMessage):
    """
    Simulate the SWIM thread: spin up a brand-new event loop in a thread
    and call _deliver_message() from inside it — exactly what the ZMQ
    router does when it receives a PEER_RESPONSE.
    """
    result = {}

    def thread_target():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(client._deliver_message(msg))
            result["ok"] = True
        except Exception as e:
            result["error"] = e
        finally:
            loop.close()

    t = threading.Thread(target=thread_target, daemon=True)
    t.start()
    t.join(timeout=5)
    return result


# ── tests ─────────────────────────────────────────────────────────────────────

class TestDeliverMessageSameLoop:
    """Baseline: same-loop delivery still works."""

    @pytest.mark.asyncio
    async def test_same_loop_resolves_future(self):
        client = _make_client()
        cid = "req-same-loop-001"

        future = asyncio.get_running_loop().create_future()
        client._pending_requests[cid] = future

        msg = _response_message(cid, {"result": "hello"})
        await client._deliver_message(msg)

        assert future.done()
        assert future.result() == {"result": "hello"}

    @pytest.mark.asyncio
    async def test_same_loop_does_not_raise(self):
        client = _make_client()
        cid = "req-same-loop-002"

        future = asyncio.get_running_loop().create_future()
        client._pending_requests[cid] = future

        msg = _response_message(cid, {"value": 42})
        # Must not raise RuntimeError
        await client._deliver_message(msg)
        assert future.result() == {"value": 42}


class TestDeliverMessageCrossLoop:
    """
    Core regression test: _deliver_message called from a different
    event loop (SWIM thread) must resolve the Future without error.
    """

    @pytest.mark.asyncio
    async def test_cross_loop_resolves_future(self):
        """
        Future created in main loop, _deliver_message called from a
        thread with its own loop — should resolve cleanly.
        """
        client = _make_client()
        cid = "req-cross-loop-001"

        main_loop = asyncio.get_running_loop()
        future = main_loop.create_future()
        client._pending_requests[cid] = future

        msg = _response_message(cid, {"answer": "cross-loop works"})

        # Fire _deliver_message from a separate thread loop
        thread_result = await main_loop.run_in_executor(
            None,
            _run_deliver_in_new_thread_loop,
            client,
            msg,
        )

        # Thread must not have errored
        assert "error" not in thread_result, f"Thread raised: {thread_result.get('error')}"
        assert thread_result.get("ok") is True

        # Give call_soon_threadsafe a moment to schedule set_result
        await asyncio.sleep(0.1)

        assert future.done(), "Future was not resolved after cross-loop _deliver_message"
        assert future.result() == {"answer": "cross-loop works"}

    @pytest.mark.asyncio
    async def test_cross_loop_correct_data_delivered(self):
        """Response payload is intact after crossing loop boundary."""
        client = _make_client()
        cid = "req-cross-loop-002"

        main_loop = asyncio.get_running_loop()
        future = main_loop.create_future()
        client._pending_requests[cid] = future

        payload = {"status": "ok", "items": [1, 2, 3], "meta": {"count": 3}}
        msg = _response_message(cid, payload)

        await main_loop.run_in_executor(
            None, _run_deliver_in_new_thread_loop, client, msg
        )
        await asyncio.sleep(0.1)

        assert future.done()
        assert future.result() == payload

    @pytest.mark.asyncio
    async def test_cross_loop_unknown_correlation_id_is_ignored(self):
        """Unknown correlation_id must not crash when called cross-loop."""
        client = _make_client()

        msg = _response_message("req-unknown-999", {"data": "orphan"})

        thread_result = await asyncio.get_running_loop().run_in_executor(
            None, _run_deliver_in_new_thread_loop, client, msg
        )

        assert "error" not in thread_result, f"Thread raised: {thread_result.get('error')}"

    @pytest.mark.asyncio
    async def test_cross_loop_already_done_future_is_ignored(self):
        """Already-resolved Future must not raise InvalidStateError cross-loop."""
        client = _make_client()
        cid = "req-cross-loop-done"

        main_loop = asyncio.get_running_loop()
        future = main_loop.create_future()
        future.set_result({"already": "set"})  # pre-resolve
        client._pending_requests[cid] = future

        msg = _response_message(cid, {"second": "set"})

        thread_result = await main_loop.run_in_executor(
            None, _run_deliver_in_new_thread_loop, client, msg
        )

        assert "error" not in thread_result, f"Thread raised: {thread_result.get('error')}"
        # Original result unchanged
        assert future.result() == {"already": "set"}


class TestGetRunningLoopInRequest:
    """Verify request() and ask_async() use get_running_loop(), not get_event_loop()."""

    @pytest.mark.asyncio
    async def test_request_future_bound_to_running_loop(self):
        """
        Future created by request() must be bound to the currently
        running loop, not a stale loop from get_event_loop().
        """
        import inspect
        import ast
        import textwrap

        # Read the source of request() and check for get_running_loop
        src = inspect.getsource(PeerClient.request)
        assert "get_running_loop" in src, (
            "request() must use asyncio.get_running_loop() to create the Future, "
            "not asyncio.get_event_loop() — see cross-loop fix"
        )
        assert "get_event_loop" not in src, (
            "request() must not use asyncio.get_event_loop() for Future creation"
        )

    @pytest.mark.asyncio
    async def test_ask_async_future_bound_to_running_loop(self):
        """ask_async() must also use get_running_loop()."""
        import inspect

        src = inspect.getsource(PeerClient.ask_async)
        assert "get_running_loop" in src, (
            "ask_async() must use asyncio.get_running_loop() to create the Future"
        )
        assert "get_event_loop" not in src, (
            "ask_async() must not use asyncio.get_event_loop() for Future creation"
        )

    @pytest.mark.asyncio
    async def test_deliver_message_uses_call_soon_threadsafe(self):
        """_deliver_message() must use call_soon_threadsafe for cross-loop delivery."""
        import inspect

        src = inspect.getsource(PeerClient._deliver_message)
        assert "call_soon_threadsafe" in src, (
            "_deliver_message() must use call_soon_threadsafe for cross-loop "
            "Future resolution — direct set_result() raises RuntimeError from SWIM thread"
        )
