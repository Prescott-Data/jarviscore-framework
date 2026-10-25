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
from dataclasses import dataclass, field
from typing import Any, Iterator, Optional

acting_for: ContextVar[Optional[str]] = ContextVar("jarviscore_acting_for", default=None)
#: What the person delegated for this work (systems, effects, expiry): see control.mandate.
mandate: ContextVar[Optional[dict]] = ContextVar("jarviscore_mandate", default=None)
#: The operation a credential is being resolved for, sent to Nexus with the request.
operation: ContextVar[Optional[str]] = ContextVar("jarviscore_operation", default=None)


@dataclass(frozen=True)
class OnBehalfOf:
    """Who a piece of work is for, and what they delegated for it.

    ``person`` is the key credentials, records and Nexus workspaces are keyed by.
    In a multi-tenant application make it unique across tenants with
    :meth:`of` (``"acme/u_123"``), so the same user id in two tenants never shares
    a credential. ``mandate`` (optional) narrows the work to the systems, effects
    and time the person delegated (control.mandate).
    """

    person: str
    mandate: Optional[dict] = field(default=None)

    def __post_init__(self):
        if not str(self.person or "").strip():
            raise ValueError("OnBehalfOf needs the person the work is for")
        object.__setattr__(self, "person", str(self.person).strip())

    @classmethod
    def of(cls, tenant: str, user_id: str, mandate: Optional[dict] = None) -> "OnBehalfOf":
        """A user of your application, in one of its tenants."""
        from jarviscore.auth.people import Person

        return cls(Person(tenant, user_id).key, mandate)


def on_behalf_of(value: Any) -> Optional[OnBehalfOf]:
    """``value`` as an :class:`OnBehalfOf`: one, a ``Person``, a person key, or None."""
    if value is None or value == "":
        return None
    if isinstance(value, OnBehalfOf):
        return value
    key = getattr(value, "key", None)
    if isinstance(key, str):
        return OnBehalfOf(key)
    if isinstance(value, str):
        return OnBehalfOf(value)
    raise TypeError(f"on_behalf_of takes an OnBehalfOf, a Person or a person key, not {type(value).__name__}")


def registered() -> Optional[dict]:
    """Whom the current work is for, as a workflow registers it (``acting_for``, ``mandate``).

    Taken from the runtime, never from what an agent wrote, so the steps of a
    workflow started inside this work act for the same person on any node.
    """
    found = {key: value for key, value in (("acting_for", acting_for.get()), ("mandate", mandate.get()))
             if value is not None}
    return found or None


@contextmanager
def act_for(person: Any, delegated: Optional[dict] = None) -> Iterator[None]:
    """Run the enclosed work on behalf of ``person``, within what they ``delegated``.

    ``person`` is an :class:`OnBehalfOf`, a ``Person`` or a person key. No change
    when both are empty. ``delegated`` is a mandate (control.mandate): the systems,
    effects and expiry the person granted for this work; it defaults to the one an
    ``OnBehalfOf`` carries.
    """
    if person is not None and not isinstance(person, str):
        resolved = on_behalf_of(person)
        person, delegated = resolved.person, delegated if delegated is not None else resolved.mandate
    token = acting_for.set(str(person)) if person else None
    granted = mandate.set(dict(delegated)) if isinstance(delegated, dict) else None
    try:
        yield
    finally:
        if granted is not None:
            mandate.reset(granted)
        if token is not None:
            acting_for.reset(token)
