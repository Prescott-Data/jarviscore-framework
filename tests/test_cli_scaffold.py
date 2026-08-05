"""Tests for jarviscore init: minimal-first env scaffolding."""

from pathlib import Path

from jarviscore.cli.scaffold import copy_env_example, get_data_path


def test_packaged_templates_exist_and_are_tracked():
    data = get_data_path()
    assert (data / ".env.minimal").exists()
    assert (data / ".env.example").exists()


def test_default_init_writes_the_minimal_template(tmp_path):
    assert copy_env_example(tmp_path, force=False) is True
    content = (tmp_path / ".env.example").read_text()
    lines = content.splitlines()
    assert len(lines) < 50, f"minimal template grew to {len(lines)} lines"
    for provider_key in ("CLAUDE_API_KEY", "AZURE_API_KEY", "GEMINI_API_KEY", "LLM_ENDPOINT"):
        assert provider_key in content
    assert "--full" in content       # points at the full reference


def test_full_flag_writes_the_complete_reference(tmp_path):
    assert copy_env_example(tmp_path, force=False, full=True) is True
    content = (tmp_path / ".env.example").read_text()
    assert len(content.splitlines()) > 100
    assert "P2P" in content


def test_existing_file_is_not_overwritten_without_force(tmp_path):
    (tmp_path / ".env.example").write_text("mine")
    assert copy_env_example(tmp_path, force=False) is False
    assert (tmp_path / ".env.example").read_text() == "mine"
    assert copy_env_example(tmp_path, force=True) is True
    assert (tmp_path / ".env.example").read_text() != "mine"


def test_minimal_template_has_no_em_dashes():
    data = get_data_path()
    assert "\u2014" not in (data / ".env.minimal").read_text()


def test_templates_resolve_from_repo_checkout():
    # get_data_path must resolve inside the source tree so fresh clones work
    data = get_data_path()
    assert (data / "__init__.py").exists(), (
        "jarviscore/data is missing from the checkout: the directory was "
        "gitignored by an unanchored 'data/' pattern"
    )
    assert Path(str(data)).name == "data"
