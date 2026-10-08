# RFC 0002: Elastic execution: worker pools, a provider governor, tiered models

- Status: Draft
- Target: JarvisCore 2.2
- Builds on: 2.1.0 (`da04a9d`)

## 1. Problem

A mesh runs the agents it was given at startup, and nothing more. Large workloads
queue behind them. Every LLM call goes to one deployment, and the only protection
against provider limits is backing off after a 429.

Measured on a real workload: the Evidence Engine verified 196 claims of one M&A
matter with JarvisCore 2.1.0.

| Measure | Value |
|---|---|
| Verifier agents | 4 (fixed at startup) |
| Wall clock | 201 min (about 30 min of it machine sleep) |
| Summed agent time | 604 min |
| Effective parallelism | 3.0 |
| Median time per claim | 147 s |
| LLM calls per claim | 8.5 mean, all sequential |
| Model | one strong deployment for every call |
| Output reservation | `LLM_DEFAULT_MAX_TOKENS=32000` on every call |

Each claim is independent, so the work is embarrassingly parallel. Latency per
claim comes from sequential calls to a strong model that is used even for tool
selection.

The 32,000-token output ceiling matters for capacity. Azure counts the requested
`max_tokens` against the tokens-per-minute (TPM) limit when the request is admitted.
At that ceiling, a 1M TPM deployment admits only about 30 calls per minute,
whatever they actually produce.

## 2. What 2.1.0 already has

The new pieces are built on these, not beside them.

- **Durable leased work.** `RedisContextStore.claim_step` leases a step atomically to
  one execution identity. Leases expire and are recovered, and committing requires
  holding the lease. Exactly-once execution and resume after a crash depend on this.
- **Capability matching.** `Mesh._run_agent_loop` and the distributed worker loop
  poll every 2 s, scan for ready steps whose capability matches, claim one, and run
  it inline. One agent instance runs one step at a time.
- **Workflow token budgets.** `reserve_workflow_tokens` and `settle_*` in
  `redis_store.py`, used by `orchestration/budget.py`, reserve and settle tokens per
  workflow with WATCH/MULTI. That caps cost; it does not pace calls.
- **Process-wide LLM semaphore.** `LLM_MAX_CONCURRENT` is off by default and only
  counts calls in flight in one process.
- **429 backoff.** Up to `LLM_MAX_RETRIES_429` retries with jittered exponential
  delay. The provider's retry hint is parsed from the error text and capped at
  300 s, after which the call fails fast.
- **Model tiers.** `task_model_nano`, `task_model_standard` and `task_model_heavy`
  are chosen per step by a `complexity` hint (`kernel.py`). Nothing chooses a tier
  per turn inside a step, and nothing is configured by default.

## 3. Goals

- **G1 Elastic throughput.** Agents for a capability scale with the ready backlog
  between a declared minimum and maximum, and drain when it empties.
- **G2 No 429 in normal operation.** Calls are paced against each deployment's
  requests-per-minute (RPM) and TPM limits before they are sent. A 429 is an
  anomaly that gets counted and alerted on, not routine flow control.
- **G3 Cheap where it is safe.** The research loop runs on a fast model. The work
  product that gets judged is written by the strong model.
- **G4 Unchanged guarantees.** Leasing, exactly-once commits, resume, budgets and
  traces behave exactly as in 2.1.0.

Non-goals: scaling Kubernetes or containers (pools scale inside the processes that
already run), cross-tenant fair share (an enterprise concern, see §9), and changing
the planner.

## 4. Design A: elastic worker pools

### 4.1 Declaration

```python
mesh.add(EvidenceVerifier, pool=Pool(min=1, max=32, idle_seconds=60))
```

`pool=None` keeps today's behaviour: one long-lived instance. Peers that hold
identity, such as named peers with mailboxes, credentials or conversations, stay
singletons. A pool is for stateless capability workers.

### 4.2 Backlog index

Workers find work today by scanning every workflow on each poll. That costs
O(workflows) per poll and cannot report demand. The proposal is to keep a sorted
set per capability, `ready:{capability}` (score = enqueue time), maintained in the
same transactions that move a step into or out of `pending` with its dependencies
met:

- **Workers** take candidates from it in order. `claim_step` stays the only
  authority, so a stale index entry costs one failed claim and nothing more.
- **The scaler** reads `ZCARD` to see demand.

### 4.3 Scaler

Each process runs one scaler coroutine per pool, once a second:

```
desired = clamp(ceil(backlog / per_worker), min, max)
desired = min(desired, governor.headroom_workers(pool.model_tier))
```

- **Scale up:** start `desired - live` workers with ids
  `{agent_id}-w{n}`. They are new instances of the same class sharing the process's
  LLM client, tools and stores.
- **Scale down:** a worker idle for `idle_seconds` and holding no lease stops after
  finishing its current turn. A worker holding a lease is never cancelled.
- **Across processes:** members register in `pool_members:{capability}` with a
  heartbeat TTL. The global `max` is enforced there, so two API replicas don't
  each start 32.
- **Governor bound:** the cap from the governor stops the scaler from starting
  workers that would only queue for tokens.

### 4.4 Resume affinity

A step that resumes is pinned today by `resume_agent_id`, and an ephemeral worker
id will not exist after a restart. Pooled steps are pinned to the pool's id. Any
member may resume from the durable checkpoint, which already carries the kernel
state. This is the one change to existing semantics, and it is covered by a
kill -9 test (§8).

### 4.5 Claim latency

Polling every 2 s adds a mean 1 s per step. A worker blocks on a short
`BZPOPMIN`-style wake signal for its capability, keeping the 2 s poll as a fallback.

## 5. Design B: provider governor

### 5.1 Scope and limits

A governor owns one deployment key: `(provider, endpoint, deployment)`. Its limits
come from configuration:

```
LLM_LIMITS='{"azure:gpt-5.2-chat":{"rpm":3000,"tpm":1000000}}'
```

They are refined at runtime from rate-limit headers where the provider returns them
(Azure: `x-ratelimit-remaining-requests`, `x-ratelimit-remaining-tokens`).

### 5.2 Admission

Every call reserves capacity before it is dispatched:

```
cost = estimate(prompt_tokens) + max_tokens     # what the provider charges at admission
reserve(key, requests=1, tokens=cost, lane) -> admitted | wait(seconds)
... call ...
settle(key, reservation, actual_total_tokens)   # returns the unused estimate
```

- **One atomic step.** Reserve and settle are one Lua script each over a 60 s
  sliding window in Redis (two ZSETs of timestamped reservations), so every process
  and agent shares one view of the deployment.
- **Waiting is cancellable.** A waiting caller sleeps for the returned wait, never
  past its step lease, and the wait is visible in traces as `llm_wait`.
- **Right-sized outputs.** `max_tokens` becomes a per-call decision, a turn ceiling
  rather than a global default, so 32,000-token reservations stop eating TPM. The
  kernel passes its turn budget. The default drops to the model's typical turn size.

### 5.3 Adaptive concurrency

The window enforces the rate. Additive-increase/multiplicative-decrease (AIMD)
control sets how many calls run at once:

- Raise the in-flight limit by 1 per healthy window while utilisation is below
  85 %.
- Halve it on a 429, or when p95 latency more than doubles.
- The limit then tracks what the deployment actually sustains, including shared
  quota spent by other tenants of the same deployment.

### 5.4 Priority lanes

Lanes are `interactive` (chat turns), `decision` (final work products, verdicts)
and `bulk` (research loops). Bulk is admitted only while headroom stays above a
reserve, by default 15 % of TPM. A user's chat question during a 196-claim run is
therefore not queued behind it.

### 5.5 Failure behaviour

- **429 path stays as a backstop.** It honours the `Retry-After` header, not only
  hints parsed from text, and every occurrence is a metric.
- **Redis unavailable:** fall back to an in-process window at
  `limit / expected_processes`, and log the degraded mode.
- **Separate from cost budgets.** Workflow token budgets are unchanged: the
  governor paces, budgets cap. A call needs both.

## 6. Design C: tiered models inside a step

A role profile declares tiers by turn kind:

```python
models = {"loop": "nano", "final": "heavy", "escalate_after_rejections": 1}
```

- **Loop turns** use the fast tier: choosing tools, issuing searches, reading,
  extracting quotes.
- **The final turn** uses the strong tier: the turn that emits `DONE/RESULT` for a
  work-product contract.
- **Escalation:** when a gate rejects a fast-tier result, the next turn escalates.
  A cheap model that cannot satisfy the gate gets one more chance on the strong
  model; it is never looped.
- **Decisions** that already go to Jev or another decision provider are unchanged.

Quality is a measured property, not an assumption. A tiered profile ships only
after passing the agreement test in §8 against a strong-only baseline on the same
workload.

## 7. Configuration and observability

| Setting | Default | Meaning |
|---|---|---|
| `pool=Pool(min,max,idle_seconds,per_worker)` | none (singleton) | elastic pool per capability |
| `LLM_LIMITS` | unset (governor learns from headers) | RPM/TPM per deployment |
| `LLM_TARGET_UTILISATION` | 0.85 | AIMD ceiling |
| `LLM_BULK_RESERVE` | 0.15 | TPM held back from the bulk lane |
| `models=` in role profiles | strong-only | tier per turn kind |

The mesh status endpoint and traces report:
- per pool: live workers, backlog, claim latency;
- per deployment: utilisation, in-flight limit, wait p50/p95, 429 count;
- per call: tier and lane.

## 8. Acceptance

Measured on the matter in §1 (196 claims) against the 2.1.0 baseline:

| Criterion | Target |
|---|---|
| Wall clock, machine awake | ≤ 15 min |
| 429s reaching an agent | 0; provider 429s ≤ 1 % of calls |
| Verdict agreement with strong-only baseline | ≥ 95 % (disagreements listed) |
| Cost per claim | ≤ ⅓ of baseline |
| Durability | kill -9 a process mid-run: no step lost, none committed twice |
| Interactive latency during the run | chat p95 within 1.5× idle |

Unit tests cover:
- the Lua window under concurrent reservations;
- AIMD convergence against a simulated provider;
- scaler bounds with two simulated processes;
- resume by pool id.

## 9. Core and enterprise

All of this is core. Elastic execution and safe pacing are table stakes for a
framework that claims durable multi-agent work. Enterprise adds, on the same
primitives:
- per-tenant quotas and fair share on shared deployments;
- spend forecasts and admission control by contract;
- multi-region failover across deployments.

## 10. Delivery

Each PR stands alone and is useful by itself.

1. **Governor.** Reserve/settle Lua scripts, per-call `max_tokens`, `Retry-After`,
   AIMD, lanes, metrics. Zero behaviour change when `LLM_LIMITS` is unset, apart
   from honouring headers.
2. **Backlog index and pools.** `ready:{capability}`, the scaler, pool membership,
   resume by pool id, wake signals.
3. **Tiered turns.** `models=` profile field, turn-kind routing, escalation on gate
   rejection.
4. **Adoption.** The Evidence Engine declares a verifier pool and a tiered profile,
   and the §8 benchmark runs and is published.

## 11. Open questions

1. The RPM/TPM limits and the available fast-tier deployment on our Azure resource
   (for example a mini or nano model) decide both the real ceiling and the cost
   ratio. They need confirming before the §8 targets are final.
2. Should pools also scale across processes on demand (spawning a worker
   process)? Proposed: no for 2.2; in-process pools plus more replicas cover it.
3. Fast-tier failure modes on long matter passages (quote fidelity) may need the
   quote-copying turns on the standard tier. The §8 agreement test will show it.
