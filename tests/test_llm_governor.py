"""Provider governor: pacing LLM calls per deployment before they are sent."""

import asyncio
import os
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from jarviscore.execution import governor as governor_module
from jarviscore.execution.governor import (
    BULK,
    INTERACTIVE,
    AdaptiveConcurrency,
    DeploymentGovernor,
    Limits,
    ProviderGovernor,
    RateWindow,
    _LocalWindow,
    lane_scope,
    retry_after_seconds,
)
from jarviscore.execution.llm import LLMProvider, UnifiedLLMClient


def _governor(**config):
    return ProviderGovernor({"llm_initial_concurrency": 2, **config}, shared_window=False)


@pytest.mark.asyncio
async def test_calls_in_flight_never_exceed_the_current_limit_and_grow_on_success():
    deployment = _governor().deployment("azure:test")
    peak = 0

    async def call():
        nonlocal peak
        permit = await deployment.admit(100)
        peak = max(peak, deployment.concurrency.in_flight)
        await asyncio.sleep(0.01)
        await permit.finish(total_tokens=50)

    await asyncio.gather(*(call() for _ in range(12)))

    assert peak <= 8
    assert deployment.concurrency.in_flight == 0
    # Slow start: every success while below threshold adds one call in flight.
    assert deployment.concurrency.limit == 14
    assert deployment.snapshot()["admitted"] == 12


@pytest.mark.asyncio
async def test_a_rate_limit_halves_calls_in_flight_once_per_burst():
    concurrency = AdaptiveConcurrency(initial=16, ceiling=64, bulk_reserve=0.0)
    deployment = DeploymentGovernor("azure:test", Limits(), concurrency, None)

    for _ in range(3):
        permit = await deployment.admit(10)
        await permit.finish(rate_limited=True, failed=True)

    assert concurrency.limit == 8
    assert deployment.stats.rate_limited == 3
    # After a rate limit growth is additive: one call per limit's worth of successes.
    permit = await deployment.admit(10)
    await permit.finish(total_tokens=10)
    assert concurrency.limit == pytest.approx(8 + 1 / 8)


@pytest.mark.asyncio
async def test_headers_reporting_an_almost_spent_quota_back_off_before_any_429():
    concurrency = AdaptiveConcurrency(initial=10, ceiling=64, bulk_reserve=0.0)
    deployment = DeploymentGovernor("azure:test", Limits(), concurrency, None)

    deployment.observe_headers({"x-ratelimit-remaining-tokens": "900",
                                "x-ratelimit-remaining-requests": "40"})
    permit = await deployment.admit(1000)
    await permit.finish(total_tokens=600)

    assert concurrency.limit == 5
    assert deployment.stats.congested == 1
    assert deployment.stats.rate_limited == 0


@pytest.mark.asyncio
async def test_reported_limits_skip_slow_start_to_what_they_sustain(monkeypatch):
    concurrency = AdaptiveConcurrency(initial=4, ceiling=256, bulk_reserve=0.0)
    deployment = DeploymentGovernor("azure:test", Limits(), concurrency, None)
    deployment.observe_headers({
        "x-ratelimit-limit-requests": "60000", "x-ratelimit-limit-tokens": "6000000",
        "x-ratelimit-remaining-requests": "59990", "x-ratelimit-remaining-tokens": "5900000",
    })
    clock = [1000.0]
    monkeypatch.setattr(governor_module.time, "monotonic", lambda: clock[0])

    permit = await deployment.admit(50_000)
    clock[0] += 20.0  # a 20 s call reserving 50k tokens
    await permit.finish(total_tokens=30_000)

    # 6M TPM / 50k per call = 120 calls a minute; at 20 s each that is 40 in flight.
    assert concurrency.limit >= 0.85 * 40
    assert deployment.snapshot()["tpm"] == 6_000_000


@pytest.mark.asyncio
async def test_a_rate_limit_holds_off_the_jump_for_a_minute():
    concurrency = AdaptiveConcurrency(initial=16, ceiling=256, bulk_reserve=0.0)
    deployment = DeploymentGovernor("azure:test", Limits(), concurrency, None)
    deployment.observe_headers({"x-ratelimit-limit-requests": "60000"})
    permit = await deployment.admit(10)
    await permit.finish(rate_limited=True, failed=True)
    permit = await deployment.admit(10)
    await permit.finish(total_tokens=10)
    assert concurrency.limit < 16


@pytest.mark.asyncio
async def test_bulk_work_leaves_headroom_for_interactive_calls():
    concurrency = AdaptiveConcurrency(initial=10, ceiling=10, bulk_reserve=0.2)
    deployment = DeploymentGovernor("azure:test", Limits(), concurrency, None)

    bulk = [await deployment.admit(10, BULK) for _ in range(8)]
    blocked = asyncio.ensure_future(deployment.admit(10, BULK))
    await asyncio.sleep(0.01)
    assert not blocked.done()

    interactive = await asyncio.wait_for(deployment.admit(10, INTERACTIVE), 1)
    assert concurrency.in_flight == 9

    await interactive.finish(total_tokens=1)
    for permit in bulk:
        await permit.finish(total_tokens=1)
    await (await blocked).finish(total_tokens=1)
    assert concurrency.in_flight == 0


def test_the_window_admits_within_rpm_and_tpm_and_says_how_long_to_wait():
    window = _LocalWindow()
    limits = Limits(rpm=3, tpm=1000)
    now = 1_000

    assert window.admit(now, limits, 400)[0]
    assert window.admit(now, limits, 400)[0]
    admitted, wait = window.admit(now + 10, limits, 400)
    assert not admitted and wait == 50
    window.adjust(now, -500)  # settled: the calls used less than they reserved
    assert window.admit(now + 10, limits, 400)[0]
    assert not window.admit(now + 11, limits, 1)[0]  # fourth request in the minute
    assert window.admit(now + 61, limits, 400)[0]


def test_a_call_larger_than_the_whole_tpm_still_runs_alone():
    window = _LocalWindow()
    assert window.admit(1_000, Limits(tpm=100), 5000)[0]


@pytest.mark.asyncio
async def test_known_limits_hold_a_call_until_the_window_has_room(monkeypatch):
    governor = ProviderGovernor(
        {"llm_initial_concurrency": 4, "llm_limits": {"azure:paced": {"rpm": 1}}},
        shared_window=False,
    )
    deployment = governor.deployment("azure:paced")
    waits = []

    async def fake_sleep(seconds):
        waits.append(seconds)
        deployment.window._local._seconds.clear()

    monkeypatch.setattr(governor_module.asyncio, "sleep", fake_sleep)
    first = await deployment.admit(10)
    second = await deployment.admit(10)

    assert len(waits) == 1 and waits[0] > 0
    await first.finish(total_tokens=5)
    await second.finish(total_tokens=5)


@pytest.mark.skipif(not os.environ.get("JARVISCORE_TEST_REDIS_URL"),
                    reason="needs a real Redis for Lua (JARVISCORE_TEST_REDIS_URL)")
def test_every_process_shares_one_redis_window():
    import redis

    client = redis.Redis.from_url(os.environ["JARVISCORE_TEST_REDIS_URL"], decode_responses=True)
    key = f"test-{time.time_ns()}"
    first = RateWindow(key, Limits(rpm=2), client)
    second = RateWindow(key, Limits(rpm=2), client)
    try:
        assert first.admit(10)[0]
        assert second.admit(10)[0]
        admitted, wait, _ = first.admit(10)
        assert not admitted and 0 < wait <= 60
    finally:
        client.delete(f"llm_window:{key}")


def test_an_unreachable_redis_degrades_to_local_accounting_without_stalling_calls():
    class Down:
        calls = 0

        def register_script(self, script):
            def run(**kwargs):
                Down.calls += 1
                raise ConnectionError("redis down")
            return run

    window = RateWindow("azure:test", Limits(rpm=100), Down())
    for _ in range(5):
        assert window.admit(10)[0]
    assert Down.calls == 1


@pytest.mark.asyncio
async def test_a_cancelled_admission_wait_releases_its_slot():
    concurrency = AdaptiveConcurrency(initial=1, ceiling=1, bulk_reserve=0.0)
    deployment = DeploymentGovernor("azure:test", Limits(), concurrency, None)
    held = await deployment.admit(1)
    waiting = asyncio.ensure_future(deployment.admit(1))
    await asyncio.sleep(0.01)
    waiting.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiting
    await held.finish(total_tokens=1)
    assert concurrency.in_flight == 0 and concurrency.waiting == 0


def test_retry_after_comes_from_response_headers():
    error = SimpleNamespace(response=SimpleNamespace(headers={"retry-after-ms": "1500"}))
    assert retry_after_seconds(error) == 1.5
    error = SimpleNamespace(response=SimpleNamespace(headers={"retry-after": "7"}))
    assert retry_after_seconds(error) == 7.0
    assert retry_after_seconds(RuntimeError("no response")) is None


def _client(governor, **config):
    llm = UnifiedLLMClient.__new__(UnifiedLLMClient)
    llm.config = {"llm_default_max_tokens": 100, "llm_max_retries_429": 2,
                  "azure_deployment": "strong", **config}
    llm._semaphore = None
    llm._governor = governor
    llm.provider_order = [LLMProvider.AZURE]
    return llm


@pytest.mark.asyncio
async def test_every_call_is_admitted_for_its_own_deployment_and_settled():
    governor = _governor()
    llm = _client(governor)
    llm._call_azure = AsyncMock(return_value={"content": "ok", "tokens": {"total": 42}})

    await llm.generate(prompt="hello", max_tokens=50)
    await llm.generate(prompt="hello", max_tokens=50, model="fast")

    assert set(governor.snapshot()) == {"azure:strong", "azure:fast"}
    assert governor.snapshot()["azure:strong"]["admitted"] == 1
    assert governor.snapshot()["azure:fast"]["in_flight"] == 0


@pytest.mark.asyncio
async def test_a_429_waits_for_the_providers_retry_after_and_counts(monkeypatch):
    governor = _governor()
    llm = _client(governor)

    class RateLimited(Exception):
        status_code = 429
        response = SimpleNamespace(headers={"retry-after": "3"})

    llm._call_azure = AsyncMock(side_effect=[RateLimited("too many"),
                                             {"content": "ok", "tokens": {"total": 1}}])
    sleeps = []

    async def fake_sleep(seconds):
        sleeps.append(seconds)

    monkeypatch.setattr("jarviscore.execution.llm.asyncio.sleep", fake_sleep)
    result = await llm.generate(prompt="hello", max_tokens=10)

    assert result["content"] == "ok"
    assert sleeps and sleeps[0] >= 3
    assert governor.snapshot()["azure:strong"]["rate_limited"] == 1


@pytest.mark.asyncio
async def test_the_lane_scope_reaches_admission():
    governor = _governor()
    llm = _client(governor)
    seen = []
    original = DeploymentGovernor.admit

    async def recording(self, tokens, lane=INTERACTIVE):
        seen.append(lane)
        return await original(self, tokens, lane)

    llm._call_azure = AsyncMock(return_value={"content": "ok", "tokens": {"total": 1}})
    DeploymentGovernor.admit = recording
    try:
        with lane_scope(BULK):
            await llm.generate(prompt="bulk", max_tokens=10)
        await llm.generate(prompt="chat", max_tokens=10)
    finally:
        DeploymentGovernor.admit = original
    assert seen == [BULK, INTERACTIVE]


@pytest.mark.asyncio
async def test_azure_response_headers_reach_the_deployment_they_came_from():
    governor = _governor()
    llm = _client(governor)
    response = SimpleNamespace(
        request=SimpleNamespace(url=SimpleNamespace(
            path="/openai/deployments/strong/chat/completions")),
        headers={"x-ratelimit-remaining-tokens": "12345", "content-type": "json"},
    )

    await llm._observe_azure_response(response)

    assert governor.deployment("azure:strong")._headers == {
        "x-ratelimit-remaining-tokens": "12345"
    }


@pytest.mark.asyncio
async def test_without_a_governor_calls_go_straight_through():
    llm = _client(None)
    llm._call_azure = AsyncMock(return_value={"content": "ok", "tokens": {"total": 1}})
    assert (await llm.generate(prompt="hello", max_tokens=10))["content"] == "ok"
