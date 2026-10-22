"""Checks that a Redis is safe to hold JarvisCore state.

Redis stores the workflow ledger, mailboxes and HITL queue, so eviction or a missing
password silently loses work. `strict=True` (deploy) turns the risky-but-working cases
into errors; the default (dev) reports them as warnings.
"""

import ipaddress
from collections.abc import Callable
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from . import ERROR, INFO, WARNING, CheckResult

MIN_VERSION = (5, 0)  # Streams (XADD) back the workflow ledger.
LOCAL_HOSTS = {"localhost", "redis", "host.docker.internal"}


def redact(url: str) -> str:
    """URL with any password replaced, safe for terminal and logs."""
    parts = urlsplit(url)
    if parts.password is None:
        return url
    user = parts.username or ""
    host = parts.hostname or ""
    netloc = f"{user}:***@{host}" if user else f"***@{host}"
    if parts.port:
        netloc += f":{parts.port}"
    return urlunsplit(parts._replace(netloc=netloc))


def check_redis(
    url: str,
    *,
    strict: bool = False,
    timeout: float = 3.0,
    client_factory: Callable[[str, float], Any] | None = None,
) -> list[CheckResult]:
    shown = redact(url)
    risky = ERROR if strict else WARNING
    results: list[CheckResult] = []

    parts = urlsplit(url)
    if parts.scheme not in ("redis", "rediss", "unix"):
        return [CheckResult("redis.url", ERROR, False, f"{shown} is not a Redis URL",
                            "Use redis://host:6379/0 or rediss://host:6380/0")]

    if client_factory is None:
        try:
            import redis  # noqa: F401
        except ImportError:
            return [CheckResult("redis.package", ERROR, False, "The redis Python package is not installed",
                                'pip install "jarviscore-framework[redis]"')]
        client_factory = _default_client

    client = client_factory(url, timeout)
    try:
        client.ping()
    except Exception as exc:  # noqa: BLE001 - every failure means "unreachable"
        return [_connection_failure(shown, exc)]
    results.append(CheckResult("redis.reachable", INFO,
                   True, f"Connected to {shown}"))

    results.append(_check_transport(parts, shown, risky))
    if not parts.password and not _is_local(parts.hostname):
        results.append(CheckResult(
            "redis.auth", risky, False, f"{shown} has no password",
            "Enable AUTH on the server and include it: rediss://:PASSWORD@host:6380/0",
        ))

    batched = _fetch_batched(client)
    if batched is None:
        server = _info(client, "server")
        memory = _info(client, "memory")
        persistence = _info(client, "persistence")
        config: dict = {}
    else:
        server, memory, persistence, config = batched

    results.append(_check_version(server.get("redis_version")))
    results.append(_check_eviction(client, memory, risky, config))
    results.append(_check_persistence(client, persistence, strict, config))
    return results


_CONFIG_NAMES = ("maxmemory-policy", "save")


def _fetch_batched(client):
    """INFO sections and CONFIG values in one round trip; None if the client can't pipeline."""
    pipeline = getattr(client, "pipeline", None)
    if pipeline is None:
        return None
    try:
        pipe = pipeline(transaction=False)
        for section in ("server", "memory", "persistence"):
            pipe.info(section)
        for name in _CONFIG_NAMES:
            pipe.config_get(name)
        replies = pipe.execute(raise_on_error=False)
    except Exception:  # noqa: BLE001 - fall back to one call at a time
        return None
    infos = [{} if isinstance(r, Exception) else (r or {}) for r in replies[:3]]
    config = {}
    for name, value in zip(_CONFIG_NAMES, replies[3:]):
        config[name] = value.get(name) if isinstance(value, dict) else None
    return (*infos, config)


def _default_client(url: str, timeout: float):
    import redis

    return redis.Redis.from_url(url, socket_timeout=timeout, socket_connect_timeout=timeout,
                                decode_responses=True)


def _connection_failure(shown: str, exc: Exception) -> CheckResult:
    name = type(exc).__name__
    if "Authentication" in name or "NOAUTH" in str(exc) or "WRONGPASS" in str(exc):
        return CheckResult("redis.reachable", ERROR, False, f"{shown} rejected the credentials",
                           "Check the password in the URL (redis://:PASSWORD@host:6379/0)")
    return CheckResult("redis.reachable", ERROR, False, f"Cannot reach {shown} ({name}: {exc})",
                       "Start Redis (docker run -p 6379:6379 redis:7) or fix REDIS_URL")


def _is_local(host: str | None) -> bool:
    if not host or host in LOCAL_HOSTS:
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return host.endswith((".local", ".internal", ".ts.net"))
    # 100.64.0.0/10 is the CGNAT range Tailscale uses.
    return ip.is_loopback or ip.is_private or ip in ipaddress.ip_network("100.64.0.0/10")


def _check_transport(parts, shown: str, risky: str) -> CheckResult:
    if parts.scheme in ("rediss", "unix") or _is_local(parts.hostname):
        return CheckResult("redis.tls", INFO, True, "Connection is local, private or TLS")
    return CheckResult("redis.tls", risky, False, f"{shown} is a public host without TLS",
                       "Use rediss:// (TLS) or reach Redis over a private network")


def _info(client, section: str) -> dict:
    try:
        return client.info(section) or {}
    except Exception:  # noqa: BLE001 - managed Redis may restrict INFO sections
        return {}


def _check_version(raw: str | None) -> CheckResult:
    if not raw:
        return CheckResult("redis.version", WARNING, False, "Could not read the Redis version")
    try:
        version = tuple(int(p) for p in str(raw).split(".")[:2])
    except ValueError:
        return CheckResult("redis.version", WARNING, False, f"Unrecognised Redis version {raw!r}")
    if version < MIN_VERSION:
        need = ".".join(map(str, MIN_VERSION))
        return CheckResult("redis.version", ERROR, False, f"Redis {raw} is too old (need {need}+)",
                           "Upgrade to Redis 7")
    return CheckResult("redis.version", INFO, True, f"Redis {raw}")


def _check_eviction(client, memory: dict, risky: str, config: dict | None = None) -> CheckResult:
    policy = memory.get("maxmemory_policy")
    if policy is None:
        policy = _config_get(client, "maxmemory-policy", config)
    if policy is None:
        return CheckResult("redis.eviction", WARNING, False, "Could not read maxmemory-policy",
                           "Set maxmemory-policy=noeviction in your Redis provider's settings")
    if policy != "noeviction":
        return CheckResult(
            "redis.eviction", risky, False,
            f"maxmemory-policy is {policy!r}: Redis may delete workflow state under memory pressure",
            "Set maxmemory-policy=noeviction (CONFIG SET maxmemory-policy noeviction, or provider settings)",
        )
    return CheckResult("redis.eviction", INFO, True, "maxmemory-policy is noeviction")


def _check_persistence(client, persistence: dict, strict: bool, config: dict | None = None) -> CheckResult:
    if str(persistence.get("aof_enabled", "0")) == "1":
        return CheckResult("redis.persistence", INFO, True, "Append-only file persistence is on")
    save = _config_get(client, "save", config)
    if save:
        return CheckResult("redis.persistence", INFO, True, f"RDB snapshots configured ({save})")
    severity = WARNING if strict else INFO
    if save is None:
        return CheckResult("redis.persistence", severity, False, "Could not verify persistence",
                           "Make sure AOF or RDB persistence is enabled in your Redis provider")
    return CheckResult("redis.persistence", severity, False, "Persistence is off: a restart loses all state",
                       "Run Redis with --appendonly yes")


def _config_get(client, name: str, prefetched: dict | None = None) -> str | None:
    if prefetched and name in prefetched:
        return prefetched[name]
    try:
        value = client.config_get(name)
    except Exception:  # noqa: BLE001 - CONFIG is commonly disabled on managed Redis
        return None
    if isinstance(value, dict):
        return value.get(name)
    return None
