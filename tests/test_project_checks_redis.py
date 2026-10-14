import pytest

from jarviscore.project.checks import ERROR, INFO, WARNING, has_errors
from jarviscore.project.checks.redis import check_redis, redact


class FakeRedis:
    def __init__(self, version="7.2.4", policy="noeviction", aof="1", save="", ping_error=None,
                 info_blocked=(), config_blocked=False):
        self.version, self.policy, self.aof, self.save = version, policy, aof, save
        self.ping_error, self.info_blocked, self.config_blocked = ping_error, info_blocked, config_blocked

    def ping(self):
        if self.ping_error:
            raise self.ping_error
        return True

    def info(self, section):
        if section in self.info_blocked:
            raise RuntimeError("NOPERM")
        return {
            "server": {"redis_version": self.version},
            "memory": {"maxmemory_policy": self.policy},
            "persistence": {"aof_enabled": self.aof},
        }[section]

    def config_get(self, name):
        if self.config_blocked:
            raise RuntimeError("unknown command 'CONFIG'")
        return {name: {"maxmemory-policy": self.policy, "save": self.save}[name]}


def run(url="redis://localhost:6379/0", strict=False, **fake):
    return {r.id: r for r in check_redis(url, strict=strict, client_factory=lambda u, t: FakeRedis(**fake))}


def test_healthy_local_redis_passes():
    results = run()
    assert all(r.ok for r in results.values()), results
    assert not has_errors(list(results.values()))


@pytest.mark.parametrize("url, expected", [
    ("redis://:s3cret@host:6379/0", "redis://***@host:6379/0"),
    ("rediss://default:s3cret@host:6380", "rediss://default:***@host:6380"),
    ("redis://localhost:6379", "redis://localhost:6379"),
])
def test_redact_never_shows_password(url, expected):
    assert redact(url) == expected


def test_password_never_appears_in_any_message():
    exc = ConnectionError("boom")
    for results in (run("redis://:s3cret@db.example.com:6379"),
                    run("redis://:s3cret@db.example.com:6379", ping_error=exc)):
        for r in results.values():
            assert "s3cret" not in r.message and "s3cret" not in (r.fix or "")


def test_not_a_redis_url():
    r = run("http://localhost:6379")["redis.url"]
    assert r.severity == ERROR and not r.ok


def test_unreachable_stops_further_checks():
    results = run(ping_error=ConnectionError("Connection refused"))
    assert list(results) == ["redis.reachable"]
    assert results["redis.reachable"].severity == ERROR
    assert "docker run" in results["redis.reachable"].fix


def test_bad_password_is_reported_as_credentials():
    class AuthenticationError(Exception):
        pass

    r = run(ping_error=AuthenticationError("WRONGPASS"))["redis.reachable"]
    assert "rejected the credentials" in r.message


@pytest.mark.parametrize("policy, strict, severity", [
    ("allkeys-lru", False, WARNING),
    ("allkeys-lru", True, ERROR),
    ("volatile-ttl", True, ERROR),
])
def test_eviction_policy_other_than_noeviction(policy, strict, severity):
    r = run(policy=policy, strict=strict)["redis.eviction"]
    assert not r.ok and r.severity == severity and "noeviction" in r.fix


def test_eviction_falls_back_to_config_when_info_blocked():
    r = run(policy="allkeys-lru", info_blocked=("memory",))["redis.eviction"]
    assert not r.ok and "allkeys-lru" in r.message


def test_eviction_unverifiable_on_locked_down_managed_redis():
    r = run(info_blocked=("memory",), config_blocked=True,
            strict=True)["redis.eviction"]
    assert not r.ok and r.severity == WARNING and "provider" in r.fix


def test_persistence_via_rdb_snapshots():
    r = run(aof="0", save="3600 1 300 100")["redis.persistence"]
    assert r.ok and "RDB" in r.message


@pytest.mark.parametrize("strict, severity", [(False, INFO), (True, WARNING)])
def test_persistence_off(strict, severity):
    r = run(aof="0", save="", strict=strict)["redis.persistence"]
    assert not r.ok and r.severity == severity and "appendonly" in r.fix


def test_persistence_unverifiable_when_config_blocked():
    r = run(aof="0", config_blocked=True, strict=True)["redis.persistence"]
    assert not r.ok and r.severity == WARNING and "Could not verify" in r.message


@pytest.mark.parametrize("version, ok, severity", [("4.0.14", False, ERROR), ("5.0.0", True, INFO),
                                                   ("7.2.4", True, INFO)])
def test_version_floor(version, ok, severity):
    r = run(version=version)["redis.version"]
    assert r.ok is ok and r.severity == severity


@pytest.mark.parametrize("url, needs_tls", [
    ("redis://localhost:6379", False),
    ("redis://10.0.0.5:6379", False),
    ("redis://100.101.102.103:6379", False),      # Tailscale CGNAT
    ("redis://db.tail1234.ts.net:6379", False),
    ("redis://redis:6379", False),                 # compose service name
    ("rediss://acme.redis.cache.windows.net:6380", False),
    ("redis://acme.redis.cache.windows.net:6379", True),
    ("redis://8.8.8.8:6379", True),
])
def test_tls_required_only_for_public_hosts(url, needs_tls):
    r = run(url, strict=True)["redis.tls"]
    assert r.ok is not needs_tls
    if needs_tls:
        assert r.severity == ERROR


def test_public_host_without_password_is_flagged():
    results = run("rediss://acme.example.com:6380", strict=True)
    assert results["redis.auth"].severity == ERROR
    assert "redis.auth" not in run("redis://localhost:6379")


def test_missing_package_is_reported(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "redis":
            raise ImportError
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    results = check_redis("redis://localhost:6379")
    assert results[0].id == "redis.package" and "pip install" in results[0].fix


def test_against_real_local_redis():
    url = "redis://localhost:6379/0"
    results = {r.id: r for r in check_redis(url, timeout=0.5)}
    if not results["redis.reachable"].ok:
        pytest.skip("no Redis on localhost:6379")
    assert results["redis.version"].ok
    assert results["redis.eviction"].severity in (INFO, WARNING)
