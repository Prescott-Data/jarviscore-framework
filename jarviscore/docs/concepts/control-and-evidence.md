---
icon: material/scale-balance
title: "Control and Evidence: Decided Before It Leaves, Recorded So It Can Be Checked"
description: "How JarvisCore decides on every provider call before any network I/O, refuses what policy does not allow in strict mode, and records each decision in a hash-linked journal anyone can verify offline."
---

# Control and Evidence

The model proposes. The runtime decides what runs, and keeps a record anyone can
check. Every **call to a connected provider** (GitHub, Slack, ERPs and the rest of
the catalogue) and every **other effect** an agent has outside its step (code it
runs, commands on the host, files it publishes, changes it exports, memories it
keeps, messages to other agents, the result it delivers) is decided before it
happens and recorded.

| What | Where |
|---|---|
| Every provider call is decided on before anything leaves | `NexusCallProxy` |
| What an integration's code can send, read from that code | `jarviscore.control.operations` |
| The decision rules | `jarviscore.control.policy` |
| Every other effect, decided where it happens | `jarviscore.control.effects` |
| The record of decisions and calls | `jarviscore.evidence.journal` |
| Checking the record | `jarviscore verify` |

To adopt it, follow [Turning On Control](../guides/control-policy.md); every
key of the policy file is in the [Control Policy Reference](../reference/control-policy.md).
The exact claims, their assumptions and the tests behind them are in
[`claims/`](https://github.com/Prescott-Data/jarviscore-framework/tree/main/claims).

---

## Modes

`CONTROL_MODE` sets what happens to a call policy does not allow.

| Mode | Decides | Records | Refuses |
|---|---|---|---|
| `off` | No | No | No |
| `report` (default) | Yes | Yes | No: the call goes through, marked as one strict mode would refuse |
| `strict` | Yes | Yes | Yes, before any network I/O, including the credential lookup |

Start in `report`, read what strict mode would have refused (`jarviscore policy
review` groups it by rule and target, with what to do about each), then switch
to `strict`.

In strict mode a decision that cannot be recorded refuses the call too: the
promise is that every call that leaves has its decision on record.

---

## What is decided

Each call is built from what is actually about to be sent (provider, method, URL)
and the authority it arrives with: the integration (atom), its declared effect,
and where its code came from.

| Where the code came from | Trusted to | Held to |
|---|---|---|
| `shipped`: an integration in the JarvisCore package | Run as written; reviewed, statically checked | The methods its declared effect allows. A read may POST (search and query endpoints), never PUT, PATCH or DELETE; only a destructive integration may DELETE. |
| `runtime`: the framework's own transports (the Slack room, workspace sources) | Run as written | The effect each declares (`notify`, `read`) |
| `registry` or `model`: code the model wrote or repaired, or a stored integration | Nothing beyond what its code verifiably sends | Every mutating call must be one of the operations its own code sends, read before it runs, within its declared effect |
| `direct`: an application calling the proxy itself | Reads | A mutation must come from an atom, unless a deployment rule lifts that for a named provider |

**Built-in refusals:**

| Rule | Refuses |
|---|---|
| `mutation-without-atom` | POST, PUT, PATCH or DELETE that does not come from an integration with a declared effect |
| `beyond-declared-effect` | A method beyond the integration's declared effect (a write that deletes, a read that updates) |
| `outside-contract` | Model-written code sending an operation its own code does not contain |
| `unverified-model-code` | Model-written code mutating when its operations cannot be read statically |

### Operation contracts

`read_operations(source, entry)` reads, from an integration's own code, every
operation it can send through `nexus_call`: method and URL template. It follows
module constants, local variables, closures and helper calls from the
integration's entry function, and prunes dispatcher branches the call can never
take (`if method == "get": ...`).

Across the catalogue shipped with 2.4.0:

- 914 of 1,186 integrations have a fully verified contract.
- The rest build a URL or method at run time (request signing, RPC-style APIs where the operation is in the body). They are held to their declared effect and recorded as unverified.
- **No shipped integration contains reachable code that can send beyond its declared effect.** A test checks this on every build (`claims/shipped-atoms-within-declared-effect.yaml`).

---

## Deployment rules

`CONTROL_POLICY_PATH` names a JSON or YAML file of rules. A `deny` rule refuses
more; an `allow` rule can lift only the atomless-mutation refusal, for code the
deployment owns. Nothing a deployment writes can let model-written code send what
its own code does not.

```yaml
rules:
  - name: no-payments-from-agents
    decision: deny
    match: {provider: stripe, effect: [write, destructive]}
  - name: no-deletes
    decision: deny
    match: {method: DELETE}
  - name: our-crm-client
    decision: allow            # our own reviewed client calls the proxy directly
    match: {provider: hubspot, code_origin: direct}
```

Match keys: `provider`, `atom`, `effect`, `method`, `code_origin`, `verified`. A
list matches any of its values. A rule with any other decision is treated as
`deny`, and a file that cannot be read refuses every call.

---

## The journal

Each workflow step is one run file of JSON lines under `JOURNAL_DIR` (default
`.jarviscore/journal`). For every provider call:

| Event | Written | Holds |
|---|---|---|
| `policy.decision` | Before anything leaves | Provider, method, host, path, integration, effect, code origin, whether its contract verified the call, outcome, rule, whether it was enforced |
| `effect.attempt` | Just before the request | The call id |
| `effect.outcome` | After the response, or the failure | Status code or error type, whether the credential was refreshed |

Never query strings, bodies or credentials.

Every event carries the hash of the one before it and its own hash (SHA-256 over
its canonical JSON: sorted keys, no whitespace). A separate head log, also
hash-linked, registers each run's latest event as it is written.

### Checking it

```bash
jarviscore verify                    # this deployment's journal
jarviscore verify /path/to/a/copy    # a copy handed to an auditor; no keys, no network
jarviscore verify --json
```

| Detected | How |
|---|---|
| An edited event | Its content no longer matches its hash |
| A removed or reordered event | The chain or the sequence breaks |
| A run cut short | The head log registered a later event |
| A removed run | The head log registered it |
| A provider call with no decision before it, or one policy refused | Each `effect.attempt` is checked against its `policy.decision` |

**Not yet detected:** a rewrite of the whole journal, head log included, by
whoever controls the directory. That needs the head log anchored outside the
deployment (signed checkpoints, independent witnesses), which is the next step for
the journal.

---

## Approvals

Consequential actions wait for a person ([Human-in-the-Loop](../guides/hitl.md#approving-an-agents-consequential-actions)).
What holds for them:

| Property | How |
|---|---|
| An approval covers the exact action the person saw | Bound to every argument (or the element and values a browser action touches); other arguments ask again |
| The institution decides which actions need a person, and who may approve | `approvals:` rules: roles, not the requester, least assurance; waivers never for destructive actions |
| The approver is who they say | Approval assertions signed by your backend over the exact action (`verified`) |
| Policy is checked when the action runs, not only when it was approved | A tightened policy sends the action back to a person |
| At most once | The first decision stands; starting the action is claimed atomically; an interrupted run leaves `OUTCOME_UNKNOWN` for a person to reconcile |
| A gated call cannot reach a provider without its approval | The broker refuses `approval-missing`; `jarviscore verify` checks every call carrying an approval against an approval of that exact action |
| Retries do not repeat a payment | Providers that deduplicate by key get the operation's id (Stripe, Adyen, Mollie, GoCardless, Checkout.com, PayPal headers; Square's `idempotency_key`) |

The journal records `approval.request`, `approval.decision` (approver, roles,
assurance, how they were authenticated), `approval.refused`, `approval.claim`,
`approval.settle`, `approval.reopened` and `approval.reconciled`.

---

## Acting for a person

An agent working for someone uses that person's own access, within what they
handed over, and every record names them.

| Property | How |
|---|---|
| Their credential, nobody else's | JarvisCore names the person on every credential request (`X-Nexus-Subject`, with the agent and operation); Nexus releases a credential only for the person whose connection it is. With Nexus `SUBJECT_BINDING=required`, a connection id alone releases nothing. A credential Nexus refuses is not replaced by any other, and one cached for one person is never served to another |
| Never more than they could do | It is their credential, so the provider holds the agent to that person's own permissions |
| Within what they delegated | A **mandate** registered with the work narrows it further: the systems, effects and time the person handed over. A call outside it is refused (`outside-mandate`); no deployment rule widens it |
| On record | Every decision in the journal names the person (`acting_for`) and the mandate's digest; Nexus's audit names the subject, agent and operation of every credential it releases or refuses |

```python
await mesh.execute_goal(
    "Pay supplier invoice INV-7",
    context={
        "acting_for": "ada@example.com",
        "mandate": {"systems": ["erp"], "effects": ["read", "write"],
                    "expires_at": "2026-11-01T00:00:00Z"},
    },
)
```

`acting_for` and `mandate` come only from the context your application registers
the goal with, never from what agents write, and hold for every step and peer of
that workflow. A mandate that cannot be read refuses every call.

What this does not do: Nexus binds a credential to the subject your runtime
names; it does not authenticate the person itself. Keep the gateway key with the
runtime, and authenticate people where they ask for work.

---

## Every other effect

What an agent does outside its step that is not a provider call goes through one
decision point at the place it happens, recorded the same way (`policy.decision`,
`effect.attempt`, `effect.outcome`; sizes and digests, never content), so
`jarviscore verify` holds each to "decided before it happened".

| Sink | Where | Records |
|---|---|---|
| `code` | Each program run in the sandbox: model-written code, registry and shipped integrations, browser cells | Origin, digest, whether the child was confined |
| `process` | A command on the host, outside the sandbox's child | The programs, digest |
| `artifact` | A file the sandbox publishes to blob storage | Key, size, digest |
| `workspace` | A step's changes exported for the next step or for review; a file an agent writes on the host | Counts, digest; path |
| `memory` | A fact kept for later sessions | Kind, private or shared, digest |
| `peer` | A message to another agent: `send`, `delegate` from sandboxed code, and the engine's `broadcast` of every step result to all peers | Recipient, digest |
| `output` | A step's result delivered to the steps and caller after it | Status, digest |
| `browser` | A page's top-level navigation, and every request carrying data out of the browser (a form, `fetch`, XHR, a beacon) | Method, host, the page's host, digest of the body |

Commands a confined child runs inside its own workspace are its scratch work: they
cannot reach the network or write outside the workspace, and what they produce
leaves only through the sinks above.

**Strict mode needs a confined sandbox.** Model-written code, registry
integrations and host commands the model chose are refused (`unconfined-execution`)
when they would run outside a confined child, since there they reach the network
and the host past every broker. Integrations shipped with JarvisCore still run.
Where confinement is not available (macOS `sandbox-exec`, Linux bubblewrap), a
deployment that accepts the risk says so with a rule, which is then on record with
every run it allows.

```yaml
effects:
  - name: no-broadcast-of-results     # keep step results off the P2P network
    decision: deny
    match: {sink: peer, action: broadcast}
  - name: no-exports
    decision: deny
    match: {sink: artifact, target: "*/exports/*"}
  - name: ci-runner-without-bubblewrap
    decision: allow                   # lifts only unconfined-execution
    match: {sink: code}
```

**The browser sends only to the site it is on.** In strict mode a page's request
that carries data (any method but GET, HEAD and OPTIONS) to a host other than the
page's own is refused before it leaves (`browser-send-off-site`): a script an
attacker planted, an instruction that made the agent `fetch` somewhere, a
third-party beacon. Allow the hosts your sites really send to, as `target`
globs over host and path:

```yaml
effects:
  - name: our-app-api
    decision: allow
    match: {sink: browser, target: "api.example.com/*"}
```

Requests are intercepted in strict mode (Playwright then disables the browser's
HTTP cache) and only observed in report mode, at no cost. Plain reads (images,
scripts, GET data) are neither decided on nor recorded. Strict mode blocks
service workers in contexts JarvisCore creates. Not covered: WebSocket and
WebRTC traffic, and data a GET request carries in its address.

Match keys: `sink`, `action`, `origin`, `agent`, `target` (a glob) and
`confined`. A rule that cannot be read refuses every effect. A test enumerates
every raw call in the package that runs a process, stores a blob, keeps a memory,
messages peers or writes a file from an agent tool, and fails the build if one is
neither decided on nor classified as the runtime's own.

---

## Grounding

An approval asks a person. Grounding asks the system of record. For an operation
such as a payment, the deployment names which fields of the request leaving for
the provider must come from records the broker itself read earlier in the same
workflow. The model chooses the call; it cannot choose those values. An IBAN
planted in an invoice's notes, a "we changed banks" email in the task, or a person
who approves without reading: the payment still goes only to the account on the
supplier record.

```yaml
grounding:
  - name: supplier-payment
    match: {provider: erp, method: POST, path: /payments}
    bind:                                   # follow records, in order
      - name: invoice
        read: {provider: erp, path: "/invoices/{id}"}
        where: {id: request.json.invoice}   # which invoice this call pays
      - name: supplier
        read: {provider: erp, path: "/suppliers/{id}"}
        where: {id: invoice.supplier_id}    # that invoice's supplier, not any supplier
    require:
      - {field: request.json.iban, equals: supplier.iban, as: iban}
      - {field: request.json.amount, at_most: invoice.amount_due, as: money}
    other_fields: deny                      # nothing else rides along
```

| Property | How |
|---|---|
| Sources are what the broker received | Only provider responses the broker recorded count; code cannot hand it a record |
| Relationships, not membership | A binding selects one record, and the next follows it; a value seen elsewhere in the run proves nothing |
| What leaves is what is checked | The body httpx will send (`content` over `data` over `json`); a body grounding cannot read is refused |
| Typed comparison | `iban` (ISO 13616, check digits), `money` and `number` (decimal), `email` (IDNA domain), `text` (exact after NFC, never case- or lookalike-folded), `id`, `exact` |
| Ambiguity is refused | Two records answering one selector, a field sent twice, a field missing |
| What the run changed is not a source | A record read after this workflow wrote to it grounds nothing |
| Which record can be pinned | `selectors_from: [input]` takes selectors only from the caller's structured input (`execute_goal(context=...)`), never from the request |
| Fresh at the moment of acting | `fresh: reread` reads each record again just before the call; `max_age_seconds` bounds how old a read may be |
| Every grounded call cites its reads | The decision records each record it relied on (the journal event of that response and its digest); `jarviscore verify` checks every citation |

**Before a person is asked.** When a grounding rule could apply, the action is
previewed first: the integration's own code runs with every change held at the
broker after its decision, before anything leaves (reads run as usual). If strict
policy would refuse it, nobody is asked and the agent gets `POLICY_WOULD_REFUSE`
with the reasons. Otherwise the approval request carries what was checked
(`payload.checks`: each change, its decision, and the records it was grounded on),
so the person sees, for example, that the IBAN is the one on the supplier record.
Each previewed change is journaled as `policy.preview`, and `jarviscore verify`
counts those refused before approval. The check at the moment of sending still
decides.

Relations: `equals`, `one_of` (a list, or a path with `[*]`) and `at_most`
(`money` or `number`). A refusal names every requirement that failed. A rule that
cannot be read refuses the calls it matches; one whose `match` cannot be read
refuses every call. Values are recorded as digests, never in clear.

What grounding does not do: make a system of record correct. A supplier record an
attacker already changed is still the record. Unless selectors come from the
caller's input, the model still chooses which invoice, within what the records
allow. Records are kept per process, so a workflow whose read and payment run in
different processes is refused (fail closed).

---

## Performance

Deciding and recording adds about 0.1 ms to a provider call. Grounding costs
nothing when no rule applies: responses are kept only when they can ground a rule.
Where one does, the preview before an approval runs the integration once more in
the sandbox with its changes held (about 0.5 s measured), once per action. Provider calls now
reuse their connection (`NEXUS_KEEPALIVE_SECONDS`, default 120): on a measured
HTTPS endpoint a call went from about 500 ms with a fresh connection to about
90 ms on a kept one.

---

## Not covered yet

WebSocket and WebRTC traffic from a page, and data carried in a GET request's
address, are not decided on. Signed, witnessed checkpoints come next, each with
its own claim and tests.
