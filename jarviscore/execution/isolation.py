"""OS-level confinement for code an agent wrote.

The child that runs generated code reaches providers only through the parent's
``nexus_call`` RPC on an inherited socket. Confinement makes that the only way
out: no network, no writes outside the run workspace, and reads limited to the
Python runtime, its packages and the workspace. Where no confinement mechanism
exists, callers must not run model-written code without an explicit opt-in.
"""

from __future__ import annotations

import functools
import logging
import shutil
import site
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import List, Optional, Sequence

logger = logging.getLogger(__name__)


def _runtime_paths() -> List[Path]:
    import jarviscore

    paths = {
        Path(sys.prefix), Path(sys.base_prefix), Path(sys.exec_prefix),
        Path(sys.executable).resolve().parent,
        Path(jarviscore.__file__).resolve().parent,
    }
    for entry in [*site.getsitepackages(), site.getusersitepackages()]:
        paths.add(Path(entry))
    return sorted({path.resolve() for path in paths if path.exists()})


def _quote(path: Path) -> str:
    return '"' + str(path).replace("\\", "\\\\").replace('"', '\\"') + '"'


def seatbelt_profile(workspace: Path, protected: Sequence[Path] = ()) -> str:
    """A macOS sandbox profile: deny everything, then allow what Python needs."""
    import jarviscore

    workspace = workspace.resolve()
    package_parent = Path(jarviscore.__file__).resolve().parent.parent
    reads = "\n".join(f"  (subpath {_quote(path)})" for path in _runtime_paths())
    locked = "".join(
        f"(deny file-write* (subpath {_quote(Path(path).resolve())}))\n" for path in protected
    )
    return f"""(version 1)
(deny default)
(allow process-fork)
(allow process-exec)
(allow signal (target self))
(allow sysctl-read)
(allow file-read-metadata)
(allow file-read*
{reads}
  (literal {_quote(package_parent)})
  (literal "/")
  (subpath "/System")
  (subpath "/usr/lib")
  (subpath "/usr/share")
  (subpath "/usr/bin")
  (subpath "/bin")
  (subpath "/opt/homebrew")
  (subpath "/usr/local")
  (subpath "/Library/Developer/CommandLineTools")
  (subpath "/private/etc")
  (subpath "/private/var/db")
  (subpath "/dev")
  (subpath {_quote(workspace)}))
(allow file-write*
  (literal "/dev/null")
  (subpath {_quote(workspace)}))
(allow file-ioctl (literal "/dev/null"))
{locked}"""


def bubblewrap_command(workspace: Path, protected: Sequence[Path] = ()) -> List[str]:
    """Linux confinement with bubblewrap: read-only runtime, writable workspace, no network."""
    import jarviscore

    workspace = workspace.resolve()
    command = [
        "bwrap", "--die-with-parent", "--unshare-all", "--new-session",
        "--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp",
    ]
    for system_path in ("/usr", "/lib", "/lib64", "/bin", "/etc/ssl", "/etc/localtime"):
        if Path(system_path).exists():
            command += ["--ro-bind", system_path, system_path]
    for path in [*_runtime_paths(), Path(jarviscore.__file__).resolve().parent]:
        command += ["--ro-bind", str(path), str(path)]
    command += ["--bind", str(workspace), str(workspace), "--chdir", str(workspace)]
    for path in protected:
        if Path(path).exists():
            command += ["--ro-bind", str(Path(path).resolve()), str(Path(path).resolve())]
    return command


def _mechanism() -> Optional[str]:
    if sys.platform == "darwin" and shutil.which("sandbox-exec"):
        return "seatbelt"
    if sys.platform.startswith("linux") and shutil.which("bwrap"):
        return "bubblewrap"
    return None


def _prefix_for(mechanism: str, workspace: Path, protected: Sequence[Path]) -> List[str]:
    if mechanism == "seatbelt":
        return ["sandbox-exec", "-p", seatbelt_profile(workspace, protected)]
    return bubblewrap_command(workspace, protected)


@functools.lru_cache(maxsize=None)
def confinement_unavailable_reason() -> Optional[str]:
    """Why this host cannot confine a child, or None when confinement is proven to work.

    An installed mechanism is not enough: containers commonly forbid the
    namespaces bubblewrap needs, so one confined child is actually run.
    """
    mechanism = _mechanism()
    if mechanism is None:
        return f"no confinement mechanism is installed for {sys.platform}"
    with tempfile.TemporaryDirectory() as scratch:
        workspace = Path(scratch)
        try:
            probe = subprocess.run(
                [*_prefix_for(mechanism, workspace, ()), sys.executable, "-c", "import jarviscore"],
                cwd=scratch, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=30,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            reason = f"{mechanism} could not start a confined process: {exc}"
        else:
            if probe.returncode == 0:
                return None
            reason = (
                f"{mechanism} could not start a confined process "
                f"(exit {probe.returncode}): {probe.stderr.strip()}"
            )
    logger.warning("Process confinement unavailable: %s", reason)
    return reason


def confinement_prefix(workspace: Path, protected: Sequence[Path] = ()) -> Optional[List[str]]:
    """Command prefix that confines a child process, or None where none works.

    ``protected`` paths inside the workspace stay readable but not writable, so
    confined code cannot rewrite what the framework keeps there, such as the
    function registry.
    """
    if confinement_unavailable_reason() is not None:
        return None
    return _prefix_for(_mechanism(), workspace, protected)
