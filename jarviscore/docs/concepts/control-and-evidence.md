---
icon: material/scale-balance
title: "Control and Evidence: Decided Before It Leaves, Recorded So It Can Be Checked"
description: "How JarvisCore decides on every provider call before any network I/O, refuses what policy does not allow in strict mode, and records each decision in a hash-linked journal anyone can verify offline."
---

# Control and Evidence

The model proposes. The runtime decides what runs, and keeps a record anyone can
check. This page covers the first part of that built so far: **calls to connected
providers** (GitHub, Slack, ERPs and the rest of the catalogue).

| What | Where |
|---|---|
| Every provider call is decided on before anything leaves | `NexusCallProxy` |
| What an integration's code can send, read from that code | `jarviscore.control.operations` |
| The decision rules | `jarviscore.control.policy` |
| The record of decisions and calls | `jarviscore.evidence.journal` |
| Checking the record | `jarviscore verify` |

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

Start in `report`, read what strict mode would have refused (`jarviscore verify --json`
lists the counts; the journal names each call and rule), then switch to `strict`.

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

## Performance

Deciding and recording adds about 0.1 ms to a provider call. Provider calls now
reuse their connection (`NEXUS_KEEPALIVE_SECONDS`, default 120): on a measured
HTTPS endpoint a call went from about 500 ms with a fresh connection to about
90 ms on a kept one.

---

## Not covered yet

Effects that do not go through a provider call are not decided on here yet:
workspace files and processes, the browser, memory, and messages between agents.
Approvals bound to the exact operation, typed limits on arguments, and signed,
witnessed checkpoints come next, each with its own claim and tests.
