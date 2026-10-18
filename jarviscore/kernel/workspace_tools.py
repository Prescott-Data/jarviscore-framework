"""File tools for a step that works on a workspace (a room, a repository, a folder).

Every Kernel sub-agent that does the work of a step bound to files gets
these tools, so the router can send a writing task to the writer and a
coding task to the coder and both can open and change the files. The tools
act through the step's sandbox, which is confined to the workspace root.
"""

from __future__ import annotations

from typing import Any, Callable, Dict

WORKSPACE_TOOL_NAMES = (
    "workspace_list", "workspace_read", "workspace_search", "workspace_write", "workspace_edit",
)


def register_workspace_tools(subagent, sandbox: Callable[[], Any], *, run: bool = False) -> None:
    """Register the file tools on ``subagent``; ``sandbox()`` returns the step's sandbox.

    ``run=True`` adds ``workspace_run`` for allow-listed commands (tests, builds).
    """

    def bound():
        box = sandbox()
        if box is None:
            return None, {"status": "error", "error": "No workspace is attached to this step."}
        return box, None

    def workspace_list(path: str = ".", recursive: bool = False, limit: int = 500, **_) -> Dict[str, Any]:
        box, error = bound()
        return error or box.list_workspace(path, recursive=recursive, limit=limit)

    def workspace_read(path: str, start_line: int = 1, end_line: int = 400, **_) -> Dict[str, Any]:
        box, error = bound()
        return error or box.read_workspace(path, start_line=start_line, end_line=end_line)

    def workspace_search(query: str, path: str = ".", glob: str = "*", regex: bool = False,
                         limit: int = 100, **_) -> Dict[str, Any]:
        box, error = bound()
        return error or box.search_workspace(query, path=path, glob=glob, regex=regex, limit=limit)

    def workspace_write(path: str, content: str, executable: bool = False, **_) -> Dict[str, Any]:
        box, error = bound()
        return error or box.write_workspace(path, content, executable=executable)

    def workspace_edit(path: str, start_line: int, end_line: int, replacement: str,
                       expected_sha256: str, **_) -> Dict[str, Any]:
        box, error = bound()
        return error or box.edit_workspace(path, start_line=start_line, end_line=end_line,
                                           replacement=replacement, expected_sha256=expected_sha256)

    def workspace_run(command: str, cwd: str = ".", **_) -> Dict[str, Any]:
        box, error = bound()
        return error or box.run_workspace(command, cwd=cwd)

    subagent.register_tool(
        "workspace_list", workspace_list,
        "List files or directories in the step's workspace. "
        "Params: {\"path\": \".\", \"recursive\": false, \"limit\": 500}",
        phase="thinking",
    )
    subagent.register_tool(
        "workspace_read", workspace_read,
        "Read a bounded UTF-8 line range from a workspace file. "
        "Params: {\"path\": \"README.md\", \"start_line\": 1, \"end_line\": 400}",
        phase="thinking",
    )
    subagent.register_tool(
        "workspace_search", workspace_search,
        "Search workspace text with literal matching by default and return file/line evidence. "
        "Params: {\"query\": \"TODO\", \"path\": \".\", \"glob\": \"*.md\", \"regex\": false, \"limit\": 100}",
        phase="thinking",
    )
    subagent.register_tool(
        "workspace_write", workspace_write,
        "Create or fully replace one UTF-8 file in the workspace. content must be the complete "
        "final file; use workspace_edit to change part of an existing file. Use this for new "
        "files, tests and fixtures instead of shell redirection, heredocs or writer scripts. "
        "The step's changes to the files are its work, which people review. "
        "Params: {\"path\": \"plan.md\", \"content\": \"<exact file content>\", \"executable\": false}",
        phase="action",
    )
    subagent.register_tool(
        "workspace_edit", workspace_edit,
        "Replace an inclusive line range in an existing UTF-8 file, keeping everything else. "
        "First call workspace_read and pass its sha256 as expected_sha256; a stale file fails "
        "closed. Params: {\"path\": \"plan.md\", \"start_line\": 12, \"end_line\": 14, "
        "\"replacement\": \"<complete replacement lines>\", \"expected_sha256\": \"<sha256>\"}",
        phase="action",
    )
    if run:
        subagent.register_tool(
            "workspace_run", workspace_run,
            "Run an allow-listed command in a workspace directory and return exit code/stdout/stderr. "
            "Params: {\"command\": \"python -m pytest -q\", \"cwd\": \".\"}",
            phase="action",
        )
