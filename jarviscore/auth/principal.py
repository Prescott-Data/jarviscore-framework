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
#: What the person delegated for this work (systems, effects, expiry): see control.mandate.
mandate: ContextVar[Optional[dict]] = ContextVar("jarviscore_mandate", default=None)
#: The operation a credential is being resolved for, sent to Nexus with the request.
operation: ContextVar[Optional[str]] = ContextVar("jarviscore_operation", default=None)


@contextmanager
def act_for(person: Optional[str], delegated: Optional[dict] = None) -> Iterator[None]:
    """Run the enclosed work on behalf of ``person``, within what they ``delegated``.

    No change when both are empty. ``delegated`` is a mandate (control.mandate):
    the systems, effects and expiry the person granted for this work.
    """
    token = acting_for.set(str(person)) if person else None
    granted = mandate.set(dict(delegated)) if isinstance(delegated, dict) else None
    try:
        yield
    finally:
        if granted is not None:
            mandate.reset(granted)
        if token is not None:
            acting_for.reset(token)
