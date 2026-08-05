"""Tests for jarviscore init --skill: AI editor skill installation."""

from pathlib import Path

import jarviscore
from jarviscore.cli.scaffold import copy_skill

_SKILL = Path(jarviscore.__file__).parent / "skills" / "jarviscore" / "SKILL.md"


def test_packaged_skill_exists_with_valid_frontmatter():
    skill = Path(str(__import__("importlib.resources", fromlist=["files"]).files("jarviscore"))) / "skills" / "jarviscore" / "SKILL.md"
    assert skill.exists()
    text = skill.read_text()
    assert text.startswith("---\n")
    assert "name: jarviscore" in text
    assert "description:" in text
    assert "\u2014" not in text                       # house style: no em dashes


def test_skill_installs_to_both_editor_locations(tmp_path):
    assert copy_skill(tmp_path, force=False) is True
    for editor_dir in (".github", ".claude"):
        dest = tmp_path / editor_dir / "skills" / "jarviscore" / "SKILL.md"
        assert dest.exists()
        assert "AutoAgent" in dest.read_text()


def test_skill_does_not_overwrite_without_force(tmp_path):
    target = tmp_path / ".github" / "skills" / "jarviscore" / "SKILL.md"
    target.parent.mkdir(parents=True)
    target.write_text("customised")
    copy_skill(tmp_path, force=False)
    assert target.read_text() == "customised"        # preserved
    assert (tmp_path / ".claude" / "skills" / "jarviscore" / "SKILL.md").exists()
    copy_skill(tmp_path, force=True)
    assert target.read_text() != "customised"        # force overwrites


def test_skill_teaches_the_real_api_surface():
    """The skill must never drift from the code it describes."""
    text = (Path(str(__import__("importlib.resources", fromlist=["files"]).files("jarviscore"))) / "skills" / "jarviscore" / "SKILL.md").read_text()
    from jarviscore.profiles import AutoAgent, CustomAgent  # noqa: F401  (import = contract)

    for claim in ("mesh.run_task", "mesh.workflow", "await mesh.start()",
                  "system_prompt", "goal_oriented", "on_peer_request"):
        assert claim in text, f"skill lost the {claim} contract"
