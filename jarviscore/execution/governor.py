"""Paces LLM calls against each deployment's capacity before they are sent.

A deployment is a key such as ``azure:gpt-5.2-chat``. Its calls in flight are found
rather than configured: slow start from a small limit, growth on success, and halving
when the provider signals congestion (a 429, or response headers reporting the
remaining quota nearly spent). When requests- or tokens-per-minute limits are known,
a 60-second window shared through Redis admits a call only if both fit, so every
process drawing on one deployment shares one budget. A 429 is then an anomaly to
count, not the way capacity is discovered.
"""

from __future__ import annotations

import asyncio
import logging
import math
import time
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, Iterator, Mapping, Optional

logger = logging.getLogger(__name__)

WINDOW_SECONDS = 60
INTERACTIVE = "interactive"
BULK = "bulk"
# Congestion signals inside this interval belong to the same burst: halve once.
_DECREASE_COOLDOWN_SECONDS = 2.0
# After a Redis failure the window counts locally this long before trying again.
_REDIS_RETRY_SECONDS = 30.0
# Share of a reported limit the governor plans to use.
_TARGET_UTILISATION = 0.85
_LANE: ContextVar[str] = ContextVar("llm_lane", default=INTERACTIVE)


def current_lane() -> str:
    return _LANE.get()


@contextmanager
def lane_scope(lane: str) -> Iterator[None]:
    """Run the enclosed LLM calls in a lane; bulk work yields headroom to interactive."""
    token = _LANE.set(lane)
    try:
        yield
    finally:
        _LANE.reset(token)

_WINDOW_ADMIT = """
local key = KEYS[1]
local now = tonumber(ARGV[1])
local rpm = tonumber(ARGV[2])
local tpm = tonumber(ARGV[3])
local tokens = tonumber(ARGV[4])
local fields = redis.call('HGETALL', key)
local requests, used, oldest = 0, 0, now
for i = 1, #fields, 2 do
  local name = fields[i]
  local second = tonumber(string.sub(name, 3))
  if second <= now - 60 then
    redis.call('HDEL', key, name)
  else
    local value = tonumber(fields[i + 1])
    if string.sub(name, 1, 1) == 'r' then requests = requests + value else used = used + value end
    if second < oldest then oldest = second end
  end
end
local over_requests = rpm > 0 and requests + 1 > rpm
local over_tokens = tpm > 0 and used > 0 and used + tokens > tpm
if over_requests or over_tokens then
  return {0, oldest + 60 - now}
end
redis.call('HINCRBY', key, 'r:' .. now, 1)
redis.call('HINCRBY', key, 't:' .. now, tokens)
redis.call('EXPIRE', key, 120)
return {1, now}
"""


@dataclass
class Limits:
    rpm: int = 0
    tpm: int = 0

    @classmethod
    def from_config(cls, value: Mapping[str, Any] | None) -> "Limits":
        value = value or {}
        return cls(rpm=int(value.get("rpm") or 0), tpm=int(value.get("tpm") or 0))

    @property
    def known(self) -> bool:
        return bool(self.rpm or self.tpm)


class _LocalWindow:
    """The same 60-second accounting as the Redis script, for one process."""

    def __init__(self) -> None:
        self._seconds: dict[int, list[int]] = {}

    def admit(self, now: int, limits: Limits, tokens: int) -> tuple[bool, float]:
        for second in [s for s in self._seconds if s <= now - WINDOW_SECONDS]:
            del self._seconds[second]
        requests = sum(entry[0] for entry in self._seconds.values())
        used = sum(entry[1] for entry in self._seconds.values())
        over_requests = limits.rpm and requests + 1 > limits.rpm
        over_tokens = limits.tpm and used and used + tokens > limits.tpm
        if over_requests or over_tokens:
            oldest = min(self._seconds) if self._seconds else now
            return False, float(oldest + WINDOW_SECONDS - now)
        entry = self._seconds.setdefault(now, [0, 0])
        entry[0] += 1
        entry[1] += tokens
        return True, float(now)

    def adjust(self, second: int, delta: int) -> None:
        if second in self._seconds:
            self._seconds[second][1] += delta


class RateWindow:
    """Requests and tokens admitted to one deployment in the last 60 seconds."""

    def __init__(self, key: str, limits: Limits, redis_client=None) -> None:
        self.key = key
        self.limits = limits
        self._redis = redis_client
        self._script = None
        self._local = _LocalWindow()
        self._redis_retry_at = 0.0

    def _redis_key(self) -> str:
        return f"llm_window:{self.key}"

    def _shared(self):
        if self._redis is None or time.monotonic() < self._redis_retry_at:
            return None
        return self._redis

    def _redis_failed(self, error: Exception) -> None:
        if not self._redis_retry_at:
            logger.warning("LLM rate window for %s using local accounting: %s", self.key, error)
        self._redis_retry_at = time.monotonic() + _REDIS_RETRY_SECONDS

    def admit(self, tokens: int) -> tuple[bool, float, int]:
        """Admit or report how long until the window has room; returns (ok, wait, second)."""
        now = int(time.time())
        shared = self._shared()
        if shared is not None:
            try:
                if self._script is None:
                    self._script = shared.register_script(_WINDOW_ADMIT)
                admitted, value = self._script(
                    keys=[self._redis_key()],
                    args=[now, self.limits.rpm, self.limits.tpm, int(tokens)],
                )
                if int(admitted):
                    return True, 0.0, now
                return False, max(0.5, float(value)), now
            except Exception as error:  # noqa: BLE001 - any Redis failure degrades to local
                self._redis_failed(error)
        ok, value = self._local.admit(now, self.limits, int(tokens))
        return (True, 0.0, now) if ok else (False, max(0.5, value), now)

    def settle(self, second: int, reserved: int, actual: int) -> None:
        delta = int(actual) - int(reserved)
        if not delta:
            return
        shared = self._shared()
        if shared is not None:
            try:
                key = self._redis_key()
                if shared.hexists(key, f"t:{second}"):
                    shared.hincrby(key, f"t:{second}", delta)
                    return
            except Exception as error:  # noqa: BLE001 - settlement is best effort
                self._redis_failed(error)
        self._local.adjust(second, delta)


class AdaptiveConcurrency:
    """Calls in flight for one deployment, found by slow start and AIMD."""

    def __init__(self, initial: int, ceiling: int, bulk_reserve: float) -> None:
        self.initial = max(1, int(initial))
        self.ceiling = max(self.initial, int(ceiling))
        self.bulk_reserve = min(max(float(bulk_reserve), 0.0), 0.9)
        self.limit = float(self.initial)
        self.threshold = math.inf
        self.in_flight = 0
        self.waiting = 0
        self._last_decrease = 0.0
        self._condition: Optional[asyncio.Condition] = None
        self._loop = None

    def _wait_condition(self) -> asyncio.Condition:
        loop = asyncio.get_running_loop()
        if self._condition is None or self._loop is not loop:
            # A new event loop (a restarted service, a test) starts with no calls in flight.
            self._condition = asyncio.Condition()
            self._loop = loop
            self.in_flight = 0
            self.waiting = 0
        return self._condition

    def _capacity(self, lane: str) -> int:
        limit = max(1, int(self.limit))
        if lane == BULK:
            return max(1, int(limit * (1.0 - self.bulk_reserve)))
        return limit

    async def acquire(self, lane: str) -> None:
        condition = self._wait_condition()
        async with condition:
            self.waiting += 1
            try:
                await condition.wait_for(lambda: self.in_flight < self._capacity(lane))
            finally:
                self.waiting -= 1
            self.in_flight += 1

    async def release(self, outcome: str) -> None:
        condition = self._wait_condition()
        async with condition:
            self.in_flight = max(0, self.in_flight - 1)
            if outcome == "ok":
                self._increase()
            elif outcome == "congested":
                self._decrease()
            condition.notify_all()

    def _increase(self) -> None:
        if self.limit < self.threshold:
            self.limit = min(self.ceiling, self.limit + 1.0)
        else:
            self.limit = min(self.ceiling, self.limit + 1.0 / self.limit)

    def _decrease(self) -> None:
        now = time.monotonic()
        if now - self._last_decrease < _DECREASE_COOLDOWN_SECONDS:
            return
        self._last_decrease = now
        self.threshold = max(1.0, self.limit / 2.0)
        self.limit = self.threshold

    def raise_to(self, target: float) -> None:
        """Skip slow start when the provider has said how much it allows."""
        if time.monotonic() - self._last_decrease < 60.0:
            return
        self.limit = max(self.limit, min(float(self.ceiling), target))


@dataclass
class DeploymentStats:
    admitted: int = 0
    rate_limited: int = 0
    congested: int = 0
    waited_seconds: float = 0.0
    max_wait_seconds: float = 0.0


@dataclass
class Permit:
    """One admitted call; settle it with the provider's outcome."""

    governor: "DeploymentGovernor"
    lane: str
    reserved: int
    second: Optional[int]
    waited: float
    started: float = field(default_factory=lambda: time.monotonic())
    _released: bool = field(default=False, repr=False)

    async def finish(self, *, total_tokens: int = 0, rate_limited: bool = False,
                     failed: bool = False) -> None:
        if self._released:
            return
        self._released = True
        await self.governor._finish(self, int(total_tokens), rate_limited, failed)


class DeploymentGovernor:
    """Admission for one deployment key."""

    def __init__(self, key: str, limits: Limits, concurrency: AdaptiveConcurrency,
                 window: Optional[RateWindow]) -> None:
        self.key = key
        self.limits = limits
        self.concurrency = concurrency
        self.window = window
        self.stats = DeploymentStats()
        self._headers: dict[str, str] = {}
        self.reported = Limits()

    async def admit(self, tokens: int, lane: str = INTERACTIVE) -> Permit:
        started = time.monotonic()
        await self.concurrency.acquire(lane)
        second = None
        try:
            while self.window is not None:
                admitted, wait, second = self.window.admit(tokens)
                if admitted:
                    break
                await asyncio.sleep(wait)
        except BaseException:
            await self.concurrency.release("cancelled")
            raise
        waited = time.monotonic() - started
        self.stats.admitted += 1
        self.stats.waited_seconds += waited
        self.stats.max_wait_seconds = max(self.stats.max_wait_seconds, waited)
        return Permit(self, lane, int(tokens), second, waited)

    def observe_headers(self, headers: Mapping[str, str]) -> None:
        self._headers = {k.lower(): v for k, v in headers.items()
                         if k.lower().startswith("x-ratelimit") or k.lower().startswith("retry-after")}
        try:
            self.reported = Limits(
                rpm=int(float(self._headers.get("x-ratelimit-limit-requests") or 0)),
                tpm=int(float(self._headers.get("x-ratelimit-limit-tokens") or 0)),
            )
        except ValueError:
            pass

    def _allowed_in_flight(self, seconds_per_call: float, reserved: int) -> float:
        """Calls in flight the reported limits sustain at this latency (Little's law)."""
        if seconds_per_call <= 0:
            return 0.0
        bounds = []
        if self.reported.rpm:
            bounds.append(self.reported.rpm / 60.0 * seconds_per_call)
        if self.reported.tpm and reserved:
            bounds.append(self.reported.tpm / 60.0 / reserved * seconds_per_call)
        return _TARGET_UTILISATION * min(bounds) if bounds else 0.0

    def _headers_report_congestion(self, reserved: int) -> bool:
        def number(name: str) -> Optional[float]:
            try:
                return float(self._headers[name])
            except (KeyError, TypeError, ValueError):
                return None

        remaining_requests = number("x-ratelimit-remaining-requests")
        remaining_tokens = number("x-ratelimit-remaining-tokens")
        if remaining_requests is not None and remaining_requests <= 1:
            return True
        # Less room than two more calls like this one: stop growing and back off.
        return remaining_tokens is not None and remaining_tokens < 2 * max(reserved, 1)

    async def _finish(self, permit: Permit, total_tokens: int, rate_limited: bool,
                      failed: bool) -> None:
        if self.window is not None and permit.second is not None:
            self.window.settle(permit.second, permit.reserved,
                               total_tokens if not failed else 0)
        if rate_limited:
            self.stats.rate_limited += 1
            outcome = "congested"
        elif failed:
            outcome = "neutral"
        elif self._headers_report_congestion(permit.reserved):
            self.stats.congested += 1
            outcome = "congested"
        else:
            outcome = "ok"
            self.concurrency.raise_to(self._allowed_in_flight(
                time.monotonic() - permit.started, permit.reserved
            ))
        await self.concurrency.release(outcome)

    def snapshot(self) -> dict[str, Any]:
        return {
            "limit": round(self.concurrency.limit, 2),
            "in_flight": self.concurrency.in_flight,
            "waiting": self.concurrency.waiting,
            "rpm": self.limits.rpm or self.reported.rpm or None,
            "tpm": self.limits.tpm or self.reported.tpm or None,
            "admitted": self.stats.admitted,
            "rate_limited": self.stats.rate_limited,
            "congested": self.stats.congested,
            "mean_wait_seconds": round(
                self.stats.waited_seconds / self.stats.admitted, 3
            ) if self.stats.admitted else 0.0,
            "max_wait_seconds": round(self.stats.max_wait_seconds, 3),
        }


class ProviderGovernor:
    """Every deployment's admission in this process."""

    def __init__(self, config: Mapping[str, Any], redis_client=None, *,
                 shared_window: bool = True) -> None:
        self.enabled = bool(config.get("llm_governor_enabled", True))
        self._limits = {
            str(key): Limits.from_config(value)
            for key, value in (config.get("llm_limits") or {}).items()
        }
        self._initial = int(config.get("llm_initial_concurrency", 8))
        ceiling = int(config.get("llm_concurrency_ceiling", 256))
        explicit = int(config.get("llm_max_concurrent", 0) or 0)
        self._ceiling = min(ceiling, explicit) if explicit > 0 else ceiling
        self._bulk_reserve = float(config.get("llm_bulk_reserve", 0.15))
        self._redis = redis_client
        self._shared_window = shared_window
        self._redis_config = config
        self._deployments: dict[str, DeploymentGovernor] = {}

    def _redis_client(self):
        if self._redis is not None or not self._shared_window:
            return self._redis
        try:
            import redis

            config = self._redis_config
            # Admission sits on every LLM call: a slow Redis must not stall it.
            timeouts = {"socket_connect_timeout": 1.0, "socket_timeout": 1.0}
            if config.get("redis_url"):
                self._redis = redis.Redis.from_url(
                    config["redis_url"], decode_responses=True, **timeouts
                )
            else:
                self._redis = redis.Redis(
                    host=config.get("redis_host", "localhost"),
                    port=int(config.get("redis_port", 6379)),
                    password=config.get("redis_password"),
                    db=int(config.get("redis_db", 0)),
                    decode_responses=True,
                    **timeouts,
                )
        except Exception as error:  # noqa: BLE001 - the window degrades to local accounting
            logger.warning("LLM rate window has no Redis: %s", error)
            self._redis = None
        return self._redis

    def deployment(self, key: str) -> DeploymentGovernor:
        governor = self._deployments.get(key)
        if governor is None:
            limits = self._limits.get(key) or Limits()
            window = RateWindow(key, limits, self._redis_client()) if limits.known else None
            governor = DeploymentGovernor(
                key, limits,
                AdaptiveConcurrency(self._initial, self._ceiling, self._bulk_reserve),
                window,
            )
            self._deployments[key] = governor
        return governor

    def snapshot(self) -> dict[str, dict[str, Any]]:
        return {key: governor.snapshot() for key, governor in self._deployments.items()}


_PROCESS_GOVERNOR: Optional[ProviderGovernor] = None


def process_governor(config: Mapping[str, Any]) -> ProviderGovernor:
    """The governor shared by every LLM client in this process."""
    global _PROCESS_GOVERNOR
    if _PROCESS_GOVERNOR is None:
        _PROCESS_GOVERNOR = ProviderGovernor(config)
    return _PROCESS_GOVERNOR


def snapshot() -> dict[str, dict[str, Any]]:
    return _PROCESS_GOVERNOR.snapshot() if _PROCESS_GOVERNOR is not None else {}


def retry_after_seconds(error: BaseException) -> Optional[float]:
    """The provider's own retry delay from a rate-limit error's response headers."""
    response = getattr(error, "response", None)
    headers = getattr(response, "headers", None) or {}
    for name, scale in (("retry-after-ms", 0.001), ("retry-after", 1.0)):
        value = headers.get(name) if hasattr(headers, "get") else None
        if value is None:
            continue
        try:
            return float(value) * scale
        except (TypeError, ValueError):
            continue
    return None
