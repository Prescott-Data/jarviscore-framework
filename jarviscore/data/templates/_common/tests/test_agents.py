"""Every agent in jarviscore.yaml loads and resolves to exactly one agent."""

from pathlib import Path

import pytest

from jarviscore.cli.serve import load_agent_module, resolve_agent
from jarviscore.project import load_project

PROJECT = load_project(Path(__file__).resolve().parent.parent)


@pytest.mark.parametrize("name", list(PROJECT.project.agents))
def test_agent_file_resolves(name):
    spec = PROJECT.project.agents[name]
    agent = resolve_agent(load_agent_module(
        PROJECT.root, PROJECT.root / spec.path))
    assert agent.role and agent.capabilities
