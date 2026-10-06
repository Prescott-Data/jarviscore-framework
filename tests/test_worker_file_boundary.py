import shutil

import pytest

from jarviscore.kernel.defaults.communicator import CommunicatorSubAgent
from jarviscore.kernel.defaults.researcher import ResearcherSubAgent


class LLM:
    async def generate(self, *args, **kwargs):
        return {"content": "", "tokens": {}, "cost_usd": 0.0}


def test_communicator_files_stay_inside_the_run_workspace(tmp_path):
    workspace = tmp_path / "run"
    workspace.mkdir()
    secret = tmp_path / "secret.env"
    secret.write_text("API_KEY=do-not-read")
    writer = CommunicatorSubAgent(agent_id="c1", llm_client=LLM())
    writer.workspace_root = workspace

    assert writer._tool_write_file("notes/plan.md", "Plan")["status"] == "success"
    assert (workspace / "notes" / "plan.md").read_text() == "Plan"
    assert writer._tool_read_file("notes/plan.md")["content"] == "Plan"

    for refused in (
        writer._tool_read_file(str(secret)),
        writer._tool_read_file("../secret.env"),
        writer._tool_write_file("../escape.txt", "x"),
        writer._tool_list_files(".."),
    ):
        assert refused["status"] == "error"
        assert "outside this run's workspace" in refused["error"]
    assert not (tmp_path / "escape.txt").exists()


def test_without_a_workspace_file_tools_are_unavailable(tmp_path):
    writer = CommunicatorSubAgent(agent_id="c1", llm_client=LLM())

    refused = writer._tool_write_file(str(tmp_path / "x.txt"), "x")

    assert refused["status"] == "error"
    assert not (tmp_path / "x.txt").exists()


@pytest.mark.asyncio
async def test_researcher_reads_and_searches_only_the_run_workspace(tmp_path):
    workspace = tmp_path / "run"
    workspace.mkdir()
    (workspace / "spec.yaml").write_text("needle: true\n")
    (tmp_path / "secret.env").write_text("needle=secret\n")
    researcher = ResearcherSubAgent(agent_id="r1", llm_client=LLM())
    researcher.workspace_root = workspace

    outside = await researcher._tool_read_file(file_path=str(tmp_path / "secret.env"))
    assert outside["status"] == "error"

    escaped = await researcher._tool_grep_codebase(pattern="needle", path="..", file_glob="*")
    assert escaped["status"] == "error"

    found = await researcher._tool_grep_codebase(pattern="needle", path=".", file_glob="*")
    assert {match["file"].rsplit("/", 1)[-1] for match in found["matches"]} == {"spec.yaml"}


@pytest.mark.asyncio
@pytest.mark.skipif(shutil.which("rg") is None, reason="ripgrep is not installed")
async def test_a_search_pattern_is_never_read_as_a_ripgrep_option(tmp_path):
    marker = tmp_path / "ran"
    program = tmp_path / "pre.sh"
    program.write_text(f"#!/bin/sh\ntouch {marker}\ncat \"$1\"\n")
    program.chmod(0o755)
    (tmp_path / "a.txt").write_text("hello\n")
    researcher = ResearcherSubAgent(agent_id="r1", llm_client=LLM())
    researcher.workspace_root = tmp_path

    result = await researcher._tool_grep_codebase(
        pattern=f"--pre={program}", path=".", file_glob="*.txt"
    )

    assert result["status"] == "success"
    assert not marker.exists()
