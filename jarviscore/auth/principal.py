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
#: What the person may do in their organisation (control.scopes): scope -> terms.
scopes: ContextVar[Optional[dict]] = ContextVar("jarviscore_scopes", default=None)
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
    #: What the person may do in their organisation, from your application's own
    #: roles: ``{"claims.approve": {"amount": "10000"}, "claims.vet": {}}`` or a list
    #: of scope names. Held at every call the work makes (control.scopes).
    scopes: Optional[dict] = field(default=None)

    def __post_init__(self):
        if not str(self.person or "").strip():
            raise ValueError("OnBehalfOf needs the person the work is for")
        object.__setattr__(self, "person", str(self.person).strip())
        if self.scopes is not None:
            from jarviscore.control.scopes import parse_grant

            object.__setattr__(self, "scopes", parse_grant(self.scopes))

    @classmethod
    def of(cls, tenant: str, user_id: str, mandate: Optional[dict] = None,
           scopes: Any = None) -> "OnBehalfOf":
        """A user of your application, in one of its tenants."""
        from jarviscore.auth.people import Person

        return cls(Person(tenant, user_id).key, mandate, scopes)


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
    found = {key: value for key, value in (
        ("acting_for", acting_for.get()), ("mandate", mandate.get()), ("scopes", scopes.get()),
    ) if value is not None}
    return found or None


@contextmanager
def act_for(person: Any, delegated: Optional[dict] = None, held: Any = None) -> Iterator[None]:
    """Run the enclosed work on behalf of ``person``, within what they ``delegated``.

    ``person`` is an :class:`OnBehalfOf`, a ``Person`` or a person key. ``delegated``
    is a mandate (control.mandate): the systems, effects, scopes and expiry the
    person granted for this work. ``held`` is what the person may do in their
    organisation (control.scopes). Both default to what an ``OnBehalfOf`` carries.

    Naming a person replaces the whole principal: work for Bob inside work for Ada
    never keeps Ada's mandate or scopes. With no person, a ``delegated`` mandate
    narrows the current work; with neither, nothing changes.
    """
    if person is not None and not isinstance(person, str):
        resolved = on_behalf_of(person)
        person = resolved.person
        delegated = delegated if delegated is not None else resolved.mandate
        held = held if held is not None else resolved.scopes
    if held is not None:
        from jarviscore.control.scopes import parse_grant

        held = parse_grant(held)
    tokens = []
    if person:
        tokens += [(acting_for, acting_for.set(str(person))),
                   (mandate, mandate.set(dict(delegated) if isinstance(delegated, dict) else None)),
                   (scopes, scopes.set(held))]
    elif isinstance(delegated, dict):
        tokens.append((mandate, mandate.set(dict(delegated))))
    try:
        yield
    finally:
        for variable, token in reversed(tokens):
            variable.reset(token)
