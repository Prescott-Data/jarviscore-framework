"""Core framework classes."""

from typing import TYPE_CHECKING

from .agent import Agent
from .profile import Profile

if TYPE_CHECKING:
    from .mesh import Mesh, MeshMode

__all__ = ["Agent", "Profile", "Mesh", "MeshMode"]


def __getattr__(name: str):
    if name not in {"Mesh", "MeshMode"}:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    # Lightweight core helpers are also used by search. Eagerly loading Mesh
    # here imports the researcher, which needs the not-yet-defined InternetSearch.
    from .mesh import Mesh, MeshMode

    globals().update(Mesh=Mesh, MeshMode=MeshMode)
    return globals()[name]


def __dir__():
    return sorted(set(globals()) | set(__all__))
