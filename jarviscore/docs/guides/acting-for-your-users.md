---
icon: material/account-key
title: "Agents That Act for Your Users: Tenants, Consent, Mandates and Evidence"
description: "How to run JarvisCore agents on behalf of your application's own users and tenants: whom work is for, connecting each user's accounts, limiting what they delegate, approvals from your sign-in, and per-tenant evidence for their auditors."
---

# Agents That Act for Your Users

Your application already knows who its users are: it signs them in, and it may
have tenants, roles and an admin console. This guide connects that to
JarvisCore, so that an agent working for one of your users:

- uses **that user's own accounts** (their Salesforce, their Gmail), never
  another user's and never a shared service account;
- does **only what they delegated** for this work;
- leaves a record that **names them**, which you can hand to their auditor.

You keep user management. JarvisCore never authenticates your users; it acts for
whoever your application says the work is for.

---

## Which case are you?

| You are building | What you need |
|---|---|
| An internal tool, a script, one team | Nothing on this page. Work runs as the deployment's own user (`NEXUS_USER_ID`). |
| A product with signed-in users, each connecting their own accounts | [Name whom the work is for](#1-name-whom-the-work-is-for), [connect their accounts](#2-connect-each-users-accounts), [turn on subject binding](#3-make-nexus-hold-you-to-it) |
| A multi-tenant SaaS | All of the above with tenant-qualified people (`OnBehalfOf.of(tenant, user)`), plus [per-tenant evidence](#6-evidence-per-user-and-per-tenant) |
| Agents your users' admins configure | Also [mandates from your roles](#4-limit-what-they-delegated) and [approvals from your sign-in](#5-approvals-from-your-sign-in) |

---

## 1. Name whom the work is for

Every entry point takes `on_behalf_of`:

```python
from jarviscore import Mesh, OnBehalfOf

user = OnBehalfOf.of(session.tenant_id, session.user_id)   # "acme/u_123"

await mesh.run_task(agent="analyst", task="Summarise my open deals", on_behalf_of=user)
await mesh.execute_goal("Reconcile last month's invoices", on_behalf_of=user)
await mesh.workflow("wf-42", steps, on_behalf_of=user)
workflow_id = await mesh.submit_goal("Prepare the board pack", on_behalf_of=user)
```

`on_behalf_of` takes an `OnBehalfOf`, a `Person` (rooms and people peers), or a
person key string. For the length of the work it decides:

- whose credentials every provider call uses;
- what the work may do (its [mandate](#4-limit-what-they-delegated));
- whom every journal record names (`acting_for`).

It holds for every step, every sub-agent and every peer on any node of the mesh.

!!! warning "Always qualify by tenant"
    `OnBehalfOf.of("acme", "u_123")` is `acme/u_123`. Credentials, Nexus
    workspaces and records are keyed by this string, so two tenants that both
    have a user `u_123` must never share it. A tenant or user id containing `/`
    is refused.

Whom work is for comes only from your code, never from what a client sends or
an agent writes. `submit_goal` refuses a `context["acting_for"]` that disagrees
with `on_behalf_of`, so there is only ever one answer.

Inside your own async code, `act_for` does the same for a block:

```python
from jarviscore import act_for

with act_for(user):
    await my_custom_pipeline()     # every provider call in here is for that user
```

### From a chat endpoint

`create_chat_router` asks your application whom each chat is for:

```python
from fastapi import HTTPException, Request
from jarviscore import OnBehalfOf
from jarviscore.integrations import create_chat_router

async def signed_in_user(request: Request) -> OnBehalfOf:
    session = await my_auth.session(request)          # your sign-in, your tenants
    if session is None:
        raise HTTPException(status_code=401)
    return OnBehalfOf.of(session.tenant_id, session.user_id, mandate=session.mandate)

app.include_router(create_chat_router(kernel, on_behalf_of=signed_in_user), prefix="/api/v1")
```

The resolver can be sync or async. An exception you raise there (such as a 401)
becomes the response. Whatever the request body carries as `acting_for` or
`mandate` is dropped: a client cannot claim to be someone else.

---

## 2. Connect each user's accounts

A user connects an account once (OAuth consent through
[Nexus](nexus.md)), and work done for them finds it from then on, on any node:

```python
@app.post("/integrations/{provider}/connect")
async def connect(provider: str, request: Request):
    user = await signed_in_user(request)
    if await mesh.connected(provider, on_behalf_of=user):
        return {"connected": True}
    started = await mesh.connect(provider, on_behalf_of=user,
                                 return_url="https://app.example.com/integrations/done")
    return {"connected": False, "auth_url": started["auth_url"]}   # send the browser here
```

Each user's connection is stored in their own Nexus workspace, derived from the
person key. If work needs an account the user has not connected, the agent stops
and asks for consent through your [HITL surface](hitl.md); the link it raises is
for that user's workspace too.

---

## 3. Make Nexus hold you to it

JarvisCore names the person on every credential request (`X-Nexus-Subject`, with
the agent and the operation). Set the broker to refuse anything else:

```bash
SUBJECT_BINDING=required     # on nexus-broker
```

Then a connection id alone releases nothing: the broker releases a credential
only to work naming the subject that owns it, compared exactly. A credential
Nexus refuses is never replaced by another one; JarvisCore does not fall back to
a shared credential or the local store when it is acting for a person. Nexus
audits every release and refusal with subject, agent and operation.

Nexus trusts the subject your runtime names. Keep the gateway key with the
runtime, and authenticate users in your application, as above.

---

## 4. Limit what they delegated

A user's credential already limits the agent to what that user may do. A
**mandate** narrows it to what they handed over for this piece of work: which
systems, which effects, until when.

```python
user = OnBehalfOf.of(tenant, user_id, mandate={
    "systems": ["salesforce", "gmail"],
    "effects": ["read", "propose"],          # read, propose, write, notify, destructive
    "expires_at": "2026-11-01T00:00:00Z",
})
```

Derive it from your own roles. A viewer's agent gets `["read"]`; an admin's may
`write`. A call outside the mandate is refused (`outside-mandate`), recorded,
and never lifted by a deployment rule. A mandate that cannot be read refuses
everything. See [Control and Evidence](../concepts/control-and-evidence.md#acting-for-a-person).

---

## 5. Approvals from your sign-in

When an action needs a person's approval, your backend signs the approval after
your own sign-in, over the exact action. JarvisCore checks the signature and
your institution's approval rules:

```python
from jarviscore.control.approvals import sign_assertion

token = sign_assertion(APPROVAL_ASSERTION_KEY, subject=session.user_id, roles=session.roles,
                       decision="approved", workflow_id=w["workflow_id"],
                       action_id=w["action_id"], binding=w["binding"])
await mesh.resolve_hitl(w["workflow_id"], w["action_id"], decision="approved", assertion=token)
```

See [HITL: approving consequential actions](hitl.md#approving-an-agents-consequential-actions).

---

## 6. Evidence per user and per tenant

Everything an agent did for a user is in the journal under their name. Ask for
one user, or a whole tenant (a key ending in `/`):

```bash
jarviscore evidence acme/u_123
jarviscore evidence acme/
```

```text
2026-07-14T09:12:03Z  wf-42/pay  agent=ledger  for=acme/u_123  outcome=success
    2026-07-14T09:12:04Z  allowed      provider GET      erp.example/invoices
    2026-07-14T09:12:06Z  refused      provider POST     erp.example/payments  [outside-mandate]

1 run(s), 2 decision(s), 1 effect(s), 1 refused.
```

To hand a tenant's record to their auditor:

```bash
jarviscore evidence acme/ --export acme-evidence/
jarviscore verify --export acme-evidence/        # what the auditor runs; no keys, no network
```

The export holds that tenant's runs exactly as written, and the deployment's own
head log, so the auditor can check that every run is intact and is the one the
deployment recorded. A run that also worked for another tenant is left out and
listed, so one tenant never receives another's work. Add `--content` to include
what [replay](../concepts/control-and-evidence.md#replay) needs (tasks, model
calls, tool results); that is personal data, so include it only where that is
allowed. The head log carries run names and hashes for every run in the
deployment, not their content. An export proves each run in it is intact. It
cannot prove that no run was left out; that needs the whole journal and
`jarviscore verify`.

From Python, use `jarviscore.evidence.people.account(root, who)` and
`export(root, who, dest)` to build this into your admin console.

### Erasure

```bash
jarviscore evidence acme/u_123 --erase           # what would go
jarviscore evidence acme/u_123 --erase --yes     # erase it
```

This erases the replay content kept for that user's runs. The journal keeps only
digests, so it still verifies and still shows every decision; those runs can no
longer be replayed. Content another user's run also used (an identical task
text, say) is kept. Content unused for `JOURNAL_CONTENT_DAYS` (30 by default) is
erased anyway.

---

## Checklist

- [ ] Every entry point your users reach passes `on_behalf_of`, built from your sign-in, never from request data.
- [ ] People are tenant-qualified: `OnBehalfOf.of(tenant, user)`.
- [ ] `create_chat_router(..., on_behalf_of=...)` if you expose chat.
- [ ] Each user connects their own accounts (`mesh.connect`); no shared service credentials for user work.
- [ ] Nexus broker runs with `SUBJECT_BINDING=required`.
- [ ] Mandates come from your roles.
- [ ] Approvals are signed by your backend (`APPROVAL_ASSERTION_KEY`).
- [ ] You know how to answer "what did the agent do for us?" (`jarviscore evidence acme/ --export`).
