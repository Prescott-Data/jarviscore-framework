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
import hashlib
import io
import json
import logging
import os
import re
import shlex
import shutil
import signal
import socket
import subprocess
import sys
import time
from contextlib import redirect_stdout
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────
# Result Model
# ─────────────────────────────────────────────────────────────────

class _SealedEnviron(dict):
    """The process environment, withheld from generated code.

    Empty rather than absent so ordinary lookups return nothing instead of
    crashing, and explicit about why on any attempt to read a name.
    """

    def __getitem__(self, key):
        raise KeyError(
            f"{key!r}: the process environment is not readable from here. "
            "Credentials are attached by nexus_call outside the sandbox, so "
            "nothing in here needs them."
        )


class _SealedOS:
    """`os` with the environment withheld from the injected namespace.

    The real module handed generated code NEXUS_ENCRYPTION_KEY, the key the
    credential vault is encrypted with, alongside every other secret this process
    holds, and an agent duly listed them into a user-facing answer.

    This is a guard rail, not a boundary: the sandbox executes in-process, so
    `import os` still reaches the real environment. Closing that needs the
    generated code to run somewhere without the secrets, which is process
    isolation, not a namespace substitution.
    """

    environ = _SealedEnviron()
    environb = _SealedEnviron()

    @staticmethod
    def getenv(key, default=None):
        return default

    @staticmethod
    def putenv(*args, **kwargs):
        raise PermissionError("The process environment cannot be changed from here.")

    def __getattr__(self, name):
        return getattr(os, name)


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
    artifacts: List[Dict[str, Any]] = field(default_factory=list)
    #: What the credential boundary refused, if it refused. Recorded there rather
    #: than read back out of a message, because generated code catches broadly and
    #: a stringified exception loses the only reliable statement of what happened.
    access_failure: Optional[Dict[str, Any]] = None

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
            "access_failure": self.access_failure,
            "execution_time": self.execution_time,
            "artifacts": self.artifacts,
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
    "find", "grep", "sed", "awk", "sort", "uniq", "head", "tail", "wc", "pwd",
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
        result_bash = bash("git add .")
        result_bash = bash("git commit -m 'SEO: update meta tags'")
    """

    def __init__(
        self,
        workspace_dir: Path,
        timeout: int = 120,
        allowed_commands: Optional[set[str]] = None,
        command_environment: Optional[Dict[str, str]] = None,
        allow_unsafe_local_execution: bool = False,
    ):
        self.workspace = workspace_dir
        self.timeout = timeout
        self.allow_unsafe_local_execution = bool(allow_unsafe_local_execution)
        self.allowed_commands = _BASH_ALLOW_LIST | set(allowed_commands or ())
        allowed_environment = {
            "CARGO_HOME",
            "CARGO_TARGET_DIR",
            "GOCACHE",
            "GOMODCACHE",
            "GRADLE_USER_HOME",
            "NPM_CONFIG_CACHE",
            "PIP_CACHE_DIR",
            "RUSTUP_HOME",
        }
        self.command_environment = {
            str(key): str(value)
            for key, value in dict(command_environment or {}).items()
            if str(key) in allowed_environment and str(value)
        }

    def __call__(self, command: str, cwd: Optional[str] = None) -> Dict[str, Any]:
        """
        Execute a shell command. Synchronous — run from thread pool inside sandbox.

        Args:
            command: Shell command string (not a list).
            cwd: Working directory override. Defaults to workspace_dir.

        Returns:
            {"success": bool, "stdout": str, "stderr": str, "returncode": int}
        """
        if not self.allow_unsafe_local_execution:
            raise BashPermissionError(
                "Local process execution is disabled because cwd and command allow-lists "
                "do not isolate the host filesystem or network. Configure a remote/container "
                "sandbox, or explicitly set allow_unsafe_local_execution=True only for "
                "trusted code."
            )
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

        if "\n" in command or "$(" in command or "`" in command:
            raise BashPermissionError("Shell command substitution and newlines are not allowed")
        lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|<>")
        lexer.whitespace_split = True
        lexer.commenters = ""
        shell_tokens = list(lexer)
        punctuation = set(";&|<>")
        operator_tokens = [
            token for token in shell_tokens
            if token and set(token) <= punctuation
        ]
        if any("<" in token or ">" in token for token in operator_tokens):
            raise BashPermissionError("Shell redirection is not allowed")
        if "&" in operator_tokens:
            raise BashPermissionError("Background shell commands are not allowed")
        allowed_operators = {";", "&&", "||", "|"}
        unsupported = [
            token for token in operator_tokens if token not in allowed_operators
        ]
        if unsupported:
            raise BashPermissionError(
                f"Unsupported shell operator: {unsupported[0]!r}"
            )
        command_indexes = [0]
        command_indexes.extend(
            index + 1
            for index, token in enumerate(shell_tokens[:-1])
            if token in {";", "&&", "||", "|"}
        )
        for index in command_indexes:
            base_cmd = os.path.basename(shell_tokens[index])
            if base_cmd not in self.allowed_commands:
                raise BashPermissionError(
                    f"Command '{base_cmd}' is not on the Coder allow-list. "
                    f"Allowed: {sorted(self.allowed_commands)}"
                )

        workspace = self.workspace.resolve()
        requested = Path(cwd).expanduser() if cwd else workspace
        work_dir = (
            requested.resolve()
            if requested.is_absolute()
            else (workspace / requested).resolve()
        )
        if work_dir != workspace and workspace not in work_dir.parents:
            raise BashPermissionError(f"Working directory escapes workspace: {cwd!r}")
        if not work_dir.exists():
            work_dir.mkdir(parents=True, exist_ok=True)

        try:
            command_dirs = {
                str(Path(found).parent)
                for allowed in self.allowed_commands
                if (found := shutil.which(allowed)) is not None
            }
            command_dirs.add(str(Path(sys.executable).parent))
            temporary_root = self.workspace / ".tmp"
            safe_env = {
                "PATH": os.pathsep.join(sorted(command_dirs)),
                "HOME": str(temporary_root / "home"),
                "TMPDIR": str(temporary_root),
                "LANG": "C.UTF-8",
            }
            safe_env.update(self.command_environment)
            Path(safe_env["TMPDIR"]).mkdir(parents=True, exist_ok=True)
            Path(safe_env["HOME"]).mkdir(parents=True, exist_ok=True)
            for name, value in self.command_environment.items():
                if name.endswith(("_HOME", "_DIR", "CACHE")):
                    Path(value).expanduser().mkdir(parents=True, exist_ok=True)
            proc = subprocess.Popen(
                command,
                shell=True,
                cwd=str(work_dir),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=safe_env,
                start_new_session=os.name == "posix",
            )
            stdout, stderr = proc.communicate(timeout=self.timeout)
            return {
                "success": proc.returncode == 0,
                "stdout": stdout.strip(),
                "stderr": stderr.strip(),
                "returncode": proc.returncode,
            }
        except subprocess.TimeoutExpired:
            try:
                if os.name == "posix":
                    os.killpg(proc.pid, signal.SIGKILL)
                else:
                    proc.kill()
            except ProcessLookupError:
                # The command exited between the timeout and termination attempt.
                pass
            proc.communicate()
            return {
                "success": False,
                "stdout": "",
                "stderr": f"Command timed out after {self.timeout}s",
                "returncode": -1,
                "status": "timeout",
                "timed_out": True,
                "timeout_seconds": self.timeout,
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
        Returns a PR description dict (for the user to open manually or
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
        mesh_proxy=None,
        blob_storage=None,      # Optional[BlobStorage]
        artifact_prefix: str = "artifacts",
        allowed_commands: Optional[set[str]] = None,
        command_environment: Optional[Dict[str, str]] = None,
        allow_unsafe_local_execution: bool = False,
    ):
        self.workspace = Path(workspace_dir) if workspace_dir else Path.cwd()
        self.timeout = timeout
        self.output_dir = self.workspace / output_subdir
        self.output_dir.mkdir(parents=True, exist_ok=True)
        # Where a run's files end up is the developer's choice: any BlobStorage
        # backend, local or remote. The sandbox only decides that they leave.
        self.blob_storage = blob_storage
        self.artifact_prefix = artifact_prefix
        self.allow_unsafe_local_execution = bool(allow_unsafe_local_execution)

        self._bash = BashExecutor(
            self.workspace,
            timeout=bash_timeout,
            allowed_commands=allowed_commands,
            command_environment=command_environment,
            allow_unsafe_local_execution=self.allow_unsafe_local_execution,
        )
        self._git = GitHelper(self._bash, self.workspace)
        self._nexus_call_proxy = nexus_call_proxy  # NexusCallProxy | None
        self._mesh_proxy = mesh_proxy

        logger.info(
            "CoderSandbox initialized: workspace=%s timeout=%ds nexus=%s",
            self.workspace, timeout, nexus_call_proxy is not None,
        )

    def for_workspace(
        self,
        workspace_dir: Path,
        *,
        allowed_commands: Optional[set[str]] = None,
        bash_timeout: Optional[int] = None,
        command_environment: Optional[Dict[str, str]] = None,
    ) -> "CoderSandbox":
        """Clone this sandbox configuration around another workspace root."""
        return CoderSandbox(
            workspace_dir=workspace_dir,
            timeout=self.timeout,
            bash_timeout=bash_timeout or self._bash.timeout,
            output_subdir=self.output_dir.name,
            nexus_call_proxy=self._nexus_call_proxy,
            mesh_proxy=self._mesh_proxy,
            blob_storage=self.blob_storage,
            artifact_prefix=self.artifact_prefix,
            allowed_commands=self._bash.allowed_commands | set(allowed_commands or ()),
            command_environment={
                **self._bash.command_environment,
                **dict(command_environment or {}),
            },
            allow_unsafe_local_execution=self.allow_unsafe_local_execution,
        )

    def _workspace_path(self, relative: str = ".") -> Path:
        candidate = (self.workspace / relative).resolve()
        root = self.workspace.resolve()
        if candidate != root and root not in candidate.parents:
            raise ValueError(f"Path escapes the workspace: {relative!r}")
        return candidate

    def list_workspace(
        self, path: str = ".", *, recursive: bool = False, limit: int = 500
    ) -> Dict[str, Any]:
        """List bounded workspace metadata without generating code."""
        root = self.workspace.resolve()
        target = self._workspace_path(path)
        if not target.exists():
            return {"status": "not_found", "path": path, "entries": []}
        candidates = [target] if target.is_file() else (
            target.rglob("*") if recursive else target.iterdir()
        )
        entries = []
        bounded_limit = max(1, min(int(limit), 5_000))
        for candidate in sorted(candidates):
            if len(entries) >= bounded_limit:
                break
            entries.append({
                "path": candidate.resolve().relative_to(root).as_posix(),
                "kind": "directory" if candidate.is_dir() else "file",
                "size": candidate.stat().st_size if candidate.is_file() else None,
            })
        return {
            "status": "success",
            "path": path,
            "entries": entries,
            "truncated": len(entries) == bounded_limit,
        }

    def read_workspace(
        self,
        path: str,
        *,
        start_line: int = 1,
        end_line: int = 400,
        max_bytes: int = 128 * 1024,
    ) -> Dict[str, Any]:
        """Read a bounded UTF-8 line range from one workspace file."""
        target = self._workspace_path(path)
        if not target.is_file():
            return {"status": "not_found", "path": path}
        payload = target.read_bytes()
        if len(payload) > max_bytes:
            payload = payload[:max_bytes]
            byte_truncated = True
        else:
            byte_truncated = False
        try:
            text = payload.decode("utf-8")
        except UnicodeDecodeError:
            return {"status": "binary", "path": path, "size": target.stat().st_size}
        lines = text.splitlines()
        first = max(1, int(start_line))
        last = max(first, min(int(end_line), first + 2_000))
        return {
            "status": "success",
            "path": path,
            "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
            "start_line": first,
            "end_line": min(last, len(lines)),
            "content": "\n".join(lines[first - 1:last]),
            "truncated": byte_truncated or last < len(lines),
        }

    def write_workspace(
        self,
        path: str,
        content: str,
        *,
        executable: bool = False,
        max_bytes: int = 5 * 1024 * 1024,
    ) -> Dict[str, Any]:
        """Write one bounded UTF-8 file inside the copy-on-write workspace."""
        target = self._workspace_path(path)
        payload = str(content).encode("utf-8")
        bounded_max = max(1, min(int(max_bytes), 20 * 1024 * 1024))
        if len(payload) > bounded_max:
            return {
                "status": "error",
                "path": path,
                "error": f"Workspace write exceeds {bounded_max} bytes",
            }
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
        if executable:
            target.chmod(target.stat().st_mode | 0o100)
        return {
            "status": "success",
            "path": path,
            "bytes": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
            "executable": bool(executable),
        }

    def edit_workspace(
        self,
        path: str,
        start_line: int,
        end_line: int,
        replacement: str,
        expected_sha256: str,
        *,
        max_bytes: int = 5 * 1024 * 1024,
    ) -> Dict[str, Any]:
        """Replace an exact inclusive line range after verifying source identity."""
        target = self._workspace_path(path)
        if not target.is_file():
            return {"status": "not_found", "path": path}
        original = target.read_bytes()
        observed_sha256 = hashlib.sha256(original).hexdigest()
        if observed_sha256 != str(expected_sha256):
            return {
                "status": "conflict",
                "path": path,
                "expected_sha256": str(expected_sha256),
                "observed_sha256": observed_sha256,
            }
        try:
            text = original.decode("utf-8")
        except UnicodeDecodeError:
            return {"status": "binary", "path": path, "size": len(original)}
        lines = text.splitlines(keepends=True)
        first = int(start_line)
        last = int(end_line)
        if first < 1 or last < first or last > len(lines):
            return {
                "status": "error",
                "path": path,
                "error": f"Invalid inclusive line range {first}-{last}",
            }
        replacement_text = str(replacement)
        replaced_ended_with_newline = lines[last - 1].endswith(("\n", "\r"))
        if replacement_text and replaced_ended_with_newline and not replacement_text.endswith(
            ("\n", "\r")
        ):
            replacement_text += "\r\n" if "\r\n" in text else "\n"
        payload = (
            "".join(lines[: first - 1])
            + replacement_text
            + "".join(lines[last:])
        ).encode("utf-8")
        bounded_max = max(1, min(int(max_bytes), 20 * 1024 * 1024))
        if len(payload) > bounded_max:
            return {
                "status": "error",
                "path": path,
                "error": f"Workspace edit exceeds {bounded_max} bytes",
            }
        target.write_bytes(payload)
        return {
            "status": "success",
            "path": path,
            "bytes": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
            "executable": bool(target.stat().st_mode & 0o100),
        }

    def search_workspace(
        self,
        query: str,
        *,
        path: str = ".",
        glob: str = "*",
        regex: bool = False,
        limit: int = 100,
    ) -> Dict[str, Any]:
        """Search bounded text files and return line-addressable evidence."""
        root = self.workspace.resolve()
        target = self._workspace_path(path)
        pattern = re.compile(query if regex else re.escape(query), re.IGNORECASE)
        candidates = [target] if target.is_file() else target.rglob(glob)
        matches = []
        bounded_limit = max(1, min(int(limit), 1_000))
        for candidate in sorted(candidates):
            if (
                candidate.is_symlink()
                or not candidate.is_file()
                or candidate.stat().st_size > 2 * 1024 * 1024
            ):
                continue
            try:
                lines = candidate.read_text(encoding="utf-8").splitlines()
            except (UnicodeDecodeError, OSError):
                continue
            for line_number, line in enumerate(lines, 1):
                if pattern.search(line):
                    matches.append({
                        "path": candidate.resolve().relative_to(root).as_posix(),
                        "line": line_number,
                        "text": line[:1_000],
                    })
                    if len(matches) >= bounded_limit:
                        return {"status": "success", "matches": matches, "truncated": True}
        return {"status": "success", "matches": matches, "truncated": False}

    def run_workspace(self, command: str, *, cwd: str = ".") -> Dict[str, Any]:
        """Run an allow-listed command inside the workspace."""
        target = self._workspace_path(cwd)
        if not target.is_dir():
            return {
                "success": False,
                "stdout": "",
                "stderr": f"Workspace directory not found: {cwd}",
                "returncode": -1,
            }
        result = self._bash(command, cwd=str(target))
        for output_field in ("stdout", "stderr"):
            value = str(result.get(output_field) or "")
            if len(value) > 100_000:
                result[output_field] = value[:100_000] + "\n[output truncated]"
        return result

    # ─────────────────────────────────────────────────────────────
    # Main Execute
    # ─────────────────────────────────────────────────────────────

    async def execute(
        self,
        code: str,
        context: Optional[Dict] = None,
        timeout: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Execute generated code in a child process with no parent secrets."""
        if not self.allow_unsafe_local_execution:
            raise BashPermissionError(
                "Local generated-code execution is disabled because a subprocess does not "
                "isolate the host filesystem or network. Configure a remote/container "
                "sandbox, or explicitly set allow_unsafe_local_execution=True only for "
                "trusted code."
            )
        return await self._execute_subprocess(code, context, timeout or self.timeout)

    async def _execute_subprocess(
        self, code: str, context: Optional[Dict], timeout: int
    ) -> Dict[str, Any]:
        start = time.time()
        self._access_failure = None
        before = self._snapshot_output()
        parent_socket, child_socket = socket.socketpair()
        safe_context = {
            key: value for key, value in (context or {}).items()
            if key in {"task", "system", "workflow_id", "step_id", "prior_outputs"}
        }
        request = {
            "code": code, "context": safe_context,
            "workspace": str(self.workspace), "output_dir": str(self.output_dir),
            "bash_timeout": self._bash.timeout, "rpc_fd": child_socket.fileno(),
            "allow_unsafe_local_execution": self.allow_unsafe_local_execution,
        }
        command_dirs = {
            str(Path(found).parent)
            for command in self._bash.allowed_commands
            if (found := shutil.which(command)) is not None
        }
        command_dirs.add(str(Path(sys.executable).parent))
        safe_env = {
            "PATH": os.pathsep.join(sorted(command_dirs)),
            "HOME": str(self.workspace),
            "TMPDIR": str(self.workspace / ".tmp"),
            "LANG": "C.UTF-8",
            "PYTHONPATH": str(Path(__file__).resolve().parents[2]),
        }
        Path(safe_env["TMPDIR"]).mkdir(parents=True, exist_ok=True)
        process = await asyncio.create_subprocess_exec(
            sys.executable, "-m", "jarviscore.execution.sandbox_worker",
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE, env=safe_env,
            pass_fds=(child_socket.fileno(),), start_new_session=True,
        )
        child_socket.close()
        rpc_task = asyncio.create_task(self._serve_child_rpc(parent_socket, context or {}))
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(json.dumps(request).encode()), timeout=timeout
            )
        except asyncio.TimeoutError:
            await self._terminate_process_tree(process)
            return self._to_sandbox_dict(CoderResult(
                success=False, error=f"Coder execution timed out after {timeout}s",
                error_type="ExecutionTimeout", execution_time=time.time() - start,
            ))
        except asyncio.CancelledError:
            await self._terminate_process_tree(process)
            raise
        finally:
            parent_socket.close()
            if not rpc_task.done():
                rpc_task.cancel()
            try:
                await asyncio.wait_for(
                    asyncio.gather(rpc_task, return_exceptions=True),
                    timeout=2.0,
                )
            except asyncio.TimeoutError:
                logger.warning("Sandbox RPC task did not stop within the cleanup deadline")

        if process.returncode != 0:
            return self._to_sandbox_dict(CoderResult(
                success=False, error=stderr.decode(errors="replace")[-2000:] or "Sandbox child failed.",
                error_type="SandboxProcessError", execution_time=time.time() - start,
            ))
        try:
            response = json.loads(stdout)
        except Exception:
            response = {"error": "Sandbox child returned an invalid response.", "error_type": "SandboxProtocolError"}
        if response.get("error"):
            cr = CoderResult(
                success=False, stdout=response.get("stdout", ""),
                error=response["error"], error_type=response.get("error_type"),
                execution_time=time.time() - start,
            )
        else:
            cr = self._parse_result(response.get("result"), response.get("stdout", ""), time.time() - start)
            await self._collect_artifacts(cr, before)
        return self._to_sandbox_dict(cr)

    @staticmethod
    async def _terminate_process_tree(process) -> None:
        """Terminate the isolated sandbox session, including child processes."""
        if process.returncode is not None:
            return
        try:
            if os.name == "posix":
                os.killpg(process.pid, signal.SIGKILL)
            else:
                process.kill()
        except ProcessLookupError:
            # The sandbox exited between the return-code check and group kill.
            pass
        await process.wait()

    async def _serve_child_rpc(self, sock: socket.socket, context: Dict[str, Any]) -> None:
        sock.setblocking(False)
        reader, writer = await asyncio.open_connection(sock=sock)
        try:
            while line := await reader.readline():
                request = json.loads(line)
                try:
                    if request["operation"] == "nexus_call":
                        payload = request["payload"]
                        method = str(payload.get("method") or "GET").upper()
                        mutation = context.get("_mutation_authority")
                        if method not in {"GET", "HEAD", "OPTIONS"} and not (
                            isinstance(mutation, dict)
                            and mutation.get("atom")
                            and mutation.get("action_id")
                        ):
                            raise RuntimeError(
                                "Provider mutations must use a registered atom with "
                                "declared policy and idempotency identity."
                            )
                        requested_provider = payload.get("provider")
                        provider = str(
                            requested_provider
                            or context.get("_nexus_provider")
                            or ""
                        ).strip().lower()
                        connection_id = context.get("_nexus_connection_id")
                        if requested_provider and self._nexus_call_proxy:
                            connection_id = self._nexus_call_proxy.connection_handle(provider)
                        if not self._nexus_call_proxy or not connection_id:
                            raise RuntimeError("No provider account is connected for this task.")
                        call = self._recording_nexus_call(
                            lambda method, url, **kwargs: self._nexus_call_proxy.call(
                                connection_id, method, url, **kwargs
                            ),
                            provider or str(connection_id),
                        )
                        result = await call(
                            method, payload["url"], **payload.get("kwargs", {})
                        )
                    elif request["operation"] == "fetch_artifact":
                        if self.blob_storage is None:
                            raise RuntimeError("No blob storage is configured.")
                        import base64
                        content = await self.blob_storage.read(request["payload"]["key"])
                        if content is None:
                            raise FileNotFoundError(request["payload"]["key"])
                        if isinstance(content, str):
                            content = content.encode()
                        result = {"content": base64.b64encode(content).decode("ascii")}
                    elif request["operation"] == "mesh_list_peers":
                        if self._mesh_proxy is None:
                            raise RuntimeError("No mesh is attached to this agent.")
                        result = self._mesh_proxy.list_peers()
                        if hasattr(result, "__await__"):
                            result = await result
                    elif request["operation"] == "mesh_delegate":
                        if self._mesh_proxy is None:
                            raise RuntimeError("No mesh is attached to this agent.")
                        payload = request["payload"]
                        result = await self._mesh_proxy.delegate(
                            to=str(payload.get("to") or ""),
                            task=str(payload.get("task") or ""),
                            context=payload.get("context"),
                            capability=payload.get("capability"),
                            timeout=payload.get("timeout"),
                        )
                    else:
                        raise RuntimeError("Unknown sandbox RPC operation.")
                    response = {"id": request["id"], "result": self._rpc_jsonable(result)}
                except Exception as exc:
                    response = {"id": request.get("id"), "error": str(exc), "error_type": type(exc).__name__}
                writer.write((json.dumps(response) + "\n").encode())
                await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()

    @staticmethod
    def _rpc_jsonable(value: Any) -> Any:
        import base64
        if isinstance(value, bytes):
            return {"__bytes__": base64.b64encode(value).decode("ascii")}
        if isinstance(value, dict):
            return {str(key): CoderSandbox._rpc_jsonable(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [CoderSandbox._rpc_jsonable(item) for item in value]
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        return str(value)

    async def _execute_local(
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

        self._access_failure = None
        namespace = self._build_namespace(context)
        stdout_capture = io.StringIO()
        before = self._snapshot_output()

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

            raw = namespace.get("result")
            cr = self._parse_result(raw, stdout_capture.getvalue(), time.time() - start)
            await self._collect_artifacts(cr, before)
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
                entry = None
                if "main" in namespace and callable(namespace["main"]):
                    entry = namespace["main"]
                elif "run" in namespace and callable(namespace["run"]):
                    entry = namespace["run"]
                if entry is not None:
                    returned = await entry()
                    # What the entry point returns is the outcome. Code that
                    # assigns `result` itself still wins when it returns nothing.
                    if returned is not None:
                        namespace["result"] = returned
            return {}
        except Exception as e:
            return {"error": str(e), "error_type": type(e).__name__}

    # ─────────────────────────────────────────────────────────────
    # Namespace
    # ─────────────────────────────────────────────────────────────

    def get_manifest(self) -> str:
        """Return a string listing all pre-loaded modules and globals available in the sandbox."""
        ns = self._build_namespace(None)
        available = []
        import types
        for key, value in ns.items():
            if key == '__builtins__':
                continue
            if isinstance(value, types.ModuleType):
                available.append(f"- {key} (module)")
            elif isinstance(value, type):
                available.append(f"- {key} (class)")
            elif callable(value):
                available.append(f"- {key}() (function/callable)")
            else:
                available.append(f"- {key} ({type(value).__name__})")
        return "\\n".join(sorted(available))

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

        storage = self.blob_storage

        async def fetch_artifact(key: str) -> Path:
            """Bring an artifact from a previous run back into this workspace.

            Long-horizon work needs yesterday's output to still be reachable,
            wherever the developer configured storage to be.
            """
            if storage is None:
                raise RuntimeError(
                    "No blob storage is configured, so artifacts from earlier "
                    "runs cannot be fetched. Configure one on the mesh."
                )
            content = await storage.read(key)
            if content is None:
                raise FileNotFoundError(f"No artifact stored at {key!r}")
            local = blob_path(key.rsplit("/", 1)[-1])
            if isinstance(content, str):
                local.write_text(content, encoding="utf-8")
            else:
                local.write_bytes(content)
            return local

        namespace = {
            "__builtins__": builtins,
            "result": None,

            # Workspace helpers
            "workspace": workspace,
            "output_dir": output_dir,
            "blob_path": blob_path,
            "fetch_artifact": fetch_artifact,

            # Controlled execution tools
            "bash": bash,
            "git": git,

            # Standard library convenience
            "Path": pathlib.Path,
            "json": json,
            "os": _SealedOS(),
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
            namespace["nexus_call"] = self._recording_nexus_call(
                NexusCallProxy.make_nexus_call_fn(self._nexus_call_proxy, _conn_id),
                str((context or {}).get("_nexus_provider") or _conn_id),
            )
        else:
            # No Nexus connection available — inject a stub that raises clearly
            async def _nexus_unavailable(method: str, url: str, **kwargs):
                raise RuntimeError(
                    "No provider account is connected for this task, so this call "
                    "cannot be signed. Name the provider you need with "
                    "write_code(system=...), and if it is registered but not yet "
                    "connected, request_access will ask someone to approve it."
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
        cr.access_failure = cr.access_failure or getattr(self, "_access_failure", None)
        d = cr.to_dict()
        return {
            # SandboxExecutor contract (what CoderSubAgent reads)
            "status":         "success" if cr.success else "failure",
            "output":         d,           # full CoderResult dict lives here
            "error":          cr.error,
            "error_type":     cr.error_type,
            "access_failure": cr.access_failure,
            "execution_time": cr.execution_time,
            "mode":           "coder_sandbox",
            # Promoted fields (convenience for Coder.execute_task())
            "files_created":  cr.files_created,
            "files_modified": cr.files_modified,
            "git_branch":     cr.git_branch,
            "data":           cr.data,
            "stdout":         cr.stdout,
            "artifacts":      cr.artifacts,
        }

    def _recording_nexus_call(self, call_fn, provider: str):
        """Wrap nexus_call so a refusal at the credential boundary is kept as fact."""
        from jarviscore.nexus.hosts import HostNotAllowed
        from jarviscore.nexus.strategy import StrategyError

        async def nexus_call(method: str, url: str, **kwargs):
            try:
                response = await call_fn(method, url, **kwargs)
            except StrategyError as exc:
                self._access_failure = {
                    "kind": "no_usable_credential",
                    "provider": provider,
                    "detail": str(exc),
                }
                raise
            except HostNotAllowed as exc:
                self._access_failure = {
                    "kind": "destination_not_owned_by_provider",
                    "provider": provider,
                    "detail": str(exc),
                }
                raise
            if not response.get("ok") and response.get("status_code") in (401, 403):
                # Evidence, not a verdict: the credential was formed and placed,
                # and the provider rejected it. What that means is decided with
                # the connection state, not here.
                self._access_failure = {
                    "kind": "provider_rejected_credential",
                    "provider": provider,
                    "status_code": response.get("status_code"),
                    "detail": str(response.get("body") or "")[:400],
                }
            return response

        return nexus_call

    # ─────────────────────────────────────────────────────────────
    # Result Parsing
    # ─────────────────────────────────────────────────────────────

    #: Keys that only this sandbox's result contract uses. `success` and `error`
    #: are excluded on purpose: atoms return those as part of their own answer.
    _ENVELOPE_KEYS = frozenset({
        "files_created", "files_modified", "git_branch", "data", "error_type", "stdout",
    })

    def _snapshot_output(self) -> Dict[str, float]:
        """Modification times under output_dir, to tell apart what a run produced."""
        snapshot = {}
        for path in self.output_dir.rglob("*"):
            if path.is_file():
                snapshot[str(path)] = path.stat().st_mtime_ns
        return snapshot

    async def _collect_artifacts(self, cr: "CoderResult", before: Dict[str, float]) -> None:
        """Hand what the run produced to storage, and report it as a handle.

        An agent that downloads a file has to be able to say what it produced
        and reach it again in a later run. Reporting is observed rather than
        declared, because code that forgets to list a file has still made one.
        """
        after = self._snapshot_output()
        produced = [p for p, stamp in after.items() if before.get(p) != stamp]
        if not produced:
            return

        for path in sorted(produced):
            local = Path(path)
            record: Dict[str, Any] = {
                "name": str(local.relative_to(self.output_dir)),
                "path": str(local),
                "bytes": local.stat().st_size,
                "key": None,
            }
            if self.blob_storage is not None:
                key = f"{self.artifact_prefix}/{record['name']}"
                try:
                    await self.blob_storage.save(key, local.read_bytes())
                    record["key"] = key
                except Exception as exc:  # noqa: BLE001 - storage must not fail the run
                    logger.warning("Could not store artifact %s: %s", key, exc)
                    record["error"] = str(exc)
            cr.artifacts.append(record)
            if path not in before:
                cr.files_created.append(path)
            elif path not in cr.files_modified:
                cr.files_modified.append(path)

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

        # A dict is only this sandbox's envelope when it carries a key that
        # belongs to the envelope. An atom returns its own answer shape, often
        # with `success` and `error` of its own, and reading `data` out of that
        # would discard the very thing that was asked for.
        if not (raw.keys() & self._ENVELOPE_KEYS):
            return CoderResult(
                success=bool(raw.get("success", True)),
                data=raw,
                stdout=stdout,
                error=raw.get("error"),
                execution_time=elapsed,
            )

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
    mesh_proxy=None,
    blob_storage=None,      # Optional[BlobStorage] — where a run's files end up
    artifact_prefix: str = "artifacts",
    allowed_commands: Optional[set[str]] = None,
    command_environment: Optional[Dict[str, str]] = None,
    allow_unsafe_local_execution: bool = False,
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
        mesh_proxy=mesh_proxy,
        blob_storage=blob_storage,
        artifact_prefix=artifact_prefix,
        allowed_commands=allowed_commands,
        command_environment=command_environment,
        allow_unsafe_local_execution=allow_unsafe_local_execution,
    )
