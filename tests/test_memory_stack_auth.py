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
