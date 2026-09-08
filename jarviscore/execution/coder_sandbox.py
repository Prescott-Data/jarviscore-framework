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
import json
import logging
import os
import re
import shlex
import socket
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
        blob_storage=None,      # Optional[BlobStorage]
        artifact_prefix: str = "artifacts",
    ):
        self.workspace = Path(workspace_dir) if workspace_dir else Path.cwd()
        self.timeout = timeout
        self.output_dir = self.workspace / output_subdir
        self.output_dir.mkdir(parents=True, exist_ok=True)
        # Where a run's files end up is the developer's choice: any BlobStorage
        # backend, local or remote. The sandbox only decides that they leave.
        self.blob_storage = blob_storage
        self.artifact_prefix = artifact_prefix

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
        """Execute generated code in a child process with no parent secrets."""
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
        }
        safe_env = {
            "PATH": os.path.dirname(sys.executable),
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
            process.kill()
            await process.wait()
            return self._to_sandbox_dict(CoderResult(
                success=False, error=f"Coder execution timed out after {timeout}s",
                error_type="ExecutionTimeout", execution_time=time.time() - start,
            ))
        finally:
            parent_socket.close()
            await asyncio.gather(rpc_task, return_exceptions=True)

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

    async def _serve_child_rpc(self, sock: socket.socket, context: Dict[str, Any]) -> None:
        sock.setblocking(False)
        reader, writer = await asyncio.open_connection(sock=sock)
        try:
            while line := await reader.readline():
                request = json.loads(line)
                try:
                    if request["operation"] == "nexus_call":
                        connection_id = context.get("_nexus_connection_id")
                        if not self._nexus_call_proxy or not connection_id:
                            raise RuntimeError("No provider account is connected for this task.")
                        payload = request["payload"]
                        call = self._recording_nexus_call(
                            lambda method, url, **kwargs: self._nexus_call_proxy.call(
                                connection_id, method, url, **kwargs
                            ),
                            str(context.get("_nexus_provider") or connection_id),
                        )
                        result = await call(
                            payload["method"], payload["url"], **payload.get("kwargs", {})
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
            if key == '__builtins__': continue
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
    blob_storage=None,      # Optional[BlobStorage] — where a run's files end up
    artifact_prefix: str = "artifacts",
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
        blob_storage=blob_storage,
        artifact_prefix=artifact_prefix,
    )
