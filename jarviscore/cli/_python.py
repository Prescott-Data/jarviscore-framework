"""Which Python runs a project's agents, and install hints for missing packages.

Agents run with the project's own virtualenv when it has one, so the dependencies in
the project's pyproject.toml are importable even when the CLI itself was installed
elsewhere (pipx, a global venv).
"""

import os
import subprocess
import sys
from pathlib import Path

_HAS_JARVISCORE = (
    "import importlib.util, sys; "
    "sys.exit(0 if importlib.util.find_spec('jarviscore') else 1)"
)


class InterpreterError(Exception):
    pass


def project_python(root: Path) -> tuple[str, str | None]:
    """(interpreter, note): the project's `.venv` Python, else this one with a note."""
    venv = root / ".venv"
    for candidate in (venv / "bin" / "python", venv / "Scripts" / "python.exe"):
        if candidate.is_file():
            return str(candidate), None
    return sys.executable, f"note: no {venv} found; running agents with {sys.executable}"


def ensure_jarviscore(python: str, root: Path) -> None:
    """Fail early, with the fix, if `python` cannot import jarviscore."""
    if os.path.abspath(python) == os.path.abspath(sys.executable):
        return
    try:
        ok = subprocess.run([python, "-c", _HAS_JARVISCORE], capture_output=True,
                            timeout=30, check=False).returncode == 0
    except (OSError, subprocess.SubprocessError):
        ok = False
    if not ok:
        raise InterpreterError(
            f"{python} cannot import jarviscore. Install the project's dependencies: "
            f"run `uv sync` in {root}, or delete {root / '.venv'} and run `jarviscore dev` "
            "to recreate it")


def running_under_pipx() -> bool:
    parts = Path(sys.prefix).parts
    return "pipx" in parts and "venvs" in parts


def install_hint(package: str) -> str:
    """How to add `package` to the environment this CLI runs from."""
    if running_under_pipx():
        return f"pipx inject jarviscore-framework {package}"
    return f'"{sys.executable}" -m pip install {package}'
