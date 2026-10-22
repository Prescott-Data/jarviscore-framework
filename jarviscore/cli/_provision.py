"""Create a project's `.venv` on the first `jarviscore dev`.

With uv on PATH this is `uv sync` (which honours uv.lock); otherwise `python -m venv`
with this interpreter, then `pip install` of the `[project].dependencies` in the
project's pyproject.toml. Never `pip install -e .`: generated projects set
`[tool.uv] package = false` and have no build backend.
"""

from __future__ import annotations

import collections
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Mapping
from pathlib import Path

NO_SYNC_ENV = "JARVISCORE_DEV_NO_SYNC"
# Whole-step ceilings: a cold pip install of the p2p/redis extras is ~1 minute.
VENV_TIMEOUT = 300
INSTALL_TIMEOUT = 1800
STOP_GRACE = 5
TAIL_LINES = 40


class ProvisionError(Exception):
    pass


class Interrupted(KeyboardInterrupt):
    """Ctrl-C or SIGTERM while provisioning; `signum` gives the exit code (128+N)."""

    def __init__(self, signum: int = signal.SIGINT) -> None:
        super().__init__()
        self.signum = int(signum)


def venv_python(venv: Path) -> Path:
    if os.name == "nt":
        return venv / "Scripts" / "python.exe"
    return venv / "bin" / "python"


def sync_disabled(environ: Mapping[str, str]) -> bool:
    return environ.get(NO_SYNC_ENV, "").strip().lower() in {"1", "true", "yes", "on"}


def should_provision(root: Path, *, sync: bool = True,
                     environ: Mapping[str, str] | None = None) -> bool:
    environ = os.environ if environ is None else environ
    if not sync or sync_disabled(environ):
        return False
    venv = root / ".venv"
    if venv.exists() or venv.is_symlink():
        return False
    return (root / "pyproject.toml").is_file()


# ── pyproject.toml ───────────────────────────────────────────────────────

def project_dependencies(pyproject: Path) -> list[str]:
    """`[project].dependencies` from pyproject.toml (tomllib, tomli, or a minimal parse)."""
    text = pyproject.read_text(encoding="utf-8")
    loads = _toml_loads()
    if loads is None:
        return _minimal_dependencies(text)
    try:
        data = loads(text)
    except ValueError as exc:  # tomllib/tomli.TOMLDecodeError subclass ValueError
        raise ProvisionError(f"{pyproject} is not valid TOML: {exc}") from None
    deps = data.get("project", {}).get("dependencies", [])
    if not isinstance(deps, list) or not all(isinstance(d, str) for d in deps):
        raise ProvisionError(f"[project].dependencies in {pyproject} must be a list of strings")
    return deps


def _toml_loads():
    if sys.version_info >= (3, 11):
        import tomllib

        return tomllib.loads
    try:
        import tomli
    except ImportError:
        return None
    return tomli.loads


_SECTION = re.compile(r"^\s*\[\[?\s*([^\]]+?)\s*\]\]?\s*(?:#.*)?$")
_DEPS_START = re.compile(r"^\s*dependencies\s*=\s*\[", re.MULTILINE)
_ARRAY_TOKEN = re.compile(r'"((?:[^"\\]|\\.)*)"|\'([^\']*)\'|(\])|#[^\n]*|[\s,]+')


def _minimal_dependencies(text: str) -> list[str]:
    """Enough TOML for `dependencies = [ "a", 'b', ... ]` under `[project]` (3.10 sans tomli)."""
    body: list[str] = []
    in_project = False
    for line in text.splitlines():
        match = _SECTION.match(line)
        if match and not line.lstrip().startswith(("'", '"')):
            in_project = match.group(1) == "project"
            continue
        if in_project:
            body.append(line)
    section = "\n".join(body)
    start = _DEPS_START.search(section)
    if not start:
        return []
    deps: list[str] = []
    pos = start.end()
    while pos < len(section):
        token = _ARRAY_TOKEN.match(section, pos)
        if not token:
            raise ProvisionError("Could not parse [project].dependencies in pyproject.toml")
        if token.group(3):
            return deps
        if token.group(1) is not None:
            deps.append(token.group(1).encode().decode("unicode_escape"))
        elif token.group(2) is not None:
            deps.append(token.group(2))
        pos = token.end()
    raise ProvisionError("Unterminated [project].dependencies in pyproject.toml")


# ── Provisioning ─────────────────────────────────────────────────────────

def plan(root: Path, *, which: Callable[[str], str | None] = shutil.which,
         python: str | None = None) -> tuple[str, list[list[str]], str]:
    """(tool, commands, manual command to show on failure)."""
    uv = which("uv")
    if uv:
        return "uv", [[uv, "sync"]], f"cd {shlex.quote(str(root))} && uv sync"
    python = python or sys.executable
    deps = project_dependencies(root / "pyproject.toml")
    if not deps:
        raise ProvisionError(
            f"{root / 'pyproject.toml'} lists no [project].dependencies, so there is nothing "
            f"to install into .venv. Create it yourself, or add "
            f"\"jarviscore-framework[p2p,redis]\" to the dependencies.")
    venv = root / ".venv"
    vpy = venv_python(venv)
    pip = [str(vpy), "-m", "pip", "install", "--disable-pip-version-check", *deps]
    manual = " && ".join([
        f"cd {shlex.quote(str(root))}",
        shlex.join([python, "-m", "venv", ".venv"]),
        shlex.join([str(venv_python(Path(".venv"))), "-m", "pip", "install", *deps]),
    ])
    return "pip", [[python, "-m", "venv", str(venv)], pip], manual


def provision(root: Path, *, which: Callable[[str], str | None] = shutil.which,
              python: str | None = None, note: Callable[[str], None] | None = None,
              runner: Callable[[list[str], Path, float], tuple[int, list[str]]] | None = None,
              ) -> None:
    """Create `root/.venv`. Raises ProvisionError (with the manual fix) or Interrupted;
    either way a half-created .venv is removed."""
    note = note or _note
    runner = runner or run_step
    tool, commands, manual = plan(root, which=which, python=python)
    venv = root / ".venv"
    started = time.monotonic()
    note("Setting up project environment in .venv (first run)…")
    if tool == "uv":
        note("  uv sync")
    else:
        deps = commands[1][commands[1].index("--disable-pip-version-check") + 1:]
        note(f"  uv not found; using {Path(commands[0][0]).name} -m venv + pip")
        note(f"  installing {' '.join(deps)} (this can take a minute)…")
    with _sigterm_as_interrupt():
        try:
            for argv in commands:
                timeout = VENV_TIMEOUT if argv[1:3] == ["-m", "venv"] else INSTALL_TIMEOUT
                code, tail = runner(argv, root, timeout)
                if code != 0:
                    shown = "\n".join(f"    {line}" for line in tail) or "    (no output)"
                    reason = (f"timed out after {timeout}s" if code is None
                              else f"exited with code {code}")
                    raise ProvisionError(
                        f"Setting up .venv failed: `{shlex.join(argv)}` {reason}. Last output:\n"
                        f"{shown}\nFix the problem above, then run it yourself:\n  {manual}\n"
                        f"or skip this step with `jarviscore dev --no-sync`.")
        except BaseException:
            _remove(venv)
            raise
    note(f"✓ .venv ready ({time.monotonic() - started:.0f}s)")


def run_step(argv: list[str], cwd: Path, timeout: float) -> tuple[int | None, list[str]]:
    """Run one installer step, keeping the last lines of output. None code = timed out."""
    tail: collections.deque[str] = collections.deque(maxlen=TAIL_LINES)
    try:
        proc = subprocess.Popen(argv, cwd=cwd, stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, errors="replace", start_new_session=True)
    except OSError as exc:
        return 127, [f"could not run {argv[0]}: {exc}"]

    def pump() -> None:
        for line in proc.stdout:
            tail.append(line.rstrip())

    reader = threading.Thread(target=pump, daemon=True)
    reader.start()
    try:
        proc.wait(timeout)
    except subprocess.TimeoutExpired:
        _stop(proc)
        return None, list(tail)
    except BaseException:
        _stop(proc)
        raise
    reader.join(2)
    return proc.returncode, list(tail)


def _stop(proc: subprocess.Popen) -> None:
    # The installer leads its own session, so its children (pip build steps) go too.
    for sig, grace in ((signal.SIGTERM, STOP_GRACE), (signal.SIGKILL, STOP_GRACE)):
        try:
            os.killpg(proc.pid, sig)
        except (OSError, AttributeError):
            try:
                proc.kill()
            except OSError:
                pass
        try:
            proc.wait(grace)
            return
        except subprocess.TimeoutExpired:
            continue


def _remove(venv: Path) -> None:
    if venv.is_symlink():
        venv.unlink(missing_ok=True)
    elif venv.exists():
        shutil.rmtree(venv, ignore_errors=True)


class _sigterm_as_interrupt:
    """SIGINT/SIGTERM raise Interrupted(signum) once so cleanup runs; repeats are
    ignored so a second Ctrl-C cannot cut the (bounded) cleanup short. Main thread only."""

    def __enter__(self):
        self._saved = {}
        if threading.current_thread() is not threading.main_thread():
            return self
        fired: list[int] = []

        def handler(signum, _frame):
            if fired:
                return
            fired.append(signum)
            raise Interrupted(signum)

        for sig in (signal.SIGINT, signal.SIGTERM):
            self._saved[sig] = signal.signal(sig, handler)
        return self

    def __exit__(self, *exc) -> None:
        for sig, previous in self._saved.items():
            signal.signal(sig, previous)


def _note(text: str) -> None:
    print(text, file=sys.stderr, flush=True)
