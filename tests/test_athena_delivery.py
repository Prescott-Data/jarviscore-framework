"""The Athena tier ships what it is given, or says what it lost (#128).

The tier was fail-soft to the point of being unfalsifiable: writes were awaited
on the reasoning path, failures were swallowed and logged at debug, and an
initialisation error disabled memory for the life of the process. A configured
tier storing nothing looked exactly like a working one.

The first test here is the one that matters most. Every event write without an
explicit timestamp was silently dropped before it reached the network, from
v1.4.0 through v1.7.0, and nothing in the suite noticed.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from jarviscore.memory.athena_client import (
    AthenaClient,
    AthenaWriteRejected,
    ROLE_AGENT,
    TYPE_THOUGHT,
)
from jarviscore.memory.athena_memory import AthenaMemory
from jarviscore.memory.delivery import IDEMPOTENCY_KEY, CircuitBreaker, Outbox
from jarviscore.memory.unified import UnifiedMemory


def _response(payload=None, status_code=200):
    response = MagicMock()
    response.status_code = status_code
    response.raise_for_status = MagicMock()
    response.json.return_value = payload if payload is not None else {"success": True}
    return response


def _client(http=None):
    client = AthenaClient(base_url="http://athena.test")
    client._client = http or AsyncMock()
    return client


# ──────────────────────────────────────────────────────────────────
# The write actually leaves the process
# ──────────────────────────────────────────────────────────────────

class TestEventIsPosted:

    @pytest.mark.asyncio
    async def test_event_without_a_timestamp_is_posted(self):
        """Regression: the POST sat inside `if serialized_timestamp:`.

        AthenaMemory never passes a timestamp, so from v1.4.0 to v1.7.0 every
        thought, action and observation was assembled and then never sent. The
        call returned False, nobody checks the return, and the tier was empty.
        """
        http = AsyncMock()
        http.post.return_value = _response()
        client = _client(http)

        await client.write_event("s1", ROLE_AGENT, TYPE_THOUGHT, "a thought")

        http.post.assert_awaited_once()
        assert http.post.await_args.args[0] == "/api/v1/sessions/s1/events"
        assert http.post.await_args.kwargs["json"]["content"] == "a thought"
        assert "timestamp" not in http.post.await_args.kwargs["json"]

    @pytest.mark.asyncio
    async def test_event_with_a_timestamp_is_still_posted(self):
        http = AsyncMock()
        http.post.return_value = _response()

        await _client(http).write_event(
            "s1", ROLE_AGENT, TYPE_THOUGHT, "c", timestamp="2026-09-06T00:00:00Z",
        )

        assert http.post.await_args.kwargs["json"]["timestamp"] == "2026-09-06T00:00:00Z"

    @pytest.mark.asyncio
    async def test_payload_is_attached_without_a_timestamp(self):
        http = AsyncMock()
        http.post.return_value = _response()

        await _client(http).write_event(
            "s1", ROLE_AGENT, TYPE_THOUGHT, "c", payload=b"\x00\x01", mime_type="application/octet-stream",
        )

        assert http.post.await_args.kwargs["json"]["mime_type"] == "application/octet-stream"


class TestWriteEventRaises:
    """The outbox cannot count or retry a failure it is never told about."""

    @pytest.mark.asyncio
    async def test_transport_failure_raises(self):
        http = AsyncMock()
        http.post.side_effect = RuntimeError("connection refused")

        with pytest.raises(RuntimeError, match="connection refused"):
            await _client(http).write_event("s1", ROLE_AGENT, TYPE_THOUGHT, "c")

    @pytest.mark.asyncio
    async def test_declined_write_raises(self):
        http = AsyncMock()
        http.post.return_value = _response({"success": False, "error": "full"})

        with pytest.raises(AthenaWriteRejected):
            await _client(http).write_event("s1", ROLE_AGENT, TYPE_THOUGHT, "c")

    @pytest.mark.asyncio
    async def test_store_event_keeps_its_boolean_contract(self):
        http = AsyncMock()
        http.post.side_effect = RuntimeError("down")

        assert await _client(http).store_event("s1", ROLE_AGENT, TYPE_THOUGHT, "c") is False

    @pytest.mark.asyncio
    async def test_missing_mime_type_is_a_caller_error_not_a_delivery_failure(self):
        with pytest.raises(ValueError):
            await _client().store_event(
                "s1", ROLE_AGENT, TYPE_THOUGHT, "c", payload=b"x",
            )


# ──────────────────────────────────────────────────────────────────
# Outbox
# ──────────────────────────────────────────────────────────────────

class TestOutbox:

    @pytest.mark.asyncio
    async def test_submit_returns_before_the_write_lands(self):
        started = asyncio.Event()
        release = asyncio.Event()

        async def slow(**kwargs):
            started.set()
            await release.wait()

        outbox = Outbox()
        outbox.submit(slow, content="c")          # returns immediately
        await asyncio.wait_for(started.wait(), timeout=1)
        assert outbox.stats.shipped == 0
        release.set()
        assert await outbox.flush(timeout=1)
        assert outbox.stats.shipped == 1

    @pytest.mark.asyncio
    async def test_writes_ship_in_order(self):
        seen = []

        async def record(**kwargs):
            seen.append(kwargs["content"])

        outbox = Outbox()
        for i in range(20):
            outbox.submit(record, content=i)
        await outbox.flush(timeout=2)

        assert seen == list(range(20))

    @pytest.mark.asyncio
    async def test_a_failed_write_is_counted_not_swallowed(self):
        async def broken(**kwargs):
            raise RuntimeError("athena down")

        outbox = Outbox()
        outbox.submit(broken, content="c")
        await outbox.flush(timeout=2)

        assert outbox.stats.dropped == 1
        assert outbox.stats.shipped == 0
        assert "athena down" in outbox.stats.last_error

    @pytest.mark.asyncio
    async def test_no_retry_without_deduplication(self):
        """A replayed write invents history. That is worse than a counted gap."""
        attempts = []

        async def broken(**kwargs):
            attempts.append(1)
            raise RuntimeError("boom")

        outbox = Outbox(max_attempts=4, deduplicates=False)
        outbox.submit(broken, content="c")
        await outbox.flush(timeout=2)

        assert len(attempts) == 1
        assert outbox.stats.retried == 0

    @pytest.mark.asyncio
    async def test_retries_when_the_receiver_deduplicates(self):
        attempts = []

        async def flaky(**kwargs):
            attempts.append(kwargs["metadata"][IDEMPOTENCY_KEY])
            if len(attempts) < 3:
                raise RuntimeError("boom")

        outbox = Outbox(max_attempts=4, deduplicates=True, base_delay=0.001)
        outbox.submit(flaky, content="c", metadata={"agent_id": "a"})
        await outbox.flush(timeout=2)

        assert len(attempts) == 3
        assert len(set(attempts)) == 1          # same key every attempt
        assert outbox.stats.shipped == 1

    @pytest.mark.asyncio
    async def test_idempotency_key_is_absent_when_not_deduplicating(self):
        seen = {}

        async def record(**kwargs):
            seen.update(kwargs.get("metadata") or {})

        outbox = Outbox(deduplicates=False)
        outbox.submit(record, content="c", metadata={"agent_id": "a"})
        await outbox.flush(timeout=2)

        assert IDEMPOTENCY_KEY not in seen

    @pytest.mark.asyncio
    async def test_overflow_drops_the_oldest_and_counts_it(self):
        release = asyncio.Event()
        shipped = []

        async def blocked(**kwargs):
            await release.wait()
            shipped.append(kwargs["content"])

        outbox = Outbox(max_queue=3)
        for i in range(6):
            outbox.submit(blocked, content=i)

        assert outbox.stats.dropped_overflow == 3
        release.set()
        await outbox.flush(timeout=2)
        assert shipped[-1] == 5              # the newest survived

    @pytest.mark.asyncio
    async def test_stats_report_the_queue_depth(self):
        release = asyncio.Event()

        async def blocked(**kwargs):
            await release.wait()

        outbox = Outbox()
        for i in range(4):
            outbox.submit(blocked, content=i)
        assert outbox.stats.depth == 4
        release.set()
        await outbox.flush(timeout=2)
        assert outbox.stats.depth == 0

    @pytest.mark.asyncio
    async def test_close_flushes_what_is_queued(self):
        shipped = []

        async def record(**kwargs):
            shipped.append(kwargs["content"])

        outbox = Outbox()
        for i in range(5):
            outbox.submit(record, content=i)
        assert await outbox.close(timeout=2)

        assert shipped == list(range(5))


class TestCircuitBreaker:

    def test_opens_after_the_threshold(self):
        breaker = CircuitBreaker(threshold=2, cooldown=60)
        assert breaker.allows()
        breaker.record_failure()
        assert breaker.state == "closed"
        breaker.record_failure()
        assert breaker.state == "open"
        assert not breaker.allows()

    def test_probes_once_after_the_cooldown(self):
        breaker = CircuitBreaker(threshold=1, cooldown=0)
        breaker.record_failure()
        assert breaker.allows()
        assert breaker.state == "probing"

    def test_a_success_closes_it_again(self):
        breaker = CircuitBreaker(threshold=1, cooldown=0)
        breaker.record_failure()
        breaker.allows()
        breaker.record_success()
        assert breaker.state == "closed"

    def test_success_resets_the_failure_run(self):
        breaker = CircuitBreaker(threshold=3, cooldown=60)
        breaker.record_failure()
        breaker.record_failure()
        breaker.record_success()
        breaker.record_failure()
        breaker.record_failure()
        assert breaker.state == "closed"


# ──────────────────────────────────────────────────────────────────
# The tier
# ──────────────────────────────────────────────────────────────────

class TestAthenaMemoryDelivery:

    def _memory(self, http, **outbox_kwargs):
        return AthenaMemory(
            agent_id="a", session_id="s1", client=_client(http),
            outbox=Outbox(**outbox_kwargs),
        )

    @pytest.mark.asyncio
    async def test_recorded_events_reach_athena(self):
        http = AsyncMock()
        http.post.return_value = _response()
        memory = self._memory(http)

        await memory.record_thought("thinking")
        await memory.record_action("acting")
        await memory.flush(timeout=2)

        assert http.post.await_count == 2
        assert memory.delivery_stats["shipped"] == 2

    @pytest.mark.asyncio
    async def test_a_slow_athena_does_not_hold_up_the_turn(self):
        release = asyncio.Event()
        http = AsyncMock()

        async def slow(*args, **kwargs):
            await release.wait()
            return _response()

        http.post.side_effect = slow
        memory = self._memory(http)

        await asyncio.wait_for(memory.record_thought("thinking"), timeout=0.5)

        release.set()
        await memory.flush(timeout=2)

    @pytest.mark.asyncio
    async def test_an_outage_is_visible_in_the_counters(self):
        http = AsyncMock()
        http.post.side_effect = RuntimeError("athena down")
        memory = self._memory(http)

        await memory.record_thought("thinking")
        await memory.flush(timeout=2)

        stats = memory.delivery_stats
        assert stats["shipped"] == 0
        assert stats["dropped"] == 1
        assert "athena down" in stats["last_error"]

    @pytest.mark.asyncio
    async def test_domain_events_go_through_the_outbox_too(self):
        http = AsyncMock()
        http.post.return_value = _response()
        memory = self._memory(http)

        await memory.on_task_completed("t1", "Ship the thing", "done")
        await memory.flush(timeout=2)

        assert memory.delivery_stats["shipped"] == 1
        assert "Ship the thing" in http.post.await_args.kwargs["json"]["content"]


# ──────────────────────────────────────────────────────────────────
# Sessions and recovery
# ──────────────────────────────────────────────────────────────────

class TestStaleSession:

    @pytest.mark.asyncio
    async def test_a_deleted_session_is_recreated(self):
        http = AsyncMock()
        http.get.return_value = _response(status_code=404)
        http.post.return_value = _response({"session_id": "fresh"})
        client = _client(http)
        redis_store = MagicMock()
        redis_store._redis.get.return_value = "stale"

        session_id = await client.get_or_create_session("a", redis_store=redis_store)

        assert session_id == "fresh"
        redis_store._redis.set.assert_called()

    @pytest.mark.asyncio
    async def test_a_live_session_is_reused(self):
        http = AsyncMock()
        http.get.return_value = _response({"id": "live"}, status_code=200)
        client = _client(http)
        redis_store = MagicMock()
        redis_store._redis.get.return_value = "live"

        assert await client.get_or_create_session("a", redis_store=redis_store) == "live"
        http.post.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_unreachable_athena_does_not_discard_the_session(self):
        """A network blink is not evidence the session was deleted."""
        http = AsyncMock()
        http.get.side_effect = RuntimeError("connection refused")
        client = _client(http)
        redis_store = MagicMock()
        redis_store._redis.get.return_value = "keep-me"

        assert await client.get_or_create_session("a", redis_store=redis_store) == "keep-me"


class TestTierRecovery:

    @pytest.mark.asyncio
    async def test_a_failed_start_does_not_disable_memory_for_the_process(self):
        """Athena restarting used to cost the whole run's memory."""
        attempts = {"n": 0}

        class Flaky:
            async def get_or_create_session(self, *args, **kwargs):
                attempts["n"] += 1
                if attempts["n"] == 1:
                    raise RuntimeError("athena starting up")
                return "s1"

        memory = UnifiedMemory(
            workflow_id="w", step_id="s", agent_id="a", athena_client=Flaky(),
        )

        assert await memory._get_athena_memory() is None
        assert memory._athena_client is not None      # not nulled out
        assert await memory._get_athena_memory() is not None
        assert attempts["n"] == 2

    @pytest.mark.asyncio
    async def test_stats_are_none_when_the_tier_is_not_active(self):
        memory = UnifiedMemory(workflow_id="w", step_id="s", agent_id="a")
        assert memory.athena_delivery_stats is None
        assert await memory.close() is True
