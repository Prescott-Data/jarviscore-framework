"""Project configuration (`jarviscore.yaml`) for `jarviscore dev` and deploy commands."""

from importlib import import_module
from typing import TYPE_CHECKING

# Resolved on first access (PEP 562) so `project._names` does not load pydantic models.
_LAZY = {
    **dict.fromkeys(
        ["LoadedProject", "ProjectError", "build_env", "find_root", "load_project"], "loader"),
    **dict.fromkeys(["Accessory", "Agent", "EnvSpec", "Project", "Proxy", "Server"], "schema"),
}


def __getattr__(name: str):
    if name not in _LAZY:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module(f".{_LAZY[name]}", __name__), name)
    globals()[name] = value
    return value


def __dir__():
    return sorted(set(globals()) | set(_LAZY))


if TYPE_CHECKING:
    from .loader import LoadedProject, ProjectError, build_env, find_root, load_project
    from .schema import Accessory, Agent, EnvSpec, Project, Proxy, Server

__all__ = [
    "Accessory", "Agent", "EnvSpec", "LoadedProject", "Project", "ProjectError", "Proxy",
    "Server", "build_env", "find_root", "load_project",
]
