from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from jarviscore.memory import athena_client
from jarviscore.memory.athena_client import AthenaClient
from jarviscore.memory import get_athena_client


def _response(payload):
    response = MagicMock()
    response.raise_for_status = MagicMock()
    response.json.return_value = payload
    return response


@pytest.mark.asyncio
async def test_get_context_preserves_athena_v015_response_fields():
    client = AthenaClient("http://athena.test")
    http = AsyncMock()
    http.get.return_value = _response(
        {
            "stmEvents": [{"role": "user", "content": "recent"}],
            "relevantPages": [{"id": "chain-1", "summary": "prior decision"}],
            "segments": [{"id": "segment-1", "content": "evidence"}],
            "userPersona": {"userId": "owner"},
            "ltpm": {"status": "ready"},
        }
    )
    client._client = http

    context = await client.get_context("session-1", limit=7)

    http.get.assert_awaited_once_with(
        "/api/v1/sessions/session-1/context", params={"limit": 7}
    )
    assert context == {
        "stm_events": [{"role": "user", "content": "recent"}],
        "mtm_chains": [{"id": "chain-1", "summary": "prior decision"}],
        "segments": [{"id": "segment-1", "content": "evidence"}],
        "user_persona": {"userId": "owner"},
        "ltpm": {"status": "ready"},
        "heat_score": 0.0,
    }


@pytest.mark.asyncio
async def test_get_context_retains_legacy_aliases():
    client = AthenaClient("http://athena.test")
    http = AsyncMock()
    http.get.return_value = _response(
        {
            "events": [{"content": "legacy event"}],
            "chains": [{"summary": "legacy chain"}],
            "heatScore": 0.4,
        }
    )
    client._client = http

    context = await client.get_context("session-1")

    assert context["stm_events"] == [{"content": "legacy event"}]
    assert context["mtm_chains"] == [{"summary": "legacy chain"}]
    assert context["heat_score"] == 0.4


@pytest.mark.asyncio
async def test_get_context_failure_returns_complete_empty_shape():
    client = AthenaClient("http://athena.test")
    http = AsyncMock()
    http.get.side_effect = RuntimeError("offline")
    client._client = http

    context = await client.get_context("session-1")

    assert context == {
        "stm_events": [],
        "mtm_chains": [],
        "segments": [],
        "user_persona": None,
        "ltpm": None,
        "heat_score": 0.0,
    }


@pytest.mark.asyncio
async def test_get_context_sends_query_and_segment_options():
    client = AthenaClient("http://athena.test")
    http = AsyncMock()
    http.get.return_value = _response({})
    client._client = http

    await client.get_context(
        "session-1", limit=8, query="prior decisions", include_segments=True
    )

    http.get.assert_awaited_once_with(
        "/api/v1/sessions/session-1/context",
        params={
            "limit": 8,
            "query": "prior decisions",
            "includeSegments": True,
        },
    )


@pytest.mark.asyncio
async def test_store_event_with_id_serializes_payload_and_timestamp():
    client = AthenaClient("http://athena.test", tenant_id="tenant-1")
    http = AsyncMock()
    http.post.return_value = _response(
        {"success": True, "eventId": "68b5f26cc7e80f7a577792a1"}
    )
    client._client = http

    event_id = await client.store_event_with_id(
        "session-1",
        "agent",
        "observation",
        "structured result",
        {"workflow_id": "wf-1"},
        timestamp=datetime(2026, 9, 1, 12, 30, tzinfo=timezone.utc),
        payload=b'{"result": 42}',
        mime_type="application/json",
    )

    assert event_id == "68b5f26cc7e80f7a577792a1"
    request = http.post.await_args.kwargs["json"]
    assert request["timestamp"] == "2026-09-01T12:30:00Z"
    assert request["payload"] == "eyJyZXN1bHQiOiA0Mn0="
    assert request["mime_type"] == "application/json"
    assert request["metadata"] == {
        "tenant_id": "tenant-1",
        "origin_service": "jarviscore",
        "workflow_id": "wf-1",
    }


@pytest.mark.asyncio
async def test_store_event_keeps_boolean_compatibility():
    client = AthenaClient("http://athena.test")
    http = AsyncMock()
    http.post.return_value = _response({"success": True, "eventId": "event-1"})
    client._client = http

    assert await client.store_event(
        "session-1", "agent", "observation", "result"
    ) is True


@pytest.mark.asyncio
async def test_store_event_requires_mime_type_for_payload():
    client = AthenaClient("http://athena.test")
    with pytest.raises(ValueError, match="mime_type"):
        await client.store_event(
            "session-1", "agent", "observation", "result", payload=b"data"
        )


@pytest.mark.asyncio
async def test_search_memory_sends_metadata_filter():
    client = AthenaClient("http://athena.test")
    http = AsyncMock()
    http.post.return_value = _response({"results": [{"sourceId": "chain-1"}]})
    client._client = http

    results = await client.search_memory(
        "session-1",
        "gold decisions",
        limit=3,
        similarity_threshold=0.8,
        metadata_filter={"origin_service": "billy"},
    )

    assert results == [{"sourceId": "chain-1"}]
    assert http.post.await_args.kwargs["json"]["filter"] == {
        "origin_service": "billy"
    }


@pytest.mark.asyncio
async def test_session_interaction_and_analysis_methods():
    client = AthenaClient("http://athena.test")
    http = AsyncMock()
    http.get.side_effect = [
        _response({"session": {"sessionId": "session-1"}}),
        _response({"topics": [{"topic": "markets"}]}),
        _response({"segments": [{"id": "segment-1"}]}),
    ]
    http.post.side_effect = [
        _response({"success": True}),
        _response({"success": True}),
    ]
    http.delete.return_value = _response({"success": True})
    client._client = http

    assert await client.get_session("session-1") == {"sessionId": "session-1"}
    assert await client.store_interaction(
        "session-1", "question", "answer", {"channel": "telegram"}
    ) is True
    assert await client.analyze_topics("session-1") == [{"topic": "markets"}]
    assert await client.get_segments("session-1", limit=4) == [{"id": "segment-1"}]
    assert await client.trigger_graph_analytics() is True
    assert await client.delete_session("session-1") is True
    assert http.get.await_args_list[-1].kwargs["params"] == {"limit": 4}


@pytest.mark.asyncio
async def test_heat_metrics_unwraps_canonical_response():
    client = AthenaClient("http://athena.test")
    http = AsyncMock()
    http.get.return_value = _response(
        {"heatMetrics": {"overallHeat": 0.7, "totalInteractions": 12}}
    )
    client._client = http

    metrics = await client.get_heat_metrics("session-1")

    assert metrics == {"overallHeat": 0.7, "totalInteractions": 12}


def test_from_env_loads_auth_tenant_and_timeout(monkeypatch):
    monkeypatch.setenv("ATHENA_URL", "https://athena.example")
    monkeypatch.setenv("ATHENA_TENANT_ID", "tenant-1")
    monkeypatch.setenv("ATHENA_HTTP_TIMEOUT", "4.5")
    monkeypatch.setenv("ATHENA_API_KEY", "api-secret")
    monkeypatch.setenv("ATHENA_JWT_TOKEN", "jwt-secret")

    client = AthenaClient.from_env()

    assert client is not None
    assert client._tenant_id == "tenant-1"
    assert client._timeout == 4.5
    assert client._api_key == "api-secret"
    assert client._jwt_token == "jwt-secret"


@pytest.mark.asyncio
async def test_http_recreates_only_a_boolean_closed_client():
    client = AthenaClient("http://athena.test", api_key="api-secret")
    closed = MagicMock()
    closed.is_closed = True
    client._client = closed
    replacement = MagicMock()

    with patch("httpx.AsyncClient", return_value=replacement) as constructor:
        assert await client._http() is replacement

    assert constructor.call_args.kwargs["headers"]["X-API-Key"] == "api-secret"


@pytest.mark.asyncio
async def test_create_session_sends_distinct_user_and_agent_identity():
    client = AthenaClient("http://athena.test", tenant_id="tenant-1")
    http = AsyncMock()
    http.post.return_value = _response({"sessionId": "session-1"})
    client._client = http

    session_id = await client.create_session(
        "billy-conversation", {"channel": "telegram"}, user_id="owner"
    )

    assert session_id == "session-1"
    assert http.post.await_args.kwargs["json"] == {
        "tenant_id": "tenant-1",
        "user_id": "owner",
        "agent_id": "billy-conversation",
        "metadata": {
            "agent_id": "billy-conversation",
            "origin_service": "jarviscore",
            "channel": "telegram",
        },
    }


@pytest.mark.asyncio
async def test_create_session_defaults_user_to_agent_for_compatibility():
    client = AthenaClient("http://athena.test")
    http = AsyncMock()
    http.post.return_value = _response({"sessionId": "session-1"})
    client._client = http

    await client.create_session("researcher")

    request = http.post.await_args.kwargs["json"]
    assert request["user_id"] == "researcher"
    assert request["agent_id"] == "researcher"


@pytest.mark.asyncio
async def test_session_cache_key_isolates_tenant_user_and_agent():
    client = AthenaClient("http://athena.test", tenant_id="tenant-1")
    redis = MagicMock()
    redis._redis.get.return_value = None
    redis._redis.set = MagicMock()
    client.create_session = AsyncMock(return_value="session-1")

    session_id = await client.get_or_create_session(
        "analyst", redis_store=redis, user_id="owner"
    )

    assert session_id == "session-1"
    assert redis._redis.get.call_args_list == [
        call("athena_session:scoped:tenant-1:owner:analyst"),
    ]
    redis._redis.set.assert_called_once_with(
        "athena_session:scoped:tenant-1:owner:analyst", "session-1", ex=30 * 86400
    )
    client.create_session.assert_awaited_once_with(
        "analyst", None, user_id="owner", tenant_id="tenant-1"
    )


@pytest.mark.asyncio
async def test_session_cache_promotes_legacy_agent_key():
    client = AthenaClient("http://athena.test", tenant_id="tenant-1")
    redis = MagicMock()
    redis._redis.get.side_effect = [None, "legacy-session"]
    redis._redis.set = MagicMock()

    session_id = await client.get_or_create_session("analyst", redis_store=redis)

    assert session_id == "legacy-session"
    assert redis._redis.get.call_args_list == [
        call("athena_session:tenant-1:analyst:analyst"),
        call("athena_session:analyst"),
    ]
    redis._redis.set.assert_called_once_with(
        "athena_session:tenant-1:analyst:analyst",
        "legacy-session",
        ex=30 * 86400,
    )


@pytest.mark.asyncio
async def test_scoped_session_refuses_the_unscoped_legacy_session():
    """The legacy key belongs to no scope, so no scope may inherit it."""
    client = AthenaClient("http://athena.test", tenant_id="tenant-1")
    cache = {"athena_session:analyst": "legacy-session"}
    redis = MagicMock()
    redis._redis.get.side_effect = cache.get
    redis._redis.set = MagicMock()
    client.create_session = AsyncMock(return_value="session-for-matter-a")

    session_id = await client.get_or_create_session(
        "analyst", redis_store=redis, user_id="matter-a"
    )

    assert session_id == "session-for-matter-a"
    assert redis._redis.get.call_args_list == [
        call("athena_session:scoped:tenant-1:matter-a:analyst"),
    ]


@pytest.mark.asyncio
async def test_scoped_session_never_resolves_to_a_default_or_pre_scoping_key():
    """A scope equal to the agent id, or a scope containing the separator,
    must not land on a key the unscoped path (or older code) wrote."""
    client = AthenaClient("http://athena.test", tenant_id="tenant-1")
    cache = {
        "athena_session:tenant-1:analyst:analyst": "default-session",
        "athena_session:tenant-1:a:b:analyst": "pre-scoping-session",
    }
    redis = MagicMock()
    redis._redis.get.side_effect = cache.get
    redis._redis.set = MagicMock()
    client.create_session = AsyncMock(side_effect=["scoped-1", "scoped-2"])

    same_as_agent = await client.get_or_create_session(
        "analyst", redis_store=redis, user_id="analyst"
    )
    with_separator = await client.get_or_create_session(
        "analyst", redis_store=redis, user_id="a:b"
    )

    assert (same_as_agent, with_separator) == ("scoped-1", "scoped-2")
    assert redis._redis.get.call_args_list == [
        call("athena_session:scoped:tenant-1:analyst:analyst"),
        call("athena_session:scoped:tenant-1:a%3Ab:analyst"),
    ]


def test_public_factory_uses_environment_auth_fallback(monkeypatch):
    monkeypatch.setenv("ATHENA_API_KEY", "api-secret")
    monkeypatch.setenv("ATHENA_JWT_TOKEN", "jwt-secret")
    settings = SimpleNamespace(
        athena_url="https://athena.example",
        athena_tenant_id="tenant-1",
        athena_http_timeout=3.0,
        athena_api_key=None,
        athena_jwt_token=None,
    )

    client = get_athena_client(settings)

    assert client is not None
    assert client._api_key == "api-secret"
    assert client._jwt_token == "jwt-secret"


@pytest.mark.asyncio
async def test_a_session_can_be_in_another_tenant_than_the_clients(monkeypatch):
    """A room's memory is in the room's tenant, whatever the deployment's default."""
    client = AthenaClient("http://athena:8080", tenant_id="default")
    sent = {}

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {"sessionId": "s-acme"}

    class Http:
        async def post(self, path, json):
            sent.update(json)
            return Response()

    async def http():
        return Http()

    monkeypatch.setattr(client, "_http", http)
    assert await client.create_session("room", user_id="acme/launch", tenant_id="acme") == "s-acme"
    assert (sent["tenant_id"], sent["user_id"], sent["agent_id"]) == ("acme", "acme/launch", "room")


@pytest.mark.asyncio
async def test_erase_memory_posts_the_scope_and_returns_counts():
    client = AthenaClient("http://athena.test")
    http = AsyncMock()
    response = _response({"success": True, "eventsDeleted": 9})
    response.status_code = 200
    http.post.return_value = response
    client._client = http

    assert await client.erase_memory("acme", "acme/launch") == {"success": True, "eventsDeleted": 9}
    assert http.post.await_args.args[0] == "/api/v1/memory/erase"
    assert http.post.await_args.kwargs["json"] == {"tenant_id": "acme", "user_id": "acme/launch", "agent_id": ""}


@pytest.mark.asyncio
async def test_erase_memory_raises_when_athena_did_not_erase():
    client = AthenaClient("http://athena.test")
    http = AsyncMock()
    response = _response({})
    response.status_code = 500
    response.text = "failed to erase memory (safe to retry)"
    http.post.return_value = response
    client._client = http

    with pytest.raises(RuntimeError, match="did not erase"):
        await client.erase_memory("acme", "u")
    with pytest.raises(ValueError):
        await client.erase_memory("")


class TestAnAthenaThatDoesNotAnswerIsLeftAlone:
    """Every call to an unreachable Athena waited out its limit, again for every turn of a
    task. After a few failures in a row the address fails at once for a while."""

    DEAD = "http://127.0.0.1:9"  # nothing listens: refused at once

    @pytest.fixture(autouse=True)
    def fresh_breakers(self):
        athena_client._BREAKERS.clear()
        yield
        athena_client._BREAKERS.clear()

    @pytest.mark.asyncio
    async def test_after_three_failures_a_call_fails_without_being_made(self):
        import httpx

        client = AthenaClient(self.DEAD, tenant_id="t")
        http = await client._http()
        for _ in range(3):
            with pytest.raises(httpx.ConnectError):
                await http.get("/api/v1/health")
        assert athena_client._breaker(self.DEAD).state == "open"
        with pytest.raises(httpx.ConnectError, match="left alone"):
            await http.get("/api/v1/health")
        await client.close()

    @pytest.mark.asyncio
    async def test_the_breaker_is_the_address_s_not_one_client_s(self):
        """A client is made for each piece of work: a breaker of its own would start
        closed every time."""
        first = AthenaClient(self.DEAD, tenant_id="t")
        for _ in range(3):
            assert await first.create_session("agent") is None
        await first.close()

        second = AthenaClient(self.DEAD, tenant_id="t")
        http = await second._http()
        import httpx

        with pytest.raises(httpx.ConnectError, match="left alone"):
            await http.get("/api/v1/health")
        await second.close()

    @pytest.mark.asyncio
    async def test_one_call_is_let_through_after_the_cooldown_and_an_answer_closes_it(self):
        breaker = athena_client._breaker(self.DEAD)
        for _ in range(3):
            breaker.record_failure()
        assert not breaker.allows()
        breaker.cooldown = 0.0
        assert breaker.allows() and breaker.state == "probing"
        breaker.record_success()
        assert breaker.state == "closed"

    def test_reaching_athena_has_a_shorter_limit_than_waiting_for_its_answer(self):
        client = AthenaClient("http://athena.example", tenant_id="t", timeout=10.0)
        assert client._connect_timeout == 3.0
        assert AthenaClient("http://athena.example", timeout=2.0)._connect_timeout == 2.0


class _Server:
    """A local stand-in for Athena that answers as told: at once, late, 502, or never."""

    def __init__(self):
        self.mode, self.delay, self.requests = "ok", 0.0, 0

    async def __aenter__(self):
        import asyncio

        async def handle(reader, writer):
            await reader.readuntil(b"\r\n\r\n")
            self.requests += 1
            try:
                if self.mode == "hang":
                    await asyncio.sleep(30)
                if self.delay:
                    await asyncio.sleep(self.delay)
                status = "502 Bad Gateway" if self.mode == "502" else "200 OK"
                writer.write(f"HTTP/1.1 {status}\r\ncontent-type: application/json\r\n"
                             "content-length: 2\r\nconnection: close\r\n\r\n{}".encode())
                await writer.drain()
            finally:
                writer.close()

        self._server = await asyncio.start_server(handle, "127.0.0.1", 0)
        self.url = f"http://127.0.0.1:{self._server.sockets[0].getsockname()[1]}"
        return self

    async def __aexit__(self, *exc):
        self._server.close()


class TestTheBreakerHoldsInEveryWayAthenaCanFail:
    @pytest.fixture(autouse=True)
    def fresh_breakers(self):
        athena_client._BREAKERS.clear()
        yield
        athena_client._BREAKERS.clear()

    @staticmethod
    async def client(server, timeout=0.3):
        client = AthenaClient(server.url, tenant_id="t", timeout=timeout)
        return client, await client._http(), athena_client._breaker(server.url)

    @pytest.mark.asyncio
    async def test_one_call_that_had_to_be_waited_out_opens_it(self):
        """Athena behind a gateway that is up: the connection is made and nothing comes
        back. Three such waits before opening would be three times the limit."""
        import httpx

        async with _Server() as server:
            server.mode = "hang"
            client, http, breaker = await self.client(server)
            with pytest.raises(httpx.ReadTimeout):
                await http.get("/api/v1/health")
            assert breaker.state == "open"
            with pytest.raises(httpx.ConnectError, match="left alone"):
                await http.get("/api/v1/health")
            assert server.requests == 1
            await client.close()

    @pytest.mark.asyncio
    async def test_a_caller_that_gives_up_waiting_opens_it_too(self, monkeypatch):
        """A caller may wait less than the client's own limit."""
        import asyncio

        monkeypatch.setattr(athena_client, "_GAVE_UP_AFTER", 0.05)
        async with _Server() as server:
            server.mode = "hang"
            client, http, breaker = await self.client(server, timeout=5.0)
            with pytest.raises(asyncio.TimeoutError):
                await asyncio.wait_for(http.get("/api/v1/health"), 0.2)
            assert breaker.state == "open"
            await client.close()

    @pytest.mark.asyncio
    async def test_a_call_cancelled_before_it_was_waited_for_says_nothing_about_athena(self):
        """A task cancelled for its own reasons (shutdown, a sibling that failed) while a
        call is in flight has not found Athena slow."""
        import asyncio

        async with _Server() as server:
            server.mode = "hang"
            client, http, breaker = await self.client(server, timeout=5.0)
            for _ in range(5):
                call_ = asyncio.ensure_future(http.get("/api/v1/health"))
                await asyncio.sleep(0.05)
                call_.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await call_
            assert breaker.state == "closed"
            await client.close()

    @pytest.mark.asyncio
    async def test_a_gateway_saying_athena_is_unavailable_counts_and_so_does_a_late_answer(self):
        async with _Server() as server:
            client, http, breaker = await self.client(server)
            server.mode = "502"
            for _ in range(3):
                assert (await http.get("/api/v1/health")).status_code == 502
            assert breaker.state == "open"

            athena_client._BREAKERS.clear()
            await client.close()
            client, http, breaker = await self.client(server)
            server.mode, server.delay = "ok", 0.27  # answers, later than 0.8 of the limit
            for _ in range(3):
                assert (await http.get("/api/v1/health")).status_code == 200
            assert breaker.state == "open"
            await client.close()

    @pytest.mark.asyncio
    async def test_one_call_at_a_time_finds_out_and_each_failure_doubles_the_wait(self):
        import asyncio

        import httpx

        async with _Server() as server:
            server.mode = "hang"
            client, http, breaker = await self.client(server)
            breaker.cooldown = 0.05
            with pytest.raises(httpx.ReadTimeout):
                await http.get("/api/v1/health")
            await asyncio.sleep(0.06)

            results = await asyncio.gather(
                *(http.get("/api/v1/health") for _ in range(5)), return_exceptions=True,
            )
            # Five asked at once after the cooldown: one was let through, four were refused.
            assert sum(isinstance(r, httpx.ReadTimeout) for r in results) == 1
            assert sum(isinstance(r, httpx.ConnectError) for r in results) == 4
            assert server.requests == 2
            assert breaker.cooldown == pytest.approx(0.1)
            await client.close()

    @pytest.mark.asyncio
    async def test_an_answer_closes_it_and_the_wait_goes_back_to_what_it_was(self):
        import asyncio

        import httpx

        async with _Server() as server:
            server.mode = "hang"
            client, http, breaker = await self.client(server)
            breaker.cooldown = 0.05
            with pytest.raises(httpx.ReadTimeout):
                await http.get("/api/v1/health")
            server.mode = "ok"
            await asyncio.sleep(0.06)
            assert (await http.get("/api/v1/health")).status_code == 200
            assert breaker.state == "closed"
            assert (await http.get("/api/v1/health")).status_code == 200
            await client.close()

    def test_a_probe_whose_outcome_was_never_recorded_does_not_shut_the_breaker_for_good(self):
        from jarviscore.memory.delivery import CircuitBreaker

        breaker = CircuitBreaker(threshold=1, cooldown=0.0)
        breaker.record_failure()
        assert breaker.allows()          # the probe is let through and never reports back
        breaker.cooldown = 30.0
        breaker._opened_at -= 60
        assert not breaker.allows()      # others wait for it
        breaker._probe_at -= 60
        assert breaker.allows()          # until it has been gone a whole cooldown
