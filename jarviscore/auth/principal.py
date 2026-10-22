"""
Who an agent is acting for right now.

A shared agent does work for many people. Each of them connects their own
accounts in Nexus, in their own workspace, and a step must use the
credentials of the person who asked for it: their access, and their name in
the provider's audit log, never a shared identity that holds everyone's.

The Mesh sets this for the duration of each step from the workflow's
``acting_for`` (a room sets it to whoever asked). Anything that resolves a
credential reads it; with nobody set, the deployment's default identity is
used, as before.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator, Optional

acting_for: ContextVar[Optional[str]] = ContextVar("jarviscore_acting_for", default=None)


@contextmanager
def act_for(person: Optional[str]) -> Iterator[None]:
    """Run the enclosed work on behalf of ``person`` (no change when empty)."""
    if not person:
        yield
        return
    token = acting_for.set(str(person))
    try:
        yield
    finally:
        acting_for.reset(token)
