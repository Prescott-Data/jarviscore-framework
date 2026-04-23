"""
CoderSandbox — File-Capable Execution Engine for the Coder Agent
=================================================================
A deliberate extension of JarvisCore's sandboxing model that grants
file system and subprocess access, scoped to a controlled workspace.

Design principles:
  - The existing SandboxExecutor blocks `open` for *API agents* (correct).
  - This sandbox *intentionally opens* file + subprocess access for the
    Coder agent only. The security boundary is the workspace directory
    and the bash allow-list, not Python builtins.
  - Result contract: always returns a CoderResult with structured output
    including file paths, git state, stdout, and errors.
  - Same repair & timeout guarantees as SandboxExecutor.

Output contract (result variable in generated code):
    result = {
        "success": bool,
        "files_created": [str],   # absolute paths written
        "files_modified": [str],  # absolute paths modified
        "git_branch": str | None, # branch name if git ops performed
        "stdout": str,            # captured print() output
        "data": Any,              # any structured return data
        "error": str | None,
    }
"""
import ast
import asyncio
import io
import logging
import os
import re
import shlex
import subprocess
import sys
import time
from contextlib import redirect_stdout
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────
# Result Model
# ─────────────────────────────────────────────────────────────────

@dataclass
class CoderResult:
    """Structured result from a CoderSandbox execution."""
    success: bool
    files_created: List[str] = field(default_factory=list)
    files_modified: List[str] = field(default_factory=list)
    git_branch: Optional[str] = None
    stdout: str = ""
    data: Any = None
    error: Optional[str] = None
    error_type: Optional[str] = None
    execution_time: float = 0.0

    def to_dict(self) -> Dict:
        return {
            "success": self.success,
            "files_created": self.files_created,
            "files_modified": self.files_modified,
            "git_branch": self.git_branch,
            "stdout": self.stdout,
            "data": self.data,
            "error": self.error,
            "error_type": self.error_type,
            "execution_time": self.execution_time,
        }


# ─────────────────────────────────────────────────────────────────
# Bash Allow-List
# ─────────────────────────────────────────────────────────────────

# Commands the Coder is permitted to run via bash_exec().
# Anything not in this list raises PermissionError.
_BASH_ALLOW_LIST = {
    # Git operations — the primary use case
    "git",
    # Package/file utilities
    "pip", "pip3",
    "cp", "mv", "mkdir", "rm", "ls", "cat", "echo", "touch",
    "find", "grep", "sed", "awk", "sort", "uniq", "head", "tail", "wc",
    # Format / convert utilities
    "pandoc", "convert", "ffmpeg", "magick",
    # Node/npm for frontend work
    "npm", "npx", "node",
    # Python itself (for running sub-scripts)
    "python", "python3",
    # curl for quick HTTP (auth-free only — no token flags validated here)
    "curl",
}

# Hard-blocked regardless of allow-list (defense in depth)
_BASH_DENY_PATTERNS = [
    r"rm\s+-rf\s+/",       # rm -rf /
    r">\s*/dev/sd",         # overwrite block devices
    r"chmod\s+777",         # world-writable
    r"sudo",                # privilege escalation
    r"&&\s*rm",             # chained delete after another command
    r"\|\s*sh",             # pipe to shell
    r"\|\s*bash",           # pipe to bash
    r"eval\s",              # eval
    r"curl.*\|\s*(bash|sh)",# curl | bash
]


class BashPermissionError(PermissionError):
    """Raised when a bash command is not on the allow-list."""
    pass


# ─────────────────────────────────────────────────────────────────
# BashExecutor
# ─────────────────────────────────────────────────────────────────

class BashExecutor:
    """
    Controlled subprocess runner with allow-list enforcement.

    Used by CoderSandbox.bash_exec() and available inside generated
    code as the `bash` callable in the namespace.

    Example (inside generated code):
        result_bash = bash("git checkout -b feat/seo-updates")
        result_bash = bash("git add . && git commit -m 'SEO: update meta tags'")
    """

    def __init__(self, workspace_dir: Path, timeout: int = 120):
        self.workspace = workspace_dir
        self.timeout = timeout

    def __call__(self, command: str, cwd: Optional[str] = None) -> Dict[str, Any]:
        """
        Execute a shell command. Synchronous — run from thread pool inside sandbox.

        Args:
            command: Shell command string (not a list).
            cwd: Working directory override. Defaults to workspace_dir.

        Returns:
            {"success": bool, "stdout": str, "stderr": str, "returncode": int}
        """
        return self._run(command, cwd)

    def _run(self, command: str, cwd: Optional[str] = None) -> Dict[str, Any]:
        # Security: check against deny patterns first
        for pattern in _BASH_DENY_PATTERNS:
            if re.search(pattern, command, re.IGNORECASE):
                raise BashPermissionError(
                    f"Command blocked by deny pattern '{pattern}': {command!r}"
                )

        # Security: check allow-list (first token of command)
        try:
            tokens = shlex.split(command)
        except ValueError as e:
            return {"success": False, "stdout": "", "stderr": f"Invalid command syntax: {e}", "returncode": -1}

        if not tokens:
            return {"success": False, "stdout": "", "stderr": "Empty command", "returncode": -1}

        base_cmd = os.path.basename(tokens[0])  # handle /usr/bin/git → git
        if base_cmd not in _BASH_ALLOW_LIST:
            raise BashPermissionError(
                f"Command '{base_cmd}' is not on the Coder allow-list. "
                f"Allowed: {sorted(_BASH_ALLOW_LIST)}"
            )

        work_dir = Path(cwd) if cwd else self.workspace
        if not work_dir.exists():
            work_dir.mkdir(parents=True, exist_ok=True)

        try:
            proc = subprocess.run(
                command,
                shell=True,
                cwd=str(work_dir),
                capture_output=True,
                text=True,
                timeout=self.timeout,
            )
            return {
                "success": proc.returncode == 0,
                "stdout": proc.stdout.strip(),
                "stderr": proc.stderr.strip(),
                "returncode": proc.returncode,
            }
        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "stdout": "",
                "stderr": f"Command timed out after {self.timeout}s",
                "returncode": -1,
            }
        except Exception as e:
            return {
                "success": False,
                "stdout": "",
                "stderr": str(e),
                "returncode": -1,
            }


# ─────────────────────────────────────────────────────────────────
# GitHelper — convenience on top of BashExecutor
# ─────────────────────────────────────────────────────────────────

class GitHelper:
    """
    High-level git operations for the Coder agent.

    Available inside generated code as the `git` object.

    Example:
        git.checkout_branch("feat/seo-2026-04-21")
        git.add_all()
        git.commit("SEO: fix meta descriptions on /pricing")
        git.push()
        pr_info = git.describe_pr("Fix broken meta tags", "Updates 3 pages to match brand standards")
    """

    def __init__(self, bash: BashExecutor, workspace_dir: Path):
        self._bash = bash
        self.workspace = workspace_dir

    def checkout_branch(self, branch_name: str) -> Dict[str, Any]:
        """Create and checkout a new branch (or checkout existing)."""
        # Try creating new branch first
        r = self._bash(f"git checkout -b {shlex.quote(branch_name)}")
        if not r["success"] and "already exists" in r["stderr"]:
            r = self._bash(f"git checkout {shlex.quote(branch_name)}")
        return r

    def add(self, path: str = ".") -> Dict[str, Any]:
        return self._bash(f"git add {shlex.quote(path)}")

    def add_all(self) -> Dict[str, Any]:
        return self._bash("git add -A")

    def commit(self, message: str) -> Dict[str, Any]:
        return self._bash(f"git commit -m {shlex.quote(message)}")

    def push(self, remote: str = "origin", branch: Optional[str] = None) -> Dict[str, Any]:
        if branch:
            return self._bash(f"git push {remote} {shlex.quote(branch)}")
        return self._bash(f"git push {remote} HEAD")

    def current_branch(self) -> str:
        r = self._bash("git rev-parse --abbrev-ref HEAD")
        return r["stdout"].strip() if r["success"] else "unknown"

    def status(self) -> Dict[str, Any]:
        return self._bash("git status --short")

    def diff(self, staged: bool = True) -> str:
        flag = "--cached" if staged else ""
        r = self._bash(f"git diff {flag}")
        return r["stdout"]

    def describe_pr(self, title: str, body: str) -> Dict[str, Any]:
        """
        Returns a PR description dict (for Muyukani to open manually or
        for gh CLI if available).
        """
        branch = self.current_branch()
        diff_stat = self._bash("git diff HEAD~1 --stat").get("stdout", "")
        return {
            "title": title,
            "body": body,
            "branch": branch,
            "diff_stat": diff_stat,
            "gh_command": f"gh pr create --title {shlex.quote(title)} --body {shlex.quote(body)}",
        }


# ─────────────────────────────────────────────────────────────────
# CoderSandbox
# ─────────────────────────────────────────────────────────────────

class CoderSandbox:
    """
    File-capable execution sandbox for the Coder agent.

    Unlike SandboxExecutor (which blocks `open`, `exec`, `subprocess`),
    this sandbox *intentionally grants* those capabilities — scoped to
    workspace_dir and gated by the bash allow-list.

    Namespace injected into generated code:
        - workspace      : Path — the allowed working directory
        - bash(cmd)      : BashExecutor call — controlled subprocess
        - git            : GitHelper — high-level git ops
        - nexus_call     : async fn(method, url, **kwargs) → HTTP response via Nexus
        - Path           : pathlib.Path — for path manipulation
        - common libs    : json, os, re, datetime, dataclasses, etc.
        - blob_path(name): helper to get a path inside workspace/output/

    Agents NEVER see raw credentials — nexus_call() internally resolves
    the DynamicStrategy via NexusCallProxy.
    """

    def __init__(
        self,
        workspace_dir: Optional[Path] = None,
        timeout: int = 300,
        bash_timeout: int = 120,
        output_subdir: str = "output",
        nexus_call_proxy=None,  # Optional[NexusCallProxy]
    ):
        self.workspace = Path(workspace_dir) if workspace_dir else Path.cwd()
        self.timeout = timeout
        self.output_dir = self.workspace / output_subdir
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self._bash = BashExecutor(self.workspace, timeout=bash_timeout)
        self._git = GitHelper(self._bash, self.workspace)
        self._nexus_call_proxy = nexus_call_proxy  # NexusCallProxy | None

        logger.info(
            "CoderSandbox initialized: workspace=%s timeout=%ds nexus=%s",
            self.workspace, timeout, nexus_call_proxy is not None,
        )

    # ─────────────────────────────────────────────────────────────
    # Main Execute
    # ─────────────────────────────────────────────────────────────

    async def execute(
        self,
        code: str,
        context: Optional[Dict] = None,
        timeout: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Execute Python code with full file system + subprocess access.

        Returns a dict compatible with SandboxExecutor's contract so the
        Kernel's CoderSubAgent can call .get("status") and .get("output")
        without crashing.  All CoderResult-specific fields (files_created,
        git_branch, etc.) are embedded inside ``output`` AND promoted to
        the top level for callers that read them directly.

        Shape:
            {
                "status":        "success" | "failure",
                "output":        CoderResult.to_dict(),   # the full structured result
                "error":         str | None,
                "error_type":    str | None,
                "execution_time": float,
                "mode":          "coder_sandbox",
                # promoted fields (convenience):
                "files_created":  [...],
                "files_modified": [...],
                "git_branch":     str | None,
                "data":           Any,
            }
        """
        """
        Execute Python code with full file system + subprocess access.

        Args:
            code: Python code to execute. Must set `result` variable.
            context: Extra variables to inject into namespace.
            timeout: Per-call timeout override.

        Returns:
            CoderResult with files_created, git_branch, stdout, etc.
        """
        timeout = timeout or self.timeout
        start = time.time()

        namespace = self._build_namespace(context)
        stdout_capture = io.StringIO()

        try:
            # Syntax check before execution
            try:
                ast.parse(code)
            except SyntaxError as e:
                cr = CoderResult(
                    success=False,
                    error=f"SyntaxError at line {e.lineno}: {e.msg}",
                    error_type="SyntaxError",
                    execution_time=time.time() - start,
                )
                return self._to_sandbox_dict(cr)

            is_async = "async def" in code or "await " in code or "asyncio" in code

            if is_async:
                exec_result = await asyncio.wait_for(
                    self._run_async(code, namespace, stdout_capture),
                    timeout=timeout,
                )
            else:
                loop = asyncio.get_event_loop()
                exec_result = await asyncio.wait_for(
                    loop.run_in_executor(
                        None,
                        self._run_sync,
                        code, namespace, stdout_capture,
                    ),
                    timeout=timeout,
                )

            if exec_result.get("error"):
                cr = CoderResult(
                    success=False,
                    stdout=stdout_capture.getvalue(),
                    error=exec_result["error"],
                    error_type=exec_result.get("error_type", "RuntimeError"),
                    execution_time=time.time() - start,
                )
                return self._to_sandbox_dict(cr)

            raw = namespace.get("result") or {}
            cr = self._parse_result(raw, stdout_capture.getvalue(), time.time() - start)
            return self._to_sandbox_dict(cr)

        except asyncio.TimeoutError:
            cr = CoderResult(
                success=False,
                stdout=stdout_capture.getvalue(),
                error=f"Coder execution timed out after {timeout}s",
                error_type="ExecutionTimeout",
                execution_time=time.time() - start,
            )
            return self._to_sandbox_dict(cr)
        except BashPermissionError as e:
            cr = CoderResult(
                success=False,
                stdout=stdout_capture.getvalue(),
                error=str(e),
                error_type="BashPermissionError",
                execution_time=time.time() - start,
            )
            return self._to_sandbox_dict(cr)
        except Exception as e:
            cr = CoderResult(
                success=False,
                stdout=stdout_capture.getvalue(),
                error=str(e),
                error_type=type(e).__name__,
                execution_time=time.time() - start,
            )
            return self._to_sandbox_dict(cr)

    # ─────────────────────────────────────────────────────────────
    # Sync / Async runners
    # ─────────────────────────────────────────────────────────────

    def _run_sync(
        self,
        code: str,
        namespace: Dict,
        stdout_capture: io.StringIO,
    ) -> Dict[str, Any]:
        try:
            with redirect_stdout(stdout_capture):
                exec(code, namespace)  # noqa: S102 — deliberate, scoped
            return {}
        except Exception as e:
            return {"error": str(e), "error_type": type(e).__name__}

    async def _run_async(
        self,
        code: str,
        namespace: Dict,
        stdout_capture: io.StringIO,
    ) -> Dict[str, Any]:
        namespace["asyncio"] = asyncio
        try:
            with redirect_stdout(stdout_capture):
                exec(code, namespace)  # noqa: S102
                if "main" in namespace and callable(namespace["main"]):
                    await namespace["main"]()
                elif "run" in namespace and callable(namespace["run"]):
                    await namespace["run"]()
            return {}
        except Exception as e:
            return {"error": str(e), "error_type": type(e).__name__}

    # ─────────────────────────────────────────────────────────────
    # Namespace
    # ─────────────────────────────────────────────────────────────

    def _build_namespace(self, context: Optional[Dict]) -> Dict:
        """
        Build the execution namespace with all Coder capabilities injected.

        Security: context is NOT blindly injected. Only safe, non-credential
        values are explicitly extracted and placed in the namespace.
        Credentials NEVER appear here — nexus_call() is the credential boundary.
        """
        import builtins
        import datetime
        import hashlib
        import json
        import math
        import pathlib
        import re as _re
        import shutil
        import tempfile
        import textwrap
        import uuid

        workspace = self.workspace
        output_dir = self.output_dir
        bash = self._bash
        git = self._git

        def blob_path(filename: str) -> Path:
            """Return a path inside workspace/output/ — safe write location."""
            p = output_dir / filename
            p.parent.mkdir(parents=True, exist_ok=True)
            return p

        namespace = {
            "__builtins__": builtins,
            "result": None,

            # Workspace helpers
            "workspace": workspace,
            "output_dir": output_dir,
            "blob_path": blob_path,

            # Controlled execution tools
            "bash": bash,
            "git": git,

            # Standard library convenience
            "Path": pathlib.Path,
            "json": json,
            "os": os,
            "re": _re,
            "sys": sys,
            "datetime": datetime,
            "math": math,
            "hashlib": hashlib,
            "uuid": uuid,
            "shutil": shutil,
            "tempfile": tempfile,
            "textwrap": textwrap,
        }

        # ── nexus_call: the ONLY way to call provider APIs ──────────────
        # Resolves credentials internally via NexusCallProxy.
        # Sandbox code sees nexus_call(method, url, **kwargs) → response dict.
        # Credentials are NEVER in the namespace.
        _conn_id = (context or {}).get("_nexus_connection_id") if context else None
        if self._nexus_call_proxy and _conn_id:
            from jarviscore.nexus.call_proxy import NexusCallProxy
            namespace["nexus_call"] = NexusCallProxy.make_nexus_call_fn(
                self._nexus_call_proxy, _conn_id
            )
        else:
            # No Nexus connection available — inject a stub that raises clearly
            async def _nexus_unavailable(method: str, url: str, **kwargs):
                raise RuntimeError(
                    "nexus_call is not available: no Nexus connection_id for this task. "
                    "Ensure NEXUS_GATEWAY_URL is set and the agent task specifies a 'system'."
                )
            namespace["nexus_call"] = _nexus_unavailable

        # ── Safe context injection (explicit allowlist) ──────────────────
        # Only non-credential task metadata is passed into the sandbox.
        # _nexus_connection_id, _nexus_provider, and any other _ keys are
        # intentionally excluded to prevent accidental credential logging.
        if context:
            SAFE_CONTEXT_KEYS = {
                "task", "system", "workflow_id", "step_id",
                "prior_outputs", "registry_candidate", "_hint",
            }
            for k, v in context.items():
                if k in SAFE_CONTEXT_KEYS:
                    namespace[k] = v

        return namespace

    # ─────────────────────────────────────────────────────────────
    # SandboxExecutor-compatible dict conversion
    # ─────────────────────────────────────────────────────────────

    def _to_sandbox_dict(self, cr: "CoderResult") -> Dict[str, Any]:
        """
        Convert a CoderResult into a SandboxExecutor-compatible dict.

        The Kernel's CoderSubAgent calls sandbox.execute() and then does:
            result.get("status")  → "success" | "failure"
            result.get("error")   → str | None
            result.get("output")  → Any

        We satisfy that contract while also promoting CoderResult-specific
        fields to the top level so Coder.execute_task() can read them directly.
        """
        d = cr.to_dict()
        return {
            # SandboxExecutor contract (what CoderSubAgent reads)
            "status":         "success" if cr.success else "failure",
            "output":         d,           # full CoderResult dict lives here
            "error":          cr.error,
            "error_type":     cr.error_type,
            "execution_time": cr.execution_time,
            "mode":           "coder_sandbox",
            # Promoted fields (convenience for Coder.execute_task())
            "files_created":  cr.files_created,
            "files_modified": cr.files_modified,
            "git_branch":     cr.git_branch,
            "data":           cr.data,
            "stdout":         cr.stdout,
        }

    # ─────────────────────────────────────────────────────────────
    # Result Parsing
    # ─────────────────────────────────────────────────────────────

    def _parse_result(
        self,
        raw: Any,
        stdout: str,
        elapsed: float,
    ) -> CoderResult:
        """
        Normalise whatever the generated code put in `result`.

        Accepts:
          - dict with our contract keys
          - str (error message or file path)
          - None (treat as success with no files)
        """
        if raw is None:
            return CoderResult(success=True, stdout=stdout, execution_time=elapsed)

        if isinstance(raw, str):
            # Bare string return — treat as a note in data
            return CoderResult(success=True, data=raw, stdout=stdout, execution_time=elapsed)

        if not isinstance(raw, dict):
            return CoderResult(success=True, data=raw, stdout=stdout, execution_time=elapsed)

        # Normalise file lists — accept str or list
        def _as_list(val) -> List[str]:
            if not val:
                return []
            if isinstance(val, str):
                return [val]
            return [str(v) for v in val]

        return CoderResult(
            success=raw.get("success", True),
            files_created=_as_list(raw.get("files_created")),
            files_modified=_as_list(raw.get("files_modified")),
            git_branch=raw.get("git_branch"),
            stdout=raw.get("stdout", stdout),
            data=raw.get("data"),
            error=raw.get("error"),
            error_type=raw.get("error_type"),
            execution_time=elapsed,
        )


# ─────────────────────────────────────────────────────────────────
# System prompt snippet for CodeGenerator
# ─────────────────────────────────────────────────────────────────

CODER_GENERATION_SYSTEM_PROMPT = """\
You are the JarvisCore Coder Agent — a senior Python engineer writing production scripts.

## Mission
Write a Python script that fulfills the given task.
Store the final outcome in a variable called `result` (dict matching the contract below).

## Environment — What's Available
Your code runs inside CoderSandbox with these pre-injected names:

  workspace   : pathlib.Path  — project root (safe to read/write recursively)
  output_dir  : pathlib.Path  — workspace/output/ (preferred write location)
  blob_path(n): Path          — shorthand: output_dir / n (creates parent dirs)
  bash(cmd)   : BashExecutor  — run allowed shell commands (git, pip, pandoc, etc.)
  git         : GitHelper     — high-level git: checkout_branch, add_all, commit, push
  Path        : pathlib.Path  — path manipulation
  json, os, re, datetime, math, shutil, tempfile, textwrap, uuid — all imported

  You may `import` any installed package (python-pptx, reportlab, Pillow, etc.)
  You may read/write any file under workspace using standard open().

## Bash Security
bash() enforces an allow-list: git, pip, pip3, pandoc, convert, ffmpeg, npm, npx,
node, python, python3, curl, cp, mv, mkdir, rm, ls, cat, echo, find, grep, etc.
sudo, rm -rf /, eval, pipe-to-shell are hard-blocked.

## Result Contract — ALWAYS set `result` with this structure:
result = {
    "success": True,                         # bool — did the task complete?
    "files_created": ["path/to/file.pptx"],  # list of str — files written
    "files_modified": ["path/to/file.md"],   # list of str — files changed
    "git_branch": "feat/seo-2026-04-21",     # str or None
    "data": { ... },                         # any structured data to return
    "error": None,                           # str or None
}

## Output Format — EXACTLY 2 blocks
```json
{"oauth_required": false, "provider_name": null, "scopes": []}
```
```python
# your code here
result = { ... }
```
"""


# ─────────────────────────────────────────────────────────────────
# Factory
# ─────────────────────────────────────────────────────────────────

def create_coder_sandbox(
    workspace_dir: Optional[Path] = None,
    timeout: int = 300,
    bash_timeout: int = 120,
    nexus_call_proxy=None,  # Optional[NexusCallProxy] — wires nexus_call() into sandbox
) -> CoderSandbox:
    """
    Create a CoderSandbox scoped to the given workspace directory.

    Args:
        workspace_dir:    Root directory for file operations. Defaults to cwd.
        timeout:          Max Python execution time in seconds.
        bash_timeout:     Max shell command time in seconds.
        nexus_call_proxy: NexusCallProxy instance. When provided, sandbox code
                          can call nexus_call(method, url) to make authenticated
                          API calls through Nexus. If None, nexus_call() raises
                          a RuntimeError with instructions.

    Returns:
        CoderSandbox instance.
    """
    return CoderSandbox(
        workspace_dir=workspace_dir,
        timeout=timeout,
        bash_timeout=bash_timeout,
        nexus_call_proxy=nexus_call_proxy,
    )
