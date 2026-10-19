"""
People: who a person is, across the surfaces they use.

Multiplayer work is done by people in a tenant (a company, a team, a customer
of your product). A person is reached through accounts on surfaces: a Slack
user, a user of your web app. Every action in a room is taken by a ``Person``,
and who that is comes only from a surface's own authentication.

    identities = Identities(redis_store)
    alice = identities.person_for(Account("acme", "slack:T0123", "U0ALICE", "alice"))

An account seen for the first time becomes a person of its own. The same
human using two surfaces links them: on a surface where they are already
signed in, ``begin_link`` gives them a one-time code; entering it on the other
surface (``complete_link``, from that surface's authenticated account) makes
both accounts the same person, with the same roles and the same connected
accounts in Nexus.

Removing someone (``deprovision``) ends everything they could do at once:
their accounts stop resolving, room roles stop applying, and decisions or
answers waiting on them can no longer be given by them.
"""

from __future__ import annotations

import json
import secrets
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

#: How long a link code works, in seconds.
LINK_CODE_SECONDS = 600


class IdentityError(ValueError):
    """An account, link or person is not valid for this request."""


def _check(label: str, value: str) -> str:
    value = str(value or "").strip()
    if not value or "/" in value or "{" in value or "}" in value:
        raise IdentityError(f"{label} must be non-empty without '/', '{{' or '}}': {value!r}")
    return value


@dataclass(frozen=True)
class Person:
    """A person in a tenant. ``id`` is stable; ``name`` is how others see them."""

    tenant: str
    id: str
    name: str = ""

    def __post_init__(self):
        object.__setattr__(self, "tenant", _check("tenant", self.tenant))
        object.__setattr__(self, "id", _check("person id", self.id))

    @property
    def key(self) -> str:
        """Unique across tenants; what credentials and audit records are keyed by."""
        return f"{self.tenant}/{self.id}"

    @property
    def display(self) -> str:
        return self.name or self.id

    def to_record(self) -> Dict[str, str]:
        return {"tenant": self.tenant, "id": self.id, "name": self.name}

    @classmethod
    def from_record(cls, record: Dict[str, Any]) -> "Person":
        return cls(record["tenant"], record["id"], record.get("name", ""))


@dataclass(frozen=True)
class Account:
    """An authenticated account on a surface: who the surface says is speaking.

    ``issuer`` names the authority that authenticated them, such as
    ``slack:T0123`` (a Slack workspace) or ``app`` (your product's login).
    """

    tenant: str
    issuer: str
    subject: str
    name: str = ""

    def __post_init__(self):
        object.__setattr__(self, "tenant", _check("tenant", self.tenant))
        if not str(self.issuer or "").strip() or not str(self.subject or "").strip():
            raise IdentityError("An account needs the issuer that authenticated it and its subject")

    @property
    def ref(self) -> str:
        return f"{self.issuer}|{self.subject}"


class Identities:
    """Accounts, the people they are, links between them, and who has been removed.

    Stored in the mesh's Redis, so every surface and node sees the same people.
    """

    def __init__(self, redis_store):
        self._redis = redis_store._redis

    @staticmethod
    def _key(tenant: str, *parts: str) -> str:
        return ":".join(("people", "{" + tenant + "}", *parts))

    # ── The tenant's record of identity changes ────────────────────────────

    def _log(self, tenant: str, action: str, **fields) -> None:
        self._redis.xadd(self._key(tenant, "log"), {"action": action, "at": str(time.time()),
                                                     **{k: str(v) for k, v in fields.items()}})

    def log(self, tenant: str, since: float = 0.0) -> List[Dict[str, Any]]:
        """Who was added, linked, unlinked or removed in a tenant, oldest first."""
        entries = []
        for entry_id, data in self._redis.xrange(self._key(tenant, "log")):
            if float(data.get("at") or 0) >= since:
                entries.append({"id": entry_id, **data, "at": float(data.get("at") or 0)})
        return entries

    # ── Resolving ───────────────────────────────────────────────────────────

    def person_for(self, account: Account, *, auto_provision: bool = True) -> Person:
        """The person an authenticated account belongs to.

        An account never seen before becomes a person of its own, named after
        it, unless ``auto_provision`` is off (then ``IdentityError``). A removed
        person's accounts do not resolve.
        """
        account_key = self._key(account.tenant, "account", account.ref)
        person_id = self._redis.get(account_key)
        if person_id is None:
            if not auto_provision:
                raise IdentityError(f"{account.ref} is not a known person in {account.tenant}")
            person_id = self._provision(account)
        record = self._person_record(account.tenant, person_id)
        if record.get("status") == "removed":
            raise IdentityError(f"{record.get('name') or person_id} has been removed from {account.tenant}")
        if account.name and record.get("name") != account.name and record.get("named_by") == account.ref:
            self._update(account.tenant, person_id, lambda r: {**r, "name": account.name})
            record["name"] = account.name
        return Person(account.tenant, person_id, record.get("name") or account.name)

    def _provision(self, account: Account) -> str:
        base = _check("person id", f"{account.issuer}.{account.subject}".replace("/", "."))
        record = {"name": account.name, "named_by": account.ref, "status": "active",
                  "accounts": [account.ref], "created_at": time.time()}
        account_key = self._key(account.tenant, "account", account.ref)
        candidate = base
        # An id is never reused: an account that was unlinked, or moved to another
        # person, comes back as someone new, with none of the old person's roles.
        while not self._redis.set(self._key(account.tenant, "person", candidate), json.dumps(record), nx=True):
            candidate = f"{base}.{secrets.token_hex(3)}"
        # Two surfaces seeing a new account at once agree on one person.
        if self._redis.set(account_key, candidate, nx=True):
            self._log(account.tenant, "person.added", person=candidate, account=account.ref)
            return candidate
        self._redis.delete(self._key(account.tenant, "person", candidate))
        return self._redis.get(account_key)

    def _update(self, tenant: str, person_id: str, change, *, allow_removed: bool = False) -> Dict[str, Any]:
        """Apply ``change(record) -> record`` atomically. A removed person stays removed:
        nothing written from a record read before the removal can bring them back."""
        from redis.exceptions import WatchError  # only needed once there is a Redis

        key = self._key(tenant, "person", person_id)
        with self._redis.pipeline() as pipe:
            while True:
                try:
                    pipe.watch(key)
                    raw = pipe.get(key)
                    record = json.loads(raw) if raw else {"status": "active", "accounts": []}
                    if record.get("status") == "removed" and not allow_removed:
                        pipe.unwatch()
                        raise IdentityError(f"{record.get('name') or person_id} has been removed")
                    updated = change(dict(record))
                    if record.get("status") == "removed":
                        updated["status"] = "removed"
                    pipe.multi()
                    pipe.set(key, json.dumps(updated))
                    pipe.execute()
                    return updated
                except WatchError:
                    continue

    def _person_record(self, tenant: str, person_id: str) -> Dict[str, Any]:
        raw = self._redis.get(self._key(tenant, "person", person_id))
        return json.loads(raw) if raw else {"status": "active", "accounts": []}

    def get(self, tenant: str, person_id: str) -> Optional[Person]:
        """A person by id, or None if unknown or removed."""
        raw = self._redis.get(self._key(tenant, "person", person_id))
        if not raw:
            return None
        record = json.loads(raw)
        if record.get("status") == "removed":
            return None
        return Person(tenant, person_id, record.get("name", ""))

    def is_active(self, person: Person) -> bool:
        """False once the person has been removed. Unknown people (made directly
        with ``Person(...)`` by an application that manages its own users) are active."""
        return self._person_record(person.tenant, person.id).get("status") != "removed"

    def register(self, person: Person) -> Person:
        """Record a person an application manages itself (its own user ids)."""
        key = self._key(person.tenant, "person", person.id)
        record = {"name": person.name, "status": "active", "accounts": [], "created_at": time.time()}
        if not self._redis.set(key, json.dumps(record), nx=True):
            existing = json.loads(self._redis.get(key))
            if existing.get("status") == "removed":
                raise IdentityError(f"{person.display} has been removed from {person.tenant}")
        else:
            self._log(person.tenant, "person.registered", person=person.id)
        return person

    # ── Linking accounts ────────────────────────────────────────────────────

    def begin_link(self, person: Person) -> str:
        """A one-time code that makes another account this person, when entered from it."""
        if not self.is_active(person):
            raise IdentityError(f"{person.display} has been removed")
        code = secrets.token_hex(4)
        self._redis.set(self._key(person.tenant, "link", code), person.id, ex=LINK_CODE_SECONDS)
        return code

    def complete_link(self, account: Account, code: str) -> Person:
        """Make ``account`` (authenticated by its surface) the person who was given ``code``."""
        person_id = self._redis.getdel(self._key(account.tenant, "link", str(code).strip()))
        if person_id is None:
            raise IdentityError("That link code is unknown or has expired")
        record = self._person_record(account.tenant, person_id)
        if record.get("status") == "removed":
            raise IdentityError("That person has been removed")
        account_key = self._key(account.tenant, "account", account.ref)
        previous = self._redis.get(account_key)
        if previous and previous != person_id and \
                self._person_record(account.tenant, previous).get("status") == "removed":
            raise IdentityError("That account belongs to someone who was removed")
        record = self._update(account.tenant, person_id, lambda r: {
            **r, "accounts": sorted(set(r.get("accounts", [])) | {account.ref})})
        self._redis.set(account_key, person_id)
        self._log(account.tenant, "account.linked", person=person_id, account=account.ref,
                  previously=previous or "")
        if previous and previous != person_id:
            try:
                self._update(account.tenant, previous, lambda r: {
                    **r, "accounts": [a for a in r.get("accounts", []) if a != account.ref]})
            except IdentityError:
                pass
        return Person(account.tenant, person_id, record.get("name") or account.name)

    def accounts(self, person: Person) -> List[str]:
        return list(self._person_record(person.tenant, person.id).get("accounts", []))

    def unlink(self, account: Account) -> None:
        """The account no longer resolves to anyone; it is a new person next time."""
        account_key = self._key(account.tenant, "account", account.ref)
        person_id = self._redis.get(account_key)
        if person_id is None:
            return
        self._redis.delete(account_key)
        self._log(account.tenant, "account.unlinked", person=person_id, account=account.ref)
        self._update(account.tenant, person_id, lambda r: {
            **r, "accounts": [a for a in r.get("accounts", []) if a != account.ref]}, allow_removed=True)

    def deprovision(self, person: Person) -> None:
        """Remove a person: their accounts stop resolving and nothing they held applies.

        Their accounts stay tied to the removed person, so they are refused
        rather than coming back as someone new. ``unlink`` an account to let it
        be someone again.
        """
        self._update(person.tenant, person.id, lambda r: {**r, "status": "removed", "removed_at": time.time()},
                     allow_removed=True)
        self._log(person.tenant, "person.removed", person=person.id)
