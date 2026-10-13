import stat
import subprocess
import sys

import pytest

from jarviscore.cli.project_init import TEMPLATES, InitError, create_project
from jarviscore.cli.serve import load_agent_module, resolve_agent
from jarviscore.project import load_project

EXPECTED_AGENTS = {
    "minimal": {"assistant"},
    "support": {"triage", "responder"},
    "research": {"researcher", "writer"},
    "pipeline": {"extractor", "analyst", "reporter"},
}


@pytest.mark.parametrize("template", list(TEMPLATES))
def test_template_generates_a_valid_project(tmp_path, template):
    result = create_project(tmp_path, "demo-bot", template)
    root = result.root
    assert root == tmp_path / "demo-bot"

    for rel in ("jarviscore.yaml", "pyproject.toml", ".gitignore", ".jarviscore/secrets",
                ".env", ".env.example", "tests/test_agents.py"):
        assert (root / rel).is_file(), rel
    assert not list(root.rglob("*.tmpl"))
    assert not list(root.rglob("dot_*"))
    for path in root.rglob("*"):
        if path.is_file():
            assert "{{" not in path.read_text(), path

    loaded = load_project(root)
    assert loaded.project.service == "demo-bot"
    assert set(loaded.project.agents) == EXPECTED_AGENTS[template]
    for name, spec in loaded.project.agents.items():
        agent = resolve_agent(load_agent_module(root, root / spec.path))
        assert agent.role == name


def test_pyproject_pins_current_framework(tmp_path):
    root = create_project(tmp_path, "demo", "minimal").root
    text = (root / "pyproject.toml").read_text()
    assert 'name = "demo"' in text
    assert "jarviscore-framework[p2p,redis]>=" in text


def test_gitignore_covers_local_secrets_and_build(tmp_path):
    lines = (create_project(tmp_path, "demo").root /
             ".gitignore").read_text().splitlines()
    for entry in (".env", ".jarviscore/secrets.local", ".jarviscore/build/"):
        assert entry in lines


def test_provider_credentials_go_to_env_and_refs_to_secrets(tmp_path):
    root = create_project(
        tmp_path, "demo", "support", provider="claude", credentials={"CLAUDE_API_KEY": "sk-test"},
    ).root
    env = (root / ".env").read_text()
    assert "CLAUDE_API_KEY=sk-test" in env
    assert stat.S_IMODE((root / ".env").stat().st_mode) == 0o600

    secrets = (root / ".jarviscore/secrets").read_text()
    assert "CLAUDE_API_KEY=$CLAUDE_API_KEY" in secrets
    assert "sk-test" not in secrets
    assert load_project(root).project.env.secret == ["CLAUDE_API_KEY"]


def test_azure_writes_all_three_settings(tmp_path):
    root = create_project(tmp_path, "demo", provider="azure", credentials={
        "AZURE_API_KEY": "k", "AZURE_ENDPOINT": "https://x.openai.azure.com",
    }).root
    env = (root / ".env").read_text()
    assert "AZURE_API_KEY=k" in env and "AZURE_ENDPOINT=https://x.openai.azure.com" in env
    assert "# AZURE_DEPLOYMENT=" in env
    assert load_project(root).project.env.secret == ["AZURE_API_KEY"]


def test_no_provider_leaves_placeholders(tmp_path):
    root = create_project(tmp_path, "demo").root
    assert "# CLAUDE_API_KEY=" in (root / ".env").read_text()
    assert load_project(root).project.env.secret == []


@pytest.mark.parametrize("kwargs, message", [
    ({"name": "Demo"}, "Project name"),
    ({"name": "demo", "template": "nope"}, "Unknown template"),
    ({"name": "demo", "provider": "openrouter"}, "Unknown provider"),
])
def test_invalid_inputs(tmp_path, kwargs, message):
    with pytest.raises(InitError, match=message):
        create_project(tmp_path, **kwargs)


def test_refuses_non_empty_directory_without_force(tmp_path):
    (tmp_path / "demo").mkdir()
    (tmp_path / "demo" / "keep.txt").write_text("mine")
    with pytest.raises(InitError, match="not empty"):
        create_project(tmp_path, "demo")
    create_project(tmp_path, "demo", force=True)
    assert (tmp_path / "demo" / "keep.txt").read_text() == "mine"


def _cli(*args, cwd):
    return subprocess.run(
        [sys.executable, "-m", "jarviscore.cli", "init", *args],
        cwd=cwd, capture_output=True, text=True, stdin=subprocess.DEVNULL, check=False,
    )


def test_cli_named_init_is_non_interactive_without_tty(tmp_path):
    out = _cli("demo", "--template", "research",
               "--provider", "gemini", cwd=tmp_path)
    assert out.returncode == 0, out.stdout + out.stderr
    assert "Created demo/" in out.stdout and "jarviscore dev" in out.stdout
    assert (tmp_path / "demo" / "agents" / "writer.py").is_file()
    assert "# GEMINI_API_KEY=" in (tmp_path / "demo" / ".env").read_text()


def test_cli_named_init_reports_errors(tmp_path):
    out = _cli("Bad_Name", cwd=tmp_path)
    assert out.returncode == 2 and "Project name" in out.stdout


def test_cli_plain_init_is_unchanged(tmp_path):
    out = _cli("--dir", str(tmp_path), cwd=tmp_path)
    assert out.returncode == 0, out.stdout + out.stderr
    assert sorted(p.name for p in tmp_path.iterdir()) == [".env.example"]


def test_generated_project_tests_pass(tmp_path):
    root = create_project(tmp_path, "demo", "pipeline").root
    out = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"],
        cwd=root, capture_output=True, text=True, check=False,
    )
    assert out.returncode == 0, out.stdout + out.stderr
    assert "3 passed" in out.stdout
