import textwrap

import pytest

from jarviscore.project import ProjectError, build_env, find_root, load_project

BASE = """
service: support-bot
agents:
  triage:    { path: agents/triage.py }
  responder: { path: agents/responder.py, replicas: 2, env: { clear: { TONE: friendly } } }
env:
  clear: { LOG_LEVEL: DEBUG }
  secret: [CLAUDE_API_KEY]
"""


def write(root, name, text):
    (root / name).write_text(textwrap.dedent(text))


@pytest.fixture
def proj(tmp_path):
    write(tmp_path, "jarviscore.yaml", BASE)
    return tmp_path


def test_find_root_walks_up(proj):
    nested = proj / "agents" / "deep"
    nested.mkdir(parents=True)
    assert find_root(nested) == proj.resolve()


def test_find_root_missing_points_to_init(tmp_path):
    with pytest.raises(ProjectError, match="jarviscore init"):
        find_root(tmp_path)


def test_base_load_adds_local_redis_and_no_sandbox(proj):
    loaded = load_project(proj)
    acc = loaded.project.accessories
    assert loaded.environment == "development"
    assert "redis" in acc and not acc["redis"].external and acc["redis"].placed_on == [
    ]
    assert "sandbox" not in acc


def test_overlay_deep_merges_maps_and_replaces_lists(proj):
    write(proj, "jarviscore.prod.yaml", """
        servers: { main: 100.64.0.10 }
        env:
          clear: { LOG_LEVEL: INFO }
          secret: [CLAUDE_API_KEY, SLACK_TOKEN]
        accessories:
          redis: { url: "secret:REDIS_URL" }
    """)
    loaded = load_project(proj, destination="prod")
    p = loaded.project
    assert loaded.environment == "prod"
    assert [f.name for f in loaded.files] == [
        "jarviscore.yaml", "jarviscore.prod.yaml"]
    assert p.env.clear == {"LOG_LEVEL": "INFO"}
    assert p.env.secret == ["CLAUDE_API_KEY", "SLACK_TOKEN"]
    assert p.agents["responder"].replicas == 2
    assert p.accessories["redis"].external


def test_single_server_defaults_hosts_redis_and_sandbox(proj):
    write(proj, "jarviscore.prod.yaml", "servers: { main: 100.64.0.10 }\n")
    p = load_project(proj, destination="prod").project
    assert all(a.hosts == ["main"] for a in p.agents.values())
    assert p.accessories["redis"].placed_on == ["main"]
    assert p.accessories["sandbox"].placed_on == ["main"]


def test_multi_server_requires_explicit_redis(proj):
    write(proj, "jarviscore.prod.yaml", """
        servers: { a: h1, b: h2 }
        agents:
          triage:    { hosts: [a] }
          responder: { hosts: [a, b] }
    """)
    with pytest.raises(ProjectError, match="declare where Redis runs"):
        load_project(proj, destination="prod")


def test_multi_server_sandbox_defaults_to_every_agent_host(proj):
    write(proj, "jarviscore.prod.yaml", """
        servers: { a: h1, b: h2 }
        agents:
          triage:    { hosts: [a] }
          responder: { hosts: [b] }
        accessories:
          redis: { host: a }
    """)
    p = load_project(proj, destination="prod").project
    assert p.accessories["sandbox"].placed_on == ["a", "b"]


def test_missing_destination_lists_available(proj):
    write(proj, "jarviscore.staging.yaml", "{}\n")
    with pytest.raises(ProjectError, match="Available: staging"):
        load_project(proj, destination="prod")


def test_invalid_destination_name(proj):
    with pytest.raises(ProjectError, match="Invalid destination"):
        load_project(proj, destination="../etc")


def test_yaml_syntax_error_reports_file_and_line(proj):
    write(proj, "jarviscore.yaml", "service: bot\nagents: [unclosed\n")
    with pytest.raises(ProjectError, match=r"jarviscore\.yaml:\d+:\d+: invalid YAML"):
        load_project(proj)


def test_non_mapping_top_level(proj):
    write(proj, "jarviscore.yaml", "- just\n- a list\n")
    with pytest.raises(ProjectError, match="top level must be a mapping"):
        load_project(proj)


def test_typo_suggests_correct_key_and_names_file(proj):
    write(proj, "jarviscore.prod.yaml", "agents:\n  triage: { replica: 3 }\n")
    with pytest.raises(ProjectError) as exc:
        load_project(proj, destination="prod")
    text = str(exc.value)
    assert "jarviscore.prod.yaml: agents.triage.replica" in text
    assert "did you mean 'replicas'?" in text


def test_top_level_typo_suggestion(proj):
    write(proj, "jarviscore.yaml", BASE + "sevrers: {}\n")
    with pytest.raises(ProjectError, match="did you mean 'servers'"):
        load_project(proj)


def test_build_env_for_dev(proj):
    loaded = load_project(proj)
    env = build_env(loaded, "responder", endpoints={
                    "redis": "redis://localhost:6379/0"})
    assert env["JARVISCORE_SERVICE"] == "support-bot"
    assert env["JARVISCORE_ENV"] == "development"
    assert env["JARVISCORE_ROLE"] == "responder"
    assert env["LOG_LEVEL"] == "DEBUG" and env["TONE"] == "friendly"
    assert env["REDIS_URL"] == "redis://localhost:6379/0"
    assert "CLAUDE_API_KEY" not in env  # left to .env


def test_build_env_resolves_secrets_and_external_accessories(proj):
    write(proj, "jarviscore.prod.yaml", """
        servers: { main: h }
        accessories:
          redis: { url: "secret:REDIS_URL" }
          nexus: { url: https://nexus.internal }
    """)
    loaded = load_project(proj, destination="prod")
    env = build_env(loaded, "triage", secrets={
                    "CLAUDE_API_KEY": "sk-x", "REDIS_URL": "rediss://r:6380"})
    assert env["CLAUDE_API_KEY"] == "sk-x"
    assert env["REDIS_URL"] == "rediss://r:6380"
    assert env["NEXUS_GATEWAY_URL"] == "https://nexus.internal"
    assert "TONE" not in env


def test_agent_env_overrides_project_env(proj):
    write(proj, "jarviscore.yaml", BASE.replace(
        "TONE: friendly", "LOG_LEVEL: WARNING"))
    env = build_env(load_project(proj), "responder")
    assert env["LOG_LEVEL"] == "WARNING"
