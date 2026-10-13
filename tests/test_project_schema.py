import pytest
import yaml
from pydantic import ValidationError

from jarviscore.project import Project

MINIMAL = {"service": "support-bot",
           "agents": {"triage": {"path": "agents/triage.py"}}}

FULL_YAML = """
service: support-bot
x-common-env: &common
  LOG_LEVEL: INFO
servers:
  main: 100.64.0.10
  edge: { host: edge.example.com, user: deploy, port: 2222 }
agents:
  triage:    { path: agents/triage.py, hosts: [main] }
  responder: { path: agents/responder.py, hosts: [main, edge], replicas: 2, hitl: true }
accessories:
  redis:   { host: main }
  sandbox: { hosts: [main, edge] }
  nexus:   { url: https://nexus.internal.acme.com }
  qdrant:  { image: qdrant/qdrant:v1.9.0, host: edge, port: 6333 }
proxy:
  host: support-bot.example.com
env:
  clear: *common
  secret: [CLAUDE_API_KEY]
llm: { rpm: 60 }
drain_timeout: 45
"""


def project(**overrides):
    return Project.model_validate({**MINIMAL, **overrides})


def test_minimal_project_applies_defaults():
    p = project()
    assert p.agents["triage"].replicas == 1
    assert p.servers == {} and p.accessories == {}
    assert (p.drain_timeout, p.deploy_timeout,
            p.retain_releases) == (30, 120, 5)


def test_full_kamal_style_file_parses():
    p = Project.model_validate(yaml.safe_load(FULL_YAML))
    assert p.servers["main"].host == "100.64.0.10" and p.servers["main"].user == "root"
    assert p.servers["edge"].port == 2222
    assert p.agents["responder"].hosts == ["main", "edge"]
    assert p.accessories["nexus"].external and not p.accessories["redis"].external
    assert p.env.clear == {"LOG_LEVEL": "INFO"}
    assert p.proxy.ssl is True
    assert p.agent_hosts() == {"main", "edge"}


@pytest.mark.parametrize("data, message", [
    ({**MINIMAL, "sevrers": {}}, "sevrers"),
    ({**MINIMAL, "agents": {"triage": {"path": "a.py", "replica": 2}}}, "replica"),
    ({**MINIMAL, "proxy": {"host": "x", "tls": True}}, "tls"),
])
def test_unknown_keys_are_rejected(data, message):
    with pytest.raises(ValidationError, match=message):
        Project.model_validate(data)


def test_x_extension_keys_are_ignored_at_any_depth():
    p = Project.model_validate({
        **MINIMAL,
        "x-anchors": {"anything": 1},
        "agents": {"triage": {"path": "agents/triage.py", "x-note": "ignored"}, "x-shared": {"path": "nope"}},
    })
    assert list(p.agents) == ["triage"]


@pytest.mark.parametrize("bad", ["Support", "1bot", "bot_name", "-bot", ""])
def test_service_name_must_be_container_safe(bad):
    with pytest.raises(ValidationError, match="service name"):
        project(service=bad)


def test_requires_at_least_one_agent():
    with pytest.raises(ValidationError, match="at least one agent"):
        project(agents={})


@pytest.mark.parametrize("path", ["/abs/agent.py", "../outside.py", "agents/triage.txt"])
def test_agent_path_must_be_relative_python_file(path):
    with pytest.raises(ValidationError):
        project(agents={"triage": {"path": path}})


def test_agent_hosts_must_reference_defined_servers():
    with pytest.raises(ValidationError, match="unknown server"):
        project(servers={"main": "1.2.3.4"}, agents={
                "triage": {"path": "a.py", "hosts": ["other"]}})


def test_agent_hosts_without_servers_is_an_error():
    with pytest.raises(ValidationError, match="no 'servers'"):
        project(agents={"triage": {"path": "a.py", "hosts": ["main"]}})


def test_accessory_cannot_be_both_managed_and_external():
    with pytest.raises(ValidationError, match="external accessory"):
        project(servers={"main": "h"}, accessories={
                "redis": {"host": "main", "url": "redis://x"}})


def test_accessory_host_and_hosts_are_exclusive():
    with pytest.raises(ValidationError, match="either 'host' or 'hosts'"):
        project(servers={"main": "h"}, accessories={
                "sandbox": {"host": "main", "hosts": ["main"]}})


@pytest.mark.parametrize("url, ok", [
    ("secret:REDIS_URL", True),
    ("rediss://acme.redis.cache.windows.net:6380", True),
    ("secret:redis-url", False),
])
def test_external_url_secret_reference_format(url, ok):
    if ok:
        assert project(accessories={"redis": {"url": url}}
                       ).accessories["redis"].external
    else:
        with pytest.raises(ValidationError, match="secret reference"):
            project(accessories={"redis": {"url": url}})


def test_custom_accessory_needs_image():
    with pytest.raises(ValidationError, match="need 'image'"):
        project(servers={"main": "h"}, accessories={
                "qdrant": {"host": "main"}})


def test_only_one_redis_host():
    with pytest.raises(ValidationError, match="one Redis"):
        project(servers={"a": "h1", "b": "h2"}, accessories={
                "redis": {"hosts": ["a", "b"]}})


def test_sandbox_must_cover_every_agent_host():
    with pytest.raises(ValidationError, match=r"missing \['b'\]"):
        project(
            servers={"a": "h1", "b": "h2"},
            agents={"triage": {"path": "t.py", "hosts": ["a", "b"]}},
            accessories={"sandbox": {"host": "a"}},
        )


def test_env_values_are_strings_and_names_validated():
    p = project(
        env={"clear": {"LOG_LEVEL": "INFO", "WORKERS": 4, "DEBUG": False}})
    assert p.env.clear == {"LOG_LEVEL": "INFO",
                           "WORKERS": "4", "DEBUG": "false"}
    with pytest.raises(ValidationError, match="env var name"):
        project(env={"secret": ["claude-key"]})


def test_env_var_cannot_be_both_clear_and_secret():
    with pytest.raises(ValidationError, match="both env.clear and env.secret"):
        project(env={"clear": {"API_KEY": "x"}, "secret": ["API_KEY"]})
