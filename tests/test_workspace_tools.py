import asyncio
import shlex
import time
from unittest.mock import MagicMock

import pytest

from jarviscore.execution import BashPermissionError, create_coder_sandbox
from jarviscore.kernel.defaults.coder import CoderSubAgent
from jarviscore.kernel.state import KernelState


def test_workspace_tools_list_read_and_search_bound_files(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src/main.py").write_text("def run():\n    return 'needle'\n")
    sandbox = create_coder_sandbox(workspace_dir=tmp_path)

    listing = sandbox.list_workspace("src")
    reading = sandbox.read_workspace("src/main.py", start_line=1, end_line=2)
    search = sandbox.search_workspace("needle", glob="*.py")

    assert listing["entries"] == [
        {"path": "src/main.py", "kind": "file", "size": 31}
    ]
    assert reading["content"] == "def run():\n    return 'needle'"
    assert search["matches"][0]["path"] == "src/main.py"
    assert search["matches"][0]["line"] == 2


def test_workspace_tools_reject_path_escape(tmp_path):
    sandbox = create_coder_sandbox(workspace_dir=tmp_path)

    with pytest.raises(ValueError, match="escapes"):
        sandbox.read_workspace("../outside.txt")
    with pytest.raises(ValueError, match="escapes"):
        sandbox.write_workspace("../outside.txt", "blocked")


def test_workspace_search_skips_symlinks_to_files_outside_workspace(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("private needle\n")
    (workspace / "outside-link.txt").symlink_to(outside)
    (workspace / "inside.txt").write_text("public needle\n")
    sandbox = create_coder_sandbox(workspace_dir=workspace)

    result = sandbox.search_workspace("needle", glob="*.txt")

    assert result == {
        "status": "success",
        "matches": [{"path": "inside.txt", "line": 1, "text": "public needle"}],
        "truncated": False,
    }


def test_workspace_write_creates_bounded_fixture_without_shell(tmp_path):
    sandbox = create_coder_sandbox(workspace_dir=tmp_path)
    content = '{"value": "line one\\nline two"}\n'

    result = sandbox.write_workspace("tests/fixtures/case.json", content)

    assert result["status"] == "success"
    assert result["bytes"] == len(content.encode())
    assert (tmp_path / "tests/fixtures/case.json").read_text() == content
    assert sandbox.write_workspace("too-large.txt", "abc", max_bytes=2) == {
        "status": "error",
        "path": "too-large.txt",
        "error": "Workspace write exceeds 2 bytes",
    }


def test_workspace_edit_replaces_only_hash_guarded_line_range(tmp_path):
    path = tmp_path / "src/main.rs"
    path.parent.mkdir()
    path.write_text("first\nold one\nold two\nlast\n")
    sandbox = create_coder_sandbox(workspace_dir=tmp_path)
    source = sandbox.read_workspace("src/main.rs", start_line=2, end_line=3)

    result = sandbox.edit_workspace(
        "src/main.rs",
        2,
        3,
        "new one\nnew two",
        source["sha256"],
    )

    assert result["status"] == "success"
    assert path.read_text() == "first\nnew one\nnew two\nlast\n"
    assert sandbox.edit_workspace(
        "src/main.rs",
        2,
        3,
        "stale",
        source["sha256"],
    )["status"] == "conflict"


def test_workspace_run_uses_existing_bash_allow_list(tmp_path):
    (tmp_path / "value.txt").write_text("42\n")
    sandbox = create_coder_sandbox(workspace_dir=tmp_path)

    success = sandbox.run_workspace("cat value.txt")
    assert success["success"] is True
    assert success["stdout"] == "42"
    assert sandbox.run_workspace("pwd")["success"] is True

    with pytest.raises(BashPermissionError):
        sandbox.run_workspace("uname -a")


def test_workspace_run_accepts_explicit_domain_commands(tmp_path, monkeypatch):
    sandbox = create_coder_sandbox(
        workspace_dir=tmp_path,
        allowed_commands={"cargo"},
    )
    monkeypatch.setattr(
        sandbox._bash,
        "_run",
        lambda command, cwd=None: {
            "success": True,
            "stdout": command,
            "stderr": "",
            "returncode": 0,
        },
    )

    assert "cargo" in sandbox._bash.allowed_commands
    assert sandbox.run_workspace("cargo test")["success"] is True


def test_workspace_run_does_not_inherit_parent_secrets(tmp_path, monkeypatch):
    monkeypatch.setenv("WORKSPACE_SECRET", "must-not-leak")
    sandbox = create_coder_sandbox(workspace_dir=tmp_path)

    result = sandbox.run_workspace(
        "python -c \"import os; print(os.getenv('WORKSPACE_SECRET', 'missing'))\""
    )

    assert result["success"] is True
    assert result["stdout"] == "missing"


def test_workspace_run_keeps_tool_home_state_out_of_source_root(tmp_path):
    sandbox = create_coder_sandbox(workspace_dir=tmp_path)
    command = (
        "python -c \"import os; from pathlib import Path; "
        "home = Path(os.environ['HOME']); "
        "(home / 'tool-state').write_text('state'); print(home)\""
    )

    result = sandbox.run_workspace(command)

    expected_home = tmp_path / ".tmp" / "home"
    assert result["success"] is True
    assert result["stdout"] == str(expected_home)
    assert (expected_home / "tool-state").read_text() == "state"
    assert not (tmp_path / "tool-state").exists()


def test_workspace_run_receives_only_trusted_build_environment(tmp_path, monkeypatch):
    cache = tmp_path / "shared-cargo"
    monkeypatch.setenv("WORKSPACE_SECRET", "must-not-leak")
    sandbox = create_coder_sandbox(
        workspace_dir=tmp_path / "workspace",
        command_environment={
            "CARGO_HOME": str(cache),
            "WORKSPACE_SECRET": "also-must-not-leak",
        },
    )

    result = sandbox.run_workspace(
        "python -c \"import os; print(os.getenv('CARGO_HOME')); print(os.getenv('WORKSPACE_SECRET', 'missing'))\""
    )

    assert result["success"] is True
    assert result["stdout"].splitlines() == [str(cache), "missing"]
    assert cache.is_dir()


def test_workspace_clone_accepts_trusted_command_timeout_and_cache(tmp_path):
    original = create_coder_sandbox(workspace_dir=tmp_path / "original")
    cache = tmp_path / "cache"

    bound = original.for_workspace(
        tmp_path / "bound",
        bash_timeout=600,
        command_environment={"CARGO_HOME": str(cache)},
    )

    assert bound._bash.timeout == 600
    assert bound._bash.command_environment == {"CARGO_HOME": str(cache)}


def test_workspace_run_rejects_command_substitution(tmp_path):
    sandbox = create_coder_sandbox(workspace_dir=tmp_path)

    with pytest.raises(BashPermissionError, match="substitution"):
        sandbox.run_workspace("echo $(pwd)")


def test_workspace_run_validates_every_chained_command(tmp_path):
    sandbox = create_coder_sandbox(workspace_dir=tmp_path)

    with pytest.raises(BashPermissionError, match="uname"):
        sandbox.run_workspace("echo safe && uname -a")
    with pytest.raises(BashPermissionError, match="redirection"):
        sandbox.run_workspace("echo unsafe > outside.txt")

    result = sandbox.run_workspace("echo one && echo two")
    assert result["success"] is True
    assert result["stdout"] == "one\ntwo"


def test_workspace_run_rejects_background_command_bypass(tmp_path):
    sandbox = create_coder_sandbox(workspace_dir=tmp_path)

    with pytest.raises(BashPermissionError, match="Background"):
        sandbox.run_workspace("echo safe & uname -a")


def test_workspace_run_rejects_pipe_ampersand_bypass(tmp_path):
    sandbox = create_coder_sandbox(workspace_dir=tmp_path)

    with pytest.raises(BashPermissionError, match="Unsupported shell operator"):
        sandbox.run_workspace("echo safe |& uname -a")


@pytest.mark.parametrize("cwd", ["/", "/tmp", "../outside"])
def test_workspace_run_rejects_cwd_outside_workspace(tmp_path, cwd):
    sandbox = create_coder_sandbox(workspace_dir=tmp_path / "workspace")

    with pytest.raises(BashPermissionError, match="escapes workspace"):
        sandbox._bash("pwd", cwd=cwd)


def test_workspace_run_accepts_cwd_inside_workspace(tmp_path):
    workspace = tmp_path / "workspace"
    nested = workspace / "nested"
    nested.mkdir(parents=True)
    sandbox = create_coder_sandbox(workspace_dir=workspace)

    result = sandbox._bash("pwd", cwd="nested")

    assert result["success"] is True
    assert result["stdout"] == str(nested)


def test_workspace_run_timeout_kills_child_processes(tmp_path):
    marker = tmp_path / "orphaned.txt"
    child = (
        "import time; from pathlib import Path; time.sleep(0.5); "
        f"Path({str(marker)!r}).write_text('orphaned')"
    )
    parent = (
        "import subprocess, sys, time; "
        f"subprocess.Popen([sys.executable, '-c', {child!r}]); "
        "time.sleep(30)"
    )
    sandbox = create_coder_sandbox(workspace_dir=tmp_path, bash_timeout=0.1)

    result = sandbox.run_workspace(f"python -c {shlex.quote(parent)}")
    time.sleep(0.7)

    assert result["status"] == "timeout"
    assert not marker.exists()


@pytest.mark.asyncio
async def test_generated_code_receives_explicit_command_on_path(tmp_path):
    sandbox = create_coder_sandbox(
        workspace_dir=tmp_path,
        allowed_commands={"pwd"},
    )

    result = await sandbox.execute(
        "response = bash('pwd')\nresult = {'returncode': response['returncode']}"
    )

    assert result["status"] == "success"
    assert result["data"] == {"returncode": 0}


@pytest.mark.asyncio
async def test_sandbox_timeout_kills_grandchildren(tmp_path):
    sandbox = create_coder_sandbox(workspace_dir=tmp_path)
    marker = tmp_path / "orphaned.txt"
    child = (
        "import time\n"
        "from pathlib import Path\n"
        "time.sleep(0.5)\n"
        f"Path({str(marker)!r}).write_text('orphaned')\n"
    )
    code = (
        "import subprocess, sys, time\n"
        f"subprocess.Popen([sys.executable, '-c', {child!r}])\n"
        "time.sleep(30)\n"
        "result = {}\n"
    )

    result = await sandbox.execute(code, timeout=0.1)
    await asyncio.sleep(0.7)

    assert result["error_type"] == "ExecutionTimeout"
    assert not marker.exists()


@pytest.mark.asyncio
async def test_sandbox_cancels_rpc_task_after_child_exits(tmp_path, monkeypatch):
    sandbox = create_coder_sandbox(workspace_dir=tmp_path)
    cancelled = asyncio.Event()

    async def hanging_rpc(sock, context):
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    monkeypatch.setattr(sandbox, "_serve_child_rpc", hanging_rpc)

    result = await asyncio.wait_for(
        sandbox.execute("result = {'ok': True}"),
        timeout=10.0,
    )

    assert result["status"] == "success"
    assert cancelled.is_set()


def test_workspace_tools_handle_symlinked_workspace_ancestors(tmp_path, monkeypatch):
    real = tmp_path / "real"
    real.mkdir()
    (real / "value.txt").write_text("needle\n")
    alias = tmp_path / "alias"
    alias.symlink_to(real, target_is_directory=True)
    sandbox = create_coder_sandbox(workspace_dir=alias)

    paths = {entry["path"] for entry in sandbox.list_workspace()["entries"]}
    assert "value.txt" in paths
    assert sandbox.search_workspace("needle")["matches"][0]["path"] == "value.txt"


def test_coder_offers_workspace_tools_without_codegen(tmp_path):
    sandbox = create_coder_sandbox(workspace_dir=tmp_path)
    coder = CoderSubAgent(
        agent_id="workspace-coder",
        llm_client=MagicMock(),
        sandbox=sandbox,
    )

    assert {
        "workspace_list",
        "workspace_read",
        "workspace_search",
        "workspace_write",
        "workspace_run",
    } <= set(coder._tools)

    state = MagicMock(tool_history=[])
    state.turn = 0
    prompt = coder._build_user_prompt(state, "context")
    assert "workspace_list" in prompt
    assert "workspace_read" in prompt
    assert "workspace_write" in prompt
    assert coder._tools["write_code"].phase == "thinking"
    assert coder._tools["validate_code"].phase == "thinking"
    assert coder._tools["execute_code"].phase == "action"


def test_coder_completion_observes_product_declared_tool_evidence(tmp_path):
    sandbox = create_coder_sandbox(workspace_dir=tmp_path)
    coder = CoderSubAgent(
        agent_id="workspace-coder",
        llm_client=MagicMock(),
        sandbox=sandbox,
    )
    state = KernelState(
        workflow_id="wf-evidence",
        step_id="build",
        agent_id="workspace-coder",
        task="Verify build",
        context={
            "execution_contract": {
                "required_tool_groups": [
                    ["workspace_read", "read_file"],
                    ["workspace_run"],
                ]
            }
        },
    )
    state.add_tool_result("workspace_read", {"path": "Cargo.toml"}, {"status": "success"})

    allowed, evidence = coder._can_complete(state, {"result": {"status": "incomplete"}})

    assert allowed is False
    assert evidence.check == "declared_action_evidence"
    assert evidence.observed["missing_tool_groups"] == [["workspace_run"]]
    state.add_tool_result("workspace_run", {"command": "cargo test"}, {"success": True})
    allowed, _ = coder._can_complete(state, {"result": {"status": "success"}})
    assert allowed is True