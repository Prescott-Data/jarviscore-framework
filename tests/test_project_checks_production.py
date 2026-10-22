import json
import subprocess
import sys
import textwrap

import pytest

from jarviscore.project import load_project
from jarviscore.project.checks import ERROR, INFO, WARNING, CheckResult, has_errors
from jarviscore.project.checks.production import run_production_checks

GOOD_BASE = """
service: support-bot
agents:
  triage:    { path: agents/triage.py }
  responder: { path: agents/responder.py }
env:
  clear: { LOG_LEVEL: INFO, PROMETHEUS_ENABLED: "true" }
  secret: [CLAUDE_API_KEY]
llm: { rpm: 60 }
"""
GOOD_PROD = "servers: { main: 100.64.0.10 }\n"
GOOD_ENV = {"CLAUDE_API_KEY": "sk-test"}


def make(tmp_path, base=GOOD_BASE, prod=GOOD_PROD, dotenv=None):
    (tmp_path / "jarviscore.yaml").write_text(textwrap.dedent(base))
    (tmp_path / "jarviscore.prod.yaml").write_text(textwrap.dedent(prod))
    if dotenv is not None:
        (tmp_path / ".env").write_text(dotenv)
    return load_project(tmp_path, destination="prod")


def checks(loaded, environ=GOOD_ENV, **kwargs):
    results = run_production_checks(loaded, dict(environ), **kwargs)
    return results, {r.id: r for r in results}


def failing(results):
    return {r.id: r.severity for r in results if not r.ok}


def test_good_project_is_ready(tmp_path):
    results, _ = checks(make(tmp_path))
    assert failing(results) == {}
    assert not has_errors(results)


def test_no_servers(tmp_path):
    _, by_id = checks(make(tmp_path, prod="{}\n"))
    assert by_id["deploy.servers"].severity == ERROR and "jarviscore.prod.yaml" in by_id["deploy.servers"].fix


def test_provider_must_be_declared_not_just_present(tmp_path):
    base = GOOD_BASE.replace("secret: [CLAUDE_API_KEY]", "secret: []")
    _, by_id = checks(make(tmp_path, base=base))
    assert by_id["llm.provider"].severity == ERROR
    assert by_id["secrets.undeclared"].severity == WARNING
    assert "CLAUDE_API_KEY" in by_id["secrets.undeclared"].message


def test_declared_secret_without_value(tmp_path):
    _, by_id = checks(make(tmp_path), environ={})
    assert not by_id["llm.provider"].ok


def test_declared_secret_from_dotenv(tmp_path):
    _, by_id = checks(make(tmp_path, dotenv="CLAUDE_API_KEY=sk-from-dotenv\n"), environ={})
    assert by_id["llm.provider"].ok


def test_shell_variables_do_not_count_unless_declared(tmp_path):
    base = GOOD_BASE.replace("LOG_LEVEL: INFO, ", "")
    _, by_id = checks(make(tmp_path, base=base), environ={**GOOD_ENV, "LOG_LEVEL": "DEBUG"})
    assert by_id["logging.level"].ok  # shell DEBUG is not what gets deployed


@pytest.mark.parametrize("clear, check_id, severity", [
    ('LOG_LEVEL: DEBUG', "logging.level", ERROR),
    ('ALLOW_UNSAFE_LOCAL_EXECUTION: "true"', "sandbox.unsafe", ERROR),
    ('PROMETHEUS_ENABLED: "false"', "observability.prometheus", WARNING),
    ('P2P_ENABLED: "false"', "p2p.enabled", ERROR),
    ('STORAGE_BACKEND: azure', "storage.backend", ERROR),
    ('NEXUS_GATEWAY_URL: http://localhost:8090', "nexus.gateway", ERROR),
    ('OPENAI_API_KEY: sk-oops', "secrets.inline", ERROR),
])
def test_individual_rules(tmp_path, clear, check_id, severity):
    # Appended last, so it also overrides an existing key such as PROMETHEUS_ENABLED.
    base = GOOD_BASE.replace('PROMETHEUS_ENABLED: "true" }', f'PROMETHEUS_ENABLED: "true", {clear} }}')
    results, _ = checks(make(tmp_path, base=base))
    assert failing(results).get(check_id) == severity, failing(results)


def test_concurrency_warning_without_rpm_or_limit(tmp_path):
    _, by_id = checks(make(tmp_path, base=GOOD_BASE.replace("llm: { rpm: 60 }", "")))
    assert by_id["llm.concurrency"].severity == WARNING
    base = GOOD_BASE.replace("llm: { rpm: 60 }", "").replace("LOG_LEVEL: INFO", "LOG_LEVEL: INFO, LLM_MAX_CONCURRENT: 5")
    _, by_id = checks(make(tmp_path, base=base))
    assert by_id["llm.concurrency"].ok


def test_agent_level_override_is_reported_per_agent(tmp_path):
    base = GOOD_BASE.replace("responder: { path: agents/responder.py }",
                             "responder: { path: agents/responder.py, env: { clear: { LOG_LEVEL: DEBUG } } }")
    results, _ = checks(make(tmp_path, base=base))
    bad = [r for r in results if r.id == "logging.level" and not r.ok]
    assert len(bad) == 1 and "agents: responder" in bad[0].message


def test_nexus_needs_long_secret(tmp_path):
    prod = GOOD_PROD + "accessories:\n  nexus: { url: https://nexus.internal }\n"
    base = GOOD_BASE.replace("[CLAUDE_API_KEY]", "[CLAUDE_API_KEY, NEXUS_SECRET]")
    _, by_id = checks(make(tmp_path, base=base, prod=prod), environ={**GOOD_ENV, "NEXUS_SECRET": "short"})
    assert by_id["nexus.secret"].severity == ERROR
    _, by_id = checks(make(tmp_path, base=base, prod=prod), environ={**GOOD_ENV, "NEXUS_SECRET": "x" * 48})
    assert by_id["nexus.secret"].ok


def test_managed_redis_is_not_connected(tmp_path):
    calls = []
    _, by_id = checks(make(tmp_path), redis_checker=lambda *a, **k: calls.append(a) or [])
    assert by_id["redis.managed"].ok and calls == []


def test_external_redis_uses_secret_value_in_strict_mode(tmp_path):
    prod = GOOD_PROD + 'accessories:\n  redis: { url: "secret:REDIS_URL" }\n'
    seen = {}

    def fake(url, strict):
        seen.update(url=url, strict=strict)
        return [CheckResult("redis.reachable", INFO, True, "ok")]

    _, by_id = checks(make(tmp_path, prod=prod), environ={**GOOD_ENV, "REDIS_URL": "rediss://r:6380"},
                      redis_checker=fake)
    assert seen == {"url": "rediss://r:6380", "strict": True}
    assert by_id["redis.reachable"].ok


def test_external_redis_secret_missing(tmp_path):
    prod = GOOD_PROD + 'accessories:\n  redis: { url: "secret:REDIS_URL" }\n'
    _, by_id = checks(make(tmp_path, prod=prod))
    assert by_id["redis.url"].severity == ERROR and "REDIS_URL" in by_id["redis.url"].message


def test_no_connect_skips_redis(tmp_path):
    prod = GOOD_PROD + "accessories:\n  redis: { url: rediss://r:6380 }\n"
    _, by_id = checks(make(tmp_path, prod=prod), connect=False,
                      redis_checker=lambda *a, **k: pytest.fail("should not connect"))
    assert by_id["redis.reachable"].ok


# ── CLI ───────────────────────────────────────────────────────────────────

def _cli(tmp_path, *args, env=None):
    import os
    run_env = {k: v for k, v in os.environ.items() if k not in ("CLAUDE_API_KEY", "LOG_LEVEL")}
    run_env.update(env or {})
    return subprocess.run([sys.executable, "-m", "jarviscore.cli", "check", *args],
                          cwd=tmp_path, env=run_env, capture_output=True, text=True, check=False)


def test_cli_json_ready(tmp_path):
    make(tmp_path)
    out = _cli(tmp_path, "--profile", "prod", "-d", "prod", "--json", env=GOOD_ENV)
    assert out.returncode == 0, out.stdout + out.stderr
    data = json.loads(out.stdout)
    assert data["ok"] is True and data["environment"] == "prod"
    assert {"id", "severity", "ok", "message", "fix"} <= set(data["results"][0])


def test_cli_json_not_ready_exits_1(tmp_path):
    make(tmp_path)
    out = _cli(tmp_path, "--profile", "prod", "-d", "prod", "--json")
    assert out.returncode == 1
    assert json.loads(out.stdout)["ok"] is False


def test_cli_human_output_shows_fixes(tmp_path):
    make(tmp_path)
    out = _cli(tmp_path, "--profile", "prod", "-d", "prod")
    assert out.returncode == 1
    assert "✗ No LLM provider configured" in out.stdout and "→ Add e.g. CLAUDE_API_KEY" in out.stdout
    assert "Not ready: 1 error(s)" in out.stdout


def test_cli_without_project_exits_2(tmp_path):
    out = _cli(tmp_path, "--profile", "prod", "--json")
    assert out.returncode == 2 and "jarviscore init" in json.loads(out.stdout)["error"]


def test_cli_plain_check_still_runs_health_check(tmp_path):
    out = _cli(tmp_path)
    assert "JarvisCore Health Check" in out.stdout


@pytest.mark.parametrize("args", [["--json"], ["-d", "prod"], ["--no-connect"]])
def test_cli_profile_flags_without_profile_are_usage_errors(tmp_path, args):
    out = _cli(tmp_path, *args)
    assert out.returncode == 2
    assert out.stdout == "" and "requires --profile prod" in out.stderr


def test_cli_profile_defaults_to_the_prod_overlay(tmp_path):
    make(tmp_path)
    out = _cli(tmp_path, "--profile", "prod", "--json", env=GOOD_ENV)
    assert json.loads(out.stdout)["environment"] == "prod"
    human = _cli(tmp_path, "--profile", "prod", env=GOOD_ENV)
    assert "(prod, from jarviscore.prod.yaml" in human.stdout


def test_cli_profile_without_overlay_says_how_to_pick_one(tmp_path):
    (tmp_path / "jarviscore.yaml").write_text(textwrap.dedent(GOOD_BASE))
    out = _cli(tmp_path, "--profile", "prod", env=GOOD_ENV)
    assert "pass -d <env>" in out.stdout


def test_cli_project_error_goes_to_stderr(tmp_path):
    out = _cli(tmp_path, "--profile", "prod")
    assert out.returncode == 2 and "✗" in out.stderr and "✗" not in out.stdout
