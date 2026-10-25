---
icon: material/account-key
title: "Agents That Act for Your Users: Tenants, Consent, Scopes, Mandates and Evidence"
description: "How to run JarvisCore agents on behalf of your application's own users and tenants: whom work is for, connecting each user's accounts, limiting what they delegate, approvals from your sign-in, and per-tenant evidence for their auditors."
---

# Agents That Act for Your Users

Your application already knows who its users are: it signs them in, and it may
have tenants, roles and an admin console. This guide connects that to
JarvisCore, so that an agent working for one of your users:

- uses **that user's own accounts** (their Salesforce, their Gmail), never
  another user's and never a shared service account;
- does **only what they may do in your organisation** (your scopes: approve
  claims up to their limit, read financial reports) and **only what they
  delegated** for this work;
- leaves a record that **names them**, which you can hand to their auditor.

You keep user management. JarvisCore never authenticates your users; it acts for
whoever your application says the work is for.

---

## Which case are you?

| You are building | What you need |
|---|---|
| An internal tool, a script, one team | Nothing on this page. Work runs as the deployment's own user (`NEXUS_USER_ID`). |
| A product with signed-in users, each connecting their own accounts | [Name whom the work is for](#1-name-whom-the-work-is-for), [connect their accounts](#2-connect-each-users-accounts), [turn on subject binding](#3-make-nexus-hold-you-to-it) |
| A multi-tenant SaaS | All of the above with tenant-qualified people (`OnBehalfOf.of(tenant, user)`), plus [per-tenant evidence](#7-evidence-per-user-and-per-tenant) |
| Teams where only some people may do some things (approve claims, read financial reports, file a SAR) | Also [your organisation's scopes](#4-hold-them-to-your-organisations-scopes) |
| Agents your users' admins configure | Also [mandates from your roles](#5-limit-what-they-delegated-for-this-work) and [approvals from your sign-in](#6-approvals-from-your-sign-in) |

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
- what the work may do (their [scopes](#4-hold-them-to-your-organisations-scopes) and its [mandate](#5-limit-what-they-delegated-for-this-work));
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

## 4. Hold them to your organisation's scopes

A provider's own scopes (`read`, `write`) say what a credential can reach. They
cannot say that only Carol may approve claims, and only up to 10,000; that
suspicious-activity reports go only to the MLRO; that only finance opens
financial reports. Those are **your organisation's scopes**, you define them, and
an agent working for a person holds exactly that person's.

**Your application says what each person holds**, from its own roles or identity
provider:

```python
carol = OnBehalfOf.of("acme", "carol", scopes={
    "claims.vet": {},
    "claims.approve": {"amount": "10000"},             # a level: up to 10,000
    "fincrime.sar.send": {"recipients": ["mlro@acme.com"]},
})
await mesh.execute_goal("Settle the claims in today's queue", on_behalf_of=carol)
```

**Your policy file says which operations need which scope**, and the limits:

```yaml title="control-policy.yaml"
scopes:
  require:
    - name: claim-approval
      match: {provider: guidewire, method: POST, path: "/claims/{id}/approve"}
      requires: claims.approve
      limits:
        - {field: json.amount, kind: money, at_most: amount}
    - name: sar-recipients
      match: {provider: casework, method: POST, path: "/sars/{id}/send"}
      requires: fincrime.sar.send
      limits:
        - {field: json.to, kind: email, one_of: recipients}
    - name: financial-reports
      match: {provider: erp, method: GET, path: "/reports/financial/{id}"}
      requires: finance.reports.read
    - name: finance-portal                   # the same, in a browser
      match: {sink: browser, target: "finance.acme.com/*"}
      requires: finance.reports.read
```

Then, for work done for Carol: a 4,000 claim is approved; a 40,000 claim is
refused (`over-scope-limit`); a SAR to anyone but the MLRO is refused. For Dave,
who holds only `claims.vet`, approving any claim is refused (`scope-missing`).

**The answer is no, every time:**

- **In report mode too.** Your application said what the person may do, so a
  scope is never only reported. (`CONTROL_MODE=off` switches all control off.)
- **Whatever code tries.** Match on the operation (`method` and `path`), and an
  integration, code the model wrote, or your own client reaching it are all held.
  `atom:` alone holds only that integration; `jarviscore policy scopes` flags it.
- **Fail closed.** A grant that does not state a limit the requirement checks is
  refused; `"*"` states that there is none. A value the request does not carry, or
  carries where it cannot be read, is refused. Every item of a list is checked.
- **Checked on what leaves.** Limits are read from the request as it is sent, with
  typed comparison (money as decimals, email by domain). Add a
  [grounding rule](../concepts/control-and-evidence.md#grounding) on the same
  operation, and the amount must also be the claims system's own figure, so an
  agent cannot understate it to get under the limit.
- **No deployment rule lifts it**, and the agent never holds more than the person:
  a [mandate](#5-limit-what-they-delegated-for-this-work) can narrow scopes for one
  piece of work (`"scopes": ["claims.vet"]`), never widen them.

**Doing and authorising are different scopes.** `approved_by` requires that
whoever approves holds a scope, within its limits for this exact request:

```yaml
    - name: claim-payment
      match: {provider: guidewire, method: POST, path: "/claims/{id}/payments"}
      requires: claims.pay              # the person the agent works for
      approved_by: claims.approve       # whoever approves it
      limits:
        - {field: json.amount, kind: money, at_most: amount}
```

Such an action always waits for an approval, whatever the `approvals:` rules
say, and only an approver known to hold the scope may give it: one your backend
signs with `sign_assertion(..., scopes=...)`, or an `Approver(..., scopes=...)`
your code builds (a bare name is refused). The approver's limit is checked
against the request when the action runs.

**People without your sign-in** (rooms, people peers) take their scopes from the
policy file; your application's grant comes first for any scope it names:

```yaml
scopes:
  grants:
    acme/carol: {claims.approve: {amount: "10000"}}
  unattended: {}       # what work done for no one holds
```

The agent is told what is out of reach. An integration every one of whose
operations needs a scope the person lacks is shown to it as refused: calling it
runs nothing, reaches nothing, and returns the refusal, which is recorded. So
the agent says the person may not, rather than reaching for the nearest thing
it can do (an agent that could not see "approve" was seen raising a payment
instead). Every decision records the
requirements and limits it was checked against (never the values), and
`jarviscore evidence` shows them. `jarviscore policy scopes` prints who may do
what, for you and your auditors.

---

## 5. Limit what they delegated for this work

A user's credential and scopes already limit the agent to what that user may do.
A **mandate** narrows it to what they handed over for this piece of work: which
systems, which effects, which of their scopes, until when.

```python
user = OnBehalfOf.of(tenant, user_id, mandate={
    "systems": ["salesforce", "gmail"],
    "effects": ["read", "propose"],          # read, propose, write, notify, destructive
    "scopes": ["claims.vet"],                # of their scopes, these only
    "expires_at": "2026-11-01T00:00:00Z",
})
```

Derive it from your own roles. A viewer's agent gets `["read"]`; an admin's may
`write`. A call outside the mandate is refused (`outside-mandate`), in report
mode as in strict, recorded, and never lifted by a deployment rule. A mandate
that cannot be read refuses everything. See
[Control and Evidence](../concepts/control-and-evidence.md#acting-for-a-person).

---

## 6. Approvals from your sign-in

When an action needs a person's approval, your backend signs the approval after
your own sign-in, over the exact action. JarvisCore checks the signature and
your institution's approval rules:

```python
from jarviscore.control.approvals import sign_assertion

approver = OnBehalfOf.of(session.tenant_id, session.user_id)
token = sign_assertion(APPROVAL_ASSERTION_KEY, subject=approver.person, roles=session.roles,
                       scopes=session.scopes,          # for approved_by scopes
                       decision="approved", workflow_id=w["workflow_id"],
                       action_id=w["action_id"], binding=w["binding"])
await mesh.resolve_hitl(w["workflow_id"], w["action_id"], decision="approved", assertion=token)
```

Use the approver's person key (`OnBehalfOf.of(tenant, user).person`) as the
subject, so `grants` and the record name them as everywhere else. See
[HITL: approving consequential actions](hitl.md#approving-an-agents-consequential-actions).

---

## 7. Evidence per user and per tenant

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
- [ ] What only some people may do is a scope: required in `scopes.require` (matched on the operation), granted on `OnBehalfOf(..., scopes=...)` from your roles.
- [ ] `jarviscore policy check` and `jarviscore policy scopes` read your policy as you meant it.
- [ ] Mandates come from your roles.
- [ ] Approvals are signed by your backend (`APPROVAL_ASSERTION_KEY`), with the approver's scopes where `approved_by` asks for them.
- [ ] You know how to answer "what did the agent do for us?" (`jarviscore evidence acme/ --export`).
