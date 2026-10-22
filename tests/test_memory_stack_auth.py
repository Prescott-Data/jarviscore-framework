"""The bundled Athena stack runs with authentication and an initialised LTM graph."""
from pathlib import Path

import jarviscore.cli.memory as memory_cli

COMPOSE = Path(memory_cli.__file__).resolve().parents[1] / "memory" / "_data" / "docker-compose.athena.yml"


def test_stack_requires_a_service_key():
    text = COMPOSE.read_text()
    assert 'MEMORY_OS_REQUIRE_API_KEY: "true"' in text
    # JarvisCore serves many tenants, so its key is a service key ("<key>=*").
    assert "MEMORY_OS_API_KEYS: \"${ATHENA_API_KEY:?" in text and "}=*\"" in text
    assert "default-api-key" not in text


def test_stack_initialises_the_ltm_graph_before_athena_starts():
    text = COMPOSE.read_text()
    assert 'command: ["./init-ltm"]' in text
    assert "athena-ltm-init:\n        condition: service_completed_successfully" in text


def test_dotenv_value(tmp_path):
    env = tmp_path / ".env"
    assert memory_cli._dotenv_value(env, "ATHENA_API_KEY") == ""
    env.write_text("ATHENA_URL=http://x\nATHENA_API_KEY = 'abc'\n# ATHENA_API_KEY=commented\n")
    assert memory_cli._dotenv_value(env, "ATHENA_API_KEY") == "abc"
    assert memory_cli._dotenv_value(env, "MISSING") == ""


def _azure(monkeypatch, replies):
    calls = []

    def post(url, key, body):
        calls.append(body)
        return replies.pop(0)

    monkeypatch.setattr(memory_cli, "_post_json", post)
    monkeypatch.setenv("ATHENA_LLM_BASE_URL", "https://r/chat")
    monkeypatch.setenv("ATHENA_EMBEDDING_BASE_URL", "https://r/embed")
    monkeypatch.delenv("ATHENA_LLM_REASONING", raising=False)
    return calls


def test_a_reasoning_deployment_is_recognised_not_reported_missing(monkeypatch, capsys):
    import os
    calls = _azure(monkeypatch, [(400, "Use 'max_completion_tokens' instead."), (200, "{}"), (200, "{}")])
    memory_cli._check_azure_deployments("k", "gpt-5", "emb")
    assert "max_completion_tokens" in calls[1]
    assert os.environ["ATHENA_LLM_REASONING"] == "true"
    assert "did not answer" not in capsys.readouterr().out


def test_a_missing_deployment_is_reported(monkeypatch, capsys):
    import os
    _azure(monkeypatch, [(404, "DeploymentNotFound"), (200, "{}")])
    memory_cli._check_azure_deployments("k", "nope", "emb")
    assert "'nope' did not answer" in capsys.readouterr().out
    assert "ATHENA_LLM_REASONING" not in os.environ


def test_stack_passes_reasoning_detection_to_athena():
    assert "LLM_REASONING_MODEL: ${ATHENA_LLM_REASONING:-false}" in COMPOSE.read_text()


def test_dotenv_without_trailing_newline_keeps_lines_apart(tmp_path):
    env = tmp_path / ".env"
    env.write_text("ATHENA_URL=http://x\nOPENAI_API_KEY=sk-abc")
    memory_cli._append_dotenv(env, "ATHENA_API_KEY", "k")
    assert memory_cli._dotenv_value(env, "OPENAI_API_KEY") == "sk-abc"
    assert memory_cli._dotenv_value(env, "ATHENA_API_KEY") == "k"
    memory_cli._append_dotenv(tmp_path / "new.env", "ATHENA_URL", "http://y")
    assert (tmp_path / "new.env").read_text() == "ATHENA_URL=http://y\n"
