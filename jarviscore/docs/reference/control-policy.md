---
icon: material/file-cog
title: "Control Policy Reference: Every Section, Key and Built-in Rule"
description: "The complete schema of JarvisCore's control policy file (rules, approvals, principals, grounding, effects, scopes), the built-in refusals, the journal's event kinds, and the Python API."
---

# Control Policy Reference

`CONTROL_POLICY_PATH` names one YAML or JSON file with up to six sections (`rules`, `approvals`, `principals`, `grounding`, `effects`, `scopes`). All
are optional. To adopt it step by step, see [Turning On Control](../guides/control-policy.md);
for what each part guarantees, [Control and Evidence](../concepts/control-and-evidence.md).

**Fail closed.** A file that cannot be read refuses every provider call and
every effect, and requires a verified approver for every action. A rule that
cannot be read refuses what it matches (or everything, when its `match` cannot be
read). `jarviscore policy check` names each such problem before you deploy.

The file is read again when it changes on disk; no restart is needed.

---

## `rules`: provider calls

Refuse more provider calls, or lift `mutation-without-atom` for your own code.

```yaml
rules:
  - name: no-deletes
    decision: deny
    match: {method: DELETE}
  - name: our-crm-client
    decision: allow
    match: {provider: hubspot, code_origin: direct}
```

| Key | Values |
|---|---|
| `name` | Recorded with every decision the rule makes |
| `decision` | `deny`, or `allow` (lifts only `mutation-without-atom`); anything else is treated as `deny` |
| `match.provider` / `system` | Provider name |
| `match.atom` | Integration name |
| `match.effect` | `read`, `propose`, `write`, `notify`, `destructive` |
| `match.method` | HTTP method |
| `match.code_origin` | `runtime`, `shipped`, `registry`, `model`, `direct` |
| `match.verified` | Whether the call is one of the operations the integration's code verifiably sends |

A list matches any of its values. All keys must match.

## `approvals` and `principals`: who decides

```yaml
approvals:
  - name: payments-need-finance
    match: {provider: erp, effect: [write, destructive]}
    roles: [finance]
    distinct_from: [requester]
    assurance: verified
  - name: drafts-need-nobody
    match: {atom: gmail_create_draft}
    require: none
principals:
  carol@example.com: [finance]
```

| Key | Values |
|---|---|
| `match` | `provider`/`system`, `atom`, `effect`. The first matching rule decides |
| `require` | `approval` (default) or `none`. `none` never removes approval from a destructive action |
| `roles` | The approver must hold one (from their assertion, or `principals`) |
| `distinct_from` | `[requester]`: the person the run acts for may not approve it |
| `assurance` | Least identity strength: `unauthenticated`, `asserted` (an `Approver` from your code), `verified` (an assertion signed with `APPROVAL_ASSERTION_KEY`) |
| `principals` | Roles held per approver, when their sign-in does not carry them |

Without a matching rule, the integration's own `ATOM_POLICY` decides. See
[HITL: Who may approve](../guides/hitl.md#who-may-approve).

## `grounding`: values from the system of record

Request fields that must come from records the runtime read itself.

```yaml
grounding:
  - name: pay-the-supplier-on-record
    match: {provider: erp, method: POST, path: /payments}
    bind:
      - name: invoice
        read: {provider: erp, path: "/invoices/{id}"}
        where: {id: request.json.invoice}
      - name: supplier
        read: {provider: erp, path: "/suppliers/{id}"}
        where: {id: invoice.supplier_id}
    require:
      - {field: request.json.iban, equals: supplier.iban, as: iban}
      - {field: request.json.amount, at_most: invoice.amount_due, as: money}
    selectors_from: [input, request]
    other_fields: deny
    fresh: run
    max_age_seconds: 900
```

| Key | Values |
|---|---|
| `match` | `provider`/`system`, `method`, `atom`, `host`, `path` (a template such as `/payments/{id}`) |
| `bind[]` | Records to follow, in order. `name`; `read.provider`, `read.path` (template); `read.record` (dot path to the record in the response), or `read.items` + `read.key` for a list; `where`: path variables or record fields, each selected by an expression |
| Expressions | `request.json.*`, `request.form.*`, `request.query.*`, `request.path.*`, `input.*` (the caller's `execute_goal(context=...)`), or an earlier binding (`invoice.supplier_id`). `[*]` expands a list |
| `require[]` | `field` (a `request.*` path), one of `equals`, `one_of`, `at_most`, and `as` |
| `as` | `exact` (default), `id`, `text` (NFC, exact), `iban` (ISO 13616 with check digits), `money` and `number` (decimal), `email` (IDNA domain) |
| `selectors_from` | Where `where` may take selectors from: `input`, `request`. `[input]` pins which record to the caller |
| `other_fields` | `deny`: the request may send no top-level field no requirement or selector names |
| `fresh` | `run` (default): any read in this workflow; `reread`: read each record again just before the call |
| `max_age_seconds` | Ignore reads older than this |

## `effects`: everything else

```yaml
effects:
  - name: shop-api
    decision: allow
    match: {sink: browser, target: "api.shop.example/*"}
  - name: no-broadcast
    decision: deny
    match: {sink: peer, action: broadcast}
```

| Key | Values |
|---|---|
| `decision` | `deny`, or `allow` (lifts only `unconfined-execution` and `browser-send-off-site`) |
| `match.sink` | `code`, `process`, `artifact`, `workspace`, `memory`, `peer`, `output`, `browser` |
| `match.action` | `run`; `publish`; `export`, `write`, `append`; `send`, `delegate`, `broadcast`; `deliver`; `navigate` |
| `match.origin` | `runtime`, `shipped`, `registry`, `model`, `page` |
| `match.agent` | Agent id |
| `match.target` | Glob over the target: a host and path (`browser`), artifact key, recipient, command, memory kind, step id |
| `match.confined` | `true` or `false`: whether code ran in a confined child |

---

## `scopes`: what each person may do in your organisation

```yaml
scopes:
  require:
    - name: claim-approval
      match: {provider: guidewire, method: POST, path: "/claims/{id}/approve"}
      requires: claims.approve
      limits:
        - {field: json.amount, kind: money, at_most: amount}
    - name: claim-payment
      match: {provider: guidewire, method: POST, path: "/claims/{id}/payments"}
      requires: claims.pay
      approved_by: claims.approve
      limits:
        - {field: json.amount, kind: money, at_most: amount}
    - name: finance-portal
      match: {sink: browser, target: "finance.acme.com/*"}
      requires: finance.reports.read
  grants:
    acme/carol: {claims.approve: {amount: "10000"}, claims.vet: {}}
  unattended: {}
```

| Key | Meaning |
|---|---|
| `require[].match` | A provider call (`provider`/`system`, `method`, `host`, `path` with `{variables}`, `atom`, `effect`) or another effect (`sink`, `action`, `target` glob, `origin`, `agent`), not both. Match the operation (`method` and `path`) to hold any code reaching it; `atom` alone holds only that integration |
| `require[].requires` | The scope the person the work is for must hold |
| `require[].approved_by` | The scope the approver must hold (provider calls only). The action then always needs an approval from an `asserted` or `verified` approver |
| `require[].limits` | Each `{field, kind, at_most\|one_of\|equals: <term>}`: the request `field` (`json.*`, `query.*`, `form.*`, `path.<variable>`; effects: `attributes.*`, `target`) compared as `kind` (`money`, `number`, `email`, `iban`, `id`, `text`, `exact`) with the holder's grant term. `at_most` takes `money` or `number` |
| `grants` | Scopes per person key, for people whose sign-in does not carry them. Your application's `OnBehalfOf(..., scopes=...)` comes first for every scope it names |
| `unattended` | Scopes work done for no one holds |

A grant is `{scope: {term: value}}` or a list of scope names. A term the
requirement checks and the grant does not state is refused; `"*"` states no
limit. Every requirement a call matches must hold. A value the request does not
carry, or carries in a body that cannot be read, is refused; every item of a list
is checked. A requirement that cannot be read refuses what it matches (everything,
when its match cannot be read); a `scopes` section that cannot be read refuses
everything. `jarviscore policy check` names each problem; `jarviscore policy
scopes` prints who may do what.

Browser requests are intercepted, in report mode too, wherever a `sink: browser`
requirement exists, so a refusal stops them. A page's own reads (`fetch`/XHR
`GET`) are not decided on; its navigations and sends are.

## Mandate (workflow context, not this file)

What a person delegated travels with the work, registered by your application:
`execute_goal(..., on_behalf_of=OnBehalfOf(person, mandate={...}, scopes={...}))` (or the same
`on_behalf_of` on `run_task`, `workflow`, `submit_goal`, `create_chat_router`).

| Key | Values |
|---|---|
| `systems` | Providers the work may call |
| `effects` | Any of `read`, `propose`, `write`, `notify`, `destructive` |
| `scopes` | Of the person's own scopes, the ones this work may use (narrows, never widens) |
| `expires_at` | ISO 8601 time with a zone, or epoch seconds |

Unknown keys or malformed values make the mandate unreadable, which refuses every
call. See [Acting for a person](../concepts/control-and-evidence.md#acting-for-a-person).

## Built-in refusals

Made in report and strict mode alike; enforced only in strict, except what a
person may do (`outside-mandate`, `scope-missing`, `over-scope-limit`), which is
enforced in report mode too: your application said what the person may do.

| Rule | Refuses | Liftable |
|---|---|---|
| `outside-mandate` | A provider call outside what the person delegated (system, effect, expiry, scopes) | No |
| `scope-missing` | A call or effect needing a scope the person (or, for `approved_by`, the approver) does not hold, or one a `scopes` section that cannot be read may cover | No |
| `over-scope-limit` | A request beyond the limit of the holder's scope, or one whose limit cannot be checked | No |
| `approval-missing` | A gated action reaching the broker without its approval | No |
| `ungrounded-argument` | A call a `grounding` rule matches whose values are not grounded | No |
| `mutation-without-atom` | A provider mutation not from an integration | `rules: allow` |
| `beyond-declared-effect` | A method beyond the integration's declared effect. For code not shipped with JarvisCore (registry, model, direct), a call is never taken as less than its method: a "read" that POSTs is a write | No |
| `outside-contract` | Model-written code sending an operation its code does not contain | No |
| `unverified-model-code` | Model-written code mutating where its operations cannot be read | No |
| `unapproved-model-effect` | Model-written code mutating without an approval of that exact action | No |
| `unconfined-execution` | Model or registry code, or a model-chosen host command, outside a confined sandbox | `effects: allow` |
| `browser-send-off-site` | A page sending data to a host other than its own | `effects: allow` |

## The journal

Each workflow step's run is a file of hash-linked events under `JOURNAL_DIR/runs/`,
with every run's latest event registered in `JOURNAL_DIR/heads.jsonl`.

| Kind | Holds |
|---|---|
| `policy.decision` | One decision: the call or effect, `outcome`, `rule`, `enforced`, `acting_for`, the `reason` for a refusal, for grounded calls the checks and the reads cited, and for scoped calls the requirements, each holder, whether they held the scope and each limit's outcome (`scope`; never the values) |
| `policy.preview` | A decision on a previewed action, before anyone was asked |
| `effect.attempt` / `effect.outcome` | That it was attempted, and what became of it |
| `approval.request` / `decision` / `refused` / `claim` / `settle` / `reopened` / `reconciled` | An approval's life |

Records hold methods, hosts, paths, sizes and digests, never bodies, query
strings or credentials.

## Python API

| Name | Use |
|---|---|
| `jarviscore.control.policy.check_policy(path)` | `(problems, summary)` for a policy file, as `jarviscore policy check` |
| `jarviscore.control.policy.review_journal(root)` | Refusals grouped by rule and target, as `jarviscore policy review` |
| `jarviscore.control.effects.mediated(Effect(...))` | Decide on and record your own effect ([guide](../guides/control-policy.md#your-own-effects)) |
| `jarviscore.evidence.journal.verify(root)` | The checks `jarviscore verify` runs |
| `jarviscore.control.approvals.sign_assertion(..., scopes=...)` | Sign an approval in your backend, for `verified` assurance, with the approver's scopes |
| `jarviscore.OnBehalfOf(person, mandate=..., scopes=...)` | Whom work is for, what they delegated, what they may do |
| `jarviscore.control.scopes.parse_section(raw)` | The `scopes` section as the deployment reads it |

Settings: `CONTROL_MODE`, `CONTROL_POLICY_PATH`, `JOURNAL_DIR`,
`APPROVAL_ASSERTION_KEY(S)` ([Configuration](configuration.md)).
